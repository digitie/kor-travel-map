#!/usr/bin/env bash

# C7 executor image를 working tree가 아닌 exact Git commit archive로만 만든다.
set +x
set -euo pipefail
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly IMAGE_TAG="kor-travel-map-c7-playwright:local"
readonly PLAYWRIGHT_BASE_IMAGE="mcr.microsoft.com/playwright:v1.60.0-noble@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948"

die() {
  printf 'C7 executor build failed: %s (values redacted)\n' "$1" >&2
  exit 1
}

for command in docker git mktemp python3 tar; do
  command -v -- "$command" >/dev/null 2>&1 || die "required command is missing: $command"
done

actual_root="$(git -C "$REPO_ROOT" rev-parse --show-toplevel 2>/dev/null)" ||
  die "repository root lookup failed"
actual_root="$(cd -- "$actual_root" && pwd -P)" || die "repository root canonicalization failed"
[[ "$actual_root" == "$REPO_ROOT" ]] || die "repository root mismatch"
commit="$(git -C "$REPO_ROOT" rev-parse --verify 'HEAD^{commit}' 2>/dev/null)" ||
  die "repository commit lookup failed"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || die "repository commit is invalid"
git -C "$REPO_ROOT" diff --quiet --ignore-submodules -- || die "working tree is dirty"
git -C "$REPO_ROOT" diff --cached --quiet --ignore-submodules -- || die "index is dirty"
[[ -z "$(git -C "$REPO_ROOT" ls-files --others --exclude-standard)" ]] ||
  die "working tree has untracked inputs"

context="$(mktemp -d)" || die "temporary build context creation failed"
cleanup() {
  rm -rf -- "$context"
}
trap cleanup EXIT INT TERM
chmod 700 -- "$context"

# git archive가 ignored/untracked/editor/cache bytes를 build context에서 구조적으로 제외한다.
git -C "$REPO_ROOT" archive --format=tar "$commit" |
  tar -xf - -C "$context" || die "exact commit archive extraction failed"

image_id="$(
  docker build \
    --pull=false \
    --quiet \
    --build-arg "C7_REPOSITORY_COMMIT=$commit" \
    -f "$context/docker/c7-playwright.Dockerfile" \
    -t "$IMAGE_TAG" \
    "$context"
)" || die "executor image build failed"
[[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "executor image ID is invalid"

python3 - "$image_id" "$commit" "$PLAYWRIGHT_BASE_IMAGE" <<'PY'
import json
import subprocess
import sys

image_id, commit, base = sys.argv[1:]
completed = subprocess.run(
    ["docker", "image", "inspect", "--", image_id],
    check=True,
    capture_output=True,
    text=True,
    timeout=30,
)
records = json.loads(completed.stdout)
if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
    raise SystemExit(1)
labels = records[0].get("Config", {}).get("Labels", {})
if (
    records[0].get("Id") != image_id
    or not isinstance(labels, dict)
    or labels.get("io.kortravelmap.c7.repository-commit") != commit
    or labels.get("io.kortravelmap.c7.playwright-base") != base
):
    raise SystemExit(1)
PY

printf '%s\n' "$image_id"

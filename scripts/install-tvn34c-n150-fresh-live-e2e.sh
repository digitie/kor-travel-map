#!/usr/bin/env bash
# T-VN-34C fresh live gate를 n150의 root-owned immutable snapshot으로 설치한다.
# 설치하는 Map/PinVi 소스와 receipt는 모두 지정 Git commit에서 archive로 만든다.
set -Eeuo pipefail
umask 077

readonly MAP_REPOSITORY="$(cd -- "$(dirname -- "$0")/.." && pwd -P)"
readonly RECEIPT_PATH="contracts/vnext/consumer-rollout-v1.json"
readonly DEFAULT_INSTALL_ROOT="/var/lib/kor-travel-map/tvn34c-fresh-live"

die() {
  printf 'T-VN-34C fresh-live installer failed: %s\n' "$1" >&2
  exit 1
}

usage() {
  printf 'usage: %s <n150-host> <pinvi-repository> [map-runner-ref]\n' "$(basename "$0")" >&2
  exit 2
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is unavailable: $1"
}

[[ "$#" -ge 2 && "$#" -le 3 ]] || usage
readonly N150_HOST="$1"
readonly PINVI_REPOSITORY="$(cd -- "$2" && pwd -P)"
readonly RUNNER_REF="${3:-HEAD}"

for command in git python3 sha256sum ssh tar; do
  require_command "$command"
done
[[ -d "$PINVI_REPOSITORY/.git" || -f "$PINVI_REPOSITORY/.git" ]] || die "PinVi repository is not a Git worktree"

readonly RUNNER_COMMIT="$(git -C "$MAP_REPOSITORY" rev-parse --verify "$RUNNER_REF^{commit}")"
mapfile -t receipt_values < <(
  git -C "$MAP_REPOSITORY" show "$RUNNER_COMMIT:$RECEIPT_PATH" |
    python3 -c '
import json
import re
import sys

receipt = json.load(sys.stdin)["tasks"]["T-VN-34"]["pinvi_snapshot_receipt"]
keys = (
    "map_commit",
    "pinvi_commit",
    "map_user_openapi_sha256",
    "map_full_openapi_sha256",
    "pinvi_user_vendor_sha256",
    "pinvi_admin_detail_vendor_sha256",
)
for key in keys:
    value = receipt.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise SystemExit(1)
    print(value)
'
)
[[ "${#receipt_values[@]}" == 6 ]] || die "T-VN-34C consumer receipt is incomplete"
readonly MAP_COMMIT="${receipt_values[0]}"
readonly PINVI_COMMIT="${receipt_values[1]}"
readonly MAP_USER_OPENAPI_SHA256="${receipt_values[2]}"
readonly MAP_FULL_OPENAPI_SHA256="${receipt_values[3]}"
readonly PINVI_USER_VENDOR_SHA256="${receipt_values[4]}"
readonly PINVI_ADMIN_VENDOR_SHA256="${receipt_values[5]}"

git -C "$MAP_REPOSITORY" cat-file -e "$MAP_COMMIT^{commit}" || die "receipt Map commit is unavailable locally"
git -C "$PINVI_REPOSITORY" cat-file -e "$PINVI_COMMIT^{commit}" || die "receipt PinVi commit is unavailable locally"

hash_git_path() {
  local repository="$1"
  local commit="$2"
  local path="$3"
  git -C "$repository" show "$commit:$path" | sha256sum | awk '{print $1}'
}

[[ "$(hash_git_path "$MAP_REPOSITORY" "$MAP_COMMIT" packages/kor-travel-map-api/openapi.user.json)" == "$MAP_USER_OPENAPI_SHA256" ]] ||
  die "receipt Map user OpenAPI hash mismatch"
[[ "$(hash_git_path "$MAP_REPOSITORY" "$MAP_COMMIT" packages/kor-travel-map-api/openapi.json)" == "$MAP_FULL_OPENAPI_SHA256" ]] ||
  die "receipt Map full OpenAPI hash mismatch"
[[ "$(hash_git_path "$PINVI_REPOSITORY" "$PINVI_COMMIT" apps/api/tests/contract/kor-travel-map-openapi-user.json)" == "$PINVI_USER_VENDOR_SHA256" ]] ||
  die "receipt PinVi user vendor hash mismatch"
[[ "$(hash_git_path "$PINVI_REPOSITORY" "$PINVI_COMMIT" apps/api/tests/contract/kor-travel-map-openapi-admin-detail-snapshot.json)" == "$PINVI_ADMIN_VENDOR_SHA256" ]] ||
  die "receipt PinVi admin vendor hash mismatch"

local_stage="$(mktemp -d "${TMPDIR:-/tmp}/tvn34c-fresh-live.XXXXXX")"
remote_stage=""
cleanup() {
  rm -rf -- "$local_stage"
  if [[ -n "$remote_stage" ]]; then
    ssh "$N150_HOST" "rm -rf -- '$remote_stage'" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

git -C "$MAP_REPOSITORY" archive --format=tar.gz --prefix=map/ "$MAP_COMMIT" >"$local_stage/map-source.tar.gz"
git -C "$PINVI_REPOSITORY" archive --format=tar.gz --prefix=pinvi/ "$PINVI_COMMIT" >"$local_stage/pinvi-source.tar.gz"
git -C "$MAP_REPOSITORY" archive --format=tar "$RUNNER_COMMIT" \
  scripts/run-tvn34c-n150-fresh-live-e2e.sh \
  scripts/tvn34c_fresh_live_etl_seed.py \
  "$RECEIPT_PATH" | tar --extract --file - --directory "$local_stage"
mv "$local_stage/$RECEIPT_PATH" "$local_stage/consumer-rollout-v1.json"

readonly MAP_ARCHIVE_SHA256="$(sha256sum "$local_stage/map-source.tar.gz" | awk '{print $1}')"
readonly PINVI_ARCHIVE_SHA256="$(sha256sum "$local_stage/pinvi-source.tar.gz" | awk '{print $1}')"
readonly RUNNER_SHA256="$(sha256sum "$local_stage/scripts/run-tvn34c-n150-fresh-live-e2e.sh" | awk '{print $1}')"
readonly HELPER_SHA256="$(sha256sum "$local_stage/scripts/tvn34c_fresh_live_etl_seed.py" | awk '{print $1}')"
readonly RECEIPT_SHA256="$(sha256sum "$local_stage/consumer-rollout-v1.json" | awk '{print $1}')"

printf '{"map":{"archive_sha256":"%s","commit":"%s"},"pinvi":{"archive_sha256":"%s","commit":"%s"},"receipt_sha256":"%s","runner_sha256":"%s","seed_helper_sha256":"%s","version":3}\n' \
  "$MAP_ARCHIVE_SHA256" "$MAP_COMMIT" "$PINVI_ARCHIVE_SHA256" "$PINVI_COMMIT" \
  "$RECEIPT_SHA256" "$RUNNER_SHA256" "$HELPER_SHA256" >"$local_stage/manifest.json"

readonly snapshot_name="${MAP_COMMIT}-${PINVI_COMMIT}"
readonly install_directory="$DEFAULT_INSTALL_ROOT/$snapshot_name"
remote_stage="$(ssh "$N150_HOST" 'umask 077; mktemp -d /tmp/tvn34c-fresh-live.XXXXXX')" || die "cannot allocate n150 staging directory"
[[ "$remote_stage" =~ ^/tmp/tvn34c-fresh-live\.[A-Za-z0-9]+$ ]] || die "n150 staging directory is unsafe"
tar --create --gzip --file - --directory "$local_stage" \
  map-source.tar.gz pinvi-source.tar.gz consumer-rollout-v1.json manifest.json scripts | \
  ssh "$N150_HOST" "umask 077; tar --extract --gzip --file - --directory '$remote_stage'"

ssh "$N150_HOST" "sudo /bin/bash -s -- '$install_directory' '$remote_stage' '$MAP_ARCHIVE_SHA256' '$PINVI_ARCHIVE_SHA256' '$RECEIPT_SHA256' '$RUNNER_SHA256' '$HELPER_SHA256'" <<'REMOTE'
set -Eeuo pipefail
install_directory="$1"
stage="$2"
map_hash="$3"
pinvi_hash="$4"
receipt_hash="$5"
runner_hash="$6"
helper_hash="$7"
root="/var/lib/kor-travel-map/tvn34c-fresh-live"
[[ "$install_directory" == "$root"/* ]] || exit 1
[[ -d "$stage" && ! -L "$stage" ]] || exit 1
[[ ! -e "$install_directory" ]] || exit 1
parent="$(dirname "$install_directory")"
install -d -o root -g root -m 0700 "$root"
temporary="$parent/.install-$(basename "$install_directory").$$"
trap 'rm -rf -- "$temporary"' EXIT
install -d -o root -g root -m 0700 "$temporary/scripts"
install -o root -g root -m 0600 "$stage/map-source.tar.gz" "$temporary/map-source.tar.gz"
install -o root -g root -m 0600 "$stage/pinvi-source.tar.gz" "$temporary/pinvi-source.tar.gz"
install -o root -g root -m 0600 "$stage/consumer-rollout-v1.json" "$temporary/consumer-rollout-v1.json"
install -o root -g root -m 0600 "$stage/manifest.json" "$temporary/manifest.json"
install -o root -g root -m 0500 "$stage/scripts/run-tvn34c-n150-fresh-live-e2e.sh" "$temporary/run-tvn34c-n150-fresh-live-e2e.sh"
install -o root -g root -m 0500 "$stage/scripts/tvn34c_fresh_live_etl_seed.py" "$temporary/scripts/tvn34c_fresh_live_etl_seed.py"
[[ "$(sha256sum "$temporary/map-source.tar.gz" | awk '{print $1}')" == "$map_hash" ]]
[[ "$(sha256sum "$temporary/pinvi-source.tar.gz" | awk '{print $1}')" == "$pinvi_hash" ]]
[[ "$(sha256sum "$temporary/consumer-rollout-v1.json" | awk '{print $1}')" == "$receipt_hash" ]]
[[ "$(sha256sum "$temporary/run-tvn34c-n150-fresh-live-e2e.sh" | awk '{print $1}')" == "$runner_hash" ]]
[[ "$(sha256sum "$temporary/scripts/tvn34c_fresh_live_etl_seed.py" | awk '{print $1}')" == "$helper_hash" ]]
mv -T "$temporary" "$install_directory"
trap - EXIT
REMOTE

remote_stage=""
printf 'Installed immutable T-VN-34C snapshot. Run on n150: sudo %s/run-tvn34c-n150-fresh-live-e2e.sh run\n' "$install_directory"

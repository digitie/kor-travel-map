#!/usr/bin/env bash

# #741/#785 전용 production live lane. strict C7 state와 섞지 않는다.
set +x
set -euo pipefail
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly FIXTURE_HELPER="$SCRIPT_DIR/admin_feature_live_fixture.py"
readonly STATE_ROOT="/var/lib/kor-travel-map/admin-feature-live-acceptance"
readonly BLOCKED_FILE="$STATE_ROOT/BLOCKED.json"
readonly LOCK_FILE="$STATE_ROOT/orchestrator.lock"
readonly MODE="${1-run}"
RUN_ID=""
RUNTIME_DIR=""
ACTIVE_CONTAINER=""

die() {
  printf 'admin feature live acceptance failed: %s (values redacted)\n' "$1" >&2
  exit 1
}

require_command() {
  command -v -- "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

require_env() {
  local name="$1"
  [[ -n "${!name-}" ]] || die "required env is missing: $name"
}

safe_root_file() {
  local path="$1"
  [[
    -f "$path" &&
    ! -L "$path" &&
    "$(stat -c '%u:%g:%a' -- "$path")" == "0:0:555"
  ]] || die "runner source is not a root-owned immutable file"
}

atomic_json() {
  local destination="$1"
  local phase="$2"
  local status="$3"
  python3 - "$destination" "$RUN_ID" "$phase" "$status" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

destination = Path(sys.argv[1])
payload = {
    "phase": sys.argv[3],
    "recorded_at": datetime.now(timezone.utc).isoformat(),
    "run_id": sys.argv[2],
    "status": sys.argv[4],
    "version": 1,
}
temporary = destination.parent / f".{destination.name}.{os.getpid()}.tmp"
descriptor = os.open(
    temporary,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
    0o600,
)
try:
    os.fchown(descriptor, 0, 0)
    body = (json.dumps(payload, sort_keys=True) + "\n").encode()
    os.write(descriptor, body)
    os.fsync(descriptor)
finally:
    os.close(descriptor)
os.replace(temporary, destination)
os.chown(destination, 0, 0)
os.chmod(destination, 0o600)
directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY
}

read_blocked_run_id() {
  python3 - "$BLOCKED_FILE" <<'PY'
import json
import os
import re
import stat
import sys

descriptor = os.open(sys.argv[1], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
try:
    observed = os.fstat(descriptor)
    payload = json.loads(os.read(descriptor, 16384))
finally:
    os.close(descriptor)
if (
    not stat.S_ISREG(observed.st_mode)
    or observed.st_uid != 0
    or observed.st_gid != 0
    or stat.S_IMODE(observed.st_mode) != 0o600
    or not isinstance(payload, dict)
    or payload.get("version") != 1
    or not isinstance(payload.get("run_id"), str)
    or re.fullmatch(r"[a-z0-9][a-z0-9-]{15,79}", payload["run_id"]) is None
):
    raise SystemExit(1)
print(payload["run_id"])
PY
}

initialize_state() {
  (( EUID == 0 )) || die "fixed production state requires root execution"
  [[ ! -L "$STATE_ROOT" ]] || die "state root symlink is forbidden"
  mkdir -p -- "$STATE_ROOT"
  chown 0:0 -- "$STATE_ROOT"
  chmod 700 -- "$STATE_ROOT"
  [[ "$(stat -c '%u:%g:%a' -- "$STATE_ROOT")" == "0:0:700" ]] ||
    die "state root ownership/mode is unsafe"
  exec 9>"$LOCK_FILE"
  chown 0:0 -- "$LOCK_FILE"
  chmod 600 -- "$LOCK_FILE"
  flock -n 9 || die "another admin feature acceptance run owns the lock"
}

validate_runtime() {
  require_command docker
  require_command flock
  require_command python3
  require_env E2E_BASE_URL
  require_env E2E_ADMIN_PASSWORD
  require_env E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE
  require_env E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE
  require_env E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT
  [[ "${E2E_LIVE_ALLOW_PROD-}" == "1" ]] || die "E2E_LIVE_ALLOW_PROD=1 opt-in required"
  [[ "${E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE-}" == "1" ]] ||
    die "E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1 opt-in required"
  [[ "$E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] ||
    die "invalid API compose service"
  [[ "$E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] ||
    die "Playwright image must be an immutable image ID"
  [[ "$E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT" =~ ^[0-9a-f]{40}$ ]] ||
    die "expected git commit must be 40 lowercase hex"
  local image_commit
  image_commit="$(
    docker image inspect \
      --format '{{ index .Config.Labels "io.kortravelmap.c7.repository-commit" }}' \
      "$E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE" 2>/dev/null
  )" || die "Playwright image inspection failed"
  [[ "$image_commit" == "$E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT" ]] ||
    die "Playwright image source revision mismatch"
  docker compose --project-directory "$PWD" ps -q \
    "$E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE" >/dev/null 2>&1 ||
    die "Map API compose service lookup failed"
}

fixture_helper() {
  local action="$1"
  local output="$2"
  docker compose --project-directory "$PWD" exec -T \
    "$E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE" \
    python - "$action" --run-id "$RUN_ID" \
    <"$FIXTURE_HELPER" >"$output"
  chmod 600 -- "$output"
  chown 0:0 -- "$output"
}

stop_lingering_containers() {
  local container
  while IFS= read -r container; do
    [[ -z "$container" ]] && continue
    docker stop --time 15 "$container" >/dev/null 2>&1 || true
    docker container rm "$container" >/dev/null 2>&1 || true
  done < <(
    docker ps -aq \
      --filter "label=io.kortravelmap.admin-feature-acceptance.run-id=$RUN_ID"
  )
}

run_playwright() {
  local recovery_only="$1"
  local artifact_dir="$2"
  ACTIVE_CONTAINER="kor-travel-map-admin-feature-acceptance-${RUN_ID//[^a-z0-9]/-}-$RANDOM"
  mkdir -- "$artifact_dir"
  chown 0:0 -- "$artifact_dir"
  chmod 700 -- "$artifact_dir"
  local -a env_args=(
    --env E2E_BASE_URL
    --env E2E_ADMIN_PASSWORD
    --env E2E_LIVE_ALLOW_PROD=1
    --env E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1
    --env "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID=$RUN_ID"
    --env E2E_LIVE_WORKERS=1
    --env PLAYWRIGHT_ARTIFACT_ROOT=/evidence
    --env E2E_STORAGE_STATE=/tmp/admin-feature-acceptance-state.json
  )
  if [[ -n "${E2E_ADMIN_USERNAME-}" ]]; then
    env_args+=(--env E2E_ADMIN_USERNAME)
  fi
  if [[ "$recovery_only" == "1" ]]; then
    env_args+=(--env E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY=1)
  fi
  docker run \
    --name "$ACTIVE_CONTAINER" \
    --label "io.kortravelmap.admin-feature-acceptance.run-id=$RUN_ID" \
    --mount "type=bind,src=$artifact_dir,dst=/evidence" \
    "${env_args[@]}" \
    "$E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE" \
    npm run e2e:live -- \
    e2e/live/admin-feature-acceptance-write.live.spec.ts \
    --workers=1 --retries=0
  local status=$?
  docker container rm "$ACTIVE_CONTAINER" >/dev/null 2>&1 || true
  ACTIVE_CONTAINER=""
  return "$status"
}

finish_signal() {
  local code="$1"
  if [[ -n "$ACTIVE_CONTAINER" ]]; then
    docker stop --time 15 "$ACTIVE_CONTAINER" >/dev/null 2>&1 || true
  fi
  atomic_json "$BLOCKED_FILE" interrupted blocked || true
  exit "$code"
}

recover_run() {
  RUN_ID="$(read_blocked_run_id)" || die "BLOCKED state is invalid"
  RUNTIME_DIR="$STATE_ROOT/recovery-$RUN_ID-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -- "$RUNTIME_DIR"
  chown 0:0 -- "$RUNTIME_DIR"
  chmod 700 -- "$RUNTIME_DIR"
  atomic_json "$BLOCKED_FILE" recovery_running blocked
  stop_lingering_containers
  local browser_status=0
  local fixture_status=0
  run_playwright 1 "$RUNTIME_DIR/playwright-recovery" || browser_status=$?
  fixture_helper cleanup "$RUNTIME_DIR/direct-cleanup.json" || fixture_status=$?
  fixture_helper audit "$RUNTIME_DIR/direct-audit.json" || fixture_status=$?
  if (( browser_status != 0 || fixture_status != 0 )); then
    atomic_json "$BLOCKED_FILE" recovery_failed blocked
    die "recovery left owned residue"
  fi
  atomic_json "$RUNTIME_DIR/result.json" recovered complete
  python3 - "$BLOCKED_FILE" <<'PY'
import os
import sys

os.unlink(sys.argv[1])
PY
}

run_new() {
  [[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "prior BLOCKED state requires recover mode"
  RUN_ID="$(python3 - <<'PY'
import secrets
from datetime import datetime, timezone

stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
print(f"live-{stamp}-{secrets.token_hex(6)}")
PY
)"
  RUNTIME_DIR="$STATE_ROOT/run-$RUN_ID"
  mkdir -- "$RUNTIME_DIR"
  chown 0:0 -- "$RUNTIME_DIR"
  chmod 700 -- "$RUNTIME_DIR"
  atomic_json "$BLOCKED_FILE" fixture_seed_pending blocked
  fixture_helper seed "$RUNTIME_DIR/direct-seed.json" || {
    atomic_json "$BLOCKED_FILE" fixture_seed_failed blocked
    die "direct fixture seed failed"
  }
  atomic_json "$BLOCKED_FILE" browser_running blocked
  local test_status=0
  local browser_cleanup_status=0
  local fixture_cleanup_status=0
  run_playwright 0 "$RUNTIME_DIR/playwright-main" || test_status=$?
  atomic_json "$BLOCKED_FILE" browser_cleanup_running blocked
  run_playwright 1 "$RUNTIME_DIR/playwright-recovery" || browser_cleanup_status=$?
  fixture_helper cleanup "$RUNTIME_DIR/direct-cleanup.json" || fixture_cleanup_status=$?
  fixture_helper audit "$RUNTIME_DIR/direct-audit.json" || fixture_cleanup_status=$?
  if (( browser_cleanup_status != 0 || fixture_cleanup_status != 0 )); then
    atomic_json "$BLOCKED_FILE" cleanup_failed blocked
    die "owned fixture cleanup left residue"
  fi
  if (( test_status != 0 )); then
    atomic_json "$BLOCKED_FILE" test_failed_restored blocked
    die "acceptance assertion failed; residue restored but recovery acknowledgement required"
  fi
  atomic_json "$RUNTIME_DIR/result.json" passed complete
  python3 - "$BLOCKED_FILE" <<'PY'
import os
import sys

os.unlink(sys.argv[1])
PY
}

[[ "$MODE" == "run" || "$MODE" == "recover" ]] || die "usage: runner [run|recover]"
safe_root_file "${BASH_SOURCE[0]}"
safe_root_file "$FIXTURE_HELPER"
initialize_state
validate_runtime
trap 'finish_signal 130' INT
trap 'finish_signal 143' TERM
if [[ "$MODE" == "recover" ]]; then
  [[ -f "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] || die "no BLOCKED state to recover"
  recover_run
else
  run_new
fi

#!/usr/bin/env bash

# #741/#785 전용 production live lane. strict C7 state와 섞지 않는다.
set +x
set -euo pipefail
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly FIXTURE_HELPER="$SCRIPT_DIR/admin_feature_live_fixture.py"
readonly STATE_HELPER="$SCRIPT_DIR/admin_feature_live_state.py"
readonly SOURCE_MANIFEST="$SCRIPT_DIR/source-manifest.json"
readonly EXPECTED_INSTALL_ROOT="/usr/local/lib/kor-travel-map/admin-feature-live-acceptance"
readonly STATE_ROOT="/var/lib/kor-travel-map/admin-feature-live-acceptance"
readonly BLOCKED_FILE="$STATE_ROOT/BLOCKED.json"
readonly LOCK_FILE="$STATE_ROOT/orchestrator.lock"
readonly MODE="${1-run}"
RUN_ID=""
RUN_KEY=""
RUNTIME_DIR=""
ACTIVE_CONTAINER=""
ACTIVE_CONTAINER_ID=""
ACTIVE_EXECUTOR_STATE=""
RECOVERY_MODE=0

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
  local mode="${2-555}"
  [[
    -f "$path" &&
    ! -L "$path" &&
    "$(stat -c '%u:%g:%a' -- "$path")" == "0:0:$mode"
  ]] || die "root snapshot file metadata is unsafe"
}

state_helper() {
  python3 "$STATE_HELPER" "$@"
}

write_blocked() {
  state_helper write-blocked \
    --path "$BLOCKED_FILE" \
    --run-id "$RUN_ID" \
    --phase "$1" \
    --status blocked
}

write_result() {
  state_helper write-result \
    --path "$RUNTIME_DIR/result.json" \
    --run-id "$RUN_ID" \
    --phase "$1" \
    --status complete
}

write_executor() {
  local state_file="$1"
  local phase="$2"
  local name="$3"
  local container_id="$4"
  local exit_code="${5-}"
  local -a args=(
    write-executor
    --path "$state_file"
    --phase "$phase"
    --container-name "$name"
    --container-id "$container_id"
  )
  [[ -z "$exit_code" ]] || args+=(--exit-code "$exit_code")
  state_helper "${args[@]}"
}

set_run_key() {
  RUN_KEY="$(state_helper run-key --run-id "$RUN_ID")" || die "run identity hash failed"
  [[ "$RUN_KEY" =~ ^[0-9a-f]{64}$ ]] || die "run identity hash is invalid"
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

validate_compose_service_revision() {
  local service="$1"
  local label="$2"
  local container_id image_id revision running health
  container_id="$(
    docker compose --project-directory "$PWD" ps --no-trunc -q "$service" 2>/dev/null
  )" || die "$label compose service lookup failed"
  [[ "$container_id" =~ ^[0-9a-f]{64}$ ]] ||
    die "$label compose service does not resolve to one container"
  running="$(docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null)" ||
    die "$label container inspection failed"
  health="$(
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' \
      "$container_id" 2>/dev/null
  )" || die "$label health inspection failed"
  [[ "$running" == "true" && "$health" == "healthy" ]] ||
    die "$label container is not running and healthy"
  image_id="$(docker inspect --format '{{.Image}}' "$container_id" 2>/dev/null)" ||
    die "$label image lookup failed"
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "$label image ID is invalid"
  revision="$(
    docker image inspect \
      --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
      "$image_id" 2>/dev/null
  )" || die "$label image revision lookup failed"
  [[ "$revision" == "$E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT" ]] ||
    die "$label image source revision mismatch"
}

validate_runtime() {
  require_command docker
  require_command flock
  require_command python3
  require_env E2E_BASE_URL
  require_env E2E_ADMIN_PASSWORD
  require_env E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE
  require_env E2E_ADMIN_FEATURE_ACCEPTANCE_UI_SERVICE
  require_env E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE
  require_env E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT
  require_env E2E_C7_EXPECTED_UI_ORIGIN_SHA256
  require_env E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256
  [[ "${E2E_LIVE_ALLOW_PROD-}" == "1" ]] || die "E2E_LIVE_ALLOW_PROD=1 opt-in required"
  [[ "${E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE-}" == "1" ]] ||
    die "E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1 opt-in required"
  [[ "$E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] ||
    die "invalid API compose service"
  [[ "$E2E_ADMIN_FEATURE_ACCEPTANCE_UI_SERVICE" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] ||
    die "invalid UI compose service"
  [[ "$E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE" != "$E2E_ADMIN_FEATURE_ACCEPTANCE_UI_SERVICE" ]] ||
    die "API and UI compose services must be distinct"
  [[ "$E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] ||
    die "Playwright image must be an immutable image ID"
  [[ "$E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT" =~ ^[0-9a-f]{40}$ ]] ||
    die "expected git commit must be 40 lowercase hex"
  [[ "$E2E_C7_EXPECTED_UI_ORIGIN_SHA256" =~ ^[0-9a-f]{64}$ ]] ||
    die "expected UI origin hash must be 64 lowercase hex"
  [[ "$E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256" =~ ^[0-9a-f]{64}$ ]] ||
    die "expected API WebSocket origin hash must be 64 lowercase hex"

  state_helper validate-source \
    --root "$SCRIPT_DIR" \
    --expected-root "$EXPECTED_INSTALL_ROOT" \
    --manifest "$SOURCE_MANIFEST" \
    --expected-commit "$E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT" \
    --required-file "${BASH_SOURCE[0]##*/}" \
    --required-file "${FIXTURE_HELPER##*/}" \
    --required-file "${STATE_HELPER##*/}" || die "root source snapshot validation failed"

  local image_commit
  image_commit="$(
    docker image inspect \
      --format '{{ index .Config.Labels "io.kortravelmap.c7.repository-commit" }}' \
      "$E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE" 2>/dev/null
  )" || die "Playwright image inspection failed"
  [[ "$image_commit" == "$E2E_ADMIN_FEATURE_ACCEPTANCE_EXPECTED_GIT_COMMIT" ]] ||
    die "Playwright image source revision mismatch"
  validate_compose_service_revision "$E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE" "Map API"
  validate_compose_service_revision "$E2E_ADMIN_FEATURE_ACCEPTANCE_UI_SERVICE" "Map UI"
}

fixture_helper() {
  local action="$1"
  local output="$2"
  [[ "$RECOVERY_MODE" == "0" || "$action" != "seed" ]] ||
    die "recovery mode cannot seed fixtures"
  docker compose --project-directory "$PWD" exec -T \
    "$E2E_ADMIN_FEATURE_ACCEPTANCE_API_SERVICE" \
    python - "$action" --run-id "$RUN_ID" \
    <"$FIXTURE_HELPER" >"$output" 2>/dev/null || return
  chmod 600 -- "$output" || return
  chown 0:0 -- "$output" || return
}

write_lingering() {
  local state_file="$1"
  local phase="$2"
  shift 2
  local -a args=(write-lingering --path "$state_file" --phase "$phase")
  local container_id
  for container_id in "$@"; do
    args+=(--container-id "$container_id")
  done
  state_helper "${args[@]}"
}

stop_lingering_containers() {
  local state_file="$1"
  local container containers
  local -a container_ids=()
  containers="$(
    docker ps -aq --no-trunc \
      --filter "label=io.kortravelmap.admin-feature-acceptance.run-id=$RUN_ID"
  )" || return
  while IFS= read -r container; do
    [[ -z "$container" ]] && continue
    [[ "$container" =~ ^[0-9a-f]{64}$ ]] || return
    container_ids+=("$container")
  done <<<"$containers"
  write_lingering "$state_file" removal_pending "${container_ids[@]}" || return
  for container in "${container_ids[@]}"; do
    docker container rm --force "$container" >/dev/null 2>&1 || return
  done
  write_lingering "$state_file" removed "${container_ids[@]}"
}

clear_active() {
  ACTIVE_CONTAINER=""
  ACTIVE_CONTAINER_ID=""
  ACTIVE_EXECUTOR_STATE=""
}

remove_active() {
  local reference="${ACTIVE_CONTAINER_ID:-$ACTIVE_CONTAINER}"
  [[ -z "$reference" ]] || docker container rm --force "$reference" >/dev/null 2>&1 || true
  clear_active
}

run_playwright() {
  local recovery_only="$1"
  local artifact_dir="$2"
  local executor_state="$3"
  ACTIVE_CONTAINER="kor-travel-map-admin-feature-acceptance-${RUN_KEY:0:20}-$RANDOM"
  ACTIVE_CONTAINER_ID=""
  ACTIVE_EXECUTOR_STATE="$executor_state"
  mkdir -- "$artifact_dir" || return
  chown 0:0 -- "$artifact_dir" || return
  chmod 700 -- "$artifact_dir" || return
  local -a env_args=(
    --env E2E_BASE_URL
    --env E2E_ADMIN_PASSWORD
    --env E2E_LIVE_ALLOW_PROD=1
    --env E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1
    --env "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID=$RUN_ID"
    --env E2E_C7_EXPECTED_UI_ORIGIN_SHA256
    --env E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256
    --env E2E_LIVE_WORKERS=1
    --env PLAYWRIGHT_ARTIFACT_ROOT=/evidence
    --env E2E_STORAGE_STATE=/tmp/admin-feature-acceptance-state.json
  )
  [[ -z "${E2E_ADMIN_USERNAME-}" ]] || env_args+=(--env E2E_ADMIN_USERNAME)
  [[ "$recovery_only" != "1" ]] ||
    env_args+=(--env E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY=1)

  write_executor "$executor_state" create_pending "$ACTIVE_CONTAINER" "" || return
  local container_id exit_code
  container_id="$(docker create --pull=never \
    --name "$ACTIVE_CONTAINER" \
    --label "io.kortravelmap.admin-feature-acceptance.run-id=$RUN_ID" \
    --network bridge \
    --ipc private \
    --read-only \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --tmpfs /root/.cache:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.config:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.npm:rw,nosuid,nodev,noexec,mode=700 \
    --cap-drop ALL \
    --mount "type=bind,src=$artifact_dir,dst=/evidence" \
    "${env_args[@]}" \
    "$E2E_ADMIN_FEATURE_ACCEPTANCE_PLAYWRIGHT_IMAGE" \
    npm run e2e:live -- \
    e2e/live/admin-feature-acceptance-write.live.spec.ts \
    --workers=1 --retries=0 2>/dev/null)" || {
      write_executor "$executor_state" create_failed "$ACTIVE_CONTAINER" "" || true
      remove_active
      return 1
    }
  if [[ ! "$container_id" =~ ^[0-9a-f]{64}$ ]]; then
    write_executor "$executor_state" create_failed "$ACTIVE_CONTAINER" "" || true
    remove_active
    return 1
  fi
  ACTIVE_CONTAINER_ID="$container_id"
  write_executor "$executor_state" created "$ACTIVE_CONTAINER" "$container_id" || {
    remove_active
    return 1
  }
  if ! docker start "$container_id" >/dev/null 2>&1; then
    write_executor "$executor_state" start_failed "$ACTIVE_CONTAINER" "$container_id" || true
    remove_active
    return 1
  fi
  write_executor "$executor_state" running "$ACTIVE_CONTAINER" "$container_id" || {
    remove_active
    return 1
  }
  exit_code="$(docker wait "$container_id" 2>/dev/null)" || {
    write_executor "$executor_state" wait_failed "$ACTIVE_CONTAINER" "$container_id" || true
    remove_active
    return 1
  }
  if [[ ! "$exit_code" =~ ^[0-9]+$ ]]; then
    write_executor "$executor_state" wait_failed "$ACTIVE_CONTAINER" "$container_id" || true
    remove_active
    return 1
  fi
  write_executor "$executor_state" exited "$ACTIVE_CONTAINER" "$container_id" "$exit_code" ||
    return
  if ! docker container rm "$container_id" >/dev/null 2>&1; then
    write_executor \
      "$executor_state" remove_failed "$ACTIVE_CONTAINER" "$container_id" "$exit_code" || true
    return 1
  fi
  write_executor "$executor_state" removed "$ACTIVE_CONTAINER" "$container_id" "$exit_code" ||
    return
  clear_active
  return "$exit_code"
}

finish_signal() {
  local code="$1"
  if [[ -n "$ACTIVE_CONTAINER" ]]; then
    docker container rm --force \
      "${ACTIVE_CONTAINER_ID:-$ACTIVE_CONTAINER}" >/dev/null 2>&1 || true
    [[ -z "$ACTIVE_EXECUTOR_STATE" ]] ||
      write_executor \
        "$ACTIVE_EXECUTOR_STATE" interrupted "$ACTIVE_CONTAINER" "$ACTIVE_CONTAINER_ID" || true
  fi
  if [[ "$RUN_ID" =~ ^[a-z0-9][a-z0-9-]{15,79}$ ]]; then
    write_blocked interrupted || true
  fi
  exit "$code"
}

recover_run() {
  RECOVERY_MODE=1
  RUN_ID="$(state_helper read-blocked --path "$BLOCKED_FILE")" || die "BLOCKED state is invalid"
  set_run_key
  RUNTIME_DIR="$STATE_ROOT/recovery-$RUN_KEY-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -- "$RUNTIME_DIR"
  chown 0:0 -- "$RUNTIME_DIR"
  chmod 700 -- "$RUNTIME_DIR"
  write_blocked recovery_running
  stop_lingering_containers "$RUNTIME_DIR/lingering-containers.json"
  local browser_status=0
  local fixture_status=0
  run_playwright \
    1 \
    "$RUNTIME_DIR/playwright-recovery" \
    "$RUNTIME_DIR/executor-recovery.json" || browser_status=$?
  fixture_helper cleanup "$RUNTIME_DIR/direct-cleanup.json" || fixture_status=$?
  fixture_helper audit "$RUNTIME_DIR/direct-audit.json" || fixture_status=$?
  if (( browser_status != 0 || fixture_status != 0 )); then
    write_blocked recovery_failed
    die "recovery left owned residue"
  fi
  write_result recovered
  state_helper clear-blocked --path "$BLOCKED_FILE"
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
  set_run_key
  RUNTIME_DIR="$STATE_ROOT/run-$RUN_KEY"
  mkdir -- "$RUNTIME_DIR"
  chown 0:0 -- "$RUNTIME_DIR"
  chmod 700 -- "$RUNTIME_DIR"
  write_blocked fixture_seed_pending
  fixture_helper seed "$RUNTIME_DIR/direct-seed.json" || {
    write_blocked fixture_seed_failed
    die "direct fixture seed failed"
  }
  write_blocked browser_running
  local test_status=0
  local browser_cleanup_status=0
  local fixture_cleanup_status=0
  run_playwright \
    0 \
    "$RUNTIME_DIR/playwright-main" \
    "$RUNTIME_DIR/executor-main.json" || test_status=$?
  write_blocked browser_cleanup_running
  run_playwright \
    1 \
    "$RUNTIME_DIR/playwright-recovery" \
    "$RUNTIME_DIR/executor-recovery.json" || browser_cleanup_status=$?
  fixture_helper cleanup "$RUNTIME_DIR/direct-cleanup.json" || fixture_cleanup_status=$?
  fixture_helper audit "$RUNTIME_DIR/direct-audit.json" || fixture_cleanup_status=$?
  if (( browser_cleanup_status != 0 || fixture_cleanup_status != 0 )); then
    write_blocked cleanup_failed
    die "owned fixture cleanup left residue"
  fi
  if (( test_status != 0 )); then
    write_blocked test_failed_restored
    die "acceptance assertion failed; residue restored but recovery acknowledgement required"
  fi
  write_result passed
  state_helper clear-blocked --path "$BLOCKED_FILE"
}

[[ "$MODE" == "run" || "$MODE" == "recover" ]] || die "usage: runner [run|recover]"
safe_root_file "${BASH_SOURCE[0]}"
safe_root_file "$FIXTURE_HELPER"
safe_root_file "$STATE_HELPER"
safe_root_file "$SOURCE_MANIFEST" 444
validate_runtime
initialize_state
trap 'finish_signal 130' INT
trap 'finish_signal 143' TERM
if [[ "$MODE" == "recover" ]]; then
  [[ -f "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] || die "no BLOCKED state to recover"
  recover_run
else
  run_new
fi

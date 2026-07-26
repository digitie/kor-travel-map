#!/usr/bin/env bash

# #741/#785/T-VN-15 전용 production live lane. strict C7 state와 섞지 않는다.
set +x
set -euo pipefail
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly FIXTURE_HELPER="$SCRIPT_DIR/admin_feature_live_fixture.py"
readonly STATE_HELPER="$SCRIPT_DIR/admin_feature_live_state.py"
readonly SUPERVISOR="$SCRIPT_DIR/admin_feature_live_supervisor.py"
readonly SOURCE_MANIFEST="$SCRIPT_DIR/source-manifest.json"
readonly INSTALL_BASE="/usr/local/lib/kor-travel-map/admin-feature-live-acceptance"
readonly C7_INSTALL_BASE="/usr/local/lib/kor-travel-map/c7-runner"
readonly HOST_ATTESTATION_FILE="/etc/kor-travel-map/c7-prod-live-e2e-attestation.json"
readonly PLAYWRIGHT_BASE_IMAGE="mcr.microsoft.com/playwright:v1.60.0-noble@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948"
readonly STATE_ROOT="/var/lib/kor-travel-map/admin-feature-live-acceptance"
readonly BLOCKED_FILE="$STATE_ROOT/BLOCKED.json"
readonly ACTIVE_FILE="$STATE_ROOT/ACTIVE.json"
readonly LOCK_FILE="$STATE_ROOT/orchestrator.lock"
readonly BARRIER_FILE="$STATE_ROOT/docker-lifecycle.barrier"
readonly MODE="${1-run}"

RUN_ID=""
RUN_KEY=""
ACTOR="main"
ATTEMPT=0
RUNTIME_DIR=""
LIFECYCLE_DIR=""
API_CONTAINER_ID=""
API_IMAGE_ID=""
COMPATIBLE_PAIR_SHA256=""
HOST_ATTESTATION_SHA256=""
BARRIER_FD=""

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
  local mode="$2"
  [[
    -f "$path" &&
    ! -L "$path" &&
    "$(stat -c '%u:%g:%a' -- "$path")" == "0:0:$mode"
  ]] || die "root snapshot file metadata is unsafe"
}

state_helper() {
  python3 -I -B "$STATE_HELPER" "$@"
}

write_blocked() {
  state_helper write-blocked \
    --path "$BLOCKED_FILE" \
    --run-id "$RUN_ID" \
    --recovery-attempt "$ATTEMPT" \
    --phase "$1" \
    --status blocked
}

write_result() {
  state_helper write-result \
    --path "$RUNTIME_DIR/result.json" \
    --run-id "$RUN_ID" \
    --recovery-attempt "$ATTEMPT" \
    --phase "$1" \
    --status complete \
    --compatible-pair-sha256 "$COMPATIBLE_PAIR_SHA256" \
    --host-attestation-sha256 "$HOST_ATTESTATION_SHA256"
}

set_run_key() {
  RUN_KEY="$(state_helper run-key --run-id "$RUN_ID")" || die "run identity hash failed"
  [[ "$RUN_KEY" =~ ^[0-9a-f]{64}$ ]] || die "run identity hash is invalid"
}

validate_service_env() {
  local name="$1"
  require_env "$name"
  [[ "${!name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] ||
    die "compose service env is invalid: $name"
}

validate_sha256_env() {
  local name="$1"
  require_env "$name"
  [[ "${!name}" =~ ^[0-9a-f]{64}$ ]] || die "SHA256 env is invalid: $name"
}

validate_runtime() {
  require_command docker
  require_command flock
  require_command python3
  require_command setsid
  docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is unavailable"
  (( EUID == 0 )) || die "fixed production state requires root execution"

  require_env E2E_BASE_URL
  require_env NEXT_PUBLIC_KOR_TRAVEL_MAP_API
  require_env E2E_DAGSTER_URL
  require_env E2E_ADMIN_PASSWORD
  require_env E2E_C7_EXPECTED_GIT_COMMIT
  require_env E2E_C7_COMPATIBLE_PAIR_MANIFEST
  require_env E2E_C7_PLAYWRIGHT_IMAGE
  validate_sha256_env E2E_C7_EXPECTED_UI_ORIGIN_SHA256
  validate_sha256_env E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256
  validate_sha256_env E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256
  validate_service_env E2E_C7_DAGSTER_WEB_SERVICE
  validate_service_env E2E_C7_DAGSTER_DAEMON_SERVICE
  validate_service_env E2E_C7_UI_SERVICE
  validate_service_env E2E_C7_MAP_API_SERVICE
  validate_service_env E2E_C7_PINVI_API_SERVICE

  [[ "${E2E_LIVE_ALLOW_PROD-}" == "1" ]] || die "E2E_LIVE_ALLOW_PROD=1 opt-in required"
  [[ "${E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE-}" == "1" ]] ||
    die "E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1 opt-in required"
  [[ "$E2E_C7_EXPECTED_GIT_COMMIT" =~ ^[0-9a-f]{40}$ ]] ||
    die "expected Git commit is invalid"
  [[ "$E2E_C7_PLAYWRIGHT_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] ||
    die "Playwright executor must be an immutable image ID"
  [[ "$E2E_C7_COMPATIBLE_PAIR_MANIFEST" == /* ]] ||
    die "compatible-pair manifest path must be absolute"

  local expected_root c7_module
  expected_root="$INSTALL_BASE/$E2E_C7_EXPECTED_GIT_COMMIT"
  c7_module="$C7_INSTALL_BASE/$E2E_C7_EXPECTED_GIT_COMMIT/scripts/lib/c7_prod_attestation.py"
  state_helper validate-source \
    --root "$SCRIPT_DIR" \
    --expected-root "$expected_root" \
    --manifest "$SOURCE_MANIFEST" \
    --expected-commit "$E2E_C7_EXPECTED_GIT_COMMIT" \
    --required-file "${BASH_SOURCE[0]##*/}" \
    --required-file "${FIXTURE_HELPER##*/}" \
    --required-file "${STATE_HELPER##*/}" \
    --required-file "${SUPERVISOR##*/}" || die "targeted source snapshot validation failed"
  state_helper validate-c7-module \
    --module "$c7_module" \
    --attestation "$HOST_ATTESTATION_FILE" \
    --expected-commit "$E2E_C7_EXPECTED_GIT_COMMIT" ||
    die "strict C7 module bootstrap validation failed"

  local -a attestation_output=()
  mapfile -t attestation_output < <(
    python3 -I -B "$c7_module" runtime \
      "$HOST_ATTESTATION_FILE" \
      "$E2E_C7_COMPATIBLE_PAIR_MANIFEST" \
      "$PWD" \
      "$PLAYWRIGHT_BASE_IMAGE" 2>/dev/null
  ) || die "trusted C7 v3/v4 runtime attestation failed"
  (( ${#attestation_output[@]} == 2 )) || die "runtime attestation output is invalid"
  COMPATIBLE_PAIR_SHA256="${attestation_output[0]}"
  HOST_ATTESTATION_SHA256="${attestation_output[1]}"
  [[ "$COMPATIBLE_PAIR_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "pair hash is invalid"
  [[ "$HOST_ATTESTATION_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "attestation hash is invalid"

  API_CONTAINER_ID="$(
    docker compose --project-directory "$PWD" ps --no-trunc -q \
      "$E2E_C7_MAP_API_SERVICE" 2>/dev/null
  )" || die "Map API compose lookup failed"
  [[ "$API_CONTAINER_ID" =~ ^[0-9a-f]{64}$ ]] || die "Map API container identity is invalid"
  API_IMAGE_ID="$(docker inspect --format '{{.Image}}' "$API_CONTAINER_ID" 2>/dev/null)" ||
    die "Map API image lookup failed"
  [[ "$API_IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Map API image identity is invalid"
}

initialize_state() {
  [[ ! -L "$STATE_ROOT" ]] || die "state root symlink is forbidden"
  mkdir -p -- "$STATE_ROOT"
  chown 0:0 -- "$STATE_ROOT"
  chmod 700 -- "$STATE_ROOT"
  [[ "$(stat -c '%u:%g:%a' -- "$STATE_ROOT")" == "0:0:700" ]] ||
    die "state root ownership/mode is unsafe"
  exec 9>"$LOCK_FILE"
  chown 0:0 -- "$LOCK_FILE"
  chmod 600 -- "$LOCK_FILE"
  flock -n 9 || die "another targeted live orchestrator owns the lock"
  exec {BARRIER_FD}>"$BARRIER_FILE"
  chown 0:0 -- "$BARRIER_FILE"
  chmod 600 -- "$BARRIER_FILE"
  flock "$BARRIER_FD" || die "Docker lifecycle barrier acquisition failed"
}

make_runtime() {
  mkdir -- "$RUNTIME_DIR"
  chown 0:0 -- "$RUNTIME_DIR"
  chmod 700 -- "$RUNTIME_DIR"
  LIFECYCLE_DIR="$RUNTIME_DIR/lifecycle"
  mkdir -- "$LIFECYCLE_DIR"
  chown 0:0 -- "$LIFECYCLE_DIR"
  chmod 700 -- "$LIFECYCLE_DIR"
}

container_name() {
  local actor="$1"
  local attempt="$2"
  local operation="$3"
  printf 'kor-travel-map-afla-%s-%s-a%s-%s\n' \
    "${RUN_KEY:0:16}" "${actor:0:1}" "$attempt" "$operation"
}

verify_owned_container() {
  local reference="$1"
  local actor="$2"
  local attempt="$3"
  local operation="$4"
  local run_label actor_label attempt_label operation_label
  run_label="$(
    docker inspect --format '{{index .Config.Labels "io.kortravelmap.admin-feature-acceptance.run-key"}}' \
      "$reference" 2>/dev/null
  )" || return 1
  actor_label="$(
    docker inspect --format '{{index .Config.Labels "io.kortravelmap.admin-feature-acceptance.actor"}}' \
      "$reference" 2>/dev/null
  )" || return 1
  attempt_label="$(
    docker inspect --format '{{index .Config.Labels "io.kortravelmap.admin-feature-acceptance.attempt"}}' \
      "$reference" 2>/dev/null
  )" || return 1
  operation_label="$(
    docker inspect --format '{{index .Config.Labels "io.kortravelmap.admin-feature-acceptance.operation"}}' \
      "$reference" 2>/dev/null
  )" || return 1
  [[
    "$run_label" == "$RUN_KEY" &&
    "$actor_label" == "$actor" &&
    "$attempt_label" == "$attempt" &&
    "$operation_label" == "$operation"
  ]]
}

drain_terminal_active() {
  local expected_actor="$1"
  local expected_attempt="$2"
  local expected_operation="$3"
  [[ -e "$ACTIVE_FILE" || -L "$ACTIVE_FILE" ]] || return 0
  local -a active=()
  mapfile -t active < <(
    state_helper read-terminal-active --path "$ACTIVE_FILE" --run-key "$RUN_KEY"
  ) || die "ACTIVE operation lacks a dead supervisor terminal outcome"
  (( ${#active[@]} == 3 )) || die "ACTIVE terminal output is invalid"
  local container_id="${active[0]}"
  local container_name="${active[1]}"
  if [[ -n "$container_id" ]] && docker container inspect "$container_id" >/dev/null 2>&1; then
    verify_owned_container \
      "$container_id" "$expected_actor" "$expected_attempt" "$expected_operation" ||
      die "ACTIVE container ownership mismatch"
    docker container rm --force -- "$container_id" >/dev/null 2>&1 ||
      die "ACTIVE container removal failed"
  fi
  if docker container inspect "$container_name" >/dev/null 2>&1; then
    verify_owned_container \
      "$container_name" "$expected_actor" "$expected_attempt" "$expected_operation" ||
      die "ACTIVE name ownership mismatch"
    docker container rm --force -- "$container_name" >/dev/null 2>&1 ||
      die "ACTIVE named container removal failed"
  fi
  state_helper clear-active --path "$ACTIVE_FILE" || die "ACTIVE terminal clear failed"
}

run_supervisor() {
  local mode="$1"
  local operation="$2"
  shift 2
  local name status=0
  name="$(container_name "$ACTOR" "$ATTEMPT" "$operation")"
  [[ ! -e "$ACTIVE_FILE" && ! -L "$ACTIVE_FILE" ]] ||
    die "prior ACTIVE operation must be drained before launch"
  setsid python3 -I -B "$SUPERVISOR" \
    --mode "$mode" \
    --actor "$ACTOR" \
    --attempt "$ATTEMPT" \
    --operation "$operation" \
    --run-key "$RUN_KEY" \
    --run-id "$RUN_ID" \
    --barrier-fd "$BARRIER_FD" \
    --state-helper "$STATE_HELPER" \
    --active-file "$ACTIVE_FILE" \
    --lifecycle-dir "$LIFECYCLE_DIR" \
    --runtime-dir "$RUNTIME_DIR" \
    --container-name "$name" \
    "$@" &
  local supervisor_pid=$!
  if wait "$supervisor_pid"; then status=0; else status=$?; fi
  drain_terminal_active "$ACTOR" "$ATTEMPT" "$operation"
  return "$status"
}

run_helper() {
  local action="$1"
  local output="$2"
  if [[ "$ACTOR" == "recovery" && "$action" == "seed" ]]; then
    die "recovery mode cannot seed fixtures"
  fi
  run_supervisor helper "helper-$action" \
    --image "$API_IMAGE_ID" \
    --api-container "$API_CONTAINER_ID" \
    --fixture "$FIXTURE_HELPER" \
    --helper-action "$action" \
    --output "$output"
}

run_executor() {
  local operation="$1"
  local artifact_dir="$2"
  local recovery_only="$3"
  mkdir -- "$artifact_dir"
  chown 0:0 -- "$artifact_dir"
  chmod 700 -- "$artifact_dir"
  local -a extra=()
  [[ "$recovery_only" != "1" ]] || extra+=(--recovery-only)
  run_supervisor executor "$operation" \
    --image "$E2E_C7_PLAYWRIGHT_IMAGE" \
    --artifact-dir "$artifact_dir" \
    "${extra[@]}"
}

run_cursor_probe() {
  run_supervisor probe probe-cursor-missing \
    --image "$API_IMAGE_ID" \
    --output "$RUNTIME_DIR/cursor-probe.json"
}

assert_container_residue_zero() {
  local containers
  containers="$(
    docker ps -aq --no-trunc \
      --filter "label=io.kortravelmap.admin-feature-acceptance.run-key=$RUN_KEY"
  )" || die "owned container residue lookup failed"
  [[ -z "$containers" ]] || die "owned Docker container residue remains"
  local actor attempt operation name
  for actor in main recovery; do
    for (( attempt = 0; attempt <= ATTEMPT; attempt += 1 )); do
      for operation in \
        probe-cursor-missing helper-seed executor-main executor-recovery helper-cleanup helper-audit; do
        name="$(container_name "$actor" "$attempt" "$operation")"
        ! docker container inspect -- "$name" >/dev/null 2>&1 ||
          die "deterministic Docker container name residue remains"
      done
    done
  done
  [[ ! -e "$ACTIVE_FILE" && ! -L "$ACTIVE_FILE" ]] || die "ACTIVE journal remains"
}

normalize_evidence_metadata() {
  chown -R 0:0 -- "$RUNTIME_DIR"
  find "$RUNTIME_DIR" -type d -exec chmod 700 {} +
  find "$RUNTIME_DIR" -type f -exec chmod 600 {} +
}

validate_evidence() {
  local mode="$1"
  normalize_evidence_metadata
  state_helper validate-evidence \
    --runtime "$RUNTIME_DIR" \
    --mode "$mode" \
    --attempt "$ATTEMPT" || die "host evidence validation failed"
}

finish_signal() {
  local code="$1"
  [[ -z "$RUN_ID" ]] || write_blocked interrupted || true
  exit "$code"
}

recover_run() {
  ACTOR="recovery"
  local -a recovery_identity=()
  mapfile -t recovery_identity < <(
    state_helper begin-recovery --path "$BLOCKED_FILE"
  ) || die "BLOCKED state is invalid"
  (( ${#recovery_identity[@]} == 2 )) || die "recovery identity output is invalid"
  RUN_ID="${recovery_identity[0]}"
  ATTEMPT="${recovery_identity[1]}"
  [[ "$ATTEMPT" =~ ^[1-9][0-9]*$ ]] || die "recovery attempt is invalid"
  set_run_key
  RUNTIME_DIR="$STATE_ROOT/recovery-$RUN_KEY-a$ATTEMPT"
  make_runtime

  if [[ -e "$ACTIVE_FILE" || -L "$ACTIVE_FILE" ]]; then
    # actor/attempt/operation은 terminal state 자체의 strict label 검증에서 다시 확인한다.
    # 정확한 prior identity를 읽지 못하면 catastrophic kill로 보고 자동 clear하지 않는다.
    local prior_actor prior_attempt prior_operation
    read -r prior_actor prior_attempt prior_operation < <(
      state_helper describe-active --path "$ACTIVE_FILE" --run-key "$RUN_KEY"
    ) || die "ACTIVE operation is not safely recoverable"
    drain_terminal_active "$prior_actor" "$prior_attempt" "$prior_operation"
  fi
  write_blocked recovery-running
  local browser_status=0 helper_status=0
  run_executor executor-recovery "$RUNTIME_DIR/playwright-recovery" 1 || browser_status=$?
  run_helper cleanup "$RUNTIME_DIR/direct-cleanup.json" || helper_status=$?
  run_helper audit "$RUNTIME_DIR/direct-audit.json" || helper_status=$?
  assert_container_residue_zero
  if (( browser_status != 0 || helper_status != 0 )); then
    write_blocked recovery-failed
    die "recovery left owned residue"
  fi
  validate_evidence recover
  write_result recovered
  state_helper clear-blocked --path "$BLOCKED_FILE" || die "BLOCKED clear failed"
  # clear 성공 직후 INT/TERM이 오면 finish_signal이 이미 성공한 run에 대해 새
  # BLOCKED를 재작성하는 창이 있었다(R792-4). RUN_ID를 비워 guard를 닫는다.
  RUN_ID=""
}

run_new() {
  [[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "prior BLOCKED state requires recover mode"
  [[ ! -e "$ACTIVE_FILE" && ! -L "$ACTIVE_FILE" ]] ||
    die "prior ACTIVE state requires operator recovery"
  RUN_ID="$(python3 - <<'PY'
import secrets
from datetime import datetime, timezone

stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
print(f"live-{stamp}-{secrets.token_hex(6)}")
PY
)"
  ACTOR="main"
  ATTEMPT=0
  set_run_key
  RUNTIME_DIR="$STATE_ROOT/run-$RUN_KEY"
  make_runtime
  write_blocked cursor-probe-pending
  run_cursor_probe || {
    write_blocked cursor-probe-failed
    die "cursor fail-closed probe failed"
  }
  write_blocked fixture-seed-pending
  run_helper seed "$RUNTIME_DIR/direct-seed.json" || {
    write_blocked fixture-seed-failed
    die "direct fixture seed failed"
  }
  write_blocked browser-running
  local test_status=0 browser_cleanup_status=0 helper_cleanup_status=0
  run_executor executor-main "$RUNTIME_DIR/playwright-main" 0 || test_status=$?
  write_blocked browser-cleanup-running
  run_executor executor-recovery "$RUNTIME_DIR/playwright-recovery" 1 ||
    browser_cleanup_status=$?
  run_helper cleanup "$RUNTIME_DIR/direct-cleanup.json" || helper_cleanup_status=$?
  run_helper audit "$RUNTIME_DIR/direct-audit.json" || helper_cleanup_status=$?
  assert_container_residue_zero
  if (( browser_cleanup_status != 0 || helper_cleanup_status != 0 )); then
    write_blocked cleanup-failed
    die "owned fixture cleanup left residue"
  fi
  if (( test_status != 0 )); then
    write_blocked test-failed-restored
    die "acceptance assertion failed; recovery acknowledgement required"
  fi
  validate_evidence normal
  write_result passed
  state_helper clear-blocked --path "$BLOCKED_FILE" || die "BLOCKED clear failed"
  # clear 성공 직후 signal 창 봉쇄 — recover_run과 동일(R792-4).
  RUN_ID=""
}

[[ "$MODE" == "run" || "$MODE" == "recover" ]] || die "usage: runner [run|recover]"
safe_root_file "${BASH_SOURCE[0]}" 555
safe_root_file "$FIXTURE_HELPER" 444
safe_root_file "$STATE_HELPER" 444
safe_root_file "$SUPERVISOR" 444
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

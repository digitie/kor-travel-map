#!/usr/bin/env bash

# 이 orchestrator는 n150의 docker compose project 디렉터리에서 실행한다. 실제
# host, URL, secret, compose service 이름에는 기본값을 두지 않는다.
set +x
set -euo pipefail
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly FRONTEND_DIR="$REPO_ROOT/packages/kor-travel-map-admin/frontend"
readonly COMPOSE_PROJECT_DIR="$PWD"
readonly SAFE_DAGSTER_JOB="feature_weather_kma_ultra_short_nowcast_job"
readonly SAFE_SCHEDULE="feature_weather_kma_short_forecast_hourly_schedule"
readonly HOST_ATTESTATION_FILE="/etc/kor-travel-map/c7-prod-live-e2e-attestation.json"
readonly FIXED_STATE_ROOT="/var/lib/kor-travel-map/c7-prod-live-e2e"
STATE_ROOT=""
BLOCKED_FILE=""
LOCK_FILE=""
LOCK_GUARD_INPUT_FD=""
LOCK_GUARD_OUTPUT_FD=""
LOCK_GUARD_PID=""
ORCHESTRATOR_VERIFIED=0
RUN_STATE_FILE=""
SCHEDULE_STATE_FILE=""
KMA_STATE_FILE=""
POI_STATE_FILE=""
RUNTIME_DIR=""

die() {
  printf 'C7 prod live E2E orchestrator failed: %s (values redacted)\n' "$1" >&2
  exit 1
}

require_env() {
  local name="$1"
  [[ -n "${!name-}" ]] || die "required env is missing: $name"
}

require_enabled() {
  local name="$1"
  [[ "${!name-}" == "1" ]] || die "explicit opt-in is required: $name=1"
}

require_command() {
  local name="$1"
  command -v -- "$name" >/dev/null 2>&1 || die "required command is missing: $name"
}

initialize_state_paths() {
  (( EUID == 0 )) || die "fixed production state root requires root execution"
  [[ -z "${XDG_STATE_HOME+x}" ]] ||
    die "XDG_STATE_HOME override is forbidden for prod live state"
  [[ ! -L "$FIXED_STATE_ROOT" ]] ||
    die "fixed production state root must not be a symlink"
  mkdir -p -- "$FIXED_STATE_ROOT"
  chown 0:0 -- "$FIXED_STATE_ROOT"
  chmod 700 -- "$FIXED_STATE_ROOT"
  STATE_ROOT="$(cd -- "$FIXED_STATE_ROOT" && pwd -P)" ||
    die "state root canonicalization failed"
  [[
    "$STATE_ROOT" == "$FIXED_STATE_ROOT" &&
    -d "$STATE_ROOT" &&
    ! -L "$STATE_ROOT" &&
    "$(stat -c '%u:%g:%a' -- "$STATE_ROOT")" == "0:0:700"
  ]] || die "state root is not canonical root-owned production storage"
  BLOCKED_FILE="$STATE_ROOT/BLOCKED.json"
  LOCK_FILE="$STATE_ROOT/orchestrator.lock"
}

fsync_file_and_parent() {
  local target="$1"
  python3 - "$target" <<'PY'
import os
import sys
from pathlib import Path

target = Path(sys.argv[1])
file_fd = os.open(target, os.O_RDONLY)
try:
    os.fsync(file_fd)
finally:
    os.close(file_fd)
directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory_fd)
finally:
    os.close(directory_fd)
PY
}

fsync_state_root() {
  python3 - "$STATE_ROOT" <<'PY'
import os
import sys

fd = os.open(sys.argv[1], os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
}

atomic_replace_state() {
  local destination="$1"
  local payload="$2"
  local temporary
  temporary="$(mktemp "$STATE_ROOT/.state.XXXXXX")" ||
    die "durable state temporary creation failed"
  chmod 600 -- "$temporary"
  printf '%s\n' "$payload" >"$temporary"
  fsync_file_and_parent "$temporary" || {
    rm -f -- "$temporary"
    die "durable state temporary fsync failed"
  }
  mv -T -- "$temporary" "$destination"
  chmod 600 -- "$destination"
  fsync_file_and_parent "$destination" ||
    die "durable state replace fsync failed"
}

start_orchestrator_lock_guard() {
  local lock_status
  coproc C7_LOCK_GUARD {
    python3 - "$LOCK_FILE" 3<&0 2>/dev/null <<'PY'
import fcntl
import os
import stat
import sys

path = sys.argv[1]
try:
    existing = os.lstat(path)
except FileNotFoundError:
    existing = None
if existing is not None and not stat.S_ISREG(existing.st_mode):
    raise SystemExit(2)

flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
fd = os.open(path, flags, 0o600)
try:
    if existing is None:
        os.fchown(fd, 0, 0)
        os.fchmod(fd, 0o600)
    observed = os.fstat(fd)
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != 0
        or observed.st_gid != 0
        or stat.S_IMODE(observed.st_mode) != 0o600
    ):
        raise SystemExit(3)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    os.fsync(fd)
    directory_fd = os.open(
        os.path.dirname(path),
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print("locked", flush=True)
    while os.read(3, 4096):
        pass
finally:
    os.close(fd)
PY
  }
  LOCK_GUARD_PID="$C7_LOCK_GUARD_PID"
  LOCK_GUARD_OUTPUT_FD="${C7_LOCK_GUARD[0]}"
  LOCK_GUARD_INPUT_FD="${C7_LOCK_GUARD[1]}"
  IFS= read -r -u "$LOCK_GUARD_OUTPUT_FD" lock_status ||
    die "orchestrator lock safe open/flock failed"
  [[ "$lock_status" == "locked" ]] ||
    die "orchestrator lock guard handshake failed"
  exec {LOCK_GUARD_OUTPUT_FD}<&-
}

runtime_is_private_direct_child() {
  local canonical_runtime runtime_name runtime_parent
  [[ -n "$RUNTIME_DIR" && -d "$RUNTIME_DIR" && ! -L "$RUNTIME_DIR" ]] ||
    return 1
  canonical_runtime="$(cd -- "$RUNTIME_DIR" && pwd -P)" || return 1
  runtime_parent="$(dirname -- "$canonical_runtime")"
  runtime_name="$(basename -- "$canonical_runtime")"
  [[ "$runtime_parent" == "$STATE_ROOT" ]] || return 1
  [[ "$runtime_name" =~ ^runtime\.[A-Za-z0-9]{6}$ ]] || return 1
  [[ "$canonical_runtime" == "$STATE_ROOT/$runtime_name" ]]
}

validate_sha256_env() {
  local name="$1"
  require_env "$name"
  [[ "${!name}" =~ ^[0-9a-f]{64}$ ]] || die "invalid lowercase SHA-256 env: $name"
}

validate_service_env() {
  local name="$1"
  require_env "$name"
  [[ "${!name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] ||
    die "invalid compose service env: $name"
}

finish() {
  local status=$?
  trap - EXIT INT TERM
  set +e
  if [[ -n "$RUNTIME_DIR" ]] && runtime_is_private_direct_child; then
    rm -rf -- "$RUNTIME_DIR" || status=1
    [[ ! -e "$RUNTIME_DIR" && ! -L "$RUNTIME_DIR" ]] || status=1
  elif [[ -n "$RUNTIME_DIR" ]]; then
    status=1
  fi
  if (( status == 0 && ORCHESTRATOR_VERIFIED == 1 )); then
    if rm -f -- \
      "$RUN_STATE_FILE" \
      "$SCHEDULE_STATE_FILE" \
      "$KMA_STATE_FILE" \
      "$POI_STATE_FILE"; then
      rm -f -- "$BLOCKED_FILE" || status=1
      fsync_state_root || status=1
    else
      status=1
    fi
  else
    (( status == 0 )) && status=1
  fi
  if [[ -n "$LOCK_GUARD_INPUT_FD" ]]; then
    exec {LOCK_GUARD_INPUT_FD}>&- || status=1
  fi
  if [[ -n "$LOCK_GUARD_PID" ]]; then
    wait "$LOCK_GUARD_PID" || status=1
  fi
  exit "$status"
}

create_blocked_sentinel() {
  [[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "BLOCKED.json was created concurrently"
  atomic_replace_state \
    "$BLOCKED_FILE" \
    '{"phase":"orchestrator_preflight","version":2}'
}

has_residual_state() {
  compgen -G "$STATE_ROOT/run-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/schedule-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/kma-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/poi-*.json" >/dev/null
}

require_command python3
initialize_state_paths
readonly STATE_ROOT BLOCKED_FILE LOCK_FILE
start_orchestrator_lock_guard

[[ ! -e "$BLOCKED_FILE" ]] ||
  die "BLOCKED.json exists; audited recovery is required before another run"
create_blocked_sentinel
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

has_residual_state &&
  die "residual run/schedule/KMA state exists; audited recovery is required"

RUNTIME_DIR="$(mktemp -d "$STATE_ROOT/runtime.XXXXXX")" ||
  die "private runtime directory creation failed"
chmod 700 -- "$RUNTIME_DIR"
export E2E_STORAGE_STATE="$RUNTIME_DIR/admin-state.json"
export PLAYWRIGHT_ARTIFACT_ROOT="$RUNTIME_DIR/playwright"
mkdir -p -- "$PLAYWRIGHT_ARTIFACT_ROOT"
chmod 700 -- "$PLAYWRIGHT_ARTIFACT_ROOT"

require_env E2E_BASE_URL
require_env NEXT_PUBLIC_KOR_TRAVEL_MAP_API
require_env E2E_DAGSTER_URL
require_env E2E_ADMIN_PASSWORD
require_env E2E_DAGSTER_JOB
require_env E2E_C7_SCHEDULE
validate_sha256_env E2E_C7_EXPECTED_UI_ORIGIN_SHA256
validate_sha256_env E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256
validate_sha256_env E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256
validate_service_env E2E_C7_DAGSTER_WEB_SERVICE
validate_service_env E2E_C7_DAGSTER_DAEMON_SERVICE
validate_service_env E2E_C7_UI_SERVICE

require_enabled E2E_LIVE_ALLOW_PROD
require_enabled E2E_ADMIN_WRITE
require_enabled E2E_C7_READ_AUTH_WRITE
require_enabled E2E_KMA_SCOPE_WRITE
require_enabled E2E_DAGSTER_WRITE
require_enabled E2E_DAGSTER_RUN
require_enabled E2E_QUEUE_SENSOR_BARRIER

[[ "$E2E_DAGSTER_JOB" == "$SAFE_DAGSTER_JOB" ]] ||
  die "E2E_DAGSTER_JOB is not the allowlisted KMA job"
[[ "$E2E_C7_SCHEDULE" == "$SAFE_SCHEDULE" ]] ||
  die "E2E_C7_SCHEDULE is not the allowlisted KMA schedule"

verify_trusted_host_attestation() {
  [[ -f "$HOST_ATTESTATION_FILE" && ! -L "$HOST_ATTESTATION_FILE" ]] ||
    die "trusted host attestation file is missing or unsafe"
  [[ "$(stat -c '%u' -- "$HOST_ATTESTATION_FILE")" == "0" ]] ||
    die "trusted host attestation must be root-owned"
  local mode
  mode="$(stat -c '%a' -- "$HOST_ATTESTATION_FILE")" ||
    die "trusted host attestation mode read failed"
  (( (8#$mode & 8#022) == 0 )) ||
    die "trusted host attestation must not be group/world writable"
  python3 - "$HOST_ATTESTATION_FILE" <<'PY'
import hashlib
import ipaddress
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def public_origin(
    raw: str, *, websocket: bool = False, require_root_path: bool = True
) -> str:
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or (require_root_path and parsed.path not in {"", "/"})
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit(10)
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise SystemExit(11)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_loopback
        or address.is_link_local
        or address.is_unspecified
    ):
        raise SystemExit(12)
    port = f":{parsed.port}" if parsed.port is not None else ""
    scheme = "wss" if websocket else "https"
    return urlunsplit((scheme, f"{host}{port}", "", "", ""))


def canonical_graphql(raw: str) -> str:
    parsed = urlsplit(raw)
    origin = public_origin(raw, require_root_path=False)
    pathname = parsed.path.rstrip("/")
    pathname = pathname if pathname.endswith("/graphql") else f"{pathname}/graphql"
    return f"{origin}{pathname}"


attestation_path = Path(sys.argv[1])
try:
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    machine_id = Path("/etc/machine-id").read_text(encoding="utf-8").strip()
except (OSError, ValueError):
    raise SystemExit(2)

required = {
    "api_ws_origin_sha256",
    "dagster_graphql_url_sha256",
    "hostname_sha256",
    "machine_id_sha256",
    "ui_origin_sha256",
    "version",
}
if not isinstance(attestation, dict) or set(attestation) != required:
    raise SystemExit(3)
if attestation["version"] != 1 or not machine_id:
    raise SystemExit(4)
for key in required - {"version"}:
    value = attestation[key]
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise SystemExit(5)

hostname = socket.getfqdn().rstrip(".").lower()
ui_origin = public_origin(os.environ["E2E_BASE_URL"])
api_ws_origin = public_origin(
    os.environ["NEXT_PUBLIC_KOR_TRAVEL_MAP_API"], websocket=True
)
dagster_graphql = canonical_graphql(os.environ["E2E_DAGSTER_URL"])
observed = {
    "api_ws_origin_sha256": sha256(api_ws_origin),
    "dagster_graphql_url_sha256": sha256(dagster_graphql),
    "hostname_sha256": sha256(hostname),
    "machine_id_sha256": sha256(machine_id),
    "ui_origin_sha256": sha256(ui_origin),
}
if any(attestation[key] != value for key, value in observed.items()):
    raise SystemExit(6)
if os.environ["E2E_C7_EXPECTED_UI_ORIGIN_SHA256"] != observed["ui_origin_sha256"]:
    raise SystemExit(7)
if (
    os.environ["E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256"]
    != observed["api_ws_origin_sha256"]
):
    raise SystemExit(8)
if (
    os.environ["E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256"]
    != observed["dagster_graphql_url_sha256"]
):
    raise SystemExit(9)
PY
}

verify_trusted_host_attestation ||
  die "trusted production host/machine/origin attestation failed"

canonical_dagster_graphql_sha256() {
  node <<'NODE'
const { createHash } = require("node:crypto");
let url;
try {
  url = new URL(process.env.E2E_DAGSTER_URL);
} catch {
  process.exit(2);
}
if (
  url.protocol !== "https:" ||
  url.username !== "" ||
  url.password !== "" ||
  url.search !== "" ||
  url.hash !== ""
) {
  process.exit(3);
}
const pathname = url.pathname.replace(/\/+$/, "");
url.pathname = pathname.endsWith("/graphql")
  ? pathname
  : `${pathname}/graphql`;
process.stdout.write(createHash("sha256").update(url.href).digest("hex"));
NODE
}

actual_dagster_origin_sha256="$(canonical_dagster_graphql_sha256)" ||
  die "Dagster GraphQL HTTPS endpoint canonicalization failed"
[[ "$actual_dagster_origin_sha256" =~ ^[0-9a-f]{64}$ ]] ||
  die "Dagster GraphQL endpoint SHA-256 attestation output is invalid"
[[ "$actual_dagster_origin_sha256" == "$E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256" ]] ||
  die "Dagster GraphQL endpoint origin attestation mismatch"

export E2E_LIVE_ALLOW_PROD
export E2E_ADMIN_WRITE E2E_C7_READ_AUTH_WRITE E2E_KMA_SCOPE_WRITE
export E2E_DAGSTER_WRITE E2E_DAGSTER_RUN E2E_QUEUE_SENSOR_BARRIER
export E2E_C7_SCHEDULE
export E2E_C7_EXPECTED_UI_ORIGIN_SHA256
export E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256
export E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256

RUN_STATE_FILE="$STATE_ROOT/run-$(date -u +%Y%m%dT%H%M%SZ)-$$.json"
SCHEDULE_STATE_FILE="$STATE_ROOT/schedule-$(date -u +%Y%m%dT%H%M%SZ)-$$.json"
KMA_STATE_FILE="$STATE_ROOT/kma-$(date -u +%Y%m%dT%H%M%SZ)-$$.json"
POI_STATE_FILE="$STATE_ROOT/poi-$(date -u +%Y%m%dT%H%M%SZ)-$$.json"
printf -v run_state_payload \
  '{"dagsterGraphqlEndpointSha256":"%s","phase":"orchestrator_started","version":2}' \
  "$actual_dagster_origin_sha256"
atomic_replace_state "$RUN_STATE_FILE" "$run_state_payload"
printf -v schedule_state_payload \
  '{"dagsterGraphqlEndpointSha256":"%s","phase":"schedule_snapshot_pending","version":2}' \
  "$actual_dagster_origin_sha256"
atomic_replace_state "$SCHEDULE_STATE_FILE" "$schedule_state_payload"
# helper의 이전-run fail-closed 검사와 호환되는 빈 restored baseline이다. 최종
# 검증은 sentinel run_id와 null cleanup_result를 거부하므로 실행 생략을 성공으로
# 오인하지 않는다.
atomic_replace_state \
  "$KMA_STATE_FILE" \
  '{"cleanup_result":null,"completed_scenarios":[],"external_systems":[],"idempotency_entries":[],"phase":"restored","request_ids":[],"request_terminal_statuses":{},"run_id":"__orchestrator_pending__","target_history":[],"target_refs":[],"version":3}'
atomic_replace_state \
  "$POI_STATE_FILE" \
  '{"phase":"orchestrator_pending","version":1}'

printf -v blocked_running_payload \
  '{"dagsterGraphqlEndpointSha256":"%s","expectedDagsterGraphqlEndpointSha256":"%s","phase":"orchestrator_running","version":2}' \
  "$actual_dagster_origin_sha256" \
  "$E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256"
atomic_replace_state "$BLOCKED_FILE" "$blocked_running_payload"

read_cap() {
  local service="$1"
  local temporary value
  local -a lines
  temporary="$(mktemp "$STATE_ROOT/cap.XXXXXX")"
  chmod 600 -- "$temporary"
  if ! docker compose --project-directory "$COMPOSE_PROJECT_DIR" exec -T "$service" \
    python -c \
      'from kortravelmap.settings import KorTravelMapSettings
value = KorTravelMapSettings().kma_weather_max_grids_per_run
if type(value) is not int or not 1 <= value <= 500:
    raise SystemExit(3)
print(value)' \
    >"$temporary" 2>/dev/null; then
    rm -f -- "$temporary"
    return 1
  fi
  mapfile -t lines <"$temporary"
  rm -f -- "$temporary"
  (( ${#lines[@]} == 1 )) || return 1
  value="${lines[0]}"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  (( value >= 1 && value <= 500 )) || return 1
  printf '%s\n' "$value"
}

web_cap="$(read_cap "$E2E_C7_DAGSTER_WEB_SERVICE")" ||
  die "Dagster web cap attestation failed"
daemon_cap="$(read_cap "$E2E_C7_DAGSTER_DAEMON_SERVICE")" ||
  die "Dagster daemon cap attestation failed"
[[ "$web_cap" == "$daemon_cap" ]] || die "Dagster cap attestation mismatch"

verify_ui_auth_preflight() {
  local -a container_ids
  mapfile -t container_ids < <(
    docker compose --project-directory "$COMPOSE_PROJECT_DIR" \
      ps -q "$E2E_C7_UI_SERVICE"
  )
  (( ${#container_ids[@]} == 1 )) ||
    die "UI compose service must resolve to exactly one running container"
  [[ -n "${container_ids[0]}" ]] || die "UI container id is empty"
  docker inspect -- "${container_ids[0]}" | python3 -c '
import json
import sys

try:
    records = json.load(sys.stdin)
    env = records[0]["Config"]["Env"]
except (IndexError, KeyError, TypeError, ValueError):
    raise SystemExit(2)
prefix = "KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH="
values = [item[len(prefix):] for item in env if isinstance(item, str) and item.startswith(prefix)]
if len(values) != 1 or not values[0]:
    raise SystemExit(3)
' >/dev/null || die "UI admin password hash runtime attestation failed"

  node <<'NODE'
async function main() {
  const baseUrl = new URL(process.env.E2E_BASE_URL);
  const loginUrl = new URL("/api/auth/login", baseUrl);
  const username = process.env.E2E_ADMIN_USERNAME || "admin";
  const response = await fetch(loginUrl, {
    body: JSON.stringify({ password: process.env.E2E_ADMIN_PASSWORD, username }),
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      Origin: baseUrl.origin,
    },
    method: "POST",
    redirect: "manual",
    signal: AbortSignal.timeout(30_000),
  });
  const setCookie = response.headers.get("set-cookie");
  if (
    response.status !== 200 ||
    typeof setCookie !== "string" ||
    setCookie.length === 0
  ) {
    process.exit(2);
  }
}
main().catch(() => {
  process.exitCode = 3;
});
NODE
}

verify_ui_auth_preflight || die "UI login POST/Set-Cookie preflight failed"

export E2E_C7_ORCHESTRATOR_STATE_FILE="$RUN_STATE_FILE"
export E2E_C7_SCHEDULE_STATE_FILE="$SCHEDULE_STATE_FILE"
export E2E_C7_KMA_STATE_FILE="$KMA_STATE_FILE"
export E2E_C7_POI_STATE_FILE="$POI_STATE_FILE"
export E2E_KMA_GRID_CAP="$daemon_cap"
export E2E_KMA_GRID_CAP_FROM_RUNTIME=1
export E2E_LIVE_WORKERS=1
export E2E_POI_CACHE_WRITE=1

cd -- "$FRONTEND_DIR"
readonly SPECS=(
  "e2e/live/ops-c7-read-auth.live.spec.ts"
  "e2e/live/ops-c7-kma-active-write.live.spec.ts"
  "e2e/live/ops-c7-kma-empty-write.live.spec.ts"
  "e2e/live/ops-c7-kma-cap-write.live.spec.ts"
  "e2e/live/ops-c7-schedule-write.live.spec.ts"
)
for spec in "${SPECS[@]}"; do
  npm run e2e:live -- "$spec" --workers=1 --retries=0
done
npm run e2e:live -- \
  "e2e/live/poi-cache-targets-write.live.spec.ts" \
  --workers=1 \
  --retries=0 \
  --grep \
  "API PUT로 target을 생성/수정/삭제하면 백엔드와 admin 목록·상세에 모두 반영된다"

state_is_exact_restored() {
  local kind="$1"
  local state_file="$2"
  python3 - "$kind" "$state_file" "$E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256" <<'PY'
import json
import re
import sys

kind, state_path, expected_hash = sys.argv[1:]


def exact_dict(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def nonempty_string(value):
    return isinstance(value, str) and bool(value)


uuid_pattern = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)


def sensor_snapshot(value):
    keys = {
        "canReset",
        "defaultStatus",
        "minIntervalSeconds",
        "selector",
        "selectorId",
        "sensorId",
        "status",
    }
    selector_keys = {
        "repositoryLocationName",
        "repositoryName",
        "sensorName",
    }
    if not exact_dict(value, keys) or not exact_dict(value["selector"], selector_keys):
        return False
    return (
        type(value["canReset"]) is bool
        and value["defaultStatus"] in {"RUNNING", "STOPPED"}
        and type(value["minIntervalSeconds"]) is int
        and value["minIntervalSeconds"] >= 0
        and nonempty_string(value["selectorId"])
        and nonempty_string(value["sensorId"])
        and value["status"] in {"RUNNING", "STOPPED"}
        and all(nonempty_string(item) for item in value["selector"].values())
    )


def schedule_snapshot(value):
    keys = {
        "canReset",
        "defaultCronSchedule",
        "defaultStatus",
        "effectiveCronSchedule",
        "name",
        "overrideCronSchedule",
        "overrideEffective",
        "overrideSaved",
        "repositoryLocationName",
        "repositoryName",
        "selectorId",
        "stateId",
        "status",
    }
    if not exact_dict(value, keys):
        return False
    return (
        type(value["canReset"]) is bool
        and type(value["overrideSaved"]) is bool
        and value["defaultStatus"] in {"RUNNING", "STOPPED"}
        and value["status"] in {"RUNNING", "STOPPED"}
        and (
            value["overrideCronSchedule"] is None
            or isinstance(value["overrideCronSchedule"], str)
        )
        and (
            value["overrideEffective"] is None
            or type(value["overrideEffective"]) is bool
        )
        and all(
            nonempty_string(value[field])
            for field in (
                "defaultCronSchedule",
                "effectiveCronSchedule",
                "name",
                "repositoryLocationName",
                "repositoryName",
                "selectorId",
                "stateId",
            )
        )
    )


try:
    with open(state_path, encoding="utf-8") as stream:
        state = json.load(stream)
except (OSError, ValueError):
    raise SystemExit(2)
if not isinstance(state, dict):
    raise SystemExit(15)
if state.get("phase") != "restored":
    raise SystemExit(3)
if kind == "sensor":
    if state.get("version") != 3 or state.get("mutationIntent") is not None:
        raise SystemExit(14)
    snapshots = [
        state.get("initialSensor"),
        state.get("observedSensor"),
        state.get("ownedExpectedSensor"),
    ]
    if not all(sensor_snapshot(item) for item in snapshots):
        raise SystemExit(16)
    if not (
        snapshots[0] == snapshots[1] == snapshots[2]
    ):
        raise SystemExit(4)
elif kind == "schedule":
    if state.get("version") != 4 or state.get("mutationIntent") is not None:
        raise SystemExit(17)
    snapshots = [state.get("initial"), state.get("current"), state.get("ownedExpected")]
    if not all(schedule_snapshot(item) for item in snapshots):
        raise SystemExit(18)
    if not (
        snapshots[0] == snapshots[1] == snapshots[2]
    ):
        raise SystemExit(5)
elif kind == "kma":
    if state.get("version") != 3:
        raise SystemExit(19)
    cleanup = state.get("cleanup_result")
    if (
        not nonempty_string(state.get("run_id"))
        or state["run_id"] == "__orchestrator_pending__"
    ):
        raise SystemExit(8)
    if not exact_dict(
        cleanup,
        {"allRequestsTerminal", "preservedForManualCleanup", "restored"},
    ):
        raise SystemExit(9)
    if not (
        cleanup.get("allRequestsTerminal") is True
        and cleanup.get("preservedForManualCleanup") is False
        and cleanup.get("restored") is True
    ):
        raise SystemExit(10)
    target_refs = state.get("target_refs")
    if not isinstance(target_refs, list) or not target_refs:
        raise SystemExit(20)
    if any(
        not exact_dict(
            item,
            {
                "body",
                "entityTag",
                "externalSystem",
                "lockVersion",
                "status",
                "targetId",
                "targetKey",
            },
        )
        or not isinstance(item["body"], dict)
        or not nonempty_string(item["externalSystem"])
        or re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
            item["targetId"] if isinstance(item.get("targetId"), str) else "",
        )
        is None
        or type(item["lockVersion"]) is not int
        or item["lockVersion"] <= 0
        or item["entityTag"] != f'"{item["targetId"]}:{item["lockVersion"]}"'
        or not nonempty_string(item["targetKey"])
        or item["status"] != "deleted"
        for item in target_refs
    ):
        raise SystemExit(11)
    completed = state.get("completed_scenarios")
    if (
        not isinstance(completed, list)
        or not all(isinstance(item, str) for item in completed)
        or sorted(completed) != [
        "active",
        "cap",
        "empty",
        "invalidation",
        ]
    ):
        raise SystemExit(12)
    if len(completed) != len(set(completed)):
        raise SystemExit(13)
    external_systems = state.get("external_systems")
    if (
        not isinstance(external_systems, list)
        or not external_systems
        or not all(nonempty_string(item) for item in external_systems)
        or external_systems != sorted(set(external_systems))
        or external_systems
        != sorted({item["externalSystem"] for item in target_refs})
    ):
        raise SystemExit(22)
    identities = [
        (item["externalSystem"], item["targetKey"], item["targetId"])
        for item in target_refs
    ]
    if len(identities) != len(set(identities)):
        raise SystemExit(23)
    target_history = state.get("target_history")
    if not isinstance(target_history, list) or not target_history:
        raise SystemExit(33)
    history_identities = []
    for item in target_history:
        if (
            not exact_dict(
                item,
                {
                    "body",
                    "entityTag",
                    "externalSystem",
                    "lockVersion",
                    "status",
                    "targetId",
                    "targetKey",
                },
            )
            or not isinstance(item["body"], dict)
            or not nonempty_string(item["externalSystem"])
            or not nonempty_string(item["targetKey"])
            or not isinstance(item["targetId"], str)
            or uuid_pattern.fullmatch(item["targetId"]) is None
            or type(item["lockVersion"]) is not int
            or item["lockVersion"] <= 0
            or item["entityTag"]
            != f'"{item["targetId"]}:{item["lockVersion"]}"'
            or item["status"] != "deleted"
        ):
            raise SystemExit(34)
        history_identities.append(
            (item["externalSystem"], item["targetKey"], item["targetId"])
        )
    if len(history_identities) != len(set(history_identities)):
        raise SystemExit(35)
    current_by_natural_key = {
        (item["externalSystem"], item["targetKey"]): item["targetId"]
        for item in target_refs
    }
    current_target_ids = set(current_by_natural_key.values())
    if len(current_by_natural_key) != len(target_refs) or any(
        current_by_natural_key.get((item["externalSystem"], item["targetKey"]))
        is None
        or item["targetId"] in current_target_ids
        for item in target_history
    ):
        raise SystemExit(36)
    request_ids = state.get("request_ids")
    if (
        not isinstance(request_ids, list)
        or not request_ids
        or request_ids != sorted(set(request_ids))
        or not all(
            isinstance(item, str) and uuid_pattern.fullmatch(item)
            for item in request_ids
        )
    ):
        raise SystemExit(24)
    terminal_statuses = state.get("request_terminal_statuses")
    if (
        not isinstance(terminal_statuses, dict)
        or set(terminal_statuses) != set(request_ids)
        or not all(
            status in {"done", "failed", "cancelled"}
            for status in terminal_statuses.values()
        )
    ):
        raise SystemExit(25)
    idempotency_entries = state.get("idempotency_entries")
    if not isinstance(idempotency_entries, list) or not idempotency_entries:
        raise SystemExit(26)
    idempotency_keys = []
    for item in idempotency_entries:
        if (
            not exact_dict(
                item,
                {"body", "idempotency_key", "request_id", "status"},
            )
            or not isinstance(item["body"], dict)
            or not isinstance(item["idempotency_key"], str)
            or uuid_pattern.fullmatch(item["idempotency_key"]) is None
            or item["request_id"] not in request_ids
            or not nonempty_string(item["status"])
        ):
            raise SystemExit(27)
        idempotency_keys.append(item["idempotency_key"])
    if len(idempotency_keys) != len(set(idempotency_keys)):
        raise SystemExit(28)
elif kind == "poi":
    if state.get("version") != 1:
        raise SystemExit(29)
    if not exact_dict(
        state,
        {
            "entity_tag",
            "intended_body",
            "lock_version",
            "natural_key",
            "phase",
            "run_id",
            "same_socket_receipts",
            "target_id",
            "updated_at",
            "version",
        },
    ):
        raise SystemExit(30)
    target_id = state.get("target_id")
    lock_version = state.get("lock_version")
    entity_tag = state.get("entity_tag")
    if (
        state.get("phase") != "restored"
        or not nonempty_string(state.get("run_id"))
        or not isinstance(state.get("intended_body"), dict)
        or not exact_dict(
            state.get("natural_key"),
            {"external_system", "target_key"},
        )
        or not all(nonempty_string(value) for value in state["natural_key"].values())
        or not isinstance(target_id, str)
        or uuid_pattern.fullmatch(target_id) is None
        or type(lock_version) is not int
        or lock_version <= 0
        or entity_tag != f'"{target_id}:{lock_version}"'
        or not nonempty_string(state.get("updated_at"))
    ):
        raise SystemExit(31)
    receipts = state.get("same_socket_receipts")
    if (
        not isinstance(receipts, list)
        or len(receipts) != 3
        or any(type(item) is not int or item <= 0 for item in receipts)
        or receipts != sorted(set(receipts))
    ):
        raise SystemExit(32)
else:
    raise SystemExit(21)
if kind in {"sensor", "schedule"}:
    if state.get("dagsterGraphqlEndpointSha256") != expected_hash:
        raise SystemExit(6)
    if state.get("expectedDagsterGraphqlEndpointSha256") != expected_hash:
        raise SystemExit(7)
PY
}

remote_state_is_exact_restored() {
  node - \
    "$RUN_STATE_FILE" \
    "$SCHEDULE_STATE_FILE" \
    "$KMA_STATE_FILE" \
    "$POI_STATE_FILE" \
    "$E2E_STORAGE_STATE" <<'NODE'
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { readFile } = require("node:fs/promises");
const { chromium, devices } = require("@playwright/test");

const [
  sensorStatePath,
  scheduleStatePath,
  kmaStatePath,
  poiStatePath,
  storageStatePath,
] =
  process.argv.slice(2);
const SAFE_SENSOR = "feature_update_request_queue_sensor";
const SAFE_SCHEDULE = "feature_weather_kma_short_forecast_hourly_schedule";
const SCHEDULES_PATH = "/v1/ops/pipeline/schedules";

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function canonicalDagsterGraphql(raw) {
  const url = new URL(raw);
  if (
    url.protocol !== "https:" ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    throw new Error("unsafe Dagster endpoint");
  }
  const pathname = url.pathname.replace(/\/+$/, "");
  url.pathname = pathname.endsWith("/graphql")
    ? pathname
    : `${pathname}/graphql`;
  return url;
}

function requiredString(value) {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error("required string missing");
  }
  return value;
}

function stableStatus(value) {
  if (value !== "RUNNING" && value !== "STOPPED") {
    throw new Error("unstable status");
  }
  return value;
}

function scheduleSnapshot(schedule) {
  const overrideCronSchedule = schedule.override_cron_schedule ?? null;
  const overrideEffective = schedule.override_effective;
  if (
    overrideCronSchedule === null
      ? overrideEffective !== null || schedule.override_saved !== false
      : typeof overrideEffective !== "boolean" || schedule.override_saved !== true
  ) {
    throw new Error("schedule override contract mismatch");
  }
  return {
    canReset: schedule.can_reset,
    defaultCronSchedule: requiredString(schedule.default_cron_schedule),
    defaultStatus: stableStatus(schedule.default_status),
    effectiveCronSchedule: requiredString(schedule.effective_cron_schedule),
    name: requiredString(schedule.name),
    overrideCronSchedule,
    overrideEffective,
    overrideSaved: schedule.override_saved,
    repositoryLocationName: requiredString(schedule.repository_location_name),
    repositoryName: requiredString(schedule.repository_name),
    selectorId: requiredString(schedule.selector_id),
    stateId: requiredString(schedule.state_id),
    status: stableStatus(schedule.status),
  };
}

async function readJson(file) {
  return JSON.parse(await readFile(file, "utf8"));
}

async function verifySensor(sensorState, graphqlUrl, expectedHash) {
  const initial = sensorState.initialSensor;
  assert.equal(initial.selector.sensorName, SAFE_SENSOR);
  const query = `
query C7FinalQueueSensorStatus($selector: SensorSelector!) {
  sensorOrError(sensorSelector: $selector) {
    __typename
    ... on Sensor {
      name
      defaultStatus
      canReset
      minIntervalSeconds
      sensorState {
        id
        selectorId
        status
        repositoryName
        repositoryLocationName
      }
    }
  }
}`;
  const response = await fetch(graphqlUrl, {
    body: JSON.stringify({ query, variables: { selector: initial.selector } }),
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    method: "POST",
    redirect: "error",
    signal: AbortSignal.timeout(15_000),
  });
  if (!response.ok) throw new Error("sensor query failed");
  const envelope = await response.json();
  if (Array.isArray(envelope.errors) && envelope.errors.length > 0) {
    throw new Error("sensor GraphQL error");
  }
  const sensor = envelope?.data?.sensorOrError;
  if (sensor?.__typename !== "Sensor" || sensor.name !== SAFE_SENSOR) {
    throw new Error("sensor identity mismatch");
  }
  const state = sensor.sensorState;
  const observed = {
    canReset: sensor.canReset,
    defaultStatus: stableStatus(sensor.defaultStatus),
    minIntervalSeconds: sensor.minIntervalSeconds,
    selector: {
      repositoryLocationName: requiredString(state.repositoryLocationName),
      repositoryName: requiredString(state.repositoryName),
      sensorName: SAFE_SENSOR,
    },
    selectorId: requiredString(state.selectorId),
    sensorId: requiredString(state.id),
    status: stableStatus(state.status),
  };
  assert.equal(sha256(graphqlUrl.href), expectedHash);
  assert.deepEqual(observed, initial);
}

async function verifyScheduleAndKma(
  scheduleState,
  kmaState,
  poiState,
  storageStatePath,
  expectedHash,
) {
  const baseUrl = new URL(process.env.E2E_BASE_URL);
  if (
    baseUrl.protocol !== "https:" ||
    baseUrl.username !== "" ||
    baseUrl.password !== "" ||
    baseUrl.pathname !== "/" ||
    baseUrl.search !== "" ||
    baseUrl.hash !== "" ||
    sha256(baseUrl.origin) !== process.env.E2E_C7_EXPECTED_UI_ORIGIN_SHA256
  ) {
    throw new Error("UI origin attestation mismatch");
  }

  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({
      ...devices["Desktop Chrome"],
      storageState: storageStatePath,
    });
    const page = await context.newPage();
    const navigation = await page.goto(
      new URL("/ops/pipeline?tab=schedules", baseUrl).href,
      { waitUntil: "domcontentloaded" },
    );
    if (!navigation?.ok() || new URL(page.url()).pathname.startsWith("/login")) {
      throw new Error("authenticated schedule bootstrap failed");
    }
    const result = await page.evaluate(async (path) => {
      const response = await fetch(`/api/proxy${path}`, {
        cache: "no-store",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(30_000),
      });
      return { body: await response.json(), status: response.status };
    }, SCHEDULES_PATH);
    if (result.status !== 200 || result.body?.data?.status !== "ok") {
      throw new Error("schedule read failed");
    }
    const graphqlUrl = canonicalDagsterGraphql(result.body.data.graphql_url);
    assert.equal(sha256(graphqlUrl.href), expectedHash);
    const matches = (result.body.data.schedules ?? []).filter(
      (schedule) => schedule.name === SAFE_SCHEDULE,
    );
    assert.equal(matches.length, 1);
    assert.deepEqual(scheduleSnapshot(matches[0]), scheduleState.initial);
    const kmaProbe = await page.evaluate(
      async ({ externalSystems, refs }) => {
        const exactKeys = (value, keys) =>
          value !== null &&
          typeof value === "object" &&
          !Array.isArray(value) &&
          JSON.stringify(Object.keys(value).sort()) ===
            JSON.stringify([...keys].sort());
        const fetchJson = async (path) => {
          const expectedUrl = new URL(
            `/api/proxy${path}`,
            window.location.origin,
          ).href;
          const response = await fetch(expectedUrl, {
            cache: "no-store",
            credentials: "same-origin",
            headers: { Accept: "application/json" },
            signal: AbortSignal.timeout(30_000),
          });
          const contentType = response.headers.get("content-type") ?? "";
          let body = null;
          if (contentType.toLowerCase().includes("json")) {
            try {
              body = await response.json();
            } catch {
              body = null;
            }
          }
          return {
            body,
            contentType,
            exactUrl: response.url === expectedUrl,
            status: response.status,
          };
        };
        const targetStatuses = [];
        for (let offset = 0; offset < refs.length; offset += 10) {
          const batch = refs.slice(offset, offset + 10);
          targetStatuses.push(
            ...(await Promise.all(
              batch.map(async (ref) => ({
                externalSystem: ref.externalSystem,
                result: await fetchJson(
                  `/v1/admin/poi-cache-targets/${encodeURIComponent(
                    ref.externalSystem,
                  )}/${encodeURIComponent(ref.targetKey)}`,
                ),
                targetKey: ref.targetKey,
              })),
            )),
          );
        }
        const systemCounts = [];
        for (const externalSystem of externalSystems) {
          const query = new URLSearchParams({
            external_system: externalSystem,
            include_deleted: "false",
            page_size: "500",
          });
          const result = await fetchJson(
            `/v1/admin/poi-cache-targets?${query.toString()}`,
          );
          const body = result.body;
          const exactEnvelope =
            result.status === 200 &&
            result.exactUrl &&
            result.contentType.toLowerCase().startsWith("application/json") &&
            exactKeys(body, ["data", "meta"]) &&
            exactKeys(body.data, ["items"]) &&
            Array.isArray(body.data.items) &&
            exactKeys(body.meta, ["duration_ms", "page", "request_id"]) &&
            typeof body.meta.duration_ms === "number" &&
            body.meta.duration_ms >= 0 &&
            typeof body.meta.request_id === "string" &&
            body.meta.request_id.length > 0 &&
            exactKeys(body.meta.page, ["next_cursor", "page_size", "total"]) &&
            body.meta.page.next_cursor === null &&
            body.meta.page.page_size === 500 &&
            body.meta.page.total === null;
          systemCounts.push({
            count: exactEnvelope
              ? body.data.items.length
              : null,
            exactEnvelope,
            externalSystem,
            status: result.status,
          });
        }
        return {
          systemCounts,
          targetStatuses: targetStatuses.map((item) => {
            const expectedDetail = `POI/cache target 없음: '${item.externalSystem}'/'${item.targetKey}'`;
            return {
              exactNotFound:
                item.result.status === 404 &&
                item.result.exactUrl &&
                item.result.contentType
                  .toLowerCase()
                  .startsWith("application/problem+json") &&
                exactKeys(item.result.body, [
                  "code",
                  "detail",
                  "errors",
                  "request_id",
                  "status",
                  "title",
                  "type",
                ]) &&
                item.result.body.type ===
                  "https://kor-travel-map/errors/not-found" &&
                item.result.body.title === expectedDetail &&
                item.result.body.status === 404 &&
                item.result.body.detail === expectedDetail &&
                item.result.body.code === "NOT_FOUND" &&
                typeof item.result.body.request_id === "string" &&
                item.result.body.request_id.length > 0 &&
                Array.isArray(item.result.body.errors) &&
                item.result.body.errors.length === 0,
              externalSystem: item.externalSystem,
              status: item.result.status,
              targetKey: item.targetKey,
            };
          }),
        };
      },
      {
        externalSystems: [
          ...new Set([
            ...kmaState.external_systems,
            poiState.natural_key.external_system,
          ]),
        ].sort(),
        refs: [
          ...kmaState.target_refs,
          {
            externalSystem: poiState.natural_key.external_system,
            targetId: poiState.target_id,
            targetKey: poiState.natural_key.target_key,
          },
        ],
      },
    );
    assert.equal(
      kmaProbe.targetStatuses.length,
      kmaState.target_refs.length + 1,
    );
    assert.equal(
      kmaProbe.targetStatuses.every(
        (item) => item.status === 404 && item.exactNotFound,
      ),
      true,
    );
    assert.equal(
      kmaProbe.systemCounts.length,
      new Set([
        ...kmaState.external_systems,
        poiState.natural_key.external_system,
      ]).size,
    );
    assert.equal(
      kmaProbe.systemCounts.every(
        (item) =>
          item.status === 200 && item.exactEnvelope && item.count === 0,
      ),
      true,
    );
    await context.close();
  } finally {
    await browser.close();
  }
}

async function main() {
  const expectedHash = process.env.E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256;
  if (!/^[0-9a-f]{64}$/.test(expectedHash ?? "")) {
    throw new Error("invalid expected hash");
  }
  const graphqlUrl = canonicalDagsterGraphql(process.env.E2E_DAGSTER_URL);
  assert.equal(sha256(graphqlUrl.href), expectedHash);
  const [sensorState, scheduleState, kmaState, poiState] = await Promise.all([
    readJson(sensorStatePath),
    readJson(scheduleStatePath),
    readJson(kmaStatePath),
    readJson(poiStatePath),
  ]);
  await verifySensor(sensorState, graphqlUrl, expectedHash);
  await verifyScheduleAndKma(
    scheduleState,
    kmaState,
    poiState,
    storageStatePath,
    expectedHash,
  );
}

main().catch(() => {
  process.stderr.write(
    "C7 final remote read-only restoration verification failed (values redacted)\n",
  );
  process.exitCode = 1;
});
NODE
}

# 각 helper가 최초 상태와 최종 상태의 exact equality를 확인해 `restored`를
# 원자 기록한 경우에만 상태 파일과 BLOCKED sentinel을 제거한다.
state_is_exact_restored sensor "$RUN_STATE_FILE" ||
  die "sensor exact restoration evidence is missing"
state_is_exact_restored schedule "$SCHEDULE_STATE_FILE" ||
  die "schedule exact restoration evidence is missing"
state_is_exact_restored kma "$KMA_STATE_FILE" ||
  die "KMA exact restoration evidence is missing"
state_is_exact_restored poi "$POI_STATE_FILE" ||
  die "POI causal write exact restoration evidence is missing"
remote_state_is_exact_restored ||
  die "final remote exact restoration evidence is missing"
ORCHESTRATOR_VERIFIED=1

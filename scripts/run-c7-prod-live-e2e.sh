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
readonly RAW_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
STATE_ROOT=""
BLOCKED_FILE=""
LOCK_FILE=""
ORCHESTRATOR_VERIFIED=0
RUN_STATE_FILE=""
SCHEDULE_STATE_FILE=""
KMA_STATE_FILE=""
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

initialize_state_paths() {
  local requested_root
  [[ "$RAW_STATE_HOME" == /* ]] ||
    die "XDG state home must be an absolute path"
  requested_root="$RAW_STATE_HOME/kor-travel-map/c7-prod-live-e2e"
  mkdir -p -- "$requested_root"
  chmod 700 -- "$requested_root"
  STATE_ROOT="$(cd -- "$requested_root" && pwd -P)" ||
    die "state root canonicalization failed"
  [[ "$STATE_ROOT" == /* && -d "$STATE_ROOT" && ! -L "$STATE_ROOT" ]] ||
    die "state root is not a canonical directory"
  BLOCKED_FILE="$STATE_ROOT/BLOCKED.json"
  LOCK_FILE="$STATE_ROOT/orchestrator.lock"
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
    if rm -f -- "$RUN_STATE_FILE" "$SCHEDULE_STATE_FILE" "$KMA_STATE_FILE"; then
      rm -f -- "$BLOCKED_FILE" || status=1
    else
      status=1
    fi
  else
    (( status == 0 )) && status=1
  fi
  exit "$status"
}

create_blocked_sentinel() {
  if ! (
    set -o noclobber
    umask 077
    printf '%s\n' '{"phase":"orchestrator_preflight","version":2}' \
      >"$BLOCKED_FILE"
  ) 2>/dev/null; then
    die "BLOCKED.json was created concurrently"
  fi
  chmod 600 -- "$BLOCKED_FILE"
}

has_residual_state() {
  compgen -G "$STATE_ROOT/run-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/schedule-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/kma-*.json" >/dev/null
}

initialize_state_paths
readonly STATE_ROOT BLOCKED_FILE LOCK_FILE
exec 9>"$LOCK_FILE"
chmod 600 -- "$LOCK_FILE"
flock -n 9 || die "another C7 prod live E2E orchestrator holds the lock"

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
require_env E2E_DAGSTER_URL
require_env E2E_ADMIN_PASSWORD
require_env E2E_DAGSTER_JOB
require_env E2E_C7_SCHEDULE
validate_sha256_env E2E_C7_EXPECTED_UI_ORIGIN_SHA256
validate_sha256_env E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256
validate_sha256_env E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256
validate_service_env E2E_C7_DAGSTER_WEB_SERVICE
validate_service_env E2E_C7_DAGSTER_DAEMON_SERVICE

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
printf '{"dagsterGraphqlEndpointSha256":"%s","phase":"orchestrator_started","version":2}\n' \
  "$actual_dagster_origin_sha256" >"$RUN_STATE_FILE"
chmod 600 -- "$RUN_STATE_FILE"
printf '{"dagsterGraphqlEndpointSha256":"%s","phase":"schedule_snapshot_pending","version":2}\n' \
  "$actual_dagster_origin_sha256" >"$SCHEDULE_STATE_FILE"
chmod 600 -- "$SCHEDULE_STATE_FILE"
# helper의 이전-run fail-closed 검사와 호환되는 빈 restored baseline이다. 최종
# 검증은 sentinel run_id와 null cleanup_result를 거부하므로 실행 생략을 성공으로
# 오인하지 않는다.
printf '%s\n' '{"cleanup_result":null,"phase":"restored","run_id":"__orchestrator_pending__","version":1}' \
  >"$KMA_STATE_FILE"
chmod 600 -- "$KMA_STATE_FILE"

blocked_temporary="$BLOCKED_FILE.$$"
printf '{"dagsterGraphqlEndpointSha256":"%s","expectedDagsterGraphqlEndpointSha256":"%s","phase":"orchestrator_running","version":2}\n' \
  "$actual_dagster_origin_sha256" \
  "$E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256" >"$blocked_temporary"
chmod 600 -- "$blocked_temporary"
mv -- "$blocked_temporary" "$BLOCKED_FILE"

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

export E2E_C7_ORCHESTRATOR_STATE_FILE="$RUN_STATE_FILE"
export E2E_C7_SCHEDULE_STATE_FILE="$SCHEDULE_STATE_FILE"
export E2E_C7_KMA_STATE_FILE="$KMA_STATE_FILE"
export E2E_KMA_GRID_CAP="$daemon_cap"
export E2E_KMA_GRID_CAP_FROM_RUNTIME=1
export E2E_LIVE_WORKERS=1

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

state_is_exact_restored() {
  local kind="$1"
  local state_file="$2"
  python - "$kind" "$state_file" "$E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256" <<'PY'
import json
import sys

kind, state_path, expected_hash = sys.argv[1:]


def exact_dict(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def nonempty_string(value):
    return isinstance(value, str) and bool(value)


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
        "recentTicks",
        "repositoryLocationName",
        "repositoryName",
        "selectorId",
        "stateId",
        "status",
    }
    if not exact_dict(value, keys):
        return False
    tick_keys = {
        "cursor",
        "endTimestamp",
        "errorClass",
        "errorMessage",
        "runIds",
        "runKeys",
        "skipReason",
        "status",
        "tickId",
        "timestamp",
    }
    recent_ticks = value["recentTicks"]
    valid_ticks = isinstance(recent_ticks, list) and all(
        exact_dict(tick, tick_keys)
        and nonempty_string(tick["status"])
        and nonempty_string(tick["tickId"])
        and isinstance(tick["timestamp"], (int, float))
        and isinstance(tick["runIds"], list)
        and isinstance(tick["runKeys"], list)
        for tick in recent_ticks
    )
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
        and valid_ticks
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
    if state.get("version") != 1:
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
        not exact_dict(item, {"externalSystem", "targetKey", "status"})
        or not nonempty_string(item["externalSystem"])
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
  node - "$RUN_STATE_FILE" "$SCHEDULE_STATE_FILE" "$E2E_STORAGE_STATE" <<'NODE'
const assert = require("node:assert/strict");
const { createHash } = require("node:crypto");
const { readFile } = require("node:fs/promises");
const { chromium, devices } = require("@playwright/test");

const [sensorStatePath, scheduleStatePath, storageStatePath] = process.argv.slice(2);
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
    recentTicks: (schedule.recent_ticks ?? []).map((tick) => ({
      cursor: tick.cursor ?? null,
      endTimestamp: tick.end_timestamp ?? null,
      errorClass: tick.error?.class_name ?? null,
      errorMessage: tick.error?.message ?? null,
      runIds: [...(tick.run_ids ?? [])],
      runKeys: [...(tick.run_keys ?? [])],
      skipReason: tick.skip_reason ?? null,
      status: requiredString(tick.status),
      tickId: requiredString(tick.tick_id),
      timestamp: tick.timestamp,
    })),
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

async function verifySchedule(scheduleState, storageStatePath, expectedHash) {
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
  const [sensorState, scheduleState] = await Promise.all([
    readJson(sensorStatePath),
    readJson(scheduleStatePath),
  ]);
  await verifySensor(sensorState, graphqlUrl, expectedHash);
  await verifySchedule(scheduleState, storageStatePath, expectedHash);
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
remote_state_is_exact_restored ||
  die "final remote exact restoration evidence is missing"
ORCHESTRATOR_VERIFIED=1

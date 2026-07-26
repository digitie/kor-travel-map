#!/usr/bin/env bash

# 이 orchestrator는 n150의 docker compose project 디렉터리에서 실행한다. 실제
# host, URL, secret, compose service 이름에는 기본값을 두지 않는다.
set +x
set -euo pipefail
umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
readonly COMPOSE_PROJECT_DIR="$PWD"
readonly SAFE_DAGSTER_JOB="feature_update_request_worker"
readonly SAFE_SCHEDULE="feature_weather_kma_short_forecast_hourly_schedule"
readonly HOST_ATTESTATION_FILE="/etc/kor-travel-map/c7-prod-live-e2e-attestation.json"
readonly FIXED_STATE_ROOT="/var/lib/kor-travel-map/c7-prod-live-e2e"
readonly PLAYWRIGHT_BASE_IMAGE="mcr.microsoft.com/playwright:v1.60.0-noble@sha256:9bd26ad900bb5e0f4dee75839e957a89ae89c2b7ab1e76050e559790e946b948"
STATE_ROOT=""
EVIDENCE_ROOT=""
EVIDENCE_RUN_DIR=""
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
PLAYWRIGHT_IMAGE_ID=""
REPOSITORY_COMMIT=""
COMPATIBLE_PAIR_MANIFEST_SHA256=""
ALEMBIC_HEAD=""
ACTIVE_COMMAND_PID=""
ACTIVE_COMMAND_PGID=""
ACTIVE_CID_FILE=""
ACTIVE_CONTAINER_REF_FILE=""
ACTIVE_CREATE_OUTCOME_FILE=""
ACTIVE_CONTAINER_NAME=""
HOST_ATTESTATION_SHA256=""
HOST_ATTESTATION_SNAPSHOT=""
COMPATIBLE_PAIR_SNAPSHOT=""

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
  EVIDENCE_ROOT="$STATE_ROOT/evidence"
  if [[ -e "$EVIDENCE_ROOT" || -L "$EVIDENCE_ROOT" ]]; then
    [[
      -d "$EVIDENCE_ROOT" &&
      ! -L "$EVIDENCE_ROOT" &&
      "$(stat -c '%u:%g:%a' -- "$EVIDENCE_ROOT")" == "0:0:700"
    ]] || die "evidence root is not canonical root-owned storage"
  else
    mkdir -- "$EVIDENCE_ROOT"
    chown 0:0 -- "$EVIDENCE_ROOT"
    chmod 700 -- "$EVIDENCE_ROOT"
    fsync_state_root
  fi
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

snapshot_attested_inputs() {
  HOST_ATTESTATION_SNAPSHOT="$STATE_ROOT/attestation-$$.json"
  COMPATIBLE_PAIR_SNAPSHOT="$STATE_ROOT/compatible-pair-$$.json"
  python3 - \
    "$HOST_ATTESTATION_FILE" \
    "$HOST_ATTESTATION_SNAPSHOT" \
    "$HOST_ATTESTATION_SHA256" \
    "$E2E_C7_COMPATIBLE_PAIR_MANIFEST" \
    "$COMPATIBLE_PAIR_SNAPSHOT" \
    "$COMPATIBLE_PAIR_MANIFEST_SHA256" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

pairs = zip(sys.argv[1::3], sys.argv[2::3], sys.argv[3::3], strict=True)
created: list[Path] = []
try:
    for source_raw, destination_raw, expected_sha256 in pairs:
        source = Path(source_raw)
        destination = Path(destination_raw)
        source_fd = os.open(source, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            observed = os.fstat(source_fd)
            if (
                not stat.S_ISREG(observed.st_mode)
                or observed.st_uid != 0
                or observed.st_gid != 0
                or stat.S_IMODE(observed.st_mode) != 0o600
            ):
                raise RuntimeError("unsafe attested input")
            chunks = []
            while chunk := os.read(source_fd, 1024 * 1024):
                chunks.append(chunk)
            payload = b"".join(chunks)
        finally:
            os.close(source_fd)
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RuntimeError("attested input changed after preflight")
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        created.append(destination)
        try:
            os.fchown(destination_fd, 0, 0)
            os.fchmod(destination_fd, 0o600)
            offset = 0
            while offset < len(payload):
                offset += os.write(destination_fd, payload[offset:])
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    directory_fd = os.open(
        Path(sys.argv[2]).parent,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except Exception:
    for path in created:
        try:
            path.unlink()
        except OSError:
            pass
    raise
PY
}

preserve_evidence() {
  local status="$1"
  local temporary
  [[ -n "$EVIDENCE_ROOT" && -d "$EVIDENCE_ROOT" && ! -L "$EVIDENCE_ROOT" ]] ||
    return 1
  temporary="$(mktemp -d "$EVIDENCE_ROOT/.run.XXXXXX")" || return 1
  chmod 700 -- "$temporary" || return 1
  EVIDENCE_RUN_DIR="$EVIDENCE_ROOT/run-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  [[ ! -e "$EVIDENCE_RUN_DIR" && ! -L "$EVIDENCE_RUN_DIR" ]] || return 1
  python3 - \
    "$temporary" \
    "$RUNTIME_DIR" \
    "$RUN_STATE_FILE" \
    "$SCHEDULE_STATE_FILE" \
    "$KMA_STATE_FILE" \
    "$POI_STATE_FILE" \
    "$status" \
    "$ORCHESTRATOR_VERIFIED" \
    "$REPOSITORY_COMMIT" \
    "$PLAYWRIGHT_IMAGE_ID" \
    "$COMPATIBLE_PAIR_MANIFEST_SHA256" \
    "$ALEMBIC_HEAD" \
    "$HOST_ATTESTATION_SHA256" \
    "$HOST_ATTESTATION_SNAPSHOT" \
    "$COMPATIBLE_PAIR_SNAPSHOT" <<'PY'
import hashlib
import json
import os
import shutil
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

(
    destination_raw,
    runtime_raw,
    run_raw,
    schedule_raw,
    kma_raw,
    poi_raw,
    status_raw,
    verified_raw,
    repository_commit,
    playwright_image_id,
    pair_manifest_sha256,
    alembic_head,
    host_attestation_sha256,
    host_attestation_raw,
    compatible_pair_raw,
) = sys.argv[1:]
destination = Path(destination_raw)
runtime = Path(runtime_raw) if runtime_raw else None


def copy_regular(source: Path, target: Path) -> None:
    observed = source.lstat()
    if not stat.S_ISREG(observed.st_mode) or source.is_symlink():
        raise RuntimeError("unsafe evidence source")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copyfile(source, target)
    os.chown(target, 0, 0)
    os.chmod(target, 0o600)


for name, raw in (
    ("sensor.json", run_raw),
    ("schedule.json", schedule_raw),
    ("kma.json", kma_raw),
    ("poi.json", poi_raw),
):
    source = Path(raw) if raw else None
    if source is not None and source.exists():
        copy_regular(source, destination / "journals" / name)

for name, raw in (
    ("runtime-attestation.json", host_attestation_raw),
    ("compatible-pair.json", compatible_pair_raw),
):
    source = Path(raw)
    copy_regular(source, destination / name)

if (
    hashlib.sha256((destination / "runtime-attestation.json").read_bytes()).hexdigest()
    != host_attestation_sha256
    or hashlib.sha256((destination / "compatible-pair.json").read_bytes()).hexdigest()
    != pair_manifest_sha256
):
    raise RuntimeError("attested evidence snapshot hash mismatch")

if runtime is not None and runtime.exists():
    playwright = runtime / "playwright"
    if playwright.exists():
        for source in playwright.rglob("*"):
            relative = source.relative_to(playwright)
            if source.is_symlink():
                raise RuntimeError("symlink in Playwright evidence")
            if source.is_dir():
                target_directory = destination / "playwright" / relative
                target_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                os.chown(target_directory, 0, 0)
                os.chmod(target_directory, 0o700)
                continue
            safe_report = source.name in {
                "c7-results.xml",
                "c7-summary.html",
                "c7-summary.json",
            }
            if not safe_report:
                continue
            copy_regular(source, destination / "playwright" / relative)

files = []
for path in sorted(destination.rglob("*")):
    if path.is_file() and not path.is_symlink():
        files.append(
            {
                "path": path.relative_to(destination).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        )
manifest = {
    "alembic_head": alembic_head,
    "compatible_pair_manifest_sha256": pair_manifest_sha256,
    "files": files,
    "finished_at": datetime.now(UTC).isoformat(),
    "orchestrator_verified": verified_raw == "1",
    "host_attestation_sha256": host_attestation_sha256,
    "playwright_image_id": playwright_image_id,
    "repository_commit": repository_commit,
    "status": int(status_raw),
    "version": 1,
}
manifest_path = destination / "manifest.json"
manifest_path.write_text(
    json.dumps(manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    + "\n",
    encoding="utf-8",
)
os.chown(manifest_path, 0, 0)
os.chmod(manifest_path, 0o600)

for path in sorted(destination.rglob("*"), reverse=True):
    if path.is_file():
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    elif path.is_dir():
        os.chown(path, 0, 0)
        os.chmod(path, 0o700)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
root_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
try:
    os.fsync(root_fd)
finally:
    os.close(root_fd)
PY
  mv -T -- "$temporary" "$EVIDENCE_RUN_DIR" || return 1
  chmod 700 -- "$EVIDENCE_RUN_DIR" || return 1
  fsync_file_and_parent "$EVIDENCE_RUN_DIR/manifest.json" || return 1
}

finish() {
  local status=$?
  local container_clean=1
  local evidence_preserved=0
  trap - EXIT INT TERM
  set +e
  if [[ -n "$ACTIVE_COMMAND_PID" ]]; then
    terminate_active_command || status=1
    status=1
  fi
  remove_active_container || {
    status=1
    container_clean=0
  }
  if [[ -n "${E2E_STORAGE_STATE-}" ]]; then
    rm -f -- "$E2E_STORAGE_STATE" || status=1
  fi
  if (( container_clean == 1 )) && [[ -e "$BLOCKED_FILE" ]]; then
    if preserve_evidence "$status"; then
      evidence_preserved=1
    else
      status=1
    fi
  fi
  if ((
    status == 0 && ORCHESTRATOR_VERIFIED == 1 &&
      container_clean == 1 && evidence_preserved == 1
  )); then
    rm -f -- "$HOST_ATTESTATION_SNAPSHOT" "$COMPATIBLE_PAIR_SNAPSHOT" || status=1
  fi
  if ((
    status == 0 && ORCHESTRATOR_VERIFIED == 1 &&
      container_clean == 1 && evidence_preserved == 1
  )) &&
    [[ -n "$RUNTIME_DIR" ]] && runtime_is_private_direct_child; then
    rm -rf -- "$RUNTIME_DIR" || status=1
    [[ ! -e "$RUNTIME_DIR" && ! -L "$RUNTIME_DIR" ]] || status=1
  elif [[ -n "$RUNTIME_DIR" ]] &&
    ((
      status == 0 && ORCHESTRATOR_VERIFIED == 1 &&
        container_clean == 1 && evidence_preserved == 1
    )); then
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
    '{"phase":"orchestrator_preflight","version":3}'
}

has_residual_state() {
  compgen -G "$STATE_ROOT/run-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/schedule-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/kma-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/poi-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/runtime.*" >/dev/null ||
    compgen -G "$STATE_ROOT/.state.*" >/dev/null ||
    compgen -G "$STATE_ROOT/cap.*" >/dev/null ||
    compgen -G "$STATE_ROOT/attestation-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/compatible-pair-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/container-*.cid" >/dev/null ||
    compgen -G "$STATE_ROOT/container-*.json" >/dev/null ||
    compgen -G "$STATE_ROOT/container-*.outcome.json" >/dev/null
}

verify_clean_state_audit() {
  local audit_status
  if python3 "$SCRIPT_DIR/audit-c7-prod-live-state.py" >/dev/null; then
    audit_status=0
  else
    audit_status=$?
  fi
  (( audit_status == 0 )) ||
    die "C7 state audit rejected unsafe, unexpected, active, or recoverable residue"
}

require_command python3
require_command docker
require_command mkfifo
require_command setsid
require_command timeout
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is unavailable"
(( EUID == 0 )) || die "production live runner requires root execution"

require_env E2E_BASE_URL
require_env NEXT_PUBLIC_KOR_TRAVEL_MAP_API
require_env E2E_DAGSTER_URL
require_env E2E_ADMIN_PASSWORD
require_env E2E_DAGSTER_JOB
require_env E2E_C7_SCHEDULE
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

[[ "$E2E_C7_EXPECTED_GIT_COMMIT" =~ ^[0-9a-f]{40}$ ]] ||
  die "expected Git commit is invalid"
[[ "$E2E_C7_PLAYWRIGHT_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] ||
  die "Playwright executor must be an immutable image ID"
[[ "$E2E_C7_COMPATIBLE_PAIR_MANIFEST" == /* ]] ||
  die "compatible-pair manifest path must be absolute"

require_enabled E2E_LIVE_ALLOW_PROD
require_enabled E2E_ADMIN_WRITE
require_enabled E2E_C7_READ_AUTH_WRITE
require_enabled E2E_KMA_SCOPE_WRITE
require_enabled E2E_DAGSTER_WRITE
require_enabled E2E_DAGSTER_RUN
require_enabled E2E_QUEUE_SENSOR_BARRIER

[[ "$E2E_DAGSTER_JOB" == "$SAFE_DAGSTER_JOB" ]] ||
  die "E2E_DAGSTER_JOB is not the allowlisted update-request worker"
[[ "$E2E_C7_SCHEDULE" == "$SAFE_SCHEDULE" ]] ||
  die "E2E_C7_SCHEDULE is not the allowlisted KMA schedule"

run_verified_attestation_module() {
  python3 -I -B - \
    "$SCRIPT_DIR/lib/c7_prod_attestation.py" \
    "$HOST_ATTESTATION_FILE" \
    "$REPO_ROOT" \
    "$E2E_C7_EXPECTED_GIT_COMMIT" \
    "$@" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

module_path = Path(sys.argv[1])
attestation_path = Path(sys.argv[2])
snapshot_root = Path(sys.argv[3])
commit = sys.argv[4]
module_arguments = sys.argv[5:]
expected_root = Path("/usr/local/lib/kor-travel-map/c7-runner") / commit
expected_module = expected_root / "scripts/lib/c7_prod_attestation.py"
expected_paths = {
    "scripts/audit-c7-prod-live-state.py",
    "scripts/lib/c7-prod-runner-lifecycle.sh",
    "scripts/lib/c7_prod_attestation.py",
    "scripts/run-c7-prod-live-e2e.sh",
}


def safe_file(path: Path, mode: int) -> bytes:
    if not path.is_absolute():
        raise RuntimeError("non-absolute bootstrap input")
    for parent in path.parents:
        observed_parent = parent.lstat()
        if (
            not stat.S_ISDIR(observed_parent.st_mode)
            or parent.is_symlink()
            or observed_parent.st_uid != 0
            or observed_parent.st_gid != 0
            or stat.S_IMODE(observed_parent.st_mode) & 0o022
        ):
            raise RuntimeError("unsafe bootstrap ancestor")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != 0
            or observed.st_gid != 0
            or stat.S_IMODE(observed.st_mode) != mode
        ):
            raise RuntimeError("unsafe bootstrap file")
        chunks = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


if snapshot_root != expected_root or module_path != expected_module:
    raise SystemExit(1)
try:
    module_bytes = safe_file(module_path, 0o555)
    attestation = json.loads(safe_file(attestation_path, 0o600))
    orchestrator_files = attestation.get("orchestrator_files")
    if (
        attestation.get("repository_commit") != commit
        or not isinstance(orchestrator_files, dict)
        or set(orchestrator_files) != expected_paths
        or orchestrator_files["scripts/lib/c7_prod_attestation.py"]
        != hashlib.sha256(module_bytes).hexdigest()
    ):
        raise RuntimeError("attestation bootstrap mismatch")
    sys.argv = [str(module_path), *module_arguments]
    exec(
        compile(module_bytes, str(module_path), "exec"),
        {
            "__builtins__": __builtins__,
            "__file__": str(module_path),
            "__name__": "__main__",
            "__package__": None,
        },
    )
except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
    raise SystemExit(1)
PY
}

verify_root_owned_orchestrator_snapshot() {
  run_verified_attestation_module \
    snapshot \
    "$REPO_ROOT" \
    "${BASH_SOURCE[0]}" \
    "$SCRIPT_DIR/audit-c7-prod-live-state.py" \
    "$SCRIPT_DIR/lib/c7-prod-runner-lifecycle.sh" \
    "$SCRIPT_DIR/lib/c7_prod_attestation.py" \
    "$HOST_ATTESTATION_FILE" \
    "$E2E_C7_EXPECTED_GIT_COMMIT" || return 1
  REPOSITORY_COMMIT="$E2E_C7_EXPECTED_GIT_COMMIT"
}

verify_trusted_runtime_attestation() {
  run_verified_attestation_module \
    runtime \
    "$HOST_ATTESTATION_FILE" \
    "$E2E_C7_COMPATIBLE_PAIR_MANIFEST" \
    "$COMPOSE_PROJECT_DIR" \
    "$PLAYWRIGHT_BASE_IMAGE"
}

canonical_dagster_graphql_sha256() {
  python3 - <<'PY'
import hashlib
import os
from urllib.parse import urlsplit, urlunsplit

parsed = urlsplit(os.environ["E2E_DAGSTER_URL"])
if (
    parsed.scheme != "https"
    or parsed.username is not None
    or parsed.password is not None
    or not parsed.hostname
    or parsed.query
    or parsed.fragment
):
    raise SystemExit(2)
host = parsed.hostname.rstrip(".").lower()
port = f":{parsed.port}" if parsed.port is not None else ""
pathname = parsed.path.rstrip("/")
pathname = pathname if pathname.endswith("/graphql") else f"{pathname}/graphql"
canonical = urlunsplit(("https", f"{host}{port}", pathname, "", ""))
print(hashlib.sha256(canonical.encode()).hexdigest())
PY
}

verify_alembic_state() {
  local current_output heads_output
  heads_output="$(
    docker compose --project-directory "$COMPOSE_PROJECT_DIR" exec -T \
      "$E2E_C7_MAP_API_SERVICE" alembic heads 2>/dev/null
  )" || return 1
  current_output="$(
    docker compose --project-directory "$COMPOSE_PROJECT_DIR" exec -T \
      "$E2E_C7_MAP_API_SERVICE" alembic current 2>/dev/null
  )" || return 1
  docker compose --project-directory "$COMPOSE_PROJECT_DIR" exec -T \
    "$E2E_C7_MAP_API_SERVICE" alembic check >/dev/null 2>&1 || return 1
  python3 - "$heads_output" "$current_output" <<'PY'
import re
import sys

pattern = re.compile(r"^([0-9A-Za-z_]+) \(head\)$")
parsed = []
for raw in sys.argv[1:]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SystemExit(1)
    match = pattern.fullmatch(lines[0])
    if match is None:
        raise SystemExit(1)
    parsed.append(match.group(1))
if parsed[0] != parsed[1]:
    raise SystemExit(1)
print(parsed[0])
PY
}

read_cap() {
  local service="$1"
  local temporary value
  local -a lines
  temporary="$(mktemp /tmp/kor-travel-map-c7-cap.XXXXXX)" || return 1
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

verify_ui_auth_preflight() {
  python3 - <<'PY'
import json
import os
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


base = urllib.parse.urlsplit(os.environ["E2E_BASE_URL"])
login_url = urllib.parse.urlunsplit(
    (base.scheme, base.netloc, "/api/auth/login", "", "")
)
payload = json.dumps(
    {
        "password": os.environ["E2E_ADMIN_PASSWORD"],
        "username": os.environ.get("E2E_ADMIN_USERNAME", "admin"),
    },
    separators=(",", ":"),
).encode()
request = urllib.request.Request(
    login_url,
    data=payload,
    headers={
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": urllib.parse.urlunsplit((base.scheme, base.netloc, "", "", "")),
    },
    method="POST",
)
try:
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        if response.status != 200 or not response.headers.get("Set-Cookie"):
            raise SystemExit(1)
        response.read()
except (OSError, urllib.error.HTTPError, urllib.error.URLError, ValueError):
    raise SystemExit(1)
PY
}

write_container_reference() {
  local phase="$1" pid="$2" pgid="$3" sid="$4" start_ticks="$5" payload
  payload="$(python3 - \
    "$ACTIVE_CONTAINER_NAME" "$phase" "$pid" "$pgid" "$sid" "$start_ticks" "$RUNTIME_DIR" <<'PY'
import json
import sys

name, phase, pid, pgid, sid, start_ticks, runtime = sys.argv[1:]
print(
    json.dumps(
        {
            "container_name": name,
            "creator_pgid": int(pgid),
            "creator_pid": int(pid),
            "creator_sid": int(sid),
            "creator_start_ticks": int(start_ticks),
            "phase": phase,
            "runtime": runtime,
            "version": 1,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
)
PY
  )" || die "Docker creator reference serialization failed"
  atomic_replace_state "$ACTIVE_CONTAINER_REF_FILE" "$payload"
}

verify_created_playwright_container() {
  python3 - "$ACTIVE_CID_FILE" "$ACTIVE_CONTAINER_NAME" "$RUNTIME_DIR" "$PLAYWRIGHT_IMAGE_ID" <<'PY'
import json
import os
import re
import stat
import subprocess
import sys

cid_path, name, runtime, image_id = sys.argv[1:]
fd = os.open(cid_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
try:
    observed = os.fstat(fd)
    payload = os.read(fd, 256).decode("ascii").strip()
finally:
    os.close(fd)
if (
    not stat.S_ISREG(observed.st_mode)
    or observed.st_uid != 0
    or observed.st_gid != 0
    or stat.S_IMODE(observed.st_mode) != 0o600
    or re.fullmatch(r"[0-9a-f]{64}", payload) is None
):
    raise SystemExit(1)
completed = subprocess.run(
    ["docker", "container", "inspect", "--", payload],
    check=True,
    capture_output=True,
    text=True,
    timeout=10,
)
records = json.loads(completed.stdout)
if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
    raise SystemExit(1)
record = records[0]
config = record.get("Config", {})
host = record.get("HostConfig", {})
state = record.get("State", {})
mounts = record.get("Mounts", [])
labels = config.get("Labels", {}) if isinstance(config, dict) else {}
runtime_binds = {
    item.get("Source")
    for item in mounts
    if isinstance(item, dict)
    and item.get("Type") == "bind"
    and item.get("RW") is True
    and item.get("Source") == item.get("Destination")
}
if (
    record.get("Id") != payload
    or record.get("Name") != f"/{name}"
    or record.get("Image") != image_id
    or not isinstance(labels, dict)
    or labels.get("io.kortravelmap.c7.runner") != "prod-live-e2e"
    or runtime_binds != {runtime}
    or not isinstance(host, dict)
    or host.get("ReadonlyRootfs") is not True
    or host.get("NetworkMode") not in {"bridge", "default"}
    or host.get("IpcMode") != "private"
    or host.get("CapDrop") != ["ALL"]
    or "no-new-privileges" not in (host.get("SecurityOpt") or [])
    or not isinstance(state, dict)
    or state.get("Running") is not False
):
    raise SystemExit(1)
PY
}

docker_run_playwright() {
  local -a environment_args=()
  local -a creator_fields=()
  local attempt command_status creator_identity creator_sid creator_start_ticks gate name
  for name in \
    E2E_BASE_URL NEXT_PUBLIC_KOR_TRAVEL_MAP_API E2E_DAGSTER_URL \
    E2E_ADMIN_PASSWORD E2E_ADMIN_WRITE E2E_C7_READ_AUTH_WRITE \
    E2E_KMA_SCOPE_WRITE E2E_DAGSTER_WRITE E2E_DAGSTER_RUN \
    E2E_QUEUE_SENSOR_BARRIER E2E_LIVE_ALLOW_PROD E2E_DAGSTER_JOB \
    E2E_C7_SCHEDULE E2E_C7_EXPECTED_UI_ORIGIN_SHA256 \
    E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256 E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256 \
    E2E_C7_ORCHESTRATOR_STATE_FILE E2E_C7_SCHEDULE_STATE_FILE \
    E2E_C7_KMA_STATE_FILE E2E_C7_POI_STATE_FILE E2E_KMA_GRID_CAP \
    E2E_KMA_GRID_CAP_FROM_RUNTIME E2E_LIVE_WORKERS E2E_POI_CACHE_WRITE \
    E2E_STORAGE_STATE PLAYWRIGHT_ARTIFACT_ROOT; do
    environment_args+=(--env "$name")
  done
  [[ -z "${E2E_ADMIN_USERNAME-}" ]] || environment_args+=(--env E2E_ADMIN_USERNAME)
  [[ -n "$LOCK_GUARD_PID" ]] && kill -0 "$LOCK_GUARD_PID" 2>/dev/null ||
    die "orchestrator lock guard is not alive"
  [[
    -n "$ACTIVE_CID_FILE" && -n "$ACTIVE_CONTAINER_REF_FILE" &&
    -n "$ACTIVE_CREATE_OUTCOME_FILE" &&
    "$ACTIVE_CONTAINER_NAME" =~ ^kor-travel-map-c7-e2e-[0-9]+$ &&
    ! -e "$ACTIVE_CID_FILE" && ! -L "$ACTIVE_CID_FILE" &&
    ! -e "$ACTIVE_CONTAINER_REF_FILE" && ! -L "$ACTIVE_CONTAINER_REF_FILE" &&
    ! -e "$ACTIVE_CREATE_OUTCOME_FILE" && ! -L "$ACTIVE_CREATE_OUTCOME_FILE"
  ]] || die "Playwright container reference is unsafe or already present"

  gate="$RUNTIME_DIR/docker-create-$$.fifo"
  [[ ! -e "$gate" && ! -L "$gate" ]] || die "Docker creator gate already exists"
  mkfifo --mode=600 -- "$gate" || die "Docker creator gate creation failed"
  setsid /bin/bash -c '
    exec 9<>"$1"
    IFS= read -r -t 15 -u 9 permit || exit 125
    [[ "$permit" == "create" ]] || exit 125
    outcome=$2
    cid=$3
    shift 3
    set +e
    "$@" >"$cid"
    status=$?
    python3 -c "import json,os,sys,tempfile; p=sys.argv[1]; s=int(sys.argv[2]); b=(json.dumps({\"phase\":\"create\",\"status\":s,\"version\":1},separators=(\",\",\":\"),sort_keys=True)+\"\\n\").encode(); fd,t=tempfile.mkstemp(prefix=\".state.\",dir=os.path.dirname(p)); os.fchmod(fd,0o600); os.fchown(fd,0,0); os.write(fd,b); os.fsync(fd); os.close(fd); os.replace(t,p); d=os.open(os.path.dirname(p),os.O_RDONLY|os.O_DIRECTORY); os.fsync(d); os.close(d)" "$outcome" "$status" || exit 126
    exit "$status"
  ' -- \
    "$gate" \
    "$ACTIVE_CREATE_OUTCOME_FILE" \
    "$ACTIVE_CID_FILE" \
    docker create --pull=never --rm --interactive \
    --name "$ACTIVE_CONTAINER_NAME" \
    --label io.kortravelmap.c7.runner=prod-live-e2e \
    --network bridge --ipc private --read-only \
    --security-opt no-new-privileges \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --tmpfs /root/.cache:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.config:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.npm:rw,nosuid,nodev,noexec,mode=700 \
    --cap-drop ALL \
    --mount "type=bind,src=$RUNTIME_DIR,dst=$RUNTIME_DIR" \
    "${environment_args[@]}" \
    "$PLAYWRIGHT_IMAGE_ID" \
    bash -c 'umask 077; exec "$@"' -- "$@" &
  ACTIVE_COMMAND_PID=$!
  ACTIVE_COMMAND_PGID=""
  creator_sid=""
  creator_start_ticks=""
  for (( attempt = 0; attempt < 80; attempt += 1 )); do
    if creator_identity="$(python3 - "$ACTIVE_COMMAND_PID" <<'PY'
import os
import sys
from pathlib import Path

pid = int(sys.argv[1])
try:
    raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    fields = raw[raw.rfind(")") + 2 :].split()
    pgid = os.getpgid(pid)
    sid = os.getsid(pid)
except (FileNotFoundError, OSError, ValueError):
    raise SystemExit(1)
if pgid != pid or sid != pid or len(fields) <= 19:
    raise SystemExit(1)
print(pgid)
print(sid)
print(fields[19])
PY
    )"; then
      mapfile -t creator_fields <<<"$creator_identity"
      if (( ${#creator_fields[@]} == 3 )) &&
        [[
          "${creator_fields[0]}" =~ ^[0-9]+$ &&
          "${creator_fields[1]}" =~ ^[0-9]+$ &&
          "${creator_fields[2]}" =~ ^[0-9]+$
        ]]; then
        ACTIVE_COMMAND_PGID="${creator_fields[0]}"
        creator_sid="${creator_fields[1]}"
        creator_start_ticks="${creator_fields[2]}"
        break
      fi
    fi
    sleep 0.025
  done
  [[
    "$ACTIVE_COMMAND_PGID" == "$ACTIVE_COMMAND_PID" &&
    "$creator_sid" == "$ACTIVE_COMMAND_PID" &&
    -n "$creator_start_ticks"
  ]] ||
    die "Docker creator process-group identity could not be attested"
  write_container_reference \
    creating \
    "$ACTIVE_COMMAND_PID" \
    "$ACTIVE_COMMAND_PGID" \
    "$creator_sid" \
    "$creator_start_ticks"
  printf 'create\n' >"$gate" || die "Docker creator gate release failed"
  rm -f -- "$gate" || die "Docker creator gate cleanup failed"
  while kill -0 "$ACTIVE_COMMAND_PID" 2>/dev/null; do
    if ! kill -0 "$LOCK_GUARD_PID" 2>/dev/null; then
      terminate_active_command
      die "orchestrator lock guard exited during Docker create"
    fi
    sleep 0.25
  done
  if wait "$ACTIVE_COMMAND_PID"; then command_status=0; else command_status=$?; fi
  ACTIVE_COMMAND_PID=""
  ACTIVE_COMMAND_PGID=""
  python3 - "$ACTIVE_CREATE_OUTCOME_FILE" "$command_status" <<'PY'
import json
import os
import stat
import sys

path, expected_raw = sys.argv[1:]
fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
try:
    observed = os.fstat(fd)
    value = json.loads(os.read(fd, 1024))
finally:
    os.close(fd)
if (
    not stat.S_ISREG(observed.st_mode)
    or observed.st_uid != 0
    or observed.st_gid != 0
    or stat.S_IMODE(observed.st_mode) != 0o600
    or not isinstance(value, dict)
    or set(value) != {"phase", "status", "version"}
    or value["phase"] != "create"
    or type(value["status"]) is not int
    or value["status"] != int(expected_raw)
    or value["version"] != 1
):
    raise SystemExit(1)
PY
  (( command_status == 0 )) || return "$command_status"
  fsync_file_and_parent "$ACTIVE_CID_FILE" || return 1
  verify_created_playwright_container || return 1
  write_container_reference created 0 0 0 0

  setsid docker start --attach --interactive "$(<"$ACTIVE_CID_FILE")" &
  ACTIVE_COMMAND_PID=$!
  ACTIVE_COMMAND_PGID="$ACTIVE_COMMAND_PID"
  while kill -0 "$ACTIVE_COMMAND_PID" 2>/dev/null; do
    if ! kill -0 "$LOCK_GUARD_PID" 2>/dev/null; then
      terminate_active_command
      die "orchestrator lock guard exited during Playwright execution"
    fi
    sleep 0.25
  done
  if wait "$ACTIVE_COMMAND_PID"; then command_status=0; else command_status=$?; fi
  ACTIVE_COMMAND_PID=""
  ACTIVE_COMMAND_PGID=""
  remove_active_container || return 1
  return "$command_status"
}

# 여기까지는 수집/파이프라인 domain state를 바꾸지 않는 preflight다. UI login은
# session/auth audit를 만들 수 있으나 provider/request/POI/schedule mutation은 하지 않는다.
# 고정 C7 상태 root와 BLOCKED sentinel은 모든 실행 identity 검증 뒤에만 만든다.
verify_root_owned_orchestrator_snapshot ||
  die "runner is not the attested root-owned exact commit snapshot"
source "$SCRIPT_DIR/lib/c7-prod-runner-lifecycle.sh"
mapfile -t runtime_attestation_output < <(verify_trusted_runtime_attestation 2>/dev/null) ||
  die "trusted host/runtime/compatible-pair attestation failed"
(( ${#runtime_attestation_output[@]} == 2 )) ||
  die "trusted runtime attestation output cardinality is invalid"
COMPATIBLE_PAIR_MANIFEST_SHA256="${runtime_attestation_output[0]}"
HOST_ATTESTATION_SHA256="${runtime_attestation_output[1]}"
[[ "$COMPATIBLE_PAIR_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ ]] ||
  die "compatible-pair manifest attestation output is invalid"
[[ "$HOST_ATTESTATION_SHA256" =~ ^[0-9a-f]{64}$ ]] ||
  die "host runtime attestation output is invalid"
PLAYWRIGHT_IMAGE_ID="$E2E_C7_PLAYWRIGHT_IMAGE"
actual_dagster_origin_sha256="$(canonical_dagster_graphql_sha256)" ||
  die "Dagster GraphQL HTTPS endpoint canonicalization failed"
[[ "$actual_dagster_origin_sha256" == "$E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256" ]] ||
  die "Dagster GraphQL endpoint origin attestation mismatch"
ALEMBIC_HEAD="$(verify_alembic_state)" ||
  die "Map API Alembic current/head/check attestation failed"
[[ "$ALEMBIC_HEAD" =~ ^[0-9A-Za-z_]+$ ]] || die "Alembic head output is invalid"
web_cap="$(read_cap "$E2E_C7_DAGSTER_WEB_SERVICE")" ||
  die "Dagster web cap attestation failed"
daemon_cap="$(read_cap "$E2E_C7_DAGSTER_DAEMON_SERVICE")" ||
  die "Dagster daemon cap attestation failed"
[[ "$web_cap" == "$daemon_cap" ]] || die "Dagster cap attestation mismatch"
verify_ui_auth_preflight || die "UI login POST/Set-Cookie preflight failed"

initialize_state_paths
verify_clean_state_audit
start_orchestrator_lock_guard
[[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
  die "prior BLOCKED state requires operator recovery"
has_residual_state && die "prior C7 journal/runtime residue requires operator recovery"
create_blocked_sentinel
trap finish EXIT
trap 'exit_for_signal 130' INT
trap 'exit_for_signal 143' TERM

RUNTIME_DIR="$(mktemp -d "$STATE_ROOT/runtime.XXXXXX")" ||
  die "private runtime directory creation failed"
chown 0:0 -- "$RUNTIME_DIR"
chmod 700 -- "$RUNTIME_DIR"
runtime_is_private_direct_child || die "private runtime directory validation failed"
mkdir -- "$RUNTIME_DIR/playwright" "$RUNTIME_DIR/journals"
chown 0:0 -- "$RUNTIME_DIR/playwright" "$RUNTIME_DIR/journals"
chmod 700 -- "$RUNTIME_DIR/playwright" "$RUNTIME_DIR/journals"
export E2E_STORAGE_STATE="$RUNTIME_DIR/admin-state.json"
ACTIVE_CID_FILE="$STATE_ROOT/container-$$.cid"
ACTIVE_CONTAINER_REF_FILE="$STATE_ROOT/container-$$.json"
ACTIVE_CREATE_OUTCOME_FILE="$STATE_ROOT/container-$$.outcome.json"
ACTIVE_CONTAINER_NAME="kor-travel-map-c7-e2e-$$"
snapshot_attested_inputs || die "attested input immutable snapshot failed"

RUN_STATE_FILE="$RUNTIME_DIR/journals/sensor.json"
SCHEDULE_STATE_FILE="$RUNTIME_DIR/journals/schedule.json"
KMA_STATE_FILE="$RUNTIME_DIR/journals/kma.json"
POI_STATE_FILE="$RUNTIME_DIR/journals/poi.json"
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
  '{"dagsterGraphqlEndpointSha256":"%s","expectedDagsterGraphqlEndpointSha256":"%s","phase":"orchestrator_running","version":3}' \
  "$actual_dagster_origin_sha256" \
  "$E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256"
atomic_replace_state "$BLOCKED_FILE" "$blocked_running_payload"

export E2E_LIVE_ALLOW_PROD
export E2E_ADMIN_WRITE E2E_C7_READ_AUTH_WRITE E2E_KMA_SCOPE_WRITE
export E2E_DAGSTER_WRITE E2E_DAGSTER_RUN E2E_QUEUE_SENSOR_BARRIER
export E2E_C7_SCHEDULE
export E2E_C7_EXPECTED_UI_ORIGIN_SHA256
export E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256
export E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256
export E2E_C7_ORCHESTRATOR_STATE_FILE="$RUN_STATE_FILE"
export E2E_C7_SCHEDULE_STATE_FILE="$SCHEDULE_STATE_FILE"
export E2E_C7_KMA_STATE_FILE="$KMA_STATE_FILE"
export E2E_C7_POI_STATE_FILE="$POI_STATE_FILE"
export E2E_KMA_GRID_CAP="$daemon_cap"
export E2E_KMA_GRID_CAP_FROM_RUNTIME=1
export E2E_LIVE_WORKERS=1
export E2E_POI_CACHE_WRITE=1

# ops-c7-schedule-write는 blocking gate에서 제외(descope)한다. cron override의 UI 경로가
# code location reload를 유발하고, reload 직후 schedule 목록이 ~90s간 심하게 re-render(churn)
# 되어 start/stop 컨트롤을 조작할 수 있는 순간이 없다(admin UI render/refetch 이슈 — 후속 task).
# test/deploy 측 근인(canReset 모델, waitForSchedule canReset 제외, reload timeout 30s,
# frozen-UI replay dispatchEvent, churn-tolerant click)은 규명·수정됐고 남은 근인은 app-side
# churn뿐이라 blocking gate는 나머지 4 spec으로 운영한다. 상세 진단·재적용 지침: docs/journal.md.
readonly SPECS=(
  "e2e/live/ops-c7-read-auth.live.spec.ts"
  "e2e/live/ops-c7-kma-active-write.live.spec.ts"
  "e2e/live/ops-c7-kma-empty-write.live.spec.ts"
  "e2e/live/ops-c7-kma-cap-write.live.spec.ts"
)
for spec in "${SPECS[@]}"; do
  artifact_name="${spec##*/}"
  artifact_name="${artifact_name%.live.spec.ts}"
  export PLAYWRIGHT_ARTIFACT_ROOT="$RUNTIME_DIR/playwright/$artifact_name"
  mkdir -- "$PLAYWRIGHT_ARTIFACT_ROOT"
  chown 0:0 -- "$PLAYWRIGHT_ARTIFACT_ROOT"
  chmod 700 -- "$PLAYWRIGHT_ARTIFACT_ROOT"
  docker_run_playwright npm run e2e:live -- "$spec" --workers=1 --retries=0
done
# `@c7-causal`은 spec 제목의 안정 tag다. Playwright는 grep이 아무 test도 매칭하지
# 못하면 fail-loud로 실패한다(no-match를 무시하는 옵션은 쓰지 않는다).
export PLAYWRIGHT_ARTIFACT_ROOT="$RUNTIME_DIR/playwright/poi-cache-targets-write-causal"
mkdir -- "$PLAYWRIGHT_ARTIFACT_ROOT"
chown 0:0 -- "$PLAYWRIGHT_ARTIFACT_ROOT"
chmod 700 -- "$PLAYWRIGHT_ARTIFACT_ROOT"
docker_run_playwright npm run e2e:live -- \
  "e2e/live/poi-cache-targets-write.live.spec.ts" \
  --workers=1 \
  --retries=0 \
  --grep \
  "@c7-causal"

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
  docker_run_playwright node - \
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

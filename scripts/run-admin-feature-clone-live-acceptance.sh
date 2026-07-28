#!/usr/bin/env bash

# T-VN-48D 전용 격리 실데이터 clone Live 인수 runner.
set +x
set -euo pipefail
umask 077

readonly INSTALL_BASE="/usr/local/lib/kor-travel-map/admin-feature-clone-live-acceptance"
readonly STATE_ROOT="/var/lib/kor-travel-map/admin-feature-clone-live-acceptance"
readonly BLOCKED_FILE="$STATE_ROOT/BLOCKED.json"
readonly LOCK_FILE="$STATE_ROOT/orchestrator.lock"
readonly MODE="${1-run}"
readonly SOURCE_COMMIT="${E2E_SOURCE_COMMIT-}"
readonly REPOSITORY_ROOT="${E2E_REPOSITORY_ROOT-}"
readonly DB_CONTAINER="${E2E_CLONE_DB_CONTAINER-}"
readonly DB_HOST_PORT="${E2E_CLONE_DB_PORT-}"
readonly API_PORT="${E2E_CLONE_API_PORT:-18701}"
readonly UI_PORT="${E2E_CLONE_UI_PORT:-18705}"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

die() {
  printf 'admin feature clone live acceptance failed: %s (values redacted)\n' "$1" >&2
  exit 1
}

require_command() {
  command -v -- "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

require_env() {
  local name="$1"
  [[ -n "${!name-}" ]] || die "required env is missing: $name"
}

git_repo() {
  git -c "safe.directory=$REPOSITORY_ROOT" -C "$REPOSITORY_ROOT" "$@"
}

safe_remove_runtime() {
  local path="$1"
  [[ "$path" == /tmp/ktm-admin-feature-clone-live.* && -d "$path" && ! -L "$path" ]] ||
    die "runtime cleanup target is unsafe"
  rm -rf -- "$path"
}

install_snapshot() {
  (( EUID == 0 )) || die "trusted snapshot bootstrap requires root"
  [[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "source commit is invalid"
  [[ -d "$REPOSITORY_ROOT/.git" || -f "$REPOSITORY_ROOT/.git" ]] ||
    die "repository root is invalid"
  [[ "$(git_repo rev-parse HEAD)" == "$SOURCE_COMMIT" ]] ||
    die "repository HEAD differs from source commit"
  [[ -z "$(git_repo status --porcelain)" ]] ||
    die "repository worktree is not clean"

  local expected_root="$INSTALL_BASE/$SOURCE_COMMIT"
  if [[ ! -e "$expected_root" ]]; then
    local temporary stage
    temporary="$(mktemp -d /tmp/ktm-admin-feature-clone-live.XXXXXX)"
    stage="$temporary/snapshot"
    mkdir -p -- "$stage"
    git_repo archive "$SOURCE_COMMIT" -- \
      scripts/admin_feature_clone_live_state.py \
      scripts/admin_feature_live_fixture.py \
      scripts/run-admin-feature-clone-live-acceptance.sh |
      tar -x -C "$temporary"
    install -o root -g root -m 0555 \
      "$temporary/scripts/run-admin-feature-clone-live-acceptance.sh" \
      "$stage/run-admin-feature-clone-live-acceptance.sh"
    install -o root -g root -m 0444 \
      "$temporary/scripts/admin_feature_clone_live_state.py" \
      "$stage/admin_feature_clone_live_state.py"
    install -o root -g root -m 0444 \
      "$temporary/scripts/admin_feature_live_fixture.py" \
      "$stage/admin_feature_live_fixture.py"
    python3 -I -B - "$stage" "$SOURCE_COMMIT" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
commit = sys.argv[2]
files = {}
for name in (
    "admin_feature_clone_live_state.py",
    "admin_feature_live_fixture.py",
    "run-admin-feature-clone-live-acceptance.sh",
):
    files[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
payload = {"files": files, "repository_commit": commit, "version": 1}
path = root / "source-manifest.json"
descriptor = os.open(
    path,
    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
    0o444,
)
try:
    view = memoryview(
        (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    )
    while view:
        written = os.write(descriptor, view)
        view = view[written:]
    os.fchmod(descriptor, 0o444)
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY
    chown root:root -- "$stage"
    chmod 0555 -- "$stage"
    mkdir -p -- "$INSTALL_BASE"
    chown root:root -- "$INSTALL_BASE"
    chmod 0555 -- "$INSTALL_BASE"
    mv -- "$stage" "$expected_root"
    safe_remove_runtime "$temporary"
  fi
  exec "$expected_root/run-admin-feature-clone-live-acceptance.sh" "$MODE"
}

validate_snapshot() {
  local snapshot_commit="${1:-$SOURCE_COMMIT}"
  local snapshot_root="${2:-$SCRIPT_DIR}"
  local expected_root="$INSTALL_BASE/$snapshot_commit"
  python3 -I -B - "$snapshot_root" "$expected_root" "$snapshot_commit" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

root = Path(sys.argv[1])
expected = Path(sys.argv[2])
commit = sys.argv[3]
if root != expected or root.resolve() != expected:
    raise SystemExit("snapshot root mismatch")
if root.is_symlink() or not root.is_dir():
    raise SystemExit("snapshot root is unsafe")
if stat.S_IMODE(root.stat().st_mode) != 0o555 or root.stat().st_uid != 0:
    raise SystemExit("snapshot root metadata is unsafe")
expected_files = {
    "admin_feature_clone_live_state.py": 0o444,
    "admin_feature_live_fixture.py": 0o444,
    "run-admin-feature-clone-live-acceptance.sh": 0o555,
    "source-manifest.json": 0o444,
}
if {item.name for item in root.iterdir()} != set(expected_files):
    raise SystemExit("snapshot exact file set mismatch")
for name, mode in expected_files.items():
    path = root / name
    metadata = path.stat()
    if path.is_symlink() or not path.is_file():
        raise SystemExit("snapshot file is unsafe")
    if metadata.st_uid != 0 or metadata.st_gid != 0:
        raise SystemExit("snapshot ownership is unsafe")
    if stat.S_IMODE(metadata.st_mode) != mode:
        raise SystemExit("snapshot mode is unsafe")
manifest = json.loads((root / "source-manifest.json").read_text(encoding="utf-8"))
if manifest.get("version") != 1 or manifest.get("repository_commit") != commit:
    raise SystemExit("snapshot manifest identity mismatch")
files = manifest.get("files")
if not isinstance(files, dict) or set(files) != set(expected_files) - {"source-manifest.json"}:
    raise SystemExit("snapshot manifest file set mismatch")
for name, digest in files.items():
    actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
    if actual != digest:
        raise SystemExit("snapshot file digest mismatch")
for ancestor in (root.parent, root.parent.parent, root.parent.parent.parent):
    metadata = ancestor.stat()
    if ancestor.is_symlink() or metadata.st_uid != 0:
        raise SystemExit("snapshot ancestor ownership is unsafe")
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise SystemExit("snapshot ancestor is writable")
PY
}

if [[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] &&
  [[ "$SCRIPT_DIR" != "$INSTALL_BASE/$SOURCE_COMMIT" ]]; then
  install_snapshot
fi

[[ "$MODE" == "run" || "$MODE" == "recover" ]] ||
  die "usage: runner run|recover"
require_command docker
require_command flock
require_command git
require_command python3
require_command sha256sum
require_command tar
require_env E2E_SOURCE_COMMIT
require_env E2E_REPOSITORY_ROOT
require_env E2E_CLONE_DB_CONTAINER
require_env E2E_CLONE_DB_PORT
(( EUID == 0 )) || die "fixed clone evidence state requires root"
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "source commit is invalid"
[[ "$DB_CONTAINER" =~ ^ktm-[a-z0-9-]+-db$ ]] || die "clone DB container name is invalid"
[[ "$DB_HOST_PORT" =~ ^[0-9]+$ ]] || die "clone DB host port is invalid"
(( DB_HOST_PORT >= 1024 && DB_HOST_PORT <= 65535 && DB_HOST_PORT != 5432 )) ||
  die "clone DB host port is unsafe"
if [[ "$MODE" == "run" ]]; then
  require_command curl
  require_command openssl
  require_command ss
  require_env E2E_ADMIN_PASSWORD
  require_env E2E_VWORLD_API_KEY
  for port in "$API_PORT" "$UI_PORT"; do
    [[ "$port" =~ ^[0-9]+$ ]] || die "candidate port is invalid"
    (( port >= 1024 && port <= 65535 && port != 12701 && port != 12705 )) ||
      die "candidate port overlaps production/default"
  done
  [[ "$API_PORT" != "$UI_PORT" ]] || die "candidate ports overlap"
  [[ "$API_PORT" != "$DB_HOST_PORT" ]] || die "candidate ports overlap"
  [[ "$UI_PORT" != "$DB_HOST_PORT" ]] || die "candidate ports overlap"
  [[ "${E2E_ADMIN_PASSWORD}" != *$'\n'* && "${E2E_ADMIN_PASSWORD}" != *$'\r'* ]] ||
    die "admin password contains a newline"
  [[ "${E2E_VWORLD_API_KEY}" != *$'\n'* && "${E2E_VWORLD_API_KEY}" != *$'\r'* ]] ||
    die "VWorld key contains a newline"
fi
validate_snapshot
[[ "$(git_repo rev-parse HEAD)" == "$SOURCE_COMMIT" ]] ||
  die "repository HEAD differs from source commit"
[[ -z "$(git_repo status --porcelain)" ]] ||
  die "repository worktree is not clean"

if [[ -e "$STATE_ROOT" || -L "$STATE_ROOT" ]]; then
  [[ -d "$STATE_ROOT" && ! -L "$STATE_ROOT" ]] ||
    die "state root is unsafe"
else
  [[ "$MODE" == "run" ]] || die "recoverable state root is missing"
  mkdir -- "$STATE_ROOT"
  chown root:root -- "$STATE_ROOT"
  chmod 0700 -- "$STATE_ROOT"
fi
[[ "$(stat -c '%u:%g:%a' -- "$STATE_ROOT")" == "0:0:700" ]] ||
  die "state root metadata is unsafe"
if [[ -e "$LOCK_FILE" || -L "$LOCK_FILE" ]]; then
  [[ -f "$LOCK_FILE" && ! -L "$LOCK_FILE" ]] ||
    die "orchestrator lock is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$LOCK_FILE")" == "0:0:600" ]] ||
    die "orchestrator lock metadata is unsafe"
else
  install -o root -g root -m 0600 /dev/null "$LOCK_FILE"
fi
exec 9<>"$LOCK_FILE"
flock -n 9 || die "another clone acceptance runner owns the lock"
if [[ "$MODE" == "run" ]]; then
  [[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "prior BLOCKED state requires operator recovery"
  for port in "$API_PORT" "$UI_PORT"; do
    ! ss -ltnH | awk '{print $4}' | grep -Eq "(^|:)$port$" ||
      die "candidate port is already occupied"
  done
else
  [[ -f "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "recoverable BLOCKED state is missing"
  [[ "$(stat -c '%u:%g:%a' -- "$BLOCKED_FILE")" == "0:0:600" ]] ||
    die "BLOCKED state metadata is unsafe"
fi
docker container inspect "$DB_CONTAINER" >/dev/null 2>&1 ||
  die "clone DB container is missing"
[[ "$(docker inspect --format '{{.State.Running}}' "$DB_CONTAINER")" == "true" ]] ||
  die "clone DB container is not running"
db_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$DB_CONTAINER")"
[[ -z "$db_health" || "$db_health" == "healthy" ]] ||
  die "clone DB container is unhealthy"
[[ "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$DB_CONTAINER")" != "host" ]] ||
  die "clone DB cannot use host network"
clone_compose_project="$(
  docker inspect --format \
    '{{index .Config.Labels "com.docker.compose.project"}}' "$DB_CONTAINER"
)"
[[ "$clone_compose_project" != "kor-travel-docker-manager" ]] ||
  die "production compose DB is forbidden"
[[ "$(docker port "$DB_CONTAINER" 5432/tcp)" == "127.0.0.1:$DB_HOST_PORT" ]] ||
  die "clone DB loopback port binding mismatch"

db_user="postgres"
db_name=""
db_password=""
while IFS= read -r entry; do
  case "$entry" in
    POSTGRES_USER=*) db_user="${entry#POSTGRES_USER=}" ;;
    POSTGRES_DB=*) db_name="${entry#POSTGRES_DB=}" ;;
    POSTGRES_PASSWORD=*) db_password="${entry#POSTGRES_PASSWORD=}" ;;
  esac
done < <(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$DB_CONTAINER")
[[ "$db_user" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "clone DB user is invalid"
[[ "$db_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "clone DB name is invalid"
[[ -n "$db_password" && "$db_password" != *$'\n'* && "$db_password" != *$'\r'* ]] ||
  die "clone DB password is invalid"
db_dsn="$(
  python3 -I -B - "$db_user" "$db_password" "$DB_HOST_PORT" "$db_name" <<'PY'
import sys
from urllib.parse import quote

user, password, port, database = sys.argv[1:]
print(
    "postgresql+asyncpg://"
    f"{quote(user, safe='')}:{quote(password, safe='')}"
    f"@127.0.0.1:{port}/{quote(database, safe='')}"
)
PY
)"
export KOR_TRAVEL_MAP_PG_DSN="$db_dsn"

psql_value() {
  local query="$1"
  docker exec -e PGPASSWORD="$db_password" "$DB_CONTAINER" \
    psql -X -v ON_ERROR_STOP=1 -Atq -U "$db_user" -d "$db_name" -c "$query"
}

mapfile -t migration_heads < <(
  (
    cd -- "$REPOSITORY_ROOT"
    .venv/bin/alembic -c alembic.ini heads
  ) | awk '{print $1}'
)
(( ${#migration_heads[@]} == 1 )) || die "repository must have one Alembic head"
readonly EXPECTED_MIGRATION_HEAD="${migration_heads[0]}"
clone_migration_head="$(
  psql_value "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version"
)"
[[ "$clone_migration_head" == "$EXPECTED_MIGRATION_HEAD" ]] ||
  die "clone DB migration head differs from source"

readonly CLONE_CONTAINER_ID="$(docker inspect --format '{{.Id}}' "$DB_CONTAINER")"
readonly CLONE_CONTAINER_SHA256="$(printf '%s' "$CLONE_CONTAINER_ID" | sha256sum | awk '{print $1}')"
clone_system_identifier="$(psql_value "SELECT system_identifier::text FROM pg_control_system()")"
readonly CLONE_SYSTEM_SHA256="$(printf '%s' "$clone_system_identifier" | sha256sum | awk '{print $1}')"
unset clone_system_identifier
readonly CLONE_IDENTITY_SHA256="$(
  printf '%s\n%s\n%s\n%s\n' \
    "$CLONE_CONTAINER_SHA256" "$CLONE_SYSTEM_SHA256" "$DB_HOST_PORT" \
    "$EXPECTED_MIGRATION_HEAD" | sha256sum | awk '{print $1}'
)"

write_snapshot() {
  local path="$1"
  local run_id="$2"
  local migration_head relation_count feature_total feature_non_deleted
  local active_owned nonterminal_owned
  [[ "$run_id" =~ ^[a-z0-9][a-z0-9-]{15,79}$ ]] ||
    die "snapshot run ID is invalid"
  migration_head="$(psql_value "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version")"
  relation_count="$(psql_value "SELECT count(*) FROM pg_class WHERE relnamespace IN (SELECT oid FROM pg_namespace WHERE nspname IN ('feature','ops','provider_sync')) AND relkind IN ('r','p','v','m')")"
  feature_total="$(psql_value "SELECT count(*) FROM feature.features")"
  feature_non_deleted="$(psql_value "SELECT count(*) FROM feature.features WHERE status <> 'deleted'")"
  active_owned="$(psql_value "SELECT count(*) FROM feature.features WHERE feature_id LIKE 'e2e_live_acceptance::${run_id}::%' AND status <> 'deleted'")"
  nonterminal_owned="$(psql_value "SELECT count(*) FROM ops.feature_change_requests WHERE feature_id LIKE 'e2e_live_acceptance::${run_id}::%' AND state = 'pending'")"
  python3 -I -B "$SCRIPT_DIR/admin_feature_clone_live_state.py" write-snapshot \
    --path "$path" \
    --active-owned-features "$active_owned" \
    --clone-container-sha256 "$CLONE_CONTAINER_SHA256" \
    --clone-system-identifier-sha256 "$CLONE_SYSTEM_SHA256" \
    --feature-non-deleted "$feature_non_deleted" \
    --feature-total "$feature_total" \
    --host-port "$DB_HOST_PORT" \
    --migration-head "$migration_head" \
    --nonterminal-owned-change-requests "$nonterminal_owned" \
    --relation-count "$relation_count"
}

if [[ "$MODE" == "recover" ]]; then
  state_helper=(python3 -I -B "$SCRIPT_DIR/admin_feature_clone_live_state.py")
  blocked_source="$("${state_helper[@]}" read-blocked --path "$BLOCKED_FILE" --field source_commit)"
  blocked_run_id="$("${state_helper[@]}" read-blocked --path "$BLOCKED_FILE" --field run_id)"
  blocked_run_key="$("${state_helper[@]}" read-blocked --path "$BLOCKED_FILE" --field run_key)"
  blocked_clone_identity="$("${state_helper[@]}" read-blocked --path "$BLOCKED_FILE" --field clone_identity_sha256)"
  blocked_api_image="$("${state_helper[@]}" read-blocked --path "$BLOCKED_FILE" --field api_image_id)"
  blocked_ui_image="$("${state_helper[@]}" read-blocked --path "$BLOCKED_FILE" --field ui_image_id)"
  blocked_playwright_image="$("${state_helper[@]}" read-blocked --path "$BLOCKED_FILE" --field playwright_image_id)"
  [[ "$blocked_source" =~ ^[0-9a-f]{40}$ ]] ||
    die "BLOCKED source commit is invalid"
  [[ "$blocked_run_id" =~ ^[a-z0-9][a-z0-9-]{15,79}$ ]] ||
    die "BLOCKED run ID is invalid"
  [[ "$blocked_run_key" =~ ^[0-9a-f]{64}$ ]] ||
    die "BLOCKED run key is invalid"
  [[ "$blocked_clone_identity" == "$CLONE_IDENTITY_SHA256" ]] ||
    die "clone DB identity changed after failure"
  validate_snapshot "$blocked_source" "$INSTALL_BASE/$blocked_source"

  readonly RECOVERY_RUNTIME="$STATE_ROOT/run-$blocked_run_key"
  [[ -d "$RECOVERY_RUNTIME" && ! -L "$RECOVERY_RUNTIME" ]] ||
    die "BLOCKED runtime directory is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$RECOVERY_RUNTIME")" == "0:0:700" ]] ||
    die "BLOCKED runtime metadata is unsafe"
  [[ -z "$(
    docker ps -aq --no-trunc \
      --filter "label=io.kortravelmap.admin-feature-clone-acceptance.run-key=$blocked_run_key"
  )" ]] || die "BLOCKED execution still owns containers"

  for image in "$blocked_api_image" "$blocked_ui_image" "$blocked_playwright_image"; do
    docker image inspect "$image" >/dev/null 2>&1 ||
      die "BLOCKED execution image is missing"
  done
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
      "$blocked_api_image"
  )" == "$blocked_source" ]] || die "BLOCKED API image revision mismatch"
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
      "$blocked_ui_image"
  )" == "$blocked_source" ]] || die "BLOCKED UI image revision mismatch"
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "io.kortravelmap.c7.repository-commit"}}' \
      "$blocked_playwright_image"
  )" == "$blocked_source" ]] || die "BLOCKED Playwright image revision mismatch"

  "${state_helper[@]}" update-blocked \
    --path "$BLOCKED_FILE" --phase recovery-validating
  recovery_snapshot="$RECOVERY_RUNTIME/clone-recovery-current.json"
  write_snapshot "$recovery_snapshot" "$blocked_run_id"
  find "$RECOVERY_RUNTIME" -type d -exec chown root:root {} +
  find "$RECOVERY_RUNTIME" -type f -exec chown root:root {} +
  find "$RECOVERY_RUNTIME" -type d -exec chmod 0700 {} +
  find "$RECOVERY_RUNTIME" -type f -exec chmod 0600 {} +
  "${state_helper[@]}" complete \
    --blocked-path "$BLOCKED_FILE" \
    --phase recovered \
    --current-snapshot "$recovery_snapshot" \
    --recovery-tool-source-commit "$SOURCE_COMMIT" \
    --result-path "$RECOVERY_RUNTIME/result.json" \
    --runtime "$RECOVERY_RUNTIME"
  docker image rm --force \
    "$blocked_api_image" "$blocked_ui_image" "$blocked_playwright_image" >/dev/null
  printf 'admin feature clone live acceptance recovered: source=%s result=%s\n' \
    "$blocked_source" "$RECOVERY_RUNTIME/result.json"
  exit 0
fi

readonly RUN_ID="clone-$(date -u +%Y%m%d%H%M%S)-$(openssl rand -hex 6)"
readonly RUN_KEY="$(printf '%s' "$RUN_ID" | sha256sum | awk '{print $1}')"
readonly RUNTIME_DIR="$STATE_ROOT/run-$RUN_KEY"
mkdir -- "$RUNTIME_DIR"
chown root:root -- "$RUNTIME_DIR"
chmod 0700 -- "$RUNTIME_DIR"
readonly TEMPORARY="$(mktemp -d /tmp/ktm-admin-feature-clone-live.XXXXXX)"
readonly BUILD_CONTEXT="$TEMPORARY/build-context"
mkdir -- "$BUILD_CONTEXT"

API_CONTAINER=""
UI_CONTAINER=""
API_IMAGE_ID=""
UI_IMAGE_ID=""
PLAYWRIGHT_IMAGE_ID=""
API_IMAGE_TAG="kor-travel-map-clone-live-api:${SOURCE_COMMIT:0:12}-${RUN_KEY:0:12}"
UI_IMAGE_TAG="kor-travel-map-clone-live-ui:${SOURCE_COMMIT:0:12}-${RUN_KEY:0:12}"
PLAYWRIGHT_IMAGE_TAG="kor-travel-map-clone-live-playwright:${SOURCE_COMMIT:0:12}-${RUN_KEY:0:12}"
BLOCKED_WRITTEN=0
SEEDED=0
COMPLETE=0

remove_owned_containers() {
  local containers
  containers="$(
    docker ps -aq --no-trunc \
      --filter "label=io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY"
  )" || return 1
  if [[ -n "$containers" ]]; then
    docker container rm --force -- $containers >/dev/null 2>&1 || return 1
  fi
}

run_helper() {
  local action="$1"
  local output="$2"
  local name="ktm-afcla-${RUN_KEY:0:12}-helper-$action"
  docker run --rm \
    --name "$name" \
    --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
    --network host \
    --read-only \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --env KOR_TRAVEL_MAP_PG_DSN \
    --mount "type=bind,src=$SCRIPT_DIR/admin_feature_live_fixture.py,dst=/opt/admin-feature-live-fixture.py,readonly" \
    --entrypoint python \
    "$API_IMAGE_ID" \
    /opt/admin-feature-live-fixture.py "$action" --run-id "$RUN_ID" >"$output"
  chmod 0600 -- "$output"
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  set +e
  if (( SEEDED == 1 )); then
    run_helper cleanup "$RUNTIME_DIR/direct-cleanup-interrupted.json" >/dev/null 2>&1
    run_helper audit "$RUNTIME_DIR/direct-audit-interrupted.json" >/dev/null 2>&1
  fi
  remove_owned_containers
  if (( COMPLETE == 1 )); then
    docker image rm --force \
      "$API_IMAGE_ID" "$UI_IMAGE_ID" "$PLAYWRIGHT_IMAGE_ID" >/dev/null 2>&1
  fi
  safe_remove_runtime "$TEMPORARY"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

git_repo archive --format=tar "$SOURCE_COMMIT" |
  tar -x -C "$BUILD_CONTEXT"
captured_head="$(git_repo rev-parse HEAD)"
captured_status="$(git_repo status --porcelain)"
[[ "$captured_head" == "$SOURCE_COMMIT" && -z "$captured_status" ]] ||
  die "source changed while build context was captured"

docker build --pull=false \
  --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=$SOURCE_COMMIT" \
  --file "$BUILD_CONTEXT/docker/api.Dockerfile" \
  --tag "$API_IMAGE_TAG" \
  "$BUILD_CONTEXT"
API_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$API_IMAGE_TAG")"
api_image_revision="$(
  docker image inspect --format \
    '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$API_IMAGE_ID"
)"
[[ "$api_image_revision" == "$SOURCE_COMMIT" ]] ||
  die "API image source revision mismatch"

docker build --pull=false \
  --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=$SOURCE_COMMIT" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_API=http://127.0.0.1:$API_PORT" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=http://127.0.0.1:18702" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=http://127.0.0.1:12501" \
  --build-arg "NEXT_PUBLIC_VWORLD_API_KEY=$E2E_VWORLD_API_KEY" \
  --build-arg "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY=$E2E_VWORLD_API_KEY" \
  --file "$BUILD_CONTEXT/docker/frontend.Dockerfile" \
  --tag "$UI_IMAGE_TAG" \
  "$BUILD_CONTEXT"
UI_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$UI_IMAGE_TAG")"
ui_image_revision="$(
  docker image inspect --format \
    '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$UI_IMAGE_ID"
)"
[[ "$ui_image_revision" == "$SOURCE_COMMIT" ]] ||
  die "UI image source revision mismatch"

docker build --pull=false \
  --build-arg "C7_REPOSITORY_COMMIT=$SOURCE_COMMIT" \
  --file "$BUILD_CONTEXT/docker/c7-playwright.Dockerfile" \
  --tag "$PLAYWRIGHT_IMAGE_TAG" \
  "$BUILD_CONTEXT"
PLAYWRIGHT_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$PLAYWRIGHT_IMAGE_TAG")"
playwright_image_revision="$(
  docker image inspect --format \
    '{{index .Config.Labels "io.kortravelmap.c7.repository-commit"}}' \
    "$PLAYWRIGHT_IMAGE_ID"
)"
[[ "$playwright_image_revision" == "$SOURCE_COMMIT" ]] ||
  die "Playwright image source revision mismatch"

write_snapshot "$RUNTIME_DIR/clone-startup-before.json" "$RUN_ID"

admin_secret="$(printf '%s' "$RUN_ID:admin" | sha256sum | awk '{print $1}')"
service_token="$(printf '%s' "$RUN_ID:service" | sha256sum | awk '{print $1}')"
cursor_secret="$(printf '%s' "$RUN_ID:cursor" | sha256sum | awk '{print $1}')"
session_secret="$(printf '%s' "$RUN_ID:session" | sha256sum | awk '{print $1}')"
password_hash="$(
  python3 -I -B - "$E2E_ADMIN_PASSWORD" "$RUN_ID" <<'PY'
import base64
import hashlib
import sys

password, run_id = sys.argv[1:]
salt = hashlib.sha256(f"{run_id}:password-salt".encode()).digest()[:16]
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000, 32)
encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
print(f"pbkdf2_sha256$310000${encode(salt)}${encode(digest)}")
PY
)"
export KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET="$admin_secret"
export KOR_TRAVEL_MAP_API_SERVICE_TOKEN="$service_token"
export KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET="$cursor_secret"
export KOR_TRAVEL_MAP_API_VWORLD_API_KEY="$E2E_VWORLD_API_KEY"

API_CONTAINER="ktm-afcla-${RUN_KEY:0:12}-api"
docker run -d \
  --name "$API_CONTAINER" \
  --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
  --network host \
  --read-only \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
  --env KOR_TRAVEL_MAP_PG_DSN \
  --env KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET \
  --env KOR_TRAVEL_MAP_API_SERVICE_TOKEN \
  --env KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET \
  --env KOR_TRAVEL_MAP_API_VWORLD_API_KEY \
  --env KOR_TRAVEL_MAP_API_PROFILE=production \
  --env KOR_TRAVEL_MAP_API_HOST=127.0.0.1 \
  --env "KOR_TRAVEL_MAP_API_PORT=$API_PORT" \
  --env KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true \
  --env KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED=true \
  --env KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false \
  --env KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED=false \
  --env KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED=true \
  --env KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED=true \
  --env KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED=false \
  --env KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=false \
  --env 'KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS=["127.0.0.1/32"]' \
  --entrypoint python \
  "$API_IMAGE_ID" \
  -m uvicorn kortravelmap.api.app:app --host 127.0.0.1 --port "$API_PORT" \
  >/dev/null
for _ in $(seq 1 90); do
  if curl --fail --silent --show-error "http://127.0.0.1:$API_PORT/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error "http://127.0.0.1:$API_PORT/health" >/dev/null ||
  die "candidate API health check failed"
write_snapshot "$RUNTIME_DIR/clone-startup-after.json" "$RUN_ID"

UI_CONTAINER="ktm-afcla-${RUN_KEY:0:12}-ui"
export KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH="$password_hash"
export KOR_TRAVEL_MAP_UI_SESSION_SECRET="$session_secret"
docker run -d \
  --name "$UI_CONTAINER" \
  --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
  --network host \
  --read-only \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
  --env "PORT=$UI_PORT" \
  --env HOSTNAME=127.0.0.1 \
  --env "NEXT_PUBLIC_KOR_TRAVEL_MAP_API=http://127.0.0.1:$API_PORT" \
  --env "KOR_TRAVEL_MAP_API_INTERNAL_URL=http://127.0.0.1:$API_PORT" \
  --env KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET \
  --env KOR_TRAVEL_MAP_UI_ADMIN_USERNAME=admin \
  --env KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH \
  --env KOR_TRAVEL_MAP_UI_SESSION_SECRET \
  --env "KOR_TRAVEL_MAP_UI_PUBLIC_ORIGINS=http://127.0.0.1:$UI_PORT" \
  "$UI_IMAGE_ID" >/dev/null
for _ in $(seq 1 90); do
  if curl --fail --silent --show-error "http://127.0.0.1:$UI_PORT/login" >/dev/null; then
    break
  fi
  sleep 1
done
curl --fail --silent --show-error "http://127.0.0.1:$UI_PORT/login" >/dev/null ||
  die "candidate UI health check failed"
build_revision="$(
  curl --fail --silent --show-error "http://127.0.0.1:$UI_PORT/api/build-info" |
    python3 -I -B -c 'import json,sys; print(json.load(sys.stdin)["revision"])'
)"
[[ "$build_revision" == "$SOURCE_COMMIT" ]] || die "candidate UI build revision mismatch"

python3 -I -B "$SCRIPT_DIR/admin_feature_clone_live_state.py" write-blocked \
  --path "$BLOCKED_FILE" \
  --phase fixture-seed-pending \
  --run-id "$RUN_ID" \
  --run-key "$RUN_KEY" \
  --api-image-id "$API_IMAGE_ID" \
  --clone-identity-sha256 "$CLONE_IDENTITY_SHA256" \
  --playwright-image-id "$PLAYWRIGHT_IMAGE_ID" \
  --source-commit "$SOURCE_COMMIT" \
  --ui-image-id "$UI_IMAGE_ID"
BLOCKED_WRITTEN=1

run_helper seed "$RUNTIME_DIR/direct-seed.json"
SEEDED=1

run_executor() {
  local name="$1"
  local artifact_dir="$2"
  local recovery_only="$3"
  mkdir -- "$artifact_dir"
  chmod 0700 -- "$artifact_dir"
  local -a recovery_env=()
  [[ "$recovery_only" != "1" ]] ||
    recovery_env+=(--env E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY=1)
  docker run --rm \
    --name "$name" \
    --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
    --network host \
    --ipc private \
    --read-only \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --tmpfs /root/.cache:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.config:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.npm:rw,nosuid,nodev,noexec,mode=700 \
    --mount "type=bind,src=$artifact_dir,dst=/evidence" \
    --env "E2E_BASE_URL=http://127.0.0.1:$UI_PORT" \
    --env E2E_ADMIN_USERNAME=admin \
    --env E2E_ADMIN_PASSWORD \
    --env E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1 \
    --env "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID=$RUN_ID" \
    --env E2E_ISOLATED_LIVE_EVIDENCE=1 \
    --env E2E_LIVE_WORKERS=1 \
    --env PLAYWRIGHT_ARTIFACT_ROOT=/evidence \
    --env E2E_STORAGE_STATE=/tmp/admin-feature-clone-state.json \
    "${recovery_env[@]}" \
    "$PLAYWRIGHT_IMAGE_ID" \
    npm run e2e:live -- \
    e2e/live/admin-feature-acceptance-write.live.spec.ts \
    --workers=1 --retries=0
}

python3 -I -B "$SCRIPT_DIR/admin_feature_clone_live_state.py" update-blocked \
  --path "$BLOCKED_FILE" --phase browser-running
main_status=0
run_executor \
  "ktm-afcla-${RUN_KEY:0:12}-executor-main" \
  "$RUNTIME_DIR/playwright-main" 0 || main_status=$?
python3 -I -B "$SCRIPT_DIR/admin_feature_clone_live_state.py" update-blocked \
  --path "$BLOCKED_FILE" --phase browser-recovery-running
recovery_status=0
run_executor \
  "ktm-afcla-${RUN_KEY:0:12}-executor-recovery" \
  "$RUNTIME_DIR/playwright-recovery" 1 || recovery_status=$?

run_helper cleanup "$RUNTIME_DIR/direct-cleanup.json"
SEEDED=0
run_helper audit "$RUNTIME_DIR/direct-audit.json"
write_snapshot "$RUNTIME_DIR/clone-final.json" "$RUN_ID"
remove_owned_containers || die "owned container cleanup failed"
(( main_status == 0 && recovery_status == 0 )) || {
  python3 -I -B "$SCRIPT_DIR/admin_feature_clone_live_state.py" update-blocked \
    --path "$BLOCKED_FILE" --phase test-failed-restored
  die "Playwright acceptance failed after cleanup"
}

find "$RUNTIME_DIR" -type d -exec chown root:root {} +
find "$RUNTIME_DIR" -type f -exec chown root:root {} +
find "$RUNTIME_DIR" -type d -exec chmod 0700 {} +
find "$RUNTIME_DIR" -type f -exec chmod 0600 {} +
python3 -I -B "$SCRIPT_DIR/admin_feature_clone_live_state.py" complete \
  --blocked-path "$BLOCKED_FILE" \
  --phase passed \
  --result-path "$RUNTIME_DIR/result.json" \
  --runtime "$RUNTIME_DIR"
COMPLETE=1
BLOCKED_WRITTEN=0
printf 'admin feature clone live acceptance complete: source=%s result=%s\n' \
  "$SOURCE_COMMIT" "$RUNTIME_DIR/result.json"

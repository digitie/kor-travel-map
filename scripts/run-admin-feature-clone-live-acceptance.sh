#!/usr/bin/env bash

# T-VN-48D 전용 격리 실데이터 clone Live 인수 runner.
set +x
set -euo pipefail
umask 077
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
unset \
  ALL_PROXY BASH_ENV CDPATH DOCKER_CERT_PATH DOCKER_CONFIG DOCKER_CONTEXT \
  DOCKER_HOST DOCKER_TLS_VERIFY ENV GIT_CONFIG_COUNT GIT_CONFIG_GLOBAL \
  GIT_CONFIG_SYSTEM HTTPS_PROXY HTTP_PROXY NO_PROXY \
  all_proxy https_proxy http_proxy no_proxy

readonly INSTALL_BASE="/usr/local/lib/kor-travel-map/admin-feature-clone-live-acceptance"
readonly STATE_ROOT="/var/lib/kor-travel-map/admin-feature-clone-live-acceptance"
readonly BLOCKED_FILE="$STATE_ROOT/BLOCKED.json"
readonly CHECKPOINT_FILE="$STATE_ROOT/clone-checkpoint.json"
readonly LOCK_FILE="$STATE_ROOT/orchestrator.lock"
readonly BOOTSTRAP_LOCK_FILE="$INSTALL_BASE/bootstrap.lock"
readonly MODE="${1-run}"
readonly SOURCE_COMMIT="${E2E_SOURCE_COMMIT-}"
readonly DB_CONTAINER="${E2E_CLONE_DB_CONTAINER-}"
readonly DB_HOST_PORT="${E2E_CLONE_DB_PORT-}"
readonly API_PORT="${E2E_CLONE_API_PORT:-18701}"
readonly UI_PORT="${E2E_CLONE_UI_PORT:-18705}"
readonly LOOPBACK_UI_PORT=18706
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SOURCE_ARCHIVE="$SCRIPT_DIR/source.tar.gz"
readonly ARCHIVE_PREFIX="kor-travel-map-$SOURCE_COMMIT"
readonly ARCHIVE_URL="https://github.com/digitie/kor-travel-map/archive/$SOURCE_COMMIT.tar.gz"
LOOPBACK_PROXY_HELPER=""

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

safe_remove_temporary() {
  local path="$1"
  [[ "$path" == /tmp/ktm-admin-feature-clone-live.* && -d "$path" && ! -L "$path" ]] ||
    die "temporary cleanup target is unsafe"
  rm -rf -- "$path"
}

bootstrap_snapshot() {
  (( EUID != 0 )) || die "bootstrap must run without root"
  require_command curl
  require_command flock
  require_command openssl
  require_command sudo
  require_command tar
  [[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "source commit is invalid"

  local expected_root="$INSTALL_BASE/$SOURCE_COMMIT"
  sudo -n install -d -o root -g root -m 0555 "$INSTALL_BASE"
  sudo -n touch "$BOOTSTRAP_LOCK_FILE"
  sudo -n chown root:root "$BOOTSTRAP_LOCK_FILE"
  sudo -n chmod 0600 "$BOOTSTRAP_LOCK_FILE"
  [[ "$(sudo -n stat -c '%u:%g:%a' -- "$BOOTSTRAP_LOCK_FILE")" == "0:0:600" ]] ||
    die "bootstrap lock metadata is unsafe"

  # flock guardian이 stdin EOF까지 lock을 소유한다. 호출자가 SIGKILL되어도 coproc의
  # write end가 닫혀 lock과 caller 고유 incoming 디렉터리가 다음 실행을 막지 않는다.
  coproc BOOTSTRAP_LOCK_GUARD {
    sudo -n flock --exclusive "$BOOTSTRAP_LOCK_FILE" \
      /bin/sh -c 'printf "locked\n"; IFS= read -r _'
  }
  local lock_status
  IFS= read -r lock_status <&"${BOOTSTRAP_LOCK_GUARD[0]}" ||
    die "bootstrap lock guardian did not start"
  [[ "$lock_status" == "locked" ]] || die "bootstrap lock was not acquired"

  local stale_name stale_path
  while IFS= read -r stale_name; do
    [[ "$stale_name" =~ ^\.incoming-[0-9a-f]{40}-[0-9]+(-[0-9a-f]{12})?$ ]] ||
      die "stale bootstrap path is unsafe"
    stale_path="$INSTALL_BASE/$stale_name"
    [[ "$(sudo -n stat -c '%u:%g:%a' -- "$stale_path")" == "0:0:700" ]] ||
      die "stale bootstrap metadata is unsafe"
    sudo -n rm -rf -- "$stale_path"
  done < <(
    sudo -n find "$INSTALL_BASE" -mindepth 1 -maxdepth 1 -type d \
      -name '.incoming-*' -printf '%f\n'
  )

  local incoming="$INSTALL_BASE/.incoming-$SOURCE_COMMIT-$$-$(openssl rand -hex 6)"
  local bootstrap_status=0
  (
    set -e
    sudo -n install -d -o root -g root -m 0700 "$incoming"
    sudo -n curl -q --fail --show-error --silent --location \
      --proto '=https' --proto-redir '=https' --tlsv1.2 \
      --output "$incoming/source.tar.gz" "$ARCHIVE_URL"
    sudo -n tar --extract --gzip --file "$incoming/source.tar.gz" \
      --directory "$incoming" --strip-components=2 \
      "$ARCHIVE_PREFIX/scripts/admin_feature_clone_live_state.py" \
      "$ARCHIVE_PREFIX/scripts/admin_feature_live_fixture.py" \
      "$ARCHIVE_PREFIX/scripts/c7-loopback-ui-proxy.mjs" \
      "$ARCHIVE_PREFIX/scripts/run-admin-feature-clone-live-acceptance.sh"
    sudo -n chown root:root \
      "$incoming/source.tar.gz" \
      "$incoming/admin_feature_clone_live_state.py" \
      "$incoming/admin_feature_live_fixture.py" \
      "$incoming/c7-loopback-ui-proxy.mjs" \
      "$incoming/run-admin-feature-clone-live-acceptance.sh"
    sudo -n chmod 0444 \
      "$incoming/source.tar.gz" \
      "$incoming/admin_feature_clone_live_state.py" \
      "$incoming/admin_feature_live_fixture.py" \
      "$incoming/c7-loopback-ui-proxy.mjs"
    sudo -n chmod 0555 "$incoming/run-admin-feature-clone-live-acceptance.sh"
    sudo -n chmod 0555 "$incoming"
    if ! sudo -n mv -T --no-clobber -- "$incoming" "$expected_root"; then
      sudo -n rm -rf -- "$incoming"
      sudo -n test -d "$expected_root"
    fi
  ) || bootstrap_status=$?
  if sudo -n test -e "$incoming"; then
    sudo -n rm -rf -- "$incoming"
  fi
  (( bootstrap_status == 0 )) || die "immutable snapshot bootstrap failed"
  validate_snapshot "$SOURCE_COMMIT" "$expected_root"

  printf 'release\n' >&"${BOOTSTRAP_LOCK_GUARD[1]}" || true
  wait "$BOOTSTRAP_LOCK_GUARD_PID" ||
    die "bootstrap lock guardian exited unexpectedly"

  exec sudo -n \
    --preserve-env=E2E_SOURCE_COMMIT,E2E_CLONE_DB_CONTAINER,E2E_CLONE_DB_PORT,E2E_CLONE_DB_DUMP,E2E_CLONE_DUMP_PATH,E2E_CLONE_API_PORT,E2E_CLONE_UI_PORT,E2E_ADMIN_PASSWORD,E2E_VWORLD_API_KEY \
    "$expected_root/run-admin-feature-clone-live-acceptance.sh" "$MODE"
}

validate_snapshot() {
  local snapshot_commit="${1:-$SOURCE_COMMIT}"
  local snapshot_root="${2:-$SCRIPT_DIR}"
  local expected_root="$INSTALL_BASE/$snapshot_commit"
  local archive="$snapshot_root/source.tar.gz"
  local prefix="kor-travel-map-$snapshot_commit"
  [[ "$snapshot_root" == "$expected_root" && "$snapshot_root" == "$(readlink -f -- "$snapshot_root")" ]] ||
    die "snapshot root mismatch"
  [[ -d "$snapshot_root" && ! -L "$snapshot_root" ]] ||
    die "snapshot root is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$snapshot_root")" == "0:0:555" ]] ||
    die "snapshot root metadata is unsafe"
  local installed_names legacy_names actual_names
  installed_names=$'admin_feature_clone_live_state.py\nadmin_feature_live_fixture.py\nc7-loopback-ui-proxy.mjs\nrun-admin-feature-clone-live-acceptance.sh\nsource.tar.gz'
  legacy_names=$'admin_feature_clone_live_state.py\nadmin_feature_live_fixture.py\nrun-admin-feature-clone-live-acceptance.sh\nsource.tar.gz'
  actual_names="$(
    find "$snapshot_root" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort
  )"
  if [[ "$actual_names" == "$installed_names" ]]; then
    LOOPBACK_PROXY_HELPER="$snapshot_root/c7-loopback-ui-proxy.mjs"
  elif [[ "$actual_names" == "$legacy_names" ]]; then
    # 이전 immutable bootstrap root는 새 보조 파일을 설치하지 못한다. 현재 runner의
    # archive에만 proxy member를 요구하고, recover가 검증하는 과거 fixture snapshot은
    # 기존 정확한 세 helper만으로 읽기 전용 호환을 유지한다.
    if [[ "$snapshot_root" == "$SCRIPT_DIR" ]]; then
      [[ "$(tar -tzf "$archive" "$prefix/scripts/c7-loopback-ui-proxy.mjs")" == "$prefix/scripts/c7-loopback-ui-proxy.mjs" ]] ||
        die "legacy current snapshot lacks the loopback proxy source"
    fi
  else
    die "snapshot exact file set mismatch"
  fi
  [[ "$(stat -c '%u:%g:%a' -- "$archive")" == "0:0:444" && ! -L "$archive" ]] ||
    die "source archive metadata is unsafe"
  local name expected_mode archive_digest installed_digest
  local -a snapshot_files=(
    admin_feature_clone_live_state.py \
    admin_feature_live_fixture.py \
    run-admin-feature-clone-live-acceptance.sh
  )
  [[ -z "$LOOPBACK_PROXY_HELPER" ]] || snapshot_files+=(c7-loopback-ui-proxy.mjs)
  for name in "${snapshot_files[@]}"; do
    expected_mode=444
    [[ "$name" != run-admin-feature-clone-live-acceptance.sh ]] || expected_mode=555
    [[ "$(stat -c '%u:%g:%a' -- "$snapshot_root/$name")" == "0:0:$expected_mode" ]] ||
      die "snapshot file metadata is unsafe"
    [[ ! -L "$snapshot_root/$name" ]] || die "snapshot file is a symlink"
    archive_digest="$(
      tar -xOf "$archive" "$prefix/scripts/$name" | sha256sum | awk '{print $1}'
    )"
    installed_digest="$(sha256sum "$snapshot_root/$name" | awk '{print $1}')"
    [[ "$archive_digest" == "$installed_digest" ]] ||
      die "snapshot file differs from source archive"
  done
  local ancestor
  for ancestor in "$snapshot_root/.." "$snapshot_root/../.." "$snapshot_root/../../.."; do
    ancestor="$(readlink -f -- "$ancestor")"
    [[ -d "$ancestor" && ! -L "$ancestor" ]] || die "snapshot ancestor is unsafe"
    [[ "$(stat -c '%u:%g' -- "$ancestor")" == "0:0" ]] ||
      die "snapshot ancestor ownership is unsafe"
    (( (8#$(stat -c '%a' -- "$ancestor") & 8#022) == 0 )) ||
      die "snapshot ancestor is writable"
  done
}

require_env E2E_SOURCE_COMMIT
if [[ "$SCRIPT_DIR" != "$INSTALL_BASE/$SOURCE_COMMIT" ]]; then
  bootstrap_snapshot
fi

(( EUID == 0 )) || die "trusted installed runner requires root"
validate_snapshot
[[ "$MODE" == "baseline" || "$MODE" == "checkpoint" ||
   "$MODE" == "recover" || "$MODE" == "run" || "$MODE" == "abort" ]] ||
  die "usage: runner baseline|checkpoint|recover|run|abort"
require_command docker
require_command find
require_command flock
require_command openssl
require_command python3
require_command sha256sum
require_command sort
require_command stat
require_command tar
require_env E2E_CLONE_DB_CONTAINER
require_env E2E_CLONE_DB_PORT
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "source commit is invalid"
[[ "$DB_CONTAINER" =~ ^ktm-[a-z0-9-]+-db$ ]] || die "clone DB container name is invalid"
[[ "$DB_HOST_PORT" =~ ^[0-9]+$ ]] || die "clone DB host port is invalid"
(( DB_HOST_PORT >= 1024 && DB_HOST_PORT <= 65535 && DB_HOST_PORT != 5432 )) ||
  die "clone DB host port is unsafe"
for port in "$API_PORT" "$UI_PORT"; do
  [[ "$port" =~ ^[0-9]+$ ]] || die "candidate port is invalid"
  (( port >= 1024 && port <= 65535 && port != 12701 && port != 12705 )) ||
    die "candidate port overlaps production/default"
done
[[ "$API_PORT" != "$UI_PORT" ]] || die "candidate ports overlap"
if [[ "$MODE" != "baseline" && "$MODE" != "checkpoint" ]]; then
  require_env E2E_ADMIN_PASSWORD
  require_env E2E_VWORLD_API_KEY
  [[ "${E2E_ADMIN_PASSWORD}" != *$'\n'* && "${E2E_ADMIN_PASSWORD}" != *$'\r'* ]] ||
    die "admin password contains a newline"
  [[ "${E2E_VWORLD_API_KEY}" != *$'\n'* && "${E2E_VWORLD_API_KEY}" != *$'\r'* ]] ||
    die "VWorld key contains a newline"
fi

if [[ -e "$STATE_ROOT" || -L "$STATE_ROOT" ]]; then
  [[ -d "$STATE_ROOT" && ! -L "$STATE_ROOT" ]] || die "state root is unsafe"
else
  [[ "$MODE" != "recover" ]] || die "recoverable state root is missing"
  mkdir -- "$STATE_ROOT"
  chown root:root -- "$STATE_ROOT"
  chmod 0700 -- "$STATE_ROOT"
fi
[[ "$(stat -c '%u:%g:%a' -- "$STATE_ROOT")" == "0:0:700" ]] ||
  die "state root metadata is unsafe"
if [[ -e "$LOCK_FILE" || -L "$LOCK_FILE" ]]; then
  [[ -f "$LOCK_FILE" && ! -L "$LOCK_FILE" ]] || die "orchestrator lock is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$LOCK_FILE")" == "0:0:600" ]] ||
    die "orchestrator lock metadata is unsafe"
else
  install -o root -g root -m 0600 /dev/null "$LOCK_FILE"
fi
# 별도 guardian만 flock을 소유한다. coproc pipe는 외부 명령에 상속되지 않으므로
# runner가 SIGKILL돼도 장시간 docker/build/executor 자식이 복구 lock을 붙잡지 않는다.
coproc ORCHESTRATOR_LOCK_GUARD {
  flock --exclusive --nonblock "$LOCK_FILE" \
    /bin/sh -c 'printf "locked\n"; IFS= read -r _'
}
orchestrator_lock_status=""
IFS= read -r orchestrator_lock_status <&"${ORCHESTRATOR_LOCK_GUARD[0]}" ||
  die "another clone acceptance runner owns the lock"
[[ "$orchestrator_lock_status" == "locked" ]] ||
  die "orchestrator lock guardian did not acquire the lock"

readonly STATE_HELPER="$SCRIPT_DIR/admin_feature_clone_live_state.py"
state_helper() {
  python3 -I -B "$STATE_HELPER" "$@"
}

docker container inspect "$DB_CONTAINER" >/dev/null 2>&1 ||
  die "clone DB container is missing"
readonly BASE_CLONE_CONTAINER_ID="$(
  docker inspect --format '{{.Id}}' "$DB_CONTAINER"
)"
readonly BASE_CLONE_IMAGE_ID="$(
  docker inspect --format '{{.Image}}' "$DB_CONTAINER"
)"

verify_clone_container() {
  local observed_id
  observed_id="$(docker inspect --format '{{.Id}}' "$DB_CONTAINER")" ||
    die "clone DB container disappeared"
  [[ "$observed_id" == "$BASE_CLONE_CONTAINER_ID" ]] ||
    die "clone DB container identity changed"
  [[ "$(docker inspect --format '{{.State.Running}}' "$DB_CONTAINER")" == "true" ]] ||
    die "clone DB container is not running"
  local health
  health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$DB_CONTAINER")"
  [[ -z "$health" || "$health" == "healthy" ]] || die "clone DB container is unhealthy"
  [[ "$(docker inspect --format '{{.HostConfig.NetworkMode}}' "$DB_CONTAINER")" != "host" ]] ||
    die "clone DB cannot use host network"
  [[ "$(
    docker inspect --format \
      '{{index .Config.Labels "com.docker.compose.project"}}' "$DB_CONTAINER"
  )" != "kor-travel-docker-manager" ]] || die "production compose DB is forbidden"
  [[ "$(docker port "$DB_CONTAINER" 5432/tcp)" == "127.0.0.1:$DB_HOST_PORT" ]] ||
    die "clone DB loopback port binding mismatch"
}
verify_clone_container

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
readonly ORIGINAL_DB_NAME="$db_name"
PSQL_APP_NAME=""
PSQL_SESSION_OPTIONS=""

psql_query() {
  local query="$1"
  PGPASSWORD="$db_password" \
    PGOPTIONS="$PSQL_SESSION_OPTIONS" \
    PGAPPNAME="$PSQL_APP_NAME" \
    docker exec -e PGPASSWORD -e PGOPTIONS -e PGAPPNAME "$DB_CONTAINER" \
    psql -X -v ON_ERROR_STOP=1 -Atq -U "$db_user" -d "$db_name" -c "$query"
}

psql_stream() {
  PGPASSWORD="$db_password" \
    PGOPTIONS="$PSQL_SESSION_OPTIONS" \
    PGAPPNAME="$PSQL_APP_NAME" \
    docker exec -i -e PGPASSWORD -e PGOPTIONS -e PGAPPNAME "$DB_CONTAINER" \
    psql -X -v ON_ERROR_STOP=1 -Atq -U "$db_user" -d "$db_name"
}

psql_value() {
  local value
  value="$(psql_query "$1")"
  [[ "$value" != *$'\n'* ]] || die "scalar DB query returned multiple rows"
  printf '%s' "$value"
}

make_dsn() {
  local host="$1"
  local port="$2"
  local connection_password="$db_password"
  if (( CHECKPOINT_LOGIN_FENCED == 1 )); then
    [[ -n "$CHECKPOINT_FENCE_PASSWORD" ]] ||
      die "active clone DB login fence has no runner password"
    connection_password="$CHECKPOINT_FENCE_PASSWORD"
  fi
  KTM_E2E_DB_USER="$db_user" \
    KTM_E2E_DB_PASSWORD="$connection_password" \
    KTM_E2E_DB_HOST="$host" \
    KTM_E2E_DB_PORT="$port" \
    KTM_E2E_DB_NAME="$db_name" \
    python3 -I -B -c '
import os
from urllib.parse import quote
user = quote(os.environ["KTM_E2E_DB_USER"], safe="")
password = quote(os.environ["KTM_E2E_DB_PASSWORD"], safe="")
host = os.environ["KTM_E2E_DB_HOST"]
port = os.environ["KTM_E2E_DB_PORT"]
database = quote(os.environ["KTM_E2E_DB_NAME"], safe="")
print(
    "postgresql+asyncpg://" + user + ":" + password + "@"
    + host + ":" + port + "/" + database
)
'
}

schema_sha256() {
  local query
  query="$(cat <<'SQL'
COPY (
  WITH objects AS (
    SELECT
      'column'::text AS kind,
      namespace.nspname AS schema_name,
      relation.relname AS object_name,
      -- ALTER TABLE DROP COLUMN 뒤의 attnum gap은 pg_dump/pg_restore가 정규화한다.
      -- 이름·형식·필수성·identity/generated/default와 active-column 상대 순서가
      -- column contract이다. gap만 무시하도록 dense ordinal을 넣는다.
      row_number() OVER (
        PARTITION BY attribute.attrelid ORDER BY attribute.attnum
      )::text || ':' || attribute.attname || ':' ||
      pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) || ':' ||
      attribute.attnotnull::text || ':' ||
      attribute.attidentity::text || ':' ||
      attribute.attgenerated::text || ':' ||
      COALESCE(attribute.attacl::text, '') || ':' ||
      COALESCE(pg_catalog.pg_get_expr(default_row.adbin, default_row.adrelid), '')
        AS definition
    FROM pg_catalog.pg_attribute AS attribute
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    LEFT JOIN pg_catalog.pg_attrdef AS default_row
      ON default_row.adrelid = attribute.attrelid
     AND default_row.adnum = attribute.attnum
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind IN ('r', 'p', 'v', 'm')
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
    UNION ALL
    SELECT
      'relation', namespace.nspname, relation.relname,
      concat_ws(
        ':',
        relation.relkind,
        relation.relowner::regrole::text,
        COALESCE(relation.relacl::text, ''),
        relation.relrowsecurity,
        relation.relforcerowsecurity,
        COALESCE(
          pg_catalog.pg_get_expr(
            relation.relpartbound,
            relation.oid,
            true
          ),
          ''
        )
      )
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'S')
    UNION ALL
    SELECT
      'constraint', namespace.nspname, relation.relname,
      -- pg_restore는 같은 CHECK AST를 다시 parse/deparse하면서 괄호·암묵 cast의
      -- 텍스트만 바꿀 수 있다. dump SHA-256 + pg_restore 성공이 expression bytes와
      -- 적용을 보장하므로, restore 동등성 fingerprint에는 deparser 문자열 대신
      -- structural catalog 축만 넣는다. conkey/confkey도 dropped column 뒤에는 raw
      -- attnum을 보유하므로, key 순서를 보존한 column name으로 정규화한다. 그렇지
      -- 않으면 같은 constraint가 false-red가 된다.
      concat_ws(
        ':',
        constraint_row.conname,
        constraint_row.contype,
        COALESCE(
          (
            SELECT string_agg(
              key_attribute.attname,
              ',' ORDER BY array_position(constraint_row.conkey, key_attribute.attnum)
            )
            FROM pg_catalog.pg_attribute AS key_attribute
            WHERE key_attribute.attrelid = constraint_row.conrelid
              AND key_attribute.attnum = ANY(constraint_row.conkey)
          ),
          ''
        ),
        COALESCE(
          (
            SELECT string_agg(
              referenced_attribute.attname,
              ',' ORDER BY array_position(
                constraint_row.confkey,
                referenced_attribute.attnum
              )
            )
            FROM pg_catalog.pg_attribute AS referenced_attribute
            WHERE referenced_attribute.attrelid = constraint_row.confrelid
              AND referenced_attribute.attnum = ANY(constraint_row.confkey)
          ),
          ''
        ),
        COALESCE(constraint_row.confrelid::regclass::text, ''),
        constraint_row.confupdtype,
        constraint_row.confdeltype,
        constraint_row.confmatchtype,
        constraint_row.condeferrable,
        constraint_row.condeferred,
        constraint_row.convalidated,
        constraint_row.connoinherit,
        COALESCE(constraint_row.conexclop::text, '')
      )
    FROM pg_catalog.pg_constraint AS constraint_row
    JOIN pg_catalog.pg_class AS relation ON relation.oid = constraint_row.conrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
      'index', namespace.nspname, relation.relname,
      index_row.relname || ':' || pg_catalog.pg_get_indexdef(index_row.oid)
    FROM pg_catalog.pg_index AS index_link
    JOIN pg_catalog.pg_class AS relation ON relation.oid = index_link.indrelid
    JOIN pg_catalog.pg_class AS index_row ON index_row.oid = index_link.indexrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
      'trigger', namespace.nspname, relation.relname,
      trigger_row.tgname || ':' ||
      trigger_row.tgenabled::text || ':' ||
      pg_catalog.pg_get_triggerdef(trigger_row.oid, true)
    FROM pg_catalog.pg_trigger AS trigger_row
    JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger_row.tgrelid
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND NOT trigger_row.tgisinternal
    UNION ALL
    SELECT
      'view', namespace.nspname, relation.relname,
      pg_catalog.pg_get_viewdef(relation.oid, true)
    FROM pg_catalog.pg_class AS relation
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND relation.relkind IN ('v', 'm')
    UNION ALL
    SELECT
      'routine',
      namespace.nspname,
      routine.proname || ':' ||
        pg_catalog.pg_get_function_identity_arguments(routine.oid),
      routine.proowner::regrole::text || ':' ||
        COALESCE(routine.proacl::text, '') || ':' ||
        pg_catalog.pg_get_functiondef(routine.oid)
    FROM pg_catalog.pg_proc AS routine
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
      'type',
      namespace.nspname,
      type_row.typname,
      concat_ws(
        ':',
        type_row.typtype,
        type_row.typcategory,
        type_row.typnotnull,
        type_row.typbasetype::regtype::text,
        type_row.typtypmod,
        type_row.typowner::regrole::text,
        COALESCE(type_row.typacl::text, ''),
        COALESCE(enum_values.labels, '')
      )
    FROM pg_catalog.pg_type AS type_row
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = type_row.typnamespace
    LEFT JOIN LATERAL (
      SELECT string_agg(enum_row.enumlabel, ',' ORDER BY enum_row.enumsortorder)
        AS labels
      FROM pg_catalog.pg_enum AS enum_row
      WHERE enum_row.enumtypid = type_row.oid
    ) AS enum_values ON true
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
      AND type_row.typrelid = 0
      AND type_row.typisdefined
    UNION ALL
    SELECT
      'domain_constraint',
      namespace.nspname,
      type_row.typname,
      concat_ws(
        ':',
        constraint_row.conname,
        constraint_row.contype,
        constraint_row.convalidated,
        constraint_row.connoinherit
      )
    FROM pg_catalog.pg_constraint AS constraint_row
    JOIN pg_catalog.pg_type AS type_row
      ON type_row.oid = constraint_row.contypid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = type_row.typnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
      'policy',
      namespace.nspname,
      relation.relname,
      policy.polname || ':' || policy.polcmd::text || ':' ||
        policy.polroles::text || ':' ||
        COALESCE(
          pg_catalog.pg_get_expr(policy.polqual, policy.polrelid, true),
          ''
        ) || ':' ||
        COALESCE(
          pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid, true),
          ''
        )
    FROM pg_catalog.pg_policy AS policy
    JOIN pg_catalog.pg_class AS relation ON relation.oid = policy.polrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
      'sequence',
      namespace.nspname,
      relation.relname,
      concat_ws(
        ':',
        sequence.seqstart,
        sequence.seqincrement,
        sequence.seqmax,
        sequence.seqmin,
        sequence.seqcache,
        sequence.seqcycle
      )
    FROM pg_catalog.pg_sequence AS sequence
    JOIN pg_catalog.pg_class AS relation ON relation.oid = sequence.seqrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
      'namespace',
      namespace.nspname,
      namespace.nspname,
      namespace.nspowner::regrole::text || ':' ||
        COALESCE(namespace.nspacl::text, '')
    FROM pg_catalog.pg_namespace AS namespace
    WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
    UNION ALL
    SELECT
      'default_acl',
      COALESCE(namespace.nspname, '<global>'),
      default_acl.defaclrole::regrole::text || ':' ||
        default_acl.defaclobjtype::text,
      COALESCE(default_acl.defaclacl::text, '')
    FROM pg_catalog.pg_default_acl AS default_acl
    LEFT JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = default_acl.defaclnamespace
    WHERE default_acl.defaclnamespace = 0
       OR namespace.nspname IN ('feature', 'ops', 'provider_sync')
  )
  SELECT concat_ws(chr(31), kind, schema_name, object_name, definition)
  FROM objects
  ORDER BY kind, schema_name, object_name, definition
) TO STDOUT
SQL
)"
  psql_query "$query" | sha256sum | awk '{print $1}'
}

database_sha256() {
  local query
  query="$(cat <<'SQL'
COPY (
  WITH objects AS (
    SELECT
      'database'::text AS kind,
      '<current>'::text AS object_name,
      concat_ws(
        ':',
        database.encoding,
        database.datlocprovider,
        database.datistemplate,
        database.datallowconn,
        database.datconnlimit,
        database.dattablespace,
        database.datcollate,
        database.datctype,
        COALESCE(database.daticulocale, ''),
        COALESCE(database.daticurules, ''),
        COALESCE(database.datcollversion, ''),
        -- 검증 DB는 crash-safe cleanup을 위해 일회성 전용 role이 소유한다.
        -- 원본 DB owner는 checkpoint_login_role_invariant에서 별도로 검증한다.
        '<database-owner>',
        COALESCE(database.datacl::text, '')
      ) AS definition
    FROM pg_catalog.pg_database AS database
    WHERE database.datname = current_database()
    UNION ALL
    SELECT
      'database_setting',
      CASE
        WHEN setting.setrole = 0 THEN '<database>'
        ELSE setting.setrole::regrole::text
      END,
      configuration.value
    FROM pg_catalog.pg_db_role_setting AS setting
    CROSS JOIN LATERAL unnest(setting.setconfig) AS configuration(value)
    WHERE setting.setdatabase = (
      SELECT oid
      FROM pg_catalog.pg_database
      WHERE datname = current_database()
    )
  )
  SELECT concat_ws(chr(31), kind, object_name, definition)
  FROM objects
  ORDER BY kind, object_name, definition
) TO STDOUT
SQL
)"
  psql_query "$query" | sha256sum | awk '{print $1}'
}

extension_sha256() {
  psql_query "
    COPY (
      SELECT concat_ws(
        chr(31),
        extension.extname,
        extension.extowner::regrole::text,
        namespace.nspname,
        extension.extrelocatable,
        extension.extversion,
        COALESCE(
          (
            SELECT string_agg(
              concat_ws(
                chr(30),
                config_namespace.nspname,
                config_relation.relname
              ),
              chr(29)
              ORDER BY config.ordinality
            )
            FROM unnest(extension.extconfig) WITH ORDINALITY
              AS config(relation_oid, ordinality)
            JOIN pg_catalog.pg_class AS config_relation
              ON config_relation.oid = config.relation_oid
            JOIN pg_catalog.pg_namespace AS config_namespace
              ON config_namespace.oid = config_relation.relnamespace
          ),
          ''
        ),
        COALESCE(extension.extcondition::text, '')
      )
      FROM pg_catalog.pg_extension AS extension
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = extension.extnamespace
      ORDER BY extension.extname
    ) TO STDOUT
  " | sha256sum | awk '{print $1}'
}

content_sha256() {
  local run_id="$1"
  local dataset_projection_revision="${2-}"
  local dataset_projection_updated_at="${3-}"
  [[ "$run_id" =~ ^[a-z0-9][a-z0-9-]{15,79}$ ]] ||
    die "content digest run ID is invalid"
  [[ "$CONTENT_CUTOFF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$ ]] ||
    die "content digest cutoff is invalid"
  if [[ -n "$dataset_projection_revision" ||
        -n "$dataset_projection_updated_at" ]]; then
    [[ "$dataset_projection_revision" =~ ^[0-9]+$ ]] ||
      die "dataset projection baseline revision is invalid"
    [[ "$dataset_projection_updated_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$ ]] ||
      die "dataset projection baseline timestamp is invalid"
  fi
  local statement_query statements
  statement_query="$(cat <<SQL
SELECT CASE
  WHEN relation.relkind = 'S' THEN format(
    'SELECT %L || chr(31) || ''1'' || chr(31) || last_value::text || ' ||
    'chr(31) || is_called::text FROM %I.%I;',
    namespace.nspname || '.' || relation.relname,
    namespace.nspname,
    relation.relname
  )
  WHEN namespace.nspname = 'ops'
    AND relation.relname = 'ops_live_topic_revisions'
    AND '${dataset_projection_revision}' <> ''
  THEN format(
    'SELECT %L || chr(31) || count(*)::text || chr(31) || ' ||
    'COALESCE(bit_xor(hashtextextended(row_value::text, 0))::text, ''null'') || ' ||
    'chr(31) || COALESCE(bit_xor(hashtextextended(row_value::text, ' ||
    '9223372036854775807))::text, ''null'') ' ||
    'FROM (' ||
    'SELECT topic, revision, updated_at FROM %I.%I ' ||
    'WHERE topic <> ''dataset_projection'' ' ||
    'UNION ALL SELECT ''dataset_projection'', %s::bigint, %L::timestamptz' ||
    ') AS row_value;',
    namespace.nspname || '.' || relation.relname,
    namespace.nspname,
    relation.relname,
    '${dataset_projection_revision}',
    '${dataset_projection_updated_at}'
  )
  ELSE format(
    'SELECT %L || chr(31) || count(*)::text || chr(31) || ' ||
    'COALESCE(bit_xor(hashtextextended(row_value::text, 0))::text, ''null'') || ' ||
    'chr(31) || COALESCE(bit_xor(hashtextextended(row_value::text, ' ||
    '9223372036854775807))::text, ''null'') ' ||
    'FROM %I.%I AS row_value%s;',
    namespace.nspname || '.' || relation.relname,
    namespace.nspname,
    relation.relname,
    CASE
      WHEN EXISTS (
        SELECT 1
        FROM pg_catalog.pg_attribute AS attribute
        WHERE attribute.attrelid = relation.oid
          AND attribute.attname = 'feature_id'
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
      ) THEN format(
        ' WHERE row_value.feature_id NOT LIKE %L ESCAPE %L',
        'e2e_live_acceptance::${run_id}::%',
        chr(92)
      )
      WHEN namespace.nspname = 'ops'
        AND relation.relname = 'admin_auth_events'
      THEN format(
        ' WHERE row_value.request_id IS DISTINCT FROM %L' ||
        ' AND row_value.request_id IS DISTINCT FROM %L',
        'e2e_live_acceptance::${run_id}::auth::main',
        'e2e_live_acceptance::${run_id}::auth::recovery'
      )
      ELSE ''
    END
  )
END
FROM pg_catalog.pg_class AS relation
JOIN pg_catalog.pg_namespace AS namespace
  ON namespace.oid = relation.relnamespace
WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
  AND relation.relkind IN ('r', 'p', 'm', 'S')
  AND NOT relation.relispartition
ORDER BY namespace.nspname, relation.relname
SQL
)"
  statements="$(psql_query "$statement_query")"
  [[ -n "$statements" ]] || die "durable content table set is empty"
  {
    printf '%s\n' \
      "SET statement_timeout = '20min';" \
      "SET max_parallel_workers_per_gather = 4;"
    printf '%s\n' "$statements"
  } | psql_stream | LC_ALL=C sort | sha256sum | awk '{print $1}'
}

EXPECTED_MIGRATION_HEAD=""
BASE_CLONE_CONTAINER_SHA256=""
BASE_CLONE_SYSTEM_SHA256=""
CONTENT_CUTOFF=""
DATASET_PROJECTION_START_REVISION=""
DATASET_PROJECTION_START_UPDATED_AT=""
DATASET_PROJECTION_START_SOURCE=""

read_current_dataset_projection() {
  local row
  row="$(
    psql_value "
      SELECT revision::text || chr(9) ||
        to_char(
          updated_at AT TIME ZONE 'UTC',
          'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'
        )
      FROM ops.ops_live_topic_revisions
      WHERE topic = 'dataset_projection'
    "
  )"
  [[ "$row" =~ ^([0-9]+)$'\t'([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z)$ ]] ||
    die "dataset projection current row is invalid"
  DATASET_PROJECTION_CURRENT_REVISION="${BASH_REMATCH[1]}"
  DATASET_PROJECTION_CURRENT_UPDATED_AT="${BASH_REMATCH[2]}"
}

load_dataset_projection_start_from_dump() {
  local checkpoint_path="$1"
  local filename dump_path restore_output row raw_updated_at
  filename="$(
    state_helper read-checkpoint \
      --checkpoint "$checkpoint_path" --field dump_filename
  )"
  dump_path="$STATE_ROOT/$filename"
  [[ "$dump_path" == "$STATE_ROOT"/clone-checkpoint-*.dump &&
     -f "$dump_path" && ! -L "$dump_path" ]] ||
    die "dataset projection checkpoint dump path is unsafe"
  restore_output="$(
    docker run --rm \
      --network none \
      --read-only \
      --security-opt no-new-privileges \
      --cap-drop ALL \
      --mount "type=bind,src=$dump_path,dst=/checkpoint.dump,readonly" \
      --entrypoint pg_restore \
      "$BASE_CLONE_IMAGE_ID" \
      --data-only \
      --schema=ops \
      --table=ops_live_topic_revisions \
      -f - \
      /checkpoint.dump
  )"
  row="$(
    awk -F $'\t' '
      $1 == "dataset_projection" {
        if (NF != 3) {
          exit 2
        }
        value = $2 FS $3
        count += 1
      }
      END {
        if (count != 1) {
          exit 3
        }
        print value
      }
    ' <<<"$restore_output"
  )"
  unset restore_output
  [[ "$row" =~ ^([0-9]+)$'\t'([0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}\+00)$ ]] ||
    die "dataset projection checkpoint row is invalid"
  DATASET_PROJECTION_START_REVISION="${BASH_REMATCH[1]}"
  raw_updated_at="${BASH_REMATCH[2]}"
  DATASET_PROJECTION_START_UPDATED_AT="${raw_updated_at/ /T}"
  DATASET_PROJECTION_START_UPDATED_AT="${DATASET_PROJECTION_START_UPDATED_AT%+00}Z"
  DATASET_PROJECTION_START_SOURCE="checkpoint-dump"
}

load_dataset_projection_start_from_runtime() {
  local path="$RUNTIME_DIR/topic-revision-start.json"
  [[ -f "$path" && ! -L "$path" ]] ||
    die "dataset projection runtime start evidence is missing"
  DATASET_PROJECTION_START_REVISION="$(
    state_helper read-topic-revision-start \
      --field revision --path "$path"
  )"
  DATASET_PROJECTION_START_UPDATED_AT="$(
    state_helper read-topic-revision-start \
      --field updated_at --path "$path"
  )"
  [[ "$(
    state_helper read-topic-revision-start \
      --field checkpoint_sha256 --path "$path"
  )" == "$(state_helper read-blocked \
    --path "$BLOCKED_FILE" --field clone_checkpoint_sha256
  )" ]] || die "dataset projection runtime checkpoint binding differs"
  [[ "$(
    state_helper read-topic-revision-start \
      --field run_id --path "$path"
  )" == "$RUN_ID" ]] || die "dataset projection runtime run ID differs"
  DATASET_PROJECTION_START_SOURCE="runtime-start"
}

snapshot_content_sha256() {
  local path="$1"
  local digest
  digest="$(
    KTM_SNAPSHOT_PATH="$path" python3 -I -B -c '
import json
import os
from pathlib import Path

value = json.loads(Path(os.environ["KTM_SNAPSHOT_PATH"]).read_text())["content_sha256"]
if not isinstance(value, str):
    raise SystemExit("invalid snapshot content digest")
print(value)
'
  )"
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] ||
    die "snapshot content digest is invalid"
  printf '%s' "$digest"
}

write_dataset_projection_snapshots() {
  local observed_path="$1"
  local normalized_path="$2"
  local checkpoint_sha256 observed_content normalized_content
  [[ "$DATASET_PROJECTION_START_REVISION" =~ ^[0-9]+$ ]] ||
    die "dataset projection start revision is unavailable"
  [[ "$DATASET_PROJECTION_START_UPDATED_AT" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$ ]] ||
    die "dataset projection start timestamp is unavailable"
  [[ "$DATASET_PROJECTION_START_SOURCE" == "runtime-start" ||
     "$DATASET_PROJECTION_START_SOURCE" == "checkpoint-dump" ]] ||
    die "dataset projection start source is unavailable"
  write_snapshot "$observed_path" "$RUN_ID"
  read_current_dataset_projection
  (( DATASET_PROJECTION_CURRENT_REVISION >
     DATASET_PROJECTION_START_REVISION )) ||
    die "dataset projection revision did not advance"
  [[ "$DATASET_PROJECTION_CURRENT_UPDATED_AT" > "$DATASET_PROJECTION_START_UPDATED_AT" ]] ||
    die "dataset projection revision timestamp did not advance"
  write_snapshot \
    "$normalized_path" \
    "$RUN_ID" \
    "$DATASET_PROJECTION_START_REVISION" \
    "$DATASET_PROJECTION_START_UPDATED_AT"
  checkpoint_sha256="$(
    state_helper read-blocked \
      --path "$BLOCKED_FILE" --field clone_checkpoint_sha256
  )"
  observed_content="$(snapshot_content_sha256 "$observed_path")"
  normalized_content="$(snapshot_content_sha256 "$normalized_path")"
  state_helper write-topic-revision-proof \
    --checkpoint-sha256 "$checkpoint_sha256" \
    --current-revision "$DATASET_PROJECTION_CURRENT_REVISION" \
    --current-updated-at "$DATASET_PROJECTION_CURRENT_UPDATED_AT" \
    --normalized-content-sha256 "$normalized_content" \
    --observed-content-sha256 "$observed_content" \
    --path "$RUNTIME_DIR/topic-revision-proof.json" \
    --run-id "$RUN_ID" \
    --source "$DATASET_PROJECTION_START_SOURCE" \
    --start-revision "$DATASET_PROJECTION_START_REVISION" \
    --start-updated-at "$DATASET_PROJECTION_START_UPDATED_AT"
}

read_image_migration_head() {
  local image_id="$1"
  local -a heads=()
  mapfile -t heads < <(
    docker run --rm \
      --network none \
      --read-only \
      --security-opt no-new-privileges \
      --cap-drop ALL \
      --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
      --entrypoint python \
      "$image_id" \
      -m alembic -c /app/alembic.ini heads |
      awk '{print $1}'
  )
  (( ${#heads[@]} == 1 )) || die "candidate API image must have one Alembic head"
  printf '%s' "${heads[0]}"
}

write_snapshot() {
  local path="$1"
  local run_id="$2"
  local dataset_projection_revision="${3-}"
  local dataset_projection_updated_at="${4-}"
  [[ "$run_id" =~ ^[a-z0-9][a-z0-9-]{15,79}$ ]] ||
    die "snapshot run ID is invalid"
  verify_clone_container
  local before_id="$(
    docker inspect --format '{{.Id}}' "$DB_CONTAINER"
  )"
  local container_sha system_identifier system_sha
  local migration_head relation_count feature_total feature_non_deleted
  local active_owned nonterminal_owned schema_digest content_digest
  local database_digest extension_digest
  container_sha="$(printf '%s' "$before_id" | sha256sum | awk '{print $1}')"
  system_identifier="$(psql_value "SELECT system_identifier::text FROM pg_control_system()")"
  system_sha="$(printf '%s' "$system_identifier" | sha256sum | awk '{print $1}')"
  unset system_identifier
  migration_head="$(psql_value "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version")"
  relation_count="$(psql_value "SELECT count(*) FROM pg_class WHERE relnamespace IN (SELECT oid FROM pg_namespace WHERE nspname IN ('feature','ops','provider_sync')) AND relkind IN ('r','p','v','m')")"
  feature_total="$(psql_value "SELECT count(*) FROM feature.features")"
  feature_non_deleted="$(psql_value "SELECT count(*) FROM feature.features WHERE status <> 'deleted'")"
  active_owned="$(psql_value "SELECT count(*) FROM feature.features WHERE feature_id LIKE 'e2e\\_live\\_acceptance::${run_id}::%' ESCAPE '\\' AND status <> 'deleted'")"
  nonterminal_owned="$(psql_value "SELECT count(*) FROM ops.feature_change_requests WHERE feature_id LIKE 'e2e\\_live\\_acceptance::${run_id}::%' ESCAPE '\\' AND state = 'pending'")"
  schema_digest="$(schema_sha256)"
  database_digest="$(database_sha256)"
  extension_digest="$(extension_sha256)"
  content_digest="$(
    content_sha256 \
      "$run_id" \
      "$dataset_projection_revision" \
      "$dataset_projection_updated_at"
  )"
  verify_clone_container
  [[ "$(docker inspect --format '{{.Id}}' "$DB_CONTAINER")" == "$before_id" ]] ||
    die "clone DB container changed during snapshot"
  [[ "$(printf '%s' "$(psql_value "SELECT system_identifier::text FROM pg_control_system()")" | sha256sum | awk '{print $1}')" == "$system_sha" ]] ||
    die "clone DB system identifier changed during snapshot"
  if [[ -n "$EXPECTED_MIGRATION_HEAD" ]]; then
    [[ "$migration_head" == "$EXPECTED_MIGRATION_HEAD" ]] ||
      die "clone DB migration head differs from candidate source"
  fi
  if [[ -n "$BASE_CLONE_CONTAINER_SHA256" ]]; then
    [[ "$container_sha" == "$BASE_CLONE_CONTAINER_SHA256" ]] ||
      die "clone DB container differs from baseline"
    [[ "$system_sha" == "$BASE_CLONE_SYSTEM_SHA256" ]] ||
      die "clone DB system differs from baseline"
  fi
  state_helper write-snapshot \
    --path "$path" \
    --active-owned-features "$active_owned" \
    --clone-container-sha256 "$container_sha" \
    --clone-system-identifier-sha256 "$system_sha" \
    --content-cutoff "$CONTENT_CUTOFF" \
    --content-sha256 "$content_digest" \
    --database-sha256 "$database_digest" \
    --extension-sha256 "$extension_digest" \
    --feature-non-deleted "$feature_non_deleted" \
    --feature-total "$feature_total" \
    --host-port "$DB_HOST_PORT" \
    --migration-head "$migration_head" \
    --nonterminal-owned-change-requests "$nonterminal_owned" \
    --relation-count "$relation_count" \
    --schema-sha256 "$schema_digest"
}

TEMPORARY=""
BUILD_CONTEXT=""
RUNTIME_DIR=""
RUN_ID=""
RUN_KEY=""
NETWORK_NAME=""
NETWORK_CREATED_ID=""
API_IMAGE_ID=""
UI_IMAGE_ID=""
PLAYWRIGHT_IMAGE_ID=""
API_IMAGE_TAG=""
UI_IMAGE_TAG=""
PLAYWRIGHT_IMAGE_TAG=""
API_CONTAINER=""
UI_CONTAINER=""
FIXTURE_HELPER="$SCRIPT_DIR/admin_feature_live_fixture.py"
NEW_CHECKPOINT_DUMP=""
CHECKPOINT_SNAPSHOT=""
RESTORED_CHECKPOINT_SNAPSHOT=""
FINAL_CHECKPOINT_SNAPSHOT=""
OLD_CHECKPOINT_DUMP=""
OLD_CHECKPOINT_DUMP_SHA256=""
OLD_CHECKPOINT_DUMP_SIZE=""
VERIFICATION_DB=""
VERIFICATION_DB_TOKEN=""
VERIFICATION_DB_OID=""
VERIFICATION_OWNER_ROLE=""
VERIFICATION_OWNER_ROLE_OID=""
VERIFICATION_DB_OWNED=0
VERIFICATION_ROLE_OWNED=0
readonly VERIFICATION_STATE="$STATE_ROOT/checkpoint-scratch.json"
readonly CHECKPOINT_QUIESCENCE_STATE="$STATE_ROOT/checkpoint-quiescence.json"
CHECKPOINT_QUIESCENCE_APP=""
CHECKPOINT_QUIESCENCE_PROCESS=""
CHECKPOINT_QUIESCENCE_BACKEND_PID=""
CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH=""
CHECKPOINT_FENCE_PASSWORD=""
CHECKPOINT_LOGIN_FENCED=0
CHECKPOINT_DUMP_DURABLE=0
BLOCKED_WRITTEN=0
COMPLETE=0

prepare_loopback_proxy_helper() {
  if [[ -n "$LOOPBACK_PROXY_HELPER" ]]; then
    [[ "$(stat -c '%u:%g:%a' -- "$LOOPBACK_PROXY_HELPER")" == "0:0:444" ]] &&
      [[ ! -L "$LOOPBACK_PROXY_HELPER" ]] ||
      die "installed loopback proxy metadata is unsafe"
    return
  fi

  local archive_member="$ARCHIVE_PREFIX/scripts/c7-loopback-ui-proxy.mjs"
  [[ "$(tar -tzf "$SOURCE_ARCHIVE" "$archive_member")" == "$archive_member" ]] ||
    die "loopback proxy source is absent from the immutable archive"
  local proxy_path="$RUNTIME_DIR/c7-loopback-ui-proxy.mjs"
  if [[ -e "$proxy_path" || -L "$proxy_path" ]]; then
    [[ -f "$proxy_path" && ! -L "$proxy_path" ]] &&
      [[ "$(stat -c '%u:%g:%a' -- "$proxy_path")" == "0:0:444" ]] ||
      die "existing runtime loopback proxy is unsafe"
    # 이전 recover tool이 남긴 root-owned helper는 실행하지 않는다. 현재 immutable
    # archive의 동일 member로 교체해 source commit 간 retry도 fail-closed로 수렴한다.
    rm -f -- "$proxy_path"
  fi
  local temporary_path
  temporary_path="$(mktemp "$RUNTIME_DIR/.c7-loopback-ui-proxy.XXXXXX")"
  tar -xOf "$SOURCE_ARCHIVE" "$archive_member" >"$temporary_path"
  [[ -s "$temporary_path" ]] || die "loopback proxy source is empty"
  chown root:root -- "$temporary_path"
  chmod 0444 -- "$temporary_path"
  mv -T --no-clobber -- "$temporary_path" "$proxy_path" ||
    die "runtime loopback proxy installation failed"
  [[ "$(sha256sum "$proxy_path" | awk '{print $1}')" == "$(tar -xOf "$SOURCE_ARCHIVE" "$archive_member" | sha256sum | awk '{print $1}')" ]] ||
    die "runtime loopback proxy differs from the immutable archive"
  LOOPBACK_PROXY_HELPER="$proxy_path"
}

prepare_build_context() {
  local snapshot_root="$1"
  TEMPORARY="$(mktemp -d /tmp/ktm-admin-feature-clone-live.XXXXXX)"
  BUILD_CONTEXT="$TEMPORARY/build-context"
  mkdir -- "$BUILD_CONTEXT"
  tar --extract --gzip --file "$snapshot_root/source.tar.gz" \
    --directory "$BUILD_CONTEXT" --strip-components=1 \
    --no-same-owner --no-same-permissions
}

build_api_image() {
  docker build --pull=false \
    --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=$SOURCE_COMMIT" \
    --file "$BUILD_CONTEXT/docker/api.Dockerfile" \
    --tag "$API_IMAGE_TAG" \
    "$BUILD_CONTEXT"
  API_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$API_IMAGE_TAG")"
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
      "$API_IMAGE_ID"
  )" == "$SOURCE_COMMIT" ]] || die "API image source revision mismatch"
}

build_ui_image() {
  export NEXT_PUBLIC_VWORLD_API_KEY="$E2E_VWORLD_API_KEY"
  export NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY="$E2E_VWORLD_API_KEY"
  docker build --pull=false \
    --build-arg "KOR_TRAVEL_MAP_GIT_COMMIT=$SOURCE_COMMIT" \
    --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_API=http://candidate-api:$API_PORT" \
    --build-arg "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL=http://candidate-dagster:18702" \
    --build-arg "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL=http://candidate-geo:12501" \
    --build-arg NEXT_PUBLIC_VWORLD_API_KEY \
    --build-arg NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY \
    --file "$BUILD_CONTEXT/docker/frontend.Dockerfile" \
    --tag "$UI_IMAGE_TAG" \
    "$BUILD_CONTEXT"
  unset NEXT_PUBLIC_VWORLD_API_KEY NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY
  UI_IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$UI_IMAGE_TAG")"
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
      "$UI_IMAGE_ID"
  )" == "$SOURCE_COMMIT" ]] || die "UI image source revision mismatch"
}

build_playwright_image() {
  docker build --pull=false \
    --build-arg "C7_REPOSITORY_COMMIT=$SOURCE_COMMIT" \
    --file "$BUILD_CONTEXT/docker/c7-playwright.Dockerfile" \
    --tag "$PLAYWRIGHT_IMAGE_TAG" \
    "$BUILD_CONTEXT"
  PLAYWRIGHT_IMAGE_ID="$(
    docker image inspect --format '{{.Id}}' "$PLAYWRIGHT_IMAGE_TAG"
  )"
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "io.kortravelmap.c7.repository-commit"}}' \
      "$PLAYWRIGHT_IMAGE_ID"
  )" == "$SOURCE_COMMIT" ]] || die "Playwright image source revision mismatch"
}

owned_containers() {
  [[ -n "$RUN_KEY" ]] || {
    printf '0'
    return
  }
  docker ps -aq --no-trunc \
    --filter "label=io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" |
    wc -l
}

remove_owned_containers() {
  [[ -n "$RUN_KEY" ]] || return 0
  local containers
  containers="$(
    docker ps -aq --no-trunc \
      --filter "label=io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY"
  )"
  if [[ -n "$containers" ]]; then
    docker container rm --force -- $containers >/dev/null
  fi
}

clone_network_attached() {
  [[ -n "$NETWORK_NAME" ]] || {
    printf 'false'
    return
  }
  docker inspect --format '{{json .NetworkSettings.Networks}}' "$DB_CONTAINER" |
    NETWORK_TO_FIND="$NETWORK_NAME" python3 -I -B -c '
import json
import os
import sys
print(str(os.environ["NETWORK_TO_FIND"] in json.load(sys.stdin)).lower())
'
}

owned_network_identity() {
  [[ -n "$NETWORK_NAME" && -n "$RUN_KEY" ]] ||
    die "runner-owned network identity is incomplete"
  [[ "$NETWORK_NAME" == "ktm-afcla-${RUN_KEY:0:12}-net" ]] ||
    die "runner-owned network name is invalid"
  local observed_id observed_run_key
  observed_id="$(docker network inspect --format '{{.Id}}' "$NETWORK_NAME")" ||
    return 1
  observed_run_key="$(
    docker network inspect --format \
      '{{index .Labels "io.kortravelmap.admin-feature-clone-acceptance.run-key"}}' \
      "$NETWORK_NAME"
  )"
  [[ "$observed_run_key" == "$RUN_KEY" ]] ||
    die "candidate network ownership label mismatch"
  if [[ -n "$NETWORK_CREATED_ID" ]]; then
    [[ "$observed_id" == "$NETWORK_CREATED_ID" ]] ||
      die "candidate network identity changed"
  fi
  printf '%s' "$observed_id"
}

remove_owned_network() {
  [[ -n "$NETWORK_NAME" ]] || return 0
  if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    return 0
  fi
  local observed_id
  observed_id="$(owned_network_identity)" || return 0
  [[ -n "$observed_id" ]] || die "candidate network identity is empty"
  if [[ "$(clone_network_attached)" == "true" ]]; then
    docker network disconnect "$NETWORK_NAME" "$DB_CONTAINER"
  fi
  docker network rm "$NETWORK_NAME" >/dev/null
  NETWORK_CREATED_ID=""
}

remove_owned_images() {
  remove_owned_image_tag "$API_IMAGE_TAG" "$API_IMAGE_ID"
  remove_owned_image_tag "$UI_IMAGE_TAG" "$UI_IMAGE_ID"
  remove_owned_image_tag "$PLAYWRIGHT_IMAGE_TAG" "$PLAYWRIGHT_IMAGE_ID"
}

remove_owned_image_tag() {
  local tag="$1"
  local expected_id="$2"
  [[ -n "$tag" && -n "$expected_id" ]] || return 0
  local observed_id
  observed_id="$(docker image inspect --format '{{.Id}}' "$tag" 2>/dev/null)" ||
    return 0
  [[ "$observed_id" == "$expected_id" ]] ||
    die "runner-owned image tag was reassigned"
  # ID를 --force 삭제하면 같은 content-addressable image를 참조하는 foreign/cache
  # tag까지 제거한다. 실행별 tag만 비강제로 해제한다.
  docker image rm "$tag" >/dev/null
}

owned_images() {
  local count=0 tag expected_id observed_id
  while IFS='|' read -r tag expected_id; do
    [[ -n "$tag" && -n "$expected_id" ]] || continue
    observed_id="$(docker image inspect --format '{{.Id}}' "$tag" 2>/dev/null)" ||
      continue
    [[ "$observed_id" == "$expected_id" ]] ||
      die "runner-owned image tag was reassigned"
    count=$((count + 1))
  done <<EOF
$API_IMAGE_TAG|$API_IMAGE_ID
$UI_IMAGE_TAG|$UI_IMAGE_ID
$PLAYWRIGHT_IMAGE_TAG|$PLAYWRIGHT_IMAGE_ID
EOF
  printf '%s' "$count"
}

owned_networks() {
  [[ -n "$RUN_KEY" ]] || {
    printf '0'
    return
  }
  docker network ls -q \
    --filter "label=io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" |
    wc -l
}

foreign_cluster_sessions() {
  local owned_backend_filter=""
  if [[ -n "$CHECKPOINT_QUIESCENCE_BACKEND_PID" ||
        -n "$CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH" ]]; then
    [[ "$CHECKPOINT_QUIESCENCE_BACKEND_PID" =~ ^[1-9][0-9]*$ ]] ||
      die "checkpoint quiescence backend PID is invalid"
    [[ "$CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH" =~ ^[0-9]+(\.[0-9]+)?$ ]] ||
      die "checkpoint quiescence backend start is invalid"
    owned_backend_filter="
      AND NOT (
        pid = $CHECKPOINT_QUIESCENCE_BACKEND_PID
        AND extract(epoch FROM backend_start) =
          $CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH
      )"
  fi
  psql_value "
    SELECT count(*)
    FROM pg_catalog.pg_stat_activity
    WHERE pid <> pg_backend_pid()
      AND backend_type = 'client backend'
      $owned_backend_filter
  "
}

checkpoint_login_role_invariant() {
  [[ "$(
    psql_value "
      SELECT count(*)
      FROM pg_catalog.pg_roles
      WHERE rolcanlogin
    "
  )" == "1" ]] || return 1
  [[ "$(
    psql_value "
      SELECT count(*)
      FROM pg_catalog.pg_roles
      WHERE rolcanlogin
        AND rolname = '$db_user'
    "
  )" == "1" ]] || return 1
  [[ "$(
    psql_value "
      SELECT count(*)
      FROM pg_catalog.pg_database AS database
      JOIN pg_catalog.pg_roles AS owner ON owner.oid = database.datdba
      WHERE database.datname = '$ORIGINAL_DB_NAME'
        AND owner.rolname = '$db_user'
    "
  )" == "1" ]]
}

checkpoint_read_only_setting_count() {
  psql_value "
    SELECT count(*)
    FROM pg_catalog.pg_db_role_setting AS setting
    CROSS JOIN LATERAL unnest(setting.setconfig) AS configuration(value)
    WHERE setting.setdatabase = (
      SELECT oid
      FROM pg_catalog.pg_database
      WHERE datname = '$ORIGINAL_DB_NAME'
    )
      AND setting.setrole = 0
      AND configuration.value = 'default_transaction_read_only=on'
  "
}

checkpoint_transaction_setting_count() {
  psql_value "
    SELECT count(*)
    FROM pg_catalog.pg_db_role_setting AS setting
    CROSS JOIN LATERAL unnest(setting.setconfig) AS configuration(value)
    WHERE setting.setdatabase = (
      SELECT oid
      FROM pg_catalog.pg_database
      WHERE datname = '$ORIGINAL_DB_NAME'
    )
      AND setting.setrole = 0
      AND split_part(configuration.value, '=', 1) =
        'default_transaction_read_only'
  "
}

clear_checkpoint_quiescence_state() {
  state_helper clear-quiescence \
    --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
    --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
    --path "$CHECKPOINT_QUIESCENCE_STATE"
}

set_clone_database_password() {
  local role_password="$1"
  KTM_CHECKPOINT_DB_ROLE_PASSWORD="$role_password" \
    PGPASSWORD="$db_password" \
    PGOPTIONS="$PSQL_SESSION_OPTIONS" \
    PGAPPNAME="$PSQL_APP_NAME" \
    docker exec -i \
    -e KTM_CHECKPOINT_DB_ROLE_PASSWORD \
    -e PGPASSWORD \
    -e PGOPTIONS \
    -e PGAPPNAME \
    "$DB_CONTAINER" \
    psql -X -v ON_ERROR_STOP=1 -Atq -U "$db_user" -d "$ORIGINAL_DB_NAME" \
    <<SQL
\getenv checkpoint_role_password KTM_CHECKPOINT_DB_ROLE_PASSWORD
ALTER ROLE "$db_user" PASSWORD :'checkpoint_role_password';
SQL
}

clone_host_tcp_password_works() {
  local role_password="$1"
  PGPASSWORD="$role_password" \
    PGAPPNAME="ktm_checkpoint_tcp_probe" \
    PGCONNECT_TIMEOUT=3 \
    docker run --rm \
    --network host \
    --read-only \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
    -e PGPASSWORD -e PGAPPNAME -e PGCONNECT_TIMEOUT \
    --entrypoint psql \
    "$BASE_CLONE_IMAGE_ID" \
    -X -v ON_ERROR_STOP=1 -Atq \
    -h 127.0.0.1 -p "$DB_HOST_PORT" \
    -U "$db_user" -d "$ORIGINAL_DB_NAME" \
    -c "SELECT 1" >/dev/null 2>&1
}

terminate_checkpoint_backends() {
  local application_name="$1"
  [[ "$application_name" =~ ^ktm_checkpoint_[0-9a-f]{16}$ ]] ||
    die "checkpoint backend application name is invalid"
  local owner_filter="application_name = '$application_name'"
  if [[ -n "$CHECKPOINT_QUIESCENCE_BACKEND_PID" ||
        -n "$CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH" ]]; then
    [[ "$CHECKPOINT_QUIESCENCE_BACKEND_PID" =~ ^[1-9][0-9]*$ ]] ||
      die "checkpoint quiescence backend PID is invalid"
    [[ "$CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH" =~ ^[0-9]+(\.[0-9]+)?$ ]] ||
      die "checkpoint quiescence backend start is invalid"
    owner_filter="
      pid = $CHECKPOINT_QUIESCENCE_BACKEND_PID
      AND extract(epoch FROM backend_start) =
        $CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH"
  fi
  psql_query "
    SELECT pg_catalog.pg_terminate_backend(pid)
    FROM pg_catalog.pg_stat_activity
    WHERE backend_type = 'client backend'
      AND $owner_filter
      AND pid <> pg_backend_pid()
  " >/dev/null
}

terminate_legacy_checkpoint_backends() {
  psql_query "
    SELECT pg_catalog.pg_terminate_backend(pid)
    FROM pg_catalog.pg_stat_activity
    WHERE datname = '$ORIGINAL_DB_NAME'
      AND backend_type = 'client backend'
      AND application_name ~ '^ktm_checkpoint_[0-9a-f]{16}$'
      AND pid <> pg_backend_pid()
  " >/dev/null
}

terminate_foreign_cluster_sessions() {
  psql_query "
    SELECT pg_catalog.pg_terminate_backend(pid)
    FROM pg_catalog.pg_stat_activity
    WHERE backend_type = 'client backend'
      AND pid <> pg_backend_pid()
  " >/dev/null
}

recover_checkpoint_quiescence() {
  local journaled_application journaled_version setting_count
  PSQL_SESSION_OPTIONS="-c default_transaction_read_only=off"
  PSQL_APP_NAME="ktm_checkpoint_recovery"
  if [[ -f "$CHECKPOINT_QUIESCENCE_STATE" &&
        ! -L "$CHECKPOINT_QUIESCENCE_STATE" ]]; then
    [[ "$(state_helper read-quiescence \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field database \
        --path "$CHECKPOINT_QUIESCENCE_STATE"
    )" == "$ORIGINAL_DB_NAME" ]] ||
      die "checkpoint quiescence state DB differs from clone DB"
    journaled_version="$(
      state_helper read-quiescence \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field version \
        --path "$CHECKPOINT_QUIESCENCE_STATE"
    )"
    if [[ "$journaled_version" == "1" ]]; then
      setting_count="$(checkpoint_transaction_setting_count)"
      [[ "$setting_count" == "0" || (
        "$setting_count" == "1" &&
        "$(checkpoint_read_only_setting_count)" == "1"
      ) ]] || die "legacy checkpoint quiescence setting cardinality is invalid"
      terminate_legacy_checkpoint_backends ||
        die "legacy checkpoint backend termination failed"
      if [[ "$setting_count" == "1" ]]; then
        psql_query \
          "ALTER DATABASE \"$ORIGINAL_DB_NAME\" RESET default_transaction_read_only" \
          >/dev/null
      fi
    else
      [[ "$journaled_version" == "2" || "$journaled_version" == "3" ]] ||
        die "checkpoint quiescence version is unsupported"
      journaled_application="$(
        state_helper read-quiescence \
          --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
          --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
          --field application_name \
          --path "$CHECKPOINT_QUIESCENCE_STATE"
      )"
      terminate_checkpoint_backends "$journaled_application" ||
        die "orphaned checkpoint backend termination failed"
      set_clone_database_password "$db_password" ||
        die "checkpoint DB login restoration failed"
      clone_host_tcp_password_works "$db_password" ||
        die "restored checkpoint DB login was not accepted at the host boundary"
    fi
    clear_checkpoint_quiescence_state ||
      die "recovered checkpoint quiescence state cleanup failed"
  else
    [[ ! -e "$CHECKPOINT_QUIESCENCE_STATE" &&
       ! -L "$CHECKPOINT_QUIESCENCE_STATE" ]] ||
      die "checkpoint quiescence state is unsafe"
    [[ "$(checkpoint_transaction_setting_count)" == "0" ]] ||
      die "clone DB has an unowned default_transaction_read_only setting"
    clone_host_tcp_password_works "$db_password" ||
      die "clone DB login differs without an ownership journal at the host boundary"
  fi
  PSQL_SESSION_OPTIONS=""
  PSQL_APP_NAME=""
}

start_database_login_fence() {
  checkpoint_login_role_invariant ||
    die "clone cluster must have exactly the configured LOGIN role"
  CHECKPOINT_QUIESCENCE_APP="ktm_checkpoint_${RUN_KEY:0:16}"
  state_helper write-quiescence \
    --application-name "$CHECKPOINT_QUIESCENCE_APP" \
    --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
    --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
    --database "$ORIGINAL_DB_NAME" \
    --path "$CHECKPOINT_QUIESCENCE_STATE"
  PSQL_APP_NAME="$CHECKPOINT_QUIESCENCE_APP"
  CHECKPOINT_FENCE_PASSWORD="$(openssl rand -hex 32)"
  set_clone_database_password "$CHECKPOINT_FENCE_PASSWORD"
  CHECKPOINT_LOGIN_FENCED=1
  terminate_foreign_cluster_sessions
  checkpoint_login_role_invariant ||
    die "clone cluster LOGIN role invariant changed during login fence"
  clone_host_tcp_password_works "$CHECKPOINT_FENCE_PASSWORD" ||
    die "runner-owned fence password was not accepted at the host boundary"
  if clone_host_tcp_password_works "$db_password"; then
    die "clone DB accepted its original password at the host boundary during login fence"
  fi
  [[ "$(foreign_cluster_sessions)" == "0" ]] ||
    die "clone cluster retained a foreign client after login fencing"
}

assert_database_login_fence() {
  checkpoint_login_role_invariant ||
    die "clone cluster LOGIN role invariant changed during login fence"
  clone_host_tcp_password_works "$CHECKPOINT_FENCE_PASSWORD" ||
    die "runner-owned fence password changed during acceptance"
  if clone_host_tcp_password_works "$db_password"; then
    die "clone DB login fence disappeared during acceptance"
  fi
}

start_checkpoint_quiescence() {
  [[ -z "$CHECKPOINT_QUIESCENCE_PROCESS" ]] ||
    die "checkpoint quiescence is already active"
  start_database_login_fence
  local lock_statements
  lock_statements="$(
    psql_query "
      SELECT format(
        'LOCK TABLE %I.%I IN SHARE MODE;',
        namespace.nspname,
        relation.relname
      )
      FROM pg_catalog.pg_class AS relation
      JOIN pg_catalog.pg_namespace AS namespace
        ON namespace.oid = relation.relnamespace
      WHERE namespace.nspname IN ('feature', 'ops', 'provider_sync')
        AND relation.relkind IN ('r', 'p', 'm')
      ORDER BY namespace.nspname, relation.relname
    "
  )"
  [[ -n "$lock_statements" ]] || die "checkpoint lock relation set is empty"
  PGPASSWORD="$db_password" \
    PGAPPNAME="$CHECKPOINT_QUIESCENCE_APP" \
    docker exec -e PGPASSWORD -e PGAPPNAME "$DB_CONTAINER" \
    psql -X -v ON_ERROR_STOP=1 -Atq -U "$db_user" -d "$db_name" \
    -c "BEGIN; SET LOCAL statement_timeout = 0; $lock_statements SELECT pg_sleep(86400); ROLLBACK;" \
    >/dev/null 2>&1 &
  CHECKPOINT_QUIESCENCE_PROCESS="$!"
  local attempt backend_identity
  for attempt in $(seq 1 300); do
    kill -0 "$CHECKPOINT_QUIESCENCE_PROCESS" 2>/dev/null ||
      die "checkpoint quiescence process exited before acquiring locks"
    backend_identity="$(
      psql_value "
        SELECT pid::text || '|' || extract(epoch FROM backend_start)::text
        FROM pg_catalog.pg_stat_activity
        WHERE datname = current_database()
          AND backend_type = 'client backend'
          AND pid <> pg_backend_pid()
          AND application_name = '$CHECKPOINT_QUIESCENCE_APP'
          AND state = 'active'
          AND wait_event_type = 'Timeout'
          AND wait_event = 'PgSleep'
      "
    )"
    if [[ "$backend_identity" =~ ^([1-9][0-9]*)\|([0-9]+(\.[0-9]+)?)$ ]]; then
      CHECKPOINT_QUIESCENCE_BACKEND_PID="${BASH_REMATCH[1]}"
      CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH="${BASH_REMATCH[2]}"
      [[ "$(foreign_cluster_sessions)" == "0" ]] ||
        die "clone cluster gained a foreign session during checkpoint quiescence"
      return
    fi
    sleep 0.1
  done
  die "checkpoint quiescence locks were not acquired"
}

assert_checkpoint_quiescence() {
  [[ "$CHECKPOINT_QUIESCENCE_PROCESS" =~ ^[0-9]+$ ]] ||
    die "checkpoint quiescence process is missing"
  kill -0 "$CHECKPOINT_QUIESCENCE_PROCESS" 2>/dev/null ||
    die "checkpoint quiescence process exited"
  [[ "$(
    psql_value "
      SELECT count(*)
      FROM pg_catalog.pg_stat_activity
      WHERE datname = current_database()
        AND backend_type = 'client backend'
        AND pid = $CHECKPOINT_QUIESCENCE_BACKEND_PID
        AND extract(epoch FROM backend_start) =
          $CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH
        AND state = 'active'
        AND wait_event_type = 'Timeout'
        AND wait_event = 'PgSleep'
    "
  )" == "1" ]] || die "checkpoint quiescence backend is not holding locks"
  assert_database_login_fence
  [[ "$(foreign_cluster_sessions)" == "0" ]] ||
    die "clone cluster has a foreign session during checkpoint quiescence"
}

start_acceptance_login_fence() {
  [[ -z "$CHECKPOINT_QUIESCENCE_PROCESS" ]] ||
    die "checkpoint quiescence process exists before acceptance"
  start_database_login_fence
}

assert_acceptance_login_fence_after_resources() {
  # candidate containers를 제거한 뒤 남는 연결은 runner-owned가 아니므로 모두 종료하고
  # 새 연결이 original credential로 재진입하지 못하는지 다시 확인한다.
  terminate_foreign_cluster_sessions
  assert_database_login_fence
  [[ "$(foreign_cluster_sessions)" == "0" ]] ||
    die "clone cluster has a foreign session after candidate cleanup"
}

stop_checkpoint_quiescence() {
  if [[ -n "$CHECKPOINT_QUIESCENCE_PROCESS" &&
        -n "$CHECKPOINT_QUIESCENCE_APP" ]]; then
    terminate_checkpoint_backends "$CHECKPOINT_QUIESCENCE_APP" || return 1
    wait "$CHECKPOINT_QUIESCENCE_PROCESS" 2>/dev/null || true
  fi
  CHECKPOINT_QUIESCENCE_PROCESS=""
  CHECKPOINT_QUIESCENCE_BACKEND_PID=""
  CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH=""
  if [[ -f "$CHECKPOINT_QUIESCENCE_STATE" &&
        ! -L "$CHECKPOINT_QUIESCENCE_STATE" ]]; then
    [[ "$(state_helper read-quiescence \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field database \
        --path "$CHECKPOINT_QUIESCENCE_STATE"
    )" == "$ORIGINAL_DB_NAME" ]] ||
      return 1
    [[ "$(state_helper read-quiescence \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field application_name \
        --path "$CHECKPOINT_QUIESCENCE_STATE"
    )" == "$CHECKPOINT_QUIESCENCE_APP" ]] ||
      return 1
    set_clone_database_password "$db_password" || return 1
    clone_host_tcp_password_works "$db_password" || return 1
    if [[ -n "$CHECKPOINT_FENCE_PASSWORD" ]] &&
      clone_host_tcp_password_works "$CHECKPOINT_FENCE_PASSWORD"; then
      return 1
    fi
    clear_checkpoint_quiescence_state || return 1
  elif (( CHECKPOINT_LOGIN_FENCED == 1 )); then
    return 1
  fi
  CHECKPOINT_LOGIN_FENCED=0
  CHECKPOINT_FENCE_PASSWORD=""
  CHECKPOINT_QUIESCENCE_APP=""
  PSQL_SESSION_OPTIONS=""
  PSQL_APP_NAME=""
}

verify_dump_archive() {
  local dump_path="$1"
  docker run --rm \
    --network none \
    --read-only \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --mount "type=bind,src=$dump_path,dst=/checkpoint.dump,readonly" \
    --entrypoint pg_restore \
    "$BASE_CLONE_IMAGE_ID" \
    --list /checkpoint.dump >/dev/null
}

fsync_file_and_directory() {
  local path="$1"
  KTM_FSYNC_PATH="$path" python3 -I -B -c '
import os
from pathlib import Path

path = Path(os.environ["KTM_FSYNC_PATH"])
descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
try:
    os.fsync(directory)
finally:
    os.close(directory)
'
}

drop_verification_database() {
  (( VERIFICATION_DB_OWNED == 1 || VERIFICATION_ROLE_OWNED == 1 )) || return 0
  local scratch_version
  scratch_version="$(
    state_helper read-scratch \
      --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
      --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
      --field version \
      --path "$VERIFICATION_STATE"
  )"
  [[ "$VERIFICATION_DB_TOKEN" =~ ^[0-9a-f]{64}$ ]] ||
    die "checkpoint verification DB token is unsafe"
  [[ "$(state_helper read-scratch \
      --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
      --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
      --field ownership_token \
      --path "$VERIFICATION_STATE"
  )" == "$VERIFICATION_DB_TOKEN" ]] ||
    die "checkpoint verification DB ownership token state is invalid"
  if (( VERIFICATION_DB_OWNED == 1 )); then
    [[ "$VERIFICATION_DB" =~ ^ktm_checkpoint_[0-9a-f]{24}$ ]] ||
      die "checkpoint verification DB name is unsafe"
    [[ "$VERIFICATION_DB_OID" =~ ^[0-9]+$ && "$VERIFICATION_DB_OID" != "0" ]] ||
      die "checkpoint verification DB OID is unsafe"
    [[ "$(state_helper read-scratch \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field database \
        --path "$VERIFICATION_STATE"
    )" == "$VERIFICATION_DB" ]] ||
      die "checkpoint verification DB ownership state is invalid"
    [[ "$(state_helper read-scratch \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field database_oid \
        --path "$VERIFICATION_STATE"
    )" == "$VERIFICATION_DB_OID" ]] ||
      die "checkpoint verification DB ownership OID state is invalid"
    local expected_database_identity
    expected_database_identity="$VERIFICATION_DB_OID:"
    if (( VERIFICATION_ROLE_OWNED == 1 )); then
      expected_database_identity+="$VERIFICATION_OWNER_ROLE_OID:"
    fi
    expected_database_identity+="ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN"
    [[ "$(
      psql_value "
        SELECT oid::text || ':' ||
          CASE
            WHEN datdba = (
              SELECT oid FROM pg_catalog.pg_roles
              WHERE rolname = '$VERIFICATION_OWNER_ROLE'
            ) THEN datdba::text || ':'
            ELSE ''
          END ||
          COALESCE(pg_catalog.shobj_description(oid, 'pg_database'), '')
        FROM pg_catalog.pg_database
        WHERE datname = '$VERIFICATION_DB'
      "
    )" == "$expected_database_identity" ]] ||
      die "checkpoint verification DB server ownership marker is invalid"
    db_name="$ORIGINAL_DB_NAME"
    PGPASSWORD="$db_password" \
      PGAPPNAME="$PSQL_APP_NAME" \
      docker exec -e PGPASSWORD -e PGAPPNAME "$DB_CONTAINER" \
      dropdb --if-exists --force -U "$db_user" "$VERIFICATION_DB" ||
      return 1
  fi
  if (( VERIFICATION_ROLE_OWNED == 1 )); then
    [[ "$VERIFICATION_OWNER_ROLE" =~ ^ktm_checkpoint_owner_[0-9a-f]{24}$ ]] ||
      die "checkpoint verification owner role name is unsafe"
    [[ "$VERIFICATION_OWNER_ROLE_OID" =~ ^[0-9]+$ &&
       "$VERIFICATION_OWNER_ROLE_OID" != "0" ]] ||
      die "checkpoint verification owner role OID is unsafe"
    [[ "$(state_helper read-scratch \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field owner_role \
        --path "$VERIFICATION_STATE"
    )" == "$VERIFICATION_OWNER_ROLE" ]] ||
      die "checkpoint verification owner role state is invalid"
    if [[ "$scratch_version" == "5" ]]; then
      [[ "$(state_helper read-scratch \
          --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
          --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
          --field owner_role_oid \
          --path "$VERIFICATION_STATE"
      )" == "$VERIFICATION_OWNER_ROLE_OID" ]] ||
        die "checkpoint verification owner role OID state is invalid"
    else
      [[ "$scratch_version" == "4" && "$VERIFICATION_DB_OWNED" == "0" ]] ||
        die "checkpoint verification owner role state version is invalid"
    fi
    [[ "$(
      psql_value "
        SELECT concat_ws(
          ':',
          oid,
          rolsuper,
          rolinherit,
          rolcreaterole,
          rolcreatedb,
          rolcanlogin,
          rolreplication,
          rolbypassrls,
          COALESCE(pg_catalog.shobj_description(oid, 'pg_authid'), '')
        )
        FROM pg_catalog.pg_roles
        WHERE rolname = '$VERIFICATION_OWNER_ROLE'
      "
    )" == "$VERIFICATION_OWNER_ROLE_OID:f:f:f:f:f:f:f:ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN" ]] ||
      die "checkpoint verification owner role server identity is invalid"
    psql_query "DROP ROLE \"$VERIFICATION_OWNER_ROLE\"" >/dev/null || return 1
  fi
  state_helper clear-scratch \
    --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
    --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
    --path "$VERIFICATION_STATE" || return 1
  VERIFICATION_DB=""
  VERIFICATION_DB_TOKEN=""
  VERIFICATION_DB_OID=""
  VERIFICATION_OWNER_ROLE=""
  VERIFICATION_OWNER_ROLE_OID=""
  VERIFICATION_DB_OWNED=0
  VERIFICATION_ROLE_OWNED=0
}

recover_verification_database() {
  local database_exists role_exists scratch_version server_identity
  if [[ -f "$VERIFICATION_STATE" && ! -L "$VERIFICATION_STATE" ]]; then
    VERIFICATION_DB="$(
      state_helper read-scratch \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field database \
        --path "$VERIFICATION_STATE"
    )"
    VERIFICATION_DB_TOKEN="$(
      state_helper read-scratch \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field ownership_token \
        --path "$VERIFICATION_STATE"
    )"
    VERIFICATION_OWNER_ROLE="$(
      state_helper read-scratch \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field owner_role \
        --path "$VERIFICATION_STATE" 2>/dev/null || true
    )"
    scratch_version="$(
      state_helper read-scratch \
        --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
        --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
        --field version \
        --path "$VERIFICATION_STATE"
    )"
    database_exists="$(
      psql_value \
        "SELECT count(*) FROM pg_database WHERE datname = '$VERIFICATION_DB'"
    )"
    [[ "$database_exists" == "0" || "$database_exists" == "1" ]] ||
      die "checkpoint verification DB cardinality is invalid"
    if [[ "$scratch_version" == "2" ]]; then
      if [[ "$database_exists" == "1" ]]; then
        server_identity="$(
          psql_value "
            SELECT oid::text || ':' || COALESCE(
              pg_catalog.shobj_description(oid, 'pg_database'), ''
            )
            FROM pg_catalog.pg_database
            WHERE datname = '$VERIFICATION_DB'
          "
        )"
        [[ "$server_identity" =~ ^([0-9]+):ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN$ ]] ||
          die "legacy journaled checkpoint DB lacks its ownership marker"
        VERIFICATION_DB_OID="${BASH_REMATCH[1]}"
        state_helper claim-scratch \
          --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
          --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
          --database-oid "$VERIFICATION_DB_OID" \
          --path "$VERIFICATION_STATE"
        VERIFICATION_DB_OWNED=1
        drop_verification_database
      else
        state_helper clear-scratch \
          --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
          --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
          --path "$VERIFICATION_STATE"
      fi
    elif [[ "$scratch_version" == "3" ]]; then
      if [[ "$database_exists" == "1" ]]; then
        VERIFICATION_DB_OID="$(
          state_helper read-scratch \
            --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
            --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
            --field database_oid \
            --path "$VERIFICATION_STATE"
        )"
        [[ "$(
          psql_value "
            SELECT oid::text || ':' || COALESCE(
              pg_catalog.shobj_description(oid, 'pg_database'), ''
            )
            FROM pg_catalog.pg_database
            WHERE datname = '$VERIFICATION_DB'
          "
        )" == "$VERIFICATION_DB_OID:ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN" ]] ||
          die "journaled checkpoint DB lacks its server ownership marker"
        VERIFICATION_DB_OWNED=1
        drop_verification_database
      else
        state_helper clear-scratch \
          --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
          --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
          --path "$VERIFICATION_STATE"
      fi
    elif [[ "$scratch_version" == "4" || "$scratch_version" == "5" ]]; then
      [[ "$VERIFICATION_OWNER_ROLE" =~ ^ktm_checkpoint_owner_[0-9a-f]{24}$ ]] ||
        die "journaled checkpoint owner role name is invalid"
      role_exists="$(
        psql_value \
          "SELECT count(*) FROM pg_roles WHERE rolname = '$VERIFICATION_OWNER_ROLE'"
      )"
      [[ "$role_exists" == "0" || "$role_exists" == "1" ]] ||
        die "checkpoint verification owner role cardinality is invalid"
      if [[ "$role_exists" == "0" ]]; then
        [[ "$database_exists" == "0" ]] ||
          die "journaled checkpoint owner role disappeared"
        state_helper clear-scratch \
          --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
          --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
          --path "$VERIFICATION_STATE"
      else
        server_identity="$(
          psql_value "
            SELECT concat_ws(
              ':',
              oid,
              rolsuper,
              rolinherit,
              rolcreaterole,
              rolcreatedb,
              rolcanlogin,
              rolreplication,
              rolbypassrls,
              COALESCE(pg_catalog.shobj_description(oid, 'pg_authid'), '')
            )
            FROM pg_catalog.pg_roles
            WHERE rolname = '$VERIFICATION_OWNER_ROLE'
          "
        )"
        [[ "$server_identity" =~ ^([0-9]+):f:f:f:f:f:f:f:ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN$ ]] ||
          die "journaled checkpoint owner role identity is invalid"
        VERIFICATION_OWNER_ROLE_OID="${BASH_REMATCH[1]}"
        VERIFICATION_ROLE_OWNED=1
        if [[ "$database_exists" == "1" ]]; then
          server_identity="$(
            psql_value "
              SELECT oid::text || ':' || datdba::text || ':' ||
                COALESCE(pg_catalog.shobj_description(oid, 'pg_database'), '')
              FROM pg_catalog.pg_database
              WHERE datname = '$VERIFICATION_DB'
            "
          )"
          [[ "$server_identity" =~ ^([0-9]+):$VERIFICATION_OWNER_ROLE_OID:(|ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN)$ ]] ||
            die "journaled checkpoint DB owner differs from owned role"
          VERIFICATION_DB_OID="${BASH_REMATCH[1]}"
          if [[ -z "${BASH_REMATCH[2]}" ]]; then
            psql_query \
              "COMMENT ON DATABASE \"$VERIFICATION_DB\" IS 'ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN'" \
              >/dev/null
          fi
          if [[ "$scratch_version" == "4" ]]; then
            state_helper claim-scratch \
              --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
              --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
              --database-oid "$VERIFICATION_DB_OID" \
              --owner-role-oid "$VERIFICATION_OWNER_ROLE_OID" \
              --path "$VERIFICATION_STATE"
          else
            [[ "$(state_helper read-scratch \
                --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
                --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
                --field database_oid \
                --path "$VERIFICATION_STATE"
            )" == "$VERIFICATION_DB_OID" ]] ||
              die "journaled checkpoint DB OID changed"
            [[ "$(state_helper read-scratch \
                --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
                --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
                --field owner_role_oid \
                --path "$VERIFICATION_STATE"
            )" == "$VERIFICATION_OWNER_ROLE_OID" ]] ||
              die "journaled checkpoint owner role OID changed"
          fi
          VERIFICATION_DB_OWNED=1
        fi
        drop_verification_database
      fi
    else
      die "checkpoint verification scratch version is unsupported"
    fi
    VERIFICATION_DB=""
    VERIFICATION_DB_TOKEN=""
    VERIFICATION_DB_OID=""
    VERIFICATION_OWNER_ROLE=""
    VERIFICATION_OWNER_ROLE_OID=""
    VERIFICATION_DB_OWNED=0
    VERIFICATION_ROLE_OWNED=0
  else
    [[ "$(
      psql_value \
        "SELECT count(*) FROM pg_database WHERE datname LIKE 'ktm_checkpoint_%'"
    )" == "0" ]] || die "unowned checkpoint verification DB exists"
  fi
  [[ "$(
    psql_value \
      "SELECT count(*) FROM pg_database WHERE datname LIKE 'ktm_checkpoint_%'"
  )" == "0" ]] ||
    die "unexpected checkpoint verification DB exists"
  [[ "$(
    psql_value \
      "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'ktm_checkpoint_owner_%'"
  )" == "0" ]] ||
    die "unexpected checkpoint verification owner role exists"
}

copy_database_settings_to_verification() {
  [[ "$VERIFICATION_DB" =~ ^ktm_checkpoint_[0-9a-f]{24}$ ]] ||
    die "checkpoint verification DB name is unsafe"
  local statements
  statements="$(
    psql_query "
      SELECT CASE
        WHEN setting.setrole = 0 THEN format(
          'ALTER DATABASE %I SET %I = %s;',
          '$VERIFICATION_DB',
          split_part(configuration.value, '=', 1),
          substring(
            configuration.value
            FROM length(split_part(configuration.value, '=', 1)) + 2
          )
        )
        ELSE format(
          'ALTER ROLE %I IN DATABASE %I SET %I = %s;',
          setting.setrole::regrole::text,
          '$VERIFICATION_DB',
          split_part(configuration.value, '=', 1),
          substring(
            configuration.value
            FROM length(split_part(configuration.value, '=', 1)) + 2
          )
        )
      END
      FROM pg_catalog.pg_db_role_setting AS setting
      CROSS JOIN LATERAL unnest(setting.setconfig) AS configuration(value)
      WHERE setting.setdatabase = (
        SELECT oid
        FROM pg_catalog.pg_database
        WHERE datname = current_database()
      )
      ORDER BY setting.setrole, configuration.value
    "
  )"
  [[ -z "$statements" ]] || printf '%s\n' "$statements" | psql_stream >/dev/null
}

verify_dump_restore() {
  local dump_path="$1"
  local restored_snapshot="$2"
  VERIFICATION_DB="ktm_checkpoint_$(openssl rand -hex 12)"
  VERIFICATION_DB_TOKEN="$(openssl rand -hex 32)"
  VERIFICATION_OWNER_ROLE="ktm_checkpoint_owner_$(openssl rand -hex 12)"
  [[ "$(psql_value "SELECT count(*) FROM pg_database WHERE datname = '$VERIFICATION_DB'")" == "0" ]] ||
    die "checkpoint verification DB already exists"
  [[ "$(psql_value "SELECT count(*) FROM pg_roles WHERE rolname = '$VERIFICATION_OWNER_ROLE'")" == "0" ]] ||
    die "checkpoint verification owner role already exists"
  state_helper write-scratch \
    --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
    --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
    --database "$VERIFICATION_DB" \
    --ownership-token "$VERIFICATION_DB_TOKEN" \
    --owner-role "$VERIFICATION_OWNER_ROLE" \
    --path "$VERIFICATION_STATE"
  psql_query "
    BEGIN;
    CREATE ROLE \"$VERIFICATION_OWNER_ROLE\"
      NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT
      NOREPLICATION NOBYPASSRLS;
    COMMENT ON ROLE \"$VERIFICATION_OWNER_ROLE\"
      IS 'ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN';
    COMMIT;
  " >/dev/null
  VERIFICATION_OWNER_ROLE_OID="$(
    psql_value \
      "SELECT oid::text FROM pg_roles WHERE rolname = '$VERIFICATION_OWNER_ROLE'"
  )"
  [[ "$VERIFICATION_OWNER_ROLE_OID" =~ ^[0-9]+$ &&
     "$VERIFICATION_OWNER_ROLE_OID" != "0" ]] ||
    die "checkpoint verification owner role OID was not observed"
  VERIFICATION_ROLE_OWNED=1
  PGPASSWORD="$db_password" \
    PGAPPNAME="$PSQL_APP_NAME" \
    docker exec -e PGPASSWORD -e PGAPPNAME "$DB_CONTAINER" \
    createdb -U "$db_user" --template=template0 \
    --owner="$VERIFICATION_OWNER_ROLE" "$VERIFICATION_DB"
  VERIFICATION_DB_OWNED=1
  psql_query \
    "COMMENT ON DATABASE \"$VERIFICATION_DB\" IS 'ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN'" \
    >/dev/null
  VERIFICATION_DB_OID="$(
    psql_value \
      "SELECT oid::text FROM pg_catalog.pg_database WHERE datname = '$VERIFICATION_DB'"
  )"
  [[ "$VERIFICATION_DB_OID" =~ ^[0-9]+$ && "$VERIFICATION_DB_OID" != "0" ]] ||
    die "checkpoint verification DB OID was not observed"
  [[ "$(
    psql_value "
      SELECT oid::text || ':' || datdba::text || ':' || COALESCE(
        pg_catalog.shobj_description(oid, 'pg_database'), ''
      )
      FROM pg_catalog.pg_database
      WHERE datname = '$VERIFICATION_DB'
    "
  )" == "$VERIFICATION_DB_OID:$VERIFICATION_OWNER_ROLE_OID:ktm-checkpoint-owner:$VERIFICATION_DB_TOKEN" ]] ||
    die "checkpoint verification DB server ownership marker was not written"
  state_helper claim-scratch \
    --clone-container-sha256 "$BASE_CLONE_CONTAINER_SHA256" \
    --clone-system-identifier-sha256 "$BASE_CLONE_SYSTEM_SHA256" \
    --database-oid "$VERIFICATION_DB_OID" \
    --owner-role-oid "$VERIFICATION_OWNER_ROLE_OID" \
    --path "$VERIFICATION_STATE"
  copy_database_settings_to_verification
  PGPASSWORD="$db_password" \
    PGAPPNAME="$PSQL_APP_NAME" \
    docker exec -i -e PGPASSWORD -e PGAPPNAME "$DB_CONTAINER" \
    pg_restore --exit-on-error --single-transaction \
    -U "$db_user" -d "$VERIFICATION_DB" <"$dump_path"
  db_name="$VERIFICATION_DB"
  write_snapshot "$restored_snapshot" "$RUN_ID"
  db_name="$ORIGINAL_DB_NAME"
  drop_verification_database
}

checkpoint_path_references_dump() {
  local checkpoint_path="$1"
  local dump_path="$2"
  local filename
  [[ -f "$checkpoint_path" && ! -L "$checkpoint_path" ]] || return 1
  filename="$(
    state_helper read-checkpoint \
      --checkpoint "$checkpoint_path" --field dump_filename 2>/dev/null
  )" || return 1
  [[ "$STATE_ROOT/$filename" == "$dump_path" ]]
}

checkpoint_references_dump() {
  local dump_path="$1"
  checkpoint_path_references_dump "$CHECKPOINT_FILE" "$dump_path" && return 0
  [[ -n "$RUNTIME_DIR" ]] || return 1
  checkpoint_path_references_dump \
    "$RUNTIME_DIR/clone-checkpoint.json" "$dump_path"
}

remove_unreferenced_checkpoint_dumps() {
  local dump_path
  while IFS= read -r -d '' dump_path; do
    [[ "$dump_path" == "$NEW_CHECKPOINT_DUMP" ]] && continue
    [[ "$dump_path" =~ ^${STATE_ROOT}/clone-checkpoint-[0-9a-f]{64}\.dump$ &&
       -f "$dump_path" && ! -L "$dump_path" ]] ||
      die "unreferenced checkpoint dump path is unsafe"
    [[ "$(stat -c '%u:%g:%a' -- "$dump_path")" == "0:0:600" ]] ||
      die "unreferenced checkpoint dump metadata is unsafe"
    checkpoint_references_dump "$dump_path" && continue
    rm -- "$dump_path"
  done < <(
    find "$STATE_ROOT" -maxdepth 1 \
      -name 'clone-checkpoint-????????????????????????????????????????????????????????????????.dump' \
      -print0
  )
}

select_reusable_checkpoint_dump() {
  local excluded_path="$1"
  local excluded_sha256="$2"
  local excluded_size="$3"
  local -a candidates=()
  local candidate candidate_size
  [[ -z "$excluded_sha256" || "$excluded_sha256" =~ ^[0-9a-f]{64}$ ]] ||
    die "excluded checkpoint dump SHA256 is unsafe"
  [[ -z "$excluded_size" || "$excluded_size" =~ ^[1-9][0-9]*$ ]] ||
    die "excluded checkpoint dump size is unsafe"
  while IFS= read -r -d '' candidate; do
    [[ "$candidate" =~ ^${STATE_ROOT}/clone-checkpoint-[0-9a-f]{64}\.dump$ &&
       -f "$candidate" && ! -L "$candidate" ]] ||
      die "checkpoint dump resume path is unsafe"
    [[ "$(stat -c '%u:%g:%a' -- "$candidate")" == "0:0:600" ]] ||
      die "checkpoint dump resume metadata is unsafe"
    [[ -z "$excluded_path" || "$candidate" != "$excluded_path" ]] || continue
    candidate_size="$(stat -Lc '%s' -- "$candidate")"
    if [[ -n "$excluded_sha256" && "$candidate_size" == "$excluded_size" ]] &&
      [[ "$(sha256sum -- "$candidate" | awk '{print $1}')" == "$excluded_sha256" ]]; then
      continue
    fi
    candidates+=("$candidate")
  done < <(
    find "$STATE_ROOT" -maxdepth 1 \
      -name 'clone-checkpoint-????????????????????????????????????????????????????????????????.dump' \
      -print0
  )
  (( ${#candidates[@]} <= 1 )) ||
    die "checkpoint dump resume is ambiguous"
  if (( ${#candidates[@]} == 1 )); then
    printf '%s' "${candidates[0]}"
  fi
}

verify_checkpoint_dump() {
  local checkpoint_path="$1"
  local filename expected_sha expected_size dump_path
  filename="$(
    state_helper read-checkpoint \
      --checkpoint "$checkpoint_path" --field dump_filename
  )"
  expected_sha="$(
    state_helper read-checkpoint \
      --checkpoint "$checkpoint_path" --field dump_sha256
  )"
  expected_size="$(
    state_helper read-checkpoint \
      --checkpoint "$checkpoint_path" --field dump_size
  )"
  dump_path="$STATE_ROOT/$filename"
  [[ "$dump_path" == "$STATE_ROOT"/clone-checkpoint-*.dump ]] ||
    die "checkpoint dump path is unsafe"
  [[ -f "$dump_path" && ! -L "$dump_path" ]] ||
    die "checkpoint dump is missing"
  [[ "$(stat -c '%u:%g:%a' -- "$dump_path")" == "0:0:600" ]] ||
    die "checkpoint dump metadata is unsafe"
  [[ "$(stat -Lc '%s' -- "$dump_path")" == "$expected_size" ]] ||
    die "checkpoint dump size differs from signed provenance"
  [[ "$(sha256sum -- "$dump_path" | awk '{print $1}')" == "$expected_sha" ]] ||
    die "checkpoint dump digest differs from signed provenance"
  verify_dump_archive "$dump_path"
}

refresh_blocked_written_from_durable_state() {
  (( COMPLETE == 0 && BLOCKED_WRITTEN == 0 )) || return 0
  [[ -n "$RUN_KEY" && -f "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] || return 0
  [[ "$(stat -c '%u:%g:%a' -- "$BLOCKED_FILE")" == "0:0:600" ]] || return 0
  local durable_run_key
  durable_run_key="$(
    state_helper read-blocked --path "$BLOCKED_FILE" --field run_key 2>/dev/null
  )" || return 0
  [[ "$durable_run_key" == "$RUN_KEY" ]] || return 0
  BLOCKED_WRITTEN=1
}

cleanup_on_exit() {
  local status=$?
  trap - EXIT INT TERM
  set +e
  # write-blocked의 atomic replace 직후 signal이 와도 메모리 flag보다 durable state를
  # 정본으로 삼아 recovery용 runtime/image를 보존한다.
  refresh_blocked_written_from_durable_state
  remove_owned_containers
  remove_owned_network
  stop_checkpoint_quiescence
  if (( BLOCKED_WRITTEN == 0 || COMPLETE == 1 )); then
    remove_owned_images
  fi
  if [[ -n "$TEMPORARY" && -d "$TEMPORARY" ]]; then
    safe_remove_temporary "$TEMPORARY"
  fi
  drop_verification_database
  if (( BLOCKED_WRITTEN == 0 && COMPLETE == 0 )) &&
    [[ -n "$RUNTIME_DIR" && -d "$RUNTIME_DIR" ]]; then
    rm -rf -- "$RUNTIME_DIR"
  fi
  if (( COMPLETE == 0 )) &&
    (( CHECKPOINT_DUMP_DURABLE == 0 )) &&
    [[ -n "$NEW_CHECKPOINT_DUMP" &&
       "$NEW_CHECKPOINT_DUMP" == "$STATE_ROOT"/clone-checkpoint-*.dump &&
       -f "$NEW_CHECKPOINT_DUMP" && ! -L "$NEW_CHECKPOINT_DUMP" ]] &&
    ! checkpoint_references_dump "$NEW_CHECKPOINT_DUMP"; then
    rm -f -- "$NEW_CHECKPOINT_DUMP"
  fi
  if (( COMPLETE == 0 )) &&
    [[ -n "$CHECKPOINT_SNAPSHOT" &&
       "$CHECKPOINT_SNAPSHOT" == "$STATE_ROOT"/.clone-checkpoint-snapshot-*.json &&
       -f "$CHECKPOINT_SNAPSHOT" && ! -L "$CHECKPOINT_SNAPSHOT" ]]; then
    rm -f -- "$CHECKPOINT_SNAPSHOT"
  fi
  if (( COMPLETE == 0 )) &&
    [[ -n "$RESTORED_CHECKPOINT_SNAPSHOT" &&
       "$RESTORED_CHECKPOINT_SNAPSHOT" == "$STATE_ROOT"/.clone-checkpoint-restored-*.json &&
       -f "$RESTORED_CHECKPOINT_SNAPSHOT" &&
       ! -L "$RESTORED_CHECKPOINT_SNAPSHOT" ]]; then
    rm -f -- "$RESTORED_CHECKPOINT_SNAPSHOT"
  fi
  if (( COMPLETE == 0 )) &&
    [[ -n "$FINAL_CHECKPOINT_SNAPSHOT" &&
       "$FINAL_CHECKPOINT_SNAPSHOT" == "$STATE_ROOT"/.clone-checkpoint-final-*.json &&
       -f "$FINAL_CHECKPOINT_SNAPSHOT" &&
       ! -L "$FINAL_CHECKPOINT_SNAPSHOT" ]]; then
    rm -f -- "$FINAL_CHECKPOINT_SNAPSHOT"
  fi
  exit "$status"
}
trap cleanup_on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$MODE" == "baseline" || "$MODE" == "checkpoint" ]]; then
  [[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "BLOCKED state must be recovered before checkpoint"
  RUN_ID="checkpoint-$(date -u +%Y%m%d%H%M%S)-$(openssl rand -hex 6)"
  RUN_KEY="$(printf '%s' "$RUN_ID" | sha256sum | awk '{print $1}')"
  API_IMAGE_TAG="kor-travel-map-clone-live-api:${SOURCE_COMMIT:0:12}-checkpoint-${RUN_KEY:0:12}"
  prepare_build_context "$SCRIPT_DIR"
  build_api_image
  EXPECTED_MIGRATION_HEAD="$(read_image_migration_head "$API_IMAGE_ID")"
  BASE_CLONE_CONTAINER_SHA256="$(
    printf '%s' "$BASE_CLONE_CONTAINER_ID" | sha256sum | awk '{print $1}'
  )"
  BASE_CLONE_SYSTEM_SHA256="$(
    printf '%s' "$(psql_value "SELECT system_identifier::text FROM pg_control_system()")" |
      sha256sum | awk '{print $1}'
  )"
  recover_checkpoint_quiescence
  recover_verification_database
  existing_checkpoint_version=""
  if [[ -f "$CHECKPOINT_FILE" && ! -L "$CHECKPOINT_FILE" ]]; then
    existing_checkpoint_version="$(
      KTM_CHECKPOINT_PATH="$CHECKPOINT_FILE" python3 -I -B -c '
import json
import os
from pathlib import Path

value = json.loads(Path(os.environ["KTM_CHECKPOINT_PATH"]).read_text())["version"]
if not isinstance(value, int) or isinstance(value, bool):
    raise SystemExit("invalid checkpoint version")
print(value)
'
    )"
    if [[ "$existing_checkpoint_version" == "1" ]]; then
      old_dump_filename="$(
        state_helper read-replaced-checkpoint-dump \
          --checkpoint "$CHECKPOINT_FILE"
      )"
      if [[ -n "$old_dump_filename" ]]; then
        OLD_CHECKPOINT_DUMP="$STATE_ROOT/$old_dump_filename"
        [[ "$OLD_CHECKPOINT_DUMP" == "$STATE_ROOT"/clone-checkpoint-*.dump ]] ||
          die "replaced checkpoint dump path is unsafe"
      fi
      OLD_CHECKPOINT_DUMP_SHA256="$(
        state_helper read-replaced-checkpoint-dump \
          --checkpoint "$CHECKPOINT_FILE" --field sha256
      )"
      OLD_CHECKPOINT_DUMP_SIZE="$(
        state_helper read-replaced-checkpoint-dump \
          --checkpoint "$CHECKPOINT_FILE" --field size
      )"
    elif [[ "$existing_checkpoint_version" == "2" ||
            "$existing_checkpoint_version" == "3" ||
            "$existing_checkpoint_version" == "4" ||
            "$existing_checkpoint_version" == "5" ]]; then
      [[ "$MODE" == "baseline" || "$existing_checkpoint_version" != "5" ]] ||
        die "full restore certification cannot reuse a baseline-only checkpoint"
      [[ "$(state_helper read-checkpoint \
          --checkpoint "$CHECKPOINT_FILE" --field version
      )" == "$existing_checkpoint_version" ]] ||
        die "existing checkpoint version validation changed"
      verify_checkpoint_dump "$CHECKPOINT_FILE"
      remove_unreferenced_checkpoint_dumps
      CONTENT_CUTOFF="$(
        state_helper read-checkpoint \
          --checkpoint "$CHECKPOINT_FILE" --field content_cutoff
      )"
      FINAL_CHECKPOINT_SNAPSHOT="$STATE_ROOT/.clone-checkpoint-final-$$.json"
      start_checkpoint_quiescence
      assert_checkpoint_quiescence
      write_snapshot "$FINAL_CHECKPOINT_SNAPSHOT" "$RUN_ID"
      state_helper verify-checkpoint \
        --checkpoint "$CHECKPOINT_FILE" \
        --snapshot "$FINAL_CHECKPOINT_SNAPSHOT" >/dev/null
      if [[ "$existing_checkpoint_version" == "2" ||
            "$existing_checkpoint_version" == "3" ]]; then
        state_helper promote-checkpoint \
          --checkpoint "$CHECKPOINT_FILE" \
          --final-snapshot "$FINAL_CHECKPOINT_SNAPSHOT" \
          --path "$CHECKPOINT_FILE"
        existing_checkpoint_version="4"
      fi
      assert_checkpoint_quiescence
      verify_checkpoint_dump "$CHECKPOINT_FILE"
      remove_unreferenced_checkpoint_dumps
      COMPLETE=1
      rm -- "$FINAL_CHECKPOINT_SNAPSHOT"
      stop_checkpoint_quiescence
      remove_owned_images
      printf 'admin feature clone live checkpoint reused: source=%s version=%s checkpoint=%s\n' \
        "$SOURCE_COMMIT" "$existing_checkpoint_version" "$CHECKPOINT_FILE"
      exit 0
    else
      die "existing checkpoint version is unsupported"
    fi
  fi
  CONTENT_CUTOFF="$(
    psql_value \
      "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"
  )"
  CHECKPOINT_SNAPSHOT="$STATE_ROOT/.clone-checkpoint-snapshot-$$.json"
  RESTORED_CHECKPOINT_SNAPSHOT="$STATE_ROOT/.clone-checkpoint-restored-$$.json"
  FINAL_CHECKPOINT_SNAPSHOT="$STATE_ROOT/.clone-checkpoint-final-$$.json"
  start_checkpoint_quiescence
  assert_checkpoint_quiescence
  write_snapshot "$CHECKPOINT_SNAPSHOT" "$RUN_ID"
  [[ "$(psql_value "SELECT count(*) FROM feature.features WHERE feature_id LIKE 'e2e\\_live\\_acceptance::%' ESCAPE '\\' AND status <> 'deleted'")" == "0" ]] ||
    die "clone checkpoint has active acceptance Feature residue"
  [[ "$(psql_value "SELECT count(*) FROM ops.feature_change_requests WHERE feature_id LIKE 'e2e\\_live\\_acceptance::%' ESCAPE '\\' AND state = 'pending'")" == "0" ]] ||
    die "clone checkpoint has pending acceptance change request residue"
  assert_checkpoint_quiescence
  NEW_CHECKPOINT_DUMP="$(
    select_reusable_checkpoint_dump \
      "$OLD_CHECKPOINT_DUMP" \
      "$OLD_CHECKPOINT_DUMP_SHA256" \
      "$OLD_CHECKPOINT_DUMP_SIZE"
  )"
  if [[ -n "$NEW_CHECKPOINT_DUMP" ]]; then
    CHECKPOINT_DUMP_DURABLE=1
  else
    NEW_CHECKPOINT_DUMP="$STATE_ROOT/clone-checkpoint-$RUN_KEY.dump"
    [[ ! -e "$NEW_CHECKPOINT_DUMP" && ! -L "$NEW_CHECKPOINT_DUMP" ]] ||
      die "checkpoint dump target already exists"
    PGPASSWORD="$db_password" \
      PGAPPNAME="$PSQL_APP_NAME" \
      docker exec -e PGPASSWORD -e PGAPPNAME "$DB_CONTAINER" \
      pg_dump --format=custom \
      --serializable-deferrable -U "$db_user" -d "$db_name" \
      >"$NEW_CHECKPOINT_DUMP"
    chown root:root -- "$NEW_CHECKPOINT_DUMP"
    chmod 0600 -- "$NEW_CHECKPOINT_DUMP"
    fsync_file_and_directory "$NEW_CHECKPOINT_DUMP"
    CHECKPOINT_DUMP_DURABLE=1
  fi
  assert_checkpoint_quiescence
  verify_dump_archive "$NEW_CHECKPOINT_DUMP"
  dump_before="$(stat -Lc '%d:%i:%s:%Y' -- "$NEW_CHECKPOINT_DUMP")"
  dump_size="$(stat -Lc '%s' -- "$NEW_CHECKPOINT_DUMP")"
  dump_sha256="$(sha256sum -- "$NEW_CHECKPOINT_DUMP" | awk '{print $1}')"
  [[ "$(stat -Lc '%d:%i:%s:%Y' -- "$NEW_CHECKPOINT_DUMP")" == "$dump_before" ]] ||
    die "clone dump changed during checkpoint hashing"
  if [[ "$MODE" == "checkpoint" ]]; then
    verify_dump_restore "$NEW_CHECKPOINT_DUMP" "$RESTORED_CHECKPOINT_SNAPSHOT"
    assert_checkpoint_quiescence
    write_snapshot "$FINAL_CHECKPOINT_SNAPSHOT" "$RUN_ID"
    assert_checkpoint_quiescence
  fi
  [[ "$(stat -Lc '%d:%i:%s:%Y' -- "$NEW_CHECKPOINT_DUMP")" == "$dump_before" ]] ||
    die "clone dump changed during restore verification"
  [[ "$(sha256sum -- "$NEW_CHECKPOINT_DUMP" | awk '{print $1}')" == "$dump_sha256" ]] ||
    die "clone dump digest changed during restore verification"
  if [[ -z "$OLD_CHECKPOINT_DUMP" &&
        -f "$CHECKPOINT_FILE" && ! -L "$CHECKPOINT_FILE" ]]; then
    old_dump_filename="$(
      state_helper read-replaced-checkpoint-dump --checkpoint "$CHECKPOINT_FILE"
    )"
    if [[ -n "$old_dump_filename" ]]; then
      OLD_CHECKPOINT_DUMP="$STATE_ROOT/$old_dump_filename"
      [[ "$OLD_CHECKPOINT_DUMP" == "$STATE_ROOT"/clone-checkpoint-*.dump ]] ||
        die "replaced checkpoint dump path is unsafe"
    fi
  fi
  if [[ "$MODE" == "checkpoint" ]]; then
    state_helper write-checkpoint \
      --dump-filename "$(basename -- "$NEW_CHECKPOINT_DUMP")" \
      --dump-sha256 "$dump_sha256" \
      --dump-size "$dump_size" \
      --final-snapshot "$FINAL_CHECKPOINT_SNAPSHOT" \
      --path "$CHECKPOINT_FILE" \
      --restored-snapshot "$RESTORED_CHECKPOINT_SNAPSHOT" \
      --snapshot "$CHECKPOINT_SNAPSHOT"
  else
    state_helper write-baseline-checkpoint \
      --dump-filename "$(basename -- "$NEW_CHECKPOINT_DUMP")" \
      --dump-sha256 "$dump_sha256" \
      --dump-size "$dump_size" \
      --path "$CHECKPOINT_FILE" \
      --snapshot "$CHECKPOINT_SNAPSHOT"
  fi
  COMPLETE=1
  CHECKPOINT_DUMP_DURABLE=0
  rm -- "$CHECKPOINT_SNAPSHOT"
  if [[ "$MODE" == "checkpoint" ]]; then
    rm -- "$RESTORED_CHECKPOINT_SNAPSHOT" "$FINAL_CHECKPOINT_SNAPSHOT"
  fi
  if [[ -n "$OLD_CHECKPOINT_DUMP" &&
        "$OLD_CHECKPOINT_DUMP" != "$NEW_CHECKPOINT_DUMP" &&
        -f "$OLD_CHECKPOINT_DUMP" && ! -L "$OLD_CHECKPOINT_DUMP" ]]; then
    rm -- "$OLD_CHECKPOINT_DUMP"
  fi
  remove_unreferenced_checkpoint_dumps
  assert_checkpoint_quiescence
  stop_checkpoint_quiescence
  remove_owned_images
  printf 'admin feature clone live %s complete: source=%s checkpoint=%s\n' \
    "$MODE" "$SOURCE_COMMIT" "$CHECKPOINT_FILE"
  exit 0
fi

readonly_candidate_secrets() {
  admin_secret="$(printf '%s' "$RUN_ID:admin" | sha256sum | awk '{print $1}')"
  service_token="$(printf '%s' "$RUN_ID:service" | sha256sum | awk '{print $1}')"
  cursor_secret="$(printf '%s' "$RUN_ID:cursor" | sha256sum | awk '{print $1}')"
  session_secret="$(printf '%s' "$RUN_ID:session" | sha256sum | awk '{print $1}')"
  password_hash="$(
    KTM_E2E_ADMIN_PASSWORD="$E2E_ADMIN_PASSWORD" \
      KTM_E2E_RUN_ID="$RUN_ID" \
      python3 -I -B -c '
import base64
import hashlib
import os
password = os.environ["KTM_E2E_ADMIN_PASSWORD"]
run_id = os.environ["KTM_E2E_RUN_ID"]
salt = hashlib.sha256(f"{run_id}:password-salt".encode()).digest()[:16]
digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000, 32)
encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
print(f"pbkdf2_sha256$310000${encode(salt)}${encode(digest)}")
'
  )"
}

create_candidate_network() {
  local create_output="" create_status=0
  create_output="$(
    docker network create --internal \
      --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
      "$NETWORK_NAME"
  )" || create_status=$?
  if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    NETWORK_CREATED_ID="$(owned_network_identity)"
  fi
  (( create_status == 0 )) ||
    die "candidate network create returned failure after ownership inspection"
  [[ -n "$NETWORK_CREATED_ID" && "$create_output" == "$NETWORK_CREATED_ID" ]] ||
    die "candidate network create identity mismatch"
  [[ "$(docker network inspect --format '{{.Internal}}' "$NETWORK_NAME")" == "true" ]] ||
    die "candidate network is not internal"
  docker network connect --alias clone-db "$NETWORK_NAME" "$DB_CONTAINER"
  NETWORK_CIDR="$(
    docker network inspect --format '{{(index .IPAM.Config 0).Subnet}}' "$NETWORK_NAME"
  )"
  [[ "$NETWORK_CIDR" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$ ]] ||
    die "candidate network subnet is invalid"
}

assert_candidate_container() {
  local name="$1"
  local image_id="$2"
  [[ "$(docker inspect --format '{{.State.Running}}' "$name")" == "true" ]] ||
    die "candidate container stopped"
  [[ "$(docker inspect --format '{{.Image}}' "$name")" == "$image_id" ]] ||
    die "candidate container image identity mismatch"
  [[ "$(
    docker inspect --format \
      "{{if index .NetworkSettings.Networks \"$NETWORK_NAME\"}}true{{else}}false{{end}}" \
      "$name"
  )" == "true" ]] || die "candidate container network mismatch"
}

start_candidate_services() {
  readonly_candidate_secrets
  local internal_dsn
  internal_dsn="$(make_dsn clone-db 5432)"
  export KOR_TRAVEL_MAP_PG_DSN="$internal_dsn"
  export KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET="$admin_secret"
  export KOR_TRAVEL_MAP_API_SERVICE_TOKEN="$service_token"
  export KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET="$cursor_secret"
  export KOR_TRAVEL_MAP_API_VWORLD_API_KEY="$E2E_VWORLD_API_KEY"
  API_CONTAINER="ktm-afcla-${RUN_KEY:0:12}-api"
  docker run -d \
    --name "$API_CONTAINER" \
    --network "$NETWORK_NAME" \
    --network-alias candidate-api \
    --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
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
    --env KOR_TRAVEL_MAP_API_HOST=0.0.0.0 \
    --env "KOR_TRAVEL_MAP_API_PORT=$API_PORT" \
    --env KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true \
    --env KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED=true \
    --env KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false \
    --env KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED=false \
    --env KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED=true \
    --env KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED=true \
    --env KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED=false \
    --env KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=false \
    --env "KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS=[\"$NETWORK_CIDR\"]" \
    --entrypoint python \
    "$API_IMAGE_ID" \
    -m uvicorn kortravelmap.api.app:app --host 0.0.0.0 --port "$API_PORT" \
    >/dev/null
  for _ in $(seq 1 90); do
    if assert_candidate_container "$API_CONTAINER" "$API_IMAGE_ID" 2>/dev/null &&
      docker exec "$API_CONTAINER" python -I -B -c \
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$API_PORT/health', timeout=2).read()" \
        >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  assert_candidate_container "$API_CONTAINER" "$API_IMAGE_ID"
  docker exec "$API_CONTAINER" python -I -B -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:$API_PORT/health', timeout=2).read()" \
    >/dev/null || die "candidate API health check failed"
  docker exec "$API_CONTAINER" python -I -B -c \
    "import json, urllib.request; spec=json.load(urllib.request.urlopen('http://127.0.0.1:$API_PORT/openapi.json', timeout=2)); assert 'post' in spec.get('paths', {}).get('/v1/admin/features', {})" \
    >/dev/null || die "candidate API admin feature create route is not mounted"

  export KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH="$password_hash"
  export KOR_TRAVEL_MAP_UI_SESSION_SECRET="$session_secret"
  UI_CONTAINER="ktm-afcla-${RUN_KEY:0:12}-ui"
  docker run -d \
    --name "$UI_CONTAINER" \
    --network "$NETWORK_NAME" \
    --network-alias candidate-ui \
    --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
    --read-only \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --env "PORT=$UI_PORT" \
    --env HOSTNAME=0.0.0.0 \
    --env "NEXT_PUBLIC_KOR_TRAVEL_MAP_API=http://candidate-api:$API_PORT" \
    --env "KOR_TRAVEL_MAP_API_INTERNAL_URL=http://candidate-api:$API_PORT" \
    --env KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET \
    --env KOR_TRAVEL_MAP_UI_ADMIN_USERNAME=admin \
    --env KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH \
    --env KOR_TRAVEL_MAP_UI_SESSION_SECRET \
    --env "KOR_TRAVEL_MAP_UI_PUBLIC_ORIGINS=http://candidate-ui:$UI_PORT" \
    "$UI_IMAGE_ID" >/dev/null
  for _ in $(seq 1 90); do
    if assert_candidate_container "$UI_CONTAINER" "$UI_IMAGE_ID" 2>/dev/null &&
      docker exec "$UI_CONTAINER" node -e \
        "fetch('http://127.0.0.1:$UI_PORT/login').then(r=>{if(!r.ok)process.exit(1)})" \
        >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  assert_candidate_container "$UI_CONTAINER" "$UI_IMAGE_ID"
  docker exec "$UI_CONTAINER" node -e \
    "fetch('http://127.0.0.1:$UI_PORT/login').then(r=>{if(!r.ok)process.exit(1)})" \
    >/dev/null || die "candidate UI health check failed"
  docker exec "$UI_CONTAINER" node -e \
    "fetch('http://127.0.0.1:$UI_PORT/api/proxy/v1/admin/features',{method:'POST'}).then(r=>{if(r.status!==401)process.exit(1)})" \
    >/dev/null || die "candidate UI admin proxy route is not mounted"
  build_revision="$(
    docker exec "$UI_CONTAINER" node -e \
      "fetch('http://127.0.0.1:$UI_PORT/api/build-info').then(r=>r.json()).then(v=>process.stdout.write(v.revision))"
  )"
  [[ "$build_revision" == "$(state_helper read-blocked --path "$BLOCKED_FILE" --field source_commit)" ]] ||
    die "candidate UI build revision mismatch"
  assert_candidate_container "$API_CONTAINER" "$API_IMAGE_ID"
  assert_candidate_container "$UI_CONTAINER" "$UI_IMAGE_ID"
  assert_database_login_fence
}

run_helper() {
  local action="$1"
  local output="$2"
  local name="ktm-afcla-${RUN_KEY:0:12}-helper-$action"
  local -a helper_args=(
    /opt/admin-feature-live-fixture.py "$action" --run-id "$RUN_ID"
  )
  docker run --rm \
    --name "$name" \
    --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
    --network "$NETWORK_NAME" \
    --read-only \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --env KOR_TRAVEL_MAP_PG_DSN \
    --mount "type=bind,src=$FIXTURE_HELPER,dst=/opt/admin-feature-live-fixture.py,readonly" \
    --entrypoint python \
    "$API_IMAGE_ID" \
    "${helper_args[@]}" >"$output"
  chmod 0600 -- "$output"
}

run_executor() {
  local name="$1"
  local artifact_dir="$2"
  local recovery_only="$3"
  prepare_loopback_proxy_helper
  mkdir -- "$artifact_dir"
  chmod 0700 -- "$artifact_dir"
  local -a recovery_env=()
  [[ "$recovery_only" != "1" ]] ||
    recovery_env+=(--env E2E_ADMIN_FEATURE_ACCEPTANCE_RECOVERY_ONLY=1)
  docker run --rm \
    --name "$name" \
    --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
    --network "$NETWORK_NAME" \
    --ipc private \
    --read-only \
    --security-opt no-new-privileges \
    --cap-drop ALL \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --tmpfs /root/.cache:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.config:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.npm:rw,nosuid,nodev,noexec,mode=700 \
    --mount "type=bind,src=$artifact_dir,dst=/evidence" \
    --mount "type=bind,src=$LOOPBACK_PROXY_HELPER,dst=/opt/c7-loopback-ui-proxy.mjs,readonly" \
    --env "E2E_BASE_URL=http://127.0.0.1:$LOOPBACK_UI_PORT" \
    --env "KTM_C7_LOOPBACK_UI_PROXY_PORT=$LOOPBACK_UI_PORT" \
    --env "KTM_C7_LOOPBACK_UI_PROXY_TARGET=http://candidate-ui:$UI_PORT" \
    --env E2E_ADMIN_USERNAME=admin \
    --env E2E_ADMIN_PASSWORD \
    --env E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1 \
    --env "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID=$RUN_ID" \
    --env E2E_ISOLATED_LIVE_EVIDENCE=1 \
    --env E2E_ISOLATED_LIVE_DOCKER_NETWORK=1 \
    --env E2E_LIVE_WORKERS=1 \
    --env PLAYWRIGHT_ARTIFACT_ROOT=/evidence \
    --env E2E_STORAGE_STATE=/tmp/admin-feature-clone-state.json \
    "${recovery_env[@]}" \
    --entrypoint /bin/sh \
    "$PLAYWRIGHT_IMAGE_ID" \
    -ec '
      node /opt/c7-loopback-ui-proxy.mjs &
      proxy_pid=$!
      cleanup_proxy() {
        kill "$proxy_pid" 2>/dev/null || true
        wait "$proxy_pid" 2>/dev/null || true
      }
      trap cleanup_proxy EXIT INT TERM
      for _ in $(seq 1 30); do
        node -e "fetch(process.env.E2E_BASE_URL + \"/login\").then((response) => process.exit(response.ok ? 0 : 1)).catch(() => process.exit(1))" && break
        sleep 1
      done
      node -e "fetch(process.env.E2E_BASE_URL + \"/login\").then((response) => process.exit(response.ok ? 0 : 1))"
      npm run e2e:live -- e2e/live/admin-feature-acceptance-write.live.spec.ts --workers=1 --retries=0
    '
}

reset_evidence_path() {
  local path="$1"
  [[ "$path" == "$RUNTIME_DIR/"* && "$path" != "$RUNTIME_DIR/" ]] ||
    die "evidence reset path is unsafe"
  [[ ! -L "$path" ]] || die "evidence reset path is a symlink"
  if [[ -e "$path" ]]; then
    rm -rf -- "$path"
  fi
}

write_resource_final() {
  state_helper write-resource-state \
    --no-clone-network-attached \
    --owned-containers "$(owned_containers)" \
    --owned-images "$(owned_images)" \
    --owned-networks "$(owned_networks)" \
    --path "$RUNTIME_DIR/resource-final.json"
}

finalize_resources() {
  remove_owned_containers
  remove_owned_network
  remove_owned_images
  [[ "$(owned_containers)" == "0" ]] || die "owned containers remain"
  [[ "$(owned_images)" == "0" ]] || die "owned images remain"
  [[ "$(owned_networks)" == "0" ]] || die "owned network remains"
  [[ "$(clone_network_attached)" == "false" ]] || die "clone network remains attached"
  write_resource_final
}

completion_args=()
set_completion_args() {
  local phase="$1"
  completion_args=(
    --blocked-path "$BLOCKED_FILE"
    --observed-snapshot "$RUNTIME_DIR/clone-final-observed.json"
    --phase "$phase"
    --runtime "$RUNTIME_DIR"
    --topic-revision-proof "$RUNTIME_DIR/topic-revision-proof.json"
  )
  if [[ "$DATASET_PROJECTION_START_SOURCE" == "runtime-start" ]]; then
    completion_args+=(
      --topic-revision-start "$RUNTIME_DIR/topic-revision-start.json"
    )
  fi
  if [[ "$phase" == "recovered" ]]; then
    completion_args+=(
      --current-snapshot "$RUNTIME_DIR/clone-recovery-current.json"
      --recovery-tool-source-commit "$SOURCE_COMMIT"
    )
  fi
}

run_acceptance_from_fixture() {
  state_helper update-blocked --path "$BLOCKED_FILE" --phase fixture-seed-running
  run_helper seed "$RUNTIME_DIR/direct-seed.json"
  state_helper update-blocked --path "$BLOCKED_FILE" --phase browser-main-running
  local main_status=0 recovery_status=0 cleanup_status=0 audit_status=0
  local api_audit_status=0 auth_status=0
  run_executor \
    "ktm-afcla-${RUN_KEY:0:12}-executor-main" \
    "$RUNTIME_DIR/playwright-main" 0 || main_status=$?
  state_helper update-blocked --path "$BLOCKED_FILE" --phase browser-recovery-running
  run_executor \
    "ktm-afcla-${RUN_KEY:0:12}-executor-recovery" \
    "$RUNTIME_DIR/playwright-recovery" 1 || recovery_status=$?
  state_helper update-blocked --path "$BLOCKED_FILE" --phase direct-cleanup-running
  # UI failure 뒤에도 fixture cleanup과 모든 audit receipt를 끝까지 수집해야 다음
  # recover가 trusted checkpoint로 돌아갈 수 있다. 각 실패는 아래 단일 terminal
  # branch에서 합산해 acceptance를 통과시키지 않는다.
  run_helper cleanup "$RUNTIME_DIR/direct-cleanup.json" || cleanup_status=$?
  run_helper audit "$RUNTIME_DIR/direct-audit.json" || audit_status=$?
  run_helper api-audit "$RUNTIME_DIR/api-owned-audit.json" || api_audit_status=$?
  run_helper auth-verify "$RUNTIME_DIR/auth-audit.json" || auth_status=$?
  assert_database_login_fence
  write_dataset_projection_snapshots \
    "$RUNTIME_DIR/clone-final-observed.json" \
    "$RUNTIME_DIR/clone-final.json"
  (( main_status == 0 && recovery_status == 0 && cleanup_status == 0 &&
    audit_status == 0 && api_audit_status == 0 && auth_status == 0 )) || {
    state_helper update-blocked --path "$BLOCKED_FILE" --phase test-failed-restored
    die "Playwright or fixture acceptance failed after cleanup"
  }
}

load_blocked() {
  RUN_ID="$(state_helper read-blocked --path "$BLOCKED_FILE" --field run_id)"
  RUN_KEY="$(state_helper read-blocked --path "$BLOCKED_FILE" --field run_key)"
  NETWORK_NAME="$(state_helper read-blocked --path "$BLOCKED_FILE" --field network_name)"
  API_IMAGE_ID="$(state_helper read-blocked --path "$BLOCKED_FILE" --field api_image_id)"
  UI_IMAGE_ID="$(state_helper read-blocked --path "$BLOCKED_FILE" --field ui_image_id)"
  PLAYWRIGHT_IMAGE_ID="$(
    state_helper read-blocked --path "$BLOCKED_FILE" --field playwright_image_id
  )"
  RUNTIME_DIR="$STATE_ROOT/run-$RUN_KEY"
  [[ -d "$RUNTIME_DIR" && ! -L "$RUNTIME_DIR" ]] || die "BLOCKED runtime is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$RUNTIME_DIR")" == "0:0:700" ]] ||
    die "BLOCKED runtime metadata is unsafe"
}

if [[ "$MODE" == "abort" ]]; then
  [[ -f "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "failed-run BLOCKED state is missing"
  [[ "$(stat -c '%u:%g:%a' -- "$BLOCKED_FILE")" == "0:0:600" ]] ||
    die "BLOCKED state metadata is unsafe"
  BLOCKED_WRITTEN=1
  load_blocked
  blocked_source="$(state_helper read-blocked --path "$BLOCKED_FILE" --field source_commit)"
  [[ "$(state_helper read-blocked --path "$BLOCKED_FILE" --field phase)" == \
      "test-failed-restored" ||
     "$(state_helper read-blocked --path "$BLOCKED_FILE" --field phase)" == \
      "failed-resource-finalizing" ]] ||
    die "only a cleaned failed browser run can be abandoned"
  API_IMAGE_TAG="kor-travel-map-clone-live-api:${blocked_source:0:12}-${RUN_KEY:0:12}"
  UI_IMAGE_TAG="kor-travel-map-clone-live-ui:${blocked_source:0:12}-${RUN_KEY:0:12}"
  PLAYWRIGHT_IMAGE_TAG="kor-travel-map-clone-live-playwright:${blocked_source:0:12}-${RUN_KEY:0:12}"
  validate_snapshot "$blocked_source" "$INSTALL_BASE/$blocked_source"
  CONTENT_CUTOFF="$(
    state_helper read-checkpoint \
      --checkpoint "$RUNTIME_DIR/clone-checkpoint.json" \
      --field content_cutoff
  )"
  verify_checkpoint_dump "$RUNTIME_DIR/clone-checkpoint.json"
  remove_unreferenced_checkpoint_dumps
  BASE_CLONE_CONTAINER_SHA256="$(
    printf '%s' "$BASE_CLONE_CONTAINER_ID" | sha256sum | awk '{print $1}'
  )"
  BASE_CLONE_SYSTEM_SHA256="$(
    printf '%s' "$(psql_value "SELECT system_identifier::text FROM pg_control_system()")" |
      sha256sum | awk '{print $1}'
  )"
  recover_checkpoint_quiescence
  recover_verification_database
  start_acceptance_login_fence
  state_helper update-blocked --path "$BLOCKED_FILE" --phase failed-resource-finalizing
  finalize_resources
  assert_acceptance_login_fence_after_resources
  stop_checkpoint_quiescence ||
    die "clone DB login fence restoration failed after failed-run cleanup"
  state_helper abandon-failed-run \
    --blocked-path "$BLOCKED_FILE" \
    --result-path "$RUNTIME_DIR/failed-restored.json" \
    --runtime "$RUNTIME_DIR"
  COMPLETE=1
  BLOCKED_WRITTEN=0
  printf 'admin feature clone live acceptance failed run restored: source=%s result=%s\n' \
    "$blocked_source" "$RUNTIME_DIR/failed-restored.json"
  exit 0
fi

if [[ "$MODE" == "recover" ]]; then
  [[ -f "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "recoverable BLOCKED state is missing"
  [[ "$(stat -c '%u:%g:%a' -- "$BLOCKED_FILE")" == "0:0:600" ]] ||
    die "BLOCKED state metadata is unsafe"
  BLOCKED_WRITTEN=1
  load_blocked
  blocked_source="$(state_helper read-blocked --path "$BLOCKED_FILE" --field source_commit)"
  API_IMAGE_TAG="kor-travel-map-clone-live-api:${blocked_source:0:12}-${RUN_KEY:0:12}"
  UI_IMAGE_TAG="kor-travel-map-clone-live-ui:${blocked_source:0:12}-${RUN_KEY:0:12}"
  PLAYWRIGHT_IMAGE_TAG="kor-travel-map-clone-live-playwright:${blocked_source:0:12}-${RUN_KEY:0:12}"
  validate_snapshot "$blocked_source" "$INSTALL_BASE/$blocked_source"
  FIXTURE_HELPER="$INSTALL_BASE/$blocked_source/admin_feature_live_fixture.py"
  # SIGKILL 뒤 daemon에 남은 candidate와 DB pool을 먼저 끊어 첫 recover가 곧바로
  # 새 login fence를 세울 수 있게 한다.
  remove_owned_containers
  remove_owned_network
  CONTENT_CUTOFF="$(
    state_helper read-checkpoint \
      --checkpoint "$RUNTIME_DIR/clone-checkpoint.json" \
      --field content_cutoff
  )"
  verify_checkpoint_dump "$RUNTIME_DIR/clone-checkpoint.json"
  remove_unreferenced_checkpoint_dumps
  BASE_CLONE_CONTAINER_SHA256="$(
    printf '%s' "$BASE_CLONE_CONTAINER_ID" | sha256sum | awk '{print $1}'
  )"
  BASE_CLONE_SYSTEM_SHA256="$(
    printf '%s' "$(psql_value "SELECT system_identifier::text FROM pg_control_system()")" |
      sha256sum | awk '{print $1}'
  )"
  recover_checkpoint_quiescence
  recover_verification_database
  start_acceptance_login_fence
  if [[ -f "$RUNTIME_DIR/topic-revision-start.json" &&
        ! -L "$RUNTIME_DIR/topic-revision-start.json" ]]; then
    load_dataset_projection_start_from_runtime
  else
    [[ "$blocked_source" != "$SOURCE_COMMIT" ]] ||
      die "legacy dataset projection recovery requires a newer tool revision"
    legacy_recovery_phase="$(
      state_helper read-blocked \
        --path "$BLOCKED_FILE" --field phase
    )"
    [[ "$legacy_recovery_phase" == "direct-cleanup-running" ||
       "$legacy_recovery_phase" == "recovery-resource-finalizing" ]] ||
      die "legacy dataset projection recovery phase is not eligible"
    load_dataset_projection_start_from_dump \
      "$RUNTIME_DIR/clone-checkpoint.json"
  fi
  write_dataset_projection_snapshots \
    "$RUNTIME_DIR/clone-recovery-observed.json" \
    "$RUNTIME_DIR/clone-recovery-current.json"
  if [[ "$DATASET_PROJECTION_START_SOURCE" == "checkpoint-dump" ]]; then
    install -o root -g root -m 0600 \
      "$RUNTIME_DIR/clone-recovery-observed.json" \
      "$RUNTIME_DIR/clone-final-observed.json"
  fi
  set_completion_args recovered
  # 빠른 완료는 이미 checkpoint에 복귀한 경우만 허용한다. browser 중단 직후의
  # owned mutation은 정상적인 recovery 대상이므로, mismatch 자체로 fallback을
  # 막아서는 안 된다.
  if state_helper verify-checkpoint \
      --allow-owned-drift \
      --checkpoint "$RUNTIME_DIR/clone-checkpoint.json" \
      --snapshot "$RUNTIME_DIR/clone-recovery-current.json" >/dev/null 2>&1 &&
    state_helper validate-evidence "${completion_args[@]}" >/dev/null 2>&1; then
    state_helper update-blocked --path "$BLOCKED_FILE" --phase recovery-resource-finalizing
    finalize_resources
    assert_acceptance_login_fence_after_resources
    stop_checkpoint_quiescence ||
      die "clone DB login fence restoration failed after recovery"
    state_helper complete "${completion_args[@]}" \
      --result-path "$RUNTIME_DIR/result.json"
    COMPLETE=1
    BLOCKED_WRITTEN=0
    printf 'admin feature clone live acceptance recovered: source=%s result=%s\n' \
      "$blocked_source" "$RUNTIME_DIR/result.json"
    exit 0
  fi

  for image in "$API_IMAGE_ID" "$UI_IMAGE_ID" "$PLAYWRIGHT_IMAGE_ID"; do
    docker image inspect "$image" >/dev/null 2>&1 || die "BLOCKED image is missing"
  done
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$API_IMAGE_ID"
  )" == "$blocked_source" ]] || die "BLOCKED API image revision mismatch"
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$UI_IMAGE_ID"
  )" == "$blocked_source" ]] || die "BLOCKED UI image revision mismatch"
  [[ "$(
    docker image inspect --format \
      '{{index .Config.Labels "io.kortravelmap.c7.repository-commit"}}' \
      "$PLAYWRIGHT_IMAGE_ID"
  )" == "$blocked_source" ]] || die "BLOCKED Playwright image revision mismatch"
  EXPECTED_MIGRATION_HEAD="$(read_image_migration_head "$API_IMAGE_ID")"
  state_helper update-blocked --path "$BLOCKED_FILE" --phase recovery-interruption-cleanup
  remove_owned_containers
  remove_owned_network
  create_candidate_network
  start_candidate_services
  if [[ ! -e "$RUNTIME_DIR/clone-startup-after.json" ]]; then
    write_snapshot "$RUNTIME_DIR/clone-startup-after.json" "$RUN_ID"
  fi
  interruption_dir="$RUNTIME_DIR/playwright-interruption-cleanup"
  reset_evidence_path "$interruption_dir"
  run_executor \
    "ktm-afcla-${RUN_KEY:0:12}-executor-interruption-cleanup" \
    "$interruption_dir" 1
  run_helper cleanup "$RUNTIME_DIR/direct-cleanup-interrupted.json"
  run_helper audit "$RUNTIME_DIR/direct-audit-interrupted.json"
  state_helper update-blocked --path "$BLOCKED_FILE" --phase recovery-hard-purge-running
  run_helper purge "$RUNTIME_DIR/direct-purge-interrupted.json"
  state_helper update-blocked --path "$BLOCKED_FILE" --phase recovery-auth-reset-running
  run_helper auth-reset "$RUNTIME_DIR/auth-audit-reset.json"
  for path in \
    "$RUNTIME_DIR/direct-seed.json" \
    "$RUNTIME_DIR/direct-cleanup.json" \
    "$RUNTIME_DIR/direct-audit.json" \
    "$RUNTIME_DIR/api-owned-audit.json" \
    "$RUNTIME_DIR/auth-audit.json" \
    "$RUNTIME_DIR/clone-final.json" \
    "$RUNTIME_DIR/clone-final-observed.json" \
    "$RUNTIME_DIR/playwright-main" \
    "$RUNTIME_DIR/playwright-recovery" \
    "$RUNTIME_DIR/topic-revision-proof.json"; do
    reset_evidence_path "$path"
  done
  run_acceptance_from_fixture
  write_dataset_projection_snapshots \
    "$RUNTIME_DIR/clone-recovery-observed.json" \
    "$RUNTIME_DIR/clone-recovery-current.json"
  set_completion_args recovered
  state_helper validate-evidence "${completion_args[@]}"
  state_helper update-blocked --path "$BLOCKED_FILE" --phase recovery-resource-finalizing
  finalize_resources
  assert_acceptance_login_fence_after_resources
  stop_checkpoint_quiescence ||
    die "clone DB login fence restoration failed after recovery"
  state_helper complete "${completion_args[@]}" \
    --result-path "$RUNTIME_DIR/result.json"
  COMPLETE=1
  BLOCKED_WRITTEN=0
  printf 'admin feature clone live acceptance recovered: source=%s result=%s\n' \
    "$blocked_source" "$RUNTIME_DIR/result.json"
  exit 0
fi

[[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
  die "prior BLOCKED state requires operator recovery"
[[ -f "$CHECKPOINT_FILE" && ! -L "$CHECKPOINT_FILE" ]] ||
  die "trusted clone checkpoint is missing"
[[ "$(stat -c '%u:%g:%a' -- "$CHECKPOINT_FILE")" == "0:0:600" ]] ||
  die "trusted clone checkpoint metadata is unsafe"
CONTENT_CUTOFF="$(
  state_helper read-checkpoint \
    --checkpoint "$CHECKPOINT_FILE" --field content_cutoff
)"
verify_checkpoint_dump "$CHECKPOINT_FILE"
remove_unreferenced_checkpoint_dumps

RUN_ID="clone-$(date -u +%Y%m%d%H%M%S)-$(openssl rand -hex 6)"
RUN_KEY="$(printf '%s' "$RUN_ID" | sha256sum | awk '{print $1}')"
NETWORK_NAME="ktm-afcla-${RUN_KEY:0:12}-net"
RUNTIME_DIR="$STATE_ROOT/run-$RUN_KEY"
mkdir -- "$RUNTIME_DIR"
chown root:root -- "$RUNTIME_DIR"
chmod 0700 -- "$RUNTIME_DIR"
API_IMAGE_TAG="kor-travel-map-clone-live-api:${SOURCE_COMMIT:0:12}-${RUN_KEY:0:12}"
UI_IMAGE_TAG="kor-travel-map-clone-live-ui:${SOURCE_COMMIT:0:12}-${RUN_KEY:0:12}"
PLAYWRIGHT_IMAGE_TAG="kor-travel-map-clone-live-playwright:${SOURCE_COMMIT:0:12}-${RUN_KEY:0:12}"
prepare_build_context "$SCRIPT_DIR"
build_api_image
build_ui_image
build_playwright_image
EXPECTED_MIGRATION_HEAD="$(read_image_migration_head "$API_IMAGE_ID")"
BASE_CLONE_CONTAINER_SHA256="$(
  printf '%s' "$BASE_CLONE_CONTAINER_ID" | sha256sum | awk '{print $1}'
)"
BASE_CLONE_SYSTEM_SHA256="$(
  printf '%s' "$(psql_value "SELECT system_identifier::text FROM pg_control_system()")" |
    sha256sum | awk '{print $1}'
)"
recover_checkpoint_quiescence
recover_verification_database
start_acceptance_login_fence
write_snapshot "$RUNTIME_DIR/clone-startup-before.json" "$RUN_ID"
install -o root -g root -m 0600 "$CHECKPOINT_FILE" "$RUNTIME_DIR/clone-checkpoint.json"
clone_checkpoint_sha256="$(
  state_helper verify-checkpoint \
    --checkpoint "$RUNTIME_DIR/clone-checkpoint.json" \
    --snapshot "$RUNTIME_DIR/clone-startup-before.json"
)"
read_current_dataset_projection
DATASET_PROJECTION_START_REVISION="$DATASET_PROJECTION_CURRENT_REVISION"
DATASET_PROJECTION_START_UPDATED_AT="$DATASET_PROJECTION_CURRENT_UPDATED_AT"
DATASET_PROJECTION_START_SOURCE="runtime-start"
state_helper write-topic-revision-start \
  --checkpoint-sha256 "$clone_checkpoint_sha256" \
  --path "$RUNTIME_DIR/topic-revision-start.json" \
  --revision "$DATASET_PROJECTION_START_REVISION" \
  --run-id "$RUN_ID" \
  --updated-at "$DATASET_PROJECTION_START_UPDATED_AT"
startup_schema="$(
  python3 -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["schema_sha256"])' \
    "$RUNTIME_DIR/clone-startup-before.json"
)"
startup_content="$(
  python3 -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["content_sha256"])' \
    "$RUNTIME_DIR/clone-startup-before.json"
)"
startup_database="$(
  python3 -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["database_sha256"])' \
    "$RUNTIME_DIR/clone-startup-before.json"
)"
startup_extension="$(
  python3 -I -B -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["extension_sha256"])' \
    "$RUNTIME_DIR/clone-startup-before.json"
)"
clone_identity_sha256="$(
  printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' \
    "$BASE_CLONE_CONTAINER_SHA256" "$BASE_CLONE_SYSTEM_SHA256" "$DB_HOST_PORT" \
    "$EXPECTED_MIGRATION_HEAD" "$startup_database" "$startup_extension" \
    "$startup_schema" "$startup_content" |
    sha256sum | awk '{print $1}'
)"
state_helper write-image-evidence \
  --api-image-id "$API_IMAGE_ID" \
  --path "$RUNTIME_DIR/image-evidence.json" \
  --playwright-image-id "$PLAYWRIGHT_IMAGE_ID" \
  --source-commit "$SOURCE_COMMIT" \
  --ui-image-id "$UI_IMAGE_ID"
state_helper write-blocked \
  --path "$BLOCKED_FILE" \
  --phase candidate-startup-pending \
  --run-id "$RUN_ID" \
  --run-key "$RUN_KEY" \
  --api-image-id "$API_IMAGE_ID" \
  --clone-checkpoint-sha256 "$clone_checkpoint_sha256" \
  --clone-identity-sha256 "$clone_identity_sha256" \
  --network-name "$NETWORK_NAME" \
  --playwright-image-id "$PLAYWRIGHT_IMAGE_ID" \
  --source-commit "$SOURCE_COMMIT" \
  --ui-image-id "$UI_IMAGE_ID"
BLOCKED_WRITTEN=1
create_candidate_network
state_helper update-blocked --path "$BLOCKED_FILE" --phase candidate-startup-running
start_candidate_services
write_snapshot "$RUNTIME_DIR/clone-startup-after.json" "$RUN_ID"
run_acceptance_from_fixture
set_completion_args passed
state_helper validate-evidence "${completion_args[@]}"
state_helper update-blocked --path "$BLOCKED_FILE" --phase resource-finalizing
finalize_resources
assert_acceptance_login_fence_after_resources
stop_checkpoint_quiescence ||
  die "clone DB login fence restoration failed after acceptance"
state_helper complete "${completion_args[@]}" \
  --result-path "$RUNTIME_DIR/result.json"
COMPLETE=1
BLOCKED_WRITTEN=0
printf 'admin feature clone live acceptance complete: source=%s result=%s\n' \
  "$SOURCE_COMMIT" "$RUNTIME_DIR/result.json"

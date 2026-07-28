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
readonly MODE="${1-run}"
readonly SOURCE_COMMIT="${E2E_SOURCE_COMMIT-}"
readonly DB_CONTAINER="${E2E_CLONE_DB_CONTAINER-}"
readonly DB_HOST_PORT="${E2E_CLONE_DB_PORT-}"
readonly API_PORT="${E2E_CLONE_API_PORT:-18701}"
readonly UI_PORT="${E2E_CLONE_UI_PORT:-18705}"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SOURCE_ARCHIVE="$SCRIPT_DIR/source.tar.gz"
readonly ARCHIVE_PREFIX="kor-travel-map-$SOURCE_COMMIT"
readonly ARCHIVE_URL="https://github.com/digitie/kor-travel-map/archive/$SOURCE_COMMIT.tar.gz"

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
  require_command sudo
  require_command tar
  [[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "source commit is invalid"

  local expected_root="$INSTALL_BASE/$SOURCE_COMMIT"
  if ! sudo -n test -d "$expected_root"; then
    local incoming="$INSTALL_BASE/.incoming-$SOURCE_COMMIT-$$"
    sudo -n install -d -o root -g root -m 0555 "$INSTALL_BASE"
    sudo -n install -d -o root -g root -m 0700 "$incoming"
    sudo -n curl -q --fail --show-error --silent --location \
      --proto '=https' --proto-redir '=https' --tlsv1.2 \
      --output "$incoming/source.tar.gz" "$ARCHIVE_URL"
    sudo -n tar --extract --gzip --file "$incoming/source.tar.gz" \
      --directory "$incoming" --strip-components=2 \
      "$ARCHIVE_PREFIX/scripts/admin_feature_clone_live_state.py" \
      "$ARCHIVE_PREFIX/scripts/admin_feature_live_fixture.py" \
      "$ARCHIVE_PREFIX/scripts/run-admin-feature-clone-live-acceptance.sh"
    sudo -n chown root:root \
      "$incoming/source.tar.gz" \
      "$incoming/admin_feature_clone_live_state.py" \
      "$incoming/admin_feature_live_fixture.py" \
      "$incoming/run-admin-feature-clone-live-acceptance.sh"
    sudo -n chmod 0444 \
      "$incoming/source.tar.gz" \
      "$incoming/admin_feature_clone_live_state.py" \
      "$incoming/admin_feature_live_fixture.py"
    sudo -n chmod 0555 "$incoming/run-admin-feature-clone-live-acceptance.sh"
    sudo -n chmod 0555 "$incoming"
    sudo -n mv -- "$incoming" "$expected_root"
  fi

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
  local expected_names actual_names
  expected_names=$'admin_feature_clone_live_state.py\nadmin_feature_live_fixture.py\nrun-admin-feature-clone-live-acceptance.sh\nsource.tar.gz'
  actual_names="$(
    find "$snapshot_root" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort
  )"
  [[ "$actual_names" == "$expected_names" ]] || die "snapshot exact file set mismatch"
  [[ "$(stat -c '%u:%g:%a' -- "$archive")" == "0:0:444" && ! -L "$archive" ]] ||
    die "source archive metadata is unsafe"
  local name expected_mode archive_digest installed_digest
  for name in \
    admin_feature_clone_live_state.py \
    admin_feature_live_fixture.py \
    run-admin-feature-clone-live-acceptance.sh; do
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

[[ "$MODE" == "checkpoint" || "$MODE" == "recover" || "$MODE" == "run" ]] ||
  die "usage: runner checkpoint|recover|run"
require_env E2E_SOURCE_COMMIT
if [[ "$SCRIPT_DIR" != "$INSTALL_BASE/$SOURCE_COMMIT" ]]; then
  bootstrap_snapshot
fi

(( EUID == 0 )) || die "trusted installed runner requires root"
validate_snapshot
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
if [[ "$MODE" != "checkpoint" ]]; then
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
exec 9<>"$LOCK_FILE"
flock -n 9 || die "another clone acceptance runner owns the lock"

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

psql_query() {
  local query="$1"
  PGPASSWORD="$db_password" docker exec -e PGPASSWORD "$DB_CONTAINER" \
    psql -X -v ON_ERROR_STOP=1 -Atq -U "$db_user" -d "$db_name" -c "$query"
}

psql_stream() {
  PGPASSWORD="$db_password" docker exec -i -e PGPASSWORD "$DB_CONTAINER" \
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
  KTM_E2E_DB_USER="$db_user" \
    KTM_E2E_DB_PASSWORD="$db_password" \
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
      attribute.attnum::text || ':' || attribute.attname || ':' ||
      pg_catalog.format_type(attribute.atttypid, attribute.atttypmod) || ':' ||
      attribute.attnotnull::text || ':' ||
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
      constraint_row.conname || ':' ||
      pg_catalog.pg_get_constraintdef(constraint_row.oid, true)
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
      constraint_row.conname || ':' ||
        pg_catalog.pg_get_constraintdef(constraint_row.oid, true)
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
      policy.polname || ':' || policy.polcmd || ':' ||
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
  )
  SELECT concat_ws(chr(31), kind, schema_name, object_name, definition)
  FROM objects
  ORDER BY kind, schema_name, object_name, definition
) TO STDOUT
SQL
)"
  psql_query "$query" | sha256sum | awk '{print $1}'
}

content_sha256() {
  local run_id="$1"
  [[ "$run_id" =~ ^[a-z0-9][a-z0-9-]{15,79}$ ]] ||
    die "content digest run ID is invalid"
  [[ "$CONTENT_CUTOFF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$ ]] ||
    die "content digest cutoff is invalid"
  local statement_query statements
  statement_query="$(cat <<SQL
SELECT format(
  'SELECT %L || chr(31) || count(*)::text || chr(31) || ' ||
  'COALESCE(bit_xor(hash_record_extended(row_value, 0))::text, ''null'') || ' ||
  'chr(31) || COALESCE(bit_xor(hash_record_extended(' ||
  'row_value, 9223372036854775807))::text, ''null'') ' ||
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
      '\\'
    )
    WHEN namespace.nspname = 'ops'
      AND relation.relname IN ('admin_auth_events', 'api_call_log')
    THEN format(
      ' WHERE row_value.created_at < %L::timestamptz',
      '${CONTENT_CUTOFF}'
    )
    ELSE ''
  END
)
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
  [[ "$run_id" =~ ^[a-z0-9][a-z0-9-]{15,79}$ ]] ||
    die "snapshot run ID is invalid"
  verify_clone_container
  local before_id="$(
    docker inspect --format '{{.Id}}' "$DB_CONTAINER"
  )"
  local container_sha system_identifier system_sha
  local migration_head relation_count feature_total feature_non_deleted
  local active_owned nonterminal_owned schema_digest content_digest
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
  content_digest="$(content_sha256 "$run_id")"
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
BLOCKED_WRITTEN=0
COMPLETE=0

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

remove_owned_network() {
  [[ -n "$NETWORK_NAME" ]] || return 0
  if [[ "$(clone_network_attached)" == "true" ]]; then
    docker network disconnect "$NETWORK_NAME" "$DB_CONTAINER"
  fi
  if docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    docker network rm "$NETWORK_NAME" >/dev/null
  fi
}

remove_owned_images() {
  local -a images=()
  local image
  for image in "$API_IMAGE_ID" "$UI_IMAGE_ID" "$PLAYWRIGHT_IMAGE_ID"; do
    if [[ -n "$image" ]] && docker image inspect "$image" >/dev/null 2>&1; then
      images+=("$image")
    fi
  done
  (( ${#images[@]} == 0 )) || docker image rm --force "${images[@]}" >/dev/null
}

owned_images() {
  local count=0 image
  for image in "$API_IMAGE_ID" "$UI_IMAGE_ID" "$PLAYWRIGHT_IMAGE_ID"; do
    if [[ -n "$image" ]] && docker image inspect "$image" >/dev/null 2>&1; then
      count=$((count + 1))
    fi
  done
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

foreign_db_sessions() {
  psql_value "
    SELECT count(*)
    FROM pg_catalog.pg_stat_activity
    WHERE datname = current_database()
      AND pid <> pg_backend_pid()
      AND backend_type = 'client backend'
  "
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

cleanup_on_exit() {
  local status=$?
  trap - EXIT INT TERM
  set +e
  remove_owned_containers
  remove_owned_network
  if (( BLOCKED_WRITTEN == 0 || COMPLETE == 1 )); then
    remove_owned_images
  fi
  if [[ -n "$TEMPORARY" && -d "$TEMPORARY" ]]; then
    safe_remove_temporary "$TEMPORARY"
  fi
  if (( BLOCKED_WRITTEN == 0 && COMPLETE == 0 )) &&
    [[ -n "$RUNTIME_DIR" && -d "$RUNTIME_DIR" ]]; then
    rm -rf -- "$RUNTIME_DIR"
  fi
  if (( COMPLETE == 0 )) &&
    [[ -n "$NEW_CHECKPOINT_DUMP" &&
       "$NEW_CHECKPOINT_DUMP" == "$STATE_ROOT"/clone-checkpoint-*.dump &&
       -f "$NEW_CHECKPOINT_DUMP" && ! -L "$NEW_CHECKPOINT_DUMP" ]]; then
    rm -f -- "$NEW_CHECKPOINT_DUMP"
  fi
  exit "$status"
}
trap cleanup_on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$MODE" == "checkpoint" ]]; then
  [[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "BLOCKED state must be recovered before checkpoint"
  RUN_ID="checkpoint-$(date -u +%Y%m%d%H%M%S)-$(openssl rand -hex 6)"
  RUN_KEY="$(printf '%s' "$RUN_ID" | sha256sum | awk '{print $1}')"
  API_IMAGE_TAG="kor-travel-map-clone-live-api:${SOURCE_COMMIT:0:12}-checkpoint"
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
  CONTENT_CUTOFF="$(
    psql_value \
      "SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"
  )"
  [[ "$(foreign_db_sessions)" == "0" ]] ||
    die "clone DB has a foreign client session before checkpoint dump"
  NEW_CHECKPOINT_DUMP="$STATE_ROOT/clone-checkpoint-$RUN_KEY.dump"
  [[ ! -e "$NEW_CHECKPOINT_DUMP" && ! -L "$NEW_CHECKPOINT_DUMP" ]] ||
    die "checkpoint dump target already exists"
  PGPASSWORD="$db_password" docker exec -e PGPASSWORD "$DB_CONTAINER" \
    pg_dump --format=custom --no-owner --no-privileges \
    --serializable-deferrable -U "$db_user" -d "$db_name" \
    >"$NEW_CHECKPOINT_DUMP"
  chown root:root -- "$NEW_CHECKPOINT_DUMP"
  chmod 0600 -- "$NEW_CHECKPOINT_DUMP"
  [[ "$(foreign_db_sessions)" == "0" ]] ||
    die "clone DB has a foreign client session after checkpoint dump"
  verify_dump_archive "$NEW_CHECKPOINT_DUMP"
  checkpoint_snapshot="$STATE_ROOT/.clone-checkpoint-snapshot-$$.json"
  write_snapshot "$checkpoint_snapshot" "$RUN_ID"
  [[ "$(psql_value "SELECT count(*) FROM feature.features WHERE feature_id LIKE 'e2e\\_live\\_acceptance::%' ESCAPE '\\' AND status <> 'deleted'")" == "0" ]] ||
    die "clone checkpoint has active acceptance Feature residue"
  [[ "$(psql_value "SELECT count(*) FROM ops.feature_change_requests WHERE feature_id LIKE 'e2e\\_live\\_acceptance::%' ESCAPE '\\' AND state = 'pending'")" == "0" ]] ||
    die "clone checkpoint has pending acceptance change request residue"
  dump_before="$(stat -Lc '%d:%i:%s:%Y' -- "$NEW_CHECKPOINT_DUMP")"
  dump_size="$(stat -Lc '%s' -- "$NEW_CHECKPOINT_DUMP")"
  dump_sha256="$(sha256sum -- "$NEW_CHECKPOINT_DUMP" | awk '{print $1}')"
  [[ "$(stat -Lc '%d:%i:%s:%Y' -- "$NEW_CHECKPOINT_DUMP")" == "$dump_before" ]] ||
    die "clone dump changed during checkpoint hashing"
  state_helper write-checkpoint \
    --dump-filename "$(basename -- "$NEW_CHECKPOINT_DUMP")" \
    --dump-sha256 "$dump_sha256" \
    --dump-size "$dump_size" \
    --path "$CHECKPOINT_FILE" \
    --snapshot "$checkpoint_snapshot"
  rm -- "$checkpoint_snapshot"
  remove_owned_images
  COMPLETE=1
  printf 'admin feature clone live checkpoint complete: source=%s checkpoint=%s\n' \
    "$SOURCE_COMMIT" "$CHECKPOINT_FILE"
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
  docker network create --internal \
    --label "io.kortravelmap.admin-feature-clone-acceptance.run-key=$RUN_KEY" \
    "$NETWORK_NAME" >/dev/null
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
  build_revision="$(
    docker exec "$UI_CONTAINER" node -e \
      "fetch('http://127.0.0.1:$UI_PORT/api/build-info').then(r=>r.json()).then(v=>process.stdout.write(v.revision))"
  )"
  [[ "$build_revision" == "$(state_helper read-blocked --path "$BLOCKED_FILE" --field source_commit)" ]] ||
    die "candidate UI build revision mismatch"
  assert_candidate_container "$API_CONTAINER" "$API_IMAGE_ID"
  assert_candidate_container "$UI_CONTAINER" "$UI_IMAGE_ID"
}

run_helper() {
  local action="$1"
  local output="$2"
  local name="ktm-afcla-${RUN_KEY:0:12}-helper-$action"
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
    /opt/admin-feature-live-fixture.py "$action" --run-id "$RUN_ID" >"$output"
  chmod 0600 -- "$output"
}

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
    --env "E2E_BASE_URL=http://candidate-ui:$UI_PORT" \
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
    "$PLAYWRIGHT_IMAGE_ID" \
    npm run e2e:live -- \
    e2e/live/admin-feature-acceptance-write.live.spec.ts \
    --workers=1 --retries=0
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
    --phase "$phase"
    --runtime "$RUNTIME_DIR"
  )
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
  local main_status=0 recovery_status=0
  run_executor \
    "ktm-afcla-${RUN_KEY:0:12}-executor-main" \
    "$RUNTIME_DIR/playwright-main" 0 || main_status=$?
  state_helper update-blocked --path "$BLOCKED_FILE" --phase browser-recovery-running
  run_executor \
    "ktm-afcla-${RUN_KEY:0:12}-executor-recovery" \
    "$RUNTIME_DIR/playwright-recovery" 1 || recovery_status=$?
  state_helper update-blocked --path "$BLOCKED_FILE" --phase direct-cleanup-running
  run_helper cleanup "$RUNTIME_DIR/direct-cleanup.json"
  run_helper audit "$RUNTIME_DIR/direct-audit.json"
  write_snapshot "$RUNTIME_DIR/clone-final.json" "$RUN_ID"
  (( main_status == 0 && recovery_status == 0 )) || {
    state_helper update-blocked --path "$BLOCKED_FILE" --phase test-failed-restored
    die "Playwright acceptance failed after cleanup"
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

if [[ "$MODE" == "recover" ]]; then
  [[ -f "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "recoverable BLOCKED state is missing"
  [[ "$(stat -c '%u:%g:%a' -- "$BLOCKED_FILE")" == "0:0:600" ]] ||
    die "BLOCKED state metadata is unsafe"
  BLOCKED_WRITTEN=1
  load_blocked
  blocked_source="$(state_helper read-blocked --path "$BLOCKED_FILE" --field source_commit)"
  validate_snapshot "$blocked_source" "$INSTALL_BASE/$blocked_source"
  FIXTURE_HELPER="$INSTALL_BASE/$blocked_source/admin_feature_live_fixture.py"
  CONTENT_CUTOFF="$(
    state_helper read-checkpoint \
      --checkpoint "$RUNTIME_DIR/clone-checkpoint.json" \
      --field content_cutoff
  )"
  verify_checkpoint_dump "$RUNTIME_DIR/clone-checkpoint.json"
  BASE_CLONE_CONTAINER_SHA256="$(
    printf '%s' "$BASE_CLONE_CONTAINER_ID" | sha256sum | awk '{print $1}'
  )"
  BASE_CLONE_SYSTEM_SHA256="$(
    printf '%s' "$(psql_value "SELECT system_identifier::text FROM pg_control_system()")" |
      sha256sum | awk '{print $1}'
  )"
  write_snapshot "$RUNTIME_DIR/clone-recovery-current.json" "$RUN_ID"
  state_helper verify-checkpoint \
    --allow-owned-drift \
    --checkpoint "$RUNTIME_DIR/clone-checkpoint.json" \
    --snapshot "$RUNTIME_DIR/clone-recovery-current.json" >/dev/null
  set_completion_args recovered
  if state_helper validate-evidence "${completion_args[@]}" >/dev/null 2>&1; then
    state_helper update-blocked --path "$BLOCKED_FILE" --phase recovery-resource-finalizing
    finalize_resources
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
  for path in \
    "$RUNTIME_DIR/direct-seed.json" \
    "$RUNTIME_DIR/direct-cleanup.json" \
    "$RUNTIME_DIR/direct-audit.json" \
    "$RUNTIME_DIR/clone-final.json" \
    "$RUNTIME_DIR/playwright-main" \
    "$RUNTIME_DIR/playwright-recovery"; do
    reset_evidence_path "$path"
  done
  run_acceptance_from_fixture
  write_snapshot "$RUNTIME_DIR/clone-recovery-current.json" "$RUN_ID"
  set_completion_args recovered
  state_helper validate-evidence "${completion_args[@]}"
  state_helper update-blocked --path "$BLOCKED_FILE" --phase recovery-resource-finalizing
  finalize_resources
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
write_snapshot "$RUNTIME_DIR/clone-startup-before.json" "$RUN_ID"
install -o root -g root -m 0600 "$CHECKPOINT_FILE" "$RUNTIME_DIR/clone-checkpoint.json"
clone_checkpoint_sha256="$(
  state_helper verify-checkpoint \
    --checkpoint "$RUNTIME_DIR/clone-checkpoint.json" \
    --snapshot "$RUNTIME_DIR/clone-startup-before.json"
)"
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
clone_identity_sha256="$(
  printf '%s\n%s\n%s\n%s\n%s\n%s\n' \
    "$BASE_CLONE_CONTAINER_SHA256" "$BASE_CLONE_SYSTEM_SHA256" "$DB_HOST_PORT" \
    "$EXPECTED_MIGRATION_HEAD" "$startup_schema" "$startup_content" |
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
state_helper complete "${completion_args[@]}" \
  --result-path "$RUNTIME_DIR/result.json"
COMPLETE=1
BLOCKED_WRITTEN=0
printf 'admin feature clone live acceptance complete: source=%s result=%s\n' \
  "$SOURCE_COMMIT" "$RUNTIME_DIR/result.json"

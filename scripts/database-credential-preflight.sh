#!/bin/sh

require_map_database_credential() {
  credential_name="$1"
  eval "credential_value=\${$credential_name:-}"
  if [ "${#credential_value}" -lt 32 ] \
    || [ "${#credential_value}" -gt 256 ] \
    || ! printf '%s\n' "$credential_value" | grep -Eq '^[A-Za-z0-9._~-]+$'; then
    echo "$credential_name must be 32..256 URI-unreserved characters" >&2
    return 1
  fi
}

bind_map_database_authority() {
  authority_value="$1"
  case "$authority_value" in
    *:*)
      authority_host="${authority_value%:*}"
      authority_port="${authority_value##*:}"
      case "$authority_host" in
        '' | *[!A-Za-z0-9_.-]*)
          echo "database DSN authority host is invalid" >&2
          return 1
          ;;
      esac
      case "$authority_port" in
        '' | *[!0-9]*)
          echo "database DSN authority port is invalid" >&2
          return 1
          ;;
      esac
      ;;
    *)
      authority_host="$authority_value"
      authority_port=5432
      ;;
  esac
  case "$authority_host" in
    '' | *[!A-Za-z0-9_.-]*)
      echo "database DSN authority host is invalid" >&2
      return 1
      ;;
  esac
  canonical_authority="${authority_host}:${authority_port}"
  if [ -z "${map_database_canonical_authority:-}" ]; then
    map_database_canonical_authority="$canonical_authority"
  elif [ "$map_database_canonical_authority" != "$canonical_authority" ]; then
    echo "all database DSNs must share one canonical authority" >&2
    return 1
  fi
}

require_bound_map_postgres_dsn() {
  dsn_name="$1"
  dsn_scheme="$2"
  expected_user="$3"
  password_name="$4"
  expected_database="$5"
  eval "dsn_value=\${$dsn_name:-}"
  eval "dsn_password=\${$password_name:-}"
  dsn_prefix="${dsn_scheme}${expected_user}:${dsn_password}@"

  case "$dsn_value" in
    *'?'* | *'#'* | *[![:graph:]]*)
      echo "$dsn_name must be a strict URI without query, fragment, or whitespace" >&2
      return 1
      ;;
  esac
  case "$dsn_value" in
    "$dsn_prefix"*) dsn_server="${dsn_value#"$dsn_prefix"}" ;;
    *)
      echo "$dsn_name credential does not match $password_name and its dedicated login" >&2
      return 1
      ;;
  esac
  case "$dsn_server" in
    */"$expected_database") dsn_authority="${dsn_server%/"$expected_database"}" ;;
    *)
      echo "$dsn_name database does not match KOR_TRAVEL_MAP_POSTGRES_DB" >&2
      return 1
      ;;
  esac
  bind_map_database_authority "$dsn_authority" || return 1
}

validate_map_database_credentials() {
  metadata_dsn_name="$1"
  map_database_canonical_authority=""
  for required_name in \
    KOR_TRAVEL_MAP_POSTGRES_DB \
    KOR_TRAVEL_MAP_POSTGRES_USER \
    KOR_TRAVEL_MAP_POSTGRES_PASSWORD \
    KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN \
    KOR_TRAVEL_MAP_MIGRATOR_PASSWORD \
    KOR_TRAVEL_MAP_MIGRATOR_PG_DSN \
    KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD \
    KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN \
    KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD \
    KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN \
    KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB \
    KOR_TRAVEL_MAP_DAGSTER_METADATA_USER \
    KOR_TRAVEL_MAP_DAGSTER_METADATA_PASSWORD \
    "$metadata_dsn_name"; do
    eval "required_value=\${$required_name:-}"
    if [ -z "$required_value" ]; then
      echo "$required_name is required from ignored deployment env or vault" >&2
      return 1
    fi
  done
  if [ "$KOR_TRAVEL_MAP_DAGSTER_METADATA_USER" != "$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB" ]; then
    echo "Dagster metadata login and database must share one dedicated identity" >&2
    return 1
  fi

  credential_names='KOR_TRAVEL_MAP_POSTGRES_PASSWORD
KOR_TRAVEL_MAP_MIGRATOR_PASSWORD
KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD
KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD
KOR_TRAVEL_MAP_DAGSTER_METADATA_PASSWORD'
  for left_name in $credential_names; do
    require_map_database_credential "$left_name" || return 1
    eval "left_value=\${$left_name}"
    seen_right=false
    for right_name in $credential_names; do
      if [ "$seen_right" = false ]; then
        [ "$right_name" = "$left_name" ] && seen_right=true
        continue
      fi
      eval "right_value=\${$right_name}"
      if [ "$left_value" = "$right_value" ]; then
        echo "database credentials must be pairwise distinct: $left_name and $right_name" >&2
        return 1
      fi
    done
  done

  require_bound_map_postgres_dsn \
    KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN postgresql:// \
    "$KOR_TRAVEL_MAP_POSTGRES_USER" KOR_TRAVEL_MAP_POSTGRES_PASSWORD \
    "$KOR_TRAVEL_MAP_POSTGRES_DB" || return 1
  require_bound_map_postgres_dsn \
    KOR_TRAVEL_MAP_MIGRATOR_PG_DSN postgresql+asyncpg:// \
    ktm_feature_migrator KOR_TRAVEL_MAP_MIGRATOR_PASSWORD \
    "$KOR_TRAVEL_MAP_POSTGRES_DB" || return 1
  require_bound_map_postgres_dsn \
    KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN postgresql+asyncpg:// \
    ktm_feature_api_runtime KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD \
    "$KOR_TRAVEL_MAP_POSTGRES_DB" || return 1
  require_bound_map_postgres_dsn \
    KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN postgresql+asyncpg:// \
    ktm_feature_dagster_runtime KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD \
    "$KOR_TRAVEL_MAP_POSTGRES_DB" || return 1
  require_bound_map_postgres_dsn \
    "$metadata_dsn_name" postgresql:// \
    "$KOR_TRAVEL_MAP_DAGSTER_METADATA_USER" \
    KOR_TRAVEL_MAP_DAGSTER_METADATA_PASSWORD \
    "$KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB" || return 1

  if [ -n "${KOR_TRAVEL_MAP_POSTGRES_INIT_HOST:-}" ]; then
    case "$KOR_TRAVEL_MAP_POSTGRES_INIT_HOST" in
      *[!A-Za-z0-9_.-]*)
        echo "KOR_TRAVEL_MAP_POSTGRES_INIT_HOST must be one canonical host without a port" >&2
        return 1
        ;;
    esac
    if [ "$map_database_canonical_authority" \
      != "${KOR_TRAVEL_MAP_POSTGRES_INIT_HOST}:5432" ]; then
      echo "database DSN authority must match KOR_TRAVEL_MAP_POSTGRES_INIT_HOST" >&2
      return 1
    fi
  fi
}

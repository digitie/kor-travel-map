#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

API_ENV_FILE="${KOR_TRAVEL_MAP_API_ENV_FILE:-$ROOT_DIR/packages/kor-travel-map-api/.env}"
FRONTEND_ENV_FILE="${KOR_TRAVEL_MAP_FRONTEND_ENV_FILE:-$ROOT_DIR/packages/kor-travel-map-admin/frontend/.env.local}"
if [[ ! -f "$API_ENV_FILE" ]]; then
  echo "required API env file is missing: $API_ENV_FILE" >&2
  echo "copy packages/kor-travel-map-api/.env.example and configure it first" >&2
  exit 1
fi

SCOPED_ENV_FOUND=0
SCOPED_ENV_VALUE=""
read_scoped_env_key() {
  local file="$1"
  local wanted_key="$2"
  local line key value first last
  SCOPED_ENV_FOUND=0
  SCOPED_ENV_VALUE=""
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    [[ "$key" == "$wanted_key" ]] || continue
    if [[ "$SCOPED_ENV_FOUND" == "1" ]]; then
      echo "duplicate key in scoped env: $wanted_key" >&2
      exit 1
    fi
    value="${line#*=}"
    if [[ ${#value} -ge 2 ]]; then
      first="${value:0:1}"
      last="${value: -1}"
      if [[ "$first$last" == '\"\"' || "$first$last" == "''" ]]; then
        value="${value:1:${#value}-2}"
      elif [[ "$value" =~ [[:space:]]# ]]; then
        echo "inline comments are not allowed in scoped env values: $wanted_key" >&2
        exit 1
      fi
    fi
    SCOPED_ENV_FOUND=1
    SCOPED_ENV_VALUE="$value"
  done <"$file"
}

validate_frontend_manual_create_dotenv() {
  local file="$1"
  local manual_raw="${2:-}"
  local line key value first last
  [[ -f "$file" ]] || return 0

  for api_only_key in \
    KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
    KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED; do
    read_scoped_env_key "$file" "$api_only_key"
    if [[ "$SCOPED_ENV_FOUND" == "1" ]]; then
      echo "API-only key is not allowed in frontend env: $api_only_key" >&2
      exit 1
    fi
  done

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
    [[ "$line" == export\ * ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue
    key="${line%%=*}"
    value="${line#*=}"
    [[ "$key" == NEXT_PUBLIC_* ]] || continue
    if [[ ${#value} -ge 2 ]]; then
      first="${value:0:1}"
      last="${value: -1}"
      if [[ "$first$last" == '\"\"' || "$first$last" == "''" ]]; then
        value="${value:1:${#value}-2}"
      fi
    fi
    if [[ "$value" == *'$KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN'* \
      || "$value" == *'${KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN}'* ]]; then
      echo "public frontend env must not reference the manual Feature create credential: $key" >&2
      exit 1
    fi
    if [[ -n "$manual_raw" && "$value" == *"$manual_raw"* ]]; then
      echo "manual Feature create credential must be distinct from public frontend values" >&2
      exit 1
    fi
  done <"$file"
}

validate_manual_feature_create_routed_env() {
  local scope="$1"
  local manual_raw="$2"
  local manual_digest="$3"
  local entry name value
  shift 3
  for entry in "$@"; do
    name="${entry%%=*}"
    value="${entry#*=}"
    case "$scope:$name" in
      api:KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 | \
        api:KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED | \
        frontend:KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN)
        continue
        ;;
    esac
    if [[ -n "$value" \
      && ( ( -n "$manual_raw" && "$value" == *"$manual_raw"* ) \
        || ( -n "$manual_digest" && "$value" == *"$manual_digest"* ) ) ]]; then
      echo "manual Feature create credentials are not allowed in $scope runtime aliases" >&2
      exit 1
    fi
  done
}

for manual_create_key in \
  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED; do
  read_scoped_env_key "$ENV_FILE" "$manual_create_key"
  if [[ "$SCOPED_ENV_FOUND" == "1" ]]; then
    echo "$manual_create_key must not be configured in root env because Dagster reads that file" >&2
    exit 1
  fi
done
frontend_runtime_dir="$ROOT_DIR/packages/kor-travel-map-admin/frontend"
validate_frontend_manual_create_dotenv "$FRONTEND_ENV_FILE"

COMMON_PROCESS_ENV=(
  "PATH=$PATH"
  "HOME=${HOME:-$ROOT_DIR}"
  "LANG=${LANG:-C.UTF-8}"
  "PYTHONUNBUFFERED=1"
)
for name in \
  LC_ALL LC_CTYPE TZ VIRTUAL_ENV PYTHONPATH LD_LIBRARY_PATH SSL_CERT_FILE \
  REQUESTS_CA_BUNDLE CURL_CA_BUNDLE HTTP_PROXY HTTPS_PROXY NO_PROXY \
  http_proxy https_proxy no_proxy; do
  if [[ -v "$name" ]]; then
    COMMON_PROCESS_ENV+=("$name=${!name}")
  fi
done

API_SHARED_ENV=()
FRONTEND_PROCESS_ENV=()
DAGSTER_PROCESS_ENV=()
while IFS= read -r name; do
  case "$name" in
    KOR_TRAVEL_MAP_OPS_* | KOR_TRAVEL_MAP_API_OPS_*)
      echo "ops principal keys are allowed only in the API package env: $name" >&2
      exit 1
      ;;
  esac
  case "$name" in
    KOR_TRAVEL_MAP_PG_* | KOR_TRAVEL_MAP_OBJECT_STORE_* | KOR_TRAVEL_MAP_OFFLINE_UPLOAD_* | KOR_TRAVEL_MAP_FILE_REGISTRY_* | KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS)
      API_SHARED_ENV+=("$name=${!name}")
      ;;
  esac
  case "$name" in
    NEXT_PUBLIC_* | KOR_TRAVEL_GEO_API_KEY | KOR_TRAVEL_MAP_API_INTERNAL_URL | KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET | KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN | KOR_TRAVEL_MAP_UI_*)
      FRONTEND_PROCESS_ENV+=("$name=${!name}")
      ;;
  esac
  case "$name" in
    KOR_TRAVEL_MAP_API_* | KOR_TRAVEL_MAP_ADMIN_* | KOR_TRAVEL_MAP_UI_*)
      ;;
    KOR_TRAVEL_MAP_* | DAGSTER_*)
      DAGSTER_PROCESS_ENV+=("$name=${!name}")
      ;;
  esac
done < <(compgen -A variable)

declare -a API_SCOPED_ENV=()
declare -A API_SCOPED_VALUES=()
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"
  [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
  if [[ "$line" == export\ * ]]; then
    line="${line#export }"
  fi
  [[ "$line" == *=* ]] || continue
  key="${line%%=*}"
  value="${line#*=}"
  if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "invalid API env key: $key" >&2
    exit 1
  fi
  case "$key" in
    KOR_TRAVEL_MAP_API_KMA_SERVICE_KEY | KOR_TRAVEL_MAP_API_KMA_APIHUB_KEY | KOR_TRAVEL_MAP_API_OPINET_SERVICE_KEY | KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY | KOR_TRAVEL_MAP_API_VISITKOREA_SERVICE_KEY | KOR_TRAVEL_MAP_API_KREX_SERVICE_KEY | KOR_TRAVEL_MAP_API_KNPS_SERVICE_KEY | KOR_TRAVEL_MAP_API_AIRKOREA_SERVICE_KEY | KOR_TRAVEL_MAP_API_KRFOREST_SERVICE_KEY | KOR_TRAVEL_MAP_API_ETL_LIVE_PREVIEW_ENABLED)
      echo "removed provider runtime key is not allowed in API env: $key" >&2
      exit 1
      ;;
    KOR_TRAVEL_MAP_API_INTERNAL_URL)
      echo "frontend-only key is not allowed in API env: $key" >&2
      exit 1
      ;;
    KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET)
      echo "shared admin proxy secret must be configured only in root env: KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET" >&2
      exit 1
      ;;
    KOR_TRAVEL_MAP_API_OPS_ACTOR)
      echo "KOR_TRAVEL_MAP_API_OPS_ACTOR was removed; the audit actor is fixed" >&2
      exit 1
      ;;
    KOR_TRAVEL_MAP_API_* | KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_* | KOR_TRAVEL_MAP_KAKAO_* | KOR_TRAVEL_MAP_NAVER_* | KOR_TRAVEL_MAP_GOOGLE_PLACES_*)
      ;;
    *)
      echo "unsupported key in API env: $key" >&2
      exit 1
      ;;
  esac
  if [[ -v "API_SCOPED_VALUES[$key]" ]]; then
    echo "duplicate key in API env: $key" >&2
    exit 1
  fi
  if [[ ${#value} -ge 2 ]]; then
    first="${value:0:1}"
    last="${value: -1}"
    if [[ "$first$last" == '""' || "$first$last" == "''" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" =~ [[:space:]]# ]]; then
      echo "inline comments are not allowed in API env values: $key" >&2
      exit 1
    fi
  fi
  API_SCOPED_VALUES["$key"]="$value"
  API_SCOPED_ENV+=("$key=$value")
done <"$API_ENV_FILE"

# Secret-store process env는 package file보다 우선한다. root `.env`에서 온 값은
# 위 guard가 거부하므로 이 override가 Dagster/provider env_file로 새지 않는다.
for manual_api_key in \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED; do
  if [[ -v "$manual_api_key" ]]; then
    API_SCOPED_VALUES["$manual_api_key"]="${!manual_api_key}"
    API_SCOPED_ENV+=("$manual_api_key=${!manual_api_key}")
  fi
done

manual_feature_create_raw="${KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN:-}"
if [[ ! -v KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN ]]; then
  read_scoped_env_key "$FRONTEND_ENV_FILE" KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN
  if [[ "$SCOPED_ENV_FOUND" == "1" ]]; then
    manual_feature_create_raw="$SCOPED_ENV_VALUE"
    FRONTEND_PROCESS_ENV+=(
      "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN=$manual_feature_create_raw"
    )
  fi
fi
validate_frontend_manual_create_dotenv \
  "$FRONTEND_ENV_FILE" \
  "$manual_feature_create_raw"
while IFS= read -r public_name; do
  public_value="${!public_name:-}"
  if [[ -n "$manual_feature_create_raw" && -n "$public_value" \
    && "$public_value" == *"$manual_feature_create_raw"* ]]; then
    echo "manual Feature create credential must be distinct from public frontend values" >&2
    exit 1
  fi
done < <(compgen -A variable NEXT_PUBLIC_)

frontend_proxy_secret="${KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET:-}"
trimmed_frontend_proxy_secret="${frontend_proxy_secret#"${frontend_proxy_secret%%[![:space:]]*}"}"
trimmed_frontend_proxy_secret="${trimmed_frontend_proxy_secret%"${trimmed_frontend_proxy_secret##*[![:space:]]}"}"
if [[ "$frontend_proxy_secret" != "$trimmed_frontend_proxy_secret" || ${#frontend_proxy_secret} -lt 32 ]]; then
  echo "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET must be at least 32 characters without surrounding whitespace" >&2
  exit 1
fi

ops_read_key=KOR_TRAVEL_MAP_API_OPS_READ_TOKEN
ops_cancel_key=KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN
ops_fixture_key=KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN
ops_required_key=KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED
ops_read_is_set=0
ops_cancel_is_set=0
ops_fixture_is_set=0
[[ -v "API_SCOPED_VALUES[$ops_read_key]" ]] && ops_read_is_set=1
[[ -v "API_SCOPED_VALUES[$ops_cancel_key]" ]] && ops_cancel_is_set=1
[[ -v "API_SCOPED_VALUES[$ops_fixture_key]" ]] && ops_fixture_is_set=1
if [[ "$ops_read_is_set" != "$ops_cancel_is_set" || "$ops_read_is_set" != "$ops_fixture_is_set" ]]; then
  echo "$ops_read_key, $ops_cancel_key, and $ops_fixture_key must be configured together" >&2
  exit 1
fi
ops_principal_required=false
if [[ -v "API_SCOPED_VALUES[$ops_required_key]" ]]; then
  ops_principal_required="${API_SCOPED_VALUES[$ops_required_key]}"
  if [[ "$ops_principal_required" != "true" && "$ops_principal_required" != "false" ]]; then
    echo "$ops_required_key must be exactly true or false" >&2
    exit 1
  fi
fi
if [[ "$ops_read_is_set" == "0" ]]; then
  if [[ "$ops_principal_required" == "true" ]]; then
    echo "ops principal is required but read/cancel/fixture tokens are absent" >&2
    exit 1
  fi
else
  ops_read_token="${API_SCOPED_VALUES[$ops_read_key]}"
  ops_cancel_token="${API_SCOPED_VALUES[$ops_cancel_key]}"
  ops_fixture_token="${API_SCOPED_VALUES[$ops_fixture_key]}"
  if [[ -z "$ops_read_token" && -z "$ops_cancel_token" && -z "$ops_fixture_token" ]]; then
    if [[ "$ops_principal_required" == "true" ]]; then
      echo "ops principal is required but read/cancel/fixture tokens are empty" >&2
      exit 1
    fi
  elif [[ -z "$ops_read_token" || -z "$ops_cancel_token" || -z "$ops_fixture_token" ]]; then
    echo "ops read, cancel, and fixture tokens must all be empty or all be non-empty" >&2
    exit 1
  else
    if [[ "$ops_read_token" =~ [[:space:]] ]]; then
      echo "$ops_read_key must contain no whitespace" >&2
      exit 1
    fi
    if [[ "$ops_cancel_token" =~ [[:space:]] ]]; then
      echo "$ops_cancel_key must contain no whitespace" >&2
      exit 1
    fi
    if [[ "$ops_fixture_token" =~ [[:space:]] ]]; then
      echo "$ops_fixture_key must contain no whitespace" >&2
      exit 1
    fi
    if [[ ${#ops_read_token} -lt 32 ]]; then
      echo "$ops_read_key must be at least 32 characters" >&2
      exit 1
    fi
    if [[ ${#ops_cancel_token} -lt 32 ]]; then
      echo "$ops_cancel_key must be at least 32 characters" >&2
      exit 1
    fi
    if [[ ${#ops_fixture_token} -lt 32 ]]; then
      echo "$ops_fixture_key must be at least 32 characters" >&2
      exit 1
    fi
    if [[ "$ops_read_token" == "$ops_cancel_token" || "$ops_read_token" == "$ops_fixture_token" || "$ops_cancel_token" == "$ops_fixture_token" ]]; then
      echo "ops read, cancel, and fixture tokens must be distinct" >&2
      exit 1
    fi
    if [[ "$ops_read_token" == "$frontend_proxy_secret" || "$ops_cancel_token" == "$frontend_proxy_secret" || "$ops_fixture_token" == "$frontend_proxy_secret" ]]; then
      echo "ops read/cancel/fixture tokens must be distinct from the admin proxy secret" >&2
      exit 1
    fi
    api_service_token="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_SERVICE_TOKEN]:-}"
    if [[ -n "$api_service_token" && ( "$ops_read_token" == "$api_service_token" || "$ops_cancel_token" == "$api_service_token" || "$ops_fixture_token" == "$api_service_token" ) ]]; then
      echo "ops read/cancel/fixture tokens must be distinct from the service token" >&2
      exit 1
    fi
  fi
fi

cursor_signing_key=KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET
cursor_signing_secret="${API_SCOPED_VALUES[$cursor_signing_key]:-}"
api_profile="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_PROFILE]:-local-dev}"
features_routes_enabled="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED]:-true}"
if [[ "$api_profile" != "production" && "$api_profile" != "local-dev" ]]; then
  echo "KOR_TRAVEL_MAP_API_PROFILE must be exactly production or local-dev" >&2
  exit 1
fi
if [[ "$api_profile" != "local-dev" \
  || "${KOR_TRAVEL_MAP_API_PROFILE:-local-dev}" != "local-dev" \
  || "${KOR_TRAVEL_MAP_DAGSTER_PROFILE:-local-dev}" != "local-dev" ]]; then
  echo "admin:stack is a loopback local-dev smoke launcher; production requires Docker Manager" >&2
  exit 1
fi
while IFS= read -r authority_key; do
  case "$authority_key" in
    KOR_TRAVEL_MAP_*PERMIT* | KOR_TRAVEL_MAP_*WRITER_FENCE* | \
      KOR_TRAVEL_MAP_*HANDOFF*)
      echo "admin:stack rejects production authority input: $authority_key" >&2
      exit 1
      ;;
  esac
done < <(compgen -A variable KOR_TRAVEL_MAP_)
if [[ "$features_routes_enabled" != "true" && "$features_routes_enabled" != "false" ]]; then
  echo "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED must be exactly true or false" >&2
  exit 1
fi
if [[ "$api_profile" == "production" && "$features_routes_enabled" == "true" && -z "$cursor_signing_secret" ]]; then
  echo "production profile is fail-closed (ADR-066): $cursor_signing_key must be configured while the public features surface is enabled" >&2
  exit 1
fi
if [[ -n "$cursor_signing_secret" ]]; then
  if [[ "$cursor_signing_secret" =~ [[:space:]] ]]; then
    echo "$cursor_signing_key must contain no whitespace" >&2
    exit 1
  fi
  if [[ ${#cursor_signing_secret} -lt 32 ]]; then
    echo "$cursor_signing_key must be at least 32 characters" >&2
    exit 1
  fi
  api_service_token="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_SERVICE_TOKEN]:-}"
  api_metrics_token="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_METRICS_TOKEN]:-}"
  api_public_key="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_VWORLD_API_KEY]:-}"
  if [[ "$cursor_signing_secret" == "$frontend_proxy_secret" \
    || ( -n "$api_service_token" && "$cursor_signing_secret" == "$api_service_token" ) ]]; then
    echo "$cursor_signing_key must be distinct from admin and service credentials" >&2
    exit 1
  fi
  if [[ "$ops_read_is_set" == "1" \
    && ( "$cursor_signing_secret" == "${API_SCOPED_VALUES[$ops_read_key]}" \
      || "$cursor_signing_secret" == "${API_SCOPED_VALUES[$ops_cancel_key]}" \
      || "$cursor_signing_secret" == "${API_SCOPED_VALUES[$ops_fixture_key]}" ) ]]; then
    echo "$cursor_signing_key must be distinct from ops credentials" >&2
    exit 1
  fi
  if [[ -n "$api_metrics_token" && "$cursor_signing_secret" == "$api_metrics_token" ]]; then
    echo "$cursor_signing_key must be distinct from the metrics credential" >&2
    exit 1
  fi
  if [[ -n "$api_public_key" && "$cursor_signing_secret" == "$api_public_key" ]]; then
    echo "$cursor_signing_key must be distinct from the public API key" >&2
    exit 1
  fi
fi

manual_feature_create_digest="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256]:-}"
manual_feature_create_enabled="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED]:-false}"
if [[ "$manual_feature_create_enabled" != "true" && "$manual_feature_create_enabled" != "false" ]]; then
  echo "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED must be exactly true or false" >&2
  exit 1
fi
manual_feature_create_required=false
if [[ "$api_profile" == "production" || "$manual_feature_create_enabled" == "true" \
  || -n "$manual_feature_create_raw" || -n "$manual_feature_create_digest" ]]; then
  manual_feature_create_required=true
fi
if [[ "$manual_feature_create_required" == "true" ]]; then
  if [[ ${#manual_feature_create_raw} -lt 32 || "$manual_feature_create_raw" =~ [[:space:]] ]]; then
    echo "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN must be at least 32 characters and contain no whitespace" >&2
    exit 1
  fi
  if [[ ! "$manual_feature_create_digest" =~ ^[0-9a-f]{64}$ ]]; then
    echo "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 must be lowercase SHA-256 hex" >&2
    exit 1
  fi
  manual_feature_create_computed="$(printf '%s' "$manual_feature_create_raw" | sha256sum)"
  manual_feature_create_computed="${manual_feature_create_computed%% *}"
  if [[ "$manual_feature_create_computed" != "$manual_feature_create_digest" ]]; then
    echo "manual Feature create raw token SHA-256 must match the API digest" >&2
    exit 1
  fi
  if [[ "$manual_feature_create_raw" == "$frontend_proxy_secret" ]]; then
    echo "manual Feature create credential must be distinct from existing credentials" >&2
    exit 1
  fi
  for protected_name in \
    KOR_TRAVEL_MAP_API_SERVICE_TOKEN \
    KOR_TRAVEL_MAP_API_OPS_READ_TOKEN \
    KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN \
    KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN \
    KOR_TRAVEL_MAP_API_METRICS_TOKEN; do
    protected_value="${API_SCOPED_VALUES[$protected_name]:-${!protected_name:-}}"
    if [[ -n "$protected_value" && "$manual_feature_create_raw" == "$protected_value" ]]; then
      echo "manual Feature create credential must be distinct from existing credentials" >&2
      exit 1
    fi
  done
  for protected_name in \
    KOR_TRAVEL_MAP_API_PINVI_CURATION_SNAPSHOT_TOKEN_SHA256 \
    KOR_TRAVEL_MAP_API_PINVI_CURATION_CUTOVER_MAPPING_TOKEN_SHA256; do
    protected_value="${API_SCOPED_VALUES[$protected_name]:-${!protected_name:-}}"
    if [[ -n "$protected_value" && "$manual_feature_create_digest" == "$protected_value" ]]; then
      echo "manual Feature create digest must be distinct from curation credentials" >&2
      exit 1
    fi
  done
  protected_value="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_CACHE_TARGET_SERVICE_PRINCIPALS]:-${KOR_TRAVEL_MAP_API_CACHE_TARGET_SERVICE_PRINCIPALS:-}}"
  if [[ -n "$protected_value" && "$protected_value" == *"$manual_feature_create_digest"* ]]; then
    echo "manual Feature create digest must be distinct from cache-target credentials" >&2
    exit 1
  fi
fi
while IFS= read -r public_name; do
  public_value="${!public_name:-}"
  if [[ -n "$manual_feature_create_digest" && -n "$public_value" \
    && "$public_value" == *"$manual_feature_create_digest"* ]]; then
    echo "manual Feature create credentials must be distinct from public frontend values" >&2
    exit 1
  fi
done < <(compgen -A variable NEXT_PUBLIC_)
reject_exported_manual_feature_create_aliases \
  "$manual_feature_create_raw" \
  "$manual_feature_create_digest"
validate_manual_feature_create_routed_env \
  api \
  "$manual_feature_create_raw" \
  "$manual_feature_create_digest" \
  "${API_SHARED_ENV[@]}" \
  "${API_SCOPED_ENV[@]}"
validate_manual_feature_create_routed_env \
  frontend \
  "$manual_feature_create_raw" \
  "$manual_feature_create_digest" \
  "${FRONTEND_PROCESS_ENV[@]}"
validate_manual_feature_create_routed_env \
  dagster \
  "$manual_feature_create_raw" \
  "$manual_feature_create_digest" \
  "${DAGSTER_PROCESS_ENV[@]}"

# Next와 같은 parser·development precedence로 실제 auto dotenv 결과를 계산한다.
# raw는 argv/초기 OS env가 아니라 stdin으로 넘기고 validator 내부에서만 Next의
# process-env precedence를 재현한다. child는 M01 세 키가 든 caller env를 상속하지 않는다.
node_bin="$(command -v node || true)"
if [[ -z "$node_bin" ]]; then
  echo "node is required to validate frontend dotenv files" >&2
  exit 1
fi
if ! printf '%s\0' \
  "$manual_feature_create_raw" \
  "$manual_feature_create_digest" \
  "${COMMON_PROCESS_ENV[@]}" \
  "${FRONTEND_PROCESS_ENV[@]}" \
  | env -i \
    PATH="$PATH" \
    HOME="${HOME:-$ROOT_DIR}" \
    NODE_ENV=development \
    "$node_bin" \
    "$ROOT_DIR/scripts/validate-frontend-manual-create-env.mjs" \
    "$frontend_runtime_dir"; then
  exit 1
fi

# Secret-store process env는 위에서 API/frontend 전용 env-i 배열에 캡처했다. 이
# 시점부터 preflight-ports, Alembic, DB bootstrap, Dagster launcher 같은 일반 child가
# 세 값을 상속하지 못하도록 export 상태를 제거한다. 전용 runtime만 아래의 배열을
# 명시적으로 소비한다.
unset \
  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED
for manual_create_key in \
  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN \
  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 \
  KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED; do
  if [[ -v "$manual_create_key" ]]; then
    echo "internal error: manual Feature create credential remained exported" >&2
    exit 1
  fi
done
unset \
  manual_feature_create_computed \
  manual_feature_create_digest \
  manual_feature_create_enabled \
  manual_feature_create_raw \
  manual_feature_create_required \
  protected_value

api_backup_root="${API_SCOPED_VALUES[KOR_TRAVEL_MAP_API_BACKUP_ROOT]:-data/backups}"
if [[ "$api_backup_root" != /* ]]; then
  api_backup_root="$ROOT_DIR/$api_backup_root"
fi

if [[ "${KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY:-0}" == "1" ]]; then
  echo "admin stack environment is valid"
  exit 0
fi

LOG_DIR="${KOR_TRAVEL_MAP_LOG_DIR:-"$ROOT_DIR/.codex_tmp/admin-stack"}"
mkdir -p "$LOG_DIR"

# 고정 포트가 이미 사용 중이면 새 포트로 열지 않고, 강제종료 여부를 묻는다.
# 강제종료하지 않으면 preflight가 exit 1 → set -e로 기동 중지(기존 서비스 보존).
"$ROOT_DIR/scripts/preflight-ports.sh" \
  "$KOR_TRAVEL_MAP_API_PORT" "$KOR_TRAVEL_MAP_ADMIN_WEB_PORT" "$KOR_TRAVEL_MAP_DAGSTER_PORT"

PYTHON_BIN="${PYTHON_BIN:-"$ROOT_DIR/.venv/bin/python"}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi

console_script_usable() {
  local bin="$1"
  if [[ ! -x "$bin" ]]; then
    return 1
  fi

  local first_line=""
  IFS= read -r first_line <"$bin" || true
  if [[ "$first_line" != '#!'* || "$first_line" == '#!/usr/bin/env '* ]]; then
    return 0
  fi

  local interpreter="${first_line#\#!}"
  interpreter="${interpreter%% *}"
  [[ -x "$interpreter" ]]
}

dagster_webserver_bin="${DAGSTER_WEBSERVER_BIN:-"$ROOT_DIR/.venv/bin/dagster-webserver"}"
if console_script_usable "$dagster_webserver_bin"; then
  DAGSTER_WEBSERVER_CMD=("$dagster_webserver_bin")
else
  dagster_webserver_bin="$(command -v dagster-webserver || true)"
  if [[ -n "$dagster_webserver_bin" ]] && console_script_usable "$dagster_webserver_bin"; then
    DAGSTER_WEBSERVER_CMD=("$dagster_webserver_bin")
  else
    DAGSTER_WEBSERVER_CMD=(
      "$PYTHON_BIN" -c
      "from dagster_webserver.cli import main; raise SystemExit(main())"
    )
  fi
fi

dagster_daemon_bin="${DAGSTER_DAEMON_BIN:-"$ROOT_DIR/.venv/bin/dagster-daemon"}"
if console_script_usable "$dagster_daemon_bin"; then
  DAGSTER_DAEMON_CMD=("$dagster_daemon_bin")
else
  dagster_daemon_bin="$(command -v dagster-daemon || true)"
  if [[ -n "$dagster_daemon_bin" ]] && console_script_usable "$dagster_daemon_bin"; then
    DAGSTER_DAEMON_CMD=("$dagster_daemon_bin")
  else
    DAGSTER_DAEMON_CMD=(
      "$PYTHON_BIN" -c
      "from dagster._daemon.cli import main; raise SystemExit(main())"
    )
  fi
fi

echo "verify pre-provisioned local application and Dagster databases"
(
  "$PYTHON_BIN" - <<'PY'
from __future__ import annotations

import os
from urllib.parse import urlsplit

import psycopg


def _psycopg_dsn(value: str) -> str:
    for scheme in ("postgresql+psycopg://", "postgresql+asyncpg://"):
        if value.startswith(scheme):
            return value.replace(scheme, "postgresql://", 1)
    return value


def _require_loopback_dsn(name: str) -> str:
    value = os.environ.get(name, "")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"postgresql", "postgresql+psycopg", "postgresql+asyncpg"}
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port not in {None, 5432}
        or not parsed.username
        or not parsed.password
        or not parsed.path.startswith("/")
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit(f"{name} must be one strict loopback PostgreSQL DSN")
    return _psycopg_dsn(value)


app_dsn = _require_loopback_dsn("KOR_TRAVEL_MAP_PG_DSN_SYNC")
metadata_dsn = _require_loopback_dsn("KOR_TRAVEL_MAP_DAGSTER_PG_URL")
metadata_url = urlsplit(os.environ["KOR_TRAVEL_MAP_DAGSTER_PG_URL"])
metadata_identity = os.environ["KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB"]
if metadata_url.username != metadata_identity or metadata_url.path != f"/{metadata_identity}":
    raise SystemExit("Dagster metadata DSN must use its dedicated DB identity")

with psycopg.connect(app_dsn) as connection:
    application_identity = connection.execute(
        """
        SELECT current_database(), pg_control_system().system_identifier::text,
               owner.rolname
        FROM pg_database AS database
        JOIN pg_roles AS owner ON owner.oid = database.datdba
        WHERE database.datname = current_database()
        """
    ).fetchone()
    revisions = connection.execute(
        "SELECT version_num FROM public.alembic_version ORDER BY version_num"
    ).fetchall()
if application_identity is None or revisions != [("300",)]:
    raise SystemExit("admin:stack requires a pre-provisioned exact application revision 300")

with psycopg.connect(metadata_dsn) as connection:
    metadata = connection.execute(
        """
        SELECT current_database(), session_user::text, current_user::text,
               owner.rolname, role.rolsuper, role.rolcreatedb, role.rolcreaterole,
               role.rolreplication, role.rolbypassrls,
               (SELECT count(*) FROM pg_auth_members WHERE member = role.oid),
               (SELECT count(*) FROM pg_auth_members WHERE roleid = role.oid),
               pg_control_system().system_identifier::text,
               (SELECT count(*) FROM pg_tables WHERE schemaname = 'public')
        FROM pg_database AS database
        JOIN pg_roles AS owner ON owner.oid = database.datdba
        JOIN pg_roles AS role ON role.rolname = session_user
        WHERE database.datname = current_database()
        """
    ).fetchone()
expected_prefix = (
    metadata_identity,
    metadata_identity,
    metadata_identity,
    metadata_identity,
    False,
    False,
    False,
    False,
    False,
    0,
    0,
)
if metadata is None or metadata[:11] != expected_prefix:
    raise SystemExit("Dagster metadata database identity is not dedicated and restricted")
if metadata[11] != application_identity[1] or metadata[3] == application_identity[2]:
    raise SystemExit("application and Dagster metadata database isolation is invalid")
if not isinstance(metadata[12], int) or metadata[12] < 1:
    raise SystemExit("Dagster metadata storage must be migrated before admin:stack")
print("pre-provisioned local application and Dagster database identities verified")
PY
)

DAGSTER_HOME_DIR="${DAGSTER_HOME:-"$ROOT_DIR/.dagster"}"
mkdir -p "$DAGSTER_HOME_DIR"
install -m 0644 "$ROOT_DIR/docker/dagster.yaml" "$DAGSTER_HOME_DIR/dagster.yaml"

# dev 기본은 내부 주소(127.0.0.1) 바인드다. Windows Playwright e2e처럼 WSL 밖에서
# 접근해야 하는 경우에만 KOR_TRAVEL_MAP_*_BIND_HOST=0.0.0.0으로 명시 opt-in한다
# (docs/dev-environment.md §dev/prod 구분).
API_BIND_HOST="${KOR_TRAVEL_MAP_API_BIND_HOST:-127.0.0.1}"
WEB_BIND_HOST="${KOR_TRAVEL_MAP_ADMIN_WEB_BIND_HOST:-127.0.0.1}"
DAGSTER_BIND_HOST="${KOR_TRAVEL_MAP_DAGSTER_BIND_HOST:-127.0.0.1}"
NEXT_DEV_ARGS=(dev)
if (
  cd "$ROOT_DIR/packages/kor-travel-map-admin/frontend"
  npx next dev --help 2>/dev/null | grep -q -- "--webpack"
); then
  NEXT_DEV_ARGS+=(--webpack)
fi

stop_logged_pid() {
  local name="$1"
  local pid_file="$LOG_DIR/$name.pid"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    echo "$name pid=$pid stopping"
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
}

stop_logged_pid dagster-daemon

start_bg() {
  local name="$1"
  shift
  local log_file="$LOG_DIR/$name.log"
  if command -v setsid >/dev/null 2>&1; then
    nohup setsid "$@" >"$log_file" 2>&1 </dev/null &
  else
    nohup "$@" >"$log_file" 2>&1 </dev/null &
  fi
  local pid="$!"
  echo "$pid" >"$LOG_DIR/$name.pid"
  echo "$name pid=$pid log=$log_file"
}

(
  cd "$ROOT_DIR/packages/kor-travel-map-api"
  start_bg api env -i \
    "${COMMON_PROCESS_ENV[@]}" \
    "${API_SHARED_ENV[@]}" \
    "${API_SCOPED_ENV[@]}" \
    KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET="$frontend_proxy_secret" \
    KOR_TRAVEL_MAP_API_HOST="$API_BIND_HOST" \
    KOR_TRAVEL_MAP_API_PORT="$KOR_TRAVEL_MAP_API_PORT" \
    KOR_TRAVEL_MAP_API_BACKUP_ROOT="$api_backup_root" \
    KOR_TRAVEL_MAP_API_BACKUP_PROJECT_ROOT="$ROOT_DIR" \
    "$PYTHON_BIN" -m uvicorn kortravelmap.api.app:app \
    --host "$API_BIND_HOST" --port "$KOR_TRAVEL_MAP_API_PORT"
)

(
  cd "$ROOT_DIR/packages/kor-travel-map-admin/frontend"
  start_bg web env -i \
    "${COMMON_PROCESS_ENV[@]}" \
    "${FRONTEND_PROCESS_ENV[@]}" \
    npx next "${NEXT_DEV_ARGS[@]}" --port "$KOR_TRAVEL_MAP_ADMIN_WEB_PORT" --hostname "$WEB_BIND_HOST"
)

(
  cd "$ROOT_DIR"
  start_bg dagster env -i \
    "${COMMON_PROCESS_ENV[@]}" \
    "${DAGSTER_PROCESS_ENV[@]}" \
    TMPDIR=/tmp TEMP=/tmp TMP=/tmp \
    DAGSTER_HOME="$DAGSTER_HOME_DIR" \
    DAGSTER_DISABLE_TELEMETRY="$DAGSTER_DISABLE_TELEMETRY" \
    KOR_TRAVEL_MAP_DAGSTER_PG_URL="$KOR_TRAVEL_MAP_DAGSTER_PG_URL" \
    "${DAGSTER_WEBSERVER_CMD[@]}" -m kortravelmap.dagster.definitions \
    -h "$DAGSTER_BIND_HOST" -p "$KOR_TRAVEL_MAP_DAGSTER_PORT"
)

(
  cd "$ROOT_DIR"
  start_bg dagster-daemon env -i \
    "${COMMON_PROCESS_ENV[@]}" \
    "${DAGSTER_PROCESS_ENV[@]}" \
    TMPDIR=/tmp TEMP=/tmp TMP=/tmp \
    DAGSTER_HOME="$DAGSTER_HOME_DIR" \
    DAGSTER_DISABLE_TELEMETRY="$DAGSTER_DISABLE_TELEMETRY" \
    KOR_TRAVEL_MAP_DAGSTER_PG_URL="$KOR_TRAVEL_MAP_DAGSTER_PG_URL" \
    "${DAGSTER_DAEMON_CMD[@]}" run -m kortravelmap.dagster.definitions
)

wait_url() {
  local name="$1"
  local url="$2"
  local pid_file="$LOG_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"
  local pid
  pid="$(cat "$pid_file")"
  local pid_exited=""
  for _ in $(seq 1 60); do
    if url_ready "$url"; then
      echo "$name ready: $url"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      pid_exited="yes"
    fi
    sleep 1
  done
  echo "$name did not become ready. log: $log_file" >&2
  if [[ "$pid_exited" == "yes" ]]; then
    echo "$name launcher pid $pid exited before readiness." >&2
  fi
  tail -n 80 "$log_file" >&2 || true
  return 1
}

url_ready() {
  local url="$1"
  if curl -fsS "$url" >/dev/null 2>&1; then
    return 0
  fi
  if command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c curl.exe -fsS "$url" -o NUL >/dev/null 2>&1 && return 0
  fi
  return 1
}

ensure_bg_alive() {
  local name="$1"
  local pid_file="$LOG_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"
  local pid
  pid="$(cat "$pid_file")"
  if kill -0 "$pid" 2>/dev/null; then
    echo "$name running: pid=$pid"
    return 0
  fi
  echo "$name exited before readiness. log: $log_file" >&2
  tail -n 80 "$log_file" >&2 || true
  return 1
}

wait_url api "http://127.0.0.1:${KOR_TRAVEL_MAP_API_PORT}/health"
wait_url web "http://127.0.0.1:${KOR_TRAVEL_MAP_ADMIN_WEB_PORT}/"
wait_url dagster "http://127.0.0.1:${KOR_TRAVEL_MAP_DAGSTER_PORT}/"
ensure_bg_alive dagster-daemon

echo "api=http://127.0.0.1:${KOR_TRAVEL_MAP_API_PORT}"
echo "web=http://127.0.0.1:${KOR_TRAVEL_MAP_ADMIN_WEB_PORT}"
echo "dagster=http://127.0.0.1:${KOR_TRAVEL_MAP_DAGSTER_PORT}"

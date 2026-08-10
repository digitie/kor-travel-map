#!/usr/bin/env bash
# T-VN-34C — n150 전용 fresh PostGIS / Map+PinVi isolated live gate.
#
# 이 파일은 ``install-tvn34c-n150-fresh-live-e2e.sh``가 root-owned immutable
# snapshot으로 설치한 뒤에만 실행한다. production compose project, DB, volume,
# image에는 절대 연결하지 않는다.
set -Eeuo pipefail
umask 077

readonly SCRIPT_NAME="$(basename "$0")"
readonly INSTALL_DIR="$(cd -- "$(dirname -- "$0")" && pwd -P)"
readonly MANIFEST="$INSTALL_DIR/manifest.json"
readonly RECEIPT="$INSTALL_DIR/consumer-rollout-v1.json"
readonly MAP_ARCHIVE="$INSTALL_DIR/map-source.tar.gz"
readonly PINVI_ARCHIVE="$INSTALL_DIR/pinvi-source.tar.gz"
readonly SEED_HELPER="$INSTALL_DIR/scripts/tvn34c_fresh_live_etl_seed.py"
readonly STATE_ROOT="$INSTALL_DIR/runs"
readonly BLOCKED_FILE="$INSTALL_DIR/BLOCKED.json"
readonly EXPECTED_HEAD="0097_tvn34c_final_cutover"

MODE="${1:-run}"
RUN_ID=""
RUN_KEY=""
RUN_DIR=""
MAP_DIR=""
PINVI_DIR=""
MAP_ENV=""
PINVI_ENV=""
MAP_COMPOSE_OVERRIDE=""
MAP_PROJECT=""
PINVI_PROJECT=""
MAP_NETWORK=""
PINVI_NETWORK=""
MAP_API_IMAGE=""
MAP_DAGSTER_IMAGE=""
MAP_PLAYWRIGHT_IMAGE=""
PINVI_API_CONTAINER=""
MAP_COMMIT=""
PINVI_COMMIT=""
MAP_ARCHIVE_SHA256=""
PINVI_ARCHIVE_SHA256=""
SEED_HELPER_SHA256=""
MAP_E2E_FEATURE_ID=""
UI_ADMIN_PASSWORD=""
FINISHED=0

die() {
  printf 'T-VN-34C n150 fresh live failed: %s (values redacted)\n' "$1" >&2
  exit 1
}

require_root_snapshot() {
  [[ "$(id -u)" == "0" ]] || die "root-owned snapshot runner must be invoked via sudo"
  [[ "$INSTALL_DIR" == /var/lib/kor-travel-map/tvn34c-fresh-live/* ]] ||
    die "runner install directory is outside the dedicated state root"
  for path in "$INSTALL_DIR" "$MANIFEST" "$RECEIPT" "$MAP_ARCHIVE" "$PINVI_ARCHIVE" "$SEED_HELPER" "$0"; do
    [[ -e "$path" && ! -L "$path" ]] || die "immutable snapshot input is missing or unsafe"
  done
  [[ "$(stat -c '%u:%g:%a' -- "$INSTALL_DIR")" == "0:0:700" ]] ||
    die "immutable snapshot directory metadata is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$MANIFEST")" == "0:0:600" ]] ||
    die "manifest metadata is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$RECEIPT")" == "0:0:600" ]] ||
    die "consumer receipt metadata is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$MAP_ARCHIVE")" == "0:0:600" ]] ||
    die "Map archive metadata is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$PINVI_ARCHIVE")" == "0:0:600" ]] ||
    die "PinVi archive metadata is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$0")" == "0:0:500" ]] ||
    die "runner metadata is unsafe"
  [[ "$(stat -c '%u:%g:%a' -- "$SEED_HELPER")" == "0:0:500" ]] ||
    die "fresh ETL helper metadata is unsafe"
}

read_manifest() {
  local values
  values="$(python3 - "$MANIFEST" "$0" "$RECEIPT" <<'PY'
import hashlib
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
runner_path = Path(sys.argv[2])
receipt_path = Path(sys.argv[3])
helper_path = runner_path.parent / "scripts" / "tvn34c_fresh_live_etl_seed.py"
data = json.loads(manifest_path.read_text(encoding="utf-8"))
pattern = re.compile(r"^[0-9a-f]{40}$")
sha_pattern = re.compile(r"^[0-9a-f]{64}$")
if set(data) != {"map", "pinvi", "receipt_sha256", "runner_sha256", "seed_helper_sha256", "version"} or data["version"] != 3:
    raise SystemExit(2)
for side in ("map", "pinvi"):
    value = data[side]
    if set(value) != {"archive_sha256", "commit"}:
        raise SystemExit(3)
    if not pattern.fullmatch(value["commit"]) or not sha_pattern.fullmatch(value["archive_sha256"]):
        raise SystemExit(4)
if not all(sha_pattern.fullmatch(data[name]) for name in ("runner_sha256", "seed_helper_sha256", "receipt_sha256")):
    raise SystemExit(5)
if hashlib.sha256(runner_path.read_bytes()).hexdigest() != data["runner_sha256"]:
    raise SystemExit(6)
if hashlib.sha256(helper_path.read_bytes()).hexdigest() != data["seed_helper_sha256"]:
    raise SystemExit(7)
if hashlib.sha256(receipt_path.read_bytes()).hexdigest() != data["receipt_sha256"]:
    raise SystemExit(8)
print(data["map"]["commit"])
print(data["pinvi"]["commit"])
print(data["map"]["archive_sha256"])
print(data["pinvi"]["archive_sha256"])
print(data["seed_helper_sha256"])
PY
)" || die "manifest shape or immutable runner hash is invalid"
  mapfile -t manifest_values <<<"$values"
  [[ "${#manifest_values[@]}" == "5" ]] || die "manifest values are incomplete"
  MAP_COMMIT="${manifest_values[0]}"
  PINVI_COMMIT="${manifest_values[1]}"
  MAP_ARCHIVE_SHA256="${manifest_values[2]}"
  PINVI_ARCHIVE_SHA256="${manifest_values[3]}"
  SEED_HELPER_SHA256="${manifest_values[4]}"
  [[ "$(sha256sum "$MAP_ARCHIVE" | awk '{print $1}')" == "$MAP_ARCHIVE_SHA256" ]] ||
    die "Map source archive hash mismatch"
  [[ "$(sha256sum "$PINVI_ARCHIVE" | awk '{print $1}')" == "$PINVI_ARCHIVE_SHA256" ]] ||
    die "PinVi source archive hash mismatch"
}

safe_extract() {
  local archive="$1"
  local destination="$2"
  python3 - "$archive" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:gz") as archive:
    for item in archive.getmembers():
        name = item.name
        if (
            name.startswith("/")
            or ".." in name.split("/")
            or not (item.isfile() or item.isdir())
        ):
            raise SystemExit(1)
PY
  tar --extract --gzip --file "$archive" --directory "$destination" \
    --no-same-owner --no-same-permissions || die "source archive extraction failed"
}

read_pair_receipt() {
  python3 - "$RECEIPT" "$MAP_DIR" "$PINVI_DIR" "$MAP_COMMIT" "$PINVI_COMMIT" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
map_root = Path(sys.argv[2])
pinvi_root = Path(sys.argv[3])
map_commit = sys.argv[4]
pinvi_commit = sys.argv[5]
data = json.loads(path.read_text(encoding="utf-8"))
receipt = data["tasks"]["T-VN-34"]["pinvi_snapshot_receipt"]
if receipt["map_commit"] != map_commit or receipt["pinvi_commit"] != pinvi_commit:
    raise SystemExit(1)
for name in ("openapi.user.json", "openapi.json"):
    digest = hashlib.sha256((map_root / "packages" / "kor-travel-map-api" / name).read_bytes()).hexdigest()
    expected = receipt["map_user_openapi_sha256"] if name.endswith("user.json") else receipt["map_full_openapi_sha256"]
    if digest != expected:
        raise SystemExit(2)
for path, key in (
    (
        pinvi_root / "apps" / "api" / "tests" / "contract" / "kor-travel-map-openapi-user.json",
        "pinvi_user_vendor_sha256",
    ),
    (
        pinvi_root / "apps" / "api" / "tests" / "contract" / "kor-travel-map-openapi-admin-detail-snapshot.json",
        "pinvi_admin_detail_vendor_sha256",
    ),
):
    if hashlib.sha256(path.read_bytes()).hexdigest() != receipt[key]:
        raise SystemExit(3)
PY
}

random_secret() {
  openssl rand -hex 32
}

write_env_files() {
  local postgres_password migrator_password api_password dagster_password
  local admin_proxy_secret service_token cursor_secret metrics_token
  local ops_read ops_cancel ops_fixture ui_session ui_password_hash compose_ui_password_hash object_secret
  postgres_password="$(random_secret)"
  migrator_password="$(random_secret)"
  api_password="$(random_secret)"
  dagster_password="$(random_secret)"
  admin_proxy_secret="$(random_secret)"
  service_token="$(random_secret)"
  cursor_secret="$(random_secret)"
  metrics_token="$(random_secret)"
  ops_read="$(random_secret)"
  ops_cancel="$(random_secret)"
  ops_fixture="$(random_secret)"
  ui_session="$(random_secret)"
  UI_ADMIN_PASSWORD="$(random_secret)"
  ui_password_hash="$(UI_ADMIN_PASSWORD="$UI_ADMIN_PASSWORD" python3 - <<'PY'
import base64
import hashlib
import os
import secrets

def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

salt = secrets.token_bytes(16)
digest = hashlib.pbkdf2_hmac(
    "sha256", os.environ["UI_ADMIN_PASSWORD"].encode("utf-8"), salt, 310_000
)
print(f"pbkdf2_sha256$310000${encode(salt)}${encode(digest)}")
PY
)"
  # Compose의 env-file parser는 `$NAME`을 보간한다. PBKDF2 format의 `$`는 `$$`로
  # escape해야 frontend container가 원래 hash를 받는다.
  compose_ui_password_hash="${ui_password_hash//\$/\$\$}"
  object_secret="$(random_secret)"
  local port_seed
  port_seed="$((16#${RUN_KEY:0:4}))"
  local api_port dagster_port web_port postgres_port rustfs_port
  api_port="$((30000 + port_seed % 2000))"
  dagster_port="$((api_port + 1))"
  web_port="$((api_port + 2))"
  postgres_port="$((api_port + 3))"
  rustfs_port="$((api_port + 4))"
  MAP_ENV="$RUN_DIR/map.env"
  PINVI_ENV="$RUN_DIR/pinvi.env"
  cat >"$MAP_ENV" <<EOF
KOR_TRAVEL_MAP_GIT_COMMIT=$MAP_COMMIT
KOR_TRAVEL_MAP_POSTGRES_DB=kor_travel_map
KOR_TRAVEL_MAP_POSTGRES_USER=kor_travel_map
KOR_TRAVEL_MAP_POSTGRES_PASSWORD=$postgres_password
KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE=kor_travel_map
KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN=postgresql://kor_travel_map:$postgres_password@postgres:5432/kor_travel_map
KOR_TRAVEL_MAP_MIGRATOR_PASSWORD=$migrator_password
KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD=$api_password
KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD=$dagster_password
KOR_TRAVEL_MAP_MIGRATOR_PG_DSN=postgresql+asyncpg://ktm_feature_migrator:$migrator_password@postgres:5432/kor_travel_map
KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN=postgresql+asyncpg://ktm_feature_api_runtime:$api_password@postgres:5432/kor_travel_map
KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN=postgresql+asyncpg://ktm_feature_dagster_runtime:$dagster_password@postgres:5432/kor_travel_map
KOR_TRAVEL_MAP_PG_DSN=postgresql+asyncpg://ktm_feature_dagster_runtime:$dagster_password@postgres:5432/kor_travel_map
KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL=postgresql://kor_travel_map:$postgres_password@postgres:5432/kor_travel_map_dagster
KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=$EXPECTED_HEAD
KOR_TRAVEL_MAP_DOCKER_BIND_HOST=127.0.0.1
KOR_TRAVEL_MAP_API_PORT=$api_port
KOR_TRAVEL_MAP_DAGSTER_PORT=$dagster_port
KOR_TRAVEL_MAP_ADMIN_WEB_PORT=$web_port
KOR_TRAVEL_MAP_POSTGRES_HOST_PORT=$postgres_port
KOR_TRAVEL_MAP_RUSTFS_API_PORT=$rustfs_port
KOR_TRAVEL_MAP_RUSTFS_CONSOLE_PORT=$((rustfs_port + 1))
KOR_TRAVEL_MAP_MOIS_SOURCE_DB_VOLUME=$MAP_PROJECT-mois
KOR_TRAVEL_MAP_RUSTFS_VOLUME=$MAP_PROJECT-rustfs
KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=$admin_proxy_secret
KOR_TRAVEL_MAP_API_SERVICE_TOKEN=$service_token
KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=$cursor_secret
KOR_TRAVEL_MAP_API_METRICS_TOKEN=$metrics_token
KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=true
KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=$ops_read
KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=$ops_cancel
KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN=$ops_fixture
KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED=true
KOR_TRAVEL_MAP_API_VWORLD_API_KEY=$(random_secret)
KOR_TRAVEL_MAP_OBJECT_STORE_ACCESS_KEY_ID=tvn34c$RUN_KEY
KOR_TRAVEL_MAP_OBJECT_STORE_SECRET_ACCESS_KEY=$object_secret
KOR_TRAVEL_MAP_UI_ADMIN_USERNAME=admin
KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH=$compose_ui_password_hash
KOR_TRAVEL_MAP_UI_SESSION_SECRET=$ui_session
KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED=true
EOF
  cat >"$PINVI_ENV" <<EOF
PINVI_ENVIRONMENT=smoke
PINVI_SOURCE_REVISION=$PINVI_COMMIT
PINVI_API_BUILD_CONTEXT=$PINVI_DIR
PINVI_APP_BUILD_CONTEXT=$PINVI_DIR
PINVI_POSTGRES_PASSWORD=$(random_secret)
PINVI_JWT_SECRET_KEY=$(random_secret)
PINVI_MCP_JWT_SECRET=$(random_secret)
PINVI_API_PORT=$((api_port + 10))
PINVI_WEB_PORT=$((api_port + 11))
PINVI_RUSTFS_PORT=$((api_port + 12))
PINVI_RUSTFS_CONSOLE_PORT=$((api_port + 13))
PINVI_WEB_BASE_URL=http://127.0.0.1:$((api_port + 11))
PINVI_KOR_TRAVEL_MAP_API_BASE_URL=http://map-api:$api_port
PINVI_KOR_TRAVEL_MAP_SERVICE_TOKEN=$service_token
PINVI_KOR_TRAVEL_MAP_ADMIN_BASE_URL=http://map-api:$api_port
PINVI_KOR_TRAVEL_MAP_CACHE_TARGET_SYNC_ENABLED=false
EOF
  chmod 0600 "$MAP_ENV" "$PINVI_ENV"
  : >"$MAP_DIR/packages/kor-travel-map-api/.env"
  : >"$MAP_DIR/.env"
  chmod 0600 "$MAP_DIR/packages/kor-travel-map-api/.env" "$MAP_DIR/.env"
  export E2E_ADMIN_PASSWORD="$UI_ADMIN_PASSWORD"
  # Next의 password verifier를 raw password에 맞춘다. raw password는 process memory/env에서만 유지한다.
  export KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH="$ui_password_hash"
}

configure_map_network_isolation() {
  local existing_subnets subnet api_ip frontend_ip
  existing_subnets="$(docker network ls -q | xargs -r docker network inspect \
    --format '{{range .IPAM.Config}}{{.Subnet}}{{"\\n"}}{{end}}' 2>/dev/null || true)"
  subnet="$(python3 - "$RUN_KEY" "$existing_subnets" <<'PY'
import ipaddress
import sys

seed = int(sys.argv[1][:8], 16)
existing = []
for raw in sys.argv[2].splitlines():
    try:
        existing.append(ipaddress.ip_network(raw.strip(), strict=False))
    except ValueError:
        pass
for offset in range(224):
    third = (seed + offset) % 224
    candidate = ipaddress.ip_network(f"172.29.{third}.0/29")
    if not any(candidate.overlaps(network) for network in existing):
        print(candidate)
        break
else:
    raise SystemExit(1)
PY
)" || die "dedicated admin-control subnet cannot be allocated"
  api_ip="${subnet%/*}"
  api_ip="${api_ip%.*}.2"
  frontend_ip="${subnet%/*}"
  frontend_ip="${frontend_ip%.*}.3"
  MAP_COMPOSE_OVERRIDE="$RUN_DIR/map-isolation.override.yml"
  cat >"$MAP_COMPOSE_OVERRIDE" <<EOF
services:
  api:
    environment:
      KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS: '["$frontend_ip/32"]'
    networks:
      admin-control:
        ipv4_address: $api_ip
  frontend:
    networks:
      admin-control:
        ipv4_address: $frontend_ip
networks:
  admin-control:
    ipam:
      config:
        - subnet: $subnet
EOF
  chmod 0600 "$MAP_COMPOSE_OVERRIDE"
}

compose_map() {
  docker compose --project-name "$MAP_PROJECT" --env-file "$MAP_ENV" \
    --file "$MAP_DIR/docker-compose.yml" --file "$MAP_COMPOSE_OVERRIDE" "$@"
}

compose_pinvi() {
  docker compose --project-name "$PINVI_PROJECT" --env-file "$PINVI_ENV" \
    --file "$PINVI_DIR/infra/docker-compose.app.yml" "$@"
}

cleanup_resources() {
  set +e
  [[ -n "$PINVI_DIR" && -f "$PINVI_ENV" ]] && compose_pinvi down --volumes --remove-orphans >/dev/null 2>&1
  [[ -n "$MAP_DIR" && -f "$MAP_ENV" ]] && compose_map down --volumes --remove-orphans >/dev/null 2>&1
  [[ -n "$MAP_PLAYWRIGHT_IMAGE" ]] && docker image rm --force "$MAP_PLAYWRIGHT_IMAGE" >/dev/null 2>&1
  [[ -n "$RUN_DIR" ]] && rm -f -- "$MAP_ENV" "$PINVI_ENV" \
    "$MAP_COMPOSE_OVERRIDE" "$MAP_DIR/.env" "$MAP_DIR/packages/kor-travel-map-api/.env"
  unset E2E_ADMIN_PASSWORD KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH UI_ADMIN_PASSWORD
  set -e
}

on_exit() {
  local code=$?
  if (( code != 0 )) && (( FINISHED == 0 )); then
    printf 'T-VN-34C n150 fresh live is blocked; run recover from the same immutable snapshot\n' >&2
  fi
}

write_blocked() {
  python3 - "$BLOCKED_FILE" "$RUN_ID" "$RUN_KEY" "$MAP_PROJECT" "$PINVI_PROJECT" \
    "$MAP_COMMIT" "$PINVI_COMMIT" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = dict(zip(("run_id", "run_key", "map_project", "pinvi_project", "map_commit", "pinvi_commit"), sys.argv[2:], strict=True))
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    json.dump(payload, stream, sort_keys=True)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
PY
  chown root:root "$BLOCKED_FILE"
}

load_blocked() {
  local values
  values="$(python3 - "$BLOCKED_FILE" <<'PY'
import json
import re
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if set(data) != {"map_commit", "map_project", "pinvi_commit", "pinvi_project", "run_id", "run_key"}:
    raise SystemExit(1)
for key in ("map_project", "pinvi_project"):
    if not re.fullmatch(r"tvn34c-[a-z0-9-]{6,40}", data[key]):
        raise SystemExit(2)
for key in ("map_commit", "pinvi_commit"):
    if not re.fullmatch(r"[0-9a-f]{40}", data[key]):
        raise SystemExit(3)
print(data["run_id"])
print(data["run_key"])
print(data["map_project"])
print(data["pinvi_project"])
print(data["map_commit"])
print(data["pinvi_commit"])
PY
)" || die "BLOCKED state is invalid"
  mapfile -t values_array <<<"$values"
  [[ "${#values_array[@]}" == "6" ]] || die "BLOCKED values are incomplete"
  RUN_ID="${values_array[0]}"; RUN_KEY="${values_array[1]}"
  MAP_PROJECT="${values_array[2]}"; PINVI_PROJECT="${values_array[3]}"
  MAP_COMMIT="${values_array[4]}"; PINVI_COMMIT="${values_array[5]}"
  RUN_DIR="$STATE_ROOT/run-$RUN_KEY"
  MAP_DIR="$RUN_DIR/map"; PINVI_DIR="$RUN_DIR/pinvi"
  MAP_ENV="$RUN_DIR/map.env"; PINVI_ENV="$RUN_DIR/pinvi.env"
  MAP_COMPOSE_OVERRIDE="$RUN_DIR/map-isolation.override.yml"
  MAP_PLAYWRIGHT_IMAGE="tvn34c-playwright:${RUN_KEY:0:12}"
  [[ -d "$RUN_DIR" && ! -L "$RUN_DIR" ]] || die "BLOCKED runtime directory is unsafe"
}

recover() {
  [[ -f "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] || die "recoverable BLOCKED state is missing"
  [[ "$(stat -c '%u:%g:%a' -- "$BLOCKED_FILE")" == "0:0:600" ]] ||
    die "BLOCKED state metadata is unsafe"
  load_blocked
  cleanup_resources
  rm -rf -- "$RUN_DIR"
  rm -f -- "$BLOCKED_FILE"
  printf 'T-VN-34C n150 fresh live recovered: pair=%s/%s\n' "${MAP_COMMIT:0:12}" "${PINVI_COMMIT:0:12}"
}

seed_fresh_etl() {
  MAP_DAGSTER_IMAGE="$(compose_map images -q dagster)"
  [[ "$MAP_DAGSTER_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Dagster image is not immutable"
  MAP_NETWORK="${MAP_PROJECT}_default"
  local seed_output="$RUN_DIR/fresh-etl.json"
  docker run --rm --read-only --security-opt no-new-privileges --cap-drop ALL \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --network "$MAP_NETWORK" \
    --env-file "$MAP_ENV" \
    --env KOR_TRAVEL_MAP_RUNTIME_DB_PREFLIGHT_REQUIRED=true \
    --mount "type=bind,src=$SEED_HELPER,dst=/opt/tvn34c_fresh_live_etl_seed.py,readonly" \
    --entrypoint python "$MAP_DAGSTER_IMAGE" -I -B /opt/tvn34c_fresh_live_etl_seed.py \
    --run-id "$RUN_ID" >"$seed_output"
  chmod 0600 "$seed_output"
  MAP_E2E_FEATURE_ID="$(python3 - "$seed_output" <<'PY'
import json
import re
import sys
value = json.load(open(sys.argv[1], encoding="utf-8"))
feature_id = value.get("feature_id")
if not isinstance(feature_id, str) or not re.fullmatch(r"tvn34c::fresh-live::[a-z0-9-]{15,79}::beach", feature_id):
    raise SystemExit(1)
if value.get("features_inserted") != 1 or value.get("source_links_inserted") != 1:
    raise SystemExit(2)
print(feature_id)
PY
)" || die "fresh ETL seed receipt is invalid"
}

verify_map_schema() {
  local db_container
  db_container="$(compose_map ps -q postgres)"
  [[ -n "$db_container" ]] || die "fresh Map PostgreSQL container is missing"
  docker exec "$db_container" psql -U kor_travel_map -d kor_travel_map -Atqc \
    "SELECT version_num FROM alembic_version" | grep -Fx "$EXPECTED_HEAD" >/dev/null ||
    die "fresh Map database migration head mismatch"
  docker exec "$db_container" psql -U kor_travel_map -d kor_travel_map -Atqc \
    "SELECT to_regclass('feature.features_detailed') IS NULL" | grep -Fx t >/dev/null ||
    die "T-VN-34C private detail bridge remains"
}

build_playwright_image() {
  MAP_PLAYWRIGHT_IMAGE="tvn34c-playwright:${RUN_KEY:0:12}"
  local image_id
  image_id="$(docker build --pull=false --quiet \
    --build-arg "C7_REPOSITORY_COMMIT=$MAP_COMMIT" \
    --file "$MAP_DIR/docker/c7-playwright.Dockerfile" \
    --tag "$MAP_PLAYWRIGHT_IMAGE" "$MAP_DIR")"
  [[ "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "Playwright image build failed"
  [[ "$(docker image inspect --format '{{index .Config.Labels "io.kortravelmap.c7.repository-commit"}}' "$image_id")" == "$MAP_COMMIT" ]] ||
    die "Playwright image source revision mismatch"
}

run_map_browser() {
  local evidence="$RUN_DIR/map-playwright"
  mkdir -m 0700 "$evidence"
  docker run --rm --read-only --security-opt no-new-privileges --cap-drop ALL \
    --ipc private --network "$MAP_NETWORK" \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,mode=1777 \
    --tmpfs /root/.cache:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.config:rw,nosuid,nodev,noexec,mode=700 \
    --tmpfs /root/.npm:rw,nosuid,nodev,noexec,mode=700 \
    --mount "type=bind,src=$evidence,dst=/evidence" \
    --env "E2E_BASE_URL=http://frontend:12705" \
    --env E2E_ADMIN_USERNAME=admin \
    --env E2E_ADMIN_PASSWORD \
    --env E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1 \
    --env "E2E_ADMIN_FEATURE_ACCEPTANCE_RUN_ID=$RUN_ID" \
    --env E2E_ISOLATED_LIVE_EVIDENCE=1 \
    --env E2E_ISOLATED_LIVE_DOCKER_NETWORK=1 \
    --env E2E_LIVE_WORKERS=1 \
    --env PLAYWRIGHT_ARTIFACT_ROOT=/evidence \
    --env E2E_STORAGE_STATE=/tmp/tvn34c-admin-state.json \
    "$MAP_PLAYWRIGHT_IMAGE" npm run e2e:live -- \
      e2e/live/admin-feature-acceptance-write.live.spec.ts --workers=1 --retries=0
}

run_pinvi_probe() {
  compose_pinvi up --detach --build --wait app-postgres app-rustfs app-rustfs-init app-api
  PINVI_API_CONTAINER="$(compose_pinvi ps -q app-api)"
  [[ -n "$PINVI_API_CONTAINER" ]] || die "PinVi API container is missing"
  PINVI_NETWORK="${PINVI_PROJECT}_default"
  docker network connect --alias map-api "$MAP_NETWORK" "$PINVI_API_CONTAINER" 2>/dev/null || true
  docker exec "$PINVI_API_CONTAINER" python - "$MAP_E2E_FEATURE_ID" <<'PY'
import json
import sys
from urllib.request import urlopen

feature_id = sys.argv[1]
with urlopen("http://127.0.0.1:8000/public/beaches?page_size=50", timeout=20) as response:
    if response.status != 200:
        raise SystemExit(1)
    body = json.load(response)
items = body.get("data", {}).get("items", [])
if not any(isinstance(item, dict) and item.get("feature_id") == feature_id for item in items):
    raise SystemExit(2)
PY
}

write_result() {
  python3 - "$RUN_DIR/result.json" "$RUN_ID" "$MAP_COMMIT" "$PINVI_COMMIT" "$MAP_E2E_FEATURE_ID" <<'PY'
import json
import os
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "map_commit": sys.argv[3],
    "pinvi_commit": sys.argv[4],
    "result": "passed",
    "run_id_sha256": __import__("hashlib").sha256(sys.argv[2].encode()).hexdigest(),
    "seed_feature_id_sha256": __import__("hashlib").sha256(sys.argv[5].encode()).hexdigest(),
}
path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(path, 0o600)
PY
}

run() {
  [[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]] ||
    die "prior interrupted run requires recover"
  RUN_ID="tvn34c-$(date -u +%Y%m%d%H%M%S)-$(openssl rand -hex 6)"
  RUN_KEY="$(printf '%s' "$RUN_ID" | sha256sum | awk '{print $1}')"
  RUN_DIR="$STATE_ROOT/run-$RUN_KEY"
  MAP_PROJECT="tvn34c-map-${RUN_KEY:0:12}"
  PINVI_PROJECT="tvn34c-pinvi-${RUN_KEY:0:12}"
  mkdir -p -m 0700 "$STATE_ROOT" "$RUN_DIR"
  MAP_DIR="$RUN_DIR/map"; PINVI_DIR="$RUN_DIR/pinvi"
  safe_extract "$MAP_ARCHIVE" "$RUN_DIR"
  safe_extract "$PINVI_ARCHIVE" "$RUN_DIR"
  [[ -d "$MAP_DIR" && -d "$PINVI_DIR" ]] || die "source archive root is invalid"
  read_pair_receipt || die "Map/PinVi pinned contract receipt mismatch"
  write_env_files
  configure_map_network_isolation
  write_blocked
  trap on_exit EXIT
  compose_map up --detach --build --wait \
    postgres db-role-bootstrap dagster-db-init rustfs rustfs-init dagster-storage-migrate api frontend dagster
  verify_map_schema
  seed_fresh_etl
  build_playwright_image
  run_map_browser
  run_pinvi_probe
  write_result
  cleanup_resources
  rm -f -- "$BLOCKED_FILE"
  FINISHED=1
  printf 'T-VN-34C n150 fresh live complete: map=%s pinvi=%s result=%s\n' \
    "${MAP_COMMIT:0:12}" "${PINVI_COMMIT:0:12}" "$RUN_DIR/result.json"
}

case "$MODE" in
  run)
    require_root_snapshot
    read_manifest
    run
    ;;
  recover)
    require_root_snapshot
    read_manifest
    recover
    ;;
  *)
    printf 'usage: %s [run|recover]\n' "$SCRIPT_NAME" >&2
    exit 2
    ;;
esac

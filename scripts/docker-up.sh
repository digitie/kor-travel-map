#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

# 외부(공유) 객체 저장소 모드 (#372, ADR-052 amendment):
# kor-travel-docker-manager 소유 RustFS를 쓸 때는 자체 rustfs 계열을 기동하지 않고,
# 공유 인스턴스 포트(12101/12105)를 stop 대상에 넣지 않는다 — 넣으면
# stop-fixed-ports.sh가 공유 `tripmate-rustfs` 컨테이너를 중지시킨다.
#
# 외부(공유) 인프라 모드:
# kor-travel-docker-manager 소유 PostGIS(:5432) + RustFS(:12101)를 함께 쓸 때 local
# postgres/rustfs 계열을 모두 기동하지 않는다.
external_infra="${KOR_TRAVEL_MAP_INFRA_EXTERNAL:-false}"
external_object_store="${KOR_TRAVEL_MAP_OBJECT_STORE_EXTERNAL:-false}"

compose_files=(-f docker-compose.yml)
services=(postgres dagster-db-init api frontend dagster dagster-daemon)
ports=("$KOR_TRAVEL_MAP_API_PORT" "$KOR_TRAVEL_MAP_ADMIN_WEB_PORT" "$KOR_TRAVEL_MAP_DAGSTER_PORT")

if [[ "$external_infra" == "true" ]]; then
  compose_files+=(-f docker-compose.external-infra.yml)
  services=(api frontend dagster dagster-daemon)
elif [[ "$external_object_store" == "true" ]]; then
  compose_files+=(-f docker-compose.external-object-store.yml)
else
  services=(postgres dagster-db-init rustfs rustfs-init api frontend dagster dagster-daemon)
  ports+=("$KOR_TRAVEL_MAP_RUSTFS_API_PORT" "$KOR_TRAVEL_MAP_RUSTFS_CONSOLE_PORT")
fi

"$ROOT_DIR/scripts/stop-fixed-ports.sh" "${ports[@]}"

cd "$ROOT_DIR"
docker compose "${compose_files[@]}" up -d --build "${services[@]}"
docker compose "${compose_files[@]}" ps

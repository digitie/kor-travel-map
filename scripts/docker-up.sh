#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=load-env.sh
source "$ROOT_DIR/scripts/load-env.sh"

# 외부(공유) 객체 저장소 모드 (#372, ADR-052 amendment):
# tripmate-manager 소유 RustFS를 쓸 때는 자체 rustfs 계열을 기동하지 않고,
# 공유 인스턴스 포트(9003/9004)를 stop 대상에 넣지 않는다 — 넣으면
# stop-fixed-ports.sh가 공유 `tripmate-rustfs` 컨테이너를 중지시킨다.
external_object_store="${KRTOUR_MAP_OBJECT_STORE_EXTERNAL:-false}"

compose_files=(-f docker-compose.yml)
services=(postgres dagster-db-init api frontend dagster dagster-daemon)
ports=("$KRTOUR_MAP_ADMIN_PORT" "$KRTOUR_MAP_ADMIN_WEB_PORT" "$KRTOUR_MAP_DAGSTER_PORT")

if [[ "$external_object_store" == "true" ]]; then
  compose_files+=(-f docker-compose.external-object-store.yml)
else
  services=(postgres dagster-db-init rustfs rustfs-init api frontend dagster dagster-daemon)
  ports+=("$KRTOUR_MAP_RUSTFS_API_PORT" "$KRTOUR_MAP_RUSTFS_CONSOLE_PORT")
fi

"$ROOT_DIR/scripts/stop-fixed-ports.sh" "${ports[@]}"

cd "$ROOT_DIR"
docker compose "${compose_files[@]}" up -d --build "${services[@]}"
docker compose "${compose_files[@]}" ps

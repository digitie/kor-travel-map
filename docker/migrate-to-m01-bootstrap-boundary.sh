#!/usr/bin/env sh
# T-VN-M01 — frozen 0200/0202 role graph와 0226 dedicated writer 사이의
# one-shot migration boundary. API process에 bootstrap superuser DSN을 주지
# 않고, compose의 별도 superuser phase가 안전하게 실행될 수 있는 0225까지만
# restricted migrator로 전진한다.
set -eu

migrator_dsn="${KOR_TRAVEL_MAP_MIGRATOR_PG_DSN:?KOR_TRAVEL_MAP_MIGRATOR_PG_DSN is required}"
export KOR_TRAVEL_MAP_PG_DSN="$migrator_dsn"
export KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE=true

# 이미 0226 이상인 DB를 0225로 되돌리지 않는다. 대상 relation 존재 여부는
# forward-only M01 boundary의 durable marker다. partial DDL은 Alembic
# transaction rollback 대상이므로 marker 하나만 있는 상태도 fail-loud하게 둔다.
set +e
python - <<'PY'
from __future__ import annotations

import asyncio
import os

from sqlalchemy import text

from kortravelmap.infra.db import make_async_engine


async def main() -> int:
    engine = make_async_engine(os.environ["KOR_TRAVEL_MAP_PG_DSN"])
    try:
        async with engine.connect() as connection:
            claim, origin, revision = (
                await connection.execute(
                    text(
                        "SELECT to_regclass('feature.manual_feature_identity_claims'), "
                        "to_regclass('feature.feature_creation_origins'), "
                        "(SELECT version_num FROM public.alembic_version)"
                    )
                )
            ).one()
    finally:
        await engine.dispose()
    if (claim is None) != (origin is None):
        print("M01 relation marker is partial; refusing bootstrap boundary", file=sys.stderr)
        return 2
    if claim is not None:
        if revision not in {
            "0226_m01_manual_feature_create",
            "0227_m02_feature_provenance",
            "0228_m03_manual_curation",
            "0233_m04_feature_request_queue",
        }:
            print("M01 relation marker requires a known M01/M02 head", file=sys.stderr)
            return 2
        return 0
    return 1


import sys

raise SystemExit(asyncio.run(main()))
PY
marker_status=$?
set -e

case "$marker_status" in
  0) exit 0 ;;
  1) ;;
  2)
    echo "M01 relation marker is partial; refusing bootstrap boundary" >&2
    exit 1
    ;;
  *)
    echo "M01 relation marker probe failed" >&2
    exit "$marker_status"
    ;;
esac

alembic upgrade 0225_tvn40c_physical_removal

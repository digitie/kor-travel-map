#!/usr/bin/env sh
# T-VN-M05 — superuser가 M05 NOLOGIN graph를 완성한 뒤 restricted migrator가
# 오직 0231만 적용한다. API 기동이 이 choreography를 우회해 head를 만들 수 없다.
set -eu

migrator_dsn="${KOR_TRAVEL_MAP_MIGRATOR_PG_DSN:?KOR_TRAVEL_MAP_MIGRATOR_PG_DSN is required}"
export KOR_TRAVEL_MAP_PG_DSN="$migrator_dsn"
export KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE=true

python - <<'PY'
from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text

from kortravelmap.infra.db import make_async_engine


_ROLES = (
    "ktm_manual_provider_dedup_procedure_owner",
    "ktm_manual_provider_dedup_detector_executor",
    "ktm_manual_provider_dedup_admin_executor",
    "ktm_feature_reference_reconciliation_service_executor",
)


async def main() -> int:
    engine = make_async_engine(os.environ["KOR_TRAVEL_MAP_PG_DSN"])
    try:
        async with engine.connect() as connection:
            revision = await connection.scalar(
                text("SELECT version_num FROM public.alembic_version")
            )
            role_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_catalog.pg_roles "
                    "WHERE rolname = ANY(CAST(:roles AS text[]))"
                ),
                {"roles": list(_ROLES)},
            )
    finally:
        await engine.dispose()
    if revision != "0230_m04_feature_request_queue" or role_count != len(_ROLES):
        print("M05 migration requires the exact 0230 role boundary", file=sys.stderr)
        return 2
    return 0


raise SystemExit(asyncio.run(main()))
PY

alembic upgrade 0231_m05_manual_provider_dedup

#!/usr/bin/env sh
# T-VN-M05 — superuser가 M05 NOLOGIN graph를 완성한 뒤 restricted migrator가
# 0231 기반 증거 테이블 뒤 delivery extension 0232까지 적용한다. API 기동이 이
# choreography를 우회해 head를 만들 수 없다.
set -eu

migrator_dsn="${KOR_TRAVEL_MAP_MIGRATOR_PG_DSN:?KOR_TRAVEL_MAP_MIGRATOR_PG_DSN is required}"
export KOR_TRAVEL_MAP_PG_DSN="$migrator_dsn"
export KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE=true

set +e
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
_RELATIONS = (
    "ops.manual_provider_dedup_cases",
    "ops.manual_provider_dedup_resolutions",
    "ops.feature_reference_reconciliation_events",
    "ops.feature_reference_reconciliation_subscriptions",
    "ops.feature_reference_reconciliation_acks",
    "ops.feature_reference_reconciliation_leases",
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
            relation_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM unnest(CAST(:relations AS text[])) "
                    "AS expected(relation_name) "
                    "WHERE to_regclass(expected.relation_name) IS NOT NULL"
                ),
                {"relations": list(_RELATIONS)},
            )
    finally:
        await engine.dispose()
    if (
        revision == "0230_m04_feature_request_queue"
        and role_count == len(_ROLES)
        and relation_count == 0
    ):
        return 1
    if (
        revision == "0231_m05_manual_provider_dedup"
        and role_count == len(_ROLES)
        and relation_count == len(_RELATIONS)
    ):
        return 2
    if (
        revision == "0232_m05_reconciliation_delivery"
        and role_count == len(_ROLES)
        and relation_count == len(_RELATIONS)
    ):
        return 0
    print("M05 migration marker is not a retryable boundary", file=sys.stderr)
    return 3


raise SystemExit(asyncio.run(main()))
PY

marker_status=$?
set -e
case "$marker_status" in
  0) exit 0 ;;
  1|2) alembic upgrade 0232_m05_reconciliation_delivery ;;
  3)
    echo "M05 migration marker is not a retryable boundary" >&2
    exit 1
    ;;
  *)
    echo "M05 migration marker probe failed" >&2
    exit "$marker_status"
    ;;
esac

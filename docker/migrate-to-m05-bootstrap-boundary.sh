#!/usr/bin/env sh
# T-VN-M05 — M01 role graph 뒤에서만 0230을 확정하는 two-phase boundary.
# M05 role은 이 script 다음 superuser phase가 만들며, 여기서는 0231 object를
# 절대 만들지 않는다.
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

    if relation_count not in (0, len(_RELATIONS)):
        print("M05 relation marker is partial; refusing bootstrap boundary", file=sys.stderr)
        return 2
    if relation_count == len(_RELATIONS):
        if revision != "0231_m05_manual_provider_dedup":
            print("M05 relation marker requires exactly 0231", file=sys.stderr)
            return 2
        return 0
    return 1


raise SystemExit(asyncio.run(main()))
PY
marker_status=$?
set -e

case "$marker_status" in
  0) exit 0 ;;
  1) ;;
  2)
    echo "M05 relation marker is partial; refusing bootstrap boundary" >&2
    exit 1
    ;;
  *)
    echo "M05 relation marker probe failed" >&2
    exit "$marker_status"
    ;;
esac

alembic upgrade 0230_m04_feature_request_queue

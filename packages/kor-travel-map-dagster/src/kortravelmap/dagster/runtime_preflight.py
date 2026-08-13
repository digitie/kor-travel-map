"""Dagster runtime DB principal startup preflight (ADR-090)."""

from __future__ import annotations

import asyncio

from kortravelmap.infra.db import assert_runtime_db_privilege_boundary, make_async_engine
from kortravelmap.settings import KorTravelMapSettings


async def _preflight() -> None:
    settings = KorTravelMapSettings()
    if not settings.runtime_db_preflight_required:
        return
    if settings.pg_dsn is None:
        raise RuntimeError(
            "KOR_TRAVEL_MAP_PG_DSN Dagster runtime DSN is required for ADR-090 preflight"
        )
    engine = make_async_engine(settings.pg_dsn)
    try:
        await assert_runtime_db_privilege_boundary(
            engine,
            expected_login="ktm_feature_dagster_runtime",
        )
    finally:
        await engine.dispose()


def main() -> None:
    """Dagster webserver/daemon exec 전 runtime DSN의 최소권한을 확인한다."""

    asyncio.run(_preflight())


if __name__ == "__main__":  # pragma: no cover - shell entrypoint가 호출
    main()

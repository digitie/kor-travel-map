"""0060 weather 무결성 migration 회귀 (T-VN-17, ADR-072/075).

전용 stepping engine으로 검증한다:
- DEDUP keep-rule: 0059에서 semantic tuple 중복(다른 weather_value_key)을 심고
  0060 upgrade 시 collected_at 최신 winner만 남는지.
- upgrade→downgrade→upgrade 왕복에서 제약/index가 되돌고 복원되는지.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_PRE_REVISION = "0059_public_features_view"
_TARGET_REVISION = "0060_weather_integrity"

_CONSTRAINTS_SQL = """
SELECT conname FROM pg_constraint
WHERE conrelid = 'feature.feature_weather_values'::regclass
  AND conname IN (
      'ck_weather_value_range',
      'ck_weather_value_payload_object',
      'fk_weather_value_source_record'
  )
ORDER BY conname
"""
_UNIQUE_INDEX_SQL = """
SELECT count(*) FROM pg_class c
JOIN pg_index i ON i.indexrelid = c.oid
WHERE c.relname = 'uq_weather_value_identity' AND i.indisvalid
"""


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _seed_weather_feature_and_duplicates(dsn: str) -> None:
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    INSERT INTO feature.features (
                        feature_id, kind, name, category, status, updated_at
                    )
                    VALUES ('f_mig_w', 'weather', '날씨', '00000000', 'active', now())
                    """
                )
            )
            # 같은 semantic tuple, 다른 weather_value_key(tz-표기 divergence 모사),
            # collected_at 상이 → dedup은 최신 collected_at winner만 남긴다.
            t = datetime(2026, 7, 19, 9, 0, tzinfo=_KST)
            for key, collected in (
                ("wv_loser", datetime(2026, 7, 19, 10, 0, tzinfo=_KST)),
                ("wv_winner", datetime(2026, 7, 19, 12, 0, tzinfo=_KST)),
                ("wv_mid", datetime(2026, 7, 19, 11, 0, tzinfo=_KST)),
            ):
                await conn.execute(
                    text(
                        """
                        INSERT INTO feature.feature_weather_values (
                            weather_value_key, feature_id, provider, weather_domain,
                            forecast_style, metric_key, value_number,
                            issued_at, valid_at, collected_at
                        ) VALUES (
                            :k, 'f_mig_w', 'python-kma-api', 'kma_short_forecast',
                            'short', 'TMP', 20.0, :t, :t, :c
                        )
                        """
                    ),
                    {"k": key, "t": t, "c": collected},
                )
            # 시간축이 모두 NULL인 별도 tuple 중복(NULLS NOT DISTINCT dedup 확인).
            for key in ("wv_null_lose", "wv_null_keep"):
                await conn.execute(
                    text(
                        """
                        INSERT INTO feature.feature_weather_values (
                            weather_value_key, feature_id, provider, weather_domain,
                            forecast_style, metric_key, value_text, collected_at
                        ) VALUES (
                            :k, 'f_mig_w', 'python-kma-api', 'kma_weather_alert',
                            'advisory', 'FIRE', '주의보',
                            CASE WHEN :k = 'wv_null_keep'
                                 THEN TIMESTAMPTZ '2026-07-19T13:00:00+09:00'
                                 ELSE TIMESTAMPTZ '2026-07-19T08:00:00+09:00' END
                        )
                        """
                    ),
                    {"k": key},
                )
    finally:
        await engine.dispose()


async def test_weather_integrity_dedup_and_roundtrip(pg_container: Any) -> None:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"weather_integrity_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))

    target_engine = None
    try:
        # 1) 0059까지 올리고 중복을 심는다 (semantic UNIQUE 없는 상태).
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION)
        await _seed_weather_feature_and_duplicates(target_dsn)

        # 2) 0060 upgrade — dedup + CONCURRENTLY unique + CHECK/FK.
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            # dedup: 시간축 tuple은 collected_at 최신(wv_winner)만, NULL tuple은
            # wv_null_keep만 남는다.
            survivors = await connection.execute(
                text(
                    "SELECT weather_value_key FROM feature.feature_weather_values "
                    "WHERE feature_id = 'f_mig_w' ORDER BY weather_value_key"
                )
            )
            keys = [r[0] for r in survivors]
            assert keys == ["wv_null_keep", "wv_winner"]

            # 제약·유효 unique index 존재.
            assert await connection.scalar(text(_UNIQUE_INDEX_SQL)) == 1
            constraints = await connection.execute(text(_CONSTRAINTS_SQL))
            assert [r[0] for r in constraints] == [
                "ck_weather_value_payload_object",
                "ck_weather_value_range",
                "fk_weather_value_source_record",
            ]
        await target_engine.dispose()
        target_engine = None

        # 3) downgrade → 제약/index 제거.
        await asyncio.to_thread(_run_alembic, target_dsn, _PRE_REVISION, downgrade=True)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            assert await connection.scalar(text(_UNIQUE_INDEX_SQL)) == 0
            constraints = await connection.execute(text(_CONSTRAINTS_SQL))
            assert [r[0] for r in constraints] == []
        await target_engine.dispose()
        target_engine = None

        # 4) 재-upgrade → 복원(빈 중복이므로 dedup no-op).
        await asyncio.to_thread(_run_alembic, target_dsn, _TARGET_REVISION)
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            assert await connection.scalar(text(_UNIQUE_INDEX_SQL)) == 1
    finally:
        if target_engine is not None:
            await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()

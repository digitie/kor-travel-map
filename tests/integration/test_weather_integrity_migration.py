"""0060 weather 무결성 migration 회귀 (T-VN-17, ADR-072/075).

전용 stepping engine으로 검증한다:
- DEDUP keep-rule: 0059에서 semantic tuple 중복(다른 weather_value_key)을 심고
  0060 upgrade 시 collected_at 최신 winner만 남는지.
- upgrade→downgrade→upgrade 왕복에서 제약/index가 되돌고 복원되는지.
- lock 규율(S2 회귀): VALIDATE는 SHARE UPDATE EXCLUSIVE만 잡아 concurrent INSERT를
  막지 않고, ADD ... NOT VALID의 ACCESS EXCLUSIVE는 (트랜잭션이 열린 동안) INSERT를
  막는다 — migration이 ADD를 commit한 뒤 VALIDATE해야 하는 이유.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_PRE_REVISION = "0059_public_features_view"
_TARGET_REVISION = "0060_weather_integrity"


@asynccontextmanager
async def _fresh_database(pg_container: Any) -> AsyncIterator[str]:
    """격리된 새 DB를 만들고 dsn을 yield, 끝나면 drop한다."""
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"weather_integrity_{uuid4().hex}"
    target_dsn = make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    admin_engine = make_async_engine(admin_dsn)
    async with admin_engine.connect() as connection:
        autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit.execute(text(f'CREATE DATABASE "{database}"'))
    try:
        yield target_dsn
    finally:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()

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


_LOCK_MODES_SQL = """
SELECT l.mode
FROM pg_locks l
JOIN pg_class c ON c.oid = l.relation
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'feature'
  AND c.relname = 'feature_weather_values'
  AND l.locktype = 'relation'
  AND l.pid = :apid
"""

_WEATHER_INSERT_SQL = """
INSERT INTO feature.feature_weather_values (
    weather_value_key, feature_id, provider, weather_domain,
    forecast_style, metric_key, value_number, issued_at, valid_at
) VALUES (
    :k, 'f_lock', 'python-kma-api', 'kma_short_forecast',
    'short', :m, 20.0, :t, :t
)
"""


async def test_validate_takes_share_update_exclusive_and_add_blocks_writes(
    pg_container: Any,
) -> None:
    """S2 회귀: VALIDATE는 SHARE UPDATE EXCLUSIVE만 잡아 concurrent INSERT를 막지
    않고(ADD를 commit한 뒤 VALIDATE하기 때문), 반대로 ADD ... NOT VALID의 ACCESS
    EXCLUSIVE는 트랜잭션이 열린 동안 INSERT를 막는다."""
    _t = datetime(2026, 7, 19, 9, 0, tzinfo=_KST)
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
        engine = make_async_engine(dsn)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO feature.features "
                        "(feature_id, kind, name, category, status, updated_at) "
                        "VALUES ('f_lock', 'weather', '날씨', '00000000', 'active', now())"
                    )
                )
                await conn.execute(
                    text(_WEATHER_INSERT_SQL), {"k": "wv_seed", "m": "TMP", "t": _t}
                )
            # ck_range를 NOT VALID로 되돌려 VALIDATE 대상을 확보(commit).
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "ALTER TABLE feature.feature_weather_values "
                        "DROP CONSTRAINT ck_weather_value_range"
                    )
                )
                await conn.execute(
                    text(
                        "ALTER TABLE feature.feature_weather_values "
                        "ADD CONSTRAINT ck_weather_value_range CHECK ("
                        " valid_from IS NULL OR valid_until IS NULL"
                        " OR valid_from <= valid_until) NOT VALID"
                    )
                )

            # POSITIVE — conn A가 VALIDATE lock을 연 채로 유지, conn B가 관찰+INSERT.
            async with engine.connect() as conn_a:
                a_pid = await conn_a.scalar(text("SELECT pg_backend_pid()"))
                await conn_a.execute(
                    text(
                        "ALTER TABLE feature.feature_weather_values "
                        "VALIDATE CONSTRAINT ck_weather_value_range"
                    )
                )
                async with engine.connect() as conn_b:
                    modes = (
                        await conn_b.execute(text(_LOCK_MODES_SQL), {"apid": a_pid})
                    ).scalars().all()
                    assert "ShareUpdateExclusiveLock" in modes
                    assert "AccessExclusiveLock" not in modes
                    # ROW EXCLUSIVE INSERT는 SHARE UPDATE EXCLUSIVE와 충돌하지 않는다.
                    await conn_b.execute(text("SET statement_timeout = '5s'"))
                    await conn_b.execute(
                        text(_WEATHER_INSERT_SQL),
                        {"k": "wv_concurrent", "m": "REH", "t": _t},
                    )
                    await conn_b.commit()
                await conn_a.rollback()

            # NEGATIVE — ADD ... NOT VALID의 ACCESS EXCLUSIVE는 INSERT를 막는다.
            async with engine.connect() as conn_a2:
                await conn_a2.execute(
                    text(
                        "ALTER TABLE feature.feature_weather_values "
                        "ADD CONSTRAINT ck_dummy_lock CHECK (true) NOT VALID"
                    )
                )  # commit 안 함 → ACCESS EXCLUSIVE 유지.
                async with engine.connect() as conn_b2:
                    await conn_b2.execute(text("SET statement_timeout = '1500ms'"))
                    with pytest.raises(DBAPIError):
                        await conn_b2.execute(
                            text(_WEATHER_INSERT_SQL),
                            {"k": "wv_blocked", "m": "PTY", "t": _t},
                        )
                await conn_a2.rollback()
        finally:
            await engine.dispose()

"""0060 weather 무결성 migration 회귀 (T-VN-17, ADR-072/075).

전용 stepping engine으로 검증한다:
- DEDUP keep-rule: 0059에서 semantic tuple 중복(다른 weather_value_key)을 심고
  0060 upgrade 시 collected_at 최신 winner만 남는지.
- actual migration이 dedup DELETE 안에서 멈춘 동안 두 번째 connection의 INSERT가
  writer fence에 막히고, release 뒤 transactional UNIQUE까지 성공하는지.
- upgrade 뒤 0060 downgrade가 데이터·writer 계약을 조용히 깨지 않고 fail-closed하는지.
- lock 규율(S2 회귀): VALIDATE는 SHARE UPDATE EXCLUSIVE만 잡아 concurrent INSERT를
  막지 않고, ADD ... NOT VALID의 ACCESS EXCLUSIVE는 (트랜잭션이 열린 동안) INSERT를
  막는다 — migration이 ADD를 commit한 뒤 VALIDATE해야 하는 이유.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic.autogenerate.api import RevisionContext
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
_HEAD_REVISION = "0061_gist_brin_index_audit"
_DEDUP_GATE_KEY = 766_060
_VALIDATE_GATE_KEY = 766_061


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
_INVALID_UNIQUE_INDEX_SQL = """
SELECT count(*) FROM pg_class c
JOIN pg_index i ON i.indexrelid = c.oid
WHERE c.relname = 'uq_weather_value_identity' AND NOT i.indisvalid
"""
_CONSTRAINT_VALIDITY_SQL = """
SELECT conname, convalidated FROM pg_constraint
WHERE conrelid = 'feature.feature_weather_values'::regclass
  AND conname IN (
      'ck_weather_value_range',
      'ck_weather_value_payload_object',
      'fk_weather_value_source_record'
  )
ORDER BY conname
"""
_WEATHER_INDEX_SNAPSHOT_SQL = """
SELECT n.nspname, c.relname, i.indisvalid, i.indisready, i.indisunique,
       i.indnullsnotdistinct, pg_get_indexdef(i.indexrelid)
FROM pg_index AS i
JOIN pg_class AS c ON c.oid = i.indexrelid
JOIN pg_namespace AS n ON n.oid = c.relnamespace
WHERE i.indrelid = 'feature.feature_weather_values'::regclass
ORDER BY n.nspname, c.relname
"""
_WEATHER_CONSTRAINT_SNAPSHOT_SQL = """
SELECT conname, convalidated, pg_get_constraintdef(oid, true)
FROM pg_constraint
WHERE conrelid = 'feature.feature_weather_values'::regclass
ORDER BY conname
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


def _stamp_alembic(dsn: str, revision: str) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    command.stamp(config, revision)


def _alembic_config(dsn: str) -> Config:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    return config


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


async def test_weather_integrity_dedup_and_forward_only(pg_container: Any) -> None:
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

        # 2) 0060 upgrade — writer fence + dedup + transactional unique + CHECK/FK.
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

        # 3) destructive dedup과 새 writer conflict target은 migration만 내려서
        #    안전하게 되돌릴 수 없다. downgrade는 DB를 건드리기 전에 fail-closed한다.
        with pytest.raises(RuntimeError, match="0060 is forward-only"):
            await asyncio.to_thread(
                _run_alembic,
                target_dsn,
                _PRE_REVISION,
                downgrade=True,
            )
        target_engine = make_async_engine(target_dsn)
        async with target_engine.begin() as connection:
            assert await connection.scalar(text(_UNIQUE_INDEX_SQL)) == 1
            constraints = await connection.execute(text(_CONSTRAINTS_SQL))
            assert [r[0] for r in constraints] == [
                "ck_weather_value_payload_object",
                "ck_weather_value_range",
                "fk_weather_value_source_record",
            ]
    finally:
        if target_engine is not None:
            await target_engine.dispose()
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        await admin_engine.dispose()


async def test_forward_only_guard_runs_before_descendant_downgrade(
    pg_container: Any,
) -> None:
    """0061 head→0059 요청은 0061 DDL도 실행하기 전에 전역 거부한다."""
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _HEAD_REVISION)
        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                before = (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    ),
                    tuple(
                        tuple(row)
                        for row in (
                            await connection.execute(
                                text(_WEATHER_INDEX_SNAPSHOT_SQL)
                            )
                        ).all()
                    ),
                    tuple(
                        tuple(row)
                        for row in (
                            await connection.execute(
                                text(_WEATHER_CONSTRAINT_SNAPSHOT_SQL)
                            )
                        ).all()
                    ),
                )

            with pytest.raises(RuntimeError, match="0060 is forward-only"):
                await asyncio.to_thread(
                    _run_alembic,
                    dsn,
                    _PRE_REVISION,
                    downgrade=True,
                )

            async with engine.connect() as connection:
                after = (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    ),
                    tuple(
                        tuple(row)
                        for row in (
                            await connection.execute(
                                text(_WEATHER_INDEX_SNAPSHOT_SQL)
                            )
                        ).all()
                    ),
                    tuple(
                        tuple(row)
                        for row in (
                            await connection.execute(
                                text(_WEATHER_CONSTRAINT_SNAPSHOT_SQL)
                            )
                        ).all()
                    ),
                )
            assert after == before
        finally:
            await engine.dispose()


async def test_forward_only_guard_resolves_relative_targets_from_current_head(
    pg_container: Any,
) -> None:
    """상대 target은 현재 DB head 기준으로 계획하되 0060을 내리는 step만 막는다."""
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _HEAD_REVISION)

        # 0061 -> 0060은 forward-only 경계를 보존하므로 허용한다.
        await asyncio.to_thread(_run_alembic, dsn, "-1", downgrade=True)
        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == _TARGET_REVISION
                )
        finally:
            await engine.dispose()

        # 0060 -> 0061 상대 upgrade도 현재 head 기준으로 정상 해석한다.
        await asyncio.to_thread(_run_alembic, dsn, "+1")
        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == _HEAD_REVISION
                )
        finally:
            await engine.dispose()

        # 0061 -> 0059는 실제 plan에 0060 downgrade가 포함되어 첫 step 전에 차단한다.
        with pytest.raises(RuntimeError, match="0060 is forward-only"):
            await asyncio.to_thread(_run_alembic, dsn, "-2", downgrade=True)
        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == _HEAD_REVISION
                )
        finally:
            await engine.dispose()


@pytest.mark.parametrize("revision", [_PRE_REVISION, "base"])
async def test_forward_only_guard_blocks_stamp_below_boundary_before_mutation(
    pg_container: Any,
    revision: str,
) -> None:
    """stamp도 source/destination ancestry로 0060 경계 하향을 원자 차단한다."""
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _HEAD_REVISION)
        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                before = (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    ),
                    tuple(
                        tuple(row)
                        for row in (
                            await connection.execute(
                                text(_WEATHER_INDEX_SNAPSHOT_SQL)
                            )
                        ).all()
                    ),
                    tuple(
                        tuple(row)
                        for row in (
                            await connection.execute(
                                text(_WEATHER_CONSTRAINT_SNAPSHOT_SQL)
                            )
                        ).all()
                    ),
                )

            with pytest.raises(RuntimeError, match="0060 is forward-only"):
                await asyncio.to_thread(_stamp_alembic, dsn, revision)

            async with engine.connect() as connection:
                after = (
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    ),
                    tuple(
                        tuple(row)
                        for row in (
                            await connection.execute(
                                text(_WEATHER_INDEX_SNAPSHOT_SQL)
                            )
                        ).all()
                    ),
                    tuple(
                        tuple(row)
                        for row in (
                            await connection.execute(
                                text(_WEATHER_CONSTRAINT_SNAPSHOT_SQL)
                            )
                        ).all()
                    ),
                )
            assert after == before
        finally:
            await engine.dispose()


async def test_forward_only_guard_invokes_non_destination_callbacks_once(
    pg_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """current 출력과 check autogenerate callback을 guard가 중복 실행하지 않는다."""
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _HEAD_REVISION)

        current_config = _alembic_config(dsn)
        output = StringIO()
        current_config.stdout = output
        await asyncio.to_thread(command.current, current_config)
        assert output.getvalue().count(_HEAD_REVISION) == 1

        calls = 0
        original = RevisionContext.run_autogenerate

        def count_autogenerate(
            self: RevisionContext,
            rev: tuple[str, ...],
            migration_context: Any,
        ) -> None:
            nonlocal calls
            calls += 1
            original(self, rev, migration_context)

        monkeypatch.setattr(RevisionContext, "run_autogenerate", count_autogenerate)
        await asyncio.to_thread(command.check, _alembic_config(dsn))
        assert calls == 1


async def test_upgrade_fences_writer_from_dedup_through_unique(
    pg_container: Any,
) -> None:
    """실제 0060의 dedup→UNIQUE 경계에서 concurrent writer가 끼어들 수 없다.

    DELETE trigger의 advisory lock은 migration을 dedup statement 내부에 결정적으로
    정지시킨다. 그 순간 다른 connection INSERT가 table writer fence에 막혀야 하고,
    gate 해제 뒤 migration은 valid UNIQUE까지 원자 완료해야 한다.
    """
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_weather_feature_and_duplicates(dsn)
        engine = make_async_engine(dsn)
        migration_task: asyncio.Task[None] | None = None
        try:
            async with engine.begin() as setup:
                await setup.execute(
                    text(
                        f"""
                        CREATE FUNCTION public.pause_weather_dedup()
                        RETURNS trigger
                        LANGUAGE plpgsql
                        AS $function$
                        BEGIN
                            PERFORM pg_advisory_xact_lock({_DEDUP_GATE_KEY});
                            RETURN OLD;
                        END
                        $function$
                        """
                    )
                )
                await setup.execute(
                    text(
                        """
                        CREATE TRIGGER pause_weather_dedup
                        AFTER DELETE ON feature.feature_weather_values
                        FOR EACH ROW EXECUTE FUNCTION public.pause_weather_dedup()
                        """
                    )
                )

            body_error: BaseException | None = None
            async with engine.connect() as gate:
                await gate.execute(
                    text("SELECT pg_advisory_lock(:key)"),
                    {"key": _DEDUP_GATE_KEY},
                )
                migration_task = asyncio.create_task(
                    asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
                )
                migration_pid: int | None = None
                try:
                    for _ in range(100):
                        async with engine.connect() as observer:
                            migration_pid = await observer.scalar(
                                text(
                                    "SELECT pid FROM pg_locks"
                                    " WHERE locktype = 'advisory'"
                                    " AND database = ("
                                    "   SELECT oid FROM pg_database"
                                    "   WHERE datname = current_database()"
                                    " )"
                                    " AND classid = 0 AND objid = :key"
                                    " AND objsubid = 1 AND NOT granted"
                                    " LIMIT 1"
                                ),
                                {"key": _DEDUP_GATE_KEY},
                            )
                        if migration_pid is not None:
                            break
                        await asyncio.sleep(0.05)
                    assert migration_pid is not None, (
                        "migration did not reach the dedup gate"
                    )

                    # Fresh 0059 main cutover의 장기 table lock은 writer-only여야 한다.
                    # Retry normalization의 ACCESS EXCLUSIVE는 별도 짧은 transaction이다.
                    async with engine.connect() as observer:
                        relation_modes = {
                            row[0]
                            for row in (
                                await observer.execute(
                                    text(
                                        "SELECT mode FROM pg_locks"
                                        " WHERE pid = :pid"
                                        " AND relation = "
                                        "   'feature.feature_weather_values'::regclass"
                                        " AND granted"
                                    ),
                                    {"pid": migration_pid},
                                )
                            ).all()
                        }
                    assert "ShareRowExclusiveLock" in relation_modes
                    assert "AccessExclusiveLock" not in relation_modes

                    async with engine.connect() as reader:
                        await reader.execute(text("SET statement_timeout = '1000ms'"))
                        assert (
                            await reader.scalar(
                                text(
                                    "SELECT count(*) "
                                    "FROM feature.feature_weather_values"
                                )
                            )
                            == 5
                        )

                    async with engine.connect() as writer:
                        await writer.execute(text("SET statement_timeout = '1500ms'"))
                        with pytest.raises(DBAPIError) as blocked:
                            await writer.execute(
                                text(
                                    """
                                    INSERT INTO feature.feature_weather_values (
                                        weather_value_key, feature_id, provider,
                                        weather_domain, forecast_style, metric_key,
                                        value_number, issued_at, valid_at, collected_at
                                    ) VALUES (
                                        'wv_racer', 'f_mig_w', 'python-kma-api',
                                        'kma_short_forecast', 'short', 'TMP', 30.0,
                                        TIMESTAMPTZ '2026-07-19T09:00:00+09:00',
                                        TIMESTAMPTZ '2026-07-19T09:00:00+09:00', now()
                                    )
                                    """
                                )
                            )
                        assert getattr(blocked.value.orig, "sqlstate", None) == "57014"
                except BaseException as exc:
                    body_error = exc
                finally:
                    await gate.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": _DEDUP_GATE_KEY},
                    )

            migration_error: BaseException | None = None
            assert migration_task is not None
            try:
                await asyncio.wait_for(asyncio.shield(migration_task), timeout=60)
            except TimeoutError as exc:
                async with engine.connect() as killer:
                    await killer.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND pid <> pg_backend_pid()"
                        )
                    )
                with suppress(BaseException):
                    await asyncio.wait_for(
                        asyncio.shield(migration_task),
                        timeout=10,
                    )
                migration_error = AssertionError(
                    "migration thread did not terminate after the dedup gate opened"
                )
                migration_error.__cause__ = exc
            except BaseException as exc:
                migration_error = exc

            if body_error is not None:
                raise body_error
            if migration_error is not None:
                raise migration_error

            async with engine.connect() as verify:
                assert await verify.scalar(text(_UNIQUE_INDEX_SQL)) == 1
                assert (
                    await verify.scalar(
                        text(
                            "SELECT count(*) FROM feature.feature_weather_values "
                            "WHERE feature_id = 'f_mig_w'"
                        )
                    )
                    == 2
                )
        finally:
            if migration_task is not None and not migration_task.done():
                async with engine.connect() as killer:
                    await killer.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND pid <> pg_backend_pid()"
                        )
                    )
                await asyncio.wait_for(asyncio.shield(migration_task), timeout=10)
            await engine.dispose()


async def test_validate_lock_wait_is_bounded_and_retryable(pg_container: Any) -> None:
    """autocommit VALIDATE도 lock timeout을 잃지 않고 미stamp 재시도 가능하다."""
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_weather_feature_and_duplicates(dsn)
        engine = make_async_engine(dsn)
        gate = None
        blocker = None
        blocker_transaction = None
        blocker_task: asyncio.Task[Any] | None = None
        migration_task: asyncio.Task[None] | None = None
        try:
            async with engine.begin() as setup:
                await setup.execute(
                    text(
                        f"""
                        CREATE FUNCTION public.pause_weather_before_validate()
                        RETURNS trigger
                        LANGUAGE plpgsql
                        AS $function$
                        BEGIN
                            PERFORM pg_advisory_xact_lock({_VALIDATE_GATE_KEY});
                            RETURN OLD;
                        END
                        $function$
                        """
                    )
                )
                await setup.execute(
                    text(
                        """
                        CREATE TRIGGER pause_weather_before_validate
                        AFTER DELETE ON feature.feature_weather_values
                        FOR EACH ROW
                        EXECUTE FUNCTION public.pause_weather_before_validate()
                        """
                    )
                )

            gate = await engine.connect()
            await gate.execute(
                text("SELECT pg_advisory_lock(:key)"),
                {"key": _VALIDATE_GATE_KEY},
            )
            migration_task = asyncio.create_task(
                asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
            )

            waiting_at_dedup = False
            for _ in range(100):
                async with engine.connect() as observer:
                    waiting_at_dedup = bool(
                        await observer.scalar(
                            text(
                                "SELECT EXISTS ("
                                " SELECT 1 FROM pg_locks"
                                " WHERE locktype = 'advisory'"
                                " AND database = ("
                                "   SELECT oid FROM pg_database"
                                "   WHERE datname = current_database()"
                                " )"
                                " AND classid = 0 AND objid = :key"
                                " AND objsubid = 1 AND NOT granted"
                                ")"
                            ),
                            {"key": _VALIDATE_GATE_KEY},
                        )
                    )
                if waiting_at_dedup:
                    break
                await asyncio.sleep(0.05)
            assert waiting_at_dedup, "migration did not reach the validation gate"

            blocker = await engine.connect()
            blocker_transaction = await blocker.begin()
            blocker_pid = await blocker.scalar(text("SELECT pg_backend_pid()"))
            blocker_task = asyncio.create_task(
                blocker.execute(
                    text(
                        "LOCK TABLE feature.feature_weather_values "
                        "IN SHARE UPDATE EXCLUSIVE MODE"
                    )
                )
            )

            blocker_waiting = False
            for _ in range(100):
                async with engine.connect() as observer:
                    blocker_waiting = bool(
                        await observer.scalar(
                            text(
                                "SELECT EXISTS ("
                                " SELECT 1 FROM pg_locks"
                                " WHERE pid = :pid"
                                " AND relation = "
                                "   'feature.feature_weather_values'::regclass"
                                " AND mode = 'ShareUpdateExclusiveLock'"
                                " AND NOT granted"
                                ")"
                            ),
                            {"pid": blocker_pid},
                        )
                    )
                if blocker_waiting:
                    break
                await asyncio.sleep(0.05)
            assert blocker_waiting, "validation blocker did not queue behind writer lock"

            await gate.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": _VALIDATE_GATE_KEY},
            )
            await gate.close()
            gate = None
            await asyncio.wait_for(blocker_task, timeout=10)

            with pytest.raises(DBAPIError) as timed_out:
                await asyncio.wait_for(asyncio.shield(migration_task), timeout=15)
            assert getattr(timed_out.value.orig, "sqlstate", None) == "55P03"

            await blocker_transaction.rollback()
            blocker_transaction = None
            await blocker.close()
            blocker = None

            async with engine.connect() as partial:
                assert await partial.scalar(text(_UNIQUE_INDEX_SQL)) == 1
                validity = [
                    tuple(row)
                    for row in (
                        await partial.execute(text(_CONSTRAINT_VALIDITY_SQL))
                    ).all()
                ]
                assert validity == [
                    ("ck_weather_value_payload_object", False),
                    ("ck_weather_value_range", False),
                    ("fk_weather_value_source_record", False),
                ]

            # 같은 0060 재실행이 partial state를 정규화하고 끝까지 완료해야 한다.
            await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
            async with engine.connect() as verified:
                assert await verified.scalar(text(_UNIQUE_INDEX_SQL)) == 1
                assert all(
                    row[1]
                    for row in (
                        await verified.execute(text(_CONSTRAINT_VALIDITY_SQL))
                    ).all()
                )
        finally:
            if gate is not None:
                with suppress(Exception):
                    await gate.execute(
                        text("SELECT pg_advisory_unlock(:key)"),
                        {"key": _VALIDATE_GATE_KEY},
                    )
                await gate.close()
            if blocker_transaction is not None:
                with suppress(Exception):
                    await blocker_transaction.rollback()
            if blocker is not None:
                await blocker.close()
            if blocker_task is not None and not blocker_task.done():
                blocker_task.cancel()
                await asyncio.gather(blocker_task, return_exceptions=True)
            if migration_task is not None and not migration_task.done():
                async with engine.connect() as killer:
                    await killer.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND pid <> pg_backend_pid()"
                        )
                    )
                await asyncio.wait_for(asyncio.shield(migration_task), timeout=10)
            await engine.dispose()


async def test_upgrade_rejects_existing_constraint_violations_before_cutover(
    pg_container: Any,
) -> None:
    """기존 오염은 dedup/index commit 전에 23514로 fail-closed한다."""
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_weather_feature_and_duplicates(dsn)
        engine = make_async_engine(dsn)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO feature.feature_weather_values (
                            weather_value_key, feature_id, provider,
                            weather_domain, forecast_style, metric_key,
                            value_number, valid_from, valid_until, collected_at
                        ) VALUES (
                            'wv_invalid_range', 'f_mig_w', 'python-kma-api',
                            'kma_short_forecast', 'short', 'RH', 80,
                            TIMESTAMPTZ '2026-07-20T10:00:00+09:00',
                            TIMESTAMPTZ '2026-07-20T09:00:00+09:00', now()
                        )
                        """
                    )
                )

            with pytest.raises(DBAPIError) as rejected:
                await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)
            assert getattr(rejected.value.orig, "sqlstate", None) == "23514"

            async with engine.connect() as unchanged:
                assert await unchanged.scalar(text(_UNIQUE_INDEX_SQL)) == 0
                assert (await unchanged.execute(text(_CONSTRAINTS_SQL))).all() == []
                assert (
                    await unchanged.scalar(
                        text("SELECT version_num FROM alembic_version")
                    )
                    == _PRE_REVISION
                )
                assert (
                    await unchanged.scalar(
                        text(
                            "SELECT count(*) FROM feature.feature_weather_values "
                            "WHERE feature_id = 'f_mig_w'"
                        )
                    )
                    == 6
                )
        finally:
            await engine.dispose()


async def test_upgrade_replaces_leftover_invalid_unique_index(
    pg_container: Any,
) -> None:
    """과거 concurrent 실패의 INVALID index도 새 원자 cutover가 자동 복구한다."""
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        await _seed_weather_feature_and_duplicates(dsn)
        engine = make_async_engine(dsn)
        try:
            async with engine.connect() as connection:
                autocommit = await connection.execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                with pytest.raises(DBAPIError):
                    await autocommit.execute(
                        text(
                            """
                            CREATE UNIQUE INDEX CONCURRENTLY uq_weather_value_identity
                            ON feature.feature_weather_values (
                                feature_id, provider, weather_domain,
                                forecast_style, metric_key,
                                issued_at, valid_at, observed_at
                            ) NULLS NOT DISTINCT
                            """
                        )
                    )
            async with engine.connect() as connection:
                assert (
                    await connection.scalar(text(_INVALID_UNIQUE_INDEX_SQL)) == 1
                )

            await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)

            async with engine.connect() as connection:
                assert await connection.scalar(text(_UNIQUE_INDEX_SQL)) == 1
                assert (
                    await connection.scalar(text(_INVALID_UNIQUE_INDEX_SQL)) == 0
                )
        finally:
            await engine.dispose()


async def test_upgrade_normalizes_unstamped_constraints_before_retry(
    pg_container: Any,
) -> None:
    """VALIDATE 실패 뒤 commit된 미stamp 제약도 재시도에서 exact 복구한다."""
    async with _fresh_database(pg_container) as dsn:
        await asyncio.to_thread(_run_alembic, dsn, _PRE_REVISION)
        engine = make_async_engine(dsn)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        ALTER TABLE feature.feature_weather_values
                        ADD CONSTRAINT ck_weather_value_range
                        CHECK (
                            valid_from IS NULL OR valid_until IS NULL
                            OR valid_from <= valid_until
                        ) NOT VALID
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        ALTER TABLE feature.feature_weather_values
                        ADD CONSTRAINT ck_weather_value_payload_object
                        CHECK (jsonb_typeof(payload) = 'object') NOT VALID
                        """
                    )
                )
                await connection.execute(
                    text(
                        """
                        ALTER TABLE feature.feature_weather_values
                        ADD CONSTRAINT fk_weather_value_source_record
                        FOREIGN KEY (source_record_key)
                        REFERENCES provider_sync.source_records(source_record_key)
                        ON DELETE SET NULL NOT VALID
                        """
                    )
                )
            async with engine.connect() as connection:
                before = [
                    tuple(row)
                    for row in (
                        await connection.execute(text(_CONSTRAINT_VALIDITY_SQL))
                    ).all()
                ]
                assert before == [
                    ("ck_weather_value_payload_object", False),
                    ("ck_weather_value_range", False),
                    ("fk_weather_value_source_record", False),
                ]

            await asyncio.to_thread(_run_alembic, dsn, _TARGET_REVISION)

            async with engine.connect() as connection:
                after = [
                    tuple(row)
                    for row in (
                        await connection.execute(text(_CONSTRAINT_VALIDITY_SQL))
                    ).all()
                ]
                assert after == [
                    ("ck_weather_value_payload_object", True),
                    ("ck_weather_value_range", True),
                    ("fk_weather_value_source_record", True),
                ]
        finally:
            await engine.dispose()


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

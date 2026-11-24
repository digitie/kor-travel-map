"""import job event clock — 긴 transaction이 다른 event 기록을 막지 않는다(alembic 457).

배경: 2026-10-22 큐 요청 8건이 ``INSERT INTO ops.import_job_events``에서 lock timeout으로
실패했다. 76분 동안 refresh transaction을 연 앞 요청이 event를 쓴 뒤 그 transaction에서 적재를
이어 갔고, event statement trigger가 올린 전역 단일 행 ``ops.import_job_event_clock``의 row lock을
commit까지 쥐었다.

이 파일이 지키는 것.

1. **경합 재현**: transaction A가 event를 쓰고 commit하지 않은 채 머무는 동안, transaction B(다른
   job, ``lock_timeout`` 2초)의 event 기록이 기다리지 않고 끝난다. 457 전(main 456)에서 같은
   시험은 B가 ``LockNotAvailableError``로 실패한다 — 시험 이름이 그 회귀를 가리킨다.
2. **변경 감지(읽기 계약)**: ``/v1/ops/live``의 ``event_clock_revision``은 commit된 event DML
   statement마다 정확히 1 늘고, late commit(먼저 시작해 나중에 commit)도 그 commit 시점에 값을
   바꾸며, rollback은 값을 바꾸지 않는다. 값은 실제 reader
   SQL(``_IMPORT_JOBS_LIVE_SQL``·``_IMPORT_JOB_EVENTS_LIVE_SQL``)로 읽는다.
3. **slot 수의 상한**: 순차 transaction은 slot을 늘리지 않고, 새 slot은 모든 slot이 다른
   transaction에 잡혀 있을 때만 생긴다.
4. **guard**: slot은 event trigger 밖에서 INSERT·UPDATE·DELETE·TRUNCATE할 수 없다.
5. **provider attempt event 소유자**(``ktm_curation_command_owner``)도 새 slot을 만들 수
   있다(identity).
6. **이관**: 456의 singleton 값이 457 slot 합으로 그대로 옮겨지고, event transaction이 진행 중이면
   migration이 ``lock_timeout``으로 실패해 값을 옮기지 않는다.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import pytest
from alembic.config import Config
from kortravelmap.api.routers.ops_live import (
    _IMPORT_JOB_EVENTS_LIVE_SQL,
    _IMPORT_JOBS_LIVE_SQL,
)
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from alembic import command
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.jobs_repo import (
    finish_import_job,
    record_import_job_event,
    start_unpaired_import_job,
)
from tests.integration._application_300_bootstrap import (
    _TEST_RUNTIME_PASSWORD,
    alembic_schema_owner_role,
    bootstrapped_application_300_migrator_dsn,
    upgrade_head_with_application_300_bootstrap,
)

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]
_BEFORE: Final = "456_feature_update_retry"
_AFTER: Final = "457_event_clock_slots"

#: B가 기다릴 수 있는 상한. 457 전에는 이 시간이 지나 LockNotAvailableError가 난다.
_WAITER_LOCK_TIMEOUT: Final = "2s"
#: "기다리지 않았다"의 판정 — lock_timeout보다 충분히 짧다.
_NO_WAIT_SECONDS: Final = 1.0


@pytest.fixture(scope="module")
async def head_db(pg_container: object) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    """이 모듈 전용 DB를 배포 경로로 head까지 올린다. (superuser engine, runtime engine).

    이 파일의 시험은 slot 동작을 보려고 job·event를 **commit**한다. session 공용
    DB(``migrated_engine``)에 남기면 그 DB의 전체 job을 세는 다른 시험(``test_jobs_repo``의
    큐 claim, ``test_mois_loader``의 job 목록)이 깨진다(CI 실측). 그래서 DB를 따로 만들고
    끝나면 지운다. runtime 권한은 배포 entrypoint와 같이 ``reconcile_runtime_privileges``로
    준다.
    """

    from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"event_clock_head_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}"')
    superuser_dsn = normalize_async_dsn(_with_database(raw_dsn, database))
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    superuser_engine: AsyncEngine | None = None
    runtime: AsyncEngine | None = None
    try:
        await upgrade_head_with_application_300_bootstrap(config, superuser_dsn)
        migrator_dsn = str(config.get_main_option("sqlalchemy.url"))
        previous = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
        os.environ["KOR_TRAVEL_MAP_PG_DSN"] = migrator_dsn
        try:
            await reconcile_runtime_privileges()
        finally:
            if previous is None:
                os.environ.pop("KOR_TRAVEL_MAP_PG_DSN", None)
            else:
                os.environ["KOR_TRAVEL_MAP_PG_DSN"] = previous
        superuser_engine = make_async_engine(superuser_dsn, pool_size=4)
        runtime = make_async_engine(
            make_url(superuser_dsn)
            .set(username="ktm_feature_service", password=_TEST_RUNTIME_PASSWORD)
            .render_as_string(hide_password=False),
            pool_size=4,
        )
        yield superuser_engine, runtime
    finally:
        if runtime is not None:
            await runtime.dispose()
        if superuser_engine is not None:
            await superuser_engine.dispose()
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')


@pytest.fixture
def migrated_engine(head_db: tuple[AsyncEngine, AsyncEngine]) -> AsyncEngine:
    """이 모듈에서는 공용 ``migrated_engine`` 대신 전용 DB의 superuser engine을 쓴다."""

    return head_db[0]


@pytest.fixture
def runtime_engine(head_db: tuple[AsyncEngine, AsyncEngine]) -> AsyncEngine:
    """실제 runtime LOGIN(``ktm_feature_service``)으로 동시 연결 여럿을 연다."""

    return head_db[1]


async def _root_job(engine: AsyncEngine) -> str:
    """event를 붙일 root job — 큐가 집지 않게 **이미 끝난**(``done``) 상태로 commit한다.

    끝난 job에도 event는 기록된다(진행 중 적재의 heartbeat와 같은 INSERT 경로).
    """

    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        job = await start_unpaired_import_job(
            session,
            kind="provider_load",
            payload={"test": "event-clock-slots", "nonce": uuid4().hex},
        )
        finished = await finish_import_job(session, job.job_id, status="done")
        assert finished is not None
    return job.job_id


async def _live_revision(engine: AsyncEngine, job_id: str | None = None) -> int:
    """``/v1/ops/live``가 보는 값 — 새 snapshot(새 transaction)에서 읽는다."""

    async with AsyncSession(engine) as session, session.begin():
        if job_id is None:
            row = (await session.execute(text(_IMPORT_JOBS_LIVE_SQL))).mappings().one()
        else:
            row = (
                (await session.execute(text(_IMPORT_JOB_EVENTS_LIVE_SQL), {"job_id": job_id}))
                .mappings()
                .one()
            )
    return int(row["event_clock_revision"])


async def _slot_count(engine: AsyncEngine) -> int:
    async with engine.connect() as connection:
        return int(
            (
                await connection.execute(
                    text("SELECT count(*) FROM ops.import_job_event_clock_slots")
                )
            ).scalar_one()
        )


async def _event(session: AsyncSession, job_id: str, message: str) -> None:
    event = await record_import_job_event(session, job_id, message=message)
    assert event is not None


async def _begin_bounded(session: AsyncSession) -> None:
    """transaction을 열고 lock 대기 상한을 건다 — slot이 다시 직렬화되면 10분 hang이 아니라
    2초 뒤 55P03으로 빨갛게 끝난다."""

    await session.begin()
    await session.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": _WAITER_LOCK_TIMEOUT},
    )


async def _slots_incremented_by_this_transaction(session: AsyncSession) -> list[int]:
    """이 transaction이 올린 slot(새 판의 xmin이 자기 xid인 행)."""

    rows = await session.execute(
        text(
            "SELECT slot_id FROM ops.import_job_event_clock_slots "
            "WHERE xmin = pg_current_xact_id()::xid ORDER BY slot_id"
        )
    )
    return [int(value) for value in rows.scalars().all()]


async def test_long_event_transaction_does_not_block_other_job_event(
    runtime_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
) -> None:
    """10-22 재현: 긴 transaction이 event를 쥔 동안 다른 job의 event 기록이 기다리지 않는다."""

    long_job = await _root_job(migrated_engine)
    other_job = await _root_job(migrated_engine)
    before = await _live_revision(migrated_engine)

    async with AsyncSession(runtime_engine) as long_load:
        await long_load.begin()
        # 긴 적재 transaction: event를 쓴 뒤 commit하지 않고 머문다(적재가 도는 동안).
        await _event(long_load, long_job, "long load heartbeat")

        async with AsyncSession(runtime_engine) as other:
            await other.begin()
            await other.execute(
                text("SELECT set_config('lock_timeout', :value, true)"),
                {"value": _WAITER_LOCK_TIMEOUT},
            )
            started = time.monotonic()
            # 457 전에는 여기서 2초 뒤 LockNotAvailableError(55P03)가 난다.
            await asyncio.wait_for(_event(other, other_job, "claim"), timeout=10)
            elapsed = time.monotonic() - started
            await other.commit()

        assert elapsed < _NO_WAIT_SECONDS, f"event 기록이 {elapsed:.2f}s 기다렸다"
        # 다른 job의 commit은 긴 transaction이 끝나기 전에 이미 보인다.
        assert await _live_revision(migrated_engine) == before + 1
        await long_load.commit()

    assert await _live_revision(migrated_engine) == before + 2


async def test_live_revision_counts_commits_in_commit_order_including_late_commit(
    runtime_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
) -> None:
    """먼저 시작해 나중에 commit한 transaction도 그 commit 시점에 revision을 올린다."""

    job_a = await _root_job(migrated_engine)
    job_b = await _root_job(migrated_engine)
    r0 = await _live_revision(migrated_engine)
    r0_job = await _live_revision(migrated_engine, job_a)
    assert r0_job == r0  # job topic도 같은 전역 clock을 본다

    async with AsyncSession(runtime_engine) as early, AsyncSession(runtime_engine) as late:
        await early.begin()
        # early: statement 둘(각각 +1). 아직 commit하지 않는다.
        await _event(early, job_a, "early 1")
        await _event(early, job_a, "early 2")
        assert await _live_revision(migrated_engine) == r0  # 미commit은 보이지 않는다

        await late.begin()
        await _event(late, job_b, "late 1")
        await late.commit()
        r1 = await _live_revision(migrated_engine)
        assert r1 == r0 + 1

        # late commit: early가 나중에 commit해도 값이 바뀐다(감지 누락 없음).
        await early.commit()
    r2 = await _live_revision(migrated_engine)
    assert r2 == r1 + 2
    assert await _live_revision(migrated_engine, job_a) == r2

    # rollback은 값을 바꾸지 않는다.
    async with AsyncSession(runtime_engine) as rolled_back:
        await rolled_back.begin()
        await _event(rolled_back, job_b, "rolled back")
        await rolled_back.rollback()
    assert await _live_revision(migrated_engine) == r2

    # UPDATE·DELETE statement도 1씩 센다(0052 계약: 최근 page 밖 변경 감지). 0행 UPDATE도
    # statement trigger라 센다.
    async with AsyncSession(migrated_engine) as editor, editor.begin():
        await editor.execute(
            text(
                "UPDATE ops.import_job_events SET message = message "
                "WHERE job_id = CAST(:job_id AS uuid)"
            ),
            {"job_id": job_b},
        )
    assert await _live_revision(migrated_engine) == r2 + 1


async def test_sequential_transactions_reuse_slots_and_concurrency_bounds_new_slots(
    runtime_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
) -> None:
    """slot은 모든 slot이 다른 transaction에 잡혀 있을 때만 늘어난다."""

    jobs = [await _root_job(migrated_engine) for _ in range(3)]

    # 순차 transaction은 slot을 늘리지 않는다.
    baseline_slots = await _slot_count(migrated_engine)
    for index in range(5):
        async with AsyncSession(runtime_engine) as session:
            await _begin_bounded(session)
            await _event(session, jobs[0], f"sequential {index}")
            await session.commit()
    assert await _slot_count(migrated_engine) == baseline_slots

    # 동시에 열린 transaction 수만큼까지만 늘어난다(기존 slot을 먼저 쓴다).
    sessions = [AsyncSession(runtime_engine) for _ in range(3)]
    try:
        for session, job_id in zip(sessions, jobs, strict=True):
            await _begin_bounded(session)
            await _event(session, job_id, "concurrent first")
            # 같은 transaction의 두 번째 statement는 자기가 쥔 slot을 다시 쓸 수 있다.
            await _event(session, job_id, "concurrent second")
        assert await _slot_count(migrated_engine) <= max(baseline_slots, 3)
        for session in sessions:
            await session.commit()
    finally:
        for session in sessions:
            await session.close()

    slots = await _slot_count(migrated_engine)
    assert slots <= max(baseline_slots, 3)
    # 다시 순차로 돌면 늘지 않는다.
    async with AsyncSession(runtime_engine) as session:
        await _begin_bounded(session)
        await _event(session, jobs[1], "after concurrency")
        await session.commit()
    assert await _slot_count(migrated_engine) == slots


async def test_transaction_keeps_one_slot_when_a_lower_slot_frees_up(
    runtime_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
) -> None:
    """긴 transaction은 더 낮은 slot이 풀려도 처음 고른 slot 하나만 쓴다.

    그러지 않으면 긴 transaction이 slot을 여럿 쥐고, 그만큼 다른 transaction이 새 slot을 만들어
    slot 수가 동시 transaction 수를 넘는다(적대 리뷰 실측: 동시 3개에 slot 5개).
    """

    job_a = await _root_job(migrated_engine)
    job_b = await _root_job(migrated_engine)
    async with AsyncSession(runtime_engine) as first, AsyncSession(runtime_engine) as second:
        await _begin_bounded(first)
        await _event(first, job_a, "first")
        await _begin_bounded(second)
        await _event(second, job_b, "second")
        [slot_first] = await _slots_incremented_by_this_transaction(first)
        [slot_second] = await _slots_incremented_by_this_transaction(second)
        assert slot_first != slot_second
        # 낮은 slot을 쥔 쪽이 commit해 그 slot을 풀고, 높은 slot을 쥔 쪽이 event를 더 쓴다.
        low, high = (first, second) if slot_first < slot_second else (second, first)
        high_slot = max(slot_first, slot_second)
        high_job = job_b if high is second else job_a
        await low.commit()
        await _event(high, high_job, "after the lower slot freed")
        await _event(high, high_job, "and again")
        assert await _slots_incremented_by_this_transaction(high) == [high_slot]
        await high.commit()


def _sqlstate(error: BaseException) -> str | None:
    orig = getattr(error, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(
        getattr(orig, "__cause__", None), "sqlstate", None
    )


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ops.import_job_event_clock_slots SET revision = revision + 1",
        "UPDATE ops.import_job_event_clock_slots SET revision = revision + 5",
        "DELETE FROM ops.import_job_event_clock_slots",
        "INSERT INTO ops.import_job_event_clock_slots (revision) VALUES (1)",
    ],
)
async def test_slots_reject_writes_outside_the_event_trigger(
    runtime_engine: AsyncEngine,
    migrated_engine: AsyncEngine,
    statement: str,
) -> None:
    """runtime은 표 권한(``_ORDINARY_OPS``)을 가지므로 거부는 권한이 아니라 guard(23514)다."""

    from sqlalchemy.exc import DBAPIError

    # guard가 막을 행이 적어도 하나 있게 한다.
    job_id = await _root_job(migrated_engine)
    async with AsyncSession(runtime_engine) as session, session.begin():
        await _event(session, job_id, "ensure slot")
    async with AsyncSession(runtime_engine) as session:
        await session.begin()
        with pytest.raises(DBAPIError) as raised:
            await session.execute(text(statement))
        await session.rollback()
    assert _sqlstate(raised.value) == "23514"


async def test_slots_reject_truncate_even_by_the_schema_owner(
    migrated_engine: AsyncEngine,
) -> None:
    """runtime에는 TRUNCATE 권한이 없다 — guard는 표 소유자로 확인한다."""

    from sqlalchemy.exc import DBAPIError

    async with migrated_engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text("SET LOCAL ROLE ktm_feature_schema_owner"))
        with pytest.raises(DBAPIError) as raised:
            await connection.execute(text("TRUNCATE ops.import_job_event_clock_slots"))
        await transaction.rollback()
    assert _sqlstate(raised.value) == "23514"


async def test_curation_command_owner_can_open_a_new_slot(
    migrated_engine: AsyncEngine,
) -> None:
    """provider attempt event procedure의 소유자도 모든 slot이 잡혀 있으면 새 slot을 만든다."""

    job_id = await _root_job(migrated_engine)
    async with migrated_engine.connect() as holder_connection:
        holder = await holder_connection.begin()
        # 기존 slot을 전부 잡아 새 slot 경로를 강제한다.
        await holder_connection.execute(
            text("SELECT slot_id FROM ops.import_job_event_clock_slots FOR UPDATE")
        )
        before = await _slot_count(migrated_engine)
        async with migrated_engine.connect() as owner_connection:
            owner = await owner_connection.begin()
            await owner_connection.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
            await owner_connection.execute(
                text("SELECT set_config('lock_timeout', '2s', true)")
            )
            await owner_connection.execute(
                text(
                    "INSERT INTO ops.import_job_events (job_id, level, message) "
                    "VALUES (CAST(:job_id AS uuid), 'info', 'owner event')"
                ),
                {"job_id": job_id},
            )
            await owner.commit()
        await holder.rollback()
    assert await _slot_count(migrated_engine) == before + 1


# ---------------------------------------------------------------------------
# 이관 — 456 singleton 값이 457 slot 합으로
# ---------------------------------------------------------------------------


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


async def _connect(url: str) -> Any:
    import asyncpg

    parts = urlsplit(url)
    return await asyncpg.connect(
        user=parts.username,
        password=parts.password,
        host=parts.hostname,
        port=parts.port,
        database=(parts.path or "/postgres").lstrip("/"),
    )


async def _admin_execute(url: str, statement: str) -> None:
    connection = await _connect(url)
    try:
        await connection.execute(statement)
    finally:
        await connection.close()


@pytest.fixture
async def db_at_456(pg_container: object) -> AsyncIterator[tuple[Config, str]]:
    """fresh DB를 배포 경로로 **456까지만** 올린다. (Config, superuser DSN)."""

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"event_clock_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}"')
    superuser_dsn = _with_database(raw_dsn, database)
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    try:
        config.set_main_option(
            "sqlalchemy.url",
            await bootstrapped_application_300_migrator_dsn(normalize_async_dsn(superuser_dsn)),
        )
        with alembic_schema_owner_role():
            await asyncio.to_thread(command.upgrade, config, _BEFORE)
        yield config, superuser_dsn
    finally:
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')


async def _upgrade_to_457(config: Config) -> None:
    with alembic_schema_owner_role():
        await asyncio.to_thread(command.upgrade, config, _AFTER)


async def _insert_event(connection: Any, job_id: str, message: str) -> None:
    await connection.execute(
        "INSERT INTO ops.import_job_events (job_id, level, message) "
        "VALUES ($1::uuid, 'info', $2)",
        job_id,
        message,
    )


async def test_migration_carries_singleton_revision_and_refuses_in_flight_writers(
    db_at_456: tuple[Config, str],
) -> None:
    config, superuser_dsn = db_at_456
    seed_engine = make_async_engine(normalize_async_dsn(superuser_dsn), pool_size=1)
    try:
        job_id = await _root_job(seed_engine)
    finally:
        await seed_engine.dispose()
    connection = await _connect(superuser_dsn)
    in_flight = await _connect(superuser_dsn)
    try:
        start = int(
            await connection.fetchval(
                "SELECT revision FROM ops.import_job_event_clock WHERE clock_id"
            )
        )
        for index in range(3):
            await _insert_event(connection, job_id, f"before {index}")
        old_revision = int(
            await connection.fetchval(
                "SELECT revision FROM ops.import_job_event_clock WHERE clock_id"
            )
        )
        assert old_revision == start + 3

        # 운영처럼 runtime이 456의 event 경로 권한을 가진 상태를 만든다(이 fixture는 ACL 조정을
        # 돌리지 않는다). 456에서 runtime event 기록이 되는지 먼저 본다 — 457 뒤 검사의 대조군.
        await connection.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ops.import_jobs, "
            "ops.import_job_events, ops.import_job_event_clock TO ktm_feature_runtime"
        )
        await connection.execute(
            "GRANT SELECT ON ALL TABLES IN SCHEMA provider_sync TO ktm_feature_runtime"
        )
        baseline_transaction = in_flight.transaction()
        await baseline_transaction.start()
        await in_flight.execute("SET LOCAL ROLE ktm_feature_runtime")
        await _insert_event(in_flight, job_id, "runtime at 456")
        await baseline_transaction.commit()
        old_revision += 1

        # event transaction이 진행 중이면(옛 singleton 행을 쥔 채) migration은 기다리지 않고
        # 실패한다.
        transaction = in_flight.transaction()
        await transaction.start()
        await _insert_event(in_flight, job_id, "in flight")
        with pytest.raises(Exception, match="lock timeout"):
            await _upgrade_to_457(config)
        assert (
            await connection.fetchval("SELECT version_num FROM public.alembic_version")
        ) == _BEFORE
        await transaction.commit()

        await _upgrade_to_457(config)
        assert (
            await connection.fetchval("SELECT version_num FROM public.alembic_version")
        ) == _AFTER
        assert await connection.fetchval("SELECT to_regclass('ops.import_job_event_clock')") is None
        carried = int(
            await connection.fetchval(
                "SELECT COALESCE(SUM(revision), 0) FROM ops.import_job_event_clock_slots"
            )
        )
        # 진행 중이던 event(+1)까지 정확히 옮겨졌다.
        assert carried == old_revision + 1
        assert await connection.fetchval(
            "SELECT count(*) FROM ops.import_job_event_clock_slots"
        ) == 1

        await _insert_event(connection, job_id, "after")
        assert int(
            await connection.fetchval(
                "SELECT SUM(revision) FROM ops.import_job_event_clock_slots"
            )
        ) == carried + 1

        # runtime ACL 조정(별도 process) 전에도 runtime의 event 기록이 된다 — 457이 새 표 권한을
        # 직접 준다. 조정 전 창에서 42501이면 회전 중 모든 event 기록이 실패한다(적대 리뷰).
        runtime_transaction = in_flight.transaction()
        await runtime_transaction.start()
        await in_flight.execute("SET LOCAL ROLE ktm_feature_runtime")
        await _insert_event(in_flight, job_id, "runtime before reconciliation")
        await runtime_transaction.commit()
        assert int(
            await connection.fetchval(
                "SELECT SUM(revision) FROM ops.import_job_event_clock_slots"
            )
        ) == carried + 2
    finally:
        await in_flight.close()
        await connection.close()

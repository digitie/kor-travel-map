"""소유 backend의 부분 TX 종료 중 다른 연결의 GC가 입력·예약을 지우지 않음을 검증한다."""

from __future__ import annotations

import asyncio
import warnings

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SAWarning
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _rest_snapshot as io
from kortravelmap.infra.db import make_async_engine
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_provider_snapshot_atomic import _state
from tests.integration.test_rest_snapshot_atomic_recovery import _gone_with_no_advisory
from tests.integration.test_rest_snapshot_registration import (
    _limits,
    _prepare_rest_case,
    _quota_state,
    _seed_rest_baseline,
    _snapshot_count,
)
from tests.integration.test_rest_snapshot_registration import (
    _rest_catalog as _rest_catalog,
)
from tests.integration.test_rest_snapshot_two_writers import (
    _cancel_ready,
    _exact_blocker,
    _run_case,
    _wait_stage,
)
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(40)]


@pytest.fixture(scope="module")
async def rest_baseline(scalar_engines, rest_catalog):
    return await _seed_rest_baseline(*scalar_engines, rest_catalog, count=2)


async def _dispose_owned_pools(pools, primary):
    first_error = None
    for pool in pools:
        try:
            await pool.dispose()
        except BaseException as error:
            if primary is not None:
                primary.add_note("owned pool disposal failed: " + type(error).__name__)
            elif first_error is None:
                first_error = error
            else:
                first_error.add_note("second owned pool disposal failed: " + type(error).__name__)
    if first_error is not None:
        raise first_error


async def test_gc_waits_for_exact_live_writer_then_preserves_input_after_backend_death(
    scalar_engines, rest_catalog, rest_baseline, request
):
    admin, runtime = scalar_engines
    case = await _prepare_rest_case(admin, runtime, rest_catalog, count=2)
    before = await _state(admin)
    quota = await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport)
    writer_pool = make_async_engine(
        runtime.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0
    )
    gc_pool = make_async_engine(
        runtime.url.render_as_string(hide_password=False), pool_size=1, max_overflow=0
    )
    client = AsyncKorTravelMapClient(writer_pool)
    held, release, gc_entered = asyncio.Event(), asyncio.Event(), asyncio.Event()
    identities, tasks, primary = {}, {}, None

    async def hold_after_actual_work(bound, fresh):
        async with bound._session_factory() as session, session.begin():
            identities["writer"] = tuple(
                (await session.execute(text("""SELECT pid,backend_start,usename
                FROM pg_stat_activity WHERE pid=pg_backend_pid()
                AND backend_type='client backend'"""))).one()
            )
            assert identities["writer"][2] == "ktm_feature_service"
            assert fresh.snapshot_id == case.observed.snapshot_id
            held.set()
            await release.wait()
            # 실제 backend 종료의 다음 SQL 오류를 받는다. 예상 전제 실패도 commit하지 않는다.
            await session.scalar(text("SELECT 1"))
            raise AssertionError("owned writer must have been terminated before release")

    async def collect_on_other_connection():
        async with AsyncSession(gc_pool) as session, session.begin():
            await _limits(session)
            identities["gc"] = tuple(
                (await session.execute(text("""SELECT pid,backend_start,usename
                FROM pg_stat_activity WHERE pid=pg_backend_pid()
                AND backend_type='client backend'"""))).one()
            )
            assert identities["gc"][2] == "ktm_feature_service"
            assert identities["gc"][0] != identities["writer"][0]
            gc_entered.set()
            return await session.scalar(text("SELECT ops.collect_expired_provider_snapshots(1)"))

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="^transaction already deassociated from connection$",
                category=SAWarning,
            )
            tasks["writer"] = asyncio.create_task(
                _run_case(case, client=client, after_work=hold_after_actual_work)
            )
            await _wait_stage(tasks["writer"], held)
            tasks["gc"] = asyncio.create_task(collect_on_other_connection())
            await _wait_stage(tasks["gc"], gc_entered)
            wait = await _exact_blocker(
                admin, identities["gc"], identities["writer"], tasks["gc"]
            )
            assert not tasks["writer"].done()
            pid, started, login = identities["writer"]
            async with AsyncSession(admin) as observer, observer.begin():
                await _limits(observer)
                assert await observer.scalar(
                    text("""SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                    WHERE pid=:pid AND backend_start=:started AND usename=:login
                      AND datname=current_database() AND backend_type='client backend'
                      AND pid<>pg_backend_pid()"""),
                    dict(pid=pid, started=started, login=login),
                ) is True
            release.set()
            async with asyncio.timeout(5):
                writer_result, gc_result = await asyncio.gather(
                    tasks["writer"], tasks["gc"], return_exceptions=True
                )
            assert isinstance(writer_result, DBAPIError)
            assert gc_result == 0
        await _gone_with_no_advisory(admin, identities["writer"])
        assert await _state(admin) == before
        assert await _quota_state(admin, rest_catalog.dataset, rest_catalog.airport) == quota
        assert await _snapshot_count(admin, [case.member.root_id]) == 1
        fresh = await io.read_rest_snapshot(client, case.member, pins=case.pins)
        assert fresh.status == "prepared"
        assert fresh.artifact_payload == case.observed.artifact_payload
        assert fresh.observation_context == case.observed.observation_context
        assert fresh.kernel_binding.attempt_id == case.plan.attempt_id
        assert writer_pool.pool.checkedout() == gc_pool.pool.checkedout() == 0
        async with writer_pool.connect() as connection:
            assert await connection.scalar(text("SELECT 1")) == 1
            assert await connection.scalar(text("SELECT pg_backend_pid()")) != pid
        assert writer_pool.pool.checkedout() == gc_pool.pool.checkedout() == 0
        request.node.user_properties.append(("concurrent_gc_wait", str(wait)))
    except BaseException as error:
        primary = error
        raise
    finally:
        release.set()
        for task in tasks.values():
            if not task.done():
                task.cancel()
        try:
            async with asyncio.timeout(5):
                await asyncio.gather(*tasks.values(), return_exceptions=True)
        except BaseException as cleanup:
            if primary is None:
                primary = cleanup
                raise
            primary.add_note("owned writer/GC drain failed: " + type(cleanup).__name__)
        finally:
            try:
                await _cancel_ready(runtime, case, primary)
            except BaseException as cleanup:
                if primary is None:
                    primary = cleanup
                raise
            finally:
                await _dispose_owned_pools((writer_pool, gc_pool), primary)

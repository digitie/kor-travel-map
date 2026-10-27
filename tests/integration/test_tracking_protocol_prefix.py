"""고유 PostGIS에서 tracking 진입 순서·직접 SD·롤백 경계를 반증한다.

434 WI-1 분류: 큐레이션을 확정하는 쓰기(root 완결, seal, 권위 finish, SUCCESS 완결 취소
전이)만 P EX→L이다. 장부 쓰기(ensure·event·fill-starts·실패/취소 terminal·비권위 finish·
나머지 취소 전이)는 L만 잡는다. finish와 취소 전이는 인자로 고르므로 두 쪽을 다 본다.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_state_lifecycle_protocol_entry import (
    owned_scalar_resource_bounds as owned_scalar_resource_bounds,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_VERSIONS = Path(__file__).resolve().parents[2] / "alembic/versions"


def _load(name: str, filename: str) -> ModuleType:
    spec = spec_from_file_location(name, _VERSIONS / filename)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_migration = _load("_integration_424", "424_tracking_protocol_prefix.py")
_narrowing = _load("_integration_433", "434_protocol_entry_narrowing.py")
_FINISH = "ops.finish_provider_feature_membership_command"
_CANCEL = "ops.transition_provider_cancellation_job_command"
#: 430이 본문을 의도적으로 바꾼 셋 — 공식 head dump와 통째로 대조한다.
_GOLDEN_NAMES = frozenset(
    {
        "feature.finalize_provider_curation_root",
        "feature.seal_provider_curation_snapshot_receipt",
        _FINISH,
    }
)
#: 434 이후 첫 문장인 진입의 인자(리터럴로 고르는 루틴).
_ENTRY_ARGUMENT = {
    "feature.finalize_provider_curation_root": "true",
    "feature.seal_provider_curation_snapshot_receipt": "true",
    "ops.append_provider_feature_attempt_event_command": "false",
    "ops.ensure_provider_feature_operation_command": "false",
    "ops.fill_provider_cancellation_starts_command": "false",
    "ops.transition_provider_feature_operation_terminal_command": "false",
}
_SUCCESS_DONE = (
    ("p_result", "'already_terminal'"),
    ("p_target_status", "'done'"),
    ("p_dagster_terminal_status", "'SUCCESS'"),
)
_FAILURE_FAILED = (
    ("p_result", "'already_terminal'"),
    ("p_target_status", "'failed'"),
    ("p_dagster_terminal_status", "'FAILURE'"),
)
#: (id, 루틴, 인자 덮어쓰기, 확정 여부). 덮어쓰지 않은 인자는 typed NULL이다.
_CASES = (
    ("finalize-root", "feature.finalize_provider_curation_root", (), True),
    ("seal-receipt", "feature.seal_provider_curation_snapshot_receipt", (), True),
    ("finish-authoritative", _FINISH, (("p_authoritative_snapshot_complete", "true"),), True),
    ("cancel-success-done", _CANCEL, _SUCCESS_DONE, True),
    ("append-event", "ops.append_provider_feature_attempt_event_command", (), False),
    ("ensure-operation", "ops.ensure_provider_feature_operation_command", (), False),
    ("fill-starts", "ops.fill_provider_cancellation_starts_command", (), False),
    ("terminal", "ops.transition_provider_feature_operation_terminal_command", (), False),
    ("finish-ledger", _FINISH, (("p_authoritative_snapshot_complete", "false"),), False),
    ("cancel-failure-failed", _CANCEL, _FAILURE_FAILED, False),
    ("cancel-null", _CANCEL, (), False),
)
_FINAL = [pytest.param(name, args, id=case) for case, name, args, final in _CASES if final]
_LEAF = [pytest.param(name, args, id=case) for case, name, args, final in _CASES if not final]
_L = 6832465333779826081
_P = "SELECT ops.lock_scoped_feature_write_protocol(:exclusive)"
_GOLDEN = (Path(__file__).resolve().parents[2] / "alembic/head-schema.sql").read_text()


async def _direct(session, name, overrides=()):
    item = _migration._EXPECTED[name]
    modes = item["modes"] or ["i"] * len(item["types"])
    given = dict(overrides)
    assert set(given) <= set(item["names"]), given
    # procedure OUT에는 typed NULL이 필요하고 FUNCTION TABLE 출력은 인수가 아니다.
    args = [
        given.get(parameter, "NULL") + "::" + kind
        for parameter, kind, mode in zip(item["names"], item["types"], modes, strict=True)
        if item["kind"] == "p" or mode in ("i", "b", "v")
    ]
    command = "CALL " if item["kind"] == "p" else "SELECT * FROM "
    await session.execute(text(command + name + "(" + ",".join(args) + ")"))


async def _owner(session):
    await session.connection(execution_options={"isolation_level": "READ COMMITTED"})
    await session.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
    await session.execute(text("SET LOCAL lock_timeout='700ms'"))
    await session.execute(text("SET LOCAL statement_timeout='3s'"))
    return int(await session.scalar(text("SELECT pg_backend_pid()")))


async def _released(admin):
    async with admin.begin() as observer:
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(1369104691,115)"))
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _L})


def _first_block(name: str) -> str:
    """434 이후 ``\\nBEGIN\\n`` 바로 뒤에 오는 진입 블록."""
    if name == _CANCEL:
        return _narrowing._CANCEL_TRANSITION_NEW.removeprefix("\nBEGIN\n")
    return "  PERFORM ops.lock_provider_feature_tracking_protocol(" + _ENTRY_ARGUMENT[name] + ");\n"


@pytest.mark.parametrize("name", sorted(_migration._EXPECTED))
async def test_catalog_original_body_owner_acl_and_prefix(scalar_engines, name):
    admin, _ = scalar_engines
    async with admin.connect() as observer:
        row = (
            (await observer.execute(text(_migration._CATALOG_SQL), {"names": [name]}))
            .mappings()
            .one()
        )
        helper = (
            await observer.execute(
                text("""SELECT r.rolname,p.prosecdef,p.proconfig,
          has_function_privilege('ktm_feature_runtime',p.oid,'EXECUTE'),
          EXISTS(SELECT 1 FROM aclexplode(p.proacl) WHERE grantee=0)
          FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
          WHERE p.oid='ops.lock_provider_feature_tracking_protocol(boolean)'::regprocedure""")
            )
        ).one()
    item = _migration._EXPECTED[name]
    body = row["body"]
    assert body.count("ops.lock_provider_feature_tracking_protocol(") == 1
    if name in _GOLDEN_NAMES:
        # 공식 head dump와 전부 대조한다(430 본문 변경 + 434 진입).
        bodies = re.findall(
            rf"CREATE (?:FUNCTION|PROCEDURE) {re.escape(name)}\(.*?AS (\$[A-Za-z0-9_]*\$)(.*?)\1;",
            _GOLDEN,
            re.DOTALL,
        )
        assert len(bodies) == 1
        assert body == bodies[0][1]
    if name == _FINISH:
        # 434: 모드는 권위 인자 그대로다. NULL 검사는 잠금을 잡지 않으므로 진입보다 앞선다.
        entry = (
            "  PERFORM ops.lock_provider_feature_tracking_protocol("
            "p_authoritative_snapshot_complete);\n"
        )
        assert body.count(entry) == 1
        assert body.index("p_authoritative_snapshot_complete IS NULL") < body.index(entry)
        assert body.index(entry) < body.index("pg_has_role(")
    else:
        block = _first_block(name)
        assert body.partition("\nBEGIN\n")[2].startswith(block)
        assert body.count(block) == 1
        if name not in _GOLDEN_NAMES:
            original = body.replace(block, "", 1)
            assert hashlib.sha256(original.encode()).hexdigest() == item["body_sha256"]
    assert row["owner"] == "ktm_curation_command_owner"
    assert row["config"] == item["config"]
    assert row["names"] == item["names"]
    assert row["modes"] == item["modes"]
    assert row["types"] == item["types"]
    assert tuple(helper) == (
        "ktm_curation_command_owner",
        True,
        ["search_path=pg_catalog"],
        True,
        False,
    )


@pytest.mark.parametrize(("name", "overrides"), _FINAL)
async def test_final_l_only_rejects_before_protocol_or_input(scalar_engines, name, overrides):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        await _owner(session)
        await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _L})
        try:
            with pytest.raises(DBAPIError) as caught:
                await _direct(session, name, overrides)
            assert caught.value.orig.sqlstate == "23514"
            assert "cannot acquire protocol after lineage" in str(caught.value.orig)
        finally:
            await session.rollback()
    await _released(admin)


@pytest.mark.parametrize(("name", "overrides"), _LEAF)
@pytest.mark.parametrize("exclusive", [False, True])
async def test_leaf_p_without_l_refuses_new_blocking_l(scalar_engines, name, overrides, exclusive):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        await _owner(session)
        await session.execute(text(_P), {"exclusive": exclusive})
        try:
            with pytest.raises(DBAPIError) as caught:
                await _direct(session, name, overrides)
            assert caught.value.orig.sqlstate == "23514"
            assert "leaf cannot acquire lineage" in str(caught.value.orig)
        finally:
            await session.rollback()
    await _released(admin)


@pytest.mark.parametrize(("name", "overrides"), _FINAL)
async def test_final_waits_on_exact_protocol_pid_before_lineage(scalar_engines, name, overrides):
    admin, runtime = scalar_engines
    ready = asyncio.get_running_loop().create_future()
    async with AsyncSession(runtime) as holder, holder.begin():
        await holder.execute(text(_P), {"exclusive": False})
        blocker = int(await holder.scalar(text("SELECT pg_backend_pid()")))

        async def call():
            async with AsyncSession(admin) as session:
                pid = await _owner(session)
                ready.set_result(pid)
                try:
                    with pytest.raises(DBAPIError) as caught:
                        await _direct(session, name, overrides)
                    assert caught.value.orig.sqlstate == "55P03"
                finally:
                    await session.rollback()

        task = asyncio.create_task(call())
        try:
            pid = await asyncio.wait_for(ready, 3)
            async with asyncio.timeout(2):
                while True:
                    if task.done():
                        await task
                        raise AssertionError("call ended before protocol blocker observation")
                    async with admin.connect() as observer:
                        found = await observer.scalar(
                            text("""SELECT EXISTS(
                          SELECT 1 FROM pg_locks WHERE pid=:pid AND locktype='advisory'
                          AND database=(SELECT oid FROM pg_database
                                        WHERE datname=current_database())
                          AND classid=1369104691::oid AND objid=115::oid AND objsubid=2
                          AND mode='ExclusiveLock' AND NOT granted)
                          AND :blocker=ANY(pg_blocking_pids(:pid))"""),
                            {"pid": pid, "blocker": blocker},
                        )
                    if found:
                        break
                    await asyncio.sleep(0.005)
            async with admin.begin() as observer:
                assert await observer.scalar(
                    text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": _L}
                )
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    await _released(admin)


@pytest.mark.parametrize(("name", "overrides"), _LEAF)
async def test_ledger_entry_does_not_wait_behind_a_protocol_ex_holder(
    scalar_engines, name, overrides
):
    """434 WI-1: 다른 backend가 P EX(적재)를 쥐어도 장부 진입은 P에 줄 서지 않는다.

    typed NULL 인자라 본문은 자기 검증에서 멈출 수 있다 — 여기서 보는 것은 진입이 P를
    기다리지 않았다는 것(55P03 아님, P 대기 없음)과 L을 실제로 잡았다는 것이다.
    """
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as holder, holder.begin():
        await holder.execute(text(_P), {"exclusive": True})
        async with AsyncSession(admin) as session:
            await _owner(session)
            try:
                failure: DBAPIError | None = None
                try:
                    await _direct(session, name, overrides)
                except DBAPIError as error:
                    failure = error
                if failure is not None:
                    assert failure.orig.sqlstate != "55P03", failure
                    assert "ck_provider_tracking_prefix" not in str(failure.orig), failure
                    await session.rollback()
                else:
                    lineage = await session.scalar(
                        text("""SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid()
                        AND locktype='advisory' AND classid=1590807301::oid
                        AND objid=1746797985::oid AND objsubid=1 AND granted""")
                    )
                    assert lineage >= 1
                    protocol = await session.scalar(
                        text("""SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid()
                        AND locktype='advisory' AND classid=1369104691::oid
                        AND objid=115::oid AND objsubid=2""")
                    )
                    assert protocol == 0
            finally:
                await session.rollback()
    await _released(admin)


async def test_ledger_then_finalizing_in_one_transaction_is_rejected(scalar_engines):
    """L만 잡은 장부 transaction은 같은 transaction에서 확정으로 올라갈 수 없다(역순 금지)."""
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as session:
        try:
            await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(false)"))
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text("SELECT ops.lock_provider_feature_tracking_protocol(true)")
                )
            assert caught.value.orig.sqlstate == "23514"
            assert "cannot acquire protocol after lineage" in str(caught.value.orig)
        finally:
            await session.rollback()
    await _released(admin)


async def test_null_mode_and_reentry_preserve_settings(scalar_engines):
    admin, runtime = scalar_engines
    async with AsyncSession(runtime) as session:
        try:
            with pytest.raises(DBAPIError) as caught:
                await session.execute(
                    text("SELECT ops.lock_provider_feature_tracking_protocol(NULL)")
                )
            assert caught.value.orig.sqlstate == "22023"
        finally:
            await session.rollback()
    async with AsyncSession(runtime) as session, session.begin():
        await session.execute(text("SET LOCAL lock_timeout='17ms'"))
        original = await session.scalar(text("SELECT current_user"))
        await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(true)"))
        await session.execute(text("SELECT ops.lock_provider_feature_tracking_protocol(false)"))
        assert await session.scalar(text("SHOW lock_timeout")) == "17ms"
        assert await session.scalar(text("SELECT current_user")) == original
    await _released(admin)

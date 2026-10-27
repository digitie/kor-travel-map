"""state/lifecycle5개 SQL의 valid 중첩 호출·실제 scoped 경합과 rollback 경계."""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.admin_feature_repo import (
    reactivate_admin_feature_state,
    transition_admin_feature_state,
)
from kortravelmap.infra.feature_reference_reconciliation_repo import (
    resolve_manual_provider_dedup_case,
)
from kortravelmap.infra.feature_repo import retire_features_by_source_entity_ids
from kortravelmap.infra.scoped_feature_writes import (
    begin_scoped_feature_write,
    finish_scoped_feature_write,
    lock_scoped_feature_write_protocol,
)
from tests.integration.test_provider_field_scalar_projection import _activate, _plan, _seed
from tests.integration.test_provider_field_scalar_projection import (
    scalar_container as scalar_container,
)
from tests.integration.test_provider_field_scalar_projection import scalar_engines as scalar_engines
from tests.integration.test_tvn_m05_manual_provider_dedup import (
    _open_command,
    _record_candidate,
    _seed_manual_provider_pair,
)

pytestmark = [pytest.mark.integration, pytest.mark.timeout(35)]
_INDEX = itertools.count()
_CALLS = {
    "transition_admin_feature_state": """CALL feature.transition_admin_feature_state(
        :feature,NULL,NULL,NULL,:revision,'state-415',:actor,'retire',NULL,NULL,NULL)""",
    "reactivate_admin_feature_state": """CALL feature.reactivate_admin_feature_state(
        :feature,:dataset,:entity,:record,:revision,'state-415',:actor,NULL,NULL,NULL)""",
    "transition_feature_state": """CALL feature.transition_feature_state(
        :feature,'retired','suppressed','valid',:revision,CAST(:context AS jsonb),NULL,NULL)""",
    "author_lifecycle_override": """CALL feature.author_lifecycle_override(
        :feature,'active','active',true,'state-415',:actor,:revision,NULL)""",
    "revoke_lifecycle_override": """CALL feature.revoke_lifecycle_override(
        :feature,:actor,:revision,NULL)""",
}
_BASE_BODY = {
    "transition_admin_feature_state": (
        "0379801bdf8f90fdaf565dcae9a8505d54fdd9ef42c2cc103a08c1e09a84e8b6"
    ),
    "reactivate_admin_feature_state": (
        "d5eb0ca77cbe114e4e755420d6584b63b61fb2c7a60dc0a2e1d19797b008e353"
    ),
    "transition_feature_state": "16427ca4b0210a8c143c9b68ec71153a64df9fd1127d68e9f4c664b9b2d234a4",
    "author_lifecycle_override": "9cd2e50329bf5ee20eb36e7c9b90b3fb2ebdf19a4bb54e5059d570cc3e7698ac",
    "revoke_lifecycle_override": "053598682fa30798841fcd3b6e86e8666fd3820a1996a57fd52cee2f18d73e96",
}


@pytest.fixture(scope="module", autouse=True)
def owned_scalar_resource_bounds(scalar_container):
    wrapped = scalar_container.get_wrapped_container()
    wrapped.reload()
    identity = wrapped.labels["codex.scalar-projection"]
    assert wrapped.name == "kt-map-scalar-" + identity
    limits = wrapped.attrs["HostConfig"]
    assert limits["NanoCpus"] == 2_000_000_000
    assert limits["Memory"] == limits["MemorySwap"] == 1536 * 1024 * 1024
    assert limits["PidsLimit"] == 256
    print(
        json.dumps(
            dict(
                test="state-lifecycle-owned",
                container_id=wrapped.id,
                identity=identity,
                cpu=2,
                memory_bytes=limits["Memory"],
                pids=256,
            ),
            sort_keys=True,
        )
    )


@dataclass
class Case:
    feature: UUID
    dataset: int
    entity: str
    record: str
    actor: str
    revision: int

    def params(self) -> dict[str, Any]:
        return dict(
            feature=self.feature,
            dataset=self.dataset,
            entity=self.entity,
            record=self.record,
            actor=self.actor,
            revision=self.revision,
            context=json.dumps(
                dict(transition_kind="system", reason_code="state-415", principal=self.actor)
            ),
        )


class _ExclusiveSeed:
    """정본 M05 seed의 admin TX에만 EX를 준다. 관측 대상 runtime engine은 그대로다."""

    def __init__(self, admin):
        self.admin = admin

    @asynccontextmanager
    async def begin(self):
        async with self.admin.begin() as connection:
            # 앞 시험의 active guard가 있어도 새 seed는 적법한 legacy EX 경계로 만든다.
            await connection.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
            yield connection


async def _case(admin) -> Case:
    pair = await _seed_manual_provider_pair(_ExclusiveSeed(admin), index=next(_INDEX))
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT entity.provider_dataset_id,
            head.current_source_record_key,core.row_revision
            FROM provider_sync.source_entities entity
            JOIN provider_sync.source_entity_heads head USING(source_entity_key)
            CROSS JOIN feature.features core
            WHERE entity.source_entity_key=:entity AND core.feature_id=:feature"""),
                {"entity": pair["source_entity_key"], "feature": pair["provider_uuid"]},
            )
        ).one()
    return Case(
        pair["provider_uuid"], row[0], pair["source_entity_key"], row[1], str(pair["actor"]), row[2]
    )


async def _call(session, name: str, case: Case):
    return (await session.execute(text(_CALLS[name]), case.params())).mappings().one()


async def _prepare(runtime, name: str, case: Case) -> None:
    if name == "reactivate_admin_feature_state":
        async with AsyncSession(runtime) as session, session.begin():
            row = await _call(session, "transition_admin_feature_state", case)
            case.revision = row["o_row_revision"]
    elif name == "revoke_lifecycle_override":
        async with AsyncSession(runtime) as session, session.begin():
            await _call(session, "author_lifecycle_override", case)


async def _snapshot(admin, case: Case) -> str:
    filters = {
        "feature.features": ("feature_id", case.feature),
        "feature.feature_places": ("feature_id", case.feature),
        "feature.feature_state_transitions": ("feature_id", case.feature),
        "feature.feature_base_field_values": ("feature_id", case.feature),
        "feature.provider_field_active_policies": ("feature_id", case.feature),
        "feature.provider_field_shadow_candidates": ("feature_id", case.feature),
        "ops.feature_overrides": ("feature_id", case.feature),
        "provider_sync.source_entity_heads": ("source_entity_key", case.entity),
        "provider_sync.source_links": ("source_entity_key", case.entity),
    }
    value = {}
    async with AsyncSession(admin) as session:
        for table, (column, key) in filters.items():
            value[table] = list(
                (
                    await session.scalars(
                        text(
                            f"SELECT to_jsonb(row) FROM {table} row WHERE {column}=:key "
                            'ORDER BY to_jsonb(row)::text COLLATE "C"'
                        ),
                        {"key": key},
                    )
                ).all()
            )
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def _assert_effect(admin, name: str, case: Case) -> None:
    async with AsyncSession(admin) as session:
        state = (
            await session.execute(
                text("""SELECT lifecycle_state,publication_state,row_revision
            FROM feature.features WHERE feature_id=:feature"""),
                {"feature": case.feature},
            )
        ).one()
        overrides = list(
            (
                await session.scalars(
                    text("""SELECT override_value FROM ops.feature_overrides
            WHERE feature_id=:feature AND field_path='lifecycle_state' AND status='active'"""),
                    {"feature": case.feature},
                )
            ).all()
        )
    if name in {"transition_admin_feature_state", "transition_feature_state"}:
        assert tuple(state) == ("retired", "suppressed", case.revision + 1)
        assert overrides == ["retired"]
    elif name == "reactivate_admin_feature_state":
        assert tuple(state) == ("active", "suppressed", case.revision + 1)
        assert overrides == []
    else:
        assert state.lifecycle_state == "active"
        assert state.row_revision == case.revision
        assert overrides == (["active"] if name == "author_lifecycle_override" else [])


#: provider 증거를 먼저 잡는 writer — 434도 종전 P EX를 유지한다. 적재는 bundle을 차례로 쓰며
#: Feature를 쥔 채 다음 head를 갱신하므로, P 없이 겹치면 순환이다(434 적대 리뷰).
_EVIDENCE = frozenset({"reactivate_admin_feature_state"})


async def _wait_blocked_on_rows(admin, waiting: int, blocker: int, task) -> None:
    """434 DC-1: epoch=0의 단건 writer는 P가 아니라 실제 행 잠금에서 기다린다."""
    async with asyncio.timeout(4):
        while True:
            if task.done():
                task.result()
                raise AssertionError("state entry did not wait behind the scoped rows")
            async with AsyncSession(admin) as observer:
                row = (
                    await observer.execute(
                        text("""SELECT :blocker=ANY(pg_blocking_pids(:waiting)),
                        EXISTS(SELECT 1 FROM pg_locks WHERE pid=:waiting
                        AND locktype='advisory' AND classid=1369104691::oid
                        AND objid=115::oid AND objsubid=2)"""),
                        {"waiting": waiting, "blocker": blocker},
                    )
                ).one()
            if row[0]:
                # P 요청 자체가 없다 — 보유도 대기도 아니다.
                assert row[1] is False
                return
            await asyncio.sleep(0.01)


async def _wait_blocked_on_protocol(admin, waiting: int, blocker: int, task) -> None:
    """증거 writer는 종전처럼 P EX를 행보다 먼저 기다린다."""
    async with asyncio.timeout(4):
        while True:
            if task.done():
                task.result()
                raise AssertionError("evidence writer did not wait on the protocol gate")
            async with AsyncSession(admin) as observer:
                found = await observer.scalar(
                    text("""SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=:waiting
                    AND locktype='advisory' AND classid=1369104691::oid AND objid=115::oid
                    AND objsubid=2 AND mode='ExclusiveLock' AND NOT granted)
                    AND :blocker=ANY(pg_blocking_pids(:waiting))"""),
                    {"waiting": waiting, "blocker": blocker},
                )
            if found:
                return
            await asyncio.sleep(0.01)


@pytest.mark.parametrize("name", _CALLS)
async def test_epoch0_state_call_waits_on_scoped_rows_not_on_protocol(scalar_engines, name):
    admin, runtime = scalar_engines
    async with admin.connect() as observer:
        assert await observer.scalar(
            text("SELECT epoch FROM feature.provider_field_policy_epoch WHERE singleton")
        ) == 0
    case = await _case(admin)
    await _prepare(runtime, name, case)
    attempt, owner, digest = await _plan(runtime, str(case.feature), case.dataset)
    waiting = asyncio.get_running_loop().create_future()

    async def legacy():
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='8s'"))
            waiting.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            return await _call(session, name, case)

    task = None
    try:
        async with AsyncSession(runtime) as scoped, scoped.begin():
            receipt = await begin_scoped_feature_write(
                scoped, attempt_id=attempt, owner=owner, manifest_digest=digest
            )
            assert receipt["status"] == "applying"
            blocker = int(await scoped.scalar(text("SELECT pg_backend_pid()")))
            task = asyncio.create_task(legacy())
            pid = await asyncio.wait_for(asyncio.shield(waiting), 4)
            if name in _EVIDENCE:
                await _wait_blocked_on_protocol(admin, pid, blocker, task)
            else:
                await _wait_blocked_on_rows(admin, pid, blocker, task)
            assert not task.done()
            finished = await finish_scoped_feature_write(
                scoped, attempt_id=attempt, owner=owner, result_digest="f" * 64
            )
            assert finished["status"] == "completed"
        result = await asyncio.wait_for(asyncio.shield(task), 5)
        assert result["o_row_revision"] >= case.revision
        await _assert_effect(admin, name, case)
    finally:
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("name", _CALLS)
async def test_epoch0_entry_under_shared_protocol_does_not_upgrade(scalar_engines, name):
    """434 DC-1: epoch=0의 진입은 P를 잡지 않으므로 SH를 쥔 caller에서 승격(23514)이 없다.

    epoch>0의 SH→EX 승격 거부는 ``test_single_writer_regime_entry.py``가 활성화 뒤에 본다.
    """
    admin, runtime = scalar_engines
    case = await _case(admin)
    await _prepare(runtime, name, case)
    if name in _EVIDENCE:
        with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 같은 TX의 SH caller와 CALL
            async with AsyncSession(runtime) as session, session.begin():
                await lock_scoped_feature_write_protocol(session, exclusive=False)
                await _call(session, name, case)
        assert caught.value.orig.sqlstate == "23514"
        return
    async with AsyncSession(runtime) as session, session.begin():
        await lock_scoped_feature_write_protocol(session, exclusive=False)
        await _call(session, name, case)
        modes = (
            await session.scalars(
                text("""SELECT mode FROM pg_locks WHERE pid=pg_backend_pid()
                AND locktype='advisory' AND classid=1369104691::oid
                AND objid=115::oid AND objsubid=2 AND granted"""),
            )
        ).all()
    assert modes == ["ShareLock"]
    await _assert_effect(admin, name, case)


@pytest.mark.parametrize("name", _CALLS)
async def test_epoch0_state_call_finishes_while_a_load_holds_protocol_ex(scalar_engines, name):
    """434 DC-1: 적재가 P EX를 쥔 동안에도 다른 Feature의 상태·lifecycle writer는 끝난다.

    provider 증거를 먼저 잡는 재활성화만 종전처럼 P EX로 적재 뒤에 선다(적재가 bundle을
    차례로 쓰며 Feature를 쥔 채 다음 head를 갱신하므로, P 없이 겹치면 순환이다).
    """
    admin, runtime = scalar_engines
    case = await _case(admin)
    await _prepare(runtime, name, case)
    async with AsyncSession(runtime) as holder, holder.begin():
        await lock_scoped_feature_write_protocol(holder, exclusive=True)
        if name in _EVIDENCE:
            with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 실제 대기 상한
                async with AsyncSession(runtime) as session, session.begin():
                    await session.execute(text("SET LOCAL lock_timeout='300ms'"))
                    await _call(session, name, case)
            assert caught.value.orig.sqlstate == "55P03"
            return
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text("SET LOCAL lock_timeout='300ms'"))
            await _call(session, name, case)
    await _assert_effect(admin, name, case)


@pytest.mark.parametrize("name", _CALLS)
async def test_successful_state_call_obeys_caller_rollback(scalar_engines, name):
    admin, runtime = scalar_engines
    case = await _case(admin)
    await _prepare(runtime, name, case)
    before = await _snapshot(admin, case)
    async with AsyncSession(runtime) as session:
        await _call(session, name, case)
        await session.rollback()
    assert await _snapshot(admin, case) == before
    async with AsyncSession(admin) as observer, observer.begin():
        assert await observer.scalar(text("SELECT pg_try_advisory_xact_lock(1369104691,115)"))
        assert (
            await observer.scalar(
                text("SELECT 1 FROM feature.features WHERE feature_id=:feature FOR UPDATE NOWAIT"),
                {"feature": case.feature},
            )
            == 1
        )
    async with AsyncSession(runtime) as session, session.begin():
        await _call(session, name, case)
    await _assert_effect(admin, name, case)


async def test_admin_retire_reactivate_and_existing_provider_retire_reenter_core(scalar_engines):
    admin, runtime = scalar_engines
    case = await _case(admin)
    async with AsyncSession(runtime) as session, session.begin():
        retired = await transition_admin_feature_state(
            session,
            str(case.feature),
            expected_row_revision=case.revision,
            reason_code="retire-415",
            operator=case.actor,
            action="retire",
        )
    assert retired.audit_transition_id > 0
    case.revision = retired.row_revision
    async with AsyncSession(runtime) as session, session.begin():
        restored = await reactivate_admin_feature_state(
            session,
            str(case.feature),
            expected_row_revision=case.revision,
            reason_code="restore-415",
            operator=case.actor,
            provider_dataset_id=case.dataset,
            source_entity_key=case.entity,
            source_record_key=case.record,
        )
    assert restored.audit_transition_id != retired.audit_transition_id
    assert restored.row_revision == retired.row_revision + 1
    async with AsyncSession(admin) as observer:
        entity_id = await observer.scalar(
            text(
                "SELECT source_entity_id FROM provider_sync.source_entities "
                "WHERE source_entity_key=:key"
            ),
            {"key": case.entity},
        )
    async with AsyncSession(runtime) as session, session.begin():
        count = await retire_features_by_source_entity_ids(
            session,
            provider="python-m05-integration",
            dataset_key="m05-integration",
            source_entity_type="place",
            source_entity_ids={entity_id},
        )
    assert count == 1
    async with AsyncSession(admin) as observer:
        audits = (
            await observer.execute(
                text("""SELECT transition_id,transition_kind
            FROM feature.feature_state_transitions WHERE feature_id=:feature
            ORDER BY row_revision"""),
                {"feature": case.feature},
            )
        ).all()
        assert [row.transition_kind for row in audits] == ["admin", "admin", "provider_sync"]
        assert [row.transition_id for row in audits[:2]] == [
            retired.audit_transition_id,
            restored.audit_transition_id,
        ]


@pytest.mark.parametrize("decision", ["merged", "manual_retired"])
async def test_m05_non_kept_decision_reenters_admin_core_and_lifecycle(scalar_engines, decision):
    admin, runtime = scalar_engines
    pair = await _seed_manual_provider_pair(_ExclusiveSeed(admin), index=next(_INDEX))
    recorded = await _record_candidate(
        runtime,
        manual_feature_id=str(pair["manual_feature_id"]),
        provider_feature_id=str(pair["provider_feature_id"]),
    )
    command = await _open_command(
        admin, actor=str(pair["actor"]), operation="admin.manual-provider-dedup-case.resolve.v1"
    )
    async with AsyncSession(admin) as session, session.begin():
        await session.execute(
            text("""INSERT INTO ops.feature_reference_reconciliation_subscriptions(
            principal_id,initial_event_sequence,read_scope,ack_scope)
            VALUES('service:feature-reference-reconciliation',0,
                'feature-reference-reconciliation:read','feature-reference-reconciliation:ack')
            ON CONFLICT DO NOTHING""")
        )
        await session.execute(
            text("""INSERT INTO ops.feature_reference_reconciliation_leases(
            principal_id,acked_through_sequence,worker_id,lease_epoch,lease_expires_at)
            VALUES('service:feature-reference-reconciliation',0,NULL,0,NULL)
            ON CONFLICT DO NOTHING""")
        )
        row = (
            await session.execute(
                text("""SELECT evidence_fingerprint,
            manual_feature_row_revision,provider_feature_row_revision
            FROM ops.manual_provider_dedup_cases WHERE case_id=:id"""),
                {"id": recorded["o_case_id"]},
            )
        ).one()
    async with AsyncSession(runtime) as session, session.begin():
        result = await resolve_manual_provider_dedup_case(
            session,
            case_id=recorded["o_case_id"],
            decision=decision,
            expected_case_fingerprint=row[0],
            expected_manual_row_revision=row[1],
            expected_provider_row_revision=row[2],
            survivor_feature_id=str(pair["provider_feature_id"]) if decision == "merged" else None,
            reason="state-415",
            actor=str(pair["actor"]),
            command_id=command,
        )
    assert result.outcome == decision
    assert result.resolution_id is not None
    assert result.event_id is not None
    async with AsyncSession(admin) as observer:
        state = (
            await observer.execute(
                text("""SELECT lifecycle_state,publication_state,row_revision
            FROM feature.features WHERE feature_id=:id"""),
                {"id": pair["manual_uuid"]},
            )
        ).one()
        assert tuple(state) == ("retired", "suppressed", row[1] + 1)
        assert (
            await observer.scalar(
                text("""SELECT override_value FROM ops.feature_overrides
            WHERE feature_id=:id AND field_path='lifecycle_state' AND status='active'"""),
                {"id": pair["manual_uuid"]},
            )
            == "retired"
        )


@pytest.mark.parametrize("name", _CALLS)
async def test_active_scalar_policy_still_rejects_state_or_lifecycle_mutation(scalar_engines, name):
    admin, runtime = scalar_engines
    feature, datasets, entities = await _seed(admin)
    async with AsyncSession(admin) as observer:
        record = await observer.scalar(
            text("""SELECT current_source_record_key
            FROM provider_sync.source_entity_heads WHERE source_entity_key=:entity"""),
            {"entity": entities[0]},
        )
        revision = await observer.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=:id"),
            {"id": UUID(feature)},
        )
    case = Case(UUID(feature), datasets[0], entities[0], record, "admin:state-415", revision)
    await _prepare(runtime, name, case)
    await _activate(admin, feature)
    async with AsyncSession(admin) as observer:
        case.revision = await observer.scalar(
            text("SELECT row_revision FROM feature.features WHERE feature_id=:id"),
            {"id": case.feature},
        )
    before = await _snapshot(admin, case)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 실제 caller TX의 guard/commit 경계
        async with AsyncSession(runtime) as session, session.begin():
            await _call(session, name, case)
    assert caught.value.orig.sqlstate == "23514"
    assert await _snapshot(admin, case) == before


@pytest.mark.parametrize("name", _CALLS)
async def test_body_owner_acl_and_search_path_are_preserved(scalar_engines, name):
    admin, _ = scalar_engines
    async with AsyncSession(admin) as session:
        row = (
            await session.execute(
                text("""SELECT p.prosrc,p.proconfig,r.rolname,
            has_function_privilege('ktm_feature_service',p.oid,'EXECUTE'),
            EXISTS(SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0)
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            JOIN pg_roles r ON r.oid=p.proowner
            WHERE n.nspname='feature' AND p.proname=:name"""),
                {"name": name},
            )
        ).one()
    # 434 DC-1: 415의 무조건 EX 진입을 regime 진입 한 줄로 바꿨다. 그 줄을 빼면 414 원문이다.
    entry = (
        "  PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
        if name in _EVIDENCE
        else "  PERFORM ops.lock_single_feature_writer_protocol();\n"
    )
    assert row.prosrc.count(entry) == 1
    if name not in _EVIDENCE:
        assert "lock_scoped_feature_write_protocol" not in row.prosrc
    assert row.prosrc.partition("\nBEGIN\n")[2].startswith(entry)
    assert hashlib.sha256(row.prosrc.replace(entry, "", 1).encode()).hexdigest() == _BASE_BODY[name]
    assert row.proconfig == ["search_path=pg_catalog"]
    assert row.rolname == "ktm_feature_state_procedure_owner"
    assert row[3] is True
    assert row[4] is False


@pytest.mark.parametrize("mode", ["stale", "missing", "noop"])
async def test_existing_state_error_boundaries_preserve_transaction(scalar_engines, mode):
    admin, runtime = scalar_engines
    case = await _case(admin)
    before = await _snapshot(admin, case)
    params = case.params()
    statement = _CALLS["transition_feature_state"]
    expected = {"stale": "40001", "missing": "P0002", "noop": "23514"}[mode]
    if mode == "stale":
        params["revision"] += 1
    elif mode == "missing":
        params["feature"] = uuid4()
    else:
        statement = """CALL feature.transition_feature_state(
            :feature,'active','published','valid',:revision,CAST(:context AS jsonb),NULL,NULL)"""
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 실제 valid CALL의 실패/rollback
        async with AsyncSession(runtime) as session, session.begin():
            await session.execute(text(statement), params)
    assert caught.value.orig.sqlstate == expected
    assert await _snapshot(admin, case) == before
    async with AsyncSession(runtime) as session, session.begin():
        await _call(session, "transition_feature_state", case)
    await _assert_effect(admin, "transition_feature_state", case)


@pytest.mark.parametrize("name", _CALLS)
async def test_ungranted_procedure_owner_cannot_enter_state_sql(scalar_engines, name):
    admin, runtime = scalar_engines
    case = await _case(admin)
    await _prepare(runtime, name, case)
    before = await _snapshot(admin, case)
    with pytest.raises(DBAPIError) as caught:  # noqa: PT012 - 실제 role의 closed EXECUTE 경계
        async with AsyncSession(admin) as denied, denied.begin():
            await denied.execute(text("SET LOCAL ROLE ktm_manual_feature_procedure_owner"))
            await _call(denied, name, case)
    assert caught.value.orig.sqlstate == "42501"
    assert await _snapshot(admin, case) == before

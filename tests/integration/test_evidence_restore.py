"""D단계 — 조문의 남은 두 요구를 **복원본 데이터베이스에 대고** 실측한다.

A·B는 artifact만 본다. 여기서는 진짜 delivery 이력(판정 → event → lease → ack)을
만든 뒤, 복원 직후에 벌어질 일을 그대로 재현한다.

각 테스트는 **고쳐야 할 상태를 심고 그것이 잡히는지** 본다. 정상 상태가 통과하는
것만 재면 수리기를 통째로 비워도 초록이다.
"""

from __future__ import annotations

from itertools import count
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kortravelmap.infra.evidence_restore import (
    invalidate_leases,
    preflight_evidence_graph,
    rebuild_acked_through,
    repair_restored_database,
)
from tests.integration.test_tvn_m05_manual_provider_dedup import (
    _ack_event,
    _lease_event,
    _open_command,
    _record_candidate,
    _runtime_engine,
    _seed_manual_provider_pair,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("tvn_m01_m05_role_graph"),
]

_ACK_OPERATION = "service.feature-reference-reconciliation.ack.v1"

#: `_seed_manual_provider_pair`의 `index`는 좌표를 `index * 0.01`도씩 민다.
#: 크면 위경도 범위를 벗어나 PostGIS가 `Invalid coordinate`로 죽고, 겹치면
#: `uq_manual_feature_identity_claims_exact`에 걸린다 — DB가 session-scope라
#: 다른 모듈이 쓰는 0·10~13·20번대·30번대·40·41·50·60·61을 피해 100부터 센다.
_PAIR_INDEX = count(100)


async def _publish_event(
    engine: AsyncEngine, api: AsyncEngine, dagster: AsyncEngine, *, index: int
) -> dict[str, object]:
    """한 쌍을 심고 판정까지 밀어 event 하나를 만든다.

    event는 직접 INSERT할 수 없다 — case·resolution·transition·feature identity로 묶여
    있고 append-only 트리거가 걸려 있다. 그것이 이 테스트가 진짜 이력을 만드는 이유이자,
    이 축이 공허하지 않은 이유다.
    """

    pair = await _seed_manual_provider_pair(engine, index=index)
    await _provision_canonical_subscription(engine, api, actor=str(pair["actor"]))
    recorded = await _record_candidate(
        dagster,
        manual_feature_id=str(pair["manual_feature_id"]),
        provider_feature_id=str(pair["provider_feature_id"]),
    )
    case_id = UUID(str(recorded["o_case_id"]))

    async with engine.connect() as connection:
        case = (
            await connection.execute(
                text(
                    "SELECT evidence_fingerprint, manual_feature_row_revision,"
                    " provider_feature_row_revision"
                    " FROM ops.manual_provider_dedup_cases WHERE case_id = :case_id"
                ),
                {"case_id": case_id},
            )
        ).mappings().one()

    decision_command = await _open_command(
        engine,
        actor=str(pair["actor"]),
        operation="admin.manual-provider-dedup-case.resolve.v1",
    )
    async with api.begin() as connection:
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        )
        resolved = dict(
            (
                await connection.execute(
                    text(
                        """
                        CALL feature.resolve_manual_provider_dedup_case_v2(
                          CAST(:case_id AS uuid), 'merged', CAST(:fingerprint AS text),
                          CAST(:manual_revision AS bigint),
                          CAST(:provider_revision AS bigint),
                          CAST(:survivor_feature_id AS text), 'restore drill',
                          CAST(:actor AS text), CAST(:command_id AS bigint),
                          NULL::text, NULL::uuid, NULL::uuid, NULL::text, NULL::bigint
                        )
                        """
                    ),
                    {
                        "case_id": case_id,
                        "fingerprint": case["evidence_fingerprint"],
                        "manual_revision": case["manual_feature_row_revision"],
                        "provider_revision": case["provider_feature_row_revision"],
                        "survivor_feature_id": pair["provider_feature_id"],
                        "actor": pair["actor"],
                        "command_id": decision_command,
                    },
                )
            )
            .mappings()
            .one()
        )
    assert resolved["o_outcome"] == "merged"

    async with engine.connect() as connection:
        event = (
            await connection.execute(
                text(
                    "SELECT event_id, event_sequence, event_sha256"
                    " FROM ops.feature_reference_reconciliation_events"
                    " WHERE event_id = CAST(:event_id AS uuid)"
                ),
                {"event_id": resolved["o_event_id"]},
            )
        ).mappings().one()
    return dict(event)


async def _provision_canonical_subscription(
    engine: AsyncEngine, api: AsyncEngine, *, actor: str
) -> None:
    """판정이 event를 낼 수 있으려면 정본 구독이 먼저 있어야 한다.

    `resolve_manual_provider_dedup_case_v2`는 구독이 없으면
    `feature reference reconciliation subscription is not provisioned`로 죽는다.
    다른 M05 테스트는 이미 provision된 DB를 물려받아 그 사실이 가려져 있었다 —
    이 파일만 돌리면 드러난다.
    """

    command_id = await _open_command(
        engine,
        actor=actor,
        operation="admin.feature-reference-reconciliation-subscription.provision.v1",
    )
    async with api.begin() as connection:
        await connection.execute(
            text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        )
        outcome = (
            await connection.execute(
                text(
                    "CALL feature."
                    "provision_feature_reference_reconciliation_subscription("
                    " 'service:feature-reference-reconciliation', 0,"
                    " CAST(:actor AS text), CAST(:command_id AS bigint),"
                    " NULL::text, NULL::bigint)"
                ),
                {"actor": actor, "command_id": command_id},
            )
        ).mappings().one()
    assert outcome["o_outcome"] in {"provisioned", "already_provisioned"}, outcome


async def _provision_principal(
    engine: AsyncEngine, *, principal_id: str, initial_event_sequence: int
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO ops.feature_reference_reconciliation_subscriptions ("
                " principal_id, initial_event_sequence, read_scope, ack_scope"
                ") VALUES (:principal_id, :initial,"
                " 'feature-reference-reconciliation:read',"
                " 'feature-reference-reconciliation:ack')"
            ),
            {"principal_id": principal_id, "initial": initial_event_sequence},
        )
        await connection.execute(
            text(
                "INSERT INTO ops.feature_reference_reconciliation_leases ("
                " principal_id, acked_through_sequence, worker_id, lease_epoch,"
                " lease_expires_at"
                ") VALUES (:principal_id, :initial, NULL, 0, NULL)"
            ),
            {"principal_id": principal_id, "initial": initial_event_sequence},
        )


async def _read_lease(engine: AsyncEngine, principal_id: str) -> dict[str, object]:
    async with engine.connect() as connection:
        return dict(
            (
                await connection.execute(
                    text(
                        "SELECT acked_through_sequence, worker_id, lease_epoch,"
                        " lease_expires_at"
                        " FROM ops.feature_reference_reconciliation_leases"
                        " WHERE principal_id = :principal_id"
                    ),
                    {"principal_id": principal_id},
                )
            )
            .mappings()
            .one()
        )


async def _deliver_one(
    engine: AsyncEngine, api: AsyncEngine, *, principal_id: str
) -> dict[str, object]:
    """다음 event 하나를 lease하고 ack한다 — 진짜 프로시저로."""

    worker_id = uuid4()
    leased = await _lease_event(api, principal_id=principal_id, worker_id=worker_id)
    assert leased["o_outcome"] == "leased", leased
    ack_command = await _open_command(
        engine, actor=principal_id, operation=_ACK_OPERATION
    )
    acked = await _ack_event(
        api,
        principal_id=principal_id,
        event_id=UUID(str(leased["o_event_id"])),
        worker_id=worker_id,
        lease_epoch=int(str(leased["o_lease_epoch"])),
        event_sha256=str(leased["o_event_sha256"]),
        local_receipt_sha256="b" * 64,
        command_id=ack_command,
    )
    assert acked["o_outcome"] == "acked", acked
    return {
        "worker_id": worker_id,
        "lease_epoch": int(str(leased["o_lease_epoch"])),
        "event_sequence": int(str(leased["o_event_sequence"])),
    }


@pytest.fixture
async def delivery(migrated_engine: AsyncEngine) -> dict[str, object]:
    """event 둘, 그중 하나만 ack된 principal 하나. 살아 있는 holder를 남긴다."""

    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        first = await _publish_event(
            migrated_engine, api, dagster, index=next(_PAIR_INDEX)
        )
        second = await _publish_event(
            migrated_engine, api, dagster, index=next(_PAIR_INDEX)
        )
        principal_id = f"service:m05-restore-{uuid4().hex}"
        await _provision_principal(
            migrated_engine,
            principal_id=principal_id,
            initial_event_sequence=int(str(first["event_sequence"])) - 1,
        )
        held = await _deliver_one(migrated_engine, api, principal_id=principal_id)
        # 두 번째 event를 잡아 두고 ack하지 않는다 — 복원 시점의 in-flight holder다.
        # **같은 worker로** 잡는다. ack는 holder를 놓아 주지 않으므로 다른 worker가
        # 오면 `lease_conflict`가 맞다(그것 자체가 lease가 살아 있다는 증거다).
        worker_id = UUID(str(held["worker_id"]))
        leased = await _lease_event(
            api, principal_id=principal_id, worker_id=worker_id
        )
        assert leased["o_outcome"] == "leased", leased
        return {
            "principal_id": principal_id,
            "acked_sequence": int(str(held["event_sequence"])),
            "pending_event_id": UUID(str(leased["o_event_id"])),
            "pending_event_sha256": str(leased["o_event_sha256"]),
            "pending_sequence": int(str(second["event_sequence"])),
            "worker_id": worker_id,
            "lease_epoch": int(str(leased["o_lease_epoch"])),
        }
    finally:
        await api.dispose()
        await dagster.dispose()


async def test_a_dry_run_reports_the_holder_without_writing_anything(
    migrated_engine: AsyncEngine, delivery: dict[str, object]
) -> None:
    principal_id = str(delivery["principal_id"])
    before = await _read_lease(migrated_engine, principal_id)

    async with migrated_engine.connect() as connection:
        report = await repair_restored_database(connection, apply=False)

    assert report.preflight_failures == []
    assert report.applied is False
    mine = next(
        row for row in report.invalidated if row.principal_id == principal_id
    )
    # dump 시점에 holder가 살아 있었다는 사실 자체가 split-brain 후보 신호다.
    assert mine.held is True
    assert mine.cleared_worker_id == str(delivery["worker_id"])
    assert mine.lease_epoch == mine.previous_lease_epoch + 1

    assert await _read_lease(migrated_engine, principal_id) == before


async def test_the_restored_cursor_matches_the_contiguous_prefix(
    migrated_engine: AsyncEngine, delivery: dict[str, object]
) -> None:
    """정합한 스냅숏에는 drift가 0이다 — ack 행과 cursor가 한 블록에서 쓰이므로."""

    principal_id = str(delivery["principal_id"])
    async with migrated_engine.connect() as connection:
        rebuilt, failures = await rebuild_acked_through(connection, apply=False)

    mine = next(row for row in rebuilt if row.principal_id == principal_id)
    assert mine.stored_sequence == delivery["acked_sequence"]
    assert mine.rebuilt_sequence == delivery["acked_sequence"]
    assert mine.drifted is False
    assert mine.first_missing_sequence == delivery["pending_sequence"]
    assert [failure for failure in failures if principal_id in failure] == []


@pytest.mark.parametrize("direction", ["ahead", "behind"])
async def test_a_drifted_cursor_is_fail_loud_and_repaired_to_the_prefix(
    migrated_engine: AsyncEngine, delivery: dict[str, object], direction: str
) -> None:
    """어느 방향이든 drift는 실패다.

    앞서 있으면 ACK 행을 잃은 것이고 뒤처져 있으면 cursor를 잃은 것이다 — 둘 다 dump가
    relation 사이에서 시점이 갈렸다는 신호다. 조용히 고치고 넘어가면 그 사실이 사라진다.
    """

    principal_id = str(delivery["principal_id"])
    acked = int(str(delivery["acked_sequence"]))
    damaged = (
        int(str(delivery["pending_sequence"])) if direction == "ahead" else acked - 1
    )

    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                "UPDATE ops.feature_reference_reconciliation_leases"
                " SET acked_through_sequence = :damaged"
                " WHERE principal_id = :principal_id"
            ),
            {"damaged": damaged, "principal_id": principal_id},
        )

    async with migrated_engine.begin() as connection:
        report = await repair_restored_database(connection, apply=True)

    drift = [failure for failure in report.failures if principal_id in failure]
    assert drift, report.failures
    assert f"cursor drift({direction})" in drift[0]
    assert report.ok is False

    # 수리는 했다 — 실패로 **보고하면서도** 연속 prefix로 되돌린다.
    assert (await _read_lease(migrated_engine, principal_id))[
        "acked_through_sequence"
    ] == acked


async def test_the_rebuild_stops_at_the_gap_not_at_the_maximum_ack(
    migrated_engine: AsyncEngine, delivery: dict[str, object]
) -> None:
    """끊긴 뒤의 ack는 cursor를 밀지 못한다.

    이 축은 앞의 테스트들이 **가려 준다.** 정상 이력에는 구멍이 없어서 연속 prefix와
    최댓값이 늘 같기 때문이다 — 그 상태만 재면 `max(...)`로 바꿔도 초록이다.
    그래서 여기서만 구멍을 만든다: event 셋 중 첫째는 프로시저로 ack하고, 둘째는
    건너뛰고, 셋째의 ack 행만 직접 심는다(ack는 append-only라 INSERT가 열려 있다).

    최댓값을 쓰면 cursor가 셋째까지 밀려 **둘째가 영영 배달되지 않는다.**
    """

    principal_id = str(delivery["principal_id"])
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        third = await _publish_event(
            migrated_engine, api, dagster, index=next(_PAIR_INDEX)
        )
    finally:
        await api.dispose()
        await dagster.dispose()

    skipped_command = await _open_command(
        migrated_engine, actor=principal_id, operation=_ACK_OPERATION
    )
    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO ops.feature_reference_reconciliation_acks ("
                " event_id, principal_id, event_sha256, local_receipt_sha256,"
                " command_id"
                ") VALUES (CAST(:event_id AS uuid), :principal_id, :event_sha256,"
                " repeat('d', 64), :command_id)"
            ),
            {
                "event_id": third["event_id"],
                "principal_id": principal_id,
                "event_sha256": third["event_sha256"],
                "command_id": skipped_command,
            },
        )

    async with migrated_engine.connect() as connection:
        rebuilt, _ = await rebuild_acked_through(connection, apply=False)

    mine = next(row for row in rebuilt if row.principal_id == principal_id)
    assert mine.first_missing_sequence == delivery["pending_sequence"]
    # 최댓값이면 third["event_sequence"]가 됐을 자리다.
    assert mine.rebuilt_sequence == delivery["acked_sequence"]
    assert mine.rebuilt_sequence < int(str(third["event_sequence"]))
    assert mine.drifted is False


async def test_invalidation_breaks_the_pre_restore_fencing_token(
    migrated_engine: AsyncEngine, delivery: dict[str, object]
) -> None:
    """이 항목의 요지 — 복원 전 worker가 복원본에 ack하지 못해야 한다.

    복원본은 원본의 사본이라 dump 시점의 `(worker_id, lease_epoch)`가 양쪽에서 동시에
    유효하다. 무효화하지 않으면 원본을 향해 돌던 worker가 복원본의 cursor도 민다 —
    그것이 split-brain이다. 실제 ack 프로시저로 잰다.
    """

    principal_id = str(delivery["principal_id"])
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    try:
        async with migrated_engine.begin() as connection:
            invalidated = await invalidate_leases(connection, apply=True)
        mine = next(
            row for row in invalidated if row.principal_id == principal_id
        )
        assert mine.held is True

        after = await _read_lease(migrated_engine, principal_id)
        assert after["worker_id"] is None
        assert after["lease_expires_at"] is None
        assert int(str(after["lease_epoch"])) == mine.previous_lease_epoch + 1

        ack_command = await _open_command(
            migrated_engine, actor=principal_id, operation=_ACK_OPERATION
        )
        refused = await _ack_event(
            api,
            principal_id=principal_id,
            event_id=UUID(str(delivery["pending_event_id"])),
            worker_id=UUID(str(delivery["worker_id"])),
            lease_epoch=int(str(delivery["lease_epoch"])),
            event_sha256=str(delivery["pending_event_sha256"]),
            local_receipt_sha256="c" * 64,
            command_id=ack_command,
        )
        assert refused["o_outcome"] == "lease_conflict"
        # cursor가 밀리지 않았다는 것까지 본다 — outcome만 보면 부작용을 놓친다.
        assert int(
            str((await _read_lease(migrated_engine, principal_id))[
                "acked_through_sequence"
            ])
        ) == delivery["acked_sequence"]
    finally:
        await api.dispose()


async def _rollback_scope(migrated_engine: AsyncEngine) -> AsyncConnection:
    connection = await migrated_engine.connect()
    await connection.begin()
    return connection


async def test_a_disabled_append_only_trigger_is_caught_and_blocks_repair(
    migrated_engine: AsyncEngine, delivery: dict[str, object]
) -> None:
    """`--disable-triggers` 복원은 트리거를 **지우지 않고 꺼 둔 채로** 남긴다.

    행도 다 있고 카탈로그에 트리거도 있어 겉보기에는 멀쩡하다. `tgenabled`를 봐야
    드러난다. 그리고 그 상태에서는 **수리하지 않는다** — 검증되지 않은 상태를 고치면
    손상을 되돌릴 수 없게 확정한다.
    """

    principal_id = str(delivery["principal_id"])
    before = await _read_lease(migrated_engine, principal_id)
    connection = await _rollback_scope(migrated_engine)
    try:
        await connection.execute(
            text(
                "ALTER TABLE ops.feature_reference_reconciliation_acks"
                " DISABLE TRIGGER"
                " trg_feature_reference_reconciliation_acks_append_only"
            )
        )
        failures = await preflight_evidence_graph(connection)
        assert any("트리거가 꺼져 있다" in failure for failure in failures), failures
        assert any("acks_append_only" in failure for failure in failures)

        report = await repair_restored_database(connection, apply=True)
        assert report.ok is False
        assert report.applied is False
        # preflight에서 멈췄으므로 무엇도 재구축하지 않았다.
        assert report.rebuilt == []
        assert report.invalidated == []
    finally:
        await connection.rollback()
        await connection.close()

    assert await _read_lease(migrated_engine, principal_id) == before


async def test_an_ack_orphaned_from_its_event_is_caught(
    migrated_engine: AsyncEngine, delivery: dict[str, object]
) -> None:
    """FK가 복원에서 살아나지 않으면 행 점검만이 그 사실을 말한다.

    정상 스키마에서는 이 손상을 만들 수 없다 — FK가 막는다. 그것이 바로 이 점검이
    필요한 이유다: data-only 복원이나 post-data 단계 실패는 FK 없는 DB를 남긴다.
    그 상태를 재현하려면 FK를 떼야 하고, 그래서 이 테스트는 롤백 범위에서 돈다.
    """

    connection = await _rollback_scope(migrated_engine)
    try:
        assert await preflight_evidence_graph(connection) == []
        await connection.execute(
            text(
                "ALTER TABLE ops.feature_reference_reconciliation_acks"
                " DROP CONSTRAINT fk_feature_reference_reconciliation_acks_event"
            )
        )
        orphan_command = await _open_command(
            migrated_engine, actor=str(delivery["principal_id"]),
            operation=_ACK_OPERATION,
        )
        await connection.execute(
            text(
                "INSERT INTO ops.feature_reference_reconciliation_acks ("
                " event_id, principal_id, event_sha256, local_receipt_sha256,"
                " command_id"
                ") VALUES (x_extension.gen_random_uuid(), :principal_id,"
                " repeat('a', 64), repeat('b', 64), :command_id)"
            ),
            {
                "principal_id": delivery["principal_id"],
                "command_id": orphan_command,
            },
        )
        failures = await preflight_evidence_graph(connection)
        assert any(
            "event를 가리키지 않는 ACK" in failure for failure in failures
        ), failures
    finally:
        await connection.rollback()
        await connection.close()


async def test_an_origin_without_its_identity_claim_is_caught(
    migrated_engine: AsyncEngine, delivery: dict[str, object]
) -> None:
    """origin과 claim이 갈리면 append-only 불변 자체가 깨진다.

    exporter가 `domain_commands`를 담는 이유가 이것이다. 정상 스키마에서는 복합 FK와
    append-only 트리거가 이 상태를 막으므로, 재현하려면 둘 다 떼야 한다 — data-only
    복원이나 post-data 단계 실패가 남기는 DB가 정확히 그 모양이다.
    """

    del delivery  # 이력이 있어야 origin이 하나라도 있다.
    connection = await _rollback_scope(migrated_engine)
    try:
        await connection.execute(
            text(
                "ALTER TABLE feature.manual_feature_identity_claims"
                " DISABLE TRIGGER trg_manual_feature_identity_claims_append_only"
            )
        )
        await connection.execute(
            text(
                "ALTER TABLE feature.feature_creation_origins"
                " DROP CONSTRAINT fk_feature_creation_origins_claim"
            )
        )
        removed = await connection.execute(
            text(
                "DELETE FROM feature.manual_feature_identity_claims"
                " WHERE feature_id IN ("
                " SELECT feature_id FROM feature.feature_creation_origins LIMIT 1)"
            )
        )
        assert removed.rowcount == 1

        failures = await preflight_evidence_graph(connection)
        assert any(
            "identity claim이 없는 manual origin" in failure for failure in failures
        ), failures
    finally:
        await connection.rollback()
        await connection.close()


async def test_a_missing_relation_stops_before_the_row_checks(
    migrated_engine: AsyncEngine,
) -> None:
    """없는 relation을 향해 행 점검을 돌리면 `UndefinedTable`로 죽는다.

    그러면 "무엇이 없는지"를 말하지 못한다 — 검증기가 손상된 입력에 죽으면 안 된다는
    B단계의 규약과 같다.
    """

    connection = await _rollback_scope(migrated_engine)
    try:
        await connection.execute(
            text(
                "ALTER TABLE ops.feature_reference_reconciliation_acks"
                " RENAME TO feature_reference_reconciliation_acks_moved"
            )
        )
        failures = await preflight_evidence_graph(connection)
        assert failures == [
            "relation이 없다: ops.feature_reference_reconciliation_acks"
        ]
    finally:
        await connection.rollback()
        await connection.close()


async def test_the_evidence_relations_the_repairer_requires_match_the_exporter() -> None:
    """수리기가 요구하는 relation과 exporter가 담는 relation이 갈리면 안 된다.

    갈리면 담기지 않은 relation을 복원본에서 요구하거나(늘 실패), 담긴 relation을
    점검하지 않는다(조용한 구멍). 값이 아니라 두 정본을 대조한다.
    """

    from kortravelmap.infra.evidence_export import EVIDENCE_RELATIONS
    from kortravelmap.infra.evidence_restore import _REQUIRED_RELATIONS

    exported = {relation.name for relation in EVIDENCE_RELATIONS}
    required = {relation.split(".", 1)[1] for relation in _REQUIRED_RELATIONS}
    # 수리기는 exporter가 담는 열에 **더해** `leases`를 요구한다. lease는 일부러 담지
    # 않지만(fencing token), 복원본에는 반드시 있어야 무효화할 것이 있다.
    assert required - exported == {"feature_reference_reconciliation_leases"}
    assert exported - required == set()


def test_the_module_is_wired_into_the_backup_runbook() -> None:
    """문서가 D단계를 모르면 복원 담당자가 이 도구의 존재를 알 길이 없다."""

    import pathlib

    runbook = pathlib.Path(__file__).resolve().parents[2] / "docs" / "backup-restore.md"
    body = runbook.read_text(encoding="utf-8")
    assert "evidence_restore" in body
    assert "repair_restored_database" in body

"""ADR-121 R4 전환 실행기 — 실 PostGIS에서 attach·collapse·retire와 M05 사건.

``migrated_session``(테스트 끝에 rollback) 안에서 실행기를 **API runtime 로그인**으로 돌린다 —
사건 writer는 ``session_user = ktm_feature_service``와 admin executor membership을 요구한다.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.core.theme_attach import PlanEntry
from kortravelmap.infra import feature_repo
from kortravelmap.infra.mcst_theme_transition_repo import (
    TransitionBatchResult,
    TransitionPlan,
    build_transition_plan,
    execute_transition_batch,
    load_transition_plan,
)
from tests.integration.conftest import as_api_runtime
from tests.integration.test_theme_attach_load import (
    _feature_of_entity,
    _master_bundle,
    _master_id,
    _mcst_bundles,
    _offset,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def _mcst_feature(session: AsyncSession, slug: str, name: str, east_m: float) -> str:
    [bundle] = await _mcst_bundles(slug, (name, _offset(east_m)))
    await feature_repo.load_bundles(session, [bundle])
    [(feature_id, _role)] = await _feature_of_entity(
        session, str(bundle.feature.provider_natural_key), f"mcst_{slug}"
    )
    return feature_id


async def _revision(session: AsyncSession, feature_id: str) -> int:
    return int(
        (
            await session.execute(
                text("SELECT row_revision FROM feature.features WHERE feature_id = :id"),
                {"id": feature_id},
            )
        ).scalar_one()
    )


async def _state(session: AsyncSession, feature_id: str) -> tuple[str, str]:
    row = (
        await session.execute(
            text(
                "SELECT lifecycle_state, publication_state FROM feature.features "
                "WHERE feature_id = :id"
            ),
            {"id": feature_id},
        )
    ).one()
    return str(row[0]), str(row[1])


async def _plan(session: AsyncSession, entries: list[PlanEntry]) -> TransitionPlan:
    revisions = {entry.feature_id: await _revision(session, entry.feature_id) for entry in entries}
    plan = build_transition_plan(entries, revisions=revisions, rule_version="theme-attach-v1")
    # 계획 파일 왕복이 같은 계획을 돌려준다(sha 검증 포함).
    assert load_transition_plan(plan.as_json()) == plan
    return plan


async def _run(
    session: AsyncSession, plan: TransitionPlan, *, batch_size: int = 500
) -> TransitionBatchResult:
    async with session.begin_nested(), as_api_runtime(session):
        return await execute_transition_batch(
            session, plan=plan, batch_size=batch_size, batch_index=0, items=plan.items
        )


async def _events_for(session: AsyncSession, feature_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            text(
                "SELECT action, origin_kind, CAST(case_id AS text) AS case_id, "
                "CAST(resolution_id AS text) AS resolution_id, "
                "CAST(replacement_feature_id AS text) AS replacement, event_payload, "
                "event_sha256, manual_case_ref, mcst_item_ref "
                "FROM ops.feature_reference_reconciliation_events "
                "WHERE old_feature_id = CAST(:id AS uuid)"
            ),
            {"id": feature_id},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def test_attach_collapse_and_retire_emit_m05_events(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    await feature_repo.load_bundles(
        session, [_master_bundle("전환테스트박물관", _offset(7000), "tr-master-1")]
    )
    master = await _master_id(session, "tr-master-1")
    attach = await _mcst_feature(session, "barrier_free_places_csv", "전환테스트박물관", 7005)
    survivor = await _mcst_feature(session, "independent_bookstores_csv", "전환테스트책방", 7400)
    collapse = await _mcst_feature(
        session, "family_infant_culture_facilities_csv", "전환테스트책방", 7402
    )
    retire = await _mcst_feature(
        session, "pet_friendly_culture_facilities_csv", "전환테스트동물병원", 7800
    )
    # 패자를 가리키는 열린 dedup 검토 행은 전환과 함께 닫힌다.
    await session.execute(
        text(
            "INSERT INTO ops.dedup_review_queue (feature_id_a, feature_id_b, total_score, "
            "name_score, spatial_score, category_score) VALUES ("
            "LEAST(CAST(:a AS uuid), CAST(:b AS uuid)), GREATEST(CAST(:a AS uuid), "
            "CAST(:b AS uuid)), 90, 90, 90, 90)"
        ),
        {"a": collapse, "b": survivor},
    )
    plan = await _plan(
        session,
        [
            PlanEntry(attach, "mcst_barrier_free_places_csv", "attach", master, {}),
            PlanEntry(
                collapse, "mcst_family_infant_culture_facilities_csv", "collapse", survivor, {}
            ),
            PlanEntry(retire, "mcst_pet_friendly_culture_facilities_csv", "retire", None, {}),
        ],
    )

    result = await _run(session, plan)

    assert result.counts() == {"attach:done": 1, "collapse:done": 1, "retire:done": 1}
    for loser in (attach, collapse, retire):
        assert await _state(session, loser) == ("retired", "suppressed")
    assert await _state(session, master) == ("active", "published")
    assert await _state(session, survivor) == ("active", "published")
    # 병합된 MCST link는 master에 enrichment로 붙는다(master의 primary는 그대로).
    roles = sorted(
        str(role)
        for (role,) in (
            await session.execute(
                text(
                    "SELECT source_role FROM provider_sync.source_links "
                    "WHERE feature_id = CAST(:id AS uuid)"
                ),
                {"id": master},
            )
        ).all()
    )
    assert roles == ["enrichment", "primary"]

    [attach_event] = await _events_for(session, attach)
    [collapse_event] = await _events_for(session, collapse)
    [retire_event] = await _events_for(session, retire)
    assert (attach_event["action"], attach_event["replacement"]) == ("rebind", master)
    assert (collapse_event["action"], collapse_event["replacement"]) == ("rebind", survivor)
    assert (retire_event["action"], retire_event["replacement"]) == ("detach", None)
    for event in (attach_event, collapse_event, retire_event):
        assert event["origin_kind"] == "mcst_theme_transition"
        assert event["manual_case_ref"] is None
        assert event["mcst_item_ref"] is not None
        payload = event["event_payload"]
        # PinVi 소비 모델이 요구하는 키 그대로 — case/resolution은 batch/item이다.
        assert set(payload) == {
            "payload_schema_version", "event_id", "event_sequence", "occurred_at", "case_id",
            "resolution_id", "action", "old_feature", "replacement_feature",
            "manual_retire_transition_id", "manual_retire_row_revision_after_transition",
            "command_id",
        }
        assert payload["case_id"] == event["case_id"]
        assert payload["resolution_id"] == event["resolution_id"]
        assert payload["manual_retire_row_revision_after_transition"] >= 2
    # sha는 jsonb 본문 렌더링의 sha256이다(M05와 같은 규칙).
    rendered = (
        await session.execute(
            text(
                "SELECT event_payload::text FROM ops.feature_reference_reconciliation_events "
                "WHERE old_feature_id = CAST(:id AS uuid)"
            ),
            {"id": retire},
        )
    ).scalar_one()
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == retire_event["event_sha256"]

    # 장부에 되돌림 근거가 남는다.
    before = (
        await session.execute(
            text(
                "SELECT before_state FROM ops.mcst_theme_transition_items "
                "WHERE feature_id = CAST(:id AS uuid)"
            ),
            {"id": attach},
        )
    ).scalar_one()
    assert before["lifecycle_state"] == "active"
    assert [link["source_role"] for link in before["links"]] == ["primary"]
    assert [link["source_role"] for link in before["target_links"]] == ["primary"]

    # 단독 퇴역은 lifecycle override를 남긴다 — provider 재적재가 되살리지 않는다.
    override = (
        await session.execute(
            text(
                "SELECT override_value FROM ops.feature_overrides "
                "WHERE feature_id = CAST(:id AS uuid) AND field_path = 'lifecycle_state' "
                "AND status = 'active'"
            ),
            {"id": retire},
        )
    ).scalar_one()
    assert override == "retired"

    review_status = (
        await session.execute(
            text(
                "SELECT status FROM ops.dedup_review_queue "
                "WHERE CAST(:id AS uuid) IN (feature_id_a, feature_id_b)"
            ),
            {"id": collapse},
        )
    ).scalar_one()
    assert review_status == "ignored"

    # 같은 계획의 같은 batch는 다시 돌지 않는다.
    again = await _run(session, plan)
    assert again.skipped_batch
    # 다른 batch 크기로 다시 돌리면 batch는 새로 잡히지만 Feature는 하나도 다시 바뀌지 않는다.
    resized = await _run(session, plan, batch_size=1)
    assert not resized.skipped_batch
    assert resized.counts() == {
        "attach:already_done": 1,
        "collapse:already_done": 1,
        "retire:already_done": 1,
    }
    assert len(await _events_for(session, attach)) == 1


async def test_stale_plan_rows_are_skipped_without_changes(
    migrated_session: AsyncSession,
) -> None:
    session = migrated_session
    await feature_repo.load_bundles(
        session, [_master_bundle("낡은계획테스트관", _offset(9000), "tr-master-stale")]
    )
    master = await _master_id(session, "tr-master-stale")
    loser = await _mcst_feature(session, "barrier_free_places_csv", "낡은계획테스트관", 9004)
    revisions = {loser: await _revision(session, loser) + 7}  # 계획 뒤에 바뀐 것처럼
    plan = build_transition_plan(
        [PlanEntry(loser, "mcst_barrier_free_places_csv", "attach", master, {})],
        revisions=revisions,
        rule_version="theme-attach-v1",
    )

    result = await _run(session, plan)

    assert result.counts() == {"attach:stale_revision": 1}
    assert await _state(session, loser) == ("active", "published")
    assert await _events_for(session, loser) == []


async def test_retired_target_is_skipped(migrated_session: AsyncSession) -> None:
    session = migrated_session
    gone = await _mcst_feature(session, "pet_friendly_culture_facilities_csv", "사라질곳", 9600)
    loser = await _mcst_feature(session, "barrier_free_places_csv", "사라질곳", 9603)
    first = await _plan(
        session, [PlanEntry(gone, "mcst_pet_friendly_culture_facilities_csv", "retire", None, {})]
    )
    assert (await _run(session, first)).counts() == {"retire:done": 1}
    second = await _plan(
        session, [PlanEntry(loser, "mcst_barrier_free_places_csv", "collapse", gone, {})]
    )

    result = await _run(session, second)

    assert result.counts() == {"collapse:stale_target": 1}
    assert await _state(session, loser) == ("active", "published")
    assert await _events_for(session, loser) == []


async def test_plan_file_tampering_is_rejected() -> None:
    plan = build_transition_plan(
        [PlanEntry("00000000-0000-7000-8000-000000000001", "d", "retire", None, {})],
        revisions={"00000000-0000-7000-8000-000000000001": 3},
        rule_version="theme-attach-v1",
    )
    payload = plan.as_json()
    payload["items"][0]["row_revision"] = 4
    with pytest.raises(ValueError, match="plan_sha256"):
        load_transition_plan(payload)

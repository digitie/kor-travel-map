"""geo 릴리스 재지오코딩 계획 — 감지·기준선·멱등·항목·커버리지·완료(ADR-109 결정 5, T-GR-04).

DB는 head(408)까지 올린 통합 DB이고, provider dataset·operation은 baseline seed 그대로다(KNPS
두 job에 dataset 다섯씩, MCST 열셋, 자동 적재를 끈 넷, 큐 전용 MOIS 갱신 셋). Feature는 실제
변환기(``standard_data`` 축제·``krheritage``)에 가짜 역지오코더를 꽂아 적재한다.

세션은 테스트마다 롤백된다(``migrated_session``) — 계획 표는 테스트마다 비어서 시작한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.dto import Address
from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.infra import geo_release_repo
from kortravelmap.infra.feature_geocode_stamp_repo import coverage, upsert_stamps
from kortravelmap.infra.feature_repo import load_bundles
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from tests.integration.test_geo_release_load_path import (
    REF_A,
    REF_B,
    TOKEN_A,
    TOKEN_B,
    VERSION_A,
    _ctx,
    _FakeReverse,
    _feature_id,
    _festival,
    _geo,
    _heritage,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto import FeatureBundle

pytestmark = pytest.mark.integration

_KNPS_POINTS = "feature_place_knps_points_job"
_KNPS_GEOMETRY = "feature_geometry_knps_records_job"
_FESTIVALS = "feature_event_datagokr_cultural_festivals_job"


async def _dataset_id(session: AsyncSession, bundle: FeatureBundle) -> int:
    """적재된 bundle의 primary link가 가리키는 dataset — dataset_key만으로는 유일하지 않다(다른
    테스트가 같은 key를 다른 provider로 등록한다)."""
    feature_id = await _feature_id(session, bundle)
    return int(
        (
            await session.execute(
                text(
                    "SELECT DISTINCT entity.provider_dataset_id "
                    "FROM provider_sync.source_links AS link "
                    "JOIN provider_sync.source_entities AS entity "
                    "  ON entity.source_entity_key = link.source_entity_key "
                    "WHERE link.feature_id = CAST(:id AS uuid) AND link.source_role = 'primary'"
                ),
                {"id": feature_id},
            )
        ).scalar_one()
    )


async def _set_all_items(session: AsyncSession, plan_id: int, state: str) -> None:
    await session.execute(
        text(
            "UPDATE ops.kor_travel_geo_release_items SET state = :state "
            "WHERE plan_id = :plan_id AND state <> 'skipped'"
        ),
        {"plan_id": plan_id, "state": state},
    )


async def _plan_rows(session: AsyncSession) -> list[tuple[Any, ...]]:
    return [
        tuple(row)
        for row in await session.execute(
            text(
                "SELECT geo_data_token, plan_seq, state FROM ops.kor_travel_geo_releases "
                "ORDER BY plan_id"
            )
        )
    ]


async def _baseline_then(session: AsyncSession, ref: DatasetRef) -> geo_release_repo.GeoReleasePlan:
    baseline = await geo_release_repo.plan_geo_release(session, REF_A)
    assert baseline.kind == "baseline_recorded"
    outcome = await geo_release_repo.plan_geo_release(session, ref)
    assert outcome.kind == "created", outcome.kind
    assert outcome.plan is not None
    return outcome.plan


# -- 감지·기준선·멱등 ----------------------------------------------------------------------------


async def test_first_observed_token_is_a_baseline_not_a_plan(
    migrated_session: AsyncSession,
) -> None:
    """소유자 결정(2026-10-15) — 처음 관측한 토큰은 기준선으로만 남고 계획·항목이 없다."""
    first = await geo_release_repo.plan_geo_release(migrated_session, REF_A)
    again = await geo_release_repo.plan_geo_release(migrated_session, REF_A)

    assert (first.kind, again.kind) == ("baseline_recorded", "baseline")
    assert first.plan is not None
    assert first.plan.state == "baseline"
    assert first.plan.items == ()
    assert await _plan_rows(migrated_session) == [(TOKEN_A, 1, "baseline")]


async def test_a_token_without_data_token_never_plans(migrated_session: AsyncSession) -> None:
    outcome = await geo_release_repo.plan_geo_release(
        migrated_session, DatasetRef(version_token=VERSION_A)
    )
    assert outcome.kind == "no_token"
    assert await _plan_rows(migrated_session) == []


async def test_detect_twice_with_the_same_token_keeps_one_active_plan(
    migrated_session: AsyncSession,
) -> None:
    plan = await _baseline_then(migrated_session, REF_B)
    again = await geo_release_repo.plan_geo_release(migrated_session, REF_B)

    assert again.kind == "existing"
    assert again.plan is not None
    assert again.plan.plan_id == plan.plan_id
    assert await _plan_rows(migrated_session) == [
        (TOKEN_A, 1, "baseline"),
        (TOKEN_B, 1, "planned"),
    ]


async def test_rollback_a_b_a_plans_the_second_a_again(migrated_session: AsyncSession) -> None:
    """A→B→A — B의 run이 행을 B로 다시 봉인했으면 두 번째 A는 ``plan_seq=2`` 새 계획이다."""
    bundle = await _festival("rollback-aba", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_A))
    feature_id = await _feature_id(migrated_session, bundle)
    b_plan = await _baseline_then(migrated_session, REF_B)
    # B 계획이 그 행을 B로 다시 적재했다.
    await upsert_stamps(migrated_session, current=REF_B, outcomes={feature_id: "called"})

    second_a = await geo_release_repo.plan_geo_release(migrated_session, REF_A)

    assert second_a.kind == "created"
    assert second_a.plan is not None
    assert second_a.plan.plan_seq == 2
    assert second_a.superseded_plan_ids == (b_plan.plan_id,)
    assert await _plan_rows(migrated_session) == [
        (TOKEN_A, 1, "baseline"),
        (TOKEN_B, 1, "superseded"),
        (TOKEN_A, 2, "planned"),
    ]


async def test_a_finished_token_with_no_residual_is_not_planned_again(
    migrated_session: AsyncSession,
) -> None:
    bundle = await _festival("finished", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_B))
    plan = await _baseline_then(migrated_session, REF_B)
    await _set_all_items(migrated_session, plan.plan_id, "done")
    completed = await geo_release_repo.complete_plan(migrated_session, plan.plan_id)
    assert completed.kind == "done"

    again = await geo_release_repo.plan_geo_release(migrated_session, REF_B)

    assert again.kind == "already_complete"
    assert len(await _plan_rows(migrated_session)) == 2


# -- 항목 ----------------------------------------------------------------------------------------


async def test_items_follow_the_db_operations_and_the_core_policy(
    migrated_session: AsyncSession,
) -> None:
    plan = await _baseline_then(migrated_session, REF_B)
    items = plan.items
    by_op: dict[str, list[geo_release_repo.GeoReleaseItem]] = {}
    for item in items:
        by_op.setdefault(item.operation_key, []).append(item)

    # KNPS — job 하나에 dataset 다섯, 항목도 다섯이고 run_config가 dataset마다 다르다.
    for operation_key, resources in (
        (_KNPS_POINTS, ("knps_point_dataset_key", "knps_point_records")),
        (_KNPS_GEOMETRY, ("knps_geometry_dataset_key", "knps_geometry_records")),
    ):
        knps = by_op[operation_key]
        assert len(knps) == 5
        assert all(item.state == "pending" for item in knps)
        assert {
            json_key
            for item in knps
            for json_key in (item.run_config or {}).get("resources", {})
        } == set(resources)
        assert sorted(
            item.run_config["resources"][resources[1]]["config"]["dataset_key"]  # type: ignore[index]
            for item in knps
        ) == sorted(item.dataset_key for item in knps)

    # 자동 적재를 끈 넷 → skipped(disabled); geo를 쓰지 않는 job → skipped(no_geo_dependency);
    # Dagster job이 없는 큐 전용 operation → skipped(queue_only).
    reasons = {item.operation_key: (item.state, item.state_reason) for item in items}
    assert reasons["feature_place_standard_special_streets_job"] == ("skipped", "disabled")
    assert reasons["feature_place_datagokr_jeju_local_restaurants_job"] == ("skipped", "disabled")
    assert reasons["feature_event_visitkorea_enrichment_job"] == ("skipped", "no_geo_dependency")
    assert reasons["feature_notice_transport_highway_incidents_job"] == (
        "skipped",
        "no_geo_dependency",
    )
    assert reasons["feature_price_transport_fuel_stations_job"] == (
        "skipped",
        "no_geo_dependency",
    )
    assert reasons["mois_license_incremental_update"] == ("skipped", "queue_only")

    # 쿼터 민감 → replay run_config.
    mois = by_op["feature_place_mois_licenses_job"][0]
    assert mois.run_config == {
        "resources": {"mois_license_records": {"config": {"source_mode": "replay"}}}
    }
    bookstores = by_op["feature_place_datagokr_seoul_bookstores_job"][0]
    assert bookstores.run_config == {
        "resources": {
            "datagokr_file_data_dataset_key": {
                "config": {"dataset_key": "datagokr_seoul_bookstores"}
            },
            "datagokr_file_data_records": {
                "config": {"dataset_key": "datagokr_seoul_bookstores", "source_mode": "replay"}
            },
        }
    }

    # 순서 — 실행 항목이 skip보다 앞, 공개 place가 concierge보다 앞, MOIS는 실행 항목의 맨 끝.
    states = [item.state for item in items]
    assert states == sorted(states, key=lambda state: state == "skipped")
    pending = [item.operation_key for item in items if item.state == "pending"]
    assert pending[-1] == "feature_place_mois_licenses_job"
    concierge = pending.index("feature_place_kor_travel_concierge_youtube_job")
    assert pending.index("feature_place_krheritage_items_job") < concierge
    assert [item.position for item in items] == list(range(1, len(items) + 1))


def test_run_config_for_a_job_without_dataset_binding_is_none() -> None:
    assert geo_release_repo.run_config_for_dataset("feature_place_khoa_beaches_job", "x") is None


# -- 커버리지 ------------------------------------------------------------------------------------


async def test_coverage_is_limited_to_the_given_datasets(migrated_session: AsyncSession) -> None:
    bundles = [await _festival(f"coverage-{index}", _FakeReverse(_geo())) for index in range(4)]
    await load_bundles(migrated_session, bundles, geo=_ctx(REF_A))
    ids = [await _feature_id(migrated_session, bundle) for bundle in bundles]
    heritage = await _heritage(_FakeReverse(_geo()))
    await load_bundles(migrated_session, [heritage], geo=_ctx(REF_A))
    # ids[0] = 옛 토큰(stale), ids[1] = 현재 토큰, ids[2] = 스탬프 없음, ids[3] = not_called.
    await upsert_stamps(migrated_session, current=REF_B, outcomes={ids[1]: "called"})
    await upsert_stamps(migrated_session, current=REF_A, outcomes={ids[3]: "not_called"})
    await migrated_session.execute(
        text("DELETE FROM feature.feature_geocode_stamps WHERE feature_id = CAST(:id AS uuid)"),
        {"id": ids[2]},
    )
    festivals = await _dataset_id(migrated_session, bundles[0])
    heritage_items = await _dataset_id(migrated_session, heritage)

    result = await coverage(
        migrated_session,
        TOKEN_B,
        provider_dataset_ids={festivals},
        skipped_provider_dataset_ids={heritage_items},
    )

    assert result.total_provider_with_coord == 4  # heritage 행은 분모 밖
    assert (result.stamped_current, result.stamped_other, result.unstamped) == (1, 1, 1)
    assert result.not_called_by_kind == {"event": 1}
    assert result.excluded_by_skip == 1
    assert result.unstamped_non_provider == 0
    assert result.remaining == 2


# -- 운영자 전이 ---------------------------------------------------------------------------------


async def test_skip_and_replan(migrated_session: AsyncSession) -> None:
    plan = await _baseline_then(migrated_session, REF_B)
    position = next(item.position for item in plan.items if item.state == "pending")

    skipped = await geo_release_repo.skip_item(migrated_session, plan.plan_id, position)
    item = next(item for item in skipped.items if item.position == position)
    assert (item.state, item.state_reason) == ("skipped", "operator")
    with pytest.raises(geo_release_repo.GeoReleaseConflict):
        await geo_release_repo.skip_item(migrated_session, plan.plan_id, position)

    replanned = await geo_release_repo.replan(migrated_session, plan.plan_id)
    assert (replanned.geo_data_token, replanned.plan_seq) == (TOKEN_B, 2)
    assert replanned.state == "planned"
    old = await geo_release_repo.get_geo_release_plan(migrated_session, plan.plan_id)
    assert old is not None
    assert old.state == "superseded"
    with pytest.raises(geo_release_repo.GeoReleaseConflict):
        await geo_release_repo.skip_item(migrated_session, plan.plan_id, position)


# -- 완료 ----------------------------------------------------------------------------------------


async def test_completion_sweeps_once_then_records_the_residual(
    migrated_session: AsyncSession,
) -> None:
    bundle = await _festival("sweep", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_A))  # B 기준 stale
    plan = await _baseline_then(migrated_session, REF_B)
    await _set_all_items(migrated_session, plan.plan_id, "requested")
    not_ready = await geo_release_repo.complete_plan(migrated_session, plan.plan_id)
    assert not_ready.kind == "not_ready"
    await _set_all_items(migrated_session, plan.plan_id, "done")

    first = await geo_release_repo.complete_plan(migrated_session, plan.plan_id)
    assert first.kind == "sweep"
    swept = [item for item in first.plan.items if item.position in first.sweep_positions]
    assert [item.operation_key for item in swept] == [_FESTIVALS]
    assert (swept[0].state, swept[0].state_reason, swept[0].attempt_seq) == ("pending", "sweep", 2)

    await _set_all_items(migrated_session, plan.plan_id, "done")
    second = await geo_release_repo.complete_plan(migrated_session, plan.plan_id)
    assert second.kind == "done"
    assert second.plan.residual_stale == 1  # 두 번째 sweep은 운영자 replan이다


async def test_completion_moves_a_same_sigungu_link_to_the_new_target(
    migrated_session: AsyncSession,
) -> None:
    """geo 릴리스로 ``sigungu_code``가 바뀐 행의 ``same_sigungu`` 링크가 새 target으로 옮겨진다."""
    targets = {}
    for key, lon, lat in (("yeongdeungpo", 126.92, 37.52), ("gangnam", 127.05, 37.50)):
        target = await upsert_poi_cache_target(
            migrated_session,
            external_system="geo-release-test",
            target_key=key,
            lon=lon,
            lat=lat,
            radius_km=1.0,
            scope_mode="sigungu_by_radius",
        )
        targets[key] = str(target.target_id)
    sigungu_of = {126.92: "11560", 127.05: "11680"}

    async def resolver(*, lon: float, lat: float, radius_km: float) -> tuple[str, ...]:
        del lat, radius_km
        return (sigungu_of[round(lon, 2)],)

    bundle = await _festival("link-move", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_A))
    feature_id = await _feature_id(migrated_session, bundle)
    await geo_release_repo._resync_cache_target_links(  # noqa: SLF001 — 초기 링크 상태
        migrated_session, sigungu_resolver=resolver
    )
    assert await _active_link_targets(migrated_session, feature_id) == {targets["yeongdeungpo"]}

    # 새 geo 릴리스 B가 같은 좌표를 강남구로 해석한다(적재 경로 stale 분기가 주소를 고쳐 쓴다).
    moved = Address(
        legal="서울특별시 강남구 역삼동",
        admin="역삼1동",
        bjd_code="1168010100",
        admin_dong_code="1168064000",
        sigungu_code="11680",
        sido_code="11",
        sido_name="서울특별시",
        sigungu_name="강남구",
    )
    plan = await _baseline_then(migrated_session, REF_B)
    again = await _festival("link-move", _FakeReverse(moved))
    result = await load_bundles(migrated_session, [again], geo=_ctx(REF_B))
    assert result.geo_stale_rewritten == 1
    await _set_all_items(migrated_session, plan.plan_id, "done")

    completed = await geo_release_repo.complete_plan(
        migrated_session, plan.plan_id, sigungu_resolver=resolver
    )

    assert completed.kind == "done"
    assert completed.linked_target_count == 2
    assert await _active_link_targets(migrated_session, feature_id) == {targets["gangnam"]}


async def _active_link_targets(session: AsyncSession, feature_id: str) -> set[str]:
    rows = await session.execute(
        text(
            "SELECT target_id::text FROM ops.poi_cache_target_feature_links "
            "WHERE feature_id = CAST(:id AS uuid) AND active AND relation = 'same_sigungu'"
        ),
        {"id": feature_id},
    )
    return {str(row[0]) for row in rows}

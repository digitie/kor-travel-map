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

from kortravelmap.core.feature_operation import (
    REPLAY_RECORDS_RESOURCES,
    SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS,
)
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
    completed = await geo_release_repo.complete_plan(
        migrated_session, plan.plan_id, sigungu_resolver=None
    )
    assert completed.kind == "done"

    again = await geo_release_repo.plan_geo_release(migrated_session, REF_B)

    assert again.kind == "already_complete"
    assert len(await _plan_rows(migrated_session)) == 2


async def test_a_done_plan_with_residual_is_not_replanned_on_the_next_detect(
    migrated_session: AsyncSession,
) -> None:
    """잔여를 남기고 끝난 계획 — 다음 감지·tick이 매번 다시 계획하면 쿼터를 사이클마다 다시 쓴다."""
    bundle = await _festival("residual", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_A))  # B 기준 stale, 고쳐지지 않는다
    plan = await _baseline_then(migrated_session, REF_B)
    for _ in range(2):  # sweep 1회 뒤 완료
        await _set_all_items(migrated_session, plan.plan_id, "done")
        await geo_release_repo.complete_plan(
            migrated_session, plan.plan_id, sigungu_resolver=None
        )
    finished = await geo_release_repo.get_geo_release_plan(migrated_session, plan.plan_id)
    assert finished is not None
    assert (finished.state, finished.residual_stale) == ("done", 1)

    again = await geo_release_repo.plan_geo_release(migrated_session, REF_B)

    assert again.kind == "already_complete"
    assert len(await _plan_rows(migrated_session)) == 2


async def test_rollback_before_the_new_plan_ran_supersedes_it(
    migrated_session: AsyncSession,
) -> None:
    """기준선 A → B 계획 → B가 돌기 전에 geo가 A로 롤백(재스탬프 없음) — B는 활성이 아니다."""
    bundle = await _festival("rollback-early", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_A))
    b_plan = await _baseline_then(migrated_session, REF_B)

    back = await geo_release_repo.plan_geo_release(migrated_session, REF_A)

    assert back.kind == "already_complete"
    assert back.superseded_plan_ids == (b_plan.plan_id,)
    assert await _plan_rows(migrated_session) == [
        (TOKEN_A, 1, "baseline"),
        (TOKEN_B, 1, "superseded"),
    ]


async def test_replan_only_the_latest_token_and_never_a_baseline(
    migrated_session: AsyncSession,
) -> None:
    baseline = await geo_release_repo.plan_geo_release(migrated_session, REF_A)
    assert baseline.plan is not None
    with pytest.raises(geo_release_repo.GeoReleaseConflict):
        await geo_release_repo.replan(migrated_session, baseline.plan.plan_id)
    b_plan = (await geo_release_repo.plan_geo_release(migrated_session, REF_B)).plan
    assert b_plan is not None
    # A가 다시 관측돼 그 토큰이 최신이 됐다 — 옛 B 계획을 다시 돌리지 않는다.
    bundle = await _festival("replan-latest", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_B))
    a_again = await geo_release_repo.plan_geo_release(migrated_session, REF_A)
    assert a_again.kind == "created"
    with pytest.raises(geo_release_repo.GeoReleaseConflict) as old_token:
        await geo_release_repo.replan(migrated_session, b_plan.plan_id)
    assert not isinstance(old_token.value, geo_release_repo.GeoReleaseNotFound)
    with pytest.raises(geo_release_repo.GeoReleaseNotFound):
        await geo_release_repo.replan(migrated_session, 999_999)


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
        assert all(len(item.datasets) == 1 for item in knps)
        assert sorted(
            item.run_config["resources"][resources[1]]["config"]["dataset_key"]  # type: ignore[index]
            for item in knps
        ) == sorted(item.datasets[0].dataset_key for item in knps)
        assert all(item.launch_blocked_reason is None for item in knps)

    # MCST — job 하나에 dataset 13개, run_config가 없으니 run 1개 = 항목 1개.
    mcst = by_op["feature_place_mcst_culture_job"]
    assert len(mcst) == 1
    assert len(mcst[0].datasets) == 13
    assert mcst[0].run_config is None

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
    # replay 게이트 — T-GR-08 전에는 센서가 낼 수 없는 항목이다(코드 게이트).
    assert mois.launch_blocked_reason == "replay_not_launchable_before_t_gr_08"
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

    assert [item.position for item in items] == list(range(1, len(items) + 1))


async def test_items_are_ordered_by_group_then_stale_count(migrated_session: AsyncSession) -> None:
    """ADR-109 결정 5.3 순서의 경계마다 — ① 공개 place < ② event·route·geometry < ③ concierge <
    ④ replay < MOIS < skip, 같은 묶음 안에서는 stale 수 내림차순."""
    heritage = await _heritage(_FakeReverse(_geo()))
    await load_bundles(migrated_session, [heritage], geo=_ctx(REF_A))  # B 기준 stale 1
    plan = await _baseline_then(migrated_session, REF_B)
    keys = [item.operation_key for item in plan.items]
    states = [item.state for item in plan.items]

    def group(key: str) -> int:
        if key == "feature_place_mois_licenses_job":
            return 5
        if key in REPLAY_RECORDS_RESOURCES:
            return 4
        if key == "feature_place_kor_travel_concierge_youtube_job":
            return 3
        return 1 if key.startswith("feature_place_") else 2

    pending = [key for key, state in zip(keys, states, strict=True) if state == "pending"]
    groups = [group(key) for key in pending]
    assert groups == sorted(groups), groups
    assert set(groups) == {1, 2, 3, 4, 5}  # 경계가 다 있다
    # ① 안에서 stale이 있는 krheritage가 stale 0인 place(이름순으로 앞인 khoa 등)보다 앞이다.
    assert pending[0] == "feature_place_krheritage_items_job"
    assert pending.index("feature_place_khoa_beaches_job") > 0
    # 실행 항목 전부가 skip보다 앞.
    first_skipped = states.index("skipped")
    assert all(state == "skipped" for state in states[first_skipped:])


def test_run_config_for_a_job_without_dataset_binding_is_none() -> None:
    assert geo_release_repo.run_config_for_dataset("feature_place_khoa_beaches_job", "x") is None


def test_no_replay_operation_is_launchable_before_t_gr_08() -> None:
    """replay records resource(``source_mode``)는 T-GR-08이 구현한다 — 그 전 게이트는 닫혀 있다."""
    assert frozenset() == SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS
    for operation_key in REPLAY_RECORDS_RESOURCES:
        config = geo_release_repo.run_config_for_dataset(operation_key, "any")
        assert (
            geo_release_repo.launch_blocked_reason(operation_key, config)
            == "replay_not_launchable_before_t_gr_08"
        )
    assert geo_release_repo.launch_blocked_reason("feature_place_khoa_beaches_job", None) is None


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
    not_ready = await geo_release_repo.complete_plan(
        migrated_session, plan.plan_id, sigungu_resolver=None
    )
    assert not_ready.kind == "not_ready"
    await _set_all_items(migrated_session, plan.plan_id, "done")

    first = await geo_release_repo.complete_plan(
        migrated_session, plan.plan_id, sigungu_resolver=None
    )
    assert first.kind == "sweep"
    swept = [item for item in first.plan.items if item.position in first.sweep_positions]
    assert [item.operation_key for item in swept] == [_FESTIVALS]
    assert (swept[0].state, swept[0].state_reason, swept[0].attempt_seq) == ("pending", "sweep", 2)

    await _set_all_items(migrated_session, plan.plan_id, "done")
    second = await geo_release_repo.complete_plan(
        migrated_session, plan.plan_id, sigungu_resolver=None
    )
    assert second.kind == "done"
    assert second.plan.residual_stale == 1  # 두 번째 sweep은 운영자 replan이다


async def test_completion_moves_a_same_sigungu_link_to_the_new_target(
    migrated_session: AsyncSession,
) -> None:
    """geo 릴리스로 ``sigungu_code``가 바뀐 행의 ``same_sigungu`` 링크가 새 target으로 옮겨진다."""
    # 반경(center_radius) target — 좌표는 그대로라 within_radius 링크는 남아야 한다.
    center = await upsert_poi_cache_target(
        migrated_session,
        external_system="geo-release-test",
        target_key="center",
        lon=126.9239,
        lat=37.5263,
        radius_km=1.0,
        scope_mode="center_radius",
    )
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

    # sigungu_by_radius target이 있는데 resolver가 없으면 쓰기 전에 거부한다(롤백 대신 명확한 오류).
    with pytest.raises(geo_release_repo.GeoReleaseResolverRequired):
        await geo_release_repo.complete_plan(
            migrated_session, plan.plan_id, sigungu_resolver=None
        )
    completed = await geo_release_repo.complete_plan(
        migrated_session, plan.plan_id, sigungu_resolver=resolver
    )

    assert completed.kind == "done"
    assert completed.linked_target_count == 3
    assert await _active_link_targets(migrated_session, feature_id) == {targets["gangnam"]}
    assert await _active_link_targets(
        migrated_session, feature_id, relation="within_radius"
    ) == {str(center.target_id)}


async def _active_link_targets(
    session: AsyncSession, feature_id: str, *, relation: str = "same_sigungu"
) -> set[str]:
    rows = await session.execute(
        text(
            "SELECT target_id::text FROM ops.poi_cache_target_feature_links "
            "WHERE feature_id = CAST(:id AS uuid) AND active AND relation = :relation"
        ),
        {"id": feature_id, "relation": relation},
    )
    return {str(row[0]) for row in rows}


async def test_replan_follows_the_latest_non_superseded_plan_after_a_rollback(
    migrated_session: AsyncSession,
) -> None:
    """A done → B planned → geo가 A로 롤백(잔여 0, B만 superseded) — 지금 서빙되는 A는 replan할 수
    있고, 닫힌 B는 409다(최신 행 그대로 보면 반대가 된다 — #1331 재리뷰 F1)."""
    bundle = await _festival("replan-rollback", _FakeReverse(_geo()))
    assert (await geo_release_repo.plan_geo_release(migrated_session, REF_B)).kind == (
        "baseline_recorded"
    )
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_B))  # A 기준 stale
    feature_id = await _feature_id(migrated_session, bundle)
    a_outcome = await geo_release_repo.plan_geo_release(migrated_session, REF_A)
    assert a_outcome.kind == "created"
    assert a_outcome.plan is not None
    a_plan = a_outcome.plan
    await upsert_stamps(migrated_session, current=REF_A, outcomes={feature_id: "called"})
    await _set_all_items(migrated_session, a_plan.plan_id, "done")
    done = await geo_release_repo.complete_plan(
        migrated_session, a_plan.plan_id, sigungu_resolver=None
    )
    assert done.kind == "done"
    b_outcome = await geo_release_repo.plan_geo_release(migrated_session, REF_B)
    assert b_outcome.kind == "created"
    assert b_outcome.plan is not None
    rollback = await geo_release_repo.plan_geo_release(migrated_session, REF_A)
    assert rollback.kind == "already_complete"
    assert rollback.superseded_plan_ids == (b_outcome.plan.plan_id,)

    replanned = await geo_release_repo.replan(migrated_session, a_plan.plan_id)
    assert (replanned.geo_data_token, replanned.state) == (TOKEN_A, "planned")
    with pytest.raises(geo_release_repo.GeoReleaseConflict) as refused:
        await geo_release_repo.replan(migrated_session, b_outcome.plan.plan_id)
    assert not isinstance(refused.value, geo_release_repo.GeoReleaseNotFound)


async def test_resolver_is_only_required_when_completion_reaches_the_link_resync(
    migrated_session: AsyncSession,
) -> None:
    """``not_ready``·``sweep``에서는 sigungu resolver를 묻지 않는다(#1331 재리뷰 F2)."""
    await upsert_poi_cache_target(
        migrated_session,
        external_system="geo-release-test",
        target_key="needs-resolver",
        lon=126.92,
        lat=37.52,
        radius_km=1.0,
        scope_mode="sigungu_by_radius",
    )
    bundle = await _festival("resolver-late", _FakeReverse(_geo()))
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_A))  # B 기준 stale → sweep
    plan = await _baseline_then(migrated_session, REF_B)
    not_ready = await geo_release_repo.complete_plan(
        migrated_session, plan.plan_id, sigungu_resolver=None
    )
    assert not_ready.kind == "not_ready"
    await _set_all_items(migrated_session, plan.plan_id, "done")
    sweep = await geo_release_repo.complete_plan(
        migrated_session, plan.plan_id, sigungu_resolver=None
    )
    assert sweep.kind == "sweep"
    await _set_all_items(migrated_session, plan.plan_id, "done")
    with pytest.raises(geo_release_repo.GeoReleaseResolverRequired):
        await geo_release_repo.complete_plan(
            migrated_session, plan.plan_id, sigungu_resolver=None
        )


def test_launch_gate_tolerates_malformed_run_config() -> None:
    """resource config가 dict가 아니어도 게이트가 죽지 않는다(#1331 재리뷰 F4)."""
    for config in (
        {"resources": "x"},
        {"resources": {"mois_license_records": "replay"}},
        {"resources": {"mois_license_records": {"config": "replay"}}},
    ):
        assert (
            geo_release_repo.launch_blocked_reason("feature_place_mois_licenses_job", config)
            is None
        )


# -- 센서 전이(T-GR-05) --------------------------------------------------------------------------


async def test_sensor_transitions_request_settle_and_requeue(
    migrated_session: AsyncSession,
) -> None:
    plan = await _baseline_then(migrated_session, REF_B)
    item = next(i for i in plan.items if i.state == "pending" and i.launch_blocked_reason is None)
    key = f"geo_release/{TOKEN_B}/1/{item.operation_key}/{item.position}/1"

    assert await geo_release_repo.mark_item_requested(
        migrated_session, plan.plan_id, item.position, attempt_seq=1, run_key=key
    )
    # 같은 attempt를 다시 요청하지 않는다(다른 tick이 먼저 냈다).
    assert not await geo_release_repo.mark_item_requested(
        migrated_session, plan.plan_id, item.position, attempt_seq=1, run_key=key
    )
    running = await geo_release_repo.get_geo_release_plan(migrated_session, plan.plan_id)
    assert running is not None
    assert running.state == "running"
    requested = next(i for i in running.items if i.position == item.position)
    assert (requested.state, requested.run_key) == ("requested", key)
    assert requested.requested_at is not None

    assert await geo_release_repo.requeue_item(migrated_session, plan.plan_id, item.position) == 2
    assert await geo_release_repo.mark_item_requested(
        migrated_session, plan.plan_id, item.position, attempt_seq=2, run_key=key + "-2"
    )
    assert await geo_release_repo.settle_item(
        migrated_session,
        plan.plan_id,
        item.position,
        state="failed",
        reason="run_failed",
        dagster_run_id="run-x",
    )
    after = await geo_release_repo.get_geo_release_plan(migrated_session, plan.plan_id)
    assert after is not None
    settled = next(i for i in after.items if i.position == item.position)
    assert (settled.state, settled.state_reason, settled.attempt_seq, settled.dagster_run_id) == (
        "failed",
        "run_failed",
        2,
        "run-x",
    )
    # 끝난 항목은 다시 끝내지 않는다.
    assert not await geo_release_repo.settle_item(
        migrated_session, plan.plan_id, item.position, state="done"
    )


async def test_superseding_a_plan_fails_its_in_flight_items(migrated_session: AsyncSession) -> None:
    """옛 계획의 ``requested`` 항목은 ``failed(superseded)`` — 진행 중 고아가 남지 않는다."""
    bundle = await _festival("supersede-in-flight", _FakeReverse(_geo()))
    assert (await geo_release_repo.plan_geo_release(migrated_session, REF_B)).kind == (
        "baseline_recorded"
    )
    await load_bundles(migrated_session, [bundle], geo=_ctx(REF_B))  # A 기준 stale
    created = await geo_release_repo.plan_geo_release(migrated_session, REF_A)
    assert created.plan is not None
    plan = created.plan
    item = next(i for i in plan.items if i.state == "pending" and i.launch_blocked_reason is None)
    assert await geo_release_repo.mark_item_requested(
        migrated_session, plan.plan_id, item.position, attempt_seq=1, run_key="k-a"
    )
    feature_id = await _feature_id(migrated_session, bundle)
    await upsert_stamps(migrated_session, current=REF_A, outcomes={feature_id: "called"})

    # geo가 B를 서빙한다 — 행은 A로 봉인돼 있어 B 계획이 생기고 A 계획은 닫힌다.
    outcome = await geo_release_repo.plan_geo_release(migrated_session, REF_B)
    assert outcome.kind == "created"
    assert outcome.superseded_plan_ids == (plan.plan_id,)
    closed = await geo_release_repo.get_geo_release_plan(migrated_session, plan.plan_id)
    assert closed is not None
    orphan = next(i for i in closed.items if i.position == item.position)
    assert (closed.state, orphan.state, orphan.state_reason) == (
        "superseded",
        "failed",
        "superseded",
    )

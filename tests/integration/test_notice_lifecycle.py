"""``test_notice_lifecycle`` — notice 사건 단위 identity 라이프사이클 (#632).

``close_notice_features``(특보 해제) / ``supersede_stale_notice_features``
(계보 중복 soft-delete + feed 소멸 닫기) / ``purge_expired_notices``(§9 보존) /
사용자 활성 read 필터(계보 latest만 + 종료 notice 숨김)를 testcontainers
PostGIS로 끝까지 검증한다. 정리 마이그레이션(0040)의 KREX 술어는
``supersede_stale_notice_features``와 동일 계보/최신 판정이라 본 테스트가
사실상 그 술어의 회귀 가드다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    NoticeDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import admin_feature_repo, feature_repo
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from kortravelmap.providers.kma import (
    kma_alert_notice_feature_id,
    weather_alert_lift_closures,
    weather_alerts_to_notice_bundles,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 7, 3, 12, 0, tzinfo=_KST)

_KREX = "python-krex-api"
_KREX_DS = "krex_traffic_notices"
_KREX_ET = "traffic_notice"


def _krex_notice_bundle(
    *,
    source_entity_id: str,
    raw_data: dict[str, Any],
    feature_suffix: str | None = None,
    lon: float = 127.1,
    lat: float = 37.4,
    valid_start: datetime | None = None,
) -> FeatureBundle:
    """계보 시뮬레이션용 KREX notice bundle.

    ``feature_suffix``를 주면 자연키에 suffix를 붙여 **다른 feature_id**를
    만든다 — 구세대(raw-hash/bjd-split) identity가 같은 계보(raw_data 단서)에
    공존하던 상황 재현.
    """
    key_for_id = f"{source_entity_id}::{feature_suffix}" if feature_suffix else source_entity_id
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.NOTICE.value,
        category="99000000",
        source_type=f"{_KREX}:{_KREX_DS}",
        source_natural_key=key_for_id,
    )
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    start = valid_start or _NOW
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.NOTICE,
        name=f"[테스트] 교통 공지 {source_entity_id[-12:]}",
        coord=Coordinate(lon=lon, lat=lat),
        address=Address(),
        category="99000000",
        marker_icon="danger",
        marker_color="P-15",
        detail=NoticeDetail(
            feature_id=feature_id,
            notice_type="traffic",
            severity=None,
            valid_start_time=start,
            valid_end_time=None,
            source_agency="한국도로공사",
            payload={"domain": "highway"},
        ),
    )
    source_record = SourceRecord(
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_name=feature.name,
        raw_address="테스트 노선",
        raw_data=raw_data,
        fetched_at=_NOW,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(feature=feature, source_record=source_record, source_link=source_link)


async def _pin_seen_at(session: AsyncSession, source_record_key: str, seen_at: datetime) -> None:
    await session.execute(
        text(
            "UPDATE provider_sync.source_records"
            " SET last_seen_at = :seen_at WHERE source_record_key = :key"
        ),
        {"seen_at": seen_at, "key": source_record_key},
    )


_CLUES = {
    "occurred_date": "2026.07.03",
    "occurred_time": "07:25:43",
    "route_no": "0550",
    "direction": "부산방향",
    "point_name": "남제천(272.5k)",
    "incident_type_code": "03",
}
_LINEAGE = "2026.07.03::07:25:43::0550::부산방향::남제천(272.5k)::03"


async def _seed_dup_lineage(
    session: AsyncSession,
) -> tuple[FeatureBundle, FeatureBundle]:
    """같은 계보의 서로 다른 entity 2개를 심는다 (신세대가 latest).

    ADR-063 이후 같은 ``source_entity_id``의 payload 이력은 하나의 entity/current
    관측으로 접힌다. 따라서 legacy identity 중복은 raw 계보 단서는 같되 entity
    identity가 다른 두 source로 재현해야 한다.
    """
    old_gen = _krex_notice_bundle(
        source_entity_id=f"legacy::{_LINEAGE}",
        raw_data={**_CLUES, "gen": "old"},
        feature_suffix="oldgen",
    )
    new_gen = _krex_notice_bundle(
        source_entity_id=_LINEAGE,
        raw_data={**_CLUES, "gen": "new"},
    )
    assert old_gen.feature.feature_id != new_gen.feature.feature_id
    assert old_gen.source_record.source_entity_id != new_gen.source_record.source_entity_id
    await feature_repo.load_bundles(session, [old_gen, new_gen])
    await _pin_seen_at(session, old_gen.source_record.source_record_key, _NOW - timedelta(hours=2))
    await _pin_seen_at(session, new_gen.source_record.source_record_key, _NOW)
    return old_gen, new_gen


async def _seed_split_max_tuple_lineage(
    session: AsyncSession,
) -> tuple[FeatureBundle, FeatureBundle]:
    """서로 다른 row에서 ``max(seen_at)``/``max(source_record_key)``가 나오는 계보.

    한 feature에 같은 계보의 current source entity가 여러 개 연결될 수 있다. 낮은
    record key에는 최신 시각을, 높은 record key에는 과거 시각을 주고, 두 key 사이의
    최신 row를 다른 feature에 둔다. 합성 max tuple은 존재하지 않으며 실제
    lexicographic winner는 가운데 key의 feature다.
    """
    bundles = [
        _krex_notice_bundle(
            source_entity_id=f"split-max::{suffix}",
            raw_data={**_CLUES, "gen": suffix},
            feature_suffix=suffix,
        )
        for suffix in ("a", "b", "c")
    ]
    await feature_repo.load_bundles(session, bundles)
    low, middle, high = sorted(
        bundles,
        key=lambda bundle: bundle.source_record.source_record_key,
    )

    # low/high entity를 한 feature에 묶는다. high의 원 feature는 감사 이력으로
    # soft-delete해 후보에서 제외하고, middle feature만 실제 최신 경쟁자로 둔다.
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method,
                confidence, is_primary_source, created_at
            )
            SELECT
                :feature_id, source_entity_key, 'primary',
                'identity_migration', 100, true, :seen_at
            FROM provider_sync.source_records
            WHERE source_record_key = :source_record_key
            """
        ),
        {
            "feature_id": low.feature.feature_id,
            "seen_at": _NOW,
            "source_record_key": high.source_record.source_record_key,
        },
    )
    await session.execute(
        text(
            "UPDATE feature.features"
            " SET status = 'inactive', deleted_at = :deleted_at"
            " WHERE feature_id = :feature_id"
        ),
        {
            "deleted_at": _NOW,
            "feature_id": high.feature.feature_id,
        },
    )
    await _pin_seen_at(session, low.source_record.source_record_key, _NOW)
    await _pin_seen_at(session, middle.source_record.source_record_key, _NOW)
    await _pin_seen_at(
        session,
        high.source_record.source_record_key,
        _NOW - timedelta(hours=1),
    )
    await session.flush()
    return low, middle


async def _feature_state(
    session: AsyncSession, feature_id: str
) -> tuple[str, datetime | None, Any]:
    row = (
        await session.execute(
            text(
                "SELECT status, deleted_at, detail ->> 'valid_end_time' AS valid_end"
                " FROM feature.features WHERE feature_id = :fid"
            ),
            {"fid": feature_id},
        )
    ).one()
    return row.status, row.deleted_at, row.valid_end


async def test_supersede_soft_deletes_non_latest_per_lineage(
    migrated_session: AsyncSession,
) -> None:
    old_gen, new_gen = await _seed_dup_lineage(migrated_session)

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )

    assert result.superseded == 1
    assert result.closed == 0
    status, deleted_at, _ = await _feature_state(migrated_session, old_gen.feature.feature_id)
    assert status == "inactive"
    assert deleted_at is not None
    status, deleted_at, valid_end = await _feature_state(
        migrated_session, new_gen.feature.feature_id
    )
    assert deleted_at is None
    assert valid_end is None  # 계보가 살아 있으면 닫지 않는다.


async def test_reconcile_exact_tie_prefers_current_identity(
    migrated_session: AsyncSession,
) -> None:
    """seen/source record 동률에도 현 사건 identity feature가 남는다.

    identity 이행 중 하나의 current source entity가 구/신 feature 양쪽에
    primary link로 남은 실제 형태를 재현한다. ``feature_id ASC``만으로
    고르면 구세대가 이기도록 구 ID를 작게 정해 canonical 판정을 검증한다.
    """
    current = _krex_notice_bundle(
        source_entity_id=_LINEAGE,
        raw_data={**_CLUES, "gen": "current"},
    )
    await feature_repo.load_bundles(migrated_session, [current])
    legacy_feature_id = "f_global_n_0000000000000000"
    assert legacy_feature_id < current.feature.feature_id
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, coord_precision_digits,
                marker_icon, marker_color, detail, status
            )
            SELECT
                :legacy_feature_id, kind, name, category, coord,
                coord_precision_digits, marker_icon, marker_color, detail, status
            FROM feature.features
            WHERE feature_id = :current_feature_id
            """
        ),
        {
            "legacy_feature_id": legacy_feature_id,
            "current_feature_id": current.feature.feature_id,
        },
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method,
                confidence, is_primary_source, created_at
            )
            SELECT
                :legacy_feature_id, source_entity_key, 'primary',
                'identity_migration', 100, true, :seen_at
            FROM provider_sync.source_records
            WHERE source_record_key = :source_record_key
            """
        ),
        {
            "legacy_feature_id": legacy_feature_id,
            "seen_at": _NOW,
            "source_record_key": current.source_record.source_record_key,
        },
    )
    await migrated_session.flush()

    # write reconcile 전 read 필터도 동일 canonical 1건만 노출한다.
    rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=127.0,
        min_lat=37.0,
        max_lon=127.5,
        max_lat=37.8,
        kinds=["notice"],
    )
    assert {row["feature_id"] for row in rows} == {current.feature.feature_id}

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )
    assert result.superseded == 1
    assert (await _feature_state(migrated_session, legacy_feature_id))[1] is not None
    assert (await _feature_state(migrated_session, current.feature.feature_id))[1] is None

    # 같은 snapshot/reconcile을 다시 적용해도 winner가 바뀌지 않는다.
    again = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )
    assert again.superseded == 0
    assert (await _feature_state(migrated_session, current.feature.feature_id))[1] is None


async def test_actual_lexicographic_notice_row_wins_across_reads_and_reconcile(
    migrated_session: AsyncSession,
) -> None:
    """분리된 max 값으로 존재하지 않는 tuple을 만들지 않고 실제 row 하나를 고른다."""
    synthesized_winner, actual_winner = await _seed_split_max_tuple_lineage(migrated_session)
    expected_ids = {actual_winner.feature.feature_id}
    candidate_ids = {
        synthesized_winner.feature.feature_id,
        actual_winner.feature.feature_id,
    }
    await migrated_session.execute(
        text(
            "UPDATE feature.features"
            " SET sido_code = '11', name = '[테스트] 동일 교통 공지'"
            " WHERE feature_id = ANY(CAST(:feature_ids AS text[]))"
        ),
        {"feature_ids": list(candidate_ids)},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, geom, status
            ) VALUES (
                'notice-split-max-area', 'area', '공지 lexicographic 테스트 영역',
                '03000000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(127.1, 37.4), 4326
                ),
                x_extension.ST_SetSRID(
                    x_extension.ST_GeomFromText(
                        'POLYGON((127.0 37.3,127.2 37.3,127.2 37.5,'
                        '127.0 37.5,127.0 37.3))'
                    ),
                    4326
                ),
                'active'
            )
            """
        )
    )
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="notice-test",
        target_key="split-max-tuple",
        lon=127.1,
        lat=37.4,
        radius_km=10.0,
    )
    await migrated_session.flush()

    bbox = (127.0, 37.3, 127.2, 37.5)
    for include_geometry in (False, True):
        rows = await feature_repo.features_in_bbox(
            migrated_session,
            min_lon=bbox[0],
            min_lat=bbox[1],
            max_lon=bbox[2],
            max_lat=bbox[3],
            kinds=["notice"],
            include_geometry=include_geometry,
        )
        assert {row["feature_id"] for row in rows} == expected_ids

    search_by_bbox = await feature_repo.search_features(
        migrated_session,
        bbox=bbox,
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in search_by_bbox.items} == expected_ids
    assert search_by_bbox.total_count == 1

    search_by_name = await feature_repo.search_features(
        migrated_session,
        q="[테스트] 동일 교통 공지",
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in search_by_name.items} == expected_ids
    assert search_by_name.total_count == 1

    nearby = await feature_repo.features_nearby(
        migrated_session,
        lon=127.1,
        lat=37.4,
        radius_m=20_000,
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in nearby.items} == expected_ids

    nearby_target = await feature_repo.features_nearby_poi_cache_target(
        migrated_session,
        target_id=target.target_id,
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in nearby_target.items} == expected_ids

    contained = await feature_repo.features_contained_in_area(
        migrated_session,
        feature_id="notice-split-max-area",
        kinds=["notice"],
        limit=20,
    )
    assert {row["feature_id"] for row in contained} == expected_ids

    clusters = await feature_repo.cluster_features_in_bbox(
        migrated_session,
        min_lon=bbox[0],
        min_lat=bbox[1],
        max_lon=bbox[2],
        max_lat=bbox[3],
        cluster_unit="sido",
        kinds=["notice"],
    )
    assert clusters == [
        {
            "cluster_key": "11",
            "feature_count": 1,
            "lon": 127.1,
            "lat": 37.4,
        }
    ]
    counts = await feature_repo.category_feature_counts(migrated_session)
    assert counts.get("99000000", 0) == 1

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
    )
    assert result.superseded == 1
    assert (await _feature_state(migrated_session, actual_winner.feature.feature_id))[1] is None
    assert (await _feature_state(migrated_session, synthesized_winner.feature.feature_id))[
        1
    ] is not None


async def test_supersede_closes_lineage_missing_from_feed(
    migrated_session: AsyncSession,
) -> None:
    _, new_gen = await _seed_dup_lineage(migrated_session)
    closed_at = _NOW + timedelta(minutes=10)

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={"다른::계보"},  # 이번 feed에 이 계보 없음.
        closed_at=closed_at,
    )

    assert result.superseded == 1  # 구세대는 여전히 중복 정리.
    assert result.closed == 1
    assert result.reopened == 0
    _, deleted_at, valid_end = await _feature_state(migrated_session, new_gen.feature.feature_id)
    assert deleted_at is None  # latest는 soft-delete가 아니라 '종료'.
    assert valid_end is not None
    assert datetime.fromisoformat(valid_end) == closed_at

    # 종료됐던 계보가 feed에 다시 나타나면 active로 self-heal한다.
    reappeared = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        closed_at=closed_at + timedelta(minutes=10),
    )
    assert reappeared.superseded == 0
    assert reappeared.closed == 0
    assert reappeared.reopened == 1
    _, deleted_at, valid_end = await _feature_state(migrated_session, new_gen.feature.feature_id)
    assert deleted_at is None
    assert valid_end is None

    # 이미 열린 상태에서 같은 snapshot을 재적용하면 no-op이다.
    again = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        closed_at=closed_at + timedelta(minutes=20),
    )
    assert again.closed == 0
    assert again.reopened == 0


async def test_close_notice_features_kma_lift_roundtrip(
    migrated_session: AsyncSession,
) -> None:
    class _Region:
        region_code = "stn:108"
        region_name = "전국"

    class _Alert:
        alert_id = "108:202607030600:20"
        alert_type = "폭염"  # 실제 경로처럼 현상 토큰(정규화 가능 값).
        level = "주의보"
        title = "폭염주의보 발표"
        description = None
        issued_at = _NOW
        effective_from = None
        effective_until = None
        source_agency = "기상청"
        regions = [_Region()]

    bundles = weather_alerts_to_notice_bundles([_Alert()], fetched_at=_NOW)
    assert len(bundles) == 1
    await feature_repo.load_bundles(migrated_session, bundles)
    feature_id = kma_alert_notice_feature_id("stn:108", "폭염")
    assert bundles[0].feature.feature_id == feature_id

    class _Lift(_Alert):
        alert_id = "108:202607031800:25"
        title = "폭염주의보 해제"
        issued_at = _NOW + timedelta(hours=6)

    closures = weather_alert_lift_closures([_Lift()])
    closed = await feature_repo.close_notice_features(
        migrated_session,
        closures={c.feature_id: c.closed_at for c in closures},
    )
    assert closed == 1
    _, deleted_at, valid_end = await _feature_state(migrated_session, feature_id)
    assert deleted_at is None
    assert valid_end is not None
    assert datetime.fromisoformat(valid_end) == _NOW + timedelta(hours=6)

    # 이미 닫힌 feature 재닫기는 no-op.
    assert (
        await feature_repo.close_notice_features(
            migrated_session,
            closures={feature_id: _NOW + timedelta(hours=7)},
        )
        == 0
    )


async def test_close_skips_reannounced_feature(
    migrated_session: AsyncSession,
) -> None:
    """해제 시각보다 나중에 재발표된 feature는 닫지 않는다 (순서 역전 방어)."""
    bundle = _krex_notice_bundle(
        source_entity_id="reannounce::계보",
        raw_data={"occurred_date": "2026.07.03"},
        valid_start=_NOW,  # 발표(=valid_start)가 해제 시각보다 나중.
    )
    await feature_repo.load_bundles(migrated_session, [bundle])
    closed = await feature_repo.close_notice_features(
        migrated_session,
        closures={bundle.feature.feature_id: _NOW - timedelta(hours=1)},
    )
    assert closed == 0


async def test_bbox_read_hides_non_latest_and_ended(
    migrated_session: AsyncSession,
) -> None:
    old_gen, new_gen = await _seed_dup_lineage(migrated_session)
    bbox = {
        "min_lon": 127.0,
        "min_lat": 37.0,
        "max_lon": 127.5,
        "max_lat": 37.8,
        "limit": 50,
    }
    rows = await feature_repo.features_in_bbox(migrated_session, kinds=["notice"], **bbox)
    ids = {row["feature_id"] for row in rows}
    # 계보 latest만 — 구세대는 soft-delete 전이라도 read에서 숨는다.
    assert new_gen.feature.feature_id in ids
    assert old_gen.feature.feature_id not in ids

    # 종료된 notice는 숨는다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET detail = jsonb_set("
            " detail, '{valid_end_time}', to_jsonb(CAST(:t AS text)), true)"
            " WHERE feature_id = :fid"
        ),
        {"t": (_NOW - timedelta(hours=1)).isoformat(), "fid": new_gen.feature.feature_id},
    )
    rows = await feature_repo.features_in_bbox(migrated_session, kinds=["notice"], **bbox)
    ids = {row["feature_id"] for row in rows}
    assert new_gen.feature.feature_id not in ids


async def test_public_active_reads_share_latest_and_ended_notice_filter(
    migrated_session: AsyncSession,
) -> None:
    """legacy/current 중복과 종료 notice를 모든 사용자 목록·집계에서 동일 제외한다.

    admin 감사 목록은 원천 이력 추적을 위해 세 feature를 모두 유지한다.
    """
    old_gen, new_gen = await _seed_dup_lineage(migrated_session)
    ended = _krex_notice_bundle(
        source_entity_id="public-read::ended",
        raw_data={
            "occurred_date": "2026.07.03",
            "occurred_time": "08:10:00",
            "route_no": "0010",
            "direction": "서울방향",
            "point_name": "종료지점",
            "incident_type_code": "03",
        },
        lon=127.11,
        lat=37.41,
    )
    await feature_repo.load_bundles(migrated_session, [ended])
    all_ids = {
        old_gen.feature.feature_id,
        new_gen.feature.feature_id,
        ended.feature.feature_id,
    }
    expected_ids = {new_gen.feature.feature_id}
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET sido_code = '11', detail = CASE"
            " WHEN feature_id = :ended_id THEN jsonb_set("
            " detail, '{valid_end_time}', to_jsonb(CAST(:ended_at AS text)), true)"
            " ELSE detail END WHERE feature_id = ANY(CAST(:feature_ids AS text[]))"
        ),
        {
            "ended_id": ended.feature.feature_id,
            "ended_at": (_NOW - timedelta(hours=1)).isoformat(),
            "feature_ids": list(all_ids),
        },
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, geom, status
            ) VALUES (
                'notice-public-read-area', 'area', '공지 조회 테스트 영역', '03000000',
                x_extension.ST_SetSRID(
                    x_extension.ST_MakePoint(127.1, 37.4), 4326
                ),
                x_extension.ST_SetSRID(
                    x_extension.ST_GeomFromText(
                        'POLYGON((127.0 37.3,127.2 37.3,127.2 37.5,'
                        '127.0 37.5,127.0 37.3))'
                    ),
                    4326
                ),
                'active'
            )
            """
        )
    )
    await migrated_session.flush()

    bbox = (127.0, 37.3, 127.2, 37.5)
    bbox_rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=bbox[0],
        min_lat=bbox[1],
        max_lon=bbox[2],
        max_lat=bbox[3],
        kinds=["notice"],
    )
    assert {row["feature_id"] for row in bbox_rows} == expected_ids

    search_page = await feature_repo.search_features(
        migrated_session,
        bbox=bbox,
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in search_page.items} == expected_ids
    assert search_page.total_count == 1

    nearby_page = await feature_repo.features_nearby(
        migrated_session,
        lon=127.1,
        lat=37.4,
        radius_m=20_000,
        kinds=["notice"],
        limit=20,
    )
    assert {item.feature_id for item in nearby_page.items} == expected_ids

    contained = await feature_repo.features_contained_in_area(
        migrated_session,
        feature_id="notice-public-read-area",
        kinds=["notice"],
        limit=20,
    )
    assert {row["feature_id"] for row in contained} == expected_ids

    clusters = await feature_repo.cluster_features_in_bbox(
        migrated_session,
        min_lon=bbox[0],
        min_lat=bbox[1],
        max_lon=bbox[2],
        max_lat=bbox[3],
        cluster_unit="sido",
        kinds=["notice"],
    )
    assert clusters == [
        {
            "cluster_key": "11",
            "feature_count": 1,
            "lon": 127.1,
            "lat": 37.4,
        }
    ]

    counts = await feature_repo.category_feature_counts(migrated_session)
    assert counts.get("99000000", 0) == 1

    direct_public_ids = await feature_repo.public_active_notice_feature_ids(
        migrated_session,
        list(all_ids),
    )
    assert direct_public_ids == expected_ids

    audit_page = await admin_feature_repo.list_admin_features(
        migrated_session,
        kinds=["notice"],
        statuses=None,
        include_ended=True,
        page_size=100,
    )
    assert all_ids <= {item.feature_id for item in audit_page.items}


async def test_purge_expired_notices(migrated_session: AsyncSession) -> None:
    stale = _krex_notice_bundle(
        source_entity_id="purge::stale",
        raw_data={"occurred_date": "2025.06.01"},
        valid_start=_NOW - timedelta(days=400),
    )
    fresh = _krex_notice_bundle(
        source_entity_id="purge::fresh",
        raw_data={"occurred_date": "2026.07.01"},
        valid_start=_NOW - timedelta(days=2),
    )
    await feature_repo.load_bundles(migrated_session, [stale, fresh])

    purged = await feature_repo.purge_expired_notices(migrated_session)

    assert purged == 1
    status, deleted_at, _ = await _feature_state(migrated_session, stale.feature.feature_id)
    assert status == "inactive"
    assert deleted_at is not None
    _, deleted_at, _ = await _feature_state(migrated_session, fresh.feature.feature_id)
    assert deleted_at is None


async def test_read_paths_exclude_ended_notice_by_default(
    migrated_session: AsyncSession,
) -> None:
    """수집 feed에서 사라져 종료된(valid_end_time) notice는 목록·카운트 등 read에서
    기본 제외되고(사용자 요구: 수집에 없는 notice는 과거 자료로 노출하지 않음),
    infra raw by-id와 admin 감사 목록에만 남고 public by-id에서는 숨는다.

    (bbox/search/nearby/area/cluster/counts/admin이 모두 동일 ``valid_end_time``
    술어를 공유하므로 counts·admin·by-id로 대표 검증한다 — bbox는 별도 테스트.)
    """
    active = _krex_notice_bundle(
        source_entity_id="read::active",
        raw_data={"occurred_date": "2026.07.03", "route_no": "0010", "point_name": "가"},
    )
    ended = _krex_notice_bundle(
        source_entity_id="read::ended",
        raw_data={"occurred_date": "2026.07.03", "route_no": "0020", "point_name": "나"},
    )
    await feature_repo.load_bundles(migrated_session, [active, ended])
    active_id = active.feature.feature_id
    ended_id = ended.feature.feature_id
    category = active.feature.category

    counts_before = dict(await feature_repo.category_feature_counts(migrated_session))
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET detail = jsonb_set("
            " detail, '{valid_end_time}', to_jsonb(CAST(:t AS text)), true)"
            " WHERE feature_id = :fid"
        ),
        {"t": (_NOW - timedelta(hours=1)).isoformat(), "fid": ended_id},
    )

    # category_feature_counts: 종료 notice는 카운트에서 빠진다.
    counts_after = dict(await feature_repo.category_feature_counts(migrated_session))
    assert counts_after.get(category, 0) == counts_before.get(category, 0) - 1

    # admin 목록: 기본 제외.
    default_page = await admin_feature_repo.list_admin_features(
        migrated_session, kinds=["notice"], statuses=None, page_size=100
    )
    default_ids = {item.feature_id for item in default_page.items}
    assert active_id in default_ids
    assert ended_id not in default_ids

    # admin 목록: include_ended=True면 감사용으로 다시 포함.
    audit_page = await admin_feature_repo.list_admin_features(
        migrated_session,
        kinds=["notice"],
        statuses=None,
        include_ended=True,
        page_size=100,
    )
    assert ended_id in {item.feature_id for item in audit_page.items}

    # infra raw by-id는 admin/감사를 위해 종료돼도 반환한다.
    row = await feature_repo.get_feature_row(migrated_session, ended_id)
    assert row is not None
    assert row["feature_id"] == ended_id
    # public 단건/batch가 사용하는 필터는 ID 직접 조회 우회를 허용하지 않는다.
    assert await feature_repo.public_active_notice_feature_ids(
        migrated_session,
        [active_id, ended_id],
    ) == {active_id}


async def test_reconcile_empty_snapshot_closes_all_active_lineages(
    migrated_session: AsyncSession,
) -> None:
    """성공한 빈 snapshot은 모든 latest notice가 feed에서 소멸했다는 뜻이다."""
    a = _krex_notice_bundle(
        source_entity_id="empty::a",
        raw_data={"occurred_date": "2026.07.03", "route_no": "0030"},
    )
    b = _krex_notice_bundle(
        source_entity_id="empty::b",
        raw_data={"occurred_date": "2026.07.02", "route_no": "0040"},
    )
    await feature_repo.load_bundles(migrated_session, [a, b])

    result = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys=set(),
        closed_at=_NOW + timedelta(minutes=10),
    )

    assert result.closed == 2
    assert result.reopened == 0
    for bundle in (a, b):
        status, deleted_at, valid_end = await _feature_state(
            migrated_session, bundle.feature.feature_id
        )
        assert valid_end is not None
        assert deleted_at is None
        assert status == "active"

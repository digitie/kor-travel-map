"""``test_notice_lifecycle`` — notice 사건 단위 identity 라이프사이클 (#632).

``close_notice_features``(특보 해제) / ``supersede_stale_notice_features``
(계보 중복 soft-delete + feed 소멸 닫기) / ``purge_expired_notices``(§9 보존)
/ bbox read 필터(계보 latest만 + 종료 notice 숨김)를 testcontainers PostGIS로
끝까지 검증한다. 정리 마이그레이션(0040)의 KREX 술어는
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
    """같은 계보에 구세대/신세대 feature 2개를 심는다 (신세대가 latest)."""
    old_gen = _krex_notice_bundle(
        source_entity_id=_LINEAGE,
        raw_data={**_CLUES, "gen": "old"},
        feature_suffix="oldgen",
    )
    new_gen = _krex_notice_bundle(
        source_entity_id=_LINEAGE,
        raw_data={**_CLUES, "gen": "new"},
    )
    assert old_gen.feature.feature_id != new_gen.feature.feature_id
    await feature_repo.load_bundles(session, [old_gen, new_gen])
    await _pin_seen_at(session, old_gen.source_record.source_record_key, _NOW - timedelta(hours=2))
    await _pin_seen_at(session, new_gen.source_record.source_record_key, _NOW)
    return old_gen, new_gen


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
    _, deleted_at, valid_end = await _feature_state(migrated_session, new_gen.feature.feature_id)
    assert deleted_at is None  # latest는 soft-delete가 아니라 '종료'.
    assert valid_end is not None
    assert datetime.fromisoformat(valid_end) == closed_at

    # 계보가 feed에 있으면 닫지 않는다 (idempotent 재실행 겸 검증).
    again = await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider=_KREX,
        dataset_key=_KREX_DS,
        source_entity_type=_KREX_ET,
        active_lineage_keys={_LINEAGE},
        closed_at=closed_at + timedelta(minutes=10),
    )
    assert again.superseded == 0
    assert again.closed == 0  # 이미 닫힌 feature는 다시 닫지 않는다.


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
    by-id 직접 조회로만 노출된다. admin 목록은 include_ended=True면 감사용으로 포함.

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

    # by-id 직접 조회는 종료돼도 반환한다(직접 참조·상세).
    row = await feature_repo.get_feature_row(migrated_session, ended_id)
    assert row is not None
    assert row["feature_id"] == ended_id


async def test_reconcile_empty_feed_closes_nothing(
    migrated_session: AsyncSession,
) -> None:
    """빈/실패 feed 안전장치: asset은 fetch가 0건이면 ``active_lineage_keys=None``을
    넘긴다. 이 경우 reconcile은 어떤 notice의 ``valid_end_time``도 채우지 않는다 —
    장애 poll에서 전체 notice가 통째로 API에서 사라지는 사고를 방지한다.
    """
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
        active_lineage_keys=None,  # 빈 feed → asset이 None을 넘김
        closed_at=None,
    )

    assert result.closed == 0
    for bundle in (a, b):
        status, deleted_at, valid_end = await _feature_state(
            migrated_session, bundle.feature.feature_id
        )
        assert valid_end is None, "빈 feed에서 notice가 닫히면 안 된다"
        assert deleted_at is None
        assert status == "active"

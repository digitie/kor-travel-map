"""``test_feature_repo_load`` — ``infra/feature_repo`` 적재 경로 (testcontainers).

``FeatureBundle`` → ``feature_repo.load_bundles`` → PostGIS 적재 → 재조회 검증.
첫 실 DB write 경로(ADR-004 raw SQL upsert)를 testcontainer에서 끝까지 검증한다.

검증: ① upsert 카운트(신규/갱신) ② idempotent 재적재(ON CONFLICT, §4.4)
③ coord_5179 STORED generated(ADR-012) ④ source_link FK ⑤ source_record 이력
보존(DO NOTHING) ⑥ get_feature_row round-trip.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    Feature,
    FeatureBundle,
    FeatureKind,
    NoticeDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import feature_repo
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 (좌표 있는 케이스).

    provider 실모델 ``PublicCulturalFestival`` 필드명 (ADR-044 재정렬, #374).
    """

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


async def _bundle(seed: str = "FEST-REPO-001"):
    # 자연키는 name::address 파생(#374) — 이름은 동일하게 두고(검색 테스트
    # 전제) 주소에 seed를 넣어 feature를 구분한다.
    item = _Festival(
        fstvl_nm="서울 봄꽃 축제",
        opar="여의도공원",
        fstvl_start_date=date(2026, 4, 5),
        fstvl_end_date=date(2026, 4, 12),
        fstvl_co="봄꽃 축제 상세.",
        mnnst_nm="영등포구청",
        phone_number="02-2670-3114",
        rdnmadr=f"서울특별시 영등포구 여의공원로 120 ({seed})",
        lnmadr="서울특별시 영등포구 여의도동 8",
        latitude=37.5263,
        longitude=126.9239,
        reference_date=date(2026, 3, 1),
        instt_nm="서울특별시 영등포구",
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
        )
    )[0]


def _first_probe_notice_bundle(
    *,
    message: str,
    fetched_at: datetime,
) -> FeatureBundle:
    raw_data = {
        "natural_key": "2026.06.01::0010::서울방향::천안분기점::3",
        "message": message,
    }
    raw_payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        source_entity_id=raw_data["natural_key"],
        raw_payload_hash=raw_payload_hash,
    )
    feature_id = "f_global_n_first_probe_notice"
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.NOTICE,
        name="[경부고속도로] 공사",
        address=Address(),
        category="99000000",
        marker_icon="roadblock",
        marker_color="P-13",
        detail=NoticeDetail(
            feature_id=feature_id,
            notice_type="roadwork",
            valid_start_time=fetched_at,
            source_agency="한국도로공사",
            payload={
                "domain": "highway",
                "description": message,
                "valid_start_origin": "first_probe",
            },
        ),
        created_at=fetched_at,
        updated_at=fetched_at,
    )
    source_record = SourceRecord(
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        source_entity_id=raw_data["natural_key"],
        raw_payload_hash=raw_payload_hash,
        raw_name=message,
        raw_data=raw_data,
        fetched_at=fetched_at,
        imported_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
        created_at=fetched_at,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


async def test_load_bundle_inserts_and_roundtrips(
    migrated_session: AsyncSession,
) -> None:
    bundle = await _bundle()
    result = await feature_repo.load_bundle(migrated_session, bundle)
    await migrated_session.flush()

    assert result.bundles_total == 1
    assert result.features_inserted == 1
    assert result.features_updated == 0
    assert result.source_records_inserted == 1
    assert result.source_links_inserted == 1

    # get_feature_row round-trip
    row = await feature_repo.get_feature_row(
        migrated_session, bundle.feature.feature_id
    )
    assert row is not None
    assert row["kind"] == "event"
    assert row["name"] == bundle.feature.name
    assert isinstance(row["detail"], dict)
    assert row["detail"]  # detail JSONB 비어있지 않음

    # coord_5179 STORED generated (ADR-012) — 좌표 4326 일치
    assert row["coord_5179_srid"] == 5179
    assert row["coord_precision_digits"] == bundle.feature.coord_precision_digits == 6
    assert abs(float(row["lon"]) - float(bundle.feature.coord.lon)) < 1e-6
    assert abs(float(row["lat"]) - float(bundle.feature.coord.lat)) < 1e-6

    # source_link FK 정합
    link = (
        await migrated_session.execute(
            text(
                "SELECT source_record_key, is_primary_source "
                "FROM provider_sync.source_links WHERE feature_id = :fid"
            ),
            {"fid": bundle.feature.feature_id},
        )
    ).one()
    assert link.source_record_key == bundle.source_record.source_record_key


async def test_load_bundle_is_idempotent(migrated_session: AsyncSession) -> None:
    bundle = await _bundle("FEST-REPO-IDEM")

    first = await feature_repo.load_bundle(migrated_session, bundle)
    await migrated_session.flush()
    assert first.features_inserted == 1
    assert first.source_records_inserted == 1

    before = (
        await migrated_session.execute(
            text(
                "SELECT last_seen_at FROM provider_sync.source_records "
                "WHERE source_record_key = :k"
            ),
            {"k": bundle.source_record.source_record_key},
        )
    ).scalar_one()

    await asyncio.sleep(0.01)
    mutated = bundle.model_copy(
        update={
            "feature": bundle.feature.model_copy(
                update={"name": "중복 재수집에서 바뀌면 안 되는 이름"}
            )
        }
    )

    # 동일 source_record_key 재적재 — 원문/feature 내용은 건드리지 않고 last_seen만 갱신.
    second = await feature_repo.load_bundle(migrated_session, mutated)
    await migrated_session.flush()
    assert second.features_inserted == 0
    assert second.features_updated == 0
    assert second.source_records_inserted == 0
    assert second.source_links_updated == 1

    # 각 테이블 1행씩만 존재
    fcount = (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.features WHERE feature_id = :fid"),
            {"fid": bundle.feature.feature_id},
        )
    ).scalar_one()
    assert fcount == 1
    feature_name = (
        await migrated_session.execute(
            text("SELECT name FROM feature.features WHERE feature_id = :fid"),
            {"fid": bundle.feature.feature_id},
        )
    ).scalar_one()
    assert feature_name == bundle.feature.name
    source_row = (
        await migrated_session.execute(
            text(
                "SELECT count(*) AS count, max(last_seen_at) AS last_seen_at "
                "FROM provider_sync.source_records "
                "WHERE source_record_key = :k"
            ),
            {"k": bundle.source_record.source_record_key},
        )
    ).mappings().one()
    assert source_row["count"] == 1
    assert source_row["last_seen_at"] > before


async def test_notice_first_probe_start_time_is_preserved_on_payload_update(
    migrated_session: AsyncSession,
) -> None:
    first_seen = datetime(2026, 6, 1, 9, 0, tzinfo=_KST)
    second_seen = datetime(2026, 6, 1, 9, 5, tzinfo=_KST)
    first = _first_probe_notice_bundle(
        message="공사 시작",
        fetched_at=first_seen,
    )
    second = _first_probe_notice_bundle(
        message="공사 내용 수정",
        fetched_at=second_seen,
    )

    await feature_repo.load_bundle(migrated_session, first)
    await feature_repo.load_bundle(migrated_session, second)
    await migrated_session.flush()

    detail = (
        await migrated_session.execute(
            text("SELECT detail FROM feature.features WHERE feature_id = :fid"),
            {"fid": first.feature.feature_id},
        )
    ).scalar_one()

    assert detail["valid_start_time"] == first_seen.isoformat()
    assert detail["payload"]["description"] == "공사 내용 수정"
    assert detail["payload"]["valid_start_origin"] == "first_probe"


async def test_load_bundles_aggregates_counts(
    migrated_session: AsyncSession,
) -> None:
    bundles = [await _bundle("FEST-REPO-A"), await _bundle("FEST-REPO-B")]
    result = await feature_repo.load_bundles(migrated_session, bundles)
    await migrated_session.flush()

    assert result.bundles_total == 2
    assert result.features_inserted == 2
    assert result.source_records_inserted == 2
    assert result.source_links_inserted == 2


async def test_get_feature_row_missing_returns_none(
    migrated_session: AsyncSession,
) -> None:
    row = await feature_repo.get_feature_row(migrated_session, "does-not-exist")
    assert row is None


async def test_features_in_bbox_finds_loaded_feature(
    migrated_session: AsyncSession,
) -> None:
    bundle = await _bundle("FEST-BBOX")
    await feature_repo.load_bundle(migrated_session, bundle)
    await migrated_session.flush()

    lon = float(bundle.feature.coord.lon)
    lat = float(bundle.feature.coord.lat)

    # feature를 포함하는 bbox
    rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=lon - 0.1, min_lat=lat - 0.1,
        max_lon=lon + 0.1, max_lat=lat + 0.1,
    )
    ids = {r["feature_id"] for r in rows}
    assert bundle.feature.feature_id in ids
    hit = next(r for r in rows if r["feature_id"] == bundle.feature.feature_id)
    assert abs(float(hit["lon"]) - lon) < 1e-6
    assert hit["kind"] == "event"

    # kind 필터 mismatch면 제외
    rows_place = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=lon - 0.1, min_lat=lat - 0.1,
        max_lon=lon + 0.1, max_lat=lat + 0.1,
        kinds=["place"],
    )
    assert bundle.feature.feature_id not in {r["feature_id"] for r in rows_place}

    # category 필터 mismatch면 제외
    rows_category = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=lon - 0.1, min_lat=lat - 0.1,
        max_lon=lon + 0.1, max_lat=lat + 0.1,
        categories=["does-not-match"],
    )
    assert bundle.feature.feature_id not in {r["feature_id"] for r in rows_category}

    # provider(소스) 필터: primary source provider와 일치하면 포함
    rows_provider = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=lon - 0.1, min_lat=lat - 0.1,
        max_lon=lon + 0.1, max_lat=lat + 0.1,
        providers=[bundle.source_record.provider],
    )
    assert bundle.feature.feature_id in {r["feature_id"] for r in rows_provider}

    # provider 필터 mismatch면 제외
    rows_provider_miss = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=lon - 0.1, min_lat=lat - 0.1,
        max_lon=lon + 0.1, max_lat=lat + 0.1,
        providers=["does-not-match-provider"],
    )
    assert bundle.feature.feature_id not in {
        r["feature_id"] for r in rows_provider_miss
    }

    # feature 밖 bbox면 빈 결과
    rows_far = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=lon + 1.0, min_lat=lat + 1.0,
        max_lon=lon + 1.1, max_lat=lat + 1.1,
    )
    assert bundle.feature.feature_id not in {r["feature_id"] for r in rows_far}


async def test_features_in_bbox_hides_stale_notice_revisions(
    migrated_session: AsyncSession,
) -> None:
    old_seen = datetime(2026, 6, 1, 9, 0, tzinfo=_KST)
    new_seen = datetime(2026, 6, 1, 9, 5, tzinfo=_KST)
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category,
                coord, coord_precision_digits,
                marker_icon, marker_color, status
            )
            VALUES
            (
                'f_notice_legacy_old', 'notice', '이전 교통 공지', '99000000',
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.5678, 36.1234), 4326),
                6, 'warning', 'P-05', 'active'
            ),
            (
                'f_notice_legacy_new', 'notice', '최신 교통 공지', '99000000',
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.5678, 36.1234), 4326),
                6, 'warning', 'P-05', 'active'
            )
            """
        )
    )
    for suffix, message, series_no, seen_at in (
        ("old", "공사 시작", "100", old_seen),
        ("new", "공사 내용 수정", "101", new_seen),
    ):
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_records (
                    source_record_key, provider, dataset_key,
                    source_entity_type, source_entity_id,
                    raw_name, raw_data, raw_payload_hash,
                    fetched_at, imported_at, last_seen_at
                )
                VALUES (
                    :source_record_key, 'python-krex-api', 'krex_traffic_notices',
                    'traffic_notice', :source_entity_id,
                    :raw_name, CAST(:raw_data AS jsonb), :raw_payload_hash,
                    :seen_at, :seen_at, :seen_at
                )
                """
            ),
            {
                "source_record_key": f"sr_notice_legacy_{suffix}",
                "source_entity_id": f"legacy-hash-key-{suffix}",
                "raw_name": message,
                "raw_payload_hash": f"hash-{suffix}",
                "raw_data": (
                    "{"
                    '"occurred_date":"2026.06.01",'
                    '"occurred_time":"09:00:00",'
                    '"route_no":"0010",'
                    '"direction":"서울방향",'
                    '"point_name":"천안분기점",'
                    '"incident_type_code":"3",'
                    f'"series_no":"{series_no}",'
                    f'"message":"{message}"'
                    "}"
                ),
                "seen_at": seen_at,
            },
        )
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.source_links (
                    feature_id, source_record_key, source_role,
                    match_method, confidence, is_primary_source, created_at
                )
                VALUES (
                    :feature_id, :source_record_key, 'primary',
                    'natural_key', 100, true, :seen_at
                )
                """
            ),
            {
                "feature_id": f"f_notice_legacy_{suffix}",
                "source_record_key": f"sr_notice_legacy_{suffix}",
                "seen_at": seen_at,
            },
        )
    await migrated_session.flush()

    rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=127.5,
        min_lat=36.0,
        max_lon=127.7,
        max_lat=36.2,
        kinds=["notice"],
    )
    ids = {row["feature_id"] for row in rows}

    assert "f_notice_legacy_new" in ids
    assert "f_notice_legacy_old" not in ids


async def test_features_in_bbox_include_geometry_returns_route_area_shape(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category,
                coord, coord_precision_digits, geom,
                marker_icon, marker_color, status
            )
            VALUES
            (
                'f_route_bbox_geometry', 'route', '탐방로', '02000000',
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.05, 37.55), 4326),
                6,
                x_extension.ST_SetSRID(
                    x_extension.ST_GeomFromText(
                        'LINESTRING(127.0 37.5,127.1 37.6)'
                    ),
                    4326
                ),
                'park', 'P-06', 'active'
            ),
            (
                'f_area_bbox_geometry', 'area', '국립공원', '03000000',
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.05, 37.55), 4326),
                6,
                x_extension.ST_SetSRID(
                    x_extension.ST_GeomFromText(
                        'POLYGON((127.0 37.5,127.1 37.5,127.1 37.6,127.0 37.6,127.0 37.5))'
                    ),
                    4326
                ),
                'park', 'P-06', 'active'
            )
            """
        )
    )
    await migrated_session.flush()

    rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=126.9,
        min_lat=37.4,
        max_lon=127.2,
        max_lat=37.7,
        include_geometry=True,
    )
    by_id = {row["feature_id"]: row for row in rows}

    route = by_id["f_route_bbox_geometry"]
    assert route["geometry"]["type"] == "LineString"
    assert route["area_square_meters"] is None

    area = by_id["f_area_bbox_geometry"]
    assert area["geometry"]["type"] == "Polygon"
    assert float(area["area_square_meters"]) > 0


async def test_features_contained_in_area_returns_points_inside_polygon(
    migrated_session: AsyncSession,
) -> None:
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category,
                coord, coord_precision_digits, geom,
                marker_icon, marker_color, status
            )
            VALUES
            (
                'f_area_contains_query', 'area', '포함 영역', '03000000',
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.05, 37.55), 4326),
                6,
                x_extension.ST_SetSRID(
                    x_extension.ST_GeomFromText(
                        'POLYGON((127.0 37.5,127.1 37.5,127.1 37.6,127.0 37.6,127.0 37.5))'
                    ),
                    4326
                ),
                'park', 'P-06', 'active'
            ),
            (
                'f_area_inside_point', 'place', '안쪽 장소', '01000000',
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.04, 37.54), 4326),
                6, NULL, 'star', 'P-03', 'active'
            ),
            (
                'f_area_outside_point', 'place', '바깥 장소', '01000000',
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(127.5, 37.9), 4326),
                6, NULL, 'star', 'P-03', 'active'
            )
            """
        )
    )
    await migrated_session.flush()

    rows = await feature_repo.features_contained_in_area(
        migrated_session,
        feature_id="f_area_contains_query",
    )
    ids = {row["feature_id"] for row in rows}

    assert "f_area_inside_point" in ids
    assert "f_area_outside_point" not in ids
    inside = next(row for row in rows if row["feature_id"] == "f_area_inside_point")
    assert inside["kind"] == "place"
    assert inside["status"] == "active"


async def test_features_in_bbox_include_geometry_matches_geom_only_branch(
    migrated_session: AsyncSession,
) -> None:
    """geom-only OR 분기(coord NULL 또는 coord 밖 + geom이 bbox 교차) 검증.

    ``_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL``의 두 번째 OR 항(``kind IN
    ('route','area') AND geom && envelope``)은 coord가 bbox 안에 있으면 첫 항으로
    이미 매칭돼 단독으로 검증되지 않는다. 여기서는 ① coord=NULL(좌표 미상),
    ② coord가 bbox **밖** 두 케이스 모두 geom만으로 반환되는지 확인한다.
    ``ck_features_coord_precision`` 충족 위해 coord=NULL 행은
    coord_precision_digits=NULL로 둔다.
    """
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category,
                coord, coord_precision_digits, geom,
                marker_icon, marker_color, status
            )
            VALUES
            (
                'f_route_geom_only_null_coord', 'route', '좌표미상 탐방로', '02000000',
                NULL, NULL,
                x_extension.ST_SetSRID(
                    x_extension.ST_GeomFromText(
                        'LINESTRING(127.0 37.5,127.1 37.6)'
                    ),
                    4326
                ),
                'park', 'P-06', 'active'
            ),
            (
                'f_route_geom_only_coord_outside', 'route', '밖 좌표 탐방로', '02000000',
                x_extension.ST_SetSRID(x_extension.ST_MakePoint(129.5, 35.1), 4326),
                6,
                x_extension.ST_SetSRID(
                    x_extension.ST_GeomFromText(
                        'LINESTRING(127.0 37.5,127.1 37.6)'
                    ),
                    4326
                ),
                'park', 'P-06', 'active'
            )
            """
        )
    )
    await migrated_session.flush()

    rows = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=126.9,
        min_lat=37.4,
        max_lon=127.2,
        max_lat=37.7,
        include_geometry=True,
    )
    by_id = {row["feature_id"]: row for row in rows}

    # coord=NULL이지만 geom이 bbox를 교차 → geom-only 분기로 반환.
    null_coord = by_id["f_route_geom_only_null_coord"]
    assert null_coord["geometry"]["type"] == "LineString"
    assert null_coord["lon"] is None
    assert null_coord["lat"] is None

    # coord는 bbox 밖(129.5, 35.1)이지만 geom은 bbox 교차 → geom-only 분기로 반환.
    coord_outside = by_id["f_route_geom_only_coord_outside"]
    assert coord_outside["geometry"]["type"] == "LineString"


async def test_features_in_bbox_returns_stable_feature_id_subset(
    migrated_session: AsyncSession,
) -> None:
    bundles = [await _bundle(f"FEST-BBOX-STABLE-{idx}") for idx in range(4)]
    result = await feature_repo.load_bundles(migrated_session, bundles)
    await migrated_session.flush()
    assert result.bundles_total == 4

    lon = float(bundles[0].feature.coord.lon)
    lat = float(bundles[0].feature.coord.lat)
    params = {
        "min_lon": lon - 0.1,
        "min_lat": lat - 0.1,
        "max_lon": lon + 0.1,
        "max_lat": lat + 0.1,
        "limit": 2,
    }

    first = await feature_repo.features_in_bbox(migrated_session, **params)
    second = await feature_repo.features_in_bbox(migrated_session, **params)
    expected = sorted(bundle.feature.feature_id for bundle in bundles)[:2]
    assert [row["feature_id"] for row in first] == expected
    assert [row["feature_id"] for row in second] == expected


async def test_get_feature_rows_by_ids_and_search_features(
    migrated_session: AsyncSession,
) -> None:
    first = await _bundle("FEST-SEARCH-A")
    second = await _bundle("FEST-SEARCH-B")
    third = await _bundle("FEST-SEARCH-C")
    await feature_repo.load_bundles(migrated_session, [first, second, third])
    await migrated_session.flush()

    rows = await feature_repo.get_feature_rows_by_ids(
        migrated_session,
        [first.feature.feature_id, "missing"],
    )
    assert set(rows) == {first.feature.feature_id}
    assert rows[first.feature.feature_id]["updated_at"] == first.feature.updated_at

    # D-12(T-217b): soft-deleted(inactive) feature는 missing이 아니라 status와 함께
    # found로 반환된다 — "철회/폐업됨"과 "미존재"를 소비자가 구분한다.
    inactivated = await feature_repo.inactivate_features_by_source_entity_ids(
        migrated_session,
        provider=second.source_record.provider,
        dataset_key=second.source_record.dataset_key,
        source_entity_type=second.source_record.source_entity_type,
        source_entity_ids={second.source_record.source_entity_id},
    )
    assert inactivated == 1
    rows_after = await feature_repo.get_feature_rows_by_ids(
        migrated_session,
        [second.feature.feature_id, "missing"],
    )
    assert set(rows_after) == {second.feature.feature_id}
    inactive_row = rows_after[second.feature.feature_id]
    assert inactive_row["status"] == "inactive"
    assert inactive_row["deleted_at"] is not None
    # 검색(목록 read)은 기존대로 active만 — 아래 search 루프가 3건 전제를 깨지
    # 않도록 다시 active로 되돌린다.
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET status='active', deleted_at=NULL "
            "WHERE feature_id = :fid"
        ),
        {"fid": second.feature.feature_id},
    )

    lon = float(first.feature.coord.lon)
    lat = float(first.feature.coord.lat)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(3):
        page = await feature_repo.search_features(
            migrated_session,
            q="서울 봄꽃 축제",
            bbox=(lon - 0.1, lat - 0.1, lon + 0.1, lat + 0.1),
            kinds=["event"],
            categories=[first.feature.category],
            limit=1,
            cursor=cursor,
        )
        assert len(page.items) == 1
        assert page.total_count == 3
        assert page.items[0].score_cursor is not None
        seen.append(page.items[0].feature_id)
        cursor = page.next_cursor

    assert seen == sorted(
        [
            first.feature.feature_id,
            second.feature.feature_id,
            third.feature.feature_id,
        ]
    )
    assert cursor is None

    bbox_only = await feature_repo.search_features(
        migrated_session,
        bbox=(lon - 0.1, lat - 0.1, lon + 0.1, lat + 0.1),
        limit=10,
    )
    assert bbox_only.total_count == 3
    assert first.feature.feature_id in {item.feature_id for item in bbox_only.items}


async def test_inactivate_geometryless_area_features_by_source(
    migrated_session: AsyncSession,
) -> None:
    geometryless = await _bundle("AREA-NO-GEOM")
    with_geom = await _bundle("AREA-WITH-GEOM")
    place = await _bundle("AREA-PLACE")
    await feature_repo.load_bundles(migrated_session, [geometryless, with_geom, place])
    await migrated_session.flush()

    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET kind = 'area', geom = NULL
            WHERE feature_id = :fid
            """
        ),
        {"fid": geometryless.feature.feature_id},
    )
    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET kind = 'area',
                geom = x_extension.ST_SetSRID(
                    x_extension.ST_GeomFromText(
                        'POLYGON((126.9 37.5, 126.91 37.5, 126.91 37.51, 126.9 37.51, 126.9 37.5))'
                    ),
                    4326
                )
            WHERE feature_id = :fid
            """
        ),
        {"fid": with_geom.feature.feature_id},
    )
    await migrated_session.flush()

    inactivated = await feature_repo.inactivate_geometryless_area_features_by_source(
        migrated_session,
        provider=geometryless.source_record.provider,
        dataset_key=geometryless.source_record.dataset_key,
        source_entity_type=geometryless.source_record.source_entity_type,
    )
    assert inactivated == 1

    rows = await feature_repo.get_feature_rows_by_ids(
        migrated_session,
        [
            geometryless.feature.feature_id,
            with_geom.feature.feature_id,
            place.feature.feature_id,
        ],
    )
    assert rows[geometryless.feature.feature_id]["status"] == "inactive"
    assert rows[geometryless.feature.feature_id]["deleted_at"] is not None
    assert rows[with_geom.feature.feature_id]["status"] == "active"
    assert rows[place.feature.feature_id]["status"] == "active"


async def test_area_feature_geom_persists(migrated_session: AsyncSession) -> None:
    """route/area Feature.geom(WKT)이 features.geom으로 적재되는지 (ADR-012)."""
    from kortravelmap.providers.knps import knps_geometry_records_to_bundles

    @dataclass(frozen=True)
    class _GRec:
        source_id: str
        name: str
        geom_wkt: str
        raw: dict

    rec = _GRec(
        "PB-1",
        "북한산국립공원",
        "POLYGON((126.9 37.6, 127.0 37.6, 127.0 37.7, 126.9 37.7, 126.9 37.6))",
        {"PARK": "북한산"},
    )
    bundle = (
        await knps_geometry_records_to_bundles(
            [rec], dataset_key="knps_park_boundaries", fetched_at=_FETCHED
        )
    )[0]

    await feature_repo.load_bundle(migrated_session, bundle)
    await migrated_session.flush()

    # geom이 4326 polygon으로 저장됐는지 직접 확인.
    row = (
        await migrated_session.execute(
            text(
                "SELECT x_extension.ST_SRID(geom) AS srid, "
                "x_extension.GeometryType(geom) AS gtype "
                "FROM feature.features WHERE feature_id = :fid"
            ),
            {"fid": bundle.feature.feature_id},
        )
    ).one()
    assert row.srid == 4326
    assert row.gtype == "POLYGON"

    # get_feature_row는 coord(centroid) 기반 lon/lat 반환.
    got = await feature_repo.get_feature_row(
        migrated_session, bundle.feature.feature_id
    )
    assert got is not None
    assert got["kind"] == "area"
    assert got["lon"] is not None  # centroid

"""``test_feature_repo_load`` — ``infra/feature_repo`` 적재 경로 (testcontainers).

``FeatureBundle`` → ``feature_repo.load_bundles`` → PostGIS 적재 → 재조회 검증.
첫 실 DB write 경로(ADR-004 raw SQL upsert)를 testcontainer에서 끝까지 검증한다.

검증: ① upsert 카운트(신규/갱신) ② idempotent 재적재(ON CONFLICT, §4.4)
③ coord_5179 STORED generated(ADR-012) ④ source_link FK ⑤ source_record 이력
보존(DO NOTHING) ⑥ get_feature_row round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra import feature_repo
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 5, 29, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 (좌표 있는 케이스)."""

    management_no: str
    festival_name: str
    venue_name: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    road_address: str | None
    jibun_address: str | None
    organizer_name: str | None
    organizer_tel: str | None
    data_reference_date: date | None
    provider_org_name: str | None
    bjd_code: str | None = None
    sigungu_code: str | None = None
    sido_code: str | None = None
    admin_address: str | None = None


async def _bundle(management_no: str = "FEST-REPO-001"):
    item = _Festival(
        management_no=management_no,
        festival_name="서울 봄꽃 축제",
        venue_name="여의도공원",
        start_date=date(2026, 4, 5),
        end_date=date(2026, 4, 12),
        description="봄꽃 축제 상세.",
        latitude=Decimal("37.5263"),
        longitude=Decimal("126.9239"),
        road_address="서울특별시 영등포구 여의공원로 120",
        jibun_address="서울특별시 영등포구 여의도동 8",
        organizer_name="영등포구청",
        organizer_tel="02-2670-3114",
        data_reference_date=date(2026, 3, 1),
        provider_org_name="서울특별시 영등포구",
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
        )
    )[0]


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

    # 동일 bundle 재적재 — ON CONFLICT (test-strategy §4.4)
    second = await feature_repo.load_bundle(migrated_session, bundle)
    await migrated_session.flush()
    assert second.features_inserted == 0
    assert second.features_updated == 1
    # source_record는 DO NOTHING (이력 보존, ADR-017)
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
    scount = (
        await migrated_session.execute(
            text(
                "SELECT count(*) FROM provider_sync.source_records "
                "WHERE source_record_key = :k"
            ),
            {"k": bundle.source_record.source_record_key},
        )
    ).scalar_one()
    assert scount == 1


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

    # feature 밖 bbox면 빈 결과
    rows_far = await feature_repo.features_in_bbox(
        migrated_session,
        min_lon=lon + 1.0, min_lat=lat + 1.0,
        max_lon=lon + 1.1, max_lat=lat + 1.1,
    )
    assert bundle.feature.feature_id not in {r["feature_id"] for r in rows_far}


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
    assert first.feature.feature_id in {item.feature_id for item in bbox_only.items}


async def test_area_feature_geom_persists(migrated_session: AsyncSession) -> None:
    """route/area Feature.geom(WKT)이 features.geom으로 적재되는지 (ADR-012)."""
    from krtour.map.providers.knps import knps_geometry_records_to_bundles

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

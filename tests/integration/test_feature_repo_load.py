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

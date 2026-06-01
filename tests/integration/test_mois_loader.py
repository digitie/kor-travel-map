"""``test_mois_loader`` — MOIS 인허가 변환 → 적재 → 재조회 (Sprint 4a loader).

``krtour.map.mois.load_mois_license_features_bulk``가 ``providers.mois`` 변환
출력을 PostGIS에 idempotent upsert하는지 검증한다.

검증: ① PROMOTED record 적재 + 재조회(JSONB detail/address) ② EXCLUDED/비영업
record는 적재되지 않음 ③ 재적재 idempotent (feature 수 불변) ④ FeatureLoadResult
카운트.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select, text

from krtour.map.infra.models import FeatureRow, SourceLinkRow
from krtour.map.mois import (
    delete_mois_license_features_not_in,
    load_mois_license_features_bulk,
    sync_mois_license_features_bulk,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Record:
    """``MoisLicensePlaceRecord`` Protocol 만족 (mois.db.PlaceRecord 모사)."""

    service_slug: str
    mng_no: str | None = "MNG-0001"
    is_open: bool | None = True
    place_name: str | None = "테스트 사업장"
    category: str | None = None
    title: str | None = None
    opn_authority_code: str | None = None
    status_code: str | None = "01"
    status_name: str | None = "영업/정상"
    detail_status_code: str | None = None
    detail_status_name: str | None = None
    license_date: date | None = None
    telno: str | None = None
    road_address: str | None = None
    lot_address: str | None = None
    road_zip: str | None = None
    lot_zip: str | None = None
    legal_dong_code: str | None = "1111010100"
    road_name_code: str | None = None
    building_management_number: str | None = None
    lon: float | None = None
    lat: float | None = None
    source_x: float | None = None
    source_y: float | None = None
    business_type_name: str | None = None
    subtype_name: str | None = None
    multi_use_business_place_yn: str | None = None
    sanitation_business_status_name: str | None = None
    facility_total_scale: str | None = None
    water_supply_facility_type_name: str | None = None
    culture_sports_business_type_name: str | None = None
    sales_method_name: str | None = None
    designation_date: date | None = None
    building_usage_name: str | None = None
    ground_floor_count: int | None = None
    underground_floor_count: int | None = None
    total_floor_count: int | None = None
    facility_area: float | None = None
    total_area: float | None = None
    sickbed_count: int | None = None
    bed_count: int | None = None
    healthcare_worker_count: int | None = None
    hospital_room_count: int | None = None
    medical_institution_type_name: str | None = None
    medical_subject_names: str | None = None


async def _feature_count(session: AsyncSession) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(FeatureRow))).scalar_one()
    )


async def test_loader_persists_promoted_and_skips_others(
    migrated_session: AsyncSession,
) -> None:
    records = [
        _Record(
            service_slug="general_restaurants",
            mng_no="keep-restaurant",
            place_name="한식당 가나다",
            road_address="서울특별시 종로구 세종대로 1",
            telno="0212345678",
            lon=126.9784,
            lat=37.5665,
        ),
        _Record(service_slug="public_baths", mng_no="keep-bath", place_name="대중목욕탕"),
        _Record(service_slug="billiard_halls", mng_no="drop-excluded"),  # EXCLUDED
        _Record(service_slug="hospitals", mng_no="drop-unmapped"),  # 미매핑
        _Record(
            service_slug="bakeries", mng_no="drop-closed", is_open=False
        ),  # 비영업
    ]

    result = await load_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED
    )
    await migrated_session.flush()

    # ② PROMOTED·영업중 2건만 적재 (EXCLUDED/미매핑/비영업 skip).
    assert result.bundles_total == 2
    assert result.features_inserted == 2
    assert await _feature_count(migrated_session) == 2

    # ① 적재된 feature 재조회 + place_kind/category.
    rows = (
        await migrated_session.execute(
            select(FeatureRow).order_by(FeatureRow.feature_id)
        )
    ).scalars().all()
    by_name = {r.name: r for r in rows}
    assert "한식당 가나다" in by_name
    restaurant = by_name["한식당 가나다"]
    assert restaurant.kind == "place"
    assert restaurant.category == "02010100"
    assert restaurant.marker_color == "P-01"
    assert isinstance(restaurant.detail, dict)
    assert restaurant.detail["place_kind"] == "restaurant"

    # ③ source_link FK 정합 (PRIMARY).
    links = (
        await migrated_session.execute(select(SourceLinkRow))
    ).scalars().all()
    assert len(links) == 2
    assert all(link.is_primary_source is True for link in links)


async def test_loader_idempotent_reload(migrated_session: AsyncSession) -> None:
    records = [
        _Record(service_slug="general_restaurants", mng_no="idem-1", lon=126.97, lat=37.56),
        _Record(service_slug="bakeries", mng_no="idem-2"),
    ]

    first = await load_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED
    )
    await migrated_session.flush()
    assert first.features_inserted == 2
    assert await _feature_count(migrated_session) == 2

    # 재적재 — 같은 record → feature 수 불변, update 경로.
    second = await load_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED
    )
    await migrated_session.flush()
    assert second.bundles_total == 2
    assert second.features_inserted == 0
    assert second.features_updated == 2
    assert await _feature_count(migrated_session) == 2


async def test_loader_empty_when_all_skipped(migrated_session: AsyncSession) -> None:
    records = [
        _Record(service_slug="billiard_halls"),
        _Record(service_slug="hospitals"),
    ]
    result = await load_mois_license_features_bulk(
        migrated_session, records, fetched_at=_FETCHED
    )
    await migrated_session.flush()
    assert result.bundles_total == 0
    assert result.features_inserted == 0
    count = (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.features")
        )
    ).scalar_one()
    assert int(count) == 0


async def _active_entity_ids(session: AsyncSession) -> set[str]:
    rows = (
        await session.execute(
            text(
                "SELECT sr.source_entity_id "
                "FROM feature.features f "
                "JOIN provider_sync.source_links sl ON sl.feature_id = f.feature_id "
                "JOIN provider_sync.source_records sr "
                "  ON sr.source_record_key = sl.source_record_key "
                "WHERE f.deleted_at IS NULL AND sl.is_primary_source"
            )
        )
    ).scalars().all()
    return set(rows)


async def test_delete_not_in_snapshot_soft_deletes_missing(
    migrated_session: AsyncSession,
) -> None:
    # 1차 적재 — 3건.
    first = [
        _Record(service_slug="general_restaurants", mng_no="keep-1"),
        _Record(service_slug="bakeries", mng_no="keep-2"),
        _Record(service_slug="public_baths", mng_no="gone-3"),
    ]
    await load_mois_license_features_bulk(migrated_session, first, fetched_at=_FETCHED)
    await migrated_session.flush()
    assert await _active_entity_ids(migrated_session) == {
        "general_restaurants::keep-1",
        "bakeries::keep-2",
        "public_baths::gone-3",
    }

    # snapshot에 keep-1/keep-2만 → gone-3 soft-delete.
    snapshot = {"general_restaurants::keep-1", "bakeries::keep-2"}
    deleted = await delete_mois_license_features_not_in(migrated_session, snapshot)
    await migrated_session.flush()
    assert deleted == 1
    assert await _active_entity_ids(migrated_session) == snapshot

    # 재호출 idempotent — 이미 비활성이므로 0건.
    again = await delete_mois_license_features_not_in(migrated_session, snapshot)
    assert again == 0

    # deleted_at + status='inactive' 확인 (비활성 1건).
    statuses = (
        await migrated_session.execute(
            text("SELECT status, deleted_at IS NOT NULL AS gone FROM feature.features")
        )
    ).all()
    inactive = [s for s in statuses if s.status == "inactive"]
    assert len(inactive) == 1
    assert inactive[0].gone is True


async def test_sync_bulk_loads_and_prunes_in_one_call(
    migrated_session: AsyncSession,
) -> None:
    # 1차 snapshot — 2건.
    await sync_mois_license_features_bulk(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="a"),
            _Record(service_slug="bakeries", mng_no="b"),
        ],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert await _active_entity_ids(migrated_session) == {
        "general_restaurants::a",
        "bakeries::b",
    }

    # 2차 snapshot — a는 유지, b는 사라지고 c 신규 + EXCLUDED 1건(무시).
    result = await sync_mois_license_features_bulk(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="a"),
            _Record(service_slug="public_baths", mng_no="c"),
            _Record(service_slug="billiard_halls", mng_no="excluded"),
        ],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert result.load.bundles_total == 2  # a(update) + c(insert)
    assert result.deactivated == 1  # b
    assert await _active_entity_ids(migrated_session) == {
        "general_restaurants::a",
        "public_baths::c",
    }


async def test_sync_bulk_empty_snapshot_deactivates_all(
    migrated_session: AsyncSession,
) -> None:
    await sync_mois_license_features_bulk(
        migrated_session,
        [_Record(service_slug="bakeries", mng_no="solo")],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()
    assert await _active_entity_ids(migrated_session) == {"bakeries::solo"}

    # 빈 snapshot(전부 폐업) → 모두 비활성화.
    result = await sync_mois_license_features_bulk(
        migrated_session, [], fetched_at=_FETCHED
    )
    await migrated_session.flush()
    assert result.load.bundles_total == 0
    assert result.deactivated == 1
    assert await _active_entity_ids(migrated_session) == set()

"""``test_status_repo`` — gather_status_counts 운영 현황 집계 (ADR-039 status).

testcontainers PostGIS에 mois feature + import_job을 적재한 뒤 카운트 집계를
검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from krtour.map.infra.jobs_repo import enqueue_import_job, start_import_job
from krtour.map.infra.status_repo import gather_status_counts
from krtour.map.mois import load_mois_license_features_bulk

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 1, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Record:
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


async def test_status_counts_empty(migrated_session: AsyncSession) -> None:
    counts = await gather_status_counts(migrated_session)
    assert counts.features_total == 0
    assert counts.features_active == 0
    assert counts.features_by_kind == {}
    assert counts.source_records_by_provider == {}
    assert counts.import_jobs_by_status == {}
    assert counts.dedup_queue_by_status == {}


async def test_status_counts_with_data(migrated_session: AsyncSession) -> None:
    await load_mois_license_features_bulk(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="r1"),
            _Record(service_slug="bakeries", mng_no="b1"),
        ],
        fetched_at=_FETCHED,
    )
    await enqueue_import_job(migrated_session, kind="k")
    await start_import_job(migrated_session, kind="k")
    await migrated_session.flush()

    counts = await gather_status_counts(migrated_session)
    assert counts.features_total == 2
    assert counts.features_active == 2
    assert counts.features_inactive == 0
    assert counts.features_by_kind == {"place": 2}
    assert counts.source_records_by_provider == {"python-mois-api": 2}
    assert counts.import_jobs_by_status == {"queued": 1, "running": 1}

"""``test_sibling_dedup`` — MOIS self-sibling 후보 적재 (ADR-016).

같은 사업장이 2슬러그로 중복 적재된 MOIS feature를 ``find_sibling_candidates``로
탐지해 ``ops.dedup_review_queue``에 적재하는지 검증한다 (within-set pairwise).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.core.dedup import find_sibling_candidates
from krtour.map.infra.dedup_repo import enqueue_dedup_candidates
from krtour.map.infra.feature_repo import get_feature_row
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
    place_name: str | None = "행복식당"
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
    lon: float | None = 127.0
    lat: float | None = 37.5
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


async def test_sibling_candidates_enqueued(migrated_session: AsyncSession) -> None:
    # 같은 사업장(이름/좌표 동일)이 두 식음 슬러그로 등록 → sibling.
    await load_mois_license_features_bulk(
        migrated_session,
        [
            _Record(service_slug="general_restaurants", mng_no="biz-1"),
            _Record(service_slug="tourist_restaurants", mng_no="biz-1"),
        ],
        fetched_at=_FETCHED,
    )
    await migrated_session.flush()

    # 적재된 feature를 DedupInput으로 재구성(Feature가 Protocol 만족하나 여기선
    # 경량 stub로 row에서 뽑음).
    rows = (
        await migrated_session.execute(
            text(
                "SELECT feature_id, name, category, "
                "x_extension.ST_X(coord) lon, x_extension.ST_Y(coord) lat "
                "FROM feature.features WHERE deleted_at IS NULL"
            )
        )
    ).all()
    assert len(rows) == 2

    from decimal import Decimal

    from krtour.map.dto.coordinate import Coordinate

    @dataclass(frozen=True)
    class _Feat:
        feature_id: str
        name: str
        coord: Coordinate | None
        category: str

    feats = [
        _Feat(
            r.feature_id,
            r.name,
            Coordinate(lon=Decimal(str(r.lon)), lat=Decimal(str(r.lat))),
            r.category,
        )
        for r in rows
    ]
    candidates = find_sibling_candidates(feats)
    assert len(candidates) == 1

    queue = await enqueue_dedup_candidates(migrated_session, candidates)
    await migrated_session.flush()
    assert queue.inserted == 1

    # 큐 적재 확인 + FK 정합(두 feature 존재).
    cnt = (
        await migrated_session.execute(
            text("SELECT count(*) FROM ops.dedup_review_queue WHERE status='pending'")
        )
    ).scalar_one()
    assert int(cnt) == 1
    assert await get_feature_row(migrated_session, candidates[0].feature_id_a) is not None
    assert await get_feature_row(migrated_session, candidates[0].feature_id_b) is not None

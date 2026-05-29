"""``test_feature_bundle_persist`` — FeatureBundle → ORM → PostGIS → 재조회.

provider 변환 결과(`FeatureBundle`)를 `infra/models` ORM(features/source_records/
source_links)으로 적재한 뒤 재조회해 DB 계약을 검증한다 (사용자 지시 통합 검증
#116). 실 적재 경로 `feature_repo.py`는 Sprint 3 예정이므로 본 테스트가 DTO→DB
round-trip을 선행 검증한다.

검증: ① JSONB(detail/address) round-trip ② STORED generated ``coord_5179``
(= ST_Transform(coord,5179), ADR-012) ③ source_link FK(feature/source_record) 정합.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text

from krtour.map.infra.models import FeatureRow, SourceLinkRow, SourceRecordRow
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))


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


_ITEM = _Festival(
    management_no="FEST-PERSIST-001",
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


async def test_feature_bundle_persists_and_roundtrips(
    migrated_session: AsyncSession,
) -> None:
    from geoalchemy2 import WKTElement

    bundle = (
        await cultural_festivals_to_bundles(
            [_ITEM],  # type: ignore[list-item]
            fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
        )
    )[0]
    feature, source_record, source_link = (
        bundle.feature,
        bundle.source_record,
        bundle.source_link,
    )
    assert feature.coord is not None  # 좌표 있는 케이스

    feature_row = FeatureRow(
        feature_id=feature.feature_id,
        kind=feature.kind.value,
        name=feature.name,
        category=feature.category,
        coord=WKTElement(
            f"POINT({feature.coord.lon} {feature.coord.lat})", srid=4326
        ),
        address=feature.address.model_dump(mode="json"),
        detail=feature.detail.model_dump(mode="json") if feature.detail else {},
        marker_icon=feature.marker_icon,
        marker_color=feature.marker_color,
    )
    source_record_row = SourceRecordRow(
        source_record_key=source_record.source_record_key,
        provider=source_record.provider,
        dataset_key=source_record.dataset_key,
        source_entity_type=source_record.source_entity_type,
        source_entity_id=source_record.source_entity_id,
        raw_payload_hash=source_record.raw_payload_hash,
        raw_name=source_record.raw_name,
        raw_data=source_record.raw_data,
        fetched_at=source_record.fetched_at,
    )
    migrated_session.add_all([feature_row, source_record_row])
    await migrated_session.flush()  # features/source_records INSERT → coord_5179 계산

    source_link_row = SourceLinkRow(
        feature_id=source_link.feature_id,
        source_record_key=source_link.source_record_key,
        source_role=source_link.source_role.value,
        match_method=source_link.match_method,
        confidence=source_link.confidence,
        is_primary_source=source_link.is_primary_source,
    )
    migrated_session.add(source_link_row)
    await migrated_session.flush()

    # ① feature 재조회 + JSONB round-trip
    got = (
        await migrated_session.execute(
            select(FeatureRow).where(FeatureRow.feature_id == feature.feature_id)
        )
    ).scalar_one()
    assert got.kind == "event"
    assert got.name == feature.name
    assert got.category == feature.category
    assert isinstance(got.detail, dict)
    assert got.detail  # detail JSONB 비어있지 않음
    assert isinstance(got.address, dict)

    # ② coord_5179 STORED generated(ST_Transform) + coord 좌표 일치
    res = await migrated_session.execute(
        text(
            "SELECT ST_SRID(coord_5179) AS srid, ST_X(coord) AS x, ST_Y(coord) AS y "
            "FROM feature.features WHERE feature_id = :fid"
        ),
        {"fid": feature.feature_id},
    )
    srid5179, x, y = res.one()
    assert srid5179 == 5179
    assert abs(float(x) - float(feature.coord.lon)) < 1e-6
    assert abs(float(y) - float(feature.coord.lat)) < 1e-6

    # ③ source_link FK 정합
    link = (
        await migrated_session.execute(
            select(SourceLinkRow).where(
                SourceLinkRow.feature_id == feature.feature_id
            )
        )
    ).scalar_one()
    assert link.source_record_key == source_record.source_record_key
    assert link.is_primary_source is True

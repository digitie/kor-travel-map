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
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text

from kortravelmap.infra.models import FeatureRow, SourceLinkRow, SourceRecordRow
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))


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


_ITEM = _Festival(
    fstvl_nm="서울 봄꽃 축제",
    opar="여의도공원",
    fstvl_start_date=date(2026, 4, 5),
    fstvl_end_date=date(2026, 4, 12),
    fstvl_co="봄꽃 축제 상세.",
    mnnst_nm="영등포구청",
    phone_number="02-2670-3114",
    rdnmadr="서울특별시 영등포구 여의공원로 120",
    lnmadr="서울특별시 영등포구 여의도동 8",
    latitude=37.5263,
    longitude=126.9239,
    reference_date=date(2026, 3, 1),
    instt_nm="서울특별시 영등포구",
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

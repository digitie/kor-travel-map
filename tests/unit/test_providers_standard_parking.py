"""``test_providers_standard_parking`` — datagokr 주차장 표준데이터 (T-RV-55b)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from kortravelmap.dto import FeatureBundle, FeatureKind, SourceRole
from kortravelmap.providers.standard_data import (
    DATASET_KEY_PARKING_LOTS,
    PARKING_CATEGORY,
    PARKING_MARKER_COLOR,
)
from kortravelmap.providers.standard_data import (
    parking_lots_to_bundles as _parking_async,
)

KST = timezone(timedelta(hours=9))


def parking_lots_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    return asyncio.run(_parking_async(items, **kwargs))


@dataclass(frozen=True)
class _Parking:
    prkplce_no: str | None
    prkplce_nm: str | None
    prkplce_se: str | None
    rdnmadr: str | None
    lnmadr: str | None
    prkcmprt: int | None
    parkingchrge_info: str | None
    latitude: float | None
    longitude: float | None
    phone_number: str | None
    instt_code: str | None
    raw: Any = field(default_factory=dict)


_P1 = _Parking(
    prkplce_no="PK-0001",
    prkplce_nm="시청 공영주차장",
    prkplce_se="공영",
    rdnmadr="서울특별시 중구 세종대로 110",
    lnmadr=None,
    prkcmprt=120,
    parkingchrge_info="유료",
    latitude=37.5663,
    longitude=126.9779,
    phone_number="02-120",
    instt_code="PK-INSTT",
)


def _now() -> datetime:
    return datetime(2026, 6, 8, 12, 0, 0, tzinfo=KST)


@pytest.mark.unit
def test_parking_feature_fields() -> None:
    bundle = parking_lots_to_bundles([_P1], fetched_at=_now())[0]
    feature = bundle.feature
    assert feature.kind == FeatureKind.PLACE
    assert feature.name == "시청 공영주차장"
    assert feature.category == PARKING_CATEGORY  # 06010000
    assert feature.marker_color == PARKING_MARKER_COLOR
    detail = feature.detail
    assert detail is not None
    assert detail.place_kind == "parking"  # type: ignore[union-attr]
    assert detail.facility_info["prkcmprt"] == 120  # type: ignore[union-attr]
    assert bundle.source_record.dataset_key == DATASET_KEY_PARKING_LOTS
    # 안정키 = prkplce_no.
    assert bundle.source_record.source_entity_id == "PK-0001"


@pytest.mark.unit
def test_parking_derived_key_when_no_ids() -> None:
    item = _Parking(
        prkplce_no=None,
        prkplce_nm="노상 주차장",
        prkplce_se="노상",
        rdnmadr="부산광역시 해운대구 우동 1",
        lnmadr=None,
        prkcmprt=None,
        parkingchrge_info=None,
        latitude=None,
        longitude=None,
        phone_number=None,
        instt_code=None,
    )
    bundle = parking_lots_to_bundles([item], fetched_at=_now())[0]
    assert bundle.source_record.source_entity_id == "노상 주차장::부산광역시 해운대구 우동 1"
    assert bundle.feature.coord is None


@pytest.mark.unit
def test_parking_out_of_korea_coordinate_isolated() -> None:
    """한국 경계 밖 오타 좌표는 격리(coord None)하고 row는 주소 단서로 적재.

    T-212e live 실측(run `bc740f74`): 주차장 표준데이터에 `lat=26.128492`
    row가 실존 — 좌표 한 쌍의 오타가 dataset 전체 적재를 차단하면 안 된다
    (#386 날짜 역전 격리와 동일 패턴).
    """

    bad = _Parking(
        prkplce_no="PK-BAD-COORD",
        prkplce_nm="좌표 오타 주차장",
        prkplce_se="공영",
        rdnmadr="경상남도 어딘가로 1",
        lnmadr=None,
        prkcmprt=10,
        parkingchrge_info=None,
        latitude=26.128492,  # 한국 lat 허용범위 [33.0, 39.5] 밖
        longitude=128.33976,
        phone_number=None,
        instt_code=None,
    )
    bundles = parking_lots_to_bundles([bad, _P1], fetched_at=_now())
    assert len(bundles) == 2
    isolated = bundles[0]
    assert isolated.feature.coord is None  # 좌표 격리
    assert isolated.source_record.raw_address is not None  # 주소 단서 보존
    # 정상 row는 영향 없음.
    assert bundles[1].feature.coord is not None


@pytest.mark.unit
def test_parking_prefers_instt_code_over_derived() -> None:
    item = _Parking(
        prkplce_no=None,
        prkplce_nm="주차장A",
        prkplce_se="공영",
        rdnmadr="대구광역시 중구 1",
        lnmadr=None,
        prkcmprt=10,
        parkingchrge_info=None,
        latitude=None,
        longitude=None,
        phone_number=None,
        instt_code="INSTT-9",
    )
    bundle = parking_lots_to_bundles([item], fetched_at=_now())[0]
    assert bundle.source_record.source_entity_id == "INSTT-9"
    assert bundle.source_link.source_role == SourceRole.PRIMARY

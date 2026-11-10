"""통합 테스트용 TourAPI 축제 입력 — 표준데이터 축제(2026-11-10 퇴역)를 대신한다.

축제 원천은 TourAPI(``searchFestival2``) 하나다(``docs/etl/event-feature-etl.md``). 표준데이터
축제 dataset은 migration 447에서 비활성이라 head DB에는 그 dataset으로 적재할 수 없다 — 축제
Feature가 필요한 통합 테스트는 이 모듈로 TourAPI 행을 만든다.

자연키는 ``content_id``다. 같은 이름의 Feature를 여럿 심으려면 ``content_id``만 바꾼다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from kortravelmap.dto import FeatureBundle
from kortravelmap.providers.visitkorea import (
    DATASET_KEY_VISITKOREA_FESTIVALS,
    FESTIVAL_SOURCE_ENTITY_TYPE,
    VISITKOREA_PROVIDER_NAME,
    tourapi_festivals_to_bundles,
)

__all__ = [
    "FESTIVAL_DATASET_KEY",
    "FESTIVAL_ENTITY_TYPE",
    "FESTIVAL_PROVIDER",
    "TourApiFestival",
    "festival_bundles",
    "festival_item",
]

FESTIVAL_PROVIDER: Final[str] = VISITKOREA_PROVIDER_NAME
FESTIVAL_DATASET_KEY: Final[str] = DATASET_KEY_VISITKOREA_FESTIVALS
FESTIVAL_ENTITY_TYPE: Final[str] = FESTIVAL_SOURCE_ENTITY_TYPE


@dataclass(frozen=True)
class TourApiFestival:
    """``VisitKoreaFestivalItem`` Protocol 만족(provider ``TourItem`` 필드 이름)."""

    content_id: str | None
    title: str | None
    content_type_id: str | None = "15"
    addr1: str | None = None
    addr2: str | None = None
    zipcode: str | None = None
    tel: str | None = None
    first_image: str | None = None
    first_image2: str | None = None
    map_x: float | None = None
    map_y: float | None = None
    lcls_systm1: str | None = "EV"
    lcls_systm2: str | None = "EV01"
    lcls_systm3: str | None = "EV010200"
    l_dong_regn_cd: str | None = None
    l_dong_signgu_cd: str | None = None
    created_time: datetime | None = None
    modified_time: datetime | None = None
    copyright_division_code: str | None = None
    event_start_date: str | None = None
    event_end_date: str | None = None
    overview: str | None = None
    homepage: str | None = None


def _yyyymmdd(value: date | None) -> str | None:
    return value.strftime("%Y%m%d") if value is not None else None


def festival_item(
    content_id: str,
    title: str,
    *,
    starts_on: date | None = date(2026, 4, 5),
    ends_on: date | None = date(2026, 4, 12),
    addr1: str | None = "서울특별시 영등포구 여의공원로 120",
    addr2: str | None = "여의도공원",
    lon: float | None = 126.9239,
    lat: float | None = 37.5263,
    tel: str | None = "02-2670-3114",
    overview: str | None = None,
    **extra: Any,
) -> TourApiFestival:
    """축제 한 행. 기본값은 여의도 봄꽃 축제 모양(좌표·기간·개최지 주소가 다 있다)."""
    return TourApiFestival(
        content_id=content_id,
        title=title,
        addr1=addr1,
        addr2=addr2,
        tel=tel,
        map_x=lon,
        map_y=lat,
        event_start_date=_yyyymmdd(starts_on),
        event_end_date=_yyyymmdd(ends_on),
        overview=overview,
        **extra,
    )


async def festival_bundles(
    items: Iterable[TourApiFestival], *, fetched_at: datetime, **kwargs: Any
) -> list[FeatureBundle]:
    """``tourapi_festivals_to_bundles`` 그대로(geo 인자도 같다)."""
    return await tourapi_festivals_to_bundles(items, fetched_at=fetched_at, **kwargs)

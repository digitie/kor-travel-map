"""``krtour.map.providers.standard_data`` — data.go.kr 표준데이터 → FeatureBundle.

본 모듈은 공공데이터포털 ``data.go.kr-standard`` 표준데이터를 본 라이브러리의
``FeatureBundle``로 정규화한다. provider client + typed model은 별도
``python-datagokr-api`` 라이브러리가 제공 (ADR-006 wrapper 금지 정신: 본
모듈은 변환만, client 호출은 호출자가 직접).

지원 dataset (Sprint 2부터 점진 추가):

| dataset_key | Feature.kind | 함수 | Sprint |
|-------------|-------------|------|--------|
| ``datagokr_cultural_festivals`` | ``event`` | ``cultural_festivals_to_bundles`` | 2 (본 PR) |
| ``datagokr_tourism_points`` | ``place`` | ``tourism_points_to_bundles`` | 5 |

ADR 참조
--------
- ADR-006 — provider wrapper 금지 (public client 직접 사용)
- ADR-009 — ``make_feature_id`` / ``make_source_record_key`` / ``make_payload_hash``
- ADR-018 — ``Feature.detail``은 ``EventDetail`` 인스턴스로
- ADR-019 — 모든 datetime aware (KST, ``Asia/Seoul``)
- ADR-024 — canonical provider name ``data.go.kr-standard``
- ADR-042 — datagokr 표준데이터 축제 1차 source (visitkorea TourAPI는
  enrichment 2차)

설계 메모
--------
``python-datagokr-api``의 typed model은 본 라이브러리가 import해서 인스턴스로
받지 않는다 (ADR-006 — public client 직접 사용, 본 모듈은 변환 순수 함수).
대신 본 모듈은 ``CulturalFestivalItem`` ``Protocol``로 입력 shape만 정의한다.
``python-datagokr-api``는 자기 dataclass/Pydantic 모델이 본 Protocol을 만족
하도록 필드 이름을 맞추거나, 호출자가 가벼운 dict→model adapter를 자기
영역에서 만든다.

``reverse_geocoder``는 좌표 → 법정동코드 / 시도/시군구 코드 reverse geocoding
helper (있으면). Sprint 1 시점에는 placeholder Protocol — 실제 구현은
``python-kraddr-geo`` 측에. ``None``이면 ``Feature.address.bjd_code``는 비움.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
    Address,
    Coordinate,
    EventDetail,
    Feature,
    FeatureBundle,
    FeatureKind,
    SourceLink,
    SourceRecord,
    SourceRole,
)

__all__ = [
    "CulturalFestivalItem",
    "ReverseGeocodeResult",
    "ReverseGeocoder",
    "cultural_festivals_to_bundles",
    # 상수 (호출자가 source_role/marker 등 변경하고 싶을 때 참조)
    "DATASET_KEY_CULTURAL_FESTIVALS",
    "FESTIVAL_CATEGORY",
    "FESTIVAL_MARKER_ICON",
    "FESTIVAL_MARKER_COLOR",
]


# -- 상수 -----------------------------------------------------------------

DATASET_KEY_CULTURAL_FESTIVALS: Final[str] = "datagokr_cultural_festivals"
"""``provider_sync.source_records.dataset_key`` 값 — 전국문화축제표준데이터."""

_PROVIDER_NAME: Final[str] = "data.go.kr-standard"
"""canonical provider name (``ADR-024`` ``CANONICAL_PROVIDER_NAMES``)."""

_SOURCE_ENTITY_TYPE: Final[str] = "cultural_festival"
"""provider 내 entity 종류 — ``source_records.source_entity_type``."""

FESTIVAL_CATEGORY: Final[str] = "01000000"
"""``Feature.category`` — ``PlaceCategoryCode.TOURISM`` 8자리 (ADR-042).

festival은 sub-category 없이 ``EventDetail.event_kind='festival'``에서 분기.
"""

FESTIVAL_MARKER_ICON: Final[str] = "star"
"""Maki icon name. ``docs/event-feature-etl.md §4`` 표 참조."""

FESTIVAL_MARKER_COLOR: Final[str] = "P-11"
"""축제 marker color palette (자홍 계열). ``docs/event-feature-etl.md §4`` 표."""


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class CulturalFestivalItem(Protocol):
    """전국문화축제표준데이터 한 row의 입력 shape.

    ``python-datagokr-api``의 typed model이 본 Protocol을 만족해야 한다.
    필드 이름이 다르면 호출자가 가벼운 dataclass adapter를 자기 영역에서 만들어
    전달.

    원천 한국어 컬럼 → 본 Protocol 영문 필드 매핑은 ``docs/event-feature-etl.md
    §4`` 표 참조.

    Notes
    -----
    ``runtime_checkable``로 두지만 isinstance 검사는 비싸므로 본 모듈은 사용
    하지 않는다 — 함수 호출 시점에 attribute 접근으로 자연 검증.
    """

    management_no: str
    """관리번호 — provider 내 자연키 (``source_entity_id``로 매핑)."""

    festival_name: str
    """축제명 (``Feature.name``)."""

    venue_name: str | None
    """개최장소 (``EventDetail.venue_name``)."""

    start_date: date | None
    """축제시작일자 (``EventDetail.starts_on``)."""

    end_date: date | None
    """축제종료일자 (``EventDetail.ends_on``)."""

    description: str | None
    """축제내용 (``SourceRecord.raw_data``에만 저장, Feature 본체는 미반영)."""

    latitude: Decimal | None
    """위도 (WGS84). ``None`` 가능."""

    longitude: Decimal | None
    """경도 (WGS84). ``None`` 가능."""

    road_address: str | None
    """도로명주소 (``Feature.address.road`` + ``SourceRecord.raw_address``)."""

    jibun_address: str | None
    """지번주소 (``Feature.address.legal``)."""

    organizer_name: str | None
    """주관기관명 (``EventDetail.payload['organizer_name']``)."""

    organizer_tel: str | None
    """주관기관전화번호 (``EventDetail.tel``)."""

    data_reference_date: date | None
    """데이터기준일자 (``SourceRecord.raw_data``에 저장)."""

    provider_org_name: str | None
    """제공기관명 (``SourceRecord.source_version`` 또는 raw_data)."""


# -- Reverse geocoder Protocol -------------------------------------------


class ReverseGeocodeResult(Protocol):
    """``reverse_geocoder.lookup(lon, lat)``의 반환 shape."""

    bjd_code: str | None
    """법정동코드 10자리."""

    sigungu_code: str | None
    """시·군·구 코드 5자리."""

    sido_code: str | None
    """시·도 코드 2자리."""

    admin_address: str | None
    """행정동 주소 (있으면)."""


class ReverseGeocoder(Protocol):
    """좌표 → 행정구역 코드 reverse geocoding helper (있으면).

    Sprint 1 시점에는 plug-in 인터페이스만 정의 — 구현체는 ``python-kraddr-
    geo`` 측이 후속 PR에서 제공.
    """

    def lookup(
        self, *, lon: Decimal, lat: Decimal
    ) -> ReverseGeocodeResult | None: ...


# -- 단일 변환 ------------------------------------------------------------


def _item_to_bundle(
    item: CulturalFestivalItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    """한 row → 한 ``FeatureBundle``. 본 함수는 모듈 private."""

    # 1) Coordinate (한 쪽이라도 None이면 좌표 미상).
    coord: Coordinate | None
    if item.latitude is not None and item.longitude is not None:
        coord = Coordinate(lon=item.longitude, lat=item.latitude)
    else:
        coord = None

    # 2) Reverse geocoding (있으면, 좌표 있을 때만).
    bjd_code: str | None = None
    sigungu_code: str | None = None
    sido_code: str | None = None
    admin_address: str | None = None
    if coord is not None and reverse_geocoder is not None:
        rg = reverse_geocoder.lookup(lon=coord.lon, lat=coord.lat)
        if rg is not None:
            bjd_code = rg.bjd_code
            sigungu_code = rg.sigungu_code
            sido_code = rg.sido_code
            admin_address = rg.admin_address

    # 3) Address — 빈 필드는 None으로 남김 (Address(extra='forbid'), road/legal/admin은 nullable).
    address = Address(
        road=item.road_address,
        legal=item.jibun_address,
        admin=admin_address,
        bjd_code=bjd_code,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
    )

    # 4) Raw payload (canonical JSON 직렬화 가능한 dict).
    raw_data: dict[str, Any] = {
        "management_no": item.management_no,
        "festival_name": item.festival_name,
        "venue_name": item.venue_name,
        "start_date": item.start_date.isoformat() if item.start_date else None,
        "end_date": item.end_date.isoformat() if item.end_date else None,
        "description": item.description,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "road_address": item.road_address,
        "jibun_address": item.jibun_address,
        "organizer_name": item.organizer_name,
        "organizer_tel": item.organizer_tel,
        "data_reference_date": (
            item.data_reference_date.isoformat()
            if item.data_reference_date else None
        ),
        "provider_org_name": item.provider_org_name,
    }
    payload_hash = make_payload_hash(raw_data)

    # 5) source_record_key (ADR-009).
    source_record_key = make_source_record_key(
        provider=_PROVIDER_NAME,
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=item.management_no,
        raw_payload_hash=payload_hash,
    )

    # 6) feature_id (ADR-009). bjd_code 미상 시 'global' fallback은 make_feature_id 내부.
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.EVENT.value,
        category=FESTIVAL_CATEGORY,
        source_type=f"{_PROVIDER_NAME}:{DATASET_KEY_CULTURAL_FESTIVALS}",
        source_natural_key=item.management_no,
    )

    # 7) Feature 본체.
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name=item.festival_name,
        coord=coord,
        address=address,
        category=FESTIVAL_CATEGORY,
        marker_icon=FESTIVAL_MARKER_ICON,
        marker_color=FESTIVAL_MARKER_COLOR,
        detail=EventDetail(
            feature_id=feature_id,
            event_kind="festival",
            starts_on=item.start_date,
            ends_on=item.end_date,
            venue_name=item.venue_name,
            tel=item.organizer_tel,
            # area_code / sigungu_code 등 TourAPI 식별자는 visitkorea enrichment
            # 단계에서 채움 (ADR-042). 표준데이터는 영문 행정코드만.
            payload={
                "organizer_name": item.organizer_name,
                "provider_org_name": item.provider_org_name,
            },
        ),
    )

    # 8) SourceRecord (raw 보존).
    source_record = SourceRecord(
        provider=normalize_provider_name(_PROVIDER_NAME),
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=item.management_no,
        raw_payload_hash=payload_hash,
        source_version=None,  # 표준데이터 자체에 schema version은 없음
        raw_name=item.festival_name,
        raw_address=item.road_address or item.jibun_address,
        raw_longitude=item.longitude,
        raw_latitude=item.latitude,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )

    # 9) SourceLink — primary (ADR-042 datagokr 1차 source).
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",  # management_no 직접 매핑
        confidence=100,  # 1차 source는 항상 100
        is_primary_source=True,
    )

    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


# -- 공개 API -----------------------------------------------------------


def cultural_festivals_to_bundles(
    items: Iterable[CulturalFestivalItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """전국문화축제표준데이터 items → ``list[FeatureBundle]`` (ADR-042 1차 source).

    Parameters
    ----------
    items
        ``python-datagokr-api``의 cultural festival typed model iterable.
        본 모듈의 ``CulturalFestivalItem`` Protocol을 만족해야 한다.
    fetched_at
        provider 호출 시각 (KST aware, ADR-019). 모든 bundle의 ``SourceRecord
        .fetched_at``에 같은 값 사용 — 호출자가 page batch 단위로 1회 결정.
    reverse_geocoder
        좌표 → 법정동코드 helper (있으면). ``None``이면 ``Feature.address.
        bjd_code`` 등은 비움 — 후속 enrichment PR에서 채울 수 있음.

    Returns
    -------
    list[FeatureBundle]
        입력 순서 유지. 각 bundle은 ``Feature`` + ``SourceRecord`` +
        ``SourceLink``로 구성. ``feature_id`` / ``source_record_key``는
        결정적(ADR-009)이라 같은 입력은 항상 같은 ID.

    Raises
    ------
    ValueError
        ``fetched_at``이 naive datetime (ADR-019 enforce — ``SourceRecord``의
        validator에서 raise).
    pydantic.ValidationError
        ``EventDetail.ends_on < starts_on`` 같은 도메인 룰 위반.

    Examples
    --------
    호출자(TripMate apps 또는 Dagster asset) 측 사용 예시:

    >>> from datetime import datetime, timezone, timedelta
    >>> from krtour.map.providers.standard_data import (
    ...     cultural_festivals_to_bundles,
    ... )
    >>> # client = AsyncDataGoKrClient(...)
    >>> # items = [item async for item in client.aiter_cultural_festivals()]
    >>> # bundles = cultural_festivals_to_bundles(
    >>> #     items,
    >>> #     fetched_at=datetime.now(timezone(timedelta(hours=9))),
    >>> #     reverse_geocoder=kraddr_reverse,
    >>> # )
    >>> # await client_app.load_feature_bundles(bundles)

    Notes
    -----
    - 좌표 nullable: 본 표준데이터는 좌표 없는 row가 종종 있음. 좌표 없으면
      ``Feature.coord=None``으로 적재되고 ``features_in_bounds`` 쿼리에서
      자연히 제외된다 (ADR-012).
    - reverse_geocoder가 ``None``이고 좌표가 있어도 ``bjd_code``는 채워지지
      않는다 — 호출자가 이후 enrichment PR에서 batch 보강.
    - visitkorea enrichment(이미지 / 상세설명 / contentId)는 Sprint 2 끝물
      별도 PR — `festival_to_enrichment_links`에서 처리.
    """
    return [
        _item_to_bundle(
            item, fetched_at=fetched_at, reverse_geocoder=reverse_geocoder
        )
        for item in items
    ]

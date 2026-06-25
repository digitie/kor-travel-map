"""``kortravelmap.providers.standard_data`` — data.go.kr 표준데이터 → FeatureBundle.

본 모듈은 공공데이터포털 ``data.go.kr-standard`` 표준데이터를 본 라이브러리의
``FeatureBundle``로 정규화한다. provider client + typed model은 별도
``python-datagokr-api`` 라이브러리가 제공 (ADR-006 wrapper 금지 정신: 본
모듈은 변환만, client 호출은 호출자가 직접).

지원 dataset (Sprint 2부터 점진 추가):

| dataset_key | Feature.kind | 함수 | Sprint |
|-------------|-------------|------|--------|
| ``datagokr_cultural_festivals`` | ``event`` | ``cultural_festivals_to_bundles`` | 2 (본 PR) |
| ``datagokr_tourism_points`` | ``place`` | ``tourism_points_to_bundles`` | 5 |
| ``standard_special_streets`` | ``place`` | ``special_streets_to_bundles`` | T-223b |

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

``reverse_geocoder``는 좌표 → ``Address``(법정동코드 등) async 역지오코더이고,
``address_resolver``는 주소 문자열 → 행정코드 보강 geocoder다. feature_id가
bjd_code에 의존하므로(ADR-009) 변환 함수는 **async**이고 feature_id 계산 전에
``await``한다. 좌표 reverse가 없거나 실패해도 주소가 있으면 kor-travel-geo
``/v2/geocode`` structured ``legal_dong_code``로 보강한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from pydantic import ValidationError

from kortravelmap.category import (
    PlaceCategoryCode,
    mapbox_maki_icon_or_none,
)
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
    normalize_phone_number,
)
from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    Coordinate,
    EventDetail,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.geocoding import (
    AddressResolver,
    ReverseGeocoder,
    cached_address_resolver,
    cached_reverse_geocoder,
)

__all__ = [
    "CulturalFestivalItem",
    "PublicMuseumArtItem",
    "PublicParkingLotItem",
    "PublicSpecialStreetItem",
    "PublicTouristAttractionItem",
    "cultural_festivals_to_bundles",
    "museums_to_bundles",
    "parking_lots_to_bundles",
    "special_streets_to_bundles",
    "tourist_attractions_to_bundles",
    # 상수 (호출자가 source_role/marker 등 변경하고 싶을 때 참조)
    "DATASET_KEY_CULTURAL_FESTIVALS",
    "DATASET_KEY_MUSEUMS",
    "FESTIVAL_CATEGORY",
    "FESTIVAL_MARKER_ICON",
    "FESTIVAL_MARKER_COLOR",
    "MUSEUM_CATEGORY",
    "MUSEUM_MARKER_COLOR",
    "STANDARD_DATA_PROVIDER_NAME",
    "DATASET_KEY_TOURIST_ATTRACTIONS",
    "TOURIST_ATTRACTION_CATEGORY",
    "TOURIST_MARKER_COLOR",
    "DATASET_KEY_PARKING_LOTS",
    "PARKING_CATEGORY",
    "PARKING_MARKER_COLOR",
    "DATASET_KEY_SPECIAL_STREETS",
    "SPECIAL_STREET_CATEGORY",
    "SPECIAL_STREET_MARKER_COLOR",
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
"""Maki icon name. ``docs/etl/event-feature-etl.md §4`` 표 참조."""

FESTIVAL_MARKER_COLOR: Final[str] = "P-11"
"""축제 marker color palette (자홍 계열). ``docs/etl/event-feature-etl.md §4`` 표."""

STANDARD_DATA_PROVIDER_NAME: Final[str] = _PROVIDER_NAME
"""``data.go.kr-standard`` canonical provider name 공개 alias(asset/fetcher 참조용)."""

DATASET_KEY_MUSEUMS: Final[str] = "datagokr_museums"
"""``source_records.dataset_key`` — 전국박물관미술관표준데이터(ADR-034 9단계)."""

_MUSEUM_ENTITY_TYPE: Final[str] = "museum_art_gallery"
"""provider 내 entity 종류 — ``source_records.source_entity_type``."""

MUSEUM_CATEGORY: Final[str] = PlaceCategoryCode.TOURISM_CULTURAL_FACILITY.value
"""``Feature.category`` 기본값 — 문화시설 01040000. fclty_type으로 박물관(01040100)/
미술관(01040200) sub-code로 정밀화한다."""

MUSEUM_PLACE_KIND: Final[str] = "museum"
"""``PlaceDetail.place_kind``."""

MUSEUM_MARKER_COLOR: Final[str] = "P-09"
"""박물관/미술관 marker color (ADR-029 P-01~P-16 범위)."""

_DEFAULT_MUSEUM_ICON: Final[str] = "museum"
"""category maki 매핑이 없을 때 fallback Maki icon."""


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class CulturalFestivalItem(Protocol):
    """전국문화축제표준데이터 1 row 입력 shape (``PublicCulturalFestival``).

    ``python-datagokr-api``의 ``festival.iter_all()`` 결과 model이 본 Protocol을
    **필드명 그대로** 만족한다 (ADR-044 재정렬, #374 — 종전 Protocol은
    ``management_no``/``road_address`` 등 provider에 없는 필드를 발명했었다).
    좌표는 WGS84 ``float``.

    본 dataset에는 안정 관리번호 컬럼이 없다 — 자연키는 ``name::address``
    파생 (ADR-009 ``::``, ``_museum_to_bundle`` fallback과 동일 패턴).

    원천 한국어 컬럼 → 본 Protocol 필드 매핑은 ``docs/etl/event-feature-etl.md
    §4`` 표 참조.

    Notes
    -----
    ``runtime_checkable``로 두지만 isinstance 검사는 비싸므로 본 모듈은 사용
    하지 않는다 — 함수 호출 시점에 attribute 접근으로 자연 검증.
    """

    fstvl_nm: str | None
    """축제명 (``Feature.name``). 없으면 해당 row skip."""

    opar: str | None
    """개최장소 (``EventDetail.venue_name``)."""

    fstvl_start_date: date | None
    """축제시작일자 (``EventDetail.starts_on``)."""

    fstvl_end_date: date | None
    """축제종료일자 (``EventDetail.ends_on``)."""

    fstvl_co: str | None
    """축제내용 (``SourceRecord.raw_data``에만 저장, Feature 본체는 미반영)."""

    mnnst_nm: str | None
    """주관기관명 (``EventDetail.payload['organizer_name']``)."""

    auspc_instt_nm: str | None
    """주최기관명 (``SourceRecord.raw_data``)."""

    suprt_instt_nm: str | None
    """후원기관명 (``SourceRecord.raw_data``)."""

    phone_number: str | None
    """전화번호 (``EventDetail.tel``)."""

    homepage_url: str | None
    """홈페이지주소 (``SourceRecord.raw_data``)."""

    relate_info: str | None
    """관련정보 (``SourceRecord.raw_data``)."""

    rdnmadr: str | None
    """도로명주소 (``Feature.address.road`` + ``SourceRecord.raw_address``)."""

    lnmadr: str | None
    """지번주소 (``Feature.address.legal``)."""

    latitude: float | None
    """위도 (WGS84). ``None`` 가능."""

    longitude: float | None
    """경도 (WGS84). ``None`` 가능."""

    reference_date: date | None
    """데이터기준일자 (``SourceRecord.raw_data``에 저장)."""

    instt_code: str | None
    """제공기관코드 (``SourceRecord.raw_data``)."""

    instt_nm: str | None
    """제공기관명 (``EventDetail.payload['provider_org_name']``)."""


# -- 단일 변환 ------------------------------------------------------------


def _coordinate_or_none(longitude: float | None, latitude: float | None) -> Coordinate | None:
    """좌표 쌍 → ``Coordinate``. 결측이거나 검증 실패면 좌표 미상(None) 격리.

    표준데이터 live에는 한국 경계 밖 오타 좌표가 실존한다(T-212e 실측 —
    주차장 row `lat=26.128492`, run `bc740f74`). 좌표 한 쌍의 오타가 dataset
    전체 적재를 차단하지 않도록 #386(축제 날짜 역전)과 같은 격리 패턴을
    적용한다 — 좌표만 버리고 row는 주소 단서로 적재(원본은 raw_data 보존).
    """

    if longitude is None or latitude is None:
        return None
    try:
        return Coordinate(lon=Decimal(str(longitude)), lat=Decimal(str(latitude)))
    except ValidationError:
        return None


async def _item_to_bundle(
    item: CulturalFestivalItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle | None:
    """한 row → 한 ``FeatureBundle``. 본 함수는 모듈 private.

    축제명(``fstvl_nm``)이 정규화 후에도 비면 Feature를 만들 수 없으므로
    ``None`` 반환 — ``cultural_festivals_to_bundles``가 filter (#374).

    한국어 텍스트/전화번호/법정동코드는 ``kortravelmap.core.address``의 정규화
    helper를 적극 활용해 provider raw 변형(전각 공백 / dash 변형 / 9자리
    bjd_code 등)을 흡수한다 (ADR-041).
    """

    # 0) 축제명 없는 row는 skip (자연키/Feature.name 모두 이름 의존).
    name = normalize_korean_text(item.fstvl_nm)
    if not name:
        return None

    # 1) Coordinate (결측/검증 실패면 좌표 미상 — `_coordinate_or_none`).
    coord = _coordinate_or_none(item.longitude, item.latitude)

    road_text = normalize_korean_text(item.rdnmadr)
    legal_text = normalize_korean_text(item.lnmadr)

    # 2) Geocoding 보강. 좌표 reverse를 먼저 쓰고, bjd_code가 없으면 주소
    #    geocode 결과의 structured legal_dong_code를 사용한다.
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(road=road_text, legal=legal_text))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    bjd_code = geo.bjd_code if geo is not None else None
    sigungu_code = (geo.sigungu_code if geo is not None else None) or extract_sigungu_code(bjd_code)
    sido_code = (geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)

    # 3) Address — 표시 텍스트는 item 원천(도로명/지번)을 정규화해 유지하고,
    #    행정코드/행정동명/우편번호 등은 reverse lookup 결과(geo)에서 채운다.
    #    nullable 필드는 None 유지 — Address(extra='forbid') validator 통과.
    address = Address(
        road=road_text,
        legal=legal_text,
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )

    # 4) 자연키 — 본 dataset에 안정 관리번호 컬럼이 없어 ``name::address``
    #    파생 (ADR-009 ``::``, museum/mcst fallback 패턴과 동일, #374).
    natural_key = "::".join([name, road_text or legal_text or ""])

    # 5) Raw payload (canonical JSON 직렬화 가능한 dict, provider 필드명 그대로).
    raw_data: dict[str, Any] = {
        "fstvl_nm": item.fstvl_nm,
        "opar": item.opar,
        "fstvl_start_date": (item.fstvl_start_date.isoformat() if item.fstvl_start_date else None),
        "fstvl_end_date": (item.fstvl_end_date.isoformat() if item.fstvl_end_date else None),
        "fstvl_co": item.fstvl_co,
        "mnnst_nm": item.mnnst_nm,
        "auspc_instt_nm": item.auspc_instt_nm,
        "suprt_instt_nm": item.suprt_instt_nm,
        "phone_number": item.phone_number,
        "homepage_url": item.homepage_url,
        "relate_info": item.relate_info,
        "rdnmadr": item.rdnmadr,
        "lnmadr": item.lnmadr,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "reference_date": (item.reference_date.isoformat() if item.reference_date else None),
        "instt_code": item.instt_code,
        "instt_nm": item.instt_nm,
    }
    payload_hash = make_payload_hash(raw_data)

    # 6) source_record_key (ADR-009).
    source_record_key = make_source_record_key(
        provider=_PROVIDER_NAME,
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )

    # 7) feature_id (ADR-009). bjd_code 미상 시 'global' fallback은 make_feature_id 내부.
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.EVENT.value,
        category=FESTIVAL_CATEGORY,
        source_type=f"{_PROVIDER_NAME}:{DATASET_KEY_CULTURAL_FESTIVALS}",
        source_natural_key=natural_key,
    )

    # 8) Feature 본체. 한국어 텍스트는 normalize, 전화번호는 dash 표준 표기로.
    #    실데이터에 시작/종료 역전 row(원천 오타, 예: 시작 2025-10-25/종료
    #    2024-10-01)가 존재한다(#386) — 어느 쪽이 오타인지 추정할 수 없으므로
    #    둘 다 격리(None)하고 raw_data에만 원본을 보존한다. EventDetail의
    #    ends_on >= starts_on 도메인 검증이 dataset 전체를 죽이지 않게 한다.
    starts_on = item.fstvl_start_date
    ends_on = item.fstvl_end_date
    if starts_on is not None and ends_on is not None and ends_on < starts_on:
        starts_on = None
        ends_on = None
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name=name,
        coord=coord,
        address=address,
        category=FESTIVAL_CATEGORY,
        marker_icon=FESTIVAL_MARKER_ICON,
        marker_color=FESTIVAL_MARKER_COLOR,
        detail=EventDetail(
            feature_id=feature_id,
            event_kind="festival",
            starts_on=starts_on,
            ends_on=ends_on,
            venue_name=normalize_korean_text(item.opar),
            tel=normalize_phone_number(item.phone_number),
            # area_code / sigungu_code 등 TourAPI 식별자는 visitkorea enrichment
            # 단계에서 채움 (ADR-042). 표준데이터는 영문 행정코드만.
            # key 이름 organizer_name/provider_org_name은 downstream(visitkorea
            # enrichment) 소비 계약 — 유지 (#374).
            payload={
                "organizer_name": normalize_korean_text(item.mnnst_nm),
                "provider_org_name": normalize_korean_text(item.instt_nm),
            },
        ),
    )

    # 9) SourceRecord (raw 보존).
    source_record = SourceRecord(
        provider=normalize_provider_name(_PROVIDER_NAME),
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        source_version=None,  # 표준데이터 자체에 schema version은 없음
        raw_name=item.fstvl_nm,
        raw_address=item.rdnmadr or item.lnmadr,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )

    # 10) SourceLink — primary (ADR-042 datagokr 1차 source).
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",  # name::address 파생키 직접 매핑
        confidence=100,  # 1차 source는 항상 100
        is_primary_source=True,
    )

    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


# -- 공개 API -----------------------------------------------------------


async def cultural_festivals_to_bundles(
    items: Iterable[CulturalFestivalItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
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
        좌표 → ``Address`` async 역지오코더 (``kortravelmap.geocoding.
        ReverseGeocoder``, 예: ``kor_travel_geo_reverse_geocoder(client)``).
        feature_id가 bjd_code에 의존하므로(ADR-009) feature_id 계산 전에 await해
        채운다. 중복 좌표는 내부에서 ``cached_reverse_geocoder``로 1회만 호출.
    address_resolver
        주소 → ``Address`` async 보강 geocoder. 좌표가 없거나 reverse 결과에
        bjd_code가 없을 때 road/jibun 주소로 ``/v2/geocode``를 호출해
        ``legal_dong_code``를 채운다. 중복 주소는 ``cached_address_resolver``로
        1회만 호출.

    Returns
    -------
    list[FeatureBundle]
        입력 순서 유지. 각 bundle은 ``Feature`` + ``SourceRecord`` +
        ``SourceLink``로 구성. ``feature_id`` / ``source_record_key``는
        결정적(ADR-009)이라 같은 입력은 항상 같은 ID. 축제명(``fstvl_nm``)이
        정규화 후 빈 row는 skip — 결과 길이가 입력보다 짧을 수 있다 (#374).

    Raises
    ------
    ValueError
        ``fetched_at``이 naive datetime (ADR-019 enforce — ``SourceRecord``의
        validator에서 raise).
    pydantic.ValidationError
        ``EventDetail.ends_on < starts_on`` 같은 도메인 룰 위반.

    Examples
    --------
    호출자(PinVi apps 또는 Dagster asset) 측 사용 예시:

    >>> from datetime import datetime, timezone, timedelta
    >>> from kortravelmap.providers.standard_data import (
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
    - reverse_geocoder/address_resolver가 모두 ``None``이면 ``bjd_code``는 채워지지
      않는다 — 호출자가 kor-travel-geo resolver를 주입하면 batch 보강된다.
    - visitkorea enrichment(이미지 / 상세설명 / contentId)는 Sprint 2 끝물
      별도 PR — `festival_to_enrichment_links`에서 처리.
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    bundles: list[FeatureBundle] = []
    for item in items:
        bundle = await _item_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        if bundle is not None:
            bundles.append(bundle)
    return bundles


# -- 박물관/미술관 (place, ADR-034 9단계) ---------------------------------


@runtime_checkable
class PublicMuseumArtItem(Protocol):
    """전국박물관미술관표준데이터 1 row 입력 shape (``PublicMuseumArtGallery``).

    ``python-datagokr-api``의 ``museum_art.iter_all()`` 결과 model이 본 Protocol을
    만족한다(필드명 동일). 좌표는 WGS84 ``float``.
    """

    fclty_nm: str | None
    """시설명(박물관/미술관명) — ``Feature.name``."""

    fclty_type: str | None
    """시설 구분(박물관/미술관) — category sub-code 분기 + ``facility_info``."""

    rdnmadr: str | None
    """도로명주소 — ``Feature.address.road``."""

    lnmadr: str | None
    """지번주소 — ``Feature.address.legal``."""

    latitude: float | None
    longitude: float | None

    oper_phone_number: str | None
    """운영기관 전화번호 — ``PlaceDetail.phones``."""

    homepage_url: str | None

    instt_code: str | None
    """제공기관코드 — 안정 식별자(``source_entity_id``). 없으면 name::road 파생."""

    raw: Any
    """provider 원천 dict."""


def _resolve_museum_category(fclty_type: str | None) -> str:
    """``fclty_type``으로 박물관(01040100)/미술관(01040200) 분기. 미상이면 01040000."""
    text = normalize_korean_text(fclty_type) or ""
    if "미술" in text:
        return PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_ART.value
    if "박물" in text:
        return PlaceCategoryCode.TOURISM_CULTURAL_FACILITY_MUSEUM.value
    return MUSEUM_CATEGORY


async def _museum_to_bundle(
    item: PublicMuseumArtItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    """박물관/미술관 1 row → place ``FeatureBundle``."""
    name = item.fclty_nm or ""
    coord = _coordinate_or_none(item.longitude, item.latitude)

    road_text = normalize_korean_text(item.rdnmadr)
    legal_text = normalize_korean_text(item.lnmadr)

    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(road=road_text, legal=legal_text))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    bjd_code = geo.bjd_code if geo is not None else None
    sigungu_code = (geo.sigungu_code if geo is not None else None) or extract_sigungu_code(bjd_code)
    sido_code = (geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)
    address = Address(
        road=road_text,
        legal=legal_text,
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )

    natural_key = item.instt_code or "::".join(
        [normalize_korean_text(name) or name, road_text or ""]
    )
    category = _resolve_museum_category(item.fclty_type)
    raw_data: dict[str, Any] = {
        "fclty_nm": item.fclty_nm,
        "fclty_type": item.fclty_type,
        "rdnmadr": item.rdnmadr,
        "lnmadr": item.lnmadr,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "oper_phone_number": item.oper_phone_number,
        "homepage_url": item.homepage_url,
        "instt_code": item.instt_code,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=_PROVIDER_NAME,
        dataset_key=DATASET_KEY_MUSEUMS,
        source_entity_type=_MUSEUM_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=category,
        source_type=f"{_PROVIDER_NAME}:{DATASET_KEY_MUSEUMS}",
        source_natural_key=natural_key,
    )
    phone = normalize_phone_number(item.oper_phone_number)
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=normalize_korean_text(name) or name,
        coord=coord,
        address=address,
        category=category,
        marker_icon=mapbox_maki_icon_or_none(category) or _DEFAULT_MUSEUM_ICON,
        marker_color=MUSEUM_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=MUSEUM_PLACE_KIND,
            phones=[phone] if phone else [],
            facility_info={
                k: v
                for k, v in {
                    "fclty_type": normalize_korean_text(item.fclty_type),
                    "homepage_url": item.homepage_url,
                }.items()
                if v is not None
            },
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(_PROVIDER_NAME),
        dataset_key=DATASET_KEY_MUSEUMS,
        source_entity_type=_MUSEUM_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=item.fclty_nm,
        raw_address=item.rdnmadr or item.lnmadr,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )


async def museums_to_bundles(
    items: Iterable[PublicMuseumArtItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """전국박물관미술관표준데이터 items → ``list[FeatureBundle]`` (place, ADR-034 9단계).

    각 bundle은 박물관/미술관 place Feature(category 0104xxxx) + SourceRecord + PRIMARY
    SourceLink. ``instt_code``가 없으면 ``name::road`` 파생키(ADR-009 ``::``).
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    return [
        await _museum_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        for item in items
    ]


# -- 관광지/주차장 공용 place 조립 helper (ADR-034 보조 dataset) -----------


async def _standard_place_to_bundle(
    *,
    name: str,
    natural_key: str,
    dataset_key: str,
    entity_type: str,
    category: str,
    place_kind: str,
    road_text: str | None,
    legal_text: str | None,
    latitude: float | None,
    longitude: float | None,
    phone_raw: str | None,
    facility_info: dict[str, Any],
    raw_data: dict[str, Any],
    raw_name: str | None,
    default_icon: str,
    marker_color: str,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    """data.go.kr 표준데이터 place 1건 → ``FeatureBundle`` 공용 조립(관광지/주차장)."""
    coord = _coordinate_or_none(longitude, latitude)

    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(road=road_text, legal=legal_text))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    bjd_code = geo.bjd_code if geo is not None else None
    sigungu_code = (geo.sigungu_code if geo is not None else None) or extract_sigungu_code(bjd_code)
    sido_code = (geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)
    address = Address(
        road=road_text,
        legal=legal_text,
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )

    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=_PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.PLACE.value,
        category=category,
        source_type=f"{_PROVIDER_NAME}:{dataset_key}",
        source_natural_key=natural_key,
    )
    phone = normalize_phone_number(phone_raw)
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=normalize_korean_text(name) or name,
        coord=coord,
        address=address,
        category=category,
        marker_icon=mapbox_maki_icon_or_none(category) or default_icon,
        marker_color=marker_color,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=place_kind,
            phones=[phone] if phone else [],
            facility_info={k: v for k, v in facility_info.items() if v is not None},
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(_PROVIDER_NAME),
        dataset_key=dataset_key,
        source_entity_type=entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=raw_name,
        raw_address=road_text or legal_text,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(feature=feature, source_record=source_record, source_link=source_link)


# -- 관광지 (place, ADR-034 보조) -----------------------------------------

DATASET_KEY_TOURIST_ATTRACTIONS: Final[str] = "datagokr_tourist_attractions"
"""``source_records.dataset_key`` — 전국관광지표준데이터."""

_TOURIST_ENTITY_TYPE: Final[str] = "tourist_attraction"
TOURIST_ATTRACTION_CATEGORY: Final[str] = PlaceCategoryCode.TOURISM.value
"""``Feature.category`` — 관광 01000000(일반 관광지). 세부는 trrsrt_se(facility_info)."""
TOURIST_PLACE_KIND: Final[str] = "tourist_attraction"
TOURIST_MARKER_COLOR: Final[str] = "P-02"
_DEFAULT_TOURIST_ICON: Final[str] = "attraction"


@runtime_checkable
class PublicTouristAttractionItem(Protocol):
    """전국관광지표준데이터 1 row 입력 shape (``PublicTouristAttraction``)."""

    trrsrt_nm: str | None
    trrsrt_se: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    phone_number: str | None
    instt_code: str | None
    raw: Any


async def _tourist_to_bundle(
    item: PublicTouristAttractionItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    name = item.trrsrt_nm or ""
    road_text = normalize_korean_text(item.rdnmadr)
    legal_text = normalize_korean_text(item.lnmadr)
    natural_key = item.instt_code or "::".join(
        [normalize_korean_text(name) or name, road_text or ""]
    )
    raw_data: dict[str, Any] = {
        "trrsrt_nm": item.trrsrt_nm,
        "trrsrt_se": item.trrsrt_se,
        "rdnmadr": item.rdnmadr,
        "lnmadr": item.lnmadr,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "phone_number": item.phone_number,
        "instt_code": item.instt_code,
    }
    return await _standard_place_to_bundle(
        name=name,
        natural_key=natural_key,
        dataset_key=DATASET_KEY_TOURIST_ATTRACTIONS,
        entity_type=_TOURIST_ENTITY_TYPE,
        category=TOURIST_ATTRACTION_CATEGORY,
        place_kind=TOURIST_PLACE_KIND,
        road_text=road_text,
        legal_text=legal_text,
        latitude=item.latitude,
        longitude=item.longitude,
        phone_raw=item.phone_number,
        facility_info={"trrsrt_se": normalize_korean_text(item.trrsrt_se)},
        raw_data=raw_data,
        raw_name=item.trrsrt_nm,
        default_icon=_DEFAULT_TOURIST_ICON,
        marker_color=TOURIST_MARKER_COLOR,
        fetched_at=fetched_at,
        reverse_geocoder=reverse_geocoder,
        address_resolver=address_resolver,
    )


async def tourist_attractions_to_bundles(
    items: Iterable[PublicTouristAttractionItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """전국관광지표준데이터 items → ``list[FeatureBundle]`` (place, ADR-034 보조).

    각 bundle은 관광지 place Feature(category 01000000) + SourceRecord + PRIMARY
    SourceLink. ``instt_code``가 없으면 ``name::road`` 파생키(ADR-009 ``::``).
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    return [
        await _tourist_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        for item in items
    ]


# -- 주차장 (place, ADR-034 보조) -----------------------------------------

DATASET_KEY_PARKING_LOTS: Final[str] = "datagokr_parking_lots"
"""``source_records.dataset_key`` — 전국주차장표준데이터."""

_PARKING_ENTITY_TYPE: Final[str] = "parking_lot"
PARKING_CATEGORY: Final[str] = PlaceCategoryCode.TRANSPORT_PARKING.value
"""``Feature.category`` — 주차장 06010000."""
PARKING_PLACE_KIND: Final[str] = "parking"
PARKING_MARKER_COLOR: Final[str] = "P-13"
_DEFAULT_PARKING_ICON: Final[str] = "parking"


@runtime_checkable
class PublicParkingLotItem(Protocol):
    """전국주차장표준데이터 1 row 입력 shape (``PublicParkingLot``)."""

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
    raw: Any


async def _parking_to_bundle(
    item: PublicParkingLotItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    name = item.prkplce_nm or ""
    road_text = normalize_korean_text(item.rdnmadr)
    legal_text = normalize_korean_text(item.lnmadr)
    natural_key = (
        item.prkplce_no
        or item.instt_code
        or "::".join([normalize_korean_text(name) or name, road_text or ""])
    )
    raw_data: dict[str, Any] = {
        "prkplce_no": item.prkplce_no,
        "prkplce_nm": item.prkplce_nm,
        "prkplce_se": item.prkplce_se,
        "rdnmadr": item.rdnmadr,
        "lnmadr": item.lnmadr,
        "prkcmprt": item.prkcmprt,
        "parkingchrge_info": item.parkingchrge_info,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "phone_number": item.phone_number,
        "instt_code": item.instt_code,
    }
    return await _standard_place_to_bundle(
        name=name,
        natural_key=natural_key,
        dataset_key=DATASET_KEY_PARKING_LOTS,
        entity_type=_PARKING_ENTITY_TYPE,
        category=PARKING_CATEGORY,
        place_kind=PARKING_PLACE_KIND,
        road_text=road_text,
        legal_text=legal_text,
        latitude=item.latitude,
        longitude=item.longitude,
        phone_raw=item.phone_number,
        facility_info={
            "prkplce_se": normalize_korean_text(item.prkplce_se),
            "prkcmprt": item.prkcmprt,
            "parkingchrge_info": normalize_korean_text(item.parkingchrge_info),
        },
        raw_data=raw_data,
        raw_name=item.prkplce_nm,
        default_icon=_DEFAULT_PARKING_ICON,
        marker_color=PARKING_MARKER_COLOR,
        fetched_at=fetched_at,
        reverse_geocoder=reverse_geocoder,
        address_resolver=address_resolver,
    )


async def parking_lots_to_bundles(
    items: Iterable[PublicParkingLotItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """전국주차장표준데이터 items → ``list[FeatureBundle]`` (place, category 06010000).

    안정키 ``prkplce_no``(없으면 ``instt_code``, 그것도 없으면 ``name::road`` 파생).
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    return [
        await _parking_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        for item in items
    ]


# -- 지역특화거리 (place anchor, T-223b curated source) --------------------

DATASET_KEY_SPECIAL_STREETS: Final[str] = "standard_special_streets"
"""``source_records.dataset_key`` — 전국지역특화거리표준데이터."""

_SPECIAL_STREET_ENTITY_TYPE: Final[str] = "special_street"
SPECIAL_STREET_CATEGORY: Final[str] = PlaceCategoryCode.TOURISM.value
"""``Feature.category`` — 개별 점포가 아닌 테마 구역 anchor이므로 관광 parent."""
SPECIAL_STREET_PLACE_KIND: Final[str] = "theme_area_anchor"
SPECIAL_STREET_MARKER_COLOR: Final[str] = "P-14"
_DEFAULT_SPECIAL_STREET_ICON: Final[str] = "marker"


@runtime_checkable
class PublicSpecialStreetItem(Protocol):
    """전국지역특화거리표준데이터 1 row 입력 shape (``PublicSpecialStreet``)."""

    stret_nm: str | None
    stret_intrcn: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    stret_lt: float | None
    stor_number: int | None
    appn_year: int | None
    phone_number: str | None
    institution_nm: str | None
    reference_date: date | None
    instt_code: str | None
    instt_nm: str | None
    raw: Any


async def _special_street_to_bundle(
    item: PublicSpecialStreetItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle:
    name = item.stret_nm or ""
    road_text = normalize_korean_text(item.rdnmadr)
    legal_text = normalize_korean_text(item.lnmadr)
    normalized_name = normalize_korean_text(name) or name
    natural_key = "::".join([normalized_name, road_text or legal_text or ""])
    raw_data: dict[str, Any] = {
        "stret_nm": item.stret_nm,
        "stret_intrcn": item.stret_intrcn,
        "rdnmadr": item.rdnmadr,
        "lnmadr": item.lnmadr,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "stret_lt": item.stret_lt,
        "stor_number": item.stor_number,
        "appn_year": item.appn_year,
        "phone_number": item.phone_number,
        "institution_nm": item.institution_nm,
        "reference_date": item.reference_date.isoformat()
        if item.reference_date is not None
        else None,
        "instt_code": item.instt_code,
        "instt_nm": item.instt_nm,
    }
    return await _standard_place_to_bundle(
        name=normalized_name,
        natural_key=natural_key,
        dataset_key=DATASET_KEY_SPECIAL_STREETS,
        entity_type=_SPECIAL_STREET_ENTITY_TYPE,
        category=SPECIAL_STREET_CATEGORY,
        place_kind=SPECIAL_STREET_PLACE_KIND,
        road_text=road_text,
        legal_text=legal_text,
        latitude=item.latitude,
        longitude=item.longitude,
        phone_raw=item.phone_number,
        facility_info={
            "stret_intrcn": normalize_korean_text(item.stret_intrcn),
            "stret_lt": item.stret_lt,
            "stor_number": item.stor_number,
            "appn_year": item.appn_year,
            "institution_nm": normalize_korean_text(item.institution_nm),
            "instt_code": item.instt_code,
            "instt_nm": normalize_korean_text(item.instt_nm),
            "reference_date": raw_data["reference_date"],
        },
        raw_data=raw_data,
        raw_name=item.stret_nm,
        default_icon=_DEFAULT_SPECIAL_STREET_ICON,
        marker_color=SPECIAL_STREET_MARKER_COLOR,
        fetched_at=fetched_at,
        reverse_geocoder=reverse_geocoder,
        address_resolver=address_resolver,
    )


async def special_streets_to_bundles(
    items: Iterable[PublicSpecialStreetItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """전국지역특화거리표준데이터 items → place anchor ``FeatureBundle``.

    특화거리는 개별 POI가 아니라 거리/구역 메타 source다. T-223b에서는 geometry가
    없는 원천 좌표를 ``theme_area_anchor`` place로 보존하고, 후속 curated overlay가
    PinVi 복사 시 ``pinvi_relation='theme_area_anchor'``로 해석한다.
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    bundles: list[FeatureBundle] = []
    for item in items:
        name = normalize_korean_text(item.stret_nm)
        road_text = normalize_korean_text(item.rdnmadr)
        legal_text = normalize_korean_text(item.lnmadr)
        coord = _coordinate_or_none(item.longitude, item.latitude)
        if name is None or (coord is None and road_text is None and legal_text is None):
            continue
        bundles.append(
            await _special_street_to_bundle(
                item,
                fetched_at=fetched_at,
                reverse_geocoder=geocoder,
                address_resolver=resolver,
            )
        )
    return bundles

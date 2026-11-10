"""``kortravelmap.providers.visitkorea`` — TourAPI 축제·공연·행사(``searchFestival2``) → event.

2026-11-10 소유자 결정("datagokr 축제 소스는 아예 쓰지마")으로 **TourAPI 축제가 유일한 축제
원천**이다. 종전에는 data.go.kr 전국문화축제표준데이터가 1차 source였고 본 모듈은 그 Feature에
이름으로 붙는 2차 enrichment였다(구 ADR-042). 표준데이터 키가 403(SERVICE_KEY_IS_NOT_REGISTERED,
마지막 성공 2026-10-31)이 됐고, 소유자는 표준데이터를 되살리지 않고 원천을 바꾸기로 했다.
본 모듈은 이제 Feature를 직접 만든다(``docs/etl/event-feature-etl.md``).

| dataset_key | kind | 함수 |
|-------------|------|------|
| ``visitkorea_festivals`` | ``event`` | ``tourapi_festivals_to_bundles`` |

입력·자연키·분류
---------------

- 입력 shape는 :class:`VisitKoreaFestivalItem` ``Protocol``이다. ``python-visitkorea-api``의
  ``TourItem``이 그대로 만족한다(ADR-006 — wrapper 없음).
- 자연키는 TourAPI ``contentid``다.
- 분류는 모두 축제·행사(``01090000``)이고 ``EventDetail.event_kind='festival'``이다 — TourAPI는
  축제(EV01)·공연(EV02)·행사(EV03)를 한 목록("행사정보")으로 주고, 공개 축제 API가 그 목록 전체를
  축제로 보여 준다. 세부 분류(``lclsSystm3``)는 ``payload``에 남긴다.
- 개최 기간은 원천 ``eventstartdate``/``eventenddate``(YYYYMMDD)다. 읽을 수 없거나 거꾸로 된
  날짜는 추정하지 않고 비우며, 그 행은 격리(``quarantined``)된다(#1439 행사 품질 경계).
- 개최 장소(``venue_name``)는 원천이 준 개최지 주소(``addr1`` + ``addr2``)다. 목록 응답에는
  ``eventplace``가 없다(``detailIntro2``에만 있다) — 행정구역에서 장소를 만들지 않는다.

상세(overview·homepage)
----------------------

관광지 dataset과 같은 ``detailCommon2``를 예산 안에서 채운다(``plan_attraction_details`` 재사용).
그 오퍼레이션의 일일 한도(1,000)는 두 dataset이 **나눠 쓴다** — 예산 합은 Dagster
``assets.VISITKOREA_DETAIL_DAILY_BUDGET`` 아래로 묶인다.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, Final, Protocol, runtime_checkable

from pydantic import ValidationError

from kortravelmap.category import PlaceCategoryCode
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
    normalize_phone_number,
)
from kortravelmap.core.events import has_required_event_details
from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    EventDetail,
    Feature,
    FeatureBundle,
    FeatureKind,
    FeatureQualityState,
    FeatureUrls,
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
from kortravelmap.providers.visitkorea_attractions import (
    _coordinate,
    _file_sources,
    _homepage_url,
    _iso,
    _plain_text,
    _sigungu_from_ldong,
    _split_address,
    _zipcode,
)

__all__ = [
    "VisitKoreaFestivalItem",
    "festival_window_start",
    "tourapi_festivals_to_bundles",
    "VISITKOREA_PROVIDER_NAME",
    "DATASET_KEY_VISITKOREA_FESTIVALS",
    "FESTIVAL_SOURCE_ENTITY_TYPE",
    "FESTIVAL_CATEGORY",
    "FESTIVAL_EVENT_KIND",
    "FESTIVAL_MARKER_ICON",
    "FESTIVAL_MARKER_COLOR",
    "TOURAPI_FESTIVAL_CONTENT_TYPE_ID",
]


# -- 상수 -----------------------------------------------------------------

VISITKOREA_PROVIDER_NAME: Final[str] = "python-visitkorea-api"
"""canonical provider name (ADR-024). ``normalize_provider_name``으로 정규화."""

DATASET_KEY_VISITKOREA_FESTIVALS: Final[str] = "visitkorea_festivals"
"""``provider_sync.source_records.dataset_key`` — TourAPI 축제·공연·행사(contentTypeId 15)."""

FESTIVAL_SOURCE_ENTITY_TYPE: Final[str] = "festival"
"""provider 내 entity 종류 — ``source_records.source_entity_type``."""

TOURAPI_FESTIVAL_CONTENT_TYPE_ID: Final[str] = "15"

FESTIVAL_CATEGORY: Final[str] = PlaceCategoryCode.TOURISM_EVENT.value
FESTIVAL_EVENT_KIND: Final[str] = "festival"
"""공개 축제 API(``public_views_repo``)가 고르는 ``event_kind``."""

FESTIVAL_MARKER_ICON: Final[str] = "star"
FESTIVAL_MARKER_COLOR: Final[str] = "P-11"
"""축제 marker — 종전 표준데이터 축제와 같은 모양이다(PinVi·관리자 지도가 같은 표시를 본다)."""

_ATTRIBUTION: Final[str] = "한국관광공사"
_KOGL_LICENSE: Final[dict[str, str]] = {
    "Type1": "공공누리 제1유형(출처표시)",
    "Type3": "공공누리 제3유형(출처표시·변경금지)",
}


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class VisitKoreaFestivalItem(Protocol):
    """TourAPI ``searchFestival2`` 한 item (``visitkorea.models.TourItem``이 만족)."""

    content_id: str | None
    content_type_id: str | None
    title: str | None
    addr1: str | None
    addr2: str | None
    zipcode: str | None
    tel: str | None
    first_image: str | None
    first_image2: str | None
    map_x: float | None
    map_y: float | None
    lcls_systm1: str | None
    lcls_systm2: str | None
    lcls_systm3: str | None
    l_dong_regn_cd: str | None
    l_dong_signgu_cd: str | None
    created_time: datetime | None
    modified_time: datetime | None
    copyright_division_code: str | None
    event_start_date: str | None
    """축제 시작일(YYYYMMDD)."""
    event_end_date: str | None
    """축제 종료일(YYYYMMDD)."""
    overview: str | None
    """``detailCommon2`` 상세 설명. ``None``=상세 미수신, ``""``=받았으나 비어 있음."""
    homepage: str | None


# -- 수집 창 --------------------------------------------------------------


def festival_window_start(today: date) -> date:
    """``searchFestival2`` ``eventStartDate`` — 한 해 전 그달 1일.

    원천은 그날 이후에 **끝나는** 행사를 준다(2026-11-10 실측). 공개 축제 API는 요청 달과 앞뒤 한
    달을 세므로 지난 한 해를 덮는다. 창 밖으로 밀려난 행사는 다음 적재에서 부재 퇴역한다.
    """
    year, month = (today.year - 1, today.month)
    return date(year, month, 1)


# -- 변환 -----------------------------------------------------------------


def _event_date(value: str | None) -> date | None:
    text = (value or "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return date(int(text[:4]), int(text[4:6]), int(text[6:]))
    except ValueError:
        return None


def _venue(addr1: str | None, addr2: str | None) -> str | None:
    parts = [part for part in (normalize_korean_text(addr1), normalize_korean_text(addr2)) if part]
    return " ".join(parts) or None


def _urls(homepage: str | None) -> FeatureUrls:
    url = _homepage_url(homepage)
    if url is None:
        return FeatureUrls()
    try:
        return FeatureUrls.model_validate({"homepage": url})
    except ValidationError:
        return FeatureUrls()


async def _festival_to_bundle(
    item: VisitKoreaFestivalItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle | None:
    content_id = (item.content_id or "").strip()
    name = normalize_korean_text(item.title)
    if not content_id or name is None:
        return None
    # raw_data 키는 TourItem 필드 이름 그대로다 — replay가 ``TourItem.model_validate``로 되살린다.
    raw_data: dict[str, Any] = {
        "content_id": item.content_id,
        "content_type_id": item.content_type_id,
        "title": item.title,
        "addr1": item.addr1,
        "addr2": item.addr2,
        "zipcode": item.zipcode,
        "tel": item.tel,
        "first_image": item.first_image,
        "first_image2": item.first_image2,
        "map_x": str(item.map_x) if item.map_x is not None else None,
        "map_y": str(item.map_y) if item.map_y is not None else None,
        "lcls_systm1": item.lcls_systm1,
        "lcls_systm2": item.lcls_systm2,
        "lcls_systm3": item.lcls_systm3,
        "l_dong_regn_cd": item.l_dong_regn_cd,
        "l_dong_signgu_cd": item.l_dong_signgu_cd,
        "created_time": _iso(item.created_time),
        "modified_time": _iso(item.modified_time),
        "copyright_division_code": item.copyright_division_code,
        "event_start_date": item.event_start_date,
        "event_end_date": item.event_end_date,
        "overview": item.overview,
        "homepage": item.homepage,
    }
    coord = _coordinate(item.map_x, item.map_y)
    road_text, legal_text = _split_address(item.addr1)

    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(road=road_text, legal=legal_text))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    bjd_code = geo.bjd_code if geo is not None else None
    sigungu_code = (
        (geo.sigungu_code if geo is not None else None)
        or extract_sigungu_code(bjd_code)
        or _sigungu_from_ldong(item.l_dong_regn_cd, item.l_dong_signgu_cd)
    )
    sido_code = (
        (geo.sido_code if geo is not None else None)
        or extract_sido_code(bjd_code)
        or (sigungu_code[:2] if sigungu_code else None)
    )
    address = Address(
        road=road_text or (geo.road if geo is not None else None),
        legal=legal_text or (geo.legal if geo is not None else None),
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=(geo.zipcode if geo is not None else None) or _zipcode(item.zipcode),
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )

    starts_on = _event_date(item.event_start_date)
    ends_on = _event_date(item.event_end_date)
    if starts_on is not None and ends_on is not None and ends_on < starts_on:
        # 어느 쪽이 오타인지 모른다 — 둘 다 비우고 원문은 raw_data에 둔다(#386과 같은 격리).
        starts_on = ends_on = None

    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=VISITKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_VISITKOREA_FESTIVALS,
        source_entity_type=FESTIVAL_SOURCE_ENTITY_TYPE,
        source_entity_id=content_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.EVENT.value,
        category=FESTIVAL_CATEGORY,
        source_type=f"{VISITKOREA_PROVIDER_NAME}:{DATASET_KEY_VISITKOREA_FESTIVALS}",
        source_natural_key=content_id,
    )
    license_code = (item.copyright_division_code or "").strip() or None
    payload: dict[str, Any] = {
        "content": _plain_text(item.overview),
        "lcls_systm2": item.lcls_systm2,
        "lcls_systm3": item.lcls_systm3,
        "image_url": item.first_image or None,
        "thumbnail_url": item.first_image2 or None,
        "attribution": _ATTRIBUTION,
        "license": _KOGL_LICENSE.get(license_code or "", license_code),
        "modified_time": _iso(item.modified_time),
    }
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=content_id,
        kind=FeatureKind.EVENT,
        name=name,
        coord=coord,
        address=address,
        category=FESTIVAL_CATEGORY,
        marker_icon=FESTIVAL_MARKER_ICON,
        marker_color=FESTIVAL_MARKER_COLOR,
        urls=_urls(item.homepage),
        detail=EventDetail(
            feature_id=feature_id,
            event_kind=FESTIVAL_EVENT_KIND,
            starts_on=starts_on,
            ends_on=ends_on,
            venue_name=_venue(item.addr1, item.addr2),
            tel=normalize_phone_number(item.tel),
            content_id=content_id,
            content_type_id=(item.content_type_id or "").strip() or None,
            payload={key: value for key, value in payload.items() if value is not None},
        ),
    )
    if not has_required_event_details(feature.detail):
        feature = feature.model_copy(update={"quality_state": FeatureQualityState.QUARANTINED})
    source_record = SourceRecord(
        provider=normalize_provider_name(VISITKOREA_PROVIDER_NAME),
        dataset_key=DATASET_KEY_VISITKOREA_FESTIVALS,
        source_entity_type=FESTIVAL_SOURCE_ENTITY_TYPE,
        source_entity_id=content_id,
        raw_payload_hash=payload_hash,
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
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        file_sources=_file_sources(
            feature_id=feature_id,
            source_record_key=source_record_key,
            primary=item.first_image,
            thumbnail=item.first_image2,
            alt_text=name,
            license_code=license_code,
            dataset_key=DATASET_KEY_VISITKOREA_FESTIVALS,
        ),
    )


async def tourapi_festivals_to_bundles(
    items: Iterable[VisitKoreaFestivalItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """TourAPI 축제 items → event ``FeatureBundle`` (자연키 contentid, 1차 source).

    - 좌표는 원천 ``mapx``/``mapy``(WGS84, 2026-11-10 실측 879건 모두 보유)이고 역지오코딩으로
      법정동 코드를 채운다. 실패하면 주소 해석, 그래도 없으면 TourAPI 법정동 시도·시군구 코드다.
    - contentid나 이름이 없는 행은 건너뛴다. 같은 contentid가 두 번 오면 payload hash가 작은 쪽
      하나만 남긴다(결정적).
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    resolver = cached_address_resolver(address_resolver) if address_resolver is not None else None
    chosen: dict[str, FeatureBundle] = {}
    order: list[str] = []
    for item in items:
        bundle = await _festival_to_bundle(
            item, fetched_at=fetched_at, reverse_geocoder=geocoder, address_resolver=resolver
        )
        if bundle is None:
            continue
        key = bundle.source_record.source_entity_id
        kept = chosen.get(key)
        if kept is None:
            order.append(key)
            chosen[key] = bundle
        elif bundle.source_record.raw_payload_hash < kept.source_record.raw_payload_hash:
            chosen[key] = bundle
    return [chosen[key] for key in order]

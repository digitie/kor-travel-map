"""``krtour.map.providers.krheritage`` — 국가유산청 → place/area/event 변환.

`python-krheritage-api`(국가유산청 Open API) typed model을 본 라이브러리 ``Feature``
계약으로 정규화한다 (ADR-034 provider ⑥, 8단계). ADR-006 — provider client/model을
직접 쓰고 본 모듈은 **순수 async 변환 함수**만 둔다.

입력 계약 (ADR-006, knps/datagokr 패턴 동일): 본 모듈은 krheritage를 import하지
않고 **structural Protocol**(`KrHeritageItem`/`KrHeritageEvent`)로 입력 shape만
의존한다. provider model이 필드명을 맞추거나 호출자가 가벼운 adapter를 둔다.

kind 판정 (``docs/krheritage-feature-etl.md §4``)
------------------------------------------------
``ccba_kdcd``(종목코드) 기준: 국보/보물/등록/무형 → ``place``, 사적/명승 →
``area``, 천연기념물 → 경계(geom) 있으면 ``area`` 없으면 ``place``.

geometry는 GIS(`gis_spca`/`gis_3070426`)에서 보강된 **WGS84 WKT**(MultiPolygon)를
item에 실어 넘기면 ``area``로 적재(centroid는 대표 좌표). 파싱/좌표계 변환은 GIS
응답 제공 측 책임 (ADR-044) — 본 모듈은 WKT만 받는다.

feature_id는 bjd_code 의존(ADR-009)이라 변환 함수는 async이고 reverse_geocoder가
주입되면 feature_id 계산 전에 await해 ``Address``(bjd_code)를 채운다.

ADR 참조
--------
- ADR-002 — 순수 async 변환 함수
- ADR-006 — provider 직접 사용 (wrapper class 금지), 구조 Protocol 입력
- ADR-009 — ``make_feature_id`` 결정적 생성 (bjd_code 의존)
- ADR-012 — ``Coordinate``는 WGS84; area 대표 좌표 = centroid
- ADR-034 — provider 구현 순서 (krheritage는 8단계)
- ADR-044 — 데이터 정합성·GIS 파싱 1차 책임은 provider 라이브러리
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from krtour.map.category import get_category, is_known_category_code
from krtour.map.core.address import normalize_korean_text, normalize_phone_number
from krtour.map.core.geometry import (
    AREA_GEOMETRY_TYPES,
    GeometryError,
    geometry_area_square_meters,
    normalize_geometry,
)
from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import (
    Address,
    AreaDetail,
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
from krtour.map.geocoding import ReverseGeocoder, cached_reverse_geocoder

__all__ = [
    "KrHeritageItem",
    "KrHeritageEvent",
    "heritage_items_to_bundles",
    "heritage_events_to_bundles",
    "classify_heritage_kind",
    "resolve_heritage_category",
    "PROVIDER_NAME",
    "DATASET_KEY_HERITAGE",
    "DATASET_KEY_EVENT",
    "HERITAGE_MARKER_COLOR",
]


PROVIDER_NAME: Final[str] = "python-krheritage-api"
"""canonical provider name (ADR-024)."""

DATASET_KEY_HERITAGE: Final[str] = "krheritage_heritage_features"
DATASET_KEY_EVENT: Final[str] = "krheritage_event_list"

_HERITAGE_ENTITY_TYPE: Final[str] = "heritage"
_EVENT_ENTITY_TYPE: Final[str] = "heritage_event"

HERITAGE_MARKER_COLOR: Final[str] = "P-07"
"""국가유산 marker color (보라/자홍 계열, docs §4-pre)."""

_EVENT_MARKER_ICON: Final[str] = "star"

# category 코드 → maki override (docs/krheritage-feature-etl.md §4-pre).
_HERITAGE_MAKI: Final[dict[str, str]] = {
    "01070100": "religious-buddhist",  # 전통사찰
    "01070200": "castle",  # 궁궐·왕릉
    "01070300": "monument",  # 사적·기념물
    "01070400": "village",  # 한옥·민속마을
    "01070000": "monument",  # 미분류 유산
}

# 유산 대분류 category fallback.
_HERITAGE_CATEGORY: Final[str] = "01070000"  # TOURISM_HERITAGE
_NATURAL_MONUMENT_CATEGORY: Final[str] = "01020400"  # 천연기념물 → 자연경관 계열


# -- 입력 Protocol ------------------------------------------------------------


@runtime_checkable
class KrHeritageItem(Protocol):
    """국가유산 1건(place/area)의 입력 shape (`SearchKindOpenapiDt` 등)."""

    @property
    def ccba_kdcd(self) -> str:
        """종목코드 (11 국보 / 12 보물 / 13 사적 / 15 천연기념물 / 16 명승 / 31 무형…)."""
        ...

    @property
    def ccba_asno(self) -> str:
        """지정번호."""
        ...

    @property
    def ccba_ctcd(self) -> str:
        """시도 코드."""
        ...

    @property
    def name(self) -> str:
        """국가유산 명칭 (ccbaMnm1)."""
        ...

    @property
    def heritage_type(self) -> str | None:
        """유형 텍스트 (ccmaName 등) — category 분류 보조."""
        ...

    @property
    def longitude(self) -> Decimal | float | None:
        """경도 (WGS84)."""
        ...

    @property
    def latitude(self) -> Decimal | float | None:
        """위도 (WGS84)."""
        ...

    @property
    def location_text(self) -> str | None:
        """소재지 주소 텍스트."""
        ...

    @property
    def designated_date(self) -> date | None:
        """지정일."""
        ...

    @property
    def manager(self) -> str | None:
        """관리자/관리기관."""
        ...

    @property
    def geom_wkt(self) -> str | None:
        """GIS 보강된 WGS84 WKT (MultiPolygon 등). 있으면 area geometry."""
        ...

    @property
    def raw(self) -> dict[str, Any]:
        """원천 row 전체 (raw_data JSONB 보존용)."""
        ...


@runtime_checkable
class KrHeritageEvent(Protocol):
    """무형유산/행사 1건(event)의 입력 shape (`selectEventListOpenapi`)."""

    @property
    def sn(self) -> str:
        """provider event id (자연키)."""
        ...

    @property
    def title(self) -> str:
        """행사명."""
        ...

    @property
    def start_date(self) -> date | None:
        """행사 시작일."""
        ...

    @property
    def end_date(self) -> date | None:
        """행사 종료일."""
        ...

    @property
    def venue_name(self) -> str | None:
        """개최 장소."""
        ...

    @property
    def tel(self) -> str | None:
        """문의 전화."""
        ...

    @property
    def location_text(self) -> str | None:
        """장소 주소 텍스트."""
        ...

    @property
    def longitude(self) -> Decimal | float | None:
        """경도 (WGS84). 없을 수 있음."""
        ...

    @property
    def latitude(self) -> Decimal | float | None:
        """위도 (WGS84)."""
        ...

    @property
    def raw(self) -> dict[str, Any]:
        """원천 row 전체."""
        ...


# -- 분류 helper --------------------------------------------------------------


def classify_heritage_kind(item: KrHeritageItem) -> FeatureKind:
    """``ccba_kdcd`` → FeatureKind (docs/krheritage-feature-etl.md §4)."""
    kdcd = (item.ccba_kdcd or "").strip()
    if kdcd in ("13", "16"):  # 사적 / 명승
        return FeatureKind.AREA
    if kdcd == "15":  # 천연기념물 — 경계 있으면 area, 없으면 place
        return FeatureKind.AREA if (item.geom_wkt or "").strip() else FeatureKind.PLACE
    return FeatureKind.PLACE  # 국보/보물/등록/무형/기타


def resolve_heritage_category(item: KrHeritageItem) -> str:
    """유산 유형 → category 코드 (docs/krheritage-feature-etl.md §4-pre).

    명칭/유형 텍스트의 키워드를 우선 보고, 없으면 종목코드로 fallback.
    """
    kdcd = (item.ccba_kdcd or "").strip()
    if kdcd == "15":  # 천연기념물 → 자연경관 계열
        return _NATURAL_MONUMENT_CATEGORY
    text = f"{item.name or ''} {item.heritage_type or ''}"
    if any(token in text for token in ("사찰", "전통사찰", "사지")):
        return "01070100"  # TOURISM_HERITAGE_TEMPLE
    if any(token in text for token in ("궁궐", "왕릉", "행궁", "태실", "능원")):
        return "01070200"  # TOURISM_HERITAGE_PALACE_ROYAL_TOMB
    if any(token in text for token in ("민속마을", "한옥", "전통마을", "고택")):
        return "01070400"  # TOURISM_HERITAGE_HANOK_FOLK_VILLAGE
    if kdcd in ("13", "16") or any(
        token in text for token in ("사적", "명승", "유적", "기념물")
    ):
        return "01070300"  # TOURISM_HERITAGE_HISTORIC_SITE
    return _HERITAGE_CATEGORY  # TOURISM_HERITAGE (미분류)


def _maki_for(category: str) -> str:
    """category → maki icon (유산 override 우선, 없으면 카탈로그/​fallback)."""
    override = _HERITAGE_MAKI.get(category)
    if override is not None:
        return override
    if is_known_category_code(category):
        return get_category(category).mapbox_maki_icon or "monument"
    return "monument"


def _place_kind(item: KrHeritageItem) -> str:
    kdcd = (item.ccba_kdcd or "").strip()
    if kdcd == "15":
        return "natural_heritage"
    if kdcd == "31":
        return "intangible_heritage_venue"
    return "heritage_site"


def _area_kind(item: KrHeritageItem) -> str:
    return "natural_heritage_area" if (item.ccba_kdcd or "").strip() == "15" else "heritage_area"


def _natural_key(item: KrHeritageItem) -> str:
    """place/area 자연키 = ``ccbaKdcd-ccbaAsno-ccbaCtcd`` (docs §3)."""
    return "-".join(
        (
            (item.ccba_kdcd or "").strip(),
            (item.ccba_asno or "").strip(),
            (item.ccba_ctcd or "").strip(),
        )
    )


def _coord_from(
    lon: Decimal | float | None, lat: Decimal | float | None
) -> Coordinate | None:
    """lon/lat → ``Coordinate`` (없거나 한국 경계 밖이면 ``None``)."""
    if lon is None or lat is None:
        return None
    try:
        return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))
    except (ValueError, ArithmeticError):
        return None


def _merge_address(geo: Address | None, location_text: str | None) -> Address:
    """reverse geocoding 결과(geo)에 원천 소재지 텍스트를 보강한 ``Address``."""
    loc = normalize_korean_text(location_text)
    if geo is None:
        return Address(legal=loc)
    if geo.legal is None and loc is not None:
        return geo.model_copy(update={"legal": loc})
    return geo


# -- place/area 변환 ----------------------------------------------------------


async def _heritage_item_to_bundle(
    item: KrHeritageItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    kind = classify_heritage_kind(item)
    category = resolve_heritage_category(item)
    natural_key = _natural_key(item)
    raw_data = dict(item.raw)

    # geometry: area + geom_wkt이면 normalize(centroid 대표 좌표). 불량이면 좌표만.
    geom: str | None = None
    coord = _coord_from(item.longitude, item.latitude)
    geom_wkt = (item.geom_wkt or "").strip()
    if kind is FeatureKind.AREA and geom_wkt:
        try:
            geom, centroid = normalize_geometry(
                geom_wkt, allowed_types=AREA_GEOMETRY_TYPES
            )
            coord = centroid
        except GeometryError:
            geom = None  # geometry 불량 → 좌표만 보존

    # bjd_code는 feature_id 전에 채워야 함 (ADR-009).
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    address = _merge_address(geo, item.location_text)
    bjd_code = address.bjd_code

    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=PROVIDER_NAME,
        dataset_key=DATASET_KEY_HERITAGE,
        source_entity_type=_HERITAGE_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=kind.value,
        category=category,
        source_type=f"{PROVIDER_NAME}:{DATASET_KEY_HERITAGE}",
        source_natural_key=natural_key,
    )

    name = normalize_korean_text(item.name) or item.name
    designated = (
        item.designated_date.isoformat() if item.designated_date is not None else None
    )
    detail_payload: dict[str, Any] = {
        "heritage_kind_code": (item.ccba_kdcd or "").strip(),
        "heritage_type": normalize_korean_text(item.heritage_type),
        "designated_date": designated,
    }
    detail: PlaceDetail | AreaDetail
    if kind is FeatureKind.AREA:
        # geometry 있으면 측지 면적(m²) 보강 (GIS spca, ADR-012 WGS84 입력).
        area_sqm = (
            geometry_area_square_meters(geom) if geom is not None else None
        )
        detail = AreaDetail(
            feature_id=feature_id,
            area_kind=_area_kind(item),
            boundary_source="gis" if geom is not None else None,
            area_square_meters=area_sqm,
            administrative_office=normalize_korean_text(item.manager),
            payload=detail_payload,
        )
    else:
        detail = PlaceDetail(
            feature_id=feature_id,
            place_kind=_place_kind(item),
            payload={**detail_payload, "manager": normalize_korean_text(item.manager)},
        )

    feature = Feature(
        feature_id=feature_id,
        kind=kind,
        name=name,
        coord=coord,
        address=address,
        geom=geom,
        category=category,
        marker_icon=_maki_for(category),
        marker_color=HERITAGE_MARKER_COLOR,
        detail=detail,
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(PROVIDER_NAME),
        dataset_key=DATASET_KEY_HERITAGE,
        source_entity_type=_HERITAGE_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        raw_name=item.name,
        raw_address=item.location_text,
        raw_longitude=Decimal(str(item.longitude)) if item.longitude is not None else None,
        raw_latitude=Decimal(str(item.latitude)) if item.latitude is not None else None,
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
        feature=feature, source_record=source_record, source_link=source_link
    )


async def heritage_items_to_bundles(
    items: Iterable[KrHeritageItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """국가유산 items → place/area ``FeatureBundle`` 리스트.

    Parameters
    ----------
    items
        ``KrHeritageItem`` Protocol 만족 iterable (search_list + GIS 보강 결과).
    fetched_at
        provider 호출 시각 (KST aware, ADR-019).
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더 (``krtour.map.geocoding``). 주입하면
        feature_id 계산 전에 bjd_code를 채워 'global' bucket을 벗어난다 (ADR-009).
        중복 좌표는 ``cached_reverse_geocoder``로 1회만 호출.

    Returns
    -------
    list[FeatureBundle]
        입력 순서 유지. ``ccba_kdcd``로 place/area 분기 (`classify_heritage_kind`).
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    return [
        await _heritage_item_to_bundle(
            item, fetched_at=fetched_at, reverse_geocoder=geocoder
        )
        for item in items
    ]


# -- event 변환 ---------------------------------------------------------------


async def _event_to_bundle(
    event: KrHeritageEvent,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    raw_data = dict(event.raw)
    coord = _coord_from(event.longitude, event.latitude)
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    address = _merge_address(geo, event.location_text)
    bjd_code = address.bjd_code

    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=PROVIDER_NAME,
        dataset_key=DATASET_KEY_EVENT,
        source_entity_type=_EVENT_ENTITY_TYPE,
        source_entity_id=event.sn,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.EVENT.value,
        category=_HERITAGE_CATEGORY,
        source_type=f"{PROVIDER_NAME}:{DATASET_KEY_EVENT}",
        source_natural_key=event.sn,
    )

    name = normalize_korean_text(event.title) or event.title
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name=name,
        coord=coord,
        address=address,
        category=_HERITAGE_CATEGORY,
        marker_icon=_EVENT_MARKER_ICON,
        marker_color=HERITAGE_MARKER_COLOR,
        detail=EventDetail(
            feature_id=feature_id,
            event_kind="heritage_event",
            starts_on=event.start_date,
            ends_on=event.end_date,
            venue_name=normalize_korean_text(event.venue_name),
            tel=normalize_phone_number(event.tel),
            content_id=event.sn,
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(PROVIDER_NAME),
        dataset_key=DATASET_KEY_EVENT,
        source_entity_type=_EVENT_ENTITY_TYPE,
        source_entity_id=event.sn,
        raw_payload_hash=payload_hash,
        raw_name=event.title,
        raw_address=event.location_text,
        raw_longitude=Decimal(str(event.longitude))
        if event.longitude is not None
        else None,
        raw_latitude=Decimal(str(event.latitude)) if event.latitude is not None else None,
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
        feature=feature, source_record=source_record, source_link=source_link
    )


async def heritage_events_to_bundles(
    events: Iterable[KrHeritageEvent],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """무형유산/행사 events → event ``FeatureBundle`` 리스트.

    ``EventDetail.event_kind='heritage_event'``. 자연키는 provider event id (`sn`).
    좌표가 있으면 reverse_geocoder로 bjd_code 보강 (ADR-009).
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    return [
        await _event_to_bundle(
            event, fetched_at=fetched_at, reverse_geocoder=geocoder
        )
        for event in events
    ]

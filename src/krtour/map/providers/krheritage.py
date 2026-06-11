"""``krtour.map.providers.krheritage`` — 국가유산청 → place/area/event 변환.

`python-krheritage-api`(국가유산청 Open API) typed model을 본 라이브러리 ``Feature``
계약으로 정규화한다 (ADR-034 provider ⑥, 8단계). ADR-006 — provider client/model을
직접 쓰고 본 모듈은 **순수 async 변환 함수**만 둔다.

입력 계약 (ADR-006, knps/datagokr 패턴 동일): 본 모듈은 krheritage를 import하지
않고 **structural Protocol**(`KrHeritageItem`/`KrHeritageEvent`)로 입력 shape만
의존한다. ``KrHeritageItem``은 provider 실모델 ``krheritage.models.
HeritageDetail``(#380, ADR-044 재정렬 — 복합키는 ``key`` 중첩, 명칭은
``name_ko``, 지정일은 ``designated_at`` 문자열)을 **필드명 그대로** 만족한다.

kind 판정 (``docs/krheritage-feature-etl.md §4``)
------------------------------------------------
``key.ccba_kdcd``(종목코드) 기준: 국보/보물/등록/무형/천연기념물 → ``place``,
사적/명승 → ``area``.

geometry(GIS 경계) 보강은 후속 — provider ``HeritageDetail``에는 경계 WKT
필드가 없고 GIS service(`gis_spca`/`gis_3070426`)는 아직 배선되지 않았다
(#380). 따라서 현재 area도 좌표(centroid 아님, 원천 좌표)만 가지며
천연기념물(15)은 경계 유무 분기 없이 ``place``다.

feature_id는 bjd_code 의존(ADR-009)이라 변환 함수는 async이고 reverse_geocoder 또는
address_resolver가 주입되면 feature_id 계산 전에 await해 ``Address``(bjd_code)를
채운다.

ADR 참조
--------
- ADR-002 — 순수 async 변환 함수
- ADR-006 — provider 직접 사용 (wrapper class 금지), 구조 Protocol 입력
- ADR-009 — ``make_feature_id`` 결정적 생성 (bjd_code 의존)
- ADR-012 — ``Coordinate``는 WGS84; area 대표 좌표 = 원천 좌표
  (GIS 경계 보강 후 centroid로 교체 예정, #380)
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
    FeatureFileSource,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from krtour.map.geocoding import (
    AddressResolver,
    ReverseGeocoder,
    cached_address_resolver,
    cached_reverse_geocoder,
)

__all__ = [
    "KrHeritageItem",
    "KrHeritageItemKey",
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
class KrHeritageItemKey(Protocol):
    """국가유산 복합 자연키 shape — provider ``krheritage.models.HeritageKey``.

    cha/khs OpenAPI는 단일 id 대신 종목코드+지정번호+시도코드 3-tuple이
    식별자다. provider가 ``natural_key``(``"11-00010000-11"`` 형태)를 제공한다.
    """

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
    def natural_key(self) -> str:
        """``ccbaKdcd-ccbaAsno-ccbaCtcd`` 결합 자연키 (provider 제공)."""
        ...


@runtime_checkable
class KrHeritageItem(Protocol):
    """국가유산 1건(place/area)의 입력 shape — provider ``HeritageDetail`` 정합.

    ADR-044 재정렬 (#380): provider 실모델 ``krheritage.models.HeritageDetail``
    (``SearchKindOpenapiDt``, ``HeritageSummary`` 상속)을 필드명 그대로 만족한다.
    종전 Protocol의 top-level ``ccba_*``/``name``/``heritage_type``/
    ``designated_date``/``geom_wkt``/``raw``는 provider에 없던 발명 shape였다.

    ``geom_wkt``(GIS 경계 WKT)는 Protocol에서 제거 — provider model에 해당
    필드가 없다. GIS 경계 보강(`gis_spca`/`gis_3070426`)은 후속 wiring에서
    별도 입력으로 재도입한다.

    provider model에 raw 보존 필드가 없으므로(``HeritageDetail``은 raw 미보유)
    ``SourceRecord.raw_data``는 본 모듈이 Protocol 필드에서 구성한다.
    """

    @property
    def key(self) -> KrHeritageItemKey:
        """복합 자연키 (``HeritageKey`` 중첩)."""
        ...

    @property
    def name_ko(self) -> str:
        """국가유산 국문 명칭 (``ccbaMnm1``). 정규화 후 비면 해당 row skip."""
        ...

    @property
    def category(self) -> str | None:
        """유형 텍스트 (``ccmaName``) — category 분류 보조."""
        ...

    @property
    def region(self) -> str | None:
        """시도명 (``ccbaCtcdNm``) — 소재지 fallback 텍스트."""
        ...

    @property
    def sigungu(self) -> str | None:
        """시군구명 (``ccsiName``) — 소재지 fallback 텍스트."""
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
        """소재지 상세 주소 텍스트 (``ccbaLcad``, detail 전용)."""
        ...

    @property
    def designated_at(self) -> str | None:
        """지정일 문자열 (``ccbaAsdt``, ``YYYYMMDD``) — 방어적 파싱."""
        ...

    @property
    def manager(self) -> str | None:
        """관리자/관리기관 (``ccbaAdmin``)."""
        ...

    @property
    def image_url(self) -> str | None:
        """대표 이미지 URL (``imageUrl``). 있으면 ``file_sources``로 변환."""
        ...


@runtime_checkable
class KrHeritageEvent(Protocol):
    """무형유산/행사 1건(event)의 입력 shape (`selectEventListOpenapi`)."""

    @property
    def sn(self) -> str | None:
        """provider event id (자연키). live 일부 row는 빈 값 — title 기반
        fallback 자연키 파생 (#380)."""
        ...

    @property
    def title(self) -> str | None:
        """행사명. ``sn``과 함께 모두 비면 해당 row skip."""
        ...

    @property
    def starts_on(self) -> date | None:
        """행사 시작일."""
        ...

    @property
    def ends_on(self) -> date | None:
        """행사 종료일."""
        ...

    @property
    def place(self) -> str | None:
        """개최 장소."""
        ...

    @property
    def tel_name(self) -> str | None:
        """문의 전화."""
        ...

    @property
    def address(self) -> str | None:
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
    def main_image(self) -> str | None:
        """대표 이미지 URL (``mainImage``). 있으면 ``file_sources``로 변환."""
        ...

    @property
    def raw(self) -> dict[str, Any]:
        """원천 row 전체."""
        ...


# -- 분류 helper --------------------------------------------------------------


def classify_heritage_kind(item: KrHeritageItem) -> FeatureKind:
    """``key.ccba_kdcd`` → FeatureKind (docs/krheritage-feature-etl.md §4).

    천연기념물(15)은 GIS 경계 보강이 배선될 때까지 항상 ``place`` —
    provider ``HeritageDetail``에 경계 WKT가 없다 (#380, 모듈 docstring).
    """
    kdcd = (item.key.ccba_kdcd or "").strip()
    if kdcd in ("13", "16"):  # 사적 / 명승
        return FeatureKind.AREA
    return FeatureKind.PLACE  # 국보/보물/등록/무형/천연기념물/기타


def resolve_heritage_category(item: KrHeritageItem) -> str:
    """유산 유형 → category 코드 (docs/krheritage-feature-etl.md §4-pre).

    명칭(``name_ko``)/유형 텍스트(``category``=ccmaName)의 키워드를 우선 보고,
    없으면 종목코드로 fallback.
    """
    kdcd = (item.key.ccba_kdcd or "").strip()
    if kdcd == "15":  # 천연기념물 → 자연경관 계열
        return _NATURAL_MONUMENT_CATEGORY
    text = f"{item.name_ko or ''} {item.category or ''}"
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
    kdcd = (item.key.ccba_kdcd or "").strip()
    if kdcd == "15":
        return "natural_heritage"
    if kdcd == "31":
        return "intangible_heritage_venue"
    return "heritage_site"


def _area_kind(item: KrHeritageItem) -> str:
    # 현재 area는 사적(13)/명승(16)뿐 — 15 분기는 GIS 경계 보강 후 재활성.
    return (
        "natural_heritage_area"
        if (item.key.ccba_kdcd or "").strip() == "15"
        else "heritage_area"
    )


def _natural_key(item: KrHeritageItem) -> str:
    """place/area 자연키 = provider ``key.natural_key`` (``ccbaKdcd-ccbaAsno-ccbaCtcd``)."""
    return item.key.natural_key


def _parse_designated_at(value: str | None) -> date | None:
    """``ccbaAsdt``(``YYYYMMDD`` 류) → ``date`` 방어적 파싱 (불량/공백은 None)."""
    digits = "".join(char for char in (value or "") if char.isdigit())
    if len(digits) != 8:
        return None
    try:
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    except ValueError:
        return None


def _heritage_location_text(item: KrHeritageItem) -> str | None:
    """소재지 텍스트 — ``location_text``(detail) 우선, 없으면 ``region+sigungu``."""
    location = normalize_korean_text(item.location_text)
    if location is not None:
        return location
    parts = [
        part
        for part in (
            normalize_korean_text(item.region),
            normalize_korean_text(item.sigungu),
        )
        if part
    ]
    return " ".join(parts) if parts else None


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


def _image_file_sources(
    *,
    feature_id: str,
    source_record_key: str,
    dataset_key: str,
    image_url: str | None,
    alt_text: str | None,
) -> list[FeatureFileSource]:
    """대표 이미지 URL → ``[FeatureFileSource]`` (없으면 빈 list).

    국가유산 미디어(이미지)를 load 시 객체 저장소 업로드 대상으로 담는다
    (docs/feature-files-rustfs.md). 단일 대표 이미지 → role='primary'.
    """
    url = (image_url or "").strip()
    if not url:
        return []
    return [
        FeatureFileSource(
            feature_id=feature_id,
            source_url=url,
            role="primary",
            display_order=0,
            file_type="image",
            alt_text=alt_text,
            provider=normalize_provider_name(PROVIDER_NAME),
            dataset_key=dataset_key,
            source_record_key=source_record_key,
        )
    ]


async def _heritage_item_to_bundle(
    item: KrHeritageItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle | None:
    # 명칭 없는 row는 Feature를 만들 수 없어 skip (#374 축제 패턴, #380).
    name = normalize_korean_text(item.name_ko)
    if not name:
        return None

    kind = classify_heritage_kind(item)
    category = resolve_heritage_category(item)
    natural_key = _natural_key(item)
    location_text = _heritage_location_text(item)

    # provider model에 raw 보존 필드가 없어 Protocol 필드에서 구성한다 (#380).
    raw_data: dict[str, Any] = {
        "ccba_kdcd": item.key.ccba_kdcd,
        "ccba_asno": item.key.ccba_asno,
        "ccba_ctcd": item.key.ccba_ctcd,
        "name_ko": item.name_ko,
        "category": item.category,
        "region": item.region,
        "sigungu": item.sigungu,
        "longitude": str(item.longitude) if item.longitude is not None else None,
        "latitude": str(item.latitude) if item.latitude is not None else None,
        "location_text": item.location_text,
        "designated_at": item.designated_at,
        "manager": item.manager,
        "image_url": item.image_url,
    }

    # geometry(GIS 경계) 보강은 후속 — 현재 area도 원천 좌표만 (모듈 docstring).
    coord = _coord_from(item.longitude, item.latitude)

    # bjd_code는 feature_id 전에 채워야 함 (ADR-009).
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(legal=location_text))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    address = _merge_address(geo, location_text)
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

    designated = _parse_designated_at(item.designated_at)
    detail_payload: dict[str, Any] = {
        "heritage_kind_code": (item.key.ccba_kdcd or "").strip(),
        "heritage_type": normalize_korean_text(item.category),
        "designated_date": designated.isoformat() if designated is not None else None,
    }
    detail: PlaceDetail | AreaDetail
    if kind is FeatureKind.AREA:
        # GIS 경계 미배선 — boundary/면적은 후속 보강 (모듈 docstring).
        detail = AreaDetail(
            feature_id=feature_id,
            area_kind=_area_kind(item),
            boundary_source=None,
            area_square_meters=None,
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
        raw_name=item.name_ko,
        raw_address=location_text,
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
    file_sources = _image_file_sources(
        feature_id=feature_id,
        source_record_key=source_record_key,
        dataset_key=DATASET_KEY_HERITAGE,
        image_url=getattr(item, "image_url", None),
        alt_text=name,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        file_sources=file_sources,
    )


async def heritage_items_to_bundles(
    items: Iterable[KrHeritageItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """국가유산 items → place/area ``FeatureBundle`` 리스트.

    Parameters
    ----------
    items
        ``KrHeritageItem`` Protocol 만족 iterable — provider ``HeritageDetail``
        (``iter_all_details``)이 그대로 만족한다 (ADR-044, #380).
    fetched_at
        provider 호출 시각 (KST aware, ADR-019).
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더 (``krtour.map.geocoding``). 주입하면
        feature_id 계산 전에 bjd_code를 채워 'global' bucket을 벗어난다 (ADR-009).
        중복 좌표는 ``cached_reverse_geocoder``로 1회만 호출.
    address_resolver
        주소 → ``Address`` async 보강 geocoder. 좌표 reverse 결과에 bjd_code가 없을
        때 소재지 텍스트로 kraddr-geo ``/v2/geocode``를 호출한다.

    Returns
    -------
    list[FeatureBundle]
        입력 순서 유지. ``key.ccba_kdcd``로 place/area 분기
        (`classify_heritage_kind`). 명칭(``name_ko``)이 정규화 후 빈 row는
        skip — 결과 길이가 입력보다 짧을 수 있다 (#374 패턴).
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    resolver = (
        cached_address_resolver(address_resolver)
        if address_resolver is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for item in items:
        bundle = await _heritage_item_to_bundle(
            item,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        if bundle is not None:
            bundles.append(bundle)
    return bundles


# -- event 변환 ---------------------------------------------------------------


def _event_natural_key(event: KrHeritageEvent) -> str | None:
    """event 자연키 — ``sn`` 우선, 비면 ``title::starts_on::place`` 파생.

    live 일부 행사 row는 ``sn``이 빈 값이라(run ``bd92b726``, #380) ADR-009
    검증(빈 source_entity_id 금지)에 걸린다. 그 경우 행사명+시작일+장소(없으면
    주소)로 결정적 fallback 키를 파생한다 (ADR-009 ``::`` 구분자, #374 패턴).
    ``sn``도 행사명도 없으면 ``None`` — 호출측이 해당 row를 skip한다.
    """
    sn = (event.sn or "").strip()
    if sn:
        return sn
    title = normalize_korean_text(event.title)
    if not title:
        return None
    starts = event.starts_on.isoformat() if event.starts_on is not None else ""
    place = (
        normalize_korean_text(event.place)
        or normalize_korean_text(event.address)
        or ""
    )
    return "::".join((title, starts, place))


async def _event_to_bundle(
    event: KrHeritageEvent,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
    address_resolver: AddressResolver | None,
) -> FeatureBundle | None:
    # sn도 행사명도 없는 row는 자연키/Feature.name 모두 만들 수 없어 skip.
    natural_key = _event_natural_key(event)
    if natural_key is None:
        return None

    raw_data = dict(event.raw)
    coord = _coord_from(event.longitude, event.latitude)
    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    if (geo is None or geo.bjd_code is None) and address_resolver is not None:
        resolved = await address_resolver(Address(legal=normalize_korean_text(event.address)))
        if resolved is not None and resolved.bjd_code is not None:
            geo = resolved
    address = _merge_address(geo, event.address)
    bjd_code = address.bjd_code

    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=PROVIDER_NAME,
        dataset_key=DATASET_KEY_EVENT,
        source_entity_type=_EVENT_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.EVENT.value,
        category=_HERITAGE_CATEGORY,
        source_type=f"{PROVIDER_NAME}:{DATASET_KEY_EVENT}",
        source_natural_key=natural_key,
    )

    # title이 비고 sn만 있는 row는 sn(=natural_key)을 표시명으로 강등.
    name = normalize_korean_text(event.title) or natural_key
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
            starts_on=event.starts_on,
            ends_on=event.ends_on,
            venue_name=normalize_korean_text(event.place),
            tel=normalize_phone_number(event.tel_name),
            content_id=natural_key,
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(PROVIDER_NAME),
        dataset_key=DATASET_KEY_EVENT,
        source_entity_type=_EVENT_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        raw_name=event.title,
        raw_address=event.address,
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
    file_sources = _image_file_sources(
        feature_id=feature_id,
        source_record_key=source_record_key,
        dataset_key=DATASET_KEY_EVENT,
        image_url=getattr(event, "main_image", None),
        alt_text=name,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        file_sources=file_sources,
    )


async def heritage_events_to_bundles(
    events: Iterable[KrHeritageEvent],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    address_resolver: AddressResolver | None = None,
) -> list[FeatureBundle]:
    """무형유산/행사 events → event ``FeatureBundle`` 리스트.

    ``EventDetail.event_kind='heritage_event'``. 자연키는 provider event id
    (`sn`)이며, live 일부 row처럼 ``sn``이 빈 값이면
    ``title::starts_on::place`` fallback을 파생한다 (#380, ADR-009 ``::``).
    ``sn``도 행사명도 없는 row는 skip — 결과 길이가 입력보다 짧을 수 있다.
    좌표가 있으면 reverse_geocoder로 bjd_code 보강하고, 없거나 실패하면
    address_resolver로 소재지 기반 보강을 시도한다 (ADR-009).
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    resolver = (
        cached_address_resolver(address_resolver)
        if address_resolver is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for event in events:
        bundle = await _event_to_bundle(
            event,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
            address_resolver=resolver,
        )
        if bundle is not None:
            bundles.append(bundle)
    return bundles

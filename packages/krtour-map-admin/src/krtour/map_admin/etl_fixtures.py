"""``krtour.map_admin.etl_fixtures`` — ETL preview용 fixture sample.

본 모듈은 디버그 UI에서 `/debug/etl/{provider}/{dataset}/preview?source=
fixture` 라우터가 사용하는 hard-coded fixture를 모은다. 실 provider client
없이 본 lib `providers/*` 변환 함수의 동작을 확인할 수 있다.

설계 메모
--------
- fixture는 dataclass로 정의 — provider Protocol을 만족하는 가벼운 typed
  model.
- registry는 `(provider, dataset_key)` 튜플 → `(variant, build_fixture,
  convert)` 매핑. 신규 변환 함수가 들어오면 본 registry에 1행 추가.
- live source(`?source=live`)는 본 PR에서는 501 Not Implemented — 후속 PR로
  실 provider client 호출 wiring.

ADR 참조
--------
- ADR-005 + ADR-035 — 디버그/관리 UI 운영 범위. ETL preview는 디버그 prefix.
- ADR-006 — provider wrapper 금지. 본 모듈은 본 lib 변환 함수만 호출.
- ADR-019 — KST aware datetime.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final

from krtour.map.providers.airkorea import (
    air_quality_stations_to_bundles,
    air_quality_to_weather_values,
)
from krtour.map.providers.khoa import beaches_to_bundles
from krtour.map.providers.kma import (
    short_forecast_to_weather_values,
    ultra_short_forecast_to_weather_values,
    ultra_short_nowcast_to_weather_values,
    weather_alerts_to_notice_bundles,
)
from krtour.map.providers.krairport import airports_to_bundles
from krtour.map.providers.krex import (
    rest_area_prices_to_values,
    rest_area_weather_to_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from krtour.map.providers.krforest import (
    arboretums_to_bundles,
    recreation_forests_to_bundles,
)
from krtour.map.providers.opinet import (
    prices_to_values,
    stations_to_bundles,
)
from krtour.map.providers.standard_data import (
    cultural_festivals_to_bundles,
    museums_to_bundles,
    parking_lots_to_bundles,
    tourist_attractions_to_bundles,
)

__all__ = [
    "EtlFixtureEntry",
    "FIXTURE_REGISTRY",
    "list_providers",
    "list_datasets",
    "run_fixture_preview",
]


KST = timezone(timedelta(hours=9))


def _now() -> datetime:
    """fixture 적재 시점 — 본 lib 호출자가 보통 `kst_now()` 전달, 본 모듈은
    deterministic용 fixed timestamp."""
    return datetime(2026, 5, 28, 4, 30, tzinfo=KST)


# ── datagokr 표준데이터 축제 fixture ────────────────────────────────────


@dataclass(frozen=True)
class _CulturalFestival:
    """`krtour.map.providers.standard_data.CulturalFestivalItem` Protocol 준수."""

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


def _datagokr_festival_fixture() -> Sequence[_CulturalFestival]:
    return [
        _CulturalFestival(
            management_no="CF-DEMO-001",
            festival_name="서울 봄꽃 축제",
            venue_name="여의도공원",
            start_date=date(2026, 4, 5),
            end_date=date(2026, 4, 12),
            description="봄꽃 만개 축제 (fixture demo).",
            latitude=Decimal("37.5263"),
            longitude=Decimal("126.9239"),
            road_address="서울특별시 영등포구 여의공원로 120",
            jibun_address="서울특별시 영등포구 여의도동 8",
            organizer_name="영등포구청",
            organizer_tel="02-2670-3114",
            data_reference_date=date(2026, 3, 1),
            provider_org_name="서울특별시 영등포구",
        ),
        _CulturalFestival(
            management_no="CF-DEMO-002",
            festival_name="제주 유채꽃 축제",
            venue_name="가시리 마을",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
            description="제주 유채꽃 축제 (fixture demo).",
            latitude=Decimal("33.3893"),
            longitude=Decimal("126.7831"),
            road_address="제주특별자치도 서귀포시 표선면 가시로 565번길 41",
            jibun_address="제주특별자치도 서귀포시 표선면 가시리",
            organizer_name="서귀포시청",
            organizer_tel="064-740-6000",
            data_reference_date=date(2026, 3, 1),
            provider_org_name="제주특별자치도 서귀포시",
        ),
    ]


async def _convert_datagokr_festival(items: Sequence[Any]) -> list[Any]:
    bundles = await cultural_festivals_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


# ── KMA 단기예보 fixture ───────────────────────────────────────────────


@dataclass(frozen=True)
class _ShortFcst:
    """`KmaShortForecastItem` Protocol 준수."""

    base_date: str
    base_time: str
    fcst_date: str
    fcst_time: str
    nx: int
    ny: int
    category: str
    fcst_value: str


def _short(category: str, fcst_value: str) -> _ShortFcst:
    return _ShortFcst(
        base_date="20260527",
        base_time="2300",
        fcst_date="20260528",
        fcst_time="0900",
        nx=60,
        ny=127,
        category=category,
        fcst_value=fcst_value,
    )


def _kma_short_forecast_fixture() -> Sequence[_ShortFcst]:
    return [
        _short("TMP", "23.5"),
        _short("REH", "65"),
        _short("WSD", "2.1"),
        _short("POP", "20"),
        _short("SKY", "3"),
        _short("PTY", "0"),
        _short("PCP", "강수없음"),
    ]


_FEATURE_ID_SEOUL_WEATHER = "f_global_w_seoul_demo"


async def _convert_kma_short(items: Sequence[Any]) -> list[Any]:
    values = short_forecast_to_weather_values(
        items, feature_id=_FEATURE_ID_SEOUL_WEATHER
    )
    return [v.model_dump(mode="json") for v in values]


# ── KMA 초단기실황 fixture ─────────────────────────────────────────────


@dataclass(frozen=True)
class _Nowcast:
    """`KmaUltraShortNowcastItem` Protocol 준수."""

    base_date: str
    base_time: str
    nx: int
    ny: int
    category: str
    obsr_value: str


def _now_item(category: str, obsr_value: str) -> _Nowcast:
    return _Nowcast(
        base_date="20260528",
        base_time="0400",
        nx=60,
        ny=127,
        category=category,
        obsr_value=obsr_value,
    )


def _kma_nowcast_fixture() -> Sequence[_Nowcast]:
    return [
        _now_item("T1H", "18.0"),
        _now_item("REH", "68"),
        _now_item("WSD", "1.8"),
        _now_item("RN1", "강수없음"),
        _now_item("PTY", "0"),
    ]


async def _convert_kma_nowcast(items: Sequence[Any]) -> list[Any]:
    values = ultra_short_nowcast_to_weather_values(
        items, feature_id=_FEATURE_ID_SEOUL_WEATHER
    )
    return [v.model_dump(mode="json") for v in values]


# ── KMA 초단기예보 fixture ─────────────────────────────────────────────


@dataclass(frozen=True)
class _UltraShortFcst:
    """`KmaUltraShortForecastItem` Protocol 준수."""

    base_date: str
    base_time: str
    fcst_date: str
    fcst_time: str
    nx: int
    ny: int
    category: str
    fcst_value: str


def _uf(category: str, fcst_value: str) -> _UltraShortFcst:
    return _UltraShortFcst(
        base_date="20260528",
        base_time="0330",
        fcst_date="20260528",
        fcst_time="0400",
        nx=60,
        ny=127,
        category=category,
        fcst_value=fcst_value,
    )


def _kma_ultra_short_forecast_fixture() -> Sequence[_UltraShortFcst]:
    return [
        _uf("T1H", "18.5"),
        _uf("RN1", "강수없음"),
        _uf("LGT", "0"),
        _uf("SKY", "1"),
    ]


async def _convert_kma_ultra_short_forecast(items: Sequence[Any]) -> list[Any]:
    values = ultra_short_forecast_to_weather_values(
        items, feature_id=_FEATURE_ID_SEOUL_WEATHER
    )
    return [v.model_dump(mode="json") for v in values]


# ── opinet 주유소 + 가격 fixture ───────────────────────────────────────


@dataclass(frozen=True)
class _Station:
    """`OpinetStationItem` Protocol 준수 (provider `Station` 정렬, ADR-044)."""

    uni_id: str
    name: str
    brand: object | None
    address_road: str | None
    address_jibun: str | None
    lon: float | None
    lat: float | None
    tel: str | None = None
    lpg_yn: str | bool | None = None


def _opinet_stations_fixture() -> Sequence[_Station]:
    return [
        _Station(
            uni_id="A0000001",
            name="SK주유소 강남점",
            brand="SKE",
            address_road="서울특별시 강남구 테헤란로 100",
            address_jibun=None,
            lon=127.0376,
            lat=37.4979,
            tel="02-1234-5678",
            lpg_yn="Y",
        ),
        _Station(
            uni_id="A0000002",
            name="GS칼텍스 부산점",
            brand="GSC",
            address_road="부산광역시 해운대구 해운대로 200",
            address_jibun=None,
            lon=129.1604,
            lat=35.1587,
            tel="0517491234",
            lpg_yn="N",
        ),
    ]


async def _convert_opinet_stations(items: Sequence[Any]) -> list[Any]:
    bundles = await stations_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _Price:
    """`OpinetPriceItem` Protocol 준수."""

    uni_id: str
    prodcd: str
    price: str
    trade_dt: datetime


def _opinet_prices_fixture() -> Sequence[_Price]:
    t1 = datetime(2026, 5, 28, 3, 0, tzinfo=KST)
    return [
        _Price(uni_id="A0000001", prodcd="B027", price="1820", trade_dt=t1),
        _Price(uni_id="A0000001", prodcd="D047", price="1650", trade_dt=t1),
        _Price(uni_id="A0000001", prodcd="C004", price="1100", trade_dt=t1),
    ]


_FEATURE_ID_OPINET_STATION_DEMO = "f_1156010100_p_opinet_demo"


async def _convert_opinet_prices(items: Sequence[Any]) -> list[Any]:
    values = prices_to_values(
        items, feature_id=_FEATURE_ID_OPINET_STATION_DEMO
    )
    return [v.model_dump(mode="json") for v in values]


# ── KMA weather_alerts fixture (PR#46) ─────────────────────────────────


@dataclass(frozen=True)
class _AlertRegion:
    """`KmaWeatherAlertRegion` Protocol 준수."""

    region_code: str
    region_name: str


@dataclass(frozen=True)
class _Alert:
    """`KmaWeatherAlertItem` Protocol 준수."""

    alert_id: str
    alert_type: str
    level: str | None
    title: str
    description: str | None
    issued_at: datetime
    effective_from: datetime | None
    effective_until: datetime | None
    source_agency: str | None
    regions: list[_AlertRegion]


def _kma_weather_alerts_fixture() -> Sequence[_Alert]:
    issued = datetime(2026, 7, 15, 9, 0, tzinfo=KST)
    return [
        _Alert(
            alert_id="DEMO-ALERT-001",
            alert_type="호우주의보",  # alias → 'heavy_rain_warning'
            level="주의보",
            title="수도권 호우주의보",
            description="2026-07-15 12:00부터 호우 예상.",
            issued_at=issued,
            effective_from=issued + timedelta(hours=3),
            effective_until=issued + timedelta(hours=12),
            source_agency="기상청",
            regions=[
                _AlertRegion(region_code="11B10101", region_name="서울특별시"),
                _AlertRegion(region_code="11B20201", region_name="경기도"),
            ],
        ),
        _Alert(
            alert_id="DEMO-ALERT-002",
            alert_type="폭염",
            level="경보",
            title="전국 폭염경보",
            description=None,
            issued_at=issued,
            effective_from=None,
            effective_until=None,
            source_agency="기상청",
            regions=[
                _AlertRegion(region_code="11B10101", region_name="서울특별시"),
            ],
        ),
    ]


async def _convert_kma_weather_alerts(items: Sequence[Any]) -> list[Any]:
    bundles = weather_alerts_to_notice_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


# ── krex 4 dataset fixtures (PR#45) ─────────────────────────────────────


@dataclass(frozen=True)
class _RestArea:
    """`KrexRestAreaItem` Protocol 준수 (provider ``krex.models.RestArea`` 정합).

    안정 식별자·주소 컬럼 없음 — 자연키는 변환부에서
    name+route_name+direction으로 파생 (ADR-044). lat/lon은 provider처럼 float.
    """

    name: str
    route_name: str | None
    direction: str | None
    lat: float | None
    lon: float | None
    phone_number: str | None


def _krex_rest_areas_fixture() -> Sequence[_RestArea]:
    return [
        _RestArea(
            name="서산휴게소",
            route_name="서해안고속도로",
            direction="부산방향",
            lat=36.7800,
            lon=126.6500,
            phone_number="041-1234-5678",
        ),
        _RestArea(
            name="경주휴게소",
            route_name="경부고속도로",
            direction="서울방향",
            lat=35.8400,
            lon=129.2200,
            phone_number="054-7491234",
        ),
    ]


async def _convert_krex_rest_areas(items: Sequence[Any]) -> list[Any]:
    bundles = await rest_areas_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


_FEATURE_ID_KREX_REST_AREA_DEMO = "f_global_p_krex_demo"


@dataclass(frozen=True)
class _KrexPrice:
    """`KrexRestAreaPriceItem` Protocol 준수."""

    uni_id: str
    category: str  # 'food' or 'fuel'
    product_key: str
    product_name: str | None
    price: str
    observed_at: datetime


def _krex_prices_fixture() -> Sequence[_KrexPrice]:
    obs = datetime(2026, 5, 28, 5, 0, tzinfo=KST)
    return [
        _KrexPrice(
            uni_id="RA-001",
            category="fuel",
            product_key="gasoline",
            product_name="휘발유",
            price="1820",
            observed_at=obs,
        ),
        _KrexPrice(
            uni_id="RA-001",
            category="food",
            product_key="menu_001",
            product_name="우동",
            price="5500",
            observed_at=obs,
        ),
    ]


async def _convert_krex_prices(items: Sequence[Any]) -> list[Any]:
    values = rest_area_prices_to_values(
        items, feature_id=_FEATURE_ID_KREX_REST_AREA_DEMO
    )
    return [v.model_dump(mode="json") for v in values]


@dataclass(frozen=True)
class _KrexWeather:
    """`KrexRestAreaWeatherItem` Protocol 준수."""

    uni_id: str
    metric_key: str
    value: str
    observed_at: datetime
    unit: str | None


def _krex_weather_fixture() -> Sequence[_KrexWeather]:
    obs = datetime(2026, 5, 28, 5, 0, tzinfo=KST)
    return [
        _KrexWeather(
            uni_id="RA-001",
            metric_key="T1H",
            value="22.5",
            observed_at=obs,
            unit="deg_c",
        ),
        _KrexWeather(
            uni_id="RA-001",
            metric_key="REH",
            value="60",
            observed_at=obs,
            unit="%",
        ),
    ]


async def _convert_krex_weather(items: Sequence[Any]) -> list[Any]:
    values = rest_area_weather_to_values(
        items, feature_id=_FEATURE_ID_KREX_REST_AREA_DEMO
    )
    return [v.model_dump(mode="json") for v in values]


@dataclass(frozen=True)
class _KrexNotice:
    """`KrexTrafficNoticeItem` Protocol 준수 (provider ``krex.models.Incident`` 정합).

    notice_id/title/notice_type/효력기간/severity/source_agency는 provider에 없고
    변환부가 파생한다(ADR-044).
    """

    route_no: str | None
    route_name: str | None
    direction: str | None
    incident_type: str | None
    message: str | None
    started_at: str | None
    ended_at: str | None
    raw: dict[str, Any]


def _krex_traffic_notices_fixture() -> Sequence[_KrexNotice]:
    return [
        _KrexNotice(
            route_no="0150",
            route_name="서해안고속도로",
            direction="부산방향",
            incident_type="공사",  # → roadwork
            message="서해안고속도로 105km 지점 도로공사",
            started_at="20260528",
            ended_at="20260530",
            raw={
                "routeNo": "0150",
                "incidentType": "공사",
                "message": "서해안고속도로 105km 지점 도로공사",
                "startDate": "20260528",
                "endDate": "20260530",
            },
        ),
    ]


async def _convert_krex_traffic_notices(items: Sequence[Any]) -> list[Any]:
    bundles = await traffic_notices_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _RecreationForest:
    """`RecreationForestItem` Protocol 준수 (provider `StandardRecreationForest` 정합)."""

    name: str | None
    sido_name: str | None
    forest_type: str | None
    address: str | None
    phone_number: str | None
    homepage_url: str | None
    latitude: float | None
    longitude: float | None
    institution_code: str | None
    raw: Any = None


def _krforest_recreation_forests_fixture() -> Sequence[_RecreationForest]:
    return [
        _RecreationForest(
            name="유명산자연휴양림",
            sido_name="경기도",
            forest_type="국립",
            address="경기도 가평군 설악면 유명산길 79-53",
            phone_number="031-589-5487",
            homepage_url="https://www.foresttrip.go.kr",
            latitude=37.6042,
            longitude=127.4831,
            institution_code="KFS-0001",
        ),
        _RecreationForest(
            name="대관령자연휴양림",
            sido_name="강원특별자치도",
            forest_type="국립",
            address="강원특별자치도 강릉시 성산면 대관령옛길 999",
            phone_number="033-641-9990",
            homepage_url=None,
            latitude=37.6810,
            longitude=128.7510,
            institution_code="KFS-0002",
        ),
    ]


async def _convert_krforest_recreation_forests(items: Sequence[Any]) -> list[Any]:
    bundles = await recreation_forests_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _Arboretum:
    """`ForestSpatialItem` Protocol 준수 (provider `ForestSpatialPoint` 정합)."""

    name: str | None
    category: str | None
    address: str | None
    phone_number: str | None
    homepage_url: str | None
    latitude: float | None
    longitude: float | None
    region_code: str | None
    region_name: str | None
    raw: Any = None


def _krforest_arboretums_fixture() -> Sequence[_Arboretum]:
    return [
        _Arboretum(
            name="국립세종수목원",
            category="국립수목원",
            address="세종특별자치시 수목원로 136",
            phone_number="044-251-0001",
            homepage_url="https://www.sjna.or.kr",
            latitude=36.4978,
            longitude=127.2895,
            region_code="36110",
            region_name="세종특별자치시",
        ),
    ]


async def _convert_krforest_arboretums(items: Sequence[Any]) -> list[Any]:
    bundles = await arboretums_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _Museum:
    """`PublicMuseumArtItem` Protocol 준수 (provider `PublicMuseumArtGallery` 정합)."""

    fclty_nm: str | None
    fclty_type: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    oper_phone_number: str | None
    homepage_url: str | None
    instt_code: str | None
    raw: Any = None


def _museums_fixture() -> Sequence[_Museum]:
    return [
        _Museum(
            fclty_nm="국립중앙박물관",
            fclty_type="박물관",
            rdnmadr="서울특별시 용산구 서빙고로 137",
            lnmadr="서울특별시 용산구 용산동6가 168-6",
            latitude=37.5240,
            longitude=126.9803,
            oper_phone_number="02-2077-9000",
            homepage_url="https://www.museum.go.kr",
            instt_code="MUS-0001",
        ),
        _Museum(
            fclty_nm="국립현대미술관 서울",
            fclty_type="미술관",
            rdnmadr="서울특별시 종로구 삼청로 30",
            lnmadr=None,
            latitude=37.5790,
            longitude=126.9800,
            oper_phone_number="02-3701-9500",
            homepage_url="https://www.mmca.go.kr",
            instt_code="MUS-0002",
        ),
    ]


async def _convert_museums(items: Sequence[Any]) -> list[Any]:
    bundles = await museums_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _Tourist:
    """`PublicTouristAttractionItem` Protocol 준수 (provider `PublicTouristAttraction`)."""

    trrsrt_nm: str | None
    trrsrt_se: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    phone_number: str | None
    instt_code: str | None
    raw: Any = None


def _tourist_fixture() -> Sequence[_Tourist]:
    return [
        _Tourist(
            trrsrt_nm="에버랜드",
            trrsrt_se="테마파크",
            rdnmadr="경기도 용인시 처인구 포곡읍 에버랜드로 199",
            lnmadr=None,
            latitude=37.2940,
            longitude=127.2020,
            phone_number="031-320-5000",
            instt_code="TR-0001",
        ),
    ]


async def _convert_tourist(items: Sequence[Any]) -> list[Any]:
    bundles = await tourist_attractions_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _Parking:
    """`PublicParkingLotItem` Protocol 준수 (provider `PublicParkingLot`)."""

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
    raw: Any = None


def _parking_fixture() -> Sequence[_Parking]:
    return [
        _Parking(
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
        ),
    ]


async def _convert_parking(items: Sequence[Any]) -> list[Any]:
    bundles = await parking_lots_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _Beach:
    """`OceanBeachInfoItem` Protocol 준수 (provider `OceanBeachInfo`)."""

    name: str
    sido_name: str
    gugun_name: str | None
    latitude: float | None
    longitude: float | None
    beach_kind: str | None
    image_url: str | None
    raw: Any = None


def _beach_fixture() -> Sequence[_Beach]:
    return [
        _Beach(
            name="해운대해수욕장",
            sido_name="부산광역시",
            gugun_name="해운대구",
            latitude=35.1587,
            longitude=129.1604,
            beach_kind="해수욕장",
            image_url="https://example.com/haeundae.jpg",
        ),
    ]


async def _convert_beaches(items: Sequence[Any]) -> list[Any]:
    bundles = await beaches_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _AirportCoordinate:
    """provider `Coordinate`(`.lat`/`.lon` float) 중첩 객체 흉내."""

    lat: float
    lon: float


@dataclass(frozen=True)
class _Airport:
    """`AirportMetadataItem` Protocol 준수 (provider `AirportMetadata`)."""

    code: str
    name_korean: str | None
    name_english: str
    icao_code: str | None
    municipality: str | None
    coordinate: Any


def _airport_fixture() -> Sequence[_Airport]:
    return [
        _Airport(
            code="ICN",
            name_korean="인천국제공항",
            name_english="Incheon International Airport",
            icao_code="RKSI",
            municipality="인천광역시",
            coordinate=_AirportCoordinate(lat=37.4602, lon=126.4407),
        ),
    ]


async def _convert_airports(items: Sequence[Any]) -> list[Any]:
    bundles = await airports_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _AirStation:
    """`AirQualityStationItem` Protocol 준수 (provider `Station`)."""

    station_name: str
    addr: str | None
    lat: float | None
    lon: float | None


def _airkorea_station_fixture() -> Sequence[_AirStation]:
    return [
        _AirStation(
            station_name="중구",
            addr="서울 중구 덕수궁길 15",
            lat=37.5640,
            lon=126.9750,
        ),
    ]


async def _convert_airkorea_stations(items: Sequence[Any]) -> list[Any]:
    bundles = await air_quality_stations_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _AirMeasurement:
    """`AirQualityMeasurementItem` Protocol 준수 (provider `AirQualityMeasurement`)."""

    station_name: str
    data_time: datetime | None
    sido_name: str | None = "서울"
    khai_value: int | None = None
    khai_grade: int | None = None
    pm10_value: float | None = None
    pm10_grade: int | None = None
    pm25_value: float | None = None
    pm25_grade: int | None = None
    o3_value: float | None = None
    o3_grade: int | None = None
    no2_value: float | None = None
    no2_grade: int | None = None
    so2_value: float | None = None
    so2_grade: int | None = None
    co_value: float | None = None
    co_grade: int | None = None


def _airkorea_air_quality_fixture() -> Sequence[_AirMeasurement]:
    return [
        _AirMeasurement(
            station_name="중구",
            data_time=_now(),
            khai_value=75,
            khai_grade=2,
            pm10_value=45.0,
            pm10_grade=2,
            pm25_value=18.0,
            pm25_grade=1,
            o3_value=0.035,
            o3_grade=2,
        ),
    ]


async def _convert_airkorea_air_quality(items: Sequence[Any]) -> list[Any]:
    # 측정값 변환에는 측정소→feature_id 매핑이 필요 — 데모용 station fixture로 구성.
    stations: Sequence[Any] = _airkorea_station_fixture()
    station_bundles = await air_quality_stations_to_bundles(
        stations, fetched_at=_now()
    )
    station_feature_ids = {
        bundle.source_record.source_entity_id: bundle.feature.feature_id
        for bundle in station_bundles
    }
    values = air_quality_to_weather_values(
        items, station_feature_ids=station_feature_ids
    )
    return [v.model_dump(mode="json") for v in values]


# ── Registry ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EtlFixtureEntry:
    """(provider, dataset) → (variant + fixture builder + converter) 한 row."""

    provider: str
    dataset: str
    variant: str  # "FeatureBundle" / "WeatherValue" / "PriceValue"
    description: str
    build_fixture: Callable[[], Sequence[Any]]
    convert: Callable[[Sequence[Any]], Awaitable[list[Any]]]


FIXTURE_REGISTRY: Final[tuple[EtlFixtureEntry, ...]] = (
    EtlFixtureEntry(
        provider="data.go.kr-standard",
        dataset="datagokr_cultural_festivals",
        variant="FeatureBundle",
        description=(
            "전국문화축제표준데이터 → event Feature (1차 source, ADR-042). "
            "PR#34."
        ),
        build_fixture=_datagokr_festival_fixture,
        convert=_convert_datagokr_festival,
    ),
    EtlFixtureEntry(
        provider="python-kma-api",
        dataset="kma_short_forecast",
        variant="WeatherValue",
        description="KMA 단기예보 (3시간 단위 5일). PR#38.",
        build_fixture=_kma_short_forecast_fixture,
        convert=_convert_kma_short,
    ),
    EtlFixtureEntry(
        provider="python-kma-api",
        dataset="kma_ultra_short_nowcast",
        variant="WeatherValue",
        description="KMA 초단기실황 (1시간 단위 관측). PR#39.",
        build_fixture=_kma_nowcast_fixture,
        convert=_convert_kma_nowcast,
    ),
    EtlFixtureEntry(
        provider="python-kma-api",
        dataset="kma_ultra_short_forecast",
        variant="WeatherValue",
        description="KMA 초단기예보 (30분 단위 6시간). PR#41.",
        build_fixture=_kma_ultra_short_forecast_fixture,
        convert=_convert_kma_ultra_short_forecast,
    ),
    EtlFixtureEntry(
        provider="python-opinet-api",
        dataset="opinet_fuel_station_details",
        variant="FeatureBundle",
        description="OpiNet 주유소 place Feature. PR#43.",
        build_fixture=_opinet_stations_fixture,
        convert=_convert_opinet_stations,
    ),
    EtlFixtureEntry(
        provider="python-opinet-api",
        dataset="opinet_gas_station_prices",
        variant="PriceValue",
        description="OpiNet 가격 시계열 (B027/D047/C004 데모). PR#42.",
        build_fixture=_opinet_prices_fixture,
        convert=_convert_opinet_prices,
    ),
    EtlFixtureEntry(
        provider="python-kma-api",
        dataset="kma_weather_alerts",
        variant="FeatureBundle",
        description=(
            "KMA 특보 → notice FeatureBundle (region 단위 fan-out). PR#46."
        ),
        build_fixture=_kma_weather_alerts_fixture,
        convert=_convert_kma_weather_alerts,
    ),
    EtlFixtureEntry(
        provider="python-krex-api",
        dataset="krex_rest_areas",
        variant="FeatureBundle",
        description="krex 휴게소 place Feature. PR#45.",
        build_fixture=_krex_rest_areas_fixture,
        convert=_convert_krex_rest_areas,
    ),
    EtlFixtureEntry(
        provider="python-krex-api",
        dataset="krex_rest_area_prices",
        variant="PriceValue",
        description="krex 휴게소 food/fuel 가격 시계열. PR#45.",
        build_fixture=_krex_prices_fixture,
        convert=_convert_krex_prices,
    ),
    EtlFixtureEntry(
        provider="python-krex-api",
        dataset="krex_rest_area_weather",
        variant="WeatherValue",
        description="krex 휴게소 관측 기상 (observed). PR#45.",
        build_fixture=_krex_weather_fixture,
        convert=_convert_krex_weather,
    ),
    EtlFixtureEntry(
        provider="python-krex-api",
        dataset="krex_traffic_notices",
        variant="FeatureBundle",
        description="krex 교통 공지 → notice FeatureBundle. PR#45.",
        build_fixture=_krex_traffic_notices_fixture,
        convert=_convert_krex_traffic_notices,
    ),
    EtlFixtureEntry(
        provider="python-krforest-api",
        dataset="krforest_recreation_forests",
        variant="FeatureBundle",
        description="자연휴양림 표준데이터 → place Feature (ADR-034 8단계). T-RV-53.",
        build_fixture=_krforest_recreation_forests_fixture,
        convert=_convert_krforest_recreation_forests,
    ),
    EtlFixtureEntry(
        provider="python-krforest-api",
        dataset="krforest_arboretums",
        variant="FeatureBundle",
        description="수목원/식물원(SHP) → place Feature (ADR-034 8단계). T-RV-53.",
        build_fixture=_krforest_arboretums_fixture,
        convert=_convert_krforest_arboretums,
    ),
    EtlFixtureEntry(
        provider="data.go.kr-standard",
        dataset="datagokr_museums",
        variant="FeatureBundle",
        description="전국박물관미술관표준데이터 → place Feature (ADR-034 9단계). T-RV-54.",
        build_fixture=_museums_fixture,
        convert=_convert_museums,
    ),
    EtlFixtureEntry(
        provider="data.go.kr-standard",
        dataset="datagokr_tourist_attractions",
        variant="FeatureBundle",
        description="전국관광지표준데이터 → place Feature (ADR-034 보조). T-RV-55.",
        build_fixture=_tourist_fixture,
        convert=_convert_tourist,
    ),
    EtlFixtureEntry(
        provider="data.go.kr-standard",
        dataset="datagokr_parking_lots",
        variant="FeatureBundle",
        description="전국주차장표준데이터 → place Feature (ADR-034 보조). T-RV-55.",
        build_fixture=_parking_fixture,
        convert=_convert_parking,
    ),
    EtlFixtureEntry(
        provider="python-khoa-api",
        dataset="khoa_beaches",
        variant="FeatureBundle",
        description="해양수산부 해수욕장정보 → place Feature (ADR-034 보조). T-RV-55.",
        build_fixture=_beach_fixture,
        convert=_convert_beaches,
    ),
    EtlFixtureEntry(
        provider="python-krairport-api",
        dataset="krairport_airports",
        variant="FeatureBundle",
        description="공항 메타데이터(번들 정적) → place Feature (ADR-034 보조). T-RV-55.",
        build_fixture=_airport_fixture,
        convert=_convert_airports,
    ),
    EtlFixtureEntry(
        provider="python-airkorea-api",
        dataset="airkorea_stations",
        variant="FeatureBundle",
        description="대기질 측정소 → weather kind Feature (ADR-034 보조). T-RV-55d.",
        build_fixture=_airkorea_station_fixture,
        convert=_convert_airkorea_stations,
    ),
    EtlFixtureEntry(
        provider="python-airkorea-api",
        dataset="airkorea_air_quality",
        variant="WeatherValue",
        description="대기질 측정값 → 오염물질별 WeatherValue (observed). T-RV-55d.",
        build_fixture=_airkorea_air_quality_fixture,
        convert=_convert_airkorea_air_quality,
    ),
)


def list_providers() -> list[str]:
    """등록된 provider canonical name 목록 (중복 제거, 정렬)."""
    return sorted({e.provider for e in FIXTURE_REGISTRY})


def list_datasets(provider: str) -> list[str]:
    """주어진 provider의 dataset 목록 (정렬)."""
    return sorted(e.dataset for e in FIXTURE_REGISTRY if e.provider == provider)


def _find_entry(provider: str, dataset: str) -> EtlFixtureEntry | None:
    for entry in FIXTURE_REGISTRY:
        if entry.provider == provider and entry.dataset == dataset:
            return entry
    return None


async def run_fixture_preview(provider: str, dataset: str) -> dict[str, Any]:
    """`(provider, dataset)`의 fixture를 변환 함수에 넘기고 결과를 dict로.

    Returns
    -------
    dict
        ``{"provider", "dataset", "source", "variant", "count", "items"}``.

    Raises
    ------
    KeyError
        registry에 없는 (provider, dataset) 조합.
    """
    entry = _find_entry(provider, dataset)
    if entry is None:
        raise KeyError(
            f"등록되지 않은 (provider, dataset): ({provider!r}, {dataset!r}). "
            f"등록된 목록: {[(e.provider, e.dataset) for e in FIXTURE_REGISTRY]!r}"
        )
    fixture = entry.build_fixture()
    items = await entry.convert(fixture)
    return {
        "provider": entry.provider,
        "dataset": entry.dataset,
        "source": "fixture",
        "variant": entry.variant,
        "description": entry.description,
        "count": len(items),
        "items": items,
    }

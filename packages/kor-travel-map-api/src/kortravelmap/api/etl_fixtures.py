"""``kortravelmap.api.etl_fixtures`` — ETL preview용 fixture sample.

본 모듈은 canonical ``POST /ops/datasets/{provider_dataset_id}/preview``가 사용하는
fixture를 모은다. 실 provider client 없이 본 lib ``providers/*`` 변환 함수의
동작을 확인할 수 있다.

설계 메모
--------
- fixture는 dataclass로 정의 — provider Protocol을 만족하는 가벼운 typed
  model.
- registry는 `(provider, dataset_key)` 튜플 → `(variant, build_fixture,
  convert)` 매핑. 신규 변환 함수가 들어오면 본 registry에 1행 추가.
- 제품 API의 preview는 fixture-only이며 외부 provider 호출 budget은 0이다.
- weather kind dataset(KMA·AirKorea·휴게소 기상·산악기상·산불위험)과 KMA 특보 notice
  fixture는 ADR-105로 제거했다. 산사태·교통 notice fixture는 남는다.

ADR 참조
--------
- ADR-064 — 데이터셋 상태·fixture preview는 ``/ops/datasets``로 수렴.
- ADR-006 — provider wrapper 금지. 본 모듈은 본 lib 변환 함수만 호출.
- ADR-019 — KST aware datetime.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Final

from kortravelmap.providers.khoa import beaches_to_bundles
from kortravelmap.providers.krairport import airports_to_bundles
from kortravelmap.providers.krex import (
    rest_area_prices_to_values,
    rest_areas_to_bundles,
    traffic_notices_to_bundles,
)
from kortravelmap.providers.krforest import (
    arboretums_to_bundles,
    dulle_trails_to_bundles,
    mountain_trails_to_bundles,
    recreation_forests_to_bundles,
)
from kortravelmap.providers.krforest_safety import (
    landslide_forecast_issues_to_bundles,
)
from kortravelmap.providers.mcst import (
    file_rows_to_bundles,
)
from kortravelmap.providers.opinet import (
    prices_to_values,
    stations_to_bundles,
)
from kortravelmap.providers.standard_data import (
    cultural_festivals_to_bundles,
    museums_to_bundles,
    parking_lots_to_bundles,
    tourist_attractions_to_bundles,
)

__all__ = [
    "EtlFixtureEntry",
    "FIXTURE_REGISTRY",
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
    """`kortravelmap.providers.standard_data.CulturalFestivalItem` Protocol 준수.

    provider 실모델 ``PublicCulturalFestival`` 필드명 (ADR-044 재정렬, #374).
    """

    fstvl_nm: str | None
    opar: str | None
    fstvl_start_date: date | None
    fstvl_end_date: date | None
    fstvl_co: str | None
    mnnst_nm: str | None
    auspc_instt_nm: str | None
    suprt_instt_nm: str | None
    phone_number: str | None
    homepage_url: str | None
    relate_info: str | None
    rdnmadr: str | None
    lnmadr: str | None
    latitude: float | None
    longitude: float | None
    reference_date: date | None
    instt_code: str | None
    instt_nm: str | None


def _datagokr_festival_fixture() -> Sequence[_CulturalFestival]:
    return [
        _CulturalFestival(
            fstvl_nm="서울 봄꽃 축제",
            opar="여의도공원",
            fstvl_start_date=date(2026, 4, 5),
            fstvl_end_date=date(2026, 4, 12),
            fstvl_co="봄꽃 만개 축제 (fixture demo).",
            mnnst_nm="영등포구청",
            auspc_instt_nm=None,
            suprt_instt_nm=None,
            phone_number="02-2670-3114",
            homepage_url=None,
            relate_info=None,
            rdnmadr="서울특별시 영등포구 여의공원로 120",
            lnmadr="서울특별시 영등포구 여의도동 8",
            latitude=37.5263,
            longitude=126.9239,
            reference_date=date(2026, 3, 1),
            instt_code=None,
            instt_nm="서울특별시 영등포구",
        ),
        _CulturalFestival(
            fstvl_nm="제주 유채꽃 축제",
            opar="가시리 마을",
            fstvl_start_date=date(2026, 4, 1),
            fstvl_end_date=date(2026, 4, 30),
            fstvl_co="제주 유채꽃 축제 (fixture demo).",
            mnnst_nm="서귀포시청",
            auspc_instt_nm=None,
            suprt_instt_nm=None,
            phone_number="064-740-6000",
            homepage_url=None,
            relate_info=None,
            rdnmadr="제주특별자치도 서귀포시 표선면 가시로 565번길 41",
            lnmadr="제주특별자치도 서귀포시 표선면 가시리",
            latitude=33.3893,
            longitude=126.7831,
            reference_date=date(2026, 3, 1),
            instt_code=None,
            instt_nm="제주특별자치도 서귀포시",
        ),
    ]


async def _convert_datagokr_festival(items: Sequence[Any]) -> list[Any]:
    bundles = await cultural_festivals_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


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
class _KrexNotice:
    """`KrexTrafficNoticeItem` Protocol 준수 (provider ``krex.models.Incident``
    realTimeSms shape 정합, #378).

    notice_id/title/notice_type/효력기간/severity/source_agency는 provider에 없고
    변환부가 파생한다(ADR-044). 좌표는 일부 row에만 있다(원천 경도 키는
    ``altitude`` — provider가 longitude로 매핑).
    """

    occurred_date: str | None
    occurred_time: str | None
    incident_type: str | None
    incident_type_code: str | None
    direction: str | None
    message: str | None
    point_name: str | None
    route_no: str | None
    route_name: str | None
    process_status: str | None
    process_status_code: str | None
    latitude: float | None
    longitude: float | None
    congestion_length: float | None
    series_no: int | None
    raw: dict[str, Any]


def _krex_traffic_notices_fixture() -> Sequence[_KrexNotice]:
    return [
        _KrexNotice(
            occurred_date="2026.05.28",
            occurred_time="05:00:00",
            incident_type="공사",  # → roadwork
            incident_type_code="3",
            direction="부산방향",
            message="서해안고속도로 105km 지점 도로공사",
            point_name="서산나들목",
            route_no="0150",
            route_name="서해안고속도로",
            process_status="진행",
            process_status_code="1",
            latitude=36.78,
            longitude=126.65,
            congestion_length=None,
            series_no=1,
            raw={
                "accDate": "2026.05.28",
                "accHour": "05:00:00",
                "accType": "공사",
                "accTypeCode": "3",
                "startEndTypeCode": "부산방향",
                "smsText": "서해안고속도로 105km 지점 도로공사",
                "accPointNM": "서산나들목",
                "nosunNM": "0150",
                "roadNM": "서해안고속도로",
                "accProcessNM": "진행",
                "accProcessCode": "1",
                "latitude": 36.78,
                "altitude": 126.65,
                "seriesNM": 1,
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
class _ForestTrail:
    """`ForestTrailItem` Protocol 준수 (C05A 공간 feature fixture)."""

    name: str | None
    source_id: str | None
    source_file: str | None
    layer_name: str | None
    geometry_type: str | None
    geometry: dict[str, Any] | None
    bbox: tuple[float, float, float, float] | None
    raw: Any = None


def _krforest_mountain_trails_fixture() -> Sequence[_ForestTrail]:
    return [
        _ForestTrail(
            name="북악산 등산로 1구간",
            source_id="mountain/111100101.zip/PMNTN.shp:keys:segment-1",
            source_file="mountain/111100101.zip/PMNTN.shp",
            layer_name="PMNTN",
            geometry_type="LineString",
            geometry={
                "type": "LineString",
                "coordinates": [[126.981, 37.592], [126.989, 37.598]],
            },
            bbox=(126.981, 37.592, 126.989, 37.598),
            raw={"MNTN_NM": "북악산", "PMNTN_NM": "등산로 1구간"},
        ),
        _ForestTrail(
            name="북악산 등산로 2구간",
            source_id="mountain/111100101.zip/PMNTN.shp:keys:segment-2",
            source_file="mountain/111100101.zip/PMNTN.shp",
            layer_name="PMNTN",
            geometry_type="LineString",
            geometry={
                "type": "LineString",
                "coordinates": [[126.989, 37.598], [126.997, 37.601]],
            },
            bbox=(126.989, 37.598, 126.997, 37.601),
            raw={"MNTN_NM": "북악산", "PMNTN_NM": "등산로 2구간"},
        ),
        _ForestTrail(
            name="빈 geometry는 제외",
            source_id="mountain/bad.shp:keys:empty",
            source_file="mountain/bad.shp",
            layer_name="bad",
            geometry_type="Point",
            geometry={"type": "Point", "coordinates": [126.99, 37.6]},
            bbox=(126.99, 37.6, 126.99, 37.6),
            raw={"MNTN_NM": "잘못된 행"},
        ),
    ]


def _krforest_dulle_trails_fixture() -> Sequence[_ForestTrail]:
    return [
        _ForestTrail(
            name="지리산둘레길 1구간",
            source_id="dulle/dule.shp:keys:dulle-1",
            source_file="dulle/dule.shp",
            layer_name="dule",
            geometry_type="MultiLineString",
            geometry={
                "type": "MultiLineString",
                "coordinates":[
                    [[127.7, 35.3], [127.71, 35.31]],
                    [[127.71, 35.31], [127.72, 35.32]],
                ],
            },
            bbox=(127.7, 35.3, 127.72, 35.32),
            raw={"Name": "지리산둘레길 1구간", "ID": "dulle-1"},
        ),
        _ForestTrail(
            name="지리산둘레길 2구간",
            source_id="dulle/dule.shp:keys:dulle-2",
            source_file="dulle/dule.shp",
            layer_name="dule",
            geometry_type="LineString",
            geometry={
                "type": "LineString",
                "coordinates": [[127.72, 35.32], [127.73, 35.33]],
            },
            bbox=(127.72, 35.32, 127.73, 35.33),
            raw={"Name": "지리산둘레길 2구간", "ID": "dulle-2"},
        ),
    ]


async def _convert_krforest_mountain_trails(items: Sequence[Any]) -> list[Any]:
    bundles = await mountain_trails_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


async def _convert_krforest_dulle_trails(items: Sequence[Any]) -> list[Any]:
    bundles = await dulle_trails_to_bundles(items, fetched_at=_now())
    return [b.model_dump(mode="json") for b in bundles]


@dataclass(frozen=True)
class _LandslideIssue:
    """`LandslideForecastIssueItem` Protocol 준수 (C05D lifecycle fixture)."""

    issue_kind_code: str | None
    issue_kind_name: str | None
    issuing_institution: str | None
    status: str | None
    issued_at: datetime | None
    raw: Any = None


def _krforest_landslide_issues_fixture() -> Sequence[_LandslideIssue]:
    issued_at = _now()
    return [
        _LandslideIssue(
            issue_kind_code="1",
            issue_kind_name="산사태주의보",
            issuing_institution="강원특별자치도",
            status="발령",
            issued_at=issued_at,
            raw={"kind": "1", "status": "발령"},
        ),
        _LandslideIssue(
            issue_kind_code="1",
            issue_kind_name="산사태주의보",
            issuing_institution="강원특별자치도",
            status="해제",
            issued_at=issued_at,
            raw={"kind": "1", "status": "해제"},
        ),
    ]


async def _convert_krforest_landslide_issues(items: Sequence[Any]) -> list[Any]:
    bundles = landslide_forecast_issues_to_bundles(items, fetched_at=_now())
    return [bundle.model_dump(mode="json") for bundle in bundles]


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


# MCST 파일데이터 CSV row fixture — 방언별 대표 1개씩 (T-220 재배선, #395).
# 컬럼/값 모양은 2026-06-12 live CSV 실측 샘플 기반.


def _mcst_kcisa_common_fixture() -> Sequence[dict[str, Any]]:
    """KCISA 공통 방언 A 대표(world_restaurants_csv) — N/E 접두 COORDINATES."""
    return [
        {
            "TITLE": "데모 세계음식점",
            "ISSUEDDATE": "2022-11-30",
            "CATEGORY1": "음식점/유흥시설",
            "CATEGORY2": "남미음식",
            "CATEGORY3": "",
            "INFORMATION": "무료주차 불가|발렛주차 불가",
            "TEL": "0507-0000-0000",
            "OPERATINGTIME": "월-금 11시-21시30분",
            "ADDRESS": "(17982)경기도 평택시 팽성읍 안정순환로222번길 92",
            "COORDINATES": "N36.960756, E127.043367",
            "RNUM": "1",
        },
    ]


async def _convert_mcst_kcisa_common(items: Sequence[Any]) -> list[Any]:
    bundles = await file_rows_to_bundles(
        items, slug="world_restaurants_csv", fetched_at=_now()
    )
    return [b.model_dump(mode="json") for b in bundles]


def _mcst_cntc_resrce_fixture() -> Sequence[dict[str, Any]]:
    """CNTC_RESRCE 방언 대표(independent_bookstores_csv) — 평문 lat-lon."""
    return [
        {
            "CNTC_RESRCE_ID": "B553457-04-012",
            "CNTC_RESRCE_NO": "1",
            "TITLE": "데모 독립서점",
            "ISSUED_DATE": "2024-10-23",
            "SUBJECT_KEYWORD": "독립서점 , 일반",
            "DESCRIPTION": "평일개점마감시간 : 11:00~21:00",
            "SUB_DESCRIPTION": "큐레이션 서점",
            "ADDRESS": "(41946) 대구광역시 중구 달구벌대로447길 72-1",
            "CONTACT_POINT": "0530000000",
            "COORDINATES": "35.86561079 , 128.6083915",
            "RNUM": "1",
        },
    ]


async def _convert_mcst_cntc_resrce(items: Sequence[Any]) -> list[Any]:
    bundles = await file_rows_to_bundles(
        items, slug="independent_bookstores_csv", fetched_at=_now()
    )
    return [b.model_dump(mode="json") for b in bundles]


def _mcst_split_coord_fixture() -> Sequence[dict[str, Any]]:
    """분리좌표 방언 대표(children_bookstores_csv) — FCLTY_LA/FCLTY_LO."""
    return [
        {
            "RNUM": "1",
            "ESNTL_ID": "KCCBSPO22N000000085",
            "FCLTY_NM": "데모 아동서점",
            "LCLAS_NM": "아동서점",
            "MLSFC_NM": "아동서적",
            "ZIP_NO": "14061",
            "FCLTY_ROAD_NM_ADDR": "경기 안양시 동안구 흥안대로 460 1층",
            "FCLTY_LA": "37.39513617",
            "FCLTY_LO": "126.9760656",
            "TEL_NO": "0310000000",
            "RSTDE_GUID_CN": "일요일휴무",
        },
    ]


async def _convert_mcst_split_coord(items: Sequence[Any]) -> list[Any]:
    bundles = await file_rows_to_bundles(
        items, slug="children_bookstores_csv", fetched_at=_now()
    )
    return [b.model_dump(mode="json") for b in bundles]


# ── Registry ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EtlFixtureEntry:
    """(provider, dataset) → (variant + fixture builder + converter) 한 row."""

    provider: str
    dataset: str
    variant: str  # "FeatureBundle" / "PriceValue"
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
        provider="python-krforest-api",
        dataset="krforest_mountain_trails",
        variant="FeatureBundle",
        description="산림청 PBD0000041 등산로 SHP → route Feature(C05A).",
        build_fixture=_krforest_mountain_trails_fixture,
        convert=_convert_krforest_mountain_trails,
    ),
    EtlFixtureEntry(
        provider="python-krforest-api",
        dataset="krforest_dulle_trails",
        variant="FeatureBundle",
        description="산림청 PBD0000031 둘레길 SHP → route Feature(C05A).",
        build_fixture=_krforest_dulle_trails_fixture,
        convert=_convert_krforest_dulle_trails,
    ),
    EtlFixtureEntry(
        provider="python-krforest-api",
        dataset="krforest_landslide_forecast_issues",
        variant="FeatureBundle",
        description="산림청 15074798 산사태 예보발령·해제 → notice Feature(C05D).",
        build_fixture=_krforest_landslide_issues_fixture,
        convert=_convert_krforest_landslide_issues,
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
        provider="python-mcst-api",
        dataset="mcst_world_restaurants_csv",
        variant="FeatureBundle",
        description=(
            "MCST 파일데이터 KCISA 공통 방언 A(8 dataset 공용 변환 대표) → "
            "place Feature. #395."
        ),
        build_fixture=_mcst_kcisa_common_fixture,
        convert=_convert_mcst_kcisa_common,
    ),
    EtlFixtureEntry(
        provider="python-mcst-api",
        dataset="mcst_independent_bookstores_csv",
        variant="FeatureBundle",
        description=(
            "MCST 파일데이터 CNTC_RESRCE 방언(서점 2 dataset 공용 변환 대표) → "
            "place Feature. #395."
        ),
        build_fixture=_mcst_cntc_resrce_fixture,
        convert=_convert_mcst_cntc_resrce,
    ),
    EtlFixtureEntry(
        provider="python-mcst-api",
        dataset="mcst_children_bookstores_csv",
        variant="FeatureBundle",
        description=(
            "MCST 파일데이터 분리좌표 방언(FCLTY_LA/LO) → place Feature. #395."
        ),
        build_fixture=_mcst_split_coord_fixture,
        convert=_convert_mcst_split_coord,
    ),
)


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

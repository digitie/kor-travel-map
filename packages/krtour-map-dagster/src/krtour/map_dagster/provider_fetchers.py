"""Provider public client live record fetcher (T-RV-04b).

각 provider별 sync fetch 함수는 ``KrtourMapSettings``에서 credential을 읽어
provider **public client**(ADR-006 — wrapper 금지, client 직접 사용)를 열고
raw record를 lazily yield한다. 본 모듈은 ``resources.py``의
``build_provider_record_live_resource``가 resource value로 노출하며, Dagster
feature-load asset의 ``_record_batches``가 sync ``Iterable``로 소비한다.

provider 라이브러리(예: ``python-datagokr-api``)는 ADR-044 로컬 체크아웃이며
일부 환경에서 부재할 수 있으므로, 각 fetch 함수는 client를 **함수 내부에서
lazy import**한다 — 본 모듈 import만으로 provider 패키지를 hard-require 하지
않는다.
"""

from __future__ import annotations

import importlib
import pathlib
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Final, cast

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from krtour.map.settings import KrtourMapSettings

__all__ = [
    "ProviderCredentialMissing",
    "fetch_airkorea_air_quality",
    "fetch_airkorea_stations",
    "fetch_datagokr_cultural_festivals",
    "fetch_khoa_beaches",
    "fetch_knps_geometry_records",
    "fetch_knps_point_records",
    "fetch_krairport_airports",
    "fetch_krex_rest_areas",
    "fetch_krex_traffic_notices",
    "fetch_krforest_arboretums",
    "fetch_krforest_recreation_forests",
    "fetch_krheritage_events",
    "fetch_mois_license_records",
    "fetch_opinet_stations",
    "fetch_standard_museums",
    "fetch_standard_parking_lots",
    "fetch_standard_tourist_attractions",
    "fetch_visitkorea_festival_events",
]


class ProviderCredentialMissing(RuntimeError):
    """provider live fetch에 필요한 credential이 설정되지 않았을 때."""


def fetch_datagokr_cultural_festivals(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """전국문화축제표준데이터 record를 datagokr public client로 stream한다.

    ``settings.data_go_kr_service_key``에서 service key를 읽어
    ``DataGoKrClient(api_key=...)``를 열고 ``client.festival.iter_all()``의
    record(``PublicCulturalFestival``, ``CulturalFestivalItem`` Protocol 충족)를
    lazily yield한다. generator가 살아 있는 동안 client는 열려 있고,
    소비 종료(또는 close)시 ``finally``에서 ``client.close()``로 닫는다.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "datagokr cultural festivals live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    # provider public client는 ADR-044 로컬 체크아웃이며 hard dependency가
    # 아니므로(부재 가능), boto3와 동일하게 import time이 아닌 호출 시점에
    # ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    datagokr = cast(Any, importlib.import_module("datagokr"))

    client = datagokr.DataGoKrClient(api_key=api_key)
    try:
        yield from client.festival.iter_all()
    finally:
        client.close()


def fetch_krheritage_events(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """국가유산 행사(event) record를 krheritage public client로 stream한다.

    ``settings.data_go_kr_service_key``에서 service key를 읽어
    ``HeritageClient(api_key=...)``를 열고 ``client.event.iter_months()``의
    record(``HeritageEvent``, ``KrHeritageEvent`` Protocol 충족)를 lazily yield
    한다. ``iter_months``는 provider 내장 rolling window(기본 ``months_back=1,
    months_ahead=12``)를 그대로 정책으로 쓴다 — custom 인자를 넘기지 않는다.
    generator가 살아 있는 동안 client는 열려 있고, 소비 종료(또는 close)시
    ``finally``에서 ``client.close()``로 닫는다.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krheritage events live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    # provider public client는 ADR-044 로컬 체크아웃이며 hard dependency가
    # 아니므로(부재 가능), datagokr와 동일하게 import time이 아닌 호출 시점에
    # ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    krheritage = cast(Any, importlib.import_module("krheritage"))

    client = krheritage.HeritageClient(api_key=api_key)
    try:
        yield from client.event.iter_months()
    finally:
        client.close()


def fetch_krex_rest_areas(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """고속도로 휴게소(rest_area) record를 krex public client로 stream한다.

    ``settings.krex_go_api_key``(source ``KEX_GO_API_KEY``)에서 data.go.kr
    service key를 읽어 ``KrexClient(go_api_key=...)``를 열고
    ``client.restarea.list_all(num_of_rows=1000, page_no=N)``을 페이지네이션하며
    record(``krex.models.RestArea``, ``KrexRestAreaItem`` Protocol 충족)를 lazily
    yield한다. ``list_all``은 ``tn_pubr_public_rest_area_api`` (data.go.kr) 호출
    이므로 EX key가 아닌 **go key**를 쓴다.

    이 dataset에는 안정 식별자가 없어 krtour 변환부가 name+route_name+direction
    으로 자연키를 파생한다(ADR-044). 페이지네이션은 빈 페이지 / 마지막 페이지
    (``len(items) < num_of_rows``) / ``total_count`` 도달 중 먼저 만나는 조건에서
    멈춘다. generator 소비 종료(또는 close)시 ``finally``에서 ``client.close()``.
    """
    secret = settings.krex_go_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krex rest_areas live fetch에는 "
            "KRTOUR_MAP_KREX_GO_API_KEY (source KEX_GO_API_KEY / "
            "DATA_GO_KR_SERVICE_KEY)가 필요하다."
        )
    api_key = secret.get_secret_value()

    # provider public client는 ADR-044 로컬 체크아웃이며 hard dependency가
    # 아니므로(부재 가능), datagokr와 동일하게 import time이 아닌 호출 시점에
    # ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    krex = cast(Any, importlib.import_module("krex"))

    client = krex.KrexClient(go_api_key=api_key)
    num_of_rows = 1000
    try:
        page_no = 1
        seen = 0
        while True:
            page = client.restarea.list_all(
                num_of_rows=num_of_rows, page_no=page_no
            )
            items = list(page.items)
            if not items:
                break
            yield from items
            seen += len(items)
            total_count = page.total_count
            if len(items) < num_of_rows:
                break
            if total_count is not None and seen >= total_count:
                break
            page_no += 1
    finally:
        client.close()


def fetch_mois_license_records(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """미리 sync된 MOIS 소스 SQLite DB에서 영업중 인허가 record를 stream한다.

    MOIS 인허가는 live REST가 아니라 별도 sync step(Phase A — LOCALDATA
    download/적재, **본 task scope 밖**)이 채워둔 SQLite 소스 DB를 읽는다.
    본 fetcher(Phase B)는 그 DB를 **읽기만** 한다.

    ``settings.mois_source_db_path``(env ``KRTOUR_MAP_MOIS_SOURCE_DB_PATH``)에서
    소스 DB 경로를 읽어, 미설정/파일 부재 시 ``ProviderCredentialMissing``으로
    명확히 실패한다. 경로가 유효하면 sqlite engine + ``Session``을 열고
    ``mois.db.iter_open_place_records(session, service_slugs=...)``의 record
    (``mois.db.PlaceRecord``, krtour ``MoisLicensePlaceRecord`` Protocol 충족)를
    lazily yield한다. scope는 krtour ``PROMOTED_SERVICE_SLUGS``(42 업종)로 좁힌다.
    generator가 살아 있는 동안 session은 열려 있고, 소비 종료(또는 close)시
    ``finally``에서 ``session.close()`` + ``engine.dispose()``로 정리한다.
    """
    db_path = settings.mois_source_db_path
    if db_path is None or not pathlib.Path(db_path).is_file():
        raise ProviderCredentialMissing(
            "MOIS 인허가 live fetch에는 미리 sync된 MOIS 소스 SQLite DB가 "
            "필요하다. Phase A sync(LOCALDATA download/적재)를 먼저 실행하고 "
            "DB 경로를 설정하라. (KRTOUR_MAP_MOIS_SOURCE_DB_PATH)"
        )

    # provider record 모델/streaming 함수는 ADR-044 로컬 체크아웃이며 hard
    # dependency가 아니므로(부재 가능), datagokr와 동일하게 import time이 아닌
    # 호출 시점에 ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    mois_db = cast(Any, importlib.import_module("mois.db"))
    # PROMOTED_SERVICE_SLUGS는 krtour(본 repo)이므로 top-level import으로 충분.
    from krtour.map.providers.mois import PROMOTED_SERVICE_SLUGS

    engine = create_engine(f"sqlite:///{db_path}")
    session = Session(engine)
    try:
        yield from mois_db.iter_open_place_records(
            session,
            service_slugs=tuple(sorted(PROMOTED_SERVICE_SLUGS)),
        )
    finally:
        session.close()
        engine.dispose()


def fetch_krex_traffic_notices(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """고속도로 교통 공지(돌발 incident) record를 krex public client로 stream한다.

    ``settings.krex_ex_api_key``(source ``KEX_GO_API_KEY``)에서 EX OpenAPI key를
    읽어 ``KrexClient(ex_api_key=...)``를 열고 ``client.traffic.incident(
    num_of_rows=1000, page_no=N)``을 페이지네이션하며 record(``krex.models.
    Incident``, ``KrexTrafficNoticeItem`` Protocol 충족)를 lazily yield한다.
    rest_areas와 달리 EX endpoint이므로 go key가 아닌 **ex key**를 쓴다.

    EX 돌발 feed는 휘발성(transient) — 해소된 사건은 사라진다(ADR-044). 페이지
    네이션은 빈 페이지 / 마지막 페이지(``len(items) < num_of_rows``) /
    ``total_count`` 도달 중 먼저 만나는 조건에서 멈춘다. generator 소비 종료
    (또는 close)시 ``finally``에서 ``client.close()``.
    """
    secret = settings.krex_ex_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krex traffic_notices live fetch에는 "
            "KRTOUR_MAP_KREX_EX_API_KEY (source KEX_GO_API_KEY)가 필요하다."
        )
    api_key = secret.get_secret_value()

    # provider public client는 ADR-044 로컬 체크아웃이며 hard dependency가
    # 아니므로(부재 가능), datagokr와 동일하게 import time이 아닌 호출 시점에
    # ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    krex = cast(Any, importlib.import_module("krex"))

    client = krex.KrexClient(ex_api_key=api_key)
    num_of_rows = 1000
    try:
        page_no = 1
        seen = 0
        while True:
            page = client.traffic.incident(
                num_of_rows=num_of_rows, page_no=page_no
            )
            items = list(page.items)
            if not items:
                break
            yield from items
            seen += len(items)
            total_count = page.total_count
            if len(items) < num_of_rows:
                break
            if total_count is not None and seen >= total_count:
                break
            page_no += 1
    finally:
        client.close()


async def fetch_knps_point_records(
    settings: KrtourMapSettings,
) -> AsyncIterator[Any]:
    """KNPS point file dataset record를 knps public client로 stream한다.

    ``settings.knps_point_dataset_key``의 keyless file dataset을 받아
    ``client.files.read_place_records(key)``의 typed record(``KnpsPlaceRecord``,
    krtour ``KnpsPointRecord`` Protocol 충족 — provider가 헤더 정규화)를 yield한다.
    krtour 측 best-guess 컬럼 매핑이 아니라 provider(python-knps-api>=0.2)의 typed
    record를 직접 소비한다(ADR-044). 다운로드/파싱은 async이므로 async generator다.
    dataset key가 카탈로그에 없으면 명확히 실패한다(keyless라 credential은 없음).
    """
    dataset_key = settings.knps_point_dataset_key
    knps = cast(Any, importlib.import_module("knps"))
    client = knps.KnpsClient()
    try:
        records = await client.files.read_place_records(dataset_key)
        for record in records:
            yield record
    finally:
        await client.aclose()


async def fetch_knps_geometry_records(
    settings: KrtourMapSettings,
) -> AsyncIterator[Any]:
    """KNPS geometry(route/area) file dataset record를 stream한다.

    ``settings.knps_geometry_dataset_key`` dataset을
    ``client.files.read_geo_records(key)``로 받아 typed record(``KnpsGeoRecord``,
    krtour ``KnpsGeometryRecord`` Protocol 충족, geometry는 WGS84 WKT)를 yield한다.
    SHP polygon dataset은 provider의 ``geo`` extra가 필요할 수 있다.
    """
    dataset_key = settings.knps_geometry_dataset_key
    knps = cast(Any, importlib.import_module("knps"))
    client = knps.KnpsClient()
    try:
        records = await client.files.read_geo_records(dataset_key)
        for record in records:
            yield record
    finally:
        await client.aclose()


async def fetch_krforest_recreation_forests(
    settings: KrtourMapSettings,
) -> AsyncIterator[Any]:
    """전국자연휴양림 표준데이터 record를 krforest public client로 stream한다.

    ``settings.data_go_kr_service_key``(source ``DATA_GO_KR_SERVICE_KEY``)로
    ``ForestClient(api_key=...)``를 열고 ``travel.standard_recreation_forests``를
    ``iter_pages``로 페이지네이션하며 record(``StandardRecreationForest``, krtour
    ``RecreationForestItem`` Protocol 충족)를 yield한다. krforest client는 async라
    async generator다. 소비 종료/조기 close 시 ``finally``에서 ``aclose()``.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krforest recreation forests live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    krforest = cast(Any, importlib.import_module("krforest"))
    client = krforest.ForestClient(api_key=api_key)
    try:
        async for page in client.iter_pages(
            client.travel.standard_recreation_forests, num_of_rows=1000
        ):
            for record in page.items:
                yield record
    finally:
        await client.aclose()


async def fetch_krforest_arboretums(
    settings: KrtourMapSettings,
) -> AsyncIterator[Any]:
    """휴양림 수목원 SHP record를 krforest public client로 stream한다.

    ``ForestClient.travel.recreation_forest_arboretums()``(SHP 다운로드+파싱, WGS84
    point)의 record(``ForestSpatialPoint``, krtour ``ForestSpatialItem`` Protocol
    충족)를 yield한다. SHP 파싱은 provider의 ``geo`` extra가 필요할 수 있다(배포
    환경 의존, 실 fetch 검증은 T-212e). file 다운로드도 data.go.kr key를 쓴다.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krforest arboretums live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    krforest = cast(Any, importlib.import_module("krforest"))
    client = krforest.ForestClient(api_key=api_key)
    try:
        records = await client.travel.recreation_forest_arboretums()
        for record in records:
            yield record
    finally:
        await client.aclose()


def fetch_standard_museums(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """전국박물관미술관표준데이터 record를 datagokr public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``DataGoKrClient(api_key=...)``를 열고
    ``client.museum_art.iter_all()``의 record(``PublicMuseumArtGallery``, krtour
    ``PublicMuseumArtItem`` Protocol 충족)를 lazily yield한다. datagokr client는
    sync이므로 sync generator다. 소비 종료/close 시 ``finally``에서 ``close()``.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "standard museums live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    datagokr = cast(Any, importlib.import_module("datagokr"))
    client = datagokr.DataGoKrClient(api_key=api_key)
    try:
        yield from client.museum_art.iter_all()
    finally:
        client.close()


def fetch_standard_tourist_attractions(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """전국관광지표준데이터 record를 datagokr public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``DataGoKrClient``를 열고
    ``client.tourist_attraction.iter_all()``의 record(``PublicTouristAttraction``,
    krtour ``PublicTouristAttractionItem`` Protocol 충족)를 lazily yield한다.
    sync client → sync generator, ``finally``에서 ``close()``.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "standard tourist attractions live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    datagokr = cast(Any, importlib.import_module("datagokr"))
    client = datagokr.DataGoKrClient(api_key=api_key)
    try:
        yield from client.tourist_attraction.iter_all()
    finally:
        client.close()


def fetch_krairport_airports(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """공항 메타데이터 record를 krairport public client로 stream한다.

    ``client.airports(active=True)``는 **번들 정적 데이터**라 credential 없이도 동작
    한다(keyless). key가 있으면 network-backed 메서드용으로 주입하되, 본 fetcher는
    bundled metadata만 yield한다(``AirportMetadata``, krtour ``AirportMetadataItem``
    Protocol 충족). sync generator, finally close.
    """
    krairport = cast(Any, importlib.import_module("krairport"))
    secret = settings.data_go_kr_service_key
    kwargs: dict[str, str] = {}
    if secret is not None:
        key = secret.get_secret_value()
        kwargs["kac_service_key"] = key
        kwargs["iiac_service_key"] = key
    client = krairport.KrairportClient(**kwargs)
    try:
        yield from client.airports(active=True)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def fetch_khoa_beaches(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """해양수산부 해수욕장정보 record를 khoa public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``KhoaClient(api_key=...)``를 열고
    시도별(``OCEANS_BEACH_INFO_DEFAULT_SIDO_NAMES``) ``oceans_beach_info(sido,
    page_no=N)``을 페이지네이션하며 record(``OceanBeachInfo``, krtour
    ``OceanBeachInfoItem`` Protocol 충족)를 yield한다. sync generator, finally close.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "khoa beaches live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    khoa = cast(Any, importlib.import_module("khoa"))
    client = khoa.KhoaClient(api_key=api_key)
    num_of_rows = 100
    try:
        for sido in khoa.OCEANS_BEACH_INFO_DEFAULT_SIDO_NAMES:
            page_no = 1
            while True:
                page = client.oceans_beach_info(
                    sido, page_no=page_no, num_of_rows=num_of_rows
                )
                items = list(page.items)
                if not items:
                    break
                yield from items
                if len(items) < num_of_rows:
                    break
                page_no += 1
    finally:
        client.close()


_AIRKOREA_SIDO_NAMES: Final[tuple[str, ...]] = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "경기", "강원",
    "충북", "충남", "전북", "전남", "경북", "경남", "제주", "세종",
)
"""airkorea ``sido_measurements`` 전국 순회용 17개 시도명(``SidoName`` 값)."""


def _airkorea_client(settings: KrtourMapSettings, *, label: str) -> Any:
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            f"airkorea {label} live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    airkorea = cast(Any, importlib.import_module("airkorea"))
    return airkorea.AirKoreaClient(service_key=secret.get_secret_value())


def _airkorea_close(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()


def fetch_airkorea_stations(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """대기질 측정소 메타데이터를 airkorea public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``AirKoreaClient(service_key=...)``를 열고
    ``stations(page_no=N)``을 페이지네이션하며 ``Station``(krtour
    ``AirQualityStationItem`` Protocol 충족, station_name/addr/lat/lon)을 yield.
    측정소는 weather-kind feature가 되고 측정값은 별도 fetcher가 가져온다.
    """
    client = _airkorea_client(settings, label="stations")
    num_of_rows = 100
    page_no = 1
    try:
        while True:
            items = list(client.stations(page_no=page_no, num_of_rows=num_of_rows))
            if not items:
                break
            yield from items
            if len(items) < num_of_rows:
                break
            page_no += 1
    finally:
        _airkorea_close(client)


def fetch_airkorea_air_quality(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """대기질 실시간 측정값을 airkorea public client로 stream한다.

    시도별(``_AIRKOREA_SIDO_NAMES``) ``sido_measurements(sido, page_no=N)``을
    페이지네이션하며 ``AirQualityMeasurement``(krtour ``AirQualityMeasurementItem``
    Protocol 충족)를 yield한다. 측정소명으로 station feature에 조인된다.
    """
    client = _airkorea_client(settings, label="air_quality")
    num_of_rows = 100
    try:
        for sido in _AIRKOREA_SIDO_NAMES:
            page_no = 1
            while True:
                items = list(
                    client.sido_measurements(
                        sido, page_no=page_no, num_of_rows=num_of_rows
                    )
                )
                if not items:
                    break
                yield from items
                if len(items) < num_of_rows:
                    break
                page_no += 1
    finally:
        _airkorea_close(client)


def _parse_opinet_bbox(raw: str) -> tuple[float, float, float, float]:
    """``"min_lon,min_lat,max_lon,max_lat"`` → 4-float tuple (검증 포함)."""
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise ProviderCredentialMissing(
            "opinet_scope_bbox는 'min_lon,min_lat,max_lon,max_lat' 4개 값이어야 한다."
        )
    try:
        min_lon, min_lat, max_lon, max_lat = (float(p) for p in parts)
    except ValueError as exc:
        raise ProviderCredentialMissing(
            f"opinet_scope_bbox 숫자 파싱 실패: {raw!r}"
        ) from exc
    if not (min_lon < max_lon and min_lat < max_lat):
        raise ProviderCredentialMissing(
            "opinet_scope_bbox는 min_lon<max_lon, min_lat<max_lat 여야 한다."
        )
    return (min_lon, min_lat, max_lon, max_lat)


def _enumerate_opinet_stations(
    client: Any,
    bboxes: Iterable[tuple[float, float, float, float]],
    *,
    radius_m: int,
) -> Iterator[Any]:
    """여러 bbox를 ``iter_stations_in_bbox``로 enumerate하며 ``uni_id`` dedup.

    bbox 단위로는 provider가 격자 내부 dedup하나, bbox 간 겹침은 여기서 제거한다.
    """
    seen: set[str] = set()
    for min_lon, min_lat, max_lon, max_lat in bboxes:
        for station in client.iter_stations_in_bbox(
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            radius_m=radius_m,
        ):
            uni_id = getattr(station, "uni_id", None)
            if isinstance(uni_id, str):
                if uni_id in seen:
                    continue
                seen.add(uni_id)
            yield station


def fetch_opinet_stations(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """OpiNet 주유소 record를 scope(bbox/POI-타깃)별로 stream한다(T-RV-04b).

    OpiNet은 전국 dump endpoint가 없어 ``iter_stations_in_bbox``(aroundAll 격자
    근사)로 영역을 enumerate한다. scope는 ``settings.opinet_scope_mode``:

    - ``disabled`` — 미적재(guard).
    - ``bbox`` — ``opinet_scope_bbox`` 영역 1개 enumerate.
    - ``poi_cache_target`` — opinet POI cache target 주변(후속 opinet-3에서 연결).

    sync generator, finally close. ``uni_id`` dedup.
    """
    mode = settings.opinet_scope_mode
    if mode == "disabled":
        raise ProviderCredentialMissing(
            "opinet 적재 비활성(opinet_scope_mode=disabled). "
            "OPINET_SCOPE_MODE=bbox|poi_cache_target 설정이 필요하다."
        )
    secret = settings.opinet_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "opinet live fetch에는 KRTOUR_MAP_OPINET_API_KEY (source OPINET_API_KEY)가 "
            "필요하다."
        )
    if mode == "poi_cache_target":
        raise ProviderCredentialMissing(
            "opinet poi_cache_target scope는 후속(T-RV-04b opinet-3)에서 연결된다."
        )
    if settings.opinet_scope_bbox is None:
        raise ProviderCredentialMissing(
            "opinet bbox scope에는 OPINET_SCOPE_BBOX "
            "(min_lon,min_lat,max_lon,max_lat)가 필요하다."
        )
    bbox = _parse_opinet_bbox(settings.opinet_scope_bbox)

    opinet = cast(Any, importlib.import_module("opinet"))
    client = opinet.OpinetClient(api_key=secret.get_secret_value())
    try:
        yield from _enumerate_opinet_stations(
            client, [bbox], radius_m=settings.opinet_scope_radius_m
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def fetch_standard_parking_lots(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """전국주차장표준데이터 record를 datagokr public client로 stream한다.

    ``client.parking.iter_all()``의 record(``PublicParkingLot``, krtour
    ``PublicParkingLotItem`` Protocol 충족)를 yield. sync generator, finally close.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "standard parking lots live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    datagokr = cast(Any, importlib.import_module("datagokr"))
    client = datagokr.DataGoKrClient(api_key=api_key)
    try:
        yield from client.parking.iter_all()
    finally:
        client.close()


def fetch_visitkorea_festival_events(
    settings: KrtourMapSettings,
) -> Iterator[Any]:
    """VisitKorea TourAPI 축제(searchFestival) record를 visitkorea client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``KrTourApiClient(service_key=...)``를 열고
    ``search_festival(event_start_date=<올해 1월 1일 KST>)``을 ``iter_pages``로
    페이지네이션하며 ``TourItem``(krtour ``VisitKoreaFestivalItem`` Protocol 충족)을
    yield한다. enrichment 2차 source라 1차(datagokr) 적재 후 매칭에 쓰인다(ADR-042).
    visitkorea client는 sync이므로 sync generator. 소비 종료/close 시 ``close()``.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "visitkorea festival events live fetch에는 "
            "KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    visitkorea = cast(Any, importlib.import_module("visitkorea"))
    client = visitkorea.KrTourApiClient(service_key=api_key)
    kst = timezone(timedelta(hours=9))
    start = date(datetime.now(kst).year, 1, 1)
    try:
        for page in client.iter_pages(
            client.search_festival, start, num_of_rows=100
        ):
            yield from page.items
    finally:
        client.close()

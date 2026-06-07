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
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from krtour.map.settings import KrtourMapSettings

__all__ = [
    "ProviderCredentialMissing",
    "fetch_datagokr_cultural_festivals",
    "fetch_krex_rest_areas",
    "fetch_krex_traffic_notices",
    "fetch_krheritage_events",
    "fetch_mois_license_records",
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

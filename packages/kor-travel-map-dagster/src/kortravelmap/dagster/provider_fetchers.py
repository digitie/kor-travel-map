"""Provider public client live record fetcher (T-RV-04b).

각 provider별 sync fetch 함수는 ``KorTravelMapSettings``에서 credential을 읽어
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
import logging
import math
import pathlib
import time
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import date, datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, Final, cast

import httpx
from kortravelmap.core.ids import make_payload_hash
from kortravelmap.dto._time import kst_now
from kortravelmap.infra.db import require_pg_dsn
from kortravelmap.providers.opinet import (
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from . import upstream_retry
from .provider_pagination import ProviderPage, iter_paginated_items
from .upstream_retry import retry_upstream

if TYPE_CHECKING:
    from kortravelmap.settings import KorTravelMapSettings

_LOGGER = logging.getLogger(__name__)
"""H45 재시도 텔레메트리. ``docker/dagster.yaml``의 ``python_logs``가 이
logger의 WARNING 이상을 Dagster event stream으로 결선한다."""

__all__ = [
    "KrexTrafficNoticeSnapshotUnstable",
    "ProviderCredentialMissing",
    "fetch_airkorea_air_quality",
    "fetch_airkorea_stations",
    "fetch_datagokr_cultural_festivals",
    "fetch_datagokr_file_data_records",
    "fetch_khoa_beaches",
    "fetch_kma_weather_alerts",
    "fetch_knps_geometry_records",
    "fetch_knps_point_records",
    "fetch_krairport_airports",
    "fetch_krex_rest_area_weather",
    "fetch_krex_rest_area_fuel_prices",
    "fetch_krex_rest_areas",
    "fetch_krex_traffic_notices",
    "fetch_krforest_arboretums",
    "fetch_krforest_dulle_trails",
    "fetch_krforest_landslide_forecast_issues",
    "fetch_krforest_mountain_trails",
    "fetch_krforest_mountain_weather",
    "fetch_krforest_recreation_forests",
    "fetch_krforest_wildfire_risk_forecast",
    "fetch_krheritage_events",
    "fetch_krheritage_items",
    "fetch_mcst_culture_records",
    "fetch_mois_license_records",
    "fetch_opinet_stations",
    "fetch_opinet_station_price_details",
    "fetch_standard_museums",
    "fetch_standard_parking_lots",
    "fetch_standard_special_streets",
    "fetch_standard_tourist_attractions",
    "fetch_kor_travel_concierge_youtube_features",
    "fetch_visitkorea_festival_events",
]


class ProviderCredentialMissing(RuntimeError):
    """provider live fetch에 필요한 credential이 설정되지 않았을 때."""


class KrexTrafficNoticeSnapshotUnstable(RuntimeError):
    """KREX 돌발 feed가 bounded retry 내에 안정 snapshot을 확보하지 못했을 때.

    휘발성(사건 appear/disappear) feed에서 연속 snapshot이 상한 내 한 번도
    일치하지 않은 경우다. ``RuntimeError`` 하위형이라 기존 예외 처리와 호환되면서,
    caller가 '일시 불일치가 아니라 지속적 불안정'을 특정해 구분할 수 있게 typed다.
    """


# 연속 snapshot 사건 집합 일치를 요구하되(불완전 pagination이 notice 종료를 오판하지
# 않도록), 휘발성 feed의 일시 불일치를 sliding 재시도로 self-heal하기 위한 상한.
# 초기 1회 + 최대 이 횟수만큼 추가 snapshot을 떠 직전과 비교한다(총 최대 상한+1 snapshot).
_KREX_NOTICE_STABILITY_RETRIES: Final[int] = 4
# 재시도 snapshot 사이의 간격(초). back-to-back으로 뜨면 같은 휘발 window를 관측해
# self-heal이 무력화될 수 있으므로 휘발 사건이 정착할 시간을 준다(#700). 최초 pair
# (initial vs 첫 재시도)는 full pagination의 자연 지연이 있으므로 delay를 넣지 않는다.
# 테스트는 이 값을 0으로 monkeypatch해 즉시 실행한다.
_KREX_NOTICE_RETRY_DELAY_SECONDS: Final[float] = 0.5


async def fetch_kor_travel_concierge_youtube_features(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """kor-travel-concierge YouTube 장소 후보 export를 REST API로 stream한다.

    ``kor_travel_concierge_feature_sync_endpoint`` 기본 ``changes``는 cursor 없이
    시작하면 후보당 1행으로 압축된 export ledger 전체(upsert/reject/tombstone)를
    재생해 full sync와 철회(제거 목록·검수 회수) 전파를 동시에 만족한다.
    ``snapshot``은 active upsert만 반환하는 opt-in(초기 적재 검증용)이다. Cursor는
    opaque string으로 취급하며 응답의 ``next_cursor``를 다음 요청에 그대로 넘긴다.
    """
    base_url = settings.kor_travel_concierge_base_url
    secret = settings.kor_travel_concierge_api_key
    if base_url is None:
        raise ProviderCredentialMissing(
            "kor-travel-concierge YouTube feature live fetch에는 "
            "KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL이 필요하다."
        )
    if secret is None:
        raise ProviderCredentialMissing(
            "kor-travel-concierge YouTube feature live fetch에는 "
            "KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY "
            "(kor-travel-concierge DB read scope 키)가 필요하다."
        )

    endpoint = settings.kor_travel_concierge_feature_sync_endpoint
    # ADR-053 identity + ADR-050 #1 경로 중립화 — REST path에 downstream 이름을 넣지 않는다.
    path = f"/api/v1/features/{endpoint}"
    cursor = settings.kor_travel_concierge_feature_cursor
    headers = {"X-API-Key": secret.get_secret_value()}
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        timeout=settings.kor_travel_concierge_timeout_seconds,
        headers=headers,
    ) as client:
        while True:
            params: dict[str, str | int] = {
                "limit": settings.kor_travel_concierge_feature_page_size
            }
            if cursor:
                params["cursor"] = cursor
            response = await client.get(path, params=params)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError(
                    "kor-travel-concierge feature export 응답은 JSON object여야 한다."
                )
            items = payload.get("items")
            if not isinstance(items, list):
                raise RuntimeError("kor-travel-concierge feature export 응답에 items list가 없다.")
            for item in items:
                yield item

            has_more = bool(payload.get("has_more"))
            next_cursor = payload.get("next_cursor")
            if not has_more:
                break
            if not isinstance(next_cursor, str) or not next_cursor:
                raise RuntimeError(
                    "kor-travel-concierge feature export has_more=true인데 next_cursor가 없다."
                )
            if next_cursor == cursor:
                raise RuntimeError(
                    "kor-travel-concierge feature export next_cursor가 이전 cursor와 같다."
                )
            cursor = next_cursor


def fetch_datagokr_cultural_festivals(
    settings: KorTravelMapSettings,
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
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
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
    settings: KorTravelMapSettings,
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
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
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


def fetch_krheritage_items(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """국가유산 본체(place/area) record를 krheritage public client로 stream한다 (#380).

    ``HeritageClient()``를 **keyless**로 열고 — 국가유산 search/detail은
    khs.go.kr OpenAPI라 service key가 필요 없다(provider transport는
    ``apis.data.go.kr`` URL에만 serviceKey를 주입) — settings
    ``krheritage_kind_codes``(기본 ``"11,12,13,15,16"``: 국보/보물/사적/
    천연기념물/명승)의 종목코드별로 ``client.search.iter_all_details(
    page_size=100, ccba_kdcd=...)``의 record(``HeritageDetail``, krtour
    ``KrHeritageItem`` Protocol 충족)를 lazily yield한다.

    detail이 **1건당 1 HTTP 콜**이므로 run당 상한
    ``krheritage_max_items_per_run``(기본 5000)에서 끊는다
    (``mcst_max_items_per_dataset`` 가드 패턴). sync generator, finally close.
    """
    # provider public client는 ADR-044 로컬 체크아웃이며 hard dependency가
    # 아니므로(부재 가능), datagokr와 동일하게 import time이 아닌 호출 시점에
    # ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    krheritage = cast(Any, importlib.import_module("krheritage"))

    kind_codes = [
        code.strip() for code in settings.krheritage_kind_codes.split(",") if code.strip()
    ]
    max_items = settings.krheritage_max_items_per_run
    client = krheritage.HeritageClient()
    seen = 0
    try:
        for kind_code in kind_codes:
            for record in client.search.iter_all_details(page_size=100, ccba_kdcd=kind_code):
                yield record
                seen += 1
                if seen >= max_items:
                    return
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def fetch_krex_rest_areas(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """고속도로 휴게소(rest_area) record를 krex public client로 stream한다.

    ``settings.krex_go_api_key``(source ``KEX_GO_API_KEY``)에서 data.go.kr
    service key를 읽어 ``KrexClient(go_api_key=...)``를 열고
    ``client.restarea.list_all(num_of_rows=1000, page_no=N)``을 페이지네이션하며
    record(``krex.models.RestArea``, ``KrexRestAreaItem`` Protocol 충족)를 lazily
    yield한다. ``list_all``은 ``tn_pubr_public_rest_area_api`` (data.go.kr) 호출
    이므로 EX key가 아닌 **go key**를 쓴다.

    이 dataset에는 안정 식별자가 없어 krtour 변환부가 name+route_name+direction
    으로 자연키를 파생한다(ADR-044). 페이지네이션 종료 판정은
    :func:`~kortravelmap.dagster.provider_pagination.iter_paginated_items`가
    소유한다 — ``total_count``가 권위이고 짧은 페이지는 그것이 없을 때만 쓰는
    대체 휴리스틱이다(provider가 파싱 실패 행을 걸러도 조용히 절단되지 않게).
    generator 소비 종료(또는 close)시 ``finally``에서 ``client.close()``.
    """
    secret = settings.krex_go_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krex rest_areas live fetch에는 "
            "KOR_TRAVEL_MAP_KREX_GO_API_KEY (source KEX_GO_API_KEY / "
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
        def _page(page_no: int) -> ProviderPage:
            page = client.restarea.list_all(num_of_rows=num_of_rows, page_no=page_no)
            return ProviderPage(items=list(page.items), total_count=page.total_count)

        yield from iter_paginated_items(
            _page,
            num_of_rows=num_of_rows,
            label="krex restarea.list_all",
            warn=_LOGGER.warning,
        )
    finally:
        client.close()


def fetch_mois_license_records(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """미리 sync된 MOIS 소스 SQLite DB에서 영업중 인허가 record를 stream한다.

    MOIS 인허가는 live REST가 아니라 별도 sync step(Phase A — LOCALDATA
    download/적재, **본 task scope 밖**)이 채워둔 SQLite 소스 DB를 읽는다.
    본 fetcher(Phase B)는 그 DB를 **읽기만** 한다.

    ``settings.mois_source_db_path``(env ``KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH``)에서
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
            "DB 경로를 설정하라. (KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH)"
        )

    # provider record 모델/streaming 함수는 ADR-044 로컬 체크아웃이며 hard
    # dependency가 아니므로(부재 가능), datagokr와 동일하게 import time이 아닌
    # 호출 시점에 ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    mois_db = cast(Any, importlib.import_module("mois.db"))
    # PROMOTED_SERVICE_SLUGS는 krtour(본 repo)이므로 top-level import으로 충분.
    from kortravelmap.providers.mois import PROMOTED_SERVICE_SLUGS

    # 파일 registry hook (H9) — Phase B가 소스 DB 소비를 시작했음을 기록.
    # consumer가 run당 generator를 한 번 생성하는 경로라 memo 불필요, 내부에서
    # 실패 무해화. 지연 import로 모듈 초기화 순환을 피한다.
    from .file_registry_hooks import record_mois_source_loaded

    record_mois_source_loaded(settings)

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
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """고속도로 교통 공지(돌발 incident) record를 krex public client로 stream한다.

    ``settings.krex_ex_api_key``(source ``KEX_GO_API_KEY``)에서 EX OpenAPI key를
    읽어 ``KrexClient(ex_api_key=...)``를 열고 ``client.traffic.incident(
    num_of_rows=1000, page_no=N)``을 페이지네이션한다. 완전 snapshot 검증 뒤
    record(``krex.models.Incident``, ``KrexTrafficNoticeItem`` Protocol 충족)를 yield한다.
    rest_areas와 달리 EX endpoint이므로 go key가 아닌 **ex key**를 쓴다.

    EX 돌발 feed는 휘발성(transient) — 해소된 사건은 사라진다(ADR-044). 서버가
    요청한 ``num_of_rows``보다 작은 page size로 clamp할 수 있으므로 응답
    ``total_count``까지 수집한다. 이 feed의 부재는 notice 종료를 뜻하므로
    ``page.raw``에 endpoint 고유 목록 키와 count가 모두 있는 완결된 snapshot만
    성공으로 인정한다. HTTP 200의 ``{}``, message-only, count-only 응답은 실패시켜
    asset reconcile이 실행되지 않게 한다. page 사이 동일 사건 identity가 다시
    나타나는 snapshot도 page boundary 이동으로 한 사건이 중복되고 다른 사건이
    누락된 불완전 응답일 수 있으므로 거부한다. 완전 pagination을 수행하되, 휘발성
    feed에서 연속 두 snapshot의 record 수·사건 identity set이 일치할 때까지
    ``_KREX_NOTICE_STABILITY_RETRIES`` 상한 내에서 매 pass를 직전과 비교하는 sliding
    재시도로 확인하고, 안정된 최신 pass만 yield한다. 상한 내 안정 pair를 못 잡으면
    ``KrexTrafficNoticeSnapshotUnstable``(typed)로 실패한다(#700 — 일시 불일치가
    run을 반복 중단시켜 notice 신선도를 정체시키던 문제). generator 소비 종료(또는
    close)시 ``finally``에서 ``client.close()``.
    """
    secret = settings.krex_ex_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krex traffic_notices live fetch에는 "
            "KOR_TRAVEL_MAP_KREX_EX_API_KEY (source KEX_GO_API_KEY)가 필요하다."
        )
    api_key = secret.get_secret_value()

    # provider public client는 ADR-044 로컬 체크아웃이며 hard dependency가
    # 아니므로(부재 가능), datagokr와 동일하게 import time이 아닌 호출 시점에
    # ``importlib`` + ``cast(Any, ...)``로 lazy resolve한다.
    krex = cast(Any, importlib.import_module("krex"))

    client = krex.KrexClient(ex_api_key=api_key)
    num_of_rows = 1000
    try:
        # 휘발성 feed에서 연속 2 snapshot이 한 번에 일치하지 않을 수 있으므로, 매 pass를
        # 직전 pass와 비교하는 sliding 방식으로 상한(_KREX_NOTICE_STABILITY_RETRIES) 내
        # 재시도해 일시 불일치를 self-heal한다. 상한 내 안정 pair를 못 잡으면 typed 실패로
        # 명확히 신호한다(무한 재시도/불완전 snapshot yield 금지 — 완전 pagination 2회-일치
        # 안전성은 유지). 안정 pair 확정 전에는 한 건도 yield하지 않아 destructive reconcile과 격리.
        previous_records, previous_identities = _fetch_krex_traffic_notice_snapshot(
            client,
            num_of_rows=num_of_rows,
        )
        stable_records: list[Any] | None = None
        for attempt in range(_KREX_NOTICE_STABILITY_RETRIES):
            # 첫 재시도(attempt 0)는 initial snapshot과 full pagination 자연 지연으로
            # 이미 떨어져 있으므로 delay 없이 비교하고, 이후 재시도만 사건 정착 시간을 준다.
            if attempt > 0 and _KREX_NOTICE_RETRY_DELAY_SECONDS > 0:
                time.sleep(_KREX_NOTICE_RETRY_DELAY_SECONDS)
            current_records, current_identities = _fetch_krex_traffic_notice_snapshot(
                client,
                num_of_rows=num_of_rows,
            )
            if (
                len(previous_records) == len(current_records)
                and previous_identities == current_identities
            ):
                stable_records = current_records
                break
            previous_records, previous_identities = (
                current_records,
                current_identities,
            )
        if stable_records is None:
            raise KrexTrafficNoticeSnapshotUnstable(
                "KREX traffic_notices 연속 snapshot이 "
                f"{_KREX_NOTICE_STABILITY_RETRIES}회 재시도 내 안정되지 않았다: "
                f"last_count={len(previous_records)}"
            )
        yield from stable_records
    finally:
        client.close()


def _fetch_krex_traffic_notice_snapshot(
    client: Any,
    *,
    num_of_rows: int,
) -> tuple[list[Any], set[str]]:
    """KREX incident snapshot 한 pass를 완전 수집하고 사건 identity를 반환한다."""
    records: list[Any] = []
    seen_lineage_identities: set[str] = set()
    page_no = 1
    expected_total: int | None = None
    while True:
        page = client.traffic.incident(num_of_rows=num_of_rows, page_no=page_no)
        items = list(page.items)
        total_count = _validate_krex_traffic_notice_page(
            page,
            page_no=page_no,
            seen=len(records),
            item_count=len(items),
            expected_total=expected_total,
        )
        if expected_total is None:
            expected_total = total_count
        if not items:
            break
        for item_index, item in enumerate(items):
            identity = _krex_traffic_notice_lineage_identity(item)
            if identity in seen_lineage_identities:
                raise RuntimeError(
                    "KREX traffic_notices snapshot에 중복 사건 identity가 있다: "
                    f"page_no={page_no}, item_index={item_index}"
                )
            seen_lineage_identities.add(identity)
        records.extend(items)
        if len(records) == total_count:
            break
        page_no += 1
    if expected_total is None or len(records) != expected_total:
        raise RuntimeError(
            "KREX traffic_notices snapshot record 수가 count와 다르다: "
            f"records={len(records)}, total_count={expected_total!r}"
        )
    return records, seen_lineage_identities


def _krex_traffic_notice_lineage_identity(item: Any) -> str:
    """map KREX 사건 자연키와 같은 필드로 pagination 중복을 판정한다.

    converter ``_traffic_notice_natural_key``와 동일하게 typed natural-key 필드를
    strip/lower한 뒤 빈 값을 제외해 ``::``로 잇는다. 전부 비면 ``series_no``를
    별도 identity로 쓰지 않고 raw payload 전체의 hash로 fallback한다.
    """
    parts = tuple(
        part
        for part in (
            (item.occurred_date or "").strip().lower(),
            (item.occurred_time or "").strip().lower(),
            (item.route_no or "").strip().lower(),
            (item.direction or "").strip().lower(),
            (item.point_name or "").strip().lower(),
            (item.incident_type_code or "").strip().lower(),
        )
        if part
    )
    if parts:
        return "::".join(parts)
    return f"raw::{make_payload_hash(item.raw)}"


def _validate_krex_traffic_notice_page(
    page: Any,
    *,
    page_no: int,
    seen: int,
    item_count: int,
    expected_total: int | None,
) -> int:
    """KREX incident page가 종료 판정에 쓸 수 있는 snapshot 조각인지 검증한다.

    ``python-krex-api``의 범용 EX normalizer는 목록 키가 없는 HTTP 200 object도
    빈 ``Page``로 정규화한다. 일반 조회에는 편리하지만, 빈 목록이 곧 모든 기존
    notice 종료인 본 asset에서는 source 실패를 정상 empty로 오인한다. 로컬 provider의
    live fixture가 고정한 ``realTimeSMSList`` + ``count`` 구조를 이 lifecycle 경계에서
    한 번 더 확인한다. 단건 응답은 provider 계약대로 object도 허용한다.
    """
    raw = getattr(page, "raw", None)
    if not isinstance(raw, dict):
        raise RuntimeError(
            f"KREX traffic_notices 응답 raw가 JSON object가 아니다: page_no={page_no}"
        )
    if "realTimeSMSList" not in raw:
        raise RuntimeError(f"KREX traffic_notices 응답에 realTimeSMSList가 없다: page_no={page_no}")
    raw_items = raw["realTimeSMSList"]
    if isinstance(raw_items, list):
        raw_item_count = len(raw_items)
    elif isinstance(raw_items, dict):
        raw_item_count = 1
    else:
        raise RuntimeError(
            f"KREX traffic_notices realTimeSMSList가 list/object가 아니다: page_no={page_no}"
        )
    if raw_item_count != item_count:
        raise RuntimeError(
            "KREX traffic_notices raw/parsed item 수가 다르다: "
            f"raw={raw_item_count}, parsed={item_count}, page_no={page_no}"
        )

    raw_page_no = _strict_non_negative_int(raw.get("pageNo"))
    if raw_page_no != page_no or getattr(page, "page_no", None) != page_no:
        raise RuntimeError(
            "KREX traffic_notices 응답 pageNo가 요청과 다르다: "
            f"requested={page_no}, raw={raw_page_no!r}, "
            f"parsed={getattr(page, 'page_no', None)!r}"
        )
    raw_num_of_rows = _strict_non_negative_int(raw.get("numOfRows"))
    if raw_num_of_rows is None or getattr(page, "num_of_rows", None) != raw_num_of_rows:
        raise RuntimeError(
            "KREX traffic_notices 응답에 유효한 numOfRows가 없다: "
            f"raw={raw_num_of_rows!r}, parsed={getattr(page, 'num_of_rows', None)!r}, "
            f"page_no={page_no}"
        )

    total_count = _strict_non_negative_int(raw.get("count"))
    if total_count is None or total_count < 0:
        raise RuntimeError(f"KREX traffic_notices 응답에 유효한 count가 없다: page_no={page_no}")
    if getattr(page, "total_count", None) != total_count:
        raise RuntimeError(
            "KREX traffic_notices raw/parsed count가 다르다: "
            f"raw={total_count}, parsed={getattr(page, 'total_count', None)!r}, "
            f"page_no={page_no}"
        )
    if expected_total is not None and total_count != expected_total:
        raise RuntimeError(
            "KREX traffic_notices 페이지 사이 count가 바뀌었다: "
            f"expected={expected_total}, actual={total_count}, page_no={page_no}"
        )
    if seen + item_count > total_count:
        raise RuntimeError(
            "KREX traffic_notices item 수가 count를 초과했다: "
            f"seen={seen}, page_items={item_count}, total_count={total_count}, "
            f"page_no={page_no}"
        )
    if item_count == 0 and seen < total_count:
        raise RuntimeError(
            "KREX traffic_notices pagination이 total_count 도달 전에 빈 page를 반환했다: "
            f"seen={seen}, total_count={total_count}, page_no={page_no}"
        )
    return total_count


def _strict_non_negative_int(value: Any) -> int | None:
    """bool/float를 수로 오인하지 않는 provider metadata 정수 파서."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def fetch_krex_rest_area_fuel_prices(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """고속도로 휴게소 유가(restarea.fuel_prices) record를 stream한다."""
    secret = settings.krex_ex_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krex rest_area_fuel_prices live fetch에는 "
            "KOR_TRAVEL_MAP_KREX_EX_API_KEY (source KEX_GO_API_KEY)가 필요하다."
        )
    api_key = secret.get_secret_value()

    krex = cast(Any, importlib.import_module("krex"))
    client = krex.KrexClient(ex_api_key=api_key)
    num_of_rows = 1000
    try:
        def _page(page_no: int) -> ProviderPage:
            page = client.restarea.fuel_prices(num_of_rows=num_of_rows, page_no=page_no)
            return ProviderPage(items=list(page.items), total_count=page.total_count)

        yield from iter_paginated_items(
            _page,
            num_of_rows=num_of_rows,
            label="krex restarea.fuel_prices",
            warn=_LOGGER.warning,
        )
    finally:
        client.close()


def fetch_krex_rest_area_weather(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """고속도로 휴게소 관측 기상(rest_area_weather) record를 krex public client로 stream한다.

    ``settings.krex_ex_api_key``(source ``KEX_GO_API_KEY``)에서 EX OpenAPI key를
    읽어 ``KrexClient(ex_api_key=...)``를 열고 ``client.restarea.latest_weather()``
    (``/openapi/restinfo/restWeatherList``, EX endpoint)의 record(``krex.models.
    RestAreaWeather``, ``KrexRestAreaWeatherRecord`` Protocol 충족 — unit_code +
    좌표 + 기온/습도/풍속/강수 wide row)를 lazily yield한다. traffic_notices와 동일
    EX endpoint이므로 go key가 아닌 **ex key**를 쓴다.

    ``latest_weather``는 전국 휴게소 1시간 snapshot을 한 Page로 돌려준다(restWeatherList
    는 휴게소 필터 없음) — 가장 최근 데이터가 있는 시각을 lookback으로 찾는다.
    페이지네이션 불필요. generator 소비 종료(또는 close)시 ``finally``에서
    ``client.close()``.
    """
    secret = settings.krex_ex_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krex rest_area_weather live fetch에는 "
            "KOR_TRAVEL_MAP_KREX_EX_API_KEY (source KEX_GO_API_KEY)가 필요하다."
        )
    api_key = secret.get_secret_value()

    # provider public client는 ADR-044 로컬 체크아웃이며 hard dependency가
    # 아니므로(부재 가능), 호출 시점에 ``importlib`` + ``cast(Any, ...)``로 resolve.
    krex = cast(Any, importlib.import_module("krex"))

    client = krex.KrexClient(ex_api_key=api_key)
    try:
        page = client.restarea.latest_weather()
        yield from page.items
    finally:
        client.close()


async def fetch_knps_point_records(
    settings: KorTravelMapSettings,
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
    settings: KorTravelMapSettings,
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
    settings: KorTravelMapSettings,
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
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
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
    settings: KorTravelMapSettings,
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
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
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


async def fetch_krforest_mountain_trails(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """산림청 등산로 SHP route feature를 `ForestSpatialFeature`로 stream한다."""

    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krforest mountain trails live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    krforest = cast(Any, importlib.import_module("krforest"))
    client = krforest.ForestClient(api_key=secret.get_secret_value())
    try:
        records = await client.travel.forest_trail_file_features()
        for record in records:
            yield record
    finally:
        await client.aclose()


async def fetch_krforest_dulle_trails(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """산림청 둘레길 SHP route feature를 `ForestSpatialFeature`로 stream한다."""

    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krforest dulle trails live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    krforest = cast(Any, importlib.import_module("krforest"))
    client = krforest.ForestClient(api_key=secret.get_secret_value())
    try:
        records = await client.travel.dulle_trail_features()
        for record in records:
            yield record
    finally:
        await client.aclose()


async def fetch_krforest_mountain_weather(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """산악기상 관측 typed row를 페이지 단위로 stream한다(C05B)."""

    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krforest mountain weather live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    krforest = cast(Any, importlib.import_module("krforest"))
    client = krforest.ForestClient(api_key=secret.get_secret_value())
    try:
        async for page in client.iter_pages(
            client.travel.mountain_weather,
            num_of_rows=1000,
        ):
            for record in page.items:
                yield record
    finally:
        await client.aclose()


async def fetch_krforest_wildfire_risk_forecast(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """전국 산불위험예보 V2 typed row를 stream한다(C05C)."""

    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krforest wildfire risk live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    krforest = cast(Any, importlib.import_module("krforest"))
    client = krforest.ForestClient(api_key=secret.get_secret_value())
    try:
        async for page in client.iter_pages(
            client.safety.wildfire_risk_forecast,
            num_of_rows=1000,
        ):
            for record in page.items:
                yield record
    finally:
        await client.aclose()


async def fetch_krforest_landslide_forecast_issues(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """산사태 예보발령·해제 typed row를 페이지 단위로 stream한다(C05D)."""

    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "krforest landslide forecast live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    krforest = cast(Any, importlib.import_module("krforest"))
    client = krforest.ForestClient(api_key=secret.get_secret_value())
    try:
        async for page in client.iter_pages(
            client.safety.landslide_forecast_issues,
            num_of_rows=1000,
        ):
            for record in page.items:
                yield record
    finally:
        await client.aclose()


def fetch_standard_museums(
    settings: KorTravelMapSettings,
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
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
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
    settings: KorTravelMapSettings,
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
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    datagokr = cast(Any, importlib.import_module("datagokr"))
    client = datagokr.DataGoKrClient(api_key=api_key)
    try:
        yield from client.tourist_attraction.iter_all()
    finally:
        client.close()


def fetch_standard_special_streets(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """전국지역특화거리표준데이터 record를 datagokr public client로 stream한다."""
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "standard special streets live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    datagokr = cast(Any, importlib.import_module("datagokr"))
    client = datagokr.DataGoKrClient(api_key=api_key)
    try:
        yield from client.special_street.iter_all()
    finally:
        client.close()


def fetch_datagokr_file_data_records(
    settings: KorTravelMapSettings,
    *,
    dataset_key: str,
) -> Iterator[Any]:
    """data.go.kr fileData 자동변환 API raw row를 datagokr public client로 stream한다."""
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "data.go.kr fileData live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    datagokr = cast(Any, importlib.import_module("datagokr"))
    client = datagokr.DataGoKrClient(api_key=api_key)
    try:
        yield from client.file_data.iter_all(dataset_key)
    finally:
        client.close()


def fetch_krairport_airports(
    settings: KorTravelMapSettings,
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


def fetch_mcst_culture_records(
    settings: KorTravelMapSettings,
    *,
    slugs: Iterable[str] | None = None,
) -> Iterator[Any]:
    """MCST 파일데이터 등록 dataset CSV row를 mcst public client로 stream한다 (#395).

    파일 다운로드는 **keyless** — ``FileDataClient()``가 카탈로그의 다운로드
    페이지를 스크레이핑해 최신 CSV를 받는다(provider #6/#7, krheritage items /
    knps file dataset과 동일하게 credential guard 없음). ``MCST_FILE_DATASETS``에
    등록된 slug 또는 worker가 명시한 slug를 순회하며 ``client.iter_csv(slug)``의 raw row(dict)를
    ``(slug, row)`` 튜플로 lazily yield한다 — asset이 slug별로 분리
    ``_load``한다(dataset_key 단위 sync state 유지). dataset당
    ``settings.mcst_max_items_per_dataset`` 상한(이상 응답 방어). sync
    generator, finally close.
    """
    # slug 메타표는 krtour(본 repo) — 변환과 fetch가 같은 표를 본다.
    from kortravelmap.providers.mcst import MCST_FILE_DATASETS

    selected_slugs = tuple(MCST_FILE_DATASETS) if slugs is None else tuple(slugs)
    unknown = sorted(set(selected_slugs) - set(MCST_FILE_DATASETS))
    if unknown:
        raise KeyError(f"MCST 메타표에 없는 slug: {unknown!r}")
    mcst = cast(Any, importlib.import_module("mcst"))
    client = mcst.FileDataClient()
    max_items = settings.mcst_max_items_per_dataset
    try:
        for slug in selected_slugs:
            for seen, row in enumerate(client.iter_csv(slug), start=1):
                yield (slug, row)
                if seen >= max_items:
                    break
    finally:
        client.close()


KMA_WEATHER_ALERT_STN_ID: Final[str] = "108"
"""KMA 특보 발표관서 — ``108`` = 전국(기상청 본청). 1차는 전국 단일 조회."""


def _provider_retry_budget(
    settings: KorTravelMapSettings,
    *,
    expected_calls: int,
) -> upstream_retry.RetryBudget:
    """settings의 비율·하한으로 run 재시도 예산을 만든다(H45 후속)."""

    return upstream_retry.RetryBudget.proportional(
        expected_calls,
        percent=settings.provider_upstream_retry_budget_percent,
        minimum=settings.provider_upstream_retry_budget_minimum,
    )


def fetch_kma_weather_alerts(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """KMA 기상특보 목록(getWthrWrnList) record를 kma public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``DataGoKrClient(service_key=...)``를
    열고 전국 발표관서(``108``)의 rolling window(오늘 포함
    ``kma_weather_alert_lookback_days``일)를 ``weather_warning_list(stn_id,
    from_tm_fc, to_tm_fc, page_no=N)``로 페이지네이션하며 record
    (``kma.models.WeatherWarningItem`` — ``stn_id``/``tm_fc``/``seq``/``title``
    + ``raw``)를 lazily yield한다. 특보 종류/등급/구역의 구조화 파싱은
    ``kma_weather.weather_warning_rows``(asset 측 adapter)가 맡는다.
    sync generator, finally close.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "kma weather alerts live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    kma = cast(Any, importlib.import_module("kma"))
    client = kma.DataGoKrClient(
        service_key=api_key,
        timeout=settings.provider_http_timeout_seconds,
        retries=upstream_retry.PROVIDER_CLIENT_INNER_RETRIES,
    )
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    window_start = today - timedelta(days=settings.kma_weather_alert_lookback_days - 1)
    budget = _provider_retry_budget(settings, expected_calls=1)
    num_of_rows = 100
    try:
        def _page(page_no: int) -> ProviderPage:
            # H45: 페이지 단건 호출만 유한 재시도 (kma ``retryable`` 규약 분류 —
            # quota/rate_limit 제외는 default predicate 소관).
            items = retry_upstream(
                partial(
                    _weather_warning_page,
                    client,
                    from_tm_fc=window_start,
                    to_tm_fc=today,
                    page_no=page_no,
                    num_of_rows=num_of_rows,
                ),
                label=f"kma weather_warning_list p{page_no}",
                base_delay=upstream_retry.PROVIDER_BOUNDARY_BASE_DELAY_SECONDS,
                budget=budget,
                on_retry=_LOGGER.warning,
            )
            # ``weather_warning_list``는 Page가 아니라 list를 돌려주므로 upstream
            # 선언 건수를 알 수 없다 — 짧은 페이지 휴리스틱만 쓸 수 있다.
            return ProviderPage(items=items, total_count=None)

        yield from iter_paginated_items(
            _page,
            num_of_rows=num_of_rows,
            label="kma weather_warning_list",
            warn=_LOGGER.warning,
        )
    finally:
        client.close()


def _weather_warning_page(
    client: Any,
    *,
    from_tm_fc: date,
    to_tm_fc: date,
    page_no: int,
    num_of_rows: int,
) -> list[Any]:
    """특보 목록 1페이지를 재시도 경계 안에서 소진한다(H45 — lazy 우회 방지)."""

    return list(
        client.weather_warning_list(
            stn_id=KMA_WEATHER_ALERT_STN_ID,
            from_tm_fc=from_tm_fc,
            to_tm_fc=to_tm_fc,
            page_no=page_no,
            num_of_rows=num_of_rows,
        )
    )


def fetch_khoa_beaches(
    settings: KorTravelMapSettings,
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
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    khoa = cast(Any, importlib.import_module("khoa"))
    client = khoa.KhoaClient(
        api_key=api_key,
        timeout=settings.provider_http_timeout_seconds,
        retries=upstream_retry.PROVIDER_CLIENT_INNER_RETRIES,
    )
    sido_names = tuple(khoa.OCEANS_BEACH_INFO_DEFAULT_SIDO_NAMES)
    budget = _provider_retry_budget(settings, expected_calls=len(sido_names))
    num_of_rows = 100
    try:
        for sido in sido_names:

            def _page(page_no: int, sido: str = sido) -> ProviderPage:
                return retry_upstream(
                    partial(
                        _khoa_beach_page,
                        client,
                        sido,
                        page_no=page_no,
                        num_of_rows=num_of_rows,
                    ),
                    label=f"khoa oceans_beach_info {sido} p{page_no}",
                    base_delay=upstream_retry.PROVIDER_BOUNDARY_BASE_DELAY_SECONDS,
                    budget=budget,
                    on_retry=_LOGGER.warning,
                )

            yield from iter_paginated_items(
                _page,
                num_of_rows=num_of_rows,
                label=f"khoa oceans_beach_info {sido}",
                warn=_LOGGER.warning,
            )
    finally:
        client.close()


def _khoa_beach_page(
    client: Any,
    sido: str,
    *,
    page_no: int,
    num_of_rows: int,
) -> ProviderPage:
    """KHOA 해수욕장 한 페이지를 재시도 경계 안에서 완전히 소진한다.

    ``khoa.models.Page.total_count``는 ``int = 0``이라 미제공과 0을 구분하지 못한다.
    그 판정은 :attr:`ProviderPage.declared_total`이 소유한다(0 이하 = 없음).
    """

    page = client.oceans_beach_info(
        sido,
        page_no=page_no,
        num_of_rows=num_of_rows,
    )
    return ProviderPage(items=list(page.items), total_count=page.total_count)


_AIRKOREA_SIDO_NAMES: Final[tuple[str, ...]] = (
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "경기",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
    "세종",
)
"""airkorea ``sido_measurements`` 전국 순회용 17개 시도명(``SidoName`` 값)."""


def _airkorea_client(settings: KorTravelMapSettings, *, label: str) -> Any:
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            f"airkorea {label} live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    airkorea = cast(Any, importlib.import_module("airkorea"))
    return airkorea.AirKoreaClient(
        service_key=secret.get_secret_value(),
        timeout=settings.provider_http_timeout_seconds,
        retries=upstream_retry.PROVIDER_CLIENT_INNER_RETRIES,
    )


AIRKOREA_RETRYABLE_EXCEPTION_NAMES: Final[tuple[str, ...]] = (
    "AirKoreaNetworkError",
    "AirKoreaServerError",
)
"""airkorea 재시도 대상 예외 top-level 이름 — 실 lib과의 계약은 contract 테스트가
고정한다. ``AirKoreaRateLimitError``(코드 22 — 일일 쿼터 소진)는 transient가
아니므로 **의도적으로 제외**(리뷰 H — 쿼터 보호와 충돌)."""


def _airkorea_retryable_types() -> tuple[type[BaseException], ...]:
    """airkorea 예외 중 재시도 대상 — 네트워크/서버(H45).

    인증·파싱·NO_DATA·쿼터는 재시도 무의미라 제외한다. airkorea lib은 kma의
    ``retryable`` 속성 규약이 없어 타입으로 분류한다. 패키지 top-level
    re-export에서 읽되, 부재 시(예: 테스트 fake 모듈) 빈 tuple로 degrade하고
    경고를 남긴다 — 재시도 없이 종전 즉시-전파 동작(무음 금지, 리뷰 M).
    """

    airkorea = cast(Any, importlib.import_module("airkorea"))
    resolved = tuple(
        candidate
        for name in AIRKOREA_RETRYABLE_EXCEPTION_NAMES
        if isinstance(candidate := getattr(airkorea, name, None), type)
        and issubclass(candidate, BaseException)
    )
    if len(resolved) != len(AIRKOREA_RETRYABLE_EXCEPTION_NAMES):
        _LOGGER.warning(
            "airkorea 재시도 예외 분류 불완전 — %d/%d 이름만 해석됨: 재시도가 "
            "부분/전체 비활성 상태로 degrade한다 (H45)",
            len(resolved),
            len(AIRKOREA_RETRYABLE_EXCEPTION_NAMES),
        )
    return resolved


def _airkorea_close(client: Any) -> None:
    close = getattr(client, "close", None)
    if callable(close):
        close()


def fetch_airkorea_stations(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """대기질 측정소 메타데이터를 airkorea public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``AirKoreaClient(service_key=...)``를 열고
    ``stations(page_no=N)``을 페이지네이션하며 ``Station``(krtour
    ``AirQualityStationItem`` Protocol 충족, station_name/addr/lat/lon)을 yield.
    측정소는 weather-kind feature가 되고 측정값은 별도 fetcher가 가져온다.
    """
    client = _airkorea_client(settings, label="stations")
    retryable_types = _airkorea_retryable_types()
    budget = _provider_retry_budget(settings, expected_calls=1)
    num_of_rows = 100
    try:

        def _page(page_no: int) -> ProviderPage:
            # H45(리뷰 1 M-3): air_quality asset이 stations를 먼저 읽으므로 이
            # 경계도 동일 재시도 — 절반만 고치면 증상이 그대로 남는다.
            items = retry_upstream(
                partial(_airkorea_stations_page, client, page_no, num_of_rows),
                label=f"airkorea stations p{page_no}",
                base_delay=upstream_retry.PROVIDER_BOUNDARY_BASE_DELAY_SECONDS,
                is_retryable=lambda exc: isinstance(exc, retryable_types),
                budget=budget,
                on_retry=_LOGGER.warning,
            )
            # ``client.stations``는 Page가 아니라 iterable을 돌려주므로 선언 건수를
            # 알 수 없다. 대신 provider가 totalCount 결측 + 만재 페이지에서
            # ``AirKoreaParseError``로 fail-close한다(핀 a206282→…).
            return ProviderPage(items=items, total_count=None)

        yield from iter_paginated_items(
            _page,
            num_of_rows=num_of_rows,
            label="airkorea stations",
            warn=_LOGGER.warning,
        )
    finally:
        _airkorea_close(client)


def _airkorea_stations_page(client: Any, page_no: int, num_of_rows: int) -> list[Any]:
    """측정소 1페이지를 재시도 경계 안에서 소진한다(H45 — lazy 우회 방지)."""

    return list(client.stations(page_no=page_no, num_of_rows=num_of_rows))


def fetch_airkorea_air_quality(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """대기질 실시간 측정값을 airkorea public client로 stream한다.

    시도별(``_AIRKOREA_SIDO_NAMES``) ``sido_measurements(sido, page_no=N)``을
    페이지네이션하며 ``AirQualityMeasurement``(krtour ``AirQualityMeasurementItem``
    Protocol 충족)를 yield한다. 측정소명으로 station feature에 조인된다.
    """
    client = _airkorea_client(settings, label="air_quality")
    retryable_types = _airkorea_retryable_types()
    budget = _provider_retry_budget(
        settings,
        expected_calls=len(_AIRKOREA_SIDO_NAMES),
    )
    num_of_rows = 100
    try:
        for sido in _AIRKOREA_SIDO_NAMES:

            def _page(page_no: int, sido: str = sido) -> ProviderPage:
                # H45: 시도×페이지 단건 호출만 유한 재시도 — 17개 시도 순회가
                # upstream 간헐 504(실측 SERVICETIMEOUT_ERROR)에 전멸하지 않게.
                items = retry_upstream(
                    partial(
                        _airkorea_sido_page,
                        client,
                        sido,
                        page_no=page_no,
                        num_of_rows=num_of_rows,
                    ),
                    label=f"airkorea sido_measurements {sido} p{page_no}",
                    base_delay=upstream_retry.PROVIDER_BOUNDARY_BASE_DELAY_SECONDS,
                    is_retryable=lambda exc: isinstance(exc, retryable_types),
                    budget=budget,
                    on_retry=_LOGGER.warning,
                )
                return ProviderPage(items=items, total_count=None)

            yield from iter_paginated_items(
                _page,
                num_of_rows=num_of_rows,
                label=f"airkorea sido_measurements {sido}",
                warn=_LOGGER.warning,
            )
    finally:
        _airkorea_close(client)


def _airkorea_sido_page(client: Any, sido: str, *, page_no: int, num_of_rows: int) -> list[Any]:
    """시도별 측정값 1페이지를 **재시도 경계 안에서** 소진한다 — lazy iterator를
    경계 밖으로 내보내면 소비 중 network 예외가 재시도를 우회한다(H45)."""

    return list(client.sido_measurements(sido, page_no=page_no, num_of_rows=num_of_rows))


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
        raise ProviderCredentialMissing(f"opinet_scope_bbox 숫자 파싱 실패: {raw!r}") from exc
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
    invalid_parameter = _opinet_invalid_parameter_error_type()
    seen: set[str] = set()
    for min_lon, min_lat, max_lon, max_lat in bboxes:
        try:
            stations = client.iter_stations_in_bbox(
                min_lon=min_lon,
                min_lat=min_lat,
                max_lon=max_lon,
                max_lat=max_lat,
                radius_m=radius_m,
            )
            for station in stations:
                uni_id = getattr(station, "uni_id", None)
                if isinstance(uni_id, str):
                    if uni_id in seen:
                        continue
                    seen.add(uni_id)
                yield station
        except invalid_parameter as exc:
            # provider가 bbox 격자 셀 수 상한(`_MAX_BBOX_GRID_CELLS`)을 넘으면
            # `OpinetInvalidParameterError`를 던진다. 셀 수는 bbox 넓이와
            # radius_m의 함수인데 provider의 계산이 private이라 Map이 복제하면
            # drift가 난다. 대신 실패를 **실제 설정 이름으로 번역**해, run 중간의
            # 불투명한 provider 예외가 아니라 조치 가능한 설정 오류로 만든다.
            raise RuntimeError(
                "opinet bbox 격자가 provider 상한을 넘었다 — "
                f"bbox=({min_lon},{min_lat},{max_lon},{max_lat}), "
                f"opinet_scope_radius_m={radius_m}. "
                "반경을 키우거나(기본 5000은 전국 bbox에서 안전) "
                "OPINET_SCOPE_BBOX를 좁게 나눌 것."
            ) from exc


def _center_radius_to_bbox(
    lon: float, lat: float, radius_km: float
) -> tuple[float, float, float, float]:
    """중심(lon/lat) + 반경(km) → WGS84 bbox(min_lon,min_lat,max_lon,max_lat).

    위도 1° ≈ 111km, 경도 1° ≈ 111·cos(lat)km 근사. 극단 위도 방어를 위해
    cos는 최소값으로 clamp한다.
    """
    dlat = radius_km / 111.0
    cos_lat = max(math.cos(math.radians(lat)), 0.01)
    dlon = radius_km / (111.0 * cos_lat)
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


# OpiNet POI-타깃 enumeration 대상 = **모든 외부 시스템**의 활성 target.
# ``external_system``은 provider명이 아니라 외부 호출자(예: external-app)다(POI 모델,
# docs/poi-cache-update-targets.md) — provider명으로 재해석하면 실제 등록 target을
# 전부 놓친다. active 정의는 scope_repo.resolve_cache_target_keys와 동일:
# deleted_at IS NULL + update_enabled + refresh_policy<>'disabled'. 추가로 해당 target이
# provider_overrides에서 opinet dataset을 targeted_policy='disabled'로 옵트아웃했으면 제외.
_OPINET_POI_TARGETS_SQL: Final[str] = """
SELECT lon, lat, radius_km
FROM ops.poi_cache_targets
WHERE deleted_at IS NULL
  AND update_enabled
  AND refresh_policy <> 'disabled'
  AND COALESCE(
        (provider_overrides -> :opinet_key) ->> 'targeted_policy', ''
      ) <> 'disabled'
"""

_OPINET_PROVIDER_OVERRIDE_KEY: Final[str] = f"{OPINET_PROVIDER_NAME}:{OPINET_STATION_DATASET_KEY}"
"""``provider_overrides`` JSONB 키(``<provider>:<dataset_key>``)."""

_OPINET_LOW_TOP_PRODUCTS: Final[tuple[str, ...]] = ("B027", "D047", "B034")
"""quota-safe 전국 분포용 제품 코드: 휘발유, 경유, 고급휘발유."""

_OPINET_VALID_SIDO_CODES: Final[frozenset[str]] = frozenset(
    {
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
        "07",
        "08",
        "09",
        "10",
        "11",
        "14",
        "15",
        "16",
        "17",
        "18",
        "19",
    }
)
"""``python-opinet-api``가 자식 area 조회에서 허용하는 OpiNet 시도 코드."""

_OPINET_LOW_TOP_COUNT: Final[int] = 20
"""OpiNet ``lowTop10`` endpoint 최대 허용 건수."""

_OPINET_LOW_TOP_FALLBACK_MIN_STATIONS: Final[int] = 500
"""``lowTop10`` 부분 성공을 전국 분포로 보기 위한 최소 station 수."""

_OPINET_LOW_TOP_MAX_AREA_PRODUCT_CALLS: Final[int] = 180
"""``lowTop10`` area×product 호출 상한 기본값. 이후 sample grid fallback으로 보강한다.

``settings.opinet_low_top_max_calls`` (env ``KOR_TRAVEL_MAP_OPINET_LOW_TOP_MAX_CALLS``)로
run별 override 가능 — 기본 180 = 제품 3종 기준 시군 60개 윈도/run."""

_OPINET_RUN_CALL_BUDGET: Final[int] = 600
"""``low_top_area`` 한 run이 쓸 수 있는 OpiNet 호출 hard cap 기본값(#545).

``get_area_codes`` + ``lowTop10`` + ``aroundAll``(``search_stations_around``)을
모두 합산해 이 값을 넘으면 enumeration을 즉시 중단한다. OpiNet 무료키 일일 한도는
1,500회/일이고 가격 asset은 하루 1회 적재이므로 600/run이면 월간 place job과 같은
경로가 같은 날 한 번 더 돌아도(=1,200) 한도 아래로 유지된다. ``lowTop10`` 상한
(180) + ``get_area_codes``(~19)을 제외하면 grid fallback에 ~400회가 남아 빈 운영
상태의 분포 보강도 가능하다. ``settings.opinet_run_call_budget``
(env ``KOR_TRAVEL_MAP_OPINET_RUN_CALL_BUDGET``)로 override 가능."""

_OPINET_SAMPLE_GRID_BBOX: Final[tuple[float, float, float, float]] = (
    124.8,
    33.1,
    131.6,
    38.6,
)
"""``lowTop10``이 빈 응답일 때 쓰는 대한민국 주변 샘플 bbox."""

_OPINET_SAMPLE_ANCHOR_CENTERS: Final[tuple[tuple[float, float], ...]] = (
    (126.9780, 37.5665),  # 서울
    (126.7052, 37.4563),  # 인천
    (127.0286, 37.2636),  # 수원
    (127.1265, 37.4200),  # 성남
    (126.8319, 37.6584),  # 고양
    (127.1776, 37.2411),  # 용인
    (127.0471, 37.7381),  # 의정부
    (127.7298, 37.8813),  # 춘천
    (127.9202, 37.3422),  # 원주
    (128.8962, 37.7519),  # 강릉
    (127.3845, 36.3504),  # 대전
    (127.4890, 36.6424),  # 청주
    (127.9259, 36.9910),  # 충주
    (127.1522, 36.8151),  # 천안
    (127.0046, 36.7898),  # 아산
    (127.2890, 36.4800),  # 세종
    (127.1190, 36.4467),  # 공주
    (127.1480, 35.8242),  # 전주
    (126.7368, 35.9676),  # 군산
    (126.9576, 35.9483),  # 익산
    (126.8514, 35.1595),  # 광주
    (126.3922, 34.8118),  # 목포
    (127.6622, 34.7604),  # 여수
    (127.4872, 34.9506),  # 순천
    (128.6014, 35.8714),  # 대구
    (129.3650, 36.0190),  # 포항
    (128.3446, 36.1195),  # 구미
    (128.7294, 36.5684),  # 안동
    (129.2247, 35.8562),  # 경주
    (129.0756, 35.1796),  # 부산
    (129.3114, 35.5384),  # 울산
    (128.6811, 35.2279),  # 창원
    (128.1076, 35.1800),  # 진주
    (128.8894, 35.2285),  # 김해
    (128.6211, 34.8806),  # 거제
    (126.5312, 33.4996),  # 제주
    (126.5601, 33.2541),  # 서귀포
)
"""Sparse grid가 도심을 비켜갈 때 보강할 전국 주요 도심 fallback anchor."""

_OPINET_SAMPLE_GRID_STEP_DEGREES: Final[float] = 0.4
"""OpiNet fallback 샘플 그리드 간격. 도심 anchor 포함 3개 제품 기준 약 900회 호출."""


def _opinet_poi_target_bboxes(
    settings: KorTravelMapSettings,
) -> list[tuple[float, float, float, float]]:
    """``ops.poi_cache_targets``의 활성 target(중심+반경) → bbox 목록(OpiNet enumeration).

    ``external_system``으로 필터하지 않는다(provider 아님). active target = deleted_at
    없음 + update_enabled + refresh_policy<>'disabled'(scope_repo와 동일), opinet을
    targeted_policy='disabled'로 옵트아웃한 target 제외. fetcher는 sync라
    ``settings.pg_dsn``(async driver)을 sync psycopg DSN으로 바꿔 짧게 조회한다.
    """
    dsn = require_pg_dsn(settings).get_secret_value().replace("+asyncpg", "+psycopg")
    engine = create_engine(dsn)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(_OPINET_POI_TARGETS_SQL),
                {"opinet_key": _OPINET_PROVIDER_OVERRIDE_KEY},
            ).all()
    finally:
        engine.dispose()
    return [
        _center_radius_to_bbox(float(lon), float(lat), float(radius_km))
        for lon, lat, radius_km in rows
    ]


def _opinet_bboxes_for_settings(
    settings: KorTravelMapSettings,
) -> list[tuple[float, float, float, float]]:
    mode = settings.opinet_scope_mode
    if mode == "disabled":
        raise ProviderCredentialMissing(
            "opinet 적재 비활성(opinet_scope_mode=disabled). "
            "OPINET_SCOPE_MODE=bbox|poi_cache_target|low_top_area 설정이 필요하다."
        )
    if mode == "bbox":
        if settings.opinet_scope_bbox is None:
            raise ProviderCredentialMissing(
                "opinet bbox scope에는 OPINET_SCOPE_BBOX "
                "(min_lon,min_lat,max_lon,max_lat)가 필요하다."
            )
        return [_parse_opinet_bbox(settings.opinet_scope_bbox)]

    bboxes = _opinet_poi_target_bboxes(settings)
    if not bboxes:
        raise ProviderCredentialMissing(
            "opinet poi_cache_target scope: ops.poi_cache_targets에 "
            "external_system='opinet' 활성 target이 없다."
        )
    return bboxes


class _OpinetCallBudget:
    """``low_top_area`` run의 OpiNet 호출 수를 추적하는 hard cap(#545).

    ``get_area_codes`` + ``lowTop10`` + ``aroundAll`` 호출을 한 카운터로 합산한다.
    각 호출 **직전** ``spend()``로 차감하고, 남은 예산이 없으면 ``exhausted``가
    ``True``가 되어 enumeration을 즉시 멈춘다. cap을 0 이하로 주면(또는 None)
    무제한으로 동작한다(테스트/특수 운영용).
    """

    __slots__ = ("_remaining", "_unbounded")

    def __init__(self, limit: int | None) -> None:
        if limit is None or limit <= 0:
            self._unbounded = True
            self._remaining = 0
        else:
            self._unbounded = False
            self._remaining = int(limit)

    @property
    def exhausted(self) -> bool:
        return not self._unbounded and self._remaining <= 0

    def spend(self) -> bool:
        """호출 1건을 예산에서 차감한다. 차감 가능하면 ``True``."""
        if self._unbounded:
            return True
        if self._remaining <= 0:
            return False
        self._remaining -= 1
        return True


def _opinet_sigungu_area_codes(
    client: Any, *, budget: _OpinetCallBudget | None = None
) -> list[str]:
    """OpiNet 시군구 area code 목록.

    ``lowTop10`` 전국 분포 모드에서 사용한다. 시도별 시군구가 없으면 해당 시도
    코드를 fallback으로 사용해 호출량을 bounded하게 유지한다. ``budget``이 주어지면
    각 ``get_area_codes`` 호출을 run 예산에서 차감하고, 소진되면 지금까지 모은 area를
    반환하고 조기 종료한다(#545). 반환 순서는 시도별 round-robin으로 섞어 호출 상한에
    걸려도 서울/수도권 같은 첫 시도에만 표본이 몰리지 않게 한다.
    """
    groups: list[list[str]] = []
    if budget is not None and not budget.spend():
        return []
    for sido in client.get_area_codes():
        sido_code = str(getattr(sido, "code", "")).strip()
        if not sido_code:
            continue
        if sido_code not in _OPINET_VALID_SIDO_CODES:
            continue
        if budget is not None and not budget.spend():
            break
        sigungu_codes = [
            str(getattr(sigungu, "code", "")).strip()
            for sigungu in client.get_area_codes(sido_code)
        ]
        sigungu_codes = [code for code in sigungu_codes if code]
        groups.append(sigungu_codes or [sido_code])

    areas: list[str] = []
    max_group_len = max((len(group) for group in groups), default=0)
    for index in range(max_group_len):
        for group in groups:
            if index < len(group):
                areas.append(group[index])
    return areas


def _opinet_sample_grid_centers() -> Iterator[tuple[float, float]]:
    """전국 유가 분포용 bounded sample grid center를 반환한다."""
    seen: set[tuple[float, float]] = set()
    for lon, lat in _OPINET_SAMPLE_ANCHOR_CENTERS:
        center = (round(lon, 6), round(lat, 6))
        seen.add(center)
        yield center

    min_lon, min_lat, max_lon, max_lat = _OPINET_SAMPLE_GRID_BBOX
    lat = min_lat
    while lat <= max_lat:
        lon = min_lon
        while lon <= max_lon:
            center = (round(lon, 6), round(lat, 6))
            if center not in seen:
                seen.add(center)
                yield center
            lon += _OPINET_SAMPLE_GRID_STEP_DEGREES
        lat += _OPINET_SAMPLE_GRID_STEP_DEGREES


def _opinet_invalid_parameter_error_type() -> type[Exception]:
    """``OpinetInvalidParameterError``를 lazy resolve한다 (ADR-006 — 직접 import 금지).

    provider에 없으면 아무것도 잡지 않도록 절대 매칭되지 않는 예외형을 돌려준다.
    """
    opinet = importlib.import_module("opinet")
    resolved = getattr(opinet, "OpinetInvalidParameterError", None)
    if isinstance(resolved, type) and issubclass(resolved, Exception):
        return resolved
    return _NeverRaised


class _NeverRaised(Exception):
    """provider 예외형을 해석하지 못했을 때의 no-op sentinel."""


def _opinet_no_data_error_type() -> type[Exception]:
    """현재 설치된 ``opinet`` 모듈의 빈 응답 예외 타입."""
    opinet = importlib.import_module("opinet")
    error_type = getattr(opinet, "OpinetNoDataError", RuntimeError)
    if isinstance(error_type, type) and issubclass(error_type, Exception):
        return error_type
    return RuntimeError


def _opinet_rotation_offset(*, window_areas: int, on_date: date | None = None) -> int:
    """시군 윈도 로테이션 offset (일 단위 결정적, KST 날짜 기준).

    호출 상한 때문에 한 run은 시군 목록의 앞쪽 윈도(기본 60개)만 소비한다 —
    offset 없이는 매일 같은 시군만 갱신되고 나머지는 영구 stale이 된다(37%가
    3–7일 stale이던 prod 근본 원인). run 날짜의 ``toordinal() × 윈도 크기``를
    offset으로 쓰면 매일 윈도 크기만큼 전진해 전국(~230 시군)을 ≈4일에 1주기로
    순회한다. 실제 나머지 연산(``% len(areas)``)은 area 목록을 아는 사용처에서
    수행한다. ``on_date``를 고정하면 테스트가 결정적이다.
    """
    if on_date is None:
        on_date = kst_now().date()
    return on_date.toordinal() * max(window_areas, 1)


def _opinet_low_top_area_stations(
    client: Any,
    *,
    dedupe_by_product: bool,
    max_low_top_calls: int = _OPINET_LOW_TOP_MAX_AREA_PRODUCT_CALLS,
    run_call_budget: int = _OPINET_RUN_CALL_BUDGET,
    rotation_offset: int | None = None,
) -> Iterator[Any]:
    """시군구별 저가 주유소를 stream한다.

    전국 bbox exhaustive enumeration은 OpiNet 일일 한도를 초과하므로, 지도
    분포용으로 ``lowTop10``을 시군구×제품 단위로 먼저 호출한다. 운영 API가
    빈 응답 또는 비정상적으로 작은 부분 응답을 반환하면 bounded sample grid의
    ``aroundAll``로 fallback한다.

    호출량 가드(#545):

    - run당 hard budget(``run_call_budget``)으로 ``get_area_codes`` +
      ``lowTop10`` + ``aroundAll`` 호출을 합산해 초과 시 즉시 중단한다.
    - ``lowTop10``이 충분히(``_OPINET_LOW_TOP_FALLBACK_MIN_STATIONS``) 산출되면
      grid fallback을 **건너뛴다**(부분 성공 후 전체 grid를 도는 케이스 차단).
    - 서버가 먼저 ``OpinetRateLimitError``를 던지면 run을 실패시킨다. 일부 record를
      얻었더라도 성공으로 삼으면 sync cursor가 전진해 갱신 장애가 숨겨지기 때문이다.

    시군 윈도 로테이션: ``rotation_offset``(기본 = 오늘 KST 날짜 기반
    ``_opinet_rotation_offset``)만큼 area 목록을 회전시켜 매 run이 다른 시군
    윈도를 소비한다 — 전체 목록이 한 윈도에 다 들어가면 회전은 no-op이다.
    """
    seen: set[str | tuple[str, str | None]] = set()
    yielded = 0
    low_top_calls = 0
    no_data_error = _opinet_no_data_error_type()
    budget = _OpinetCallBudget(run_call_budget)
    window_areas = max(max_low_top_calls // max(len(_OPINET_LOW_TOP_PRODUCTS), 1), 1)
    if rotation_offset is None:
        rotation_offset = _opinet_rotation_offset(window_areas=window_areas)

    def _dedupe_key(station: Any) -> str | tuple[str, str | None] | None:
        uni_id = getattr(station, "uni_id", None)
        if not isinstance(uni_id, str):
            return None
        if not dedupe_by_product:
            return uni_id
        raw_product = getattr(station, "product_code", None)
        product = getattr(raw_product, "value", raw_product)
        return (uni_id, str(product) if product is not None else None)

    def _emit(stations: Any) -> Iterator[Any]:
        nonlocal yielded
        for station in stations:
            key = _dedupe_key(station)
            if key is None:
                yielded += 1
                yield station
                continue
            if key in seen:
                continue
            seen.add(key)
            yielded += 1
            yield station

    areas = _opinet_sigungu_area_codes(client, budget=budget)
    if len(areas) > window_areas:
        # 윈도보다 목록이 크면 run 날짜 기반 offset으로 회전 — 매일 윈도 크기만큼
        # 전진해 전국을 ≈ ceil(len/윈도)일에 1주기로 순회한다. round-robin 인접
        # area는 서로 다른 시도라 윈도 안 지리 분포 공정성은 유지된다.
        shift = rotation_offset % len(areas)
        areas = areas[shift:] + areas[:shift]

    for area in areas:
        if budget.exhausted:
            break
        for product_code in _OPINET_LOW_TOP_PRODUCTS:
            if low_top_calls >= max_low_top_calls:
                break
            if not budget.spend():
                break
            low_top_calls += 1
            try:
                stations = client.get_lowest_price_top20(
                    product_code,
                    cnt=_OPINET_LOW_TOP_COUNT,
                    area=area,
                )
            except no_data_error:
                continue
            yield from _emit(stations)
        if budget.exhausted or low_top_calls >= max_low_top_calls:
            break

    # 부분 성공이라도 분포 임계치를 넘겼으면 grid fallback을 돌지 않는다(#545).
    # budget이 이미 소진됐어도 grid를 시작하지 않는다.
    if budget.exhausted or yielded >= _OPINET_LOW_TOP_FALLBACK_MIN_STATIONS:
        return

    for center_lon, center_lat in _opinet_sample_grid_centers():
        if budget.exhausted:
            break
        for product_code in _OPINET_LOW_TOP_PRODUCTS:
            if not budget.spend():
                break
            try:
                stations = client.search_stations_around(
                    lon=center_lon,
                    lat=center_lat,
                    radius_m=5000,
                    prodcd=product_code,
                )
            except no_data_error:
                continue
            yield from _emit(stations)


def fetch_opinet_stations(
    settings: KorTravelMapSettings,
    *,
    rotation_offset: int | None = None,
) -> Iterator[Any]:
    """OpiNet 주유소 record를 scope(bbox/POI-타깃)별로 stream한다(T-RV-04b).

    OpiNet은 전국 dump endpoint가 없어 ``iter_stations_in_bbox``(aroundAll 격자
    근사) 또는 ``lowTop10`` 지역별 목록으로 영역을 enumerate한다. scope는
    ``settings.opinet_scope_mode``:

    - ``disabled`` — 미적재(guard).
    - ``bbox`` — ``opinet_scope_bbox`` 영역 1개 enumerate.
    - ``poi_cache_target`` — ``ops.poi_cache_targets``의 opinet 활성 target(중심+반경)을
      bbox로 변환해 enumerate(여러 target 간 ``uni_id`` dedup).
    - ``low_top_area`` — 시군구별 저가 목록으로 전국 분포를 bounded 호출량으로 적재.

    sync generator, finally close.
    """
    secret = settings.opinet_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "opinet live fetch에는 KOR_TRAVEL_MAP_OPINET_API_KEY (source OPINET_API_KEY)가 "
            "필요하다."
        )

    bboxes: list[tuple[float, float, float, float]] | None = None
    if settings.opinet_scope_mode != "low_top_area":
        bboxes = _opinet_bboxes_for_settings(settings)
    opinet = cast(Any, importlib.import_module("opinet"))
    client = opinet.OpinetClient(api_key=secret.get_secret_value())
    try:
        if settings.opinet_scope_mode == "low_top_area":
            yield from _opinet_low_top_area_stations(
                client,
                dedupe_by_product=False,
                max_low_top_calls=settings.opinet_low_top_max_calls,
                run_call_budget=settings.opinet_run_call_budget,
                rotation_offset=rotation_offset,
            )
            return
        assert bboxes is not None
        yield from _enumerate_opinet_stations(
            client, bboxes, radius_m=settings.opinet_scope_radius_m
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def fetch_opinet_station_price_details(
    settings: KorTravelMapSettings,
    *,
    rotation_offset: int | None = None,
) -> Iterator[Any]:
    """현재 OpiNet scope의 가격 record를 stream한다.

    ``bbox``/``poi_cache_target``은 기존처럼 ``detailById``를 반환하고,
    ``low_top_area``는 ``lowTop10`` Station row를 반환한다. asset 변환기가 row shape에
    따라 detail/단일 제품 가격 경로를 고른다.
    """
    secret = settings.opinet_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "opinet price live fetch에는 KOR_TRAVEL_MAP_OPINET_API_KEY "
            "(source OPINET_API_KEY)가 필요하다."
        )

    bboxes: list[tuple[float, float, float, float]] | None = None
    if settings.opinet_scope_mode != "low_top_area":
        bboxes = _opinet_bboxes_for_settings(settings)
    opinet = cast(Any, importlib.import_module("opinet"))
    client = opinet.OpinetClient(api_key=secret.get_secret_value())
    try:
        if settings.opinet_scope_mode == "low_top_area":
            yield from _opinet_low_top_area_stations(
                client,
                dedupe_by_product=True,
                max_low_top_calls=settings.opinet_low_top_max_calls,
                run_call_budget=settings.opinet_run_call_budget,
                rotation_offset=rotation_offset,
            )
            return
        assert bboxes is not None
        for station in _enumerate_opinet_stations(
            client, bboxes, radius_m=settings.opinet_scope_radius_m
        ):
            yield client.get_station_detail(station.uni_id)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def fetch_standard_parking_lots(
    settings: KorTravelMapSettings,
) -> Iterator[Any]:
    """전국주차장표준데이터 record를 datagokr public client로 stream한다.

    ``client.parking.iter_all()``의 record(``PublicParkingLot``, krtour
    ``PublicParkingLotItem`` Protocol 충족)를 yield. sync generator, finally close.
    """
    secret = settings.data_go_kr_service_key
    if secret is None:
        raise ProviderCredentialMissing(
            "standard parking lots live fetch에는 "
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
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
    settings: KorTravelMapSettings,
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
            "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY (source DATA_GO_KR_SERVICE_KEY)가 "
            "필요하다."
        )
    api_key = secret.get_secret_value()

    visitkorea = cast(Any, importlib.import_module("visitkorea"))
    client = visitkorea.KrTourApiClient(service_key=api_key)
    kst = timezone(timedelta(hours=9))
    start = date(datetime.now(kst).year, 1, 1)
    try:
        for page in client.iter_pages(client.search_festival, start, num_of_rows=100):
            yield from page.items
    finally:
        client.close()

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

import asyncio
import importlib
import logging
import pathlib
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Mapping,
)
from datetime import UTC, date, datetime, timedelta, timezone
from functools import partial
from typing import TYPE_CHECKING, Any, Final, cast

import httpx
from kortravelmap.providers.kor_travel_transport import (
    EXPORT_PATH_AIRPORTS,
    EXPORT_PATH_FUEL_STATIONS,
    EXPORT_PATH_HIGHWAY_INCIDENTS_ACTIVE,
    EXPORT_PATH_REST_AREA_FUEL_PRICES,
    EXPORT_PATH_REST_AREAS,
    SERVICE_TOKEN_HEADER,
    TransportAirport,
    TransportExportContractError,
    TransportExportEmpty,
    TransportExportFailure,
    TransportExportHidden,
    TransportExportNotCurrent,
    TransportFuelStation,
    TransportHighwayIncident,
    TransportRestArea,
    TransportRestAreaFuelPrice,
    parse_active_incident_set,
    parse_airports,
    parse_export_page,
    parse_fuel_station,
    parse_rest_area,
    parse_rest_area_fuel_price,
    require_current_collection,
    require_fresh_incident_set,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from . import upstream_retry
from .provider_pagination import (
    ProviderPage,
    ProviderPaginationOverrun,
    aiter_paginated_items,
)
from .quota_exhaustion import quota_exhaustion_cause
from .upstream_requests import note_upstream_request

if TYPE_CHECKING:
    from kortravelmap.settings import KorTravelMapSettings

_LOGGER = logging.getLogger(__name__)
"""H45 재시도 텔레메트리. ``docker/dagster.yaml``의 ``python_logs``가 이
logger의 WARNING 이상을 Dagster event stream으로 결선한다."""

__all__ = [
    "ProviderCredentialMissing",
    "SeoulOpenDataError",
    "fetch_datagokr_cultural_festivals",
    "fetch_datagokr_file_data_records",
    "fetch_khoa_beaches",
    "fetch_seoul_open_data_bookstores",
    "fetch_knps_geometry_records",
    "fetch_knps_point_records",
    "fetch_krforest_arboretums",
    "fetch_krforest_dulle_trails",
    "fetch_krforest_landslide_forecast_issues",
    "fetch_krforest_mountain_trails",
    "fetch_krforest_recreation_forests",
    "fetch_krheritage_events",
    "fetch_krheritage_items",
    "fetch_mcst_culture_records",
    "fetch_mois_license_records",
    "fetch_standard_museums",
    "fetch_standard_parking_lots",
    "fetch_standard_special_streets",
    "fetch_standard_tourist_attractions",
    "fetch_kor_travel_concierge_youtube_features",
    "fetch_transport_airports",
    "fetch_transport_fuel_stations",
    "fetch_transport_highway_incidents",
    "fetch_transport_rest_area_fuel_prices",
    "fetch_transport_rest_areas",
    "fetch_visitkorea_festival_events",
]


class ProviderCredentialMissing(RuntimeError):
    """provider live fetch에 필요한 credential이 설정되지 않았을 때."""


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
            note_upstream_request()
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

# -- kor-travel-transport export (ADR-106) -----------------------------------------
#
# OpiNet 주유소·유가, KREX 휴게소·휴게소 유가·돌발, 공항은 provider 라이브러리가 아니라
# kor-travel-transport의 ``/v1/service/exports/*``에서 받는다. 이것은 공개 provider client의
# wrapper가 아니라(ADR-006은 그쪽 규칙이다) 같은 플랫폼 내부 서비스의 계약을 읽는 fetcher다 —
# kor-travel-concierge export와 같은 부류. 응답은 ``providers.kor_travel_transport``가 엄격히
# 파싱하고, 계약이 어긋나면 적재 전에 실패한다.


def _transport_connection(settings: KorTravelMapSettings) -> tuple[str, dict[str, str]]:
    """base URL과 인증 header. 빈 문자열도 미설정으로 본다(compose ``${X:-}``)."""
    base_url = (settings.kor_travel_transport_base_url or "").strip()
    token = settings.kor_travel_transport_service_token
    secret = token.get_secret_value().strip() if token is not None else ""
    if not base_url:
        raise ProviderCredentialMissing(
            "kor-travel-transport export에는 "
            "KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_BASE_URL이 필요하다."
        )
    if not secret:
        raise ProviderCredentialMissing(
            "kor-travel-transport export에는 KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_SERVICE_TOKEN"
            "(transport TRANSPORT_SERVICE_EXPORT_TOKEN과 같은 값)이 필요하다."
        )
    return base_url.rstrip("/"), {SERVICE_TOKEN_HEADER: secret}


_TRANSPORT_MAX_PAGES: Final[int] = 1000
"""페이지 루프 상한. 최대 page size 1000이면 100만 행 — 주유소 약 1.2만·휴게소 수백의 수십 배다.
넘으면 cursor가 순환하거나 계약이 깨진 것이다(같은 cursor 반복은 별도로 즉시 잡는다)."""

_TRANSPORT_TRANSIENT_STATUSES: Final[frozenset[int]] = frozenset({502, 504})
"""재시도할 HTTP 상태 — 같은 호스트의 transport 재기동·게이트웨이 순간 장애. 503은 재시도하지
않는다: transport가 "근거 수집이 현재가 아니다"라고 판정한 것이고 15초 안에 바뀌지 않는다."""

_TRANSPORT_RETRY_BASE_DELAY_SECONDS: float = upstream_retry.PROVIDER_BOUNDARY_BASE_DELAY_SECONDS
"""재시도 간격 기준(테스트가 0으로 바꾼다). 다른 내부·provider 경계와 같은 값이다."""


class _TransportTransientStatus(TransportExportFailure):
    """재시도 대상 상태(502/504). 시도를 다 쓰면 그대로 전파된다."""


def _transport_retryable(exc: BaseException) -> bool:
    """연결·timeout 같은 전송 오류와 502/504만 재시도한다. 404·503·계약 위반은 즉시 전파."""
    return isinstance(exc, httpx.TransportError | _TransportTransientStatus)


def _utcnow() -> datetime:
    """돌발 집합 나이 기준 시각(테스트가 고정한다)."""
    return datetime.now(UTC)


def _raise_transport_status(response: httpx.Response, path: str) -> None:
    status = response.status_code
    if status == 404:
        # transport는 토큰·접속 주소가 맞지 않으면 경로 자체를 숨긴다(transport ADR-013).
        # 404만으로는 셋을 가를 수 없다 — 자격증명 부재(설정 누락)는 요청 전에
        # ProviderCredentialMissing으로 난다.
        raise TransportExportHidden(
            f"kor-travel-transport {path}가 404다 — 셋 중 하나다: (1) 토큰이 transport "
            "TRANSPORT_SERVICE_EXPORT_TOKEN과 다르다 (2) 접속 주소가 transport "
            "SERVICE_EXPORT_ALLOWED_CLIENTS_CSV 밖이다(운영은 host network의 127.0.0.1, "
            "standalone은 docker bridge 대역을 열어야 한다) (3) transport가 이 export가 없는 "
            "버전이다."
        )
    if status == 503:
        raise TransportExportNotCurrent(
            f"kor-travel-transport {path}가 503이다 — 근거 수집의 이력이 없거나 실패했거나 "
            "stale이다(transport ADR-013). 이번 run은 아무것도 적재·삭제·종료하지 않는다."
        )
    if status in _TRANSPORT_TRANSIENT_STATUSES:
        raise _TransportTransientStatus(f"kor-travel-transport {path}가 {status}다.")
    response.raise_for_status()


async def _transport_request_once(
    client: httpx.AsyncClient, path: str, params: Mapping[str, Any]
) -> httpx.Response:
    """HTTP 요청 정확히 1건 — 시도마다 여기서 센다(재시도도 요청이다)."""
    note_upstream_request()
    response = await client.get(path, params=dict(params))
    _raise_transport_status(response, path)
    return response


async def _transport_get(
    client: httpx.AsyncClient,
    path: str,
    params: Mapping[str, Any],
    *,
    budget: upstream_retry.RetryBudget,
) -> httpx.Response:
    """요청 1건(전송 오류·502/504는 유한 재시도). 상태 해석까지 끝낸 응답만 돌려준다.

    재시도 규약은 ``upstream_retry``와 같다(시도 상한 ``DEFAULT_UPSTREAM_ATTEMPTS``, run 예산
    공유, 지수 backoff). 그 헬퍼에 콜러블을 넘기지 않고 여기서 도는 이유는 계수 게이트
    (``tests/lint/test_every_fetcher_counts_or_declares_why_not.py``)가 호출만 따라가기 때문이다 —
    시도마다 :func:`_transport_request_once`를 직접 불러야 재시도 요청까지 센다고 보인다.
    """
    attempts = upstream_retry.DEFAULT_UPSTREAM_ATTEMPTS
    for attempt in range(1, attempts + 1):
        try:
            return await _transport_request_once(client, path, params)
        except Exception as exc:
            if attempt >= attempts or not _transport_retryable(exc) or not budget.try_consume():
                raise
            delay = min(
                _TRANSPORT_RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
                upstream_retry.DEFAULT_UPSTREAM_MAX_DELAY_SECONDS,
            )
            _LOGGER.warning(
                "kor-travel-transport %s 재시도 %d/%d (%s)", path, attempt, attempts,
                type(exc).__name__,
            )
            await asyncio.sleep(delay)
    raise AssertionError(f"unreachable: kor-travel-transport {path}")  # pragma: no cover


async def _iter_transport_export(
    settings: KorTravelMapSettings,
    path: str,
    parse: Callable[[Mapping[str, Any]], Any],
) -> AsyncIterator[Any]:
    """cursor 페이지를 끝까지 읽어 파싱한 item을 낸다.

    각 페이지의 ``collection``이 현재가 아니면(이력 없음·실패·stale) 실패하고, 끝까지 0건이면
    :class:`TransportExportEmpty`로 실패한다 — 이 export들은 완전 snapshot reconcile의 근거라서
    빈·낡은 집합을 받아들이면 멀쩡한 feature가 지워진다. 소비자(``_record_list``)는 전부 모은 뒤에
    적재하므로 뒤 페이지의 실패도 적재 전에 run을 멈춘다.
    """
    base_url, headers = _transport_connection(settings)
    budget = upstream_retry.RetryBudget()
    cursor: str | None = None
    seen_cursors: set[str] = set()
    total = 0
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=settings.kor_travel_transport_timeout_seconds,
        headers=headers,
    ) as client:
        for _page_number in range(_TRANSPORT_MAX_PAGES):
            params: dict[str, Any] = {"limit": settings.kor_travel_transport_page_size}
            if cursor is not None:
                params["cursor"] = cursor
            response = await _transport_get(client, path, params, budget=budget)
            page = parse_export_page(response.json(), where=path)
            require_current_collection(page.collection, where=path)
            for item in page.items:
                total += 1
                yield parse(item)
            if not page.has_more:
                break
            assert page.next_cursor is not None  # parse_export_page가 보장한다.
            if page.next_cursor in seen_cursors or page.next_cursor == cursor:
                raise TransportExportContractError(
                    f"{path}: next_cursor {page.next_cursor!r}가 이미 지난 cursor다(순환)."
                )
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        else:
            raise TransportExportContractError(
                f"{path}: {_TRANSPORT_MAX_PAGES}페이지를 넘었다 — cursor 계약 이상."
            )
    if total == 0:
        raise TransportExportEmpty(
            f"kor-travel-transport {path}가 0건이다. 완전 snapshot으로 전량 삭제하지 않고 실패한다."
        )


async def fetch_transport_fuel_stations(
    settings: KorTravelMapSettings,
) -> AsyncIterator[TransportFuelStation]:
    """오피넷 주유소 + 유종별 최신 가격(transport 전국 수집본)."""
    async for station in _iter_transport_export(
        settings, EXPORT_PATH_FUEL_STATIONS, parse_fuel_station
    ):
        yield station


async def fetch_transport_rest_areas(
    settings: KorTravelMapSettings,
) -> AsyncIterator[TransportRestArea]:
    """고속도로 휴게소 기준정보."""
    async for area in _iter_transport_export(settings, EXPORT_PATH_REST_AREAS, parse_rest_area):
        yield area


async def fetch_transport_rest_area_fuel_prices(
    settings: KorTravelMapSettings,
) -> AsyncIterator[TransportRestAreaFuelPrice]:
    """휴게소 주유소 현재 유가."""
    async for price in _iter_transport_export(
        settings, EXPORT_PATH_REST_AREA_FUEL_PRICES, parse_rest_area_fuel_price
    ):
        yield price


async def fetch_transport_highway_incidents(
    settings: KorTravelMapSettings,
) -> AsyncIterator[TransportHighwayIncident]:
    """마지막 성공 수집의 활성 돌발 **전체**(페이지 없음).

    transport는 수집이 실패했거나 30분 넘게 성공하지 못했으면 503을 낸다. 그때 이 fetcher가
    실패해야 notice reconcile이 오래된 집합으로 사건을 닫지 않는다 — 503을 빈 집합으로
    바꾸면 활성 사건 전체가 해소로 오판된다. Map도 ``collection`` 플래그와 ``collected_at``
    나이(30분)를 다시 잰다(:func:`require_fresh_incident_set`). 빈 목록은 그 검사를 통과한
    뒤에만 "지금 돌발 없음"이라는 사실이다.
    """
    base_url, headers = _transport_connection(settings)
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=settings.kor_travel_transport_timeout_seconds,
        headers=headers,
    ) as client:
        response = await _transport_get(
            client,
            EXPORT_PATH_HIGHWAY_INCIDENTS_ACTIVE,
            {},
            budget=upstream_retry.RetryBudget(),
        )
        active = parse_active_incident_set(response.json())
    require_fresh_incident_set(active, now=_utcnow())
    for incident in active.items:
        yield incident


async def fetch_transport_airports(
    settings: KorTravelMapSettings,
) -> AsyncIterator[TransportAirport]:
    """국내 운영 공항 전체(transport의 krairport 번들 메타데이터)."""
    base_url, headers = _transport_connection(settings)
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=settings.kor_travel_transport_timeout_seconds,
        headers=headers,
    ) as client:
        response = await _transport_get(
            client, EXPORT_PATH_AIRPORTS, {}, budget=upstream_retry.RetryBudget()
        )
        airports = parse_airports(response.json())
    for airport in airports:
        yield airport


#: datagokr 표준데이터 요청 페이지 크기. provider의 ``DEFAULT_MAX_PAGE_SIZE``와 같다.
_DATAGOKR_STANDARD_PAGE_SIZE: Final[int] = 1000


def _iter_datagokr_standard(service: Any, *, label: str) -> AsyncIterator[Any]:
    """datagokr 표준데이터 service를 **Map의 페이지네이터로** 소진한다.

    provider의 ``iter_all()``을 쓰지 않는다. 그 구현은 짧은 페이지를 무조건
    마지막 페이지로 읽는데(`services/pagination.py`), 같은 릴리스에서 행 단위
    ``except ValidationError: continue``가 들어와 **기형 행 하나가 페이지를 짧게
    만든다.** 둘이 겹치면 18,000건짜리 데이터셋이 999건에서 조용히 끝난다 —
    예외도 로그도 없이. 그리고 Map은 그 결과를
    ``authoritative_snapshot_complete=True``로 봉인한다.

    이 저장소는 같은 부류를 이미 한 번 겪었다. ``provider_pagination`` 모듈이
    존재하는 이유가 ``python-krex-api``의 똑같은 변화이고, 그 규칙은
    **``total_count``가 권위이고 짧은 페이지는 total을 모를 때만 쓰는 대체
    휴리스틱**이다. datagokr도 그 규칙 아래로 옮긴다.
    """

    async def _page(page_no: int) -> ProviderPage:
        page = await service.list(
            page_no=page_no, num_of_rows=_DATAGOKR_STANDARD_PAGE_SIZE
        )
        return ProviderPage(items=list(page.items), total_count=page.total_count)

    return aiter_paginated_items(
        _page,
        num_of_rows=_DATAGOKR_STANDARD_PAGE_SIZE,
        label=label,
        warn=_LOGGER.warning,
    )



async def fetch_datagokr_cultural_festivals(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """전국문화축제표준데이터 record를 datagokr public client로 stream한다.

    ``settings.data_go_kr_service_key``에서 service key를 읽어
    ``DataGoKrClient(api_key=...)``를 열고 ``client.festival``
    record(``PublicCulturalFestival``, ``CulturalFestivalItem`` Protocol 충족)를
    lazily yield한다. generator가 살아 있는 동안 client는 열려 있고,
    소비 종료(또는 aclose)시 ``finally``에서 ``await client.aclose()``로 닫는다.
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
        async for record in _iter_datagokr_standard(
            client.festival, label="datagokr festival.list"
        ):
            yield record
    finally:
        await client.aclose()


#: 국가유산 행사 rolling window. provider ``iter_months`` 기본값과 같은 창이지만
#: **Map이 소유한다** — 요청 수를 셀 수 있어야 쿼터 비율을 말할 수 있다.
_KRHERITAGE_EVENT_MONTHS_BACK: Final[int] = 1
_KRHERITAGE_EVENT_MONTHS_AHEAD: Final[int] = 12


def _krheritage_event_months(anchor: date) -> Iterator[tuple[int, int]]:
    """``anchor`` 기준 rolling window의 ``(year, month)``를 순서대로 낸다.

    지난달 1개 + 이번 달 + 다음 12개월 = 14개. 그 수가 곧 이 fetcher의 요청 수다.
    """

    start = (anchor.year * 12) + (anchor.month - 1) - _KRHERITAGE_EVENT_MONTHS_BACK
    total = _KRHERITAGE_EVENT_MONTHS_BACK + _KRHERITAGE_EVENT_MONTHS_AHEAD + 1
    for offset in range(total):
        zero_based = start + offset
        yield zero_based // 12, (zero_based % 12) + 1


async def fetch_krheritage_events(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """국가유산 행사(event) record를 krheritage public client로 stream한다.

    ``settings.data_go_kr_service_key``에서 service key를 읽어
    ``HeritageClient(api_key=...)``를 열고 rolling window의 달마다
    ``client.event.by_month(...)``를 불러 record(``HeritageEvent``,
    ``KrHeritageEvent`` Protocol 충족)를 lazily yield 한다.
    async generator가 살아 있는 동안 client는 열려 있고, 소비 종료(또는 aclose)시
    ``finally``에서 ``await client.aclose()``로 닫는다.

    **``iter_months()`` 대신 Map이 직접 돈다.** 둘은 같은 창을 돌고 호출 수도
    같지만(:data:`_KRHERITAGE_EVENT_MONTHS_BACK`/``_AHEAD``가 provider 기본값과
    같다), ``iter_months``는 provider **안에서** 달을 돌기 때문에 이 층이 요청
    수를 셀 수 없다. 비어 있는 달도 요청 1건을 쓰므로 record 수로는 역산되지
    않는다 — "한도의 몇 %를 쓰는가"에 대답하려면 창을 Map이 소유해야 한다
    (2026-09-13 적대 리뷰 2차: 종전 면제 사유 "알 수 없다"가 사실과 달랐다).
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
        for year, month in _krheritage_event_months(date.today()):
            # `by_month`는 달마다 정확히 HTTP 1건이다(provider 소스 확인).
            note_upstream_request()
            for record in await client.event.by_month(year=year, month=month):
                yield record
    finally:
        await client.aclose()


async def fetch_krheritage_items(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
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
    (``mcst_max_items_per_dataset`` 가드 패턴). async generator, ``finally``에서
    ``await client.aclose()``.
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
            async for record in _iter_krheritage_details(client, kind_code=kind_code):
                yield record
                seen += 1
                if seen >= max_items:
                    return
    finally:
        await client.aclose()

#: 국가유산 목록 요청 페이지 크기. provider ``search.list``의 기본값과 같다.
_KRHERITAGE_PAGE_SIZE: Final[int] = 100


async def _iter_krheritage_details(client: Any, *, kind_code: str) -> AsyncIterator[Any]:
    """국가유산 종목코드 하나의 상세(detail) record를 전부 yield한다.

    provider의 ``search.iter_all_details()``를 쓰지 않는다. 그 안의
    ``iter_pages``는 ``if len(result.items) < page_size: return`` 하나로 끝내는데,
    같은 provider가 **복합키 결측 row를 건너뛴다**(PR#6). 둘이 겹치면 만재 페이지
    하나에서 row 하나만 빠져도 목록이 그 자리에서 조용히 끝난다.

    이 위험은 이 저장소가 이미 알고 있었다 — ``pyproject.toml``의 krheritage 핀이
    그 이유로 ``6076b523``에 묶여 있었고, 해제 조건은 "provider 측에서 total 기반
    종료를 복구한 뒤"였다. upstream은 그것을 복구하지 않았다(``8cde3aff`` 확인).
    그래서 **Map 쪽에서 권위를 되찾는다** — ``PaginatedResult.total``을 권위로 쓰는
    :func:`iter_paginated_items` 아래로 옮기면 provider의 종료 조건에 기대지 않게
    되고, 핀을 묶어 둘 이유도 함께 사라진다.

    상세 조회 규율은 provider의 것을 그대로 따른다 — 복합키 3요소가 모두 있어야
    ``details()``를 부를 수 있고, 결측 row는 조용히 버리지 않고 경고를 남긴다.
    """

    async def _page(page_no: int) -> ProviderPage:
        result = await client.search.list(
            page_size=_KRHERITAGE_PAGE_SIZE, page=page_no, ccba_kdcd=kind_code
        )
        return ProviderPage(items=list(result.items), total_count=result.total)

    async for summary in aiter_paginated_items(
        _page,
        num_of_rows=_KRHERITAGE_PAGE_SIZE,
        label=f"krheritage search.list kdcd={kind_code}",
        warn=_LOGGER.warning,
    ):
        key = summary.key
        if not (key.ccba_kdcd and key.ccba_asno and key.ccba_ctcd):
            _LOGGER.warning(
                "krheritage: 복합키가 불완전한 목록 row를 건너뛴다 "
                "(kdcd=%r asno=%r ctcd=%r name=%r)",
                key.ccba_kdcd,
                key.ccba_asno,
                key.ccba_ctcd,
                summary.name_ko,
            )
            continue
        # detail은 record당 정확히 1 HTTP다(이 파일 위쪽 docstring과
        # `krheritage_max_items_per_run`이 같은 사실에 기대고 있다). 목록
        # 페이지만 세면 실린 수가 실제의 ~1%가 된다 - run 하나가 목록 ~45건,
        # detail ~4,000건이다.
        note_upstream_request()
        yield await client.search.details(key.ccba_kdcd, key.ccba_asno, key.ccba_ctcd)



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
        note_upstream_request()
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
        note_upstream_request()
        records = await client.files.read_geo_records(dataset_key)
        for record in records:
            yield record
    finally:
        await client.aclose()


#: krforest 페이지네이션의 **절대** 상한. ``num_of_rows=1000``이므로 1장 = 1,000행이다.
#: 선언 건수(``total_count``)를 알면 헬퍼가 그 아래에서 상한을 잡는다.
#:
#: **처음 적은 전제가 낡아서 prod를 멈췄다.** 그 자리에 "이 네 dataset은 10장
#: 근처도 아니다 — 휴양림·산악기상·산불위험·산사태 모두 수천 행대"라고 적었는데,
#: 산사태 예보발령은 그 뒤로 자라 2026-09-19 실측에서 **10,562건**을 선언했다.
#: 상한 10장(=10,000행)에 걸려 `ProviderPaginationOverrun`으로 job이 매번
#: 실패했다. 검사기가 제 일을 한 것이지만(조용한 절단 대신 시끄러운 실패),
#: 숫자의 근거가 **그때 한 번 센 값**이었던 것이 문제다.
#:
#: 그래서 숫자를 올리면서 근거를 :data:`_KRFOREST_LARGEST_DECLARED_ROWS`로
#: 꺼내 둔다 — 상한이 그 값의 두 배를 넘는지 검사가 센다. 다음에 어떤 dataset이
#: 이 여유를 먹으면 **prod가 아니라 CI에서** 먼저 말한다.
#:
#: **남은 구조 문제**: 산사태 예보발령은 발령마다 행이 쌓이는 append-only 피드라
#: 계속 자란다. run마다 전 이력을 다시 걷는 지금 형태는 절대 상한을 언젠가 또
#: 먹는다 — 증분 수집(최근 발령분만)으로 바꾸는 것이 옳은 처방이고, 그것은
#: 이 상수와 별건이다.
#:
#: **라이브러리 iterator를 버린 이유는 폭주가 아니라 조용한 절단이다.** 처음 이
#: 자리에 "``max_pages``를 주지 않으면 10,000페이지까지 간다"고 적었는데 **거꾸로**였다
#: (적대 리뷰 지적). ``krforest``의 ``iter_pages``는
#: ``page_ceiling = min(max(ceil(total_count / num_of_rows), 1), 10_000)``이라
#: 10,000은 **추정치의 천장**이지 fallback이 아니다. 그리고 응답에 ``totalCount``가
#: 없으면 ``_http.py``가 ``total_count = len(items)``로 채우므로 추정치가 **1**이 되고,
#: 라이브러리는 1페이지만 읽고 **조용히 ``return``한다**. 10,000에 닿으려면 upstream이
#: 천만 건 이상을 선언해야 한다.
#:
#: 즉 실제 위험은 "쿼터 폭주"가 아니라 **행 누락이 성공으로 보이는 것**이다. 이
#: 저장소의 헬퍼는 짧은 페이지를 마지막 페이지로 읽지 않고, 상한을 넘기면
#: ``ProviderPaginationOverrun``으로 시끄럽게 실패한다.
#:
#: ``max_pages``가 아니라 ``absolute_max_pages``로 넘긴다. 전자는 천장이 아니라
#: **바닥**이라 upstream이 선언한 건수가 그 위로 올려 버린다 — 처음에 그것을
#: ``max_pages``로 줬다가, 선언 건수를 10억으로 둔 테스트가 1,000페이지를 전부 걷는
#: 것을 보고 알았다.
#: 지금까지 **실제로 관측한** krforest 최대 선언 건수.
#:
#: 2026-09-19 산사태 예보발령 10,562건(`ProviderPaginationOverrun` 문구에서 읽음).
#: 나머지 셋(휴양림·산악기상·산불위험)은 이번에 다시 재지 않았다 — 이 값은
#: "우리가 본 것"이지 "상류의 상한"이 아니다.
_KRFOREST_LARGEST_DECLARED_ROWS: Final = 10_562

_KRFOREST_MAX_PAGES: Final = 40


async def _iter_krforest_records(
    endpoint: Callable[..., Awaitable[Any]],
    *,
    label: str,
    num_of_rows: int = 1000,
) -> AsyncIterator[Any]:
    """krforest 페이지 API를 **상한이 있는** 저장소 공통 규칙으로 순회한다."""

    krforest = cast(Any, importlib.import_module("krforest"))

    async def _page(page_no: int) -> ProviderPage:
        page = await endpoint(page_no=page_no, num_of_rows=num_of_rows)
        return ProviderPage(items=page.items, total_count=page.total_count)

    async for record in aiter_paginated_items(
        _page,
        num_of_rows=num_of_rows,
        label=label,
        absolute_max_pages=_KRFOREST_MAX_PAGES,
        end_of_pages=(krforest.ForestNoDataError,),
        # **첫 페이지 NODATA는 종료가 아니라 실패다.** 이 네 fetcher는 전부
        # authoritative snapshot 적재로 흘러가고, 그중 산악기상·산불위험은
        # `retire_absent_from_snapshot=True`로 적재된다 — 빈 snapshot 하나가 그
        # source의 feature를 **전부 은퇴**시킨다. 종전 라이브러리 iterator는
        # `ForestNoDataError`를 잡지 않아 asset이 시끄럽게 죽었고, 이 헬퍼로
        # 옮기며 `end_of_pages`를 단 것이 그 신호를 삼켰다(2026-09-13 적대 리뷰).
        first_page_end_of_pages_is_failure=True,
        warn=_LOGGER.warning,
    ):
        yield record


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
        async for record in _iter_krforest_records(
            client.travel.standard_recreation_forests,
            label="krforest travel.standard_recreation_forests",
        ):
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
        # 호출 1회가 provider 안에서 popup 페이지 + 본문 파일 >=2건을 받는다.
        # 그 배수는 provider 내부라 여기서는 1로 센다 - 그래서 이름이 `_min`이다.
        note_upstream_request()
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
        # SHP 다운로드 1회가 provider 안에서 popup 페이지 + 본문 파일 >=2건을
        # 받는다. 그 배수는 provider 내부라 여기서는 1로 센다 - 이름이 `_min`인
        # 이유이고, 위 arboretums와 같은 형태다.
        note_upstream_request()
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
        # SHP 다운로드 1회가 provider 안에서 popup 페이지 + 본문 파일 >=2건을
        # 받는다. 그 배수는 provider 내부라 여기서는 1로 센다 - 이름이 `_min`인
        # 이유이고, 위 arboretums와 같은 형태다.
        note_upstream_request()
        records = await client.travel.dulle_trail_features()
        for record in records:
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
        async for record in _iter_krforest_records(
            client.safety.landslide_forecast_issues,
            label="krforest safety.landslide_forecast_issues",
        ):
            yield record
    finally:
        await client.aclose()


async def fetch_standard_museums(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """전국박물관미술관표준데이터 record를 datagokr public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``DataGoKrClient(api_key=...)``를 열고
    ``client.museum_art`` record(``PublicMuseumArtGallery``, krtour
    ``PublicMuseumArtItem`` Protocol 충족)를 lazily yield한다. datagokr client는
    async이므로 async generator다. 소비 종료/aclose 시 ``finally``에서 ``aclose()``.
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
        async for record in _iter_datagokr_standard(
            client.museum_art, label="datagokr museum_art.list"
        ):
            yield record
    finally:
        await client.aclose()


async def fetch_standard_tourist_attractions(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """전국관광지표준데이터 record를 datagokr public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``DataGoKrClient``를 열고
    ``client.tourist_attraction`` record(``PublicTouristAttraction``,
    krtour ``PublicTouristAttractionItem`` Protocol 충족)를 lazily yield한다.
    async client → async generator, ``finally``에서 ``aclose()``.
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
        async for record in _iter_datagokr_standard(
            client.tourist_attraction, label="datagokr tourist_attraction.list"
        ):
            yield record
    finally:
        await client.aclose()


async def fetch_standard_special_streets(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
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
        async for record in _iter_datagokr_standard(
            client.special_street, label="datagokr special_street.list"
        ):
            yield record
    finally:
        await client.aclose()


#: 서울 열린데이터광장 OpenAPI base. **https가 없다** — 8088 포트는 TLS를 받지
#: 않는다(2026-09-19 실측: curl 35 SSL connect error). 인증키가 경로에 실려
#: 평문으로 나간다는 뜻이고, 그래서 이 키는 **읽기 전용 공개데이터 전용**으로만
#: 쓴다. data.go.kr 키를 여기 재사용하지 않는 이유이기도 하다.
_SEOUL_OPEN_DATA_BASE_URL: Final = "http://openapi.seoul.go.kr:8088"

#: 서울 책방(서점) 현황정보 OA-21062의 서비스명.
_SEOUL_BOOKSTORE_SERVICE: Final = "TbSlibBookstoreInfo"

#: 한 요청의 행 수. 포털이 1000을 넘기면 ``ERROR-336``으로 거절한다.
_SEOUL_OPEN_DATA_PAGE_SIZE: Final = 1_000

#: 2026-09-19 실측 총 행 수(`list_total_count`). 상한이 이 값보다 충분히 큰지
#: 검사가 대조한다 — 상한을 실측에 붙여 두면 원천이 조금만 늘어도 잘린다.
_SEOUL_BOOKSTORE_DECLARED_ROWS: Final = 606

#: 페이지 상한. 1000행 x 20 = 20,000행으로 실측(606)의 30배가 넘는다.
#: 상한은 무한 루프 차단용이지 수집량 조절 손잡이가 아니다.
_SEOUL_OPEN_DATA_MAX_PAGES: Final = 20

#: 정상 응답 코드와 "더 없음" 코드.
_SEOUL_OK_CODE: Final = "INFO-000"
_SEOUL_NO_DATA_CODE: Final = "INFO-200"


class SeoulOpenDataError(RuntimeError):
    """서울 열린데이터광장이 데이터 대신 오류를 돌려줬다.

    이 포털은 **오류도 HTTP 200으로 준다.** 게다가 ``json``을 요청해도 인증 실패는
    XML(``<RESULT><CODE>INFO-100</CODE>``)로 온다(2026-09-19 실측). 상태 코드나
    파싱 성공으로 판정하면 조용히 0건이 되므로 본문의 ``RESULT.CODE``를 본다.
    """


def _is_transient_upstream_error(exc: BaseException) -> bool:
    """같은 run을 다시 돌리면 지나갈 수 있는 실패인가.

    네트워크 계층(연결·타임아웃·읽기 오류)만 True다. HTTP 상태 오류는 제외한다 —
    404/410처럼 원천이 사라진 응답이 그쪽으로 오고, 그것은 재시도로 나아지지
    않는다. 5xx는 나아질 수 있지만 그 구분까지 넣으면 판정이 상류 운영 상태에
    의존하게 되므로, **네트워크 계층만** 재시도 가능으로 본다.
    """

    if isinstance(exc, httpx.HTTPStatusError):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, TimeoutError | ConnectionError)


async def fetch_seoul_open_data_bookstores(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """서울 책방(OA-21062) row를 서울 열린데이터광장에서 stream한다.

    종전 원천인 data.go.kr odcloud 자동변환 API는 2026-09-18 기준
    **404 ``등록되지 않은 서비스 입니다``**로 사라졌다(날조한 데이터셋 번호와 같은
    응답이고 swagger 네임스페이스도 404다). 활용신청으로 되살릴 수 있는 종류가
    아니라 원천 자체를 옮긴다.
    """
    secret = settings.seoul_open_data_api_key
    if secret is None:
        raise ProviderCredentialMissing(
            "서울 책방 live fetch에는 KOR_TRAVEL_MAP_SEOUL_OPEN_DATA_API_KEY "
            "(source SEOUL_OPEN_DATA_API_KEY)가 필요하다. data.go.kr 키와 **다른 "
            "포털의 키**라 DATA_GO_KR_SERVICE_KEY로는 호출되지 않는다."
        )
    api_key = secret.get_secret_value()

    start = 1
    pages = 0
    async with httpx.AsyncClient(
        base_url=_SEOUL_OPEN_DATA_BASE_URL, timeout=60.0
    ) as client:
        while True:
            if pages >= _SEOUL_OPEN_DATA_MAX_PAGES:
                raise ProviderPaginationOverrun(
                    f"서울 책방 page 상한 {_SEOUL_OPEN_DATA_MAX_PAGES}를 넘겼다 "
                    f"(수신 {start - 1}건, 선언 {_SEOUL_BOOKSTORE_DECLARED_ROWS})"
                )
            end = start + _SEOUL_OPEN_DATA_PAGE_SIZE - 1
            note_upstream_request()
            response = await client.get(
                f"/{api_key}/json/{_SEOUL_BOOKSTORE_SERVICE}/{start}/{end}/"
            )
            _raise_seoul_status(response)
            try:
                payload = response.json()
            except ValueError as exc:
                # json을 요청했는데 XML이 왔다 = 인증 실패. 본문을 그대로 싣지
                # 않는다 — 키가 경로에 있어 에코될 수 있다.
                raise SeoulOpenDataError(
                    "서울 열린데이터광장이 JSON이 아닌 응답을 줬다(인증 실패 시 "
                    f"XML로 온다): {type(exc).__name__}"
                ) from None
            if not isinstance(payload, dict):
                raise SeoulOpenDataError("서울 열린데이터광장 응답이 JSON object가 아니다.")

            envelope = payload.get(_SEOUL_BOOKSTORE_SERVICE)
            if not isinstance(envelope, dict):
                # 범위를 넘기면 서비스 봉투 없이 RESULT만 온다.
                code = _seoul_result_code(payload)
                _stop_or_fail_seoul(code, first_page=pages == 0)
                return

            code = _seoul_result_code(envelope)
            if code != _SEOUL_OK_CODE:
                _stop_or_fail_seoul(code, first_page=pages == 0)
                return

            rows = _seoul_rows(envelope)
            if not rows:
                if pages == 0:
                    # **첫 페이지 0건은 종료가 아니라 실패다.** 이 fetcher가 흘리는
                    # 행은 `authoritative_snapshot_complete=True`로 봉인되므로,
                    # 조용한 0건은 그 dataset의 sync cursor를 전진시켜 수집 실패를
                    # 신선한 성공으로 위장한다. 저장소 공통 페이지네이터의
                    # `first_page_end_of_pages_is_failure`와 같은 규칙이다.
                    raise SeoulOpenDataError(
                        "서울 책방 첫 페이지가 0건이다 — 정상 응답 코드라도 전량이 "
                        "비었다면 수집 실패로 본다(빈 스냅샷을 권위로 봉인하면 "
                        "수집 실패가 신선한 성공으로 보인다)."
                    )
                return
            for row in rows:
                yield row

            pages += 1
            start += len(rows)
            total = envelope.get("list_total_count")
            # 총계를 **신뢰하되 검증한다** — 총계가 없거나 이상하면 빈 페이지가
            # 나올 때까지 돈다(상한이 그것을 막는다).
            if isinstance(total, int) and start > total:
                return


def _raise_seoul_status(response: httpx.Response) -> None:
    """HTTP 오류를 **키 없는** 예외로 바꾼다.

    ``response.raise_for_status()``가 만드는 ``httpx.HTTPStatusError``의 메시지는
    요청 URL 전체를 담는다. 이 포털은 인증키를 **경로**에 받으므로 그 메시지가
    Dagster step-failure 이벤트와 compute log에 키를 평문으로 남긴다
    (큐 경로는 ``raise ProviderDatasetRefreshFailure(...) from exc``로 체인까지
    보존한다). 형제 라이브러리 ``python-datagokr-api``가 같은 이유로
    ``copy_remove_param("serviceKey") + from None``을 쓴다 — 여기도 같은 규범을
    따른다. 상태 코드만 싣고 체인을 끊는다.
    """

    if response.is_success:
        return
    raise SeoulOpenDataError(
        f"서울 열린데이터광장이 HTTP {response.status_code}를 줬다 "
        "(URL은 싣지 않는다 — 인증키가 경로에 있다)."
    )


def _stop_or_fail_seoul(code: str, *, first_page: bool) -> None:
    """``INFO-200``은 종료, 나머지는 실패. 단 **첫 페이지 0건은 실패다.**"""

    if code == _SEOUL_NO_DATA_CODE and not first_page:
        return
    if code == _SEOUL_NO_DATA_CODE:
        raise SeoulOpenDataError(
            "서울 책방 첫 요청이 INFO-200(데이터 없음)이다 — 전량이 사라졌거나 "
            "서비스명이 바뀐 것이지 정상 종료가 아니다."
        )
    raise SeoulOpenDataError(f"서울 열린데이터광장 오류: {code}")


def _seoul_rows(envelope: Mapping[str, Any]) -> list[Any]:
    """``row``를 리스트로 정규화한다.

    이 포털은 행이 하나일 때 list가 아니라 object 하나를 주는 서비스가 있다.
    그 모양을 list가 아니라고 버리면 **1건짜리 응답이 0건으로 보인다** — 위의
    첫 페이지 가드와 합쳐지면 실패로 끝나므로 조용하지는 않지만, 애초에 틀린
    판정이다.
    """

    rows = envelope.get("row")
    if isinstance(rows, Mapping):
        return [rows]
    if isinstance(rows, list):
        return rows
    return []


def _seoul_result_code(payload: Mapping[str, Any]) -> str:
    result = payload.get("RESULT")
    if isinstance(result, Mapping):
        code = result.get("CODE")
        if isinstance(code, str):
            return code
    return "UNKNOWN"


#: odcloud를 떠난 dataset → 대체 원천 fetcher.
#:
#: dataset_key와 provider 이름(`python-datagokr-api`)은 **레지스트리 신원**이라
#: 바꾸지 않는다 — provider_dataset row, operation key
#: (`feature_place_datagokr_seoul_bookstores_job`), 봉인된 300 카탈로그가 전부 그
#: 이름을 쥐고 있다. 바뀐 것은 원천뿐이고, 그 사실을 이 표가 한 줄로 말한다.
_FILE_DATA_SOURCE_OVERRIDES: Final[
    dict[str, Callable[[KorTravelMapSettings], AsyncIterator[Any]]]
] = {"datagokr_seoul_bookstores": fetch_seoul_open_data_bookstores}


async def fetch_datagokr_file_data_records(
    settings: KorTravelMapSettings,
    *,
    dataset_key: str,
) -> AsyncIterator[Any]:
    """data.go.kr fileData 자동변환 API raw row를 datagokr public client로 stream한다.

    원천이 사라진 dataset은 ``_FILE_DATA_SOURCE_OVERRIDES``가 다른 fetcher로
    보낸다. 분기를 여기 두는 이유는 호출자가 둘(Dagster resource와 feature-update
    worker)이라 한쪽에만 넣으면 경로마다 원천이 달라지기 때문이다.
    """
    override = _FILE_DATA_SOURCE_OVERRIDES.get(dataset_key)
    if override is not None:
        async for row in override(settings):
            yield row
        return

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
        # `iter_all`은 provider 안에서 페이지를 돌아 이 층이 셀 수 없다.
        # `iter_pages`는 public이고 `iter_all`이 그것을 그대로 감싼 것뿐이라
        # (provider 소스 확인) 바꿔도 같은 record를 같은 순서로 낸다 - 다만
        # 페이지마다 요청 1건을 셀 수 있다.
        #
        # 여기만 요청 **뒤**에 센다(generator가 페이지를 받아 yield한 뒤 본문이
        # 돈다). 마지막 페이지가 실패하면 그 1건이 빠지지만, 분자는 하한이므로
        # 그 방향은 안전하다 - 반대로 앞에서 세면 나가지 않은 요청을 셀 수 있다.
        async for page in client.file_data.iter_pages(dataset_key):
            note_upstream_request()
            for item in page.items:
                yield item
    finally:
        await client.aclose()


async def fetch_mcst_culture_records(
    settings: KorTravelMapSettings,
    *,
    slugs: Iterable[str] | None = None,
) -> AsyncIterator[Any]:
    """MCST 파일데이터 등록 dataset CSV row를 mcst public client로 stream한다 (#395).

    파일 다운로드는 **keyless** — ``FileDataClient()``가 카탈로그의 다운로드
    페이지를 스크레이핑해 최신 CSV를 받는다(provider #6/#7, krheritage items /
    knps file dataset과 동일하게 credential guard 없음). ``MCST_FILE_DATASETS``에
    등록된 slug 또는 worker가 명시한 slug를 순회하며 ``client.iter_csv(slug)``의 raw row(dict)를
    ``(slug, row)`` 튜플로 lazily yield한다 — asset이 slug별로 분리
    ``_load``한다(dataset_key 단위 sync state 유지). dataset당
    ``settings.mcst_max_items_per_dataset`` 상한(이상 응답 방어). async
    generator, ``finally``에서 ``await client.aclose()``.
    """
    # slug 메타표는 krtour(본 repo) — 변환과 fetch가 같은 표를 본다.
    from kortravelmap.providers.mcst import (
        MCST_FILE_DATASETS,
        McstSlugAttempt,
        McstSlugFailure,
    )

    selected_slugs = tuple(MCST_FILE_DATASETS) if slugs is None else tuple(slugs)
    unknown = sorted(set(selected_slugs) - set(MCST_FILE_DATASETS))
    if unknown:
        raise KeyError(f"MCST 메타표에 없는 slug: {unknown!r}")
    mcst = cast(Any, importlib.import_module("mcst"))
    client = mcst.FileDataClient()
    max_items = settings.mcst_max_items_per_dataset
    try:
        for slug in selected_slugs:
            # slug 하나 = 카탈로그 스크레이핑 + CSV 다운로드. lib 안에서 몇 건이
            # 나가는지는 이 층에서 볼 수 없어 **1로 센다** — 하한이다.
            # **시도했다**는 사실을 먼저 알린다 — asset이 이 집합만 적재한다.
            # worker 경로는 slug 하나로 좁혀 부르므로, 이것이 없으면 나머지
            # 12개가 시도한 적도 없이 빈 적재와 sync-success를 받는다.
            yield McstSlugAttempt(slug=slug)
            note_upstream_request()
            seen = 0
            try:
                async for row in client.iter_csv(slug):
                    seen += 1
                    yield (slug, row)
                    if seen >= max_items:
                        break
            except Exception as exc:  # noqa: BLE001 — 아래에서 다시 가른다
                # **한 slug의 상류 변화가 13개를 전멸시키지 않게 한다.**
                # 이 stream을 리스트로 걷는 쪽(`_record_list`)은 예외를 그대로
                # 통과시키므로, 여기서 raise하면 앞서 수집해 둔 slug의 행까지
                # 함께 버려지고 뒤의 slug는 수집조차 되지 않는다(2026-09-18
                # prod: 아동서점 원천 이동 하나로 13개 dataset 전멸).
                #
                # **쿼터 소진은 예외다.** 그것은 slug가 아니라 run 전체의
                # 자원이 바닥난 것이라, 남은 slug를 계속 부르면 요청만 더 쓴다.
                # 그대로 올려보내 terminal 처리 경로를 타게 한다.
                if quota_exhaustion_cause(exc) is not None:
                    raise
                # 조용한 skip이 아니다 — asset이 이 표식을 보고 그 dataset의
                # 적재를 건너뛴 뒤 run을 실패로 끝낸다.
                #
                # **재시도 가능 여부는 여기서 판정한다.** 예외 타입을 아는 자리가
                # 여기뿐이다. 원천 이동·스키마 변경은 같은 run 안에서 나아지지
                # 않지만 연결 끊김·타임아웃은 다음 시도에 지나갈 수 있다 — 이
                # 구분이 없으면 asset이 전자의 이유로 붙인 `allow_retries=False`를
                # 일시적 네트워크 실패에도 그대로 적용한다(적대 리뷰 지적).
                yield McstSlugFailure(
                    slug=slug,
                    reason=f"{type(exc).__name__}: {exc}",
                    retryable=_is_transient_upstream_error(exc),
                )
    finally:
        await client.aclose()


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


async def fetch_khoa_beaches(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """해양수산부 해수욕장정보 record를 khoa public client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``KhoaClient(api_key=...)``를 열고
    시도별(``OCEANS_BEACH_INFO_DEFAULT_SIDO_NAMES``) ``aoceans_beach_info(sido,
    page_no=N)``을 페이지네이션하며 record(``OceanBeachInfo``, krtour
    ``OceanBeachInfoItem`` Protocol 충족)를 yield한다.

    **async generator다.** khoa 6.x(``3314f68``, provider PR#13)가 라이브러리를
    asyncio 전용으로 바꾸면서 ``oceans_beach_info()``·``close()``를 포함한 sync
    진입점을 전부 없앴다. 남은 ``KhoaClient.__getattr__``는 모르는 이름을
    ``AttributeError``로 바꿔 던지므로 옛 호출은 **첫 페이지에서 즉사**한다.

    부수 이득이 하나 있다. 핀 상태의 sync 진입점은 내부적으로 ``run_async()``를
    거쳐 호출마다 ``ThreadPoolExecutor`` + 새 ``asyncio.run()``을 띄우면서도
    rate limiter와 httpx 세션은 인스턴스 1회 생성분을 공유했다 — loop-bound 객체를
    throwaway 루프들 사이에서 교차 사용하는 구조였다. async 전환이 그것을 없앤다.
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

            def _page(page_no: int, sido: str = sido) -> Awaitable[ProviderPage]:
                # `retry_upstream_awaitable`이 이 콜러블을 **await**한다. 동기
                # 판(`retry_upstream_async`)에 넘기면 코루틴 객체가 그대로
                # 반환돼 재시도가 예외를 한 번도 보지 못한다.
                return upstream_retry.retry_upstream_awaitable(
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

            async for record in aiter_paginated_items(
                _page,
                num_of_rows=num_of_rows,
                label=f"khoa oceans_beach_info {sido}",
                absolute_max_pages=_KHOA_BEACH_MAX_PAGES,
                warn=_LOGGER.warning,
            ):
                yield record
    finally:
        await client.aclose()


async def _khoa_beach_page(
    client: Any,
    sido: str,
    *,
    page_no: int,
    num_of_rows: int,
) -> ProviderPage:
    """KHOA 해수욕장 한 페이지를 재시도 경계 안에서 완전히 소진한다.

    ``page.total_count``를 쓰지 않고 **raw body의 ``totalCount``를 직접 읽는다.**
    provider가 ``total_count=parsed if parsed is not None else len(rows)``로
    대체하기 때문이다(``khoa/client.py``). 만재 100행 페이지에서 upstream이
    ``totalCount``를 빠뜨리면 대체값이 100이 되고, 그것을 권위로 믿으면
    ``seen >= declared``가 참이라 **첫 페이지에서 종료**한다 — 종전 짧은 페이지
    휴리스틱보다도 나쁘다(적대 리뷰 실증). raw에 없으면 없는 것으로 둔다.
    """

    page = await client.aoceans_beach_info(
        sido,
        page_no=page_no,
        num_of_rows=num_of_rows,
    )
    raw = getattr(page, "raw", None)
    declared = raw.get("totalCount") if isinstance(raw, dict) else None
    try:
        total_count = int(declared) if declared is not None else None
    except (TypeError, ValueError):
        total_count = None
    return ProviderPage(
        items=list(page.items),
        total_count=total_count,
        # **정지 조건을 하나 더 준다.** `pageNo`를 무시하는 upstream은 같은 페이지를
        # 영원히 돌려주는데, `total_count`만 보는 순회는 `seen`이 늘어나므로 그것을
        # 정상 진행으로 읽는다. raw 응답을 지문으로 주면 반복을 알아챈다
        # (`provider_pagination` §stall). visitkorea가 쓰는 것과 같은 자리다.
        fingerprint=raw if isinstance(raw, dict) else None,
    )


#: khoa 해수욕장 순회의 **절대** 페이지 상한. 100행 × 30 = 3,000건이고 전국 해수욕장은
#: 수백 개 규모다(시도 하나에 3,000이면 크게 넘는다). 이 오퍼레이션의 실측 일일 한도는
#: 10,000이고 시도 17개를 도므로, 상한이 없으면 선언 총건수 하나가 틀리는 것만으로
#: 하루치를 넘길 수 있다. 넘으면 조용히 자르지 않고 ``ProviderPaginationOverrun``으로
#: 실패한다 — 그때 숫자를 의도적으로 올려라.
_KHOA_BEACH_MAX_PAGES: Final = 30


async def fetch_standard_parking_lots(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """전국주차장표준데이터 record를 datagokr public client로 stream한다.

    ``client.parking`` record(``PublicParkingLot``, krtour
    ``PublicParkingLotItem`` Protocol 충족)를 yield. async generator, finally aclose.
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
        async for record in _iter_datagokr_standard(
            client.parking, label="datagokr parking.list"
        ):
            yield record
    finally:
        await client.aclose()


#: visitkorea 축제 순회의 **절대** 페이지 상한. 100행 × 50 = 5,000건이면 국내 연간
#: 축제 수를 크게 넘는다. 이 오퍼레이션의 실측 일일 한도는 1,000이다
#: (docs/etl/upstream-quota.md). 넘으면 조용히 자르지 않고
#: ``ProviderPaginationOverrun``으로 실패한다 — 그때 숫자를 의도적으로 올려라.
_VISITKOREA_FESTIVAL_MAX_PAGES: Final = 50


async def fetch_visitkorea_festival_events(
    settings: KorTravelMapSettings,
) -> AsyncIterator[Any]:
    """VisitKorea TourAPI 축제(searchFestival) record를 visitkorea client로 stream한다.

    ``settings.data_go_kr_service_key``로 ``KrTourApiClient(service_key=...)``를 열고
    ``search_festival(event_start_date=<올해 1월 1일 KST>)``을 ``iter_pages``로
    페이지네이션하며 ``TourItem``(krtour ``VisitKoreaFestivalItem`` Protocol 충족)을
    yield한다. enrichment 2차 source라 1차(datagokr) 적재 후 매칭에 쓰인다(ADR-042).
    visitkorea client는 async이므로 async generator. 소비 종료/조기 close 시
    ``finally``에서 ``aclose()``.
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
    num_of_rows = 100

    async def _page(page_no: int) -> ProviderPage:
        page = await client.search_festival(start, page_no=page_no, num_of_rows=num_of_rows)
        # `fingerprint`가 라이브러리에서 잃은 '전진하지 않는 페이지네이션' 검사를
        # 되살린다(`ProviderPaginationStalled`).
        return ProviderPage(
            items=page.items,
            total_count=page.total_count,
            fingerprint=getattr(page, "raw", None),
        )

    try:
        # visitkorea의 `iter_pages`는 `max_pages`를 주지 않으면 **상한이 없다**
        # (`_pagination.iter_paginated_pages`: `total_count`가 말하는 만큼 전부 걷는다).
        # 같은 페이지 반복은 잡지만 "너무 많은 페이지"는 잡지 않는다.
        #
        # `max_pages`가 아니라 `absolute_max_pages`를 쓴다 — 전자는 천장이 아니라
        # 바닥이라 선언 건수가 그 위로 올린다(그것을 실측으로 확인했다).
        #
        # 라이브러리 iterator가 갖고 있던 "직전 페이지와 raw가 같으면 실패" 가드는
        # 위 `_page`가 `fingerprint`로 넘겨 헬퍼 쪽에서 되살린다 — 처음 옮길 때
        # 그것을 잃었고 적대 리뷰가 잡았다.
        #
        # **한계**: fingerprint가 응답 body 전체라, upstream이 매 페이지 달라지는
        # 필드(요청 시각 등)를 실어 주면 같은 items를 받아도 가드가 발화하지
        # 않는다. TourAPI 응답에는 그런 필드가 없지만 계약은 아니다.
        async for record in aiter_paginated_items(
            _page,
            num_of_rows=num_of_rows,
            label="visitkorea search_festival",
            absolute_max_pages=_VISITKOREA_FESTIVAL_MAX_PAGES,
            warn=_LOGGER.warning,
        ):
            yield record
    finally:
        await client.aclose()

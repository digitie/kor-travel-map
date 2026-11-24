"""kor-travel-transport 요청마다 걸린 시간과 ``Server-Timing``을 모은다 (감사 G2-07·MC-08).

transport는 모든 응답에 ``Server-Timing``(``app;dur=…, sql;dur=…, …``)을 싣는데 Map은 그것을 버렸고,
요청마다 걸린 시간도 남기지 않았다. 그래서 "느린 것이 transport 처리인가, 길(gateway·
네트워크)인가, 첫 페이지만인가"를 Map 쪽 기록으로 답할 수 없었다. 이 모듈은
:mod:`.upstream_requests`와 같은 방식(실행 문맥 :class:`contextvars.ContextVar`)으로 요청 단위 값을
모아, 경계를 연 op·asset이 metadata로 싣게 한다. fetcher 시그니처는 바꾸지 않는다.

- 여는 자리: :func:`~.transport_state.load_transport_state`(Valkey 상태 op)와
  :func:`~.feature_operation_tracking.run_tracked_feature_asset`(feature 적재 asset — metadata는
  ``etl._add_output_metadata``가 싣는다). 열지 않은 경로에서는 기록이 no-op이다.
- **한 번도 기록하지 않았으면 key를 싣지 않는다**(:mod:`.upstream_requests`와 같은 규칙 —
  "재지 않았다"를 "0ms"로 보이게 하지 않는다).
- ``Server-Timing``이 없는 응답(앞단 gateway가 만든 502 등)은 시간만 센다. 서버 값은 그것을 실은
  응답만 더한다(``transport_server_timed``가 그 수다).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "TransportHttpMetrics",
    "note_transport_response",
    "note_transport_retry",
    "observing_transport_http",
    "parse_server_timing",
    "transport_http_metadata",
]


@dataclass
class TransportHttpMetrics:
    """한 경계(op·asset 하나) 안의 transport 요청 계측."""

    requests: int = 0
    elapsed_ms_total: float = 0.0
    elapsed_ms_max: float = 0.0
    first_elapsed_ms: float | None = None
    server_timed: int = 0
    server_app_ms_total: float = 0.0
    server_app_ms_max: float = 0.0
    server_sql_ms_total: float = 0.0
    retries: int = 0
    retry_sleep_seconds: float = 0.0
    statuses: Counter[str] = field(default_factory=Counter)

    def note(self, status: str, elapsed_seconds: float, server_timing: str | None) -> None:
        elapsed_ms = max(0.0, elapsed_seconds) * 1000.0
        self.requests += 1
        self.elapsed_ms_total += elapsed_ms
        self.elapsed_ms_max = max(self.elapsed_ms_max, elapsed_ms)
        if self.first_elapsed_ms is None:
            self.first_elapsed_ms = elapsed_ms
        self.statuses[status] += 1
        timing = parse_server_timing(server_timing)
        app = timing.get("app")
        if app is not None:
            self.server_timed += 1
            self.server_app_ms_total += app
            self.server_app_ms_max = max(self.server_app_ms_max, app)
            self.server_sql_ms_total += timing.get("sql", 0.0)

    def metadata(self) -> dict[str, int | str]:
        """op metadata. 요청이 하나도 없었으면 빈 dict(key를 싣지 않는다)."""
        if self.requests == 0:
            return {}
        return {
            "transport_http_requests": self.requests,
            "transport_http_ms_total": round(self.elapsed_ms_total),
            "transport_http_ms_max": round(self.elapsed_ms_max),
            "transport_http_first_ms": round(self.first_elapsed_ms or 0.0),
            "transport_http_statuses": ",".join(
                f"{status}={count}" for status, count in sorted(self.statuses.items())
            ),
            "transport_http_retries": self.retries,
            "transport_http_retry_sleep_seconds": round(self.retry_sleep_seconds),
            "transport_server_timed": self.server_timed,
            "transport_server_app_ms_total": round(self.server_app_ms_total),
            "transport_server_app_ms_max": round(self.server_app_ms_max),
            "transport_server_sql_ms_total": round(self.server_sql_ms_total),
        }


_METRICS: Final[ContextVar[TransportHttpMetrics | None]] = ContextVar(
    "kortravelmap_transport_http_metrics", default=None
)


@contextmanager
def observing_transport_http(
    metrics: TransportHttpMetrics | None = None,
) -> Iterator[TransportHttpMetrics]:
    """이 블록 안의 transport 요청을 ``metrics``(없으면 새로 만든 것)에 모은다.

    중첩하면 안쪽이 이긴다.
    """
    active = metrics if metrics is not None else TransportHttpMetrics()
    token = _METRICS.set(active)
    try:
        yield active
    finally:
        _METRICS.reset(token)


def note_transport_response(status: str, elapsed_seconds: float, server_timing: str | None) -> None:
    """요청 한 건의 결과(HTTP 상태 또는 전송 오류 이름)·걸린 시간·``Server-Timing``을 기록한다."""
    metrics = _METRICS.get()
    if metrics is not None:
        metrics.note(status, elapsed_seconds, server_timing)


def note_transport_retry(delay_seconds: float) -> None:
    """HTTP 층 재시도 한 번과 그 앞의 대기를 기록한다."""
    metrics = _METRICS.get()
    if metrics is not None:
        metrics.retries += 1
        metrics.retry_sleep_seconds += max(0.0, delay_seconds)


def transport_http_metadata() -> dict[str, int | str]:
    """지금 문맥의 계측 metadata. 경계가 없거나 요청이 없었으면 빈 dict."""
    metrics = _METRICS.get()
    return {} if metrics is None else metrics.metadata()


def parse_server_timing(value: str | None) -> dict[str, float]:
    """``Server-Timing`` header에서 ``이름;dur=밀리초``만 뽑는다. 같은 이름이 거듭되면 처음 것.

    transport 형식: ``app;dur=12.3, sql;dur=4.5, sql_count;desc="3", cpu;dur=…`` — ``desc``만 있는
    항목과 읽을 수 없는 값은 건너뛴다(계측이 적재를 막지 않는다).
    """
    parsed: dict[str, float] = {}
    if not value:
        return parsed
    for entry in value.split(","):
        name, _, params = entry.strip().partition(";")
        name = name.strip()
        if not name or name in parsed:
            continue
        for param in params.split(";"):
            key, _, raw = param.strip().partition("=")
            if key.strip().lower() != "dur":
                continue
            try:
                duration = float(raw.strip().strip('"'))
            except ValueError:
                break
            if math.isfinite(duration) and duration >= 0:
                parsed[name] = duration
            break
    return parsed

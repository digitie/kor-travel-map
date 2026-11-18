"""요청 하나의 DB 시간 누산기와 느린 요청 로그 (읽기 성능 계획 T-READ-02).

지표 flag(``prometheus_metrics_enabled``)와 **무관하게** 돈다. 운영은 지표를 꺼 둔 채로도
"어느 route가, 몇 문장으로, DB에서 얼마를 썼는지"를 로그 한 줄로 남겨야 한다
(계획 F-03).

- ``app.py``의 미들웨어가 요청마다 ``RequestDbTiming``을 만들어 ContextVar에 걸고, 요청
  도착 시각을 ``request.state.started_monotonic``에 적는다.
- ``api/db.py``의 cursor 이벤트와 pool 체크아웃 대기가 그 누산기에 더한다. 이벤트는 같은
  요청의 문장만 센다(다른 요청은 다른 ContextVar 값을 본다). 추가 DB 왕복은 없다.
- 요청 시간이 문턱 이상이면 route template·status·시간·문장 수·DB 시간·pool 대기·request id를
  WARNING 한 줄로 남긴다. query string·header 값·좌표는 남기지 않는다 — route는 매칭된
  템플릿(``/v1/features/{feature_id}``)이지 실제 URL이 아니다.
"""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass

__all__ = [
    "SLOW_REQUEST_LOGGER_NAME",
    "RequestDbTiming",
    "bind_request_db_timing",
    "current_request_db_timing",
    "format_slow_request_line",
    "log_slow_request",
    "reset_request_db_timing",
]

SLOW_REQUEST_LOGGER_NAME = "kortravelmap.api.slow_request"
_slow_request_logger = logging.getLogger(SLOW_REQUEST_LOGGER_NAME)

#: request id는 client header(``X-Request-ID``)에서 올 수 있다 — 로그 한 줄의 key=value 모양을
#: 깨거나 길게 늘이지 못하게 이 문자만, 이 길이까지만 남긴다.
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9._:-]{1,64}")
_REQUEST_DB_TIMING: ContextVar[RequestDbTiming | None] = ContextVar(
    "kor_travel_map_request_db_timing",
    default=None,
)


@dataclass(slots=True)
class RequestDbTiming:
    """요청 하나가 DB에서 쓴 것. 미들웨어가 만들고 DB 이벤트가 채운다."""

    statements: int = 0
    db_seconds: float = 0.0
    pool_waits: int = 0
    pool_wait_seconds: float = 0.0

    def add_statement(self, duration_seconds: float) -> None:
        self.statements += 1
        self.db_seconds += max(0.0, duration_seconds)

    def add_pool_wait(self, duration_seconds: float) -> None:
        self.pool_waits += 1
        self.pool_wait_seconds += max(0.0, duration_seconds)


def bind_request_db_timing(timing: RequestDbTiming) -> Token[RequestDbTiming | None]:
    return _REQUEST_DB_TIMING.set(timing)


def reset_request_db_timing(token: Token[RequestDbTiming | None]) -> None:
    _REQUEST_DB_TIMING.reset(token)


def current_request_db_timing() -> RequestDbTiming | None:
    return _REQUEST_DB_TIMING.get()


def format_slow_request_line(
    *,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
    timing: RequestDbTiming,
    request_id: str,
) -> str:
    """느린 요청 로그 한 줄. ``key=value``를 공백으로 잇는다(값에 공백이 없다)."""

    return (
        "slow_request"
        f" method={_safe_token(method)}"
        f" route={route}"
        f" status={status_code}"
        f" duration_ms={_ms(duration_seconds)}"
        f" db_statements={timing.statements}"
        f" db_ms={_ms(timing.db_seconds)}"
        f" pool_waits={timing.pool_waits}"
        f" pool_wait_ms={_ms(timing.pool_wait_seconds)}"
        f" request_id={_safe_token(request_id)}"
    )


def log_slow_request(
    *,
    threshold_ms: int,
    method: str,
    route: str,
    status_code: int,
    duration_seconds: float,
    timing: RequestDbTiming,
    request_id: str,
) -> bool:
    """문턱 이상이면 한 줄을 남기고 ``True``. 문턱 0은 끈다."""

    if threshold_ms <= 0 or duration_seconds * 1000.0 < threshold_ms:
        return False
    _slow_request_logger.warning(
        "%s",
        format_slow_request_line(
            method=method,
            route=route,
            status_code=status_code,
            duration_seconds=duration_seconds,
            timing=timing,
            request_id=request_id,
        ),
    )
    return True


def _safe_token(value: str) -> str:
    return value if _SAFE_TOKEN.fullmatch(value) else "-"


def _ms(seconds: float) -> int:
    return max(0, round(seconds * 1000.0))

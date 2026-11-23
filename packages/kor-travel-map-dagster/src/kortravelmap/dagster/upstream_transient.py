"""provider 호출 하나가 **같은 run 안에서 다시 부르면 지나갈 수 있는** 실패인가 (감사 §4 #15).

:mod:`.upstream_retry`의 기본 판정(``default_upstream_retryable``)은 kma 계열 규약 —
예외의 ``retryable`` 속성 — 하나만 본다. 그런데 Map이 부르는 provider lib의 절반은 그 속성을
붙이지 않는다. 그래서 그 판정 하나로는 KHOA 말고 어디에도 걸 수 없었고, 실제로 적용처가 KHOA
하나뿐이었다(감사 §1.3 P0). 이 모듈은 lib마다 다른 신호를 한 판정으로 모은다.

**재시도하는 것(일시 오류만)**

- HTTP 상태가 실려 있으면 그것이 우선이다 — 408·425·429·500·502·503·504만 일시 오류다.
  404·410(원천이 사라짐)·401·403(키)·400(요청)은 몇 번을 다시 불러도 같다.
- 상태가 없으면 lib의 분류 — ``retryable is True``, ``failure_kind``가 network·server·timeout.
- 그것도 없으면 전송 계층 예외 — ``httpx.TransportError``(연결·timeout·읽기 오류),
  ``TimeoutError``, ``ConnectionError``.
- lib이 분류 속성 없이 던지는 일시 오류는 타입으로 선언한다(:data:`TRANSIENT_EXCEPTION_TYPES`).

**재시도하지 않는 것**

- 일일 쿼터 소진 — :func:`~.quota_exhaustion.quota_exhaustion_cause`가 찾으면 언제나 거절한다.
  다시 부르면 그날 한도를 더 넘길 뿐이다. HTTP 429(초·분 단위 throttle)는 쿼터가 아니므로
  재시도하되, 상류가 ``Retry-After``를 주면 그것을 존중한다(:func:`upstream_retry_after_seconds`).
- ``retryable is False``, 분류되지 않은 예외(파싱·계약 위반·스냅샷 불완전) — fail-close.

**왜 원 예외의 ``__cause__``도 보나.** provider lib이 httpx 오류를 자기 예외로 감싸며
``raise ... from exc``로 남기는 경우가 있다. 감싼 쪽에 분류가 없으면 원인을 본다. 반대로
감싼 쪽에 분류가 있으면 그것이 우선이다(lib이 원인을 보고 이미 판단했다).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final

import httpx

from .quota_exhaustion import quota_exhaustion_cause
from .upstream_retry import NONRETRYABLE_FAILURE_KINDS

__all__ = [
    "TRANSIENT_EXCEPTION_TYPES",
    "TRANSIENT_RESULT_CODES",
    "TRANSIENT_FAILURE_KINDS",
    "TRANSIENT_HTTP_STATUSES",
    "is_transient_upstream_failure",
    "upstream_retry_after_seconds",
]

TRANSIENT_HTTP_STATUSES: Final[frozenset[int]] = frozenset({408, 425, 429, 500, 502, 503, 504})
"""다시 부르면 지나갈 수 있는 HTTP 상태. 그 밖의 4xx·5xx(501·505 등)는 결정적이다."""

TRANSIENT_FAILURE_KINDS: Final[frozenset[str]] = frozenset({"network", "server", "timeout"})
"""lib이 ``failure_kind``로 알려 주는 일시 오류(krforest·visitkorea·mcst·knps 등)."""

#: 분류 속성 없이 던지는 lib의 **일시 오류** 타입 — ``(top-level 모듈, 클래스 이름)``.
#:
#: 핀 SHA 소스로 확인했다(2026-11-24).
#:
#: - ``datagokr.TransportError`` — ``status_code`` 없이 오면 ``httpx.TransportError`` 3회
#:   소진이다(``transport.py``, ``from None``이라 원인이 끊긴다). 상태가 실리면 상태 규칙이 먼저다.
#: - ``mois.MoisServerError`` — HTTP 5xx와 결과 코드 04·99. 전송 오류는 httpx 예외가 그대로 온다.
#: - ``mcst.McstNetworkError`` — 연결·timeout.
TRANSIENT_EXCEPTION_TYPES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("datagokr", "TransportError"),
        ("mois", "MoisServerError"),
        ("mcst", "McstNetworkError"),
    }
)

#: 분류 속성 없는 lib이 결과 코드로 알려 주는 **일시** 실패 — ``top-level 모듈 → (속성, 코드들)``.
#:
#: - datagokr ``FILE_METADATA_CHANGED`` — 공개 파일을 받는 도중 포털의 파일 메타데이터가 바뀌었다
#:   (``services/standard_file.py``). 파일을 처음부터 다시 받으면 지나간다 — 재시도 단위가 파일
#:   하나인 :func:`~.provider_fetchers._read_datagokr_standard_file`이 바로 그것을 한다.
TRANSIENT_RESULT_CODES: Final[dict[str, tuple[str, frozenset[str]]]] = {
    "datagokr": ("code", frozenset({"FILE_METADATA_CHANGED"})),
}

#: ``httpx.TransportError``의 하위 중 **결정적**인 것 — 몇 번을 다시 보내도 같다.
_DETERMINISTIC_TRANSPORT_ERRORS: Final[tuple[type[Exception], ...]] = (
    httpx.UnsupportedProtocol,
    httpx.LocalProtocolError,
)

_HTTP_STATUS_ATTRIBUTES: Final[tuple[str, ...]] = ("status_code", "http_status")
_RETRY_AFTER_ATTRIBUTES: Final[tuple[str, ...]] = ("retry_after", "retry_after_seconds")
_MAX_CAUSE_DEPTH: Final[int] = 8


def _error_status(exc: BaseException) -> int | None:
    """예외가 들고 있는 **오류** HTTP 상태(>= 400). 2xx·3xx는 판정에 쓰지 않는다.

    visitkorea·krforest는 HTTP 200 본문의 결과 코드 오류에도 ``status_code=200``을 싣는다 —
    그 200을 "일시 오류 아님"으로 읽으면 ``failure_kind="server"``(결과 코드 04·99)를 놓친다.
    """

    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code
    for name in _HTTP_STATUS_ATTRIBUTES:
        value = getattr(exc, name, None)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 400:
            return value
    return None


def _declared_transient(exc: BaseException) -> bool:
    for klass in type(exc).__mro__:
        module = getattr(klass, "__module__", "").split(".", 1)[0]
        if (module, klass.__name__) in TRANSIENT_EXCEPTION_TYPES:
            return True
    return False


def _transient_result_code(exc: BaseException) -> bool:
    declared = TRANSIENT_RESULT_CODES.get(type(exc).__module__.split(".", 1)[0])
    if declared is None:
        return False
    attribute, codes = declared
    code = getattr(exc, attribute, None)
    return code is not None and str(code).strip() in codes


def _classify(exc: BaseException) -> bool | None:
    """이 예외 하나만 보고 내린 판정. 판단할 신호가 없으면 ``None``(원인을 본다)."""

    status = _error_status(exc)
    if status is not None:
        return status in TRANSIENT_HTTP_STATUSES
    retryable = getattr(exc, "retryable", None)
    if retryable is False:
        return False
    failure_kind = getattr(exc, "failure_kind", None)
    if failure_kind in NONRETRYABLE_FAILURE_KINDS:
        # 상태 없는 rate_limit은 결과 코드 22(일일 한도)다 — 429는 위 상태 규칙에서 끝났다.
        return False
    if retryable is True or failure_kind in TRANSIENT_FAILURE_KINDS:
        return True
    if isinstance(exc, _DETERMINISTIC_TRANSPORT_ERRORS):
        return False
    if isinstance(exc, httpx.TransportError | TimeoutError | ConnectionError):
        return True
    if _transient_result_code(exc):
        return True
    if _declared_transient(exc):
        return True
    if failure_kind is not None:
        # lib이 분류했고(parse·auth·request·no_data…) 일시 오류가 아니라고 했다.
        return False
    return None


def is_transient_upstream_failure(exc: BaseException) -> bool:
    """provider 호출 실패를 같은 run 안에서 다시 시도해도 되는가."""

    if quota_exhaustion_cause(exc) is not None:
        return False
    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(_MAX_CAUSE_DEPTH):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        verdict = _classify(current)
        if verdict is not None:
            return verdict
        # 명시적 연쇄(``raise ... from``)만 따른다 — ``__context__``는 처리 중에 난 **다른**
        # 실패일 수 있다.
        current = current.__cause__
    return False


def _parse_retry_after(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = float(value)
        return seconds if math.isfinite(seconds) and seconds >= 0 else None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return max(0.0, (moment - datetime.now(UTC)).total_seconds())
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def upstream_retry_after_seconds(exc: BaseException) -> float | None:
    """상류가 알려 준 대기 시간(초). 없으면 ``None``.

    ``httpx.HTTPStatusError``는 응답 header ``Retry-After``(초 또는 HTTP-date)를, lib 예외는
    ``retry_after``/``retry_after_seconds`` 속성을 본다. 명시적 원인 연쇄를 따라간다 — lib이
    httpx 오류를 감싸며 header를 잃지 않은 경우가 있다.
    """

    current: BaseException | None = exc
    seen: set[int] = set()
    for _ in range(_MAX_CAUSE_DEPTH):
        if current is None or id(current) in seen:
            return None
        seen.add(id(current))
        if isinstance(current, httpx.HTTPStatusError):
            parsed = _parse_retry_after(current.response.headers.get("Retry-After"))
            if parsed is not None:
                return parsed
        for name in _RETRY_AFTER_ATTRIBUTES:
            parsed = _parse_retry_after(getattr(current, name, None))
            if parsed is not None:
                return parsed
        current = current.__cause__
    return None

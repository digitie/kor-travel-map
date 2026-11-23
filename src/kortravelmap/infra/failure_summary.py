"""실행 실패를 **운영자가 읽을 한 줄**과 **기계가 읽을 분류**로 줄인다 (감사 2026-11-23 §4 #15).

종전에는 큐 요청이 실패하면 Map DB에 남는 것이 ``"ProviderDatasetRefreshFailure: provider refresh
asset execution failed"`` 같은 바깥 예외 한 줄뿐이었고(원인은 ``__cause__``에만 있었다), Dagster
run이 실패한 operation root에는 ``{"kind":"dagster_run_terminal","status":"FAILURE"}``만 남았다.
그래서 10-22에 한꺼번에 실패한 큐 요청 13건이 lock timeout인지 상류 장애인지 DB만 보고는 알 수
없었다. 이 모듈은 그 정보를 **비밀값 없이** 남길 수 있는 모양으로 만든다.

- :func:`transient_db_failure_kind` — 다시 시도하면 지나갈 수 있는 DB 실패인가
  (lock timeout·serialization·deadlock·연결 끊김). 그 밖은 ``None``(결정적).
- :func:`summarize_failure` — 분류·예외 타입·짧은 메시지·명시적 원인 연쇄.
- :func:`redact_failure_text` — 메시지에 섞여 들어올 수 있는 비밀(서비스 키·토큰·DSN 비밀번호)과
  SQLAlchemy가 덧붙이는 SQL 본문·bind parameter를 걷어낸다.

원인 연쇄는 **명시적 연쇄**(``raise ... from``과 SQLAlchemy ``DBAPIError.orig``)만 따른다.
``__context__``는 처리 중에 난 **다른** 실패일 수 있다 — 따라가면 결정적 실패가 정리 중의 lock
timeout 하나로 "일시 오류"가 되어 재시도를 산다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = [
    "MAX_FAILURE_MESSAGE_CHARS",
    "FailureSummary",
    "TransientDbFailureKind",
    "redact_failure_text",
    "summarize_failure",
    "transient_db_failure_kind",
]

TransientDbFailureKind = Literal["lock_timeout", "serialization", "deadlock", "connection"]

#: SQLSTATE → 일시 DB 실패 종류. PostgreSQL 오류 코드표(Appendix A) 기준.
_TRANSIENT_SQLSTATES: Final[dict[str, TransientDbFailureKind]] = {
    "55P03": "lock_timeout",  # lock_not_available — lock_timeout·NOWAIT
    "40001": "serialization",  # serialization_failure
    "40P01": "deadlock",  # deadlock_detected
    "08000": "connection",  # connection_exception
    "08001": "connection",  # sqlclient_unable_to_establish_sqlconnection
    "08003": "connection",  # connection_does_not_exist
    "08004": "connection",  # sqlserver_rejected_establishment_of_sqlconnection
    "08006": "connection",  # connection_failure
    "57P01": "connection",  # admin_shutdown
    "57P02": "connection",  # crash_shutdown
    "57P03": "connection",  # cannot_connect_now (복구 중)
    "53300": "connection",  # too_many_connections
}

#: SQLSTATE 없이 오는 driver 연결 오류 — ``(top-level 모듈, 클래스 이름)``.
_CONNECTION_ERROR_TYPES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("asyncpg", "ConnectionDoesNotExistError"),
        ("asyncpg", "InterfaceError"),
        ("asyncpg", "ConnectionFailureError"),
        ("asyncpg", "TooManyConnectionsError"),
        ("asyncpg", "CannotConnectNowError"),
    }
)

#: 운영자가 읽을 메시지 한 조각의 최대 길이. 원문 전체는 Dagster compute log에 있다.
MAX_FAILURE_MESSAGE_CHARS: Final[int] = 300
_MAX_CHAIN: Final[int] = 6

_SQLALCHEMY_TAIL = re.compile(r"\n?\s*\[(?:SQL|parameters):.*", re.DOTALL)
_SQLALCHEMY_BACKGROUND = re.compile(r"\s*\(Background on this error at:[^)]*\)")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b((?:service_?key|api_?key|access_?key|secret|token|password|passwd|pwd|"
    r"authorization|x-api-key)\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s&'\",;)]+)"
)
_URL_CREDENTIALS = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]+")
_WHITESPACE = re.compile(r"\s+")


def redact_failure_text(text: str, *, limit: int = MAX_FAILURE_MESSAGE_CHARS) -> str:
    """비밀값·SQL 본문을 걷어내고 한 줄로 줄인다."""

    cleaned = _SQLALCHEMY_TAIL.sub("", text)
    cleaned = _SQLALCHEMY_BACKGROUND.sub("", cleaned)
    cleaned = _URL_CREDENTIALS.sub(r"\1***@", cleaned)
    # bearer 먼저 — ``Authorization: Bearer x``에서 할당 규칙이 ``Bearer``만 가리고 토큰을 남기지
    # 않게 한다.
    cleaned = _BEARER.sub(r"\1***", cleaned)
    cleaned = _SECRET_ASSIGNMENT.sub(r"\1***", cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: max(0, limit - 1)].rstrip() + "…"
    return cleaned


def _explicit_chain(exc: BaseException) -> list[BaseException]:
    """``exc``부터 명시적 원인(``__cause__``, SQLAlchemy ``orig``)을 따라간 목록."""

    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < _MAX_CHAIN:
        seen.add(id(current))
        chain.append(current)
        orig = getattr(current, "orig", None)
        if isinstance(orig, BaseException) and id(orig) not in seen:
            current = orig
            continue
        current = current.__cause__
    return chain


def _sqlstate(exc: BaseException) -> str | None:
    for name in ("sqlstate", "pgcode"):
        value = getattr(exc, name, None)
        if isinstance(value, str) and len(value) == 5:
            return value
    return None


def transient_db_failure_kind(exc: BaseException) -> TransientDbFailureKind | None:
    """다시 시도하면 지나갈 수 있는 DB 실패면 그 종류, 아니면 ``None``."""

    for node in _explicit_chain(exc):
        state = _sqlstate(node)
        if state is not None:
            kind = _TRANSIENT_SQLSTATES.get(state)
            if kind is not None:
                return kind
            # SQLSTATE가 있고 일시 오류가 아니면 결정적이다(제약 위반·문법 오류 등).
            return None
        if getattr(node, "connection_invalidated", False) is True:
            return "connection"
        for klass in type(node).__mro__:
            module = getattr(klass, "__module__", "").split(".", 1)[0]
            if (module, klass.__name__) in _CONNECTION_ERROR_TYPES:
                return "connection"
    return None


@dataclass(frozen=True)
class FailureSummary:
    """실패 하나의 비밀 없는 요약."""

    failure_class: Literal["transient_db", "execution"]
    """``transient_db``면 다시 시도할 수 있다. 그 밖은 결정적으로 본다."""

    db_failure: TransientDbFailureKind | None
    error_type: str
    message: str
    """바깥 예외의 ``"{타입}: {메시지}"`` — 종전 ``error_message``와 같은 머리."""

    causes: tuple[str, ...]
    """명시적 원인 연쇄의 ``"{타입}: {메시지}"`` (바깥 제외)."""

    failure_kind: str | None = None
    """원인 연쇄에서 처음 만난 provider ``failure_kind``(quota·server·network 등)."""

    def describe(self) -> str:
        """``error_message``에 싣는 한 줄. 원인이 있으면 가장 안쪽 원인을 덧붙인다."""

        if not self.causes:
            return self.message
        return f"{self.message} ← 원인 {self.causes[-1]}"

    def payload(self) -> dict[str, Any]:
        """import job event payload에 싣는 구조."""

        body: dict[str, Any] = {
            "failure_class": self.failure_class,
            "error_type": self.error_type,
            "error": self.message,
        }
        if self.db_failure is not None:
            body["db_failure"] = self.db_failure
        if self.failure_kind is not None:
            body["failure_kind"] = self.failure_kind
        if self.causes:
            body["causes"] = list(self.causes)
        return body


def _one_line(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {redact_failure_text(str(exc))}"


def summarize_failure(exc: BaseException) -> FailureSummary:
    """``exc``를 :class:`FailureSummary`로 줄인다. 이 함수는 예외를 던지지 않는다."""

    chain = _explicit_chain(exc)
    db_failure = transient_db_failure_kind(exc)
    failure_kind = next(
        (
            str(kind)
            for node in chain
            if isinstance(kind := getattr(node, "failure_kind", None), str) and kind
        ),
        None,
    )
    causes: list[str] = []
    for node in chain[1:]:
        # SQLAlchemy 어댑터 예외와 그 원 driver 예외는 같은 메시지를 두 번 싣는다 — 하나만 남긴다.
        line = _one_line(node)
        if causes and causes[-1].split(": ", 1)[-1] == line.split(": ", 1)[-1]:
            causes[-1] = line
            continue
        causes.append(line)
    return FailureSummary(
        failure_class="transient_db" if db_failure is not None else "execution",
        db_failure=db_failure,
        error_type=type(exc).__name__,
        message=_one_line(exc),
        causes=tuple(causes),
        failure_kind=failure_kind,
    )

"""공통 REST response envelope helper (ADR-048/T-216)."""

from __future__ import annotations

from contextvars import ContextVar, Token
from time import perf_counter
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ClusterMeta",
    "Meta",
    "OffsetMeta",
    "OffsetPageMeta",
    "PageMeta",
    "ProblemDetail",
    "ProblemDetailError",
    "bind_request_id",
    "duration_ms",
    "make_meta",
    "make_offset_meta",
    "request_id",
    "reset_request_id",
]


_CURRENT_REQUEST_ID: ContextVar[str | None] = ContextVar(
    "kor_travel_map_admin_request_id",
    default=None,
)


class PageMeta(BaseModel):
    """Cursor pagination metadata.

    ``next_cursor``는 페이지가 끝났을 때도 ``null``로 항상 직렬화한다.
    """

    model_config = ConfigDict(extra="forbid")

    page_size: int
    next_cursor: str | None = None
    total: int | None = None


class OffsetPageMeta(BaseModel):
    """Page-number/offset pagination metadata.

    Cursor를 쓰지 않는 목록은 cursor 필드를 노출하지 않는다.
    """

    model_config = ConfigDict(extra="forbid")

    page_size: int
    total: int | None = None


class ClusterMeta(BaseModel):
    """Map clustering metadata."""

    model_config = ConfigDict(extra="forbid")

    cluster_unit: str | None = None


class Meta(BaseModel):
    """전 REST 표면에서 공유하는 성공 응답 metadata."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int
    request_id: str = Field(default="", description="X-Request-ID와 같은 요청 ID.")
    page: PageMeta | None = None
    cluster: ClusterMeta | None = None


class OffsetMeta(BaseModel):
    """Cursor가 없는 page-number 목록용 성공 응답 metadata."""

    model_config = ConfigDict(extra="forbid")

    duration_ms: int
    request_id: str = Field(default="", description="X-Request-ID와 같은 요청 ID.")
    page: OffsetPageMeta | None = None


class ProblemDetailError(BaseModel):
    """RFC7807 problem 본문 ``errors`` 항목 (필드 단위 오류).

    §1.5 산문 계약은 ``{field, message}``를 정의하지만, 검증 실패(422)는 pydantic
    원본 오류(``loc``/``msg``/``type`` 등)를 그대로 싣는다. 두 형태를 모두 허용하도록
    추가 키를 열어 둔다(``extra='allow'``).
    """

    model_config = ConfigDict(extra="allow")

    field: str | None = Field(default=None, description="오류가 발생한 입력 필드.")
    message: str | None = Field(default=None, description="사람이 읽는 오류 메시지.")


class ProblemDetail(BaseModel):
    """RFC7807 ``application/problem+json`` 에러 본문 (중앙 핸들러 정본, §1.5).

    중앙 예외 핸들러(`app._error_response`)가 모든 4xx/5xx를 이 형식으로 통일한다.
    ``code``·``request_id``는 소비자 파싱 위치 고정용 top-level 확장 멤버다.
    """

    model_config = ConfigDict(extra="allow")

    type: str = Field(
        description="오류 유형 URI. 예: https://kor-travel-map/errors/not-found",
    )
    title: str = Field(description="사람이 읽는 짧은 요약(= detail).")
    status: int = Field(description="HTTP 상태 코드.")
    detail: str = Field(description="이 발생 건에 대한 사람이 읽는 설명.")
    code: str = Field(description="기계 판독용 오류 코드(§4 enum 확장). 예: NOT_FOUND.")
    request_id: str = Field(
        description="요청 상관추적 ID(`X-Request-ID`/`meta.request_id`와 동일).",
    )
    errors: list[ProblemDetailError] = Field(
        default_factory=list,
        description="필드 단위 검증 오류 목록(검증 실패 시 비어 있지 않다).",
    )


def request_id(request: Request) -> str:
    """Return stable request id for the current request."""

    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    header_value = request.headers.get("x-request-id")
    value = header_value if header_value else str(uuid4())
    request.state.request_id = value
    return value


def bind_request_id(value: str) -> Token[str | None]:
    """Bind ``value`` as the current request id for envelope helpers."""

    return _CURRENT_REQUEST_ID.set(value)


def reset_request_id(token: Token[str | None]) -> None:
    """Reset the request id context after a request has been handled."""

    _CURRENT_REQUEST_ID.reset(token)


def duration_ms(started_at: float) -> int:
    """Return elapsed milliseconds from ``perf_counter`` start."""

    return max(0, int((perf_counter() - started_at) * 1000))


def make_meta(
    request: Request | None = None,
    *,
    started_at: float,
    page_size: int | None = None,
    next_cursor: str | None = None,
    total: int | None = None,
    cluster_unit: str | None = None,
) -> Meta:
    """Build common response ``meta``.

    Page metadata is emitted only when ``page_size`` is provided.
    """

    return Meta(
        duration_ms=duration_ms(started_at),
        request_id=(
            request_id(request)
            if request is not None
            else (_CURRENT_REQUEST_ID.get() or "")
        ),
        page=(
            PageMeta(page_size=page_size, next_cursor=next_cursor, total=total)
            if page_size is not None
            else None
        ),
        cluster=ClusterMeta(cluster_unit=cluster_unit)
        if cluster_unit is not None
        else None,
    )


def make_offset_meta(
    request: Request | None = None,
    *,
    started_at: float,
    page_size: int,
    total: int | None = None,
) -> OffsetMeta:
    """Build response ``meta`` for page-number lists without cursor fields."""

    return OffsetMeta(
        duration_ms=duration_ms(started_at),
        request_id=(
            request_id(request)
            if request is not None
            else (_CURRENT_REQUEST_ID.get() or "")
        ),
        page=OffsetPageMeta(page_size=page_size, total=total),
    )

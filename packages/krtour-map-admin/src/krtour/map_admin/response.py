"""공통 REST response envelope helper (ADR-048/T-216)."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ClusterMeta",
    "Meta",
    "PageMeta",
    "duration_ms",
    "make_meta",
    "request_id",
]


class PageMeta(BaseModel):
    """Cursor pagination metadata.

    ``next_cursor``는 페이지가 끝났을 때도 ``null``로 항상 직렬화한다.
    """

    model_config = ConfigDict(extra="forbid")

    page_size: int
    next_cursor: str | None = None
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


def request_id(request: Request) -> str:
    """Return stable request id for the current request."""

    value = getattr(request.state, "request_id", None)
    if isinstance(value, str) and value:
        return value
    header_value = request.headers.get("x-request-id")
    value = header_value if header_value else str(uuid4())
    request.state.request_id = value
    return value


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
        request_id=request_id(request) if request is not None else "",
        page=(
            PageMeta(page_size=page_size, next_cursor=next_cursor, total=total)
            if page_size is not None
            else None
        ),
        cluster=ClusterMeta(cluster_unit=cluster_unit)
        if cluster_unit is not None
        else None,
    )

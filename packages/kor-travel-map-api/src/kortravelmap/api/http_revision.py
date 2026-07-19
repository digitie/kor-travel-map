"""Feature ``row_revision`` HTTP precondition helpers (T-VN-13)."""

from __future__ import annotations

import re

from fastapi import HTTPException, Request, status

_MAX_BIGINT = 9_223_372_036_854_775_807
_REVISION_ETAG_PATTERN = re.compile(r'^"([1-9][0-9]*)"$')


def revision_etag(revision: int) -> str:
    """양수 BIGINT revision을 canonical strong ETag로 직렬화한다."""
    if not 1 <= revision <= _MAX_BIGINT:
        raise ValueError("row_revision은 양수 BIGINT 범위여야 합니다.")
    return f'"{revision}"'


def parse_revision_header(
    request: Request,
    header_name: str,
    *,
    required: bool,
) -> int | None:
    """정확히 한 physical header line의 canonical strong revision ETag를 읽는다."""
    values = request.headers.getlist(header_name)
    if not values:
        if not required:
            return None
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail={
                "code": "PRECONDITION_REQUIRED",
                "message": f"{header_name} header가 필요합니다.",
            },
        )
    if len(values) != 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{header_name}는 정확히 하나의 canonical strong ETag여야 합니다.",
        )
    matched = _REVISION_ETAG_PATTERN.fullmatch(values[0])
    if matched is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{header_name}는 정확히 하나의 canonical strong ETag여야 합니다.",
        )
    revision = int(matched.group(1))
    if revision > _MAX_BIGINT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{header_name} revision이 BIGINT 범위를 벗어났습니다.",
        )
    return revision

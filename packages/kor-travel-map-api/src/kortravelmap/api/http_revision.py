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


# ─── 공개 상세 ETag: revision + 장소 속성 digest (ADR-121 §7.2) ────────────────
# 장소 속성은 source link에서 유도돼 ``row_revision``을 올리지 않고도 바뀐다. 그래서 공개
# 상세 ETag는 ``"<revision>-<digest16>"``다. 속성이 없으면 digest를 붙이지 않아 종전
# ``"<revision>"``과 같다(속성 없는 Feature의 캐시가 그대로 유효하다).
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{16}$")
_REVISION_DIGEST_ETAG_PATTERN = re.compile(r'^"([1-9][0-9]*)(?:-([0-9a-f]{16}))?"$')


def revision_digest_etag(revision: int, digest: str | None) -> str:
    """revision과 선택 digest(16자 hex)를 canonical strong ETag로 직렬화한다."""
    base = revision_etag(revision)
    if digest is None:
        return base
    if _DIGEST_PATTERN.fullmatch(digest) is None:
        raise ValueError("ETag digest는 16자 소문자 hex여야 합니다.")
    return f'"{revision}-{digest}"'


def parse_revision_digest_header(request: Request, header_name: str) -> str | None:
    """선택 header 한 줄의 canonical strong ETag(``revision_digest_etag`` 형식)를 읽는다.

    없으면 ``None``. 여러 줄·weak·형식 위반·BIGINT 초과는 422다. 반환값은 비교용 ETag 원문이다.
    """
    values = request.headers.getlist(header_name)
    if not values:
        return None
    message = f"{header_name}는 정확히 하나의 canonical strong ETag여야 합니다."
    if len(values) != 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=message)
    matched = _REVISION_DIGEST_ETAG_PATTERN.fullmatch(values[0])
    if matched is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=message)
    if int(matched.group(1)) > _MAX_BIGINT:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{header_name} revision이 BIGINT 범위를 벗어났습니다.",
        )
    return values[0]

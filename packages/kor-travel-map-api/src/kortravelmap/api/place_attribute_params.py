"""``kortravelmap.api.place_attribute_params`` — ``attribute`` 반복 query 검증(ADR-121 §7.1).

목록·검색·주변·in-bounds(공개·admin)가 같은 규칙을 쓴다.

- 최대 :data:`MAX_ATTRIBUTE_FILTERS`개, 코드마다 하나의 AND 조건이다.
- catalog(``feature.place_attributes``)에 없는 코드는 422다. 공개 경로에서는 ``admin_only``
  코드도 **없는 코드와 똑같이** 422다(존재를 드러내지 않는다).
- 비었으면(미지정) DB를 읽지 않고 ``None`` — 필터 술어가 단락된다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Final

from fastapi import HTTPException, Query, status
from kortravelmap.infra import place_attribute_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "MAX_ATTRIBUTE_FILTERS",
    "AttributeQuery",
    "resolve_attribute_filter",
]

MAX_ATTRIBUTE_FILTERS: Final[int] = 5

AttributeQuery = Annotated[
    list[str] | None,
    Query(
        description=(
            "장소 속성 코드 반복 필터(ADR-121). 지정한 코드를 **모두** 가진 feature만 "
            "남긴다(AND, 최대 5개). 코드는 `GET /v1/place-attributes` catalog를 따른다. "
            "모르는 코드는 422다."
        ),
    ),
]


def _validation_error(message: str, *, details: dict[str, object]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": "VALIDATION_ERROR", "message": message, "details": details},
    )


async def resolve_attribute_filter(
    session: AsyncSession,
    attribute: Sequence[str] | None,
    *,
    public: bool,
) -> list[str] | None:
    """요청 ``attribute`` 값을 검증해 정렬·중복 제거한 코드 목록을 돌려준다.

    ``public``이면 공개(``visibility='public'``) 코드만 받는다. 개수 상한은 DB를 읽기 전에
    본다.
    """
    if not attribute:
        return None
    if len(attribute) > MAX_ATTRIBUTE_FILTERS:
        raise _validation_error(
            f"attribute는 최대 {MAX_ATTRIBUTE_FILTERS}개까지 지정할 수 있습니다.",
            details={"max_items": MAX_ATTRIBUTE_FILTERS, "received": len(attribute)},
        )
    codes = sorted({value.strip() for value in attribute})
    if "" in codes:
        raise _validation_error(
            "attribute에 빈 값이 있습니다.",
            details={"attribute": list(attribute)},
        )
    catalog = await place_attribute_repo.list_place_attributes(session, public_only=public)
    known = {item.code for item in catalog}
    unknown = [code for code in codes if code not in known]
    if unknown:
        raise _validation_error(
            "알 수 없는 장소 속성 코드입니다.",
            details={"unknown_attributes": unknown},
        )
    return codes

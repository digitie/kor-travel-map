"""``krtour.map_admin.routers.version`` — ``GET /debug/version``.

본 패키지 + 메인 라이브러리(``python-krtour-map``)의 distribution version을
함께 응답. 디버그 / 트러블슈팅 / TripMate 측 호환성 점검에 사용.
"""

from __future__ import annotations

from fastapi import APIRouter
from krtour.map import __version__ as KRTOUR_MAP_VERSION
from pydantic import BaseModel, ConfigDict, Field

from krtour.map_admin import __version__ as DEBUG_UI_VERSION

__all__ = ["router", "VersionResponse"]


router = APIRouter(prefix="/debug", tags=["debug"])


class VersionResponse(BaseModel):
    """``/debug/version`` 응답 schema."""

    model_config = ConfigDict(extra="forbid")

    debug_ui: str = Field(description="``krtour-map-admin`` distribution version.")
    krtour_map: str = Field(description="``python-krtour-map`` (메인) distribution version.")


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="package versions",
    description=(
        "본 디버그 패키지 + 메인 라이브러리 distribution version 응답. ADR-038 CI "
        "재활성화 이후 PR 추적 / TripMate 측 호환성 점검에 사용."
    ),
)
async def get_version() -> VersionResponse:
    """본 패키지 + 메인 lib version."""
    return VersionResponse(
        debug_ui=DEBUG_UI_VERSION,
        krtour_map=KRTOUR_MAP_VERSION,
    )

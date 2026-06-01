"""``krtour.map_admin.routers.health`` — ``GET /debug/health``.

운영 LB / Cloudflare Tunnel health check / 사람이 직접 ping. 의존 없는 정적
응답 (DB/외부 자원 점검은 별도 ``/ops/health-deep`` 후속 PR).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["router", "HealthResponse"]


router = APIRouter(prefix="/debug", tags=["debug"])


class HealthResponse(BaseModel):
    """`/debug/health` 응답 schema."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(description="항상 ``'ok'``. unhealthy면 본 라우터에 도달 X.")
    service: str = Field(description="서비스 식별자 — ``'krtour-map-admin'``.")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="liveness probe",
    description=(
        "정적 응답. 본 라우터가 200을 내면 FastAPI app이 살아 있다. DB/외부 자원의 "
        "deep health check는 별도 ``/ops/health-deep`` (Sprint 3+)."
    ),
)
async def get_health() -> HealthResponse:
    """liveness probe — 의존 없이 항상 ``status='ok'``."""
    return HealthResponse(status="ok", service="krtour-map-admin")

"""``GET /health`` / ``GET /version`` — public liveness + 버전 (T-213h).

user-facing 표면. 기존 ``/debug/health``·``/debug/version``과 별개로 루트
경로에 두고 user OpenAPI subset에 포함한다. ``/health``는 **liveness**(의존 없는
정적 200)로, DB/RustFS/Dagster deep readiness는 후속(``/ops/health-deep`` 계열)로
분리한다 — liveness probe가 DB 장애에도 동작해야 하기 때문이다. ``/version``은
배포 프로그램/메인 lib 버전 + (있으면) commit으로 클라이언트 호환성 확인용이다.
응답은 admin과 동일한 ``{data, meta}`` envelope를 쓴다.
"""

from __future__ import annotations

import os
from time import perf_counter

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from kortravelmap import __version__ as KOR_TRAVEL_MAP_VERSION
from kortravelmap.api import __version__ as API_VERSION
from kortravelmap.api.response import Meta, make_meta

router = APIRouter(tags=["public"])


class HealthData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str


class PublicHealthResponse(BaseModel):
    """``GET /health`` 응답 (liveness)."""

    model_config = ConfigDict(extra="forbid")

    data: HealthData
    meta: Meta


class VersionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    kor_travel_map_version: str
    openapi_version: str
    commit: str | None = None


class PublicVersionResponse(BaseModel):
    """``GET /version`` 응답."""

    model_config = ConfigDict(extra="forbid")

    data: VersionData
    meta: Meta


@router.get(
    "/health",
    response_model=PublicHealthResponse,
    summary="public liveness probe",
)
async def get_public_health() -> PublicHealthResponse:
    """liveness — 의존 없이 항상 ``status='ok'`` 200. deep readiness는 후속."""
    started_at = perf_counter()
    return PublicHealthResponse(
        data=HealthData(status="ok", service="kor-travel-map"),
        meta=make_meta(started_at=started_at),
    )


@router.get(
    "/version",
    response_model=PublicVersionResponse,
    summary="public version",
)
async def get_public_version() -> PublicVersionResponse:
    """배포 프로그램(admin)/메인 lib 버전 + commit(env ``KOR_TRAVEL_MAP_GIT_COMMIT``)."""
    started_at = perf_counter()
    return PublicVersionResponse(
        data=VersionData(
            version=API_VERSION,
            kor_travel_map_version=KOR_TRAVEL_MAP_VERSION,
            openapi_version=API_VERSION,
            commit=os.environ.get("KOR_TRAVEL_MAP_GIT_COMMIT") or None,
        ),
        meta=make_meta(started_at=started_at),
    )

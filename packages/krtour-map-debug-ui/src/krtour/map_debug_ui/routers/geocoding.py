"""``krtour.map_debug_ui.routers.geocoding`` — kraddr-geo REST v2 디버그 라우터.

운영자/개발자가 kraddr-geo 연계가 정상인지 브라우저/curl로 즉시 확인할 수 있도록
``GET /debug/geocoding/{reverse,geocode}``(매핑된 Address/Coordinate) +
``/raw``(kraddr-geo 응답 그대로) + ``/health``(upstream 도달성) 5경로를 노출한다.

설정: ``KRTOUR_MAP_DEBUG_UI_KRADDR_GEO_BASE_URL``(예 ``http://127.0.0.1:13088/api/proxy``).
미설정 시 모든 엔드포인트는 503 반환.

ADR 참조: ADR-006(client 주입 + structural Protocol), ADR-035(/debug 운영 범위).
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from krtour.map.dto import Address, Coordinate
from krtour.map.geocoding import (
    KraddrGeoRestClient,
    geocode_response_to_coordinate,
    reverse_response_to_address,
)
from pydantic import BaseModel, ConfigDict

from krtour.map_debug_ui.settings import DebugUiSettings

__all__ = ["router", "get_settings"]

router = APIRouter(prefix="/debug/geocoding", tags=["geocoding"])


# DI — 호출별 settings 인스턴스 재사용 (FastAPI Depends).
def get_settings() -> DebugUiSettings:
    return DebugUiSettings()


def _require_base_url(settings: DebugUiSettings) -> str:
    if not settings.kraddr_geo_base_url:
        raise HTTPException(
            status_code=503,
            detail=(
                "kraddr-geo base URL 미설정. "
                "`KRTOUR_MAP_DEBUG_UI_KRADDR_GEO_BASE_URL`을 박아주세요."
            ),
        )
    return settings.kraddr_geo_base_url


async def _get_rest_client(base_url: str) -> KraddrGeoRestClient:
    """KraddrGeoRestClient + 일회용 httpx.AsyncClient. 호출 측이 close 책임.

    본 라우터는 매 호출마다 client를 새로 만들어 잡아둠 — 운영 시 connection
    pool 재사용은 후속(lifespan-scope client). 디버그 라우터라 단순성 우선.
    """
    http = httpx.AsyncClient(base_url=base_url, timeout=10.0)
    return KraddrGeoRestClient(http)


# ── 응답 schema ─────────────────────────────────────────────────────────


class GeocodingHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str
    reachable: bool
    upstream_status: int | None
    detail: str | None


class ReverseResponseSchema(BaseModel):
    """매핑된 Address (`reverse_response_to_address` 결과) — None이면 404."""

    model_config = ConfigDict(extra="forbid")

    address: Address | None


class GeocodeResponseSchema(BaseModel):
    """매핑된 Coordinate (`geocode_response_to_coordinate` 결과) — None이면 404."""

    model_config = ConfigDict(extra="forbid")

    coord: Coordinate | None


# ── 라우터 ─────────────────────────────────────────────────────────────


@router.get(
    "/health",
    response_model=GeocodingHealthResponse,
    summary="kraddr-geo upstream 도달성 확인",
)
async def health(
    settings: Annotated[DebugUiSettings, Depends(get_settings)],
) -> GeocodingHealthResponse:
    """``base_url + /v1/healthz`` 호출 결과 요약."""
    base_url = settings.kraddr_geo_base_url
    if not base_url:
        return GeocodingHealthResponse(
            base_url="",
            reachable=False,
            upstream_status=None,
            detail="base URL 미설정",
        )
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as http:
            resp = await http.get("/v1/healthz")
        return GeocodingHealthResponse(
            base_url=base_url,
            reachable=resp.status_code == 200,
            upstream_status=resp.status_code,
            detail=None if resp.status_code == 200 else resp.text[:200],
        )
    except (httpx.HTTPError, OSError) as exc:
        return GeocodingHealthResponse(
            base_url=base_url,
            reachable=False,
            upstream_status=None,
            detail=str(exc)[:200],
        )


@router.get(
    "/reverse",
    response_model=ReverseResponseSchema,
    summary="좌표 → 매핑된 Address (reverse geocoding)",
)
async def reverse_geocode(
    settings: Annotated[DebugUiSettings, Depends(get_settings)],
    lon: Annotated[float, Query(description="경도 (WGS84).")],
    lat: Annotated[float, Query(description="위도 (WGS84).")],
    type_: Annotated[
        str,
        Query(alias="type", description="road/parcel/both — kraddr-geo 인자 그대로."),
    ] = "both",
    zipcode: Annotated[bool, Query(description="우편번호 포함 여부.")] = True,
    radius_m: Annotated[int | None, Query(ge=1, le=2000)] = None,
    max_distance_m: Annotated[
        float | None, Query(ge=0, description="결과 필터 — 본 lib 변환기 옵션.")
    ] = None,
) -> ReverseResponseSchema:
    base_url = _require_base_url(settings)
    client = await _get_rest_client(base_url)
    try:
        response = await client.reverse(
            lon, lat, type_=type_, zipcode=zipcode, radius_m=radius_m  # type: ignore[arg-type]
        )
    finally:
        await client._http.aclose()  # noqa: SLF001 — 단명 디버그 client
    return ReverseResponseSchema(
        address=reverse_response_to_address(response, max_distance_m=max_distance_m),
    )


@router.get(
    "/reverse/raw",
    summary="좌표 → kraddr-geo 원본 응답 그대로 (디버그)",
)
async def reverse_raw(
    settings: Annotated[DebugUiSettings, Depends(get_settings)],
    lon: Annotated[float, Query()],
    lat: Annotated[float, Query()],
    type_: Annotated[str, Query(alias="type")] = "both",
    zipcode: Annotated[bool, Query()] = True,
    radius_m: Annotated[int | None, Query(ge=1, le=2000)] = None,
) -> dict[str, Any]:
    """``KraddrGeoRestClient`` 사용하지 않고 raw HTTP 그대로 — 디버그용."""
    base_url = _require_base_url(settings)
    params: dict[str, Any] = {
        "x": lon,
        "y": lat,
        "type": type_,
        "zipcode": str(zipcode).lower(),
    }
    if radius_m is not None:
        params["radius_m"] = radius_m
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
            r = await http.get("/v1/address/reverse", params=params)
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"kraddr-geo {exc.response.status_code}: {exc.response.text[:300]}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"kraddr-geo unreachable: {exc}"
        ) from exc


@router.get(
    "/geocode",
    response_model=GeocodeResponseSchema,
    summary="주소 → 매핑된 Coordinate (geocoding)",
)
async def geocode(
    settings: Annotated[DebugUiSettings, Depends(get_settings)],
    address: Annotated[str, Query(min_length=1, max_length=200)],
    type_: Annotated[str, Query(alias="type")] = "road",
    refine: Annotated[bool, Query()] = True,
    fallback: Annotated[str, Query()] = "local_only",
    min_confidence: Annotated[float, Query(ge=0, le=1.0)] = 0.0,
) -> GeocodeResponseSchema:
    base_url = _require_base_url(settings)
    client = await _get_rest_client(base_url)
    try:
        response = await client.geocode(
            address,
            type_=type_,  # type: ignore[arg-type]
            refine=refine,
            fallback=fallback,  # type: ignore[arg-type]
        )
    finally:
        await client._http.aclose()  # noqa: SLF001
    return GeocodeResponseSchema(
        coord=geocode_response_to_coordinate(response, min_confidence=min_confidence),
    )


@router.get(
    "/geocode/raw",
    summary="주소 → kraddr-geo 원본 응답 그대로 (디버그)",
)
async def geocode_raw(
    settings: Annotated[DebugUiSettings, Depends(get_settings)],
    address: Annotated[str, Query(min_length=1, max_length=200)],
    type_: Annotated[str, Query(alias="type")] = "road",
    refine: Annotated[bool, Query()] = True,
    fallback: Annotated[str, Query()] = "local_only",
) -> dict[str, Any]:
    base_url = _require_base_url(settings)
    params: dict[str, Any] = {
        "address": address,
        "type": type_,
        "refine": str(refine).lower(),
        "fallback": fallback,
    }
    try:
        async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
            r = await http.get("/v1/address/geocode", params=params)
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"kraddr-geo {exc.response.status_code}: {exc.response.text[:300]}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"kraddr-geo unreachable: {exc}"
        ) from exc

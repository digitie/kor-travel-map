"""Dagster API용 FastAPI request adapter."""

from __future__ import annotations

import httpx
from fastapi import Request

from kortravelmap.api.settings import ApiSettings

__all__ = [
    "dagster_http_dependencies",
    "http_client_from_request",
    "settings_from_request",
]


def settings_from_request(request: Request) -> ApiSettings:
    """앱에 주입된 설정을 읽고, 없으면 기본 설정을 사용한다."""

    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, ApiSettings):
        return settings
    return ApiSettings()


def http_client_from_request(
    request: Request,
    settings: ApiSettings,
) -> httpx.AsyncClient:
    """앱 수명 동안 재사용하는 Dagster HTTP client를 반환한다."""

    client = getattr(request.app.state, "dagster_http_client", None)
    if isinstance(client, httpx.AsyncClient) and not client.is_closed:
        return client
    client = httpx.AsyncClient(timeout=settings.dagster_request_timeout_seconds)
    request.app.state.dagster_http_client = client
    return client


def dagster_http_dependencies(
    request: Request,
) -> tuple[ApiSettings, httpx.AsyncClient]:
    """Dagster application service가 요구하는 HTTP 의존성을 조립한다."""

    settings = settings_from_request(request)
    return settings, http_client_from_request(request, settings)

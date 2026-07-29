"""공용 application service의 FastAPI adapter 단위 테스트."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import Request
from kortravelmap.infra.feature_update_repo import FeatureUpdateLockBusy

from kortravelmap.api import feature_update_service
from kortravelmap.api.dagster_http import dagster_http_dependencies
from kortravelmap.api.feature_update_http import to_http_exception
from kortravelmap.api.settings import ApiSettings


@pytest.mark.unit
@pytest.mark.asyncio
async def test_dagster_http_reuses_injected_settings_and_client() -> None:
    settings = ApiSettings(
        dagster_url="http://dagster.example:12302",
        dagster_allowed_hosts=["dagster.example"],
    )
    request = cast(
        Request,
        cast(
            Any,
            SimpleNamespace(
                app=SimpleNamespace(
                    state=SimpleNamespace(
                        settings=settings,
                        dagster_http_client=None,
                    )
                )
            ),
        ),
    )

    first_settings, first_client = dagster_http_dependencies(request)
    second_settings, second_client = dagster_http_dependencies(request)

    assert first_settings is settings
    assert second_settings is settings
    assert second_client is first_client
    await first_client.aclose()


@pytest.mark.unit
def test_feature_update_http_lock_conflict_preserves_retry_contract() -> None:
    error = feature_update_service.FeatureUpdateLockConflict(
        FeatureUpdateLockBusy(retry_after_seconds=15)
    )

    mapped = to_http_exception(error)

    assert mapped.status_code == 409
    assert mapped.headers == {"Retry-After": "15"}
    assert mapped.detail == {
        "code": "LOCK_BUSY",
        "message": "동일 feature update scope가 이미 실행 중입니다.",
        "details": {"retry_after_seconds": 15},
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            feature_update_service.FeatureUpdateValidationError("invalid scope"),
            422,
            "invalid scope",
        ),
        (
            feature_update_service.SigunguResolverUnavailable("resolver disabled"),
            503,
            {
                "code": "GEO_AUTH_NOT_CONFIGURED",
                "message": "resolver disabled",
                "details": {},
            },
        ),
        (
            feature_update_service.FeatureUpdateResolverError("upstream failed"),
            502,
            {
                "code": "PROVIDER_ERROR",
                "message": "upstream failed",
                "details": {},
            },
        ),
        (
            feature_update_service.FeatureUpdateServiceError("unknown"),
            500,
            "feature update request enqueue failed",
        ),
    ],
)
def test_feature_update_http_maps_typed_and_unknown_errors(
    error: feature_update_service.FeatureUpdateServiceError,
    expected_status: int,
    expected_detail: str | dict[str, object],
) -> None:
    mapped = to_http_exception(error)

    assert mapped.status_code == expected_status
    assert mapped.detail == expected_detail

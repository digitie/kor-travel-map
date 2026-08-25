"""`300` baseline에 포함된 C05 산림청 catalog seed를 자연키로 검증한다.

`0230`은 retired cohort이므로 active integration에서 개별 migration을 replay하지 않는다.
대신 final `300` root가 그 결과를 정확히 포함하는지 dataset/operation/scope의 자연키로
검증한다. 대리키 숫자를 고정하지 않아 source DB의 sequence 이력과 무관하게 계약을 지킨다.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_PROVIDER = "python-krforest-api"
_DATASETS: tuple[tuple[str, str, dict[str, Any], str], ...] = (
    (
        "krforest_mountain_trails",
        "산림청 등산로(PBD0000041) route",
        {"produces": ["route"], "extensions": {}, "schema_version": 1},
        "feature_route_krforest_mountain_trails_job",
    ),
    (
        "krforest_dulle_trails",
        "산림청 둘레길(PBD0000031) route",
        {"produces": ["route"], "extensions": {}, "schema_version": 1},
        "feature_route_krforest_dulle_trails_job",
    ),
    (
        "krforest_mountain_weather",
        "산림청 산악기상 관측(15084696)",
        {"produces": ["weather"], "extensions": {}, "schema_version": 1},
        "feature_weather_krforest_mountain_weather_job",
    ),
    (
        "krforest_wildfire_risk_forecast",
        "산림청 산불위험 V2 예보(15084817)",
        {"produces": ["weather"], "extensions": {}, "schema_version": 1},
        "feature_weather_krforest_wildfire_risk_forecast_job",
    ),
    (
        "krforest_landslide_forecast_issues",
        "산림청 산사태 예보발령·해제(15074798)",
        {"produces": ["notice"], "extensions": {}, "schema_version": 1},
        "feature_notice_krforest_landslide_forecast_issues_job",
    ),
)


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


@pytest.mark.asyncio
async def test_300_baseline_contains_c05_catalog_with_natural_keys(
    migrated_engine: AsyncEngine,
) -> None:
    expected_datasets = {
        (key, display_name, _canonical(capabilities))
        for key, display_name, capabilities, _ in _DATASETS
    }
    expected_operations = {
        (key, operation_key, kind, _canonical(config))
        for key, _, _, refresh_key in _DATASETS
        for operation_key, kind, config in (
            (refresh_key, "refresh", {}),
            (f"{refresh_key}.preview", "preview", {"handler": "fixture"}),
        )
    }
    expected_scopes = {
        (key, "dataset_wide", refresh_key, "refresh")
        for key, _, _, refresh_key in _DATASETS
    }

    async with migrated_engine.connect() as connection:
        datasets = {
            (str(row.dataset_key), str(row.display_name), _canonical(row.capabilities))
            for row in (
                await connection.execute(
                    text(
                        "SELECT dataset_key, display_name, capabilities "
                        "FROM provider_sync.provider_datasets "
                        "WHERE provider = :provider"
                    ),
                    {"provider": _PROVIDER},
                )
            ).mappings()
        }
        operations = {
            (
                str(row.dataset_key),
                str(row.operation_key),
                str(row.operation_kind),
                _canonical(row.config),
            )
            for row in (
                await connection.execute(
                    text(
                        "SELECT dataset.dataset_key, operation.operation_key, "
                        "operation.operation_kind, operation.config "
                        "FROM provider_sync.provider_dataset_operations AS operation "
                        "JOIN provider_sync.provider_datasets AS dataset "
                        "ON dataset.provider_dataset_id = operation.provider_dataset_id "
                        "WHERE dataset.provider = :provider"
                    ),
                    {"provider": _PROVIDER},
                )
            ).mappings()
        }
        scopes = {
            (
                str(row.dataset_key),
                str(row.sync_scope),
                str(row.operation_key),
                str(row.operation_kind),
            )
            for row in (
                await connection.execute(
                    text(
                        "SELECT dataset.dataset_key, scope.sync_scope, "
                        "scope.operation_key, scope.operation_kind "
                        "FROM provider_sync.provider_dataset_operation_scopes AS scope "
                        "JOIN provider_sync.provider_datasets AS dataset "
                        "ON dataset.provider_dataset_id = scope.provider_dataset_id "
                        "WHERE dataset.provider = :provider"
                    ),
                    {"provider": _PROVIDER},
                )
            ).mappings()
        }

    assert datasets >= expected_datasets
    assert operations >= expected_operations
    assert scopes >= expected_scopes

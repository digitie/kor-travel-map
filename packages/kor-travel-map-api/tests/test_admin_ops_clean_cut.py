"""ADR-064 C6B legacy REST clean-cut 계약."""

from __future__ import annotations

import pytest

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings

_LEGACY_OPERATIONS = {
    ("get", "/v1/ops/dagster/summary"),
    ("get", "/v1/ops/dagster/runs/{run_id}"),
    ("post", "/v1/ops/dagster/nux-seen"),
    ("patch", "/v1/ops/dagster/schedules/{schedule_name}"),
    ("post", "/v1/ops/dagster/schedules/{schedule_name}/default"),
    ("post", "/v1/ops/dagster/schedules/{schedule_name}/start"),
    ("post", "/v1/ops/dagster/schedules/{schedule_name}/stop"),
    ("post", "/v1/ops/dagster/schedules/{schedule_name}/reset"),
    ("post", "/v1/ops/dagster/schedules/{schedule_name}/run"),
    ("get", "/v1/ops/providers"),
    ("get", "/v1/ops/providers/{provider}"),
    ("get", "/v1/admin/provider-refresh-policies"),
    ("get", "/v1/admin/provider-refresh-policies/{provider}/{dataset_key}"),
    ("put", "/v1/admin/provider-refresh-policies/{provider}/{dataset_key}"),
    ("get", "/v1/ops/import-jobs"),
    ("get", "/v1/ops/import-job-events"),
    ("get", "/v1/ops/import-jobs/{job_id}"),
    ("get", "/v1/ops/import-jobs/{job_id}/events"),
    ("post", "/v1/ops/import-jobs/{job_id}/cancel"),
    ("get", "/v1/admin/features/update-requests"),
    ("post", "/v1/admin/features/update-requests"),
    ("post", "/v1/admin/features/update-requests/preview"),
    ("get", "/v1/admin/features/update-requests/{request_id}"),
    ("post", "/v1/admin/features/update-requests/{request_id}/cancel"),
    ("post", "/v1/admin/features/update-requests/{request_id}/run-now"),
    ("get", "/v1/debug/etl/providers"),
    ("get", "/v1/debug/etl/{provider}/datasets"),
    ("post", "/v1/debug/etl/{provider}/{dataset}/preview"),
}


@pytest.mark.unit
def test_legacy_admin_ops_operations_are_removed() -> None:
    assert len(_LEGACY_OPERATIONS) == 28
    spec = create_app(ApiSettings()).openapi()

    for method, path in _LEGACY_OPERATIONS:
        assert method not in spec["paths"].get(path, {})


@pytest.mark.unit
def test_canonical_admin_ops_and_public_provider_contracts_remain() -> None:
    spec = create_app(ApiSettings()).openapi()
    required_paths = {
        "/v1/ops/datasets",
        "/v1/ops/datasets/{provider_dataset_id}",
        "/v1/ops/datasets/refresh-policy",
        "/v1/ops/datasets/{provider_dataset_id}/preview",
        "/v1/ops/pipeline/overview",
        "/v1/ops/pipeline/executions",
        "/v1/ops/pipeline/events",
        "/v1/ops/pipeline/dagster-runs",
        "/v1/ops/pipeline/schedules",
        "/v1/ops/pipeline/requests",
        "/v1/providers",
        "/v1/providers/{provider}/last-sync",
    }
    assert required_paths <= set(spec["paths"])


@pytest.mark.unit
def test_non_consolidated_ops_observability_routes_remain() -> None:
    spec = create_app(ApiSettings()).openapi()
    assert {
        "/v1/ops/metrics",
        "/v1/ops/health-deep",
        "/v1/ops/system-logs",
        "/v1/ops/api-call-logs",
        "/v1/ops/consistency/reports",
        "/v1/ops/consistency/issues",
    } <= set(spec["paths"])

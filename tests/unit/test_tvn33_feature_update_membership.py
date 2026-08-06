"""T-VN-33 feature-update canonical membership 경계 검증."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from kortravelmap.infra import feature_update_active_repo as active_repo
from kortravelmap.infra import feature_update_repo as repo
from kortravelmap.infra.feature_update_executor import (
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshScope,
    _require_runner_result_membership,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget


def _membership(
    *,
    provider_dataset_id: int = 17,
    sync_scope: str = "dataset_wide",
) -> repo.FeatureUpdateRequestDataset:
    return repo.FeatureUpdateRequestDataset(
        feature_update_request_dataset_id="90000000-0000-4000-8000-000000000017",
        provider_dataset_id=provider_dataset_id,
        sync_scope=sync_scope,
        provider="python-test-api",
        dataset_key="test-dataset",
        operation_key="refresh_test_dataset",
    )


def _row(*, membership: repo.FeatureUpdateRequestDataset | None) -> SimpleNamespace:
    now = datetime(2026, 8, 7, tzinfo=UTC)
    return SimpleNamespace(
        request_id="90000000-0000-4000-8000-000000000001",
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_test_dataset",
        },
        dataset_membership_mode="single",
        update_policy={},
        run_mode="queued",
        priority=50,
        status="queued",
        matched_scope={},
        job_id="90000000-0000-4000-8000-000000000002",
        dagster_run_id=None,
        cancellation_id=None,
        cancellation_requested_at=None,
        cancellation_requested_by=None,
        cancellation_reason=None,
        operator=None,
        reason=None,
        error_message=None,
        created_at=now,
        started_at=None,
        finished_at=None,
        generation=1,
        dispatch_requested_at=None,
        feature_update_request_dataset_id=(
            membership.feature_update_request_dataset_id if membership else None
        ),
        provider_dataset_id=membership.provider_dataset_id if membership else None,
        sync_scope=membership.sync_scope if membership else None,
        operation_key=membership.operation_key if membership else None,
        provider=membership.provider if membership else None,
        dataset_key=membership.dataset_key if membership else None,
    )


def _scope() -> ProviderDatasetRefreshScope:
    return ProviderDatasetRefreshScope(
        request_id="90000000-0000-4000-8000-000000000001",
        provider_dataset_id=17,
        sync_scope="dataset_wide",
        provider="python-test-api",
        dataset_key="test-dataset",
        scope_type="provider_dataset",
        request_scope={
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_test_dataset",
        },
        update_policy={},
        feature_ids=(),
        feature_count=0,
        prevent_provider_reactivation=True,
        operation_key="refresh_test_dataset",
    )


def test_direct_scope_has_only_canonical_dataset_id() -> None:
    assert repo._canonicalize_request_scope(
        {
            "type": "provider_dataset",
            "provider_dataset_id": 17,
            "sync_scope": "dataset_wide",
            "operation_key": "refresh_test_dataset",
        }
    ) == {
        "type": "provider_dataset",
        "provider_dataset_id": 17,
        "sync_scope": "dataset_wide",
        "operation_key": "refresh_test_dataset",
    }

    with pytest.raises(ValueError, match="only permits"):
        repo._canonicalize_request_scope(
            {
                "type": "provider_dataset",
                "provider_dataset_id": 17,
                "sync_scope": "dataset_wide",
                "operation_key": "refresh_test_dataset",
                "provider": "python-test-api",
            }
        )


def test_direct_scope_must_match_its_single_membership() -> None:
    request = repo._rows_to_request([_row(membership=_membership())])
    assert repo.execution_scope_for_request(request) == {
        "type": "provider_dataset",
        "provider_dataset_id": 17,
        "sync_scope": "dataset_wide",
        "operation_key": "refresh_test_dataset",
    }

    wrong_scope = repo.FeatureUpdateRequest(
        **{
            **request.__dict__,
            "scope": {
                "type": "provider_dataset",
                "provider_dataset_id": 18,
                "sync_scope": "dataset_wide",
                "operation_key": "refresh_test_dataset",
            },
        }
    )
    with pytest.raises(RuntimeError, match="disagree"):
        repo.execution_scope_for_request(wrong_scope)


def test_persisted_request_requires_membership_and_exposes_canonical_identity() -> None:
    with pytest.raises(RuntimeError, match="requires dataset memberships"):
        repo._rows_to_request([_row(membership=None)])

    request = repo._rows_to_request([_row(membership=_membership())])
    assert request.dataset_membership_mode == "single"
    assert request.dataset_memberships == (_membership(),)
    assert not hasattr(request, "providers")
    assert not hasattr(request, "dataset_keys")
    assert not hasattr(request, "effective_sync_scope")


def test_duplicate_dataset_membership_is_rejected_before_any_writer_sql() -> None:
    target = ImportJobDatasetTarget(17, "dataset_wide", "refresh_test_dataset")
    with pytest.raises(ValueError, match="duplicate"):
        repo._normalized_dataset_memberships((target, target))


def test_request_insert_requires_job_membership_set_agreement() -> None:
    assert "ops.import_job_datasets" in repo._INSERT_REQUEST_SQL
    assert "ops.feature_update_request_datasets" in repo._INSERT_REQUEST_SQL
    assert "EXCEPT" in repo._INSERT_REQUEST_SQL
    assert "dataset_membership_mode" in repo._INSERT_REQUEST_SQL
    assert "providers" not in repo._INSERT_REQUEST_SQL
    assert "dataset_keys" not in repo._INSERT_REQUEST_SQL


def test_active_membership_overlap_uses_the_trigger_constraint_identity() -> None:
    class _DriverError(Exception):
        sqlstate = "23505"
        constraint_name = active_repo.ACTIVE_PROVIDER_DATASET_OVERLAP_CONSTRAINT

    conflict = IntegrityError("insert", {}, _DriverError())
    assert active_repo.is_active_provider_dataset_unique_violation(conflict)

    class _DifferentConstraintError(Exception):
        sqlstate = "23505"
        constraint_name = "uq_not_the_feature_update_membership"

    assert not active_repo.is_active_provider_dataset_unique_violation(
        IntegrityError("insert", {}, _DifferentConstraintError())
    )


def test_active_membership_lookup_rejects_inactive_or_disabled_target() -> None:
    class _Mappings:
        def all(self) -> list[object]:
            return []

    class _Result:
        def mappings(self) -> _Mappings:
            return _Mappings()

    class _Session:
        async def execute(self, *_args: object, **_kwargs: object) -> _Result:
            return _Result()

    async def _resolve() -> None:
        await repo._resolve_active_dataset_memberships(
            _Session(), (ImportJobDatasetTarget(17, "dataset_wide", "refresh_test_dataset"),)
        )

    with pytest.raises(ValueError, match="active dataset and enabled refresh scope"):
        asyncio.run(_resolve())


def test_runner_cannot_report_a_membership_outside_the_request_snapshot() -> None:
    scope = _scope()
    matching = ProviderDatasetRefreshResult(
        provider_dataset_id=17,
        sync_scope="dataset_wide",
        operation_key="refresh_test_dataset",
        provider="python-test-api",
        dataset_key="test-dataset",
    )
    assert _require_runner_result_membership(matching, scope) is matching

    with pytest.raises(RuntimeError, match="does not match"):
        _require_runner_result_membership(
            ProviderDatasetRefreshResult(
                provider_dataset_id=18,
                sync_scope="dataset_wide",
                operation_key="refresh_test_dataset",
                provider="python-other-api",
                dataset_key="other-dataset",
            ),
            scope,
        )

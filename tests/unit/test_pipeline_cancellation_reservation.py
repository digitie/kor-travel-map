"""Pipeline cancellation termination reservation 정본 단위 계약."""

from __future__ import annotations

import inspect

import pytest

import kortravelmap.infra as infra
from kortravelmap.infra import pipeline_cancellation_queries as queries
from kortravelmap.infra.models import (
    FeatureUpdateRequestRow,
    ImportJobRow,
    PipelineCancellationMemberRow,
    PipelineCancellationRow,
)
from kortravelmap.infra.pipeline_cancellation_repo import (
    mark_pipeline_cancellation_run_termination_reserved,
)
from kortravelmap.infra.pipeline_cancellation_types import PipelineCancellationRun

pytestmark = pytest.mark.unit


def test_reservation_query_is_pending_null_cas_with_first_status() -> None:
    statement = queries._RESERVE_RUN_TERMINATION_SQL

    assert "initial_status = COALESCE(initial_status, :initial_status)" in statement
    assert "termination_reserved_at = now()" in statement
    assert "result = 'pending'" in statement
    assert "termination_reserved_at IS NULL" in statement
    assert "RETURNING cancellation_id" in statement


def test_run_queries_project_termination_reservation() -> None:
    assert "termination_reserved_at" in queries._RUNS_SQL
    assert "termination_reserved_at" in queries._LOCK_RUN_SQL
    assert "termination_reserved_at" in PipelineCancellationRun.__annotations__


def test_reservation_writer_is_exported_from_public_infra() -> None:
    assert infra.mark_pipeline_cancellation_run_termination_reserved is (
        mark_pipeline_cancellation_run_termination_reserved
    )
    assert "initial_status" in inspect.signature(
        mark_pipeline_cancellation_run_termination_reserved
    ).parameters


def test_all_pipeline_cancellation_foreign_keys_have_orm_index_parity() -> None:
    indexed = {
        model.__tablename__: {index.name for index in model.__table__.indexes}
        for model in (
            PipelineCancellationRow,
            PipelineCancellationMemberRow,
            ImportJobRow,
            FeatureUpdateRequestRow,
        )
    }

    assert "idx_pipeline_cancellations_previous" in indexed["pipeline_cancellations"]
    assert "idx_pipeline_cancellation_members_run" in indexed[
        "pipeline_cancellation_members"
    ]
    assert "idx_import_jobs_cancellation_id" in indexed["import_jobs"]
    assert "idx_feature_update_requests_cancellation_id" in indexed[
        "feature_update_requests"
    ]

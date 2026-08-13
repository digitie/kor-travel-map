"""C3e-A1 provider feature operation frozen 계약 단위 회귀."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from typing import Any

import pytest

from kortravelmap.core.feature_operation import (
    C6C_CANCEL_PROBE_JOB_KIND,
    FEATURE_OPERATION_MEMBER_KIND,
    FEATURE_OPERATION_ROOT_KIND,
    FEATURE_UPDATE_REQUEST_JOB_KIND,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
)
from kortravelmap.infra import feature_operation_repo, feature_update_repo, jobs_repo
from kortravelmap.infra.feature_operation_repo import ensure_dagster_feature_operation
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationScopeMember,
)

_RESERVED_JOB_KINDS = (
    C6C_CANCEL_PROBE_JOB_KIND,
    FEATURE_OPERATION_ROOT_KIND,
    FEATURE_OPERATION_MEMBER_KIND,
    FEATURE_UPDATE_REQUEST_JOB_KIND,
)


def test_operation_membership_rejects_invalid_canonical_identity() -> None:
    with pytest.raises(ValueError, match="positive"):
        ProviderDatasetOperationMembership(0, "dataset_wide", "feature_place_example_job")
    with pytest.raises(ValueError, match="sync_scope"):
        ProviderDatasetOperationMembership(
            1,
            " dataset_wide",
            "feature_place_example_job",
        )


def test_generic_import_writers_make_canonical_membership_explicit() -> None:
    for writer in (
        jobs_repo.enqueue_unpaired_import_job,
        jobs_repo.start_unpaired_import_job,
    ):
        assert "provider_dataset" not in inspect.signature(writer).parameters
    for writer in (
        jobs_repo.enqueue_provider_dataset_import_job,
        jobs_repo.start_provider_dataset_import_job,
    ):
        parameters = inspect.signature(writer).parameters
        parameter = parameters["dataset_membership"]
        assert parameter.default is inspect.Parameter.empty
        assert "provider_dataset" not in parameters


def test_event_insert_requires_exact_canonical_member() -> None:
    assert "import_job_dataset_id" in jobs_repo._INSERT_EVENT_SQL
    assert "member.import_job_dataset_id" in jobs_repo._INSERT_EVENT_SQL
    assert "provider = CAST(:provider AS text)" not in jobs_repo._INSERT_EVENT_SQL
    assert "dataset_key = CAST(:dataset_key AS text)" not in jobs_repo._INSERT_EVENT_SQL


@pytest.mark.parametrize(
    "writer",
    [
        jobs_repo.enqueue_unpaired_import_job,
        jobs_repo.start_unpaired_import_job,
    ],
)
@pytest.mark.parametrize(
    "kind",
    _RESERVED_JOB_KINDS,
)
async def test_generic_writer_rejects_reserved_feature_kind(
    writer: Any,
    kind: str,
) -> None:
    with pytest.raises(FeatureOperationInvariantConflict):
        await writer(object(), kind=kind)


async def test_feature_update_job_writer_rejects_noncanonical_scope_before_sql() -> None:
    for invalid_scope in ("legacy-alias", "external_system:", f"external_system:{'x' * 113}"):
        with pytest.raises(ValueError, match="sync_scope"):
            ImportJobDatasetTarget(
                provider_dataset_id=1,
                sync_scope=invalid_scope,
                operation_key="mois_license_features_bulk_refresh",
            )


def test_generic_writer_sql_excludes_reserved_feature_kinds() -> None:
    lifecycle_sql = (
        jobs_repo._UPDATE_PAYLOAD_SQL,
        jobs_repo._BIND_DAGSTER_RUN_SQL,
        jobs_repo._ATTACH_BATCH_SQL,
        jobs_repo._CLAIM_JOB_SQL,
        jobs_repo._HEARTBEAT_SQL,
        jobs_repo._FINISH_SQL,
        jobs_repo._CANCEL_SQL,
        jobs_repo._RECOVER_STALE_SQL,
    )
    assert frozenset(_RESERVED_JOB_KINDS) == jobs_repo._GENERIC_IMPORT_RESERVED_KINDS
    assert all(
        all(f"'{kind}'" in statement for kind in _RESERVED_JOB_KINDS)
        for statement in lifecycle_sql
    )
    assert all(
        f"'{kind}'" in jobs_repo._TARGET_KINDS_SQL for kind in _RESERVED_JOB_KINDS
    )
    feature_lifecycle_sql = (
        feature_update_repo._START_REQUEST_SQL,
        feature_update_repo._FINISH_REQUEST_SQL,
        feature_update_repo._REQUEUE_REQUEST_SQL,
        feature_update_repo._HEARTBEAT_IMPORT_JOB_SQL,
        feature_update_repo._SET_MATCHED_SCOPE_SQL,
        feature_update_repo._TOUCH_QUEUED_REQUEST_FOR_LOCK_RETRY_SQL,
    )
    assert all(
        "kind = 'feature_update_request'" in statement
        for statement in feature_lifecycle_sql
    )


def test_generic_job_sql_excludes_quarantined_targets_and_parents() -> None:
    for statement in (jobs_repo._INSERT_JOB_SQL, jobs_repo._START_JOB_SQL):
        assert "parent.quarantined_at IS NULL" in statement

    assert "AND job.quarantined_at IS NULL" in jobs_repo._INSERT_EVENT_SQL

    generic_target_sql = (
        jobs_repo._UPDATE_PAYLOAD_SQL,
        jobs_repo._BIND_DAGSTER_RUN_SQL,
        jobs_repo._CLAIM_JOB_SQL,
        jobs_repo._HEARTBEAT_SQL,
        jobs_repo._FINISH_SQL,
        jobs_repo._CANCEL_SQL,
        jobs_repo._RECOVER_STALE_SQL,
    )
    assert all(
        "quarantined_at IS NULL" in statement for statement in generic_target_sql
    )

    assert "quarantined_at IS NOT NULL" in jobs_repo._ATTACH_BATCH_SQL
    assert "parent.quarantined_at IS NULL" in jobs_repo._ATTACH_BATCH_SQL
    assert "OR quarantined_at IS NOT NULL" in jobs_repo._TARGET_KINDS_SQL

    for statement in (jobs_repo._GET_JOB_SQL, jobs_repo._LIST_JOBS_BY_IDS_SQL):
        assert "quarantined_at IS NULL" in statement


def test_feature_operation_sql_excludes_quarantined_engine_state() -> None:
    assert (
        "root.quarantined_at IS NULL"
        in feature_operation_repo._LOCK_ROOT_BY_RUN_SQL
    )

    operation_read_sql = feature_operation_repo._ROOT_WITH_MEMBERS_SQL
    assert "root.quarantined_at IS NULL" in operation_read_sql
    assert "child.quarantined_at IS NULL" in operation_read_sql

    single_scope_sql = (
        feature_operation_repo._ADVANCE_ROOT_SQL,
        feature_operation_repo._ADVANCE_MEMBERS_SQL,
        feature_operation_repo._ADVANCE_RAW_QUEUED_STATUS_SQL,
        feature_operation_repo._ADVANCE_RAW_CANCELING_STATUS_SQL,
        feature_operation_repo._FINISH_MEMBERSHIP_SQL,
        feature_operation_repo._ACTIVE_ROOTS_PAGE_SQL,
    )
    assert all(
        "quarantined_at IS NULL" in statement for statement in single_scope_sql
    )

    progress_sql = feature_operation_repo._UPDATE_ROOT_PROGRESS_SQL
    assert "AND quarantined_at IS NULL" in progress_sql
    assert "root.quarantined_at IS NULL" in progress_sql

    ensure_source = inspect.getsource(
        feature_operation_repo.ensure_dagster_feature_operation
    )
    assert "AND quarantined_at IS NULL" in ensure_source

    finalize_source = inspect.getsource(
        feature_operation_repo.reconcile_dagster_feature_run
    )
    assert finalize_source.count("quarantined_at IS NULL") >= 3


def test_authoritative_finish_owns_source_observation_generation_and_seal() -> None:
    source = inspect.getsource(
        feature_operation_repo._finalize_authoritative_curation_receipts
    )
    assert "finalize_provider_curation_receipts" in source
    assert "theme_feature_candidates" not in source
    assert "theme_candidate_generations" not in source

    reconcile = inspect.getsource(feature_operation_repo.reconcile_dagster_feature_run)
    assert "authoritative_snapshot_complete" in reconcile
    assert reconcile.index("target_status == \"done\"") < reconcile.index(
        "_finalize_authoritative_curation_receipts"
    )


async def test_feature_operation_ensure_reports_quarantined_run_conflict() -> None:
    class _NoRow:
        def one_or_none(self) -> None:
            return None

    class _QuarantinedRunSession:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(
            self,
            statement: Any,
            _params: dict[str, Any] | None = None,
        ) -> _NoRow:
            self.statements.append(str(statement))
            return _NoRow()

    session = _QuarantinedRunSession()
    with pytest.raises(FeatureOperationInvariantConflict) as raised:
        await ensure_dagster_feature_operation(
            session,  # type: ignore[arg-type]
            dagster_run_id="run-quarantined",
            trigger_kind="manual",
            selected_memberships=(
                ProviderDatasetOperationMembership(
                    1,
                    "dataset_wide",
                    "feature_place_example_job",
                ),
            ),
            operation_key="feature_place_example_job",
            engine_created_at=datetime(2026, 7, 16, tzinfo=UTC),
            engine_started_at=None,
            observed_status="QUEUED",
        )

    assert raised.value.details == {"reason": "quarantined"}
    assert raised.value.dagster_run_id == "run-quarantined"
    assert len(session.statements) == 4
    assert session.statements[1] == session.statements[3]
    assert "root.quarantined_at IS NULL" in session.statements[3]


@pytest.mark.parametrize("owner", [None, "", " ", " owner", "owner "])
@pytest.mark.parametrize(
    ("writer", "owner_parameter", "extra"),
    [
        (
            feature_update_repo.start_update_request,
            "dagster_run_id",
            {"expected_generation": 1},
        ),
        (
            feature_update_repo.finish_update_request,
            "owner_dagster_run_id",
            {"expected_generation": 1},
        ),
        (
            feature_update_repo.lock_feature_update_execution_guard,
            "owner_dagster_run_id",
            {"expected_generation": 1},
        ),
        (
            feature_update_repo.set_update_request_matched_scope,
            "owner_dagster_run_id",
            {"expected_generation": 1, "matched_scope": {}},
        ),
        (
            feature_update_repo.heartbeat_feature_update_request_job,
            "owner_dagster_run_id",
            {"expected_generation": 1},
        ),
        (
            feature_update_repo.requeue_update_request_after_lock_contention,
            "caller_dagster_run_id",
            {"expected_generation": 1},
        ),
    ],
)
async def test_feature_update_lifecycle_rejects_missing_or_untrimmed_owner_before_sql(
    writer: Any,
    owner_parameter: str,
    extra: dict[str, object],
    owner: str | None,
) -> None:
    with pytest.raises(ValueError, match="trimmed non-empty"):
        await writer(
            object(),
            "11111111-1111-4111-8111-111111111111",
            **extra,
            **{owner_parameter: owner},
        )


def test_run_backed_queued_scope_member_requires_dagster_termination() -> None:
    member = PipelineCancellationScopeMember(
        job_id="11111111-1111-4111-8111-111111111111",
        initial_status="queued",
        dagster_run_id="run-1",
        cancellation_id=None,
        operation_kind=FEATURE_OPERATION_ROOT_KIND,
    )
    generic = PipelineCancellationScopeMember(
        job_id="22222222-2222-4222-8222-222222222222",
        initial_status="queued",
        dagster_run_id="run-2",
        cancellation_id=None,
        operation_kind="offline_upload_load",
    )

    assert member.requires_run_termination is True
    assert generic.requires_run_termination is False


def test_reconcile_cursor_is_engine_time_ordered() -> None:
    from kortravelmap.core.feature_operation import DagsterFeatureOperationCursor

    earlier = DagsterFeatureOperationCursor(
        created_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
        root_job_id="11111111-1111-4111-8111-111111111111",
    )
    later = DagsterFeatureOperationCursor(
        created_at=datetime(2026, 7, 15, 2, tzinfo=UTC),
        root_job_id="00000000-0000-4000-8000-000000000000",
    )
    assert earlier < later


@pytest.mark.asyncio
async def test_invalid_engine_time_fails_before_any_db_write() -> None:
    created_at = datetime(2026, 7, 15, 2, tzinfo=UTC)
    with pytest.raises(FeatureOperationInvariantConflict, match="precedes create"):
        await ensure_dagster_feature_operation(
            object(),  # type: ignore[arg-type]
            dagster_run_id="run-invalid-time",
            trigger_kind="manual",
            selected_memberships=(
                ProviderDatasetOperationMembership(
                    1,
                    "dataset_wide",
                    "feature_place_example_job",
                ),
            ),
            operation_key="feature_place_example_job",
            engine_created_at=created_at,
            engine_started_at=datetime(2026, 7, 15, 1, tzinfo=UTC),
            observed_status="STARTED",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("run_id", ["", " run", "run "])
async def test_generic_writer_rejects_blank_or_untrimmed_run_id(run_id: str) -> None:
    with pytest.raises(ValueError, match="trimmed and non-empty"):
        await jobs_repo.enqueue_unpaired_import_job(
            object(),  # type: ignore[arg-type]
            kind="generic",
            dagster_run_id=run_id,
        )

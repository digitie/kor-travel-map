"""T-VN-33 import job canonical membership writer 계약 단위 회귀."""

from __future__ import annotations

import inspect

import pytest

from kortravelmap.infra import jobs_repo
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget


def test_dataset_target_rejects_noncanonical_identity() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        ImportJobDatasetTarget(
            provider_dataset_id=0, sync_scope="dataset_wide", operation_key="op"
        )
    with pytest.raises(ValueError, match="sync_scope"):
        ImportJobDatasetTarget(
            provider_dataset_id=7, sync_scope="default", operation_key="op"
        )


def test_membership_mode_is_derived_from_canonical_target_count() -> None:
    target = ImportJobDatasetTarget(
        provider_dataset_id=7, sync_scope="dataset_wide", operation_key="op_a"
    )
    other = ImportJobDatasetTarget(
        provider_dataset_id=8, sync_scope="target_grids", operation_key="op_b"
    )

    assert jobs_repo._membership_mode(()) == "root"
    assert jobs_repo._membership_mode((target,)) == "single"
    assert jobs_repo._membership_mode((target, other)) == "multiple"


def test_membership_writer_rejects_duplicate_dataset_scope() -> None:
    target = ImportJobDatasetTarget(
        provider_dataset_id=7, sync_scope="dataset_wide", operation_key="op"
    )

    with pytest.raises(ValueError, match="duplicate"):
        jobs_repo._normalized_dataset_memberships((target, target))


def test_job_insert_writes_membership_without_forensic_pair_columns() -> None:
    for statement in (jobs_repo._INSERT_JOB_SQL, jobs_repo._START_JOB_SQL):
        assert "WITH inserted_job AS" in statement
        assert "inserted_members AS" in statement
        assert "INSERT INTO ops.import_job_datasets" in statement
        assert "dataset_membership_mode" in statement
        assert "provider, dataset_key, sync_scope" not in statement
        assert "jsonb_to_recordset" in statement


def test_event_writer_uses_exact_member_id_and_not_forensic_pair() -> None:
    statement = jobs_repo._INSERT_EVENT_SQL

    assert "import_job_dataset_id" in statement
    assert "member.job_id = job.job_id" in statement
    assert "member.import_job_dataset_id" in statement
    assert "job.dataset_membership_mode = 'root'" in statement
    assert "provider, dataset_key" not in statement


def test_membership_join_job_projection_qualifies_every_job_column() -> None:
    """Member joins must not make lifecycle columns such as ``created_at`` ambiguous."""

    for statement in (
        jobs_repo._START_JOB_SQL,
        jobs_repo._GET_JOB_SQL,
        jobs_repo._LIST_JOBS_BY_IDS_SQL,
    ):
        assert (
            f"SELECT {jobs_repo._JOB_SELECT_COLUMNS}, "
            f"{jobs_repo._MEMBER_SELECT_COLUMNS}"
        ) in statement


def test_new_writer_interfaces_do_not_accept_pair_strings() -> None:
    for writer in (
        jobs_repo.enqueue_provider_dataset_import_job,
        jobs_repo.start_provider_dataset_import_job,
    ):
        parameters = inspect.signature(writer).parameters
        assert "dataset_membership" in parameters
        assert "provider_dataset" not in parameters

    for writer in (jobs_repo.enqueue_import_job, jobs_repo.start_import_job):
        parameters = inspect.signature(writer).parameters
        assert "dataset_memberships" in parameters
        assert "provider_dataset" not in parameters


def test_feature_update_writer_requires_canonical_memberships() -> None:
    parameters = inspect.signature(jobs_repo.enqueue_feature_update_request_job).parameters

    assert "dataset_memberships" in parameters
    assert "provider_dataset" not in parameters
    assert "effective_sync_scope" not in parameters


def test_membership_writer_allows_same_scope_with_different_operation() -> None:
    """operation만 다르면 **다른 member**다 (ADR-088 §결정 2).

    실행 membership identity가 triple이므로 같은 dataset+scope에 operation이
    여럿 붙을 수 있다. pair로 중복 판정하면 둘 중 하나가 조용히 사라진다.
    """
    first = ImportJobDatasetTarget(
        provider_dataset_id=7, sync_scope="dataset_wide", operation_key="op_a"
    )
    second = ImportJobDatasetTarget(
        provider_dataset_id=7, sync_scope="dataset_wide", operation_key="op_b"
    )

    assert len(jobs_repo._normalized_dataset_memberships((first, second))) == 2

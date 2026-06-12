"""Offline upload 상태 계약 단위 테스트."""

from __future__ import annotations

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint

from krtour.map.core.offline_upload_states import (
    OFFLINE_UPLOAD_DELETABLE_STATES,
    OFFLINE_UPLOAD_IN_PROGRESS_STATES,
    OFFLINE_UPLOAD_LOADABLE_STATES,
    OFFLINE_UPLOAD_RESERVED_STATES,
    OFFLINE_UPLOAD_STATE_VALUES,
    OFFLINE_UPLOAD_STATES,
    OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES,
    OFFLINE_UPLOAD_VALIDATABLE_STATES,
    OFFLINE_UPLOAD_WRITEABLE_FORMATS,
)
from krtour.map.infra.models import OfflineUploadRow

pytestmark = pytest.mark.unit


def test_offline_upload_state_sets_are_single_source_contract() -> None:
    assert OFFLINE_UPLOAD_STATE_VALUES == (
        "uploaded",
        "validating",
        "validated",
        "validation_failed",
        "loading",
        "loaded",
        "load_failed",
        "cancelled",
    )
    assert set(OFFLINE_UPLOAD_STATE_VALUES) == OFFLINE_UPLOAD_STATES
    assert {
        "uploaded",
        "validating",
        "validated",
        "validation_failed",
        "loading",
        "loaded",
        "load_failed",
        "cancelled",
    } == OFFLINE_UPLOAD_STATES
    assert {
        "uploaded",
        "validated",
        "load_failed",
    } == OFFLINE_UPLOAD_LOADABLE_STATES
    assert {
        "uploaded",
        "validated",
        "validation_failed",
        "load_failed",
    } == OFFLINE_UPLOAD_VALIDATABLE_STATES
    assert {"validated", "load_failed"} == OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES
    assert {"cancelled"} == OFFLINE_UPLOAD_RESERVED_STATES
    assert {"validating", "loading"} == OFFLINE_UPLOAD_IN_PROGRESS_STATES
    assert {
        "uploaded",
        "validated",
        "validation_failed",
        "loaded",
        "load_failed",
        "cancelled",
    } == OFFLINE_UPLOAD_DELETABLE_STATES
    assert OFFLINE_UPLOAD_DELETABLE_STATES.isdisjoint(OFFLINE_UPLOAD_IN_PROGRESS_STATES)
    assert (
        OFFLINE_UPLOAD_DELETABLE_STATES | OFFLINE_UPLOAD_IN_PROGRESS_STATES
        == OFFLINE_UPLOAD_STATES
    )
    assert {"json", "jsonl", "csv", "tsv"} == OFFLINE_UPLOAD_WRITEABLE_FORMATS


def test_offline_upload_orm_status_check_uses_core_contract() -> None:
    status_checks = [
        str(constraint.sqltext)
        for constraint in OfflineUploadRow.__table__.constraints
        if isinstance(constraint, CheckConstraint) and "status IN" in str(constraint.sqltext)
    ]

    assert len(status_checks) == 1
    status_check = status_checks[0]
    for state in OFFLINE_UPLOAD_STATE_VALUES:
        assert f"'{state}'" in status_check


def test_offline_upload_orm_checksum_idempotency_constraint_matches_migration() -> None:
    constraints = [
        constraint
        for constraint in OfflineUploadRow.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_offline_uploads_provider_dataset_scope_checksum"
    ]

    assert len(constraints) == 1
    assert [column.name for column in constraints[0].columns] == [
        "provider",
        "dataset_key",
        "sync_scope",
        "checksum_sha256",
    ]

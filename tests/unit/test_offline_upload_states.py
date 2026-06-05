"""Offline upload 상태 계약 단위 테스트."""

from __future__ import annotations

import pytest

from krtour.map.core.offline_upload_states import (
    OFFLINE_UPLOAD_LOADABLE_STATES,
    OFFLINE_UPLOAD_RESERVED_STATES,
    OFFLINE_UPLOAD_STATES,
    OFFLINE_UPLOAD_TABULAR_LOADABLE_STATES,
    OFFLINE_UPLOAD_VALIDATABLE_STATES,
    OFFLINE_UPLOAD_WRITEABLE_FORMATS,
)

pytestmark = pytest.mark.unit


def test_offline_upload_state_sets_are_single_source_contract() -> None:
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
    assert {"json", "jsonl", "csv", "tsv"} == OFFLINE_UPLOAD_WRITEABLE_FORMATS

"""provider entity key와 observation history cursor 단위 검증."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from kortravelmap.infra.feature_repo import _make_source_entity_key
from kortravelmap.infra.observation_repo import (
    FeatureObservation,
    _decode_history_cursor,
    _encode_history_cursor,
)

_NOW = datetime(2026, 7, 13, 1, 2, 3, tzinfo=UTC)


def _observation() -> FeatureObservation:
    return FeatureObservation(
        feature_id="feature-1",
        source_entity_key="se_entity-1",
        provider="python-mcst-api",
        dataset_key="tourism",
        source_entity_type="place",
        source_entity_id="entity-1",
        first_seen_at=_NOW,
        entity_last_seen_at=_NOW,
        source_record_key="sr_record-1",
        raw_data={"edition": "2025"},
        raw_payload_hash="payload-1",
        fetched_at=_NOW,
        imported_at=_NOW,
        observed_at=_NOW,
        expires_at=None,
        source_role="primary",
        match_method="natural_key",
        confidence=100,
        linked_at=_NOW,
        is_current=True,
    )


def test_source_entity_key_is_full_sha256_of_identity() -> None:
    raw = "python-mcst-api|tourism|place|entity-1"
    expected = "se_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    assert (
        _make_source_entity_key(
            provider="python-mcst-api",
            dataset_key="tourism",
            source_entity_type="place",
            source_entity_id="entity-1",
        )
        == expected
    )


def test_observation_history_cursor_roundtrip_and_scope_guard() -> None:
    item = _observation()
    cursor = _encode_history_cursor(item)

    assert _decode_history_cursor(
        cursor,
        feature_id=item.feature_id,
        source_entity_key=item.source_entity_key,
    ) == {
        "cursor_fetched_at": _NOW,
        "cursor_imported_at": _NOW,
        "cursor_source_record_key": item.source_record_key,
    }

    with pytest.raises(ValueError, match="invalid observation history cursor"):
        _decode_history_cursor(
            cursor,
            feature_id="different-feature",
            source_entity_key=item.source_entity_key,
        )


def test_observation_history_cursor_rejects_malformed_value() -> None:
    with pytest.raises(ValueError, match="invalid observation history cursor"):
        _decode_history_cursor(
            "not-base64",
            feature_id="feature-1",
            source_entity_key="se-1",
        )

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from kortravelmap.core.cache_target_stream import (
    SnapshotMerkleRowV1,
    cache_target_source_fingerprint,
    canonical_cache_target_source_bytes,
    make_active_cache_target_source,
    make_deleted_cache_target_source,
    snapshot_leaf_digest,
    snapshot_merkle_root,
)

_GOLDEN_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "cache-target-source-v1-golden.json"
)


def _golden() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_GOLDEN_PATH.read_text(encoding="utf-8")))


def test_source_vectors_match_canonical_bytes_and_fingerprints() -> None:
    vectors = _golden()["source_vectors"]
    for vector in vectors:
        if vector["name"] == "deleted":
            source = make_deleted_cache_target_source()
        else:
            source = make_active_cache_target_source(**vector["input"])
            assert source.lon_e6 == vector["normalized"]["lon_e6"]
            assert source.lat_e6 == vector["normalized"]["lat_e6"]
            assert source.radius_m == vector["normalized"]["radius_m"]
        assert canonical_cache_target_source_bytes(source).decode("utf-8") == vector[
            "canonical_utf8"
        ]
        assert cache_target_source_fingerprint(source) == vector["sha256"]


def test_source_normalization_rejects_floats_and_out_of_range_values() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        make_active_cache_target_source(
            lon=126.9,  # type: ignore[arg-type]
            lat="37.5",
            radius_km="5",
            update_enabled=True,
        )
    with pytest.raises(ValueError, match="lon"):
        make_active_cache_target_source(
            lon="180.000001",
            lat="37.5",
            radius_km="5",
            update_enabled=True,
        )
    with pytest.raises(ValueError, match="metre"):
        make_active_cache_target_source(
            lon="126.9",
            lat="37.5",
            radius_km="0.0004",
            update_enabled=True,
        )


def test_merkle_vectors_match_leaf_empty_and_odd_promotion_roots() -> None:
    vector = _golden()["merkle_v1"]
    rows = [
        SnapshotMerkleRowV1(
            external_system=row["external_system"],
            target_key=row["target_key"],
            state=row["state"],
            source_generation=row["source_generation"],
            source_payload_fingerprint=row["source_payload_fingerprint"],
        )
        for row in vector["rows"]
    ]
    assert snapshot_merkle_root([]) == vector["empty_root"]
    assert [snapshot_leaf_digest(row).hex() for row in rows] == [
        row["leaf_sha256"] for row in vector["rows"]
    ]
    assert snapshot_merkle_root(rows) == vector["root"]
    assert snapshot_merkle_root(list(reversed(rows))) == vector["root"]


def test_merkle_rejects_nfc_equivalent_duplicate_identity() -> None:
    fingerprint = _golden()["source_vectors"][2]["sha256"]
    rows = [
        SnapshotMerkleRowV1("pinvi", "é", "deleted", 1, fingerprint),
        SnapshotMerkleRowV1("pinvi", "e\u0301", "deleted", 2, fingerprint),
    ]
    with pytest.raises(ValueError, match="중복"):
        snapshot_merkle_root(rows)

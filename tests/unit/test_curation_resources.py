"""저장소에 배포하는 공식 큐레이션 CSV와 manifest 계약 검증."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import pytest

from kortravelmap.curation_import import CURATION_CSV_HEADERS, parse_curation_csv

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_RESOURCE_DIR = _ROOT / "resources" / "curations"


def test_curation_resource_manifest_and_csv_contract() -> None:
    manifest = json.loads((_RESOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 3
    assert manifest["encoding"] == "UTF-8"
    assert manifest["delimiter"] == ","
    assert manifest["csv_columns"] == list(CURATION_CSV_HEADERS)
    assert "source_provenance_json" in CURATION_CSV_HEADERS

    for entry in manifest["files"]:
        path = _RESOURCE_DIR / entry["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        if entry["kind"] not in {"official_seed", "upload_template"}:
            continue

        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            assert tuple(reader.fieldnames or ()) == CURATION_CSV_HEADERS
            rows = list(reader)
        assert len(rows) == entry["expected_rows"]

        parsed = parse_curation_csv(path.read_bytes())
        assert parsed.has_errors is False
        assert parsed.rows_total == entry["expected_rows"]
        if entry["kind"] == "upload_template":
            assert rows == []
            continue

        identities = [
            (
                row["collection_key"],
                row["source_item_key"],
                row["source_component_key"],
            )
            for row in rows
        ]
        assert len(identities) == len(set(identities))
        assert len({identity[:2] for identity in identities}) == entry["official_items"]
        assert sum(bool(row["feature_id"]) for row in rows) == entry["linked_rows"]
        assert sum(not row["feature_id"] for row in rows) == entry["unresolved_rows"]

        components_by_item: dict[tuple[str, str], list[str]] = defaultdict(list)
        for row in rows:
            assert row["source_component_key"] == row["source_component_key"].strip()
            components_by_item[
                (row["collection_key"], row["source_item_key"])
            ].append(row["source_component_key"])
        for components in components_by_item.values():
            if len(components) == 1:
                assert components == ["primary"]
            else:
                assert components == [
                    f"component-{ordinal:02d}"
                    for ordinal in range(1, len(components) + 1)
                ]


def test_lighthouse_provenance_is_row_complete_and_manifest_bound() -> None:
    manifest = json.loads((_RESOURCE_DIR / "manifest.json").read_text(encoding="utf-8"))
    lighthouse = next(
        entry for entry in manifest["files"] if entry["path"] == "lighthouse-stamp-tour.csv"
    )
    provenance_path = _RESOURCE_DIR / lighthouse["provenance_path"]
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

    assert hashlib.sha256(provenance_path.read_bytes()).hexdigest() == lighthouse[
        "provenance_sha256"
    ]
    assert provenance["schema_version"] == 1
    assert provenance["source_csv_sha256"] == lighthouse["sha256"]
    assert len(provenance["rows"]) == lighthouse["expected_rows"] == 105

    with (_RESOURCE_DIR / lighthouse["path"]).open(
        encoding="utf-8", newline=""
    ) as stream:
        csv_rows = list(csv.DictReader(stream))
    csv_identities = [
        (
            row["collection_key"],
            row["source_item_key"],
            row["source_component_key"],
        )
        for row in csv_rows
    ]
    evidence_identities = [
        (
            row["collection_key"],
            row["source_item_key"],
            row["source_component_key"],
        )
        for row in provenance["rows"]
    ]
    assert evidence_identities == csv_identities

    for row in provenance["rows"]:
        assert row["source_type"]
        assert row["source_urls"]
        assert row["observed_at"].endswith(("+09:00", "Z"))
        assert row["returned_address"]
        assert row["normalized_address"]
        assert row["confidence"] in {"medium", "medium-high", "high"}
        assert row["derivation"] in {
            "vworld_direct",
            "vworld_probe",
            "vworld_forward",
            "vworld_direct_extra",
            "vworld_override",
            "document",
        }
        if row["derivation"] in {
            "vworld_direct",
            "vworld_probe",
            "vworld_direct_extra",
            "vworld_override",
        }:
            assert row["input_coordinate"] is not None
        if row["derivation"] == "vworld_probe":
            assert row["probe_coordinate"] is not None
            assert row["probe_offset_m"] > 0

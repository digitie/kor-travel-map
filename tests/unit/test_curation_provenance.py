"""큐레이션 행별 provenance sidecar의 strict 결박 계약."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from copy import deepcopy
from typing import Any

import pytest

from kortravelmap.curation_import import CURATION_CSV_HEADERS
from kortravelmap.curation_provenance import (
    CurationProvenanceError,
    parse_curation_provenance,
)

pytestmark = pytest.mark.unit


def _csv_content(*, source_item_key: str = "source-1") -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CURATION_CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    row = dict.fromkeys(CURATION_CSV_HEADERS, "")
    row.update(
        {
            "collection_key": "collection:2026",
            "theme_slug": "theme",
            "theme_name": "테마",
            "theme_group": "그룹",
            "title": "목록",
            "provider_dataset_id": "101",
            "source_name": "공식 원천",
            "source_item_key": source_item_key,
            "source_component_key": "primary",
            "place_name": "검증 장소",
        }
    )
    writer.writerow(row)
    return output.getvalue().encode()


def _payload(csv_content: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source_csv_sha256": hashlib.sha256(csv_content).hexdigest(),
        "rows": [
            {
                "collection_key": "collection:2026",
                "source_item_key": "source-1",
                "source_component_key": "primary",
                "source_type": "vworld_reverse_geocode",
                "derivation": "vworld_probe",
                "source_urls": ["https://api.vworld.kr/req/address"],
                "observed_at": "2026-07-31T09:21:15+09:00",
                "input_coordinate": {"lon": 129.36, "lat": 35.35},
                "probe_coordinate": {"lon": 129.361, "lat": 35.351},
                "resolved_coordinate": {"lon": 129.361, "lat": 35.351},
                "probe_offset_m": 100,
                "returned_address": [
                    {"kind": "parcel", "text": "울산광역시 울주군 서생면 대송리 1"}
                ],
                "normalized_address": "울산광역시 울주군 서생면 대송리",
                "confidence": "medium",
                "source_reference": "KHOA 좌표 → VWorld probe",
                "rationale": "직접 좌표가 해상이어서 100m 육지점을 사용했다.",
            }
        ],
    }


def _content(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode()


def test_parses_exact_csv_digest_and_ordered_identity() -> None:
    csv_content = _csv_content()
    parsed = parse_curation_provenance(
        csv_content=csv_content,
        provenance_content=_content(_payload(csv_content)),
    )
    assert parsed.rows[0].identity == ("collection:2026", "source-1", "primary")
    assert parsed.rows[0].probe_coordinate is not None


@pytest.mark.parametrize("mutation", ["digest", "identity", "unexpected_field"])
def test_rejects_digest_identity_and_schema_drift(mutation: str) -> None:
    csv_content = _csv_content()
    payload = _payload(csv_content)
    if mutation == "digest":
        payload["source_csv_sha256"] = "0" * 64
    elif mutation == "identity":
        payload["rows"][0]["source_item_key"] = "other"
    else:
        payload["rows"][0]["unreviewed_extension"] = True

    with pytest.raises(CurationProvenanceError):
        parse_curation_provenance(
            csv_content=csv_content,
            provenance_content=_content(payload),
        )


def test_rejects_probe_without_actual_probe_coordinate() -> None:
    csv_content = _csv_content()
    payload = deepcopy(_payload(csv_content))
    payload["rows"][0]["probe_coordinate"] = None

    with pytest.raises(CurationProvenanceError, match="probe 좌표"):
        parse_curation_provenance(
            csv_content=csv_content,
            provenance_content=_content(payload),
        )


def test_rejects_naive_observation_time_and_invalid_coordinates() -> None:
    csv_content = _csv_content()
    payload = _payload(csv_content)
    payload["rows"][0]["observed_at"] = "2026-07-31T09:21:15"
    payload["rows"][0]["input_coordinate"]["lat"] = 91

    with pytest.raises(CurationProvenanceError):
        parse_curation_provenance(
            csv_content=csv_content,
            provenance_content=_content(payload),
        )

#!/usr/bin/env python3
"""보존된 H31 조사 원자료를 등대 105행 provenance sidecar로 변환한다."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

_URL_PATTERN = re.compile(r"https?://[^\s|]+")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch-dir", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--observed-at",
        required=True,
        help="원자료 수집 시각(ISO-8601 timezone 필수)",
    )
    return parser.parse_args()


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _coordinate(*, lon: Any, lat: Any) -> dict[str, float]:
    return {"lon": float(lon), "lat": float(lat)}


def _response_addresses(response: dict[str, Any]) -> list[dict[str, str]]:
    payload = response["response"]
    if payload["status"] != "OK":
        raise ValueError(f"VWorld 응답이 성공이 아닙니다: {payload['status']!r}")
    if "result" in payload and isinstance(payload["result"], list):
        return [
            {"kind": str(item["type"]), "text": str(item["text"])}
            for item in payload["result"]
        ]
    refined = payload["refined"]
    return [{"kind": "refined", "text": str(refined["text"])}]


def _probe_point(
    raw_probe: list[dict[str, Any]],
    *,
    place_name: str,
) -> dict[str, float]:
    matches = [row for row in raw_probe if row["place_name"] == place_name]
    if len(matches) != 1 or matches[0]["probe"] is None:
        raise ValueError(f"{place_name}: probe 원자료를 유일하게 찾을 수 없습니다.")
    point = matches[0]["probe"]["resp"]["response"]["input"]["point"]
    return _coordinate(lon=point["x"], lat=point["y"])


def _urls(source_reference: str) -> list[str]:
    urls: list[str] = []
    dataset_urls = {
        "15130184": "https://www.data.go.kr/data/15130184/fileData.do",
        "15144073": "https://www.data.go.kr/data/15144073/fileData.do",
        "3081773": "https://www.data.go.kr/data/3081773/fileData.do",
    }
    for dataset_key, url in dataset_urls.items():
        if dataset_key in source_reference:
            urls.append(url)
    for match in _URL_PATTERN.findall(source_reference):
        url = match.rstrip("),.;")
        if url not in urls:
            urls.append(url)
    if not urls:
        raise ValueError("source URL이 없습니다.")
    return urls


def _returned_from_consolidated(
    consolidated: dict[str, Any],
    *,
    place_name: str,
) -> list[dict[str, str]]:
    item = consolidated[place_name]
    addresses = [
        {"kind": kind, "text": item[kind]}
        for kind in ("parcel", "road")
        if item.get(kind)
    ]
    if not addresses:
        raise ValueError(f"{place_name}: 반환 주소가 없습니다.")
    return addresses


def _row_provenance(
    evidence: dict[str, Any],
    csv_row: dict[str, str],
    *,
    observed_at: str,
    consolidated: dict[str, Any],
    raw_probe: list[dict[str, Any]],
    extra: dict[str, Any],
    override: dict[str, Any],
) -> dict[str, Any]:
    derivation = evidence["derivation"]
    place_name = evidence["place_name"]
    evidence_coord = evidence["evidence_coord_wgs84"]
    input_coordinate = (
        None
        if evidence_coord is None
        else _coordinate(lon=evidence_coord[1], lat=evidence_coord[0])
    )
    probe_coordinate = None
    resolved_coordinate = input_coordinate

    if derivation == "vworld_probe":
        returned_address = _returned_from_consolidated(
            consolidated, place_name=place_name
        )
        probe_coordinate = _probe_point(raw_probe, place_name=place_name)
        resolved_coordinate = probe_coordinate
        source_type = "vworld_reverse_geocode"
    elif derivation in {"vworld_direct", "vworld_direct_extra", "vworld_override"}:
        if derivation == "vworld_direct_extra":
            response = extra[place_name]["direct"]
        elif derivation == "vworld_override":
            response = override[place_name]["direct"]
        else:
            returned_address = _returned_from_consolidated(
                consolidated, place_name=place_name
            )
            response = None
        if response is not None:
            returned_address = _response_addresses(response)
        source_type = "vworld_reverse_geocode"
    elif derivation == "vworld_forward":
        response = extra[place_name]["fwd"]
        returned_address = _response_addresses(response)
        point = response["response"]["result"]["point"]
        resolved_coordinate = _coordinate(lon=point["x"], lat=point["y"])
        source_type = "vworld_forward_geocode"
    elif derivation == "document":
        returned_address = [
            {
                "kind": "official_document",
                "text": evidence["address_official_document"] or evidence["address"],
            }
        ]
        resolved_coordinate = None
        source_type = "official_document"
    else:
        raise ValueError(f"{place_name}: 알 수 없는 derivation {derivation!r}")

    if csv_row["address_hint"] != evidence["address_hint_written"]:
        raise ValueError(f"{place_name}: CSV address_hint와 evidence가 다릅니다.")
    return {
        "collection_key": csv_row["collection_key"],
        "source_item_key": csv_row["source_item_key"],
        "source_component_key": csv_row["source_component_key"],
        "source_type": source_type,
        "derivation": derivation,
        "source_urls": _urls(evidence["source"]),
        "observed_at": observed_at,
        "input_coordinate": input_coordinate,
        "probe_coordinate": probe_coordinate,
        "resolved_coordinate": resolved_coordinate,
        "probe_offset_m": evidence["probe_offset_m"],
        "returned_address": returned_address,
        "normalized_address": evidence["address_hint_written"],
        "confidence": evidence["confidence"],
        "source_reference": evidence["source"],
        "rationale": evidence["note"],
    }


def main() -> None:
    args = _args()
    csv_content = args.csv.read_bytes()
    with args.csv.open(encoding="utf-8", newline="") as stream:
        csv_rows = list(csv.DictReader(stream))
    scratch = args.scratch_dir
    evidence_rows = _read_json(scratch / "address-evidence.json")
    consolidated = _read_json(scratch / "_geo_consolidated.json")
    raw_probe = _read_json(scratch / "_vworld_probe.json")
    extra = _read_json(scratch / "_extra9.json")
    override = _read_json(scratch / "_fix2.json")

    if len(csv_rows) != len(evidence_rows) or len(csv_rows) != 105:
        raise ValueError("CSV와 evidence는 모두 정확히 105행이어야 합니다.")
    rows: list[dict[str, Any]] = []
    for index, (csv_row, evidence) in enumerate(zip(csv_rows, evidence_rows, strict=True)):
        if evidence["row_line"] != index + 2:
            raise ValueError(f"evidence row_line 순서가 다릅니다: index={index}")
        if (
            csv_row["source_item_key"] != evidence["source_item_key"]
            or csv_row["place_name"] != evidence["place_name"]
        ):
            raise ValueError(f"CSV/evidence identity가 다릅니다: index={index}")
        rows.append(
            _row_provenance(
                evidence,
                csv_row,
                observed_at=args.observed_at,
                consolidated=consolidated,
                raw_probe=raw_probe,
                extra=extra,
                override=override,
            )
        )

    payload = {
        "schema_version": 1,
        "source_csv_sha256": hashlib.sha256(csv_content).hexdigest(),
        "rows": rows,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    args.output.write_text(serialized + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()

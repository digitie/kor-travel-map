"""큐레이션 CSV와 분리한 행별 source provenance 검증 계약."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, cast
from urllib.parse import urlparse

from kortravelmap.curation_import import parse_curation_csv

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from kortravelmap.curation_import import CurationImportRow

CURATION_PROVENANCE_MAX_BYTES: Final = 4 * 1024 * 1024
CURATION_PROVENANCE_SCHEMA_VERSION: Final = 1
LIGHTHOUSE_COLLECTION_PREFIX: Final = "lighthouse-stamp-tour:"
LIGHTHOUSE_DATASET_PREFIX: Final = "lighthouse-stamp-tour-season-"

Derivation = Literal[
    "vworld_direct",
    "vworld_probe",
    "vworld_forward",
    "vworld_direct_extra",
    "vworld_override",
    "document",
]
Confidence = Literal["medium", "medium-high", "high"]

_DERIVATIONS: Final[frozenset[str]] = frozenset(
    {
        "vworld_direct",
        "vworld_probe",
        "vworld_forward",
        "vworld_direct_extra",
        "vworld_override",
        "document",
    }
)
_CONFIDENCES: Final[frozenset[str]] = frozenset({"medium", "medium-high", "high"})
_SOURCE_TYPES: Final[frozenset[str]] = frozenset(
    {"vworld_reverse_geocode", "vworld_forward_geocode", "official_document"}
)


class CurationProvenanceError(ValueError):
    """행별 provenance가 CSV 또는 구조 계약과 맞지 않을 때 발생한다."""


@dataclass(frozen=True)
class ProvenanceCoordinate:
    """WGS84 경도·위도."""

    lon: float
    lat: float


@dataclass(frozen=True)
class ReturnedAddress:
    """외부 source가 반환하거나 공식 문서가 적시한 원 주소."""

    kind: str
    text: str


@dataclass(frozen=True)
class CurationRowProvenance:
    """CSV source component 한 행의 재검증 가능한 provenance."""

    collection_key: str
    source_item_key: str
    source_component_key: str
    source_type: str
    derivation: Derivation
    source_urls: tuple[str, ...]
    observed_at: datetime
    input_coordinate: ProvenanceCoordinate | None
    probe_coordinate: ProvenanceCoordinate | None
    resolved_coordinate: ProvenanceCoordinate | None
    probe_offset_m: int
    returned_address: tuple[ReturnedAddress, ...]
    normalized_address: str
    confidence: Confidence
    source_reference: str
    rationale: str

    @property
    def identity(self) -> tuple[str, str, str]:
        """CSV와 결박하는 안정 identity."""

        return (
            self.collection_key,
            self.source_item_key,
            self.source_component_key,
        )


@dataclass(frozen=True)
class CurationProvenance:
    """검증을 마친 sidecar 전체."""

    source_csv_sha256: str
    rows: tuple[CurationRowProvenance, ...]


def requires_lighthouse_provenance(
    rows: Sequence[CurationImportRow],
    *,
    lighthouse_provider_dataset_ids: Collection[int] = (),
) -> bool:
    """저장소 공식 등대 seed이면 sidecar를 반드시 요구한다.

    CSV에는 provider/dataset 자연키를 허용하지 않는다. 호출자는 catalog에서 확인한
    canonical dataset ID만 이 순수 검증기에 전달한다.
    """

    lighthouse_ids = frozenset(lighthouse_provider_dataset_ids)
    return any(
        row.collection_key.startswith(LIGHTHOUSE_COLLECTION_PREFIX)
        or row.provider_dataset_id in lighthouse_ids
        for row in rows
    )


def provenance_row_payload(
    provenance: CurationProvenance,
    row: CurationRowProvenance,
) -> dict[str, Any]:
    """검증된 sidecar row를 CSV digest와 함께 JSON 저장 형태로 바꾼다."""

    return {
        "schema_version": CURATION_PROVENANCE_SCHEMA_VERSION,
        "source_csv_sha256": provenance.source_csv_sha256,
        "row": {
            "collection_key": row.collection_key,
            "source_item_key": row.source_item_key,
            "source_component_key": row.source_component_key,
            "source_type": row.source_type,
            "derivation": row.derivation,
            "source_urls": list(row.source_urls),
            "observed_at": row.observed_at.isoformat(),
            "input_coordinate": _coordinate_payload(row.input_coordinate),
            "probe_coordinate": _coordinate_payload(row.probe_coordinate),
            "resolved_coordinate": _coordinate_payload(row.resolved_coordinate),
            "probe_offset_m": row.probe_offset_m,
            "returned_address": [
                {"kind": address.kind, "text": address.text}
                for address in row.returned_address
            ],
            "normalized_address": row.normalized_address,
            "confidence": row.confidence,
            "source_reference": row.source_reference,
            "rationale": row.rationale,
        },
    }


def _coordinate_payload(
    coordinate: ProvenanceCoordinate | None,
) -> dict[str, float] | None:
    if coordinate is None:
        return None
    return {"lon": coordinate.lon, "lat": coordinate.lat}


def parse_curation_provenance(
    *,
    csv_content: bytes,
    provenance_content: bytes,
) -> CurationProvenance:
    """sidecar를 strict하게 읽고 exact CSV digest·ordered identity와 결박한다."""

    if len(provenance_content) > CURATION_PROVENANCE_MAX_BYTES:
        raise CurationProvenanceError(
            f"provenance 파일은 {CURATION_PROVENANCE_MAX_BYTES} bytes 이하여야 합니다."
        )
    preview = parse_curation_csv(csv_content)
    if preview.has_errors:
        raise CurationProvenanceError("provenance에 결박할 CSV가 유효하지 않습니다.")

    try:
        raw = json.loads(provenance_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurationProvenanceError("provenance는 UTF-8 JSON 객체여야 합니다.") from exc
    root = _mapping(raw, path="$")
    _exact_keys(root, {"schema_version", "source_csv_sha256", "rows"}, path="$")
    if root["schema_version"] != CURATION_PROVENANCE_SCHEMA_VERSION:
        raise CurationProvenanceError(
            f"지원하지 않는 provenance schema_version입니다: {root['schema_version']!r}"
        )

    expected_digest = hashlib.sha256(csv_content).hexdigest()
    source_csv_sha256 = _nonempty_string(root["source_csv_sha256"], path="$.source_csv_sha256")
    if source_csv_sha256 != expected_digest:
        raise CurationProvenanceError("provenance source_csv_sha256가 CSV와 일치하지 않습니다.")

    raw_rows = root["rows"]
    if not isinstance(raw_rows, list):
        raise CurationProvenanceError("$.rows는 배열이어야 합니다.")
    rows = tuple(_parse_row(value, index=index) for index, value in enumerate(raw_rows))
    expected_identities = tuple(
        (row.collection_key, row.source_item_key, row.source_component_key)
        for row in preview.rows
    )
    identities = tuple(row.identity for row in rows)
    if identities != expected_identities:
        raise CurationProvenanceError(
            "provenance rows의 수·순서·identity가 CSV와 일치하지 않습니다."
        )
    if len(identities) != len(set(identities)):
        raise CurationProvenanceError("provenance row identity가 중복됐습니다.")
    return CurationProvenance(source_csv_sha256=source_csv_sha256, rows=rows)


def _parse_row(value: object, *, index: int) -> CurationRowProvenance:
    path = f"$.rows[{index}]"
    row = _mapping(value, path=path)
    _exact_keys(
        row,
        {
            "collection_key",
            "source_item_key",
            "source_component_key",
            "source_type",
            "derivation",
            "source_urls",
            "observed_at",
            "input_coordinate",
            "probe_coordinate",
            "resolved_coordinate",
            "probe_offset_m",
            "returned_address",
            "normalized_address",
            "confidence",
            "source_reference",
            "rationale",
        },
        path=path,
    )
    source_type = _enum_string(row["source_type"], _SOURCE_TYPES, path=f"{path}.source_type")
    derivation_value = _enum_string(row["derivation"], _DERIVATIONS, path=f"{path}.derivation")
    derivation = cast("Derivation", derivation_value)
    confidence = cast(
        "Confidence",
        _enum_string(row["confidence"], _CONFIDENCES, path=f"{path}.confidence"),
    )
    source_urls = _source_urls(row["source_urls"], path=f"{path}.source_urls")
    observed_at = _aware_datetime(row["observed_at"], path=f"{path}.observed_at")
    input_coordinate = _coordinate(row["input_coordinate"], path=f"{path}.input_coordinate")
    probe_coordinate = _coordinate(row["probe_coordinate"], path=f"{path}.probe_coordinate")
    resolved_coordinate = _coordinate(
        row["resolved_coordinate"], path=f"{path}.resolved_coordinate"
    )
    probe_offset_m = row["probe_offset_m"]
    if (
        not isinstance(probe_offset_m, int)
        or isinstance(probe_offset_m, bool)
        or probe_offset_m < 0
        or probe_offset_m > 100_000
    ):
        raise CurationProvenanceError(f"{path}.probe_offset_m가 범위를 벗어났습니다.")
    returned_address = _returned_addresses(
        row["returned_address"], path=f"{path}.returned_address"
    )

    if derivation == "vworld_probe":
        if input_coordinate is None or probe_coordinate is None or probe_offset_m == 0:
            raise CurationProvenanceError(
                f"{path}: vworld_probe는 입력·probe 좌표와 양수 offset이 필요합니다."
            )
        if resolved_coordinate != probe_coordinate:
            raise CurationProvenanceError(
                f"{path}: vworld_probe 결과 좌표는 실제 probe 좌표여야 합니다."
            )
    elif probe_coordinate is not None or probe_offset_m != 0:
        raise CurationProvenanceError(
            f"{path}: probe가 아닌 derivation에는 probe 좌표·offset을 둘 수 없습니다."
        )
    if derivation in {
        "vworld_direct",
        "vworld_direct_extra",
        "vworld_override",
    }:
        if input_coordinate is None:
            raise CurationProvenanceError(f"{path}: 역지오코딩 입력 좌표가 없습니다.")
        if resolved_coordinate != input_coordinate:
            raise CurationProvenanceError(
                f"{path}: 직접 역지오코딩 결과 좌표는 입력 좌표여야 합니다."
            )
    expected_source_type = (
        "official_document"
        if derivation == "document"
        else (
            "vworld_forward_geocode"
            if derivation == "vworld_forward"
            else "vworld_reverse_geocode"
        )
    )
    if source_type != expected_source_type:
        raise CurationProvenanceError(f"{path}: derivation과 source_type이 맞지 않습니다.")
    if derivation == "vworld_forward" and (
        input_coordinate is not None or resolved_coordinate is None
    ):
        raise CurationProvenanceError(
            f"{path}: forward는 좌표 입력 없이 결과 좌표를 보존해야 합니다."
        )
    if derivation == "document" and any(
        coordinate is not None
        for coordinate in (input_coordinate, probe_coordinate, resolved_coordinate)
    ):
        raise CurationProvenanceError(
            f"{path}: 좌표 없는 문서 근거에 좌표를 합성할 수 없습니다."
        )

    return CurationRowProvenance(
        collection_key=_nonempty_string(row["collection_key"], path=f"{path}.collection_key"),
        source_item_key=_nonempty_string(row["source_item_key"], path=f"{path}.source_item_key"),
        source_component_key=_nonempty_string(
            row["source_component_key"], path=f"{path}.source_component_key"
        ),
        source_type=source_type,
        derivation=derivation,
        source_urls=source_urls,
        observed_at=observed_at,
        input_coordinate=input_coordinate,
        probe_coordinate=probe_coordinate,
        resolved_coordinate=resolved_coordinate,
        probe_offset_m=probe_offset_m,
        returned_address=returned_address,
        normalized_address=_nonempty_string(
            row["normalized_address"], path=f"{path}.normalized_address"
        ),
        confidence=confidence,
        source_reference=_nonempty_string(
            row["source_reference"], path=f"{path}.source_reference"
        ),
        rationale=_nonempty_string(row["rationale"], path=f"{path}.rationale"),
    )


def _mapping(value: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise CurationProvenanceError(f"{path}는 JSON 객체여야 합니다.")
    return cast("Mapping[str, Any]", value)


def _exact_keys(value: Mapping[str, Any], expected: set[str], *, path: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise CurationProvenanceError(
            f"{path} field가 맞지 않습니다: missing={missing}, unexpected={unexpected}"
        )


def _nonempty_string(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise CurationProvenanceError(f"{path}는 trim된 비어 있지 않은 문자열이어야 합니다.")
    return value


def _enum_string(value: object, allowed: frozenset[str], *, path: str) -> str:
    text = _nonempty_string(value, path=path)
    if text not in allowed:
        raise CurationProvenanceError(f"{path} 값이 허용 목록에 없습니다: {text!r}")
    return text


def _aware_datetime(value: object, *, path: str) -> datetime:
    text = _nonempty_string(value, path=path)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CurationProvenanceError(f"{path}는 ISO-8601 datetime이어야 합니다.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CurationProvenanceError(f"{path}에는 timezone offset이 필요합니다.")
    return parsed


def _coordinate(value: object, *, path: str) -> ProvenanceCoordinate | None:
    if value is None:
        return None
    coordinate = _mapping(value, path=path)
    _exact_keys(coordinate, {"lon", "lat"}, path=path)
    lon = coordinate["lon"]
    lat = coordinate["lat"]
    if (
        not isinstance(lon, (int, float))
        or isinstance(lon, bool)
        or not isinstance(lat, (int, float))
        or isinstance(lat, bool)
        or not -180 <= lon <= 180
        or not -90 <= lat <= 90
    ):
        raise CurationProvenanceError(f"{path} 좌표가 WGS84 범위를 벗어났습니다.")
    return ProvenanceCoordinate(lon=float(lon), lat=float(lat))


def _source_urls(value: object, *, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CurationProvenanceError(f"{path}는 비어 있지 않은 URL 배열이어야 합니다.")
    urls = tuple(
        _nonempty_string(url, path=f"{path}[{index}]") for index, url in enumerate(value)
    )
    if len(urls) != len(set(urls)):
        raise CurationProvenanceError(f"{path}에 중복 URL이 있습니다.")
    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise CurationProvenanceError(f"{path}에 유효하지 않은 HTTP URL이 있습니다.")
    return urls


def _returned_addresses(value: object, *, path: str) -> tuple[ReturnedAddress, ...]:
    if not isinstance(value, list) or not value:
        raise CurationProvenanceError(f"{path}는 비어 있지 않은 주소 배열이어야 합니다.")
    result: list[ReturnedAddress] = []
    for index, raw in enumerate(value):
        item_path = f"{path}[{index}]"
        item = _mapping(raw, path=item_path)
        _exact_keys(item, {"kind", "text"}, path=item_path)
        result.append(
            ReturnedAddress(
                kind=_nonempty_string(item["kind"], path=f"{item_path}.kind"),
                text=_nonempty_string(item["text"], path=f"{item_path}.text"),
            )
        )
    if len({(item.kind, item.text) for item in result}) != len(result):
        raise CurationProvenanceError(f"{path}에 중복 주소가 있습니다.")
    return tuple(result)

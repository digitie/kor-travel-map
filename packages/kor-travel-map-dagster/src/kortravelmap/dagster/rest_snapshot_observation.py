"""Rest 단일 current-export-window 관측을 보존한다. latest-batch/퇴역 권위는 없다."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Never

from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import (
    DecodedSnapshotArtifact,
    SnapshotArtifactPins,
)
from kortravelmap.infra.rest_area_snapshot_artifact import decode_rest_area_snapshot_artifact
from kortravelmap.infra.scoped_provider_refresh import _artifact_digest
from kortravelmap.providers.kor_travel_transport import TransportCollection

from .airport_snapshot_observation import (
    _bytes,
    _clock,
    _parse,
    _restore_stats,
    _run_ids,
    _stats_values,
)
from .validation import FeatureAddressValidationSummary, validate_feature_bundles_address

REST_EXPORT_BODY_LIMIT = 2 * 1024 * 1024
_EXPORT_DOMAIN = "transport-rest-current-export-window-v1"
_DOMAIN = "rest-area-snapshot-observation-v1"
_PATH = "/v1/service/exports/rest-areas"
_TOP_KEYS = frozenset(
    {
        "version",
        "domain",
        "artifact_sha256",
        "pins",
        "root_run_id",
        "observation_generation",
        "upstream_eof",
        "validation_mode",
        "dropped",
        "source_observations",
        "validation",
        "geo_stats",
        "export_window",
    }
)
_EXPORT_KEYS = frozenset(
    {
        "version",
        "domain",
        "path",
        "limit",
        "item_count",
        "has_more",
        "next_cursor",
        "collection",
        "body_bytes",
        "body_sha256",
        "captured_at",
    }
)


class UnsupportedRestObservation(ValueError):
    """원 관측과 artifact의 연결을 증명하지 못하면 새 등록 전에 거부한다."""


@dataclass(frozen=True)
class RestExportWindow:
    """성공한 단일 응답의 불변 metadata. raw hash는 압축 해제된 전체 본문의 SHA다."""

    item_count: int
    body_bytes: int
    body_sha256: str
    captured_at: datetime
    collection: TransportCollection


@dataclass(frozen=True)
class RestoredRestObservation:
    artifact: DecodedSnapshotArtifact
    artifact_sha256: str
    root_run_id: str
    observation_generation: str
    fetched_at: datetime
    source_observations: int
    validation: FeatureAddressValidationSummary
    geo_stats: GeoCallStats | None
    export_window: RestExportWindow
    upstream_eof: bool = True
    validation_mode: str = "strict"
    dropped: int = 0


def _reject() -> Never:
    raise UnsupportedRestObservation("unsupported or inconsistent rest observation context")


def export_window_value(window: RestExportWindow) -> dict[str, Any]:
    """외부 serializer/hook을 호출하기 전에 정확한 typed metadata만 허용한다."""
    if type(window) is not RestExportWindow or type(window.collection) is not TransportCollection:
        _reject()
    collection = window.collection
    if (
        type(window.item_count) is not int
        or not 1 <= window.item_count <= 256
        or type(window.body_bytes) is not int
        or not 1 <= window.body_bytes <= REST_EXPORT_BODY_LIMIT
        or type(window.body_sha256) is not str
        or not re.fullmatch("[0-9a-f]{64}", window.body_sha256)
        or type(window.captured_at) is not datetime
        or type(collection.last_success_at) is not datetime
        or type(collection.source) is not str
        or collection.source != "krex_rest_area"
        or collection.failed is not False
        or collection.stale is not False
    ):
        _reject()
    # 알려진 정본 timezone만 받는다. naive/future clock을 새 EOF 근거로 쓰지 않는다.
    _clock(window.captured_at)
    _clock(collection.last_success_at)
    if (
        window.captured_at.utcoffset() is None
        or collection.last_success_at.utcoffset() is None
        or collection.last_success_at > window.captured_at
    ):
        _reject()
    return {
        "version": 1,
        "domain": _EXPORT_DOMAIN,
        "path": _PATH,
        "limit": 256,
        "item_count": window.item_count,
        "has_more": False,
        "next_cursor": None,
        "collection": {
            "source": collection.source,
            "last_success_at": collection.last_success_at.isoformat(),
            "failed": False,
            "stale": False,
        },
        "body_bytes": window.body_bytes,
        "body_sha256": window.body_sha256,
        "captured_at": window.captured_at.isoformat(),
    }


def _window_from_wire(value: Any, first: datetime) -> RestExportWindow:
    if type(value) is not dict or set(value) != _EXPORT_KEYS:
        _reject()
    collection = value["collection"]
    if type(collection) is not dict or set(collection) != {
        "source",
        "last_success_at",
        "failed",
        "stale",
    }:
        _reject()
    if type(collection["last_success_at"]) is not str:
        _reject()
    result = RestExportWindow(
        value["item_count"],
        value["body_bytes"],
        value["body_sha256"],
        first,
        TransportCollection(
            collection["source"],
            datetime.fromisoformat(collection["last_success_at"]),
            collection["failed"],
            collection["stale"],
        ),
    )
    if _bytes(export_window_value(result)) != _bytes(value):
        _reject()
    return result


def _validation(
    artifact: DecodedSnapshotArtifact,
) -> tuple[FeatureAddressValidationSummary, dict[str, Any]]:
    summary = validate_feature_bundles_address(artifact.bundles)
    if summary.error_count != 0 or summary.total != len(artifact.bundles):
        _reject()
    projection = {
        "total": summary.total,
        "issue_count": summary.issue_count,
        "error_count": summary.error_count,
        "warning_count": summary.warning_count,
        "evidence_grade_counts": summary.evidence_grade_counts,
        "name_state_counts": summary.name_state_counts,
        "issues": [
            {
                "feature_id": i.feature_id,
                "source_record_key": i.source_record_key,
                "code": i.code,
                "severity": i.severity,
                "message": i.message,
                "provider_address": i.provider_address,
                "bjd_code": i.bjd_code,
                "sigungu_code": i.sigungu_code,
            }
            for i in summary.issues
        ],
    }
    return summary, {
        "total": summary.total,
        "issue_count": summary.issue_count,
        "error_count": summary.error_count,
        "warning_count": summary.warning_count,
        "full_summary_sha256": _artifact_digest(["rest-validation-full-v1", projection]),
    }


def _build(
    artifact_bytes: bytes,
    pins: SnapshotArtifactPins,
    root: str,
    generation: str,
    eof: bool,
    stats: GeoCallStats | None,
    window: RestExportWindow,
) -> tuple[dict[str, Any], RestoredRestObservation]:
    _run_ids(root, generation)
    if eof is not True:
        _reject()
    artifact = decode_rest_area_snapshot_artifact(artifact_bytes, expected_pins=pins)
    first = artifact.bundles[0].source_record.fetched_at
    signature = _clock(first)
    if any(_clock(b.source_record.fetched_at) != signature for b in artifact.bundles):
        _reject()
    export = export_window_value(window)
    if window.item_count != len(artifact.bundles) or _clock(window.captured_at) != signature:
        _reject()
    stats_values = _stats_values(stats, artifact.geo)
    validation, validation_values = _validation(artifact)
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    value = {
        "version": 1,
        "domain": _DOMAIN,
        "artifact_sha256": digest,
        "pins": {k: getattr(pins, k) for k in SnapshotArtifactPins.__dataclass_fields__},
        "root_run_id": root,
        "observation_generation": generation,
        "upstream_eof": True,
        "validation_mode": "strict",
        "dropped": 0,
        "source_observations": len(artifact.bundles),
        "validation": validation_values,
        "geo_stats": stats_values,
        "export_window": export,
    }
    return value, RestoredRestObservation(
        artifact,
        digest,
        root,
        generation,
        first,
        len(artifact.bundles),
        validation,
        _restore_stats(stats_values),
        window,
    )


def encode_rest_observation_context(
    artifact_bytes: bytes,
    *,
    pins: SnapshotArtifactPins,
    root_run_id: str,
    observation_generation: str,
    upstream_eof: bool,
    geo_stats: GeoCallStats | None,
    export_window: RestExportWindow,
) -> bytes:
    """HTTP/clock/Geo를 재취득하지 않고 원 current-window proof만 보존한다."""
    try:
        value, _ = _build(
            artifact_bytes,
            pins,
            root_run_id,
            observation_generation,
            upstream_eof,
            geo_stats,
            export_window,
        )
        raw = _bytes(value)
        _parse(raw)
        return raw
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, AttributeError) as exc:
        raise UnsupportedRestObservation("unsupported rest observation context") from exc


def decode_rest_observation_context(
    raw: bytes,
    artifact_bytes: bytes,
    *,
    expected_pins: SnapshotArtifactPins,
    expected_root_run_id: str,
) -> RestoredRestObservation:
    """원 clock/전체 validation·GeoStats·window를 exact canonical wire로 복원한다."""
    try:
        value = _parse(raw)
        if (
            type(value) is not dict
            or set(value) != _TOP_KEYS
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["domain"] != _DOMAIN
            or type(value["root_run_id"]) is not str
            or type(expected_root_run_id) is not str
            or value["root_run_id"] != expected_root_run_id
        ):
            _reject()
        artifact = decode_rest_area_snapshot_artifact(artifact_bytes, expected_pins=expected_pins)
        window = _window_from_wire(
            value["export_window"], artifact.bundles[0].source_record.fetched_at
        )
        rebuilt, result = _build(
            artifact_bytes,
            expected_pins,
            expected_root_run_id,
            value["observation_generation"],
            value["upstream_eof"],
            _restore_stats(value["geo_stats"]),
            window,
        )
        if _bytes(rebuilt) != raw:
            _reject()
        return result
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, AttributeError) as exc:
        raise UnsupportedRestObservation("invalid rest observation context") from exc

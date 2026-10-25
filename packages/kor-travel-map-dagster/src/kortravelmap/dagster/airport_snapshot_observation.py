"""고정 공항 artifact의 원 관측 context. IO/실행·후속 완료 권위는 없다."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Any, Never
from zoneinfo import ZoneInfo

from kortravelmap.dto.geo_dataset import GeoLoadContext
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import (
    DecodedSnapshotArtifact,
    SnapshotArtifactPins,
    decode_provider_snapshot_artifact,
)
from kortravelmap.infra.scoped_provider_refresh import _artifact_digest

from .validation import FeatureAddressValidationSummary, validate_feature_bundles_address

_MAX_BYTES = 8192
_MAX_BIGINT = 2**63 - 1
_DOMAIN = "airport-snapshot-observation-v1"
_ENDPOINTS = frozenset({"reverse", "geocode", "dataset_version", "regions_within_radius"})
_EMPTY_ENDPOINTS = _ENDPOINTS | {"reverse_result"}
_REUSE = frozenset({"skipped", "geocoded", "fallback", "disabled", "lookup_failed"})
_STATS_FIELDS = frozenset({"calls", "failures", "empty", "reuse", "observed_data_tokens"})


class UnsupportedAirportObservation(ValueError):
    """새 수집 시계/성공을 발명하지 않고 preDML 중단한다."""


@dataclass(frozen=True)
class RestoredAirportObservation:
    """재현값만 반환한다. mutable DTO/Stats는 후속 caller가 독점 소유한다."""

    artifact: DecodedSnapshotArtifact
    artifact_sha256: str
    root_run_id: str
    observation_generation: str
    fetched_at: datetime
    source_observations: int
    validation: FeatureAddressValidationSummary
    geo_stats: GeoCallStats | None
    upstream_eof: bool = True
    validation_mode: str = "strict"
    dropped: int = 0


def _reject() -> Never:
    raise UnsupportedAirportObservation("unsupported or inconsistent airport observation context")


def _number(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_BIGINT:
        _reject()
    return value


def _run_ids(root: Any, generation: Any) -> None:
    for value, limit in ((root, 128), (generation, 160)):
        if (
            type(value) is not str
            or not value
            or len(value) > limit
            or value != value.strip()
            or any(not c.isprintable() for c in value)
            or len(value.encode("utf-8")) > limit
        ):
            _reject()
    if "::retry:" in root:
        _reject()
    if generation != root:
        if not generation.startswith(root + "::retry:"):
            _reject()
        suffix = generation[len(root) + len("::retry:") :]
        if not re.fullmatch(r"[1-9][0-9]{0,18}", suffix) or int(suffix) > _MAX_BIGINT:
            _reject()


def _counter(value: Any, keys: frozenset[str]) -> dict[str, int]:
    # 타입 검사보다 먼저 Counter.items/외부 key의 비교를 실행하지 않는다.
    if type(value) is not Counter or len(value) > len(keys):
        _reject()
    result = {}
    total = 0
    for key, count in dict.items(value):
        if type(key) is not str or key not in keys:
            _reject()
        result[key] = _number(count)
        total += count
    _number(total)
    return result


def _stats_values(stats: Any, geo: GeoLoadContext | None) -> dict[str, Any] | None:
    if stats is None:
        if geo is not None and geo.observed_data_tokens is not None:
            _reject()
        return None
    if type(stats) is not GeoCallStats:
        _reject()
    data = stats.__dict__
    if (
        type(data) is not dict
        or len(data) != len(_STATS_FIELDS)
        or any(type(key) is not str for key in data)
        or set(data) != _STATS_FIELDS
    ):
        _reject()
    result = {
        "calls": _counter(stats.calls, _ENDPOINTS),
        "failures": _counter(stats.failures, _ENDPOINTS),
        "empty": _counter(stats.empty, _EMPTY_ENDPOINTS),
        "reuse": _counter(stats.reuse, _REUSE),
    }
    tokens = stats.observed_data_tokens
    if type(tokens) is not set or len(tokens) > 32:
        _reject()
    for token in tokens:
        if (
            type(token) is not str
            or len(token) > 256
            or not re.fullmatch(r"dd1-[0-9a-f]{32}", token)
        ):
            _reject()
    if geo is None:
        if tokens:
            _reject()
    elif type(geo.observed_data_tokens) is not set or geo.observed_data_tokens != tokens:
        # 초기 context는 실제 Stats builtinset 연결만 지원한다. frozenset은 EX다.
        _reject()
    return {**result, "observed_data_tokens": sorted(tokens)}


def _restore_stats(value: Any) -> GeoCallStats | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != _STATS_FIELDS:
        _reject()
    for key in ("calls", "failures", "empty", "reuse"):
        if type(value[key]) is not dict:
            _reject()
    tokens = value["observed_data_tokens"]
    if (
        type(tokens) is not list
        or len(tokens) > 32
        or any(type(token) is not str for token in tokens)
        or len(set(tokens)) != len(tokens)
    ):
        _reject()
    return GeoCallStats(
        calls=Counter(value["calls"]),
        failures=Counter(value["failures"]),
        empty=Counter(value["empty"]),
        reuse=Counter(value["reuse"]),
        observed_data_tokens=set(tokens),
    )


def _clock(value: datetime) -> tuple[Any, ...]:
    zone = value.tzinfo
    if zone is UTC:
        identity: Any = ["UTC"]
    elif type(zone) is timezone:
        identity = ["fixed", zone.tzname(None)]
    elif type(zone) is ZoneInfo:
        identity = ["zoneinfo", zone.key]
    else:
        _reject()
    return value.isoformat(), value.fold, identity


def _validation(
    artifact: DecodedSnapshotArtifact,
) -> tuple[FeatureAddressValidationSummary, dict[str, Any]]:
    summary = validate_feature_bundles_address(artifact.bundles)
    if summary.error_count != 0 or summary.total != len(artifact.bundles):
        _reject()
    # as_metadata의 표본/절단 정책에 의존하지 않고 모든 정본 issue 필드를 묶는다.
    projection = {
        "total": summary.total,
        "issue_count": summary.issue_count,
        "error_count": summary.error_count,
        "warning_count": summary.warning_count,
        "evidence_grade_counts": summary.evidence_grade_counts,
        "name_state_counts": summary.name_state_counts,
        "issues": [
            {
                "feature_id": issue.feature_id,
                "source_record_key": issue.source_record_key,
                "code": issue.code,
                "severity": issue.severity,
                "message": issue.message,
                "provider_address": issue.provider_address,
                "bjd_code": issue.bjd_code,
                "sigungu_code": issue.sigungu_code,
            }
            for issue in summary.issues
        ],
    }
    return summary, {
        "total": summary.total,
        "issue_count": summary.issue_count,
        "error_count": summary.error_count,
        "warning_count": summary.warning_count,
        "full_summary_sha256": _artifact_digest(["airport-validation-full-v1", projection]),
    }


def _build(
    artifact_bytes: bytes,
    pins: SnapshotArtifactPins,
    root: str,
    generation: str,
    eof: bool,
    stats: GeoCallStats | None,
) -> tuple[dict[str, Any], RestoredAirportObservation]:
    _run_ids(root, generation)
    if eof is not True:
        _reject()
    artifact = decode_provider_snapshot_artifact(artifact_bytes, expected_pins=pins)
    first = artifact.bundles[0].source_record.fetched_at
    signature = _clock(first)
    if any(_clock(bundle.source_record.fetched_at) != signature for bundle in artifact.bundles):
        _reject()
    stats_values = _stats_values(stats, artifact.geo)
    validation, validation_values = _validation(artifact)
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    value = {
        "version": 1,
        "domain": _DOMAIN,
        "artifact_sha256": digest,
        "pins": {key: getattr(pins, key) for key in SnapshotArtifactPins.__dataclass_fields__},
        "root_run_id": root,
        "observation_generation": generation,
        "upstream_eof": True,
        "validation_mode": "strict",
        "dropped": 0,
        "source_observations": len(artifact.bundles),
        "validation": validation_values,
        "geo_stats": stats_values,
    }
    return value, RestoredAirportObservation(
        artifact,
        digest,
        root,
        generation,
        first,
        len(artifact.bundles),
        validation,
        _restore_stats(stats_values),
    )


def _bytes(value: Any) -> bytes:
    result = bytearray()
    for chunk in json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).iterencode(value):
        encoded = chunk.encode("utf-8")
        if len(result) + len(encoded) > _MAX_BYTES:
            _reject()
        result.extend(encoded)
    return bytes(result)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _parse(raw: bytes) -> Any:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
        _reject()
    value = raw.decode("utf-8", errors="strict")
    depth = nodes = 0
    quoted = escaped = token = False
    for char in value:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
            nodes += 1
            token = False
        elif char in "[{":
            depth += 1
            nodes += 1
            token = False
        elif char in "]}":
            depth -= 1
            token = False
        elif char in ",: \r\n\t":
            token = False
        elif not token:
            nodes += 1
            token = True
        if depth > 8 or nodes > 256:
            _reject()
    return json.loads(value, object_pairs_hook=_unique, parse_constant=lambda _: _reject())


def encode_airport_observation_context(
    artifact_bytes: bytes,
    *,
    pins: SnapshotArtifactPins,
    root_run_id: str,
    observation_generation: str,
    upstream_eof: bool,
    geo_stats: GeoCallStats | None,
) -> bytes:
    """caller의 EOF 관측을 기록한다. upstream 전체를 다시 확인하는 권한은 없다."""
    try:
        value, _ = _build(
            artifact_bytes, pins, root_run_id, observation_generation, upstream_eof, geo_stats
        )
        raw = _bytes(value)
        # encoding도 decode 지원 한도/완전 정규 형식으로 왕복되는 context만 반환한다.
        _parse(raw)
        return raw
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, AttributeError) as exc:
        raise UnsupportedAirportObservation("unsupported airport observation context") from exc


def decode_airport_observation_context(
    raw: bytes,
    artifact_bytes: bytes,
    *,
    expected_pins: SnapshotArtifactPins,
    expected_root_run_id: str,
) -> RestoredAirportObservation:
    """원 artifact/clock/순수 검증/계수만 복원하며 후속 완료를 추측하지 않는다."""
    try:
        value = _parse(raw)
        if (
            type(value) is not dict
            or set(value)
            != {
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
            }
            or type(value["version"]) is not int
            or value["version"] != 1
            or value["domain"] != _DOMAIN
            or type(value["root_run_id"]) is not str
            or type(expected_root_run_id) is not str
            or value["root_run_id"] != expected_root_run_id
        ):
            _reject()
        rebuilt, result = _build(
            artifact_bytes,
            expected_pins,
            expected_root_run_id,
            value["observation_generation"],
            value["upstream_eof"],
            _restore_stats(value["geo_stats"]),
        )
        if _bytes(rebuilt) != raw:
            _reject()
        return result
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError, AttributeError) as exc:
        raise UnsupportedAirportObservation("invalid airport observation context") from exc

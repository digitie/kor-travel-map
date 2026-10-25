"""같은 apply TX에 보관할 원래 적재 결과. 실행/복구 권한과 DB 저장은 별도다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from kortravelmap.infra.feature_repo import FeatureLoadResult

_MAX_BYTES = 4096
_MAX_BIGINT = 2**63 - 1
_COUNTERS = (
    "bundles_total",
    "features_inserted",
    "features_updated",
    "source_records_inserted",
    "source_links_inserted",
    "source_links_updated",
    "geo_stamps_written",
    "geo_stale_rewritten",
    "geo_stale_unchanged",
    "geo_empty_guarded",
    "geo_override_stale_findings",
    "geo_partial_kept",
)
_CAPTURE = ("curation_input_member_count", "curation_input_set_hash")
_DOMAIN = "provider-full-snapshot-apply-result-v1"


class InvalidSnapshotApplyResult(ValueError):
    """완전한 원래 결과가 아니므로 재적재/새 성공으로 바꾸지 않는다."""


@dataclass(frozen=True)
class SnapshotApplyResult:
    """원래 반환값만 복원한다. child/root/finding 완료를 뜻하지 않는다."""

    load: FeatureLoadResult
    retired: int


def _number(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_BIGINT:
        raise InvalidSnapshotApplyResult("result counter must be a nonnegative PG bigint")
    return value


def _values(load: FeatureLoadResult, retired: int) -> dict[str, Any]:
    if type(load) is not FeatureLoadResult:
        raise InvalidSnapshotApplyResult("canonical FeatureLoadResult required")
    values: dict[str, Any] = {key: _number(getattr(load, key)) for key in _COUNTERS}
    values[_CAPTURE[0]] = _number(load.curation_input_member_count)
    digest = load.curation_input_set_hash
    if type(digest) is not str or not re.fullmatch("[0-9a-f]{64}", digest):
        raise InvalidSnapshotApplyResult("full snapshot requires its causal input capture")
    values[_CAPTURE[1]] = digest
    return {"domain": _DOMAIN, "load": values, "retired": _number(retired), "version": 1}


def encode_snapshot_apply_result(load: FeatureLoadResult, *, retired: int) -> bytes:
    """전체14필드와 별도 retired를 보존한다. 이 bytes만으로 출처가 입증되지는 않는다."""
    raw = json.dumps(_values(load, retired), sort_keys=True, separators=(",", ":")).encode("ascii")
    if len(raw) > _MAX_BYTES:
        raise InvalidSnapshotApplyResult("apply result exceeds4096 bytes")
    return raw


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in pairs:
        if key in values:
            raise InvalidSnapshotApplyResult("duplicate result field")
        values[key] = value
    return values


def decode_snapshot_apply_result(raw: bytes) -> SnapshotApplyResult:
    """정본의 정확한 bytes만 받는다. 미래 enum/extra/부분 결과는 암묵 변환하지 않는다."""
    if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
        raise InvalidSnapshotApplyResult("bounded nonempty result bytes required")
    try:
        # 이 형식은 2층 object와 string/unsigned integer만 쓴다. JSON parser 전 깊이 제한.
        # 현재 고정 키/hex/domain에는 괄호가 없으므로 대괄호·추가 중괄호는 항상 미지원이다.
        if b"[" in raw or b"]" in raw or raw.count(b"{") != 2 or raw.count(b"}") != 2:
            raise InvalidSnapshotApplyResult("invalid result shape")
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_unique)
        if (
            type(value) is not dict
            or set(value) != {"domain", "version", "load", "retired"}
            or value["domain"] != _DOMAIN
            or type(value["version"]) is not int
            or value["version"] != 1
            or type(value["load"]) is not dict
            or set(value["load"]) != {*_COUNTERS, *_CAPTURE}
        ):
            raise InvalidSnapshotApplyResult("invalid result contract")
        load = FeatureLoadResult(**value["load"])
        retired = _number(value["retired"])
        if encode_snapshot_apply_result(load, retired=retired) != raw:
            raise InvalidSnapshotApplyResult("noncanonical apply result")
        return SnapshotApplyResult(load, retired)
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        raise InvalidSnapshotApplyResult("invalid full snapshot apply result") from exc

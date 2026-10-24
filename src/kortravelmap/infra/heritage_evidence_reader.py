"""Heritage 증거 reader의 제한된 입력 계약. collector/SH apply 권한은 발급하지 않는다."""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MAX_TARGETS: Final[int] = 2730
_MAX_INPUT_BYTES: Final[int] = 262_144
_ENTITY: Final[re.Pattern[str]] = re.compile(r"se_[0-9a-f]{64}")


class HeritageEvidenceIneligibility(StrEnum):
    """SQL이 명시적으로 반환할 수 있는 전체 요청의 알려진 부적격 사유."""

    SCOPE_UNSUPPORTED = "scope_unsupported"
    MISSING_SOURCE = "missing_source"
    UNSUPPORTED_MEMBERSHIP = "unsupported_membership"
    INACTIVE_FEATURE = "inactive_feature"
    POLICY_UNSUPPORTED = "policy_unsupported"
    LINEAGE_INCOMPLETE = "lineage_incomplete"
    MIXED_BASE_LINEAGE = "mixed_base_lineage"
    STORAGE_UNSUPPORTED = "storage_unsupported"
    SHAPE_UNSUPPORTED = "shape_unsupported"
    BUDGET_EXCEEDED = "budget_exceeded"
    RETIRE_REQUIRED = "retire_required"


@dataclass(frozen=True)
class HeritageEvidenceRequest:
    """사전 검증된 읽기 요청. 결과의 완결성은 SH 적격성/쓰기 권한과 다르다."""

    dataset_id: int
    entity_keys: tuple[str, ...]


def validate_heritage_evidence_request(
    dataset_id: int, entity_keys: Iterable[str]
) -> HeritageEvidenceRequest:
    """MAX+1까지만 소비하고 정본 key/중복/배열 전송 예산을 SQL 호출 전에 확인한다.

    Python은 caller가 이미 만든 객체나 PG wire 전체의 메모리를 제한하지 않는다.
    서버도 배열 datum 크기를 unnest/cardinality/문자열 처리 전에 별도로 확인해야 한다.
    """
    if type(dataset_id) is not int or not 1 <= dataset_id <= 9_223_372_036_854_775_807:
        raise ValueError("dataset id must be a positive PostgreSQL bigint")
    if isinstance(entity_keys, (str, bytes, bytearray)):
        raise ValueError("entity keys must be an iterable of canonical keys")
    collected: list[str] = []
    seen: set[str] = set()
    # 배열 header/차원과 원소별 datum header/정렬 여유를 보수적으로 포함한다.
    reserved_bytes = 64
    for key in entity_keys:
        if len(collected) >= _MAX_TARGETS:
            raise ValueError("heritage evidence request exceeds 2730 targets")
        if type(key) is not str or len(key) != 67 or _ENTITY.fullmatch(key) is None:
            raise ValueError("invalid canonical source entity key")
        if key in seen:
            raise ValueError("duplicate source entity key")
        reserved_bytes += 8 + len(key)
        if reserved_bytes > _MAX_INPUT_BYTES:
            raise ValueError("heritage evidence request exceeds input byte budget")
        collected.append(key)
        seen.add(key)
    if not collected:
        raise ValueError("heritage evidence request cannot be empty")
    return HeritageEvidenceRequest(dataset_id, tuple(collected))


@dataclass(frozen=True)
class HeritageEvidenceEnvelope:
    """동일 snapshot의 증거. 적격성/manifest/apply 권한을 뜻하지 않는다."""

    request: HeritageEvidenceRequest
    evidence_complete: bool
    reason: HeritageEvidenceIneligibility | None
    policy_epoch: int | None
    items: tuple[dict[str, object], ...]


def _bounded_response(value: object) -> None:
    """DB 응답의 정규 JSON tree를 복제 전에 제한해 순회한다."""
    count = 0
    encoded = 0
    stack = [(iter((value,)), 0)]
    while stack:
        iterator, depth = stack[-1]
        try:
            node = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        count += 1
        if count > 65_536 or depth > 64:
            raise ValueError("invalid heritage evidence tree budget")
        if type(node) is dict:
            encoded += 2 + 2 * max(0, len(node) - 1) + 2 * len(node)

            # items를 list로 복사하거나 child를 한 번에 push하지 않는다.
            def entries(mapping: dict[object, object]) -> Iterator[object]:
                for key, child in mapping.items():
                    if type(key) is not str:
                        raise ValueError("invalid heritage evidence object key")
                    yield key
                    yield child

            stack.append((iter(entries(node)), depth + 1))
        elif type(node) is list:
            encoded += 2 + 2 * max(0, len(node) - 1)
            stack.append((iter(node), depth + 1))
        elif node is None or type(node) in (str, int, float, bool):
            if type(node) is str and len(node) > 1_048_576:
                raise ValueError("invalid heritage evidence string budget")
            if type(node) is int and not -(2**63) <= node < 2**63:
                raise ValueError("invalid heritage evidence integer")
            if type(node) is float and not math.isfinite(node):
                raise ValueError("invalid heritage evidence number")
            encoded += len(json.dumps(node, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        else:
            raise ValueError("invalid heritage evidence primitive")
        if encoded > 1_048_576:
            raise ValueError("invalid heritage evidence encoded budget")


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("invalid heritage evidence object schema")
    return value


_ROW_KEYS: Final[dict[str, set[str]]] = {
    "provider_datasets": {"dataset_key", "provider_dataset_id", "is_active", "provider"},
    "source_entities": {
        "last_seen_at",
        "source_entity_id",
        "source_entity_key",
        "source_entity_type",
        "first_seen_at",
        "provider_dataset_id",
    },
    "source_entity_heads": {
        "current_source_record_key",
        "lineage_key",
        "expires_at",
        "source_entity_key",
        "observed_at",
    },
    "source_records": {
        "source_record_key",
        "imported_at",
        "raw_payload_hash",
        "source_entity_key",
        "fetched_at",
        "raw_data",
    },
    "source_links": {"source_entity_key", "source_role", "feature_id"},
    "provider_feature_identities": {
        "feature_id",
        "provider_dataset_id",
        "feature_kind",
        "natural_key",
    },
    "features": {
        "publication_state",
        "kind",
        "feature_id",
        "quality_state",
        "row_revision",
        "lifecycle_state",
    },
    "provider_field_active_policies": {"field_paths", "feature_id", "policy_revision"},
    "provider_field_shadow_policies": {
        "normalizer_revision",
        "provider_dataset_id",
        "fields",
        "policy_revision",
    },
    "provider_field_shadow_candidates": {
        "validated_at",
        "field_path",
        "value_geometry_sql_null",
        "value_source_hash",
        "validated_source_hash",
        "reason",
        "value_json",
        "availability",
        "source_entity_key",
        "feature_id",
        "value_observed_at",
        "geometry_ewkb",
        "validated_source_record_key",
        "normalizer_revision",
        "provider_dataset_id",
        "value_json_sql_null",
        "value_source_record_key",
        "policy_revision",
    },
    "feature_base_field_values": {
        "field_path",
        "source_record_key",
        "value_geometry_sql_null",
        "value_json",
        "base_revision",
        "source_entity_key",
        "feature_id",
        "geometry_ewkb",
        "observed_at",
        "provider_dataset_id",
        "value_json_sql_null",
        "source_raw_payload_hash",
    },
    "feature_geocode_stamps": {
        "reverse_outcome",
        "feature_id",
        "geo_version_token",
        "geo_data_token",
        "stamped_at",
    },
}

_JSON_FIELDS: Final[set[str]] = {"raw_data", "value_json", "fields", "field_paths"}
_INT_FIELDS: Final[set[str]] = {
    "provider_dataset_id",
    "row_revision",
    "policy_revision",
    "base_revision",
}
_NULLABLE_FIELDS: Final[set[str]] = {
    "expires_at",
    "value_source_record_key",
    "value_source_hash",
    "value_observed_at",
    "normalizer_revision",
    "geometry_ewkb",
}


def _row(kind: str, value: object) -> dict[str, object]:
    row = _object(value, _ROW_KEYS[kind])
    for key, child in row.items():
        if key in _JSON_FIELDS:
            continue
        if key in _INT_FIELDS:
            if type(child) is not int or not 1 <= child < 2**63:
                raise ValueError("invalid heritage evidence row integer")
        elif key in {"is_active", "value_json_sql_null", "value_geometry_sql_null"}:
            if type(child) is not bool:
                raise ValueError("invalid heritage evidence row boolean")
        elif child is None and key in _NULLABLE_FIELDS:
            continue
        elif type(child) is not str:
            raise ValueError("invalid heritage evidence row string")
    return row


def decode_heritage_evidence(
    request: HeritageEvidenceRequest, value: object
) -> HeritageEvidenceEnvelope:
    """정확한 envelope/요청 대응을 확인한다. 임의 SQL 예외를 fallback하지 않는다."""
    _bounded_response(value)
    top = _object(
        value, {"version", "evidence_complete", "reason", "dataset_id", "policy_epoch", "items"}
    )
    if type(top["version"]) is not int or top["version"] != 1:
        raise ValueError("invalid heritage evidence version")
    if type(top["dataset_id"]) is not int or top["dataset_id"] != request.dataset_id:
        raise ValueError("invalid heritage evidence dataset binding")
    complete = top["evidence_complete"]
    items = top["items"]
    if type(complete) is not bool or type(items) is not list:
        raise ValueError("invalid heritage evidence envelope types")
    if not complete:
        if type(top["reason"]) is not str or items or top["policy_epoch"] is not None:
            raise ValueError("invalid heritage evidence rejection")
        try:
            reason = HeritageEvidenceIneligibility(top["reason"])
        except ValueError as exc:
            raise ValueError("unknown heritage evidence rejection") from exc
        return HeritageEvidenceEnvelope(request, False, reason, None, ())
    epoch = top["policy_epoch"]
    if top["reason"] is not None or type(epoch) is not int or not 0 <= epoch < 2**63:
        raise ValueError("invalid heritage evidence policy epoch")
    if len(items) != len(request.entity_keys):
        raise ValueError("incomplete heritage evidence targets")
    expected_item_keys = {
        "source_entity",
        "source_head",
        "feature",
        "claim",
        "membership",
        "active_policy",
        "policy",
        "name_candidate",
        "name_base",
        "non_name_base",
        "base_record",
        "name_value_record",
        "current_record",
        "geocode_stamp",
    }
    seen: set[str] = set()
    decoded: list[dict[str, object]] = []
    for item in items:
        row = _object(item, expected_item_keys)
        entity = _row("source_entities", row["source_entity"])
        key = entity["source_entity_key"]
        if type(key) is not str or key not in request.entity_keys or key in seen:
            raise ValueError("invalid heritage evidence target binding")
        if (
            entity["provider_dataset_id"] != request.dataset_id
            or entity["source_entity_type"] != "heritage"
        ):
            raise ValueError("invalid heritage evidence source binding")
        base = row["non_name_base"]
        if type(base) is not list or len(base) != 24:
            raise ValueError("invalid heritage evidence base count")
        feature = _row("features", row["feature"])
        feature_id = feature["feature_id"]
        for item_key, table_key in {
            "source_head": "source_entity_heads",
            "claim": "provider_feature_identities",
            "membership": "source_links",
            "active_policy": "provider_field_active_policies",
            "policy": "provider_field_shadow_policies",
            "name_candidate": "provider_field_shadow_candidates",
            "name_base": "feature_base_field_values",
            "base_record": "source_records",
            "name_value_record": "source_records",
            "current_record": "source_records",
        }.items():
            child_row = _row(table_key, row[item_key])
            if "feature_id" in child_row and child_row["feature_id"] != feature_id:
                raise ValueError("invalid heritage evidence feature binding")
            if "source_entity_key" in child_row and child_row["source_entity_key"] != key:
                raise ValueError("invalid heritage evidence entity binding")
            if (
                "provider_dataset_id" in child_row
                and child_row["provider_dataset_id"] != request.dataset_id
            ):
                raise ValueError("invalid heritage evidence dataset binding")
        paths: set[str] = set()
        for base_value in base:
            base_row = _row("feature_base_field_values", base_value)
            path = base_row["field_path"]
            if type(path) is not str or path == "core.name" or path in paths:
                raise ValueError("invalid heritage evidence base paths")
            if (
                base_row["feature_id"] != feature_id
                or base_row["source_entity_key"] != key
                or base_row["provider_dataset_id"] != request.dataset_id
            ):
                raise ValueError("invalid heritage evidence base binding")
            paths.add(path)
        if row["geocode_stamp"] is not None:
            stamp = _row("feature_geocode_stamps", row["geocode_stamp"])
            if stamp["feature_id"] != feature_id:
                raise ValueError("invalid heritage evidence stamp binding")
        if len(json.dumps(row, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 131_072:
            raise ValueError("invalid heritage evidence item budget")
        seen.add(key)
        decoded.append(row)
    return HeritageEvidenceEnvelope(request, True, None, epoch, tuple(decoded))


async def read_heritage_evidence(
    session: AsyncSession, dataset_id: int, entity_keys: Iterable[str]
) -> HeritageEvidenceEnvelope:
    """명시 요청의 읽기만 수행한다. caller의 기존 TX/격리 수준을 바꾸지 않는다."""
    request = validate_heritage_evidence_request(dataset_id, entity_keys)
    async with asyncio.timeout(3):
        value = await session.scalar(
            text(
                "SELECT feature.read_heritage_name_refresh_evidence(:dataset,CAST(:keys AS text[]))"
            ),
            {"dataset": request.dataset_id, "keys": list(request.entity_keys)},
        )
    return decode_heritage_evidence(request, value)

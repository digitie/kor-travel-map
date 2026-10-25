"""공항 SD의 정확 응답 decoder와 caller 소유 read-only snapshot 경계.

427 SD/마이그레이션에 배선하되 실제 DB 수용은 별도다. evidence_complete는 SDK 적격성이나
쓰기/수집 권한이 아니다. 응답 내부 dict는 호출자가 await 동안 독점 소유한다.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final, cast
from uuid import UUID

from sqlalchemy import text

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.infra.feature_repo import _make_source_entity_key

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_MAX_ROWS: Final = 2730
_ENTITY: Final = re.compile(r"se_[0-9a-f]{64}")
_RECORD: Final = re.compile(r"sr_[0-9a-f]{20}")
_SHA: Final = re.compile(r"[0-9a-f]{32}")
_RAW_KEYS: Final = {
    "code",
    "name_korean",
    "name_english",
    "icao_code",
    "municipality",
    "latitude",
    "longitude",
}
_NON_NAME_FIELDS: Final = frozenset(
    {
        "core.category",
        "core.coord",
        "core.coord_precision_digits",
        "core.address",
        "core.legal_dong_code",
        "core.road_name_code",
        "core.road_address_management_no",
        "core.admin_dong_code",
        "core.sido_code",
        "core.sigungu_code",
        "core.urls",
        "core.marker_icon",
        "core.marker_color",
        "core.parent_feature_id",
        "core.sibling_group_id",
        "core.raw_refs",
        "place.place_kind",
        "place.phones",
        "place.biz_number",
        "place.license_date",
        "place.business_hours",
        "place.facility_info",
        "place.reviews_link",
        "place.payload",
    }
)


class AirportEvidenceReason(StrEnum):
    BUDGET_EXCEEDED = "budget_exceeded"
    STORAGE_UNSUPPORTED = "storage_unsupported"
    SCOPE_UNSUPPORTED = "scope_unsupported"
    EMPTY_SCOPE = "empty_scope"
    MISSING_SOURCE = "missing_source"
    LINEAGE_INCOMPLETE = "lineage_incomplete"
    UNSUPPORTED_MEMBERSHIP = "unsupported_membership"
    INACTIVE_FEATURE = "inactive_feature"
    POLICY_UNSUPPORTED = "policy_unsupported"
    MIXED_BASE_LINEAGE = "mixed_base_lineage"
    SHAPE_UNSUPPORTED = "shape_unsupported"
    OVERRIDE_UNSUPPORTED = "override_unsupported"
    GEO_UNSUPPORTED = "geo_evidence_unsupported"


@dataclass(frozen=True)
class AirportEvidenceEnvelope:
    dataset_id: int
    evidence_complete: bool
    db_scope_eof: bool
    reason: AirportEvidenceReason | None
    policy_epoch: int | None
    items: tuple[dict[str, object], ...]

    @property
    def collector_ready(self) -> bool:
        return False


_ROW_KEYS: Final[dict[str, set[str]]] = {
    "feature_base_field_values": {
        "base_revision",
        "feature_id",
        "field_path",
        "geometry_ewkb",
        "observed_at",
        "provider_dataset_id",
        "source_entity_key",
        "source_raw_payload_hash",
        "source_record_key",
        "value_geometry_sql_null",
        "value_json",
        "value_json_sql_null",
    },
    "feature_geocode_stamps": {
        "feature_id",
        "geo_data_token",
        "geo_version_token",
        "reverse_outcome",
        "stamped_at",
    },
    "features": {
        "address",
        "admin_dong_code",
        "coord_precision_digits",
        "coord_sql_null",
        "feature_id",
        "geometry_ewkb",
        "kind",
        "legal_dong_code",
        "lifecycle_state",
        "publication_state",
        "quality_state",
        "road_address_management_no",
        "road_name_code",
        "row_revision",
        "sido_code",
        "sigungu_code",
    },
    "provider_datasets": {"provider_dataset_id", "is_active", "provider", "dataset_key"},
    "provider_feature_identities": {
        "feature_id",
        "feature_kind",
        "natural_key",
        "provider_dataset_id",
    },
    "provider_field_active_policies": {"field_paths", "feature_id", "policy_revision"},
    "provider_field_shadow_candidates": {
        "availability",
        "feature_id",
        "field_path",
        "geometry_ewkb",
        "normalizer_revision",
        "policy_revision",
        "provider_dataset_id",
        "reason",
        "source_entity_key",
        "validated_at",
        "validated_source_hash",
        "validated_source_record_key",
        "value_geometry_sql_null",
        "value_json",
        "value_json_sql_null",
        "value_observed_at",
        "value_source_hash",
        "value_source_record_key",
    },
    "provider_field_shadow_policies": {
        "fields",
        "normalizer_revision",
        "policy_revision",
        "provider_dataset_id",
    },
    "source_entities": {
        "first_seen_at",
        "last_seen_at",
        "provider_dataset_id",
        "source_entity_id",
        "source_entity_key",
        "source_entity_type",
    },
    "source_entity_heads": {
        "current_source_record_key",
        "expires_at",
        "lineage_key",
        "observed_at",
        "source_entity_key",
    },
    "source_links": {"source_role", "feature_id", "source_entity_key"},
    "source_records": {
        "fetched_at",
        "imported_at",
        "raw_data",
        "raw_payload_hash",
        "source_entity_key",
        "source_record_key",
    },
}

_INT_KEYS: Final = {"provider_dataset_id", "row_revision", "policy_revision", "base_revision"}
_JSON_KEYS: Final = {"raw_data", "value_json", "fields", "field_paths", "address"}
_BOOL_KEYS: Final = {
    "is_active",
    "value_json_sql_null",
    "value_geometry_sql_null",
    "coord_sql_null",
}
_NULLABLE_KEYS: Final = {
    "expires_at",
    "value_source_record_key",
    "value_source_hash",
    "value_observed_at",
    "normalizer_revision",
    "geometry_ewkb",
    "coord_precision_digits",
    "legal_dong_code",
    "road_name_code",
    "road_address_management_no",
    "admin_dong_code",
    "sido_code",
    "sigungu_code",
}
_ITEM_KEYS: Final = {
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


def _budget(value: object) -> None:
    stack: list[tuple[Iterator[object], int]] = [(iter((value,)), 0)]
    nodes = encoded = 0
    while stack:
        iterator, depth = stack[-1]
        try:
            child = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        nodes += 1
        if nodes > 65536 or depth > 64:
            raise ValueError("invalid airport evidence tree budget")
        if type(child) is dict:
            encoded += 2 + max(0, len(child) - 1) + len(child)

            def entries(mapping: dict[object, object]) -> Iterator[object]:
                for key, item in mapping.items():
                    if type(key) is not str:
                        raise ValueError("invalid airport evidence key")
                    yield key
                    yield item

            stack.append((iter(entries(child)), depth + 1))
        elif type(child) is list:
            encoded += 2 + max(0, len(child) - 1)
            stack.append((iter(child), depth + 1))
        elif child is None or type(child) in (str, bool, int, float):
            if type(child) is str and len(child) > 1048576:
                raise ValueError("invalid airport evidence string budget")
            if type(child) is int and not -(2**63) <= child < 2**63:
                raise ValueError("invalid airport evidence integer")
            if type(child) is float and not math.isfinite(child):
                raise ValueError("invalid airport evidence number")
            encoded += len(json.dumps(child, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        else:
            raise ValueError("invalid airport evidence primitive")
        if encoded > 1048576:
            raise ValueError("invalid airport evidence byte budget")


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise ValueError("invalid airport evidence schema")
    return cast("dict[str, object]", value)


def _row(kind: str, value: object) -> dict[str, object]:
    row = _object(value, _ROW_KEYS[kind])
    for key, child in row.items():
        if key in _JSON_KEYS:
            continue
        if child is None and key in _NULLABLE_KEYS:
            continue
        if key in _INT_KEYS:
            if type(child) is not int or not 1 <= child < 2**63:
                raise ValueError("invalid airport evidence row integer")
        elif key == "coord_precision_digits":
            if type(child) is not int or not 3 <= child <= 8:
                raise ValueError("invalid airport evidence precision")
        elif key in _BOOL_KEYS:
            if type(child) is not bool:
                raise ValueError("invalid airport evidence row boolean")
        elif type(child) is not str:
            raise ValueError("invalid airport evidence row string")
    return row


def _instant(value: object) -> datetime:
    if type(value) is not str or len(value) > 64:
        raise ValueError("invalid airport evidence time")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid airport evidence time") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("invalid airport evidence aware time")
    return result


def _uuid(value: object) -> None:
    if type(value) is not str or len(value) != 36:
        raise ValueError("invalid airport evidence UUID")
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise ValueError("invalid airport evidence UUID") from exc
    if str(parsed) != value:
        raise ValueError("invalid airport evidence canonical UUID")


def _record(value: object, entity: dict[str, object]) -> dict[str, object]:
    row = _row("source_records", value)
    raw = _object(row["raw_data"], _RAW_KEYS)
    if any(v is not None and type(v) is not str for v in raw.values()):
        raise ValueError("invalid airport evidence raw7")
    if row["source_entity_key"] != entity["source_entity_key"]:
        raise ValueError("invalid airport evidence record entity")
    payload_hash = row["raw_payload_hash"]
    key = row["source_record_key"]
    if (
        type(payload_hash) is not str
        or len(payload_hash) != 32
        or _SHA.fullmatch(payload_hash) is None
    ):
        raise ValueError("invalid airport evidence payload hash")
    if type(key) is not str or len(key) != 23 or _RECORD.fullmatch(key) is None:
        raise ValueError("invalid airport evidence record key")
    entity_id = cast("str", entity["source_entity_id"])
    if (
        make_payload_hash(raw) != payload_hash
        or make_source_record_key(
            provider="kor-travel-transport",
            dataset_key="transport_airports",
            source_entity_type="airport",
            source_entity_id=entity_id,
            raw_payload_hash=payload_hash,
        )
        != key
    ):
        raise ValueError("invalid airport evidence canonical source")
    _instant(row["fetched_at"])
    _instant(row["imported_at"])
    return row


def decode_transport_airport_evidence(dataset_id: int, value: object) -> AirportEvidenceEnvelope:
    """형식/대응/전체 거부를 검증한다. SQL 예외를 EX로 숨기는 catch는 없다."""
    if type(dataset_id) is not int or not 1 <= dataset_id < 2**63:
        raise ValueError("invalid airport evidence dataset")
    _budget(value)
    top = _object(
        value,
        {
            "version",
            "dataset_id",
            "evidence_complete",
            "db_scope_eof",
            "reason",
            "policy_epoch",
            "items",
        },
    )
    if (
        type(top["version"]) is not int
        or top["version"] != 1
        or type(top["dataset_id"]) is not int
        or top["dataset_id"] != dataset_id
    ):
        raise ValueError("invalid airport evidence envelope binding")
    complete = top["evidence_complete"]
    eof = top["db_scope_eof"]
    items = top["items"]
    if type(complete) is not bool or type(eof) is not bool or type(items) is not list:
        raise ValueError("invalid airport evidence envelope types")
    if not complete:
        if eof or items or top["policy_epoch"] is not None or type(top["reason"]) is not str:
            raise ValueError("invalid airport evidence whole rejection")
        try:
            reason = AirportEvidenceReason(top["reason"])
        except ValueError as exc:
            raise ValueError("unknown airport evidence reason") from exc
        return AirportEvidenceEnvelope(dataset_id, False, False, reason, None, ())
    epoch = top["policy_epoch"]
    if (
        not eof
        or top["reason"] is not None
        or type(epoch) is not int
        or not 0 <= epoch < 2**63
        or not 1 <= len(items) <= _MAX_ROWS
    ):
        raise ValueError("invalid airport evidence complete envelope")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    features: set[str] = set()
    for value_item in items:
        item = _object(value_item, _ITEM_KEYS)
        entity = _row("source_entities", item["source_entity"])
        key = entity["source_entity_key"]
        if (
            type(key) is not str
            or len(key) != 67
            or _ENTITY.fullmatch(key) is None
            or key in seen
            or entity["provider_dataset_id"] != dataset_id
            or entity["source_entity_type"] != "airport"
        ):
            raise ValueError("invalid airport evidence entity scope")
        if (
            _make_source_entity_key(
                provider="kor-travel-transport",
                dataset_key="transport_airports",
                source_entity_type="airport",
                source_entity_id=cast("str", entity["source_entity_id"]),
            )
            != key
        ):
            raise ValueError("invalid airport evidence canonical entity")
        seen.add(key)
        head = _row("source_entity_heads", item["source_head"])
        feature = _row("features", item["feature"])
        claim = _row("provider_feature_identities", item["claim"])
        link = _row("source_links", item["membership"])
        active = _row("provider_field_active_policies", item["active_policy"])
        policy = _row("provider_field_shadow_policies", item["policy"])
        candidate = _row("provider_field_shadow_candidates", item["name_candidate"])
        name = _row("feature_base_field_values", item["name_base"])
        fid = feature["feature_id"]
        _uuid(fid)
        if type(fid) is not str or fid in features:
            raise ValueError("invalid airport evidence unique Feature")
        features.add(fid)
        if (
            feature["kind"] != "place"
            or feature["lifecycle_state"] != "active"
            or claim["feature_kind"] != "place"
            or claim["provider_dataset_id"] != dataset_id
            or claim["natural_key"] != entity["source_entity_id"]
            or any(row["feature_id"] != fid for row in (claim, link, active, candidate, name))
        ):
            raise ValueError("invalid airport evidence Feature binding")
        if (
            link["source_entity_key"] != key
            or link["source_role"] != "primary"
            or head["source_entity_key"] != key
            or head["expires_at"] is not None
        ):
            raise ValueError("invalid airport evidence membership binding")
        current = _record(item["current_record"], entity)
        name_record = _record(item["name_value_record"], entity)
        base_record = _record(item["base_record"], entity)
        if (
            head["current_source_record_key"] != current["source_record_key"]
            or candidate["validated_source_record_key"] != current["source_record_key"]
            or candidate["validated_source_hash"] != current["raw_payload_hash"]
            or candidate["value_source_record_key"] != name_record["source_record_key"]
            or candidate["value_source_hash"] != name_record["raw_payload_hash"]
        ):
            raise ValueError("invalid airport evidence name R1 R2 binding")
        if _instant(candidate["validated_at"]) != _instant(head["observed_at"]) or _instant(
            candidate["value_observed_at"]
        ) != _instant(name_record["fetched_at"]):
            raise ValueError("invalid airport evidence name clocks")
        if (
            active["field_paths"] != ["core.name"]
            or policy["provider_dataset_id"] != dataset_id
            or policy["policy_revision"] != active["policy_revision"]
            or candidate["policy_revision"] != active["policy_revision"]
            or candidate["provider_dataset_id"] != dataset_id
            or any(
                row["normalizer_revision"] != "transport-airport-name-v1"
                for row in (policy, candidate)
            )
        ):
            raise ValueError("invalid airport evidence normalizer policy")
        if (
            candidate["field_path"] != "core.name"
            or candidate["source_entity_key"] != key
            or candidate["availability"] != "value"
            or candidate["reason"] not in {"supplied", "omitted_carry"}
            or type(candidate["value_json"]) is not str
            or candidate["value_json_sql_null"] is not False
            or candidate["value_geometry_sql_null"] is not True
        ):
            raise ValueError("invalid airport evidence candidate schema")
        fields = policy["fields"]
        if type(fields) is not list or len(fields) != 1:
            raise ValueError("invalid airport evidence policy fields")
        policy_field = _object(
            fields[0], {"field_path", "provider_rank", "null_policy", "omitted_policy"}
        )
        rank = policy_field["provider_rank"]
        if (
            policy_field["field_path"] != "core.name"
            or policy_field["null_policy"] != "value"
            or policy_field["omitted_policy"] != "carry_forward"
            or type(rank) is not int
            or not 0 <= rank <= 2147483647
        ):
            raise ValueError("invalid airport evidence policy field contract")
        if (
            name["provider_dataset_id"] != dataset_id
            or name["source_entity_key"] != key
            or name["field_path"] != "core.name"
            or name["source_record_key"] != name_record["source_record_key"]
            or name["source_raw_payload_hash"] != name_record["raw_payload_hash"]
            or name["value_json"] != candidate["value_json"]
        ):
            raise ValueError("invalid airport evidence name base")
        base = item["non_name_base"]
        if type(base) is not list or len(base) != 24:
            raise ValueError("invalid airport evidence base24")
        paths: set[str] = set()
        for raw_row in base:
            row = _row("feature_base_field_values", raw_row)
            path = row["field_path"]
            if type(path) is not str or path not in _NON_NAME_FIELDS or path in paths:
                raise ValueError("invalid airport evidence base fieldset")
            paths.add(path)
            if (
                row["feature_id"] != fid
                or row["provider_dataset_id"] != dataset_id
                or row["source_entity_key"] != key
                or row["source_record_key"] != base_record["source_record_key"]
                or row["source_raw_payload_hash"] != base_record["raw_payload_hash"]
            ):
                raise ValueError("invalid airport evidence base provenance")
            _instant(row["observed_at"])
        if item["geocode_stamp"] is not None:
            stamp = _row("feature_geocode_stamps", item["geocode_stamp"])
            if stamp["feature_id"] != fid:
                raise ValueError("invalid airport evidence stamp Feature")
            if stamp["reverse_outcome"] not in {"called", "geocoded", "not_called"}:
                raise ValueError("invalid airport evidence stamp outcome")
            _instant(stamp["stamped_at"])
        result.append(item)
    if [
        cast("dict[str,object]", i["source_entity"])["source_entity_key"] for i in result
    ] != sorted(seen):
        raise ValueError("invalid airport evidence scope ordering")
    return AirportEvidenceEnvelope(dataset_id, True, True, None, epoch, tuple(result))


_READ_SQL: Final = text("SELECT feature.read_transport_airport_snapshot_evidence(:dataset)")
_MODE_SQL: Final = text(
    "SELECT current_setting('transaction_isolation') AS isolation,"
    "current_setting('transaction_read_only') AS read_only"
)


async def read_transport_airport_evidence(
    session: AsyncSession, dataset_id: int
) -> AirportEvidenceEnvelope:
    """caller의 기존 RR/read-only TX를 쓴다. 새 transaction/commit/GUC 변경이 없다."""
    if type(dataset_id) is not int or not 1 <= dataset_id < 2**63:
        raise ValueError("invalid airport evidence dataset")
    if not session.in_transaction():
        raise ValueError("airport evidence requires caller-owned read-only snapshot")
    async with asyncio.timeout(3):
        mode = (await session.execute(_MODE_SQL)).mappings().one()
        if mode["isolation"] != "repeatable read" or mode["read_only"] != "on":
            raise ValueError("airport evidence requires read-only repeatable read")
        value = (await session.execute(_READ_SQL, {"dataset": dataset_id})).scalar_one()
    return decode_transport_airport_evidence(dataset_id, value)

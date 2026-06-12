"""``admin_feature_repo`` — admin feature review/deactivate/dedup SQL.

``/admin/features``와 ``/admin/dedup-review``가 쓰는 운영자용 read/write 쿼리다.
ORM 모델에는 비즈니스 로직을 두지 않고, 본 모듈의 raw SQL로 처리한다(ADR-004).
"""

from __future__ import annotations

import base64
import json
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from sqlalchemy import text

from kortravelmap.infra.merge_repo import (
    MergeConflictError,
    MergeNotFoundError,
    MergeOutcome,
    apply_feature_merge,
    merge_from_review,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "AdminFeaturePage",
    "AdminFeatureRow",
    "AdminFeatureDetail",
    "AdminFeatureDetailFeature",
    "AdminFeatureDetailFile",
    "AdminFeatureDetailIssue",
    "AdminFeatureDetailOverride",
    "AdminFeatureDetailSource",
    "AdminFeatureDetailVersion",
    "DedupReviewPage",
    "DedupReviewRow",
    "DedupFeatureSummary",
    "EnrichmentReviewPage",
    "EnrichmentReviewRow",
    "FeatureDeactivateResult",
    "FeatureStateConflict",
    "FeatureOverride",
    "FeatureChangeConflict",
    "FeatureChangeRequest",
    "deactivate_feature",
    "submit_feature_change_request",
    "apply_feature_change_request",
    "reject_feature_change_request",
    "list_feature_change_requests",
    "get_admin_feature_detail",
    "list_admin_features",
    "list_dedup_reviews",
    "list_enrichment_reviews",
    "merge_dedup_review",
    "set_dedup_review_decision",
]

AdminFeatureSort = Literal[
    "name",
    "updated_at",
    "created_at",
    "kind",
    "status",
    "provider",
    "issue_count",
]
SortOrder = Literal["asc", "desc"]
DedupDecision = Literal["accepted", "rejected", "ignored"]
FeatureChangeAction = Literal["add", "update", "delete"]
FeatureChangeState = Literal["pending", "applied", "rejected"]
FeatureChangeReviewMode = Literal["require_review", "immediate"]


@dataclass(frozen=True)
class AdminFeatureRow:
    """``GET /admin/features`` item."""

    feature_id: str
    kind: str
    name: str
    category: str
    status: str
    lon: float | None
    lat: float | None
    address_label: str
    primary_provider: str | None
    primary_dataset_key: str | None
    issue_count: int
    issues: tuple[dict[str, Any], ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AdminFeaturePage:
    """Admin feature keyset page."""

    items: tuple[AdminFeatureRow, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class AdminFeatureDetailFeature:
    """Admin feature 상세의 feature core snapshot."""

    feature_id: str
    kind: str
    name: str
    category: str
    status: str
    lon: float | None
    lat: float | None
    coord_precision_digits: int | None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    raw_refs: list[dict[str, Any]]
    legal_dong_code: str | None
    road_name_code: str | None
    road_address_management_no: str | None
    admin_dong_code: str | None
    sido_code: str | None
    sigungu_code: str | None
    marker_icon: str | None
    marker_color: str | None
    parent_feature_id: str | None
    sibling_group_id: str | None
    data_origin: str
    data_version: int
    user_change_kind: str | None
    user_change_status: str | None
    user_change_request_id: str | None
    user_deleted_at: datetime | None
    user_deleted_by: str | None
    user_change_reason: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


@dataclass(frozen=True)
class AdminFeatureDetailSource:
    """Feature에 연결된 SourceRecord + SourceLink snapshot."""

    source_record_key: str
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    source_version: str | None
    source_role: str
    match_method: str
    confidence: int
    is_primary_source: bool
    raw_name: str | None
    raw_address: str | None
    raw_longitude: float | None
    raw_latitude: float | None
    raw_payload_hash: str
    raw_data: dict[str, Any]
    fetched_at: datetime
    imported_at: datetime
    expires_at: datetime | None
    linked_at: datetime


@dataclass(frozen=True)
class AdminFeatureDetailIssue:
    """Feature 상세 issue row."""

    issue_id: str
    provider: str | None
    dataset_key: str | None
    source_record_key: str | None
    violation_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    status: str
    detected_at: datetime
    resolved_at: datetime | None


@dataclass(frozen=True)
class AdminFeatureDetailOverride:
    """Feature 상세 override row."""

    override_id: str
    source_record_key: str | None
    field_path: str
    source_value: Any
    override_value: Any
    prevent_provider_reactivation: bool
    status: str
    reason: str | None
    created_by: str | None
    created_at: datetime


@dataclass(frozen=True)
class AdminFeatureDetailVersion:
    """Feature version/history row."""

    feature_id: str
    version: int
    origin: str
    change_kind: str
    payload: dict[str, Any]
    request_id: str | None
    created_by: str | None
    created_at: datetime


@dataclass(frozen=True)
class AdminFeatureDetailFile:
    """Feature file metadata row.

    ``feature.feature_files``는 아직 모든 DB head에 존재하지 않는다. 상세 API는 테이블이
    있으면 이 모델로 반환하고, 없으면 빈 tuple을 반환한다.
    """

    file_id: str
    file_type: str
    storage_backend: str
    bucket: str
    object_key: str
    source_url: str | None
    public_url: str | None
    content_type: str | None
    byte_size: int | None
    checksum_sha256: str | None
    width: int | None
    height: int | None
    role: str
    display_order: int
    alt_text: str | None
    provider: str | None
    dataset_key: str | None
    source_record_key: str | None
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class AdminFeatureDetail:
    """Admin feature 상세 aggregate."""

    feature: AdminFeatureDetailFeature
    sources: tuple[AdminFeatureDetailSource, ...]
    issues: tuple[AdminFeatureDetailIssue, ...]
    overrides: tuple[AdminFeatureDetailOverride, ...]
    versions: tuple[AdminFeatureDetailVersion, ...]
    change_requests: tuple[FeatureChangeRequest, ...]
    files: tuple[AdminFeatureDetailFile, ...]


@dataclass(frozen=True)
class FeatureOverride:
    """생성/갱신된 feature override summary."""

    override_id: str
    feature_id: str
    field_path: str
    override_value: Any
    prevent_provider_reactivation: bool
    reason: str | None
    created_by: str | None
    created_at: datetime


@dataclass(frozen=True)
class FeatureDeactivateResult:
    """``POST /admin/features/{feature_id}/deactivate`` 결과."""

    feature_id: str
    previous_status: str
    status: str
    override_created: bool
    override: FeatureOverride | None


class FeatureStateConflict(ValueError):
    """feature 상태가 요청한 admin 전이를 허용하지 않을 때 발생."""

    def __init__(
        self,
        *,
        feature_id: str,
        current_status: str,
        deleted_at: datetime | None,
        target_status: str,
    ) -> None:
        self.feature_id = feature_id
        self.current_status = current_status
        self.deleted_at = deleted_at
        self.target_status = target_status
        reason = f"status={current_status!r}"
        if deleted_at is not None:
            reason = f"{reason}, deleted_at={deleted_at.isoformat()}"
        super().__init__(
            f"feature {feature_id!r}는 {target_status!r} 전이를 허용하지 않음: {reason}"
        )


class FeatureChangeConflict(ValueError):
    """feature add/update/delete 요청을 적용할 수 없을 때 발생."""

    def __init__(
        self,
        *,
        feature_id: str,
        action: str,
        current_status: str | None = None,
        user_deleted_at: datetime | None = None,
        message: str | None = None,
    ) -> None:
        self.feature_id = feature_id
        self.action = action
        self.current_status = current_status
        self.user_deleted_at = user_deleted_at
        if message is None:
            reason = f"status={current_status!r}"
            if user_deleted_at is not None:
                reason = f"{reason}, user_deleted_at={user_deleted_at.isoformat()}"
            message = f"feature {feature_id!r}는 {action!r} 적용 불가: {reason}"
        super().__init__(message)


@dataclass(frozen=True)
class FeatureChangeRequest:
    """``ops.feature_change_requests`` row summary."""

    request_id: str
    feature_id: str
    action: str
    state: str
    review_mode: str
    payload: dict[str, Any]
    reason: str | None
    requested_by: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    applied_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class DedupFeatureSummary:
    """Dedup 후보의 feature 한쪽 summary."""

    feature_id: str
    name: str
    kind: str
    category: str
    lon: float | None
    lat: float | None
    provider: str | None
    dataset_key: str | None


@dataclass(frozen=True)
class DedupReviewRow:
    """``GET /admin/dedup-review`` item."""

    review_id: str
    status: str
    total_score: float
    name_score: float
    spatial_score: float
    category_score: float
    feature_a: DedupFeatureSummary
    feature_b: DedupFeatureSummary
    distance_m: float | None
    decision_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    total_score_cursor: str | None = None


@dataclass(frozen=True)
class DedupReviewPage:
    """Dedup review page."""

    items: tuple[DedupReviewRow, ...]
    next_cursor: str | None


_ADMIN_FEATURE_SORT_COLUMNS: Final[dict[str, str]] = {
    "name": "sort_name",
    "updated_at": "updated_at",
    "created_at": "created_at",
    "kind": "kind",
    "status": "status",
    "provider": "sort_provider",
    "issue_count": "issue_count",
}
_TEXT_SORTS: Final[set[str]] = {"name", "kind", "status", "provider"}
_DATETIME_SORTS: Final[set[str]] = {"updated_at", "created_at"}


def _normalize_values(values: Sequence[str] | None) -> list[str] | None:
    if values is None:
        return None
    normalized = [str(value) for value in values if str(value)]
    return normalized or None


def _normalize_query(q: str | None) -> str | None:
    if q is None:
        return None
    normalized = unicodedata.normalize("NFKC", q).strip()
    return normalized or None


def _json_array(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        with suppress(json.JSONDecodeError):
            return json.loads(value)
    return value


def _json_object(value: Any) -> dict[str, Any]:
    value = _json_value(value)
    return dict(value) if isinstance(value, dict) else {}


def _json_object_list(value: Any) -> list[dict[str, Any]]:
    value = _json_value(value)
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cursor_payload(cursor: str | None, *, sort: str, order: str) -> dict[str, Any]:
    if cursor is None:
        return {}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid admin features cursor") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("sort") != sort
        or payload.get("order") != order
    ):
        raise ValueError("invalid admin features cursor")
    feature_id = payload.get("feature_id")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("invalid admin features cursor")
    return payload


def _encode_cursor(item: AdminFeatureRow, *, sort: str, order: str) -> str:
    sort_value: Any
    if sort == "name":
        sort_value = item.name
    elif sort == "updated_at":
        sort_value = item.updated_at.isoformat()
    elif sort == "created_at":
        sort_value = item.created_at.isoformat()
    elif sort == "kind":
        sort_value = item.kind
    elif sort == "status":
        sort_value = item.status
    elif sort == "provider":
        sort_value = item.primary_provider or ""
    elif sort == "issue_count":
        sort_value = item.issue_count
    else:  # pragma: no cover - sort whitelist가 선행한다.
        raise ValueError("unsupported admin features sort")
    raw = json.dumps(
        {
            "sort": sort,
            "order": order,
            "feature_id": item.feature_id,
            "value": sort_value,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _cursor_params(cursor: str | None, *, sort: str, order: str) -> dict[str, Any]:
    payload = _cursor_payload(cursor, sort=sort, order=order)
    params: dict[str, Any] = {
        "cursor_feature_id": None,
        "cursor_text": None,
        "cursor_dt": None,
        "cursor_int": None,
    }
    if not payload:
        return params
    params["cursor_feature_id"] = payload["feature_id"]
    value = payload.get("value")
    if sort in _TEXT_SORTS:
        if not isinstance(value, str):
            raise ValueError("invalid admin features cursor")
        params["cursor_text"] = value
    elif sort in _DATETIME_SORTS:
        try:
            params["cursor_dt"] = datetime.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError("invalid admin features cursor") from exc
    elif sort == "issue_count":
        if not isinstance(value, str | int | float):
            raise ValueError("invalid admin features cursor")
        try:
            params["cursor_int"] = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid admin features cursor") from exc
    return params


def _keyset_condition(*, sort: str, order: str) -> str:
    column = _ADMIN_FEATURE_SORT_COLUMNS[sort]
    op = ">" if order == "asc" else "<"
    if sort in _TEXT_SORTS:
        return (
            "(CAST(:cursor_feature_id AS text) IS NULL OR "
            f"({column}, feature_id) {op} "
            "(CAST(:cursor_text AS text), CAST(:cursor_feature_id AS text)))"
        )
    if sort in _DATETIME_SORTS:
        return (
            "(CAST(:cursor_feature_id AS text) IS NULL OR "
            f"({column}, feature_id) {op} "
            "(CAST(:cursor_dt AS timestamptz), CAST(:cursor_feature_id AS text)))"
        )
    return (
        "(CAST(:cursor_feature_id AS text) IS NULL OR "
        f"({column}, feature_id) {op} "
        "(CAST(:cursor_int AS integer), CAST(:cursor_feature_id AS text)))"
    )


def _admin_features_sql(*, sort: str, order: str) -> str:
    column = _ADMIN_FEATURE_SORT_COLUMNS[sort]
    order_sql = "ASC" if order == "asc" else "DESC"
    return f"""
WITH base AS (
    SELECT
        f.feature_id,
        f.kind,
        f.name,
        lower(f.name) AS sort_name,
        f.category,
        f.status,
        x_extension.ST_X(f.coord) AS lon,
        x_extension.ST_Y(f.coord) AS lat,
        COALESCE(
            NULLIF(f.address ->> 'road', ''),
            NULLIF(f.address ->> 'legal', ''),
            NULLIF(f.address ->> 'admin', ''),
            ''
        ) AS address_label,
        ps.provider AS primary_provider,
        ps.dataset_key AS primary_dataset_key,
        COALESCE(ps.provider, '') AS sort_provider,
        COALESCE(issue.issue_count, 0)::integer AS issue_count,
        COALESCE(issue.issues, '[]'::jsonb) AS issues,
        f.created_at,
        f.updated_at
    FROM feature.features AS f
    LEFT JOIN LATERAL (
        SELECT sr.provider, sr.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = sl.source_record_key
        WHERE sl.feature_id = f.feature_id
          AND sl.is_primary_source
        ORDER BY sr.imported_at DESC NULLS LAST, sr.source_record_key
        LIMIT 1
    ) AS ps ON TRUE
    LEFT JOIN LATERAL (
        SELECT
            count(*)::integer AS issue_count,
            jsonb_agg(
                jsonb_build_object(
                    'issue_id', v.issue_id::text,
                    'violation_type', v.violation_type,
                    'severity', v.severity,
                    'message', v.message,
                    'detected_at', v.detected_at
                )
                ORDER BY v.detected_at DESC
            ) AS issues
        FROM ops.data_integrity_violations AS v
        WHERE v.feature_id = f.feature_id
          AND v.status = 'open'
          AND (
            CAST(:issue_types AS text[]) IS NULL
            OR v.violation_type = ANY(CAST(:issue_types AS text[]))
          )
    ) AS issue ON TRUE
    WHERE (CAST(:kinds AS text[]) IS NULL OR f.kind = ANY(CAST(:kinds AS text[])))
      AND (
        CAST(:categories AS text[]) IS NULL
        OR f.category = ANY(CAST(:categories AS text[]))
      )
      AND (
        CAST(:statuses AS text[]) IS NULL
        OR f.status = ANY(CAST(:statuses AS text[]))
      )
      AND (
        CAST(:providers AS text[]) IS NULL
        OR ps.provider = ANY(CAST(:providers AS text[]))
      )
      AND (
        CAST(:dataset_keys AS text[]) IS NULL
        OR ps.dataset_key = ANY(CAST(:dataset_keys AS text[]))
      )
      AND (
        CAST(:has_coord AS boolean) IS NULL
        OR (CAST(:has_coord AS boolean) AND f.coord IS NOT NULL)
        OR (NOT CAST(:has_coord AS boolean) AND f.coord IS NULL)
      )
      AND (
        CAST(:updated_from AS timestamptz) IS NULL
        OR f.updated_at >= CAST(:updated_from AS timestamptz)
      )
      AND (
        CAST(:updated_to AS timestamptz) IS NULL
        OR f.updated_at <= CAST(:updated_to AS timestamptz)
      )
      AND (
        CAST(:q_like AS text) IS NULL
        OR f.feature_id ILIKE CAST(:q_like AS text)
        OR f.name ILIKE CAST(:q_like AS text)
        OR f.address::text ILIKE CAST(:q_like AS text)
        OR EXISTS (
            SELECT 1
            FROM provider_sync.source_links AS qsl
            JOIN provider_sync.source_records AS qsr
              ON qsr.source_record_key = qsl.source_record_key
            WHERE qsl.feature_id = f.feature_id
              AND (
                qsr.source_record_key ILIKE CAST(:q_like AS text)
                OR qsr.source_entity_id ILIKE CAST(:q_like AS text)
                OR qsr.raw_name ILIKE CAST(:q_like AS text)
                OR qsr.raw_address ILIKE CAST(:q_like AS text)
              )
        )
      )
)
SELECT *
FROM base
WHERE (
    CAST(:has_issue AS boolean) IS NULL
    OR (CAST(:has_issue AS boolean) AND issue_count > 0)
    OR (NOT CAST(:has_issue AS boolean) AND issue_count = 0)
)
  AND {_keyset_condition(sort=sort, order=order)}
ORDER BY {column} {order_sql}, feature_id {order_sql}
LIMIT :limit_plus_one
"""


def _admin_feature_row(row: Any) -> AdminFeatureRow:
    return AdminFeatureRow(
        feature_id=str(row["feature_id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        category=str(row["category"]),
        status=str(row["status"]),
        lon=float(row["lon"]) if row["lon"] is not None else None,
        lat=float(row["lat"]) if row["lat"] is not None else None,
        address_label=str(row["address_label"] or ""),
        primary_provider=row["primary_provider"],
        primary_dataset_key=row["primary_dataset_key"],
        issue_count=int(row["issue_count"]),
        issues=_json_array(row["issues"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_ADMIN_FEATURE_DETAIL_SQL: Final[str] = """
SELECT
    feature_id,
    kind,
    name,
    category,
    status,
    x_extension.ST_X(coord) AS lon,
    x_extension.ST_Y(coord) AS lat,
    coord_precision_digits,
    address,
    detail,
    urls,
    raw_refs,
    legal_dong_code,
    road_name_code,
    road_address_management_no,
    admin_dong_code,
    sido_code,
    sigungu_code,
    marker_icon,
    marker_color,
    parent_feature_id,
    sibling_group_id::text AS sibling_group_id,
    data_origin,
    data_version,
    user_change_kind,
    user_change_status,
    user_change_request_id::text AS user_change_request_id,
    user_deleted_at,
    user_deleted_by,
    user_change_reason,
    created_at,
    updated_at,
    deleted_at
FROM feature.features
WHERE feature_id = :feature_id
"""

_ADMIN_FEATURE_SOURCES_SQL: Final[str] = """
SELECT
    sr.source_record_key,
    sr.provider,
    sr.dataset_key,
    sr.source_entity_type,
    sr.source_entity_id,
    sr.source_version,
    sl.source_role,
    sl.match_method,
    sl.confidence,
    sl.is_primary_source,
    sr.raw_name,
    sr.raw_address,
    sr.raw_longitude,
    sr.raw_latitude,
    sr.raw_payload_hash,
    sr.raw_data,
    sr.fetched_at,
    sr.imported_at,
    sr.expires_at,
    sl.created_at AS linked_at
FROM provider_sync.source_links AS sl
JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = sl.source_record_key
WHERE sl.feature_id = :feature_id
ORDER BY sl.is_primary_source DESC, sr.imported_at DESC NULLS LAST,
         sl.created_at DESC, sr.source_record_key
LIMIT 50
"""

_ADMIN_FEATURE_ISSUES_SQL: Final[str] = """
SELECT
    issue_id::text AS issue_id,
    provider,
    dataset_key,
    source_record_key,
    violation_type,
    severity,
    message,
    payload,
    status,
    detected_at,
    resolved_at
FROM ops.data_integrity_violations
WHERE feature_id = :feature_id
ORDER BY (status = 'open') DESC, detected_at DESC, issue_id DESC
LIMIT 100
"""

_ADMIN_FEATURE_OVERRIDES_SQL: Final[str] = """
SELECT
    override_id::text AS override_id,
    source_record_key,
    field_path,
    source_value,
    override_value,
    prevent_provider_reactivation,
    status,
    reason,
    created_by,
    created_at
FROM ops.feature_overrides
WHERE feature_id = :feature_id
ORDER BY (status = 'active') DESC, created_at DESC, override_id DESC
LIMIT 100
"""

_ADMIN_FEATURE_VERSIONS_SQL: Final[str] = """
SELECT
    feature_id,
    version,
    origin,
    change_kind,
    payload,
    request_id::text AS request_id,
    created_by,
    created_at
FROM feature.feature_versions
WHERE feature_id = :feature_id
ORDER BY version DESC, created_at DESC
LIMIT 50
"""

_ADMIN_FEATURE_CHANGE_REQUESTS_SQL: Final[str] = """
SELECT
    request_id::text,
    feature_id,
    action,
    state,
    review_mode,
    payload,
    reason,
    requested_by,
    reviewed_by,
    reviewed_at,
    applied_at,
    created_at
FROM ops.feature_change_requests
WHERE feature_id = :feature_id
ORDER BY created_at DESC, request_id DESC
LIMIT 50
"""

_FEATURE_FILES_TABLE_EXISTS_SQL: Final[str] = """
SELECT to_regclass('feature.feature_files') IS NOT NULL AS exists
"""

_ADMIN_FEATURE_FILES_SQL: Final[str] = """
SELECT
    file_id,
    file_type,
    storage_backend,
    bucket,
    object_key,
    source_url,
    public_url,
    content_type,
    byte_size,
    checksum_sha256,
    width,
    height,
    role,
    display_order,
    alt_text,
    provider,
    dataset_key,
    source_record_key,
    payload,
    created_at,
    updated_at
FROM feature.feature_files
WHERE feature_id = :feature_id
ORDER BY display_order ASC, file_id ASC
LIMIT 100
"""


def _admin_feature_detail_feature(row: Any) -> AdminFeatureDetailFeature:
    return AdminFeatureDetailFeature(
        feature_id=str(row["feature_id"]),
        kind=str(row["kind"]),
        name=str(row["name"]),
        category=str(row["category"]),
        status=str(row["status"]),
        lon=_float_or_none(row["lon"]),
        lat=_float_or_none(row["lat"]),
        coord_precision_digits=(
            int(row["coord_precision_digits"])
            if row["coord_precision_digits"] is not None
            else None
        ),
        address=_json_object(row["address"]),
        detail=_json_object(row["detail"]),
        urls=_json_object(row["urls"]),
        raw_refs=_json_object_list(row["raw_refs"]),
        legal_dong_code=row["legal_dong_code"],
        road_name_code=row["road_name_code"],
        road_address_management_no=row["road_address_management_no"],
        admin_dong_code=row["admin_dong_code"],
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        parent_feature_id=row["parent_feature_id"],
        sibling_group_id=row["sibling_group_id"],
        data_origin=str(row["data_origin"]),
        data_version=int(row["data_version"]),
        user_change_kind=row["user_change_kind"],
        user_change_status=row["user_change_status"],
        user_change_request_id=row["user_change_request_id"],
        user_deleted_at=row["user_deleted_at"],
        user_deleted_by=row["user_deleted_by"],
        user_change_reason=row["user_change_reason"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        deleted_at=row["deleted_at"],
    )


def _admin_feature_detail_source(row: Any) -> AdminFeatureDetailSource:
    return AdminFeatureDetailSource(
        source_record_key=str(row["source_record_key"]),
        provider=str(row["provider"]),
        dataset_key=str(row["dataset_key"]),
        source_entity_type=str(row["source_entity_type"]),
        source_entity_id=str(row["source_entity_id"]),
        source_version=row["source_version"],
        source_role=str(row["source_role"]),
        match_method=str(row["match_method"]),
        confidence=int(row["confidence"]),
        is_primary_source=bool(row["is_primary_source"]),
        raw_name=row["raw_name"],
        raw_address=row["raw_address"],
        raw_longitude=_float_or_none(row["raw_longitude"]),
        raw_latitude=_float_or_none(row["raw_latitude"]),
        raw_payload_hash=str(row["raw_payload_hash"]),
        raw_data=_json_object(row["raw_data"]),
        fetched_at=row["fetched_at"],
        imported_at=row["imported_at"],
        expires_at=row["expires_at"],
        linked_at=row["linked_at"],
    )


def _admin_feature_detail_issue(row: Any) -> AdminFeatureDetailIssue:
    return AdminFeatureDetailIssue(
        issue_id=str(row["issue_id"]),
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        source_record_key=row["source_record_key"],
        violation_type=str(row["violation_type"]),
        severity=str(row["severity"]),
        message=str(row["message"]),
        payload=_json_object(row["payload"]),
        status=str(row["status"]),
        detected_at=row["detected_at"],
        resolved_at=row["resolved_at"],
    )


def _admin_feature_detail_override(row: Any) -> AdminFeatureDetailOverride:
    return AdminFeatureDetailOverride(
        override_id=str(row["override_id"]),
        source_record_key=row["source_record_key"],
        field_path=str(row["field_path"]),
        source_value=_json_value(row["source_value"]),
        override_value=_json_value(row["override_value"]),
        prevent_provider_reactivation=bool(row["prevent_provider_reactivation"]),
        status=str(row["status"]),
        reason=row["reason"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _admin_feature_detail_version(row: Any) -> AdminFeatureDetailVersion:
    return AdminFeatureDetailVersion(
        feature_id=str(row["feature_id"]),
        version=int(row["version"]),
        origin=str(row["origin"]),
        change_kind=str(row["change_kind"]),
        payload=_json_object(row["payload"]),
        request_id=row["request_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def _admin_feature_detail_file(row: Any) -> AdminFeatureDetailFile:
    return AdminFeatureDetailFile(
        file_id=str(row["file_id"]),
        file_type=str(row["file_type"]),
        storage_backend=str(row["storage_backend"]),
        bucket=str(row["bucket"]),
        object_key=str(row["object_key"]),
        source_url=row["source_url"],
        public_url=row["public_url"],
        content_type=row["content_type"],
        byte_size=int(row["byte_size"]) if row["byte_size"] is not None else None,
        checksum_sha256=row["checksum_sha256"],
        width=int(row["width"]) if row["width"] is not None else None,
        height=int(row["height"]) if row["height"] is not None else None,
        role=str(row["role"]),
        display_order=int(row["display_order"]),
        alt_text=row["alt_text"],
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        source_record_key=row["source_record_key"],
        payload=_json_object(row["payload"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _feature_files_table_exists(session: AsyncSession) -> bool:
    row = (
        await session.execute(text(_FEATURE_FILES_TABLE_EXISTS_SQL), {})
    ).mappings().one()
    return bool(row["exists"])


async def _list_admin_feature_files(
    session: AsyncSession, feature_id: str
) -> tuple[AdminFeatureDetailFile, ...]:
    if not await _feature_files_table_exists(session):
        return ()
    rows = (
        await session.execute(text(_ADMIN_FEATURE_FILES_SQL), {"feature_id": feature_id})
    ).mappings().all()
    return tuple(_admin_feature_detail_file(row) for row in rows)


async def get_admin_feature_detail(
    session: AsyncSession, feature_id: str
) -> AdminFeatureDetail | None:
    """Admin 상세 화면용 feature aggregate를 조회한다."""
    feature_row = (
        await session.execute(
            text(_ADMIN_FEATURE_DETAIL_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().first()
    if feature_row is None:
        return None

    sources = (
        await session.execute(
            text(_ADMIN_FEATURE_SOURCES_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    issues = (
        await session.execute(
            text(_ADMIN_FEATURE_ISSUES_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    overrides = (
        await session.execute(
            text(_ADMIN_FEATURE_OVERRIDES_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    versions = (
        await session.execute(
            text(_ADMIN_FEATURE_VERSIONS_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().all()
    change_requests = (
        await session.execute(
            text(_ADMIN_FEATURE_CHANGE_REQUESTS_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().all()

    return AdminFeatureDetail(
        feature=_admin_feature_detail_feature(feature_row),
        sources=tuple(_admin_feature_detail_source(row) for row in sources),
        issues=tuple(_admin_feature_detail_issue(row) for row in issues),
        overrides=tuple(_admin_feature_detail_override(row) for row in overrides),
        versions=tuple(_admin_feature_detail_version(row) for row in versions),
        change_requests=tuple(_feature_change_row(row) for row in change_requests),
        files=await _list_admin_feature_files(session, feature_id),
    )


async def list_admin_features(
    session: AsyncSession,
    *,
    q: str | None = None,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    statuses: Sequence[str] | None = ("active",),
    providers: Sequence[str] | None = None,
    dataset_keys: Sequence[str] | None = None,
    has_coord: bool | None = None,
    has_issue: bool | None = None,
    issue_types: Sequence[str] | None = None,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    page_size: int = 50,
    cursor: str | None = None,
    sort: AdminFeatureSort = "name",
    order: SortOrder = "asc",
) -> AdminFeaturePage:
    """Admin feature 목록을 keyset cursor로 조회한다."""
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    effective_limit = min(page_size, 500)
    normalized_q = _normalize_query(q)
    params = {
        "q_like": f"%{normalized_q}%" if normalized_q is not None else None,
        "kinds": _normalize_values(kinds),
        "categories": _normalize_values(categories),
        "statuses": _normalize_values(statuses),
        "providers": _normalize_values(providers),
        "dataset_keys": _normalize_values(dataset_keys),
        "has_coord": has_coord,
        "has_issue": has_issue,
        "issue_types": _normalize_values(issue_types),
        "updated_from": updated_from,
        "updated_to": updated_to,
        "limit_plus_one": effective_limit + 1,
        **_cursor_params(cursor, sort=sort, order=order),
    }
    rows = (
        await session.execute(text(_admin_features_sql(sort=sort, order=order)), params)
    ).mappings().all()
    items = tuple(_admin_feature_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_cursor(items[-1], sort=sort, order=order)
        if len(rows) > effective_limit and items
        else None
    )
    return AdminFeaturePage(items=items, next_cursor=next_cursor)


_DEACTIVATE_FEATURE_SQL: Final[str] = """
WITH locked AS (
    SELECT feature_id, status, deleted_at
    FROM feature.features
    WHERE feature_id = :feature_id
    FOR UPDATE
),
updated AS (
    UPDATE feature.features AS f
    SET status = 'inactive', updated_at = now()
    FROM locked
    WHERE f.feature_id = locked.feature_id
      AND locked.deleted_at IS NULL
      AND locked.status <> 'deleted'
    RETURNING f.feature_id, locked.status AS previous_status, f.status
)
SELECT feature_id, previous_status, status
FROM updated
"""

_DEACTIVATE_FEATURE_STATE_SQL: Final[str] = """
SELECT feature_id, status, deleted_at
FROM feature.features
WHERE feature_id = :feature_id
FOR UPDATE
"""

_UPSERT_STATUS_OVERRIDE_SQL: Final[str] = """
INSERT INTO ops.feature_overrides (
    feature_id, source_record_key, field_path,
    source_value, override_value, prevent_provider_reactivation,
    status, reason, created_by
) VALUES (
    :feature_id, NULL, 'status',
    to_jsonb(CAST(:source_value AS text)),
    to_jsonb('inactive'::text),
    :prevent_provider_reactivation,
    'active', :reason, :operator
)
ON CONFLICT (feature_id, field_path) WHERE status = 'active'
DO UPDATE SET
    source_value = EXCLUDED.source_value,
    override_value = EXCLUDED.override_value,
    prevent_provider_reactivation = EXCLUDED.prevent_provider_reactivation,
    reason = EXCLUDED.reason,
    created_by = EXCLUDED.created_by,
    created_at = now()
RETURNING
    override_id::text,
    feature_id,
    field_path,
    override_value,
    prevent_provider_reactivation,
    reason,
    created_by,
    created_at
"""


def _feature_override(row: Any) -> FeatureOverride:
    value = row["override_value"]
    if isinstance(value, str):
        with suppress(json.JSONDecodeError):
            value = json.loads(value)
    return FeatureOverride(
        override_id=str(row["override_id"]),
        feature_id=str(row["feature_id"]),
        field_path=str(row["field_path"]),
        override_value=value,
        prevent_provider_reactivation=bool(row["prevent_provider_reactivation"]),
        reason=row["reason"],
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


async def deactivate_feature(
    session: AsyncSession,
    feature_id: str,
    *,
    reason: str,
    operator: str | None = None,
    prevent_provider_reactivation: bool = True,
) -> FeatureDeactivateResult | None:
    """feature를 inactive로 전환하고, 필요 시 active status override를 남긴다."""
    row = (
        await session.execute(
            text(_DEACTIVATE_FEATURE_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().first()
    if row is None:
        state_row = (
            await session.execute(
                text(_DEACTIVATE_FEATURE_STATE_SQL),
                {"feature_id": feature_id},
            )
        ).mappings().first()
        if state_row is not None:
            raise FeatureStateConflict(
                feature_id=str(state_row["feature_id"]),
                current_status=str(state_row["status"]),
                deleted_at=state_row["deleted_at"],
                target_status="inactive",
            )
        return None

    override = None
    if prevent_provider_reactivation:
        override_row = (
            await session.execute(
                text(_UPSERT_STATUS_OVERRIDE_SQL),
                {
                    "feature_id": feature_id,
                    "source_value": row["previous_status"],
                    "prevent_provider_reactivation": prevent_provider_reactivation,
                    "reason": reason,
                    "operator": operator,
                },
            )
        ).mappings().one()
        override = _feature_override(override_row)

    return FeatureDeactivateResult(
        feature_id=str(row["feature_id"]),
        previous_status=str(row["previous_status"]),
        status=str(row["status"]),
        override_created=override is not None,
        override=override,
    )


_INSERT_FEATURE_CHANGE_REQUEST_SQL: Final[str] = """
INSERT INTO ops.feature_change_requests (
    request_id, feature_id, action, state, review_mode,
    payload, reason, requested_by
) VALUES (
    x_extension.gen_random_uuid(), :feature_id, :action, :state, :review_mode,
    CAST(:payload AS jsonb), :reason, :requested_by
)
RETURNING
    request_id::text, feature_id, action, state, review_mode,
    payload, reason, requested_by, reviewed_by, reviewed_at, applied_at, created_at
"""

_GET_CHANGE_REQUEST_FOR_UPDATE_SQL: Final[str] = """
SELECT
    request_id::text, feature_id, action, state, review_mode,
    payload, reason, requested_by, reviewed_by, reviewed_at, applied_at, created_at
FROM ops.feature_change_requests
WHERE request_id::text = :request_id
FOR UPDATE
"""

_LIST_CHANGE_REQUESTS_SQL: Final[str] = """
SELECT
    request_id::text, feature_id, action, state, review_mode,
    payload, reason, requested_by, reviewed_by, reviewed_at, applied_at, created_at
FROM ops.feature_change_requests
WHERE (CAST(:states AS text[]) IS NULL OR state = ANY(CAST(:states AS text[])))
  AND (CAST(:actions AS text[]) IS NULL OR action = ANY(CAST(:actions AS text[])))
  AND (
    CAST(:q_like AS text) IS NULL
    OR feature_id ILIKE CAST(:q_like AS text)
    OR requested_by ILIKE CAST(:q_like AS text)
    OR reason ILIKE CAST(:q_like AS text)
  )
ORDER BY created_at DESC, request_id DESC
LIMIT :limit
"""

_FEATURE_CHANGE_STATE_SQL: Final[str] = """
SELECT feature_id, kind, status, user_deleted_at
FROM feature.features
WHERE feature_id = :feature_id
FOR UPDATE
"""

_APPLY_FEATURE_ADD_SQL: Final[str] = """
INSERT INTO feature.features (
    feature_id, kind, name, category,
    coord, coord_precision_digits, geom,
    address, legal_dong_code, road_name_code, road_address_management_no,
    admin_dong_code, sido_code, sigungu_code,
    urls, marker_icon, marker_color,
    parent_feature_id, sibling_group_id,
    detail, raw_refs, status,
    data_origin, data_version, user_change_kind, user_change_status,
    user_change_request_id, user_deleted_at, user_deleted_by, user_change_reason,
    created_at, updated_at, deleted_at
) VALUES (
    :feature_id, :kind, :name, :category,
    CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
         ELSE x_extension.ST_SetSRID(
             x_extension.ST_MakePoint(
                 CAST(:lon AS double precision),
                 CAST(:lat AS double precision)
             ),
             4326
         ) END,
    :coord_precision_digits,
    CASE WHEN CAST(:geom_wkt AS text) IS NULL THEN NULL
         ELSE x_extension.ST_SetSRID(
             x_extension.ST_GeomFromText(CAST(:geom_wkt AS text)), 4326
         ) END,
    CAST(:address AS jsonb), :legal_dong_code, :road_name_code,
    :road_address_management_no, :admin_dong_code, :sido_code, :sigungu_code,
    CAST(:urls AS jsonb), :marker_icon, :marker_color,
    :parent_feature_id, :sibling_group_id,
    CAST(:detail AS jsonb), '[]'::jsonb, :status,
    'user_request', 1, 'add', 'applied',
    CAST(:request_id AS uuid), NULL, NULL, :reason,
    now(), now(), NULL
)
ON CONFLICT (feature_id) DO UPDATE SET
    kind = EXCLUDED.kind,
    name = EXCLUDED.name,
    category = EXCLUDED.category,
    coord = EXCLUDED.coord,
    coord_precision_digits = EXCLUDED.coord_precision_digits,
    geom = EXCLUDED.geom,
    address = EXCLUDED.address,
    legal_dong_code = EXCLUDED.legal_dong_code,
    road_name_code = EXCLUDED.road_name_code,
    road_address_management_no = EXCLUDED.road_address_management_no,
    admin_dong_code = EXCLUDED.admin_dong_code,
    sido_code = EXCLUDED.sido_code,
    sigungu_code = EXCLUDED.sigungu_code,
    urls = EXCLUDED.urls,
    marker_icon = EXCLUDED.marker_icon,
    marker_color = EXCLUDED.marker_color,
    parent_feature_id = EXCLUDED.parent_feature_id,
    sibling_group_id = EXCLUDED.sibling_group_id,
    detail = EXCLUDED.detail,
    status = EXCLUDED.status,
    data_origin = 'user_request',
    data_version = GREATEST(features.data_version, 1),
    user_change_kind = 'add',
    user_change_status = 'applied',
    user_change_request_id = CAST(:request_id AS uuid),
    user_deleted_at = NULL,
    user_deleted_by = NULL,
    user_change_reason = :reason,
    updated_at = now(),
    deleted_at = NULL
WHERE features.user_deleted_at IS NULL
  AND features.status <> 'deleted'
  AND features.kind IN ('place','event')
RETURNING feature_id, status, user_deleted_at
"""

_APPLY_FEATURE_UPDATE_SQL: Final[str] = """
UPDATE feature.features AS f
SET
    name = CASE WHEN CAST(:name_set AS boolean) THEN CAST(:name AS text) ELSE f.name END,
    category = CASE
        WHEN CAST(:category_set AS boolean) THEN CAST(:category AS text)
        ELSE f.category
    END,
    coord = CASE
        WHEN CAST(:coord_set AS boolean) THEN x_extension.ST_SetSRID(
            x_extension.ST_MakePoint(
                CAST(:lon AS double precision),
                CAST(:lat AS double precision)
            ),
            4326
        )
        ELSE f.coord
    END,
    coord_precision_digits = CASE
        WHEN CAST(:coord_set AS boolean) THEN CAST(:coord_precision_digits AS smallint)
        ELSE f.coord_precision_digits
    END,
    geom = CASE
        WHEN CAST(:geom_set AS boolean) THEN
            CASE WHEN CAST(:geom_wkt AS text) IS NULL THEN NULL
                 ELSE x_extension.ST_SetSRID(
                     x_extension.ST_GeomFromText(CAST(:geom_wkt AS text)), 4326
                 ) END
        ELSE f.geom
    END,
    address = CASE
        WHEN CAST(:address_set AS boolean) THEN CAST(:address AS jsonb)
        ELSE f.address
    END,
    legal_dong_code = CASE
        WHEN CAST(:legal_dong_code_set AS boolean) THEN CAST(:legal_dong_code AS text)
        ELSE f.legal_dong_code
    END,
    road_name_code = CASE
        WHEN CAST(:road_name_code_set AS boolean) THEN CAST(:road_name_code AS text)
        ELSE f.road_name_code
    END,
    road_address_management_no = CASE
        WHEN CAST(:road_address_management_no_set AS boolean) THEN
            CAST(:road_address_management_no AS text)
        ELSE f.road_address_management_no
    END,
    admin_dong_code = CASE
        WHEN CAST(:admin_dong_code_set AS boolean) THEN CAST(:admin_dong_code AS text)
        ELSE f.admin_dong_code
    END,
    sido_code = CASE
        WHEN CAST(:sido_code_set AS boolean) THEN CAST(:sido_code AS text)
        ELSE f.sido_code
    END,
    sigungu_code = CASE
        WHEN CAST(:sigungu_code_set AS boolean) THEN CAST(:sigungu_code AS text)
        ELSE f.sigungu_code
    END,
    urls = CASE WHEN CAST(:urls_set AS boolean) THEN CAST(:urls AS jsonb) ELSE f.urls END,
    marker_icon = CASE
        WHEN CAST(:marker_icon_set AS boolean) THEN CAST(:marker_icon AS text)
        ELSE f.marker_icon
    END,
    marker_color = CASE
        WHEN CAST(:marker_color_set AS boolean) THEN CAST(:marker_color AS text)
        ELSE f.marker_color
    END,
    detail = CASE
        WHEN CAST(:detail_set AS boolean) THEN CAST(:detail AS jsonb)
        ELSE f.detail
    END,
    parent_feature_id = CASE
        WHEN CAST(:parent_feature_id_set AS boolean) THEN CAST(:parent_feature_id AS text)
        ELSE f.parent_feature_id
    END,
    sibling_group_id = CASE
        WHEN CAST(:sibling_group_id_set AS boolean) THEN CAST(:sibling_group_id AS uuid)
        ELSE f.sibling_group_id
    END,
    data_origin = 'user_request',
    data_version = GREATEST(f.data_version, 1),
    user_change_kind = 'update',
    user_change_status = 'applied',
    user_change_request_id = CAST(:request_id AS uuid),
    user_change_reason = :reason,
    updated_at = now()
WHERE f.feature_id = :feature_id
  AND f.kind IN ('place','event')
  AND f.status <> 'deleted'
  AND f.user_deleted_at IS NULL
RETURNING f.feature_id, f.status, f.user_deleted_at
"""

_APPLY_FEATURE_DELETE_SQL: Final[str] = """
UPDATE feature.features AS f
SET
    status = 'deleted',
    deleted_at = now(),
    data_origin = 'user_request',
    data_version = GREATEST(f.data_version, 1),
    user_change_kind = 'delete',
    user_change_status = 'applied',
    user_change_request_id = CAST(:request_id AS uuid),
    user_deleted_at = now(),
    user_deleted_by = :operator,
    user_change_reason = :reason,
    updated_at = now()
WHERE f.feature_id = :feature_id
  AND f.kind IN ('place','event')
  AND f.status <> 'deleted'
  AND f.user_deleted_at IS NULL
RETURNING f.feature_id, f.status, f.user_deleted_at
"""

_NEXT_USER_VERSION_SQL: Final[str] = """
SELECT COALESCE(MAX(version), 0) + 1
FROM feature.feature_versions
WHERE feature_id = :feature_id
"""

_SET_FEATURE_DATA_VERSION_SQL: Final[str] = """
UPDATE feature.features
SET data_version = :version,
    updated_at = now()
WHERE feature_id = :feature_id
"""

_INSERT_USER_VERSION_FROM_FEATURE_SQL: Final[str] = """
INSERT INTO feature.feature_versions (
    feature_id, version, origin, change_kind, payload, request_id, created_by
)
SELECT
    f.feature_id,
    CAST(:version AS integer),
    'user_request',
    :change_kind,
    jsonb_build_object(
        'feature_id', f.feature_id,
        'kind', f.kind,
        'name', f.name,
        'category', f.category,
        'lon', x_extension.ST_X(f.coord),
        'lat', x_extension.ST_Y(f.coord),
        'coord_precision_digits', f.coord_precision_digits,
        'address', f.address,
        'legal_dong_code', f.legal_dong_code,
        'road_name_code', f.road_name_code,
        'road_address_management_no', f.road_address_management_no,
        'admin_dong_code', f.admin_dong_code,
        'sido_code', f.sido_code,
        'sigungu_code', f.sigungu_code,
        'urls', f.urls,
        'marker_icon', f.marker_icon,
        'marker_color', f.marker_color,
        'parent_feature_id', f.parent_feature_id,
        'sibling_group_id', f.sibling_group_id,
        'detail', f.detail,
        'status', f.status,
        'data_origin', f.data_origin,
        'data_version', f.data_version,
        'user_change_kind', f.user_change_kind,
        'user_change_status', f.user_change_status,
        'user_deleted_at', f.user_deleted_at,
        'deleted_at', f.deleted_at,
        'updated_at', f.updated_at
    ),
    CAST(:request_id AS uuid),
    :operator
FROM feature.features AS f
WHERE f.feature_id = :feature_id
"""

_MARK_CHANGE_APPLIED_SQL: Final[str] = """
UPDATE ops.feature_change_requests
SET state = 'applied',
    reviewed_by = COALESCE(:operator, reviewed_by),
    reviewed_at = COALESCE(reviewed_at, now()),
    applied_at = now()
WHERE request_id::text = :request_id
RETURNING
    request_id::text, feature_id, action, state, review_mode,
    payload, reason, requested_by, reviewed_by, reviewed_at, applied_at, created_at
"""

_MARK_CHANGE_REJECTED_SQL: Final[str] = """
UPDATE ops.feature_change_requests
SET state = 'rejected',
    reviewed_by = :operator,
    reviewed_at = now(),
    reason = COALESCE(:reason, reason)
WHERE request_id::text = :request_id
  AND state = 'pending'
RETURNING
    request_id::text, feature_id, action, state, review_mode,
    payload, reason, requested_by, reviewed_by, reviewed_at, applied_at, created_at
"""


def _feature_change_row(row: Any) -> FeatureChangeRequest:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return FeatureChangeRequest(
        request_id=str(row["request_id"]),
        feature_id=str(row["feature_id"]),
        action=str(row["action"]),
        state=str(row["state"]),
        review_mode=str(row["review_mode"]),
        payload=dict(payload or {}),
        reason=row["reason"],
        requested_by=row["requested_by"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        applied_at=row["applied_at"],
        created_at=row["created_at"],
    )


def _change_payload_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _json_param(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _add_params(
    *,
    request_id: str,
    feature_id: str,
    payload: dict[str, Any],
    reason: str | None,
) -> dict[str, Any]:
    coord = payload.get("coord") or {}
    return {
        "request_id": request_id,
        "feature_id": feature_id,
        "kind": payload["kind"],
        "name": payload["name"],
        "category": payload["category"],
        "lon": coord.get("lon"),
        "lat": coord.get("lat"),
        "coord_precision_digits": payload.get("coord_precision_digits") or (
            6 if coord else None
        ),
        "geom_wkt": payload.get("geom"),
        "address": _json_param(payload.get("address")),
        "legal_dong_code": payload.get("legal_dong_code"),
        "road_name_code": payload.get("road_name_code"),
        "road_address_management_no": payload.get("road_address_management_no"),
        "admin_dong_code": payload.get("admin_dong_code"),
        "sido_code": payload.get("sido_code"),
        "sigungu_code": payload.get("sigungu_code"),
        "urls": _json_param(payload.get("urls")),
        "marker_icon": payload["marker_icon"],
        "marker_color": payload["marker_color"],
        "parent_feature_id": payload.get("parent_feature_id"),
        "sibling_group_id": payload.get("sibling_group_id"),
        "detail": _json_param(payload.get("detail")),
        "status": payload.get("status") or "active",
        "reason": reason,
    }


def _update_params(
    *,
    request_id: str,
    feature_id: str,
    payload: dict[str, Any],
    reason: str | None,
) -> dict[str, Any]:
    coord = payload.get("coord") if "coord" in payload else None
    return {
        "request_id": request_id,
        "feature_id": feature_id,
        "name_set": "name" in payload,
        "name": payload.get("name"),
        "category_set": "category" in payload,
        "category": payload.get("category"),
        "coord_set": coord is not None,
        "lon": coord.get("lon") if isinstance(coord, dict) else None,
        "lat": coord.get("lat") if isinstance(coord, dict) else None,
        "coord_precision_digits": payload.get("coord_precision_digits") or (
            6 if coord is not None else None
        ),
        "geom_set": "geom" in payload,
        "geom_wkt": payload.get("geom"),
        "address_set": "address" in payload,
        "address": _json_param(payload.get("address")),
        "legal_dong_code_set": "legal_dong_code" in payload,
        "legal_dong_code": payload.get("legal_dong_code"),
        "road_name_code_set": "road_name_code" in payload,
        "road_name_code": payload.get("road_name_code"),
        "road_address_management_no_set": "road_address_management_no" in payload,
        "road_address_management_no": payload.get("road_address_management_no"),
        "admin_dong_code_set": "admin_dong_code" in payload,
        "admin_dong_code": payload.get("admin_dong_code"),
        "sido_code_set": "sido_code" in payload,
        "sido_code": payload.get("sido_code"),
        "sigungu_code_set": "sigungu_code" in payload,
        "sigungu_code": payload.get("sigungu_code"),
        "urls_set": "urls" in payload,
        "urls": _json_param(payload.get("urls")),
        "marker_icon_set": "marker_icon" in payload,
        "marker_icon": payload.get("marker_icon"),
        "marker_color_set": "marker_color" in payload,
        "marker_color": payload.get("marker_color"),
        "detail_set": "detail" in payload,
        "detail": _json_param(payload.get("detail")),
        "parent_feature_id_set": "parent_feature_id" in payload,
        "parent_feature_id": payload.get("parent_feature_id"),
        "sibling_group_id_set": "sibling_group_id" in payload,
        "sibling_group_id": payload.get("sibling_group_id"),
        "reason": reason,
    }


async def _state_for_conflict(
    session: AsyncSession, feature_id: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(_FEATURE_CHANGE_STATE_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().first()
    return dict(row) if row is not None else None


async def _apply_change(
    session: AsyncSession,
    request: FeatureChangeRequest,
    *,
    operator: str | None,
) -> None:
    payload = request.payload
    if request.action == "add":
        row = (
            await session.execute(
                text(_APPLY_FEATURE_ADD_SQL),
                _add_params(
                    request_id=request.request_id,
                    feature_id=request.feature_id,
                    payload=payload,
                    reason=request.reason,
                ),
            )
        ).mappings().first()
    elif request.action == "update":
        row = (
            await session.execute(
                text(_APPLY_FEATURE_UPDATE_SQL),
                _update_params(
                    request_id=request.request_id,
                    feature_id=request.feature_id,
                    payload=payload,
                    reason=request.reason,
                ),
            )
        ).mappings().first()
    else:
        row = (
            await session.execute(
                text(_APPLY_FEATURE_DELETE_SQL),
                {
                    "request_id": request.request_id,
                    "feature_id": request.feature_id,
                    "operator": operator,
                    "reason": request.reason,
                },
            )
        ).mappings().first()

    if row is None:
        state = await _state_for_conflict(session, request.feature_id)
        if state is None:
            raise FeatureChangeConflict(
                feature_id=request.feature_id,
                action=request.action,
                message=f"feature 없음: {request.feature_id!r}",
            )
        raise FeatureChangeConflict(
            feature_id=str(state["feature_id"]),
            action=request.action,
            current_status=str(state["status"]),
            user_deleted_at=state["user_deleted_at"],
        )

    next_version = int(
        (
            await session.execute(
                text(_NEXT_USER_VERSION_SQL),
                {"feature_id": request.feature_id},
            )
        ).scalar_one()
    )
    await session.execute(
        text(_SET_FEATURE_DATA_VERSION_SQL),
        {"feature_id": request.feature_id, "version": next_version},
    )
    await session.execute(
        text(_INSERT_USER_VERSION_FROM_FEATURE_SQL),
        {
            "feature_id": request.feature_id,
            "version": next_version,
            "request_id": request.request_id,
            "change_kind": request.action,
            "operator": operator,
        },
    )


async def submit_feature_change_request(
    session: AsyncSession,
    *,
    action: FeatureChangeAction,
    feature_id: str,
    payload: dict[str, Any],
    review_mode: FeatureChangeReviewMode,
    reason: str | None,
    requested_by: str | None,
) -> FeatureChangeRequest:
    """feature add/update/delete 요청을 만들고 설정에 따라 즉시 적용한다."""
    initial_state = "applied" if review_mode == "immediate" else "pending"
    row = (
        await session.execute(
            text(_INSERT_FEATURE_CHANGE_REQUEST_SQL),
            {
                "feature_id": feature_id,
                "action": action,
                "state": initial_state,
                "review_mode": review_mode,
                "payload": _change_payload_json(payload),
                "reason": reason,
                "requested_by": requested_by,
            },
        )
    ).mappings().one()
    request = _feature_change_row(row)
    if review_mode == "immediate":
        await _apply_change(session, request, operator=requested_by)
        applied = (
            await session.execute(
                text(_MARK_CHANGE_APPLIED_SQL),
                {"request_id": request.request_id, "operator": requested_by},
            )
        ).mappings().one()
        return _feature_change_row(applied)
    return request


async def apply_feature_change_request(
    session: AsyncSession,
    request_id: str,
    *,
    operator: str | None,
) -> FeatureChangeRequest | None:
    """pending feature change request를 승인하고 적용한다."""
    row = (
        await session.execute(
            text(_GET_CHANGE_REQUEST_FOR_UPDATE_SQL),
            {"request_id": request_id},
        )
    ).mappings().first()
    if row is None:
        return None
    request = _feature_change_row(row)
    if request.state != "pending":
        raise FeatureChangeConflict(
            feature_id=request.feature_id,
            action=request.action,
            message=f"request {request_id!r}는 pending 상태가 아님: {request.state!r}",
        )
    await _apply_change(session, request, operator=operator)
    applied = (
        await session.execute(
            text(_MARK_CHANGE_APPLIED_SQL),
            {"request_id": request_id, "operator": operator},
        )
    ).mappings().one()
    return _feature_change_row(applied)


async def reject_feature_change_request(
    session: AsyncSession,
    request_id: str,
    *,
    operator: str | None,
    reason: str | None,
) -> FeatureChangeRequest | None:
    """pending feature change request를 거절한다."""
    row = (
        await session.execute(
            text(_MARK_CHANGE_REJECTED_SQL),
            {"request_id": request_id, "operator": operator, "reason": reason},
        )
    ).mappings().first()
    return _feature_change_row(row) if row is not None else None


async def list_feature_change_requests(
    session: AsyncSession,
    *,
    states: Sequence[str] | None = None,
    actions: Sequence[str] | None = None,
    q: str | None = None,
    limit: int = 100,
) -> tuple[FeatureChangeRequest, ...]:
    """feature change request 목록."""
    normalized_q = _normalize_query(q)
    rows = (
        await session.execute(
            text(_LIST_CHANGE_REQUESTS_SQL),
            {
                "states": _normalize_values(states),
                "actions": _normalize_values(actions),
                "q_like": f"%{normalized_q}%" if normalized_q is not None else None,
                "limit": min(max(limit, 1), 500),
            },
        )
    ).mappings().all()
    return tuple(_feature_change_row(row) for row in rows)


_DEDUP_REVIEW_SQL: Final[str] = """
WITH reviews AS MATERIALIZED (
    SELECT
        q.review_id,
        q.status,
        q.total_score,
        q.name_score,
        q.spatial_score,
        q.category_score,
        q.feature_id_a,
        q.feature_id_b,
        q.decision_reason,
        q.reviewed_by,
        q.reviewed_at,
        q.created_at
    FROM ops.dedup_review_queue AS q
    WHERE (CAST(:statuses AS text[]) IS NULL OR q.status = ANY(CAST(:statuses AS text[])))
      AND (
        CAST(:min_score AS numeric) IS NULL
        OR q.total_score >= CAST(:min_score AS numeric)
      )
      AND (
        CAST(:max_score AS numeric) IS NULL
        OR q.total_score <= CAST(:max_score AS numeric)
      )
      AND (
        CAST(:cursor_score AS numeric) IS NULL
        OR (q.total_score, q.review_id) < (
            CAST(:cursor_score AS numeric),
            CAST(:cursor_review_id AS uuid)
        )
      )
    ORDER BY q.total_score DESC, q.review_id DESC
),
expanded AS (
    SELECT
        r.*,
        fa.name AS name_a,
        fa.kind AS kind_a,
        fa.category AS category_a,
        x_extension.ST_X(fa.coord) AS lon_a,
        x_extension.ST_Y(fa.coord) AS lat_a,
        psa.provider AS provider_a,
        psa.dataset_key AS dataset_key_a,
        fb.name AS name_b,
        fb.kind AS kind_b,
        fb.category AS category_b,
        x_extension.ST_X(fb.coord) AS lon_b,
        x_extension.ST_Y(fb.coord) AS lat_b,
        psb.provider AS provider_b,
        psb.dataset_key AS dataset_key_b,
        CASE
            WHEN fa.coord_5179 IS NULL OR fb.coord_5179 IS NULL THEN NULL
            ELSE x_extension.ST_Distance(fa.coord_5179, fb.coord_5179)::double precision
        END AS distance_m
    FROM reviews AS r
    JOIN feature.features AS fa ON fa.feature_id = r.feature_id_a
    JOIN feature.features AS fb ON fb.feature_id = r.feature_id_b
    LEFT JOIN LATERAL (
        SELECT sr.provider, sr.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = sl.source_record_key
        WHERE sl.feature_id = fa.feature_id
          AND sl.is_primary_source
        ORDER BY sr.imported_at DESC NULLS LAST, sr.source_record_key
        LIMIT 1
    ) AS psa ON TRUE
    LEFT JOIN LATERAL (
        SELECT sr.provider, sr.dataset_key
        FROM provider_sync.source_links AS sl
        JOIN provider_sync.source_records AS sr
          ON sr.source_record_key = sl.source_record_key
        WHERE sl.feature_id = fb.feature_id
          AND sl.is_primary_source
        ORDER BY sr.imported_at DESC NULLS LAST, sr.source_record_key
        LIMIT 1
    ) AS psb ON TRUE
)
SELECT *
FROM expanded
WHERE (
    CAST(:q_like AS text) IS NULL
    OR feature_id_a ILIKE CAST(:q_like AS text)
    OR feature_id_b ILIKE CAST(:q_like AS text)
    OR name_a ILIKE CAST(:q_like AS text)
    OR name_b ILIKE CAST(:q_like AS text)
)
  AND (
    CAST(:providers AS text[]) IS NULL
    OR provider_a = ANY(CAST(:providers AS text[]))
    OR provider_b = ANY(CAST(:providers AS text[]))
  )
  AND (
    CAST(:dataset_keys AS text[]) IS NULL
    OR dataset_key_a = ANY(CAST(:dataset_keys AS text[]))
    OR dataset_key_b = ANY(CAST(:dataset_keys AS text[]))
  )
  AND (
    CAST(:kinds AS text[]) IS NULL
    OR kind_a = ANY(CAST(:kinds AS text[]))
    OR kind_b = ANY(CAST(:kinds AS text[]))
  )
  AND (
    CAST(:categories AS text[]) IS NULL
    OR category_a = ANY(CAST(:categories AS text[]))
    OR category_b = ANY(CAST(:categories AS text[]))
  )
ORDER BY total_score DESC, review_id DESC
LIMIT :limit_plus_one
"""


def _dedup_cursor_payload(cursor: str | None) -> dict[str, Any]:
    if cursor is None:
        return {}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid dedup review cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid dedup review cursor")
    if not isinstance(payload.get("review_id"), str):
        raise ValueError("invalid dedup review cursor")
    return payload


def _dedup_cursor_params(cursor: str | None) -> dict[str, Any]:
    payload = _dedup_cursor_payload(cursor)
    if not payload:
        return {"cursor_score": None, "cursor_review_id": None}
    try:
        score = str(payload["total_score"])
        Decimal(score)
        UUID(str(payload["review_id"]))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("invalid dedup review cursor") from exc
    return {"cursor_score": score, "cursor_review_id": payload["review_id"]}


def _encode_dedup_cursor(item: DedupReviewRow) -> str:
    raw = json.dumps(
        {
            "review_id": item.review_id,
            "total_score": (
                item.total_score_cursor
                if item.total_score_cursor is not None
                else str(Decimal(str(item.total_score)))
            ),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _score(value: Any) -> float:
    return float(value) if value is not None else 0.0


def _dedup_feature(row: Any, suffix: str) -> DedupFeatureSummary:
    return DedupFeatureSummary(
        feature_id=str(row[f"feature_id_{suffix}"]),
        name=str(row[f"name_{suffix}"]),
        kind=str(row[f"kind_{suffix}"]),
        category=str(row[f"category_{suffix}"]),
        lon=float(row[f"lon_{suffix}"]) if row[f"lon_{suffix}"] is not None else None,
        lat=float(row[f"lat_{suffix}"]) if row[f"lat_{suffix}"] is not None else None,
        provider=row[f"provider_{suffix}"],
        dataset_key=row[f"dataset_key_{suffix}"],
    )


def _dedup_review_row(row: Any) -> DedupReviewRow:
    return DedupReviewRow(
        review_id=str(row["review_id"]),
        status=str(row["status"]),
        total_score=_score(row["total_score"]),
        name_score=_score(row["name_score"]),
        spatial_score=_score(row["spatial_score"]),
        category_score=_score(row["category_score"]),
        total_score_cursor=str(row["total_score"]),
        feature_a=_dedup_feature(row, "a"),
        feature_b=_dedup_feature(row, "b"),
        distance_m=(
            float(row["distance_m"]) if row["distance_m"] is not None else None
        ),
        decision_reason=row["decision_reason"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        created_at=row["created_at"],
    )


async def list_dedup_reviews(
    session: AsyncSession,
    *,
    statuses: Sequence[str] | None = ("pending",),
    providers: Sequence[str] | None = None,
    dataset_keys: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    q: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> DedupReviewPage:
    """Dedup review 목록을 점수 내림차순 cursor로 조회한다."""
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    effective_limit = min(page_size, 500)
    normalized_q = _normalize_query(q)
    rows = (
        await session.execute(
            text(_DEDUP_REVIEW_SQL),
            {
                "statuses": _normalize_values(statuses),
                "providers": _normalize_values(providers),
                "dataset_keys": _normalize_values(dataset_keys),
                "kinds": _normalize_values(kinds),
                "categories": _normalize_values(categories),
                "min_score": min_score,
                "max_score": max_score,
                "q_like": f"%{normalized_q}%" if normalized_q is not None else None,
                "limit_plus_one": effective_limit + 1,
                **_dedup_cursor_params(cursor),
            },
        )
    ).mappings().all()
    items = tuple(_dedup_review_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_dedup_cursor(items[-1])
        if len(rows) > effective_limit and items
        else None
    )
    return DedupReviewPage(items=items, next_cursor=next_cursor)


_SET_DEDUP_DECISION_SQL: Final[str] = """
UPDATE ops.dedup_review_queue
SET status = :decision,
    reviewed_at = now(),
    reviewed_by = :reviewed_by,
    decision_reason = COALESCE(:decision_reason, decision_reason)
WHERE review_id = :review_id
  AND status = 'pending'
  AND :decision = ANY(CAST(ARRAY['accepted','rejected','ignored'] AS text[]))
RETURNING review_id::text
"""

_SELECT_DEDUP_PAIR_SQL: Final[str] = """
SELECT feature_id_a, feature_id_b, total_score, status
FROM ops.dedup_review_queue
WHERE review_id = :review_id
FOR UPDATE
"""


async def set_dedup_review_decision(
    session: AsyncSession,
    review_id: str,
    *,
    decision: DedupDecision,
    reviewed_by: str | None = None,
    decision_reason: str | None = None,
) -> bool:
    """pending dedup review를 accepted/rejected/ignored로 전이한다."""
    row = (
        await session.execute(
            text(_SET_DEDUP_DECISION_SQL),
            {
                "review_id": review_id,
                "decision": decision,
                "reviewed_by": reviewed_by,
                "decision_reason": decision_reason,
            },
        )
    ).first()
    return row is not None


async def merge_dedup_review(
    session: AsyncSession,
    review_id: str,
    *,
    master_feature_id: str | None = None,
    merged_by: str | None = None,
    reason: str | None = None,
) -> MergeOutcome:
    """dedup review를 병합한다. ``master_feature_id``가 없으면 기존 자동 선정."""
    if master_feature_id is None:
        return await merge_from_review(
            session, review_id, merged_by=merged_by, reason=reason
        )

    row = (
        await session.execute(text(_SELECT_DEDUP_PAIR_SQL), {"review_id": review_id})
    ).one_or_none()
    if row is None:
        raise MergeNotFoundError(f"review_id 없음 — {review_id!r}")
    if row.status != "pending":
        raise MergeConflictError(
            f"이미 검토된 후보(status={row.status!r}) — {review_id!r}"
        )
    if master_feature_id == row.feature_id_a:
        loser_id = row.feature_id_b
    elif master_feature_id == row.feature_id_b:
        loser_id = row.feature_id_a
    else:
        raise MergeConflictError(
            "master_feature_id가 review 후보 쌍에 없음 — "
            f"{master_feature_id!r}"
        )
    return await apply_feature_merge(
        session,
        master_id=master_feature_id,
        loser_id=loser_id,
        score=float(row.total_score) if row.total_score is not None else None,
        review_id=review_id,
        merged_by=merged_by,
        reason=reason,
    )


# =============================================================================
# 축제 enrichment review (T-RV-52c) — ops.enrichment_review_queue 조회
# =============================================================================


@dataclass(frozen=True)
class EnrichmentReviewRow:
    """``GET /admin/enrichment-review`` item.

    enrichment은 두 번째 feature/병합이 없어 dedup보다 단순하다 — 1차(target) feature를
    join해 표시하고, source(2차, visitkorea)는 큐에 보관된 식별/이름만 노출한다.
    """

    review_id: str
    status: str
    name_score: float
    target_feature_id: str
    target_name: str
    target_kind: str | None
    target_category: str | None
    target_lon: float | None
    target_lat: float | None
    source_provider: str
    source_dataset_key: str
    source_entity_id: str
    source_name: str
    decision_reason: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    created_at: datetime
    name_score_cursor: str | None = None


@dataclass(frozen=True)
class EnrichmentReviewPage:
    """Enrichment review page."""

    items: tuple[EnrichmentReviewRow, ...]
    next_cursor: str | None


_ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER: Final[str] = """
    WHERE (CAST(:statuses AS text[]) IS NULL OR q.status = ANY(CAST(:statuses AS text[])))
"""

_ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER: Final[str] = """
    WHERE q.status = ANY(CAST(:statuses AS text[]))
"""

_ENRICHMENT_REVIEW_SCALAR_STATUS_FILTER: Final[str] = """
    WHERE q.status = CAST(:status AS text)
"""

_ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER: Final[str] = """
      AND (
        CAST(:providers AS text[]) IS NULL
        OR q.source_provider = ANY(CAST(:providers AS text[]))
      )
"""

_ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER: Final[str] = """
      AND q.source_provider = ANY(CAST(:providers AS text[]))
"""

_ENRICHMENT_REVIEW_SCALAR_PROVIDER_FILTER: Final[str] = """
      AND q.source_provider = CAST(:provider AS text)
"""


def _enrichment_review_sql(status_filter: str, provider_filter: str) -> str:
    return f"""
WITH reviews AS MATERIALIZED (
    SELECT
        q.review_id,
        q.status,
        q.name_score,
        q.target_feature_id,
        q.target_name,
        q.source_provider,
        q.source_dataset_key,
        q.source_entity_id,
        q.source_name,
        q.decision_reason,
        q.reviewed_by,
        q.reviewed_at,
        q.created_at
    FROM ops.enrichment_review_queue AS q
{status_filter.rstrip()}
      AND (
        CAST(:min_score AS numeric) IS NULL
        OR q.name_score >= CAST(:min_score AS numeric)
      )
      AND (
        CAST(:max_score AS numeric) IS NULL
        OR q.name_score <= CAST(:max_score AS numeric)
      )
{provider_filter.rstrip()}
      AND (
        CAST(:q_like AS text) IS NULL
        OR q.target_feature_id ILIKE CAST(:q_like AS text)
        OR q.target_name ILIKE CAST(:q_like AS text)
        OR q.source_name ILIKE CAST(:q_like AS text)
        OR q.source_entity_id ILIKE CAST(:q_like AS text)
      )
      AND (
        CAST(:cursor_score AS numeric) IS NULL
        OR (q.name_score, q.review_id) < (
            CAST(:cursor_score AS numeric),
            CAST(:cursor_review_id AS uuid)
        )
    )
    ORDER BY q.name_score DESC, q.review_id DESC
    LIMIT :limit_plus_one
)
SELECT
    q.review_id,
    q.status,
    q.name_score,
    q.target_feature_id,
    q.target_name,
    q.source_provider,
    q.source_dataset_key,
    q.source_entity_id,
    q.source_name,
    q.decision_reason,
    q.reviewed_by,
    q.reviewed_at,
    q.created_at,
    f.kind AS target_kind,
    f.category AS target_category,
    x_extension.ST_X(f.coord) AS target_lon,
    x_extension.ST_Y(f.coord) AS target_lat
FROM reviews AS q
LEFT JOIN feature.features AS f ON f.feature_id = q.target_feature_id
ORDER BY q.name_score DESC, q.review_id DESC
LIMIT :limit_plus_one
"""


_ENRICHMENT_REVIEW_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER,
    _ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER
)
_ENRICHMENT_REVIEW_STATUS_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER,
    _ENRICHMENT_REVIEW_OPTIONAL_PROVIDER_FILTER,
)
_ENRICHMENT_REVIEW_PROVIDER_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_OPTIONAL_STATUS_FILTER,
    _ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER
)
_ENRICHMENT_REVIEW_STATUS_PROVIDER_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_REQUIRED_STATUS_FILTER,
    _ENRICHMENT_REVIEW_REQUIRED_PROVIDER_FILTER,
)
_ENRICHMENT_REVIEW_SCALAR_STATUS_PROVIDER_SQL: Final[str] = _enrichment_review_sql(
    _ENRICHMENT_REVIEW_SCALAR_STATUS_FILTER,
    _ENRICHMENT_REVIEW_SCALAR_PROVIDER_FILTER,
)


def _enrichment_cursor_params(cursor: str | None) -> dict[str, Any]:
    payload = _dedup_cursor_payload(cursor)
    if not payload:
        return {"cursor_score": None, "cursor_review_id": None}
    try:
        score = str(payload["name_score"])
        Decimal(score)
        UUID(str(payload["review_id"]))
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("invalid enrichment review cursor") from exc
    return {"cursor_score": score, "cursor_review_id": payload["review_id"]}


def _encode_enrichment_cursor(item: EnrichmentReviewRow) -> str:
    raw = json.dumps(
        {
            "review_id": item.review_id,
            "name_score": (
                item.name_score_cursor
                if item.name_score_cursor is not None
                else str(Decimal(str(item.name_score)))
            ),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _enrichment_review_row(row: Any) -> EnrichmentReviewRow:
    return EnrichmentReviewRow(
        review_id=str(row["review_id"]),
        status=str(row["status"]),
        name_score=_score(row["name_score"]),
        name_score_cursor=str(row["name_score"]),
        target_feature_id=str(row["target_feature_id"]),
        target_name=str(row["target_name"]),
        target_kind=row["target_kind"],
        target_category=row["target_category"],
        target_lon=(
            float(row["target_lon"]) if row["target_lon"] is not None else None
        ),
        target_lat=(
            float(row["target_lat"]) if row["target_lat"] is not None else None
        ),
        source_provider=str(row["source_provider"]),
        source_dataset_key=str(row["source_dataset_key"]),
        source_entity_id=str(row["source_entity_id"]),
        source_name=str(row["source_name"]),
        decision_reason=row["decision_reason"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        created_at=row["created_at"],
    )


async def list_enrichment_reviews(
    session: AsyncSession,
    *,
    statuses: Sequence[str] | None = ("pending",),
    providers: Sequence[str] | None = None,
    min_score: float | None = None,
    max_score: float | None = None,
    q: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> EnrichmentReviewPage:
    """축제 enrichment review 목록을 name_score 내림차순 cursor로 조회한다."""
    if page_size <= 0:
        raise ValueError("page_size must be greater than 0")
    effective_limit = min(page_size, 500)
    normalized_q = _normalize_query(q)
    status_values = _normalize_values(statuses)
    provider_values = _normalize_values(providers)
    status_value = status_values[0] if status_values and len(status_values) == 1 else None
    provider_value = (
        provider_values[0] if provider_values and len(provider_values) == 1 else None
    )
    review_sql = _ENRICHMENT_REVIEW_SQL
    if status_value is not None and provider_value is not None:
        review_sql = _ENRICHMENT_REVIEW_SCALAR_STATUS_PROVIDER_SQL
    elif status_values is not None and provider_values is not None:
        review_sql = _ENRICHMENT_REVIEW_STATUS_PROVIDER_SQL
    elif status_values is not None:
        review_sql = _ENRICHMENT_REVIEW_STATUS_SQL
    elif provider_values is not None:
        review_sql = _ENRICHMENT_REVIEW_PROVIDER_SQL
    rows = (
        await session.execute(
            text(review_sql),
            {
                "statuses": status_values,
                "status": status_value,
                "providers": provider_values,
                "provider": provider_value,
                "min_score": min_score,
                "max_score": max_score,
                "q_like": f"%{normalized_q}%" if normalized_q is not None else None,
                "limit_plus_one": effective_limit + 1,
                **_enrichment_cursor_params(cursor),
            },
        )
    ).mappings().all()
    items = tuple(_enrichment_review_row(row) for row in rows[:effective_limit])
    next_cursor = (
        _encode_enrichment_cursor(items[-1])
        if len(rows) > effective_limit and items
        else None
    )
    return EnrichmentReviewPage(items=items, next_cursor=next_cursor)

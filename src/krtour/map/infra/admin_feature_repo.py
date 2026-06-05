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

from sqlalchemy import text

from krtour.map.infra.merge_repo import (
    MergeError,
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
    "DedupReviewPage",
    "DedupReviewRow",
    "DedupFeatureSummary",
    "FeatureDeactivateResult",
    "FeatureStateConflict",
    "FeatureOverride",
    "deactivate_feature",
    "list_admin_features",
    "list_dedup_reviews",
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
class FeatureOverride:
    """생성/갱신된 feature override summary."""

    override_key: str
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

    review_key: str
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
                    'violation_key', v.violation_key::text,
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
    override_key::text,
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
        override_key=str(row["override_key"]),
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


_DEDUP_REVIEW_SQL: Final[str] = """
WITH reviews AS (
    SELECT
        q.review_key,
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
  AND (
    CAST(:cursor_score AS numeric) IS NULL
    OR (total_score, review_key::text) < (
        CAST(:cursor_score AS numeric),
        CAST(:cursor_review_key AS text)
    )
  )
ORDER BY total_score DESC, review_key::text DESC
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
    if not isinstance(payload.get("review_key"), str):
        raise ValueError("invalid dedup review cursor")
    return payload


def _dedup_cursor_params(cursor: str | None) -> dict[str, Any]:
    payload = _dedup_cursor_payload(cursor)
    if not payload:
        return {"cursor_score": None, "cursor_review_key": None}
    try:
        score = str(payload["total_score"])
        Decimal(score)
    except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError("invalid dedup review cursor") from exc
    return {"cursor_score": score, "cursor_review_key": payload["review_key"]}


def _encode_dedup_cursor(item: DedupReviewRow) -> str:
    raw = json.dumps(
        {
            "review_key": item.review_key,
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
        review_key=str(row["review_key"]),
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
WHERE review_key = :review_key
  AND status = 'pending'
  AND :decision = ANY(CAST(ARRAY['accepted','rejected','ignored'] AS text[]))
RETURNING review_key::text
"""

_SELECT_DEDUP_PAIR_SQL: Final[str] = """
SELECT feature_id_a, feature_id_b, total_score, status
FROM ops.dedup_review_queue
WHERE review_key = :review_key
FOR UPDATE
"""


async def set_dedup_review_decision(
    session: AsyncSession,
    review_key: str,
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
                "review_key": review_key,
                "decision": decision,
                "reviewed_by": reviewed_by,
                "decision_reason": decision_reason,
            },
        )
    ).first()
    return row is not None


async def merge_dedup_review(
    session: AsyncSession,
    review_key: str,
    *,
    master_feature_id: str | None = None,
    merged_by: str | None = None,
    reason: str | None = None,
) -> MergeOutcome:
    """dedup review를 병합한다. ``master_feature_id``가 없으면 기존 자동 선정."""
    if master_feature_id is None:
        return await merge_from_review(
            session, review_key, merged_by=merged_by, reason=reason
        )

    row = (
        await session.execute(text(_SELECT_DEDUP_PAIR_SQL), {"review_key": review_key})
    ).one_or_none()
    if row is None:
        raise MergeError(f"review_key 없음 — {review_key!r}")
    if row.status != "pending":
        raise MergeError(f"이미 검토된 후보(status={row.status!r}) — {review_key!r}")
    if master_feature_id == row.feature_id_a:
        loser_id = row.feature_id_b
    elif master_feature_id == row.feature_id_b:
        loser_id = row.feature_id_a
    else:
        raise MergeError(
            "master_feature_id가 review 후보 쌍에 없음 — "
            f"{master_feature_id!r}"
        )
    return await apply_feature_merge(
        session,
        master_id=master_feature_id,
        loser_id=loser_id,
        score=float(row.total_score) if row.total_score is not None else None,
        review_key=review_key,
        merged_by=merged_by,
        reason=reason,
    )

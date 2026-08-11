"""Feature에 연결된 provider entity의 현재 관측과 payload 이력 조회."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureObservation",
    "ObservationHistoryPage",
    "get_current_observations",
    "get_current_observations_by_feature_ids",
    "get_observation_history",
]


@dataclass(frozen=True)
class FeatureObservation:
    """Feature↔provider entity link와 immutable payload observation 한 건."""

    feature_id: str
    source_entity_key: str
    provider: str
    dataset_key: str
    source_entity_type: str
    source_entity_id: str
    first_seen_at: datetime
    entity_last_seen_at: datetime
    source_record_key: str
    raw_data: dict[str, Any]
    raw_payload_hash: str
    fetched_at: datetime
    imported_at: datetime
    observed_at: datetime
    expires_at: datetime | None
    source_role: str
    match_method: str
    confidence: int
    linked_at: datetime
    is_current: bool


@dataclass(frozen=True)
class ObservationHistoryPage:
    """한 Feature/entity의 결정적 keyset payload history page."""

    items: tuple[FeatureObservation, ...]
    next_cursor: str | None


_OBSERVATION_COLUMNS: Final[str] = """
    sl.feature_id,
    se.source_entity_key,
    pd.provider,
    pd.dataset_key,
    se.source_entity_type,
    se.source_entity_id,
    se.first_seen_at,
    se.last_seen_at AS entity_last_seen_at,
    sr.source_record_key,
    sr.raw_data,
    sr.raw_payload_hash,
    sr.fetched_at,
    sr.imported_at,
    head.observed_at,
    head.expires_at,
    sl.source_role,
    sl.match_method,
    sl.confidence,
    sl.created_at AS linked_at,
    (sr.source_record_key = head.current_source_record_key) AS is_current
"""

_GET_CURRENT_OBSERVATIONS_SQL: Final[str] = f"""
SELECT {_OBSERVATION_COLUMNS}
FROM provider_sync.source_links AS sl
JOIN provider_sync.source_entities AS se
  ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = se.provider_dataset_id
JOIN provider_sync.source_entity_heads AS head
  ON head.source_entity_key = se.source_entity_key
JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = head.current_source_record_key
WHERE sl.feature_id = :feature_id
ORDER BY
    pd.provider,
    pd.dataset_key,
    se.source_entity_type,
    se.source_entity_id,
    se.source_entity_key
"""

_GET_CURRENT_OBSERVATIONS_BY_FEATURE_IDS_SQL: Final[str] = f"""
SELECT {_OBSERVATION_COLUMNS}
FROM provider_sync.source_links AS sl
JOIN provider_sync.source_entities AS se
  ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = se.provider_dataset_id
JOIN provider_sync.source_entity_heads AS head
  ON head.source_entity_key = se.source_entity_key
JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = head.current_source_record_key
WHERE sl.feature_id = ANY(CAST(:feature_ids AS text[]))
ORDER BY
    sl.feature_id,
    pd.provider,
    pd.dataset_key,
    se.source_entity_type,
    se.source_entity_id,
    se.source_entity_key
"""

_GET_OBSERVATION_HISTORY_SQL: Final[str] = f"""
SELECT {_OBSERVATION_COLUMNS}
FROM provider_sync.source_links AS sl
JOIN provider_sync.source_entities AS se
  ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = se.provider_dataset_id
LEFT JOIN provider_sync.source_entity_heads AS head
  ON head.source_entity_key = se.source_entity_key
JOIN provider_sync.source_records AS sr
  ON sr.source_entity_key = se.source_entity_key
WHERE sl.feature_id = :feature_id
  AND se.source_entity_key = :source_entity_key
  AND (
    CAST(:cursor_fetched_at AS timestamptz) IS NULL
    OR (
        sr.fetched_at,
        sr.imported_at,
        sr.source_record_key
    ) < (
        CAST(:cursor_fetched_at AS timestamptz),
        CAST(:cursor_imported_at AS timestamptz),
        CAST(:cursor_source_record_key AS text)
    )
  )
ORDER BY
    sr.fetched_at DESC,
    sr.imported_at DESC,
    sr.source_record_key DESC
LIMIT :limit_plus_one
"""


def _observation(row: Any) -> FeatureObservation:
    raw_data = row.raw_data
    if isinstance(raw_data, str):
        raw_data = json.loads(raw_data)
    return FeatureObservation(
        feature_id=str(row.feature_id),
        source_entity_key=str(row.source_entity_key),
        provider=str(row.provider),
        dataset_key=str(row.dataset_key),
        source_entity_type=str(row.source_entity_type),
        source_entity_id=str(row.source_entity_id),
        first_seen_at=row.first_seen_at,
        entity_last_seen_at=row.entity_last_seen_at,
        source_record_key=str(row.source_record_key),
        raw_data=dict(raw_data),
        raw_payload_hash=str(row.raw_payload_hash),
        fetched_at=row.fetched_at,
        imported_at=row.imported_at,
        observed_at=row.observed_at,
        expires_at=row.expires_at,
        source_role=str(row.source_role),
        match_method=str(row.match_method),
        confidence=int(row.confidence),
        linked_at=row.linked_at,
        is_current=bool(row.is_current),
    )


def _encode_history_cursor(item: FeatureObservation) -> str:
    payload = {
        "v": 1,
        "feature_id": item.feature_id,
        "source_entity_key": item.source_entity_key,
        "fetched_at": item.fetched_at.isoformat(),
        "imported_at": item.imported_at.isoformat(),
        "source_record_key": item.source_record_key,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_history_cursor(
    cursor: str | None,
    *,
    feature_id: str,
    source_entity_key: str,
) -> dict[str, Any]:
    empty = {
        "cursor_fetched_at": None,
        "cursor_imported_at": None,
        "cursor_source_record_key": None,
    }
    if cursor is None:
        return empty
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if (
            payload["v"] != 1
            or payload["feature_id"] != feature_id
            or payload["source_entity_key"] != source_entity_key
        ):
            raise ValueError
        return {
            "cursor_fetched_at": datetime.fromisoformat(payload["fetched_at"]),
            "cursor_imported_at": datetime.fromisoformat(payload["imported_at"]),
            "cursor_source_record_key": str(payload["source_record_key"]),
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid observation history cursor") from exc


async def get_current_observations(
    session: AsyncSession,
    feature_id: str,
) -> tuple[FeatureObservation, ...]:
    """Feature에 연결된 모든 entity의 current observation을 반환한다."""

    rows = (
        await session.execute(
            text(_GET_CURRENT_OBSERVATIONS_SQL),
            {"feature_id": feature_id},
        )
    ).all()
    return tuple(_observation(row) for row in rows)


async def get_current_observations_by_feature_ids(
    session: AsyncSession,
    feature_ids: list[str],
) -> dict[str, tuple[FeatureObservation, ...]]:
    """여러 Feature의 current observation을 한 번에 조회한다."""

    if not feature_ids:
        return {}
    unique_feature_ids = list(dict.fromkeys(feature_ids))
    rows = (
        await session.execute(
            text(_GET_CURRENT_OBSERVATIONS_BY_FEATURE_IDS_SQL),
            {"feature_ids": unique_feature_ids},
        )
    ).all()
    grouped: dict[str, list[FeatureObservation]] = {
        feature_id: [] for feature_id in unique_feature_ids
    }
    for row in rows:
        item = _observation(row)
        grouped[item.feature_id].append(item)
    return {feature_id: tuple(items) for feature_id, items in grouped.items()}


async def get_observation_history(
    session: AsyncSession,
    *,
    feature_id: str,
    source_entity_key: str,
    cursor: str | None = None,
    limit: int = 50,
) -> ObservationHistoryPage:
    """Feature/entity payload versions를 current 결정 순서대로 조회한다."""

    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200")
    params = _decode_history_cursor(
        cursor,
        feature_id=feature_id,
        source_entity_key=source_entity_key,
    )
    params.update(
        {
            "feature_id": feature_id,
            "source_entity_key": source_entity_key,
            "limit_plus_one": limit + 1,
        }
    )
    rows = (
        await session.execute(text(_GET_OBSERVATION_HISTORY_SQL), params)
    ).all()
    items = tuple(_observation(row) for row in rows[:limit])
    next_cursor = (
        _encode_history_cursor(items[-1]) if len(rows) > limit and items else None
    )
    return ObservationHistoryPage(items=items, next_cursor=next_cursor)

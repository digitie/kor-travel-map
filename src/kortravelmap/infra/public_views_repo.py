"""공개 해수욕장/축제 view 조회 repository (T-222b).

본 모듈은 ``/v1/public/*`` HTTP 표면이 쓰는 읽기 전용 projection만 제공한다.
쿼리는 기존 infra 원칙(ADR-004)에 맞춰 raw SQL로 둔다. 공개 view의 판별 기준은
문서 drift가 있는 category가 아니라 domain detail이다:

- 해수욕장: ``kind='place'`` + ``detail.place_kind='beach'``
- 축제: ``kind='event'`` + ``detail.event_kind IN ('festival', 'cultural_festival')``
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "PublicBeachPage",
    "PublicBeachRow",
    "PublicFestivalMonthSummary",
    "PublicFestivalPage",
    "PublicFestivalRow",
    "PublicMapMarkerRow",
    "get_public_beach",
    "get_public_festival",
    "list_public_beach_markers",
    "list_public_beaches",
    "list_public_festival_markers",
    "list_public_festivals_monthly",
]

CursorKind = Literal["public_beaches", "public_festivals"]


@dataclass(frozen=True)
class PublicBeachRow:
    """해수욕장 공개 projection row."""

    feature_id: str
    display_name: str
    lon: float | None
    lat: float | None
    sido_code: str | None
    sigungu_code: str | None
    legal_dong_code: str | None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    source_raw_data: dict[str, Any]
    marker_icon: str | None
    marker_color: str | None
    source_providers: tuple[str, ...]
    updated_at: datetime


@dataclass(frozen=True)
class PublicFestivalRow:
    """축제 공개 projection row."""

    feature_id: str
    festival_name: str
    lon: float | None
    lat: float | None
    sido_code: str | None
    sigungu_code: str | None
    legal_dong_code: str | None
    address: dict[str, Any]
    detail: dict[str, Any]
    urls: dict[str, Any]
    source_raw_data: dict[str, Any]
    marker_icon: str | None
    marker_color: str | None
    source_providers: tuple[str, ...]
    updated_at: datetime


@dataclass(frozen=True)
class PublicMapMarkerRow:
    """공개 지도 layer marker row."""

    feature_id: str
    name: str
    lon: float
    lat: float
    sigungu_code: str | None


@dataclass(frozen=True)
class PublicFestivalMonthSummary:
    """축제 월별 count summary."""

    year: int
    month: int
    count: int


@dataclass(frozen=True)
class PublicBeachPage:
    """해수욕장 공개 목록 keyset page."""

    items: tuple[PublicBeachRow, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class PublicFestivalPage:
    """축제 공개 목록 keyset page."""

    items: tuple[PublicFestivalRow, ...]
    months: tuple[PublicFestivalMonthSummary, ...]
    next_cursor: str | None


_SOURCE_PROVIDERS_LATERAL_SQL: Final[str] = """
LEFT JOIN LATERAL (
    SELECT COALESCE(
        array_agg(DISTINCT sr.provider ORDER BY sr.provider)
            FILTER (WHERE sr.provider IS NOT NULL),
        ARRAY[]::text[]
    ) AS source_providers
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = sl.source_record_key
    WHERE sl.feature_id = f.feature_id
) AS sp ON true
"""

_PRIMARY_SOURCE_LATERAL_SQL: Final[str] = """
LEFT JOIN LATERAL (
    SELECT sr.raw_data AS source_raw_data
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = sl.source_record_key
    WHERE sl.feature_id = f.feature_id
      AND sl.is_primary_source
    ORDER BY sl.created_at ASC, sr.imported_at ASC, sr.source_record_key ASC
    LIMIT 1
) AS ps ON true
"""

_PUBLIC_BEACH_BASE_WHERE_SQL: Final[str] = """
f.deleted_at IS NULL
  AND f.status = 'active'
  AND f.kind = 'place'
  AND f.detail ->> 'place_kind' = 'beach'
  AND (CAST(:sido_code AS text) IS NULL OR f.sido_code = CAST(:sido_code AS text))
  AND (
    CAST(:sigungu_code AS text) IS NULL
    OR f.sigungu_code = CAST(:sigungu_code AS text)
  )
"""

_PUBLIC_BEACH_LIST_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    f.name AS display_name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sido_code,
    f.sigungu_code,
    f.legal_dong_code,
    f.address,
    f.detail,
    f.urls,
    ps.source_raw_data,
    f.marker_icon,
    f.marker_color,
    sp.source_providers,
    f.updated_at
FROM feature.features AS f
{_SOURCE_PROVIDERS_LATERAL_SQL}
{_PRIMARY_SOURCE_LATERAL_SQL}
WHERE {_PUBLIC_BEACH_BASE_WHERE_SQL}
  AND (
    CAST(:q_pattern AS text) IS NULL
    OR f.name ILIKE CAST(:q_pattern AS text)
    OR COALESCE(f.address ->> 'road', '') ILIKE CAST(:q_pattern AS text)
    OR COALESCE(f.address ->> 'legal', '') ILIKE CAST(:q_pattern AS text)
    OR COALESCE(f.address ->> 'admin', '') ILIKE CAST(:q_pattern AS text)
  )
  AND (
    CAST(:cursor_updated_at AS timestamptz) IS NULL
    OR (
      f.updated_at,
      f.feature_id
    ) < (
      CAST(:cursor_updated_at AS timestamptz),
      CAST(:cursor_feature_id AS text)
    )
  )
ORDER BY f.updated_at DESC, f.feature_id DESC
LIMIT :limit
"""

_PUBLIC_BEACH_DETAIL_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    f.name AS display_name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sido_code,
    f.sigungu_code,
    f.legal_dong_code,
    f.address,
    f.detail,
    f.urls,
    ps.source_raw_data,
    f.marker_icon,
    f.marker_color,
    sp.source_providers,
    f.updated_at
FROM feature.features AS f
{_SOURCE_PROVIDERS_LATERAL_SQL}
{_PRIMARY_SOURCE_LATERAL_SQL}
WHERE {_PUBLIC_BEACH_BASE_WHERE_SQL}
  AND f.feature_id = CAST(:feature_id AS text)
"""

_PUBLIC_BEACH_MARKERS_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    f.name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sigungu_code
FROM feature.features AS f
WHERE {_PUBLIC_BEACH_BASE_WHERE_SQL}
  AND f.coord IS NOT NULL
  AND (
    NOT CAST(:bbox_enabled AS boolean)
    OR f.coord OPERATOR(x_extension.&&) x_extension.ST_MakeEnvelope(
        CAST(:min_lon AS double precision),
        CAST(:min_lat AS double precision),
        CAST(:max_lon AS double precision),
        CAST(:max_lat AS double precision),
        4326
    )
  )
ORDER BY f.name, f.feature_id
LIMIT :limit
"""

_PUBLIC_FESTIVAL_BASE_WHERE_SQL: Final[str] = """
f.deleted_at IS NULL
  AND f.status = 'active'
  AND f.kind = 'event'
  AND COALESCE(f.detail ->> 'event_kind', 'festival') IN ('festival', 'cultural_festival')
  AND (CAST(:sido_code AS text) IS NULL OR f.sido_code = CAST(:sido_code AS text))
  AND (
    CAST(:sigungu_code AS text) IS NULL
    OR f.sigungu_code = CAST(:sigungu_code AS text)
  )
  AND NULLIF(f.detail ->> 'starts_on', '')::date <= CAST(:month_end AS date)
  AND (
    NULLIF(f.detail ->> 'ends_on', '') IS NULL
    OR NULLIF(f.detail ->> 'ends_on', '')::date >= CAST(:month_start AS date)
  )
"""

_PUBLIC_FESTIVAL_LIST_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    f.name AS festival_name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sido_code,
    f.sigungu_code,
    f.legal_dong_code,
    f.address,
    f.detail,
    f.urls,
    ps.source_raw_data,
    f.marker_icon,
    f.marker_color,
    sp.source_providers,
    f.updated_at
FROM feature.features AS f
{_SOURCE_PROVIDERS_LATERAL_SQL}
{_PRIMARY_SOURCE_LATERAL_SQL}
WHERE {_PUBLIC_FESTIVAL_BASE_WHERE_SQL}
  AND (
    CAST(:cursor_start_date AS date) IS NULL
    OR (
      NULLIF(f.detail ->> 'starts_on', '')::date,
      f.updated_at,
      f.feature_id
    ) > (
      CAST(:cursor_start_date AS date),
      CAST(:cursor_updated_at AS timestamptz),
      CAST(:cursor_feature_id AS text)
    )
  )
ORDER BY NULLIF(f.detail ->> 'starts_on', '')::date ASC, f.updated_at ASC, f.feature_id ASC
LIMIT :limit
"""

_PUBLIC_FESTIVAL_DETAIL_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    f.name AS festival_name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sido_code,
    f.sigungu_code,
    f.legal_dong_code,
    f.address,
    f.detail,
    f.urls,
    ps.source_raw_data,
    f.marker_icon,
    f.marker_color,
    sp.source_providers,
    f.updated_at
FROM feature.features AS f
{_SOURCE_PROVIDERS_LATERAL_SQL}
{_PRIMARY_SOURCE_LATERAL_SQL}
WHERE f.deleted_at IS NULL
  AND f.status = 'active'
  AND f.kind = 'event'
  AND COALESCE(f.detail ->> 'event_kind', 'festival') IN ('festival', 'cultural_festival')
  AND f.feature_id = CAST(:feature_id AS text)
"""

_PUBLIC_FESTIVAL_MARKERS_SQL: Final[str] = f"""
SELECT
    f.feature_id,
    f.name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.sigungu_code
FROM feature.features AS f
WHERE {_PUBLIC_FESTIVAL_BASE_WHERE_SQL}
  AND f.coord IS NOT NULL
  AND (
    NOT CAST(:bbox_enabled AS boolean)
    OR f.coord OPERATOR(x_extension.&&) x_extension.ST_MakeEnvelope(
        CAST(:min_lon AS double precision),
        CAST(:min_lat AS double precision),
        CAST(:max_lon AS double precision),
        CAST(:max_lat AS double precision),
        4326
    )
  )
ORDER BY NULLIF(f.detail ->> 'starts_on', '')::date ASC, f.name, f.feature_id
LIMIT :limit
"""

_PUBLIC_FESTIVAL_MONTH_SUMMARY_SQL: Final[str] = """
WITH months AS (
    SELECT generate_series(
        date_trunc('month', CAST(:month_start AS date)) - interval '1 month',
        date_trunc('month', CAST(:month_start AS date)) + interval '1 month',
        interval '1 month'
    )::date AS month_start
)
SELECT
    EXTRACT(YEAR FROM m.month_start)::int AS year,
    EXTRACT(MONTH FROM m.month_start)::int AS month,
    count(f.feature_id)::int AS count
FROM months AS m
LEFT JOIN feature.features AS f
  ON f.deleted_at IS NULL
 AND f.status = 'active'
 AND f.kind = 'event'
 AND COALESCE(f.detail ->> 'event_kind', 'festival') IN ('festival', 'cultural_festival')
 AND (CAST(:sido_code AS text) IS NULL OR f.sido_code = CAST(:sido_code AS text))
 AND (
   CAST(:sigungu_code AS text) IS NULL
   OR f.sigungu_code = CAST(:sigungu_code AS text)
 )
 AND NULLIF(f.detail ->> 'starts_on', '')::date
       <= (m.month_start + interval '1 month' - interval '1 day')::date
 AND (
   NULLIF(f.detail ->> 'ends_on', '') IS NULL
   OR NULLIF(f.detail ->> 'ends_on', '')::date >= m.month_start
 )
GROUP BY m.month_start
ORDER BY m.month_start
"""


def _decode_cursor(cursor: str | None, *, kind: CursorKind) -> dict[str, Any]:
    if cursor is None:
        return {}
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid public view cursor") from exc
    if not isinstance(payload, dict) or payload.get("kind") != kind:
        raise ValueError("invalid public view cursor")
    feature_id = payload.get("feature_id")
    updated_at = payload.get("updated_at")
    if not isinstance(feature_id, str) or not feature_id:
        raise ValueError("invalid public view cursor")
    if not isinstance(updated_at, str) or not updated_at:
        raise ValueError("invalid public view cursor")
    return payload


def _encode_cursor(
    *,
    kind: CursorKind,
    feature_id: str,
    updated_at: datetime,
    start_date: date | None = None,
) -> str:
    payload: dict[str, Any] = {
        "kind": kind,
        "feature_id": feature_id,
        "updated_at": updated_at.isoformat(),
    }
    if start_date is not None:
        payload["start_date"] = start_date.isoformat()
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _beach_cursor_params(cursor: str | None) -> dict[str, Any]:
    payload = _decode_cursor(cursor, kind="public_beaches")
    if not payload:
        return {"cursor_updated_at": None, "cursor_feature_id": None}
    try:
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
    except ValueError as exc:
        raise ValueError("invalid public view cursor") from exc
    return {
        "cursor_updated_at": updated_at,
        "cursor_feature_id": payload["feature_id"],
    }


def _festival_cursor_params(cursor: str | None) -> dict[str, Any]:
    payload = _decode_cursor(cursor, kind="public_festivals")
    if not payload:
        return {
            "cursor_start_date": None,
            "cursor_updated_at": None,
            "cursor_feature_id": None,
        }
    try:
        start_date = date.fromisoformat(str(payload["start_date"]))
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
    except (KeyError, ValueError) as exc:
        raise ValueError("invalid public view cursor") from exc
    return {
        "cursor_start_date": start_date,
        "cursor_updated_at": updated_at,
        "cursor_feature_id": payload["feature_id"],
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    return {}


def _source_providers(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value if item is not None)


def _q_pattern(q: str | None) -> str | None:
    if q is None:
        return None
    stripped = q.strip()
    if not stripped:
        return None
    return f"%{stripped}%"


def _beach_row(row: Any) -> PublicBeachRow:
    lon = row["lon"]
    lat = row["lat"]
    return PublicBeachRow(
        feature_id=str(row["feature_id"]),
        display_name=str(row["display_name"]),
        lon=float(lon) if lon is not None else None,
        lat=float(lat) if lat is not None else None,
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        legal_dong_code=row["legal_dong_code"],
        address=_json_object(row["address"]),
        detail=_json_object(row["detail"]),
        urls=_json_object(row["urls"]),
        source_raw_data=_json_object(row["source_raw_data"]),
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        source_providers=_source_providers(row["source_providers"]),
        updated_at=row["updated_at"],
    )


def _festival_row(row: Any) -> PublicFestivalRow:
    lon = row["lon"]
    lat = row["lat"]
    return PublicFestivalRow(
        feature_id=str(row["feature_id"]),
        festival_name=str(row["festival_name"]),
        lon=float(lon) if lon is not None else None,
        lat=float(lat) if lat is not None else None,
        sido_code=row["sido_code"],
        sigungu_code=row["sigungu_code"],
        legal_dong_code=row["legal_dong_code"],
        address=_json_object(row["address"]),
        detail=_json_object(row["detail"]),
        urls=_json_object(row["urls"]),
        source_raw_data=_json_object(row["source_raw_data"]),
        marker_icon=row["marker_icon"],
        marker_color=row["marker_color"],
        source_providers=_source_providers(row["source_providers"]),
        updated_at=row["updated_at"],
    )


def _marker_row(row: Any) -> PublicMapMarkerRow:
    return PublicMapMarkerRow(
        feature_id=str(row["feature_id"]),
        name=str(row["name"]),
        lon=float(row["lon"]),
        lat=float(row["lat"]),
        sigungu_code=row["sigungu_code"],
    )


def _bbox_params(
    *,
    min_lon: float | None,
    min_lat: float | None,
    max_lon: float | None,
    max_lat: float | None,
) -> dict[str, Any]:
    bbox_values = (min_lon, min_lat, max_lon, max_lat)
    bbox_enabled = all(value is not None for value in bbox_values)
    if not bbox_enabled:
        return {
            "bbox_enabled": False,
            "min_lon": 0.0,
            "min_lat": 0.0,
            "max_lon": 0.0,
            "max_lat": 0.0,
        }
    if min_lon is None or min_lat is None or max_lon is None or max_lat is None:
        raise ValueError("bbox는 min_lon/min_lat/max_lon/max_lat를 모두 지정해야 합니다.")
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("bbox min 값은 max 값보다 클 수 없습니다.")
    return {
        "bbox_enabled": True,
        "min_lon": min_lon,
        "min_lat": min_lat,
        "max_lon": max_lon,
        "max_lat": max_lat,
    }


def _base_params(
    *,
    sido_code: str | None = None,
    sigungu_code: str | None = None,
) -> dict[str, Any]:
    return {"sido_code": sido_code, "sigungu_code": sigungu_code}


async def list_public_beaches(
    session: AsyncSession,
    *,
    sido_code: str | None = None,
    sigungu_code: str | None = None,
    q: str | None = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> PublicBeachPage:
    """공개 해수욕장 목록을 keyset cursor로 조회한다."""

    params = {
        **_base_params(sido_code=sido_code, sigungu_code=sigungu_code),
        **_beach_cursor_params(cursor),
        "q_pattern": _q_pattern(q),
        "limit": page_size + 1,
    }
    rows = (
        await session.execute(text(_PUBLIC_BEACH_LIST_SQL), params)
    ).mappings().all()
    items = tuple(_beach_row(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor(
            kind="public_beaches",
            feature_id=items[-1].feature_id,
            updated_at=items[-1].updated_at,
        )
        if len(rows) > page_size and items
        else None
    )
    return PublicBeachPage(items=items, next_cursor=next_cursor)


async def get_public_beach(
    session: AsyncSession,
    *,
    feature_id: str,
) -> PublicBeachRow | None:
    """해수욕장 공개 상세 1건을 조회한다."""

    row = (
        await session.execute(
            text(_PUBLIC_BEACH_DETAIL_SQL),
            {
                **_base_params(),
                "feature_id": feature_id,
            },
        )
    ).mappings().first()
    return _beach_row(row) if row is not None else None


async def list_public_beach_markers(
    session: AsyncSession,
    *,
    sido_code: str | None = None,
    sigungu_code: str | None = None,
    min_lon: float | None = None,
    min_lat: float | None = None,
    max_lon: float | None = None,
    max_lat: float | None = None,
    max_items: int = 500,
) -> tuple[PublicMapMarkerRow, ...]:
    """공개 해수욕장 지도 marker를 조회한다."""

    params = {
        **_base_params(sido_code=sido_code, sigungu_code=sigungu_code),
        **_bbox_params(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
        ),
        "limit": max_items,
    }
    rows = (
        await session.execute(text(_PUBLIC_BEACH_MARKERS_SQL), params)
    ).mappings().all()
    return tuple(_marker_row(row) for row in rows)


async def list_public_festivals_monthly(
    session: AsyncSession,
    *,
    month_start: date,
    month_end: date,
    sido_code: str | None = None,
    sigungu_code: str | None = None,
    page_size: int = 12,
    cursor: str | None = None,
    include_months: bool = True,
) -> PublicFestivalPage:
    """공개 월별 축제 목록과 선택적 전후 월 count summary를 조회한다."""

    base = {
        **_base_params(sido_code=sido_code, sigungu_code=sigungu_code),
        "month_start": month_start,
        "month_end": month_end,
    }
    rows = (
        await session.execute(
            text(_PUBLIC_FESTIVAL_LIST_SQL),
            {
                **base,
                **_festival_cursor_params(cursor),
                "limit": page_size + 1,
            },
        )
    ).mappings().all()
    items = tuple(_festival_row(row) for row in rows[:page_size])
    next_cursor = None
    if len(rows) > page_size and items:
        detail = items[-1].detail
        start_raw = detail.get("starts_on")
        if isinstance(start_raw, str):
            next_cursor = _encode_cursor(
                kind="public_festivals",
                feature_id=items[-1].feature_id,
                updated_at=items[-1].updated_at,
                start_date=date.fromisoformat(start_raw),
            )

    months: tuple[PublicFestivalMonthSummary, ...] = ()
    if include_months:
        month_rows = (
            await session.execute(text(_PUBLIC_FESTIVAL_MONTH_SUMMARY_SQL), base)
        ).mappings().all()
        months = tuple(
            PublicFestivalMonthSummary(
                year=int(row["year"]),
                month=int(row["month"]),
                count=int(row["count"]),
            )
            for row in month_rows
        )
    return PublicFestivalPage(items=items, months=months, next_cursor=next_cursor)


async def get_public_festival(
    session: AsyncSession,
    *,
    feature_id: str,
) -> PublicFestivalRow | None:
    """축제 공개 상세 1건을 조회한다."""

    row = (
        await session.execute(
            text(_PUBLIC_FESTIVAL_DETAIL_SQL),
            {"feature_id": feature_id},
        )
    ).mappings().first()
    return _festival_row(row) if row is not None else None


async def list_public_festival_markers(
    session: AsyncSession,
    *,
    month_start: date,
    month_end: date,
    min_lon: float | None = None,
    min_lat: float | None = None,
    max_lon: float | None = None,
    max_lat: float | None = None,
    max_items: int = 500,
) -> tuple[PublicMapMarkerRow, ...]:
    """공개 축제 지도 marker를 조회한다."""

    params = {
        **_base_params(),
        "month_start": month_start,
        "month_end": month_end,
        **_bbox_params(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat
        ),
        "limit": max_items,
    }
    rows = (
        await session.execute(text(_PUBLIC_FESTIVAL_MARKERS_SQL), params)
    ).mappings().all()
    return tuple(_marker_row(row) for row in rows)

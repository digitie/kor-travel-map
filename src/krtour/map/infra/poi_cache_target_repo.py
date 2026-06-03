"""``ops.poi_cache_targets`` repository (ADR-045 T-205c).

외부 앱 POI/cache target을 좌표만으로 식별하지 않고
``external_system + target_key``로 관리한다. target 주변 feature link는 후속
``cache_target_keys`` scope resolver와 targeted update 실행 본체가 재계산한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "PoiCacheTarget",
    "PoiCacheTargetConflict",
    "PoiCacheTargetFeatureLink",
    "deactivate_poi_cache_target_feature_links",
    "delete_poi_cache_target",
    "get_poi_cache_target",
    "get_poi_cache_target_by_key",
    "list_poi_cache_target_feature_links",
    "list_poi_cache_targets",
    "mark_poi_cache_targets_refresh_failed",
    "mark_poi_cache_targets_refresh_requested",
    "mark_poi_cache_targets_refreshed",
    "upsert_poi_cache_target",
    "upsert_poi_cache_target_feature_link",
]

OnConflict = Literal["reject", "move"]

_SCOPE_MODES: Final[frozenset[str]] = frozenset(
    {"center_radius", "sigungu_by_radius"}
)
_REFRESH_POLICIES: Final[frozenset[str]] = frozenset(
    {"provider_default", "follow_system", "allow_targeted", "disabled"}
)
_LINK_RELATIONS: Final[frozenset[str]] = frozenset(
    {"within_radius", "same_sigungu", "manual"}
)
_MAX_LIST_LIMIT: Final[int] = 500

_TARGET_COLUMNS: Final[str] = (
    "target_id, external_system, target_key, name, lon, lat, coord_precision_digits, "
    "coord_key, radius_km, scope_mode, update_enabled, refresh_policy, "
    "provider_overrides, metadata, last_seen_at, last_requested_at, "
    "last_refreshed_at, last_failed_at, next_eligible_refresh_at, deleted_at, "
    "created_at, updated_at"
)

_LINK_COLUMNS: Final[str] = (
    "target_id, feature_id, provider, dataset_key, distance_m, relation, active, "
    "first_seen_at, last_seen_at, last_refreshed_at"
)


class PoiCacheTargetConflict(RuntimeError):
    """같은 target key가 다른 normalized 좌표로 들어왔지만 ``move``가 아닌 경우."""


@dataclass(frozen=True)
class PoiCacheTarget:
    """``ops.poi_cache_targets`` row."""

    target_id: str
    external_system: str
    target_key: str
    name: str | None
    lon: float
    lat: float
    coord_precision_digits: int
    coord_key: str
    radius_km: float
    scope_mode: str
    update_enabled: bool
    refresh_policy: str
    provider_overrides: dict[str, Any]
    metadata: dict[str, Any]
    last_seen_at: datetime
    last_requested_at: datetime | None
    last_refreshed_at: datetime | None
    last_failed_at: datetime | None
    next_eligible_refresh_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PoiCacheTargetFeatureLink:
    """``ops.poi_cache_target_feature_links`` row."""

    target_id: str
    feature_id: str
    provider: str | None
    dataset_key: str | None
    distance_m: float | None
    relation: str
    active: bool
    first_seen_at: datetime
    last_seen_at: datetime
    last_refreshed_at: datetime | None


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _row_to_target(row: Any) -> PoiCacheTarget:
    return PoiCacheTarget(
        target_id=str(row["target_id"]),
        external_system=str(row["external_system"]),
        target_key=str(row["target_key"]),
        name=row["name"],
        lon=float(row["lon"]),
        lat=float(row["lat"]),
        coord_precision_digits=int(row["coord_precision_digits"]),
        coord_key=str(row["coord_key"]),
        radius_km=float(row["radius_km"]),
        scope_mode=str(row["scope_mode"]),
        update_enabled=bool(row["update_enabled"]),
        refresh_policy=str(row["refresh_policy"]),
        provider_overrides=_json_dict(row["provider_overrides"]),
        metadata=_json_dict(row["metadata"]),
        last_seen_at=row["last_seen_at"],
        last_requested_at=row["last_requested_at"],
        last_refreshed_at=row["last_refreshed_at"],
        last_failed_at=row["last_failed_at"],
        next_eligible_refresh_at=row["next_eligible_refresh_at"],
        deleted_at=row["deleted_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_link(row: Any) -> PoiCacheTargetFeatureLink:
    distance = row["distance_m"]
    return PoiCacheTargetFeatureLink(
        target_id=str(row["target_id"]),
        feature_id=str(row["feature_id"]),
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        distance_m=float(distance) if distance is not None else None,
        relation=str(row["relation"]),
        active=bool(row["active"]),
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        last_refreshed_at=row["last_refreshed_at"],
    )


def _coord_key(*, lon: float, lat: float, precision: int) -> str:
    return f"{lon:.{precision}f}:{lat:.{precision}f}:p{precision}"


def _validate_target(
    *,
    external_system: str,
    target_key: str,
    lon: float,
    lat: float,
    radius_km: float,
    coord_precision_digits: int,
    scope_mode: str,
    refresh_policy: str,
    on_conflict: OnConflict,
) -> None:
    if not external_system:
        raise ValueError("external_system must be non-empty")
    if not target_key:
        raise ValueError("target_key must be non-empty")
    if not 124.0 <= lon <= 132.0 or not 33.0 <= lat <= 39.5:
        raise ValueError("coord must be inside Korea lon/lat bounds")
    if radius_km <= 0 or radius_km > 100:
        raise ValueError("radius_km must be greater than 0 and <= 100")
    if coord_precision_digits < 3 or coord_precision_digits > 8:
        raise ValueError("coord_precision_digits must be between 3 and 8")
    if scope_mode not in _SCOPE_MODES:
        raise ValueError(f"scope_mode must be one of {sorted(_SCOPE_MODES)}")
    if refresh_policy not in _REFRESH_POLICIES:
        raise ValueError(
            f"refresh_policy must be one of {sorted(_REFRESH_POLICIES)}"
        )
    if on_conflict not in ("reject", "move"):
        raise ValueError("on_conflict must be 'reject' or 'move'")


_EXISTING_BY_KEY_SQL: Final[str] = """
SELECT target_id, coord_key
FROM ops.poi_cache_targets
WHERE external_system = :external_system
  AND target_key = :target_key
  AND deleted_at IS NULL
"""

_UPSERT_TARGET_SQL: Final[str] = f"""
INSERT INTO ops.poi_cache_targets (
    external_system, target_key, name, lon, lat, coord, coord_precision_digits,
    coord_key, radius_km, scope_mode, update_enabled, refresh_policy,
    provider_overrides, metadata, last_seen_at, updated_at
) VALUES (
    :external_system, :target_key, :name, :lon, :lat,
    x_extension.ST_SetSRID(
        x_extension.ST_MakePoint(
            CAST(:lon_geom AS double precision),
            CAST(:lat_geom AS double precision)
        ),
        4326
    ),
    :coord_precision_digits, :coord_key, :radius_km, :scope_mode,
    :update_enabled, :refresh_policy, CAST(:provider_overrides AS jsonb),
    CAST(:metadata_json AS jsonb), now(), now()
)
ON CONFLICT (external_system, target_key) WHERE deleted_at IS NULL DO UPDATE SET
    name = EXCLUDED.name,
    lon = EXCLUDED.lon,
    lat = EXCLUDED.lat,
    coord = EXCLUDED.coord,
    coord_precision_digits = EXCLUDED.coord_precision_digits,
    coord_key = EXCLUDED.coord_key,
    radius_km = EXCLUDED.radius_km,
    scope_mode = EXCLUDED.scope_mode,
    update_enabled = EXCLUDED.update_enabled,
    refresh_policy = EXCLUDED.refresh_policy,
    provider_overrides = EXCLUDED.provider_overrides,
    metadata = EXCLUDED.metadata,
    last_seen_at = now(),
    updated_at = now()
RETURNING {_TARGET_COLUMNS}
"""

_GET_TARGET_SQL: Final[str] = f"""
SELECT {_TARGET_COLUMNS}
FROM ops.poi_cache_targets
WHERE target_id = :target_id
  AND (CAST(:include_deleted AS boolean) OR deleted_at IS NULL)
"""

_GET_TARGET_BY_KEY_SQL: Final[str] = f"""
SELECT {_TARGET_COLUMNS}
FROM ops.poi_cache_targets
WHERE external_system = :external_system
  AND target_key = :target_key
  AND (CAST(:include_deleted AS boolean) OR deleted_at IS NULL)
ORDER BY deleted_at NULLS FIRST, updated_at DESC
LIMIT 1
"""

_LIST_TARGETS_SQL: Final[str] = f"""
SELECT {_TARGET_COLUMNS}
FROM ops.poi_cache_targets
WHERE (CAST(:external_system AS text) IS NULL
       OR external_system = CAST(:external_system AS text))
  AND (CAST(:include_deleted AS boolean) OR deleted_at IS NULL)
  AND (CAST(:update_enabled AS boolean) IS NULL
       OR update_enabled = CAST(:update_enabled AS boolean))
ORDER BY updated_at DESC, target_id
LIMIT :limit
"""

_DELETE_TARGET_SQL: Final[str] = f"""
UPDATE ops.poi_cache_targets
SET deleted_at = COALESCE(deleted_at, now()),
    update_enabled = false,
    updated_at = now()
WHERE external_system = :external_system
  AND target_key = :target_key
  AND deleted_at IS NULL
RETURNING {_TARGET_COLUMNS}
"""

_DEACTIVATE_LINKS_SQL: Final[str] = """
UPDATE ops.poi_cache_target_feature_links
SET active = false,
    last_seen_at = now()
WHERE target_id = :target_id
  AND active
RETURNING 1
"""

_UPSERT_LINK_SQL: Final[str] = f"""
INSERT INTO ops.poi_cache_target_feature_links (
    target_id, feature_id, provider, dataset_key, distance_m, relation,
    active, last_seen_at
) VALUES (
    :target_id, :feature_id, :provider, :dataset_key, :distance_m,
    :relation, true, now()
)
ON CONFLICT (target_id, feature_id) DO UPDATE SET
    provider = EXCLUDED.provider,
    dataset_key = EXCLUDED.dataset_key,
    distance_m = EXCLUDED.distance_m,
    relation = EXCLUDED.relation,
    active = true,
    last_seen_at = now()
RETURNING {_LINK_COLUMNS}
"""

_LIST_LINKS_SQL: Final[str] = f"""
SELECT {_LINK_COLUMNS}
FROM ops.poi_cache_target_feature_links
WHERE target_id = :target_id
  AND (CAST(:active_only AS boolean) IS false OR active)
ORDER BY active DESC, distance_m NULLS LAST, feature_id
LIMIT :limit
"""

_MARK_TARGETS_REQUESTED_SQL: Final[str] = """
UPDATE ops.poi_cache_targets
SET last_requested_at = now(),
    updated_at = now()
WHERE target_id::text = ANY(CAST(:target_ids AS text[]))
  AND deleted_at IS NULL
RETURNING 1
"""

_MARK_TARGETS_REFRESHED_SQL: Final[str] = """
UPDATE ops.poi_cache_targets
SET last_refreshed_at = now(),
    next_eligible_refresh_at = NULL,
    updated_at = now()
WHERE target_id::text = ANY(CAST(:target_ids AS text[]))
  AND deleted_at IS NULL
RETURNING 1
"""

_MARK_TARGETS_FAILED_SQL: Final[str] = """
UPDATE ops.poi_cache_targets
SET last_failed_at = now(),
    updated_at = now()
WHERE target_id::text = ANY(CAST(:target_ids AS text[]))
  AND deleted_at IS NULL
RETURNING 1
"""


async def upsert_poi_cache_target(
    session: AsyncSession,
    *,
    external_system: str,
    target_key: str,
    lon: float,
    lat: float,
    radius_km: float,
    name: str | None = None,
    coord_precision_digits: int = 6,
    scope_mode: str = "center_radius",
    update_enabled: bool = True,
    refresh_policy: str = "provider_default",
    provider_overrides: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    on_conflict: OnConflict = "reject",
) -> PoiCacheTarget:
    """POI/cache target을 upsert한다.

    같은 ``external_system + target_key``가 다른 normalized 좌표로 들어오면 기본은
    ``PoiCacheTargetConflict``다. ``on_conflict='move'``면 좌표를 갱신하고 기존
    active feature link를 비활성화해 후속 resolver가 다시 계산하게 한다.
    """
    _validate_target(
        external_system=external_system,
        target_key=target_key,
        lon=lon,
        lat=lat,
        radius_km=radius_km,
        coord_precision_digits=coord_precision_digits,
        scope_mode=scope_mode,
        refresh_policy=refresh_policy,
        on_conflict=on_conflict,
    )
    coord_key = _coord_key(lon=lon, lat=lat, precision=coord_precision_digits)
    existing = (
        await session.execute(
            text(_EXISTING_BY_KEY_SQL),
            {"external_system": external_system, "target_key": target_key},
        )
    ).mappings().one_or_none()
    moved = existing is not None and existing["coord_key"] != coord_key
    if moved and on_conflict == "reject":
        raise PoiCacheTargetConflict(
            f"active target {external_system}:{target_key} has different coord_key"
        )

    target = _row_to_target(
        (
            await session.execute(
                text(_UPSERT_TARGET_SQL),
                {
                    "external_system": external_system,
                    "target_key": target_key,
                    "name": name,
                    "lon": lon,
                    "lat": lat,
                    "lon_geom": lon,
                    "lat_geom": lat,
                    "coord_precision_digits": coord_precision_digits,
                    "coord_key": coord_key,
                    "radius_km": radius_km,
                    "scope_mode": scope_mode,
                    "update_enabled": update_enabled,
                    "refresh_policy": refresh_policy,
                    "provider_overrides": json.dumps(
                        dict(provider_overrides) if provider_overrides else {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "metadata_json": json.dumps(
                        dict(metadata) if metadata else {},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            )
        ).mappings().one()
    )
    if moved:
        await deactivate_poi_cache_target_feature_links(session, target.target_id)
    return target


async def get_poi_cache_target(
    session: AsyncSession,
    target_id: str,
    *,
    include_deleted: bool = False,
) -> PoiCacheTarget | None:
    """target id로 POI/cache target 조회."""
    row = (
        await session.execute(
            text(_GET_TARGET_SQL),
            {"target_id": target_id, "include_deleted": include_deleted},
        )
    ).mappings().one_or_none()
    return _row_to_target(row) if row is not None else None


async def get_poi_cache_target_by_key(
    session: AsyncSession,
    *,
    external_system: str,
    target_key: str,
    include_deleted: bool = False,
) -> PoiCacheTarget | None:
    """``external_system + target_key``로 target 조회."""
    row = (
        await session.execute(
            text(_GET_TARGET_BY_KEY_SQL),
            {
                "external_system": external_system,
                "target_key": target_key,
                "include_deleted": include_deleted,
            },
        )
    ).mappings().one_or_none()
    return _row_to_target(row) if row is not None else None


async def list_poi_cache_targets(
    session: AsyncSession,
    *,
    external_system: str | None = None,
    update_enabled: bool | None = None,
    include_deleted: bool = False,
    limit: int = 200,
) -> tuple[PoiCacheTarget, ...]:
    """POI/cache target 목록 조회."""
    rows = (
        await session.execute(
            text(_LIST_TARGETS_SQL),
            {
                "external_system": external_system,
                "update_enabled": update_enabled,
                "include_deleted": include_deleted,
                "limit": max(1, min(limit, _MAX_LIST_LIMIT)),
            },
        )
    ).mappings().all()
    return tuple(_row_to_target(row) for row in rows)


async def delete_poi_cache_target(
    session: AsyncSession,
    *,
    external_system: str,
    target_key: str,
) -> PoiCacheTarget | None:
    """target을 soft-delete하고 active feature links를 비활성화한다."""
    row = (
        await session.execute(
            text(_DELETE_TARGET_SQL),
            {"external_system": external_system, "target_key": target_key},
        )
    ).mappings().one_or_none()
    if row is None:
        return None
    target = _row_to_target(row)
    await deactivate_poi_cache_target_feature_links(session, target.target_id)
    return target


async def deactivate_poi_cache_target_feature_links(
    session: AsyncSession,
    target_id: str,
) -> int:
    """target의 active feature links를 비활성화하고 갱신된 행 수를 반환."""
    result = await session.execute(
        text(_DEACTIVATE_LINKS_SQL),
        {"target_id": target_id},
    )
    return len(result.scalars().all())


async def upsert_poi_cache_target_feature_link(
    session: AsyncSession,
    *,
    target_id: str,
    feature_id: str,
    provider: str | None = None,
    dataset_key: str | None = None,
    distance_m: float | None = None,
    relation: str = "within_radius",
) -> PoiCacheTargetFeatureLink:
    """target-feature link를 upsert한다."""
    if relation not in _LINK_RELATIONS:
        raise ValueError(f"relation must be one of {sorted(_LINK_RELATIONS)}")
    row = (
        await session.execute(
            text(_UPSERT_LINK_SQL),
            {
                "target_id": target_id,
                "feature_id": feature_id,
                "provider": provider,
                "dataset_key": dataset_key,
                "distance_m": distance_m,
                "relation": relation,
            },
        )
    ).mappings().one()
    return _row_to_link(row)


async def list_poi_cache_target_feature_links(
    session: AsyncSession,
    target_id: str,
    *,
    active_only: bool = True,
    limit: int = 500,
) -> tuple[PoiCacheTargetFeatureLink, ...]:
    """target-feature link 목록 조회."""
    rows = (
        await session.execute(
            text(_LIST_LINKS_SQL),
            {
                "target_id": target_id,
                "active_only": active_only,
                "limit": max(1, min(limit, _MAX_LIST_LIMIT)),
            },
        )
    ).mappings().all()
    return tuple(_row_to_link(row) for row in rows)


async def mark_poi_cache_targets_refresh_requested(
    session: AsyncSession,
    target_ids: list[str],
) -> int:
    """target 기반 update request가 target을 실행 대상으로 잡았음을 기록한다."""
    if not target_ids:
        return 0
    result = await session.execute(
        text(_MARK_TARGETS_REQUESTED_SQL),
        {"target_ids": target_ids},
    )
    return len(result.scalars().all())


async def mark_poi_cache_targets_refreshed(
    session: AsyncSession,
    target_ids: list[str],
) -> int:
    """target 기반 update request 성공 시 target refresh 타임스탬프를 갱신한다."""
    if not target_ids:
        return 0
    result = await session.execute(
        text(_MARK_TARGETS_REFRESHED_SQL),
        {"target_ids": target_ids},
    )
    return len(result.scalars().all())


async def mark_poi_cache_targets_refresh_failed(
    session: AsyncSession,
    target_ids: list[str],
) -> int:
    """target 기반 update request 실패 시 target 실패 타임스탬프를 갱신한다."""
    if not target_ids:
        return 0
    result = await session.execute(
        text(_MARK_TARGETS_FAILED_SQL),
        {"target_ids": target_ids},
    )
    return len(result.scalars().all())

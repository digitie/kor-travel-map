"""``ops.poi_cache_targets`` repository (ADR-045 T-205c).

외부 앱 POI/cache target을 좌표만으로 식별하지 않고
``external_system + target_key``로 관리한다. target 주변 feature link는 후속
``cache_target_keys`` scope resolver와 targeted update 실행 본체가 재계산한다.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from sqlalchemy import text

from kortravelmap.core.sync_scope import MAX_EXTERNAL_SYSTEM_NAME_LENGTH

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "PoiCacheTarget",
    "PoiCacheTargetConflict",
    "PoiCacheTargetDeleteResult",
    "PoiCacheTargetFeatureLink",
    "PoiCacheTargetFeatureLinkCandidate",
    "PoiCacheTargetPage",
    "deactivate_poi_cache_target_feature_links",
    "delete_poi_cache_target",
    "get_poi_cache_target",
    "get_poi_cache_target_by_key",
    "get_dataset_projection_revision",
    "has_active_poi_cache_targets_for_external_system",
    "list_active_poi_cache_target_external_systems",
    "list_poi_cache_target_feature_links",
    "list_poi_cache_targets",
    "mark_poi_cache_targets_refresh_failed",
    "mark_poi_cache_targets_refresh_requested",
    "mark_poi_cache_targets_refreshed",
    "poi_cache_target_entity_tag",
    "sync_poi_cache_target_feature_links",
    "upsert_poi_cache_target",
    "upsert_poi_cache_target_feature_link",
    "list_active_target_coords",
]

OnConflict = Literal["reject", "move"]

# create 경합(패자 DO NOTHING → 재-lock)이 극단적으로 반복될 때의 상한.
# 소진되면 잠금 없는 DO UPDATE fall-through 대신 명확한 실패로 닫는다.
_CREATE_RACE_MAX_ATTEMPTS: Final[int] = 3

_LIST_ACTIVE_TARGET_COORDS_SQL: Final[str] = """
SELECT lon, lat
FROM ops.poi_cache_targets
WHERE deleted_at IS NULL AND update_enabled
ORDER BY lon, lat
"""

_LIST_ACTIVE_TARGET_COORDS_BY_SYSTEM_SQL: Final[str] = """
SELECT lon, lat
FROM ops.poi_cache_targets
WHERE external_system = :external_system
  AND deleted_at IS NULL
  AND update_enabled
ORDER BY lon, lat
"""

_LIST_ACTIVE_EXTERNAL_SYSTEMS_SQL: Final[str] = """
SELECT DISTINCT external_system
FROM ops.poi_cache_targets
WHERE deleted_at IS NULL AND update_enabled
ORDER BY external_system
"""

_HAS_ACTIVE_EXTERNAL_SYSTEM_SQL: Final[str] = """
SELECT EXISTS (
    SELECT 1
    FROM ops.poi_cache_targets
    WHERE external_system = :external_system
      AND deleted_at IS NULL
      AND update_enabled
)
"""

def _validate_exact_external_system(external_system: str) -> None:
    if not external_system or external_system != external_system.strip():
        raise ValueError("external_system must be trimmed and non-empty")
    if len(external_system) > MAX_EXTERNAL_SYSTEM_NAME_LENGTH:
        raise ValueError(
            "external_system must contain at most "
            f"{MAX_EXTERNAL_SYSTEM_NAME_LENGTH} characters"
        )


async def list_active_target_coords(
    session: AsyncSession,
    *,
    external_system: str | None = None,
) -> list[tuple[float, float]]:
    """활성(미삭제 + update_enabled) POI cache target의 ``(lon, lat)`` 목록.

    KMA weather 적재 대상 격자 산출용(T-219a) — 외부 시스템이 등록한 관심 지점이
    1차 weather 대상이다(`docs/reports/kma-mcst-provider-plan-2026-06-11.md` §2.1).
    ``external_system``을 주면 그 exact system의 target만 반환한다.
    정렬은 결정적(lon, lat) — 호출자(asset)가 격자 dedupe/상한을 적용한다.
    """
    if external_system is None:
        rows = (await session.execute(text(_LIST_ACTIVE_TARGET_COORDS_SQL))).all()
    else:
        _validate_exact_external_system(external_system)
        rows = (
            await session.execute(
                text(_LIST_ACTIVE_TARGET_COORDS_BY_SYSTEM_SQL),
                {"external_system": external_system},
            )
        ).all()
    return [(float(row.lon), float(row.lat)) for row in rows]


async def list_active_poi_cache_target_external_systems(
    session: AsyncSession,
) -> list[str]:
    """활성 target이 하나 이상인 canonical ``external_system`` 목록."""
    rows = (await session.execute(text(_LIST_ACTIVE_EXTERNAL_SYSTEMS_SQL))).all()
    return [str(row.external_system) for row in rows]


async def has_active_poi_cache_targets_for_external_system(
    session: AsyncSession,
    external_system: str,
) -> bool:
    """exact ``external_system``에 활성 target이 존재하는지 반환한다."""
    _validate_exact_external_system(external_system)
    return bool(
        (
            await session.execute(
                text(_HAS_ACTIVE_EXTERNAL_SYSTEM_SQL),
                {"external_system": external_system},
            )
        ).scalar_one()
    )


_SCOPE_MODES: Final[frozenset[str]] = frozenset({"center_radius", "sigungu_by_radius"})
_REFRESH_POLICIES: Final[frozenset[str]] = frozenset(
    {"provider_default", "follow_system", "allow_targeted", "disabled"}
)
_LINK_RELATIONS: Final[frozenset[str]] = frozenset({"within_radius", "same_sigungu", "manual"})
_MAX_LIST_LIMIT: Final[int] = 500

_TARGET_COLUMNS: Final[str] = (
    "target_id, lock_version, external_system, target_key, name, lon, lat, "
    "coord_precision_digits, "
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
class PoiCacheTargetDeleteResult:
    """조건부 soft-delete 결과.

    active row lock과 READ COMMITTED 재조회로 ``not_found``와
    ``precondition_failed``를 구분해 HTTP 계층이 각각 404와 412로 매핑하게 한다.
    """

    status: Literal["deleted", "not_found", "precondition_failed"]
    target: PoiCacheTarget | None = None


@dataclass(frozen=True)
class PoiCacheTarget:
    """``ops.poi_cache_targets`` row."""

    target_id: str
    lock_version: int
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

    @property
    def entity_tag(self) -> str:
        """server canonical strong ETag."""
        return poi_cache_target_entity_tag(self.target_id, self.lock_version)


@dataclass(frozen=True)
class PoiCacheTargetPage:
    """Keyset cursor 기반 POI/cache target 목록."""

    items: tuple[PoiCacheTarget, ...]
    next_cursor: str | None


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


@dataclass(frozen=True)
class PoiCacheTargetFeatureLinkCandidate:
    """한 번의 target-link 동기화에서 활성화할 link 입력."""

    target_id: str
    feature_id: str
    provider: str | None = None
    dataset_key: str | None = None
    distance_m: float | None = None
    relation: str = "within_radius"


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def poi_cache_target_entity_tag(target_id: str, lock_version: int) -> str:
    """UUID와 positive entity version으로 canonical opaque ETag를 만든다."""
    if lock_version < 1:
        raise ValueError("lock_version must be positive")
    return f'"{UUID(target_id)}:{lock_version}"'


def _limit(value: int) -> int:
    if value <= 0:
        raise ValueError("limit must be greater than 0")
    return min(value, _MAX_LIST_LIMIT)


def _encode_cursor(item: PoiCacheTarget) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "poi_cache_targets",
            "updated_at": item.updated_at.isoformat(),
            "target_id": item.target_id,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    padded = cursor + ("=" * (-len(cursor) % 4))
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid poi cache target cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid poi cache target cursor")
    if payload.get("v") != 1 or payload.get("kind") != "poi_cache_targets":
        raise ValueError("invalid poi cache target cursor")
    try:
        updated_at = datetime.fromisoformat(str(payload["updated_at"]))
        target_id = str(UUID(str(payload["target_id"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid poi cache target cursor") from exc
    return updated_at, target_id


def _row_to_target(row: Any) -> PoiCacheTarget:
    return PoiCacheTarget(
        target_id=str(row["target_id"]),
        lock_version=int(row["lock_version"]),
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
    _validate_exact_external_system(external_system)
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
        raise ValueError(f"refresh_policy must be one of {sorted(_REFRESH_POLICIES)}")
    if on_conflict not in ("reject", "move"):
        raise ValueError("on_conflict must be 'reject' or 'move'")


# upsert의 moved/reject 판정과 실제 write 사이 TOCTOU를 막기 위해 INSERT 본체를
# 공유하고 conflict tail만 나눈다. reject create 경합의 패자는 DO NOTHING 뒤
# `_LOCK_ACTIVE_TARGET_SQL` 재획득으로 stable row에서 다시 판정한다.
_INSERT_TARGET_CONFLICT_PREFIX_SQL: Final[str] = """
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
ON CONFLICT (external_system, target_key) WHERE deleted_at IS NULL
"""

_CREATE_TARGET_SQL: Final[str] = f"""{_INSERT_TARGET_CONFLICT_PREFIX_SQL} DO NOTHING
RETURNING {_TARGET_COLUMNS}
"""

_UPSERT_TARGET_SQL: Final[str] = f"""{_INSERT_TARGET_CONFLICT_PREFIX_SQL} DO UPDATE SET
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
  AND (
    CAST(:cursor_updated_at AS timestamptz) IS NULL
    OR (updated_at, target_id) < (
        CAST(:cursor_updated_at AS timestamptz),
        CAST(:cursor_target_id AS uuid)
    )
  )
ORDER BY updated_at DESC, target_id DESC
LIMIT :limit_plus_one
"""

_LOCK_ACTIVE_TARGET_SQL: Final[str] = """
SELECT target_id, lock_version, coord_key
FROM ops.poi_cache_targets
WHERE external_system = :external_system
  AND target_key = :target_key
  AND deleted_at IS NULL
FOR UPDATE
"""

_DELETE_TARGET_SQL: Final[str] = f"""
UPDATE ops.poi_cache_targets
SET deleted_at = now(),
    update_enabled = false,
    updated_at = now()
WHERE external_system = :external_system
  AND target_key = :target_key
  AND target_id = CAST(:expected_target_id AS uuid)
  AND lock_version = :expected_lock_version
  AND deleted_at IS NULL
RETURNING {_TARGET_COLUMNS}
"""

_GET_DATASET_PROJECTION_REVISION_SQL: Final[str] = """
SELECT revision
FROM ops.ops_live_topic_revisions
WHERE topic = 'dataset_projection'
"""

_DEACTIVATE_LINKS_SQL: Final[str] = """
UPDATE ops.poi_cache_target_feature_links
SET active = false,
    last_seen_at = now()
WHERE target_id = :target_id
  AND active
RETURNING 1
"""

_LOCK_ACTIVE_TARGETS_SQL: Final[str] = """
SELECT target_id
FROM ops.poi_cache_targets
WHERE target_id = ANY(CAST(:target_ids AS uuid[]))
  AND deleted_at IS NULL
ORDER BY target_id
FOR KEY SHARE
"""

# snapshot sync는 resolver 계산 link만 교체한다. 운영자가 직접 기록한
# ``relation='manual'`` link는 resolver 재계산 대상이 아니므로 보존한다(#699 패턴).
# 단건 ``_DEACTIVATE_LINKS_SQL``(delete/move 경로)은 target 자체가 무효화되므로
# manual link도 함께 비활성화한다.
_DEACTIVATE_LINKS_FOR_TARGETS_SQL: Final[str] = """
UPDATE ops.poi_cache_target_feature_links
SET active = false,
    last_seen_at = now()
WHERE target_id = ANY(CAST(:target_ids AS uuid[]))
  AND active
  AND relation <> 'manual'
RETURNING 1
"""

_LOCK_TARGET_LINKS_SQL: Final[str] = """
SELECT target_id, feature_id
FROM ops.poi_cache_target_feature_links
WHERE target_id = ANY(CAST(:target_ids AS uuid[]))
ORDER BY target_id, feature_id
FOR UPDATE
"""

# 기존 row가 운영자 ``relation='manual'``이면 resolver 재-upsert가 분류를 되돌리지
# 못한다(#699 패턴) — 되돌아가면 다음 snapshot sync가 manual link를 비활성화한다.
# 재분류가 필요하면 운영자가 link를 명시적으로 비활성화/삭제한 뒤 다시 만든다.
_LINK_RELATION_PRESERVE_MANUAL_SQL: Final[str] = """CASE
        WHEN poi_cache_target_feature_links.relation = 'manual'
            THEN poi_cache_target_feature_links.relation
        ELSE EXCLUDED.relation
    END"""

_UPSERT_LINK_SQL: Final[str] = f"""
WITH active_target AS (
    SELECT target_id
    FROM ops.poi_cache_targets
    WHERE target_id = CAST(:target_id AS uuid)
      AND deleted_at IS NULL
    FOR KEY SHARE
)
INSERT INTO ops.poi_cache_target_feature_links (
    target_id, feature_id, provider, dataset_key, distance_m, relation,
    active, last_seen_at
) SELECT
    active_target.target_id, :feature_id, :provider, :dataset_key, :distance_m,
    :relation, true, now()
FROM active_target
ON CONFLICT (target_id, feature_id) DO UPDATE SET
    provider = EXCLUDED.provider,
    dataset_key = EXCLUDED.dataset_key,
    distance_m = EXCLUDED.distance_m,
    relation = {_LINK_RELATION_PRESERVE_MANUAL_SQL},
    active = true,
    last_seen_at = now()
RETURNING {_LINK_COLUMNS}
"""

_UPSERT_LOCKED_LINK_SQL: Final[str] = f"""
INSERT INTO ops.poi_cache_target_feature_links (
    target_id, feature_id, provider, dataset_key, distance_m, relation,
    active, last_seen_at
) VALUES (
    CAST(:target_id AS uuid), :feature_id, :provider, :dataset_key, :distance_m,
    :relation, true, now()
)
ON CONFLICT (target_id, feature_id) DO UPDATE SET
    provider = EXCLUDED.provider,
    dataset_key = EXCLUDED.dataset_key,
    distance_m = EXCLUDED.distance_m,
    relation = {_LINK_RELATION_PRESERVE_MANUAL_SQL},
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

    moved/reject 판정은 항상 active natural-key row의 ``FOR UPDATE`` lock 아래에서
    계산한다(DELETE 경로와 같은 ``_LOCK_ACTIVE_TARGET_SQL`` 패턴). unlocked read로
    판정하면 동시 PUT의 패자가 ``ON CONFLICT UPDATE``로 승자의 좌표를 조용히
    덮어쓰거나, stale ``moved=False``로 이전 좌표의 active link를 남길 수 있다.
    create 경합의 패자는 ``DO NOTHING`` insert 뒤 lock을 재획득해 재판정한다.
    이 create→재-lock은 상한(``_CREATE_RACE_MAX_ATTEMPTS``) 있는 반복이며, 소진 시
    ``RuntimeError``로 실패한다 — ``DO UPDATE``는 lock 보유 없이는 실행되지 않는다.
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

    async def _lock_existing() -> Any:
        return (
            (
                await session.execute(
                    text(_LOCK_ACTIVE_TARGET_SQL),
                    {"external_system": external_system, "target_key": target_key},
                )
            )
            .mappings()
            .one_or_none()
        )

    def _moved(locked_row: Any) -> bool:
        moved_now = locked_row is not None and locked_row["coord_key"] != coord_key
        if moved_now and on_conflict == "reject":
            raise PoiCacheTargetConflict(
                f"active target {external_system}:{target_key} has different coord_key"
            )
        return moved_now

    write_params = {
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
    }

    existing = await _lock_existing()
    moved = _moved(existing)
    # DO UPDATE tail은 active row의 FOR UPDATE lock을 보유했을 때만 실행한다.
    # create 경합에서 밀린 뒤 재-lock이 다시 비면(winner commit 직후 동시
    # soft-delete) create→재-lock을 유한 반복하고, 소진 시 조용한 덮어쓰기 대신
    # 명확히 실패한다 — 잠금 없는 fall-through로 3자 경합 clobber를 열지 않는다.
    attempts_remaining = _CREATE_RACE_MAX_ATTEMPTS
    while existing is None:
        if attempts_remaining <= 0:
            raise RuntimeError(
                "poi cache target create race did not stabilize; retry the upsert"
            )
        attempts_remaining -= 1
        created = (
            (await session.execute(text(_CREATE_TARGET_SQL), write_params))
            .mappings()
            .one_or_none()
        )
        if created is not None:
            return _row_to_target(created)
        # create 경합에서 밀렸다 — winner commit까지 lock 획득이 블록되고, 그 뒤
        # stable row로 moved/reject를 다시 판정한다.
        existing = await _lock_existing()
        moved = _moved(existing)

    target = _row_to_target(
        (await session.execute(text(_UPSERT_TARGET_SQL), write_params))
        .mappings()
        .one()
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
        (
            await session.execute(
                text(_GET_TARGET_SQL),
                {"target_id": target_id, "include_deleted": include_deleted},
            )
        )
        .mappings()
        .one_or_none()
    )
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
        (
            await session.execute(
                text(_GET_TARGET_BY_KEY_SQL),
                {
                    "external_system": external_system,
                    "target_key": target_key,
                    "include_deleted": include_deleted,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return _row_to_target(row) if row is not None else None


async def list_poi_cache_targets(
    session: AsyncSession,
    *,
    external_system: str | None = None,
    update_enabled: bool | None = None,
    include_deleted: bool = False,
    limit: int = 200,
    cursor: str | None = None,
) -> PoiCacheTargetPage:
    """``updated_at DESC, target_id DESC`` keyset cursor로 target 목록 조회."""
    effective_limit = _limit(limit)
    cursor_updated_at, cursor_target_id = _decode_cursor(cursor)
    rows = (
        (
            await session.execute(
                text(_LIST_TARGETS_SQL),
                {
                    "external_system": external_system,
                    "update_enabled": update_enabled,
                    "include_deleted": include_deleted,
                    "cursor_updated_at": cursor_updated_at,
                    "cursor_target_id": cursor_target_id,
                    "limit_plus_one": effective_limit + 1,
                },
            )
        )
        .mappings()
        .all()
    )
    items = tuple(_row_to_target(row) for row in rows[:effective_limit])
    next_cursor = _encode_cursor(items[-1]) if len(rows) > effective_limit and items else None
    return PoiCacheTargetPage(items=items, next_cursor=next_cursor)


async def delete_poi_cache_target(
    session: AsyncSession,
    *,
    external_system: str,
    target_key: str,
    expected_target_id: str,
    expected_lock_version: int,
) -> PoiCacheTargetDeleteResult:
    """natural key row lock 뒤 UUID+version이 일치할 때만 soft-delete한다."""
    expected_target_id = str(UUID(expected_target_id))
    if expected_lock_version < 1:
        raise ValueError("expected_lock_version must be positive")
    lock_params = {"external_system": external_system, "target_key": target_key}
    active = (
        (
            await session.execute(
                text(_LOCK_ACTIVE_TARGET_SQL),
                lock_params,
            )
        )
        .mappings()
        .one_or_none()
    )
    if active is None:
        recreated = (
            (await session.execute(text(_LOCK_ACTIVE_TARGET_SQL), lock_params))
            .mappings()
            .one_or_none()
        )
        return PoiCacheTargetDeleteResult(
            status="precondition_failed" if recreated is not None else "not_found"
        )
    if (
        str(active["target_id"]) != expected_target_id
        or int(active["lock_version"]) != expected_lock_version
    ):
        return PoiCacheTargetDeleteResult(status="precondition_failed")
    row = (
        (
            await session.execute(
                text(_DELETE_TARGET_SQL),
                {
                    **lock_params,
                    "expected_target_id": expected_target_id,
                    "expected_lock_version": expected_lock_version,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:  # row lock을 보유하므로 invariant 위반이다.
        raise RuntimeError("locked POI/cache target conditional delete returned no row")
    target = _row_to_target(row)
    await deactivate_poi_cache_target_feature_links(session, target.target_id)
    return PoiCacheTargetDeleteResult(status="deleted", target=target)


async def get_dataset_projection_revision(session: AsyncSession) -> int:
    """현재 transaction에서 관측되는 ``dataset_projection`` live revision."""
    revision = (
        await session.execute(text(_GET_DATASET_PROJECTION_REVISION_SQL))
    ).scalar_one()
    return int(revision)


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
) -> PoiCacheTargetFeatureLink | None:
    """active parent를 KEY SHARE lock한 경우에만 target-feature link를 upsert한다."""
    if relation not in _LINK_RELATIONS:
        raise ValueError(f"relation must be one of {sorted(_LINK_RELATIONS)}")
    row = (
        (
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
        )
        .mappings()
        .one_or_none()
    )
    return _row_to_link(row) if row is not None else None


async def sync_poi_cache_target_feature_links(
    session: AsyncSession,
    *,
    target_ids: Sequence[str],
    candidates: Sequence[PoiCacheTargetFeatureLinkCandidate],
) -> tuple[PoiCacheTargetFeatureLink, ...]:
    """active parent 전체를 먼저 잠근 뒤 link snapshot을 원자적으로 교체한다.

    caller transaction 안에서 canonical UUID 순서로 모든 parent ``KEY SHARE`` lock을
    획득한다. 이후에만 기존 resolver link를 비활성화하고(운영자 ``relation='manual'``
    link는 보존) ``target_id, feature_id`` 순서로 새 link를 upsert한다.
    target delete도 parent ``FOR UPDATE`` 뒤 link를 갱신하므로 두
    경로의 잠금 순서는 항상 parent → link다.
    """
    canonical_target_ids = tuple(
        sorted({str(UUID(str(value))) for value in target_ids})
    )
    canonical_candidates: list[tuple[str, PoiCacheTargetFeatureLinkCandidate]] = []
    requested = set(canonical_target_ids)
    for candidate in candidates:
        if candidate.relation not in _LINK_RELATIONS:
            raise ValueError(f"relation must be one of {sorted(_LINK_RELATIONS)}")
        target_id = str(UUID(str(candidate.target_id)))
        if target_id not in requested:
            raise ValueError("candidate target_id must be included in target_ids")
        canonical_candidates.append((target_id, candidate))
    canonical_candidates.sort(key=lambda item: (item[0], item[1].feature_id))
    if not canonical_target_ids:
        return ()

    locked_target_ids = tuple(
        str(UUID(str(value)))
        for value in (
            await session.execute(
                text(_LOCK_ACTIVE_TARGETS_SQL),
                {"target_ids": list(canonical_target_ids)},
            )
        )
        .scalars()
        .all()
    )
    if not locked_target_ids:
        return ()
    locked = set(locked_target_ids)
    (
        await session.execute(
            text(_LOCK_TARGET_LINKS_SQL),
            {"target_ids": list(locked_target_ids)},
        )
    ).all()
    await session.execute(
        text(_DEACTIVATE_LINKS_FOR_TARGETS_SQL),
        {"target_ids": list(locked_target_ids)},
    )

    links: list[PoiCacheTargetFeatureLink] = []
    for target_id, candidate in canonical_candidates:
        if target_id not in locked:
            continue
        row = (
            (
                await session.execute(
                    text(_UPSERT_LOCKED_LINK_SQL),
                    {
                        "target_id": target_id,
                        "feature_id": candidate.feature_id,
                        "provider": candidate.provider,
                        "dataset_key": candidate.dataset_key,
                        "distance_m": candidate.distance_m,
                        "relation": candidate.relation,
                    },
                )
            )
            .mappings()
            .one()
        )
        links.append(_row_to_link(row))
    return tuple(links)


async def list_poi_cache_target_feature_links(
    session: AsyncSession,
    target_id: str,
    *,
    active_only: bool = True,
    limit: int = 500,
) -> tuple[PoiCacheTargetFeatureLink, ...]:
    """target-feature link 목록 조회."""
    rows = (
        (
            await session.execute(
                text(_LIST_LINKS_SQL),
                {
                    "target_id": target_id,
                    "active_only": active_only,
                    "limit": max(1, min(limit, _MAX_LIST_LIMIT)),
                },
            )
        )
        .mappings()
        .all()
    )
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

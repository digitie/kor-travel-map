"""``krtour.map.infra.scope_repo`` — feature update request scope resolver.

ADR-045 feature update request가 받은 scope를 실제 feature 집합으로 해석하는
read-only repository다. T-206a는 dry-run/count와 후속 queue bridge의 기반만 제공한다.

설계 원칙:
- raw SQL ``text()``만 사용한다(ADR-004).
- 공간 반경 검색은 입력 좌표를 CTE에서 한 번만 5179로 변환하고, 술어는
  ``feature.features.coord_5179``에 직접 적용한다(ADR-012).
- kraddr-geo HTTP client는 repo가 소유하지 않는다. ``sigungu_by_radius``는 호출자가
  주입한 async resolver를 통해 시군구 코드만 받는다(레이어 역행 방지).
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureScopeRow",
    "CacheTargetFeatureMatch",
    "CacheTargetScopeTarget",
    "ProviderDatasetScope",
    "ScopeResolution",
    "SigunguByRadiusResolver",
    "resolve_feature_ids",
    "resolve_center_radius",
    "resolve_bbox",
    "resolve_sigungu_by_radius",
    "resolve_provider_dataset",
    "resolve_cache_target_keys",
    "count_features_matching_scope",
]

ScopeType = Literal[
    "feature_ids",
    "center_radius",
    "sigungu_by_radius",
    "bbox",
    "provider_dataset",
    "cache_target_keys",
]


@dataclass(frozen=True)
class FeatureScopeRow:
    """scope resolver가 반환하는 최소 feature row."""

    feature_id: str
    sigungu_code: str | None = None


@dataclass(frozen=True)
class ProviderDatasetScope:
    """scope에 포함된 feature의 primary provider/dataset 묶음."""

    provider: str
    dataset_key: str
    feature_count: int


@dataclass(frozen=True)
class CacheTargetScopeTarget:
    """``cache_target_keys`` scope에 포함된 active POI/cache target."""

    target_id: str
    external_system: str
    target_key: str
    lon: float
    lat: float
    radius_km: float
    scope_mode: str
    refresh_policy: str
    provider_overrides: dict[str, Any]


@dataclass(frozen=True)
class CacheTargetFeatureMatch:
    """target별 주변 feature 매칭 결과."""

    target_id: str
    feature_id: str
    provider: str | None
    dataset_key: str | None
    distance_m: float | None
    relation: str


@dataclass(frozen=True)
class ScopeResolution:
    """feature update request dry-run/queue가 공유하는 scope 해석 결과."""

    scope_type: ScopeType
    features: tuple[FeatureScopeRow, ...]
    provider_datasets: tuple[ProviderDatasetScope, ...] = ()
    sigungu_codes: tuple[str, ...] = ()
    cache_targets: tuple[CacheTargetScopeTarget, ...] = ()
    cache_target_matches: tuple[CacheTargetFeatureMatch, ...] = ()
    extra_matched_scope: Mapping[str, Any] = field(default_factory=dict)

    @property
    def feature_ids(self) -> tuple[str, ...]:
        return tuple(row.feature_id for row in self.features)

    @property
    def feature_count(self) -> int:
        return len(self.features)

    def matched_scope(self) -> dict[str, Any]:
        """``ops.feature_update_requests.matched_scope``에 저장할 JSONB payload."""
        payload: dict[str, Any] = {
            "feature_count": self.feature_count,
            "sigungu_codes": list(self.sigungu_codes),
        }
        if self.provider_datasets:
            provider_payload = [
                {
                    "provider": item.provider,
                    "dataset_key": item.dataset_key,
                    "feature_count": item.feature_count,
                }
                for item in self.provider_datasets
            ]
            payload["provider_datasets"] = provider_payload
            if self.scope_type == "cache_target_keys":
                payload["deduped_provider_scopes"] = provider_payload
        if self.extra_matched_scope:
            payload.update(dict(self.extra_matched_scope))
        return payload


class SigunguByRadiusResolver(Protocol):
    """kraddr-geo REST v2 ``/v2/regions/within-radius`` 호출을 감싼 콜러블."""

    def __call__(
        self,
        *,
        lon: float,
        lat: float,
        radius_km: float,
    ) -> Awaitable[tuple[str, ...]]: ...


_RESOLVE_FEATURE_IDS_SQL: Final[str] = """
WITH requested AS (
    SELECT feature_id, ord
    FROM unnest(CAST(:feature_ids AS text[])) WITH ORDINALITY AS r(feature_id, ord)
)
SELECT f.feature_id, f.sigungu_code
FROM requested AS r
JOIN feature.features AS f
  ON f.feature_id = r.feature_id
WHERE f.deleted_at IS NULL
ORDER BY r.ord
"""

_RESOLVE_CENTER_RADIUS_SQL: Final[str] = """
WITH input AS (
    SELECT x_extension.ST_Transform(
        x_extension.ST_SetSRID(
            x_extension.ST_MakePoint(
                CAST(:lon AS double precision),
                CAST(:lat AS double precision)
            ),
            4326
        ),
        5179
    ) AS pt
)
SELECT f.feature_id, f.sigungu_code
FROM feature.features AS f, input AS i
WHERE f.deleted_at IS NULL
  AND f.coord_5179 IS NOT NULL
  AND x_extension.ST_DWithin(
        f.coord_5179,
        i.pt,
        CAST(:radius_m AS double precision)
      )
ORDER BY f.coord_5179 <-> i.pt, f.feature_id
"""

_RESOLVE_BBOX_SQL: Final[str] = """
SELECT f.feature_id, f.sigungu_code
FROM feature.features AS f
WHERE f.deleted_at IS NULL
  AND f.coord IS NOT NULL
  AND f.coord && x_extension.ST_MakeEnvelope(
        CAST(:min_lon AS double precision),
        CAST(:min_lat AS double precision),
        CAST(:max_lon AS double precision),
        CAST(:max_lat AS double precision),
        4326
      )
ORDER BY f.feature_id
"""

_RESOLVE_SIGUNGU_CODES_SQL: Final[str] = """
SELECT f.feature_id, f.sigungu_code
FROM feature.features AS f
WHERE f.deleted_at IS NULL
  AND f.sigungu_code = ANY(CAST(:sigungu_codes AS text[]))
ORDER BY f.feature_id
"""

_RESOLVE_PROVIDER_DATASET_SQL: Final[str] = """
SELECT DISTINCT f.feature_id, f.sigungu_code
FROM feature.features AS f
JOIN provider_sync.source_links AS sl
  ON sl.feature_id = f.feature_id
JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = sl.source_record_key
WHERE f.deleted_at IS NULL
  AND sl.is_primary_source
  AND sr.provider = :provider
  AND sr.dataset_key = :dataset_key
ORDER BY f.feature_id
"""

_PROVIDER_DATASETS_FOR_FEATURE_IDS_SQL: Final[str] = """
SELECT sr.provider, sr.dataset_key, count(DISTINCT sl.feature_id)::int AS feature_count
FROM provider_sync.source_links AS sl
JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = sl.source_record_key
WHERE sl.is_primary_source
  AND sl.feature_id = ANY(CAST(:feature_ids AS text[]))
GROUP BY sr.provider, sr.dataset_key
ORDER BY sr.provider, sr.dataset_key
"""

_CACHE_TARGETS_BY_KEYS_SQL: Final[str] = """
WITH requested AS (
    SELECT target_key, ord
    FROM unnest(CAST(:target_keys AS text[])) WITH ORDINALITY AS r(target_key, ord)
),
ranked AS (
    SELECT
        r.target_key AS requested_key,
        r.ord,
        t.target_id,
        t.external_system,
        t.target_key,
        t.lon,
        t.lat,
        t.radius_km,
        t.scope_mode,
        t.update_enabled,
        t.refresh_policy,
        t.provider_overrides,
        t.deleted_at,
        row_number() OVER (
            PARTITION BY r.target_key
            ORDER BY
                (t.deleted_at IS NULL) DESC,
                t.updated_at DESC NULLS LAST,
                t.target_id
        ) AS rn
    FROM requested AS r
    LEFT JOIN ops.poi_cache_targets AS t
      ON t.external_system = :external_system
     AND t.target_key = r.target_key
)
SELECT *
FROM ranked
WHERE rn = 1 OR rn IS NULL
ORDER BY ord
"""

_CACHE_TARGET_CENTER_MATCHES_SQL: Final[str] = """
WITH selected_targets AS (
    SELECT
        target_id::text AS target_id,
        target_key,
        coord_5179,
        COALESCE(CAST(:radius_km AS double precision), radius_km) * 1000.0 AS radius_m
    FROM ops.poi_cache_targets
    WHERE target_id::text = ANY(CAST(:target_ids AS text[]))
      AND deleted_at IS NULL
      AND update_enabled
)
SELECT
    t.target_id,
    f.feature_id,
    f.sigungu_code,
    sr.provider,
    sr.dataset_key,
    CASE
      WHEN f.coord_5179 IS NULL OR t.coord_5179 IS NULL THEN NULL
      ELSE x_extension.ST_Distance(f.coord_5179, t.coord_5179)::double precision
    END AS distance_m,
    'within_radius' AS relation
FROM selected_targets AS t
JOIN feature.features AS f
  ON f.deleted_at IS NULL
 AND f.coord_5179 IS NOT NULL
 AND t.coord_5179 IS NOT NULL
 AND x_extension.ST_DWithin(f.coord_5179, t.coord_5179, t.radius_m)
LEFT JOIN provider_sync.source_links AS sl
  ON sl.feature_id = f.feature_id
 AND sl.is_primary_source
LEFT JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = sl.source_record_key
ORDER BY t.target_id, distance_m NULLS LAST, f.feature_id
"""

_CACHE_TARGET_SIGUNGU_MATCHES_SQL: Final[str] = """
SELECT
    CAST(:target_id AS text) AS target_id,
    f.feature_id,
    f.sigungu_code,
    sr.provider,
    sr.dataset_key,
    CASE
      WHEN f.coord_5179 IS NULL OR t.coord_5179 IS NULL THEN NULL
      ELSE x_extension.ST_Distance(f.coord_5179, t.coord_5179)::double precision
    END AS distance_m,
    'same_sigungu' AS relation
FROM ops.poi_cache_targets AS t
JOIN feature.features AS f
  ON f.deleted_at IS NULL
 AND f.sigungu_code = ANY(CAST(:sigungu_codes AS text[]))
LEFT JOIN provider_sync.source_links AS sl
  ON sl.feature_id = f.feature_id
 AND sl.is_primary_source
LEFT JOIN provider_sync.source_records AS sr
  ON sr.source_record_key = sl.source_record_key
WHERE t.target_id::text = CAST(:target_id AS text)
ORDER BY f.feature_id
"""


def _unique_preserve_order(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _rows_to_features(rows: Sequence[Any]) -> tuple[FeatureScopeRow, ...]:
    return tuple(
        FeatureScopeRow(
            feature_id=str(row["feature_id"]),
            sigungu_code=row["sigungu_code"],
        )
        for row in rows
    )


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _row_to_cache_target(row: Any) -> CacheTargetScopeTarget:
    return CacheTargetScopeTarget(
        target_id=str(row["target_id"]),
        external_system=str(row["external_system"]),
        target_key=str(row["target_key"]),
        lon=float(row["lon"]),
        lat=float(row["lat"]),
        radius_km=float(row["radius_km"]),
        scope_mode=str(row["scope_mode"]),
        refresh_policy=str(row["refresh_policy"]),
        provider_overrides=_json_dict(row["provider_overrides"]),
    )


def _row_to_cache_match(row: Any) -> CacheTargetFeatureMatch:
    distance = row["distance_m"]
    return CacheTargetFeatureMatch(
        target_id=str(row["target_id"]),
        feature_id=str(row["feature_id"]),
        provider=row["provider"],
        dataset_key=row["dataset_key"],
        distance_m=float(distance) if distance is not None else None,
        relation=str(row["relation"]),
    )


def _sigungu_codes(features: Sequence[FeatureScopeRow]) -> tuple[str, ...]:
    return tuple(
        sorted({row.sigungu_code for row in features if row.sigungu_code})
    )


async def _provider_datasets_for_feature_ids(
    session: AsyncSession,
    feature_ids: Sequence[str],
) -> tuple[ProviderDatasetScope, ...]:
    if not feature_ids:
        return ()
    rows = (
        await session.execute(
            text(_PROVIDER_DATASETS_FOR_FEATURE_IDS_SQL),
            {"feature_ids": list(feature_ids)},
        )
    ).mappings().all()
    return tuple(
        ProviderDatasetScope(
            provider=str(row["provider"]),
            dataset_key=str(row["dataset_key"]),
            feature_count=int(row["feature_count"]),
        )
        for row in rows
    )


def _features_from_matches(
    matches: Sequence[CacheTargetFeatureMatch],
    sigungu_by_feature_id: Mapping[str, str | None],
) -> tuple[FeatureScopeRow, ...]:
    seen: set[str] = set()
    features: list[FeatureScopeRow] = []
    for match in matches:
        if match.feature_id in seen:
            continue
        seen.add(match.feature_id)
        features.append(
            FeatureScopeRow(
                feature_id=match.feature_id,
                sigungu_code=sigungu_by_feature_id.get(match.feature_id),
            )
        )
    return tuple(features)


def _effective_scope_mode(
    target: CacheTargetScopeTarget,
    scope_mode: str | None,
) -> str:
    mode = scope_mode or target.scope_mode
    if mode not in {"center_radius", "sigungu_by_radius"}:
        raise ValueError("scope_mode must be 'center_radius' or 'sigungu_by_radius'")
    return mode


async def _resolution(
    session: AsyncSession,
    scope_type: ScopeType,
    features: tuple[FeatureScopeRow, ...],
    *,
    cache_targets: tuple[CacheTargetScopeTarget, ...] = (),
    cache_target_matches: tuple[CacheTargetFeatureMatch, ...] = (),
    extra_matched_scope: Mapping[str, Any] | None = None,
) -> ScopeResolution:
    provider_datasets = await _provider_datasets_for_feature_ids(
        session,
        [row.feature_id for row in features],
    )
    return ScopeResolution(
        scope_type=scope_type,
        features=features,
        provider_datasets=provider_datasets,
        sigungu_codes=_sigungu_codes(features),
        cache_targets=cache_targets,
        cache_target_matches=cache_target_matches,
        extra_matched_scope=extra_matched_scope or {},
    )


async def resolve_feature_ids(
    session: AsyncSession,
    feature_ids: Sequence[str],
) -> ScopeResolution:
    """존재하는 feature id만 입력 순서대로 해석한다."""
    unique_ids = _unique_preserve_order(feature_ids)
    if not unique_ids:
        return ScopeResolution(scope_type="feature_ids", features=())
    rows = (
        await session.execute(
            text(_RESOLVE_FEATURE_IDS_SQL),
            {"feature_ids": list(unique_ids)},
        )
    ).mappings().all()
    return await _resolution(session, "feature_ids", _rows_to_features(rows))


async def resolve_center_radius(
    session: AsyncSession,
    *,
    lon: float,
    lat: float,
    radius_km: float,
) -> ScopeResolution:
    """좌표 중심 반경 안 feature를 ``coord_5179`` + ``ST_DWithin``으로 해석한다."""
    if radius_km <= 0:
        raise ValueError("radius_km must be greater than 0")
    rows = (
        await session.execute(
            text(_RESOLVE_CENTER_RADIUS_SQL),
            {
                "lon": lon,
                "lat": lat,
                "radius_m": radius_km * 1000.0,
            },
        )
    ).mappings().all()
    return await _resolution(session, "center_radius", _rows_to_features(rows))


async def resolve_bbox(
    session: AsyncSession,
    *,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
) -> ScopeResolution:
    """bbox 안 feature를 해석한다. 입력 좌표계는 WGS84 lon/lat."""
    if min_lon > max_lon or min_lat > max_lat:
        raise ValueError("bbox min values must be less than or equal to max values")
    rows = (
        await session.execute(
            text(_RESOLVE_BBOX_SQL),
            {
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
            },
        )
    ).mappings().all()
    return await _resolution(session, "bbox", _rows_to_features(rows))


async def resolve_sigungu_by_radius(
    session: AsyncSession,
    *,
    lon: float,
    lat: float,
    radius_km: float,
    sigungu_resolver: SigunguByRadiusResolver,
) -> ScopeResolution:
    """kraddr-geo가 계산한 반경 교차 시군구 코드로 feature를 해석한다."""
    if radius_km <= 0:
        raise ValueError("radius_km must be greater than 0")
    sigungu_codes = _unique_preserve_order(
        await sigungu_resolver(lon=lon, lat=lat, radius_km=radius_km)
    )
    if not sigungu_codes:
        return ScopeResolution(scope_type="sigungu_by_radius", features=())
    rows = (
        await session.execute(
            text(_RESOLVE_SIGUNGU_CODES_SQL),
            {"sigungu_codes": list(sigungu_codes)},
        )
    ).mappings().all()
    resolution = await _resolution(
        session, "sigungu_by_radius", _rows_to_features(rows)
    )
    matched_codes = set(resolution.sigungu_codes)
    return ScopeResolution(
        scope_type=resolution.scope_type,
        features=resolution.features,
        provider_datasets=resolution.provider_datasets,
        sigungu_codes=tuple(
            code for code in sigungu_codes if code in matched_codes
        ),
    )


async def resolve_provider_dataset(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
) -> ScopeResolution:
    """primary source가 특정 provider/dataset인 feature를 해석한다."""
    rows = (
        await session.execute(
            text(_RESOLVE_PROVIDER_DATASET_SQL),
            {"provider": provider, "dataset_key": dataset_key},
        )
    ).mappings().all()
    return await _resolution(session, "provider_dataset", _rows_to_features(rows))


async def resolve_cache_target_keys(
    session: AsyncSession,
    *,
    external_system: str,
    target_keys: Sequence[str],
    radius_km: float | None = None,
    scope_mode: str | None = None,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> ScopeResolution:
    """외부 POI/cache target key 목록을 주변 feature union으로 해석한다.

    삭제되었거나 update 비활성화된 target은 제외하고, missing/deleted/disabled
    key는 ``matched_scope`` payload에 남긴다. 본 resolver는 read-only이며
    ``ops.poi_cache_target_feature_links`` 재계산은 실행기(T-206d)가 담당한다.
    """
    if not external_system:
        raise ValueError("cache_target_keys scope requires external_system")
    unique_keys = _unique_preserve_order([str(key) for key in target_keys])
    if not unique_keys:
        return ScopeResolution(
            scope_type="cache_target_keys",
            features=(),
            extra_matched_scope={
                "target_count": 0,
                "active_target_count": 0,
                "skipped_deleted_keys": [],
                "skipped_disabled_keys": [],
                "skipped_missing_keys": [],
            },
        )
    if radius_km is not None and radius_km <= 0:
        raise ValueError("radius_km must be greater than 0")

    rows = (
        await session.execute(
            text(_CACHE_TARGETS_BY_KEYS_SQL),
            {"external_system": external_system, "target_keys": list(unique_keys)},
        )
    ).mappings().all()
    active_targets: list[CacheTargetScopeTarget] = []
    skipped_deleted: list[str] = []
    skipped_disabled: list[str] = []
    skipped_missing: list[str] = []
    for row in rows:
        requested_key = str(row["requested_key"])
        if row["target_id"] is None:
            skipped_missing.append(requested_key)
            continue
        if row["deleted_at"] is not None:
            skipped_deleted.append(requested_key)
            continue
        if not bool(row["update_enabled"]) or row["refresh_policy"] == "disabled":
            skipped_disabled.append(requested_key)
            continue
        active_targets.append(_row_to_cache_target(row))

    matches: list[CacheTargetFeatureMatch] = []
    sigungu_by_feature_id: dict[str, str | None] = {}
    center_target_ids = [
        target.target_id
        for target in active_targets
        if _effective_scope_mode(target, scope_mode) == "center_radius"
    ]
    if center_target_ids:
        center_rows = (
            await session.execute(
                text(_CACHE_TARGET_CENTER_MATCHES_SQL),
                {
                    "target_ids": center_target_ids,
                    "radius_km": radius_km,
                },
            )
        ).mappings().all()
        for row in center_rows:
            match = _row_to_cache_match(row)
            matches.append(match)
            sigungu_by_feature_id[match.feature_id] = row["sigungu_code"]

    for target in active_targets:
        if _effective_scope_mode(target, scope_mode) != "sigungu_by_radius":
            continue
        if sigungu_resolver is None:
            raise ValueError("sigungu_by_radius cache target scope requires sigungu_resolver")
        effective_radius_km = radius_km if radius_km is not None else target.radius_km
        sigungu_codes = _unique_preserve_order(
            await sigungu_resolver(
                lon=target.lon,
                lat=target.lat,
                radius_km=effective_radius_km,
            )
        )
        if not sigungu_codes:
            continue
        sigungu_rows = (
            await session.execute(
                text(_CACHE_TARGET_SIGUNGU_MATCHES_SQL),
                {
                    "target_id": target.target_id,
                    "sigungu_codes": list(sigungu_codes),
                },
            )
        ).mappings().all()
        for row in sigungu_rows:
            match = _row_to_cache_match(row)
            matches.append(match)
            sigungu_by_feature_id[match.feature_id] = row["sigungu_code"]

    features = _features_from_matches(matches, sigungu_by_feature_id)
    return await _resolution(
        session,
        "cache_target_keys",
        features,
        cache_targets=tuple(active_targets),
        cache_target_matches=tuple(matches),
        extra_matched_scope={
            "target_count": len(unique_keys),
            "active_target_count": len(active_targets),
            "skipped_deleted_keys": skipped_deleted,
            "skipped_disabled_keys": skipped_disabled,
            "skipped_missing_keys": skipped_missing,
        },
    )


async def count_features_matching_scope(
    session: AsyncSession,
    scope: dict[str, Any],
    *,
    sigungu_resolver: SigunguByRadiusResolver | None = None,
) -> ScopeResolution:
    """OpenAPI scope payload를 해석해 dry-run용 count/matched_scope를 반환한다."""
    scope_type = scope.get("type")
    if scope_type == "feature_ids":
        raw_ids = scope.get("feature_ids", ())
        if not isinstance(raw_ids, list):
            raise ValueError("feature_ids scope requires feature_ids list")
        return await resolve_feature_ids(session, [str(item) for item in raw_ids])
    if scope_type == "center_radius":
        center = scope.get("center")
        if not isinstance(center, dict):
            raise ValueError("center_radius scope requires center")
        return await resolve_center_radius(
            session,
            lon=float(center["lon"]),
            lat=float(center["lat"]),
            radius_km=float(scope["radius_km"]),
        )
    if scope_type == "bbox":
        return await resolve_bbox(
            session,
            min_lon=float(scope["min_lon"]),
            min_lat=float(scope["min_lat"]),
            max_lon=float(scope["max_lon"]),
            max_lat=float(scope["max_lat"]),
        )
    if scope_type == "provider_dataset":
        return await resolve_provider_dataset(
            session,
            provider=str(scope["provider"]),
            dataset_key=str(scope["dataset_key"]),
        )
    if scope_type == "cache_target_keys":
        raw_keys = scope.get("target_keys", ())
        if not isinstance(raw_keys, list):
            raise ValueError("cache_target_keys scope requires target_keys list")
        radius_km = (
            float(scope["radius_km"]) if scope.get("radius_km") is not None else None
        )
        raw_scope_mode = scope.get("scope_mode")
        return await resolve_cache_target_keys(
            session,
            external_system=str(scope["external_system"]),
            target_keys=[str(item) for item in raw_keys],
            radius_km=radius_km,
            scope_mode=str(raw_scope_mode) if raw_scope_mode is not None else None,
            sigungu_resolver=sigungu_resolver,
        )
    if scope_type == "sigungu_by_radius":
        if sigungu_resolver is None:
            raise ValueError("sigungu_by_radius scope requires sigungu_resolver")
        center = scope.get("center")
        if not isinstance(center, dict):
            raise ValueError("sigungu_by_radius scope requires center")
        return await resolve_sigungu_by_radius(
            session,
            lon=float(center["lon"]),
            lat=float(center["lat"]),
            radius_km=float(scope["radius_km"]),
            sigungu_resolver=sigungu_resolver,
        )
    raise ValueError(f"unsupported scope type: {scope_type!r}")

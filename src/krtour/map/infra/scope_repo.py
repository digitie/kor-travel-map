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

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureScopeRow",
    "ProviderDatasetScope",
    "ScopeResolution",
    "SigunguByRadiusResolver",
    "resolve_feature_ids",
    "resolve_center_radius",
    "resolve_bbox",
    "resolve_sigungu_by_radius",
    "resolve_provider_dataset",
    "count_features_matching_scope",
]

ScopeType = Literal[
    "feature_ids",
    "center_radius",
    "sigungu_by_radius",
    "bbox",
    "provider_dataset",
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
class ScopeResolution:
    """feature update request dry-run/queue가 공유하는 scope 해석 결과."""

    scope_type: ScopeType
    features: tuple[FeatureScopeRow, ...]
    provider_datasets: tuple[ProviderDatasetScope, ...] = ()
    sigungu_codes: tuple[str, ...] = ()

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
            payload["provider_datasets"] = [
                {
                    "provider": item.provider,
                    "dataset_key": item.dataset_key,
                    "feature_count": item.feature_count,
                }
                for item in self.provider_datasets
            ]
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


async def _resolution(
    session: AsyncSession,
    scope_type: ScopeType,
    features: tuple[FeatureScopeRow, ...],
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

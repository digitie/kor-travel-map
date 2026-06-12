"""``infra.scope_repo`` feature update request scope resolver 통합 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from kortravelmap.infra import feature_repo, scope_repo
from kortravelmap.infra.poi_cache_target_repo import upsert_poi_cache_target
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 — provider 실모델 필드명 (#374)."""

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


async def _bundle(
    seed: str,
    *,
    lon: str = "126.9239",
    lat: str = "37.5263",
    bjd_code: str = "1156011000",
    sigungu_code: str = "11560",
):
    # 자연키는 name::address 파생(#374) — seed를 이름에 넣어 feature 구분.
    # bjd_code/sigungu_code는 변환 입력이 아니라 _load()의 직접 UPDATE 값.
    del bjd_code, sigungu_code
    item = _Festival(
        fstvl_nm=f"스코프 테스트 축제 {seed}",
        opar="테스트 공원",
        fstvl_start_date=date(2026, 4, 5),
        fstvl_end_date=date(2026, 4, 12),
        fstvl_co="scope resolver 테스트용 fixture.",
        mnnst_nm="영등포구청",
        phone_number="02-2670-3114",
        rdnmadr="서울특별시 영등포구 여의공원로 120",
        lnmadr="서울특별시 영등포구 여의도동 8",
        latitude=float(lat),
        longitude=float(lon),
        reference_date=date(2026, 3, 1),
        instt_nm="서울특별시 영등포구",
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
        )
    )[0]


async def _load(
    session: AsyncSession,
    seed: str,
    **kwargs: str,
):
    sigungu_code = kwargs.get("sigungu_code", "11560")
    bjd_code = kwargs.get("bjd_code", "1156011000")
    bundle = await _bundle(seed, **kwargs)
    await feature_repo.load_bundle(session, bundle)
    await session.execute(
        text(
            """
            UPDATE feature.features
            SET sigungu_code = :sigungu_code,
                sido_code = :sido_code,
                legal_dong_code = :bjd_code
            WHERE feature_id = :feature_id
            """
        ),
        {
            "feature_id": bundle.feature.feature_id,
            "sigungu_code": sigungu_code,
            "sido_code": bjd_code[:2],
            "bjd_code": bjd_code,
        },
    )
    await session.flush()
    return bundle


async def test_resolve_feature_ids_filters_existing_and_preserves_order(
    migrated_session: AsyncSession,
) -> None:
    first = await _load(migrated_session, "SCOPE-ID-1", sigungu_code="11110")
    second = await _load(migrated_session, "SCOPE-ID-2", sigungu_code="11140")

    result = await scope_repo.resolve_feature_ids(
        migrated_session,
        [
            "missing",
            second.feature.feature_id,
            first.feature.feature_id,
            second.feature.feature_id,
        ],
    )

    assert result.feature_ids == (
        second.feature.feature_id,
        first.feature.feature_id,
    )
    assert result.feature_count == 2
    assert result.sigungu_codes == ("11110", "11140")
    assert result.matched_scope()["feature_count"] == 2
    assert result.provider_datasets[0].feature_count == 2


async def test_count_feature_ids_excludes_deleted_features_from_provider_counts(
    migrated_session: AsyncSession,
) -> None:
    active = await _load(migrated_session, "SCOPE-ID-COUNT-ACTIVE", sigungu_code="11110")
    deleted = await _load(migrated_session, "SCOPE-ID-COUNT-DELETED", sigungu_code="11140")
    await migrated_session.execute(
        text(
            """
            UPDATE feature.features
            SET status = 'inactive',
                deleted_at = now()
            WHERE feature_id = :feature_id
            """
        ),
        {"feature_id": deleted.feature.feature_id},
    )
    await migrated_session.flush()

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {
            "type": "feature_ids",
            "feature_ids": [
                active.feature.feature_id,
                deleted.feature.feature_id,
            ],
        },
        preview_limit=10,
    )

    assert result.feature_ids == (active.feature.feature_id,)
    assert result.feature_count == 1
    assert result.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider=active.source_record.provider,
            dataset_key=active.source_record.dataset_key,
            feature_count=1,
        ),
    )


async def test_resolve_center_radius_uses_coord_5179_distance(
    migrated_session: AsyncSession,
) -> None:
    near = await _load(
        migrated_session,
        "SCOPE-RADIUS-NEAR",
        lon="126.9239",
        lat="37.5263",
        sigungu_code="11560",
    )
    await _load(
        migrated_session,
        "SCOPE-RADIUS-FAR",
        lon="129.0756",
        lat="35.1796",
        bjd_code="2611010100",
        sigungu_code="26110",
    )

    result = await scope_repo.resolve_center_radius(
        migrated_session,
        lon=126.9239,
        lat=37.5263,
        radius_km=1.0,
    )

    assert result.feature_ids == (near.feature.feature_id,)
    assert result.sigungu_codes == ("11560",)
    assert result.matched_scope()["provider_datasets"][0]["feature_count"] == 1


async def test_count_center_radius_uses_limited_preview_and_full_counts(
    migrated_session: AsyncSession,
) -> None:
    bundles = [
        await _load(
            migrated_session,
            f"SCOPE-RADIUS-COUNT-{index}",
            lon="126.9239",
            lat="37.5263",
            sigungu_code="11560",
        )
        for index in range(3)
    ]

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {
            "type": "center_radius",
            "center": {"lon": 126.9239, "lat": 37.5263},
            "radius_km": 1.0,
        },
        preview_limit=1,
    )

    assert result.feature_count == 3
    assert len(result.feature_ids) == 1
    assert set(result.feature_ids) <= {
        bundle.feature.feature_id for bundle in bundles
    }
    assert result.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider=bundles[0].source_record.provider,
            dataset_key=bundles[0].source_record.dataset_key,
            feature_count=3,
        ),
    )
    matched = result.matched_scope()
    assert matched["feature_count"] == 3
    assert matched["feature_preview_count"] == 1
    assert matched["feature_preview_limit"] == 1
    assert matched["feature_preview_truncated"] is True


async def test_resolve_bbox_and_provider_dataset(
    migrated_session: AsyncSession,
) -> None:
    bundle = await _load(migrated_session, "SCOPE-BBOX", sigungu_code="11560")

    bbox = await scope_repo.resolve_bbox(
        migrated_session,
        min_lon=126.8,
        min_lat=37.4,
        max_lon=127.0,
        max_lat=37.7,
    )
    assert bundle.feature.feature_id in bbox.feature_ids

    provider_scope = await scope_repo.resolve_provider_dataset(
        migrated_session,
        provider=bundle.source_record.provider,
        dataset_key=bundle.source_record.dataset_key,
    )
    assert bundle.feature.feature_id in provider_scope.feature_ids
    assert provider_scope.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider=bundle.source_record.provider,
            dataset_key=bundle.source_record.dataset_key,
            feature_count=1,
        ),
    )


async def test_count_provider_dataset_uses_limited_preview_and_full_count(
    migrated_session: AsyncSession,
) -> None:
    bundles = [
        await _load(
            migrated_session,
            f"SCOPE-PROVIDER-COUNT-{index}",
            sigungu_code="11560",
        )
        for index in range(3)
    ]
    provider = bundles[0].source_record.provider
    dataset_key = bundles[0].source_record.dataset_key

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {
            "type": "provider_dataset",
            "provider": provider,
            "dataset_key": dataset_key,
        },
        preview_limit=1,
    )

    assert result.feature_count == 3
    assert len(result.feature_ids) == 1
    assert set(result.feature_ids) <= {
        bundle.feature.feature_id for bundle in bundles
    }
    assert result.provider_datasets == (
        scope_repo.ProviderDatasetScope(
            provider=provider,
            dataset_key=dataset_key,
            feature_count=3,
        ),
    )
    assert result.matched_scope()["feature_preview_truncated"] is True


async def test_resolve_sigungu_by_radius_uses_injected_kraddr_resolver(
    migrated_session: AsyncSession,
) -> None:
    included = await _load(
        migrated_session,
        "SCOPE-SIGUNGU-IN",
        bjd_code="1114010100",
        sigungu_code="11140",
    )
    await _load(
        migrated_session,
        "SCOPE-SIGUNGU-OUT",
        bjd_code="1111010100",
        sigungu_code="11110",
    )
    seen: list[dict[str, float]] = []

    async def resolver(*, lon: float, lat: float, radius_km: float) -> tuple[str, ...]:
        seen.append({"lon": lon, "lat": lat, "radius_km": radius_km})
        return ("11140", "99999", "11140")

    result = await scope_repo.resolve_sigungu_by_radius(
        migrated_session,
        lon=126.978,
        lat=37.5665,
        radius_km=3.0,
        sigungu_resolver=resolver,
    )

    assert seen == [{"lon": 126.978, "lat": 37.5665, "radius_km": 3.0}]
    assert result.feature_ids == (included.feature.feature_id,)
    assert result.sigungu_codes == ("11140",)


async def test_count_features_matching_scope_dispatches(
    migrated_session: AsyncSession,
) -> None:
    bundle = await _load(migrated_session, "SCOPE-DISPATCH", sigungu_code="11560")

    result = await scope_repo.count_features_matching_scope(
        migrated_session,
        {"type": "feature_ids", "feature_ids": [bundle.feature.feature_id]},
    )
    assert result.feature_count == 1

    with pytest.raises(ValueError, match="unsupported scope type"):
        await scope_repo.count_features_matching_scope(
            migrated_session,
            {"type": "unknown"},
        )


async def test_count_sigungu_scope_requires_resolver(
    migrated_session: AsyncSession,
) -> None:
    with pytest.raises(ValueError, match="requires sigungu_resolver"):
        await scope_repo.count_features_matching_scope(
            migrated_session,
            {
                "type": "sigungu_by_radius",
                "center": {"lon": 126.978, "lat": 37.5665},
                "radius_km": 3.0,
            },
        )


async def test_resolve_cache_target_keys_uses_active_targets(
    migrated_session: AsyncSession,
) -> None:
    near = await _load(
        migrated_session,
        "SCOPE-TARGET-NEAR",
        lon="126.9780",
        lat="37.5665",
        sigungu_code="11140",
    )
    await _load(
        migrated_session,
        "SCOPE-TARGET-FAR",
        lon="129.0756",
        lat="35.1796",
        bjd_code="2611010100",
        sigungu_code="26110",
    )
    target = await upsert_poi_cache_target(
        migrated_session,
        external_system="tripmate",
        target_key="poi-1",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
    )
    await upsert_poi_cache_target(
        migrated_session,
        external_system="tripmate",
        target_key="poi-disabled",
        lon=126.9780,
        lat=37.5665,
        radius_km=1.0,
        update_enabled=False,
    )

    result = await scope_repo.resolve_cache_target_keys(
        migrated_session,
        external_system="tripmate",
        target_keys=["poi-1", "missing", "poi-disabled"],
    )

    assert result.feature_ids == (near.feature.feature_id,)
    assert result.cache_targets[0].target_id == target.target_id
    assert result.cache_target_matches[0].target_id == target.target_id
    assert result.cache_target_matches[0].relation == "within_radius"
    assert result.matched_scope()["target_count"] == 3
    assert result.matched_scope()["active_target_count"] == 1
    assert result.matched_scope()["skipped_missing_keys"] == ["missing"]
    assert result.matched_scope()["skipped_disabled_keys"] == ["poi-disabled"]

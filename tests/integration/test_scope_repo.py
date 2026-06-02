"""``infra.scope_repo`` feature update request scope resolver 통합 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from krtour.map.infra import feature_repo, scope_repo
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 3, 12, 0, tzinfo=_KST)


@dataclass(frozen=True)
class _Festival:
    management_no: str
    festival_name: str
    venue_name: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    road_address: str | None
    jibun_address: str | None
    organizer_name: str | None
    organizer_tel: str | None
    data_reference_date: date | None
    provider_org_name: str | None
    bjd_code: str | None = None
    sigungu_code: str | None = None
    sido_code: str | None = None
    admin_address: str | None = None


async def _bundle(
    management_no: str,
    *,
    lon: str = "126.9239",
    lat: str = "37.5263",
    bjd_code: str = "1156011000",
    sigungu_code: str = "11560",
):
    item = _Festival(
        management_no=management_no,
        festival_name=f"스코프 테스트 축제 {management_no}",
        venue_name="테스트 공원",
        start_date=date(2026, 4, 5),
        end_date=date(2026, 4, 12),
        description="scope resolver 테스트용 fixture.",
        latitude=Decimal(lat),
        longitude=Decimal(lon),
        road_address="서울특별시 영등포구 여의공원로 120",
        jibun_address="서울특별시 영등포구 여의도동 8",
        organizer_name="영등포구청",
        organizer_tel="02-2670-3114",
        data_reference_date=date(2026, 3, 1),
        provider_org_name="서울특별시 영등포구",
        bjd_code=bjd_code,
        sigungu_code=sigungu_code,
        sido_code=bjd_code[:2],
    )
    return (
        await cultural_festivals_to_bundles(
            [item],  # type: ignore[list-item]
            fetched_at=_FETCHED,
        )
    )[0]


async def _load(
    session: AsyncSession,
    management_no: str,
    **kwargs: str,
):
    sigungu_code = kwargs.get("sigungu_code", "11560")
    bjd_code = kwargs.get("bjd_code", "1156011000")
    bundle = await _bundle(management_no, **kwargs)
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
            {"type": "cache_target_keys"},
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

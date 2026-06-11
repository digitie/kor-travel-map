"""MCST place Feature 적재 Dagster asset 2종 (T-220b).

KCISA 14 dataset은 공통 ``CultureRecord`` 스키마라 record resource 1개
(``mcst_culture_records``)가 ``(slug, record)`` 튜플 스트림을 주고, asset이
slug별로 분리 ``_load``한다 — dataset_key(``mcst_<slug>``) 단위 import job/
sync state가 유지된다(계획 정본
`docs/reports/kma-mcst-provider-plan-2026-06-11.md` §3.3). ODCloud 도서관
2 dataset(``mcst_library_records``)도 같은 모양이다.

slug별 ``DagsterFeatureLoadResult``는 dataset이 달라 ``merge``할 수 없으므로
``McstLoadResult``가 dataset별 결과를 담고 합산 metadata를 낸다.
"""

# NOTE: `from __future__ import annotations` 금지 — dagster가 asset 함수의
# ``context`` 어노테이션을 런타임 타입으로 검증한다(assets.py와 동일).
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from dagster import AssetExecutionContext, asset
from krtour.map.providers.mcst import (
    MCST_CULTURE_DATASETS,
    MCST_LIBRARY_DATASETS,
    MCST_PROVIDER_NAME,
    McstDatasetSpec,
    culture_records_to_bundles,
    library_records_to_bundles,
)

from .assets import (
    _COMMON_RESOURCE_KEYS,
    FEATURE_LOAD_RETRY_POLICY,
    _fetched_at,
    _load,
    _record_list,
    _reverse_geocoder,
)
from .etl import DagsterFeatureLoadResult, _add_output_metadata

__all__ = [
    "MCST_FEATURE_ASSETS",
    "McstLoadResult",
    "feature_place_mcst_culture",
    "feature_place_mcst_libraries",
    "group_records_by_slug",
    "run_feature_place_mcst_culture",
    "run_feature_place_mcst_libraries",
]


@dataclass(frozen=True)
class McstLoadResult:
    """slug(dataset)별 적재 결과 합산 (dataset이 달라 merge 불가 — 별도 보관)."""

    provider: str
    results: tuple[DagsterFeatureLoadResult, ...]

    @property
    def bundles_total(self) -> int:
        return sum(result.load.bundles_total for result in self.results)

    def as_metadata(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "datasets_loaded": len(self.results),
            "bundles_total": self.bundles_total,
            "features_inserted": sum(
                result.load.features_inserted for result in self.results
            ),
            "features_updated": sum(
                result.load.features_updated for result in self.results
            ),
            "bundles_by_dataset": {
                result.dataset_key: result.load.bundles_total
                for result in self.results
            },
        }


def group_records_by_slug(
    records: Sequence[Any],
) -> dict[str, list[Any]]:
    """``(slug, record)`` 튜플 스트림 → slug별 record 목록 (입력 순서 유지)."""
    grouped: dict[str, list[Any]] = {}
    for entry in records:
        slug, record = entry
        grouped.setdefault(str(slug), []).append(record)
    return grouped


async def _load_grouped(
    context: AssetExecutionContext,
    *,
    resource_key: str,
    specs: dict[str, McstDatasetSpec],
    use_library_transform: bool,
) -> McstLoadResult:
    records = await _record_list(context, resource_key)
    grouped = group_records_by_slug(records)
    unknown = sorted(set(grouped) - set(specs))
    if unknown:
        raise KeyError(f"MCST 메타표에 없는 slug: {unknown!r} (resource {resource_key})")

    fetched_at = await _fetched_at(context)
    geocoder = _reverse_geocoder(context)
    results: list[DagsterFeatureLoadResult] = []
    for slug, spec in specs.items():
        slug_records = grouped.get(slug)
        if not slug_records:
            context.log.info("MCST %s record 없음 — skip.", spec.dataset_key)
            continue
        if use_library_transform:
            bundles = await library_records_to_bundles(
                slug_records,
                slug=slug,
                fetched_at=fetched_at,
                reverse_geocoder=geocoder,
            )
        else:
            bundles = await culture_records_to_bundles(
                slug_records,
                slug=slug,
                fetched_at=fetched_at,
                reverse_geocoder=geocoder,
            )
        skipped = len(slug_records) - len(bundles)
        if skipped:
            context.log.warning(
                "MCST %s record %d건이 이름/위치 단서 부재로 제외됨(전체 %d건).",
                spec.dataset_key,
                skipped,
                len(slug_records),
            )
        results.append(
            await _load(
                context,
                provider=MCST_PROVIDER_NAME,
                dataset_key=spec.dataset_key,
                bundles=bundles,
            )
        )
    result = McstLoadResult(provider=MCST_PROVIDER_NAME, results=tuple(results))
    _add_output_metadata(context, result.as_metadata())
    return result


async def run_feature_place_mcst_culture(
    context: AssetExecutionContext,
) -> McstLoadResult:
    """MCST KCISA 14 dataset record를 slug별 place Feature로 적재한다."""
    return await _load_grouped(
        context,
        resource_key="mcst_culture_records",
        specs=MCST_CULTURE_DATASETS,
        use_library_transform=False,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"mcst_culture_records"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_mcst_culture(
    context: AssetExecutionContext,
) -> McstLoadResult:
    return await run_feature_place_mcst_culture(context)


async def run_feature_place_mcst_libraries(
    context: AssetExecutionContext,
) -> McstLoadResult:
    """MCST ODCloud 도서관 2 dataset row를 slug별 place Feature로 적재한다."""
    return await _load_grouped(
        context,
        resource_key="mcst_library_records",
        specs=MCST_LIBRARY_DATASETS,
        use_library_transform=True,
    )


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"mcst_library_records"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_mcst_libraries(
    context: AssetExecutionContext,
) -> McstLoadResult:
    return await run_feature_place_mcst_libraries(context)


MCST_FEATURE_ASSETS: Final = [
    feature_place_mcst_culture,
    feature_place_mcst_libraries,
]
"""MCST place 적재 asset 목록 (T-220b)."""

"""MCST place Feature 적재 Dagster asset (T-220 재배선, #395).

파일데이터 CSV 등록 dataset은 record resource 1개(``mcst_culture_records``,
keyless ``FileDataClient``)가 ``(slug, row)`` 튜플 스트림을 주고, asset이
slug별로 분리 ``_load``한다 — dataset_key(``mcst_<slug>``) 단위 import job/
sync state가 유지된다. 구 ODCloud 도서관 asset(``feature_place_mcst_
libraries``)은 provider 재편으로 dataset이 소멸해 제거됐다(제외 사유는
``kortravelmap.providers.mcst.MCST_EXCLUDED_FILE_DATASETS``).

slug별 ``DagsterFeatureLoadResult``는 dataset이 달라 ``merge``할 수 없으므로
``McstLoadResult``가 dataset별 결과를 담고 합산 metadata를 낸다.
"""

# NOTE: `from __future__ import annotations` 금지 — dagster가 asset 함수의
# ``context`` 어노테이션을 런타임 타입으로 검증한다(assets.py와 동일).
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from kortravelmap.core.feature_operation import ProviderDatasetOperationKey
from kortravelmap.providers.mcst import (
    MCST_FILE_DATASETS,
    MCST_PROVIDER_NAME,
    file_rows_to_bundles,
)

from dagster import AssetExecutionContext, asset

from .assets import (
    _COMMON_RESOURCE_KEYS,
    FEATURE_LOAD_RETRY_POLICY,
    _fetched_at,
    _load,
    _record_list,
    _reverse_geocoder,
)
from .etl import DagsterFeatureLoadResult, _add_output_metadata
from .feature_operation_tracking import (
    append_failed_multi_pair_attempt,
    ensure_tracked_multi_pair_asset,
    finish_tracked_feature_pair,
)

__all__ = [
    "MCST_FEATURE_ASSETS",
    "McstLoadResult",
    "feature_place_mcst_culture",
    "group_records_by_slug",
    "run_feature_place_mcst_culture",
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
    """``(slug, row)`` 튜플 스트림 → slug별 row 목록 (입력 순서 유지)."""
    grouped: dict[str, list[Any]] = {}
    for entry in records:
        slug, record = entry
        grouped.setdefault(str(slug), []).append(record)
    return grouped


async def run_feature_place_mcst_culture(
    context: AssetExecutionContext,
    on_pair_done: Callable[[str, str], Awaitable[None]] | None = None,
) -> McstLoadResult:
    """MCST 파일데이터 등록 dataset CSV row를 slug별 place Feature로 적재한다."""
    records = await _record_list(context, "mcst_culture_records")
    grouped = group_records_by_slug(records)
    unknown = sorted(set(grouped) - set(MCST_FILE_DATASETS))
    if unknown:
        raise KeyError(
            f"MCST 메타표에 없는 slug: {unknown!r} (resource mcst_culture_records)"
        )

    fetched_at = await _fetched_at(context)
    geocoder = _reverse_geocoder(context)
    results: list[DagsterFeatureLoadResult] = []
    for slug, spec in MCST_FILE_DATASETS.items():
        slug_rows = grouped.get(slug)
        if not slug_rows:
            context.log.info("MCST %s row 없음 — skip.", spec.dataset_key)
            if on_pair_done is not None:
                await on_pair_done(MCST_PROVIDER_NAME, spec.dataset_key)
            continue
        bundles = await file_rows_to_bundles(
            slug_rows,
            slug=slug,
            fetched_at=fetched_at,
            reverse_geocoder=geocoder,
        )
        skipped = len(slug_rows) - len(bundles)
        if skipped:
            context.log.warning(
                "MCST %s row %d건이 이름/위치 단서 부재로 제외됨(전체 %d건).",
                spec.dataset_key,
                skipped,
                len(slug_rows),
            )
        loaded = await _load(
            context,
            provider=MCST_PROVIDER_NAME,
            dataset_key=spec.dataset_key,
            bundles=bundles,
        )
        if on_pair_done is not None:
            await on_pair_done(MCST_PROVIDER_NAME, spec.dataset_key)
        results.append(loaded)
    result = McstLoadResult(provider=MCST_PROVIDER_NAME, results=tuple(results))
    _add_output_metadata(context, result.as_metadata())
    return result


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"mcst_culture_records"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
)
async def feature_place_mcst_culture(
    context: AssetExecutionContext,
) -> McstLoadResult:
    completed: set[ProviderDatasetOperationKey] = set()

    async def _on_pair_done(provider: str, dataset_key: str) -> None:
        pair = ProviderDatasetOperationKey(provider, dataset_key)
        if guard is not None:
            await finish_tracked_feature_pair(guard, pair)
        completed.add(pair)

    pair_order = tuple(
        ProviderDatasetOperationKey(MCST_PROVIDER_NAME, spec.dataset_key)
        for spec in MCST_FILE_DATASETS.values()
    )
    guard = await ensure_tracked_multi_pair_asset(context)
    try:
        return await run_feature_place_mcst_culture(
            context,
            on_pair_done=_on_pair_done if guard is not None else None,
        )
    except Exception as exc:
        failed_pair = next((pair for pair in pair_order if pair not in completed), None)
        if guard is not None and failed_pair is not None:
            await append_failed_multi_pair_attempt(context, guard, failed_pair, exc)
        raise


MCST_FEATURE_ASSETS: Final = [
    feature_place_mcst_culture,
]
"""MCST place 적재 asset 목록 (T-220 재배선, #395)."""

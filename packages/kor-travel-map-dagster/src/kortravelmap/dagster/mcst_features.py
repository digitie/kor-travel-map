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

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.providers.mcst import (
    MCST_FILE_DATASETS,
    MCST_PROVIDER_NAME,
    McstSlugFailure,
    file_rows_to_bundles,
)

from dagster import AssetExecutionContext, Failure, asset

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
    _log_spend_on_failure,
    append_failed_multi_member_attempt,
    ensure_tracked_multi_member_asset,
    finish_tracked_feature_membership,
)
from .quota_exhaustion import raise_terminal_if_quota_exhausted
from .upstream_requests import counting_upstream_requests

__all__ = [
    "MCST_FEATURE_ASSETS",
    "McstLoadResult",
    "feature_place_mcst_culture",
    "group_records_by_slug",
    "split_slug_failures",
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
            "features_inserted": sum(result.load.features_inserted for result in self.results),
            "features_updated": sum(result.load.features_updated for result in self.results),
            "bundles_by_dataset": {
                result.dataset_key: result.load.bundles_total for result in self.results
            },
        }


def split_slug_failures(
    records: Sequence[Any],
) -> tuple[list[Any], dict[str, str]]:
    """스트림을 ``(정상 튜플, {실패 slug: 사유})``로 가른다.

    fetcher가 slug 하나의 수집 실패를 예외 대신
    :class:`~kortravelmap.providers.mcst.McstSlugFailure`로 흘린다 — 예외로
    올리면 이 stream을 리스트로 걷는 쪽이 그대로 통과시켜 **13개 dataset이
    전부 0건**이 되기 때문이다(2026-09-18 prod 실측).

    같은 slug가 두 번 실패할 일은 없지만, 그렇더라도 **첫 사유를 남긴다** —
    나중 것으로 덮으면 원인 추적이 한 단계 멀어진다.
    """

    rows: list[Any] = []
    failures: dict[str, str] = {}
    for entry in records:
        if isinstance(entry, McstSlugFailure):
            failures.setdefault(entry.slug, entry.reason)
            continue
        rows.append(entry)
    return rows, failures


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
    *,
    memberships: tuple[ProviderDatasetOperationMembership, ...] = (),
    on_memberships_completed: (
        Callable[[tuple[ProviderDatasetOperationMembership, ...]], Awaitable[None]] | None
    ) = None,
) -> McstLoadResult:
    """MCST 파일데이터 등록 dataset CSV row를 slug별 place Feature로 적재한다.

    multi-member operation의 completion은 slug/provider label을 identity로 다시
    해석하지 않는다. 모든 load가 성공한 뒤 caller가 전달한 exact membership
    snapshot 전체를 한 번에 완료 처리한다.
    """
    records = await _record_list(context, "mcst_culture_records")
    records, slug_failures = split_slug_failures(records)
    grouped = group_records_by_slug(records)
    unknown = sorted(set(grouped) - set(MCST_FILE_DATASETS))
    if unknown:
        raise KeyError(f"MCST 메타표에 없는 slug: {unknown!r} (resource mcst_culture_records)")

    fetched_at = await _fetched_at(context)
    geocoder = _reverse_geocoder(context)
    results: list[DagsterFeatureLoadResult] = []
    for slug, spec in MCST_FILE_DATASETS.items():
        if slug in slug_failures:
            # **적재를 건너뛴다.** 빈 목록으로 `_load`를 부르면
            # `authoritative_snapshot_complete=True`가 그것을 '전량'으로
            # 선언해 이 dataset의 기존 feature가 **전부 은퇴**한다 — 수집이
            # 실패했을 뿐인데 데이터를 지우는 셈이다.
            context.log.error(
                "MCST %s 수집 실패 — 이 dataset은 적재하지 않는다"
                "(빈 스냅샷을 권위로 봉인하지 않는다): %s",
                spec.dataset_key,
                slug_failures[slug],
            )
            continue
        slug_rows = grouped.get(slug, [])
        if not slug_rows:
            context.log.info(
                "MCST %s row 없음 — authoritative empty snapshot으로 seal.",
                spec.dataset_key,
            )
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
            authoritative_snapshot_complete=True,
        )
        results.append(loaded)
    if slug_failures:
        # 성공한 dataset은 이미 적재됐다 — 그것이 이 변경의 요지다.
        # 그래도 run은 **실패로 끝낸다**: 일부가 죽었는데 초록으로 보이면
        # 그것이 다음 사고다.
        #
        # 재시도는 끈다. 여기 오는 실패는 상류 스키마·원천 이동처럼
        # **같은 run 안에서 나아지지 않는** 종류다(쿼터 소진은 fetcher가
        # 위로 올려 별도 경로를 탄다). 재시도하면 성공한 12개를 다시
        # 적재하고 같은 자리에서 또 죽는다.
        loaded_keys = [result.dataset_key for result in results]
        raise Failure(
            description=(
                f"MCST slug {len(slug_failures)}건의 수집이 실패했다 — "
                f"나머지 {len(loaded_keys)}건은 적재했다. "
                f"실패: {slug_failures}"
            ),
            metadata={
                "failed_slugs": ", ".join(sorted(slug_failures)),
                "loaded_datasets": ", ".join(loaded_keys),
                "step_retries_suppressed": "true",
            },
            allow_retries=False,
        )
    result = McstLoadResult(provider=MCST_PROVIDER_NAME, results=tuple(results))
    if on_memberships_completed is not None and memberships:
        await on_memberships_completed(memberships)
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
    """MCST multi-member asset — 쿼터 판정과 분자 계수기를 둘 다 연다."""

    with counting_upstream_requests():
        guard = await ensure_tracked_multi_member_asset(context)
        memberships = guard.memberships if guard is not None else ()
        completed_memberships: tuple[ProviderDatasetOperationMembership, ...] = ()

        async def _on_memberships_completed(
            received_memberships: tuple[ProviderDatasetOperationMembership, ...],
        ) -> None:
            nonlocal completed_memberships
            if guard is not None and received_memberships != memberships:
                raise RuntimeError("MCST completed membership snapshot이 guard와 다름")
            completed_memberships = received_memberships

        try:
            result = await run_feature_place_mcst_culture(
                context,
                memberships=memberships,
                on_memberships_completed=_on_memberships_completed if guard is not None else None,
            )
            if guard is not None and completed_memberships != memberships:
                raise RuntimeError("MCST raw runner가 exact membership completion을 emit하지 않음")
        except Exception as exc:
            if guard is not None:
                for membership in memberships:
                    await append_failed_multi_member_attempt(context, guard, membership, exc)
            # 이 asset만 multi-member라 `run_tracked_feature_asset`를 지나지 않는다.
            # 같은 판정을 여기서 직접 건다(:mod:`~.quota_exhaustion`). 실패한 step은
            # output을 내지 않으므로 소비량 로그도 같은 이유로 여기서 남긴다.
            _log_spend_on_failure(context)
            raise_terminal_if_quota_exhausted(exc)
            raise
        if guard is not None:
            assert guard.operation_key is not None
            if len(result.results) != len(completed_memberships):
                raise RuntimeError("MCST authoritative member와 load seal 수가 다름")
            for loaded in result.results:
                membership = await guard.client.resolve_feature_operation_dataset_membership(
                    operation_key=guard.operation_key,
                    provider=MCST_PROVIDER_NAME,
                    dataset_key=loaded.dataset_key,
                )
                if membership not in completed_memberships:
                    raise RuntimeError("MCST load seal이 frozen membership 밖을 가리킴")
                await finish_tracked_feature_membership(
                    guard,
                    membership,
                    authoritative_snapshot_complete=True,
                    curation_input_member_count=(
                        loaded.load.curation_input_member_count
                    ),
                    curation_input_set_hash=loaded.load.curation_input_set_hash,
                )
        return result


MCST_FEATURE_ASSETS: Final = [
    feature_place_mcst_culture,
]
"""MCST place 적재 asset 목록 (T-220 재배선, #395)."""

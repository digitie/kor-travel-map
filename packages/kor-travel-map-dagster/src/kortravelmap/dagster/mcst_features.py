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
from kortravelmap.dto.geo_dataset import GeoApplied
from kortravelmap.providers.mcst import (
    MCST_FILE_DATASETS,
    MCST_PROVIDER_NAME,
    McstSlugAttempt,
    McstSlugFailure,
    file_rows_to_bundles,
)
from sqlalchemy.exc import DBAPIError

from dagster import AssetExecutionContext, Failure, asset

from .assets import (
    _COMMON_RESOURCE_KEYS,
    FEATURE_LOAD_RETRY_POLICY,
    GEO_HEAVY_POOL,
    _fetched_at,
    _load,
    _record_list,
    _reverse_geocoder,
    _transform_reusing_geo,
)
from .etl import DagsterFeatureLoadResult, _add_output_metadata
from .feature_operation_tracking import (
    FeatureOperationExecutionGuard,
    _log_spend_on_failure,
    ensure_tracked_multi_member_asset,
    finish_tracked_feature_membership,
)
from .quota_exhaustion import quota_exhaustion_cause, raise_terminal_if_quota_exhausted
from .stall_watchdog import stall_watchdog
from .upstream_requests import counting_upstream_requests

__all__ = [
    "MCST_FEATURE_ASSETS",
    "McstLoadResult",
    "feature_place_mcst_culture",
    "group_records_by_slug",
    "split_slug_markers",
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




def _retryable_load_failure(error: Exception) -> bool:
    """영구 검증 오류는 닫고, DB의 일시 실패와 연결 장애만 재시도한다."""
    if isinstance(error, TimeoutError | ConnectionError):
        return True
    if not isinstance(error, DBAPIError):
        return False
    if error.connection_invalidated:
        return True
    original = error.orig
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    return sqlstate in {"40001", "40P01", "55P03", "53300", "57P01", "57P02", "57P03"} or (
        isinstance(sqlstate, str) and sqlstate.startswith("08")
    )


class McstImportFailure(Failure):
    """성공 dataset을 보존하며 실패한 dataset의 안전한 원인만 전달한다."""

    def __init__(
        self,
        *,
        failures: dict[str, dict[str, object]],
        loaded_dataset_keys: tuple[str, ...],
    ) -> None:
        self.failures = failures
        retryable = all(item["retryable"] is True for item in failures.values())
        super().__init__(
            description=(
                f"MCST dataset {len(failures)}건 실패, "
                f"{len(loaded_dataset_keys)}건 적재 완료"
            ),
            metadata={
                "failed_slugs": ", ".join(
                    slug for slug, spec in MCST_FILE_DATASETS.items()
                    if spec.dataset_key in failures
                ),
                "loaded_datasets": ", ".join(loaded_dataset_keys),
                "step_retries_suppressed": "false" if retryable else "true",
                "retryable_failures": ", ".join(
                    slug for slug, spec in MCST_FILE_DATASETS.items()
                    if failures.get(spec.dataset_key, {}).get("retryable") is True
                ),
            },
            allow_retries=retryable,
        )


def split_slug_markers(
    records: Sequence[Any],
) -> tuple[list[Any], set[str], dict[str, McstSlugFailure]]:
    """스트림을 ``(정상 튜플, 시도한 slug, {실패 slug: 표식})``로 가른다.

    fetcher가 slug 하나의 수집 실패를 예외 대신
    :class:`~kortravelmap.providers.mcst.McstSlugFailure`로 흘린다 — 예외로
    올리면 이 stream을 리스트로 걷는 쪽이 그대로 통과시켜 **13개 dataset이
    전부 0건**이 되기 때문이다(2026-09-18 prod 실측).

    같은 slug가 두 번 실패할 일은 없지만, 그렇더라도 **첫 사유를 남긴다** —
    나중 것으로 덮으면 원인 추적이 한 단계 멀어진다.
    """

    rows: list[Any] = []
    attempted: set[str] = set()
    failures: dict[str, McstSlugFailure] = {}
    for entry in records:
        if isinstance(entry, McstSlugAttempt):
            attempted.add(entry.slug)
            continue
        if isinstance(entry, McstSlugFailure):
            attempted.add(entry.slug)
            failures.setdefault(entry.slug, entry)
            continue
        rows.append(entry)
    return rows, attempted, failures


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
    selected_dataset_keys: frozenset[str] | None = None,
    completed_dataset_keys: frozenset[str] = frozenset(),
    on_dataset_completed: Callable[[DagsterFeatureLoadResult], Awaitable[None]] | None = None,
) -> McstLoadResult:
    """각 적재의 인과 seal을 즉시 완료하고 이미 완료한 dataset은 다시 적재하지 않는다."""
    records = await _record_list(context, "mcst_culture_records")
    records, attempted_slugs, slug_failures = split_slug_markers(records)
    if not attempted_slugs and not completed_dataset_keys:
        # **시도 표식이 하나도 없는 stream은 무작업 성공이 된다.** 아래 loop가
        # 13개를 전부 `continue`하므로 `results`도 `slug_failures`도 비고, run은
        # 0건 적재로 초록이 된다 — 이 asset이 막으려던 "조용한 0건"의 새 입구다
        # (적대 리뷰 지적). fetcher는 slug마다 표식을 먼저 흘리므로, 표식이
        # 없다는 것은 fetcher가 한 slug도 시작하지 못했다는 뜻이다.
        raise Failure(
            description=(
                "MCST stream에 시도 표식이 하나도 없다 — fetcher가 어떤 slug도 "
                "시작하지 못했다. 0건 적재를 성공으로 보지 않는다."
            ),
            allow_retries=False,
        )
    grouped = group_records_by_slug(records)
    unknown = sorted(set(grouped) - set(MCST_FILE_DATASETS))
    if unknown:
        raise KeyError(f"MCST 메타표에 없는 slug: {unknown!r} (resource mcst_culture_records)")

    fetched_at = await _fetched_at(context)
    geocoder = _reverse_geocoder(context)
    results: list[DagsterFeatureLoadResult] = []
    failures: dict[str, dict[str, object]] = {}
    for slug, spec in MCST_FILE_DATASETS.items():
        if selected_dataset_keys is not None and spec.dataset_key not in selected_dataset_keys:
            continue
        if spec.dataset_key in completed_dataset_keys:
            continue
        if slug not in attempted_slugs:
            # 이 run이 **시도하지 않은** dataset이다. feature-update worker는
            # fetcher를 slug 하나로 좁혀 부르므로(`_mcst_resources`), 종전처럼
            # 13개를 다 돌면 나머지 12개가 시도한 적도 없이 빈 적재와
            # sync-success를 받아 **수집하지 않은 dataset이 신선한 것으로**
            # 보이게 된다.
            continue
        if slug in slug_failures:
            failure = slug_failures[slug]
            failures[spec.dataset_key] = {
                "code": "MCST_DATASET_FETCH_FAILED",
                "phase": "fetch",
                "reason": failure.reason,
                "retryable": failure.retryable,
            }
            # **적재를 건너뛴다.** 이 provider는 `retire_absent_from_snapshot`을
            # 넘기지 않으므로 빈 목록이 기존 feature를 지우지는 않는다.
            # 대신 빈 목록을 적재하면 그 dataset의 **sync cursor가 전진해
            # 수집 실패가 신선한 성공으로 보이고**, curation seal이 관측한 적
            # 없는 집합을 권위로 봉인한다.
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
        try:
            bundles = await _transform_reusing_geo(
                context,
                file_rows_to_bundles,
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
                geo_applied=GeoApplied(reverse=True, geocode=False),
            )
        except Exception as exc:
            if quota_exhaustion_cause(exc) is not None:
                raise
            failures[spec.dataset_key] = {
                "code": "MCST_DATASET_LOAD_FAILED",
                "phase": "load",
                "reason": type(exc).__name__,
                "retryable": _retryable_load_failure(exc),
            }
            continue
        if on_dataset_completed is not None:
            await on_dataset_completed(loaded)
        results.append(loaded)
    if failures:
        raise McstImportFailure(
            failures=failures,
            loaded_dataset_keys=tuple(result.dataset_key for result in results),
        )
    result = McstLoadResult(provider=MCST_PROVIDER_NAME, results=tuple(results))
    _add_output_metadata(context, result.as_metadata())
    return result



async def _finalize_mcst_dataset(
    guard: FeatureOperationExecutionGuard,
    member: ProviderDatasetOperationMembership,
    loaded: DagsterFeatureLoadResult,
    *,
    completed_dataset_keys: tuple[str, ...],
) -> None:
    """완료 command의 오류를 해당 dataset에 묶고 원 예외 연쇄는 보존한다."""
    try:
        await finish_tracked_feature_membership(
            guard, member,
            authoritative_snapshot_complete=True,
            curation_input_member_count=loaded.load.curation_input_member_count,
            curation_input_set_hash=loaded.load.curation_input_set_hash,
        )
    except Exception as exc:
        raise McstImportFailure(
            failures={loaded.dataset_key: {
                "code": "MCST_DATASET_FINALIZE_FAILED",
                "phase": "finalize",
                "reason": type(exc).__name__,
                "retryable": _retryable_load_failure(exc),
            }},
            loaded_dataset_keys=completed_dataset_keys,
        ) from exc


@asset(
    group_name="features_place",
    required_resource_keys=_COMMON_RESOURCE_KEYS | {"mcst_culture_records"},
    retry_policy=FEATURE_LOAD_RETRY_POLICY,
    pool=GEO_HEAVY_POOL,
)
async def feature_place_mcst_culture(
    context: AssetExecutionContext,
) -> McstLoadResult:
    """MCST multi-member asset — 쿼터 판정과 분자 계수기를 둘 다 연다."""

    # I/O 없이 멈춘 step을 진단한다 — 2026-10-23 이 asset이 3.5시간 무이벤트로 멈췄다.
    async with stall_watchdog(getattr(context, "log", None)):
        with counting_upstream_requests():
            guard = await ensure_tracked_multi_member_asset(context)
            memberships = guard.memberships if guard is not None else ()
            completed_memberships: set[ProviderDatasetOperationMembership] = set()
            dataset_memberships: dict[str, ProviderDatasetOperationMembership] = {}
            if guard is not None:
                # ensure는 잠금 아래 현재 run 장부를 읽는다. 재시도의 완료 member는
                # 재적재하지 않아 최초 causal seal과 실제 데이터가 어긋나지 않는다.
                snapshot = await guard.ensure()
                assert snapshot is not None
                completed_memberships.update(
                    member.membership
                    for member in snapshot.operation.members
                    if member.status == "done"
                )
                dataset_memberships = await guard.client.resolve_frozen_feature_operation_datasets(
                    memberships=memberships, provider=MCST_PROVIDER_NAME,
                )
                if set(dataset_memberships.values()) != set(memberships):
                    raise RuntimeError("MCST frozen membership과 dataset 집합이 다름")
                if set(dataset_memberships) - {
                    spec.dataset_key for spec in MCST_FILE_DATASETS.values()
                }:
                    raise RuntimeError("MCST frozen membership에 미등록 dataset이 있음")

            async def _on_dataset_completed(loaded: DagsterFeatureLoadResult) -> None:
                assert guard is not None
                member = dataset_memberships.get(loaded.dataset_key)
                if member is None:
                    raise RuntimeError("MCST load seal이 frozen membership 밖을 가리킴")
                if member in completed_memberships:
                    raise RuntimeError("MCST 완료 member가 다시 적재됨")
                await _finalize_mcst_dataset(
                    guard, member, loaded,
                    completed_dataset_keys=tuple(
                        key for key, value in dataset_memberships.items()
                        if value in completed_memberships
                    ),
                )
                completed_memberships.add(member)

            try:
                result = await run_feature_place_mcst_culture(
                    context,
                    selected_dataset_keys=frozenset(dataset_memberships) if guard else None,
                    completed_dataset_keys=frozenset(
                        key for key, member in dataset_memberships.items()
                        if member in completed_memberships
                    ),
                    on_dataset_completed=_on_dataset_completed if guard is not None else None,
                )
                if guard is not None and completed_memberships != set(memberships):
                    raise RuntimeError("MCST raw runner가 모든 exact member를 완료하지 않음")
            except Exception as exc:
                if guard is not None:
                    failures = exc.failures if isinstance(exc, McstImportFailure) else {}
                    for key, member in dataset_memberships.items():
                        if member in completed_memberships:
                            continue
                        error = failures.get(key, {
                            "code": "MCST_DATASET_RUN_ABORTED",
                            "phase": "run",
                            "reason": type(exc).__name__,
                            "retryable": False,
                        })
                        await guard.client.append_dagster_feature_attempt_event(
                            dagster_run_id=guard.dagster_run_id,
                            membership=member,
                            attempt_number=int(context.retry_number) + 1,
                            outcome="retryable_failure" if error["retryable"] else "failed",
                            error=error,
                        )
                _log_spend_on_failure(context)
                raise_terminal_if_quota_exhausted(exc)
                raise
            return result


MCST_FEATURE_ASSETS: Final = [
    feature_place_mcst_culture,
]
"""MCST place 적재 asset 목록 (T-220 재배선, #395)."""

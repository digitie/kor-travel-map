"""Dagster asset에서 재사용하는 FeatureBundle 검증 + DB 적재 helper."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from dagster import Failure
from kortravelmap.dagster.validation import (
    FeatureAddressValidationSummary,
    validate_feature_bundles_address,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from kortravelmap.client import AsyncKorTravelMapClient
    from kortravelmap.dto import FeatureBundle
    from kortravelmap.infra.feature_repo import FeatureLoadResult

    from dagster import AssetExecutionContext


FEATURE_LOAD_CHUNK_SIZE: Final[int] = 1000
"""Dagster asset이 FeatureBundle을 DB에 적재할 때 사용하는 기본 chunk 크기."""


@dataclass(frozen=True)
class DagsterFeatureLoadResult:
    """Dagster provider load asset 결과."""

    provider: str
    dataset_key: str
    feature_ids: tuple[str, ...]
    load: FeatureLoadResult
    address_validation: FeatureAddressValidationSummary

    def as_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "provider": self.provider,
            "dataset_key": self.dataset_key,
            "feature_ids": list(self.feature_ids),
            "bundles_total": self.load.bundles_total,
            "features_inserted": self.load.features_inserted,
            "features_updated": self.load.features_updated,
            "source_records_inserted": self.load.source_records_inserted,
            "source_links_inserted": self.load.source_links_inserted,
            "source_links_updated": self.load.source_links_updated,
        }
        metadata.update(self.address_validation.as_metadata())
        return metadata

    def merge(
        self, other: DagsterFeatureLoadResult
    ) -> DagsterFeatureLoadResult:
        """같은 provider/dataset의 chunk 적재 결과를 합산한다."""
        if self.provider != other.provider or self.dataset_key != other.dataset_key:
            raise ValueError("서로 다른 provider/dataset 적재 결과는 병합할 수 없음")
        return DagsterFeatureLoadResult(
            provider=self.provider,
            dataset_key=self.dataset_key,
            feature_ids=self.feature_ids + other.feature_ids,
            load=self.load.merge(other.load),
            address_validation=_merge_validation_summaries(
                self.address_validation, other.address_validation
            ),
        )


def _normalize_address_validation_mode(value: bool | str) -> str:
    """``strict_address`` resource 값 → 검증 모드 문자열 (#376).

    bool은 하위호환 — ``True``는 ``strict``, ``False``는 ``off``.
    """
    if value is True:
        return "strict"
    if value is False:
        return "off"
    mode = str(value)
    if mode not in {"strict", "drop", "off"}:
        raise ValueError(f"unknown address validation mode: {mode!r}")
    return mode


async def load_feature_bundles_for_dagster(
    *,
    context: AssetExecutionContext,
    client: AsyncKorTravelMapClient,
    bundles: Sequence[FeatureBundle],
    provider: str,
    dataset_key: str,
    strict_address: bool | str = True,
    chunk_size: int = FEATURE_LOAD_CHUNK_SIZE,
    load_all: Callable[[Sequence[FeatureBundle]], Awaitable[FeatureLoadResult]]
    | None = None,
) -> DagsterFeatureLoadResult:
    """주소/좌표 검증 후 ``AsyncKorTravelMapClient``로 PostGIS에 적재한다.

    ``strict_address``(모드 ``strict``/``drop``/``off``, bool 하위호환)는
    error-severity 검증 이슈 처리 정책을 정한다 — ``strict``는 run 실패,
    ``drop``은 해당 row만 제외 + 메타데이터 기록, ``off``는 전부 적재 (#376).
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    mode = _normalize_address_validation_mode(strict_address)
    validation = validate_feature_bundles_address(bundles)
    # T-VN-H28B: severity가 아니라 code allowlist(DROPPABLE_ISSUE_CODES)가 손실을 정한다.
    # 새 검증이 error를 내도 allowlist를 명시적으로 고치기 전에는 drop/실패가 불가능하다.
    if mode == "strict" and validation.has_blocking_errors:
        _add_output_metadata(context, validation.as_metadata())
        codes = ", ".join(issue.code for issue in validation.blocking_issues)
        raise Failure(
            description=f"Feature 주소/좌표 검증 실패: {codes}",
            metadata=validation.as_metadata(),
        )

    dropped_feature_ids: tuple[str, ...] = ()
    if mode == "drop" and validation.has_blocking_errors:
        error_feature_ids = {
            issue.feature_id for issue in validation.blocking_issues
        }
        dropped = [
            bundle
            for bundle in bundles
            if bundle.feature.feature_id in error_feature_ids
        ]
        bundles = [
            bundle
            for bundle in bundles
            if bundle.feature.feature_id not in error_feature_ids
        ]
        dropped_feature_ids = tuple(b.feature.feature_id for b in dropped)

    if load_all is not None:
        load = await load_all(bundles)
    else:
        load = None
        for start in range(0, len(bundles), chunk_size):
            chunk = bundles[start : start + chunk_size]
            chunk_load = await client.load_feature_bundles(chunk)
            load = chunk_load if load is None else load.merge(chunk_load)
        if load is None:
            load = await client.load_feature_bundles(bundles)
    assert load is not None

    result = DagsterFeatureLoadResult(
        provider=provider,
        dataset_key=dataset_key,
        feature_ids=tuple(bundle.feature.feature_id for bundle in bundles),
        load=load,
        address_validation=validation,
    )
    metadata = result.as_metadata()
    if dropped_feature_ids:
        # silent cap 금지 — drop 모드에서 격리한 row를 메타데이터로 노출한다.
        metadata["address_validation_dropped_count"] = len(dropped_feature_ids)
        metadata["address_validation_dropped_feature_ids"] = list(dropped_feature_ids)
    _add_output_metadata(context, metadata)
    return result


def _merge_validation_summaries(
    left: FeatureAddressValidationSummary,
    right: FeatureAddressValidationSummary,
) -> FeatureAddressValidationSummary:
    merged_grades = Counter(left.evidence_grade_counts)
    merged_grades.update(right.evidence_grade_counts)
    return FeatureAddressValidationSummary(
        total=left.total + right.total,
        issue_count=left.issue_count + right.issue_count,
        error_count=left.error_count + right.error_count,
        warning_count=left.warning_count + right.warning_count,
        # T-VN-H28B: 커버리지를 합치지 않으면 batch가 2개 이상인 run에서 빈 dict가 나가
        # "측정 안 됨"과 "잴 것이 없음"을 구분할 수 없게 된다.
        evidence_grade_counts=dict(merged_grades),
        issues=left.issues + right.issues,
    )


def _add_output_metadata(
    context: AssetExecutionContext, metadata: Mapping[str, object]
) -> None:
    try:
        context.add_output_metadata(metadata)
    except Exception as exc:
        if exc.__class__.__name__ != "DagsterInvalidPropertyError":
            raise

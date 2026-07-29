"""Dagster asset에서 재사용하는 FeatureBundle 검증 + DB 적재 helper."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from kortravelmap.client import AddressValidationFinding

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
    # drop 모드가 bundles를 재할당하기 **전에** 잡는다 — 그러지 않으면 drop된 레코드의
    # source_entity_id를 잃고 dedupe_key가 불안정한 source_record_key로 되돌아간다.
    entity_ids = _entity_ids(bundles)
    # strict는 이름 그대로 모든 error에서 run을 중단한다. 영구 손실을 제한하는
    # DROPPABLE_ISSUE_CODES allowlist는 drop 모드에만 적용한다.
    if mode == "strict" and validation.has_errors:
        # T-VN-H30A: **던지기 전에** 기록한다. strict는 배포 기본값이고, 여기서 죽는 run이
        # 바로 증거가 가장 필요한 run이다. 적재가 없으므로 FK 대상도 없다 — 전부 unlinked로
        # 남기고 id는 payload로만 나른다.
        failed_findings = _address_validation_findings(
            validation,
            provider=provider,
            dataset_key=dataset_key,
            loaded_feature_ids=frozenset(),
            dropped_feature_ids=frozenset(
                issue.feature_id
                for issue in validation.issues
                if issue.severity == "error"
            ),
            entity_ids=entity_ids,
        )
        recorded = await client.record_address_validation_findings(
            failed_findings,
            provider=provider,
            dataset_key=dataset_key,
        )
        failure_metadata = dict(validation.as_metadata())
        failure_metadata["address_validation_findings_recorded"] = recorded
        _add_output_metadata(context, failure_metadata)
        codes = ", ".join(
            issue.code for issue in validation.issues if issue.severity == "error"
        )
        raise Failure(
            description=f"Feature 주소/좌표 검증 실패: {codes}",
            metadata=failure_metadata,
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

    # T-VN-H30A: run metadata는 run이 사라지면 함께 사라진다. 검증 결과를
    # ops.data_integrity_violations에 durable하게 남겨 /admin/issues에서 보이게 한다.
    # **적재 후에** 기록한다 — feature_id/source_record_key가 FK라 적재 전에는 대상이 없다.
    loaded_ids = {bundle.feature.feature_id for bundle in bundles}
    findings = _address_validation_findings(
        validation,
        provider=provider,
        dataset_key=dataset_key,
        loaded_feature_ids=loaded_ids,
        dropped_feature_ids=frozenset(dropped_feature_ids),
        entity_ids=entity_ids,
    )
    recorded = await client.record_address_validation_findings(
        findings,
        provider=provider,
        dataset_key=dataset_key,
    )
    metadata["address_validation_findings_recorded"] = recorded
    if findings and recorded != len(findings):
        # 기록 실패를 조용히 넘기지 않는다 — 관측 경로가 죽은 것도 관측 대상이다.
        metadata["address_validation_findings_unrecorded"] = len(findings) - recorded

    _add_output_metadata(context, metadata)
    return result


def _address_validation_findings(
    validation: FeatureAddressValidationSummary,
    *,
    provider: str,
    dataset_key: str,
    loaded_feature_ids: frozenset[str] | set[str],
    dropped_feature_ids: frozenset[str],
    entity_ids: Mapping[str, str] | None = None,
) -> list[AddressValidationFinding]:
    """검증 issue → durable finding (T-VN-H30A).

    ``dedupe_key``는 (provider, dataset_key, code, **source_entity_id**)로 만든다.

    ``source_record_key``를 쓰면 안 된다 — 그 키는 ``raw_payload_hash``에서 파생되므로
    (``core.ids.make_source_record_key``) provider export에서 무관한 필드 하나만 바뀌어도
    새 key가 되고, 같은 문제가 **매 export마다 새 열린 이슈**로 쌓인다. MOIS 규모(977k)에서는
    큐가 단조 증가한다. ``source_entity_id``는 payload 변경과 무관하게 안정적이다.
    """
    entity_ids = entity_ids or {}
    findings: list[AddressValidationFinding] = []
    for issue in validation.issues:
        linked = issue.feature_id in loaded_feature_ids
        # entity id를 못 찾으면 record key로 물러선다(안정성은 떨어지지만 키를 잃지는 않는다).
        entity_id = entity_ids.get(issue.source_record_key, issue.source_record_key)
        findings.append(
            AddressValidationFinding(
                dedupe_key=(
                    f"address_validation:{provider}:{dataset_key}:"
                    f"{issue.code}:{entity_id}"
                ),
                violation_type=issue.code,
                severity=issue.severity,
                message=issue.message,
                provider=provider,
                dataset_key=dataset_key,
                source_record_key=issue.source_record_key,
                feature_id=issue.feature_id,
                linked=linked,
                payload={
                    "feature_id": issue.feature_id,
                    "source_record_key": issue.source_record_key,
                    "provider_address": issue.provider_address,
                    "bjd_code": issue.bjd_code,
                    "sigungu_code": issue.sigungu_code,
                    "dropped": issue.feature_id in dropped_feature_ids,
                },
            )
        )
    return findings


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


def _entity_ids(bundles: Sequence[FeatureBundle]) -> dict[str, str]:
    """``source_record_key`` → ``source_entity_id`` (dedupe_key 안정화용, T-VN-H30A)."""
    return {
        bundle.source_record.source_record_key: bundle.source_record.source_entity_id
        for bundle in bundles
    }


_ADDRESS_VALIDATION_CODES: Final[frozenset[str]] = frozenset(
    {
        "reverse_geocode_failed",
        "reverse_geocode_unavailable",
        "missing_address",
        "provider_address_region_disagreement",
        "admin_code_stale_sido",
        "admin_code_stale_sigungu",
        "admin_code_stale_emd",
    }
)
"""주소/좌표 검증이 **소유하는** issue code 전체 (T-VN-H30A).

자동 close(sweep)를 붙일 때 그 범위가 될 집합이다. 현재는 sweep을 달지 않았다 —
`T-VN-H32` 참조. 새 검증 code를 추가하면 여기에도 넣는다.
"""

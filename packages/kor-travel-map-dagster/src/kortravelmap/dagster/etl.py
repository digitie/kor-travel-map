"""Dagster asset에서 재사용하는 FeatureBundle 검증 + DB 적재 helper."""

from __future__ import annotations

import pickle
from collections import Counter
from dataclasses import dataclass, replace
from tempfile import TemporaryFile
from typing import TYPE_CHECKING, Final

from kortravelmap.client import AddressValidationFinding
from kortravelmap.core.exceptions import IntegrityFindingPersistenceError
from kortravelmap.core.ids import make_integrity_finding_key

from dagster import Failure
from kortravelmap.dagster.validation import (
    FeatureAddressValidationSummary,
    validate_feature_bundles_address,
)

if TYPE_CHECKING:
    from collections.abc import (
        AsyncIterable,
        AsyncIterator,
        Awaitable,
        Callable,
        Mapping,
        Sequence,
    )

    from kortravelmap.client import AsyncKorTravelMapClient
    from kortravelmap.dto import FeatureBundle
    from kortravelmap.infra.feature_repo import FeatureLoadResult

    from dagster import AssetExecutionContext


FEATURE_LOAD_CHUNK_SIZE: Final[int] = 1000
"""Dagster asset이 FeatureBundle을 DB에 적재할 때 사용하는 기본 chunk 크기."""

FEATURE_ID_METADATA_LIMIT: Final[int] = 1000
"""대용량 stream에서 Dagster metadata에 남길 Feature id 표본 상한."""

ADDRESS_VALIDATION_ISSUE_METADATA_LIMIT: Final[int] = 100
"""대용량 stream에서 Dagster metadata에 남길 검증 issue 표본 상한."""


@dataclass(frozen=True)
class AddressFindingObservationReceipt:
    """stale close 권한과 provider sync 성공을 분리하는 관측 receipt (#911).

    source snapshot을 끝까지 읽고, 비어 있지 않은 관측의 finding 전량을 durable하게 기록한
    경우에만 absence를 부정 증거로 사용할 수 있다.
    """

    authoritative_snapshot_complete: bool
    source_observations: int
    findings_observed: int
    findings_unique: int
    findings_upserted: int
    finding_persistence_complete: bool

    @property
    def permits_stale_close(self) -> bool:
        """이 관측의 absence가 기존 finding을 닫을 만큼 강한지 반환한다."""

        return (
            self.authoritative_snapshot_complete
            and self.source_observations > 0
            and self.finding_persistence_complete
            and self.findings_upserted == self.findings_unique
        )

    def merge(
        self,
        other: AddressFindingObservationReceipt,
    ) -> AddressFindingObservationReceipt:
        """같은 provider/dataset의 chunk receipt를 합산한다."""

        return AddressFindingObservationReceipt(
            authoritative_snapshot_complete=(
                self.authoritative_snapshot_complete
                and other.authoritative_snapshot_complete
            ),
            source_observations=self.source_observations + other.source_observations,
            findings_observed=self.findings_observed + other.findings_observed,
            findings_unique=self.findings_unique + other.findings_unique,
            findings_upserted=self.findings_upserted + other.findings_upserted,
            finding_persistence_complete=(
                self.finding_persistence_complete
                and other.finding_persistence_complete
            ),
        )

    def complete_authoritative_snapshot(self) -> AddressFindingObservationReceipt:
        """모든 chunk source iterator가 정상 종료된 뒤 authoritative로 승격한다."""

        return replace(self, authoritative_snapshot_complete=True)

    def as_metadata(self) -> dict[str, object]:
        return {
            "address_observation_authoritative_snapshot_complete": (
                self.authoritative_snapshot_complete
            ),
            "address_observation_source_count": self.source_observations,
            "address_observation_finding_persistence_complete": (
                self.finding_persistence_complete
            ),
            "address_observation_stale_close_permitted": self.permits_stale_close,
        }


@dataclass(frozen=True)
class DagsterFeatureLoadResult:
    """Dagster provider load asset 결과."""

    provider: str
    dataset_key: str
    feature_ids: tuple[str, ...]
    load: FeatureLoadResult
    address_validation: FeatureAddressValidationSummary
    observation_receipt: AddressFindingObservationReceipt
    feature_ids_complete: bool = True

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
        metadata.update(self.observation_receipt.as_metadata())
        if not self.feature_ids_complete:
            metadata["feature_ids_truncated"] = True
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
            observation_receipt=self.observation_receipt.merge(
                other.observation_receipt
            ),
            feature_ids_complete=(
                self.feature_ids_complete and other.feature_ids_complete
            ),
        )

    def complete_authoritative_snapshot(self) -> DagsterFeatureLoadResult:
        """chunked provider iterator가 정상 종료된 뒤 close 가능한 snapshot으로 승격한다."""

        return replace(
            self,
            observation_receipt=(
                self.observation_receipt.complete_authoritative_snapshot()
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
    authoritative_snapshot_complete: bool = False,
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
    source_observations = len(bundles)
    validation = validate_feature_bundles_address(bundles)
    # drop 모드가 bundles를 재할당하기 **전에** 잡는다 — 그러지 않으면 drop된 레코드의
    # 원천 identity를 잃고 dedupe_key가 payload hash 기반 source_record_key로 되돌아가지
    # 않도록, drop 전 bundle에서 type+id를 함께 잡는다.
    source_identities = _source_identities(bundles)
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
            source_identities=source_identities,
        )
        failure_metadata = dict(validation.as_metadata())
        try:
            sync = await client.record_address_validation_findings(
                failed_findings,
                provider=provider,
                dataset_key=dataset_key,
            )
        except IntegrityFindingPersistenceError as exc:
            failure_metadata.update(
                {
                    "address_validation_findings_observed": exc.observed_count,
                    "address_validation_findings_unique": exc.unique_count,
                    "address_validation_findings_upserted": 0,
                    "address_validation_findings_unrecorded": exc.unique_count,
                }
            )
            _add_output_metadata(context, failure_metadata)
            raise Failure(
                description="Feature 주소/좌표 검증 finding durable 기록 실패",
                metadata=failure_metadata,
            ) from None
        failure_metadata.update(
            {
                "address_validation_findings_observed": sync.observed_count,
                "address_validation_findings_unique": sync.unique_count,
                "address_validation_findings_upserted": sync.upserted_count,
            }
        )
        if sync.unrecorded_count:
            failure_metadata["address_validation_findings_unrecorded"] = (
                sync.unrecorded_count
            )
            _add_output_metadata(context, failure_metadata)
            raise Failure(
                description="Feature 주소/좌표 검증 finding durable 기록 불완전",
                metadata=failure_metadata,
            )
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
    elif authoritative_snapshot_complete:
        # Curation child receipt must be causally tied to one committed DB image.
        # Chunk transactions would allow another run to interleave and make the
        # last chunk's seal describe a mixed snapshot.
        load = await client.load_feature_bundles(
            bundles, curation_dataset=(provider, dataset_key)
        )
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
        observation_receipt=AddressFindingObservationReceipt(
            authoritative_snapshot_complete=authoritative_snapshot_complete,
            source_observations=source_observations,
            findings_observed=0,
            findings_unique=0,
            findings_upserted=0,
            finding_persistence_complete=False,
        ),
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
        source_identities=source_identities,
    )
    finding_observed = 0
    finding_unique = 0
    finding_upserted = 0
    finding_persistence_complete = False
    try:
        sync = await client.record_address_validation_findings(
            findings,
            provider=provider,
            dataset_key=dataset_key,
            run_id=_dagster_run_id(context),
        )
    except IntegrityFindingPersistenceError as exc:
        finding_observed = exc.observed_count
        finding_unique = exc.unique_count
        metadata.update(
            {
                "address_validation_findings_observed": exc.observed_count,
                "address_validation_findings_unique": exc.unique_count,
                "address_validation_findings_upserted": 0,
                "address_validation_findings_unrecorded": exc.unique_count,
            }
        )
        if mode == "strict":
            _add_output_metadata(context, metadata)
            raise Failure(
                description="Feature 주소/좌표 검증 finding durable 기록 실패",
                metadata={
                    "address_validation_findings_observed": exc.observed_count,
                    "address_validation_findings_unique": exc.unique_count,
                    "address_validation_findings_upserted": 0,
                    "address_validation_findings_unrecorded": exc.unique_count,
                },
            ) from None
    else:
        finding_observed = sync.observed_count
        finding_unique = sync.unique_count
        finding_upserted = sync.upserted_count
        finding_persistence_complete = sync.unrecorded_count == 0
        metadata.update(
            {
                "address_validation_findings_observed": sync.observed_count,
                "address_validation_findings_unique": sync.unique_count,
                "address_validation_findings_upserted": sync.upserted_count,
            }
        )
        if sync.unrecorded_count:
            metadata["address_validation_findings_unrecorded"] = sync.unrecorded_count
            if mode == "strict":
                _add_output_metadata(context, metadata)
                raise Failure(
                    description="Feature 주소/좌표 검증 finding durable 기록 불완전",
                    metadata={
                        "address_validation_findings_observed": sync.observed_count,
                        "address_validation_findings_unique": sync.unique_count,
                        "address_validation_findings_upserted": sync.upserted_count,
                        "address_validation_findings_unrecorded": (
                            sync.unrecorded_count
                        ),
                    },
                )

    result = replace(
        result,
        observation_receipt=AddressFindingObservationReceipt(
            authoritative_snapshot_complete=authoritative_snapshot_complete,
            source_observations=source_observations,
            findings_observed=finding_observed,
            findings_unique=finding_unique,
            findings_upserted=finding_upserted,
            finding_persistence_complete=finding_persistence_complete,
        ),
    )
    metadata.update(result.observation_receipt.as_metadata())
    _add_output_metadata(context, metadata)
    return result


async def load_feature_bundle_batches_for_dagster(
    *,
    context: AssetExecutionContext,
    client: AsyncKorTravelMapClient,
    batches: AsyncIterable[Sequence[FeatureBundle]],
    provider: str,
    dataset_key: str,
    strict_address: bool | str,
    load_all: Callable[
        [AsyncIterable[Sequence[FeatureBundle]]], Awaitable[FeatureLoadResult]
    ],
) -> DagsterFeatureLoadResult:
    """대용량 provider batch를 materialize하지 않고 한 DB transaction으로 적재한다.

    변환된 bundle은 현재 batch만 보유한다. validation summary와 durable finding,
    경량 feature id만 누적하고, ``load_all``은 모든 batch를 동일 session/transaction에
    흘려 넣어 authoritative curation seal과 같은 DB image를 보게 한다.
    """

    mode = _normalize_address_validation_mode(strict_address)
    validation = FeatureAddressValidationSummary(
        total=0,
        issue_count=0,
        error_count=0,
        warning_count=0,
        issues=(),
    )
    feature_ids: list[str] = []
    loaded_feature_count = 0
    dropped_feature_ids: list[str] = []
    strict_failure = False
    sync_observed = 0
    sync_unique = 0
    sync_upserted = 0

    # Finding은 Feature transaction commit 뒤 FK-linked 상태로 기록해야 한다. 전량을
    # 메모리에 보관하지 않고 batch tuple만 임시 spool에 직렬화한 뒤 bounded chunk로
    # 재생한다. 파일 수명은 이 호출로 제한되며 정상/예외 모두 즉시 닫힌다.
    with TemporaryFile() as finding_spool:

        async def _validated_batches() -> AsyncIterator[Sequence[FeatureBundle]]:
            nonlocal loaded_feature_count, strict_failure, validation
            async for raw_batch in batches:
                batch = list(raw_batch)
                batch_validation = validate_feature_bundles_address(batch)
                validation = _merge_validation_summaries(validation, batch_validation)
                source_identities = _source_identities(batch)
                if mode == "strict" and batch_validation.has_errors:
                    strict_failure = True
                    failed_findings = _address_validation_findings(
                        batch_validation,
                        provider=provider,
                        dataset_key=dataset_key,
                        loaded_feature_ids=frozenset(),
                        dropped_feature_ids=frozenset(
                            issue.feature_id
                            for issue in batch_validation.issues
                            if issue.severity == "error"
                        ),
                        source_identities=source_identities,
                    )
                    pickle.dump(tuple(failed_findings), finding_spool)
                    raise Failure(
                        description="Feature 주소/좌표 검증 실패: "
                        + ", ".join(
                            issue.code
                            for issue in batch_validation.issues
                            if issue.severity == "error"
                        ),
                        metadata=validation.as_metadata(),
                    )

                dropped_ids: set[str] = set()
                if mode == "drop" and batch_validation.has_blocking_errors:
                    dropped_ids = {
                        issue.feature_id for issue in batch_validation.blocking_issues
                    }
                    remaining_dropped = FEATURE_ID_METADATA_LIMIT - len(dropped_feature_ids)
                    if remaining_dropped > 0:
                        dropped_feature_ids.extend(sorted(dropped_ids)[:remaining_dropped])
                    batch = [
                        bundle
                        for bundle in batch
                        if bundle.feature.feature_id not in dropped_ids
                    ]
                loaded_ids = {bundle.feature.feature_id for bundle in batch}
                loaded_feature_count += len(batch)
                remaining_sample = FEATURE_ID_METADATA_LIMIT - len(feature_ids)
                if remaining_sample > 0:
                    feature_ids.extend(
                        bundle.feature.feature_id for bundle in batch[:remaining_sample]
                    )
                findings = _address_validation_findings(
                    batch_validation,
                    provider=provider,
                    dataset_key=dataset_key,
                    loaded_feature_ids=loaded_ids,
                    dropped_feature_ids=frozenset(dropped_ids),
                    source_identities=source_identities,
                )
                if findings:
                    pickle.dump(tuple(findings), finding_spool)
                yield batch

        try:
            load = await load_all(_validated_batches())
        except Failure:
            if strict_failure:
                finding_spool.seek(0)
                while findings := _load_finding_chunk(finding_spool):
                    await client.record_address_validation_findings(
                        tuple(
                            replace(
                                finding,
                                linked=False,
                                source_record_key=None,
                                feature_id=None,
                            )
                            for finding in findings
                        ),
                        provider=provider,
                        dataset_key=dataset_key,
                        run_id=_dagster_run_id(context),
                    )
            raise

        finding_spool.seek(0)
        while findings := _load_finding_chunk(finding_spool):
            sync = await client.record_address_validation_findings(
                findings,
                provider=provider,
                dataset_key=dataset_key,
                run_id=_dagster_run_id(context),
            )
            sync_observed += sync.observed_count
            sync_unique += sync.unique_count
            sync_upserted += sync.upserted_count
    result = DagsterFeatureLoadResult(
        provider=provider,
        dataset_key=dataset_key,
        feature_ids=tuple(feature_ids),
        load=load,
        address_validation=validation,
        observation_receipt=AddressFindingObservationReceipt(
            authoritative_snapshot_complete=True,
            source_observations=validation.total,
            findings_observed=sync_observed,
            findings_unique=sync_unique,
            findings_upserted=sync_upserted,
            finding_persistence_complete=sync_unique == sync_upserted,
        ),
        feature_ids_complete=loaded_feature_count <= FEATURE_ID_METADATA_LIMIT,
    )
    metadata = result.as_metadata()
    if dropped_feature_ids:
        metadata["address_validation_dropped_count"] = len(dropped_feature_ids)
        metadata["address_validation_dropped_feature_ids"] = dropped_feature_ids
    _add_output_metadata(context, metadata)
    return result


def _address_validation_findings(
    validation: FeatureAddressValidationSummary,
    *,
    provider: str,
    dataset_key: str,
    loaded_feature_ids: frozenset[str] | set[str],
    dropped_feature_ids: frozenset[str],
    source_identities: Mapping[str, tuple[str, str]],
) -> list[AddressValidationFinding]:
    """검증 issue → durable finding (T-VN-H30A).

    ``dedupe_key``는 provider/dataset/code와 source entity **type+id** 전체를
    SHA256으로 만든다.

    ``source_record_key``를 쓰면 안 된다 — 그 키는 ``raw_payload_hash``에서 파생되므로
    (``core.ids.make_source_record_key``) provider export에서 무관한 필드 하나만 바뀌어도
    새 key가 되고, 같은 문제가 **매 export마다 새 열린 이슈**로 쌓인다. MOIS 규모(977k)에서는
    큐가 단조 증가한다. source entity type+id는 payload 변경과 무관하게 안정적이다.
    """
    findings: list[AddressValidationFinding] = []
    for issue in validation.issues:
        linked = issue.feature_id in loaded_feature_ids
        identity = source_identities.get(issue.source_record_key)
        if identity is None:
            raise ValueError(
                "주소 검증 finding의 source identity가 없음: "
                f"{issue.source_record_key}"
            )
        source_entity_type, source_entity_id = identity
        findings.append(
            AddressValidationFinding(
                dedupe_key=make_integrity_finding_key(
                    provider=provider,
                    dataset_key=dataset_key,
                    source_entity_type=source_entity_type,
                    source_entity_id=source_entity_id,
                    violation_type=issue.code,
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


def _load_finding_chunk(spool: object) -> tuple[AddressValidationFinding, ...]:
    """pickle spool의 다음 bounded finding chunk를 읽는다."""

    try:
        value = pickle.load(spool)  # type: ignore[arg-type]
    except EOFError:
        return ()
    if not isinstance(value, tuple) or not all(
        isinstance(item, AddressValidationFinding) for item in value
    ):
        raise RuntimeError("address validation finding spool이 손상되었습니다.")
    return value


def _merge_validation_summaries(
    left: FeatureAddressValidationSummary,
    right: FeatureAddressValidationSummary,
) -> FeatureAddressValidationSummary:
    merged_grades = Counter(left.evidence_grade_counts)
    merged_grades.update(right.evidence_grade_counts)
    merged_name_states = Counter(left.name_state_counts)
    merged_name_states.update(right.name_state_counts)
    return FeatureAddressValidationSummary(
        total=left.total + right.total,
        issue_count=left.issue_count + right.issue_count,
        error_count=left.error_count + right.error_count,
        warning_count=left.warning_count + right.warning_count,
        # T-VN-H28B: 커버리지를 합치지 않으면 batch가 2개 이상인 run에서 빈 dict가 나가
        # "측정 안 됨"과 "잴 것이 없음"을 구분할 수 없게 된다.
        evidence_grade_counts=dict(merged_grades),
        name_state_counts=dict(merged_name_states),
        issues=(left.issues + right.issues)[:ADDRESS_VALIDATION_ISSUE_METADATA_LIMIT],
    )


def _add_output_metadata(
    context: AssetExecutionContext, metadata: Mapping[str, object]
) -> None:
    try:
        context.add_output_metadata(metadata)
    except Exception as exc:
        if exc.__class__.__name__ != "DagsterInvalidPropertyError":
            raise


def _source_identities(
    bundles: Sequence[FeatureBundle],
) -> dict[str, tuple[str, str]]:
    """``source_record_key`` → 원천 entity type+id."""
    return {
        bundle.source_record.source_record_key: (
            bundle.source_record.source_entity_type,
            bundle.source_record.source_entity_id,
        )
        for bundle in bundles
    }


def _dagster_run_id(context: AssetExecutionContext) -> str | None:
    """이 run의 외부 식별자. 직접 호출(테스트)에서는 없을 수 있다 (T-VN-H32R).

    ``run_id``가 없으면 immutable observation generation을 만들지 않고 close receipt도
    발행하지 않는다. 직접 호출은 absence를 증명하지 못하므로 **닫지 않는 쪽**으로
    fail-safe한다.
    """
    try:
        run_id = context.run_id
    except Exception:
        return None
    return str(run_id) if run_id else None

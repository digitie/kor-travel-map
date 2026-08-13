"""Dagster Feature load helper unit test."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from dagster import Failure
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.core.exceptions import IntegrityFindingPersistenceError
from kortravelmap.infra.feature_repo import FeatureLoadResult

from kortravelmap.dagster.etl import (
    AddressFindingObservationReceipt,
    DagsterFeatureLoadResult,
    load_feature_bundle_batches_for_dagster,
    load_feature_bundles_for_dagster,
)
from kortravelmap.dagster.validation import (
    DROPPABLE_ISSUE_CODES,
    FeatureAddressIssue,
    FeatureAddressValidationSummary,
    ensure_feature_address_valid,
)


@dataclass(frozen=True)
class _Feature:
    feature_id: str


@dataclass(frozen=True)
class _SourceRecord:
    """T-VN-H30A: dedupe_key는 payload hash가 아닌 안정적 entity identity에 걸린다."""

    source_record_key: str
    source_entity_id: str
    source_entity_type: str = "place"


@dataclass(frozen=True)
class _Bundle:
    feature: _Feature
    source_record: _SourceRecord = field(
        default_factory=lambda: _SourceRecord("sr_x", "entity-x")
    )


def _bundle(feature_id: str) -> _Bundle:
    return _Bundle(
        _Feature(feature_id),
        _SourceRecord(
            source_record_key=f"sr_{feature_id}",
            source_entity_id=feature_id,
        ),
    )


class _Context:
    def __init__(self, *, run_id: str | None = None) -> None:
        self.metadata: list[dict[str, object]] = []
        self.run_id = run_id

    def add_output_metadata(self, metadata: dict[str, object]) -> None:
        self.metadata.append(dict(metadata))


class _Client:
    def __init__(self) -> None:
        self.chunks: list[tuple[str, ...]] = []
        self.finding_chunks: list[list[Any]] = []

    async def load_feature_bundles(
        self, bundles: list[_Bundle], **kwargs: object
    ) -> FeatureLoadResult:
        del kwargs
        self.chunks.append(tuple(bundle.feature.feature_id for bundle in bundles))
        return FeatureLoadResult(
            bundles_total=len(bundles),
            features_inserted=len(bundles),
        )

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다).

        ``kwargs``도 보관해 provider/dataset 정체성 배선을 검증할 수 있게 한다.
        """
        current_findings = list(findings)  # type: ignore[arg-type]
        self.finding_chunks.append(current_findings)
        self.recorded_findings = current_findings
        self.recorded_kwargs = dict(kwargs)
        unique_count = len(
            {finding.dedupe_key for finding in self.recorded_findings}
        )
        return IntegrityFindingSyncResult(
            observed_count=len(self.recorded_findings),
            unique_count=unique_count,
            upserted_count=unique_count,
        )


def _receipt(
    *,
    authoritative_snapshot_complete: bool = True,
    source_observations: int = 1,
    findings_observed: int = 0,
    findings_unique: int = 0,
    findings_upserted: int = 0,
    finding_persistence_complete: bool = True,
) -> AddressFindingObservationReceipt:
    return AddressFindingObservationReceipt(
        authoritative_snapshot_complete=authoritative_snapshot_complete,
        source_observations=source_observations,
        findings_observed=findings_observed,
        findings_unique=findings_unique,
        findings_upserted=findings_upserted,
        finding_persistence_complete=finding_persistence_complete,
    )


def test_dagster_feature_load_result_merge_preserves_name_states() -> None:
    left = DagsterFeatureLoadResult(
        provider="demo",
        dataset_key="places",
        feature_ids=("left",),
        load=FeatureLoadResult(bundles_total=1, features_inserted=1),
        address_validation=FeatureAddressValidationSummary(
            total=1,
            issue_count=0,
            error_count=0,
            warning_count=0,
            evidence_grade_counts={"unarmed": 1},
            name_state_counts={"matched": 1},
            issues=(),
        ),
        observation_receipt=_receipt(),
    )
    right = DagsterFeatureLoadResult(
        provider="demo",
        dataset_key="places",
        feature_ids=("right",),
        load=FeatureLoadResult(bundles_total=1, features_inserted=1),
        address_validation=FeatureAddressValidationSummary(
            total=1,
            issue_count=1,
            error_count=0,
            warning_count=1,
            evidence_grade_counts={"unarmed": 1},
            name_state_counts={"disagreed": 1},
            issues=(),
        ),
        observation_receipt=_receipt(),
    )

    merged = left.merge(right)

    assert merged.address_validation.evidence_grade_counts == {"unarmed": 2}
    assert merged.address_validation.name_state_counts == {
        "matched": 1,
        "disagreed": 1,
    }


async def test_load_feature_bundles_for_dagster_chunks_db_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_bundle(f"feature-{index}") for index in range(5)]
    context = _Context()
    client = _Client()

    def _validate(items: Any) -> FeatureAddressValidationSummary:
        return FeatureAddressValidationSummary(
            total=len(items),
            issue_count=0,
            error_count=0,
            warning_count=0,
            issues=(),
        )

    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        _validate,
    )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=bundles,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        chunk_size=2,
    )

    assert client.chunks == [
        ("feature-0", "feature-1"),
        ("feature-2", "feature-3"),
        ("feature-4",),
    ]
    assert result.feature_ids == tuple(bundle.feature.feature_id for bundle in bundles)
    assert result.load.bundles_total == 5
    assert result.load.features_inserted == 5
    assert context.metadata[-1]["bundles_total"] == 5


async def test_streaming_feature_batches_keep_one_atomic_loader_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()
    client = _Client()
    yielded: list[int] = []
    consumed: list[tuple[str, ...]] = []

    async def _batches() -> Any:
        for start in (0, 2, 4):
            batch = [_bundle(f"feature-{index}") for index in range(start, min(5, start + 2))]
            yielded.append(len(batch))
            yield batch

    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: FeatureAddressValidationSummary(
            total=len(items),
            issue_count=0,
            error_count=0,
            warning_count=0,
            issues=(),
        ),
    )
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.FEATURE_ID_METADATA_LIMIT",
        2,
    )

    async def _load_all(batches: Any) -> FeatureLoadResult:
        result = FeatureLoadResult()
        async for batch in batches:
            consumed.append(tuple(item.feature.feature_id for item in batch))
            result = result.merge(
                FeatureLoadResult(
                    bundles_total=len(batch),
                    features_inserted=len(batch),
                )
            )
        return result

    result = await load_feature_bundle_batches_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        batches=_batches(),  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address="off",
        load_all=_load_all,  # type: ignore[arg-type]
    )

    assert yielded == [2, 2, 1]
    assert consumed == [
        ("feature-0", "feature-1"),
        ("feature-2", "feature-3"),
        ("feature-4",),
    ]
    assert result.load.bundles_total == 5
    assert result.feature_ids == ("feature-0", "feature-1")
    assert result.feature_ids_complete is False
    assert context.metadata[-1]["feature_ids_truncated"] is True
    assert result.observation_receipt.authoritative_snapshot_complete is True


async def test_streaming_clean_snapshot_records_empty_finding_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context(run_id="run-clean")
    client = _Client()

    async def _batches() -> Any:
        yield [_bundle("feature-0")]

    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: FeatureAddressValidationSummary(
            total=len(items),
            issue_count=0,
            error_count=0,
            warning_count=0,
            issues=(),
        ),
    )

    async def _load_all(batches: Any) -> FeatureLoadResult:
        loaded = 0
        async for batch in batches:
            loaded += len(batch)
        return FeatureLoadResult(bundles_total=loaded, features_inserted=loaded)

    result = await load_feature_bundle_batches_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        batches=_batches(),  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address="off",
        load_all=_load_all,  # type: ignore[arg-type]
    )

    assert client.finding_chunks == [[]]
    assert client.recorded_kwargs["run_id"] == "run-clean"
    assert result.observation_receipt.finding_persistence_complete is True


async def test_streaming_drop_metadata_keeps_total_beyond_id_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context(run_id="run-drop")
    client = _Client()

    async def _batches() -> Any:
        for index in range(3):
            yield [_bundle(f"feature-{index}")]

    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: _error_summary(
            items, error_feature_id=items[0].feature.feature_id
        ),
    )
    monkeypatch.setattr("kortravelmap.dagster.etl.FEATURE_ID_METADATA_LIMIT", 2)

    async def _load_all(batches: Any) -> FeatureLoadResult:
        loaded = 0
        async for batch in batches:
            loaded += len(batch)
        return FeatureLoadResult(bundles_total=loaded, features_inserted=loaded)

    await load_feature_bundle_batches_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        batches=_batches(),  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address="drop",
        load_all=_load_all,  # type: ignore[arg-type]
    )

    metadata = context.metadata[-1]
    assert metadata["address_validation_dropped_count"] == 3
    assert metadata["address_validation_dropped_feature_ids"] == [
        "feature-0",
        "feature-1",
    ]
    assert metadata["address_validation_dropped_feature_ids_truncated"] is True


async def test_streaming_feature_batches_bound_issue_metadata_and_finding_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()
    client = _Client()

    async def _batches() -> Any:
        for index in range(12):
            yield [_bundle(f"feature-{index}")]

    def _warning(items: list[_Bundle]) -> FeatureAddressValidationSummary:
        bundle = items[0]
        issue = FeatureAddressIssue(
            feature_id=bundle.feature.feature_id,
            source_record_key=bundle.source_record.source_record_key,
            code="reverse_geocode_not_attempted",
            severity="warning",
            message="warning",
            provider_address=None,
            bjd_code="1111010100",
            sigungu_code="11110",
        )
        return FeatureAddressValidationSummary(
            total=1,
            issue_count=1,
            error_count=0,
            warning_count=1,
            issues=(issue,),
        )

    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        _warning,
    )
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.ADDRESS_VALIDATION_ISSUE_METADATA_LIMIT",
        3,
    )

    async def _load_all(batches: Any) -> FeatureLoadResult:
        result = FeatureLoadResult()
        async for batch in batches:
            result = result.merge(
                FeatureLoadResult(
                    bundles_total=len(batch),
                    features_inserted=len(batch),
                )
            )
        return result

    result = await load_feature_bundle_batches_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        batches=_batches(),  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address="off",
        load_all=_load_all,  # type: ignore[arg-type]
    )

    assert result.address_validation.issue_count == 12
    assert len(result.address_validation.issues) == 3
    assert len(client.finding_chunks) == 12
    assert all(len(chunk) == 1 for chunk in client.finding_chunks)
    assert result.observation_receipt.findings_observed == 12
    assert len(context.metadata[-1]["address_validation_issues"]) == 3  # type: ignore[arg-type]


async def test_nonempty_complete_snapshot_receipt_permits_stale_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: FeatureAddressValidationSummary(
            total=len(items),
            issue_count=0,
            error_count=0,
            warning_count=0,
            issues=(),
        ),
    )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=[_bundle("feature-0")],  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        authoritative_snapshot_complete=True,
    )

    assert result.observation_receipt.permits_stale_close is True
    assert (
        context.metadata[-1]["address_observation_stale_close_permitted"] is True
    )


async def test_empty_snapshot_receipt_never_permits_stale_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: FeatureAddressValidationSummary(
            total=len(items),
            issue_count=0,
            error_count=0,
            warning_count=0,
            issues=(),
        ),
    )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=[],  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        authoritative_snapshot_complete=True,
    )

    assert result.observation_receipt.authoritative_snapshot_complete is True
    assert result.observation_receipt.source_observations == 0
    assert result.observation_receipt.permits_stale_close is False


@pytest.mark.parametrize("mode", ["off", "drop"])
async def test_finding_persistence_failure_revokes_stale_close_authority(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: FeatureAddressValidationSummary(
            total=len(items),
            issue_count=0,
            error_count=0,
            warning_count=0,
            issues=(),
        ),
    )

    async def _fail_recording(findings: object, **kwargs: object) -> None:
        del findings, kwargs
        raise IntegrityFindingPersistenceError(
            provider="demo",
            dataset_key="places",
            observed_count=1,
            unique_count=1,
            error_type="OperationalError",
        )

    monkeypatch.setattr(client, "record_address_validation_findings", _fail_recording)

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=[_bundle("feature-0")],  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address=mode,
        authoritative_snapshot_complete=True,
    )

    assert result.observation_receipt.finding_persistence_complete is False
    assert result.observation_receipt.permits_stale_close is False


async def test_partial_finding_persistence_revokes_stale_close_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: FeatureAddressValidationSummary(
            total=len(items),
            issue_count=1,
            error_count=0,
            warning_count=1,
            issues=(_issue("provider_address_mismatch", "feature-0"),),
        ),
    )

    async def _record_partially(
        findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        del findings, kwargs
        return IntegrityFindingSyncResult(
            observed_count=1,
            unique_count=1,
            upserted_count=0,
        )

    monkeypatch.setattr(
        client, "record_address_validation_findings", _record_partially
    )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=[_bundle("feature-0")],  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address="off",
        authoritative_snapshot_complete=True,
    )

    assert result.observation_receipt.findings_unique == 1
    assert result.observation_receipt.findings_upserted == 0
    assert result.observation_receipt.permits_stale_close is False


async def test_load_feature_bundles_for_dagster_uses_atomic_load_all_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_bundle(f"feature-{index}") for index in range(5)]
    context = _Context()
    client = _Client()
    atomic_calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: FeatureAddressValidationSummary(
            total=len(items),
            issue_count=0,
            error_count=0,
            warning_count=0,
            issues=(),
        ),
    )

    async def _load_all(items: Any) -> FeatureLoadResult:
        materialized = list(items)
        atomic_calls.append(
            tuple(bundle.feature.feature_id for bundle in materialized)
        )
        return FeatureLoadResult(
            bundles_total=len(materialized),
            features_inserted=len(materialized),
        )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=bundles,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="notices",
        chunk_size=2,
        load_all=_load_all,  # type: ignore[arg-type]
    )

    assert atomic_calls == [tuple(bundle.feature.feature_id for bundle in bundles)]
    assert client.chunks == []
    assert result.load.bundles_total == 5


def _error_summary(items: Any, *, error_feature_id: str) -> FeatureAddressValidationSummary:
    return FeatureAddressValidationSummary(
        total=len(items),
        issue_count=1,
        error_count=1,
        warning_count=0,
        issues=(
            FeatureAddressIssue(
                feature_id=error_feature_id,
                source_record_key=f"sr_{error_feature_id}",
                code="reverse_geocode_failed",
                severity="error",
                message="mismatch",
            ),
        ),
    )


@pytest.mark.parametrize("mode", ["strict", True])
async def test_load_strict_mode_fails_on_error_issue(
    monkeypatch: pytest.MonkeyPatch, mode: bool | str
) -> None:
    bundles = [_bundle(f"feature-{index}") for index in range(3)]
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: _error_summary(items, error_feature_id="feature-1"),
    )

    with pytest.raises(Failure, match="reverse_geocode_failed"):
        await load_feature_bundles_for_dagster(
            context=context,  # type: ignore[arg-type]
            client=client,  # type: ignore[arg-type]
            bundles=bundles,  # type: ignore[arg-type]
            provider="demo",
            dataset_key="places",
            strict_address=mode,
        )
    assert client.chunks == []


async def test_load_drop_mode_quarantines_error_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_bundle(f"feature-{index}") for index in range(3)]
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: _error_summary(items, error_feature_id="feature-1"),
    )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=bundles,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address="drop",
    )

    assert client.chunks == [("feature-0", "feature-2")]
    assert result.feature_ids == ("feature-0", "feature-2")
    assert context.metadata[-1]["address_validation_dropped_count"] == 1
    assert context.metadata[-1]["address_validation_dropped_feature_ids"] == [
        "feature-1"
    ]


@pytest.mark.parametrize("mode", ["off", False])
async def test_load_off_mode_loads_all_rows(
    monkeypatch: pytest.MonkeyPatch, mode: bool | str
) -> None:
    bundles = [_bundle(f"feature-{index}") for index in range(3)]
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: _error_summary(items, error_feature_id="feature-1"),
    )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=bundles,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address=mode,
    )

    assert client.chunks == [("feature-0", "feature-1", "feature-2")]
    assert result.load.bundles_total == 3
    assert "address_validation_dropped_count" not in context.metadata[-1]


async def test_load_rejects_unknown_validation_mode() -> None:
    with pytest.raises(ValueError, match="unknown address validation mode"):
        await load_feature_bundles_for_dagster(
            context=_Context(),  # type: ignore[arg-type]
            client=_Client(),  # type: ignore[arg-type]
            bundles=[],  # type: ignore[arg-type]
            provider="demo",
            dataset_key="places",
            strict_address="lenient",
        )


def _non_droppable_summary(
    items: Any, *, error_feature_id: str
) -> FeatureAddressValidationSummary:
    """allowlist에 없는 code가 error severity로 올라온 경우 (T-VN-H28B)."""
    return FeatureAddressValidationSummary(
        total=len(items),
        issue_count=1,
        error_count=1,
        warning_count=0,
        issues=(
            FeatureAddressIssue(
                feature_id=error_feature_id,
                source_record_key=f"sr_{error_feature_id}",
                code="some_future_rule_error",
                severity="error",
                message="allowlist에 없는 새 규칙",
            ),
        ),
    )


def test_ensure_feature_address_valid_rejects_every_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_bundle("feature-0")]
    monkeypatch.setattr(
        "kortravelmap.dagster.validation.validate_feature_bundles_address",
        lambda items: _non_droppable_summary(items, error_feature_id="feature-0"),
    )

    with pytest.raises(ValueError, match="some_future_rule_error"):
        ensure_feature_address_valid(bundles)  # type: ignore[arg-type]


async def test_non_allowlisted_error_fails_strict_without_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_bundle(f"feature-{index}") for index in range(3)]
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: _non_droppable_summary(items, error_feature_id="feature-1"),
    )

    with pytest.raises(Failure, match="some_future_rule_error"):
        await load_feature_bundles_for_dagster(
            context=context,  # type: ignore[arg-type]
            client=client,  # type: ignore[arg-type]
            bundles=bundles,  # type: ignore[arg-type]
            provider="demo",
            dataset_key="places",
            strict_address="strict",
        )

    assert client.chunks == []


async def test_strict_mode_fails_closed_when_durable_recording_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_bundle("feature-0")]
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: _non_droppable_summary(items, error_feature_id="feature-0"),
    )

    async def _fail_recording(findings: object, **kwargs: object) -> None:
        del findings, kwargs
        raise IntegrityFindingPersistenceError(
            provider="demo",
            dataset_key="places",
            observed_count=1,
            unique_count=1,
            error_type="OperationalError",
        )

    monkeypatch.setattr(client, "record_address_validation_findings", _fail_recording)

    with pytest.raises(Failure, match="durable 기록 실패"):
        await load_feature_bundles_for_dagster(
            context=context,  # type: ignore[arg-type]
            client=client,  # type: ignore[arg-type]
            bundles=bundles,  # type: ignore[arg-type]
            provider="demo",
            dataset_key="places",
            strict_address="strict",
        )

    assert client.chunks == []
    assert context.metadata[-1]["address_validation_findings_unrecorded"] == 1


async def test_non_allowlisted_error_is_not_permanently_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """allowlist 밖 error는 drop 모드에서 영구 손실을 만들지 않는다."""
    bundles = [_bundle(f"feature-{index}") for index in range(3)]
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: _non_droppable_summary(items, error_feature_id="feature-1"),
    )

    result = await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=bundles,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        strict_address="drop",
    )

    assert client.chunks == [("feature-0", "feature-1", "feature-2")]
    assert result.feature_ids == ("feature-0", "feature-1", "feature-2")
    # drop이 없으면 격리 metadata 키 자체가 방출되지 않는다.
    assert "address_validation_dropped_count" not in context.metadata[-1]
    assert "address_validation_dropped_feature_ids" not in context.metadata[-1]


def test_droppable_codes_are_explicit_and_minimal() -> None:
    """drop 가능한 code 집합은 명시적이며, 늘리려면 이 테스트가 먼저 깨진다."""
    assert set(DROPPABLE_ISSUE_CODES) == {"reverse_geocode_failed", "missing_address"}
    # 이름 축·행정코드 축은 어떤 형태로도 영구 손실을 만들 수 없다.
    for code in (
        "provider_address_mismatch",
        "provider_address_partial_match",
        "admin_code_stale_sido",
        "admin_code_stale_sigungu",
        "admin_code_stale_emd",
    ):
        assert code not in DROPPABLE_ISSUE_CODES


def _issue(code: str, feature_id: str, severity: str = "warning") -> FeatureAddressIssue:
    return FeatureAddressIssue(
        feature_id=feature_id,
        source_record_key=f"sr_{feature_id}",
        code=code,
        severity=severity,
        message="msg",
        provider_address="어딘가",
        bjd_code="1111017700",
        sigungu_code="11110",
    )


def test_findings_link_fk_columns_only_for_loaded_features() -> None:
    """FK 안전성 (T-VN-H30A).

    ``ops.data_integrity_violations``의 ``feature_id``/``source_record_key``는 FK다.
    주소 검증은 적재 **전**에 돌아서 drop된 행은 두 대상이 DB에 없으므로, 그대로 넘기면
    기록 자체가 FK 위반으로 실패한다. 적재된 대상만 ``linked``여야 한다.
    """
    from kortravelmap.dagster.etl import _address_validation_findings

    summary = FeatureAddressValidationSummary(
        total=2,
        issue_count=2,
        error_count=1,
        warning_count=1,
        issues=(
            _issue("admin_code_stale_sido", "feature-loaded"),
            _issue("missing_address", "feature-dropped", severity="error"),
        ),
    )
    findings = _address_validation_findings(
        summary,
        provider="demo",
        dataset_key="places",
        loaded_feature_ids={"feature-loaded"},
        dropped_feature_ids=frozenset({"feature-dropped"}),
        source_identities={
            "sr_feature-loaded": ("place", "feature-loaded"),
            "sr_feature-dropped": ("place", "feature-dropped"),
        },
    )
    by_fid = {f.payload["feature_id"]: f for f in findings}

    loaded = by_fid["feature-loaded"]
    assert loaded.linked is True
    assert loaded.feature_id == "feature-loaded"

    dropped = by_fid["feature-dropped"]
    assert dropped.linked is False  # ← FK 대상이 DB에 없다
    assert dropped.payload["dropped"] is True
    # id 자체는 잃지 않는다 — payload로 나른다.
    assert dropped.payload["source_record_key"] == "sr_feature-dropped"


def test_finding_dedupe_key_is_stable_and_discriminating() -> None:
    """같은 레코드·같은 code는 run을 반복해도 한 행으로 접혀야 한다 (T-VN-H30A)."""
    from kortravelmap.dagster.etl import _address_validation_findings

    def build(code: str, feature_id: str, dataset: str = "places") -> str:
        summary = FeatureAddressValidationSummary(
            total=1,
            issue_count=1,
            error_count=0,
            warning_count=1,
            issues=(_issue(code, feature_id),),
        )
        return _address_validation_findings(
            summary,
            provider="demo",
            dataset_key=dataset,
            loaded_feature_ids={feature_id},
            dropped_feature_ids=frozenset(),
            source_identities={f"sr_{feature_id}": ("place", feature_id)},
        )[0].dedupe_key

    base = build("admin_code_stale_sido", "f1")
    assert base == build("admin_code_stale_sido", "f1")  # 재실행 시 동일
    assert base != build("admin_code_stale_sigungu", "f1")  # code가 다르면 별건
    assert base != build("admin_code_stale_sido", "f2")  # 레코드가 다르면 별건
    assert base != build("admin_code_stale_sido", "f1", dataset="other")  # dataset 분리


async def test_findings_are_recorded_after_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기록은 적재 **후**에 일어나고 건수가 metadata로 노출된다 (T-VN-H30A)."""
    bundles = [_bundle("feature-0")]
    context = _Context()
    client = _Client()
    monkeypatch.setattr(
        "kortravelmap.dagster.etl.validate_feature_bundles_address",
        lambda items: FeatureAddressValidationSummary(
            total=len(items),
            issue_count=1,
            error_count=0,
            warning_count=1,
            issues=(_issue("admin_code_stale_sido", "feature-0"),),
        ),
    )

    await load_feature_bundles_for_dagster(
        context=context,  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=bundles,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
    )

    assert context.metadata[-1]["address_validation_findings_observed"] == 1
    assert context.metadata[-1]["address_validation_findings_unique"] == 1
    assert context.metadata[-1]["address_validation_findings_upserted"] == 1
    assert "address_validation_findings_unrecorded" not in context.metadata[-1]
    # 적재가 먼저 일어났어야 linked가 성립한다.
    assert client.chunks == [("feature-0",)]
    assert client.recorded_findings[0].linked is True


def test_dedupe_key_uses_stable_entity_id_not_payload_hash() -> None:
    """dedupe_key는 payload가 바뀌어도 같아야 한다 (T-VN-H30A 핵심 불변식).

    ``source_record_key``는 ``raw_payload_hash`` 파생이라 export의 무관한 필드 하나만
    바뀌어도 값이 달라진다. 그 키로 dedupe하면 같은 문제가 export마다 새 열린 이슈로
    쌓인다(MOIS 977k 규모에서 큐 단조 증가). 안정적인 ``source_entity_id``를 써야 한다.

    이 테스트가 없으면 ``_entity_ids()``가 빈 dict를 돌려주는 어떤 회귀에도
    ``.get(k, k)`` fallback이 조용히 옛 동작으로 되돌아간다.
    """
    from kortravelmap.dagster.etl import _address_validation_findings

    def key_for(source_record_key: str, entity_id: str) -> str:
        summary = FeatureAddressValidationSummary(
            total=1,
            issue_count=1,
            error_count=0,
            warning_count=1,
            issues=(
                FeatureAddressIssue(
                    feature_id="f1",
                    source_record_key=source_record_key,
                    code="admin_code_stale_sido",
                    severity="warning",
                    message="m",
                ),
            ),
        )
        return _address_validation_findings(
            summary,
            provider="demo",
            dataset_key="places",
            loaded_feature_ids={"f1"},
            dropped_feature_ids=frozenset(),
            source_identities={source_record_key: ("place", entity_id)},
        )[0].dedupe_key

    # payload가 바뀌어 source_record_key가 달라져도 같은 entity면 같은 키다.
    assert key_for("sr_hash_v1", "E1") == key_for("sr_hash_v2", "E1")
    # 다른 entity는 반드시 갈라진다.
    assert key_for("sr_hash_v1", "E1") != key_for("sr_hash_v1", "E2")
    # 고정 길이 digest라 원천 id 자체를 B-tree key에 노출하지 않는다.
    assert key_for("sr_hash_v1", "E1").startswith("av2_")
    assert "sr_hash_v1" not in key_for("sr_hash_v1", "E1")

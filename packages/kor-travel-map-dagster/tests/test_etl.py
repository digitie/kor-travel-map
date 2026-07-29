"""Dagster Feature load helper unit test."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from dagster import Failure
from kortravelmap.infra.feature_repo import FeatureLoadResult

from kortravelmap.dagster.etl import load_feature_bundles_for_dagster
from kortravelmap.dagster.validation import (
    DROPPABLE_ISSUE_CODES,
    FeatureAddressIssue,
    FeatureAddressValidationSummary,
)


@dataclass(frozen=True)
class _Feature:
    feature_id: str


@dataclass(frozen=True)
class _SourceRecord:
    """T-VN-H30A: dedupe_key는 payload hash가 아닌 안정적 entity id에 걸린다."""

    source_record_key: str
    source_entity_id: str


@dataclass(frozen=True)
class _Bundle:
    feature: _Feature
    source_record: _SourceRecord = field(
        default_factory=lambda: _SourceRecord("sr_x", "entity-x")
    )


class _Context:
    def __init__(self) -> None:
        self.metadata: list[dict[str, object]] = []

    def add_output_metadata(self, metadata: dict[str, object]) -> None:
        self.metadata.append(dict(metadata))


class _Client:
    def __init__(self) -> None:
        self.chunks: list[tuple[str, ...]] = []

    async def load_feature_bundles(
        self, bundles: list[_Bundle]
    ) -> FeatureLoadResult:
        self.chunks.append(tuple(bundle.feature.feature_id for bundle in bundles))
        return FeatureLoadResult(
            bundles_total=len(bundles),
            features_inserted=len(bundles),
        )

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> int:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        return len(self.recorded_findings)


async def test_load_feature_bundles_for_dagster_chunks_db_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_Bundle(_Feature(f"feature-{index}")) for index in range(5)]
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


async def test_load_feature_bundles_for_dagster_uses_atomic_load_all_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundles = [_Bundle(_Feature(f"feature-{index}")) for index in range(5)]
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
                source_record_key="record-key",
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
    bundles = [_Bundle(_Feature(f"feature-{index}")) for index in range(3)]
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
    bundles = [_Bundle(_Feature(f"feature-{index}")) for index in range(3)]
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
    bundles = [_Bundle(_Feature(f"feature-{index}")) for index in range(3)]
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
                source_record_key="record-key",
                code="some_future_rule_error",
                severity="error",
                message="allowlist에 없는 새 규칙",
            ),
        ),
    )


@pytest.mark.parametrize("mode", ["strict", "drop"])
async def test_non_allowlisted_error_never_loses_rows(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """allowlist에 없는 error code는 drop도 run 실패도 만들지 못한다 (T-VN-H28B).

    이전에는 severity만 보고 격리해서, 새 error 규칙이 하나 추가될 때마다 영구 손실
    범위가 조용히 넓어졌다 — 실제로 ``provider_address_mismatch``가 그렇게 380건을
    파괴했고 그 380건은 전부 오탐이었다.
    """
    bundles = [_Bundle(_Feature(f"feature-{index}")) for index in range(3)]
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
        strict_address=mode,
    )

    # 세 건 모두 적재되고, 아무것도 drop되지 않는다.
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
    bundles = [_Bundle(_Feature("feature-0"))]
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

    assert context.metadata[-1]["address_validation_findings_recorded"] == 1
    assert "address_validation_findings_unrecorded" not in context.metadata[-1]
    # 적재가 먼저 일어났어야 linked가 성립한다.
    assert client.chunks == [("feature-0",)]
    assert client.recorded_findings[0].linked is True

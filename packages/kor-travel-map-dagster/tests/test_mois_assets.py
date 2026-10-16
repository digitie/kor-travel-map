"""MOIS asset 경계 — 재개형 적재기로 넘기고, 끝까지 본 전 업종 run만 sync 성공을 남긴다.

ADR-108.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from kortravelmap.infra.feature_repo import FeatureLoadResult

from kortravelmap.dagster import assets
from kortravelmap.dagster.etl import (
    AddressFindingObservationReceipt,
    DagsterFeatureLoadResult,
)
from kortravelmap.dagster.mois_chunked_load import MoisChunkedLoadOutcome, MoisLoadPlan
from kortravelmap.dagster.validation import FeatureAddressValidationSummary

_PLAN = MoisLoadPlan(
    service_slugs=("bakeries",),
    full_coverage=False,
    source_db_path=None,
    geocode_concurrency=2,
    run_budget_seconds=14_400,
)


def _outcome(*, complete: bool, full_coverage: bool) -> MoisChunkedLoadOutcome:
    result = DagsterFeatureLoadResult(
        provider="python-mois-api",
        dataset_key="bulk",
        feature_ids=(),
        load=FeatureLoadResult(bundles_total=5),
        address_validation=FeatureAddressValidationSummary(
            total=5, issue_count=0, error_count=0, warning_count=0, issues=()
        ),
        observation_receipt=AddressFindingObservationReceipt(
            authoritative_snapshot_complete=complete and full_coverage,
            source_observations=5,
            findings_observed=0,
            findings_unique=0,
            findings_upserted=0,
            finding_persistence_complete=True,
        ),
    )
    return MoisChunkedLoadOutcome(
        result=result,
        complete=complete,
        full_coverage=full_coverage,
        slugs_completed=("bakeries",) if complete else (),
        stopped_in_slug=None if complete else "bakeries",
        records_seen=5,
        records_unchanged=0,
        records_converted=5,
        chunks_committed=1,
        reverse_geocode_live_calls=0,
        reverse_geocode_cache_hits=0,
        reverse_geocode_prefetch_failures=0,
        dropped_count=0,
    )


@pytest.mark.parametrize(
    ("complete", "full_coverage", "records_success"),
    [(True, True, True), (True, False, False), (False, True, False), (False, False, False)],
)
async def test_mois_asset_delegates_and_records_success_only_for_a_full_finished_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    complete: bool,
    full_coverage: bool,
    records_success: bool,
) -> None:
    records = [object(), object()]
    geocoder = object()
    client = object()
    seen: dict[str, Any] = {}
    sync_calls: list[dict[str, Any]] = []
    outcome = _outcome(complete=complete, full_coverage=full_coverage)

    async def _resource_value(_context: object, key: str, *, default: object = None) -> object:
        return {
            "mois_dataset_key": "bulk",
            "strict_address": "drop",
            "mois_load_plan": _PLAN,
            "mois_license_records": records,
        }.get(key, default)

    async def _chunked(**kwargs: Any) -> MoisChunkedLoadOutcome:
        seen.update(kwargs)
        return outcome

    async def _record_success(_context: object, _client: object, **kwargs: Any) -> None:
        sync_calls.append(kwargs)

    monkeypatch.setattr(assets, "_resource_value", _resource_value)
    monkeypatch.setattr(assets, "_resource_object", lambda *_args, **_kwargs: client)
    monkeypatch.setattr(assets, "_reverse_geocoder", lambda *_args: geocoder)
    current_dataset = object()
    monkeypatch.setattr(assets, "_current_geo_dataset", lambda *_args: _async(current_dataset))
    monkeypatch.setattr(
        assets, "_fetched_at", lambda *_args: _async(datetime(2026, 10, 12, tzinfo=UTC))
    )
    monkeypatch.setattr(assets, "load_mois_license_records_chunked", _chunked)
    monkeypatch.setattr(assets, "_record_feature_sync_success", _record_success)

    result = await assets.run_feature_place_mois_licenses(object())  # type: ignore[arg-type]

    assert result is outcome.result
    assert seen["records"] is records
    # run 시작에 읽은 현재 geo 토큰이 MOIS 적재로 간다(ADR-109 결정 2·4).
    assert seen["current_dataset"] is current_dataset
    assert seen["plan"] is _PLAN
    assert seen["reverse_geocoder"] is geocoder
    assert seen["strict_address"] == "drop"
    assert seen["dataset_key"] == "bulk"
    if records_success:
        assert len(sync_calls) == 1
        # 이 run은 이미 적재돼 있던 행을 다시 검증하지 않는다 — 미관측 finding을 닫지 않는다.
        assert sync_calls[0]["observation_receipt"] is None
        assert sync_calls[0]["cursor_extra"]["mois_load_outcome"] == "complete"
    else:
        assert sync_calls == []


async def _async(value: Any) -> Any:
    return value

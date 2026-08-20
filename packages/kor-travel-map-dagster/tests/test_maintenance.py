"""consistency/dedup refresh Dagster job unit test."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock

import pytest
from dagster import Failure
from kortravelmap.client import (
    CacheTargetSnapshotGcDrainResult,
    DedupRefreshResult,
    IntegrityFindingSyncResult,
)
from kortravelmap.core.dedup import DedupCandidate
from kortravelmap.infra.consistency import CaseResult, ConsistencyReport
from kortravelmap.infra.dedup_refresh_repo import DedupRefreshScope
from kortravelmap.infra.dedup_repo import DedupQueueResult
from kortravelmap.infra.weather_repo import WeatherSummaryMaterializeResult

import kortravelmap.dagster.maintenance as maintenance_mod
from kortravelmap.dagster.maintenance import (
    DEFAULT_DEDUP_SCOPE_PAIRS,
    MAINTENANCE_RETRY_POLICY,
    cache_target_snapshot_gc_job,
    consistency_dedup_refresh_job,
    current_weather_summary_refresh_job,
    drain_expired_cache_target_snapshots_op,
)

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


class _Client:
    def __init__(self) -> None:
        self.pairs: list[tuple[DedupRefreshScope, DedupRefreshScope, bool]] = []
        self.siblings: list[tuple[DedupRefreshScope, bool]] = []
        self.consistency_calls: list[dict[str, Any]] = []
        self.notice_purge_calls: list[str] = []
        self.finding_purge_calls: list[str] = []
        self.snapshot_gc_calls: list[dict[str, object]] = []
        self.weather_summary_calls: list[dict[str, object]] = []

    async def materialize_current_weather_summary(
        self, **kwargs: object
    ) -> WeatherSummaryMaterializeResult:
        self.weather_summary_calls.append(kwargs)
        return WeatherSummaryMaterializeResult(
            summary_run_id=91,
            selected_at=cast(datetime, kwargs["selected_at"]),
            input_count=2,
            inserted_count=0,
            updated_count=1,
            deleted_count=0,
        )

    async def drain_expired_cache_target_snapshots(
        self, **kwargs: object
    ) -> CacheTargetSnapshotGcDrainResult:
        self.snapshot_gc_calls.append(kwargs)
        return CacheTargetSnapshotGcDrainResult(
            acquired=True,
            skipped=False,
            batches=3,
            deleted_items=2_500,
            deleted_headers=4,
            compacted_materials=6,
            remaining_items=17,
            remaining_headers=2,
            total_items=10_000,
            total_headers=20,
            unexpired_unreferenced_items=4_000,
            unexpired_unreferenced_headers=8,
            referenced_items=5_983,
            referenced_headers=10,
            observation_run_id=str(kwargs["observation_run_id"]),
            observed_at=datetime(2026, 8, 2, 1, 0, tzinfo=UTC),
            observation_referenced_items=5_983,
            observation_referenced_headers=10,
            previous_observation_run_id="previous-run",
            previous_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
            previous_referenced_items=4_983,
            previous_referenced_headers=9,
            growth_baseline_observation_run_id="previous-run",
            growth_baseline_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
            growth_baseline_referenced_items=4_983,
            growth_baseline_referenced_headers=9,
            observation_growth_baseline_eligible=True,
            observation_growth_min_interval_seconds=300,
            snapshot_table_bytes=2_100_000_000,
            snapshot_index_bytes=1_100_000_000,
            snapshot_dead_tuples=100_001,
            snapshot_vacuum_lag_seconds=7_201,
        )

    async def purge_expired_notices(self, *, retention: str = "1 year") -> int:
        self.notice_purge_calls.append(retention)
        return 7

    async def purge_resolved_integrity_findings(
        self, *, retention: str = "90 days"
    ) -> int:
        self.finding_purge_calls.append(retention)
        return 11

    async def refresh_dedup_candidates_for_scope_pair(
        self,
        left_scope: DedupRefreshScope,
        right_scope: DedupRefreshScope,
        *,
        include_auto_merge: bool = True,
    ) -> DedupRefreshResult:
        self.pairs.append((left_scope, right_scope, include_auto_merge))
        return _refresh_result("pair", left_scope, right_scope)

    async def refresh_sibling_dedup_candidates(
        self,
        scope: DedupRefreshScope,
        *,
        include_auto_merge: bool = True,
    ) -> DedupRefreshResult:
        self.siblings.append((scope, include_auto_merge))
        return _refresh_result("sibling", scope, None)

    async def run_consistency_report(
        self,
        *,
        batch_id: str | None = None,
        persist: bool = True,
        sample_limit: int = 20,
        dedup_pending_threshold: int = 1000,
    ) -> ConsistencyReport:
        self.consistency_calls.append(
            {
                "batch_id": batch_id,
                "persist": persist,
                "sample_limit": sample_limit,
                "dedup_pending_threshold": dedup_pending_threshold,
            }
        )
        return ConsistencyReport(
            batch_id="batch-unit",
            severity_max="WARN",
            cases=[
                CaseResult(
                    code="F4",
                    severity="WARN",
                    description="dedup backlog",
                    count=1,
                    sample_ids=["rk-1"],
                    metadata={
                        "pending_count": 3,
                        "threshold": dedup_pending_threshold,
                        "over_threshold": True,
                    },
                )
            ],
            summary={
                "total_violations": 1,
                "cases_evaluated": 4,
                "by_code": {"F1": 0, "F2": 0, "F3": 0, "F4": 1},
                "case_metadata": {
                    "F4": {
                        "pending_count": 3,
                        "threshold": dedup_pending_threshold,
                        "over_threshold": True,
                    }
                },
            },
        )

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        count = len(self.recorded_findings)
        return IntegrityFindingSyncResult(count, count, count)


def test_consistency_dedup_refresh_job_executes_configured_scopes() -> None:
    client = _Client()

    result = consistency_dedup_refresh_job.execute_in_process(
        run_config={
            "ops": {
                "refresh_dedup_candidates": {
                    "config": {
                        "pairs": [
                            {
                                "left": {
                                    "provider": "knps",
                                    "dataset_key": "knps_visitor_centers",
                                    "categories": ["01070100"],
                                },
                                "right": {
                                    "provider": "krheritage",
                                    "dataset_key": "krheritage_heritage_features",
                                    "limit": 50,
                                    "cursor_updated_at": "2026-06-05T10:00:00+00:00",
                                    "cursor_feature_id": "feature:cursor",
                                },
                            }
                        ],
                        "sibling_scopes": [
                            {
                                "provider": "mois",
                                "dataset_key": "mois_license_features_bulk",
                            }
                        ],
                        "include_auto_merge": False,
                        "limit": 100,
                    }
                },
                "run_consistency_check": {
                    "config": {
                        "persist": True,
                        "sample_limit": 7,
                        "dedup_pending_threshold": 2,
                    }
                },
                "purge_resolved_integrity_findings": {
                    "config": {"retention": "120 days"}
                },
            }
        },
        resources={"kor_travel_map_client": client},
    )

    assert result.success
    assert client.pairs[0][0].provider == "knps"
    assert client.pairs[0][0].categories == ("01070100",)
    assert client.pairs[0][1].limit == 50
    assert client.pairs[0][1].cursor_updated_at is not None
    assert client.pairs[0][1].cursor_feature_id == "feature:cursor"
    assert client.pairs[0][2] is False
    assert client.siblings[0][0].provider == "mois"
    assert client.consistency_calls == [
        {
            "batch_id": None,
            "persist": True,
            "sample_limit": 7,
            "dedup_pending_threshold": 2,
        }
    ]

    dedup_output = result.output_for_node("refresh_dedup_candidates")
    assert dedup_output["pair_scope_count"] == 1
    assert dedup_output["sibling_scope_count"] == 1
    assert dedup_output["queue_inserted"] == 2

    consistency_output = result.output_for_node("run_consistency_check")
    assert consistency_output["severity_max"] == "WARN"
    assert consistency_output["dedup_queue_inserted"] == 2
    assert client.finding_purge_calls == ["120 days"]
    assert result.output_for_node("purge_resolved_integrity_findings") == {
        "purged": 11,
        "retention": "120 days",
    }


def test_current_weather_summary_refresh_job_rematerializes_without_provider_write() -> None:
    client = _Client()

    result = current_weather_summary_refresh_job.execute_in_process(
        resources={"kor_travel_map_client": client},
    )

    assert result.success
    assert len(client.weather_summary_calls) == 1
    assert client.weather_summary_calls[0]["run_kind"] == "reconcile"
    assert result.output_for_node("materialize_current_weather_summary") == {
        "summary_run_id": 91,
        "selected_at": client.weather_summary_calls[0]["selected_at"].isoformat(),
        "input_count": 2,
        "inserted_count": 0,
        "updated_count": 1,
        "deleted_count": 0,
    }


def test_refresh_dedup_uses_default_scopes_when_config_empty() -> None:
    # pairs/sibling_scopes op_config 미지정 → DEFAULT_DEDUP_SCOPE_PAIRS 적용.
    client = _Client()

    result = consistency_dedup_refresh_job.execute_in_process(
        resources={"kor_travel_map_client": client},
    )

    assert result.success
    assert len(client.pairs) == len(DEFAULT_DEDUP_SCOPE_PAIRS)
    # 기본 cross-provider pair: KNPS 문화시설/사찰 ↔ 국가유산(canonical provider name).
    assert client.pairs[0][0].provider == "python-knps-api"
    assert client.pairs[0][1].provider == "python-krheritage-api"
    # 자연휴양림 ↔ MOIS 관광숙박/리조트(category 좁힘).
    assert client.pairs[1][0].provider == "python-krforest-api"
    assert client.pairs[1][0].dataset_key == "krforest_recreation_forests"
    assert client.pairs[1][1].provider == "python-mois-api"
    assert client.pairs[1][1].categories == ("03010100", "03020100", "03020200")
    # 박물관/미술관 ↔ MOIS museums_and_art_galleries(01040000).
    assert client.pairs[2][0].provider == "data.go.kr-standard"
    assert client.pairs[2][0].dataset_key == "datagokr_museums"
    assert client.pairs[2][1].provider == "python-mois-api"
    assert client.pairs[2][1].categories == ("01040000",)
    # 관광지 ↔ MOIS 관광사업체(01000000).
    assert client.pairs[3][0].dataset_key == "datagokr_tourist_attractions"
    assert client.pairs[3][1].categories == ("01000000",)
    assert client.siblings == []

    dedup_output = result.output_for_node("refresh_dedup_candidates")
    assert dedup_output["pair_scope_count"] == len(DEFAULT_DEDUP_SCOPE_PAIRS)
    assert dedup_output["sibling_scope_count"] == 0

    # notice purge op(#632)도 같은 job에서 기본 보존 기간으로 실행된다.
    assert client.notice_purge_calls == ["1 year"]
    purge_output = result.output_for_node("purge_expired_notices")
    assert purge_output == {"purged": 7, "retention": "1 year"}
    assert client.finding_purge_calls == ["90 days"]
    assert result.output_for_node("purge_resolved_integrity_findings") == {
        "purged": 11,
        "retention": "90 days",
    }


def test_consistency_dedup_refresh_ops_have_retry_policy() -> None:
    retry_by_name = {
        node_def.name: node_def.retry_policy
        for node_def in consistency_dedup_refresh_job.all_node_defs
    }

    assert retry_by_name["refresh_dedup_candidates"] == MAINTENANCE_RETRY_POLICY
    assert retry_by_name["run_consistency_check"] == MAINTENANCE_RETRY_POLICY
    assert retry_by_name["purge_expired_notices"] == MAINTENANCE_RETRY_POLICY
    assert (
        retry_by_name["purge_resolved_integrity_findings"]
        == MAINTENANCE_RETRY_POLICY
    )


def test_cache_target_snapshot_gc_job_reports_metadata_and_has_retry_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _Client()
    clock = iter([100.0, 110.0])
    monkeypatch.setattr(maintenance_mod, "monotonic", lambda: next(clock))

    result = cache_target_snapshot_gc_job.execute_in_process(
        run_config={
            "ops": {
                "drain_expired_cache_target_snapshots": {
                    "config": {
                        "max_batches": 25,
                        "max_seconds": 45,
                        "item_limit": 800,
                        "header_limit": 40,
                        "batch_statement_timeout_ms": 5_000,
                        "referenced_item_ceiling": 5_000,
                        "referenced_header_ceiling": 9,
                        "referenced_item_growth_ceiling_per_hour": 900,
                        "referenced_header_growth_ceiling_per_hour": 0,
                        "referenced_growth_min_interval_seconds": 300,
                        "observation_retention_days": 30,
                        "snapshot_table_byte_ceiling": 2_000_000_000,
                        "snapshot_index_byte_ceiling": 1_000_000_000,
                        "snapshot_dead_tuple_ceiling": 100_000,
                        "snapshot_vacuum_lag_ceiling_seconds": 7_200,
                    }
                }
            }
        },
        resources={"kor_travel_map_client": client},
    )

    assert result.success
    assert len(client.snapshot_gc_calls) == 1
    assert client.snapshot_gc_calls[0] == {
        "max_batches": 25,
        "max_seconds": 45,
        "item_limit": 800,
        "header_limit": 40,
        "batch_statement_timeout_ms": 5_000,
        "observation_run_id": result.run_id,
        "observation_retention_days": 30,
        "observation_growth_min_interval_seconds": 300,
    }
    assert result.output_for_node("drain_expired_cache_target_snapshots") == {
        "acquired": True,
        "skipped": False,
        "batches": 3,
        "deleted_items": 2_500,
        "deleted_headers": 4,
        "compacted_materials": 6,
        "remaining_items": 17,
        "remaining_headers": 2,
        "total_items": 10_000,
        "total_headers": 20,
        "unexpired_unreferenced_items": 4_000,
        "unexpired_unreferenced_headers": 8,
        "referenced_items": 5_983,
        "referenced_headers": 10,
        "backlog_observed": True,
        "backlog_alert": True,
        "capacity_item_ceiling": 20_000,
        "elapsed_seconds": 10.0,
        "deleted_items_per_hour": 900_000.0,
        "referenced_observation_available": True,
        "referenced_observation_status": "observed",
        "referenced_observation_issue": False,
        "referenced_observation_issue_reasons": [],
        "referenced_observation_run_id": result.run_id,
        "referenced_observed_at": "2026-08-02T01:00:00+00:00",
        "referenced_observation_items": 5_983,
        "referenced_observation_headers": 10,
        "previous_referenced_observation_run_id": "previous-run",
        "previous_referenced_observed_at": "2026-08-02T00:00:00+00:00",
        "previous_referenced_items": 4_983,
        "previous_referenced_headers": 9,
        "growth_baseline_observation_run_id": "previous-run",
        "growth_baseline_observed_at": "2026-08-02T00:00:00+00:00",
        "growth_baseline_referenced_items": 4_983,
        "growth_baseline_referenced_headers": 9,
        "referenced_observation_growth_baseline_eligible": True,
        "referenced_observation_elapsed_seconds": 3_600.0,
        "referenced_items_delta": 1_000,
        "referenced_headers_delta": 1,
        "referenced_growth_baseline_elapsed_seconds": 3_600.0,
        "referenced_items_growth_baseline_delta": 1_000,
        "referenced_headers_growth_baseline_delta": 1,
        "referenced_growth_rate_observed": True,
        "referenced_growth_unobserved_reason": "observed",
        "referenced_items_growth_per_hour": 1_000.0,
        "referenced_headers_growth_per_hour": 1.0,
        "referenced_item_ceiling": 5_000,
        "referenced_header_ceiling": 9,
        "referenced_item_growth_ceiling_per_hour": 900,
        "referenced_header_growth_ceiling_per_hour": 0,
        "referenced_growth_min_interval_seconds": 300,
        "referenced_observation_retention_days": 30,
        "referenced_item_ceiling_alert": True,
        "referenced_header_ceiling_alert": True,
        "referenced_retention_ceiling_alert": True,
        "referenced_item_growth_alert": True,
        "referenced_header_growth_alert": True,
        "referenced_growth_alert": True,
        "referenced_item_inventory_loss_alert": False,
        "referenced_header_inventory_loss_alert": False,
        "referenced_inventory_loss_alert": False,
        "referenced_alert": True,
        "referenced_alert_reasons": [
            "referenced_item_ceiling",
            "referenced_header_ceiling",
            "referenced_item_growth",
            "referenced_header_growth",
        ],
        "referenced_requires_attention": True,
        "snapshot_storage_observed": True,
        "snapshot_table_bytes": 2_100_000_000,
        "snapshot_index_bytes": 1_100_000_000,
        "snapshot_total_relation_bytes": 3_200_000_000,
        "snapshot_dead_tuples": 100_001,
        "snapshot_vacuum_lag_seconds": 7_201,
        "snapshot_table_byte_ceiling": 2_000_000_000,
        "snapshot_index_byte_ceiling": 1_000_000_000,
        "snapshot_dead_tuple_ceiling": 100_000,
        "snapshot_vacuum_lag_ceiling_seconds": 7_200,
        "snapshot_table_byte_alert": True,
        "snapshot_index_byte_alert": True,
        "snapshot_dead_tuple_alert": True,
        "snapshot_vacuum_lag_alert": True,
        "snapshot_storage_alert": True,
        "snapshot_storage_alert_reasons": [
            "snapshot_table_bytes",
            "snapshot_index_bytes",
            "snapshot_dead_tuples",
            "snapshot_vacuum_lag",
        ],
        "snapshot_storage_observation_issue": False,
        "snapshot_storage_observation_issue_reasons": [],
        "snapshot_storage_requires_attention": True,
    }
    retry_by_name = {
        node_def.name: node_def.retry_policy
        for node_def in cache_target_snapshot_gc_job.all_node_defs
    }
    assert (
        retry_by_name["drain_expired_cache_target_snapshots"]
        == MAINTENANCE_RETRY_POLICY
    )


def test_cache_target_snapshot_gc_job_marks_skipped_backlog_unobserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SkippedClient:
        async def drain_expired_cache_target_snapshots(
            self, **_kwargs: object
        ) -> CacheTargetSnapshotGcDrainResult:
            return CacheTargetSnapshotGcDrainResult(
                acquired=False,
                skipped=True,
                batches=0,
                deleted_items=0,
                deleted_headers=0,
                remaining_items=None,
                remaining_headers=None,
            )

    clock = iter([200.0, 201.0])
    monkeypatch.setattr(maintenance_mod, "monotonic", lambda: next(clock))
    result = cache_target_snapshot_gc_job.execute_in_process(
        resources={"kor_travel_map_client": _SkippedClient()},
    )

    assert result.success
    output = result.output_for_node("drain_expired_cache_target_snapshots")
    assert output["acquired"] is False
    assert output["skipped"] is True
    assert output["remaining_items"] == "not_observed"
    assert output["remaining_headers"] == "not_observed"
    assert output["total_items"] == "not_observed"
    assert output["total_headers"] == "not_observed"
    assert output["unexpired_unreferenced_items"] == "not_observed"
    assert output["unexpired_unreferenced_headers"] == "not_observed"
    assert output["referenced_items"] == "not_observed"
    assert output["referenced_headers"] == "not_observed"
    assert output["backlog_observed"] is False
    assert output["backlog_alert"] is False
    assert output["referenced_observation_available"] is False
    assert output["referenced_observation_status"] == "overlap_skipped"
    assert output["referenced_observation_issue"] is True
    assert output["referenced_observation_issue_reasons"] == [
        "gc_overlap_skipped"
    ]
    assert output["referenced_growth_rate_observed"] is False
    assert output["referenced_observation_run_id"] == "not_observed"
    assert output["referenced_items_growth_per_hour"] == "not_observed"
    assert output["referenced_retention_ceiling_alert"] is False
    assert output["referenced_growth_alert"] is False
    assert output["referenced_alert"] is False
    assert output["referenced_alert_reasons"] == []
    assert output["referenced_requires_attention"] is True
    assert output["snapshot_storage_observed"] is False
    assert output["snapshot_table_bytes"] == "not_observed"
    assert output["snapshot_storage_alert"] is False
    assert output["snapshot_storage_observation_issue_reasons"] == [
        "gc_overlap_skipped"
    ]
    assert output["snapshot_storage_requires_attention"] is True


@pytest.mark.asyncio
async def test_cache_target_snapshot_gc_warns_when_vacuum_is_not_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NoVacuumClient(_Client):
        async def drain_expired_cache_target_snapshots(
            self, **kwargs: object
        ) -> CacheTargetSnapshotGcDrainResult:
            result = await super().drain_expired_cache_target_snapshots(**kwargs)
            return replace(
                result,
                snapshot_table_bytes=100,
                snapshot_index_bytes=100,
                snapshot_dead_tuples=0,
                snapshot_vacuum_lag_seconds=None,
            )

    clock = iter([300.0, 301.0])
    monkeypatch.setattr(maintenance_mod, "monotonic", lambda: next(clock))
    log = Mock()
    metadata: list[dict[str, object]] = []
    context = SimpleNamespace(
        resources=SimpleNamespace(kor_travel_map_client=_NoVacuumClient()),
        op_config={},
        run_id="vacuum-not-observed-run",
        log=log,
        add_output_metadata=metadata.append,
    )

    output = await drain_expired_cache_target_snapshots_op.compute_fn.decorated_fn(
        cast(Any, context)
    )

    assert output["snapshot_storage_alert"] is False
    assert output["snapshot_storage_observation_issue_reasons"] == [
        "snapshot_vacuum_not_observed"
    ]
    assert output["snapshot_storage_requires_attention"] is True
    log.warning.assert_any_call(
        "cache-target snapshot storage 관측 품질 경고: %s",
        ["snapshot_vacuum_not_observed"],
    )
    assert metadata == [output]


def test_cache_target_snapshot_gc_first_observation_checks_only_ceiling() -> None:
    sample = CacheTargetSnapshotGcDrainResult(
        acquired=True,
        skipped=False,
        batches=1,
        deleted_items=0,
        deleted_headers=0,
        remaining_items=0,
        remaining_headers=0,
        referenced_items=101,
        referenced_headers=2,
        observation_run_id="first-run",
        observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        observation_referenced_items=101,
        observation_referenced_headers=2,
        observation_growth_baseline_eligible=True,
        observation_growth_min_interval_seconds=300,
    )

    metadata = maintenance_mod._cache_target_referenced_alert_metadata(
        sample,
        item_ceiling=100,
        header_ceiling=2,
        item_growth_ceiling_per_hour=1,
        header_growth_ceiling_per_hour=1,
        growth_min_interval_seconds=300,
        observation_retention_days=90,
    )

    assert metadata["referenced_item_ceiling_alert"] is True
    assert metadata["referenced_header_ceiling_alert"] is False
    assert metadata["referenced_growth_rate_observed"] is False
    assert metadata["referenced_growth_alert"] is False
    assert metadata["referenced_alert_reasons"] == ["referenced_item_ceiling"]


def test_cache_target_snapshot_gc_does_not_extrapolate_short_interval() -> None:
    sample = CacheTargetSnapshotGcDrainResult(
        acquired=True,
        skipped=False,
        batches=1,
        deleted_items=0,
        deleted_headers=0,
        remaining_items=0,
        remaining_headers=0,
        referenced_items=200,
        referenced_headers=3,
        observation_run_id="second-run",
        observed_at=datetime(2026, 8, 2, 0, 1, tzinfo=UTC),
        observation_referenced_items=200,
        observation_referenced_headers=3,
        growth_baseline_observation_run_id="first-run",
        growth_baseline_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        growth_baseline_referenced_items=100,
        growth_baseline_referenced_headers=2,
        previous_observation_run_id="first-run",
        previous_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        previous_referenced_items=100,
        previous_referenced_headers=2,
        observation_growth_baseline_eligible=False,
        observation_growth_min_interval_seconds=300,
    )

    metadata = maintenance_mod._cache_target_referenced_alert_metadata(
        sample,
        item_ceiling=1_000,
        header_ceiling=10,
        item_growth_ceiling_per_hour=1,
        header_growth_ceiling_per_hour=1,
        growth_min_interval_seconds=300,
        observation_retention_days=90,
    )

    assert metadata["referenced_items_delta"] == 100
    assert metadata["referenced_observation_elapsed_seconds"] == 60.0
    assert metadata["referenced_growth_rate_observed"] is False
    assert metadata["referenced_items_growth_per_hour"] == "not_observed"
    assert metadata["referenced_growth_alert"] is False
    assert metadata["referenced_growth_unobserved_reason"] == (
        "minimum_interval_not_reached"
    )


def test_cache_target_snapshot_gc_alerts_inventory_loss_without_min_interval() -> None:
    sample = CacheTargetSnapshotGcDrainResult(
        acquired=True,
        skipped=False,
        batches=1,
        deleted_items=0,
        deleted_headers=0,
        remaining_items=0,
        remaining_headers=0,
        observation_run_id="loss-run",
        observed_at=datetime(2026, 8, 2, 0, 1, tzinfo=UTC),
        observation_referenced_items=90,
        observation_referenced_headers=1,
        growth_baseline_observation_run_id="baseline-run",
        growth_baseline_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        growth_baseline_referenced_items=100,
        growth_baseline_referenced_headers=2,
        previous_observation_run_id="baseline-run",
        previous_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        previous_referenced_items=100,
        previous_referenced_headers=2,
        observation_growth_baseline_eligible=False,
        observation_growth_min_interval_seconds=300,
    )

    metadata = maintenance_mod._cache_target_referenced_alert_metadata(
        sample,
        item_ceiling=1_000,
        header_ceiling=10,
        item_growth_ceiling_per_hour=1_000,
        header_growth_ceiling_per_hour=10,
        growth_min_interval_seconds=300,
        observation_retention_days=90,
    )

    assert metadata["referenced_growth_rate_observed"] is False
    assert metadata["referenced_item_inventory_loss_alert"] is True
    assert metadata["referenced_header_inventory_loss_alert"] is True
    assert metadata["referenced_inventory_loss_alert"] is True
    assert metadata["referenced_alert_reasons"] == [
        "referenced_item_inventory_loss",
        "referenced_header_inventory_loss",
    ]


def test_cache_target_snapshot_gc_marks_unavailable_and_nonforward_separately() -> None:
    unavailable = CacheTargetSnapshotGcDrainResult(
        acquired=True,
        skipped=False,
        batches=1,
        deleted_items=0,
        deleted_headers=0,
        remaining_items=0,
        remaining_headers=0,
    )
    unavailable_metadata = maintenance_mod._cache_target_referenced_alert_metadata(
        unavailable,
        item_ceiling=1_000,
        header_ceiling=10,
        item_growth_ceiling_per_hour=1_000,
        header_growth_ceiling_per_hour=10,
        growth_min_interval_seconds=300,
        observation_retention_days=90,
    )
    assert unavailable_metadata["referenced_observation_status"] == "unavailable"
    assert unavailable_metadata["referenced_observation_issue_reasons"] == [
        "referenced_observation_unavailable"
    ]
    assert unavailable_metadata["referenced_alert"] is False
    assert unavailable_metadata["referenced_requires_attention"] is True

    nonforward = CacheTargetSnapshotGcDrainResult(
        acquired=True,
        skipped=False,
        batches=1,
        deleted_items=0,
        deleted_headers=0,
        remaining_items=0,
        remaining_headers=0,
        observation_run_id="clock-run",
        observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        observation_referenced_items=10,
        observation_referenced_headers=1,
        growth_baseline_observation_run_id="baseline-run",
        growth_baseline_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        growth_baseline_referenced_items=10,
        growth_baseline_referenced_headers=1,
        previous_observation_run_id="baseline-run",
        previous_observed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        previous_referenced_items=10,
        previous_referenced_headers=1,
        observation_growth_baseline_eligible=False,
        observation_growth_min_interval_seconds=300,
    )
    nonforward_metadata = maintenance_mod._cache_target_referenced_alert_metadata(
        nonforward,
        item_ceiling=1_000,
        header_ceiling=10,
        item_growth_ceiling_per_hour=1_000,
        header_growth_ceiling_per_hour=10,
        growth_min_interval_seconds=300,
        observation_retention_days=90,
    )
    assert nonforward_metadata["referenced_observation_status"] == (
        "non_forward_database_clock"
    )
    assert nonforward_metadata["referenced_observation_issue_reasons"] == [
        "non_forward_database_clock"
    ]
    assert nonforward_metadata["referenced_growth_unobserved_reason"] == (
        "non_forward_database_clock"
    )


@pytest.mark.parametrize(
    ("value", "minimum", "maximum"),
    [
        (0, 1, None),
        (10_001, 1, 10_000),
        (-1, 0, None),
        (3_651, 1, 3_650),
    ],
)
def test_cache_target_snapshot_gc_rejects_invalid_config(
    value: int,
    minimum: int,
    maximum: int | None,
) -> None:
    with pytest.raises(Failure, match="test_value config") as exc_info:
        maintenance_mod._bounded_int_config(
            value,
            name="test_value",
            default=1,
            minimum=minimum,
            maximum=maximum,
        )
    assert exc_info.value.allow_retries is False


def _refresh_result(
    mode: str,
    left_scope: DedupRefreshScope,
    right_scope: DedupRefreshScope | None,
) -> DedupRefreshResult:
    return DedupRefreshResult(
        mode=mode,
        left_scope=left_scope,
        right_scope=right_scope,
        left_count=1,
        right_count=1 if right_scope is not None else 0,
        candidates=[
            DedupCandidate(
                feature_id_a=f"{mode}-a",
                feature_id_b=f"{mode}-b",
                name_a="불국사",
                name_b="불국사",
                score=0.9,
                decision="auto_merge",
                name_score=1.0,
                spatial_score=1.0,
                category_score=1.0,
            )
        ],
        queue=DedupQueueResult(candidates_total=1, inserted=1),
    )

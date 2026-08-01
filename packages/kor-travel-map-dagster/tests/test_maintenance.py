"""consistency/dedup refresh Dagster job unit test."""

from __future__ import annotations

from typing import Any

import pytest
from kortravelmap.client import (
    CacheTargetSnapshotGcDrainResult,
    DedupRefreshResult,
    IntegrityFindingSyncResult,
)
from kortravelmap.core.dedup import DedupCandidate
from kortravelmap.infra.consistency import CaseResult, ConsistencyReport
from kortravelmap.infra.dedup_refresh_repo import DedupRefreshScope
from kortravelmap.infra.dedup_repo import DedupQueueResult

import kortravelmap.dagster.maintenance as maintenance_mod
from kortravelmap.dagster.maintenance import (
    DEFAULT_DEDUP_SCOPE_PAIRS,
    MAINTENANCE_RETRY_POLICY,
    cache_target_snapshot_gc_job,
    consistency_dedup_refresh_job,
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
            remaining_items=17,
            remaining_headers=2,
            total_items=10_000,
            total_headers=20,
            unexpired_unreferenced_items=4_000,
            unexpired_unreferenced_headers=8,
            referenced_items=5_983,
            referenced_headers=10,
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
                    }
                }
            }
        },
        resources={"kor_travel_map_client": client},
    )

    assert result.success
    assert client.snapshot_gc_calls == [
        {
            "max_batches": 25,
            "max_seconds": 45,
            "item_limit": 800,
            "header_limit": 40,
            "batch_statement_timeout_ms": 5_000,
        }
    ]
    assert result.output_for_node("drain_expired_cache_target_snapshots") == {
        "acquired": True,
        "skipped": False,
        "batches": 3,
        "deleted_items": 2_500,
        "deleted_headers": 4,
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

"""consistency/dedup refresh Dagster job unit test."""

from __future__ import annotations

from typing import Any

import pytest
from krtour.map.client import DedupRefreshResult
from krtour.map.core.dedup import DedupCandidate
from krtour.map.infra.consistency import CaseResult, ConsistencyReport
from krtour.map.infra.dedup_refresh_repo import DedupRefreshScope
from krtour.map.infra.dedup_repo import DedupQueueResult

from krtour.map_dagster.maintenance import (
    MAINTENANCE_RETRY_POLICY,
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
            }
        },
        resources={"krtour_map_client": client},
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


def test_consistency_dedup_refresh_ops_have_retry_policy() -> None:
    retry_by_name = {
        node_def.name: node_def.retry_policy
        for node_def in consistency_dedup_refresh_job.all_node_defs
    }

    assert retry_by_name["refresh_dedup_candidates"] == MAINTENANCE_RETRY_POLICY
    assert retry_by_name["run_consistency_check"] == MAINTENANCE_RETRY_POLICY


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

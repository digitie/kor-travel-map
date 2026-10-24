"""전용 ephemeral PG에서 native DML·seal·계측 artifact까지 실제 실행한다."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from kortravelmap.infra.application_schema_head import application_schema_head
from scripts._scoped_write_baseline_pg import run_baseline, write_report
from scripts.scoped_write_baseline import load_fixture

pytestmark = [pytest.mark.integration, pytest.mark.timeout(240)]


async def test_isolated_three_run_cold_warm_baseline(tmp_path) -> None:
    fixture = load_fixture()
    # session의 공용 pg_container를 재시작하지 않는다. runner가 별도의 소유 container를 만든다.
    report = await run_baseline(fixture)
    assert report["schema_head"] == application_schema_head()
    assert report["three_repetition_baseline"] is True
    assert report["scope_complete"] is False
    assert report["global_fence_retained"] is True
    assert report["runtime_acl_boundary_verified"] is True
    assert report["operational_access"] is False
    assert len(report["trials"]) == 6
    assert {trial["case"] for trial in report["trials"]} == {"independent", "shared"}
    for trial in report["trials"]:
        binding = trial["restart_binding"]
        assert binding["source"] == "owned-testcontainer-public-mapping"
        assert binding["readiness_verified"] is True
        assert all(0 < binding[key] <= 65535 for key in ("previous_port", "current_port"))
        cold, warm = trial["cold"], trial["warm"]
        assert cold["state"]["effective_sha256"] == warm["state"]["effective_sha256"]
        assert cold["state"]["alias_sha256"] == warm["state"]["alias_sha256"]
        expected_features = len(fixture.points) * (2 if trial["case"] == "independent" else 1)
        for phase in (cold, warm):
            assert phase["state"]["feature_count"] == expected_features
            assert phase["state"]["source_count"] == 2 * len(fixture.points)
            assert phase["state"]["alias_count"] == 2 * len(fixture.points)
            assert phase["state"]["alias_sha256"]
            assert phase["dml_overlap_seconds"] == 0
            assert phase["worker_cpu_core_seconds"] >= 0
            assert phase["pg_cpu_core_seconds"] >= 0
            assert phase["worker_rss_sample_peak_bytes"] > 0
            assert phase["wal_bytes"] >= 0
            assert len({writer["backend_pid"] for writer in phase["writers"]}) == 2
            assert all(
                writer["session_login"] == writer["effective_login"] == "ktm_feature_service"
                for writer in phase["writers"]
            )
            assert all(
                writer["seal_member_count"] == len(fixture.points) for writer in phase["writers"]
            )
            assert all(writer["seal_sha256"] for writer in phase["writers"])
        assert all(
            writer["load"]["source_records_inserted"] == len(fixture.points)
            for writer in cold["writers"]
        )
        assert all(writer["load"]["source_records_inserted"] == 0 for writer in warm["writers"])
        assert all(writer["load"]["features_updated"] == 0 for writer in warm["writers"])
    target = Path(os.environ.get("KTM_CWRITE_BASELINE_REPORT", str(tmp_path / "baseline.json")))
    write_report(target, report)

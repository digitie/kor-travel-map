"""``test_cli_main`` — kor-travel-map CLI 파서 + status 포맷 (순수).

DB 없이 argparse 구성과 ``_format_status`` 출력 포맷을 검증한다.
"""

from __future__ import annotations

import pytest

from kortravelmap.cli.main import (
    _EXIT_LOCK_SKIPPED,
    _format_bulk_result,
    _format_closed_result,
    _format_incremental_result,
    _format_merge_outcome,
    _format_status,
    build_parser,
)
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.infra.jobs_repo import ImportJob
from kortravelmap.infra.merge_repo import MergeOutcome
from kortravelmap.infra.status_repo import StatusCounts
from kortravelmap.infra.sync_state_repo import SyncState
from kortravelmap.mois import (
    MoisBulkJobResult,
    MoisBulkSyncResult,
    MoisClosedJobResult,
    MoisIncrementalJobResult,
)


def test_parser_requires_command() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])  # subcommand 필수


def test_parser_status_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"
    assert hasattr(args, "func")


def test_parser_consistency_report_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["consistency-report"])

    assert args.command == "consistency-report"
    assert args.batch_id is None
    assert args.persist is False
    assert args.format == "markdown"
    assert args.output is None
    assert args.sample_limit == 20
    assert args.dedup_pending_threshold == 1000
    assert args.provider_last_success_sla_seconds == 86400
    assert args.dedup_score_regression_warn_points == 10.0
    assert args.known_file_objects is None
    assert args.fail_on_error is False
    assert hasattr(args, "func")


def test_parser_consistency_report_options() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "consistency-report",
            "--batch-id",
            "batch-1",
            "--persist",
            "--format",
            "json",
            "--output",
            "docs/reports/r.md",
            "--sample-limit",
            "5",
            "--dedup-pending-threshold",
            "10",
            "--provider-last-success-sla-seconds",
            "3600",
            "--dedup-score-regression-warn-points",
            "7.5",
            "--known-file-objects",
            "objects.jsonl",
            "--fail-on-error",
        ]
    )

    assert args.batch_id == "batch-1"
    assert args.persist is True
    assert args.format == "json"
    assert args.output == "docs/reports/r.md"
    assert args.sample_limit == 5
    assert args.dedup_pending_threshold == 10
    assert args.provider_last_success_sla_seconds == 3600
    assert args.dedup_score_regression_warn_points == 7.5
    assert args.known_file_objects == "objects.jsonl"
    assert args.fail_on_error is True


def test_parser_dsn_option() -> None:
    parser = build_parser()
    args = parser.parse_args(["--dsn", "postgresql+asyncpg://x/y", "status"])
    assert args.dsn == "postgresql+asyncpg://x/y"


def test_format_status_full() -> None:
    counts = StatusCounts(
        features_total=10,
        features_active=8,
        features_inactive=2,
        features_by_kind={"place": 7, "event": 1},
        source_records_by_provider={"python-mois-api": 8},
        import_jobs_by_status={"done": 3, "running": 1},
        dedup_queue_by_status={"pending": 5},
    )
    out = _format_status(counts)
    assert "total=10 active=8 inactive=2" in out
    assert "place=7" in out
    assert "event=1" in out
    assert "python-mois-api=8" in out
    assert "done=3" in out
    assert "running=1" in out
    assert "pending=5" in out
    # 검토 완료 후보 없음 → FP율 미산출 라인.
    assert "dedup FP(운영): 검토 완료 후보 없음" in out


def test_format_status_dedup_fp_with_resolved() -> None:
    counts = StatusCounts(
        dedup_queue_by_status={"merged": 8, "rejected": 2, "pending": 3},
    )
    out = _format_status(counts)
    assert "resolved=10" in out
    assert "confirmed=8" in out
    assert "rejected=2" in out
    assert "precision=0.800" in out
    assert "fp_rate=0.200" in out


def test_format_status_empty() -> None:
    out = _format_status(StatusCounts())
    # 빈 상태에서도 features 줄은 항상 출력.
    assert "total=0 active=0 inactive=0" in out
    # 비어있는 섹션은 생략.
    assert "by_provider" not in out
    assert "by_state" not in out
    # dedup 큐 자체가 비면 FP 라인도 없음.
    assert "dedup FP" not in out


# ── import mois 서브명령 ────────────────────────────────────────────────


def test_parser_import_mois_minimal() -> None:
    parser = build_parser()
    args = parser.parse_args(["import", "mois", "snap.ndjson"])
    assert args.command == "import"
    assert args.provider == "mois"
    assert args.records_file == "snap.ndjson"
    # 기본값 — dataset_key는 None(모드별 핸들러 해석), 모드 bulk.
    assert args.dataset_key is None
    assert args.mode == "bulk"
    assert args.cursor is None
    assert args.sync_scope == "default"
    assert args.geocoder_url is None
    assert hasattr(args, "func")


def test_parser_import_mois_incremental() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "import",
            "mois",
            "snap.ndjson",
            "--mode",
            "incremental",
            "--cursor",
            "2026-06-01",
            "--sync-scope",
            "nightly",
        ]
    )
    assert args.mode == "incremental"
    assert args.cursor == "2026-06-01"
    assert args.sync_scope == "nightly"


def test_format_incremental_result_done() -> None:
    out = _format_incremental_result(
        MoisIncrementalJobResult(
            acquired=True,
            job=ImportJob(
                job_id="job-9",
                kind="mois_license_incremental_update",
                payload={},
                status="done",
                progress=100,
                current_stage=None,
                source_checksum=None,
                error_message=None,
            ),
            load=FeatureLoadResult(
                bundles_total=3,
                features_inserted=2,
                features_updated=1,
                source_records_inserted=3,
                source_links_inserted=3,
                source_links_updated=0,
            ),
            sync_state=SyncState(
                provider="python-mois-api",
                dataset_key="mois_license_features_history",
                sync_scope="default",
                status="active",
                cursor={"last_modified_date": "2026-06-01"},
                last_success_at=None,
                last_failure_at=None,
                consecutive_failures=0,
                next_run_after=None,
            ),
        )
    )
    assert "incremental): done (job_id=job-9)" in out
    assert "inserted=2 updated=1" in out
    assert "2026-06-01" in out


def test_format_incremental_result_skipped() -> None:
    out = _format_incremental_result(MoisIncrementalJobResult(acquired=False))
    assert "skipped" in out


def test_parser_import_mois_closed() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["import", "mois", "closed.ndjson", "--mode", "closed", "--cursor", "2026-06-03"]
    )
    assert args.mode == "closed"
    assert args.cursor == "2026-06-03"


def test_format_closed_result_done() -> None:
    out = _format_closed_result(
        MoisClosedJobResult(
            acquired=True,
            job=ImportJob(
                job_id="job-c",
                kind="mois_license_closed_update",
                payload={},
                status="done",
                progress=100,
                current_stage=None,
                source_checksum=None,
                error_message=None,
            ),
            deactivated=3,
            sync_state=SyncState(
                provider="python-mois-api",
                dataset_key="mois_license_features_closed",
                sync_scope="default",
                status="active",
                cursor={"last_modified_date": "2026-06-03"},
                last_success_at=None,
                last_failure_at=None,
                consecutive_failures=0,
                next_run_after=None,
            ),
        )
    )
    assert "closed): done (job_id=job-c)" in out
    assert "deactivated (inactive 전환): 3" in out
    assert "2026-06-03" in out


def test_format_closed_result_skipped() -> None:
    out = _format_closed_result(MoisClosedJobResult(acquired=False))
    assert "skipped" in out


def test_parser_import_mois_options() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "import",
            "mois",
            "snap.ndjson",
            "--dataset-key",
            "mois_license_features_history",
            "--batch-size",
            "100",
            "--geocoder-url",
            "http://127.0.0.1:12201",
            "--source-checksum",
            "abc123",
        ]
    )
    assert args.dataset_key == "mois_license_features_history"
    assert args.batch_size == 100
    assert args.geocoder_url == "http://127.0.0.1:12201"
    assert args.source_checksum == "abc123"


def test_parser_import_requires_provider() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["import"])  # provider 서브명령 필수


def test_parser_import_requires_records_file() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["import", "mois"])  # records_file 필수


def _job_result(*, acquired: bool) -> MoisBulkJobResult:
    if not acquired:
        return MoisBulkJobResult(acquired=False)
    job = ImportJob(
        job_id="job-1",
        kind="mois_license_full_update",
        payload={"dataset_key": "mois_license_features_bulk"},
        status="done",
        progress=100,
        current_stage=None,
        source_checksum=None,
        error_message=None,
    )
    sync = MoisBulkSyncResult(
        load=FeatureLoadResult(
            bundles_total=5,
            features_inserted=4,
            features_updated=1,
            source_records_inserted=5,
            source_links_inserted=5,
            source_links_updated=0,
        ),
        deactivated=2,
    )
    return MoisBulkJobResult(acquired=True, job=job, sync=sync)


def test_format_bulk_result_done() -> None:
    out = _format_bulk_result(_job_result(acquired=True))
    assert "done (job_id=job-1)" in out
    assert "inserted=4 updated=1" in out
    assert "source_records: inserted=5" in out
    assert "deactivated (snapshot prune): 2" in out


def test_format_bulk_result_skipped() -> None:
    out = _format_bulk_result(_job_result(acquired=False))
    assert "skipped" in out
    assert _EXIT_LOCK_SKIPPED == 3


# ── dedup-merge 서브명령 ─────────────────────────────────────────────────


def test_parser_dedup_merge_minimal() -> None:
    parser = build_parser()
    args = parser.parse_args(["dedup-merge", "rk-123"])
    assert args.command == "dedup-merge"
    assert args.review_id == "rk-123"
    assert args.merged_by is None
    assert args.reason is None
    assert hasattr(args, "func")


def test_parser_dedup_merge_options() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["dedup-merge", "rk-9", "--merged-by", "op-1", "--reason", "dup"]
    )
    assert args.merged_by == "op-1"
    assert args.reason == "dup"


def test_parser_dedup_merge_requires_review_id() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["dedup-merge"])  # review_id 필수


def test_format_merge_outcome() -> None:
    out = _format_merge_outcome(
        MergeOutcome(
            master_feature_id="f_m",
            loser_feature_id="f_l",
            source_links_moved=2,
            source_links_dropped=1,
            merge_id="mid-1",
            queue_updated=True,
        )
    )
    assert "done (merge_id=mid-1)" in out
    assert "master: f_m" in out
    assert "loser:  f_l (soft-deleted)" in out
    assert "moved=2 dropped=1" in out
    assert "queue: merged" in out

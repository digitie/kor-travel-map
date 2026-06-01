"""``test_cli_main`` — krtour-map CLI 파서 + status 포맷 (순수).

DB 없이 argparse 구성과 ``_format_status`` 출력 포맷을 검증한다.
"""

from __future__ import annotations

import pytest

from krtour.map.cli.main import (
    _EXIT_LOCK_SKIPPED,
    _format_bulk_result,
    _format_merge_outcome,
    _format_status,
    build_parser,
)
from krtour.map.infra.feature_repo import FeatureLoadResult
from krtour.map.infra.jobs_repo import ImportJob
from krtour.map.infra.merge_repo import MergeOutcome
from krtour.map.infra.status_repo import StatusCounts
from krtour.map.mois import MoisBulkJobResult, MoisBulkSyncResult


def test_parser_requires_command() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])  # subcommand 필수


def test_parser_status_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["status"])
    assert args.command == "status"
    assert hasattr(args, "func")


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
        import_jobs_by_state={"done": 3, "running": 1},
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


def test_format_status_empty() -> None:
    out = _format_status(StatusCounts())
    # 빈 상태에서도 features 줄은 항상 출력.
    assert "total=0 active=0 inactive=0" in out
    # 비어있는 섹션은 생략.
    assert "by_provider" not in out
    assert "by_state" not in out


# ── import mois 서브명령 ────────────────────────────────────────────────


def test_parser_import_mois_minimal() -> None:
    parser = build_parser()
    args = parser.parse_args(["import", "mois", "snap.ndjson"])
    assert args.command == "import"
    assert args.provider == "mois"
    assert args.records_file == "snap.ndjson"
    # 기본값
    assert args.dataset_key == "mois_license_features_bulk"
    assert args.geocoder_url is None
    assert hasattr(args, "func")


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
            "http://127.0.0.1:8888",
            "--source-checksum",
            "abc123",
        ]
    )
    assert args.dataset_key == "mois_license_features_history"
    assert args.batch_size == 100
    assert args.geocoder_url == "http://127.0.0.1:8888"
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
        state="done",
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
    assert args.review_key == "rk-123"
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


def test_parser_dedup_merge_requires_review_key() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["dedup-merge"])  # review_key 필수


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

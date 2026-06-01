"""``test_cli_main`` — krtour-map CLI 파서 + status 포맷 (순수).

DB 없이 argparse 구성과 ``_format_status`` 출력 포맷을 검증한다.
"""

from __future__ import annotations

import pytest

from krtour.map.cli.main import _format_status, build_parser
from krtour.map.infra.status_repo import StatusCounts


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

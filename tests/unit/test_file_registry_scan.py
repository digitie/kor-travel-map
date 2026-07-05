"""``file_registry_scan`` 순수/파일시스템 헬퍼 단위 테스트 — DB 없는 경로만.

async scan_*/backfill 은 session(testcontainers)을 필요로 하므로 integration에서 검증.
여기서는 설정 파서·stat·열거·요약 dataclass만 좁게 커버한다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kortravelmap.infra.file_registry_scan import (
    ScanLocationResult,
    _enumerate_extra_root,
    _is_e2e_backup,
    _stat_mois_source,
    _stat_temp_file,
    parse_extra_roots,
)

pytestmark = pytest.mark.unit


def test_scan_location_result_as_dict_omits_empty_details() -> None:
    result = ScanLocationResult(location="backup_root", scanned=5, registered=2)
    payload = result.as_dict()
    assert payload == {
        "location": "backup_root",
        "scanned": 5,
        "registered": 2,
        "orphaned": 0,
        "missing": 0,
    }
    assert "details" not in payload


def test_scan_location_result_as_dict_includes_details_when_present() -> None:
    result = ScanLocationResult(location="s3", details={"truncated": True})
    assert result.as_dict()["details"] == {"truncated": True}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, []),
        ("", []),
        ("archive=/srv/archive", [("archive", Path("/srv/archive"))]),
        (
            "a=/x,b=/y",
            [("a", Path("/x")), ("b", Path("/y"))],
        ),
        # 공백 trim + 빈 항목 skip.
        (" a = /x , , b=/y ", [("a", Path("/x")), ("b", Path("/y"))]),
    ],
)
def test_parse_extra_roots_valid(raw: str | None, expected: list[tuple[str, Path]]) -> None:
    assert parse_extra_roots(raw) == expected


@pytest.mark.parametrize("raw", ["nodelim", "=/only-path", "onlylogical="])
def test_parse_extra_roots_skips_malformed(raw: str) -> None:
    # logical 또는 path 한쪽이라도 비면 항목을 버린다(전체 실패 대신 skip).
    assert parse_extra_roots(raw) == []


def test_is_e2e_backup_by_mode() -> None:
    artifact = SimpleNamespace(mode="n150-live-e2e-backup-runner", backup_id="20260704")
    assert _is_e2e_backup(artifact) is True


def test_is_e2e_backup_by_prefix() -> None:
    artifact = SimpleNamespace(mode=None, backup_id="e2e-20260704")
    assert _is_e2e_backup(artifact) is True


def test_is_e2e_backup_false_for_regular() -> None:
    artifact = SimpleNamespace(mode="manual", backup_id="20260704-full")
    assert _is_e2e_backup(artifact) is False


def test_stat_temp_file_returns_size_and_mtime(tmp_path: Path) -> None:
    f = tmp_path / "swap.env"
    f.write_bytes(b"KEY=value\n")
    stat = _stat_temp_file(f)
    assert stat is not None
    size, mtime = stat
    assert size == len(b"KEY=value\n")
    assert mtime.tzinfo is not None


def test_stat_temp_file_none_for_missing_or_dir(tmp_path: Path) -> None:
    assert _stat_temp_file(tmp_path / "nope.env") is None
    # 디렉터리는 파일이 아니므로 None.
    assert _stat_temp_file(tmp_path) is None


def test_stat_mois_source_collects_existing_sidecars(tmp_path: Path) -> None:
    db = tmp_path / "mois.db"
    db.write_bytes(b"sqlite")
    (tmp_path / "mois.db-wal").write_bytes(b"w")
    (tmp_path / "mois.db.lock").write_bytes(b"l")
    result = _stat_mois_source(str(db))
    assert result is not None
    name, size, sidecars = result
    assert name == "mois.db"
    assert size == len(b"sqlite")
    # 존재하는 sidecar만, suffix 정의 순서대로.
    assert sidecars == ["mois.db-wal", "mois.db.lock"]


def test_stat_mois_source_none_when_absent(tmp_path: Path) -> None:
    assert _stat_mois_source(str(tmp_path / "absent.db")) is None


def test_enumerate_extra_root_lists_sorted_entries(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_bytes(b"12")
    (tmp_path / "a.txt").write_bytes(b"1")
    (tmp_path / "sub").mkdir()
    entries, truncated = _enumerate_extra_root(tmp_path, max_entries=100)
    assert truncated is False
    names = [e.name for e in entries]
    assert names == ["a.txt", "b.txt", "sub"]
    by_name = {e.name: e for e in entries}
    assert by_name["a.txt"].is_dir is False
    assert by_name["a.txt"].size == 1
    # 디렉터리는 size None.
    assert by_name["sub"].is_dir is True
    assert by_name["sub"].size is None


def test_enumerate_extra_root_truncates(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"f{i}.txt").write_bytes(b"x")
    entries, truncated = _enumerate_extra_root(tmp_path, max_entries=2)
    assert len(entries) == 2
    assert truncated is True


def test_enumerate_extra_root_empty_for_non_dir(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert _enumerate_extra_root(missing, max_entries=10) == ([], False)

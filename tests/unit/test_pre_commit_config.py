"""pre-commit hook 설정 회귀 테스트."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_journal_module() -> ModuleType:
    module_path = ROOT / "scripts" / "check_journal_update.py"
    spec = importlib.util.spec_from_file_location("check_journal_update", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_pre_commit_config_registers_sprint5_hooks() -> None:
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = config["repos"][0]["hooks"]
    hook_ids = {hook["id"] for hook in hooks}

    assert "kor-travel-map-journal-required" in hook_ids
    assert "kor-travel-map-ruff-format-check" in hook_ids
    assert "kor-travel-map-mypy-strict" in hook_ids
    assert "kor-travel-map-lint-imports" in hook_ids

    journal_hook = next(hook for hook in hooks if hook["id"] == "kor-travel-map-journal-required")
    assert journal_hook["always_run"] is True
    assert journal_hook["pass_filenames"] is False


@pytest.mark.unit
def test_pre_commit_runner_uses_required_static_gates() -> None:
    runner = (ROOT / "scripts" / "run-precommit-check.sh").read_text(encoding="utf-8")

    assert "ruff format --check" in runner
    assert "mypy --strict -p kortravelmap" in runner
    assert "mypy --strict -p kortravelmap.dagster" in runner
    assert "lint_imports_command" in runner


@pytest.mark.unit
def test_journal_hook_requires_journal_for_source_or_test_changes() -> None:
    module = _load_journal_module()
    # 실제 staged diff 대신 주입 — journal이 스테이징돼 있고 실제로 줄이 추가된 상황.
    added = lambda path: 3  # noqa: E731

    assert module.requires_journal_update(["src/kortravelmap/dto.py"], added_lines=added)
    assert module.requires_journal_update(["tests/unit/test_dto.py"], added_lines=added)
    assert module.requires_journal_update(
        ["packages/kor-travel-map-dagster/src/kortravelmap/x.py"], added_lines=added
    )
    assert not module.requires_journal_update(
        ["src/kortravelmap/dto.py", "docs/journal.md"], added_lines=added
    )
    assert not module.requires_journal_update(
        ["docs/tasks.md", "README.md"], added_lines=added
    )


def test_journal_hook_rejects_zero_added_lines_and_stale_month_shards() -> None:
    """이름만 스테이징(추가 0줄)이나 과거 달 shard 편집은 기록이 아니다(R2-S10)."""
    import datetime

    module = _load_journal_module()
    none_added = lambda path: 0  # noqa: E731
    some_added = lambda path: 5  # noqa: E731
    month = datetime.date.today().strftime("%Y-%m")

    # journal이 스테이징돼 있어도 추가 줄이 0이면 기록이 아니다.
    assert module.requires_journal_update(
        ["src/kortravelmap/dto.py", "docs/journal.md"], added_lines=none_added
    )
    # 당월 shard 추가 기록은 인정.
    assert not module.requires_journal_update(
        ["src/kortravelmap/dto.py", f"docs/archive/journal-{month}a.md"],
        added_lines=some_added,
    )
    # 과거 달 shard는 인정하지 않는다.
    assert module.requires_journal_update(
        ["src/kortravelmap/dto.py", "docs/archive/journal-2026-05a.md"],
        added_lines=some_added,
    )

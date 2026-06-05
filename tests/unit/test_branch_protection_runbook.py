"""branch protection runbook 회귀 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_branch_protection_runbook_tracks_required_checks_and_deferred_checks() -> None:
    runbook = (ROOT / "docs" / "runbooks" / "branch-protection.md").read_text(encoding="utf-8")

    assert "Require a pull request before merging" in runbook
    assert "pytest (Python 3.11)" in runbook
    assert "pytest (Python 3.12)" in runbook
    assert "pytest (Python 3.13)" in runbook
    assert "lint" in runbook
    assert "openapi-drift" in runbook
    assert "type-check + next build (Node 20)" in runbook
    assert "path filter" in runbook
    assert "T-203" in runbook
    assert "Do not allow force pushes" in runbook

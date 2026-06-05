"""Sprint 5 CI workflow 구조 회귀 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


@pytest.mark.unit
def test_ci_workflow_splits_unit_integration_and_fixture_replay_jobs() -> None:
    workflow = _read(".github/workflows/ci.yml")

    assert "name: pytest (Python ${{ matrix.python-version }})" in workflow
    assert "pytest tests/unit tests/lint -q" in workflow
    assert "name: pytest integration (PostGIS)" in workflow
    assert "pytest tests/integration -q --no-cov" in workflow
    assert "name: pytest fixture replay" in workflow
    assert "[ -d tests/fixtures ]" in workflow
    assert "pytest tests/fixtures -q --no-cov" in workflow


@pytest.mark.unit
def test_openapi_and_frontend_workflows_create_checks_for_every_pr() -> None:
    openapi = _read(".github/workflows/openapi.yml")
    frontend = _read(".github/workflows/frontend.yml")

    assert "paths:" not in openapi
    assert "paths:" not in frontend
    assert "openapi-drift:" in openapi
    assert "name: type-check + next build (Node 20)" in frontend


@pytest.mark.unit
def test_branch_protection_runbook_tracks_t203_required_checks() -> None:
    runbook = _read("docs/runbooks/branch-protection.md")

    for check_name in [
        "lint",
        "pytest (Python 3.11)",
        "pytest (Python 3.12)",
        "pytest (Python 3.13)",
        "pytest integration (PostGIS)",
        "pytest fixture replay",
        "openapi-drift",
        "type-check + next build (Node 20)",
    ]:
        assert check_name in runbook

    assert "path filter를 제거" in runbook

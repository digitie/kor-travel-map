"""Sprint 5 CI workflow 구조 회귀 테스트."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _steps_by_name(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        step["name"]: step
        for step in job["steps"]
        if isinstance(step, dict) and "name" in step
    }


@pytest.mark.unit
def test_ci_workflow_splits_unit_integration_and_fixture_replay_jobs() -> None:
    workflow = yaml.safe_load(_read(".github/workflows/ci.yml"))
    jobs = workflow["jobs"]

    unit = jobs["unit"]
    assert unit["name"] == "pytest (Python ${{ matrix.python-version }})"
    assert unit["strategy"]["matrix"]["python-version"] == ["3.11", "3.12", "3.13"]
    unit_steps = _steps_by_name(unit)
    main_test = unit_steps["Run unit + lint tests"]["run"]
    assert "pytest tests/unit tests/lint -q" in main_test
    assert "--cov=src/kortravelmap" in main_test
    assert "--cov-report=xml" in main_test
    assert "--cov-fail-under=0" in main_test

    api_test = unit_steps["Run kor-travel-map-api unit tests"]
    assert api_test["env"]["COVERAGE_FILE"] == ".coverage.api"
    assert "--cov=packages/kor-travel-map-api/src/kortravelmap/api" in api_test["run"]
    assert "--cov-fail-under=70" in api_test["run"]
    dagster_test = unit_steps["Run kor-travel-map-dagster unit tests"]
    assert dagster_test["env"]["COVERAGE_FILE"] == ".coverage.dagster"
    assert (
        "--cov=packages/kor-travel-map-dagster/src/kortravelmap/dagster"
        in dagster_test["run"]
    )
    assert "--cov-fail-under=80" in dagster_test["run"]

    preserve = unit_steps["Preserve unit coverage data (latest Python only)"]
    assert preserve["if"] == "matrix.python-version == '3.13'"
    assert preserve["run"] == "mv .coverage coverage-unit"
    upload = unit_steps["Upload unit coverage data (latest Python only)"]
    assert upload["if"] == "matrix.python-version == '3.13'"
    assert upload["with"]["name"] == "coverage-unit-data"
    assert upload["with"]["path"] == "coverage-unit"

    integration = jobs["integration"]
    assert integration["name"] == "pytest integration (PostGIS)"
    assert integration["needs"] == "unit"
    integration_steps = _steps_by_name(integration)
    download = integration_steps["Download unit coverage data"]
    assert download["with"]["name"] == upload["with"]["name"]
    assert integration_steps["Restore unit coverage data"]["run"] == (
        "mv coverage-unit .coverage"
    )
    integration_test = integration_steps[
        "Run integration tests (testcontainers PostGIS via Docker)"
    ]["run"]
    assert "pytest tests/integration -q" in integration_test
    assert "--cov=src/kortravelmap" in integration_test
    assert "--cov-append" in integration_test
    assert "--cov-report=xml" in integration_test
    assert "--cov-fail-under=0" not in integration_test
    combined_upload = integration_steps["Upload combined coverage XML"]
    assert "!cancelled()" in combined_upload["if"]
    assert combined_upload["with"]["name"] == "coverage-xml"
    assert combined_upload["with"]["path"] == "coverage.xml"
    assert combined_upload["with"]["if-no-files-found"] == "ignore"

    fixture = jobs["fixture-replay"]
    assert fixture["name"] == "pytest fixture replay"
    fixture_run = _steps_by_name(fixture)["Run fixture replay tests"]["run"]
    assert "[ -d tests/fixtures ]" in fixture_run
    assert "pytest tests/fixtures -q --no-cov" in fixture_run


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

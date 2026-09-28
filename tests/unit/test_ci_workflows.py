"""Sprint 5 CI workflow 구조 회귀 테스트."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.integration._postgis_image import (
    ALPINE_POSTGIS_IMAGE,
    POSTGIS_IMAGE_ENV,
    SHARED_GLIBC_POSTGIS_IMAGE,
)

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
    node_setup = unit_steps["Set up Node 22.23.1"]
    assert node_setup["uses"] == "actions/setup-node@v4"
    assert node_setup["with"] == {
        "node-version": "22.23.1",
        "cache": "npm",
        "cache-dependency-path": "package-lock.json",
    }
    assert unit_steps["Install Next env parser for unit tests"]["run"] == (
        "npx --yes npm@12.0.1 ci --workspaces=false --omit=dev "
        "--ignore-scripts --no-audit --no-fund"
    )
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
    assert integration["name"] == "pytest integration (PostGIS, ${{ matrix.lane }})"
    assert integration["needs"] == "unit"
    # 두 lane이 같은 suite를 돈다(ADR-103). digest의 정본은 `_postgis_image.py`다 —
    # 워크플로가 그 값과 갈리면 glibc lane이 공용 instance가 아닌 이미지를 시험한다.
    assert integration["strategy"]["fail-fast"] is False
    assert integration["strategy"]["matrix"] == {
        "include": [
            {"lane": "alpine", "image": ALPINE_POSTGIS_IMAGE},
            {"lane": "glibc", "image": SHARED_GLIBC_POSTGIS_IMAGE},
        ]
    }
    assert integration["env"] == {POSTGIS_IMAGE_ENV: "${{ matrix.image }}"}
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
    # upload-artifact@v4는 같은 이름의 두 번째 업로드를 거부한다 — leg마다 이름이 다르다.
    assert combined_upload["with"]["name"] == "coverage-xml-${{ matrix.lane }}"
    assert combined_upload["with"]["path"] == "coverage.xml"
    assert combined_upload["with"]["if-no-files-found"] == "ignore"

    fixture = jobs["fixture-replay"]
    assert fixture["name"] == "pytest fixture replay"
    fixture_run = _steps_by_name(fixture)["Run fixture replay tests"]["run"]
    assert "[ -d tests/fixtures ]" in fixture_run
    assert "pytest tests/fixtures -q --no-cov" in fixture_run


#: 통합 suite의 두 lane(ADR-103). 값의 정본은 `tests/integration/_postgis_image.py`다.
_POSTGIS_LANES = [
    {"lane": "alpine", "image": ALPINE_POSTGIS_IMAGE},
    {"lane": "glibc", "image": SHARED_GLIBC_POSTGIS_IMAGE},
]
_INTEGRATION_PYTEST = re.compile(r"\bpytest\b[^\n]*\btests/integration\b")


@pytest.mark.unit
def test_every_workflow_that_runs_integration_covers_both_lanes() -> None:
    """`pytest tests/integration`을 도는 **모든** workflow job이 두 lane을 돈다.

    한 곳만 matrix를 가지면 다른 곳(수동 재확인 workflow 등)은 alpine에서만 돌며 초록이
    된다 — glibc lane이 잡는 collation·head 오라클·bootstrap 결함을 보지 못한다.
    """

    seen: list[str] = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in workflow.get("jobs", {}).items():
            runs = [
                str(step.get("run", ""))
                for step in job.get("steps", [])
                if isinstance(step, dict)
            ]
            if not any(_INTEGRATION_PYTEST.search(run) for run in runs):
                continue
            where = f"{path.name}:{job_id}"
            seen.append(where)
            assert job.get("strategy", {}).get("matrix") == {"include": _POSTGIS_LANES}, where
            assert job.get("strategy", {}).get("fail-fast") is False, where
            assert job.get("env", {}).get(POSTGIS_IMAGE_ENV) == "${{ matrix.image }}", where
    # 검사가 무엇을 봤는지의 하한 — 탐지가 비면 이 검사는 아무것도 증명하지 못한다.
    assert set(seen) >= {"ci.yml:integration", "postgis-only.yml:integration"}


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
        "pytest integration (PostGIS, alpine)",
        "pytest integration (PostGIS, glibc)",
        "pytest fixture replay",
        "openapi-drift",
        "type-check + next build (Node 20)",
    ]:
        assert check_name in runbook

    assert "path filter를 제거" in runbook

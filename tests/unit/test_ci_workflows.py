"""Sprint 5 CI workflow 구조 회귀 테스트."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.integration._postgis_image import (
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
    # lane은 공용 instance digest다(ADR-118). digest의 정본은 `_postgis_image.py`다 —
    # 워크플로가 그 값과 갈리면 CI가 prod major·collation이 아닌 이미지를 시험한다.
    assert integration["strategy"]["fail-fast"] is False
    assert integration["strategy"]["matrix"] == {"include": _POSTGIS_LANES}
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
    # 필수 lane은 측정 artifact를 요구하지 않는다. 관측값 파일이 없다고 job을 실패시키면
    # 측정 harness가 required CI로 돌아온다(scoped write 기준선이 그랬다).
    uploads = [
        step
        for step in integration["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact")
    ]
    assert uploads
    assert all(step["with"].get("if-no-files-found") != "error" for step in uploads)

    fixture = jobs["fixture-replay"]
    assert fixture["name"] == "pytest fixture replay"
    fixture_run = _steps_by_name(fixture)["Run fixture replay tests"]["run"]
    assert "[ -d tests/fixtures ]" in fixture_run
    assert "pytest tests/fixtures -q --no-cov" in fixture_run


#: 통합 suite의 lane(ADR-118). 값의 정본은 `tests/integration/_postgis_image.py`다.
_POSTGIS_LANES = [
    {"lane": "pg18", "image": SHARED_GLIBC_POSTGIS_IMAGE},
]
_INTEGRATION_PYTEST = re.compile(r"\bpytest\b[^\n]*\btests/integration\b")


@pytest.mark.unit
def test_every_workflow_that_runs_integration_covers_every_lane() -> None:
    """`pytest tests/integration`을 도는 **모든** workflow job이 같은 lane을 돈다.

    한 곳만 matrix를 가지면 다른 곳(수동 재확인 workflow 등)은 기본값이나 옛 이미지에서
    돌며 초록이 된다 — prod major가 잡는 catalog·collation·head 오라클·bootstrap 결함을
    보지 못한다.
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
        "pytest integration (PostGIS, pg18)",
        "pytest fixture replay",
        "openapi-drift",
        "type-check + next build (Node 20)",
    ]:
        assert check_name in runbook

    assert "path filter를 제거" in runbook


@pytest.mark.unit
def test_dagster_job_installs_the_pinned_datagokr_for_the_replay_golden() -> None:
    """T-GR-08 replay golden은 provider 실모델이 있어야 돈다 — CI dagster job이 pyproject와 **같은
    핀**으로 설치한다(핀을 올리고 CI를 잊으면 golden이 옛 모델로 돈다)."""
    pin = re.compile(
        r"python-datagokr-api @ git\+https://github\.com/digitie/python-datagokr-api\.git@[0-9a-f]{40}"
    )
    name = "Install python-datagokr-api (replay golden only)"
    pyproject = pin.findall(_read("pyproject.toml"))
    workflow = yaml.safe_load(_read(".github/workflows/ci.yml"))
    by_name = _steps_by_name(workflow["jobs"]["unit"])
    steps = list(by_name)
    assert len(pyproject) == 1
    assert pin.findall(by_name[name]["run"]) == pyproject
    assert steps.index("Run unit + lint tests") < steps.index(name)
    assert steps.index(name) < steps.index("Run kor-travel-map-dagster unit tests")

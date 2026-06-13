"""T-108 운영 배포 자동화 회귀 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


@pytest.mark.unit
def test_package_exposes_t108_deploy_scripts() -> None:
    package_json = json.loads(_read("package.json"))

    assert package_json["scripts"]["docker:buildx"] == "bash scripts/docker-buildx.sh"


@pytest.mark.unit
def test_buildx_script_builds_three_multi_platform_images() -> None:
    script = _read("scripts/docker-buildx.sh")

    assert "linux/amd64,linux/arm64" in script
    assert "docker buildx build" in script
    assert "docker/api.Dockerfile" in script
    assert "docker/frontend.Dockerfile" in script
    assert "docker/dagster.Dockerfile" in script
    assert "KOR_TRAVEL_MAP_API_IMAGE" in script
    assert "KOR_TRAVEL_MAP_FRONTEND_IMAGE" in script
    assert "KOR_TRAVEL_MAP_DAGSTER_IMAGE" in script
    assert "--secret id=github_token,env=GITHUB_TOKEN" in script
    assert "NEXT_PUBLIC_KOR_TRAVEL_MAP_API" in script


@pytest.mark.unit
def test_deploy_docs_cover_odroid_n150_and_exclude_streaming_replication() -> None:
    deploy = _read("docs/deploy.md")
    runbook = _read("docs/runbooks/docker-app.md")
    env_example = _read(".env.example")

    for text in (deploy, runbook):
        assert "Odroid M1S" in text
        assert "N150 16GB" in text
        assert "linux/amd64" in text
        assert "linux/arm64" in text
        assert "streaming replication은 하지 않는다" in text

    assert "KOR_TRAVEL_MAP_POSTGRES_REPLICATION_USER" not in env_example

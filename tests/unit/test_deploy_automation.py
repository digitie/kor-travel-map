"""T-108 운영 배포 자동화 회귀 테스트."""

from __future__ import annotations

import json
import os
import subprocess
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
def test_buildx_frontend_receives_exact_git_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "0123456789abcdef0123456789abcdef01234567"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    git = fake_bin / "git"
    git.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' '{revision}'\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$DOCKER_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env_file = tmp_path / "missing.env"
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_LOG", str(docker_log))
    monkeypatch.setenv("KOR_TRAVEL_MAP_ENV_FILE", str(env_file))
    monkeypatch.setenv("KOR_TRAVEL_MAP_BUILDX_OUTPUT", "docker")
    monkeypatch.setenv("KOR_TRAVEL_MAP_DOCKER_PLATFORMS", "linux/amd64")

    subprocess.run(
        ["bash", "scripts/docker-buildx.sh"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )

    frontend_build = next(
        line
        for line in docker_log.read_text(encoding="utf-8").splitlines()
        if "-f docker/frontend.Dockerfile" in line
    )
    assert f"KOR_TRAVEL_MAP_GIT_COMMIT={revision}" in frontend_build


@pytest.mark.unit
def test_local_compose_build_paths_export_exact_git_revision() -> None:
    expected = 'export KOR_TRAVEL_MAP_GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"'

    assert expected in _read("scripts/docker-build.sh")
    assert expected in _read("scripts/docker-up.sh")


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

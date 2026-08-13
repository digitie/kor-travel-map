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
def test_geo_credentials_never_fall_back_to_vworld_provider_key(
    tmp_path: Path,
) -> None:
    """VWorld provider key 하나로 Geo consumer credential을 채우지 않는다."""

    env = os.environ.copy()
    for name in (
        "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY",
        "KOR_TRAVEL_GEO_API_KEY",
        "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",
        "NEXT_PUBLIC_VWORLD_API_KEY",
        "KOR_TRAVEL_GEO_VWORLD_API_KEY",
        "VWORLD_API_KEY",
    ):
        env.pop(name, None)
    env["KOR_TRAVEL_MAP_ENV_FILE"] = str(tmp_path / "missing.env")
    env["VWORLD_API_KEY"] = "vworld-provider-key"
    result = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/load-env.sh; "
            "printf '%s\\n%s\\n%s\\n' "
            '"$NEXT_PUBLIC_VWORLD_API_KEY" '
            '"${NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY:-}" '
            '"${KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY:-}"',
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == ["vworld-provider-key", "", ""]

    buildx = _read("scripts/docker-buildx.sh")
    compose = _read("docker-compose.yml")
    geo_route = _read(
        "packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts"
    )
    live_acceptance = _read("scripts/run-admin-feature-clone-live-acceptance.sh")
    assert (
        'NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY=${NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY:-}"'
        in buildx
    )
    assert "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY:-${NEXT_PUBLIC_VWORLD_API_KEY" not in compose
    assert "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY:-${NEXT_PUBLIC_VWORLD_API_KEY" not in compose
    assert "process.env.NEXT_PUBLIC_VWORLD_API_KEY" not in geo_route
    assert "require_env E2E_KOR_TRAVEL_GEO_API_KEY" in live_acceptance
    assert (
        'NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY="$E2E_KOR_TRAVEL_GEO_API_KEY"'
        in live_acceptance
    )
    assert (
        'NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY="$E2E_VWORLD_API_KEY"'
        not in live_acceptance
    )


@pytest.mark.unit
def test_local_compose_build_paths_export_exact_git_revision() -> None:
    expected = 'export KOR_TRAVEL_MAP_GIT_COMMIT="$(git -C "$ROOT_DIR" rev-parse HEAD)"'

    assert expected in _read("scripts/docker-build.sh")
    assert expected in _read("scripts/docker-up.sh")


@pytest.mark.unit
def test_mocked_checkpoint_runner_owns_exact_frontend_container() -> None:
    script = _read(
        "packages/kor-travel-map-admin/frontend/e2e/run-mocked-checkpoint.mjs"
    )
    reporter = _read(
        "packages/kor-travel-map-admin/frontend/e2e/mocked-failure-reporter.ts"
    )

    assert "MOCKED_E2E_FRONTEND_IMAGE" not in script
    assert "MOCKED_E2E_FRONTEND_CONTAINER" not in script
    assert 'parsedBaseUrl.hostname !== "127.0.0.1"' in script
    assert '"create",' in script
    assert "imageInspect.Id" in script
    assert '"--read-only",' in script
    assert '"--cap-drop",' in script
    assert '"no-new-privileges:true",' in script
    assert '"--env-file",' in script
    assert '"--entrypoint"' not in script
    assert '"archive",' in script
    assert '"--iidfile",' in script
    assert "playwrightChild = await runManagedChild(" in script
    assert 'detached: process.platform !== "win32"' in script
    assert "process.kill(-child.pid, signal)" in script
    assert "const postContainerInspect = await inspectOwnedContainer()" in script
    assert "const postBuildInfo = await readBuildInfo(5_000)" in script
    assert "await cleanupOwnedContainer()" in script
    assert "await cleanupOwnedImage()" in script
    assert "await cleanupOwnedNetwork()" in script
    assert "removed.status !== 0" not in script
    assert "await waitForResourceAbsence(listArgs)" in script
    assert "cleanup_container_remaining" in script
    assert "cleanup_filesystem_failed" in script
    assert "containerCreateAttempted = true" in script
    assert "io.kortravelmap.mocked-e2e-owned=true" in script
    assert '`name=^${ownedContainerName}$`' in script
    assert '`name=^${ownedNetworkName}$`' in script
    assert 'const listArgs = [\n    "image",\n    "ls",' in script
    assert 'terminateChildGroup(child, "SIGKILL")' in script
    assert 'spawnSync("docker"' not in script
    assert (
        'result.status === (checkpoint === "D" ? "passed" : "failed")'
        in reporter
    )
    assert "schemaVersion: 3" in reporter
    assert "report.gatePassed = gatePassed" in reporter


@pytest.mark.unit
def test_frontend_docker_context_and_digest_exclusions_are_aligned() -> None:
    dockerignore = _read(".dockerignore")
    digest = _read("scripts/frontend-source-digest.mjs")

    assert "**/.env" in dockerignore
    assert "**/.env.*" in dockerignore
    assert "!**/.env.example" in dockerignore
    assert "**/.cache/" in dockerignore
    assert '".dockerignore",' in digest
    assert 'fileName.startsWith(".env.")' in digest
    assert '".cache",' in digest


@pytest.mark.unit
def test_frontend_source_digest_includes_public_build_inputs() -> None:
    digest = _read("scripts/frontend-source-digest.mjs")
    dockerfile = _read("docker/frontend.Dockerfile")
    build_input_contract = _read("scripts/frontend-build-inputs.mjs")
    build_inputs = (
        "NEXT_PUBLIC_KOR_TRAVEL_MAP_API",
        "NEXT_PUBLIC_KOR_TRAVEL_MAP_DAGSTER_URL",
        "NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL",
        "NEXT_PUBLIC_VWORLD_API_KEY",
        "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",
    )

    for name in build_inputs:
        assert name in build_input_contract
        assert f"ARG {name}" in dockerfile
    assert "function envOrDefault(environment, name, fallback)" in (
        build_input_contract
    )
    assert "frontendBuildInputs" in digest
    assert 'hash.update("build-arg")' in digest


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

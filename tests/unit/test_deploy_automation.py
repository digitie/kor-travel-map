"""T-108 운영 배포 자동화 회귀 테스트."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
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
def test_buildx_script_builds_four_multi_platform_runtime_images() -> None:
    script = _read("scripts/docker-buildx.sh")

    assert "linux/amd64,linux/arm64" in script
    assert "docker buildx build" in script
    assert "docker/api.Dockerfile" in script
    assert "docker/frontend.Dockerfile" in script
    assert "docker/dagster.Dockerfile" in script
    assert "KOR_TRAVEL_MAP_API_IMAGE" in script
    assert "KOR_TRAVEL_MAP_FRONTEND_IMAGE" in script
    assert "KOR_TRAVEL_MAP_DAGSTER_IMAGE" in script
    assert "KOR_TRAVEL_MAP_DAGSTER_DAEMON_IMAGE" in script
    assert "--secret id=github_token,env=GITHUB_TOKEN" in script
    assert "NEXT_PUBLIC_KOR_TRAVEL_MAP_API" in script


@pytest.mark.unit
def test_buildx_runtime_images_receive_exact_git_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "0123456789abcdef0123456789abcdef01234567"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    git = fake_bin / "git"
    git.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        f"  'rev-parse HEAD') printf '%s\\n' '{revision}' ;;\n"
        "  'status --porcelain=v1 --untracked-files=all') : ;;\n"
        f"  'archive --format=tar {revision}') "
        "tar -cf - --files-from /dev/null ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
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
    monkeypatch.setenv("TMPDIR", str(temp_dir))

    subprocess.run(
        ["bash", "scripts/docker-buildx.sh"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )

    image_builds = [
        line
        for line in docker_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("buildx build ")
    ]
    assert len(image_builds) == 3
    for image_build in image_builds:
        assert image_build.count(f"KOR_TRAVEL_MAP_GIT_COMMIT={revision}") == 1
        assert image_build.count(
            f"org.opencontainers.image.revision={revision}"
        ) == 1

    api_build = next(line for line in image_builds if "-f docker/api.Dockerfile" in line)
    frontend_build = next(
        line for line in image_builds if "-f docker/frontend.Dockerfile" in line
    )
    dagster_build = next(
        line for line in image_builds if "-f docker/dagster.Dockerfile" in line
    )
    assert "kor-travel-map-api" in api_build
    assert "kor-travel-map-admin" in frontend_build
    assert "kor-travel-map-dagster" in dagster_build
    assert "kor-travel-map-dagster-daemon" in dagster_build
    assert all(line.split()[-1] == "-" for line in image_builds)
    assert list(temp_dir.iterdir()) == []


@pytest.mark.unit
def test_buildx_rejects_dirty_source_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "0123456789abcdef0123456789abcdef01234567"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    git = fake_bin / "git"
    git.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        f"  'rev-parse HEAD') printf '%s\\n' '{revision}' ;;\n"
        "  'status --porcelain=v1 --untracked-files=all') "
        "printf '%s\\n' ' M src/changed.py' ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$DOCKER_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_LOG", str(docker_log))
    monkeypatch.setenv("KOR_TRAVEL_MAP_ENV_FILE", str(tmp_path / "missing.env"))

    result = subprocess.run(
        ["bash", "scripts/docker-buildx.sh"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == (
        "clean Git worktree is required for an exact source revision build\n"
    )
    assert not docker_log.exists()


@pytest.mark.unit
def test_buildx_rejects_unverifiable_source_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "0123456789abcdef0123456789abcdef01234567"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    git = fake_bin / "git"
    git.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        f"  'rev-parse HEAD') printf '%s\\n' '{revision}' ;;\n"
        "  'status --porcelain=v1 --untracked-files=all') exit 64 ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$DOCKER_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_LOG", str(docker_log))
    monkeypatch.setenv("KOR_TRAVEL_MAP_ENV_FILE", str(tmp_path / "missing.env"))

    result = subprocess.run(
        ["bash", "scripts/docker-buildx.sh"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == "failed to verify that the Git worktree is clean\n"
    assert not docker_log.exists()


@pytest.mark.unit
def test_buildx_oci_output_uses_one_archive_per_build_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "0123456789abcdef0123456789abcdef01234567"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    git = fake_bin / "git"
    git.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        f"  'rev-parse HEAD') printf '%s\\n' '{revision}' ;;\n"
        "  'status --porcelain=v1 --untracked-files=all') : ;;\n"
        f"  'archive --format=tar {revision}') "
        "tar -cf - --files-from /dev/null ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$DOCKER_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    output_dir = tmp_path / "oci"
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_LOG", str(docker_log))
    monkeypatch.setenv("KOR_TRAVEL_MAP_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("KOR_TRAVEL_MAP_BUILDX_OUTPUT", "oci")
    monkeypatch.setenv("KOR_TRAVEL_MAP_BUILDX_OCI_DIR", str(output_dir))

    subprocess.run(
        ["bash", "scripts/docker-buildx.sh"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
        text=True,
    )

    image_builds = [
        line
        for line in docker_log.read_text(encoding="utf-8").splitlines()
        if line.startswith("buildx build ")
    ]
    output_args = {
        token.removeprefix("type=oci,dest=")
        for line in image_builds
        for token in line.split()
        if token.startswith("type=oci,dest=")
    }
    assert output_args == {
        str(output_dir / f"api-{revision[:12]}.oci"),
        str(output_dir / f"frontend-{revision[:12]}.oci"),
        str(output_dir / f"dagster-{revision[:12]}.oci"),
    }


@pytest.mark.unit
def test_buildx_rejects_removed_single_oci_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    revision = "0123456789abcdef0123456789abcdef01234567"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker_log = tmp_path / "docker.log"
    git = fake_bin / "git"
    git.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        f"  'rev-parse HEAD') printf '%s\\n' '{revision}' ;;\n"
        "  'status --porcelain=v1 --untracked-files=all') : ;;\n"
        f"  'archive --format=tar {revision}') "
        "tar -cf - --files-from /dev/null ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$DOCKER_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")
    monkeypatch.setenv("DOCKER_LOG", str(docker_log))
    monkeypatch.setenv("KOR_TRAVEL_MAP_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setenv("KOR_TRAVEL_MAP_BUILDX_OUTPUT", "oci")
    monkeypatch.setenv("KOR_TRAVEL_MAP_BUILDX_OCI_PATH", str(tmp_path / "images.oci"))

    result = subprocess.run(
        ["bash", "scripts/docker-buildx.sh"],
        cwd=ROOT,
        env=os.environ.copy(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == (
        "KOR_TRAVEL_MAP_BUILDX_OCI_PATH was removed; "
        "use KOR_TRAVEL_MAP_BUILDX_OCI_DIR\n"
    )
    assert not docker_log.exists()


_FAKE_REVISION = "0123456789abcdef0123456789abcdef01234567"


def _fake_build_tools(tmp_path: Path) -> tuple[dict[str, str], Path, Path, Path]:
    """materialize 도중 끊기는 상황의 가짜 ``git``·``docker``와 그 env.

    가짜 ``git archive``는 자기 pid를 남기고 tar를 쓰기 시작한다. **스스로 끝난다** — 부모
    (``docker-buildx.sh``)가 사라지거나 30초가 지나면 멈춘다. 예전 가짜는 무한 루프라, 스크립트의
    정리가 writer를 놓친 날(``$!`` 경주) 고아가 되어 n150에서 몇 시간 CPU를 썼다.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    temp_dir = tmp_path / "tmp"
    temp_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    writer_pid = tmp_path / "writer.pid"
    git = fake_bin / "git"
    git.write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        f"  'rev-parse HEAD') printf '%s\\n' '{_FAKE_REVISION}' ;;\n"
        "  'status --porcelain=v1 --untracked-files=all') : ;;\n"
        f"  'archive --format=tar {_FAKE_REVISION}')\n"
        f"    printf '%s' \"$$\" > '{writer_pid}'\n"
        "    parent=$PPID\n"
        "    while (( SECONDS < 30 )) && kill -0 \"$parent\" 2>/dev/null; do\n"
        "      printf x; for ((i=0; i<10000; i++)); do :; done\n"
        "    done\n"
        # 여기 닿았다면 아무도 이 writer를 죽이지 않았다(부모가 사라졌거나 시간 초과) — 고아였다.
        f"    printf orphaned > '{writer_pid}.orphaned' ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$DOCKER_LOG"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["DOCKER_LOG"] = str(docker_log)
    env["KOR_TRAVEL_MAP_ENV_FILE"] = str(tmp_path / "missing.env")
    env["TMPDIR"] = str(temp_dir)
    return env, temp_dir, docker_log, writer_pid


def _writer_was_killed(writer_pid: Path) -> bool:
    """가짜 writer가 스크립트의 정리로 **죽었는가** — 스스로 끝났으면(고아였다) 표식이 남는다.

    writer가 끝나기를 잠깐(최대 5초) 기다린 뒤 표식을 본다. 그때까지 살아 있으면 테스트가 죽인다
    (고아를 남기지 않는다).
    """
    pid = int(writer_pid.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(pid, signal.SIGKILL)
        return False
    return not Path(f"{writer_pid}.orphaned").exists()


def _run_until_terminated(
    script: Path, env: dict[str, str], temp_dir: Path
) -> tuple[int, str, str]:
    process = subprocess.Popen(
        ["bash", str(script)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while process.poll() is None and not any(
            path.stat().st_size > 0 for path in temp_dir.glob("kor-travel-map-buildx.*.tar")
        ):
            assert time.monotonic() < deadline, "가짜 writer가 tar를 쓰기 시작하지 않았다"
            time.sleep(0.01)
        if process.poll() is None:
            os.kill(process.pid, signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    return process.returncode, stdout, stderr


@pytest.mark.unit
@pytest.mark.timeout(60)
def test_buildx_cleans_partial_archive_when_materialization_is_terminated(
    tmp_path: Path,
) -> None:
    env, temp_dir, docker_log, writer_pid = _fake_build_tools(tmp_path)

    status, stdout, stderr = _run_until_terminated(
        ROOT / "scripts" / "docker-buildx.sh", env, temp_dir
    )

    assert status == 143
    assert (stdout, stderr) == ("", "")
    assert list(temp_dir.iterdir()) == []
    assert not docker_log.exists()
    assert _writer_was_killed(writer_pid), "TERM 뒤에 tar writer가 정리되지 않았다"


@pytest.mark.unit
@pytest.mark.timeout(60)
def test_buildx_reaps_the_writer_even_when_term_lands_before_the_pid_is_recorded(
    tmp_path: Path,
) -> None:
    """``git archive … &`` 직후, writer pid를 적기도 전에 TERM이 오는 경주를 결정적으로 만든다.

    스크립트 사본에서 그 줄 바로 뒤에 ``kill -TERM $$``를 넣는다 — 부하 중 n150에서 우연히 나던 창을
    매번 연다. 정리가 ``$!``를 담은 변수에 기대면 그 변수가 아직 비어 writer가 고아가 된다.
    """
    env, temp_dir, docker_log, writer_pid = _fake_build_tools(tmp_path)
    scripts = tmp_path / "repo" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "load-env.sh").write_text(
        (ROOT / "scripts" / "load-env.sh").read_text(encoding="utf-8"), encoding="utf-8"
    )
    original = (ROOT / "scripts" / "docker-buildx.sh").read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    fork = [i for i, line in enumerate(lines) if line.startswith("git archive --format=tar ")]
    assert len(fork) == 1, "writer를 띄우는 줄을 찾지 못했다"
    lines.insert(fork[0] + 1, "kill -TERM $$\n")
    script = scripts / "docker-buildx.sh"
    script.write_text("".join(lines), encoding="utf-8")

    # 빨강이 **결정적인** 이유: writer는 스크립트의 stdout(=tar)만 바꾸고 stderr는
    # 부모와 같은 pipe를 물려받는다. 정리가 writer를 놓치면 그 고아가 stderr pipe를 쥔 채
    # 남으므로 ``communicate``는 고아가 스스로 끝날 때까지 기다린다(부모가 사라진 것을 보고
    # ``*.orphaned`` 표식을 쓴 뒤). 그래서 아래 단언 시점에는 표식이 **반드시** 있다 — 타이밍에
    # 기대지 않는다. writer는 archive 분기의 첫 명령으로 pid를 남기므로 pid 파일이 없으면
    # writer가 그 전에 죽은 것이고(정리가 이겼다) 그때는 고아도 없다.
    status, stdout, stderr = _run_until_terminated(script, env, temp_dir)

    assert status == 143
    assert (stdout, stderr) == ("", "")
    assert list(temp_dir.iterdir()) == []
    assert not docker_log.exists()
    if writer_pid.exists():  # writer가 pid를 남기기 전에 죽었으면 살아 남을 것도 없다
        assert _writer_was_killed(writer_pid), "pid 기록 전 TERM에 tar writer가 고아로 남았다"


@pytest.mark.unit
def test_geo_credentials_never_fall_back_to_vworld_provider_key(
    tmp_path: Path,
) -> None:
    """VWorld provider key 하나로 Geo consumer credential을 채우지 않는다."""

    env = os.environ.copy()
    forbidden_browser_key = "NEXT_PUBLIC_" + "KOR_TRAVEL_GEO_API_KEY"
    for name in (
        "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY",
        "KOR_TRAVEL_GEO_API_KEY",
        forbidden_browser_key,
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
            '"${KOR_TRAVEL_GEO_API_KEY:-}" '
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
    dockerfile = _read("docker/frontend.Dockerfile")
    build_inputs = _read("scripts/frontend-build-inputs.mjs")
    geo_route = _read(
        "packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts"
    )
    live_acceptance = _read("scripts/run-admin-feature-clone-live-acceptance.sh")
    assert forbidden_browser_key not in buildx
    assert forbidden_browser_key not in compose
    assert forbidden_browser_key not in dockerfile
    assert forbidden_browser_key not in build_inputs
    assert "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY:-${NEXT_PUBLIC_VWORLD_API_KEY" not in compose
    assert "process.env.NEXT_PUBLIC_VWORLD_API_KEY" not in geo_route
    assert "E2E_KOR_TRAVEL_GEO_API_KEY" not in live_acceptance
    assert forbidden_browser_key not in live_acceptance


@pytest.mark.unit
def test_local_admin_stack_receives_only_the_server_geo_alias(tmp_path: Path) -> None:
    """root 정본 키를 local Next.js server에 전달하되 browser 이름은 만들지 않는다."""

    env = os.environ.copy()
    forbidden_browser_key = "NEXT_PUBLIC_" + "KOR_TRAVEL_GEO_API_KEY"
    for name in (
        "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY",
        "KOR_TRAVEL_GEO_API_KEY",
        forbidden_browser_key,
    ):
        env.pop(name, None)
    env["KOR_TRAVEL_MAP_ENV_FILE"] = str(tmp_path / "missing.env")
    env["KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY"] = "G" * 32

    result = subprocess.run(
        [
            "bash",
            "-c",
            "source scripts/load-env.sh; "
            "printf '%s\\n%s\\n' "
            '"$KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY" '
            '"$KOR_TRAVEL_GEO_API_KEY"',
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == ["G" * 32, "G" * 32]
    assert forbidden_browser_key not in _read("scripts/load-env.sh")
    assert (
        "NEXT_PUBLIC_* | KOR_TRAVEL_GEO_API_KEY | KOR_TRAVEL_MAP_API_INTERNAL_URL"
        in _read("scripts/run-admin-stack.sh")
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
    )

    for name in build_inputs:
        assert name in build_input_contract
        assert f"ARG {name}" in dockerfile
    forbidden_browser_key = "NEXT_PUBLIC_" + "KOR_TRAVEL_GEO_API_KEY"
    assert forbidden_browser_key not in build_input_contract
    assert f"ARG {forbidden_browser_key}" not in dockerfile
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

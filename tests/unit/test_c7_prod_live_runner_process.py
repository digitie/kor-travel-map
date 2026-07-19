"""C7 runner process/container lifecycle의 subprocess 회귀 테스트."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-c7-prod-live-e2e.sh"
LIFECYCLE = ROOT / "scripts" / "lib" / "c7-prod-runner-lifecycle.sh"


def test_runner_missing_docker_fails_before_state_mutation(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in ("dirname", "git", "python3", "timeout"):
        resolved = shutil.which(command)
        assert resolved is not None
        (fake_bin / command).symlink_to(resolved)

    result = subprocess.run(
        ["/bin/bash", str(RUNNER)],
        capture_output=True,
        env={"PATH": str(fake_bin)},
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert "required command is missing: docker" in result.stderr
    assert "BLOCKED.json" not in result.stderr


def test_lifecycle_terminates_term_resistant_child_with_bounded_wait() -> None:
    script = f"""
set -euo pipefail
source {LIFECYCLE!s}
setsid /bin/bash -c 'trap "" TERM; while :; do /bin/sleep 1; done' &
ACTIVE_COMMAND_PID=$!
ACTIVE_COMMAND_PGID=$ACTIVE_COMMAND_PID
terminate_active_command 2
[[ -z "$ACTIVE_COMMAND_PID" ]]
[[ -z "$ACTIVE_COMMAND_PGID" ]]
"""

    result = subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr


def test_lifecycle_fake_docker_removes_exact_residual_container(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    container_id = "a" * 64
    cid = tmp_path / "container-10.cid"
    cid.write_text(container_id, encoding="ascii")
    cid.chmod(0o600)
    runtime = tmp_path / "runtime.A1b2C3"
    reference = tmp_path / "container-10.json"
    reference.write_text(
        json.dumps(
            {
                "container_name": "kor-travel-map-c7-e2e-10",
                "creator_pgid": 0,
                "creator_pid": 0,
                "creator_sid": 0,
                "creator_start_ticks": 0,
                "phase": "created",
                "runtime": str(runtime),
                "version": 1,
            }
        ),
        encoding="utf-8",
    )
    reference.chmod(0o600)
    outcome = tmp_path / "container-10.outcome.json"
    outcome.write_text('{"phase":"create","status":0,"version":1}\n', encoding="utf-8")
    outcome.chmod(0o600)
    marker = tmp_path / "removed"
    timeout_script = fake_bin / "timeout"
    timeout_script.write_text(
        "#!/bin/sh\nshift 2\nexec \"$@\"\n",
        encoding="utf-8",
    )
    timeout_script.chmod(0o700)
    docker_script = fake_bin / "docker"
    docker_script.write_text(
        "#!/bin/sh\n"
        'if [ "$1 $2" = "container ls" ]; then\n'
        f"  printf '%s\\n' '{container_id}'\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1 $2" = "container rm" ]; then\n'
        f"  : > '{marker}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 2\n",
        encoding="utf-8",
    )
    docker_script.chmod(0o700)
    script = f"""
set -euo pipefail
source {LIFECYCLE!s}
ACTIVE_CID_FILE={cid!s}
ACTIVE_CONTAINER_REF_FILE={reference!s}
ACTIVE_CREATE_OUTCOME_FILE={outcome!s}
ACTIVE_CONTAINER_NAME=kor-travel-map-c7-e2e-10
RUNTIME_DIR={runtime!s}
remove_active_container {os.getuid()} {os.getgid()}
[[ ! -e "$ACTIVE_CID_FILE" ]]
[[ ! -e "$ACTIVE_CONTAINER_REF_FILE" ]]
[[ ! -e "$ACTIVE_CREATE_OUTCOME_FILE" ]]
"""
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"

    result = subprocess.run(
        ["/bin/bash", "-c", script],
        capture_output=True,
        env=env,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert marker.exists()

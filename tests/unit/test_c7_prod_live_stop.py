"""C7 Docker create/start recovery의 fail-closed 회귀 테스트."""

from __future__ import annotations

import contextlib
import importlib.util
import json
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
STOPPER = ROOT / "scripts" / "stop-c7-prod-live-container.py"


def _load_stopper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("c7_prod_live_stop", STOPPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _portable_safe_entry(path: Path, *, directory: bool) -> bool:
    observed = path.lstat()
    return (
        (stat.S_ISDIR(observed.st_mode) if directory else stat.S_ISREG(observed.st_mode))
        and not path.is_symlink()
        and stat.S_IMODE(observed.st_mode) == (0o700 if directory else 0o600)
    )


def _write(path: Path, value: str) -> None:
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    phase: str,
    cid: str | None,
    outcome: int | None,
) -> tuple[ModuleType, Path]:
    stopper = _load_stopper()
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    runtime = root / "runtime.A1b2C3"
    runtime.mkdir(mode=0o700)
    _write(root / "BLOCKED.json", '{"phase":"restore_failed"}\n')
    (root / "orchestrator.lock").touch(mode=0o600)
    creator = (23, 23, 100) if phase == "creating" else (0, 0, 0)
    _write(
        root / "container-23.json",
        json.dumps(
            {
                "container_name": "kor-travel-map-c7-e2e-23",
                "creator_pgid": creator[1],
                "creator_pid": creator[0],
                "creator_sid": creator[1],
                "creator_start_ticks": creator[2],
                "phase": phase,
                "runtime": str(runtime),
                "version": 1,
            }
        ),
    )
    if cid is not None:
        _write(root / "container-23.cid", cid)
    if outcome is not None:
        _write(
            root / "container-23.outcome.json",
            json.dumps({"phase": "create", "status": outcome, "version": 1}),
        )
    monkeypatch.setattr(stopper, "STATE_ROOT", root)
    monkeypatch.setattr(stopper, "_safe_entry", _portable_safe_entry)
    monkeypatch.setattr(stopper, "_read_root_file", lambda path, limit: path.read_bytes())
    monkeypatch.setattr(stopper, "_creator_matches", lambda _reference: False)
    return stopper, root


def test_unresolved_create_without_outcome_preserves_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopper, root = _state(
        tmp_path, monkeypatch, phase="creating", cid="", outcome=None
    )
    monkeypatch.setattr(stopper, "_find_named_container", lambda _reference: None)

    assert stopper.stop_residual_container(root) == (False, False)
    assert (root / "container-23.json").exists()
    assert (root / "container-23.cid").exists()


def test_creator_stopped_before_cid_open_removes_unstarted_reference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopper, root = _state(
        tmp_path, monkeypatch, phase="creating", cid=None, outcome=None
    )
    monkeypatch.setattr(stopper, "_find_named_container", lambda _reference: None)

    assert stopper.stop_residual_container(root) == (False, True)
    assert not (root / "container-23.json").exists()


def test_cid_opened_while_creator_stops_preserves_create_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopper, root = _state(
        tmp_path, monkeypatch, phase="creating", cid=None, outcome=None
    )

    def stop_after_cid_open(_reference: object) -> None:
        _write(root / "container-23.cid", "")

    monkeypatch.setattr(stopper, "_terminate_creator", stop_after_cid_open)
    monkeypatch.setattr(stopper, "_find_named_container", lambda _reference: None)

    assert stopper.stop_residual_container(root) == (False, False)
    assert (root / "container-23.json").exists()
    assert (root / "container-23.cid").exists()


def test_failed_create_outcome_allows_reference_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopper, root = _state(
        tmp_path, monkeypatch, phase="creating", cid="", outcome=125
    )
    monkeypatch.setattr(stopper, "_find_named_container", lambda _reference: None)

    assert stopper.stop_residual_container(root) == (False, True)
    assert not (root / "container-23.json").exists()
    assert not (root / "container-23.cid").exists()
    assert not (root / "container-23.outcome.json").exists()


def test_successful_create_outcome_without_remaining_container_is_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopper, root = _state(
        tmp_path, monkeypatch, phase="creating", cid="", outcome=0
    )
    monkeypatch.setattr(stopper, "_find_named_container", lambda _reference: None)

    assert stopper.stop_residual_container(root) == (False, True)
    assert not (root / "container-23.json").exists()


def test_partial_cid_with_exact_named_container_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopper, root = _state(
        tmp_path, monkeypatch, phase="creating", cid="abc", outcome=None
    )
    container_id = "a" * 64
    observed = iter((container_id, None))
    monkeypatch.setattr(
        stopper, "_find_named_container", lambda _reference: next(observed)
    )
    removals: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        removals.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(stopper.subprocess, "run", fake_run)

    assert stopper.stop_residual_container(root) == (True, True)
    assert any(command[-1] == container_id for command in removals)
    assert not (root / "container-23.json").exists()


def test_malformed_cid_is_not_an_uncommitted_cid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopper, root = _state(
        tmp_path, monkeypatch, phase="creating", cid="not-a-cid", outcome=1
    )

    with pytest.raises(RuntimeError, match="invalid CID"):
        stopper.stop_residual_container(root)


def test_creator_group_detects_and_terminates_descendant_after_leader_exit(
    tmp_path: Path,
) -> None:
    stopper = _load_stopper()
    process = subprocess.Popen(
        [
            "setsid",
            "/bin/bash",
            "-c",
            "/bin/sleep 30 & printf '%s\\n' \"$!\"; wait",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child_pid = 0
    try:
        assert process.stdout is not None
        child_pid = int(process.stdout.readline().strip())
        identity = None
        for _ in range(20):
            identity = stopper._proc_identity(process.pid)
            if identity is not None and identity[:2] == (process.pid, process.pid):
                break
            time.sleep(0.025)
        assert identity is not None
        assert identity[:2] == (process.pid, process.pid)
        reference = stopper.CreatorReference(
            container_name="kor-travel-map-c7-e2e-99",
            creator_pid=process.pid,
            creator_pgid=process.pid,
            creator_sid=process.pid,
            creator_start_ticks=identity[2],
            phase="creating",
            runtime=str(tmp_path / "runtime.A1b2C3"),
        )
        process.kill()
        process.wait(timeout=3)

        assert stopper._creator_matches(reference) is True
        stopper._terminate_creator(reference)
        assert stopper._creator_matches(reference) is False
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        if child_pid > 1:
            with contextlib.suppress(OSError):
                subprocess.run(
                    ["kill", "-KILL", str(child_pid)],
                    check=False,
                    capture_output=True,
                    timeout=3,
                )

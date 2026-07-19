#!/usr/bin/env python3
"""SIGKILL 뒤 남은 C7 Docker creator/container만 안전하게 중지한다."""

from __future__ import annotations

import fcntl
import json
import os
import re
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final

STATE_ROOT: Final = Path("/var/lib/kor-travel-map/c7-prod-live-e2e")
_REFERENCE_NAME: Final = re.compile(r"^container-\d+\.json$")
_CID_NAME: Final = re.compile(r"^container-\d+\.cid$")
_CONTAINER_NAME: Final = re.compile(r"^kor-travel-map-c7-e2e-\d+$")


@dataclass(frozen=True)
class CreatorReference:
    container_name: str
    creator_pid: int
    creator_pgid: int
    creator_sid: int
    creator_start_ticks: int
    phase: str
    runtime: str


def _safe_entry(path: Path, *, directory: bool) -> bool:
    try:
        observed = path.lstat()
    except OSError:
        return False
    return (
        (stat.S_ISDIR(observed.st_mode) if directory else stat.S_ISREG(observed.st_mode))
        and not path.is_symlink()
        and observed.st_uid == 0
        and observed.st_gid == 0
        and stat.S_IMODE(observed.st_mode) == (0o700 if directory else 0o600)
    )


def _read_root_file(path: Path, *, limit: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        observed = os.fstat(fd)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != 0
            or observed.st_gid != 0
            or stat.S_IMODE(observed.st_mode) != 0o600
            or observed.st_size > limit
        ):
            raise RuntimeError("unsafe root file")
        payload = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if len(payload) > limit:
        raise RuntimeError("oversized root file")
    return payload


def _read_reference(path: Path) -> CreatorReference:
    try:
        value = json.loads(_read_root_file(path, limit=4096))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("invalid creator reference") from error
    expected_keys = {
        "container_name",
        "creator_pgid",
        "creator_pid",
        "creator_sid",
        "creator_start_ticks",
        "phase",
        "runtime",
        "version",
    }
    if not isinstance(value, dict) or set(value) != expected_keys or value["version"] != 1:
        raise RuntimeError("invalid creator reference shape")
    if (
        not isinstance(value["container_name"], str)
        or _CONTAINER_NAME.fullmatch(value["container_name"]) is None
        or type(value["creator_pid"]) is not int
        or type(value["creator_pgid"]) is not int
        or type(value["creator_sid"]) is not int
        or type(value["creator_start_ticks"]) is not int
        or value["phase"] not in {"creating", "created"}
        or not isinstance(value["runtime"], str)
    ):
        raise RuntimeError("invalid creator reference values")
    creator_values = (
        value["creator_pid"],
        value["creator_pgid"],
        value["creator_sid"],
        value["creator_start_ticks"],
    )
    if (
        value["phase"] == "creating"
        and not (
            value["creator_pid"] > 1
            and value["creator_pgid"] == value["creator_pid"]
            and value["creator_sid"] == value["creator_pid"]
            and value["creator_start_ticks"] > 0
        )
    ) or (value["phase"] == "created" and creator_values != (0, 0, 0, 0)):
        raise RuntimeError("invalid creator phase identity")
    runtime = Path(value["runtime"])
    if (
        runtime.parent != STATE_ROOT
        or not re.fullmatch(r"runtime\.[A-Za-z0-9]{6}", runtime.name)
        or not _safe_entry(runtime, directory=True)
    ):
        raise RuntimeError("unsafe referenced runtime")
    return CreatorReference(
        container_name=value["container_name"],
        creator_pid=value["creator_pid"],
        creator_pgid=value["creator_pgid"],
        creator_sid=value["creator_sid"],
        creator_start_ticks=value["creator_start_ticks"],
        phase=value["phase"],
        runtime=value["runtime"],
    )


def _read_cid(path: Path) -> str | None:
    try:
        payload = _read_root_file(path, limit=256).decode("ascii").strip()
    except UnicodeDecodeError as error:
        raise RuntimeError("invalid CID") from error
    if re.fullmatch(r"[0-9a-f]{64}", payload) is not None:
        return payload
    # creator가 CID 출력 파일을 열었지만 daemon 응답을 아직 쓰지 않은 create gap이다.
    if len(payload) < 64 and re.fullmatch(r"[0-9a-f]*", payload) is not None:
        return None
    raise RuntimeError("invalid CID")


def _proc_identity(pid: int) -> tuple[int, int, int, str] | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
        fields = raw[raw.rfind(")") + 2 :].split()
        if len(fields) <= 19:
            return None
        return (int(fields[2]), int(fields[3]), int(fields[19]), fields[0])
    except (FileNotFoundError, OSError, ValueError):
        return None


def _creator_group_members(reference: CreatorReference) -> list[int]:
    leader = _proc_identity(reference.creator_pid)
    if leader is not None and leader[:3] != (
        reference.creator_pgid,
        reference.creator_sid,
        reference.creator_start_ticks,
    ):
        raise RuntimeError("creator leader identity was reused")
    members: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        identity = _proc_identity(int(entry.name))
        if identity is not None and identity[3] != "Z" and identity[:2] == (
            reference.creator_pgid,
            reference.creator_sid,
        ):
            members.append(int(entry.name))
    return members


def _creator_matches(reference: CreatorReference) -> bool:
    return bool(_creator_group_members(reference))


def _terminate_creator(reference: CreatorReference) -> None:
    if reference.phase != "creating":
        return
    if not _creator_matches(reference):
        return
    os.killpg(reference.creator_pgid, signal.SIGTERM)
    for _ in range(40):
        if not _creator_matches(reference):
            return
        time.sleep(0.25)
    if _creator_matches(reference):
        os.killpg(reference.creator_pgid, signal.SIGKILL)
    for _ in range(40):
        if not _creator_matches(reference):
            return
        time.sleep(0.25)
    raise RuntimeError("Docker creator did not terminate")


def _run_json(command: list[str], *, timeout: int = 10) -> object:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return json.loads(completed.stdout)


def _inspect_validated_container(
    container_id: str, reference: CreatorReference
) -> str | None:
    listed = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"id={container_id}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    if not ids:
        return None
    if ids != [container_id]:
        raise RuntimeError("container identity is ambiguous")
    records = _run_json(["docker", "container", "inspect", "--", container_id])
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise RuntimeError("container inspect shape")
    record = records[0]
    config = record.get("Config")
    mounts = record.get("Mounts")
    if not isinstance(config, dict) or not isinstance(mounts, list):
        raise RuntimeError("container inspect contract")
    labels = config.get("Labels")
    bind_mounts = {
        item.get("Source")
        for item in mounts
        if isinstance(item, dict)
        and item.get("Type") == "bind"
        and item.get("RW") is True
        and item.get("Source") == item.get("Destination")
    }
    if (
        record.get("Id") != container_id
        or not isinstance(labels, dict)
        or labels.get("io.kortravelmap.c7.runner") != "prod-live-e2e"
        or record.get("Name") != f"/{reference.container_name}"
        or bind_mounts != {reference.runtime}
    ):
        raise RuntimeError("container ownership contract")
    return container_id


def _find_named_container(reference: CreatorReference) -> str | None:
    listed = subprocess.run(
        [
            "docker",
            "container",
            "ls",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter",
            f"name=^/{reference.container_name}$",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    if not ids:
        return None
    if len(ids) != 1 or re.fullmatch(r"[0-9a-f]{64}", ids[0]) is None:
        raise RuntimeError("container identity is ambiguous")
    return _inspect_validated_container(ids[0], reference)


def _read_create_outcome(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        value = json.loads(_read_root_file(path, limit=1024))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("invalid create outcome") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"phase", "status", "version"}
        or value["phase"] != "create"
        or type(value["status"]) is not int
        or not 0 <= value["status"] <= 255
        or value["version"] != 1
    ):
        raise RuntimeError("invalid create outcome shape")
    return value["status"]


def stop_residual_container(root: Path) -> tuple[bool, bool]:
    if root != STATE_ROOT or not _safe_entry(root, directory=True):
        raise RuntimeError("unsafe state root")
    blocker = root / "BLOCKED.json"
    if not _safe_entry(blocker, directory=False):
        raise RuntimeError("safe BLOCKED state is required")
    lock_path = root / "orchestrator.lock"
    if not _safe_entry(lock_path, directory=False):
        raise RuntimeError("unsafe orchestrator lock")
    lock_fd = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        reference_paths = [
            path for path in root.iterdir() if _REFERENCE_NAME.fullmatch(path.name)
        ]
        cid_paths = [path for path in root.iterdir() if _CID_NAME.fullmatch(path.name)]
        outcome_paths = list(root.glob("container-*.outcome.json"))
        if len(reference_paths) != 1 or len(cid_paths) > 1 or len(outcome_paths) > 1:
            raise RuntimeError("exactly one creator reference and at most one CID are required")
        reference = _read_reference(reference_paths[0])
        if cid_paths and cid_paths[0].stem != reference_paths[0].stem:
            raise RuntimeError("CID/reference identity mismatch")
        if outcome_paths and outcome_paths[0].name != reference_paths[0].name.replace(
            ".json", ".outcome.json"
        ):
            raise RuntimeError("outcome/reference identity mismatch")
        outcome = _read_create_outcome(outcome_paths[0] if outcome_paths else None)
        recorded_cid = _read_cid(cid_paths[0]) if cid_paths else None
        if reference.phase == "created" and (recorded_cid is None or outcome != 0):
            raise RuntimeError("created reference lacks successful durable outcome/CID")
        _terminate_creator(reference)
        container_id = _find_named_container(reference)
        removed_by_cid = False
        if recorded_cid is not None:
            cid_container = _inspect_validated_container(recorded_cid, reference)
            if container_id is not None and recorded_cid != container_id:
                raise RuntimeError("CID/name identity mismatch")
            if container_id is None and cid_container is not None:
                subprocess.run(
                    ["docker", "container", "rm", "--force", "--", cid_container],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                removed_by_cid = True
        if container_id is not None:
            subprocess.run(
                ["docker", "container", "rm", "--force", "--", container_id],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            removed_by_cid = True
        if _find_named_container(reference) is not None:
            raise RuntimeError("container remains after exact removal")
        create_resolved = (
            reference.phase == "created"
            or recorded_cid is not None
            or container_id is not None
            or outcome is not None
        )
        if not create_resolved:
            return (False, False)
        container_removed = removed_by_cid
        for path in (*cid_paths, *outcome_paths, reference_paths[0]):
            path.unlink()
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(root_fd)
        finally:
            os.close(root_fd)
        return (container_removed, True)
    finally:
        os.close(lock_fd)


def main() -> int:
    if os.geteuid() != 0:
        print(json.dumps({"error": "root_required"}, sort_keys=True))
        return 2
    try:
        container_removed, reference_removed = stop_residual_container(STATE_ROOT)
    except (OSError, RuntimeError, subprocess.SubprocessError):
        print(json.dumps({"error": "recovery_refused"}, sort_keys=True))
        return 1
    print(
        json.dumps(
            {
                "container_removed": container_removed,
                "reference_removed": reference_removed,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if reference_removed else 4


if __name__ == "__main__":
    raise SystemExit(main())

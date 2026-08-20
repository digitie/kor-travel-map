#!/usr/bin/env python3
"""C7 production live E2E durable state를 값 노출 없이 감사한다."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

STATE_ROOT: Final = Path("/var/lib/kor-travel-map/c7-prod-live-e2e")
_JOURNAL_PREFIXES: Final = ("run", "schedule", "kma", "poi")
_SAFE_PHASES: Final = {
    "orchestrator_pending",
    "orchestrator_preflight",
    "orchestrator_running",
    "restored",
    "restore_failed",
    "snapshotted",
    "stopping",
    "stopped_quiescent",
    "starting",
    "running",
    "restoring",
}
_EVIDENCE_RUN_PATTERN: Final = re.compile(r"^run-\d{8}T\d{6}Z-\d+$")
_CID_REFERENCE_PATTERN: Final = re.compile(r"^container-(\d+)\.cid$")
_CREATOR_REFERENCE_PATTERN: Final = re.compile(r"^container-(\d+)\.json$")
_CREATE_OUTCOME_PATTERN: Final = re.compile(r"^container-(\d+)\.outcome\.json$")
_CONTAINER_NAME_PATTERN: Final = re.compile(r"^kor-travel-map-c7-e2e-\d+$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_RUNTIME_JOURNALS: Final = {
    "sensor.json": "run",
    "schedule.json": "schedule",
    "kma.json": "kma",
    "poi.json": "poi",
}


@dataclass(frozen=True)
class AuditResult:
    state_root_exists: bool
    state_root_safe: bool
    active_lock: bool
    blocked: bool
    journals: dict[str, int]
    journal_phases: dict[str, dict[str, int]]
    runtime_directories: int
    temporary_files: int
    container_reference_files: int
    active_creator_processes: int
    running_containers: int
    evidence_directories: int
    unsafe_entries: int
    unexpected_entries: int
    requires_recovery: bool


def _safe_phase(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return "invalid"
    if not isinstance(payload, dict):
        return "invalid"
    phase = payload.get("phase")
    return phase if isinstance(phase, str) and phase in _SAFE_PHASES else "unknown"


def _safe_entry(path: Path, *, directory: bool) -> bool:
    try:
        observed = path.lstat()
    except OSError:
        return False
    expected_kind = stat.S_ISDIR if directory else stat.S_ISREG
    expected_mode = 0o700 if directory else 0o600
    return (
        expected_kind(observed.st_mode)
        and not path.is_symlink()
        and observed.st_uid == 0
        and observed.st_gid == 0
        and stat.S_IMODE(observed.st_mode) == expected_mode
    )


def _lock_is_active(lock_path: Path) -> bool:
    if not lock_path.exists():
        return False
    fd = os.open(lock_path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _valid_evidence_manifest(run: Path) -> bool:
    manifest_path = run / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    keys = {
        "alembic_head",
        "pinned_runtime_manifest_sha256",
        "rebuild_journal_sha256",
        "files",
        "finished_at",
        "host_attestation_sha256",
        "orchestrator_verified",
        "playwright_image_id",
        "repository_commit",
        "status",
        "version",
    }
    if not isinstance(manifest, dict) or set(manifest) != keys:
        return False
    if (
        manifest["version"] != 1
        or type(manifest["status"]) is not int
        or type(manifest["orchestrator_verified"]) is not bool
        or not isinstance(manifest["alembic_head"], str)
        or not re.fullmatch(r"[0-9A-Za-z_]+", manifest["alembic_head"])
        or not isinstance(manifest["repository_commit"], str)
        or re.fullmatch(r"[0-9a-f]{40}", manifest["repository_commit"]) is None
        or not isinstance(manifest["playwright_image_id"], str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["playwright_image_id"])
        is None
        or not isinstance(manifest["pinned_runtime_manifest_sha256"], str)
        or _SHA256_PATTERN.fullmatch(manifest["pinned_runtime_manifest_sha256"]) is None
        or not isinstance(manifest["rebuild_journal_sha256"], str)
        or _SHA256_PATTERN.fullmatch(manifest["rebuild_journal_sha256"]) is None
        or not isinstance(manifest["host_attestation_sha256"], str)
        or _SHA256_PATTERN.fullmatch(manifest["host_attestation_sha256"]) is None
        or not isinstance(manifest["finished_at"], str)
        or not manifest["finished_at"]
        or not isinstance(manifest["files"], list)
    ):
        return False

    observed_files: dict[str, tuple[str, int]] = {}
    for path in run.rglob("*"):
        if path == manifest_path or not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(run).as_posix()
        observed_files[relative] = (
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_size,
        )
    declared_files: dict[str, tuple[str, int]] = {}
    for item in manifest["files"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size"}:
            return False
        path_value = item["path"]
        if (
            not isinstance(path_value, str)
            or not path_value
            or Path(path_value).is_absolute()
            or ".." in Path(path_value).parts
            or path_value in declared_files
            or not isinstance(item["sha256"], str)
            or _SHA256_PATTERN.fullmatch(item["sha256"]) is None
            or type(item["size"]) is not int
            or item["size"] < 0
        ):
            return False
        declared_files[path_value] = (item["sha256"], item["size"])
    if declared_files != observed_files:
        return False
    # evidence archive 안의 세 attested document가 manifest의 digest와 각각 맞아야
    # "이 실행이 무엇을 근거로 통과했는가"가 사후에도 재구성된다.
    attested = (
        ("runtime-attestation.json", "host_attestation_sha256"),
        ("pinned-runtime-generation.json", "pinned_runtime_manifest_sha256"),
        ("pinned-runtime-rebuild.json", "rebuild_journal_sha256"),
    )
    return all(
        observed_files.get(name) is not None
        and observed_files[name][0] == manifest[digest_key]
        for name, digest_key in attested
    )


def _audit_evidence_tree(root: Path) -> tuple[int, int, int]:
    """evidence run 수와 unsafe/unexpected entry 수를 반환한다."""

    run_directories = 0
    unsafe_entries = 0
    unexpected_entries = 0
    if not _safe_entry(root, directory=True):
        return (0, 1, 0)
    for run in root.iterdir():
        if not _EVIDENCE_RUN_PATTERN.fullmatch(run.name):
            unexpected_entries += 1
        if not _safe_entry(run, directory=True):
            unsafe_entries += 1
            continue
        run_directories += 1
        manifest_count = 0
        for entry in run.rglob("*"):
            if entry.is_symlink():
                unsafe_entries += 1
                continue
            if entry.is_dir():
                if not _safe_entry(entry, directory=True):
                    unsafe_entries += 1
                continue
            if not _safe_entry(entry, directory=False):
                unsafe_entries += 1
            if entry.parent == run and entry.name == "manifest.json":
                manifest_count += 1
        if manifest_count != 1:
            unexpected_entries += 1
        elif not _valid_evidence_manifest(run):
            unsafe_entries += 1
    return (run_directories, unsafe_entries, unexpected_entries)


def _audit_runtime_tree(
    runtime: Path,
    journals: dict[str, int],
    phases: dict[str, dict[str, int]],
) -> tuple[int, int]:
    unsafe_entries = 0
    unexpected_entries = 0
    if not _safe_entry(runtime, directory=True):
        return (1, 0)
    for entry in runtime.rglob("*"):
        if entry.is_symlink():
            unsafe_entries += 1
            continue
        relative = entry.relative_to(runtime)
        if entry.is_dir():
            if not _safe_entry(entry, directory=True):
                unsafe_entries += 1
            if len(relative.parts) == 1 and entry.name not in {"journals", "playwright"}:
                unexpected_entries += 1
            continue
        if not _safe_entry(entry, directory=False):
            unsafe_entries += 1
        if relative.parts[0] == "journals":
            if len(relative.parts) != 2 or entry.name not in _RUNTIME_JOURNALS:
                unexpected_entries += 1
                continue
            prefix = _RUNTIME_JOURNALS[entry.name]
            journals[prefix] += 1
            phase = _safe_phase(entry)
            phases[prefix][phase] = phases[prefix].get(phase, 0) + 1
        elif len(relative.parts) == 1 and entry.name == "admin-state.json":
            continue
        elif relative.parts[0] != "playwright":
            unexpected_entries += 1
    return (unsafe_entries, unexpected_entries)


def _read_creator_reference(path: Path, runtimes: set[str]) -> dict[str, object] | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            observed = os.fstat(fd)
            if (
                not stat.S_ISREG(observed.st_mode)
                or observed.st_uid != 0
                or observed.st_gid != 0
                or stat.S_IMODE(observed.st_mode) != 0o600
                or observed.st_size > 4096
            ):
                return None
            payload = os.read(fd, 4097)
        finally:
            os.close(fd)
        value = json.loads(payload)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
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
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value["version"] != 1
        or not isinstance(value["container_name"], str)
        or _CONTAINER_NAME_PATTERN.fullmatch(value["container_name"]) is None
        or type(value["creator_pid"]) is not int
        or type(value["creator_pgid"]) is not int
        or type(value["creator_sid"]) is not int
        or type(value["creator_start_ticks"]) is not int
        or value["phase"] not in {"creating", "created"}
        or not isinstance(value["runtime"], str)
        or value["runtime"] not in runtimes
    ):
        return None
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
        return None
    return value


def _proc_identity(pid: int) -> tuple[int, int, int, str] | None:
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
        fields = raw[raw.rfind(")") + 2 :].split()
        if len(fields) <= 19:
            return None
        return (int(fields[2]), int(fields[3]), int(fields[19]), fields[0])
    except (FileNotFoundError, OSError, ValueError):
        return None


def _creator_is_active(reference: dict[str, object]) -> bool:
    if reference["phase"] != "creating":
        return False
    pid = reference["creator_pid"]
    pgid = reference["creator_pgid"]
    sid = reference["creator_sid"]
    start_ticks = reference["creator_start_ticks"]
    assert all(isinstance(value, int) for value in (pid, pgid, sid, start_ticks))
    leader = _proc_identity(pid)
    if leader is not None and leader[:3] != (pgid, sid, start_ticks):
        return True
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        identity = _proc_identity(int(entry.name))
        if identity is not None and identity[3] != "Z" and identity[:2] == (pgid, sid):
            return True
    return False


def _create_outcome_status(path: Path) -> int | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            observed = os.fstat(fd)
            value = json.loads(os.read(fd, 1025))
        finally:
            os.close(fd)
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not (
        stat.S_ISREG(observed.st_mode)
        and observed.st_uid == 0
        and observed.st_gid == 0
        and stat.S_IMODE(observed.st_mode) == 0o600
        and observed.st_size <= 1024
        and isinstance(value, dict)
        and set(value) == {"phase", "status", "version"}
        and value["phase"] == "create"
        and type(value["status"]) is int
        and 0 <= value["status"] <= 255
        and value["version"] == 1
    ):
        return None
    return value["status"]


def _read_complete_cid(path: Path) -> str | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            payload = os.read(fd, 257).decode("ascii").strip()
        finally:
            os.close(fd)
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError("invalid CID file") from error
    if re.fullmatch(r"[0-9a-f]{64}", payload):
        return payload
    if len(payload) < 64 and re.fullmatch(r"[0-9a-f]*", payload):
        return None
    raise ValueError("invalid CID payload")


def _validated_container_state(
    record: object,
    *,
    expected_name: str,
    expected_runtime: str,
    expected_id: str,
) -> bool | None:
    if not isinstance(record, dict):
        return None
    try:
        labels = record["Config"]["Labels"]
        mounts = record["Mounts"]
        state = record["State"]
    except (KeyError, TypeError):
        return None
    mounted_runtimes = {
        item.get("Source")
        for item in mounts
        if isinstance(item, dict)
        and item.get("Type") == "bind"
        and item.get("RW") is True
        and item.get("Source") == item.get("Destination")
    }
    if (
        record.get("Id") != expected_id
        or record.get("Name") != f"/{expected_name}"
        or not isinstance(labels, dict)
        or labels.get("io.kortravelmap.c7.runner") != "prod-live-e2e"
        or mounted_runtimes != {expected_runtime}
        or not isinstance(state, dict)
        or type(state.get("Running")) is not bool
    ):
        return None
    return state["Running"]


def _container_running_state(
    reference: dict[str, object], cid_path: Path | None
) -> bool | None:
    name = reference["container_name"]
    runtime = reference["runtime"]
    assert isinstance(name, str)
    assert isinstance(runtime, str)
    complete_cid = _read_complete_cid(cid_path) if cid_path is not None else None
    filter_value = f"id={complete_cid}" if complete_cid else f"name=^/{name}$"
    try:
        listed = subprocess.run(
            [
                "docker",
                "container",
                "ls",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter",
                filter_value,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        if not ids:
            return False
        if len(ids) != 1 or re.fullmatch(r"[0-9a-f]{64}", ids[0]) is None:
            return None
        if complete_cid is not None and ids[0] != complete_cid:
            return None
        inspected = subprocess.run(
            ["docker", "container", "inspect", "--", ids[0]],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        records = json.loads(inspected.stdout)
        if not isinstance(records, list) or len(records) != 1:
            return None
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        return None
    return _validated_container_state(
        records[0], expected_name=name, expected_runtime=runtime, expected_id=ids[0]
    )


def audit_state_root(root: Path) -> AuditResult:
    try:
        root.lstat()
    except FileNotFoundError:
        return AuditResult(
            state_root_exists=False,
            state_root_safe=False,
            active_lock=False,
            blocked=False,
            journals={prefix: 0 for prefix in _JOURNAL_PREFIXES},
            journal_phases={prefix: {} for prefix in _JOURNAL_PREFIXES},
            runtime_directories=0,
            temporary_files=0,
            container_reference_files=0,
            active_creator_processes=0,
            running_containers=0,
            evidence_directories=0,
            unsafe_entries=0,
            unexpected_entries=0,
            requires_recovery=False,
        )

    state_root_safe = _safe_entry(root, directory=True)
    journals = {prefix: 0 for prefix in _JOURNAL_PREFIXES}
    phases: dict[str, dict[str, int]] = {
        prefix: {} for prefix in _JOURNAL_PREFIXES
    }
    runtime_directories = 0
    temporary_files = 0
    evidence_directories = 0
    container_reference_files = 0
    active_creator_processes = 0
    running_containers = 0
    unsafe_entries = 0
    unexpected_entries = 0

    if not state_root_safe:
        return AuditResult(
            state_root_exists=True,
            state_root_safe=False,
            active_lock=False,
            blocked=False,
            journals=journals,
            journal_phases=phases,
            runtime_directories=0,
            temporary_files=0,
            container_reference_files=0,
            active_creator_processes=0,
            running_containers=0,
            evidence_directories=0,
            unsafe_entries=1,
            unexpected_entries=0,
            requires_recovery=True,
        )

    runtime_paths: set[str] = set()
    cid_paths: dict[str, Path] = {}
    creator_paths: dict[str, Path] = {}
    outcome_paths: dict[str, Path] = {}
    for entry in root.iterdir():
        name = entry.name
        directory = entry.is_dir() and not entry.is_symlink()
        known = False
        if name in {"BLOCKED.json", "orchestrator.lock"}:
            known = True
        elif name == "evidence":
            known = True
            if directory:
                (
                    evidence_directories,
                    evidence_unsafe,
                    evidence_unexpected,
                ) = _audit_evidence_tree(entry)
                unsafe_entries += evidence_unsafe
                unexpected_entries += evidence_unexpected
        elif name.startswith("runtime."):
            known = True
            runtime_directories += int(directory)
            if directory:
                runtime_paths.add(str(entry))
                runtime_unsafe, runtime_unexpected = _audit_runtime_tree(
                    entry, journals, phases
                )
                unsafe_entries += runtime_unsafe
                unexpected_entries += runtime_unexpected
        elif (cid_match := _CID_REFERENCE_PATTERN.fullmatch(name)) is not None:
            known = True
            container_reference_files += int(not directory)
            cid_paths[cid_match.group(1)] = entry
        elif (creator_match := _CREATOR_REFERENCE_PATTERN.fullmatch(name)) is not None:
            known = True
            container_reference_files += int(not directory)
            creator_paths[creator_match.group(1)] = entry
        elif (outcome_match := _CREATE_OUTCOME_PATTERN.fullmatch(name)) is not None:
            known = True
            temporary_files += int(not directory)
            outcome_paths[outcome_match.group(1)] = entry
        elif name.startswith(
            (
                ".state.",
                "cap.",
                "attestation-",
                "pinned-runtime-generation-",
                "pinned-runtime-rebuild-",
            )
        ):
            known = True
            temporary_files += int(not directory)
        else:
            for prefix in _JOURNAL_PREFIXES:
                if name.startswith(f"{prefix}-") and name.endswith(".json"):
                    known = True
                    journals[prefix] += 1
                    phase = _safe_phase(entry)
                    phases[prefix][phase] = phases[prefix].get(phase, 0) + 1
                    break
        if not known:
            unexpected_entries += 1
        if name == "evidence" or name.startswith("runtime."):
            safe = _safe_entry(entry, directory=True)
        else:
            safe = _safe_entry(entry, directory=False)
        if not safe:
            unsafe_entries += 1

    orphan_cids = set(cid_paths) - set(creator_paths)
    orphan_outcomes = set(outcome_paths) - set(creator_paths)
    unsafe_entries += len(orphan_cids) + len(orphan_outcomes)
    outcome_statuses: dict[str, int] = {}
    for identity, outcome_path in outcome_paths.items():
        outcome_status = _create_outcome_status(outcome_path)
        if outcome_status is None:
            unsafe_entries += 1
        else:
            outcome_statuses[identity] = outcome_status
    for identity, creator_path in creator_paths.items():
        if not _safe_entry(creator_path, directory=False):
            continue
        reference = _read_creator_reference(creator_path, runtime_paths)
        if reference is None:
            unsafe_entries += 1
            continue
        if _creator_is_active(reference):
            active_creator_processes += 1
        cid_path = cid_paths.get(identity)
        if cid_path is not None and not _safe_entry(cid_path, directory=False):
            continue
        if reference["phase"] == "created":
            try:
                complete_cid = (
                    _read_complete_cid(cid_path) if cid_path is not None else None
                )
            except ValueError:
                complete_cid = None
            if outcome_statuses.get(identity) != 0 or complete_cid is None:
                unsafe_entries += 1
        try:
            running = _container_running_state(reference, cid_path)
        except ValueError:
            unsafe_entries += 1
            continue
        if running is None:
            unsafe_entries += 1
        elif running:
            running_containers += 1

    lock_path = root / "orchestrator.lock"
    active_lock = False
    if lock_path.exists() and _safe_entry(lock_path, directory=False):
        try:
            active_lock = _lock_is_active(lock_path)
        except OSError:
            unsafe_entries += 1

    requires_recovery = (
        (root / "BLOCKED.json").exists()
        or (root / "BLOCKED.json").is_symlink()
        or runtime_directories > 0
        or temporary_files > 0
        or container_reference_files > 0
        or any(journals.values())
    )
    return AuditResult(
        state_root_exists=True,
        state_root_safe=state_root_safe,
        active_lock=active_lock,
        blocked=(root / "BLOCKED.json").exists()
        or (root / "BLOCKED.json").is_symlink(),
        journals=journals,
        journal_phases=phases,
        runtime_directories=runtime_directories,
        temporary_files=temporary_files,
        container_reference_files=container_reference_files,
        active_creator_processes=active_creator_processes,
        running_containers=running_containers,
        evidence_directories=evidence_directories,
        unsafe_entries=unsafe_entries,
        unexpected_entries=unexpected_entries,
        requires_recovery=requires_recovery,
    )


def main() -> int:
    if os.geteuid() != 0:
        print(json.dumps({"error": "root_required"}, sort_keys=True))
        return 2
    result = audit_state_root(STATE_ROOT)
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    if result.active_lock or result.active_creator_processes > 0 or result.running_containers > 0:
        return 3
    if not result.state_root_exists:
        return 0
    if (
        not result.state_root_safe
        or result.unsafe_entries > 0
        or result.unexpected_entries > 0
    ):
        return 5
    if result.requires_recovery:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

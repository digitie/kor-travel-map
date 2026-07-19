#!/usr/bin/env python3
"""Targeted admin live lane의 root snapshot·durable state helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final

_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{15,79}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_C7_MODULE_RELATIVE: Final[str] = "scripts/lib/c7_prod_attestation.py"
_C7_BASE: Final[Path] = Path("/usr/local/lib/kor-travel-map/c7-runner")


def _owned_ids(run_id: str) -> list[str]:
    prefix = f"e2e_live_acceptance::{run_id}"
    return [
        f"{prefix}::marker::draft",
        f"{prefix}::marker::inactive",
        f"{prefix}::marker::hidden",
        f"{prefix}::correction",
        f"{prefix}::weather",
        f"{prefix}::price",
        f"{prefix}::search::alpha",
        f"{prefix}::search::beta",
    ]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _recorded_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.fchown(descriptor, 0, 0)
        body = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
        offset = 0
        while offset < len(body):
            offset += os.write(descriptor, body[offset:])
        os.fsync(descriptor)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chown(path, 0, 0)
    os.chmod(path, 0o600)
    _fsync_directory(path.parent)


def _read_regular(path: Path, mode: int, limit: int = 65_536) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        observed = os.fstat(descriptor)
        body = os.read(descriptor, limit)
        if os.read(descriptor, 1):
            raise ValueError("file is too large")
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != 0
        or observed.st_gid != 0
        or stat.S_IMODE(observed.st_mode) != mode
    ):
        raise ValueError("root file metadata mismatch")
    return body


def _read_root_json(path: Path) -> dict[str, Any]:
    payload = json.loads(_read_regular(path, 0o600))
    if not isinstance(payload, dict):
        raise ValueError("state payload must be an object")
    return payload


def _blocked_payload(run_id: str, attempt: int, phase: str, status: str) -> dict[str, Any]:
    if _RUN_ID_RE.fullmatch(run_id) is None or attempt < 0:
        raise ValueError("invalid blocked identity")
    return {
        "owned_feature_ids": _owned_ids(run_id),
        "phase": phase,
        "recorded_at": _recorded_at(),
        "recovery_attempt": attempt,
        "run_id": run_id,
        "status": status,
        "version": 2,
    }


def _validated_blocked(path: Path) -> dict[str, Any]:
    payload = _read_root_json(path)
    if (
        set(payload)
        != {
            "owned_feature_ids",
            "phase",
            "recorded_at",
            "recovery_attempt",
            "run_id",
            "status",
            "version",
        }
        or payload.get("version") != 2
        or not isinstance(payload.get("run_id"), str)
        or _RUN_ID_RE.fullmatch(payload["run_id"]) is None
        or payload.get("owned_feature_ids") != _owned_ids(payload["run_id"])
        or type(payload.get("recovery_attempt")) is not int
        or payload["recovery_attempt"] < 0
        or not isinstance(payload.get("phase"), str)
        or not isinstance(payload.get("status"), str)
        or not isinstance(payload.get("recorded_at"), str)
    ):
        raise ValueError("invalid BLOCKED state")
    return payload


def _write_blocked(args: argparse.Namespace) -> None:
    if args.path.exists():
        current = _validated_blocked(args.path)
        if (
            current["run_id"] != args.run_id
            or current["recovery_attempt"] != args.recovery_attempt
        ):
            raise ValueError("blocked identity changed")
    elif args.recovery_attempt != 0:
        raise ValueError("initial recovery attempt must be zero")
    _atomic_write(
        args.path,
        _blocked_payload(args.run_id, args.recovery_attempt, args.phase, args.status),
    )


def _begin_recovery(args: argparse.Namespace) -> None:
    current = _validated_blocked(args.path)
    attempt = int(current["recovery_attempt"]) + 1
    _atomic_write(
        args.path,
        _blocked_payload(current["run_id"], attempt, "recovery_claimed", "blocked"),
    )
    print(current["run_id"])
    print(attempt)


def _clear_blocked(args: argparse.Namespace) -> None:
    _validated_blocked(args.path)
    os.unlink(args.path)
    _fsync_directory(args.path.parent)


def _write_result(args: argparse.Namespace) -> None:
    if (
        _RUN_ID_RE.fullmatch(args.run_id) is None
        or args.recovery_attempt < 0
        or _SHA256_RE.fullmatch(args.compatible_pair_sha256) is None
        or _SHA256_RE.fullmatch(args.host_attestation_sha256) is None
    ):
        raise ValueError("invalid result identity")
    _atomic_write(
        args.path,
        {
            "compatible_pair_manifest_sha256": args.compatible_pair_sha256,
            "host_attestation_sha256": args.host_attestation_sha256,
            "owned_feature_id_sha256": [_sha256(value) for value in _owned_ids(args.run_id)],
            "phase": args.phase,
            "recorded_at": _recorded_at(),
            "recovery_attempt": args.recovery_attempt,
            "run_id_sha256": _sha256(args.run_id),
            "status": args.status,
            "version": 2,
        },
    )


def _write_lifecycle(args: argparse.Namespace) -> None:
    if (
        _TOKEN_RE.fullmatch(args.actor) is None
        or _TOKEN_RE.fullmatch(args.kind) is None
        or _TOKEN_RE.fullmatch(args.operation) is None
        or _TOKEN_RE.fullmatch(args.phase) is None
        or args.attempt < 0
        or (args.container_id and re.fullmatch(r"[0-9a-f]{64}", args.container_id) is None)
        or (args.exit_code is not None and not 0 <= args.exit_code <= 255)
    ):
        raise ValueError("invalid lifecycle event")
    _atomic_write(
        args.path,
        {
            "actor": args.actor,
            "attempt": args.attempt,
            "container_id_sha256": _sha256(args.container_id) if args.container_id else None,
            "container_name_sha256": _sha256(args.container_name),
            "exit_code": args.exit_code,
            "kind": args.kind,
            "operation": args.operation,
            "phase": args.phase,
            "recorded_at": _recorded_at(),
            "version": 1,
        },
    )


def _process_start_ticks(pid: int) -> int | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
    except (FileNotFoundError, ProcessLookupError):
        return None
    if len(fields) < 22:
        raise ValueError("process stat shape mismatch")
    return int(fields[21])


def _write_active(args: argparse.Namespace) -> None:
    if (
        _SHA256_RE.fullmatch(args.run_key) is None
        or _TOKEN_RE.fullmatch(args.actor) is None
        or _TOKEN_RE.fullmatch(args.operation) is None
        or _TOKEN_RE.fullmatch(args.phase) is None
        or args.attempt < 0
        or min(args.pid, args.pgid, args.sid, args.start_ticks) <= 0
        or (args.container_id and re.fullmatch(r"[0-9a-f]{64}", args.container_id) is None)
        or (args.exit_code is not None and not 0 <= args.exit_code <= 255)
        or args.status not in {"active", "failed", "succeeded"}
    ):
        raise ValueError("invalid active operation")
    _atomic_write(
        args.path,
        {
            "actor": args.actor,
            "attempt": args.attempt,
            "container_id": args.container_id,
            "container_name": args.container_name,
            "exit_code": args.exit_code,
            "operation": args.operation,
            "phase": args.phase,
            "recorded_at": _recorded_at(),
            "run_key": args.run_key,
            "status": args.status,
            "supervisor_pgid": args.pgid,
            "supervisor_pid": args.pid,
            "supervisor_sid": args.sid,
            "supervisor_start_ticks": args.start_ticks,
            "version": 1,
        },
    )


def _validated_active(path: Path) -> dict[str, Any]:
    payload = _read_root_json(path)
    if (
        set(payload)
        != {
            "actor",
            "attempt",
            "container_id",
            "container_name",
            "exit_code",
            "operation",
            "phase",
            "recorded_at",
            "run_key",
            "status",
            "supervisor_pgid",
            "supervisor_pid",
            "supervisor_sid",
            "supervisor_start_ticks",
            "version",
        }
        or payload.get("version") != 1
        or not isinstance(payload.get("run_key"), str)
        or _SHA256_RE.fullmatch(payload["run_key"]) is None
        or not isinstance(payload.get("container_name"), str)
        or (
            payload.get("container_id")
            and (
                not isinstance(payload["container_id"], str)
                or re.fullmatch(r"[0-9a-f]{64}", payload["container_id"]) is None
            )
        )
        or type(payload.get("supervisor_pid")) is not int
        or type(payload.get("supervisor_start_ticks")) is not int
    ):
        raise ValueError("active operation shape mismatch")
    return payload


def _read_terminal_active(args: argparse.Namespace) -> None:
    payload = _validated_active(args.path)
    if payload["run_key"] != args.run_key or payload.get("phase") != "terminal":
        raise ValueError("active operation is not terminal")
    if _process_start_ticks(payload["supervisor_pid"]) == payload["supervisor_start_ticks"]:
        raise ValueError("terminal supervisor is still alive")
    print(payload["container_id"])
    print(payload["container_name"])
    print(payload["exit_code"] if payload["exit_code"] is not None else -1)


def _clear_active(args: argparse.Namespace) -> None:
    payload = _validated_active(args.path)
    if payload.get("phase") != "terminal":
        raise ValueError("non-terminal active operation cannot be cleared")
    os.unlink(args.path)
    _fsync_directory(args.path.parent)


def _write_probe(args: argparse.Namespace) -> None:
    if args.result != "cursor-secret-missing" or args.exit_code != 1:
        raise ValueError("invalid cursor probe result")
    _atomic_write(
        args.path,
        {
            "exit_code": args.exit_code,
            "phase": "entrypoint-pre-migration",
            "result": args.result,
            "version": 1,
        },
    )


def _run_key(args: argparse.Namespace) -> None:
    if _RUN_ID_RE.fullmatch(args.run_id) is None:
        raise ValueError("invalid run ID")
    print(_sha256(args.run_id))


def _file_sha256(path: Path, mode: int = 0o555) -> str:
    return hashlib.sha256(_read_regular(path, mode, 16 * 1024 * 1024)).hexdigest()


def _safe_ancestors(path: Path) -> None:
    for candidate in [path, *path.parents]:
        observed = os.lstat(candidate)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or stat.S_ISLNK(observed.st_mode)
            or observed.st_uid != 0
            or observed.st_gid != 0
            or stat.S_IMODE(observed.st_mode) & 0o022
        ):
            raise ValueError("unsafe root ancestor")


def _validate_source(args: argparse.Namespace) -> None:
    root = args.root.resolve(strict=True)
    if root != args.root or root != Path(args.expected_root):
        raise ValueError("snapshot root mismatch")
    if args.manifest.parent.resolve(strict=True) != root:
        raise ValueError("manifest parent mismatch")
    _safe_ancestors(root)
    if stat.S_IMODE(os.lstat(root).st_mode) != 0o555:
        raise ValueError("snapshot root mode mismatch")
    required = set(args.required_file)
    if set(os.listdir(root)) != required | {args.manifest.name}:
        raise ValueError("snapshot exact file set mismatch")
    manifest = json.loads(_read_regular(args.manifest, 0o444))
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"files", "repository_commit", "version"}
        or manifest.get("version") != 1
        or manifest.get("repository_commit") != args.expected_commit
        or _COMMIT_RE.fullmatch(args.expected_commit) is None
        or not isinstance(manifest.get("files"), dict)
        or set(manifest["files"]) != required
    ):
        raise ValueError("manifest contract mismatch")
    for name, expected_hash in manifest["files"].items():
        if not isinstance(expected_hash, str) or _SHA256_RE.fullmatch(expected_hash) is None:
            raise ValueError("manifest hash mismatch")
        if _file_sha256(root / name) != expected_hash:
            raise ValueError("snapshot file hash mismatch")


def _validate_c7_module(args: argparse.Namespace) -> None:
    if _COMMIT_RE.fullmatch(args.expected_commit) is None:
        raise ValueError("invalid expected commit")
    expected = _C7_BASE / args.expected_commit / _C7_MODULE_RELATIVE
    if args.module != expected:
        raise ValueError("C7 module path mismatch")
    _safe_ancestors(args.module.parent)
    attestation = json.loads(_read_regular(args.attestation, 0o600))
    orchestrator_files = attestation.get("orchestrator_files")
    if (
        attestation.get("version") != 3
        or attestation.get("repository_commit") != args.expected_commit
        or not isinstance(orchestrator_files, dict)
        or set(orchestrator_files)
        != {
            "scripts/audit-c7-prod-live-state.py",
            "scripts/lib/c7-prod-runner-lifecycle.sh",
            _C7_MODULE_RELATIVE,
            "scripts/run-c7-prod-live-e2e.sh",
        }
        or orchestrator_files.get(_C7_MODULE_RELATIVE) != _file_sha256(args.module)
    ):
        raise ValueError("C7 module bootstrap mismatch")


def _validate_direct(path: Path, action: str, counts: dict[str, int], references: int) -> int:
    payload = _read_root_json(path)
    if (
        set(payload)
        != {
            "action",
            "counts",
            "foreign_key_constraints_checked",
            "foreign_key_references",
            "version",
        }
        or payload.get("version") != 1
        or payload.get("action") != action
        or payload.get("counts") != counts
        or payload.get("foreign_key_references") != references
        or type(payload.get("foreign_key_constraints_checked")) is not int
        or payload["foreign_key_constraints_checked"] < 2
    ):
        raise ValueError("direct evidence mismatch")
    return int(payload["foreign_key_constraints_checked"])


def _validate_report(path: Path) -> None:
    payload = _read_root_json(path / "c7-summary.json")
    if payload != {
        "counts": {"passed": 2},
        "result": "passed",
        "testsObserved": 2,
        "testsPlanned": 2,
        "version": 1,
    }:
        raise ValueError("redacted report mismatch")


def _validate_root_tree(root: Path) -> None:
    root_observed = os.lstat(root)
    if (
        not stat.S_ISDIR(root_observed.st_mode)
        or stat.S_ISLNK(root_observed.st_mode)
        or root_observed.st_uid != 0
        or root_observed.st_gid != 0
        or stat.S_IMODE(root_observed.st_mode) != 0o700
    ):
        raise ValueError("evidence root metadata mismatch")
    for path in root.rglob("*"):
        observed = os.lstat(path)
        if stat.S_ISLNK(observed.st_mode) or observed.st_uid != 0 or observed.st_gid != 0:
            raise ValueError("evidence ownership mismatch")
        expected_mode = 0o700 if stat.S_ISDIR(observed.st_mode) else 0o600
        if (
            not (stat.S_ISDIR(observed.st_mode) or stat.S_ISREG(observed.st_mode))
            or stat.S_IMODE(observed.st_mode) != expected_mode
        ):
            raise ValueError("evidence mode mismatch")


def _fsync_tree(root: Path) -> None:
    files = [path for path in root.rglob("*") if path.is_file()]
    directories = [path for path in root.rglob("*") if path.is_dir()]
    for path in files:
        descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for path in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        _fsync_directory(path)
    _fsync_directory(root)


def _validate_evidence(args: argparse.Namespace) -> None:
    runtime = args.runtime.resolve(strict=True)
    lifecycle = runtime / "lifecycle"
    if args.mode == "normal":
        expected_names = {
            "cursor-probe.json",
            "direct-audit.json",
            "direct-cleanup.json",
            "direct-seed.json",
            "lifecycle",
            "playwright-main",
            "playwright-recovery",
        }
        _validate_direct(
            runtime / "direct-seed.json",
            "seed",
            {"features": 2, "price_values": 1, "weather_values": 1},
            2,
        )
        required_operations = {
            "executor-main",
            "executor-recovery",
            "helper-audit",
            "helper-cleanup",
            "helper-seed",
            "probe-cursor-missing",
        }
        if _read_root_json(runtime / "cursor-probe.json") != {
            "exit_code": 1,
            "phase": "entrypoint-pre-migration",
            "result": "cursor-secret-missing",
            "version": 1,
        }:
            raise ValueError("cursor probe evidence mismatch")
        _validate_report(runtime / "playwright-main")
        actor = "main"
    else:
        expected_names = {
            "direct-audit.json",
            "direct-cleanup.json",
            "lifecycle",
            "playwright-recovery",
        }
        required_operations = {"executor-recovery", "helper-audit", "helper-cleanup"}
        actor = "recovery"
    if {path.name for path in runtime.iterdir()} != expected_names:
        raise ValueError("evidence exact file set mismatch")
    _validate_direct(
        runtime / "direct-cleanup.json",
        "cleanup",
        {"features": 0, "price_values": 0, "weather_values": 0},
        0,
    )
    constraints = _validate_direct(
        runtime / "direct-audit.json",
        "audit",
        {"features": 0, "price_values": 0, "weather_values": 0},
        0,
    )
    _validate_report(runtime / "playwright-recovery")
    phases: dict[str, set[str]] = {}
    lifecycle_files = list(lifecycle.glob("*.json"))
    if not lifecycle_files:
        raise ValueError("lifecycle evidence is empty")
    lifecycle_keys = {
        "actor",
        "attempt",
        "container_id_sha256",
        "container_name_sha256",
        "exit_code",
        "kind",
        "operation",
        "phase",
        "recorded_at",
        "version",
    }
    for path in lifecycle_files:
        event = _read_root_json(path)
        if (
            set(event) != lifecycle_keys
            or event.get("version") != 1
            or not isinstance(event.get("actor"), str)
            or not isinstance(event.get("operation"), str)
            or not isinstance(event.get("phase"), str)
            or (
                event.get("container_id_sha256") is not None
                and (
                    not isinstance(event["container_id_sha256"], str)
                    or _SHA256_RE.fullmatch(event["container_id_sha256"]) is None
                )
            )
            or not isinstance(event.get("container_name_sha256"), str)
            or _SHA256_RE.fullmatch(event["container_name_sha256"]) is None
        ):
            raise ValueError("lifecycle evidence mismatch")
        if event["actor"] == actor and event.get("attempt") == args.attempt:
            phases.setdefault(event["operation"], set()).add(event["phase"])
    common = {
        "claim-pending",
        "created",
        "exited",
        "prepared",
        "removed",
        "start-pending",
        "started",
        "terminal",
    }
    for operation in required_operations:
        if not common.issubset(phases.get(operation, set())):
            raise ValueError("lifecycle phase set mismatch")
    _validate_root_tree(runtime)
    validation_path = runtime / "validation.json"
    _atomic_write(
        validation_path,
        {
            "direct_foreign_key_constraints_checked": constraints,
            "lifecycle_files": len(lifecycle_files),
            "mode": args.mode,
            "phase": "evidence-validated",
            "recovery_attempt": args.attempt,
            "reports_passed": 2 if args.mode == "normal" else 1,
            "version": 1,
        },
    )
    _validate_root_tree(runtime)
    _fsync_tree(runtime)


def _path(value: str) -> Path:
    return Path(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    blocked = subparsers.add_parser("write-blocked")
    blocked.add_argument("--path", type=_path, required=True)
    blocked.add_argument("--run-id", required=True)
    blocked.add_argument("--recovery-attempt", type=int, required=True)
    blocked.add_argument("--phase", required=True)
    blocked.add_argument("--status", required=True)
    blocked.set_defaults(handler=_write_blocked)

    recovery = subparsers.add_parser("begin-recovery")
    recovery.add_argument("--path", type=_path, required=True)
    recovery.set_defaults(handler=_begin_recovery)

    clear = subparsers.add_parser("clear-blocked")
    clear.add_argument("--path", type=_path, required=True)
    clear.set_defaults(handler=_clear_blocked)

    result = subparsers.add_parser("write-result")
    result.add_argument("--path", type=_path, required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--recovery-attempt", type=int, required=True)
    result.add_argument("--phase", required=True)
    result.add_argument("--status", required=True)
    result.add_argument("--compatible-pair-sha256", required=True)
    result.add_argument("--host-attestation-sha256", required=True)
    result.set_defaults(handler=_write_result)

    lifecycle = subparsers.add_parser("write-lifecycle")
    lifecycle.add_argument("--path", type=_path, required=True)
    lifecycle.add_argument("--actor", required=True)
    lifecycle.add_argument("--attempt", type=int, required=True)
    lifecycle.add_argument("--kind", required=True)
    lifecycle.add_argument("--operation", required=True)
    lifecycle.add_argument("--phase", required=True)
    lifecycle.add_argument("--container-name", required=True)
    lifecycle.add_argument("--container-id", default="")
    lifecycle.add_argument("--exit-code", type=int)
    lifecycle.set_defaults(handler=_write_lifecycle)

    active = subparsers.add_parser("write-active")
    active.add_argument("--path", type=_path, required=True)
    active.add_argument("--run-key", required=True)
    active.add_argument("--actor", required=True)
    active.add_argument("--attempt", type=int, required=True)
    active.add_argument("--operation", required=True)
    active.add_argument("--phase", required=True)
    active.add_argument("--status", required=True)
    active.add_argument("--container-name", required=True)
    active.add_argument("--container-id", default="")
    active.add_argument("--exit-code", type=int)
    active.add_argument("--pid", type=int, required=True)
    active.add_argument("--pgid", type=int, required=True)
    active.add_argument("--sid", type=int, required=True)
    active.add_argument("--start-ticks", type=int, required=True)
    active.set_defaults(handler=_write_active)

    read_active = subparsers.add_parser("read-terminal-active")
    read_active.add_argument("--path", type=_path, required=True)
    read_active.add_argument("--run-key", required=True)
    read_active.set_defaults(handler=_read_terminal_active)

    clear_active = subparsers.add_parser("clear-active")
    clear_active.add_argument("--path", type=_path, required=True)
    clear_active.set_defaults(handler=_clear_active)

    probe = subparsers.add_parser("write-probe")
    probe.add_argument("--path", type=_path, required=True)
    probe.add_argument("--result", required=True)
    probe.add_argument("--exit-code", type=int, required=True)
    probe.set_defaults(handler=_write_probe)

    key = subparsers.add_parser("run-key")
    key.add_argument("--run-id", required=True)
    key.set_defaults(handler=_run_key)

    source = subparsers.add_parser("validate-source")
    source.add_argument("--root", type=_path, required=True)
    source.add_argument("--expected-root", required=True)
    source.add_argument("--manifest", type=_path, required=True)
    source.add_argument("--expected-commit", required=True)
    source.add_argument("--required-file", action="append", required=True)
    source.set_defaults(handler=_validate_source)

    c7 = subparsers.add_parser("validate-c7-module")
    c7.add_argument("--module", type=_path, required=True)
    c7.add_argument("--attestation", type=_path, required=True)
    c7.add_argument("--expected-commit", required=True)
    c7.set_defaults(handler=_validate_c7_module)

    evidence = subparsers.add_parser("validate-evidence")
    evidence.add_argument("--runtime", type=_path, required=True)
    evidence.add_argument("--mode", choices=("normal", "recover"), required=True)
    evidence.add_argument("--attempt", type=int, required=True)
    evidence.set_defaults(handler=_validate_evidence)
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError):
        raise SystemExit("state operation failed (values redacted)") from None


if __name__ == "__main__":
    main()

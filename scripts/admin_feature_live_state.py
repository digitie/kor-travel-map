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


def _owned_ids(run_id: str) -> list[str]:
    prefix = f"e2e_live_acceptance::{run_id}"
    return [
        f"{prefix}::marker::draft",
        f"{prefix}::marker::inactive",
        f"{prefix}::marker::hidden",
        f"{prefix}::correction",
        f"{prefix}::weather",
        f"{prefix}::price",
    ]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.fchown(descriptor, 0, 0)
        os.write(descriptor, (json.dumps(payload, sort_keys=True) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chown(path, 0, 0)
    os.chmod(path, 0o600)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _read_root_json(path: Path) -> dict[str, Any]:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        observed = os.fstat(descriptor)
        body = os.read(descriptor, 16_384)
        if os.read(descriptor, 1):
            raise ValueError("state file is too large")
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != 0
        or observed.st_gid != 0
        or stat.S_IMODE(observed.st_mode) != 0o600
    ):
        raise ValueError("state file metadata mismatch")
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("state payload must be an object")
    return payload


def _recorded_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_blocked(args: argparse.Namespace) -> None:
    if _RUN_ID_RE.fullmatch(args.run_id) is None:
        raise ValueError("invalid run ID")
    _atomic_write(
        args.path,
        {
            "owned_feature_ids": _owned_ids(args.run_id),
            "phase": args.phase,
            "recorded_at": _recorded_at(),
            "run_id": args.run_id,
            "status": args.status,
            "version": 1,
        },
    )


def _validated_blocked(path: Path) -> dict[str, Any]:
    payload = _read_root_json(path)
    if (
        set(payload)
        != {"owned_feature_ids", "phase", "recorded_at", "run_id", "status", "version"}
        or payload.get("version") != 1
        or not isinstance(payload.get("run_id"), str)
        or _RUN_ID_RE.fullmatch(payload["run_id"]) is None
        or payload.get("owned_feature_ids") != _owned_ids(payload["run_id"])
        or not isinstance(payload.get("phase"), str)
        or not isinstance(payload.get("status"), str)
        or not isinstance(payload.get("recorded_at"), str)
    ):
        raise ValueError("invalid BLOCKED state")
    return payload


def _read_blocked(args: argparse.Namespace) -> None:
    print(_validated_blocked(args.path)["run_id"])


def _clear_blocked(args: argparse.Namespace) -> None:
    _validated_blocked(args.path)
    os.unlink(args.path)
    directory = os.open(args.path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_result(args: argparse.Namespace) -> None:
    if _RUN_ID_RE.fullmatch(args.run_id) is None:
        raise ValueError("invalid run ID")
    _atomic_write(
        args.path,
        {
            "owned_feature_id_sha256": [_sha256(value) for value in _owned_ids(args.run_id)],
            "phase": args.phase,
            "recorded_at": _recorded_at(),
            "run_id_sha256": _sha256(args.run_id),
            "status": args.status,
            "version": 1,
        },
    )


def _write_executor(args: argparse.Namespace) -> None:
    if args.container_id and re.fullmatch(r"[0-9a-f]{64}", args.container_id) is None:
        raise ValueError("invalid container ID")
    if args.exit_code is not None and not 0 <= args.exit_code <= 255:
        raise ValueError("invalid container exit code")
    _atomic_write(
        args.path,
        {
            "container_id_sha256": _sha256(args.container_id) if args.container_id else None,
            "container_name_sha256": _sha256(args.container_name),
            "exit_code": args.exit_code,
            "phase": args.phase,
            "recorded_at": _recorded_at(),
            "version": 1,
        },
    )


def _write_lingering(args: argparse.Namespace) -> None:
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in args.container_id):
        raise ValueError("invalid container ID")
    _atomic_write(
        args.path,
        {
            "container_id_sha256": [_sha256(value) for value in args.container_id],
            "phase": args.phase,
            "recorded_at": _recorded_at(),
            "version": 1,
        },
    )


def _run_key(args: argparse.Namespace) -> None:
    if _RUN_ID_RE.fullmatch(args.run_id) is None:
        raise ValueError("invalid run ID")
    print(_sha256(args.run_id))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        observed = os.fstat(descriptor)
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != 0
        or observed.st_gid != 0
        or stat.S_IMODE(observed.st_mode) != 0o555
    ):
        raise ValueError("snapshot source metadata mismatch")
    return digest.hexdigest()


def _validate_source(args: argparse.Namespace) -> None:
    root = args.root.resolve(strict=True)
    if root != args.root or root != Path(args.expected_root):
        raise ValueError("snapshot root mismatch")
    if args.manifest.parent.resolve(strict=True) != root:
        raise ValueError("manifest parent mismatch")
    current = Path("/")
    candidates = [current]
    for part in root.parts[1:]:
        current /= part
        candidates.append(current)
    for candidate in candidates:
        observed = os.lstat(candidate)
        if (
            not stat.S_ISDIR(observed.st_mode)
            or observed.st_uid != 0
            or observed.st_gid != 0
            or stat.S_IMODE(observed.st_mode) & 0o022
        ):
            raise ValueError("snapshot ancestor metadata mismatch")
    if stat.S_IMODE(os.lstat(root).st_mode) != 0o555:
        raise ValueError("snapshot root mode mismatch")

    required = set(args.required_file)
    expected_names = required | {args.manifest.name}
    if set(os.listdir(root)) != expected_names:
        raise ValueError("snapshot exact file set mismatch")
    descriptor = os.open(args.manifest, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        observed = os.fstat(descriptor)
        body = os.read(descriptor, 16_384)
        if os.read(descriptor, 1):
            raise ValueError("manifest is too large")
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(observed.st_mode)
        or observed.st_uid != 0
        or observed.st_gid != 0
        or stat.S_IMODE(observed.st_mode) != 0o444
    ):
        raise ValueError("manifest metadata mismatch")
    manifest = json.loads(body)
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


def _path(value: str) -> Path:
    return Path(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="action", required=True)

    blocked = subparsers.add_parser("write-blocked")
    blocked.add_argument("--path", type=_path, required=True)
    blocked.add_argument("--run-id", required=True)
    blocked.add_argument("--phase", required=True)
    blocked.add_argument("--status", required=True)
    blocked.set_defaults(handler=_write_blocked)

    read = subparsers.add_parser("read-blocked")
    read.add_argument("--path", type=_path, required=True)
    read.set_defaults(handler=_read_blocked)

    clear = subparsers.add_parser("clear-blocked")
    clear.add_argument("--path", type=_path, required=True)
    clear.set_defaults(handler=_clear_blocked)

    result = subparsers.add_parser("write-result")
    result.add_argument("--path", type=_path, required=True)
    result.add_argument("--run-id", required=True)
    result.add_argument("--phase", required=True)
    result.add_argument("--status", required=True)
    result.set_defaults(handler=_write_result)

    executor = subparsers.add_parser("write-executor")
    executor.add_argument("--path", type=_path, required=True)
    executor.add_argument("--phase", required=True)
    executor.add_argument("--container-name", required=True)
    executor.add_argument("--container-id", default="")
    executor.add_argument("--exit-code", type=int)
    executor.set_defaults(handler=_write_executor)

    lingering = subparsers.add_parser("write-lingering")
    lingering.add_argument("--path", type=_path, required=True)
    lingering.add_argument("--phase", required=True)
    lingering.add_argument("--container-id", action="append", default=[])
    lingering.set_defaults(handler=_write_lingering)

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
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError):
        raise SystemExit("state operation failed (values redacted)") from None


if __name__ == "__main__":
    main()

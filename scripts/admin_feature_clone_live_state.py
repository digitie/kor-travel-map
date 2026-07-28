#!/usr/bin/env python3
"""격리 clone Admin Feature Live 인수의 durable state와 evidence를 검증한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Final

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{15,79}$")
_IMAGE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_REPORT_FILES: Final[set[str]] = {
    "c7-results.xml",
    "c7-summary.html",
    "c7-summary.json",
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"regular file이 아닙니다: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON object가 아닙니다: {path.name}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | os.O_NOFOLLOW,
        0o600,
    )
    try:
        payload = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fchmod(descriptor, 0o600)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _require_pattern(value: str, pattern: re.Pattern[str], label: str) -> str:
    if pattern.fullmatch(value) is None:
        raise RuntimeError(f"{label} 형식이 올바르지 않습니다")
    return value


def _identity(args: argparse.Namespace) -> dict[str, str]:
    return {
        "api_image_id": _require_pattern(
            args.api_image_id, _IMAGE_ID_RE, "API image ID"
        ),
        "clone_identity_sha256": _require_pattern(
            args.clone_identity_sha256, _SHA256_RE, "clone identity SHA256"
        ),
        "playwright_image_id": _require_pattern(
            args.playwright_image_id, _IMAGE_ID_RE, "Playwright image ID"
        ),
        "source_commit": _require_pattern(
            args.source_commit, _COMMIT_RE, "source commit"
        ),
        "ui_image_id": _require_pattern(args.ui_image_id, _IMAGE_ID_RE, "UI image ID"),
    }


def _validated_blocked_identity(blocked: dict[str, Any]) -> dict[str, str]:
    identity = blocked.get("identity")
    if not isinstance(identity, dict):
        raise RuntimeError("BLOCKED execution identity가 없습니다")
    patterns = {
        "api_image_id": (_IMAGE_ID_RE, "API image ID"),
        "clone_identity_sha256": (_SHA256_RE, "clone identity SHA256"),
        "playwright_image_id": (_IMAGE_ID_RE, "Playwright image ID"),
        "source_commit": (_COMMIT_RE, "source commit"),
        "ui_image_id": (_IMAGE_ID_RE, "UI image ID"),
    }
    if set(identity) != set(patterns):
        raise RuntimeError("BLOCKED execution identity field가 예상과 다릅니다")
    validated: dict[str, str] = {}
    for field, (pattern, label) in patterns.items():
        value = identity[field]
        if not isinstance(value, str):
            raise RuntimeError(f"{label} 형식이 올바르지 않습니다")
        validated[field] = _require_pattern(value, pattern, label)
    return validated


def write_blocked(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if path.exists() or path.is_symlink():
        raise RuntimeError("기존 BLOCKED state가 있습니다")
    run_id = _require_pattern(args.run_id, _RUN_ID_RE, "run ID")
    run_key = _require_pattern(args.run_key, _SHA256_RE, "run key")
    _atomic_json(
        path,
        {
            "identity": _identity(args),
            "phase": args.phase,
            "run_id": run_id,
            "run_key": run_key,
            "status": "blocked",
            "version": 1,
        },
    )


def update_blocked(args: argparse.Namespace) -> None:
    path = Path(args.path)
    blocked = _load_object(path)
    if blocked.get("status") != "blocked" or blocked.get("version") != 1:
        raise RuntimeError("BLOCKED state 계약이 올바르지 않습니다")
    blocked["phase"] = args.phase
    _atomic_json(path, blocked)


def read_blocked(args: argparse.Namespace) -> None:
    blocked = _load_object(Path(args.path))
    if blocked.get("status") != "blocked" or blocked.get("version") != 1:
        raise RuntimeError("BLOCKED state 계약이 올바르지 않습니다")
    field = args.field
    value: object
    if field in {"run_id", "run_key", "phase"}:
        value = blocked.get(field)
    else:
        value = _validated_blocked_identity(blocked).get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError("BLOCKED field가 올바르지 않습니다")
    print(value)


def write_snapshot(args: argparse.Namespace) -> None:
    _atomic_json(
        Path(args.path),
        {
            "active_owned_features": args.active_owned_features,
            "clone_container_sha256": _require_pattern(
                args.clone_container_sha256,
                _SHA256_RE,
                "clone container SHA256",
            ),
            "clone_system_identifier_sha256": _require_pattern(
                args.clone_system_identifier_sha256,
                _SHA256_RE,
                "clone system identifier SHA256",
            ),
            "feature_non_deleted": args.feature_non_deleted,
            "feature_total": args.feature_total,
            "host_port": args.host_port,
            "migration_head": args.migration_head,
            "nonterminal_owned_change_requests": args.nonterminal_owned_change_requests,
            "relation_count": args.relation_count,
            "version": 1,
        },
    )


def _fixture_counts(
    path: Path,
    expected_action: str,
    expected: dict[str, int],
    *,
    expected_foreign_key_references: int,
) -> dict[str, Any]:
    evidence = _load_object(path)
    if (
        evidence.get("version") != 1
        or evidence.get("action") != expected_action
        or evidence.get("counts") != expected
    ):
        raise RuntimeError(f"fixture evidence가 예상과 다릅니다: {path.name}")
    if evidence.get("foreign_key_references") != expected_foreign_key_references:
        raise RuntimeError(f"fixture FK reference가 예상과 다릅니다: {path.name}")
    checked = evidence.get("foreign_key_constraints_checked")
    if not isinstance(checked, int) or checked < 1:
        raise RuntimeError(f"fixture FK audit가 없습니다: {path.name}")
    return evidence


def _report_counts(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Playwright evidence directory가 아닙니다: {path.name}")
    entries = {item.name for item in path.iterdir()}
    if entries != _REPORT_FILES or any(item.is_symlink() for item in path.iterdir()):
        raise RuntimeError(f"Playwright evidence exact file set이 아닙니다: {path.name}")
    summary = _load_object(path / "c7-summary.json")
    if (
        summary.get("version") != 1
        or summary.get("result") != "passed"
        or summary.get("testsObserved") != 2
        or summary.get("testsPlanned") != 2
        or summary.get("counts") != {"passed": 2}
    ):
        raise RuntimeError(f"Playwright summary가 예상과 다릅니다: {path.name}")
    return {"passed": 2}


def _same_startup_identity(before: dict[str, Any], after: dict[str, Any]) -> bool:
    keys = {
        "clone_container_sha256",
        "clone_system_identifier_sha256",
        "active_owned_features",
        "feature_non_deleted",
        "feature_total",
        "host_port",
        "migration_head",
        "nonterminal_owned_change_requests",
        "relation_count",
        "version",
    }
    return {key: before.get(key) for key in keys} == {
        key: after.get(key) for key in keys
    }


def complete(args: argparse.Namespace) -> None:
    runtime = Path(args.runtime)
    blocked_path = Path(args.blocked_path)
    blocked = _load_object(blocked_path)
    if blocked.get("status") != "blocked" or blocked.get("version") != 1:
        raise RuntimeError("BLOCKED state 계약이 올바르지 않습니다")
    identity = _validated_blocked_identity(blocked)

    startup_before = _load_object(runtime / "clone-startup-before.json")
    startup_after = _load_object(runtime / "clone-startup-after.json")
    final = _load_object(runtime / "clone-final.json")
    if args.phase == "recovered":
        if args.current_snapshot is None or args.recovery_tool_source_commit is None:
            raise RuntimeError("recovery 완료에는 현재 snapshot/tool commit이 필요합니다")
        current = _load_object(Path(args.current_snapshot))
        if not _same_startup_identity(final, current):
            raise RuntimeError("recovery 현재 clone DB가 실패 당시 최종 snapshot과 다릅니다")
        recovery_tool_source_commit: str | None = _require_pattern(
            args.recovery_tool_source_commit,
            _COMMIT_RE,
            "recovery tool source commit",
        )
    else:
        if args.current_snapshot is not None or args.recovery_tool_source_commit is not None:
            raise RuntimeError("일반 완료에는 recovery 전용 인자를 사용할 수 없습니다")
        recovery_tool_source_commit = None
    if not _same_startup_identity(startup_before, startup_after):
        raise RuntimeError("candidate startup이 clone DB identity/schema/data를 변경했습니다")
    clone_identity = (
        f"{startup_before.get('clone_container_sha256')}\n"
        f"{startup_before.get('clone_system_identifier_sha256')}\n"
        f"{startup_before.get('host_port')}\n"
        f"{startup_before.get('migration_head')}\n"
    )
    if identity["clone_identity_sha256"] != _sha256(clone_identity):
        raise RuntimeError("BLOCKED clone identity가 DB snapshot과 다릅니다")
    for key in (
        "clone_container_sha256",
        "clone_system_identifier_sha256",
        "host_port",
        "migration_head",
        "relation_count",
        "version",
    ):
        if final.get(key) != startup_before.get(key):
            raise RuntimeError("최종 clone DB identity/schema가 시작 기준과 다릅니다")
    if final.get("feature_non_deleted") != startup_before.get("feature_non_deleted"):
        raise RuntimeError("최종 non-deleted Feature 수가 시작 기준과 다릅니다")
    if final.get("feature_total") != startup_before.get("feature_total", 0) + 6:
        raise RuntimeError("최종 soft-delete 감사 Feature 6건이 예상과 다릅니다")
    if (
        final.get("active_owned_features") != 0
        or final.get("nonterminal_owned_change_requests") != 0
    ):
        raise RuntimeError("최종 API-owned Feature/change request residue가 있습니다")

    _fixture_counts(
        runtime / "direct-seed.json",
        "seed",
        {"features": 2, "price_values": 1, "weather_values": 1},
        expected_foreign_key_references=2,
    )
    cleanup = _fixture_counts(
        runtime / "direct-cleanup.json",
        "cleanup",
        {"features": 0, "price_values": 0, "weather_values": 0},
        expected_foreign_key_references=0,
    )
    audit = _fixture_counts(
        runtime / "direct-audit.json",
        "audit",
        {"features": 0, "price_values": 0, "weather_values": 0},
        expected_foreign_key_references=0,
    )
    tests = {
        "main": _report_counts(runtime / "playwright-main"),
        "recovery": _report_counts(runtime / "playwright-recovery"),
    }
    canonical_identity = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    result = {
        "cleanup": {
            "foreign_key_references": cleanup["foreign_key_references"],
            "owned_features": cleanup["counts"]["features"],
            "api_owned_active_features": final["active_owned_features"],
            "api_owned_nonterminal_change_requests": final[
                "nonterminal_owned_change_requests"
            ],
            "post_cleanup_audit_features": audit["counts"]["features"],
        },
        "execution_identity_sha256": _sha256(canonical_identity),
        "isolation": {
            "clone_container_sha256": startup_before["clone_container_sha256"],
            "clone_system_identifier_sha256": startup_before[
                "clone_system_identifier_sha256"
            ],
            "host_port": startup_before["host_port"],
            "production_compose_project_excluded": True,
            "startup_migration_unchanged": True,
        },
        "phase": args.phase,
        "recovery_tool_source_commit": recovery_tool_source_commit,
        "source_commit": identity.get("source_commit"),
        "status": "complete",
        "tests": tests,
        "version": 1,
    }
    _atomic_json(Path(args.result_path), result)
    blocked_path.unlink()
    directory = os.open(
        blocked_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
    )
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-image-id", required=True)
    parser.add_argument("--clone-identity-sha256", required=True)
    parser.add_argument("--playwright-image-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--ui-image-id", required=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    blocked = subparsers.add_parser("write-blocked")
    blocked.add_argument("--path", required=True)
    blocked.add_argument("--phase", required=True)
    blocked.add_argument("--run-id", required=True)
    blocked.add_argument("--run-key", required=True)
    _add_identity_arguments(blocked)
    blocked.set_defaults(handler=write_blocked)

    update = subparsers.add_parser("update-blocked")
    update.add_argument("--path", required=True)
    update.add_argument("--phase", required=True)
    update.set_defaults(handler=update_blocked)

    read = subparsers.add_parser("read-blocked")
    read.add_argument("--path", required=True)
    read.add_argument(
        "--field",
        choices=(
            "api_image_id",
            "clone_identity_sha256",
            "phase",
            "playwright_image_id",
            "run_id",
            "run_key",
            "source_commit",
            "ui_image_id",
        ),
        required=True,
    )
    read.set_defaults(handler=read_blocked)

    snapshot = subparsers.add_parser("write-snapshot")
    snapshot.add_argument("--path", required=True)
    snapshot.add_argument("--active-owned-features", required=True, type=int)
    snapshot.add_argument("--clone-container-sha256", required=True)
    snapshot.add_argument("--clone-system-identifier-sha256", required=True)
    snapshot.add_argument("--feature-non-deleted", required=True, type=int)
    snapshot.add_argument("--feature-total", required=True, type=int)
    snapshot.add_argument("--host-port", required=True, type=int)
    snapshot.add_argument("--migration-head", required=True)
    snapshot.add_argument(
        "--nonterminal-owned-change-requests", required=True, type=int
    )
    snapshot.add_argument("--relation-count", required=True, type=int)
    snapshot.set_defaults(handler=write_snapshot)

    finish = subparsers.add_parser("complete")
    finish.add_argument("--blocked-path", required=True)
    finish.add_argument("--phase", choices=("passed", "recovered"), required=True)
    finish.add_argument("--current-snapshot")
    finish.add_argument("--recovery-tool-source-commit")
    finish.add_argument("--result-path", required=True)
    finish.add_argument("--runtime", required=True)
    finish.set_defaults(handler=complete)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""격리 clone Admin Feature Live 인수의 durable state와 evidence를 검증한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Final

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{15,79}$")
_IMAGE_ID_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_NETWORK_RE: Final[re.Pattern[str]] = re.compile(r"^ktm-afcla-[0-9a-f]{12}-net$")
_CHECKPOINT_DUMP_RE: Final[re.Pattern[str]] = re.compile(
    r"^clone-checkpoint-[0-9a-f]{64}\.dump$"
)
_SCRATCH_DATABASE_RE: Final[re.Pattern[str]] = re.compile(
    r"^ktm_checkpoint_[0-9a-f]{24}$"
)
_SCRATCH_ROLE_RE: Final[re.Pattern[str]] = re.compile(
    r"^ktm_checkpoint_owner_[0-9a-f]{24}$"
)
_DATABASE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UTC_TIMESTAMP_RE: Final[re.Pattern[str]] = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$"
)
_REPORT_FILES: Final[set[str]] = {
    "c7-results.xml",
    "c7-summary.html",
    "c7-summary.json",
}
_EXPECTED_TESTS: Final[tuple[str, str]] = (
    "auth.setup.ts",
    "admin-feature-acceptance-write.live.spec.ts",
)
_SNAPSHOT_KEYS: Final[set[str]] = {
    "active_owned_features",
    "clone_container_sha256",
    "clone_system_identifier_sha256",
    "content_cutoff",
    "content_sha256",
    "database_sha256",
    "extension_sha256",
    "feature_non_deleted",
    "feature_total",
    "host_port",
    "migration_head",
    "nonterminal_owned_change_requests",
    "relation_count",
    "schema_sha256",
    "version",
}
_HTML_REPORT_RE: Final[re.Pattern[str]] = re.compile(
    r'<!doctype html><html lang="ko"><meta charset="utf-8">'
    r"<title>C7 redacted result</title><body><h1>C7 redacted result</h1>"
    r"<p>result=passed planned=2 observed=2</p><table><thead><tr>"
    r"<th>#</th><th>spec</th><th>status</th><th>duration_ms</th>"
    r"</tr></thead><tbody>"
    r"<tr><td>1</td><td>auth\.setup\.ts</td><td>passed</td>"
    r"<td>([0-9]+)</td></tr>"
    r"<tr><td>2</td><td>admin-feature-acceptance-write\.live\.spec\.ts</td>"
    r"<td>passed</td><td>([0-9]+)</td></tr>"
    r"</tbody></table></body></html>\n?"
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")))


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
        "clone_checkpoint_sha256": _require_pattern(
            args.clone_checkpoint_sha256,
            _SHA256_RE,
            "clone checkpoint SHA256",
        ),
        "clone_identity_sha256": _require_pattern(
            args.clone_identity_sha256, _SHA256_RE, "clone identity SHA256"
        ),
        "network_name": _require_pattern(
            args.network_name, _NETWORK_RE, "candidate network name"
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
        "clone_checkpoint_sha256": (_SHA256_RE, "clone checkpoint SHA256"),
        "clone_identity_sha256": (_SHA256_RE, "clone identity SHA256"),
        "network_name": (_NETWORK_RE, "candidate network name"),
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


def _validated_snapshot_object(
    snapshot: object,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise RuntimeError(f"DB snapshot object가 아닙니다: {label}")
    if set(snapshot) != _SNAPSHOT_KEYS or snapshot.get("version") != 2:
        raise RuntimeError(f"DB snapshot field/version이 예상과 다릅니다: {label}")
    for field in ("clone_container_sha256", "clone_system_identifier_sha256"):
        value = snapshot[field]
        if not isinstance(value, str):
            raise RuntimeError(f"DB snapshot identity가 없습니다: {label}")
        _require_pattern(value, _SHA256_RE, field)
    for field in (
        "content_sha256",
        "database_sha256",
        "extension_sha256",
        "schema_sha256",
    ):
        value = snapshot[field]
        if not isinstance(value, str):
            raise RuntimeError(f"DB snapshot digest가 없습니다: {label}")
        _require_pattern(value, _SHA256_RE, field)
    content_cutoff = snapshot["content_cutoff"]
    if not isinstance(content_cutoff, str):
        raise RuntimeError(f"DB snapshot content cutoff이 없습니다: {label}")
    _require_pattern(content_cutoff, _UTC_TIMESTAMP_RE, "content cutoff")
    for field in (
        "active_owned_features",
        "feature_non_deleted",
        "feature_total",
        "host_port",
        "nonterminal_owned_change_requests",
        "relation_count",
    ):
        value = snapshot[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeError(f"DB snapshot count가 올바르지 않습니다: {label}")
    migration_head = snapshot["migration_head"]
    if not isinstance(migration_head, str) or not migration_head:
        raise RuntimeError(f"DB snapshot migration head가 없습니다: {label}")
    return snapshot


def _validated_snapshot(path: Path) -> dict[str, Any]:
    return _validated_snapshot_object(_load_object(path), label=path.name)


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
            "phase_history": [args.phase],
            "run_id": run_id,
            "run_key": run_key,
            "status": "blocked",
            "version": 2,
        },
    )


def update_blocked(args: argparse.Namespace) -> None:
    path = Path(args.path)
    blocked = _load_object(path)
    if blocked.get("status") != "blocked" or blocked.get("version") != 2:
        raise RuntimeError("BLOCKED state 계약이 올바르지 않습니다")
    history = blocked.get("phase_history")
    if not isinstance(history, list) or not all(
        isinstance(item, str) and item for item in history
    ):
        raise RuntimeError("BLOCKED phase history가 올바르지 않습니다")
    blocked["phase"] = args.phase
    history.append(args.phase)
    _atomic_json(path, blocked)


def read_blocked(args: argparse.Namespace) -> None:
    blocked = _load_object(Path(args.path))
    if blocked.get("status") != "blocked" or blocked.get("version") != 2:
        raise RuntimeError("BLOCKED state 계약이 올바르지 않습니다")
    field = args.field
    value: object
    if field in {"run_id", "run_key", "phase"}:
        value = blocked.get(field)
    else:
        value = _validated_blocked_identity(blocked).get(field)
    if not isinstance(value, str) or not value:
        raise RuntimeError("BLOCKED field가 올바르지 않습니다")
    if field == "run_id":
        _require_pattern(value, _RUN_ID_RE, "run ID")
    elif field == "run_key":
        _require_pattern(value, _SHA256_RE, "run key")
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
            "content_cutoff": _require_pattern(
                args.content_cutoff, _UTC_TIMESTAMP_RE, "content cutoff"
            ),
            "content_sha256": _require_pattern(
                args.content_sha256, _SHA256_RE, "content SHA256"
            ),
            "database_sha256": _require_pattern(
                args.database_sha256, _SHA256_RE, "database SHA256"
            ),
            "extension_sha256": _require_pattern(
                args.extension_sha256, _SHA256_RE, "extension SHA256"
            ),
            "feature_non_deleted": args.feature_non_deleted,
            "feature_total": args.feature_total,
            "host_port": args.host_port,
            "migration_head": args.migration_head,
            "nonterminal_owned_change_requests": args.nonterminal_owned_change_requests,
            "relation_count": args.relation_count,
            "schema_sha256": _require_pattern(
                args.schema_sha256, _SHA256_RE, "schema SHA256"
            ),
            "version": 2,
        },
    )


def write_checkpoint(args: argparse.Namespace) -> None:
    snapshot = _validated_snapshot(Path(args.snapshot))
    restored_snapshot = _validated_snapshot(Path(args.restored_snapshot))
    final_snapshot = _validated_snapshot(Path(args.final_snapshot))
    if restored_snapshot != snapshot:
        raise RuntimeError("복원 검증 snapshot이 checkpoint baseline과 다릅니다")
    if final_snapshot != snapshot:
        raise RuntimeError("checkpoint 생성 후 원본 clone snapshot이 baseline과 다릅니다")
    dump_sha256 = _require_pattern(args.dump_sha256, _SHA256_RE, "dump SHA256")
    if args.dump_size < 1:
        raise RuntimeError("dump size가 올바르지 않습니다")
    payload: dict[str, Any] = {
        "baseline": snapshot,
        "dump": {
            "filename": _require_pattern(
                args.dump_filename,
                _CHECKPOINT_DUMP_RE,
                "checkpoint dump filename",
            ),
            "sha256": dump_sha256,
            "size": args.dump_size,
        },
        "restore_verification": {
            "snapshot_sha256": _canonical_sha256(restored_snapshot),
            "verified": True,
        },
        "source_stability": {
            "snapshot_sha256": _canonical_sha256(final_snapshot),
            "verified": True,
        },
        "write_quiescence": {
            "database_default_read_only": True,
            "relation_share_locks": True,
            "verified": True,
        },
        "version": 3,
    }
    payload["checkpoint_sha256"] = _canonical_sha256(payload)
    _atomic_json(Path(args.path), payload)


def _validated_scratch(args: argparse.Namespace) -> dict[str, Any]:
    scratch = _load_object(Path(args.path))
    database = scratch.get("database")
    ownership_token = scratch.get("ownership_token")
    if not isinstance(database, str):
        raise RuntimeError("checkpoint scratch DB 이름이 없습니다")
    if not isinstance(ownership_token, str):
        raise RuntimeError("checkpoint scratch DB ownership token이 없습니다")
    expected: dict[str, Any] = {
        "clone_container_sha256": _require_pattern(
            args.clone_container_sha256,
            _SHA256_RE,
            "scratch clone container SHA256",
        ),
        "clone_system_identifier_sha256": _require_pattern(
            args.clone_system_identifier_sha256,
            _SHA256_RE,
            "scratch clone system identifier SHA256",
        ),
        "database": _require_pattern(
            database,
            _SCRATCH_DATABASE_RE,
            "checkpoint scratch DB 이름",
        ),
        "ownership_token": _require_pattern(
            ownership_token,
            _SHA256_RE,
            "checkpoint scratch DB ownership token",
        ),
        "version": 2,
    }
    version = scratch.get("version")
    if version in {3, 5}:
        database_oid = scratch.get("database_oid")
        if (
            not isinstance(database_oid, int)
            or isinstance(database_oid, bool)
            or database_oid < 1
        ):
            raise RuntimeError("checkpoint scratch DB OID가 올바르지 않습니다")
        expected["database_oid"] = database_oid
        expected["version"] = 3
    if version in {4, 5}:
        owner_role = scratch.get("owner_role")
        if not isinstance(owner_role, str):
            raise RuntimeError("checkpoint scratch DB owner role이 없습니다")
        expected["owner_role"] = _require_pattern(
            owner_role,
            _SCRATCH_ROLE_RE,
            "checkpoint scratch DB owner role",
        )
        expected["version"] = 4
    if version == 5:
        owner_role_oid = scratch.get("owner_role_oid")
        if (
            not isinstance(owner_role_oid, int)
            or isinstance(owner_role_oid, bool)
            or owner_role_oid < 1
        ):
            raise RuntimeError("checkpoint scratch DB owner role OID가 올바르지 않습니다")
        expected["owner_role_oid"] = owner_role_oid
        expected["version"] = 5
    if version not in {2, 3, 4, 5}:
        raise RuntimeError("checkpoint scratch DB ownership version이 올바르지 않습니다")
    if scratch != expected:
        raise RuntimeError("checkpoint scratch DB ownership state가 다릅니다")
    return scratch


def write_scratch(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if path.exists() or path.is_symlink():
        raise RuntimeError("기존 checkpoint scratch DB ownership state가 있습니다")
    _atomic_json(
        path,
        {
            "clone_container_sha256": _require_pattern(
                args.clone_container_sha256,
                _SHA256_RE,
                "scratch clone container SHA256",
            ),
            "clone_system_identifier_sha256": _require_pattern(
                args.clone_system_identifier_sha256,
                _SHA256_RE,
                "scratch clone system identifier SHA256",
            ),
            "database": _require_pattern(
                args.database,
                _SCRATCH_DATABASE_RE,
                "checkpoint scratch DB 이름",
            ),
            "ownership_token": _require_pattern(
                args.ownership_token,
                _SHA256_RE,
                "checkpoint scratch DB ownership token",
            ),
            "owner_role": _require_pattern(
                args.owner_role,
                _SCRATCH_ROLE_RE,
                "checkpoint scratch DB owner role",
            ),
            "version": 4,
        },
    )


def claim_scratch(args: argparse.Namespace) -> None:
    path = Path(args.path)
    scratch = _validated_scratch(args)
    if scratch["version"] not in {2, 4}:
        raise RuntimeError("checkpoint scratch DB intent가 이미 claim됐습니다")
    if args.database_oid < 1:
        raise RuntimeError("checkpoint scratch DB OID가 올바르지 않습니다")
    if scratch["version"] == 4 and (
        args.owner_role_oid is None or args.owner_role_oid < 1
    ):
        raise RuntimeError("checkpoint scratch DB owner role OID가 올바르지 않습니다")
    payload = {**scratch, "database_oid": args.database_oid}
    if scratch["version"] == 2:
        if args.owner_role_oid is not None:
            raise RuntimeError("legacy checkpoint scratch DB에는 owner role이 없습니다")
        payload["version"] = 3
    else:
        payload["owner_role_oid"] = args.owner_role_oid
        payload["version"] = 5
    _atomic_json(path, payload)


def read_scratch(args: argparse.Namespace) -> None:
    scratch = _validated_scratch(args)
    if args.field not in scratch:
        raise RuntimeError("checkpoint scratch DB가 아직 server claim되지 않았습니다")
    print(scratch[args.field])


def clear_scratch(args: argparse.Namespace) -> None:
    _validated_scratch(args)
    path = Path(args.path)
    path.unlink()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _validated_quiescence(args: argparse.Namespace) -> dict[str, Any]:
    state = _load_object(Path(args.path))
    database = state.get("database")
    if not isinstance(database, str):
        raise RuntimeError("checkpoint quiescence DB 이름이 없습니다")
    expected = {
        "clone_container_sha256": _require_pattern(
            args.clone_container_sha256,
            _SHA256_RE,
            "quiescence clone container SHA256",
        ),
        "clone_system_identifier_sha256": _require_pattern(
            args.clone_system_identifier_sha256,
            _SHA256_RE,
            "quiescence clone system identifier SHA256",
        ),
        "database": _require_pattern(
            database,
            _DATABASE_RE,
            "checkpoint quiescence DB 이름",
        ),
        "setting": "default_transaction_read_only=on",
        "version": 1,
    }
    if state != expected:
        raise RuntimeError("checkpoint quiescence state가 다릅니다")
    return state


def write_quiescence(args: argparse.Namespace) -> None:
    path = Path(args.path)
    if path.exists() or path.is_symlink():
        raise RuntimeError("기존 checkpoint quiescence state가 있습니다")
    _atomic_json(
        path,
        {
            "clone_container_sha256": _require_pattern(
                args.clone_container_sha256,
                _SHA256_RE,
                "quiescence clone container SHA256",
            ),
            "clone_system_identifier_sha256": _require_pattern(
                args.clone_system_identifier_sha256,
                _SHA256_RE,
                "quiescence clone system identifier SHA256",
            ),
            "database": _require_pattern(
                args.database,
                _DATABASE_RE,
                "checkpoint quiescence DB 이름",
            ),
            "setting": "default_transaction_read_only=on",
            "version": 1,
        },
    )


def read_quiescence(args: argparse.Namespace) -> None:
    state = _validated_quiescence(args)
    print(state[args.field])


def clear_quiescence(args: argparse.Namespace) -> None:
    _validated_quiescence(args)
    path = Path(args.path)
    path.unlink()
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _validated_checkpoint(path: Path) -> dict[str, Any]:
    checkpoint = _load_object(path)
    version = checkpoint.get("version")
    common_keys = {
        "baseline",
        "checkpoint_sha256",
        "dump",
        "restore_verification",
        "version",
    }
    version_2_keys = (common_keys, common_keys | {"source_stability"})
    version_3_keys = common_keys | {
        "source_stability",
        "write_quiescence",
    }
    fields = set(checkpoint)
    if version == 2:
        valid_fields = fields in version_2_keys
    elif version == 3:
        valid_fields = fields == version_3_keys
    else:
        valid_fields = False
    if not valid_fields:
        raise RuntimeError("clone checkpoint field가 예상과 다릅니다")
    digest = checkpoint.get("checkpoint_sha256")
    if not isinstance(digest, str):
        raise RuntimeError("clone checkpoint digest가 없습니다")
    _require_pattern(digest, _SHA256_RE, "clone checkpoint SHA256")
    unsigned = {
        key: value
        for key, value in checkpoint.items()
        if key != "checkpoint_sha256"
    }
    if digest != _canonical_sha256(unsigned):
        raise RuntimeError("clone checkpoint digest가 일치하지 않습니다")
    dump = checkpoint.get("dump")
    if not isinstance(dump, dict) or set(dump) != {"filename", "sha256", "size"}:
        raise RuntimeError("clone checkpoint dump provenance가 없습니다")
    dump_filename = dump.get("filename")
    dump_digest = dump.get("sha256")
    dump_size = dump.get("size")
    if not isinstance(dump_filename, str):
        raise RuntimeError("clone checkpoint dump filename이 없습니다")
    _require_pattern(
        dump_filename,
        _CHECKPOINT_DUMP_RE,
        "checkpoint dump filename",
    )
    if not isinstance(dump_digest, str):
        raise RuntimeError("clone checkpoint dump digest가 없습니다")
    _require_pattern(dump_digest, _SHA256_RE, "dump SHA256")
    if not isinstance(dump_size, int) or isinstance(dump_size, bool) or dump_size < 1:
        raise RuntimeError("clone checkpoint dump size가 올바르지 않습니다")
    baseline = _validated_snapshot_object(
        checkpoint.get("baseline"), label="checkpoint baseline"
    )
    restore_verification = checkpoint.get("restore_verification")
    if (
        not isinstance(restore_verification, dict)
        or restore_verification.get("verified") is not True
        or set(restore_verification) != {"snapshot_sha256", "verified"}
        or restore_verification.get("snapshot_sha256")
        != _canonical_sha256(baseline)
    ):
        raise RuntimeError("clone checkpoint 복원 검증 provenance가 없습니다")
    source_stability = checkpoint.get("source_stability")
    if source_stability is not None:
        if (
            not isinstance(source_stability, dict)
            or source_stability.get("verified") is not True
            or set(source_stability) != {"snapshot_sha256", "verified"}
            or source_stability.get("snapshot_sha256") != _canonical_sha256(baseline)
        ):
            raise RuntimeError("clone checkpoint 원본 안정성 provenance가 없습니다")
    elif version == 3:
        raise RuntimeError("clone checkpoint 원본 안정성 provenance가 없습니다")
    if version == 3 and checkpoint.get("write_quiescence") != {
        "database_default_read_only": True,
        "relation_share_locks": True,
        "verified": True,
    }:
        raise RuntimeError("clone checkpoint write quiescence provenance가 없습니다")
    return checkpoint


def promote_checkpoint(args: argparse.Namespace) -> None:
    checkpoint = _validated_checkpoint(Path(args.checkpoint))
    if checkpoint["version"] != 2:
        raise RuntimeError("승격 대상 clone checkpoint가 v2가 아닙니다")
    final_snapshot = _validated_snapshot(Path(args.final_snapshot))
    baseline = checkpoint["baseline"]
    if final_snapshot != baseline:
        raise RuntimeError("승격 시 원본 clone snapshot이 checkpoint baseline과 다릅니다")
    payload = {
        "baseline": baseline,
        "dump": checkpoint["dump"],
        "restore_verification": checkpoint["restore_verification"],
        "source_stability": {
            "snapshot_sha256": _canonical_sha256(final_snapshot),
            "verified": True,
        },
        "write_quiescence": {
            "database_default_read_only": True,
            "relation_share_locks": True,
            "verified": True,
        },
        "version": 3,
    }
    payload["checkpoint_sha256"] = _canonical_sha256(payload)
    _atomic_json(Path(args.path), payload)


def read_checkpoint(args: argparse.Namespace) -> None:
    checkpoint = _validated_checkpoint(Path(args.checkpoint))
    if args.field == "content_cutoff":
        print(checkpoint["baseline"]["content_cutoff"])
    elif args.field == "dump_filename":
        print(checkpoint["dump"]["filename"])
    elif args.field == "dump_sha256":
        print(checkpoint["dump"]["sha256"])
    elif args.field == "version":
        print(checkpoint["version"])
    else:
        print(checkpoint["dump"]["size"])


def read_replaced_checkpoint_dump(args: argparse.Namespace) -> None:
    path = Path(args.checkpoint)
    checkpoint = _load_object(path)
    version = checkpoint.get("version")
    if version in {2, 3}:
        print(_validated_checkpoint(path)["dump"]["filename"])
        return
    if version != 1 or set(checkpoint) != {
        "baseline",
        "checkpoint_sha256",
        "dump",
        "version",
    }:
        raise RuntimeError("교체 대상 clone checkpoint 계약이 올바르지 않습니다")
    digest = checkpoint.get("checkpoint_sha256")
    if not isinstance(digest, str):
        raise RuntimeError("교체 대상 clone checkpoint digest가 없습니다")
    _require_pattern(digest, _SHA256_RE, "clone checkpoint SHA256")
    unsigned = {
        key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"
    }
    if digest != _canonical_sha256(unsigned):
        raise RuntimeError("교체 대상 clone checkpoint digest가 일치하지 않습니다")
    dump = checkpoint.get("dump")
    if not isinstance(dump, dict):
        raise RuntimeError("교체 대상 clone checkpoint dump provenance가 없습니다")
    dump_digest = dump.get("sha256")
    dump_size = dump.get("size")
    if not isinstance(dump_digest, str):
        raise RuntimeError("교체 대상 clone checkpoint dump 값이 없습니다")
    _require_pattern(dump_digest, _SHA256_RE, "dump SHA256")
    if not isinstance(dump_size, int) or isinstance(dump_size, bool) or dump_size < 1:
        raise RuntimeError("교체 대상 clone checkpoint dump size가 올바르지 않습니다")
    if not isinstance(checkpoint.get("baseline"), dict):
        raise RuntimeError("교체 대상 clone checkpoint baseline이 없습니다")
    if set(dump) == {"sha256", "size"}:
        return
    if set(dump) != {"filename", "sha256", "size"}:
        raise RuntimeError("교체 대상 clone checkpoint dump provenance가 없습니다")
    filename = dump.get("filename")
    if not isinstance(filename, str):
        raise RuntimeError("교체 대상 clone checkpoint dump filename이 없습니다")
    print(_require_pattern(filename, _CHECKPOINT_DUMP_RE, "checkpoint dump filename"))


def verify_checkpoint(args: argparse.Namespace) -> None:
    checkpoint = _validated_checkpoint(Path(args.checkpoint))
    snapshot = _validated_snapshot(Path(args.snapshot))
    baseline = checkpoint["baseline"]
    if args.allow_owned_drift:
        stable_keys = {
            "clone_container_sha256",
            "clone_system_identifier_sha256",
            "content_sha256",
            "database_sha256",
            "extension_sha256",
            "host_port",
            "migration_head",
            "relation_count",
            "schema_sha256",
            "version",
        }
        matches = {key: baseline[key] for key in stable_keys} == {
            key: snapshot[key] for key in stable_keys
        }
    else:
        matches = baseline == snapshot
    if not matches:
        raise RuntimeError("현재 clone DB가 trusted checkpoint와 다릅니다")
    print(checkpoint["checkpoint_sha256"])


def write_image_evidence(args: argparse.Namespace) -> None:
    source_commit = _require_pattern(args.source_commit, _COMMIT_RE, "source commit")
    _atomic_json(
        Path(args.path),
        {
            "api": {
                "image_id": _require_pattern(
                    args.api_image_id, _IMAGE_ID_RE, "API image ID"
                ),
                "revision": source_commit,
            },
            "playwright": {
                "image_id": _require_pattern(
                    args.playwright_image_id, _IMAGE_ID_RE, "Playwright image ID"
                ),
                "revision": source_commit,
            },
            "source_commit": source_commit,
            "ui": {
                "image_id": _require_pattern(
                    args.ui_image_id, _IMAGE_ID_RE, "UI image ID"
                ),
                "revision": source_commit,
            },
            "version": 1,
        },
    )


def write_resource_state(args: argparse.Namespace) -> None:
    for value in (
        args.owned_containers,
        args.owned_images,
        args.owned_networks,
    ):
        if value < 0:
            raise RuntimeError("resource count가 올바르지 않습니다")
    _atomic_json(
        Path(args.path),
        {
            "clone_network_attached": args.clone_network_attached,
            "owned_containers": args.owned_containers,
            "owned_images": args.owned_images,
            "owned_networks": args.owned_networks,
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


def _purge_counts(path: Path) -> dict[str, int]:
    evidence = _load_object(path)
    purged = evidence.get("purged")
    if (
        set(evidence)
        != {
            "action",
            "counts",
            "foreign_key_constraints_checked",
            "foreign_key_references",
            "purged",
            "version",
        }
        or evidence.get("version") != 1
        or evidence.get("action") != "purge"
        or evidence.get("counts")
        != {"features": 0, "price_values": 0, "weather_values": 0}
        or evidence.get("foreign_key_references") != 0
        or not isinstance(evidence.get("foreign_key_constraints_checked"), int)
        or evidence["foreign_key_constraints_checked"] < 1
        or not isinstance(purged, dict)
        or set(purged) != {"change_requests", "feature_versions", "features"}
        or not all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in purged.values()
        )
        or purged["features"] > 6
        or purged["feature_versions"] > 13
    ):
        raise RuntimeError("recovery purge evidence가 예상과 다릅니다")
    return purged


def _api_owned_audit_counts(path: Path) -> dict[str, int]:
    evidence = _load_object(path)
    counts = evidence.get("counts")
    if (
        set(evidence)
        != {
            "action",
            "counts",
            "foreign_key_constraints_checked",
            "foreign_key_references",
            "version",
        }
        or evidence.get("version") != 1
        or evidence.get("action") != "api-audit"
        or counts
        != {"change_requests": 14, "feature_versions": 13, "features": 6}
        or evidence.get("foreign_key_references") != 13
        or not isinstance(evidence.get("foreign_key_constraints_checked"), int)
        or evidence["foreign_key_constraints_checked"] < 1
    ):
        raise RuntimeError("API-owned 완료 감사 evidence가 예상과 다릅니다")
    return {
        "change_requests": int(counts["change_requests"]),
        "feature_versions": int(counts["feature_versions"]),
        "features": int(counts["features"]),
    }


def _auth_audit_counts(path: Path, action: str) -> dict[str, int]:
    evidence = _load_object(path)
    counts = evidence.get("counts")
    if (
        set(evidence) != {"action", "counts", "version"}
        or evidence.get("version") != 1
        or evidence.get("action") != action
        or not isinstance(counts, dict)
        or set(counts) != {"main", "recovery"}
        or not all(
            isinstance(value, int) and not isinstance(value, bool) and value >= 0
            for value in counts.values()
        )
    ):
        raise RuntimeError(f"run-bound 인증 감사 evidence가 예상과 다릅니다: {action}")
    if action == "auth-verify" and counts != {"main": 1, "recovery": 1}:
        raise RuntimeError("run-bound 인증 감사 완료 수가 예상과 다릅니다")
    return counts


def _report_counts(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Playwright evidence directory가 아닙니다: {path.name}")
    items = tuple(path.iterdir())
    if {item.name for item in items} != _REPORT_FILES or any(
        item.is_symlink() for item in items
    ):
        raise RuntimeError(f"Playwright evidence exact file set이 아닙니다: {path.name}")
    summary = _load_object(path / "c7-summary.json")
    if (
        summary.get("version") != 1
        or summary.get("result") != "passed"
        or summary.get("testsObserved") != 2
        or summary.get("testsPlanned") != 2
        or summary.get("counts") != {"passed": 2}
        or set(summary)
        != {"counts", "result", "testsObserved", "testsPlanned", "version"}
    ):
        raise RuntimeError(f"Playwright summary가 예상과 다릅니다: {path.name}")

    xml_root = ET.fromstring((path / "c7-results.xml").read_text(encoding="utf-8"))
    if (
        xml_root.tag != "testsuite"
        or xml_root.attrib != {"tests": "2"}
        or xml_root.text not in {None, ""}
        or xml_root.tail not in {None, ""}
    ):
        raise RuntimeError(f"Playwright XML suite가 예상과 다릅니다: {path.name}")
    cases = list(xml_root)
    if len(cases) != 2:
        raise RuntimeError(f"Playwright XML test 수가 예상과 다릅니다: {path.name}")
    xml_durations: list[int] = []
    for index, (case, expected_spec) in enumerate(
        zip(cases, _EXPECTED_TESTS, strict=True), start=1
    ):
        if (
            case.tag != "testcase"
            or case.attrib.get("classname") != "c7-redacted"
            or case.attrib.get("name") != f"{expected_spec}#{index}"
            or set(case.attrib) != {"classname", "name", "time"}
            or list(case)
            or (case.text not in {None, ""})
            or (case.tail not in {None, ""})
        ):
            raise RuntimeError(f"Playwright XML test identity가 다릅니다: {path.name}")
        try:
            duration_ms = round(float(case.attrib["time"]) * 1000)
        except (KeyError, ValueError, OverflowError) as error:
            raise RuntimeError(
                f"Playwright XML duration이 올바르지 않습니다: {path.name}"
            ) from error
        if duration_ms < 0:
            raise RuntimeError(f"Playwright XML duration이 음수입니다: {path.name}")
        xml_durations.append(duration_ms)

    html = (path / "c7-summary.html").read_text(encoding="utf-8")
    html_match = _HTML_REPORT_RE.fullmatch(html)
    if html_match is None:
        raise RuntimeError(f"Playwright HTML summary가 예상과 다릅니다: {path.name}")
    html_durations = [int(value) for value in html_match.groups()]
    if html_durations != xml_durations:
        raise RuntimeError(f"Playwright XML/HTML duration이 다릅니다: {path.name}")
    return {"passed": 2}


def _same_snapshot(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return {key: left.get(key) for key in _SNAPSHOT_KEYS} == {
        key: right.get(key) for key in _SNAPSHOT_KEYS
    }


def _validate_image_evidence(
    path: Path,
    identity: dict[str, str],
) -> None:
    evidence = _load_object(path)
    expected = {
        "api": {
            "image_id": identity["api_image_id"],
            "revision": identity["source_commit"],
        },
        "playwright": {
            "image_id": identity["playwright_image_id"],
            "revision": identity["source_commit"],
        },
        "source_commit": identity["source_commit"],
        "ui": {
            "image_id": identity["ui_image_id"],
            "revision": identity["source_commit"],
        },
        "version": 1,
    }
    if evidence != expected:
        raise RuntimeError("candidate image evidence가 BLOCKED identity와 다릅니다")


def _validate_resources(path: Path) -> None:
    resources = _load_object(path)
    if resources != {
        "clone_network_attached": False,
        "owned_containers": 0,
        "owned_images": 0,
        "owned_networks": 0,
        "version": 1,
    }:
        raise RuntimeError("candidate resource cleanup이 완결되지 않았습니다")


def _build_result(
    args: argparse.Namespace,
    *,
    require_resource_cleanup: bool,
) -> dict[str, Any]:
    runtime = Path(args.runtime)
    blocked = _load_object(Path(args.blocked_path))
    if blocked.get("status") != "blocked" or blocked.get("version") != 2:
        raise RuntimeError("BLOCKED state 계약이 올바르지 않습니다")
    identity = _validated_blocked_identity(blocked)
    phase_history = blocked.get("phase_history")
    if (
        not isinstance(phase_history, list)
        or not phase_history
        or not all(isinstance(item, str) and item for item in phase_history)
        or phase_history[-1] != blocked.get("phase")
    ):
        raise RuntimeError("BLOCKED phase history가 올바르지 않습니다")

    checkpoint = _validated_checkpoint(runtime / "clone-checkpoint.json")
    if checkpoint["checkpoint_sha256"] != identity["clone_checkpoint_sha256"]:
        raise RuntimeError("BLOCKED clone checkpoint가 runtime checkpoint와 다릅니다")
    startup_before = _validated_snapshot(runtime / "clone-startup-before.json")
    startup_after = _validated_snapshot(runtime / "clone-startup-after.json")
    final = _validated_snapshot(runtime / "clone-final.json")
    if checkpoint["baseline"] != startup_before:
        raise RuntimeError("startup clone DB가 trusted checkpoint와 다릅니다")
    if not _same_snapshot(startup_before, startup_after):
        raise RuntimeError("candidate startup이 clone DB identity/schema/data를 변경했습니다")
    clone_identity = (
        f"{startup_before['clone_container_sha256']}\n"
        f"{startup_before['clone_system_identifier_sha256']}\n"
        f"{startup_before['host_port']}\n"
        f"{startup_before['migration_head']}\n"
        f"{startup_before['database_sha256']}\n"
        f"{startup_before['extension_sha256']}\n"
        f"{startup_before['schema_sha256']}\n"
        f"{startup_before['content_sha256']}\n"
    )
    if identity["clone_identity_sha256"] != _sha256(clone_identity):
        raise RuntimeError("BLOCKED clone identity가 DB snapshot과 다릅니다")
    for key in (
        "clone_container_sha256",
        "clone_system_identifier_sha256",
        "content_sha256",
        "database_sha256",
        "extension_sha256",
        "host_port",
        "migration_head",
        "relation_count",
        "schema_sha256",
        "version",
    ):
        if final[key] != startup_before[key]:
            raise RuntimeError("최종 clone DB identity/schema/content가 시작 기준과 다릅니다")
    if final["feature_non_deleted"] != startup_before["feature_non_deleted"]:
        raise RuntimeError("최종 non-deleted Feature 수가 시작 기준과 다릅니다")
    if final["feature_total"] != startup_before["feature_total"] + 6:
        raise RuntimeError("최종 soft-delete 감사 Feature 6건이 예상과 다릅니다")
    if (
        final["active_owned_features"] != 0
        or final["nonterminal_owned_change_requests"] != 0
    ):
        raise RuntimeError("최종 API-owned Feature/change request residue가 있습니다")

    if args.phase == "recovered":
        if args.current_snapshot is None or args.recovery_tool_source_commit is None:
            raise RuntimeError("recovery 완료에는 현재 snapshot/tool commit이 필요합니다")
        current = _validated_snapshot(Path(args.current_snapshot))
        if not _same_snapshot(final, current):
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
    api_owned_audit = _api_owned_audit_counts(runtime / "api-owned-audit.json")
    auth_audit = _auth_audit_counts(runtime / "auth-audit.json", "auth-verify")
    purge = {"change_requests": 0, "feature_versions": 0, "features": 0}
    if "recovery-hard-purge-running" in phase_history:
        purge = _purge_counts(runtime / "direct-purge-interrupted.json")
    auth_reset = {"main": 0, "recovery": 0}
    if "recovery-auth-reset-running" in phase_history:
        auth_reset = _auth_audit_counts(
            runtime / "auth-audit-reset.json",
            "auth-reset",
        )
    tests = {
        "main": _report_counts(runtime / "playwright-main"),
        "recovery": _report_counts(runtime / "playwright-recovery"),
    }
    _validate_image_evidence(runtime / "image-evidence.json", identity)
    if require_resource_cleanup:
        _validate_resources(runtime / "resource-final.json")

    canonical_identity = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return {
        "cleanup": {
            "foreign_key_references": cleanup["foreign_key_references"],
            "owned_features": cleanup["counts"]["features"],
            "api_owned_change_requests": api_owned_audit["change_requests"],
            "api_owned_features": api_owned_audit["features"],
            "api_owned_feature_versions": api_owned_audit["feature_versions"],
            "auth_audit_main": auth_audit["main"],
            "auth_audit_recovery": auth_audit["recovery"],
            "recovery_auth_reset_main": auth_reset["main"],
            "recovery_auth_reset_recovery": auth_reset["recovery"],
            "recovery_purged_change_requests": purge["change_requests"],
            "recovery_purged_feature_versions": purge["feature_versions"],
            "recovery_purged_features": purge["features"],
            "api_owned_active_features": final["active_owned_features"],
            "api_owned_nonterminal_change_requests": final[
                "nonterminal_owned_change_requests"
            ],
            "post_cleanup_audit_features": audit["counts"]["features"],
        },
        "execution_identity_sha256": _sha256(canonical_identity),
        "isolation": {
            "clone_checkpoint_sha256": identity["clone_checkpoint_sha256"],
            "clone_container_sha256": startup_before["clone_container_sha256"],
            "clone_system_identifier_sha256": startup_before[
                "clone_system_identifier_sha256"
            ],
            "database_sha256": startup_before["database_sha256"],
            "extension_sha256": startup_before["extension_sha256"],
            "content_sha256": startup_before["content_sha256"],
            "host_port": startup_before["host_port"],
            "production_compose_project_excluded": True,
            "schema_sha256": startup_before["schema_sha256"],
            "startup_migration_unchanged": True,
        },
        "phase": args.phase,
        "phase_history": phase_history,
        "recovery_tool_source_commit": recovery_tool_source_commit,
        "source_commit": identity["source_commit"],
        "status": "complete",
        "tests": tests,
        "version": 2,
    }


def validate_evidence(args: argparse.Namespace) -> None:
    _build_result(args, require_resource_cleanup=False)


def complete(args: argparse.Namespace) -> None:
    blocked_path = Path(args.blocked_path)
    result = _build_result(args, require_resource_cleanup=True)
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
    parser.add_argument("--clone-checkpoint-sha256", required=True)
    parser.add_argument("--clone-identity-sha256", required=True)
    parser.add_argument("--network-name", required=True)
    parser.add_argument("--playwright-image-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--ui-image-id", required=True)


def _add_completion_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--blocked-path", required=True)
    parser.add_argument("--current-snapshot")
    parser.add_argument("--phase", choices=("passed", "recovered"), required=True)
    parser.add_argument("--recovery-tool-source-commit")
    parser.add_argument("--runtime", required=True)


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
            "clone_checkpoint_sha256",
            "clone_identity_sha256",
            "network_name",
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
    snapshot.add_argument("--content-cutoff", required=True)
    snapshot.add_argument("--content-sha256", required=True)
    snapshot.add_argument("--database-sha256", required=True)
    snapshot.add_argument("--extension-sha256", required=True)
    snapshot.add_argument("--feature-non-deleted", required=True, type=int)
    snapshot.add_argument("--feature-total", required=True, type=int)
    snapshot.add_argument("--host-port", required=True, type=int)
    snapshot.add_argument("--migration-head", required=True)
    snapshot.add_argument(
        "--nonterminal-owned-change-requests", required=True, type=int
    )
    snapshot.add_argument("--relation-count", required=True, type=int)
    snapshot.add_argument("--schema-sha256", required=True)
    snapshot.set_defaults(handler=write_snapshot)

    checkpoint = subparsers.add_parser("write-checkpoint")
    checkpoint.add_argument("--dump-filename", required=True)
    checkpoint.add_argument("--dump-sha256", required=True)
    checkpoint.add_argument("--dump-size", required=True, type=int)
    checkpoint.add_argument("--final-snapshot", required=True)
    checkpoint.add_argument("--path", required=True)
    checkpoint.add_argument("--restored-snapshot", required=True)
    checkpoint.add_argument("--snapshot", required=True)
    checkpoint.set_defaults(handler=write_checkpoint)

    promote = subparsers.add_parser("promote-checkpoint")
    promote.add_argument("--checkpoint", required=True)
    promote.add_argument("--final-snapshot", required=True)
    promote.add_argument("--path", required=True)
    promote.set_defaults(handler=promote_checkpoint)

    for command, handler in (
        ("write-scratch", write_scratch),
        ("claim-scratch", claim_scratch),
        ("read-scratch", read_scratch),
        ("clear-scratch", clear_scratch),
    ):
        scratch = subparsers.add_parser(command)
        scratch.add_argument("--clone-container-sha256", required=True)
        scratch.add_argument("--clone-system-identifier-sha256", required=True)
        scratch.add_argument("--path", required=True)
        if command == "write-scratch":
            scratch.add_argument("--database", required=True)
            scratch.add_argument("--ownership-token", required=True)
            scratch.add_argument("--owner-role", required=True)
        elif command == "claim-scratch":
            scratch.add_argument("--database-oid", required=True, type=int)
            scratch.add_argument("--owner-role-oid", type=int)
        elif command == "read-scratch":
            scratch.add_argument(
                "--field",
                choices=(
                    "database",
                    "database_oid",
                    "owner_role",
                    "owner_role_oid",
                    "ownership_token",
                    "version",
                ),
                required=True,
            )
        scratch.set_defaults(handler=handler)

    for command, handler in (
        ("write-quiescence", write_quiescence),
        ("read-quiescence", read_quiescence),
        ("clear-quiescence", clear_quiescence),
    ):
        quiescence = subparsers.add_parser(command)
        quiescence.add_argument("--clone-container-sha256", required=True)
        quiescence.add_argument("--clone-system-identifier-sha256", required=True)
        quiescence.add_argument("--path", required=True)
        if command == "write-quiescence":
            quiescence.add_argument("--database", required=True)
        elif command == "read-quiescence":
            quiescence.add_argument(
                "--field",
                choices=("database", "setting", "version"),
                required=True,
            )
        quiescence.set_defaults(handler=handler)

    checkpoint_read = subparsers.add_parser("read-checkpoint")
    checkpoint_read.add_argument("--checkpoint", required=True)
    checkpoint_read.add_argument(
        "--field",
        choices=(
            "content_cutoff",
            "dump_filename",
            "dump_sha256",
            "dump_size",
            "version",
        ),
        required=True,
    )
    checkpoint_read.set_defaults(handler=read_checkpoint)

    replaced_checkpoint = subparsers.add_parser("read-replaced-checkpoint-dump")
    replaced_checkpoint.add_argument("--checkpoint", required=True)
    replaced_checkpoint.set_defaults(handler=read_replaced_checkpoint_dump)

    checkpoint_verify = subparsers.add_parser("verify-checkpoint")
    checkpoint_verify.add_argument("--allow-owned-drift", action="store_true")
    checkpoint_verify.add_argument("--checkpoint", required=True)
    checkpoint_verify.add_argument("--snapshot", required=True)
    checkpoint_verify.set_defaults(handler=verify_checkpoint)

    image_evidence = subparsers.add_parser("write-image-evidence")
    image_evidence.add_argument("--api-image-id", required=True)
    image_evidence.add_argument("--path", required=True)
    image_evidence.add_argument("--playwright-image-id", required=True)
    image_evidence.add_argument("--source-commit", required=True)
    image_evidence.add_argument("--ui-image-id", required=True)
    image_evidence.set_defaults(handler=write_image_evidence)

    resource_state = subparsers.add_parser("write-resource-state")
    resource_state.add_argument(
        "--clone-network-attached",
        action=argparse.BooleanOptionalAction,
        required=True,
    )
    resource_state.add_argument("--owned-containers", required=True, type=int)
    resource_state.add_argument("--owned-images", required=True, type=int)
    resource_state.add_argument("--owned-networks", required=True, type=int)
    resource_state.add_argument("--path", required=True)
    resource_state.set_defaults(handler=write_resource_state)

    validate = subparsers.add_parser("validate-evidence")
    _add_completion_arguments(validate)
    validate.set_defaults(handler=validate_evidence)

    finish = subparsers.add_parser("complete")
    _add_completion_arguments(finish)
    finish.add_argument("--result-path", required=True)
    finish.set_defaults(handler=complete)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()

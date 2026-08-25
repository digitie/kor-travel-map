#!/usr/bin/env python3
"""C7 production runner의 root snapshot·runtime attestation 검증 코어."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SCHEMA_HEAD_PATTERN = re.compile(r"^[0-9a-z][0-9a-z_.-]{0,127}$")
DATABASE_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
POSTGRES_SYSTEM_IDENTIFIER_PATTERN = re.compile(r"^[0-9]{1,32}$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
ORCHESTRATOR_PATHS = (
    "scripts/audit-c7-prod-live-state.py",
    "scripts/lib/c7-prod-runner-lifecycle.sh",
    "scripts/lib/c7_prod_attestation.py",
    "scripts/run-c7-prod-live-e2e.sh",
)
# v6 generation은 Map 4개와 PinVi 3개를 **함께** 고정한다. v4 pair는 PinVi web/dagster를
# 담지 않아 두 runtime이 세대 밖에서 흔들려도 통과했다. 일곱 전부를 compose service로
# 실측 대조하려고 role을 일곱으로 늘린다.
GENERATION_RUNTIME_IMAGE_FIELDS = (
    ("map_api", "map_api_image_id"),
    ("map_ui", "map_ui_image_id"),
    ("map_dagster_web", "map_dagster_image_id"),
    ("map_dagster_daemon", "map_dagster_daemon_image_id"),
    ("pinvi_api", "pinvi_api_image_id"),
    ("pinvi_web", "pinvi_web_image_id"),
    ("pinvi_dagster", "pinvi_dagster_image_id"),
)
GENERATION_SCHEMA_HEAD_FIELDS = (
    "map_application_head",
    "map_dagster_head",
    "pinvi_head",
)
_PINVI_ROLES = frozenset({"pinvi_api", "pinvi_web", "pinvi_dagster"})
# ktdm `PinnedRuntimeGeneration.to_payload()`의 exact key 집합. 하나라도 빠지거나 늘면
# 세대 정의가 갈린 것이므로 통과시키지 않는다.
_GENERATION_KEYS = frozenset(
    {field for _, field in GENERATION_RUNTIME_IMAGE_FIELDS}
    | set(GENERATION_SCHEMA_HEAD_FIELDS)
    | {
        "map_source_revision",
        "pinvi_source_revision",
        "pinset_sha256",
        "map_application_300_candidate_evidence",
        "recorded_at",
    }
)
_MAP_APPLICATION_300_CANDIDATE_EVIDENCE_KEYS = frozenset(
    {
        "paired_receipt_sha256",
        "api_receipt_sha256",
        "candidate_git_tree",
        "postgres_image_id",
        "dagster_config_sha256",
        "dagster_yaml_sha256",
        "application_contract_sha256",
        "launch_contract_sha256",
    }
)
# ktdm `PinnedRuntimeRebuildJournal`의 exact key 집합과 최종 phase.
_JOURNAL_KEYS = frozenset(
    {
        "version",
        "transaction_id",
        "phase",
        "candidate",
        "map_application_300_candidate_evidence",
        "environment_sha256",
        "compose_sha256",
        "resolved_compose_sha256",
        "created_at",
        "pinvi_database_identity",
        "journal_generation",
        "map_application_300_execution_evidence",
        "cancel_probe",
    }
)
_JOURNAL_COMMITTED_PHASE = "committed"
_JOURNAL_COMMITTED_MIN_GENERATION = 27
_MAP_APPLICATION_300_EXECUTION_EVIDENCE_KEYS = frozenset(
    {
        "application_create_database_identity",
        "application_create_database_identity_sha256",
        "application_database_identity",
        "application_database_identity_sha256",
        "fresh_root_operation_plan",
        "fresh_finalize_operation_plan",
        "app_final_permit_sha256",
        "dagster_metadata_database_identity",
        "dagster_metadata_database_identity_sha256",
        "metadata_permit_sha256",
    }
)
_APPLICATION_DATABASE_IDENTITY_KEYS = frozenset(
    {
        "database_name",
        "database_oid",
        "database_owner",
        "postgres_system_identifier",
    }
)
_PINNED_DATABASE_IDENTITY_KEYS = frozenset(
    {"system_identifier", "name", "oid", "owner", "login_role"}
)
_DAGSTER_METADATA_DATABASE_IDENTITY_KEYS = frozenset(
    {
        "system_identifier",
        "name",
        "oid",
        "owner",
        "login_role",
        "login_role_attributes",
    }
)
_DAGSTER_METADATA_ROLE_ATTRIBUTE_KEYS = frozenset(
    {
        "can_login",
        "inherit",
        "superuser",
        "create_database",
        "create_role",
        "replication",
        "bypass_rls",
        "connection_limit",
        "valid_until_is_null",
        "role_config_count",
        "database_role_setting_count",
        "granted_role_count",
        "member_role_count",
    }
)
_APPLICATION_OPERATION_PLAN_KEYS = frozenset(
    {
        "transaction_id",
        "operation_id",
        "basis_journal_sha256",
        "basis_journal_generation",
        "writer_fence_expires_at",
        "fence_sha256",
        "result_sha256",
    }
)
# ktdm `PinnedRuntimeCancelProbeReceipt.to_payload()` / `PinnedRuntimeCancelProbeOutcome`의
# exact key 집합. 다른 sub-document와 같은 강도로 고정한다 — 여기만 느슨하면 ktdm에서
# 계약이 갈려도 감지되지 않는다.
_CANCEL_PROBE_KEYS = frozenset(
    {
        "stage",
        "job_id",
        "cancellation_id",
        "outcome",
        "fixture_created_at",
        "fixture_consumed_at",
        "fixture_finalized_at",
    }
)
_CANCEL_PROBE_OUTCOME = {
    "name": "pinvi_cancel_error",
    "status": 409,
    "code": "PIPELINE_CANCELLATION_UNSAFE",
}

CommandRunner = Callable[[list[str], str], str]
SecureReader = Callable[[Path, int], bytes]

_CURSOR_SECRET_ENV = "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET"
_CURSOR_PROTECTED_ENVS = {
    "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
    "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
    "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
    "KOR_TRAVEL_MAP_API_VWORLD_API_KEY",
}


class AttestationError(RuntimeError):
    """Attestation 계약 위반을 값 노출 없이 나타낸다."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode())


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _canonical_document_sha256(value: object) -> str:
    """Manager의 canonical evidence payload digest(JSON + LF)를 재현한다."""

    return _sha256_bytes(
        (
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    )


def _exact_dict(value: object, keys: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == keys


def _runtime_environment(items: list[str]) -> dict[str, str]:
    """Docker Env 배열을 중복 없는 exact name/value mapping으로 만든다."""

    values: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise AttestationError("runtime environment shape")
        name, value = item.split("=", 1)
        if not name or name in values:
            raise AttestationError("runtime environment shape")
        values[name] = value
    return values


def _validate_cursor_secret_runtime(role: str, environment: dict[str, str]) -> None:
    """T-VN-15 cursor secret의 API-only shape·전용성을 값 노출 없이 검증한다."""

    if role != "map_api":
        if _CURSOR_SECRET_ENV in environment:
            raise AttestationError("cursor secret escaped API runtime")
        return
    cursor = environment.get(_CURSOR_SECRET_ENV)
    if (
        environment.get("KOR_TRAVEL_MAP_API_PROFILE") != "production"
        or environment.get("KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED") != "true"
        or cursor is None
        or len(cursor) < 32
        or any(character.isspace() for character in cursor)
    ):
        raise AttestationError("cursor secret runtime shape")
    protected = {
        environment[name]
        for name in _CURSOR_PROTECTED_ENVS
        if name in environment and environment[name]
    }
    if cursor in protected:
        raise AttestationError("cursor secret runtime reuse")


def _read_secure_file(
    path: Path,
    mode: int,
    *,
    expected_uid: int = 0,
    expected_gid: int = 0,
    ancestor_floor: Path | None = None,
) -> bytes:
    """symlink·owner·mode·writable ancestor를 거부하고 regular file bytes를 읽는다."""

    if not path.is_absolute():
        raise AttestationError("root file path is not absolute")
    floor = ancestor_floor
    if floor is not None:
        floor = floor.resolve(strict=True)
        try:
            path.relative_to(floor)
        except ValueError as exc:
            raise AttestationError("file is outside trusted ancestor floor") from exc
    reached_floor = floor is None
    for parent in path.parents:
        observed_parent = parent.lstat()
        if (
            not stat.S_ISDIR(observed_parent.st_mode)
            or parent.is_symlink()
            or observed_parent.st_uid != expected_uid
            or observed_parent.st_gid != expected_gid
            or stat.S_IMODE(observed_parent.st_mode) & 0o022
        ):
            raise AttestationError("unsafe root file parent")
        if floor is not None and parent == floor:
            reached_floor = True
            break
    if not reached_floor:
        raise AttestationError("trusted ancestor floor was not reached")

    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != expected_uid
            or observed.st_gid != expected_gid
            or stat.S_IMODE(observed.st_mode) != mode
        ):
            raise AttestationError("unsafe root-owned file")
        chunks: list[bytes] = []
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _root_reader(path: Path, mode: int) -> bytes:
    return _read_secure_file(path, mode)


def verify_root_owned_orchestrator_snapshot(
    snapshot_root: Path,
    runner_path: Path,
    audit_path: Path,
    helper_path: Path,
    module_path: Path,
    attestation_path: Path,
    expected_commit: str,
    *,
    expected_base: Path = Path("/usr/local/lib/kor-travel-map/c7-runner"),
    secure_reader: SecureReader = _root_reader,
) -> None:
    """exact commit root 아래 네 orchestrator 파일의 위치·shape·hash를 검증한다."""

    expected_root = expected_base / expected_commit
    expected_files = {
        ORCHESTRATOR_PATHS[0]: audit_path,
        ORCHESTRATOR_PATHS[1]: helper_path,
        ORCHESTRATOR_PATHS[2]: module_path,
        ORCHESTRATOR_PATHS[3]: runner_path,
    }
    if (
        COMMIT_PATTERN.fullmatch(expected_commit) is None
        or snapshot_root != expected_root
        or runner_path != snapshot_root / ORCHESTRATOR_PATHS[3]
        or audit_path != snapshot_root / ORCHESTRATOR_PATHS[0]
        or helper_path != snapshot_root / ORCHESTRATOR_PATHS[1]
        or module_path != snapshot_root / ORCHESTRATOR_PATHS[2]
    ):
        raise AttestationError("orchestrator snapshot identity")

    attestation_bytes = secure_reader(attestation_path, 0o600)
    try:
        attestation = json.loads(attestation_bytes)
    except (TypeError, ValueError) as exc:
        raise AttestationError("attestation JSON") from exc
    if not isinstance(attestation, dict):
        raise AttestationError("attestation shape")
    orchestrator_files = attestation.get("orchestrator_files")
    if attestation.get("repository_commit") != expected_commit or not _exact_dict(
        orchestrator_files, set(expected_files)
    ):
        raise AttestationError("orchestrator file attestation shape")
    assert isinstance(orchestrator_files, dict)
    for relative, path in expected_files.items():
        expected_sha256 = orchestrator_files[relative]
        if (
            not isinstance(expected_sha256, str)
            or SHA256_PATTERN.fullmatch(expected_sha256) is None
            or _sha256_bytes(secure_reader(path, 0o555)) != expected_sha256
        ):
            raise AttestationError("orchestrator file attestation mismatch")


def _public_origin(raw: str, *, websocket: bool = False, require_root_path: bool = True) -> str:
    parsed = urlsplit(raw)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.hostname
        or (require_root_path and parsed.path not in {"", "/"})
        or parsed.query
        or parsed.fragment
    ):
        raise AttestationError("unsafe origin")
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise AttestationError("local origin")
    if "%" in host:
        # IPv6 zone-id(scope)는 로컬 인터페이스 스코프라 public origin에 유효하지 않다.
        raise AttestationError("scoped address")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_loopback or address.is_link_local or address.is_unspecified
    ):
        raise AttestationError("unsafe address")
    port = f":{parsed.port}" if parsed.port is not None else ""
    # IPv6 리터럴 host는 netloc 재구성 시 bracket으로 감싸야 `:port`와 모호하지 않다
    # (예: `2001:db8::1` + `:443` → `[2001:db8::1]:443`). 압축 canonical 형으로 정규화해
    # 동등한 IPv6 표기가 같은 origin으로 해시되게 한다. domain/IPv4는 무변경.
    netloc_host = f"[{address.compressed}]" if isinstance(address, ipaddress.IPv6Address) else host
    return urlunsplit(("wss" if websocket else "https", f"{netloc_host}{port}", "", "", ""))


def _canonical_graphql(raw: str) -> str:
    parsed = urlsplit(raw)
    origin = _public_origin(raw, require_root_path=False)
    pathname = parsed.path.rstrip("/")
    pathname = pathname if pathname.endswith("/graphql") else f"{pathname}/graphql"
    return f"{origin}{pathname}"


def _subprocess_output(command: list[str], project_directory: str) -> str:
    completed = subprocess.run(
        command,
        cwd=project_directory,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _compose_container(
    service: str,
    project_directory: str,
    run_json: CommandRunner,
) -> dict[str, object]:
    ids_value = run_json(
        [
            "docker",
            "compose",
            "--project-directory",
            project_directory,
            "ps",
            "-q",
            service,
        ],
        project_directory,
    )
    if not isinstance(ids_value, str):
        raise AttestationError("compose service output")
    ids = [line.strip() for line in ids_value.splitlines() if line.strip()]
    if len(ids) != 1:
        raise AttestationError("compose service cardinality")
    records = json.loads(run_json(["docker", "inspect", "--", ids[0]], project_directory))
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise AttestationError("container inspect shape")
    return records[0]


def _validate_generation(value: object) -> None:
    """v6 ``PinnedRuntimeGeneration`` payload를 exact shape으로 검증한다."""

    if not _exact_dict(value, set(_GENERATION_KEYS)):
        raise AttestationError("generation shape")
    assert isinstance(value, dict)
    for _, field in GENERATION_RUNTIME_IMAGE_FIELDS:
        image_id = value[field]
        if not isinstance(image_id, str) or IMAGE_PATTERN.fullmatch(image_id) is None:
            raise AttestationError("generation image")
    for field in ("map_source_revision", "pinvi_source_revision"):
        revision = value[field]
        if not isinstance(revision, str) or COMMIT_PATTERN.fullmatch(revision) is None:
            raise AttestationError("generation source revision")
    for field in GENERATION_SCHEMA_HEAD_FIELDS:
        head = value[field]
        if not isinstance(head, str) or SCHEMA_HEAD_PATTERN.fullmatch(head) is None:
            raise AttestationError("generation schema head")
    pinset = value["pinset_sha256"]
    if not isinstance(pinset, str) or SHA256_PATTERN.fullmatch(pinset) is None:
        raise AttestationError("generation pinset")
    _validate_candidate_evidence(value["map_application_300_candidate_evidence"])
    _validate_utc_timestamp(value["recorded_at"], "generation recorded_at")


def _validate_candidate_evidence(value: object) -> None:
    if not _exact_dict(value, set(_MAP_APPLICATION_300_CANDIDATE_EVIDENCE_KEYS)):
        raise AttestationError("generation candidate evidence shape")
    assert isinstance(value, dict)
    for field in _MAP_APPLICATION_300_CANDIDATE_EVIDENCE_KEYS - {
        "candidate_git_tree",
        "postgres_image_id",
    }:
        digest = value[field]
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise AttestationError("generation candidate evidence digest")
    tree = value["candidate_git_tree"]
    postgres_image = value["postgres_image_id"]
    if not isinstance(tree, str) or COMMIT_PATTERN.fullmatch(tree) is None:
        raise AttestationError("generation candidate git tree")
    if not isinstance(postgres_image, str) or IMAGE_PATTERN.fullmatch(postgres_image) is None:
        raise AttestationError("generation candidate PostgreSQL image")


def _validate_application_database_identity(value: object, *, label: str) -> None:
    if not _exact_dict(value, set(_APPLICATION_DATABASE_IDENTITY_KEYS)):
        raise AttestationError(f"{label} shape")
    assert isinstance(value, dict)
    if (
        not isinstance(value["database_name"], str)
        or DATABASE_IDENTIFIER_PATTERN.fullmatch(value["database_name"]) is None
        or type(value["database_oid"]) is not int
        or value["database_oid"] <= 0
        or not isinstance(value["database_owner"], str)
        or DATABASE_IDENTIFIER_PATTERN.fullmatch(value["database_owner"]) is None
        or not isinstance(value["postgres_system_identifier"], str)
        or POSTGRES_SYSTEM_IDENTIFIER_PATTERN.fullmatch(
            value["postgres_system_identifier"]
        )
        is None
    ):
        raise AttestationError(label)


def _validate_dagster_metadata_database_identity(value: object) -> None:
    if not _exact_dict(value, set(_DAGSTER_METADATA_DATABASE_IDENTITY_KEYS)):
        raise AttestationError("journal Dagster metadata identity shape")
    assert isinstance(value, dict)
    role = value["login_role_attributes"]
    if not _exact_dict(role, set(_DAGSTER_METADATA_ROLE_ATTRIBUTE_KEYS)):
        raise AttestationError("journal Dagster metadata role shape")
    assert isinstance(role, dict)
    canonical_flags = {
        "can_login": True,
        "inherit": False,
        "superuser": False,
        "create_database": False,
        "create_role": False,
        "replication": False,
        "bypass_rls": False,
    }
    if any(
        type(role[field]) is not bool or role[field] is not expected
        for field, expected in canonical_flags.items()
    ):
        raise AttestationError("journal Dagster metadata role privilege")
    if (
        type(role["connection_limit"]) is not int
        or role["connection_limit"] != -1
        or role["valid_until_is_null"] is not True
        or type(role["role_config_count"]) is not int
        or role["role_config_count"] != 0
        or type(role["database_role_setting_count"]) is not int
        or role["database_role_setting_count"] != 0
        or type(role["granted_role_count"]) is not int
        or role["granted_role_count"] != 0
        or type(role["member_role_count"]) is not int
        or role["member_role_count"] != 0
    ):
        raise AttestationError("journal Dagster metadata role membership")
    if (
        not isinstance(value["system_identifier"], str)
        or POSTGRES_SYSTEM_IDENTIFIER_PATTERN.fullmatch(value["system_identifier"])
        is None
        or type(value["oid"]) is not int
        or value["oid"] <= 0
    ):
        raise AttestationError("journal Dagster metadata identity")
    for field in ("name", "owner", "login_role"):
        identifier = value[field]
        if (
            not isinstance(identifier, str)
            or DATABASE_IDENTIFIER_PATTERN.fullmatch(identifier) is None
        ):
            raise AttestationError("journal Dagster metadata identity")
    if value["owner"] != value["login_role"]:
        raise AttestationError("journal Dagster metadata owner")


def _validate_pinned_database_identity(value: object) -> None:
    if not _exact_dict(value, set(_PINNED_DATABASE_IDENTITY_KEYS)):
        raise AttestationError("journal PinVi database identity shape")
    assert isinstance(value, dict)
    if (
        not isinstance(value["system_identifier"], str)
        or POSTGRES_SYSTEM_IDENTIFIER_PATTERN.fullmatch(value["system_identifier"])
        is None
        or type(value["oid"]) is not int
        or value["oid"] <= 0
    ):
        raise AttestationError("journal PinVi database identity")
    for field in ("name", "owner", "login_role"):
        identifier = value[field]
        if (
            not isinstance(identifier, str)
            or DATABASE_IDENTIFIER_PATTERN.fullmatch(identifier) is None
        ):
            raise AttestationError("journal PinVi database identity")
    if value["owner"] != value["login_role"]:
        raise AttestationError("journal PinVi database owner")


def _validate_operation_plan(value: object, *, label: str) -> None:
    if not _exact_dict(value, set(_APPLICATION_OPERATION_PLAN_KEYS)):
        raise AttestationError(f"journal {label} operation plan shape")
    assert isinstance(value, dict)
    for field in ("transaction_id", "operation_id"):
        identifier = value[field]
        if not isinstance(identifier, str) or UUID_PATTERN.fullmatch(identifier) is None:
            raise AttestationError(f"journal {label} operation identity")
    for field in ("basis_journal_sha256", "fence_sha256", "result_sha256"):
        digest = value[field]
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise AttestationError(f"journal {label} operation digest")
    if (
        type(value["basis_journal_generation"]) is not int
        or value["basis_journal_generation"] < 0
    ):
        raise AttestationError(f"journal {label} operation generation")
    _validate_utc_timestamp(
        value["writer_fence_expires_at"],
        f"journal {label} operation fence expiry",
    )


def _validate_application_execution_evidence(
    value: object,
    *,
    journal_generation: int,
) -> None:
    if not _exact_dict(value, set(_MAP_APPLICATION_300_EXECUTION_EVIDENCE_KEYS)):
        raise AttestationError("journal application execution evidence shape")
    assert isinstance(value, dict)
    create_identity = value["application_create_database_identity"]
    application_identity = value["application_database_identity"]
    dagster_identity = value["dagster_metadata_database_identity"]
    _validate_application_database_identity(
        create_identity,
        label="journal application create identity",
    )
    _validate_application_database_identity(
        application_identity,
        label="journal application identity",
    )
    _validate_dagster_metadata_database_identity(dagster_identity)
    assert isinstance(create_identity, dict)
    assert isinstance(application_identity, dict)
    if any(
        create_identity[field] != application_identity[field]
        for field in ("database_name", "database_oid", "postgres_system_identifier")
    ):
        raise AttestationError("journal application database identity changed")
    for identity_field, digest_field, label in (
        (
            "application_create_database_identity",
            "application_create_database_identity_sha256",
            "journal application create identity digest",
        ),
        (
            "application_database_identity",
            "application_database_identity_sha256",
            "journal application identity digest",
        ),
        (
            "dagster_metadata_database_identity",
            "dagster_metadata_database_identity_sha256",
            "journal Dagster metadata identity digest",
        ),
    ):
        digest = value[digest_field]
        if (
            not isinstance(digest, str)
            or SHA256_PATTERN.fullmatch(digest) is None
            or digest != _canonical_document_sha256(value[identity_field])
        ):
            raise AttestationError(label)
    for field in ("app_final_permit_sha256", "metadata_permit_sha256"):
        digest = value[field]
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise AttestationError("journal application permit digest")
    root_plan = value["fresh_root_operation_plan"]
    finalize_plan = value["fresh_finalize_operation_plan"]
    _validate_operation_plan(root_plan, label="root")
    _validate_operation_plan(finalize_plan, label="finalize")
    assert isinstance(root_plan, dict)
    assert isinstance(finalize_plan, dict)
    if (
        root_plan["operation_id"] == finalize_plan["operation_id"]
        or root_plan["basis_journal_generation"] >= journal_generation
        or finalize_plan["basis_journal_generation"] >= journal_generation
    ):
        raise AttestationError("journal application operation lineage")


def _validate_utc_timestamp(value: object, label: str) -> None:
    """ktdm과 같은 강도로 **UTC**를 요구한다.

    앞 판은 tz-aware이기만 하면 통과시켰다. ktdm은 offset 0을 강제하므로
    (`pinned_runtime_generation.py`) `+09:00` 문서는 애초에 만들어지지 않는다.
    이름이 UTC라고 말하면서 UTC를 보지 않으면, 다음 사람이 이 함수를 근거로
    "타임존은 검증된다"고 믿는다.
    """

    if not isinstance(value, str):
        raise AttestationError(label)
    observed_at = datetime.fromisoformat(value)
    if observed_at.utcoffset() != timedelta(0):
        raise AttestationError(label)


def _validate_committed_journal(value: object, *, generation: Mapping[str, object]) -> None:
    """v8 rebuild journal이 **이 세대를 commit한 그 transaction**인지 확인한다.

    manifest만 보면 "어떤 세대가 active인가"는 알아도 "그 세대가 파괴적 rebuild를
    끝까지 통과했는가"는 알 수 없다. journal의 phase가 ``committed``이고 candidate가
    manifest의 active generation과 **글자 그대로 같아야** 두 문서가 한 transaction의
    앞뒤라는 것이 증명된다. 그래서 부분 비교가 아니라 전체 동등성을 요구한다.
    """

    if not _exact_dict(value, set(_JOURNAL_KEYS)) or value["version"] != 8:
        raise AttestationError("journal shape")
    assert isinstance(value, dict)
    transaction_id = value["transaction_id"]
    if not isinstance(transaction_id, str) or UUID_PATTERN.fullmatch(transaction_id) is None:
        raise AttestationError("journal transaction identity")
    if value["phase"] != _JOURNAL_COMMITTED_PHASE:
        raise AttestationError("journal is not committed")
    journal_generation = value["journal_generation"]
    if (
        type(journal_generation) is not int
        or journal_generation < _JOURNAL_COMMITTED_MIN_GENERATION
    ):
        raise AttestationError("journal generation")
    for field in ("environment_sha256", "compose_sha256", "resolved_compose_sha256"):
        digest = value[field]
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise AttestationError("journal input digest")
    _validate_utc_timestamp(value["created_at"], "journal created_at")
    _validate_generation(value["candidate"])
    if value["candidate"] != generation:
        raise AttestationError("journal candidate is not the active generation")
    candidate_evidence = value["map_application_300_candidate_evidence"]
    _validate_candidate_evidence(candidate_evidence)
    if candidate_evidence != generation["map_application_300_candidate_evidence"]:
        raise AttestationError("journal candidate evidence differs")
    _validate_application_execution_evidence(
        value["map_application_300_execution_evidence"],
        journal_generation=journal_generation,
    )
    _validate_pinned_database_identity(value["pinvi_database_identity"])
    cancel_probe = value["cancel_probe"]
    if not _exact_dict(cancel_probe, set(_CANCEL_PROBE_KEYS)):
        raise AttestationError("journal cancel probe shape")
    assert isinstance(cancel_probe, dict)
    if cancel_probe["stage"] != "finalized":
        raise AttestationError("journal cancel probe is not finalized")
    if cancel_probe["outcome"] != _CANCEL_PROBE_OUTCOME:
        raise AttestationError("journal cancel probe outcome")
    for field in ("job_id", "cancellation_id"):
        identifier = cancel_probe[field]
        if not isinstance(identifier, str) or UUID_PATTERN.fullmatch(identifier) is None:
            raise AttestationError("journal cancel probe identity")
    for field in ("fixture_created_at", "fixture_consumed_at", "fixture_finalized_at"):
        _validate_utc_timestamp(cancel_probe[field], "journal cancel probe timestamp")


def verify_runtime_attestation_payloads(
    attestation_bytes: bytes,
    manifest_bytes: bytes,
    journal_bytes: bytes,
    *,
    project_directory: str,
    playwright_base: str,
    environ: Mapping[str, str],
    machine_id: str,
    hostname: str,
    run_json: CommandRunner,
) -> tuple[str, str, str]:
    """이미 안전하게 읽은 document와 실제 Docker runtime을 exact 비교한다."""

    try:
        attestation = json.loads(attestation_bytes)
        manifest = json.loads(manifest_bytes)
        journal = json.loads(journal_bytes)
    except (TypeError, ValueError) as exc:
        raise AttestationError("attestation document JSON") from exc
    top_keys = {
        "api_ws_origin_sha256",
        "compose_project_sha256",
        "dagster_graphql_url_sha256",
        "hostname_sha256",
        "machine_id_sha256",
        "orchestrator_files",
        "pinned_runtime_manifest_sha256",
        "pinned_runtime_pinset_sha256",
        "playwright_base",
        "playwright_image_id",
        "rebuild_journal_sha256",
        "rebuild_transaction_id",
        "repository_commit",
        "schema_heads",
        "service_runtime",
        "source_commits",
        "ui_origin_sha256",
        "version",
    }
    if not _exact_dict(attestation, top_keys) or attestation["version"] != 4:
        raise AttestationError("attestation shape")
    assert isinstance(attestation, dict)
    orchestrator_files = attestation["orchestrator_files"]
    if not _exact_dict(orchestrator_files, set(ORCHESTRATOR_PATHS)) or not all(
        isinstance(value, str) and SHA256_PATTERN.fullmatch(value)
        for value in orchestrator_files.values()
    ):
        raise AttestationError("orchestrator file attestation")

    source_commits = attestation["source_commits"]
    if (
        not _exact_dict(source_commits, {"map", "pinvi"})
        or not all(
            isinstance(value, str) and COMMIT_PATTERN.fullmatch(value)
            for value in source_commits.values()
        )
        or source_commits["map"] != environ["E2E_C7_EXPECTED_GIT_COMMIT"]
    ):
        raise AttestationError("source commit identity")
    for key in {
        "api_ws_origin_sha256",
        "compose_project_sha256",
        "dagster_graphql_url_sha256",
        "hostname_sha256",
        "machine_id_sha256",
        "pinned_runtime_manifest_sha256",
        "pinned_runtime_pinset_sha256",
        "rebuild_journal_sha256",
        "ui_origin_sha256",
    }:
        if (
            not isinstance(attestation[key], str)
            or SHA256_PATTERN.fullmatch(attestation[key]) is None
        ):
            raise AttestationError("attestation hash")
    if (
        not isinstance(attestation["rebuild_transaction_id"], str)
        or UUID_PATTERN.fullmatch(attestation["rebuild_transaction_id"]) is None
    ):
        raise AttestationError("attestation rebuild transaction identity")
    if (
        not isinstance(attestation["repository_commit"], str)
        or COMMIT_PATTERN.fullmatch(attestation["repository_commit"]) is None
        or attestation["repository_commit"] != environ["E2E_C7_EXPECTED_GIT_COMMIT"]
        or attestation["playwright_base"] != playwright_base
        or not isinstance(attestation["playwright_image_id"], str)
        or IMAGE_PATTERN.fullmatch(attestation["playwright_image_id"]) is None
        or attestation["playwright_image_id"] != environ["E2E_C7_PLAYWRIGHT_IMAGE"]
        or not machine_id
    ):
        raise AttestationError("attestation identity")

    manifest_sha256 = _sha256_bytes(manifest_bytes)
    journal_sha256 = _sha256_bytes(journal_bytes)
    if not _exact_dict(manifest, {"active_generation", "version"}) or manifest["version"] != 6:
        raise AttestationError("manifest shape")
    assert isinstance(manifest, dict)
    active = manifest["active_generation"]
    _validate_generation(active)
    assert isinstance(active, dict)
    _validate_committed_journal(journal, generation=active)
    assert isinstance(journal, dict)
    if journal["transaction_id"] != attestation["rebuild_transaction_id"]:
        raise AttestationError("attestation is not bound to this rebuild transaction")
    if (
        manifest_sha256 != attestation["pinned_runtime_manifest_sha256"]
        or journal_sha256 != attestation["rebuild_journal_sha256"]
        or active["pinset_sha256"] != attestation["pinned_runtime_pinset_sha256"]
        or active["map_source_revision"] != source_commits["map"]
        or active["pinvi_source_revision"] != source_commits["pinvi"]
    ):
        raise AttestationError("pinned runtime generation mismatch")
    if not _exact_dict(attestation["schema_heads"], set(GENERATION_SCHEMA_HEAD_FIELDS)) or any(
        attestation["schema_heads"][field] != active[field]
        for field in GENERATION_SCHEMA_HEAD_FIELDS
    ):
        raise AttestationError("schema head mismatch")

    observed_origins = {
        "api_ws_origin_sha256": _sha256_text(
            _public_origin(environ["NEXT_PUBLIC_KOR_TRAVEL_MAP_API"], websocket=True)
        ),
        "dagster_graphql_url_sha256": _sha256_text(_canonical_graphql(environ["E2E_DAGSTER_URL"])),
        "hostname_sha256": _sha256_text(hostname.rstrip(".").lower()),
        "machine_id_sha256": _sha256_text(machine_id),
        "ui_origin_sha256": _sha256_text(_public_origin(environ["E2E_BASE_URL"])),
    }
    if any(attestation[key] != value for key, value in observed_origins.items()):
        raise AttestationError("host/origin mismatch")
    for env_name, observed_key in (
        ("E2E_C7_EXPECTED_UI_ORIGIN_SHA256", "ui_origin_sha256"),
        ("E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256", "api_ws_origin_sha256"),
        ("E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256", "dagster_graphql_url_sha256"),
    ):
        if environ[env_name] != observed_origins[observed_key]:
            raise AttestationError("caller origin mismatch")

    role_services = {
        "map_api": environ["E2E_C7_MAP_API_SERVICE"],
        "map_dagster_daemon": environ["E2E_C7_DAGSTER_DAEMON_SERVICE"],
        "map_dagster_web": environ["E2E_C7_DAGSTER_WEB_SERVICE"],
        "map_ui": environ["E2E_C7_UI_SERVICE"],
        "pinvi_api": environ["E2E_C7_PINVI_API_SERVICE"],
        "pinvi_dagster": environ["E2E_C7_PINVI_DAGSTER_SERVICE"],
        "pinvi_web": environ["E2E_C7_PINVI_WEB_SERVICE"],
    }
    if len(set(role_services.values())) != len(role_services):
        raise AttestationError("compose services are not distinct")
    runtime_attestation = attestation["service_runtime"]
    if not _exact_dict(runtime_attestation, set(role_services)):
        raise AttestationError("runtime roles")
    assert isinstance(runtime_attestation, dict)
    compose_project_hashes: set[str] = set()
    observed_containers: set[str] = set()
    observed_images: dict[str, str] = {}
    for role, service in role_services.items():
        expected = runtime_attestation[role]
        if not _exact_dict(expected, {"command_sha256", "environment_sha256", "image_id"}):
            raise AttestationError("runtime shape")
        assert isinstance(expected, dict)
        if (
            not isinstance(expected["image_id"], str)
            or IMAGE_PATTERN.fullmatch(expected["image_id"]) is None
            or not isinstance(expected["command_sha256"], str)
            or SHA256_PATTERN.fullmatch(expected["command_sha256"]) is None
            or not isinstance(expected["environment_sha256"], str)
            or SHA256_PATTERN.fullmatch(expected["environment_sha256"]) is None
        ):
            raise AttestationError("runtime attestation value")
        record = _compose_container(service, project_directory, run_json)
        container_id = record.get("Id")
        if not isinstance(container_id, str) or re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
            raise AttestationError("runtime container identity")
        observed_containers.add(container_id)
        config = record.get("Config")
        state = record.get("State")
        if not isinstance(config, dict) or not isinstance(state, dict):
            raise AttestationError("runtime inspect")
        health = state.get("Health")
        if (
            state.get("Running") is not True
            or state.get("Paused") is True
            or state.get("Restarting") is True
            or (isinstance(health, dict) and health.get("Status") != "healthy")
        ):
            raise AttestationError("runtime is not healthy")
        labels = config.get("Labels")
        environment = config.get("Env")
        if (
            not isinstance(labels, dict)
            or labels.get("com.docker.compose.service") != service
            or not isinstance(environment, list)
            or not all(isinstance(item, str) for item in environment)
        ):
            raise AttestationError("compose/runtime identity")
        environment_values = _runtime_environment(environment)
        _validate_cursor_secret_runtime(role, environment_values)
        project_name = labels.get("com.docker.compose.project")
        if not isinstance(project_name, str) or not project_name:
            raise AttestationError("compose project identity")
        if role == "map_ui":
            password_hash_prefix = "KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH="
            password_hashes = [
                item.removeprefix(password_hash_prefix)
                for item in environment
                if item.startswith(password_hash_prefix)
            ]
            if len(password_hashes) != 1 or not password_hashes[0]:
                raise AttestationError("UI admin password hash")
        compose_project_hashes.add(_sha256_text(project_name))
        command_sha256 = _sha256_bytes(
            _canonical_json(
                {
                    "Args": record.get("Args"),
                    "Cmd": config.get("Cmd"),
                    "Entrypoint": config.get("Entrypoint"),
                    "Path": record.get("Path"),
                }
            )
        )
        environment_sha256 = _sha256_bytes(_canonical_json(sorted(environment)))
        image_id = record.get("Image")
        if (
            image_id != expected["image_id"]
            or command_sha256 != expected["command_sha256"]
            or environment_sha256 != expected["environment_sha256"]
        ):
            raise AttestationError("runtime attestation mismatch")
        image_records = json.loads(
            run_json(
                ["docker", "image", "inspect", "--", str(image_id)],
                project_directory,
            )
        )
        if (
            not isinstance(image_records, list)
            or len(image_records) != 1
            or not isinstance(image_records[0], dict)
        ):
            raise AttestationError("runtime image inspect")
        image_config = image_records[0].get("Config")
        image_labels = image_config.get("Labels") if isinstance(image_config, dict) else None
        expected_source_commit = source_commits["pinvi" if role in _PINVI_ROLES else "map"]
        if (
            not isinstance(image_labels, dict)
            or image_labels.get("org.opencontainers.image.revision") != expected_source_commit
        ):
            raise AttestationError("runtime image source provenance")
        if not isinstance(image_id, str):
            raise AttestationError("runtime image identity")
        observed_images[role] = image_id
    if len(observed_containers) != len(role_services):
        raise AttestationError("runtime containers are not distinct")
    if compose_project_hashes != {attestation["compose_project_sha256"]}:
        raise AttestationError("wrong compose project")
    for role, field in GENERATION_RUNTIME_IMAGE_FIELDS:
        if observed_images[role] != active[field]:
            raise AttestationError("active generation is not deployed")

    executor_records = json.loads(
        run_json(
            ["docker", "image", "inspect", "--", environ["E2E_C7_PLAYWRIGHT_IMAGE"]],
            project_directory,
        )
    )
    if (
        not isinstance(executor_records, list)
        or len(executor_records) != 1
        or not isinstance(executor_records[0], dict)
    ):
        raise AttestationError("executor inspect")
    executor = executor_records[0]
    executor_config = executor.get("Config")
    executor_labels = executor_config.get("Labels") if isinstance(executor_config, dict) else None
    if (
        executor.get("Id") != environ["E2E_C7_PLAYWRIGHT_IMAGE"]
        or not isinstance(executor_labels, dict)
        or executor_labels.get("io.kortravelmap.c7.repository-commit")
        != attestation["repository_commit"]
        or executor_labels.get("io.kortravelmap.c7.playwright-base") != playwright_base
    ):
        raise AttestationError("executor identity")
    return manifest_sha256, journal_sha256, _sha256_bytes(attestation_bytes)


def verify_trusted_runtime_attestation(
    attestation_path: Path,
    manifest_path: Path,
    journal_path: Path,
    project_directory: str,
    playwright_base: str,
    *,
    environ: Mapping[str, str] = os.environ,
    secure_reader: SecureReader = _root_reader,
    machine_id_path: Path = Path("/etc/machine-id"),
    hostname: str | None = None,
    run_json: CommandRunner = _subprocess_output,
) -> tuple[str, str, str]:
    """root-owned documents를 읽고 실제 host·Docker runtime을 검증한다."""

    attestation_bytes = secure_reader(attestation_path, 0o600)
    manifest_bytes = secure_reader(manifest_path, 0o600)
    journal_bytes = secure_reader(journal_path, 0o600)
    machine_id = machine_id_path.read_text(encoding="utf-8").strip()
    return verify_runtime_attestation_payloads(
        attestation_bytes,
        manifest_bytes,
        journal_bytes,
        project_directory=project_directory,
        playwright_base=playwright_base,
        environ=environ,
        machine_id=machine_id,
        hostname=socket.getfqdn() if hostname is None else hostname,
        run_json=run_json,
    )


def main(argv: list[str] | None = None) -> int:
    """runner 전용 CLI. 실패 세부값은 출력하지 않고 non-zero로 닫는다."""

    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) == 8 and arguments[0] == "snapshot":
            verify_root_owned_orchestrator_snapshot(
                Path(arguments[1]),
                Path(arguments[2]),
                Path(arguments[3]),
                Path(arguments[4]),
                Path(arguments[5]),
                Path(arguments[6]),
                arguments[7],
            )
            return 0
        if len(arguments) == 6 and arguments[0] == "runtime":
            manifest_sha256, journal_sha256, attestation_sha256 = (
                verify_trusted_runtime_attestation(
                    Path(arguments[1]),
                    Path(arguments[2]),
                    Path(arguments[3]),
                    arguments[4],
                    arguments[5],
                )
            )
            print(manifest_sha256)
            print(journal_sha256)
            print(attestation_sha256)
            return 0
    except (
        AssertionError,
        AttestationError,
        AttributeError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ):
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

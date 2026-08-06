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
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, urlunsplit

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SCHEMA_HEAD_PATTERN = re.compile(r"^[0-9a-z][0-9a-z_.-]{0,127}$")
CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
APPLICATION_HEAD_SCHEMA = "kor-travel-map.application-head.v1"
ORCHESTRATOR_PATHS = (
    "scripts/audit-c7-prod-live-state.py",
    "scripts/lib/c7-prod-runner-lifecycle.sh",
    "scripts/lib/c7_prod_attestation.py",
    "scripts/run-c7-prod-live-e2e.sh",
)
GENERATION_RUNTIME_IMAGE_FIELDS = (
    ("map_api", "map_api_image_id"),
    ("map_ui", "map_ui_image_id"),
    ("map_dagster_web", "map_dagster_image_id"),
    ("map_dagster_daemon", "map_dagster_daemon_image_id"),
    ("pinvi_api", "pinvi_api_image_id"),
    ("pinvi_web", "pinvi_web_image_id"),
    ("pinvi_dagster", "pinvi_dagster_image_id"),
)

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


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return observed.tzinfo is not None and observed.utcoffset() == timedelta(0)


def _is_canonical_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _utc_timestamp(value: object) -> datetime | None:
    if not _is_utc_timestamp(value):
        return None
    assert isinstance(value, str)
    return datetime.fromisoformat(value)


def _validated_generation(value: object) -> dict[str, str]:
    image_fields = {field for _, field in GENERATION_RUNTIME_IMAGE_FIELDS}
    expected = image_fields | {
        "map_source_revision",
        "pinvi_source_revision",
        "map_application_head",
        "map_dagster_head",
        "pinvi_head",
        "pinset_sha256",
        "recorded_at",
    }
    if not _exact_dict(value, expected):
        raise AttestationError("pinned runtime generation shape")
    assert isinstance(value, dict)
    if any(not isinstance(item, str) for item in value.values()):
        raise AttestationError("pinned runtime generation value")
    generation = cast(dict[str, str], value)
    for field in image_fields:
        if IMAGE_PATTERN.fullmatch(generation[field]) is None:
            raise AttestationError("pinned runtime generation image")
    if COMMIT_PATTERN.fullmatch(generation["map_source_revision"]) is None:
        raise AttestationError("Map source revision")
    if COMMIT_PATTERN.fullmatch(generation["pinvi_source_revision"]) is None:
        raise AttestationError("PinVi source revision")
    if any(
        SCHEMA_HEAD_PATTERN.fullmatch(generation[field]) is None
        for field in ("map_application_head", "map_dagster_head", "pinvi_head")
    ):
        raise AttestationError("pinned runtime generation schema head")
    if SHA256_PATTERN.fullmatch(generation["pinset_sha256"]) is None:
        raise AttestationError("pinned runtime generation pinset")
    if not _is_utc_timestamp(generation["recorded_at"]):
        raise AttestationError("pinned runtime generation timestamp")
    return generation


def _validate_finalized_cancel_probe(value: object) -> None:
    expected = {
        "stage",
        "job_id",
        "cancellation_id",
        "outcome",
        "fixture_created_at",
        "fixture_consumed_at",
        "fixture_finalized_at",
    }
    if not _exact_dict(value, expected):
        raise AttestationError("pinned runtime cancel probe shape")
    assert isinstance(value, dict)
    if (
        value["stage"] != "finalized"
        or not _is_canonical_uuid(value["job_id"])
        or not _is_canonical_uuid(value["cancellation_id"])
        or not all(
            _is_utc_timestamp(value[field])
            for field in (
                "fixture_created_at",
                "fixture_consumed_at",
                "fixture_finalized_at",
            )
        )
        or value["outcome"]
        != {
            "name": "pinvi_cancel_error",
            "status": 409,
            "code": "PIPELINE_CANCELLATION_UNSAFE",
        }
    ):
        raise AttestationError("pinned runtime cancel probe")
    timestamps = [
        datetime.fromisoformat(value[field])
        for field in (
            "fixture_created_at",
            "fixture_consumed_at",
            "fixture_finalized_at",
        )
    ]
    if timestamps != sorted(timestamps):
        raise AttestationError("pinned runtime cancel probe ordering")


def _validate_committed_rebuild_journal(
    value: object,
    active_generation: dict[str, str],
) -> tuple[datetime, str]:
    expected = {
        "version",
        "transaction_id",
        "phase",
        "candidate",
        "environment_sha256",
        "compose_sha256",
        "resolved_compose_sha256",
        "created_at",
        "cancel_probe",
    }
    if not _exact_dict(value, expected):
        raise AttestationError("pinned runtime rebuild journal shape")
    assert isinstance(value, dict)
    committed_at = _utc_timestamp(value["created_at"])
    transaction_id = value["transaction_id"]
    if (
        value["version"] != 7
        or value["phase"] != "committed"
        or not isinstance(transaction_id, str)
        or not _is_canonical_uuid(transaction_id)
        or not all(
            isinstance(value[field], str) and SHA256_PATTERN.fullmatch(value[field])
            for field in (
                "environment_sha256",
                "compose_sha256",
                "resolved_compose_sha256",
            )
        )
        or committed_at is None
    ):
        raise AttestationError("pinned runtime rebuild journal")
    if _validated_generation(value["candidate"]) != active_generation:
        raise AttestationError("pinned runtime journal candidate drift")
    _validate_finalized_cancel_probe(value["cancel_probe"])
    return committed_at, transaction_id


def _validate_final_schema_reload_receipt(
    value: object,
    *,
    active_generation: dict[str, str],
    manifest_sha256: str,
    rebuild_journal_sha256: str,
    rebuild_committed_at: datetime,
    rebuild_transaction_id: str,
) -> None:
    """최종 schema에서 source/ETL 재적재가 끝났다는 별도 root receipt를 검증한다."""

    expected = {
        "version",
        "pinned_runtime_manifest_sha256",
        "pinned_runtime_rebuild_journal_sha256",
        "schema_heads",
        "source_reload",
        "etl_reload",
        "canonical_dataset_availability",
        "recorded_at",
    }
    if not _exact_dict(value, expected):
        raise AttestationError("final schema reload receipt shape")
    assert isinstance(value, dict)
    expected_heads = {
        "map_application": active_generation["map_application_head"],
        "map_dagster": active_generation["map_dagster_head"],
        "pinvi": active_generation["pinvi_head"],
    }
    generation_sha256 = _sha256_bytes(_canonical_json(active_generation))
    source_reload = value["source_reload"]
    etl_reload = value["etl_reload"]
    availability = value["canonical_dataset_availability"]
    if (
        value["version"] != 1
        or value["pinned_runtime_manifest_sha256"] != manifest_sha256
        or value["pinned_runtime_rebuild_journal_sha256"] != rebuild_journal_sha256
        or value["schema_heads"] != expected_heads
        or not _exact_dict(
            source_reload,
            {
                "status",
                "source_snapshot_sha256",
                "observed_generation_sha256",
                "observed_map_api_image_id",
                "observed_schema_heads",
                "completed_at",
            },
        )
        or not _exact_dict(
            etl_reload,
            {
                "status",
                "run_id",
                "result_sha256",
                "consumed_source_snapshot_sha256",
                "rebuild_transaction_id",
                "observed_generation_sha256",
                "observed_map_api_image_id",
                "observed_schema_heads",
                "completed_at",
            },
        )
        or not _exact_dict(
            availability,
            {"status", "dataset_count", "feature_count", "availability_sha256"},
        )
    ):
        raise AttestationError("final schema reload receipt binding")
    assert isinstance(source_reload, dict)
    assert isinstance(etl_reload, dict)
    assert isinstance(availability, dict)
    recorded_at = _utc_timestamp(value["recorded_at"])
    source_completed_at = _utc_timestamp(source_reload["completed_at"])
    etl_completed_at = _utc_timestamp(etl_reload["completed_at"])
    if (
        source_reload["status"] != "succeeded"
        or not isinstance(source_reload["source_snapshot_sha256"], str)
        or SHA256_PATTERN.fullmatch(source_reload["source_snapshot_sha256"]) is None
        or source_reload["observed_generation_sha256"] != generation_sha256
        or source_reload["observed_map_api_image_id"]
        != active_generation["map_api_image_id"]
        or source_reload["observed_schema_heads"] != expected_heads
        or etl_reload["status"] != "succeeded"
        or not _is_canonical_uuid(etl_reload["run_id"])
        or not isinstance(etl_reload["result_sha256"], str)
        or SHA256_PATTERN.fullmatch(etl_reload["result_sha256"]) is None
        or etl_reload["consumed_source_snapshot_sha256"]
        != source_reload["source_snapshot_sha256"]
        or etl_reload["rebuild_transaction_id"] != rebuild_transaction_id
        or etl_reload["observed_generation_sha256"] != generation_sha256
        or etl_reload["observed_map_api_image_id"]
        != active_generation["map_api_image_id"]
        or etl_reload["observed_schema_heads"] != expected_heads
        or availability["status"] != "available"
        or type(availability["dataset_count"]) is not int
        or availability["dataset_count"] <= 0
        or type(availability["feature_count"]) is not int
        or availability["feature_count"] <= 0
        or not isinstance(availability["availability_sha256"], str)
        or SHA256_PATTERN.fullmatch(availability["availability_sha256"]) is None
        or source_completed_at is None
        or etl_completed_at is None
        or recorded_at is None
        or _utc_timestamp(active_generation["recorded_at"]) is None
        or _utc_timestamp(active_generation["recorded_at"]) > source_completed_at
        or rebuild_committed_at >= source_completed_at
        or source_completed_at >= etl_completed_at
        or etl_completed_at >= recorded_at
    ):
        raise AttestationError("final schema reload receipt")


def _parse_installed_application_schema_head(value: str) -> str:
    """ADR-085 installed artifact command의 한 줄 compact JSON만 수용한다."""

    if value.count("\n") != 1 or not value.endswith("\n"):
        raise AttestationError("Map application schema artifact output")
    document = value[:-1]
    try:
        payload = json.loads(document)
    except (TypeError, ValueError) as exc:
        raise AttestationError("Map application schema artifact output") from exc
    if (
        not _exact_dict(payload, {"schema", "head"})
        or payload["schema"] != APPLICATION_HEAD_SCHEMA
        or not isinstance(payload["head"], str)
        or SCHEMA_HEAD_PATTERN.fullmatch(payload["head"]) is None
    ):
        raise AttestationError("Map application schema artifact output")
    expected_document = json.dumps(
        {"schema": APPLICATION_HEAD_SCHEMA, "head": payload["head"]},
        separators=(",", ":"),
    )
    if document != expected_document:
        raise AttestationError("Map application schema artifact output")
    return payload["head"]


def _parse_exact_database_alembic_head(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) != 1:
        raise AttestationError("Map application database Alembic output")
    matched = re.fullmatch(r"(.+) \(head\)", lines[0])
    if (
        matched is None
        or SCHEMA_HEAD_PATTERN.fullmatch(matched.group(1)) is None
    ):
        raise AttestationError("Map application database Alembic output")
    return matched.group(1)


def _verify_map_application_schema_head(
    *,
    project_directory: str,
    service: str,
    expected_head: str,
    run_json: CommandRunner,
) -> None:
    """설치 artifact head와 실제 Map DB current를 generation head에 따로 결박한다."""

    command_prefix = [
        "docker",
        "compose",
        "--project-directory",
        project_directory,
        "exec",
        "-T",
        service,
    ]
    installed_head = _parse_installed_application_schema_head(
        run_json(
            [*command_prefix, "ktm-application-schema", "head"],
            project_directory,
        )
    )
    database_head = _parse_exact_database_alembic_head(
        run_json([*command_prefix, "alembic", "current"], project_directory)
    )
    try:
        run_json([*command_prefix, "alembic", "check"], project_directory)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AttestationError("Map application Alembic check") from exc
    if installed_head != expected_head:
        raise AttestationError("Map application installed artifact head mismatch")
    if database_head != expected_head:
        raise AttestationError("Map application database head mismatch")


def verify_runtime_attestation_payloads(
    attestation_bytes: bytes,
    manifest_bytes: bytes,
    rebuild_journal_bytes: bytes,
    final_schema_reload_receipt_bytes: bytes,
    *,
    project_directory: str,
    playwright_base: str,
    environ: Mapping[str, str],
    machine_id: str,
    hostname: str,
    run_json: CommandRunner,
) -> tuple[str, str, str, str, str]:
    """이미 안전하게 읽은 document와 실제 Docker runtime을 exact 비교한다."""

    try:
        attestation = json.loads(attestation_bytes)
        manifest = json.loads(manifest_bytes)
        rebuild_journal = json.loads(rebuild_journal_bytes)
        final_schema_reload_receipt = json.loads(final_schema_reload_receipt_bytes)
    except (TypeError, ValueError) as exc:
        raise AttestationError("attestation document JSON") from exc
    top_keys = {
        "api_ws_origin_sha256",
        "compose_project_sha256",
        "dagster_graphql_url_sha256",
        "endpoint_roles",
        "final_schema_reload_receipt_sha256",
        "hostname_sha256",
        "machine_id_sha256",
        "orchestrator_files",
        "playwright_base",
        "playwright_image_id",
        "pinned_runtime_manifest_sha256",
        "pinned_runtime_rebuild_journal_sha256",
        "pinset_sha256",
        "repository_commit",
        "schema_heads",
        "service_runtime",
        "source_commits",
        "ui_origin_sha256",
        "version",
    }
    if not _exact_dict(attestation, top_keys) or attestation["version"] != 5:
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
        "final_schema_reload_receipt_sha256",
        "hostname_sha256",
        "machine_id_sha256",
        "pinned_runtime_manifest_sha256",
        "pinned_runtime_rebuild_journal_sha256",
        "pinset_sha256",
        "ui_origin_sha256",
    }:
        if (
            not isinstance(attestation[key], str)
            or SHA256_PATTERN.fullmatch(attestation[key]) is None
        ):
            raise AttestationError("attestation hash")
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
    rebuild_journal_sha256 = _sha256_bytes(rebuild_journal_bytes)
    final_schema_reload_receipt_sha256 = _sha256_bytes(final_schema_reload_receipt_bytes)
    if (
        not _exact_dict(manifest, {"active_generation", "version"})
        or manifest["version"] != 5
    ):
        raise AttestationError("pinned runtime manifest shape")
    assert isinstance(manifest, dict)
    active = _validated_generation(manifest["active_generation"])
    rebuild_committed_at, rebuild_transaction_id = _validate_committed_rebuild_journal(
        rebuild_journal,
        active,
    )
    _validate_final_schema_reload_receipt(
        final_schema_reload_receipt,
        active_generation=active,
        manifest_sha256=manifest_sha256,
        rebuild_journal_sha256=rebuild_journal_sha256,
        rebuild_committed_at=rebuild_committed_at,
        rebuild_transaction_id=rebuild_transaction_id,
    )
    schema_heads = {
        "map_application": active["map_application_head"],
        "map_dagster": active["map_dagster_head"],
        "pinvi": active["pinvi_head"],
    }
    if (
        manifest_sha256 != attestation["pinned_runtime_manifest_sha256"]
        or rebuild_journal_sha256 != attestation["pinned_runtime_rebuild_journal_sha256"]
        or final_schema_reload_receipt_sha256
        != attestation["final_schema_reload_receipt_sha256"]
        or active["map_source_revision"] != source_commits["map"]
        or active["pinvi_source_revision"] != source_commits["pinvi"]
        or active["pinset_sha256"] != attestation["pinset_sha256"]
        or attestation["schema_heads"] != schema_heads
    ):
        raise AttestationError("pinned runtime authority mismatch")

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
        "pinvi_web": environ["E2E_C7_PINVI_WEB_SERVICE"],
        "pinvi_dagster": environ["E2E_C7_PINVI_DAGSTER_SERVICE"],
    }
    if len(set(role_services.values())) != len(role_services):
        raise AttestationError("compose services are not distinct")
    if attestation["endpoint_roles"] != {
        "api_websocket": "map_api",
        "dagster_graphql": "map_dagster_web",
        "ui": "map_ui",
    }:
        raise AttestationError("endpoint role binding")
    runtime_attestation = attestation["service_runtime"]
    if not _exact_dict(runtime_attestation, set(role_services)):
        raise AttestationError("runtime roles")
    assert isinstance(runtime_attestation, dict)
    compose_project_hashes: set[str] = set()
    observed_containers: set[str] = set()
    observed_images: dict[str, str] = {}
    for role, service in role_services.items():
        expected = runtime_attestation[role]
        if not _exact_dict(
            expected,
            {
                "command_sha256",
                "compose_service",
                "container_id",
                "environment_sha256",
                "image_id",
            },
        ):
            raise AttestationError("runtime shape")
        assert isinstance(expected, dict)
        if (
            not isinstance(expected["image_id"], str)
            or IMAGE_PATTERN.fullmatch(expected["image_id"]) is None
            or expected["compose_service"] != service
            or not isinstance(expected["container_id"], str)
            or CONTAINER_ID_PATTERN.fullmatch(expected["container_id"]) is None
            or not isinstance(expected["command_sha256"], str)
            or SHA256_PATTERN.fullmatch(expected["command_sha256"]) is None
            or not isinstance(expected["environment_sha256"], str)
            or SHA256_PATTERN.fullmatch(expected["environment_sha256"]) is None
        ):
            raise AttestationError("runtime attestation value")
        record = _compose_container(service, project_directory, run_json)
        container_id = record.get("Id")
        if (
            not isinstance(container_id, str)
            or CONTAINER_ID_PATTERN.fullmatch(container_id) is None
        ):
            raise AttestationError("runtime container identity")
        if container_id != expected["container_id"]:
            raise AttestationError("runtime container binding")
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
        expected_source_commit = source_commits["pinvi" if role.startswith("pinvi_") else "map"]
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
    _verify_map_application_schema_head(
        project_directory=project_directory,
        service=role_services["map_api"],
        expected_head=active["map_application_head"],
        run_json=run_json,
    )

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
    return (
        manifest_sha256,
        rebuild_journal_sha256,
        final_schema_reload_receipt_sha256,
        _sha256_bytes(attestation_bytes),
        active["map_application_head"],
    )


def verify_trusted_runtime_attestation(
    attestation_path: Path,
    manifest_path: Path,
    rebuild_journal_path: Path,
    final_schema_reload_receipt_path: Path,
    project_directory: str,
    playwright_base: str,
    *,
    environ: Mapping[str, str] = os.environ,
    secure_reader: SecureReader = _root_reader,
    machine_id_path: Path = Path("/etc/machine-id"),
    hostname: str | None = None,
    run_json: CommandRunner = _subprocess_output,
) -> tuple[str, str, str, str, str]:
    """root-owned documents를 읽고 실제 host·Docker runtime을 검증한다."""

    attestation_bytes = secure_reader(attestation_path, 0o600)
    manifest_bytes = secure_reader(manifest_path, 0o600)
    rebuild_journal_bytes = secure_reader(rebuild_journal_path, 0o600)
    final_schema_reload_receipt_bytes = secure_reader(final_schema_reload_receipt_path, 0o600)
    machine_id = machine_id_path.read_text(encoding="utf-8").strip()
    return verify_runtime_attestation_payloads(
        attestation_bytes,
        manifest_bytes,
        rebuild_journal_bytes,
        final_schema_reload_receipt_bytes,
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
        if len(arguments) == 7 and arguments[0] == "runtime":
            (
                manifest_sha256,
                rebuild_journal_sha256,
                final_schema_reload_receipt_sha256,
                attestation_sha256,
                map_application_head,
            ) = (
                verify_trusted_runtime_attestation(
                    Path(arguments[1]),
                    Path(arguments[2]),
                    Path(arguments[3]),
                    Path(arguments[4]),
                    arguments[5],
                    arguments[6],
                )
            )
            print(manifest_sha256)
            print(rebuild_journal_sha256)
            print(final_schema_reload_receipt_sha256)
            print(attestation_sha256)
            print(map_application_head)
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

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
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
GENERATION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
ORCHESTRATOR_PATHS = (
    "scripts/audit-c7-prod-live-state.py",
    "scripts/lib/c7-prod-runner-lifecycle.sh",
    "scripts/lib/c7_prod_attestation.py",
    "scripts/run-c7-prod-live-e2e.sh",
)
PAIR_RUNTIME_IMAGE_FIELDS = (
    ("map_api", "map_image_id"),
    ("map_ui", "map_ui_image_id"),
    ("map_dagster_web", "map_dagster_image_id"),
    ("map_dagster_daemon", "map_dagster_daemon_image_id"),
    ("pinvi_api", "pinvi_image_id"),
)

CommandRunner = Callable[[list[str], str], str]
SecureReader = Callable[[Path, int], bytes]

_CURSOR_SECRET_ENV = "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET"
_CURSOR_PROTECTED_ENVS = {
    "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
    "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
    "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
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
    if (
        attestation.get("repository_commit") != expected_commit
        or not _exact_dict(orchestrator_files, set(expected_files))
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


def _public_origin(
    raw: str, *, websocket: bool = False, require_root_path: bool = True
) -> str:
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
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_loopback or address.is_link_local or address.is_unspecified
    ):
        raise AttestationError("unsafe address")
    port = f":{parsed.port}" if parsed.port is not None else ""
    return urlunsplit(("wss" if websocket else "https", f"{host}{port}", "", "", ""))


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


def _validate_pair(value: object) -> None:
    image_fields = {field for _, field in PAIR_RUNTIME_IMAGE_FIELDS}
    if not _exact_dict(
        value,
        image_fields
        | {
            "contract_generation",
            "map_source_revision",
            "pinvi_source_revision",
            "recorded_at",
        },
    ):
        raise AttestationError("pair shape")
    assert isinstance(value, dict)
    for field in image_fields:
        image_id = value[field]
        if not isinstance(image_id, str) or IMAGE_PATTERN.fullmatch(image_id) is None:
            raise AttestationError("pair image")
    if not isinstance(value["map_source_revision"], str) or COMMIT_PATTERN.fullmatch(
        value["map_source_revision"]
    ) is None:
        raise AttestationError("Map source revision")
    if not isinstance(value["pinvi_source_revision"], str) or COMMIT_PATTERN.fullmatch(
        value["pinvi_source_revision"]
    ) is None:
        raise AttestationError("PinVi source revision")
    generation = value["contract_generation"]
    if not isinstance(generation, str) or GENERATION_PATTERN.fullmatch(generation) is None:
        raise AttestationError("generation")
    recorded_at = value["recorded_at"]
    if not isinstance(recorded_at, str):
        raise AttestationError("recorded_at")
    observed_at = datetime.fromisoformat(recorded_at)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise AttestationError("recorded_at")


def verify_runtime_attestation_payloads(
    attestation_bytes: bytes,
    manifest_bytes: bytes,
    *,
    project_directory: str,
    playwright_base: str,
    environ: Mapping[str, str],
    machine_id: str,
    hostname: str,
    run_json: CommandRunner,
) -> tuple[str, str]:
    """이미 안전하게 읽은 document와 실제 Docker runtime을 exact 비교한다."""

    try:
        attestation = json.loads(attestation_bytes)
        manifest = json.loads(manifest_bytes)
    except (TypeError, ValueError) as exc:
        raise AttestationError("attestation document JSON") from exc
    top_keys = {
        "api_ws_origin_sha256",
        "c6c_contract_generation",
        "compatible_pair_manifest_sha256",
        "compose_project_sha256",
        "dagster_graphql_url_sha256",
        "hostname_sha256",
        "machine_id_sha256",
        "orchestrator_files",
        "playwright_base",
        "playwright_image_id",
        "repository_commit",
        "service_runtime",
        "source_commits",
        "ui_origin_sha256",
        "version",
    }
    if not _exact_dict(attestation, top_keys) or attestation["version"] != 3:
        raise AttestationError("attestation shape")
    assert isinstance(attestation, dict)
    orchestrator_files = attestation["orchestrator_files"]
    if (
        not _exact_dict(orchestrator_files, set(ORCHESTRATOR_PATHS))
        or not all(
            isinstance(value, str) and SHA256_PATTERN.fullmatch(value)
            for value in orchestrator_files.values()
        )
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
        "compatible_pair_manifest_sha256",
        "compose_project_sha256",
        "dagster_graphql_url_sha256",
        "hostname_sha256",
        "machine_id_sha256",
        "ui_origin_sha256",
    }:
        if not isinstance(attestation[key], str) or SHA256_PATTERN.fullmatch(
            attestation[key]
        ) is None:
            raise AttestationError("attestation hash")
    if (
        not isinstance(attestation["repository_commit"], str)
        or COMMIT_PATTERN.fullmatch(attestation["repository_commit"]) is None
        or attestation["repository_commit"] != environ["E2E_C7_EXPECTED_GIT_COMMIT"]
        or attestation["playwright_base"] != playwright_base
        or not isinstance(attestation["playwright_image_id"], str)
        or IMAGE_PATTERN.fullmatch(attestation["playwright_image_id"]) is None
        or attestation["playwright_image_id"] != environ["E2E_C7_PLAYWRIGHT_IMAGE"]
        or not isinstance(attestation["c6c_contract_generation"], str)
        or GENERATION_PATTERN.fullmatch(attestation["c6c_contract_generation"]) is None
        or not machine_id
    ):
        raise AttestationError("attestation identity")

    manifest_sha256 = _sha256_bytes(manifest_bytes)
    if not _exact_dict(manifest, {"active", "rollback", "version"}) or manifest["version"] != 4:
        raise AttestationError("manifest shape")
    assert isinstance(manifest, dict)
    _validate_pair(manifest["active"])
    _validate_pair(manifest["rollback"])
    active = manifest["active"]
    assert isinstance(active, dict)
    if (
        manifest_sha256 != attestation["compatible_pair_manifest_sha256"]
        or active["contract_generation"] != attestation["c6c_contract_generation"]
        or active["map_source_revision"] != source_commits["map"]
        or active["pinvi_source_revision"] != source_commits["pinvi"]
    ):
        raise AttestationError("compatible pair mismatch")

    observed_origins = {
        "api_ws_origin_sha256": _sha256_text(
            _public_origin(environ["NEXT_PUBLIC_KOR_TRAVEL_MAP_API"], websocket=True)
        ),
        "dagster_graphql_url_sha256": _sha256_text(
            _canonical_graphql(environ["E2E_DAGSTER_URL"])
        ),
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
        expected_source_commit = source_commits["pinvi" if role == "pinvi_api" else "map"]
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
    for role, field in PAIR_RUNTIME_IMAGE_FIELDS:
        if observed_images[role] != active[field]:
            raise AttestationError("active pair is not deployed")

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
    executor_labels = (
        executor_config.get("Labels") if isinstance(executor_config, dict) else None
    )
    if (
        executor.get("Id") != environ["E2E_C7_PLAYWRIGHT_IMAGE"]
        or not isinstance(executor_labels, dict)
        or executor_labels.get("io.kortravelmap.c7.repository-commit")
        != attestation["repository_commit"]
        or executor_labels.get("io.kortravelmap.c7.playwright-base") != playwright_base
    ):
        raise AttestationError("executor identity")
    return manifest_sha256, _sha256_bytes(attestation_bytes)


def verify_trusted_runtime_attestation(
    attestation_path: Path,
    manifest_path: Path,
    project_directory: str,
    playwright_base: str,
    *,
    environ: Mapping[str, str] = os.environ,
    secure_reader: SecureReader = _root_reader,
    machine_id_path: Path = Path("/etc/machine-id"),
    hostname: str | None = None,
    run_json: CommandRunner = _subprocess_output,
) -> tuple[str, str]:
    """root-owned documents를 읽고 실제 host·Docker runtime을 검증한다."""

    attestation_bytes = secure_reader(attestation_path, 0o600)
    manifest_bytes = secure_reader(manifest_path, 0o600)
    machine_id = machine_id_path.read_text(encoding="utf-8").strip()
    return verify_runtime_attestation_payloads(
        attestation_bytes,
        manifest_bytes,
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
        if len(arguments) == 5 and arguments[0] == "runtime":
            manifest_sha256, attestation_sha256 = verify_trusted_runtime_attestation(
                Path(arguments[1]),
                Path(arguments[2]),
                arguments[3],
                arguments[4],
            )
            print(manifest_sha256)
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

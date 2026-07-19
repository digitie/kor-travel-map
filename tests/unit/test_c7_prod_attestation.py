"""C7 root/runtime attestation 보안 코어의 실행형 음수 테스트."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from collections.abc import Callable
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "lib" / "c7_prod_attestation.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("c7_prod_attestation", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ATTESTATION = _load_module()


def test_orchestrator_snapshot_covers_every_root_executed_file() -> None:
    assert ATTESTATION.ORCHESTRATOR_PATHS == (
        "scripts/audit-c7-prod-live-state.py",
        "scripts/lib/c7-prod-runner-lifecycle.sh",
        "scripts/lib/c7_prod_attestation.py",
        "scripts/run-c7-prod-live-e2e.sh",
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _snapshot_fixture(tmp_path: Path) -> tuple[dict[str, Path], Path, str, Callable]:
    commit = "a" * 40
    expected_base = tmp_path / "c7-runner"
    snapshot_root = expected_base / commit
    paths = {
        "scripts/audit-c7-prod-live-state.py": snapshot_root
        / "scripts/audit-c7-prod-live-state.py",
        "scripts/lib/c7-prod-runner-lifecycle.sh": snapshot_root
        / "scripts/lib/c7-prod-runner-lifecycle.sh",
        "scripts/lib/c7_prod_attestation.py": snapshot_root
        / "scripts/lib/c7_prod_attestation.py",
        "scripts/run-c7-prod-live-e2e.sh": snapshot_root
        / "scripts/run-c7-prod-live-e2e.sh",
    }
    for index, path in enumerate(paths.values(), start=1):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"file-{index}".encode())
        path.chmod(0o555)
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text(
        json.dumps(
            {
                "orchestrator_files": {
                    relative: _sha256_bytes(path.read_bytes())
                    for relative, path in paths.items()
                },
                "repository_commit": commit,
            }
        ),
        encoding="utf-8",
    )
    attestation_path.chmod(0o600)
    for directory in (tmp_path, expected_base, snapshot_root):
        directory.chmod(0o700)

    def secure_reader(path: Path, mode: int) -> bytes:
        return ATTESTATION._read_secure_file(  # noqa: SLF001
            path,
            mode,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            ancestor_floor=tmp_path,
        )

    return paths, attestation_path, commit, secure_reader


@pytest.mark.parametrize("relative", ATTESTATION.ORCHESTRATOR_PATHS)
def test_snapshot_rejects_each_tampered_orchestrator_file(
    tmp_path: Path,
    relative: str,
) -> None:
    paths, attestation_path, commit, secure_reader = _snapshot_fixture(tmp_path)
    tampered = paths[relative]
    tampered.chmod(0o755)
    tampered.write_bytes(b"tampered")
    tampered.chmod(0o555)

    with pytest.raises(ATTESTATION.AttestationError):
        ATTESTATION.verify_root_owned_orchestrator_snapshot(
            tmp_path / "c7-runner" / commit,
            paths["scripts/run-c7-prod-live-e2e.sh"],
            paths["scripts/audit-c7-prod-live-state.py"],
            paths["scripts/lib/c7-prod-runner-lifecycle.sh"],
            paths["scripts/lib/c7_prod_attestation.py"],
            attestation_path,
            commit,
            expected_base=tmp_path / "c7-runner",
            secure_reader=secure_reader,
        )


def test_secure_reader_rejects_wrong_file_owner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "attestation.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o600)
    tmp_path.chmod(0o700)
    observed = target.stat()
    monkeypatch.setattr(
        ATTESTATION.os,
        "fstat",
        lambda _descriptor: SimpleNamespace(
            st_mode=observed.st_mode,
            st_uid=os.getuid() + 1,
            st_gid=os.getgid(),
        ),
    )

    with pytest.raises(ATTESTATION.AttestationError, match="unsafe root-owned file"):
        ATTESTATION._read_secure_file(  # noqa: SLF001
            target,
            0o600,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            ancestor_floor=tmp_path,
        )


def test_secure_reader_rejects_wrong_mode_and_writable_ancestor(tmp_path: Path) -> None:
    parent = tmp_path / "trusted"
    parent.mkdir(mode=0o700)
    target = parent / "attestation.json"
    target.write_text("{}", encoding="utf-8")
    target.chmod(0o640)

    with pytest.raises(ATTESTATION.AttestationError, match="unsafe root-owned file"):
        ATTESTATION._read_secure_file(  # noqa: SLF001
            target,
            0o600,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            ancestor_floor=tmp_path,
        )

    target.chmod(0o600)
    parent.chmod(0o770)
    with pytest.raises(ATTESTATION.AttestationError, match="unsafe root file parent"):
        ATTESTATION._read_secure_file(  # noqa: SLF001
            target,
            0o600,
            expected_uid=os.getuid(),
            expected_gid=os.getgid(),
            ancestor_floor=tmp_path,
        )


def _runtime_fixture() -> tuple[dict[str, object], dict[str, object], dict[str, str], Callable]:
    map_commit = "a" * 40
    pinvi_commit = "b" * 40
    map_images = {
        "map_api": "sha256:" + "1" * 64,
        "map_ui": "sha256:" + "4" * 64,
        "map_dagster_web": "sha256:" + "5" * 64,
        "map_dagster_daemon": "sha256:" + "6" * 64,
    }
    pinvi_image = "sha256:" + "2" * 64
    executor_image = "sha256:" + "3" * 64
    project_name = "kor-travel-map-prod"
    playwright_base = "playwright@example"
    generation = "c6c-v4"
    services = {
        "map_api": "map-api",
        "map_dagster_daemon": "map-daemon",
        "map_dagster_web": "map-web",
        "map_ui": "map-ui",
        "pinvi_api": "pinvi-api",
    }
    environments = {role: ["A=1"] for role in services}
    environments["map_api"] = [
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=admin-proxy-0000000000000000000000000000",
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=cursor-secret-000000000000000000000000000",
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true",
        "KOR_TRAVEL_MAP_API_PROFILE=production",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN=service-token-000000000000000000000000000",
    ]
    environments["map_ui"] = ["KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH=hash"]
    records: dict[str, dict[str, object]] = {}
    image_records: dict[str, dict[str, object]] = {
        image_id: {
            "Config": {"Labels": {"org.opencontainers.image.revision": map_commit}}
        }
        for image_id in map_images.values()
    }
    image_records.update(
        {
            pinvi_image: {
                "Config": {"Labels": {"org.opencontainers.image.revision": pinvi_commit}}
            },
            executor_image: {
                "Config": {
                    "Labels": {
                        "io.kortravelmap.c7.playwright-base": playwright_base,
                        "io.kortravelmap.c7.repository-commit": map_commit,
                    }
                },
                "Id": executor_image,
            },
        }
    )
    runtime: dict[str, object] = {}
    service_ids: dict[str, str] = {}
    for index, (role, service) in enumerate(services.items(), start=4):
        container_id = str(index) * 64
        image_id = pinvi_image if role == "pinvi_api" else map_images[role]
        config = {
            "Cmd": ["serve"],
            "Entrypoint": ["/entrypoint"],
            "Env": environments[role],
            "Labels": {
                "com.docker.compose.project": project_name,
                "com.docker.compose.service": service,
            },
        }
        record = {
            "Args": ["serve"],
            "Config": config,
            "Id": container_id,
            "Image": image_id,
            "Path": "/entrypoint",
            "State": {"Paused": False, "Restarting": False, "Running": True},
        }
        service_ids[service] = container_id
        records[container_id] = record
        runtime[role] = {
            "command_sha256": _sha256_bytes(
                _canonical_json(
                    {
                        "Args": record["Args"],
                        "Cmd": config["Cmd"],
                        "Entrypoint": config["Entrypoint"],
                        "Path": record["Path"],
                    }
                )
            ),
            "environment_sha256": _sha256_bytes(
                _canonical_json(sorted(environments[role]))
            ),
            "image_id": image_id,
        }
    pair = {
        "contract_generation": generation,
        "map_image_id": map_images["map_api"],
        "map_ui_image_id": map_images["map_ui"],
        "map_dagster_image_id": map_images["map_dagster_web"],
        "map_dagster_daemon_image_id": map_images["map_dagster_daemon"],
        "map_source_revision": map_commit,
        "pinvi_image_id": pinvi_image,
        "pinvi_source_revision": pinvi_commit,
        "recorded_at": "2026-07-19T00:00:00+00:00",
    }
    manifest = {"active": pair, "rollback": copy.deepcopy(pair), "version": 4}
    manifest_bytes = _canonical_json(manifest)
    environ = {
        "E2E_BASE_URL": "https://map.example.test",
        "E2E_C7_DAGSTER_DAEMON_SERVICE": services["map_dagster_daemon"],
        "E2E_C7_DAGSTER_WEB_SERVICE": services["map_dagster_web"],
        "E2E_C7_EXPECTED_GIT_COMMIT": map_commit,
        "E2E_C7_MAP_API_SERVICE": services["map_api"],
        "E2E_C7_PINVI_API_SERVICE": services["pinvi_api"],
        "E2E_C7_PLAYWRIGHT_IMAGE": executor_image,
        "E2E_C7_UI_SERVICE": services["map_ui"],
        "E2E_DAGSTER_URL": "https://dagster.example.test/graphql",
        "NEXT_PUBLIC_KOR_TRAVEL_MAP_API": "https://api.example.test",
    }
    observed = {
        "api_ws_origin_sha256": _sha256_bytes(b"wss://api.example.test"),
        "dagster_graphql_url_sha256": _sha256_bytes(
            b"https://dagster.example.test/graphql"
        ),
        "hostname_sha256": _sha256_bytes(b"n150.example.test"),
        "machine_id_sha256": _sha256_bytes(b"machine-id"),
        "ui_origin_sha256": _sha256_bytes(b"https://map.example.test"),
    }
    environ.update(
        {
            "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256": observed["api_ws_origin_sha256"],
            "E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256": observed[
                "dagster_graphql_url_sha256"
            ],
            "E2E_C7_EXPECTED_UI_ORIGIN_SHA256": observed["ui_origin_sha256"],
        }
    )
    attestation = {
        **observed,
        "c6c_contract_generation": generation,
        "compatible_pair_manifest_sha256": _sha256_bytes(manifest_bytes),
        "compose_project_sha256": _sha256_bytes(project_name.encode()),
        "orchestrator_files": {
            relative: "0" * 64 for relative in ATTESTATION.ORCHESTRATOR_PATHS
        },
        "playwright_base": playwright_base,
        "playwright_image_id": executor_image,
        "repository_commit": map_commit,
        "service_runtime": runtime,
        "source_commits": {"map": map_commit, "pinvi": pinvi_commit},
        "version": 3,
    }

    def run_command(command: list[str], _project_directory: str) -> str:
        if command[:2] == ["docker", "compose"]:
            return service_ids[command[-1]] + "\n"
        if command[:3] == ["docker", "inspect", "--"]:
            return json.dumps([records[command[3]]])
        if command[:4] == ["docker", "image", "inspect", "--"]:
            return json.dumps([image_records[command[4]]])
        raise AssertionError("unexpected command")

    return attestation, manifest, environ, run_command


def _verify_runtime(
    attestation: dict[str, object],
    manifest: dict[str, object],
    environ: dict[str, str],
    run_command: Callable,
) -> tuple[str, str]:
    return ATTESTATION.verify_runtime_attestation_payloads(
        _canonical_json(attestation),
        _canonical_json(manifest),
        project_directory="/srv/kor-travel-map",
        playwright_base="playwright@example",
        environ=environ,
        machine_id="machine-id",
        hostname="n150.example.test",
        run_json=run_command,
    )


def test_runtime_attestation_fixture_accepts_exact_metadata() -> None:
    attestation, manifest, environ, run_command = _runtime_fixture()

    manifest_sha256, attestation_sha256 = _verify_runtime(
        attestation, manifest, environ, run_command
    )

    assert manifest_sha256 == _sha256_bytes(_canonical_json(manifest))
    assert attestation_sha256 == _sha256_bytes(_canonical_json(attestation))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unexpected": True}),
        lambda value: value["orchestrator_files"].pop(
            "scripts/lib/c7_prod_attestation.py"
        ),
        lambda value: value.update({"playwright_image_id": "sha256:" + "f" * 64}),
        lambda value: value["service_runtime"]["map_api"].update(
            {"image_id": "sha256:" + "f" * 64}
        ),
    ],
)
def test_runtime_attestation_rejects_wrong_shape_or_image_metadata(
    mutation: Callable[[dict[str, object]], object],
) -> None:
    attestation, manifest, environ, run_command = _runtime_fixture()
    mutation(attestation)

    with pytest.raises(ATTESTATION.AttestationError):
        _verify_runtime(attestation, manifest, environ, run_command)


def test_runtime_attestation_rejects_compatible_pair_hash_mismatch() -> None:
    attestation, manifest, environ, run_command = _runtime_fixture()
    attestation["compatible_pair_manifest_sha256"] = "f" * 64

    with pytest.raises(ATTESTATION.AttestationError, match="compatible pair mismatch"):
        _verify_runtime(attestation, manifest, environ, run_command)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"version": 3}),
        lambda value: value["active"].pop("map_ui_image_id"),
        lambda value: value["rollback"].update({"unexpected": True}),
    ],
)
def test_runtime_attestation_rejects_non_v4_or_inexact_pair_shape(
    mutation: Callable[[dict[str, object]], object],
) -> None:
    attestation, manifest, environ, run_command = _runtime_fixture()
    mutation(manifest)
    attestation["compatible_pair_manifest_sha256"] = _sha256_bytes(
        _canonical_json(manifest)
    )

    with pytest.raises(ATTESTATION.AttestationError):
        _verify_runtime(attestation, manifest, environ, run_command)


@pytest.mark.parametrize(
    "field",
    [
        "map_image_id",
        "map_ui_image_id",
        "map_dagster_image_id",
        "map_dagster_daemon_image_id",
        "pinvi_image_id",
    ],
)
def test_runtime_attestation_rejects_each_active_runtime_image_mismatch(
    field: str,
) -> None:
    attestation, manifest, environ, run_command = _runtime_fixture()
    active = manifest["active"]
    assert isinstance(active, dict)
    active[field] = "sha256:" + "f" * 64
    attestation["compatible_pair_manifest_sha256"] = _sha256_bytes(
        _canonical_json(manifest)
    )

    with pytest.raises(ATTESTATION.AttestationError, match="active pair is not deployed"):
        _verify_runtime(attestation, manifest, environ, run_command)


def test_runtime_attestation_rejects_wrong_oci_revision() -> None:
    attestation, manifest, environ, original_run_command = _runtime_fixture()

    def tampered_run_command(command: list[str], project_directory: str) -> str:
        output = original_run_command(command, project_directory)
        if command[:4] != ["docker", "image", "inspect", "--"]:
            return output
        records = json.loads(output)
        labels = records[0]["Config"]["Labels"]
        if labels.get("org.opencontainers.image.revision") == "b" * 40:
            labels["org.opencontainers.image.revision"] = "c" * 40
        return json.dumps(records)

    with pytest.raises(ATTESTATION.AttestationError, match="source provenance"):
        _verify_runtime(attestation, manifest, environ, tampered_run_command)

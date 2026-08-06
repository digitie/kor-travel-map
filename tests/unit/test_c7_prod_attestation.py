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


def test_public_origin_brackets_ipv6_and_rejects_scope() -> None:
    """#805: IPv6 origin은 netloc에서 bracket + canonical로 재구성하고 zone-id는 거부한다."""
    origin = ATTESTATION._public_origin
    err = ATTESTATION.AttestationError

    # IPv6 리터럴은 bracket으로 감싸 `:port`와 모호하지 않게 재구성한다.
    assert origin("https://[2001:db8::1]:8443/") == "https://[2001:db8::1]:8443"
    assert origin("https://[2001:db8::1]/") == "https://[2001:db8::1]"
    # 동등한 확장 IPv6 표기는 압축 canonical 형으로 정규화된다(동일 origin으로 해시).
    assert (
        origin("https://[2001:0db8:0000:0000:0000:0000:0000:0001]:443/")
        == "https://[2001:db8::1]:443"
    )
    # websocket 스킴도 동일하게 bracket.
    assert (
        origin("https://[2001:db8::1]:9443/", websocket=True)
        == "wss://[2001:db8::1]:9443"
    )

    # IPv6 zone-id(scope)는 로컬 스코프라 거부한다. 2001:db8::1은 link-local이 아닌
    # 전역 주소라 unsafe-address 검사를 통과하므로, "%" guard가 ip_address() 파싱보다
    # 먼저 실행돼야 함을 검증한다(guard 순서가 load-bearing).
    with pytest.raises(err, match="scoped address"):
        origin("https://[2001:db8::1%25eth0]/")
    # loopback/link-local/unspecified IPv6은 여전히 unsafe.
    with pytest.raises(err, match="unsafe address"):
        origin("https://[::1]/")
    with pytest.raises(err, match="unsafe address"):
        origin("https://[fe80::1]/")
    with pytest.raises(err, match="unsafe address"):
        origin("https://[::]/")

    # domain/IPv4 origin은 bracket 없이 무변경(기존 attestation 해시 영향 없음).
    assert origin("https://map.example.org:443/") == "https://map.example.org:443"
    assert origin("https://192.0.2.10:8443/") == "https://192.0.2.10:8443"


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


def _runtime_fixture() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, str],
    Callable,
]:
    map_commit = "a" * 40
    pinvi_commit = "b" * 40
    map_images = {
        "map_api": "sha256:" + "1" * 64,
        "map_ui": "sha256:" + "4" * 64,
        "map_dagster_web": "sha256:" + "5" * 64,
        "map_dagster_daemon": "sha256:" + "6" * 64,
    }
    pinvi_images = {
        "pinvi_api": "sha256:" + "2" * 64,
        "pinvi_web": "sha256:" + "7" * 64,
        "pinvi_dagster": "sha256:" + "8" * 64,
    }
    executor_image = "sha256:" + "3" * 64
    project_name = "kor-travel-map-prod"
    playwright_base = "playwright@example"
    services = {
        "map_api": "map-api",
        "map_dagster_daemon": "map-daemon",
        "map_dagster_web": "map-web",
        "map_ui": "map-ui",
        "pinvi_api": "pinvi-api",
        "pinvi_web": "pinvi-web",
        "pinvi_dagster": "pinvi-dagster",
    }
    environments = {role: ["A=1"] for role in services}
    environments["map_api"] = [
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=admin-proxy-0000000000000000000000000000",
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=cursor-secret-000000000000000000000000000",
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN=metrics-token-000000000000000000000000000",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=ops-cancel-000000000000000000000000000",
        "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN=ops-fixture-0000000000000000000000000",
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=ops-read-00000000000000000000000000000",
        "KOR_TRAVEL_MAP_API_PROFILE=production",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN=service-token-000000000000000000000000000",
        "KOR_TRAVEL_MAP_API_VWORLD_API_KEY=vworld-key-00000000000000000000000000000",
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
            image_id: {
                "Config": {"Labels": {"org.opencontainers.image.revision": pinvi_commit}}
            }
            for image_id in pinvi_images.values()
        }
    )
    image_records[executor_image] = {
        "Config": {
            "Labels": {
                "io.kortravelmap.c7.playwright-base": playwright_base,
                "io.kortravelmap.c7.repository-commit": map_commit,
            }
        },
        "Id": executor_image,
    }
    runtime: dict[str, object] = {}
    service_ids: dict[str, str] = {}
    for index, (role, service) in enumerate(services.items()):
        container_id = "456789a"[index] * 64
        image_id = pinvi_images[role] if role.startswith("pinvi_") else map_images[role]
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
            "compose_service": service,
            "container_id": container_id,
            "image_id": image_id,
        }
    active_generation = {
        "map_api_image_id": map_images["map_api"],
        "map_ui_image_id": map_images["map_ui"],
        "map_dagster_image_id": map_images["map_dagster_web"],
        "map_dagster_daemon_image_id": map_images["map_dagster_daemon"],
        "map_source_revision": map_commit,
        "pinvi_api_image_id": pinvi_images["pinvi_api"],
        "pinvi_web_image_id": pinvi_images["pinvi_web"],
        "pinvi_dagster_image_id": pinvi_images["pinvi_dagster"],
        "pinvi_source_revision": pinvi_commit,
        "map_application_head": "0090_tvn33_cutover_fence",
        "map_dagster_head": "29b539ebc72a",
        "pinvi_head": "20260804_0049",
        "pinset_sha256": "9" * 64,
        "recorded_at": "2026-07-19T00:00:00+00:00",
    }
    manifest = {"active_generation": active_generation, "version": 5}
    manifest_bytes = _canonical_json(manifest)
    rebuild_journal = {
        "version": 7,
        "transaction_id": "11111111-1111-1111-1111-111111111111",
        "phase": "committed",
        "candidate": copy.deepcopy(active_generation),
        "environment_sha256": "c" * 64,
        "compose_sha256": "d" * 64,
        "resolved_compose_sha256": "e" * 64,
        "created_at": "2026-07-19T00:00:01+00:00",
        "cancel_probe": {
            "stage": "finalized",
            "job_id": "22222222-2222-2222-2222-222222222222",
            "cancellation_id": "33333333-3333-3333-3333-333333333333",
            "outcome": {
                "name": "pinvi_cancel_error",
                "status": 409,
                "code": "PIPELINE_CANCELLATION_UNSAFE",
            },
            "fixture_created_at": "2026-07-19T00:00:02+00:00",
            "fixture_consumed_at": "2026-07-19T00:00:03+00:00",
            "fixture_finalized_at": "2026-07-19T00:00:04+00:00",
        },
    }
    rebuild_journal_bytes = _canonical_json(rebuild_journal)
    final_schema_reload_receipt = {
        "version": 1,
        "pinned_runtime_manifest_sha256": _sha256_bytes(manifest_bytes),
        "pinned_runtime_rebuild_journal_sha256": _sha256_bytes(rebuild_journal_bytes),
        "schema_heads": {
            "map_application": active_generation["map_application_head"],
            "map_dagster": active_generation["map_dagster_head"],
            "pinvi": active_generation["pinvi_head"],
        },
        "source_reload": {
            "status": "succeeded",
            "source_snapshot_sha256": "c" * 64,
            "observed_generation_sha256": _sha256_bytes(
                _canonical_json(active_generation)
            ),
            "observed_map_api_image_id": active_generation["map_api_image_id"],
            "observed_schema_heads": {
                "map_application": active_generation["map_application_head"],
                "map_dagster": active_generation["map_dagster_head"],
                "pinvi": active_generation["pinvi_head"],
            },
            "completed_at": "2026-07-19T00:00:05+00:00",
        },
        "etl_reload": {
            "status": "succeeded",
            "run_id": "44444444-4444-4444-4444-444444444444",
            "result_sha256": "e" * 64,
            "consumed_source_snapshot_sha256": "c" * 64,
            "rebuild_transaction_id": rebuild_journal["transaction_id"],
            "observed_generation_sha256": _sha256_bytes(
                _canonical_json(active_generation)
            ),
            "observed_map_api_image_id": active_generation["map_api_image_id"],
            "observed_schema_heads": {
                "map_application": active_generation["map_application_head"],
                "map_dagster": active_generation["map_dagster_head"],
                "pinvi": active_generation["pinvi_head"],
            },
            "completed_at": "2026-07-19T00:00:06+00:00",
        },
        "canonical_dataset_availability": {
            "status": "available",
            "dataset_count": 1,
            "feature_count": 1,
            "availability_sha256": "d" * 64,
        },
        "recorded_at": "2026-07-19T00:00:07+00:00",
    }
    final_schema_reload_receipt_bytes = _canonical_json(final_schema_reload_receipt)
    environ = {
        "E2E_BASE_URL": "https://map.example.test",
        "E2E_C7_DAGSTER_DAEMON_SERVICE": services["map_dagster_daemon"],
        "E2E_C7_DAGSTER_WEB_SERVICE": services["map_dagster_web"],
        "E2E_C7_EXPECTED_GIT_COMMIT": map_commit,
        "E2E_C7_MAP_API_SERVICE": services["map_api"],
        "E2E_C7_PINVI_API_SERVICE": services["pinvi_api"],
        "E2E_C7_PINVI_DAGSTER_SERVICE": services["pinvi_dagster"],
        "E2E_C7_PINVI_WEB_SERVICE": services["pinvi_web"],
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
        "compose_project_sha256": _sha256_bytes(project_name.encode()),
        "endpoint_roles": {
            "api_websocket": "map_api",
            "dagster_graphql": "map_dagster_web",
            "ui": "map_ui",
        },
        "final_schema_reload_receipt_sha256": _sha256_bytes(
            final_schema_reload_receipt_bytes
        ),
        "orchestrator_files": {
            relative: "0" * 64 for relative in ATTESTATION.ORCHESTRATOR_PATHS
        },
        "playwright_base": playwright_base,
        "playwright_image_id": executor_image,
        "pinned_runtime_manifest_sha256": _sha256_bytes(manifest_bytes),
        "pinned_runtime_rebuild_journal_sha256": _sha256_bytes(rebuild_journal_bytes),
        "pinset_sha256": active_generation["pinset_sha256"],
        "repository_commit": map_commit,
        "schema_heads": {
            "map_application": active_generation["map_application_head"],
            "map_dagster": active_generation["map_dagster_head"],
            "pinvi": active_generation["pinvi_head"],
        },
        "service_runtime": runtime,
        "source_commits": {"map": map_commit, "pinvi": pinvi_commit},
        "version": 5,
    }

    def run_command(command: list[str], _project_directory: str) -> str:
        if command[:6] == [
            "docker",
            "compose",
            "--project-directory",
            "/srv/kor-travel-map",
            "exec",
            "-T",
        ]:
            assert command[6] == services["map_api"]
            if command[7:] == ["ktm-application-schema", "head"]:
                return (
                    '{"schema":"kor-travel-map.application-head.v1","head":"'
                    f"{active_generation['map_application_head']}\"}}\n"
                )
            assert command[7] == "alembic"
            if command[8] == "current":
                return f"{active_generation['map_application_head']} (head)\n"
            if command[8] == "check":
                return ""
        if command[:2] == ["docker", "compose"]:
            return service_ids[command[-1]] + "\n"
        if command[:3] == ["docker", "inspect", "--"]:
            return json.dumps([records[command[3]]])
        if command[:4] == ["docker", "image", "inspect", "--"]:
            return json.dumps([image_records[command[4]]])
        raise AssertionError("unexpected command")

    return (
        attestation,
        manifest,
        rebuild_journal,
        final_schema_reload_receipt,
        environ,
        run_command,
    )


def _verify_runtime(
    attestation: dict[str, object],
    manifest: dict[str, object],
    rebuild_journal: dict[str, object],
    final_schema_reload_receipt: dict[str, object],
    environ: dict[str, str],
    run_command: Callable,
) -> tuple[str, str, str, str, str]:
    return ATTESTATION.verify_runtime_attestation_payloads(
        _canonical_json(attestation),
        _canonical_json(manifest),
        _canonical_json(rebuild_journal),
        _canonical_json(final_schema_reload_receipt),
        project_directory="/srv/kor-travel-map",
        playwright_base="playwright@example",
        environ=environ,
        machine_id="machine-id",
        hostname="n150.example.test",
        run_json=run_command,
    )


def _refresh_reload_receipt_authority(
    attestation: dict[str, object],
    manifest: dict[str, object],
    rebuild_journal: dict[str, object],
    receipt: dict[str, object],
) -> None:
    active = manifest["active_generation"]
    assert isinstance(active, dict)
    receipt["pinned_runtime_manifest_sha256"] = _sha256_bytes(_canonical_json(manifest))
    receipt["pinned_runtime_rebuild_journal_sha256"] = _sha256_bytes(
        _canonical_json(rebuild_journal)
    )
    receipt["schema_heads"] = {
        "map_application": active["map_application_head"],
        "map_dagster": active["map_dagster_head"],
        "pinvi": active["pinvi_head"],
    }
    observed_heads = receipt["schema_heads"]
    assert isinstance(observed_heads, dict)
    for reload_name in ("source_reload", "etl_reload"):
        reload = receipt[reload_name]
        assert isinstance(reload, dict)
        reload["observed_generation_sha256"] = _sha256_bytes(
            _canonical_json(active)
        )
        reload["observed_map_api_image_id"] = active["map_api_image_id"]
        reload["observed_schema_heads"] = observed_heads.copy()
    attestation["pinned_runtime_manifest_sha256"] = receipt[
        "pinned_runtime_manifest_sha256"
    ]
    attestation["pinned_runtime_rebuild_journal_sha256"] = receipt[
        "pinned_runtime_rebuild_journal_sha256"
    ]
    attestation["final_schema_reload_receipt_sha256"] = _sha256_bytes(
        _canonical_json(receipt)
    )


def _mutate_runtime_environment(
    attestation: dict[str, object],
    environ: dict[str, str],
    original_run_command: Callable,
    role: str,
    mutation: Callable[[list[str]], None],
) -> Callable:
    service_env = {
        "map_api": "E2E_C7_MAP_API_SERVICE",
        "map_dagster_daemon": "E2E_C7_DAGSTER_DAEMON_SERVICE",
        "map_dagster_web": "E2E_C7_DAGSTER_WEB_SERVICE",
        "map_ui": "E2E_C7_UI_SERVICE",
        "pinvi_api": "E2E_C7_PINVI_API_SERVICE",
        "pinvi_web": "E2E_C7_PINVI_WEB_SERVICE",
        "pinvi_dagster": "E2E_C7_PINVI_DAGSTER_SERVICE",
    }
    service = environ[service_env[role]]
    container_id = original_run_command(
        ["docker", "compose", "--project-directory", "/srv/kor-travel-map", "ps", "-q", service],
        "/srv/kor-travel-map",
    ).strip()
    record = json.loads(
        original_run_command(
            ["docker", "inspect", "--", container_id],
            "/srv/kor-travel-map",
        )
    )[0]
    environment = list(record["Config"]["Env"])
    mutation(environment)
    runtime = attestation["service_runtime"]
    assert isinstance(runtime, dict)
    role_runtime = runtime[role]
    assert isinstance(role_runtime, dict)
    role_runtime["environment_sha256"] = _sha256_bytes(
        _canonical_json(sorted(environment))
    )

    def run_command(command: list[str], project_directory: str) -> str:
        output = original_run_command(command, project_directory)
        if command[:3] != ["docker", "inspect", "--"] or command[3] != container_id:
            return output
        records = json.loads(output)
        records[0]["Config"]["Env"] = environment
        return json.dumps(records)

    return run_command


def test_runtime_attestation_fixture_accepts_exact_metadata() -> None:
    (
        attestation,
        manifest,
        rebuild_journal,
        final_schema_reload_receipt,
        environ,
        run_command,
    ) = _runtime_fixture()

    (
        manifest_sha256,
        rebuild_journal_sha256,
        reload_receipt_sha256,
        attestation_sha256,
        map_application_head,
    ) = _verify_runtime(
        attestation,
        manifest,
        rebuild_journal,
        final_schema_reload_receipt,
        environ,
        run_command,
    )

    assert manifest_sha256 == _sha256_bytes(_canonical_json(manifest))
    assert rebuild_journal_sha256 == _sha256_bytes(_canonical_json(rebuild_journal))
    assert reload_receipt_sha256 == _sha256_bytes(
        _canonical_json(final_schema_reload_receipt)
    )
    assert attestation_sha256 == _sha256_bytes(_canonical_json(attestation))
    assert map_application_head == "0090_tvn33_cutover_fence"


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
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    mutation(attestation)

    with pytest.raises(ATTESTATION.AttestationError):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


def test_runtime_attestation_rejects_pinned_runtime_manifest_hash_mismatch() -> None:
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    attestation["pinned_runtime_manifest_sha256"] = "f" * 64

    with pytest.raises(ATTESTATION.AttestationError, match="pinned runtime authority mismatch"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda value: value["source_reload"].update({"status": "failed"}),
            "final schema reload receipt",
        ),
        (
            lambda value: value["etl_reload"].update({"status": "running"}),
            "final schema reload receipt",
        ),
        (
            lambda value: value["canonical_dataset_availability"].update(
                {"dataset_count": 0}
            ),
            "final schema reload receipt",
        ),
        (
            lambda value: value["schema_heads"].update({"map_application": "old_head"}),
            "final schema reload receipt binding",
        ),
        (
            lambda value: value.update({"pinned_runtime_manifest_sha256": "f" * 64}),
            "final schema reload receipt binding",
        ),
        (
            lambda value: value["source_reload"].update(
                {"observed_generation_sha256": "f" * 64}
            ),
            "final schema reload receipt",
        ),
        (
            lambda value: value["etl_reload"].update(
                {"observed_map_api_image_id": "sha256:" + "f" * 64}
            ),
            "final schema reload receipt",
        ),
        (
            lambda value: value["etl_reload"]["observed_schema_heads"].update(
                {"map_application": "old_head"}
            ),
            "final schema reload receipt",
        ),
        (
            lambda value: value["source_reload"].update(
                {"completed_at": "2026-07-18T23:59:59+00:00"}
            ),
            "final schema reload receipt",
        ),
        (
            # active_generation.recorded_at과는 같아 기존 검증을 통과하지만,
            # committed rebuild(00:00:01) 이전 source output은 final reload가 아니다.
            lambda value: value["source_reload"].update(
                {"completed_at": "2026-07-19T00:00:00+00:00"}
            ),
            "final schema reload receipt",
        ),
        (
            # rebuild commit과 같은 시각은 source reload가 그 뒤에 끝났음을 증명하지 못한다.
            lambda value: value["source_reload"].update(
                {"completed_at": "2026-07-19T00:00:01+00:00"}
            ),
            "final schema reload receipt",
        ),
        (
            lambda value: value["etl_reload"].update(
                {"completed_at": "2026-07-19T00:00:05+00:00"}
            ),
            "final schema reload receipt",
        ),
        (
            lambda value: value.update({"recorded_at": "2026-07-19T00:00:06+00:00"}),
            "final schema reload receipt",
        ),
        (
            lambda value: value["etl_reload"].update(
                {"consumed_source_snapshot_sha256": "f" * 64}
            ),
            "final schema reload receipt",
        ),
        (
            lambda value: value["etl_reload"].update(
                {"rebuild_transaction_id": "99999999-9999-4999-8999-999999999999"}
            ),
            "final schema reload receipt",
        ),
        (
            lambda value: value.clear(),
            "final schema reload receipt shape",
        ),
    ],
)
def test_runtime_attestation_rejects_stale_or_incomplete_final_schema_reload_receipt(
    mutation: Callable[[dict[str, object]], object], expected: str
) -> None:
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    mutation(receipt)
    attestation["final_schema_reload_receipt_sha256"] = _sha256_bytes(
        _canonical_json(receipt)
    )

    with pytest.raises(ATTESTATION.AttestationError, match=expected):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


@pytest.mark.parametrize(
    ("role", "service_env"),
    [
        ("map_api", "E2E_C7_MAP_API_SERVICE"),
        ("map_dagster_daemon", "E2E_C7_DAGSTER_DAEMON_SERVICE"),
        ("map_dagster_web", "E2E_C7_DAGSTER_WEB_SERVICE"),
        ("map_ui", "E2E_C7_UI_SERVICE"),
        ("pinvi_api", "E2E_C7_PINVI_API_SERVICE"),
        ("pinvi_web", "E2E_C7_PINVI_WEB_SERVICE"),
        ("pinvi_dagster", "E2E_C7_PINVI_DAGSTER_SERVICE"),
    ],
)
def test_runtime_attestation_rejects_shadow_compose_service_env(
    role: str, service_env: str
) -> None:
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    environ[service_env] = f"shadow-{role}"

    with pytest.raises(ATTESTATION.AttestationError, match="runtime attestation value"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


@pytest.mark.parametrize(
    "role",
    [
        "map_api",
        "map_dagster_daemon",
        "map_dagster_web",
        "map_ui",
        "pinvi_api",
        "pinvi_web",
        "pinvi_dagster",
    ],
)
def test_runtime_attestation_rejects_each_runtime_container_binding_drift(
    role: str,
) -> None:
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    service_runtime = attestation["service_runtime"]
    assert isinstance(service_runtime, dict)
    role_runtime = service_runtime[role]
    assert isinstance(role_runtime, dict)
    role_runtime["container_id"] = "f" * 64

    with pytest.raises(ATTESTATION.AttestationError, match="runtime container binding"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


def test_runtime_attestation_rejects_endpoint_role_binding_drift() -> None:
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    attestation["endpoint_roles"] = {
        "api_websocket": "map_ui",
        "dagster_graphql": "map_dagster_web",
        "ui": "map_api",
    }
    with pytest.raises(ATTESTATION.AttestationError, match="endpoint role binding"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


@pytest.mark.parametrize(
    ("command_tail", "expected_error"),
    [
        (
            ["ktm-application-schema", "head"],
            "Map application installed artifact head mismatch",
        ),
        (["alembic", "current"], "Map application database head mismatch"),
    ],
)
def test_runtime_attestation_rejects_installed_artifact_or_database_head_drift(
    command_tail: list[str],
    expected_error: str,
) -> None:
    (
        attestation,
        manifest,
        rebuild_journal,
        receipt,
        environ,
        original_run_command,
    ) = _runtime_fixture()

    def wrong_head(command: list[str], project_directory: str) -> str:
        if command[-len(command_tail) :] == command_tail:
            if command_tail[0] == "ktm-application-schema":
                return (
                    '{"schema":"kor-travel-map.application-head.v1",'
                    '"head":"0089_tvn33_constraints"}\n'
                )
            return "0089_tvn33_constraints (head)\n"
        return original_run_command(command, project_directory)

    with pytest.raises(ATTESTATION.AttestationError, match=expected_error):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, wrong_head)


@pytest.mark.parametrize(
    "output",
    [
        '{"schema":"kor-travel-map.application-head.v1","head":"UPPER"}\n',
        '{"head":"0090_tvn33_cutover_fence","schema":"kor-travel-map.application-head.v1"}\n',
        '{"schema":"kor-travel-map.application-head.v1","head":"0090_tvn33_cutover_fence"}\nextra\n',
    ],
)
def test_runtime_attestation_rejects_noncanonical_installed_schema_artifact_output(
    output: str,
) -> None:
    attestation, manifest, rebuild_journal, receipt, environ, original_run_command = (
        _runtime_fixture()
    )

    def malformed_artifact(command: list[str], project_directory: str) -> str:
        if command[-2:] == ["ktm-application-schema", "head"]:
            return output
        return original_run_command(command, project_directory)

    with pytest.raises(ATTESTATION.AttestationError, match="schema artifact output"):
        _verify_runtime(
            attestation,
            manifest,
            rebuild_journal,
            receipt,
            environ,
            malformed_artifact,
        )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (
            lambda value: value.update({"phase": "prepared"}),
            "pinned runtime rebuild journal",
        ),
        (
            lambda value: value["candidate"].update({"pinset_sha256": "f" * 64}),
            "pinned runtime journal candidate drift",
        ),
        (
            lambda value: value["cancel_probe"].update({"stage": "consumed"}),
            "pinned runtime cancel probe",
        ),
        (
            lambda value: value["cancel_probe"].update(
                {
                    "fixture_consumed_at": "2026-07-19T00:00:01+00:00",
                    "fixture_finalized_at": "2026-07-19T00:00:00+00:00",
                }
            ),
            "pinned runtime cancel probe ordering",
        ),
    ],
)
def test_runtime_attestation_rejects_uncommitted_or_inexact_rebuild_journal(
    mutation: Callable[[dict[str, object]], object], expected: str
) -> None:
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    mutation(rebuild_journal)
    attestation["pinned_runtime_rebuild_journal_sha256"] = _sha256_bytes(
        _canonical_json(rebuild_journal)
    )

    with pytest.raises(ATTESTATION.AttestationError, match=expected):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"version": 4}),
        lambda value: value["active_generation"].pop("map_ui_image_id"),
        lambda value: value.update({"unexpected": True}),
    ],
)
def test_runtime_attestation_rejects_non_v5_or_inexact_generation_shape(
    mutation: Callable[[dict[str, object]], object],
) -> None:
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    mutation(manifest)
    attestation["pinned_runtime_manifest_sha256"] = _sha256_bytes(
        _canonical_json(manifest)
    )

    with pytest.raises(ATTESTATION.AttestationError):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


@pytest.mark.parametrize(
    "field",
    [
        "map_api_image_id",
        "map_ui_image_id",
        "map_dagster_image_id",
        "map_dagster_daemon_image_id",
        "pinvi_api_image_id",
        "pinvi_web_image_id",
        "pinvi_dagster_image_id",
    ],
)
def test_runtime_attestation_rejects_each_active_runtime_image_mismatch(
    field: str,
) -> None:
    attestation, manifest, rebuild_journal, receipt, environ, run_command = _runtime_fixture()
    active = manifest["active_generation"]
    assert isinstance(active, dict)
    active[field] = "sha256:" + "f" * 64
    candidate = rebuild_journal["candidate"]
    assert isinstance(candidate, dict)
    candidate[field] = active[field]
    _refresh_reload_receipt_authority(attestation, manifest, rebuild_journal, receipt)

    with pytest.raises(ATTESTATION.AttestationError, match="active generation is not deployed"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


def test_runtime_attestation_rejects_wrong_oci_revision() -> None:
    (
        attestation,
        manifest,
        rebuild_journal,
        receipt,
        environ,
        original_run_command,
    ) = _runtime_fixture()

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
        _verify_runtime(
            attestation,
            manifest,
            rebuild_journal,
            receipt,
            environ,
            tampered_run_command,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values.__setitem__(
            slice(None),
            [
                item
                for item in values
                if not item.startswith("KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=")
            ],
        ),
        lambda values: values.__setitem__(
            next(
                index
                for index, item in enumerate(values)
                if item.startswith("KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=")
            ),
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=short",
        ),
        lambda values: values.__setitem__(
            next(
                index
                for index, item in enumerate(values)
                if item.startswith("KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=")
            ),
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=cursor secret with whitespace 000000000000",
        ),
        lambda values: values.__setitem__(
            next(
                index
                for index, item in enumerate(values)
                if item.startswith("KOR_TRAVEL_MAP_API_PROFILE=")
            ),
            "KOR_TRAVEL_MAP_API_PROFILE=local-dev",
        ),
        lambda values: values.__setitem__(
            next(
                index
                for index, item in enumerate(values)
                if item.startswith("KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=")
            ),
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=false",
        ),
    ],
)
def test_runtime_attestation_rejects_invalid_api_cursor_secret_shape(
    mutation: Callable[[list[str]], None],
) -> None:
    (
        attestation,
        manifest,
        rebuild_journal,
        receipt,
        environ,
        original_run_command,
    ) = _runtime_fixture()
    run_command = _mutate_runtime_environment(
        attestation,
        environ,
        original_run_command,
        "map_api",
        mutation,
    )

    with pytest.raises(ATTESTATION.AttestationError, match="cursor secret runtime shape"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


@pytest.mark.parametrize(
    "protected_name",
    [
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
        "KOR_TRAVEL_MAP_API_VWORLD_API_KEY",
    ],
)
def test_runtime_attestation_rejects_api_cursor_secret_reuse(
    protected_name: str,
) -> None:
    (
        attestation,
        manifest,
        rebuild_journal,
        receipt,
        environ,
        original_run_command,
    ) = _runtime_fixture()

    def reuse_protected_value(values: list[str]) -> None:
        cursor = next(
            item.split("=", 1)[1]
            for item in values
            if item.startswith("KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=")
        )
        index = next(
            index
            for index, item in enumerate(values)
            if item.startswith(f"{protected_name}=")
        )
        values[index] = f"{protected_name}={cursor}"

    run_command = _mutate_runtime_environment(
        attestation,
        environ,
        original_run_command,
        "map_api",
        reuse_protected_value,
    )

    with pytest.raises(ATTESTATION.AttestationError, match="cursor secret runtime reuse"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


def test_runtime_attestation_rejects_duplicate_cursor_secret_name() -> None:
    (
        attestation,
        manifest,
        rebuild_journal,
        receipt,
        environ,
        original_run_command,
    ) = _runtime_fixture()
    run_command = _mutate_runtime_environment(
        attestation,
        environ,
        original_run_command,
        "map_api",
        lambda values: values.append(
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=duplicate-0000000000000000000000000000"
        ),
    )

    with pytest.raises(ATTESTATION.AttestationError, match="runtime environment shape"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)


@pytest.mark.parametrize(
    "role",
    [
        "map_dagster_daemon",
        "map_dagster_web",
        "map_ui",
        "pinvi_api",
        "pinvi_web",
        "pinvi_dagster",
    ],
)
def test_runtime_attestation_rejects_cursor_secret_outside_api(role: str) -> None:
    (
        attestation,
        manifest,
        rebuild_journal,
        receipt,
        environ,
        original_run_command,
    ) = _runtime_fixture()
    run_command = _mutate_runtime_environment(
        attestation,
        environ,
        original_run_command,
        role,
        lambda values: values.append(
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=escaped-00000000000000000000000000000"
        ),
    )

    with pytest.raises(ATTESTATION.AttestationError, match="escaped API runtime"):
        _verify_runtime(attestation, manifest, rebuild_journal, receipt, environ, run_command)

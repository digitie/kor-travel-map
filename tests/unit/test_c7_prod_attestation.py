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


def _canonical_document_sha256(value: object) -> str:
    return _sha256_bytes(
        (
            json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
    )


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
    dict[str, object], dict[str, object], dict[str, object], dict[str, str], Callable
]:
    map_commit = "a" * 40
    pinvi_commit = "b" * 40
    role_images = {
        "map_api": "sha256:" + "1" * 64,
        "map_ui": "sha256:" + "4" * 64,
        "map_dagster_web": "sha256:" + "5" * 64,
        "map_dagster_daemon": "sha256:" + "6" * 64,
        "pinvi_api": "sha256:" + "2" * 64,
        "pinvi_web": "sha256:" + "7" * 64,
        "pinvi_dagster": "sha256:" + "8" * 64,
    }
    executor_image = "sha256:" + "3" * 64
    project_name = "kor-travel-map-prod"
    playwright_base = "playwright@example"
    pinset = "c" * 64
    services = {
        "map_api": "map-api",
        "map_dagster_daemon": "map-daemon",
        "map_dagster_web": "map-web",
        "map_ui": "map-ui",
        "pinvi_api": "pinvi-api",
        "pinvi_dagster": "pinvi-dagster",
        "pinvi_web": "pinvi-web",
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
            "Config": {
                "Labels": {
                    "org.opencontainers.image.revision": (
                        pinvi_commit if role in ATTESTATION._PINVI_ROLES else map_commit
                    )
                }
            }
        }
        for role, image_id in role_images.items()
    }
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
    for index, (role, service) in enumerate(services.items(), start=1):
        container_id = f"{index:x}" * 64
        image_id = role_images[role]
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
    schema_heads = {
        "map_application_head": "300",
        "map_dagster_head": "29b539ebc72a",
        "pinvi_head": "20260804_0049",
    }
    candidate_evidence = {
        "paired_receipt_sha256": "1" * 64,
        "api_receipt_sha256": "2" * 64,
        "candidate_git_tree": "3" * 40,
        "postgres_image_id": "sha256:" + "9" * 64,
        "dagster_config_sha256": "4" * 64,
        "dagster_yaml_sha256": "5" * 64,
        "application_contract_sha256": "6" * 64,
        "launch_contract_sha256": "7" * 64,
    }
    generation = {
        **{field: role_images[role] for role, field in ATTESTATION.GENERATION_RUNTIME_IMAGE_FIELDS},
        **schema_heads,
        "map_source_revision": map_commit,
        "pinvi_source_revision": pinvi_commit,
        "pinset_sha256": pinset,
        "map_application_300_candidate_evidence": candidate_evidence,
        "recorded_at": "2026-07-19T00:00:00+00:00",
    }
    manifest = {"active_generation": generation, "version": 6}
    transaction_id = "11111111-2222-3333-4444-555555555555"
    application_create_identity = {
        "database_name": "kor_travel_map",
        "database_oid": 16384,
        "database_owner": "ktm_admin",
        "postgres_system_identifier": "1234567890123456789",
    }
    application_identity = {
        **application_create_identity,
        "database_owner": "ktm_feature_schema_owner",
    }
    dagster_identity = {
        "system_identifier": "1234567890123456789",
        "name": "kor_travel_map_dagster",
        "oid": 16385,
        "owner": "ktm_dagster",
        "login_role": "ktm_dagster",
        "login_role_attributes": {
            "can_login": True,
            "inherit": False,
            "superuser": False,
            "create_database": False,
            "create_role": False,
            "replication": False,
            "bypass_rls": False,
            "granted_role_count": 0,
            "member_role_count": 0,
        },
    }
    root_plan = {
        "transaction_id": "10000000-0000-0000-0000-000000000001",
        "operation_id": "20000000-0000-0000-0000-000000000001",
        "basis_journal_sha256": "8" * 64,
        "basis_journal_generation": 7,
        "writer_fence_expires_at": "2026-07-19T00:10:00+00:00",
        "fence_sha256": "9" * 64,
        "result_sha256": "a" * 64,
    }
    finalize_plan = {
        "transaction_id": "10000000-0000-0000-0000-000000000002",
        "operation_id": "20000000-0000-0000-0000-000000000002",
        "basis_journal_sha256": "b" * 64,
        "basis_journal_generation": 11,
        "writer_fence_expires_at": "2026-07-19T00:20:00+00:00",
        "fence_sha256": "c" * 64,
        "result_sha256": "d" * 64,
    }
    execution_evidence = {
        "application_create_database_identity": application_create_identity,
        "application_create_database_identity_sha256": (
            _canonical_document_sha256(application_create_identity)
        ),
        "application_database_identity": application_identity,
        "application_database_identity_sha256": (
            _canonical_document_sha256(application_identity)
        ),
        "fresh_root_operation_plan": root_plan,
        "fresh_finalize_operation_plan": finalize_plan,
        "app_final_permit_sha256": "e" * 64,
        "dagster_metadata_database_identity": dagster_identity,
        "dagster_metadata_database_identity_sha256": (
            _canonical_document_sha256(dagster_identity)
        ),
        "metadata_permit_sha256": "f" * 64,
    }
    journal = {
        "candidate": copy.deepcopy(generation),
        "map_application_300_candidate_evidence": copy.deepcopy(candidate_evidence),
        "map_application_300_execution_evidence": execution_evidence,
        "cancel_probe": {
            "cancellation_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            "fixture_consumed_at": "2026-07-19T00:00:01+00:00",
            "fixture_created_at": "2026-07-19T00:00:00+00:00",
            "fixture_finalized_at": "2026-07-19T00:00:02+00:00",
            "job_id": "99999999-8888-7777-6666-555555555555",
            "outcome": {
                "code": "PIPELINE_CANCELLATION_UNSAFE",
                "name": "pinvi_cancel_error",
                "status": 409,
            },
            "stage": "finalized",
        },
        "compose_sha256": "d" * 64,
        "created_at": "2026-07-19T00:00:00+00:00",
        "environment_sha256": "e" * 64,
        "journal_generation": 27,
        "phase": "committed",
        "resolved_compose_sha256": "f" * 64,
        "transaction_id": transaction_id,
        "version": 8,
    }
    manifest_bytes = _canonical_json(manifest)
    journal_bytes = _canonical_json(journal)
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
        "orchestrator_files": {
            relative: "0" * 64 for relative in ATTESTATION.ORCHESTRATOR_PATHS
        },
        "pinned_runtime_manifest_sha256": _sha256_bytes(manifest_bytes),
        "pinned_runtime_pinset_sha256": pinset,
        "playwright_base": playwright_base,
        "playwright_image_id": executor_image,
        "rebuild_journal_sha256": _sha256_bytes(journal_bytes),
        "rebuild_transaction_id": transaction_id,
        "repository_commit": map_commit,
        "schema_heads": dict(schema_heads),
        "service_runtime": runtime,
        "source_commits": {"map": map_commit, "pinvi": pinvi_commit},
        "version": 4,
    }

    def run_command(command: list[str], _project_directory: str) -> str:
        if command[:2] == ["docker", "compose"]:
            return service_ids[command[-1]] + "\n"
        if command[:3] == ["docker", "inspect", "--"]:
            return json.dumps([records[command[3]]])
        if command[:4] == ["docker", "image", "inspect", "--"]:
            return json.dumps([image_records[command[4]]])
        raise AssertionError("unexpected command")

    return attestation, manifest, journal, environ, run_command


def _verify_runtime(
    attestation: dict[str, object],
    manifest: dict[str, object],
    journal: dict[str, object],
    environ: dict[str, str],
    run_command: Callable,
) -> tuple[str, str, str]:
    return ATTESTATION.verify_runtime_attestation_payloads(
        _canonical_json(attestation),
        _canonical_json(manifest),
        _canonical_json(journal),
        project_directory="/srv/kor-travel-map",
        playwright_base="playwright@example",
        environ=environ,
        machine_id="machine-id",
        hostname="n150.example.test",
        run_json=run_command,
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
        "pinvi_dagster": "E2E_C7_PINVI_DAGSTER_SERVICE",
        "pinvi_web": "E2E_C7_PINVI_WEB_SERVICE",
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
    attestation, manifest, journal, environ, run_command = _runtime_fixture()

    manifest_sha256, journal_sha256, attestation_sha256 = _verify_runtime(
        attestation, manifest, journal, environ, run_command
    )

    assert manifest_sha256 == _sha256_bytes(_canonical_json(manifest))
    assert journal_sha256 == _sha256_bytes(_canonical_json(journal))
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
    attestation, manifest, journal, environ, run_command = _runtime_fixture()
    mutation(attestation)

    with pytest.raises(ATTESTATION.AttestationError):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


@pytest.mark.parametrize(
    "key",
    [
        "pinned_runtime_manifest_sha256",
        "rebuild_journal_sha256",
        "pinned_runtime_pinset_sha256",
    ],
)
def test_runtime_attestation_rejects_each_pinned_generation_digest_mismatch(
    key: str,
) -> None:
    attestation, manifest, journal, environ, run_command = _runtime_fixture()
    attestation[key] = "f" * 64

    with pytest.raises(
        ATTESTATION.AttestationError, match="pinned runtime generation mismatch"
    ):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.update({"version": 4}), "manifest shape"),
        (
            lambda value: value.update({"active": value["active_generation"]}),
            "manifest shape",
        ),
        (lambda value: value["active_generation"].pop("map_ui_image_id"), "generation shape"),
        (
            lambda value: value["active_generation"].update({"unexpected": True}),
            "generation shape",
        ),
        (
            lambda value: value["active_generation"].update({"pinset_sha256": "not-a-digest"}),
            "generation pinset",
        ),
        (
            lambda value: value["active_generation"].update({"pinvi_head": "NOT LOWER"}),
            "generation schema head",
        ),
        (
            lambda value: value["active_generation"].update({"map_dagster_head": 7}),
            "generation schema head",
        ),
        (
            lambda value: value["active_generation"].update(
                {"recorded_at": "2026-07-19T00:00:00"}
            ),
            "generation recorded_at",
        ),
        (
            lambda value: value["active_generation"].update(
                {"recorded_at": "2026-07-19T09:00:00+09:00"}
            ),
            "generation recorded_at",
        ),
    ],
)
def test_runtime_attestation_rejects_non_v6_or_inexact_generation_shape(
    mutation: Callable[[dict[str, object]], object],
    expected: str,
) -> None:
    """`match=`가 없으면 다른 guard가 대신 잡아 주어 해당 guard를 지워도 green이 된다.

    적대 리뷰가 exact-shape·version·schema head 세 guard를 각각 제거해도 스위트가
    통과함을 실측했다(2026-08-20). 사유 문자열까지 고정한다.
    """

    attestation, manifest, journal, environ, run_command = _runtime_fixture()
    mutation(manifest)
    attestation["pinned_runtime_manifest_sha256"] = _sha256_bytes(
        _canonical_json(manifest)
    )

    with pytest.raises(ATTESTATION.AttestationError, match=expected):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


@pytest.mark.parametrize("version", [3, 5, "4", None])
def test_runtime_attestation_rejects_non_v4_attestation_version(version: object) -> None:
    attestation, manifest, journal, environ, run_command = _runtime_fixture()
    if version is None:
        attestation.pop("version")
    else:
        attestation["version"] = version

    with pytest.raises(ATTESTATION.AttestationError, match="attestation shape"):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


def test_runtime_attestation_rejects_journal_from_another_rebuild_transaction() -> None:
    """journal의 transaction_id가 attestation과 결박되지 않으면 순수 장식이 된다."""

    attestation, manifest, journal, environ, run_command = _runtime_fixture()
    attestation["rebuild_transaction_id"] = "00000000-0000-0000-0000-000000000000"

    with pytest.raises(
        ATTESTATION.AttestationError, match="not bound to this rebuild transaction"
    ):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.update({"version": 7}), "journal shape"),
        (lambda value: value.pop("cancel_probe"), "journal shape"),
        (lambda value: value.update({"phase": "manifest_committing"}), "journal is not committed"),
        (lambda value: value.update({"transaction_id": "not-a-uuid"}), "journal transaction"),
        (lambda value: value.update({"environment_sha256": "short"}), "journal input digest"),
        (lambda value: value.update({"journal_generation": 26}), "journal generation"),
        (
            lambda value: value["map_application_300_candidate_evidence"].update(
                {"api_receipt_sha256": "0" * 64}
            ),
            "journal candidate evidence differs",
        ),
        (
            lambda value: value["map_application_300_execution_evidence"].update(
                {"application_database_identity_sha256": "0" * 64}
            ),
            "journal application identity digest",
        ),
        (
            lambda value: value["map_application_300_execution_evidence"][
                "fresh_finalize_operation_plan"
            ].update({"result_sha256": None}),
            "journal finalize operation digest",
        ),
        (
            lambda value: value["map_application_300_execution_evidence"][
                "dagster_metadata_database_identity"
            ]["login_role_attributes"].update({"inherit": True}),
            "journal Dagster metadata role privilege",
        ),
        (lambda value: value["cancel_probe"].update({"stage": "consumed"}), "cancel probe"),
        (
            lambda value: value["cancel_probe"].update({"unexpected": True}),
            "journal cancel probe shape",
        ),
        (
            lambda value: value["cancel_probe"].pop("fixture_consumed_at"),
            "journal cancel probe shape",
        ),
        (
            lambda value: value["cancel_probe"]["outcome"].update({"status": 410}),
            "journal cancel probe outcome",
        ),
        (
            lambda value: value["cancel_probe"].update({"job_id": "job-1"}),
            "journal cancel probe identity",
        ),
        (
            lambda value: value["cancel_probe"].update({"cancellation_id": "cancel-1"}),
            "journal cancel probe identity",
        ),
        (
            lambda value: value["cancel_probe"].update(
                {"fixture_finalized_at": "2026-07-19T00:00:02"}
            ),
            "journal cancel probe timestamp",
        ),
        (
            lambda value: value["candidate"].update({"map_ui_image_id": "sha256:" + "f" * 64}),
            "journal candidate is not the active generation",
        ),
    ],
)
def test_runtime_attestation_rejects_journal_that_did_not_commit_this_generation(
    mutation: Callable[[dict[str, object]], object],
    expected: str,
) -> None:
    """journal은 "이 세대가 rebuild를 끝까지 통과했다"는 유일한 증거다.

    manifest만 보면 active generation이 무엇인지는 알아도 그것이 파괴적
    transaction을 완주했는지는 알 수 없다. 그래서 phase·candidate·cancel probe가
    하나라도 어긋나면 통과시키지 않는다.
    """

    attestation, manifest, journal, environ, run_command = _runtime_fixture()
    mutation(journal)
    attestation["rebuild_journal_sha256"] = _sha256_bytes(_canonical_json(journal))

    with pytest.raises(ATTESTATION.AttestationError, match=expected):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


@pytest.mark.parametrize("field", list(ATTESTATION.GENERATION_SCHEMA_HEAD_FIELDS))
def test_runtime_attestation_rejects_each_schema_head_mismatch(field: str) -> None:
    attestation, manifest, journal, environ, run_command = _runtime_fixture()
    schema_heads = attestation["schema_heads"]
    assert isinstance(schema_heads, dict)
    schema_heads[field] = "0000_other_head"

    with pytest.raises(ATTESTATION.AttestationError, match="schema head mismatch"):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


@pytest.mark.parametrize(
    "field", [field for _, field in ATTESTATION.GENERATION_RUNTIME_IMAGE_FIELDS]
)
def test_runtime_attestation_rejects_each_active_runtime_image_mismatch(
    field: str,
) -> None:
    """일곱 image를 **전부** 실측 대조한다.

    v4 pair는 PinVi web/dagster를 담지 않아 그 둘이 세대 밖에서 바뀌어도 통과했다.
    parametrize를 v5 generation의 image field에서 직접 만들어, 세대가 늘어나면
    이 테스트도 자동으로 늘어나게 둔다.
    """

    attestation, manifest, journal, environ, run_command = _runtime_fixture()
    active = manifest["active_generation"]
    assert isinstance(active, dict)
    active[field] = "sha256:" + "f" * 64
    journal["candidate"] = copy.deepcopy(active)
    attestation["pinned_runtime_manifest_sha256"] = _sha256_bytes(
        _canonical_json(manifest)
    )
    attestation["rebuild_journal_sha256"] = _sha256_bytes(_canonical_json(journal))

    with pytest.raises(
        ATTESTATION.AttestationError, match="active generation is not deployed"
    ):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


def test_runtime_attestation_rejects_wrong_oci_revision() -> None:
    attestation, manifest, journal, environ, original_run_command = _runtime_fixture()

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
        _verify_runtime(attestation, manifest, journal, environ, tampered_run_command)


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
    attestation, manifest, journal, environ, original_run_command = _runtime_fixture()
    run_command = _mutate_runtime_environment(
        attestation,
        environ,
        original_run_command,
        "map_api",
        mutation,
    )

    with pytest.raises(ATTESTATION.AttestationError, match="cursor secret runtime shape"):
        _verify_runtime(attestation, manifest, journal, environ, run_command)


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
    attestation, manifest, journal, environ, original_run_command = _runtime_fixture()

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
        _verify_runtime(attestation, manifest, journal, environ, run_command)


def test_runtime_attestation_rejects_duplicate_cursor_secret_name() -> None:
    attestation, manifest, journal, environ, original_run_command = _runtime_fixture()
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
        _verify_runtime(attestation, manifest, journal, environ, run_command)


@pytest.mark.parametrize(
    "role",
    ["map_dagster_daemon", "map_dagster_web", "map_ui", "pinvi_api"],
)
def test_runtime_attestation_rejects_cursor_secret_outside_api(role: str) -> None:
    attestation, manifest, journal, environ, original_run_command = _runtime_fixture()
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
        _verify_runtime(attestation, manifest, journal, environ, run_command)

"""Docker Dagster 운영 형상 회귀 테스트."""

from __future__ import annotations

import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict[str, Any]:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def _command_text(command: object) -> str:
    if isinstance(command, str):
        return command
    if isinstance(command, list):
        return " ".join(str(part) for part in command)
    return ""


def _dockerfile(path: str) -> str:
    return (ROOT / "docker" / path).read_text(encoding="utf-8")


def _script(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _assigned_env_keys(text: str, *, prefix: str) -> set[str]:
    keys: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ")
        if "=" not in line:
            continue
        key = line.split("=", maxsplit=1)[0]
        if key.startswith(prefix):
            keys.add(key)
    return keys


@pytest.mark.unit
def test_docker_compose_uses_persistent_dagster_storage_and_daemon() -> None:
    services = _compose()["services"]

    assert "dagster-db-init" in services
    assert "dagster-daemon" in services

    dagster = services["dagster"]
    daemon = services["dagster-daemon"]

    assert "dagster-webserver" in _command_text(dagster["command"])
    assert "dagster dev" not in _command_text(dagster["command"])
    assert "dagster-daemon run" in _command_text(daemon["command"])
    for service in (dagster, daemon):
        assert service["build"]["dockerfile"] == "docker/dagster.Dockerfile"
        assert "entrypoint" not in service

    assert dagster["environment"]["KOR_TRAVEL_MAP_DAGSTER_PG_URL"]
    assert daemon["environment"]["KOR_TRAVEL_MAP_DAGSTER_PG_URL"]
    assert (
        dagster["environment"][
            "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED"
        ]
        == "true"
    )
    assert (
        daemon["environment"][
            "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED"
        ]
        == "true"
    )
    assert "dagster-db-init" in dagster["depends_on"]
    assert "dagster-db-init" in daemon["depends_on"]


@pytest.mark.unit
def test_bridge_admin_bff_uses_exact_trusted_peer_address() -> None:
    compose = _compose()
    services = compose["services"]

    assert compose["networks"]["admin-control"]["ipam"]["config"] == [
        {"subnet": "172.31.254.0/29"}
    ]
    assert services["api"]["networks"]["admin-control"]["ipv4_address"] == (
        "172.31.254.2"
    )
    assert services["frontend"]["networks"]["admin-control"]["ipv4_address"] == (
        "172.31.254.3"
    )
    assert services["api"]["environment"][
        "KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS"
    ] == '["172.31.254.3/32"]'

    host_compose = _script("docker-compose.host.yml")
    assert host_compose.count("networks: !reset []") == 2
    assert (
        "KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS: "
        "'[\"127.0.0.1/32\",\"::1/128\"]'"
    ) in host_compose


@pytest.mark.unit
def test_root_env_example_has_no_inline_comments_in_assignments() -> None:
    assignments = (
        line
        for line in _script(".env.example").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert all(" #" not in line for line in assignments)


@pytest.mark.unit
def test_docker_compose_has_runtime_healthchecks_and_readiness_order() -> None:
    services = _compose()["services"]

    api = services["api"]
    frontend = services["frontend"]
    dagster = services["dagster"]

    assert "/health" in _command_text(api["healthcheck"]["test"])
    assert "debug/health" not in _command_text(api["healthcheck"]["test"])
    assert "node -e" in _command_text(frontend["healthcheck"]["test"])
    assert "12705" in _command_text(frontend["healthcheck"]["test"])
    assert "KOR_TRAVEL_MAP_DAGSTER_PORT" in _command_text(dagster["healthcheck"]["test"])

    assert frontend["depends_on"]["api"]["condition"] == "service_healthy"


@pytest.mark.unit
def test_docker_compose_isolates_provider_credentials_from_api() -> None:
    services = _compose()["services"]
    shared_provider_keys = {
        "KOR_TRAVEL_MAP_DATA_GO_KR_SERVICE_KEY",
        "KOR_TRAVEL_MAP_OPINET_API_KEY",
        "KOR_TRAVEL_MAP_OPINET_SCOPE_MODE",
        "KOR_TRAVEL_MAP_OPINET_SCOPE_BBOX",
        "KOR_TRAVEL_MAP_OPINET_SCOPE_RADIUS_M",
        "KOR_TRAVEL_MAP_KREX_EX_API_KEY",
        "KOR_TRAVEL_MAP_KREX_GO_API_KEY",
    }
    all_provider_keys = shared_provider_keys | {"KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH"}

    api = services["api"]
    assert api["env_file"] == [
        {
            "path": "packages/kor-travel-map-api/.env",
            "required": True,
            "format": "raw",
        }
    ]
    assert all_provider_keys.isdisjoint(api["environment"])
    assert {
        "KOR_TRAVEL_MAP_OFFLINE_UPLOAD_PREFIX",
        "KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS",
        "KOR_TRAVEL_MAP_FILE_REGISTRY_E2E_BACKUP_TTL_DAYS",
        "KOR_TRAVEL_MAP_FILE_REGISTRY_TEMP_TTL_DAYS",
    } <= set(api["environment"])
    assert {
        key for key in api["environment"] if key.startswith("KOR_TRAVEL_MAP_API_")
    } == {
        "KOR_TRAVEL_MAP_API_HOST",
        "KOR_TRAVEL_MAP_API_PORT",
        "KOR_TRAVEL_MAP_API_DAGSTER_URL",
        "KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS",
        "KOR_TRAVEL_MAP_API_ADMIN_TRUSTED_PROXY_CIDRS",
        # ADR-066 T-VN-01 — production fail-closed 기본값과 hard-require
        # service token은 compose environment가 정본으로 주입한다.
        "KOR_TRAVEL_MAP_API_PROFILE",
        "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
        # ADR-066 결정 4 (T-VN-02) — /metrics scrape identity token도 같은
        # hard-require 패턴이다.
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
    }
    assert "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET" in api["environment"]
    # admin secret과 같은 hard-require 패턴 — host env 누락 시 compose 평가 실패.
    assert "KOR_TRAVEL_MAP_API_SERVICE_TOKEN is required" in str(
        api["environment"]["KOR_TRAVEL_MAP_API_SERVICE_TOKEN"]
    )
    assert "KOR_TRAVEL_MAP_API_METRICS_TOKEN is required" in str(
        api["environment"]["KOR_TRAVEL_MAP_API_METRICS_TOKEN"]
    )

    root_api_keys = _assigned_env_keys(_script(".env.example"), prefix="KOR_TRAVEL_MAP_API_")
    assert root_api_keys == {
        "KOR_TRAVEL_MAP_API_PORT",
        "KOR_TRAVEL_MAP_API_INTERNAL_URL",
        # compose interpolation이 root env에서 읽는 hard-require secret
        # (T-VN-01 service token, T-VN-02 metrics token).
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
    }

    package_api_keys = _assigned_env_keys(
        _script("packages/kor-travel-map-api/.env.example"),
        prefix="KOR_TRAVEL_MAP_API_",
    )
    assert {
        "KOR_TRAVEL_MAP_API_PROFILE",
        "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED",
        "KOR_TRAVEL_MAP_API_CORS_ALLOW_ORIGINS",
        "KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED",
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
        "KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
        "KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED",
        "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED",
    } <= package_api_keys
    assert "KOR_TRAVEL_MAP_API_OPS_ACTOR" not in package_api_keys

    ops_keys = {
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED",
        "KOR_TRAVEL_MAP_API_OPS_ACTOR",
    }
    assert ops_keys.isdisjoint(api["environment"])
    assert all(
        all(key not in services[name]["environment"] for key in ops_keys)
        for name in ("frontend", "dagster", "dagster-daemon")
    )
    assert "KOR_TRAVEL_MAP_OPS_TOKEN" not in _script(".env.example")

    load_env_api_keys = _assigned_env_keys(
        _script("scripts/load-env.sh"), prefix="KOR_TRAVEL_MAP_API_"
    )
    assert load_env_api_keys == {
        "KOR_TRAVEL_MAP_API_HOST",
        "KOR_TRAVEL_MAP_API_PORT",
        "KOR_TRAVEL_MAP_API_DAGSTER_URL",
        "KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS",
    }

    for service_name in ("dagster", "dagster-daemon"):
        environment = services[service_name]["environment"]
        assert shared_provider_keys <= set(environment), service_name
        assert services[service_name]["env_file"] == [
            {"path": ".env", "required": False, "format": "raw"}
        ]

    assert "KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH" in services["dagster-daemon"]["environment"]

    frontend_environment = services["frontend"]["environment"]
    assert {
        "KOR_TRAVEL_MAP_API_INTERNAL_URL",
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
        "KOR_TRAVEL_MAP_UI_ADMIN_USERNAME",
        "KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH",
        "KOR_TRAVEL_MAP_UI_SESSION_SECRET",
        "KOR_TRAVEL_MAP_UI_TRUST_PROXY_HEADERS",
        "KOR_TRAVEL_MAP_UI_PUBLIC_ORIGINS",
    } <= set(frontend_environment)

    entrypoint = _script("docker/api-entrypoint.sh")
    for removed_key in (
        "KOR_TRAVEL_MAP_API_KMA_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_KMA_APIHUB_KEY",
        "KOR_TRAVEL_MAP_API_OPINET_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_DATAGOKR_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_VISITKOREA_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_KREX_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_KNPS_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_AIRKOREA_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_KRFOREST_SERVICE_KEY",
        "KOR_TRAVEL_MAP_API_ETL_LIVE_PREVIEW_ENABLED",
    ):
        assert removed_key in entrypoint
    assert "removed provider runtime key must not enter API container" in entrypoint


@pytest.mark.unit
def test_docker_compose_publishes_host_ports_on_localhost_by_default() -> None:
    services = _compose()["services"]
    bind_prefix = "${KOR_TRAVEL_MAP_DOCKER_BIND_HOST:-127.0.0.1}:"

    exposed_services = ["postgres", "rustfs", "api", "frontend", "dagster"]
    for service_name in exposed_services:
        for port_mapping in services[service_name]["ports"]:
            assert port_mapping.startswith(bind_prefix), (service_name, port_mapping)

    assert services["api"]["environment"]["KOR_TRAVEL_MAP_API_HOST"] == "0.0.0.0"


@pytest.mark.unit
def test_dagster_image_config_points_storage_to_postgres() -> None:
    config = yaml.safe_load((ROOT / "docker" / "dagster.yaml").read_text(encoding="utf-8"))

    assert config["telemetry"] == {"enabled": False}
    assert config["storage"]["postgres"]["postgres_url"] == {
        "env": "KOR_TRAVEL_MAP_DAGSTER_PG_URL"
    }
    assert "run_storage" not in config
    assert "event_log_storage" not in config
    assert "schedule_storage" not in config


@pytest.mark.unit
def test_dagster_image_config_recovers_orphaned_runs() -> None:
    config = yaml.safe_load((ROOT / "docker" / "dagster.yaml").read_text(encoding="utf-8"))

    assert config["run_monitoring"] == {
        "enabled": True,
        "start_timeout_seconds": 600,
        "cancel_timeout_seconds": 600,
        "max_runtime_seconds": 21600,
        "max_resume_run_attempts": 0,
        "poll_interval_seconds": 15,
    }


@pytest.mark.unit
def test_dagster_image_config_serializes_provider_pools() -> None:
    config = yaml.safe_load((ROOT / "docker" / "dagster.yaml").read_text(encoding="utf-8"))

    assert config["concurrency"] == {
        "pools": {"default_limit": 1, "granularity": "run"}
    }


@pytest.mark.unit
def test_local_admin_stack_uses_same_dagster_postgres_config_and_daemon() -> None:
    script = _script("scripts/run-admin-stack.sh")

    assert "KOR_TRAVEL_MAP_API_ENV_FILE" in script
    assert "required API env file is missing" in script
    assert "inline comments are not allowed in API env values" in script
    assert "shared admin proxy secret must be configured only in root env" in script
    assert (
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET must be at least 32 characters "
        "without surrounding whitespace"
    ) in script
    assert "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN" in script
    assert "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN" in script
    assert "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED" in script
    assert "KOR_TRAVEL_MAP_API_OPS_ACTOR was removed" in script
    assert "ops read and cancel tokens must be distinct" in script
    assert "ops principal keys are allowed only in the API package env" in script
    assert 'cd "$ROOT_DIR/packages/kor-travel-map-api"' in script
    assert "start_bg api env -i" in script
    assert "start_bg web env -i" in script
    assert "start_bg dagster env -i" in script
    assert "start_bg dagster-daemon env -i" in script
    assert '"${API_SHARED_ENV[@]}"' in script
    assert '"${API_SCOPED_ENV[@]}"' in script
    assert '"${FRONTEND_PROCESS_ENV[@]}"' in script
    assert '"${DAGSTER_PROCESS_ENV[@]}"' in script
    assert "KOR_TRAVEL_MAP_FILE_REGISTRY_*" in script
    assert "KOR_TRAVEL_MAP_MOIS_SOURCE_SYNC_TTL_HOURS" in script
    assert 'KOR_TRAVEL_MAP_API_BACKUP_ROOT="$api_backup_root"' in script
    assert 'KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET="$frontend_proxy_secret"' in script
    assert 'install -m 0644 "$ROOT_DIR/docker/dagster.yaml"' in script
    assert "CREATE DATABASE" in script
    assert "dagster-webserver" in script
    assert "dagster-daemon" in script
    assert "dagster dev" not in script
    assert 'KOR_TRAVEL_MAP_DAGSTER_PG_URL="$KOR_TRAVEL_MAP_DAGSTER_PG_URL"' in script
    assert "start_bg dagster-daemon env" in script
    assert "ensure_bg_alive dagster-daemon" in script

    host_compose = _script("docker-compose.host.yml")
    assert "KOR_TRAVEL_MAP_HOST_API_INTERNAL_URL" in host_compose


@pytest.mark.unit
def test_local_admin_stack_env_validation_rejects_ambiguous_secrets(tmp_path: Path) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )

    process_env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
        "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
        "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
    }

    api_env.write_text(
        "KOR_TRAVEL_MAP_API_BACKUP_ROOT=data/backups\n"
        "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=false\n"
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=\n"
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=\n",
        encoding="utf-8",
    )
    valid = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr
    assert valid.stdout.strip() == "admin stack environment is valid"

    api_env.write_text(
        "KOR_TRAVEL_MAP_API_BACKUP_ROOT=data/backups # ambiguous\n",
        encoding="utf-8",
    )
    inline_comment = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert inline_comment.returncode != 0
    assert "inline comments are not allowed" in inline_comment.stderr

    api_env.write_text(
        "KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET=shared-secret\n",
        encoding="utf-8",
    )
    duplicate_secret_source = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert duplicate_secret_source.returncode != 0
    assert "shared admin proxy secret must be configured only in root env" in (
        duplicate_secret_source.stderr
    )

    api_env.write_text(
        "KOR_TRAVEL_MAP_API_BACKUP_ROOT=data/backups\n",
        encoding="utf-8",
    )
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=' shared-secret '\n",
        encoding="utf-8",
    )
    frontend_whitespace = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert frontend_whitespace.returncode != 0
    assert "must be at least 32 characters without surrounding whitespace" in (
        frontend_whitespace.stderr
    )

    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_OPINET_SERVICE_KEY=stale-secret\n",
        encoding="utf-8",
    )
    removed_provider_key = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert removed_provider_key.returncode != 0
    assert "removed provider runtime key is not allowed" in removed_provider_key.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ops_lines", "expected_error"),
    [
        (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=read-token-00000000000000000000000000000000\n",
            "must be configured together",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=\n",
            "must be configured together",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=\n",
            "must be configured together",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=cancel-token-000000000000000000000000000000\n",
            "must both be empty or both be non-empty",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=short\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=cancel-token-000000000000000000000000000000\n",
            "must be at least 32 characters",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=read token-00000000000000000000000000000000\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=cancel-token-000000000000000000000000000000\n",
            "must contain no whitespace",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=same-token-00000000000000000000000000000000\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=same-token-00000000000000000000000000000000\n",
            "ops read and cancel tokens must be distinct",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=true\n",
            "required but read/cancel tokens are absent",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=true\n"
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=\n",
            "required but read/cancel tokens are empty",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=TRUE\n",
            "must be exactly true or false",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_ACTOR=service:pinvi\n",
            "KOR_TRAVEL_MAP_API_OPS_ACTOR was removed",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=shared-secret-at-least-32-characters\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=cancel-token-000000000000000000000000000000\n",
            "distinct from the admin proxy secret",
        ),
        (
            "KOR_TRAVEL_MAP_API_SERVICE_TOKEN=read-token-00000000000000000000000000000000\n"
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=read-token-00000000000000000000000000000000\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=cancel-token-000000000000000000000000000000\n",
            "distinct from the service token",
        ),
    ],
)
def test_local_admin_stack_rejects_invalid_ops_principal_pair(
    tmp_path: Path,
    ops_lines: str,
    expected_error: str,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(ops_lines, encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
            "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr


@pytest.mark.unit
def test_api_container_rejects_stale_provider_env_even_when_empty() -> None:
    process_env = {
        "PATH": os.environ["PATH"],
        "KOR_TRAVEL_MAP_API_OPINET_SERVICE_KEY": "",
    }
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "removed provider runtime key must not enter API container" in result.stderr


@pytest.mark.unit
def test_api_container_rejects_legacy_root_ops_principal() -> None:
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "KOR_TRAVEL_MAP_OPS_TOKEN": "legacy-secret",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "legacy root ops principal keys" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    "proxy_secret",
    [None, "", " shared-secret", "shared-secret "],
)
def test_api_container_requires_unambiguous_proxy_secret(
    proxy_secret: str | None,
) -> None:
    process_env = {"PATH": os.environ["PATH"]}
    if proxy_secret is not None:
        process_env["KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET"] = proxy_secret
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must be at least 32 characters without surrounding whitespace" in (
        result.stderr
    )


@pytest.mark.unit
def test_api_container_rejects_legacy_duplicate_proxy_secret() -> None:
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": "shared-secret",
            "KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET": "shared-secret",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "legacy API-specific admin proxy secret" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("ops_env", "expected_error"),
    [
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": (
                    "read-token-00000000000000000000000000000000"
                )
            },
            "must be configured together",
        ),
        (
            {"KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": ""},
            "must be configured together",
        ),
        (
            {"KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": ""},
            "must be configured together",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": (
                    "cancel-token-000000000000000000000000000000"
                ),
            },
            "must both be empty or both be non-empty",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "short",
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": (
                    "cancel-token-000000000000000000000000000000"
                ),
            },
            "must be at least 32 characters",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": (
                    "read token-00000000000000000000000000000000"
                ),
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": (
                    "cancel-token-000000000000000000000000000000"
                ),
            },
            "must contain no whitespace",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": (
                    "same-token-00000000000000000000000000000000"
                ),
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": (
                    "same-token-00000000000000000000000000000000"
                ),
            },
            "ops read and cancel tokens must be distinct",
        ),
        (
            {"KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "true"},
            "required but read/cancel tokens are absent",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "true",
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": "",
            },
            "required but read/cancel tokens are empty",
        ),
        (
            {"KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": ""},
            "must be exactly true or false",
        ),
        (
            {"KOR_TRAVEL_MAP_API_OPS_ACTOR": ""},
            "KOR_TRAVEL_MAP_API_OPS_ACTOR was removed",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": (
                    "shared-secret-at-least-32-characters"
                ),
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": (
                    "cancel-token-000000000000000000000000000000"
                ),
            },
            "distinct from the admin proxy secret",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_SERVICE_TOKEN": (
                    "read-token-00000000000000000000000000000000"
                ),
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": (
                    "read-token-00000000000000000000000000000000"
                ),
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": (
                    "cancel-token-000000000000000000000000000000"
                ),
            },
            "distinct from the service token",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_SERVICE_TOKEN": (
                    "shared-secret-at-least-32-characters"
                ),
            },
            "must be distinct from KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
        ),
    ],
)
def test_api_container_rejects_invalid_ops_principal_pair(
    ops_env: dict[str, str],
    expected_error: str,
) -> None:
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
                "shared-secret-at-least-32-characters"
            ),
            **ops_env,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr


def _entrypoint_stub_path(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("alembic", "python"):
        command = bin_dir / name
        command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


@pytest.mark.unit
def test_api_container_allows_two_empty_ops_tokens_when_not_required(
    tmp_path: Path,
) -> None:
    # ADR-066 T-VN-02 (#742): 컨테이너 기본 profile은 production이므로 빈 ops
    # pair opt-out은 local-dev를 명시할 때만 유효하다(production은 아래
    # 전용 테스트에서 migration 전에 거부됨을 검증).
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            "PATH": _entrypoint_stub_path(tmp_path),
            "KOR_TRAVEL_MAP_API_PROFILE": "local-dev",
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
                "shared-secret-at-least-32-characters"
            ),
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "false",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    "ops_env",
    [
        # #742 재현: production + both-explicit-empty pair.
        {
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "false",
        },
        # pair 완전 미설정도 같은 사유로 거부된다.
        {},
    ],
)
def test_api_container_production_refuses_unconfigured_ops_pair_before_migration(
    ops_env: dict[str, str],
) -> None:
    """production + ops surface 활성 + ops pair 미구성 → migration 전에 단일
    일관 에러로 거부한다 (ADR-066 T-VN-02, issue #742).

    PROFILE env를 주지 않는다 — Docker image ENV/compose 기본과 같은 production
    기본을 entrypoint가 따르는지 함께 검증한다. alembic stub이 없으므로
    migration이 실행되면 다른 에러가 나온다 — settings production matrix와
    lockstep인 문구 하나만 나와야 한다.
    """

    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
                "shared-secret-at-least-32-characters"
            ),
            **ops_env,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "production profile is fail-closed (ADR-066): "
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN and KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN "
        "must be configured while the ops surface is enabled"
    ) in result.stderr
    assert "alembic" not in result.stderr


@pytest.mark.unit
def test_api_container_production_allows_empty_ops_pair_when_ops_surface_off(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            "PATH": _entrypoint_stub_path(tmp_path),
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
                "shared-secret-at-least-32-characters"
            ),
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "false",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_api_container_production_ops_surface_follows_features_flag(
    tmp_path: Path,
) -> None:
    # settings의 resolved_ops_routes_enabled와 같은 해석: OPS flag 미설정이면
    # FEATURES flag를 따른다 — features off면 ops pair 없이도 기동한다.
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            "PATH": _entrypoint_stub_path(tmp_path),
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
                "shared-secret-at-least-32-characters"
            ),
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED": "false",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("env_updates", "expected_error"),
    [
        (
            {"KOR_TRAVEL_MAP_API_PROFILE": "prod"},
            "KOR_TRAVEL_MAP_API_PROFILE must be exactly production or local-dev",
        ),
        (
            {"KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "TRUE"},
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED must be exactly true or false",
        ),
        (
            {"KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED": "1"},
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED must be exactly true or false",
        ),
    ],
)
def test_api_container_rejects_ambiguous_profile_or_surface_flags(
    env_updates: dict[str, str],
    expected_error: str,
) -> None:
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
                "shared-secret-at-least-32-characters"
            ),
            **env_updates,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr


@pytest.mark.unit
def test_ops_pair_validation_messages_are_lockstep_across_layers() -> None:
    """settings production matrix(정본)와 entrypoint 검사 메시지 lockstep (#742).

    같은 실패를 두 계층이 다른 문구로 설명하면 운영자가 두 번 헤맨다 —
    공유 문구가 양쪽 소스에 그대로 존재해야 한다.
    """

    entrypoint = _script("docker/api-entrypoint.sh")
    settings_source = (
        ROOT
        / "packages"
        / "kor-travel-map-api"
        / "src"
        / "kortravelmap"
        / "api"
        / "settings.py"
    ).read_text(encoding="utf-8")

    for shared_phrase in (
        "must be configured together",
        "must both be empty or both be non-empty",
        "ops read and cancel tokens must be distinct",
        "must be configured while ",
        "the ops surface is enabled",
        "production profile is fail-closed (ADR-066)",
    ):
        assert shared_phrase in entrypoint, shared_phrase
        assert shared_phrase in settings_source, shared_phrase
    # 제거된 문구가 한쪽에만 되살아나는 회귀 방지 — 옛 provenance 문구.
    assert "absent or configured together" not in entrypoint
    assert "absent or configured together" not in settings_source


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    [
        "KOR_TRAVEL_MAP_OPS_TOKEN",
        "KOR_TRAVEL_MAP_OPS_ACTOR",
        "KOR_TRAVEL_MAP_OPS_FUTURE_KEY",
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED",
        "KOR_TRAVEL_MAP_API_OPS_ACTOR",
        "KOR_TRAVEL_MAP_API_OPS_FUTURE_KEY",
    ],
)
def test_dagster_entrypoint_rejects_any_root_or_api_ops_key_even_when_empty(
    key: str,
) -> None:
    result = subprocess.run(
        ["sh", "docker/dagster-entrypoint.sh", "sh", "-c", "exit 0"],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"], key: ""},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"API-only ops principal key must not enter Dagster process: {key}" in (
        result.stderr
    )


@pytest.mark.unit
def test_dagster_entrypoint_executes_command_without_api_ops_keys() -> None:
    result = subprocess.run(
        ["sh", "docker/dagster-entrypoint.sh", "sh", "-c", "exit 0"],
        cwd=ROOT,
        env={"PATH": os.environ["PATH"]},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_admin_proxy_secret_minimum_is_enforced_at_runtime_boundaries() -> None:
    api_entrypoint = _script("docker/api-entrypoint.sh")
    admin_launcher = _script("scripts/run-admin-stack.sh")

    for script, length_expression in (
        (api_entrypoint, "${#api_proxy_secret}"),
        (admin_launcher, "${#frontend_proxy_secret}"),
    ):
        assert "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET" in script
        assert "at least 32 characters" in script
        assert length_expression in script


@pytest.mark.unit
def test_dagster_package_installs_postgres_storage_plugin() -> None:
    pyproject = tomllib.loads(
        (ROOT / "packages" / "kor-travel-map-dagster" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    dependencies = pyproject["project"]["dependencies"]
    assert any(dep.startswith("dagster-postgres") for dep in dependencies)


@pytest.mark.unit
def test_runtime_docker_images_are_multistage_and_non_root() -> None:
    api = _dockerfile("api.Dockerfile")
    dagster = _dockerfile("dagster.Dockerfile")
    frontend = _dockerfile("frontend.Dockerfile")

    assert "FROM python:3.12-slim AS builder" in api
    assert "FROM python:3.12-slim AS runtime" in api
    assert "USER appuser" in api
    assert "-e ." not in api

    assert "FROM python:3.12-slim AS builder" in dagster
    assert "FROM python:3.12-slim AS runtime" in dagster
    assert "USER appuser" in dagster
    assert 'ENTRYPOINT ["dagster-entrypoint.sh"]' in dagster
    assert "-e ." not in dagster

    assert "FROM node:22-bookworm-slim AS deps" in frontend
    assert "FROM node:22-bookworm-slim AS builder" in frontend
    assert "FROM node:22-bookworm-slim AS runner" in frontend
    assert "COPY --from=deps /app/package.json ./package.json" in frontend
    assert "USER nextjs" in frontend


@pytest.mark.unit
def test_frontend_docker_image_uses_next_standalone_server() -> None:
    dockerfile = _dockerfile("frontend.Dockerfile")
    next_config = (
        ROOT / "packages" / "kor-travel-map-admin" / "frontend" / "next.config.ts"
    ).read_text(encoding="utf-8")

    assert 'output: "standalone"' in next_config
    assert "outputFileTracingRoot: workspaceRoot" in next_config
    assert ".next/standalone" in dockerfile
    assert 'CMD ["node", "packages/kor-travel-map-admin/frontend/server.js"]' in dockerfile
    assert "next start" not in dockerfile

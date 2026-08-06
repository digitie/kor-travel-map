"""Docker Dagster 운영 형상 회귀 테스트."""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_CURSOR_SIGNING_SECRET = "cursor-signing-secret-000000000000000000000000"
_OPS_FIXTURE_TOKEN = "fixture-token-00000000000000000000000000000"


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
        # T-VN-H02R — standalone compose도 미설정 시 fail-closed(False)다.
        "KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
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
    assert "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET is required" in str(
        api["environment"]["KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET"]
    )
    assert api["environment"]["KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED"] == (
        "${KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED:-false}"
    )

    root_api_keys = _assigned_env_keys(_script(".env.example"), prefix="KOR_TRAVEL_MAP_API_")
    assert root_api_keys == {
        "KOR_TRAVEL_MAP_API_PORT",
        "KOR_TRAVEL_MAP_API_INTERNAL_URL",
        # compose interpolation이 root env에서 읽는 hard-require secret
        # (T-VN-01 service token, T-VN-02 metrics token, T-VN-15 cursor key).
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN",
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
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
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
        "KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN",
        "KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED",
        "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED",
    } <= package_api_keys
    assert "KOR_TRAVEL_MAP_API_OPS_ACTOR" not in package_api_keys
    assert all(
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET"
        not in services[name]["environment"]
        for name in ("frontend", "dagster", "dagster-daemon")
    )

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
@pytest.mark.parametrize(
    ("explicit_value", "expected"),
    [(None, "false"), ("true", "true")],
)
def test_docker_compose_resolves_destructive_opt_in_exactly(
    tmp_path: Path,
    explicit_value: str | None,
    expected: str,
) -> None:
    """공식 compose의 raw interpolation을 실제 Compose resolver로 검증한다."""

    raw_value = _compose()["services"]["api"]["environment"][
        "KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED"
    ]
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text(
        yaml.safe_dump(
            {
                "services": {
                    "api": {
                        "image": "scratch",
                        "environment": {
                            "KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED": raw_value,
                        },
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ["PATH"],
        "COMPOSE_DISABLE_ENV_FILE": "1",
    }
    if explicit_value is not None:
        env["KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED"] = explicit_value
    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config", "--format", "json"],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    resolved = json.loads(result.stdout)
    assert resolved["services"]["api"]["environment"] == {
        "KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED": expected
    }


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
    assert "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN" in script
    assert "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED" in script
    assert "KOR_TRAVEL_MAP_API_OPS_ACTOR was removed" in script
    assert "ops read, cancel, and fixture tokens must be distinct" in script
    assert "ops principal keys are allowed only in the API package env" in script
    assert "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET" in script
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
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=\n"
        "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN=\n",
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
    ("extra_lines", "expected_error"),
    [
        ("", "must be configured while the public features surface is enabled"),
        (
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=short\n",
            "must be at least 32 characters",
        ),
        (
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET="
            "cursor signing secret value 00000000000000000000\n",
            "must contain no whitespace",
        ),
        (
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=shared-secret-at-least-32-characters\n",
            "must be distinct from admin and service credentials",
        ),
        (
            f"KOR_TRAVEL_MAP_API_SERVICE_TOKEN={_CURSOR_SIGNING_SECRET}\n"
            f"KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET={_CURSOR_SIGNING_SECRET}\n",
            "must be distinct from admin and service credentials",
        ),
        (
            f"KOR_TRAVEL_MAP_API_METRICS_TOKEN={_CURSOR_SIGNING_SECRET}\n"
            f"KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET={_CURSOR_SIGNING_SECRET}\n",
            "must be distinct from the metrics credential",
        ),
        (
            f"KOR_TRAVEL_MAP_API_VWORLD_API_KEY={_CURSOR_SIGNING_SECRET}\n"
            f"KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET={_CURSOR_SIGNING_SECRET}\n",
            "must be distinct from the public API key",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN="
            "read-token-00000000000000000000000000000000\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN="
            "cancel-token-000000000000000000000000000000\n"
            f"KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN={_CURSOR_SIGNING_SECRET}\n"
            f"KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET={_CURSOR_SIGNING_SECRET}\n",
            "must be distinct from ops credentials",
        ),
    ],
)
def test_local_admin_stack_validates_cursor_signing_secret(
    tmp_path: Path,
    extra_lines: str,
    expected_error: str,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n"
        + extra_lines,
        encoding="utf-8",
    )

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
def test_local_admin_stack_accepts_production_cursor_signing_secret(
    tmp_path: Path,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n"
        f"KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET={_CURSOR_SIGNING_SECRET}\n",
        encoding="utf-8",
    )

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

    assert result.returncode == 0, result.stderr


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
                "must all be empty or all be non-empty",
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
                "ops read, cancel, and fixture tokens must be distinct",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=true\n",
            "required but read/cancel/fixture tokens are absent",
        ),
        (
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED=true\n"
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=\n"
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=\n",
            "required but read/cancel/fixture tokens are empty",
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
    if (
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=" in ops_lines
        and "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=" in ops_lines
        and "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN=" not in ops_lines
    ):
        fixture_token = _OPS_FIXTURE_TOKEN
        if (
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN=\n" in ops_lines
            and "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN=\n" in ops_lines
        ):
            fixture_token = ""
        ops_lines += f"KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN={fixture_token}\n"
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
                "must all be empty or all be non-empty",
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
            "ops read, cancel, and fixture tokens must be distinct",
        ),
        (
            {"KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "true"},
            "required but read/cancel/fixture tokens are absent",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "true",
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": "",
            },
            "required but read/cancel/fixture tokens are empty",
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
    if (
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN" in ops_env
        and "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN" in ops_env
        and "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN" not in ops_env
    ):
        fixture_token = _OPS_FIXTURE_TOKEN
        if (
            ops_env["KOR_TRAVEL_MAP_API_OPS_READ_TOKEN"] == ""
            and ops_env["KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN"] == ""
        ):
            fixture_token = ""
        ops_env = {
            **ops_env,
            "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN": fixture_token,
        }
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


_MIGRATION_BASE_ENV: Final = {
    "KOR_TRAVEL_MAP_API_PROFILE": "local-dev",
    "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": "shared-secret-at-least-32-characters",
    "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
    "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": "",
    "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN": "",
    "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "false",
}


def _migration_stub_path(
    tmp_path: Path,
    *,
    image_head: str,
    heads_script: str | None = None,
    current_script: str | None = None,
) -> tuple[str, Path]:
    """`alembic heads`가 ``image_head``를 내고, `upgrade`는 흔적을 남기는 stub.

    흔적 파일이 있으면 **DB를 건드렸다**는 뜻이다. 게이트가 막았는지 여부를 이걸로 판정한다.
    ``heads_script``/``current_script``를 주면 해당 분기를 통째로 바꾼다
    (multi-head·실행 실패·stale-image 재현용).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    marker = tmp_path / "upgrade-ran"
    heads_body = heads_script if heads_script is not None else f"echo '{image_head} (head)'"
    current_body = current_script if current_script is not None else "true"
    alembic = bin_dir / "alembic"
    alembic.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  heads) {heads_body} ;;\n"
        f"  current) {current_body} ;;\n"
        f"  upgrade) echo ran > '{marker}' ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    alembic.chmod(0o755)
    python = bin_dir / "python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    python.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}", marker


def _run_entrypoint(path: str, extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={"PATH": path, **_MIGRATION_BASE_ENV, **extra},
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_api_container_refuses_image_whose_alembic_head_differs(tmp_path: Path) -> None:
    """이미지의 alembic head가 기대값과 다르면 **DB를 건드리기 전에** 죽어야 한다.

    2026-08-03 prod 사고 재현이다. pin은 목표 revision을 가리켰는데 실제로는 chain이
    `0072`까지만 담긴 옛 이미지가 배포됐고, entrypoint가 조건 없이 `alembic upgrade head`를
    돌려 prod를 `0063` -> `0072`로 올린 뒤 **오류 없이** 끝냈다(그 이미지 기준으로는
    head가 맞으니까). `0072`는 공개 큐레이션 링크를 신뢰 불가로 두고 `0073`이 복구하는
    구조라 공개 표면이 0건이 됐다.

    핵심은 종료 코드가 아니라 **upgrade가 실행되지 않았다는 것**이다. 실행됐다면 이미
    중간 상태가 만들어졌고, 그 지점에는 되돌릴 길이 없다.
    """
    path, marker = _migration_stub_path(tmp_path, image_head="0072_curation_provenance")
    result = _run_entrypoint(
        path,
        {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": "0078_cache_target_gc_observe"},
    )

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), (
        "head가 어긋나는데 alembic upgrade가 실행됐다 — DB가 이미 중간 상태로 갔다."
    )
    assert "0072_curation_provenance" in result.stderr
    assert "0078_cache_target_gc_observe" in result.stderr


@pytest.mark.unit
def test_api_container_migrates_when_alembic_head_matches(tmp_path: Path) -> None:
    """기대값과 같으면 평소대로 migration을 돌린다 — 게이트가 정상 배포를 막으면 안 된다."""
    path, marker = _migration_stub_path(
        tmp_path, image_head="0078_cache_target_gc_observe"
    )
    result = _run_entrypoint(
        path,
        {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": "0078_cache_target_gc_observe"},
    )

    assert result.returncode == 0, result.stderr
    assert marker.exists(), "head가 일치하는데 migration이 실행되지 않았다."


@pytest.mark.unit
@pytest.mark.parametrize("mode_value", ["none", "auto", "off", ""])
def test_api_container_rejects_removed_migration_mode_env(
    tmp_path: Path, mode_value: str
) -> None:
    """`KOR_TRAVEL_MAP_MIGRATION_MODE`는 제거됐다 — 어떤 값이든 거부한다.

    `MODE=none`(orchestrator 소유 migration)은 명분이던 H35 typed helper가 같은 사고
    대응에서 사문화되며 소비자 없는 fail-open 스위치만 남았다(적대 리뷰 F2). 조용히
    무시하면 none을 기대한 배포에서 migration이 몰래 돌게 되므로, 설정 자체를 거부한다.
    """
    path, marker = _migration_stub_path(
        tmp_path, image_head="0078_cache_target_gc_observe"
    )
    result = _run_entrypoint(path, {"KOR_TRAVEL_MAP_MIGRATION_MODE": mode_value})

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "제거된 MODE env가 설정됐는데 migration이 실행됐다."
    assert "was removed" in result.stderr


@pytest.mark.unit
def test_api_container_rejects_set_but_empty_expected_head(tmp_path: Path) -> None:
    """set-but-empty가 조용히 게이트를 끄면 안 된다 (적대 리뷰 결함 2).

    compose의 `${HOST_VAR:-}` 패턴에서 host env가 누락되면 빈 값이 들어온다. 그때
    EXPECTED_HEAD 검사가 무음으로 사라진다 — pin 전달 실패가 곧 게이트 해제가 된다.
    같은 스크립트의 profile 검사가 세운 set-vs-unset 규약대로 빈 값을 거부한다.
    """
    path, marker = _migration_stub_path(
        tmp_path, image_head="0078_cache_target_gc_observe"
    )
    result = _run_entrypoint(path, {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": ""})

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "EXPECTED_HEAD가 빈 값인데 migration이 실행됐다."


@pytest.mark.unit
def test_api_container_fails_fast_when_db_is_ahead_of_image(tmp_path: Path) -> None:
    """DB revision이 이미지 chain에 없으면 retry 없이 즉시, 이유를 말하며 죽는다 (F3).

    재생성 후 stale `latest-main`(0072) 이미지가 또 배포되면 — 사고의 원인이던 바로 그
    태그 드리프트 — DB(0078)가 이미지보다 앞서 이 경로로 떨어진다. 종전에는 30회×2s
    동안 같은 오류를 반복한 뒤 일시 오류와 같은 종말 메시지로 죽어 원인 판별이 늦었다.
    `alembic current`가 같은 오류를 즉시 내므로 한 번 읽어 먼저 판정한다.
    """
    path, marker = _migration_stub_path(
        tmp_path,
        image_head="0072_curation_provenance",
        current_script=(
            "echo \"FAILED: Can't locate revision identified by "
            "'0078_cache_target_gc_observe'\"; exit 255"
        ),
    )
    result = _run_entrypoint(path, {})

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "stale 이미지인데 upgrade가 실행됐다."
    assert "stale image" in result.stderr
    assert "Can't locate revision" in result.stderr, (
        "실제 alembic 오류 원문이 로그에 없다 — 운영자가 원인을 추적할 수 없다."
    )
    assert "retrying" not in result.stderr, "영구 오류를 retry 루프로 두드렸다."


@pytest.mark.unit
def test_api_container_transient_db_error_still_reaches_retry_loop(
    tmp_path: Path,
) -> None:
    """일시 오류(연결 실패 등)는 종전대로 retry 루프가 처리한다 — fast-fail이 앗아가면 안 된다."""
    path, marker = _migration_stub_path(
        tmp_path,
        image_head="0078_cache_target_gc_observe",
        current_script='echo "connection refused" >&2; exit 1',
    )
    result = _run_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_MIGRATION_RETRIES": "1",
        },
    )

    # upgrade stub은 성공하므로 retry 루프 1회째에 통과해 기동까지 가야 한다.
    assert result.returncode == 0, result.stderr
    assert marker.exists(), "일시 오류 뒤 retry 루프가 upgrade를 실행하지 않았다."


@pytest.mark.unit
def test_api_container_refuses_multi_head_image(tmp_path: Path) -> None:
    """이미지에 alembic head가 둘이면 (분기 병합 누락) 배포를 막는다."""
    path, marker = _migration_stub_path(
        tmp_path,
        image_head="unused",
        heads_script=(
            "printf '%s\\n%s\\n' '0078_cache_target_gc_observe (head)' "
            "'0078_rogue_branch (head)'"
        ),
    )
    result = _run_entrypoint(
        path,
        {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": "0078_cache_target_gc_observe"},
    )

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "head가 둘인데 migration이 실행됐다."
    assert "more than one alembic head" in result.stderr


@pytest.mark.unit
def test_api_container_reports_broken_alembic_as_such_not_as_mismatch(
    tmp_path: Path,
) -> None:
    """alembic 실행 실패를 'revision 불일치'로 오진하면 안 된다 (적대 리뷰 결함 1).

    alembic은 CommandError를 **stdout**에 쓰고 비정상 종료한다 — stderr만 버리고 출력을
    파싱하면 `FAILED:`가 head 값처럼 흘러들어 "revision이 다르게 빌드됐다"는 오진이
    나간다. exit code로 먼저 판정해야 사고 대응이 엉뚱한 곳을 파지 않는다.
    """
    path, marker = _migration_stub_path(
        tmp_path,
        image_head="unused",
        heads_script="echo 'FAILED: No script_location key found'; exit 255",
    )
    result = _run_entrypoint(
        path,
        {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": "0078_cache_target_gc_observe"},
    )

    assert result.returncode != 0, result.stdout
    assert not marker.exists()
    assert "alembic heads failed" in result.stderr, result.stderr
    assert "does not match" not in result.stderr, (
        "alembic 실행 실패가 head 불일치로 오진됐다."
    )
    assert "FAILED: No script_location" in result.stderr, (
        "alembic이 stdout에 남긴 실제 원인이 로그에 없다 (적대 리뷰 F4)."
    )


@pytest.mark.unit
def test_api_container_allows_empty_ops_tokens_when_not_required(
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
            "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN": "",
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
            "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN": "",
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
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN, KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN, "
        "and KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN "
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
            "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "false",
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET": _CURSOR_SIGNING_SECRET,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cursor_secret", "expected_error"),
    [
        (None, "must be configured while the public features surface is enabled"),
        ("short", "must be at least 32 characters"),
        ("cursor signing secret " + "c" * 32, "must contain no whitespace"),
        (
            "shared-secret-at-least-32-characters",
            "must be distinct from admin and service credentials",
        ),
    ],
)
def test_api_container_rejects_invalid_cursor_secret_before_migration(
    cursor_secret: str | None,
    expected_error: str,
) -> None:
    env = {
        "PATH": os.environ["PATH"],
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
            "shared-secret-at-least-32-characters"
        ),
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
    }
    if cursor_secret is not None:
        env["KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET"] = cursor_secret
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert "alembic" not in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("credential_env", "expected_error"),
    [
        (
            {"KOR_TRAVEL_MAP_API_SERVICE_TOKEN": _CURSOR_SIGNING_SECRET},
            "must be distinct from admin and service credentials",
        ),
        (
            {"KOR_TRAVEL_MAP_API_METRICS_TOKEN": _CURSOR_SIGNING_SECRET},
            "must be distinct from the metrics credential",
        ),
        (
            {"KOR_TRAVEL_MAP_API_VWORLD_API_KEY": _CURSOR_SIGNING_SECRET},
            "must be distinct from the public API key",
        ),
        (
            {
                "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": _CURSOR_SIGNING_SECRET,
                "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": (
                    "cancel-token-000000000000000000000000000000"
                ),
                "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN": _OPS_FIXTURE_TOKEN,
            },
            "must be distinct from ops credentials",
        ),
    ],
)
def test_api_container_rejects_cursor_secret_reused_as_credential(
    credential_env: dict[str, str],
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
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET": _CURSOR_SIGNING_SECRET,
            **credential_env,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    assert "alembic" not in result.stderr


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
            # set-but-empty PROFILE은 조용히 production으로 접히지 않고 거부된다
            # (`+x` set-vs-unset — 직접 docker run 경로, T-VN-02 리뷰 S3.4).
            {"KOR_TRAVEL_MAP_API_PROFILE": ""},
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
        "must all be empty or all be non-empty",
        "ops read, cancel, and fixture tokens must be distinct",
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
def test_cursor_signing_secret_messages_are_lockstep_across_runtime_layers() -> None:
    settings_source = (
        ROOT
        / "packages"
        / "kor-travel-map-api"
        / "src"
        / "kortravelmap"
        / "api"
        / "settings.py"
    ).read_text(encoding="utf-8")
    entrypoint = _script("docker/api-entrypoint.sh")
    launcher = _script("scripts/run-admin-stack.sh")

    for shared_phrase in (
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET",
        "must be at least 32 characters",
        "contain no whitespace",
        "must be distinct from",
        "while the public features surface is enabled",
    ):
        assert shared_phrase in settings_source, shared_phrase
        assert shared_phrase in entrypoint, shared_phrase
        assert shared_phrase in launcher, shared_phrase


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    [
        "KOR_TRAVEL_MAP_OPS_TOKEN",
        "KOR_TRAVEL_MAP_OPS_ACTOR",
        "KOR_TRAVEL_MAP_OPS_FUTURE_KEY",
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN",
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


_DAGSTER_IMAGE_HEAD: Final = "0084_c6c_cancel_probe_fixtures"


def _dagster_gate_stub_path(
    tmp_path: Path,
    *,
    image_head: str = _DAGSTER_IMAGE_HEAD,
    heads_script: str | None = None,
    current_script: str | None = None,
    stub_python: bool = True,
) -> tuple[str, Path]:
    """dagster 게이트용 alembic stub — `heads`/`current`만 응답하는 읽기 전용 세대.

    ``upgrade``가 호출되면 흔적 파일을 남긴다. dagster-entrypoint는 migration을
    **절대** 실행하면 안 되므로(소유는 api-entrypoint) 모든 게이트 테스트가
    흔적 부재를 함께 고정한다. ``heads_script``/``current_script``를 주면 해당
    분기를 통째로 바꾼다(불일치·stale·일시 오류 재현용).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    marker = tmp_path / "upgrade-ran"
    heads_body = heads_script if heads_script is not None else f"echo '{image_head} (head)'"
    current_body = (
        current_script if current_script is not None else f"echo '{image_head} (head)'"
    )
    alembic = bin_dir / "alembic"
    alembic.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  heads) {heads_body} ;;\n"
        f"  current) {current_body} ;;\n"
        f"  upgrade) echo ran > '{marker}' ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    alembic.chmod(0o755)
    if stub_python:
        # 게이트 분기 테스트는 ops-key python guard를 통과 고정한다. 성공 경로
        # 1개는 stub_python=False로 **실 python**을 태워 inline snippet 회귀를
        # 잡는다 (리뷰 F3).
        python = bin_dir / "python"
        python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        python.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}", marker


def _run_dagster_entrypoint(
    path: str,
    extra: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "docker/dagster-entrypoint.sh", "sh", "-c", "echo interlock-passed"],
        cwd=ROOT,
        env={"PATH": path, **extra},
        check=False,
        capture_output=True,
        text=True,
        # entrypoint 메시지는 UTF-8이다 — Windows 로컬(cp949 기본)에서도 CI(Linux,
        # UTF-8)와 같은 디코딩으로 판정한다.
        encoding="utf-8",
    )


@pytest.mark.unit
def test_dagster_entrypoint_executes_command_without_api_ops_keys(
    tmp_path: Path,
) -> None:
    # 실 python으로 ops-key guard 성공 경로를 검증한다 (리뷰 F3 — stub이면
    # inline snippet 회귀가 전 컨테이너 기동 거부인데 스위트는 green이 된다).
    path, marker = _dagster_gate_stub_path(tmp_path, stub_python=False)
    result = _run_dagster_entrypoint(path, {})

    assert result.returncode == 0, result.stderr
    assert "interlock-passed" in result.stdout
    assert not marker.exists(), "dagster entrypoint가 migration을 실행했다."


@pytest.mark.unit
def test_dagster_container_execs_when_db_matches_image_head(tmp_path: Path) -> None:
    """DB revision == 이미지 head == EXPECTED_HEAD면 게이트를 통과해 명령을 exec한다."""
    path, marker = _dagster_gate_stub_path(tmp_path)
    result = _run_dagster_entrypoint(
        path,
        {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": _DAGSTER_IMAGE_HEAD},
    )

    assert result.returncode == 0, result.stderr
    assert "interlock-passed" in result.stdout
    assert not marker.exists(), "dagster entrypoint가 migration을 실행했다."


@pytest.mark.unit
def test_dagster_container_refuses_image_head_mismatch_before_db(tmp_path: Path) -> None:
    """EXPECTED_HEAD와 이미지 head가 다르면 **DB 연결 전에** 죽는다 (api와 같은 규약)."""
    db_probe = tmp_path / "current-probed"
    path, marker = _dagster_gate_stub_path(
        tmp_path,
        image_head="0082_derivation_identity_fence",
        current_script=f"echo probed > '{db_probe}'; echo '0082_derivation_identity_fence (head)'",
    )
    result = _run_dagster_entrypoint(
        path,
        {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": _DAGSTER_IMAGE_HEAD},
    )

    assert result.returncode != 0, result.stdout
    assert not marker.exists()
    assert "0082_derivation_identity_fence" in result.stderr
    assert _DAGSTER_IMAGE_HEAD in result.stderr
    assert not db_probe.exists(), "head 불일치인데 DB(alembic current)에 연결했다."


@pytest.mark.unit
def test_dagster_container_rejects_set_but_empty_expected_head(tmp_path: Path) -> None:
    """set-but-empty가 조용히 EXPECTED_HEAD 대조를 끄면 안 된다 — api와 같은 규약."""
    path, marker = _dagster_gate_stub_path(tmp_path)
    result = _run_dagster_entrypoint(
        path, {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": ""}
    )

    assert result.returncode != 0, result.stdout
    assert not marker.exists()
    assert "set but empty" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    "current_script",
    [
        # api가 아직 migration을 돌리지 않아 DB가 한 세대 뒤.
        "echo '0082_derivation_identity_fence'",
        # 빈 DB(alembic_version 부재/비어 있음) — `alembic current`는 아무것도 안 낸다.
        "true",
    ],
)
def test_dagster_container_refuses_when_db_is_behind_image(
    tmp_path: Path,
    current_script: str,
) -> None:
    """DB가 이미지보다 뒤면 즉시(retry 없이) "api를 먼저 배포하라"로 죽는다.

    dagster 이미지를 api보다 먼저 재배포하면 코드(신세대)와 DB(구세대)가 어긋난 채
    조용히 기동하던 공백 — 0083 배포 때 "api 먼저" 순서를 사람이 지켜야 했던 이유 —
    를 기계 인터록으로 만든 것이 이 게이트의 존재 이유다 (ADR-083 유예 NEW-5).
    """
    path, marker = _dagster_gate_stub_path(tmp_path, current_script=current_script)
    result = _run_dagster_entrypoint(path, {})

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "DB가 뒤인데 dagster entrypoint가 migration을 실행했다."
    assert "deploy the api container first" in result.stderr
    assert "retrying" not in result.stderr, "세대 불일치(영구 오류)를 retry로 두드렸다."


@pytest.mark.unit
def test_dagster_container_fails_fast_on_stale_image_when_db_is_ahead(
    tmp_path: Path,
) -> None:
    """DB revision이 이미지 chain 밖(stale 이미지 재배포)이면 retry 없이 즉시 죽는다."""
    path, marker = _dagster_gate_stub_path(
        tmp_path,
        image_head="0082_derivation_identity_fence",
        current_script=(
            "echo \"FAILED: Can't locate revision identified by "
            f"'{_DAGSTER_IMAGE_HEAD}'\"; exit 255"
        ),
    )
    result = _run_dagster_entrypoint(path, {})

    assert result.returncode != 0, result.stdout
    assert not marker.exists()
    assert "stale image" in result.stderr
    assert "Can't locate revision" in result.stderr, (
        "실제 alembic 오류 원문이 로그에 없다 — 운영자가 원인을 추적할 수 없다."
    )
    assert "retrying" not in result.stderr, "영구 오류를 retry 루프로 두드렸다."


@pytest.mark.unit
def test_dagster_container_gates_db_generation_even_without_expected_head(
    tmp_path: Path,
) -> None:
    """EXPECTED_HEAD 미결선이어도 DB↔이미지 head 대조는 그대로 수행한다.

    EXPECTED_HEAD는 배포측(orchestrator)이 결선하는 추가 대조일 뿐이고, DB 세대
    게이트가 인터록의 존재 이유다 — env 부재가 게이트 해제가 되면 안 된다.
    """
    path, marker = _dagster_gate_stub_path(
        tmp_path,
        current_script="echo '0082_derivation_identity_fence'",
    )
    result = _run_dagster_entrypoint(path, {})

    assert result.returncode != 0, result.stdout
    assert not marker.exists()
    assert "deploy the api container first" in result.stderr


@pytest.mark.unit
def test_dagster_container_retries_transient_db_errors_then_execs(
    tmp_path: Path,
) -> None:
    """연결 일시 오류는 retry로 기다린다 — api-entrypoint와 같은 env를 재사용한다."""
    state = tmp_path / "first-attempt-done"
    path, marker = _dagster_gate_stub_path(
        tmp_path,
        current_script=(
            f"if [ ! -f '{state}' ]; then : > '{state}'; "
            "echo 'connection refused' >&2; exit 1; fi; "
            f"echo '{_DAGSTER_IMAGE_HEAD} (head)'"
        ),
    )
    result = _run_dagster_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_MIGRATION_RETRIES": "3",
            "KOR_TRAVEL_MAP_MIGRATION_RETRY_SLEEP_SECONDS": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "interlock-passed" in result.stdout
    assert "retrying (1/3)" in result.stderr
    assert not marker.exists()


@pytest.mark.unit
def test_dagster_container_reports_exhausted_retries_as_gate_failure(
    tmp_path: Path,
) -> None:
    path, marker = _dagster_gate_stub_path(
        tmp_path,
        current_script="echo 'connection refused' >&2; exit 1",
    )
    result = _run_dagster_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_MIGRATION_RETRIES": "2",
            "KOR_TRAVEL_MAP_MIGRATION_RETRY_SLEEP_SECONDS": "0",
        },
    )

    assert result.returncode != 0, result.stdout
    assert not marker.exists()
    assert "alembic current failed after 2 attempts" in result.stderr


@pytest.mark.unit
def test_dagster_container_refuses_multi_head_image(tmp_path: Path) -> None:
    path, marker = _dagster_gate_stub_path(
        tmp_path,
        heads_script=(
            f"printf '%s\\n%s\\n' '{_DAGSTER_IMAGE_HEAD} (head)' '0083_rogue_branch (head)'"
        ),
    )
    result = _run_dagster_entrypoint(path, {})

    assert result.returncode != 0, result.stdout
    assert not marker.exists()
    assert "more than one alembic head" in result.stderr


@pytest.mark.unit
def test_dagster_container_reports_broken_alembic_as_such_not_as_mismatch(
    tmp_path: Path,
) -> None:
    """alembic 실행 실패를 'head 불일치'로 오진하면 안 된다 — api와 같은 규약."""
    path, marker = _dagster_gate_stub_path(
        tmp_path,
        heads_script="echo 'FAILED: No script_location key found'; exit 255",
    )
    result = _run_dagster_entrypoint(
        path,
        {"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": _DAGSTER_IMAGE_HEAD},
    )

    assert result.returncode != 0, result.stdout
    assert not marker.exists()
    assert "alembic heads failed" in result.stderr
    assert "does not match" not in result.stderr


@pytest.mark.unit
def test_dagster_entrypoint_gate_is_read_only() -> None:
    """dagster-entrypoint는 어떤 경로로도 migration을 실행하지 않는다 (소유는 api)."""
    entrypoint = _script("docker/dagster-entrypoint.sh")

    assert "alembic upgrade" not in entrypoint
    assert "alembic heads" in entrypoint
    assert "alembic current" in entrypoint
    # api-entrypoint와 lockstep인 규약 문구 — 같은 실패를 두 계층이 다른 문구로
    # 설명하면 운영자가 두 번 헤맨다.
    api_entrypoint = _script("docker/api-entrypoint.sh")
    for shared_phrase in (
        "is set but empty; refusing to silently disable the head gate",
        "the image has more than one alembic head",
        "the image alembic head does not match the expected head",
        "alembic heads failed; the image alembic configuration is broken",
        "the DB alembic revision is not part of this image's migration chain",
        "a stale image was deployed",
    ):
        assert shared_phrase in entrypoint, shared_phrase
        assert shared_phrase in api_entrypoint, shared_phrase


@pytest.mark.unit
def test_dagster_image_ships_alembic_chain_for_generation_gate() -> None:
    """게이트 전제: dagster 이미지에 alembic 실행 환경이 있어야 한다.

    alembic 패키지는 kortravelmap **runtime** 의존이라 `.[providers]` 설치에
    이미 포함된다 — dev extra로 옮기면 게이트가 이미지에서 침묵 파손되므로
    여기서 고정한다. chain 정의(alembic.ini + alembic/)는 Dockerfile COPY가
    담는다.
    """
    dagster = _dockerfile("dagster.Dockerfile")
    assert "COPY --chown=appuser:appuser alembic.ini ./" in dagster
    assert "COPY --chown=appuser:appuser alembic ./alembic" in dagster

    root_pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = root_pyproject["project"]["dependencies"]
    assert any(dep.startswith("alembic") for dep in dependencies)


@pytest.mark.unit
def test_docker_compose_starts_dagster_only_after_api_is_healthy() -> None:
    """fresh up에서 api migration 완료 전에 dagster 게이트가 걸리지 않도록
    compose가 api healthy(= `alembic upgrade head` 이후 기동)를 기동 조건으로 건다."""
    services = _compose()["services"]

    for service_name in ("dagster", "dagster-daemon"):
        depends_on = services[service_name]["depends_on"]
        assert depends_on["api"]["condition"] == "service_healthy", service_name


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

    node_base = (
        "node:22.23.1-bookworm-slim@sha256:"
        "6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3"
    )
    assert f"FROM {node_base} AS deps" in frontend
    assert f"FROM {node_base} AS builder" in frontend
    assert f"FROM {node_base} AS runner" in frontend
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


@pytest.mark.unit
@pytest.mark.parametrize(
    "overlay",
    [
        "docker-compose.external-infra.yml",
        "docker-compose.external-db.yml",
        "docker-compose.external-object-store.yml",
    ],
)
def test_external_overlays_keep_dagster_api_ordering_guard(
    overlay: str, tmp_path: Path
) -> None:
    """NEW-5 리뷰 F1 — external overlay의 ``depends_on: !override``가 base의
    api(service_healthy) 의존을 지우면 fresh up에서 dagster가 migration과
    경주해 게이트에 걸린다. 실제 Compose resolver의 merged config로 세 모드
    전부에서 보증이 유지됨을 고정한다."""

    # api의 env_file(required, gitignored)은 병합 해석과 무관 — clean checkout
    # (CI)에서도 resolve되도록 테스트 전용 overlay로 비운다.
    reset_overlay = tmp_path / "reset-env-file.yml"
    reset_overlay.write_text(
        "services:\n  api:\n    env_file: !reset []\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ["PATH"],
        "COMPOSE_DISABLE_ENV_FILE": "1",
        # required(:?) 변수는 병합 해석에만 필요한 더미 — 컨테이너를 띄우지 않는다.
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": "resolver-dummy",
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET": "resolver-dummy",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN": "resolver-dummy",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN": "resolver-dummy",
        "KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH": "resolver-dummy",
        "KOR_TRAVEL_MAP_UI_SESSION_SECRET": "resolver-dummy",
    }
    resolved = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "-f",
            str(ROOT / overlay),
            "-f",
            str(reset_overlay),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=True,
        cwd=ROOT,
    )
    services = json.loads(resolved.stdout)["services"]
    for name in ("dagster", "dagster-daemon"):
        depends = services[name].get("depends_on") or {}
        assert depends.get("api", {}).get("condition") == "service_healthy", (
            overlay,
            name,
            depends,
        )


@pytest.mark.unit
def test_dagster_container_rejects_removed_migration_mode_env(tmp_path: Path) -> None:
    """api-entrypoint 규약 lockstep (리뷰 F6) — 제거된 스위치는 조용히 무시하지
    않고 거부한다."""
    path, marker = _dagster_gate_stub_path(tmp_path)
    result = _run_dagster_entrypoint(
        path, {"KOR_TRAVEL_MAP_MIGRATION_MODE": "none"}
    )

    assert result.returncode == 1
    assert "KOR_TRAVEL_MAP_MIGRATION_MODE was removed" in result.stderr
    assert "interlock-passed" not in result.stdout
    assert not marker.exists()


@pytest.mark.unit
def test_dagster_container_rejects_branched_alembic_version_rows(
    tmp_path: Path,
) -> None:
    """DB alembic_version이 다행(branched)이면 behind로 오진하지 않고 전용
    문구로 fail-close한다 (리뷰 F4)."""
    path, marker = _dagster_gate_stub_path(
        tmp_path,
        current_script=(
            f"echo '{_DAGSTER_IMAGE_HEAD} (head)'; echo 'aaaa1111bbbb (head)'"
        ),
    )
    result = _run_dagster_entrypoint(path, {})

    assert result.returncode == 1
    assert "multiple alembic revisions" in result.stderr
    assert "deploy the api container first" not in result.stderr
    assert not marker.exists()

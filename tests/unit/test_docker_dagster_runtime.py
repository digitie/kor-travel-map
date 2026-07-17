"""Docker Dagster 운영 형상 회귀 테스트."""

from __future__ import annotations

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
        key for key in api["environment"] if key.startswith("KOR_TRAVEL_MAP_API_")
    } == {
        "KOR_TRAVEL_MAP_API_HOST",
        "KOR_TRAVEL_MAP_API_PORT",
        "KOR_TRAVEL_MAP_API_DAGSTER_URL",
        "KOR_TRAVEL_MAP_API_DAGSTER_ALLOWED_HOSTS",
    }

    root_api_keys = _assigned_env_keys(_script(".env.example"), prefix="KOR_TRAVEL_MAP_API_")
    assert root_api_keys == {
        "KOR_TRAVEL_MAP_API_PORT",
        "KOR_TRAVEL_MAP_API_INTERNAL_URL",
    }

    package_api_keys = _assigned_env_keys(
        _script("packages/kor-travel-map-api/.env.example"),
        prefix="KOR_TRAVEL_MAP_API_",
    )
    assert {
        "KOR_TRAVEL_MAP_API_ADMIN_PROXY_SECRET",
        "KOR_TRAVEL_MAP_API_PUBLIC_API_KEY_REQUIRED",
        "KOR_TRAVEL_MAP_API_CORS_ALLOW_ORIGINS",
        "KOR_TRAVEL_MAP_API_BACKUP_COMMAND_ENABLED",
        "KOR_TRAVEL_MAP_API_PROMETHEUS_METRICS_ENABLED",
        "KOR_TRAVEL_MAP_API_DESTRUCTIVE_ENABLED",
        "KOR_TRAVEL_MAP_API_DEBUG_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_ADMIN_ROUTES_ENABLED",
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED",
    } <= package_api_keys

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

    assert 'API_ENV_FILE="$ROOT_DIR/packages/kor-travel-map-api/.env"' in script
    assert "required API env file is missing" in script
    assert "API/frontend admin proxy secrets do not match" in script
    assert 'cd "$ROOT_DIR/packages/kor-travel-map-api"' in script
    assert "start_bg api env -i" in script
    assert "start_bg web env -i" in script
    assert "start_bg dagster env -i" in script
    assert "start_bg dagster-daemon env -i" in script
    assert '"${API_SHARED_ENV[@]}"' in script
    assert '"${API_SCOPED_ENV[@]}"' in script
    assert '"${FRONTEND_PROCESS_ENV[@]}"' in script
    assert '"${DAGSTER_PROCESS_ENV[@]}"' in script
    assert 'install -m 0644 "$ROOT_DIR/docker/dagster.yaml"' in script
    assert "CREATE DATABASE" in script
    assert "dagster-webserver" in script
    assert "dagster-daemon" in script
    assert "dagster dev" not in script
    assert 'KOR_TRAVEL_MAP_DAGSTER_PG_URL="$KOR_TRAVEL_MAP_DAGSTER_PG_URL"' in script
    assert "start_bg dagster-daemon env" in script
    assert "ensure_bg_alive dagster-daemon" in script


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

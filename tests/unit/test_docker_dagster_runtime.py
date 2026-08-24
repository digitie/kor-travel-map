"""Docker Dagster 운영 형상 회귀 테스트."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_CURSOR_SIGNING_SECRET = "cursor-signing-secret-000000000000000000000000"
_OPS_FIXTURE_TOKEN = "fixture-token-00000000000000000000000000000"
_MANUAL_FEATURE_CREATE_TOKEN = "manual-feature-create-token-00000000000000000000"
_MANUAL_FEATURE_CREATE_DIGEST = hashlib.sha256(
    _MANUAL_FEATURE_CREATE_TOKEN.encode("utf-8")
).hexdigest()
_SEALED_RUNTIME_PATH = "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
_API_IMAGE_ENV: Final = {
    "PATH": _SEALED_RUNTIME_PATH,
    "PYTHONNOUSERSITE": "1",
}


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

    assert dagster["command"] == [
        "/usr/local/bin/dagster-webserver",
        "-m",
        "kortravelmap.dagster.definitions",
        "-h",
        "0.0.0.0",
        "-p",
        "${KOR_TRAVEL_MAP_DAGSTER_PORT:-12702}",
    ]
    assert "dagster dev" not in _command_text(dagster["command"])
    assert "/usr/local/bin/dagster-daemon run" in _command_text(daemon["command"])
    for service in (dagster, daemon):
        assert service["build"]["dockerfile"] == "docker/dagster.Dockerfile"
        assert "entrypoint" not in service

    assert dagster["environment"]["KOR_TRAVEL_MAP_DAGSTER_PG_URL"]
    assert daemon["environment"]["KOR_TRAVEL_MAP_DAGSTER_PG_URL"]
    assert dagster["environment"]["KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED"] == "true"
    assert daemon["environment"]["KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED"] == "true"
    assert "dagster-db-init" in dagster["depends_on"]
    assert "dagster-db-init" in daemon["depends_on"]
    for service in (dagster, daemon):
        assert "db-role-bootstrap-300" not in service["depends_on"]


@pytest.mark.unit
def test_tvn34_compose_never_derives_runtime_or_metadata_credentials_from_bootstrap(
    tmp_path: Path,
) -> None:
    """ADR-090 principal DSN은 ignored env 입력이며 bootstrap fallback이 아니다."""

    compose = _compose()["services"]
    assert "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN" not in compose["api"]["environment"]
    local_overlay = yaml.safe_load(
        (ROOT / "docker-compose.local-dev.yml").read_text(encoding="utf-8")
    )
    assert local_overlay["services"]["api"]["environment"][
        "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN"
    ].endswith("is required for local-dev}")
    assert compose["api"]["environment"]["KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN"].endswith(
        "is required}"
    )
    for service_name in ("dagster", "dagster-daemon"):
        assert compose[service_name]["environment"]["KOR_TRAVEL_MAP_PG_DSN"].endswith(
            "is required}"
        )
        assert "db-role-bootstrap-300" not in compose[service_name]["depends_on"]

    load_env = _script("scripts/load-env.sh")
    assert "KOR_TRAVEL_MAP_PG_DSN:-postgresql" not in load_env
    assert "KOR_TRAVEL_MAP_PG_DSN_SYNC:-postgresql" not in load_env
    assert "KOR_TRAVEL_MAP_POSTGRES_PASSWORD:-kor_travel_map" not in load_env

    for compose_path in (
        "docker-compose.yml",
        "docker-compose.host.yml",
        "docker-compose.external-db.yml",
        "docker-compose.external-infra.yml",
    ):
        raw = _script(compose_path)
        assert "kor_travel_map:kor_travel_map" not in raw, compose_path
        assert "KOR_TRAVEL_MAP_POSTGRES_PASSWORD:-kor_travel_map" not in raw, compose_path

    bootstrap = _script("docker/postgres-role-bootstrap.sh")
    assert bootstrap.startswith("#!/bin/sh\n")
    assert "PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin" in bootstrap
    assert "until /usr/local/bin/psql" in bootstrap
    assert not any(line.strip().startswith("REASSIGN OWNED") for line in bootstrap.splitlines())
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" not in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ktm_feature_runtime" not in bootstrap
    assert "REVOKE ALL ON SCHEMA feature, provider_sync, ops FROM PUBLIC" in bootstrap

    # T-102 pg_prewarm의 **유일한** 설치 지점이다. migration 0022는 "current_user가
    # superuser일 때만 만든다"로 짜였는데 ADR-090 이후 alembic은 NOSUPERUSER
    # `ktm_feature_migrator`로만 돌아 그 분기가 영구 no-op이 됐다. pg_prewarm은
    # trusted extension이 아니라 schema owner 권한으로도 만들 수 없으므로, 이 dedicated
    # superuser 연결에서 빠지면 확장이 **어디서도** 생기지 않고 prewarm이 조용히
    # no-op으로 남는다. 그 상태로도 게이트가 전부 green이었기 때문에 여기서 못박는다.
    assert "CREATE EXTENSION IF NOT EXISTS pg_prewarm WITH SCHEMA x_extension" in bootstrap
    # 관리형 Postgres에는 contrib이 없을 수 있다. 없을 때 기동을 막지 않도록
    # available 여부를 먼저 본다는 것도 계약의 일부다.
    assert "pg_available_extensions" in bootstrap

    # wrong target confirmation must fail before a network/psql side effect.
    result = subprocess.run(
        ["sh", "docker/postgres-role-bootstrap.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_ENABLED": "true",
            "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN": "postgresql://unused.invalid/ktm",
            "KOR_TRAVEL_MAP_MIGRATOR_PASSWORD": "test-only",
            "KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD": "test-only",
            "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD": "test-only",
            "KOR_TRAVEL_MAP_POSTGRES_DB": "dedicated_map",
            "KOR_TRAVEL_MAP_POSTGRES_USER": "bootstrap",
            "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_CONFIRM_DATABASE": "other_database",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "must equal KOR_TRAVEL_MAP_POSTGRES_DB" in result.stderr
    assert "psql" not in result.stderr


@pytest.mark.unit
def test_resolved_dagster_services_exclude_application_privileged_credentials(
    tmp_path: Path,
) -> None:
    """root deployment env의 bootstrap/migrator 값은 Dagster에 전달되지 않는다."""

    reset_overlay = tmp_path / "reset-api-env-file.yml"
    reset_overlay.write_text(
        "services:\n  api:\n    env_file: !reset []\n",
        encoding="utf-8",
    )
    poison = "privileged-value-must-not-enter-dagster"
    environment = {
        "PATH": os.environ["PATH"],
        "COMPOSE_DISABLE_ENV_FILE": "1",
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": "resolver-dummy",
        "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET": "resolver-dummy",
        "KOR_TRAVEL_MAP_API_METRICS_TOKEN": "resolver-dummy",
        "KOR_TRAVEL_MAP_API_SERVICE_TOKEN": "resolver-dummy",
        "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN": _MANUAL_FEATURE_CREATE_TOKEN,
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256": (
            _MANUAL_FEATURE_CREATE_DIGEST
        ),
        "KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH": "resolver-dummy",
        "KOR_TRAVEL_MAP_UI_SESSION_SECRET": "resolver-dummy",
        "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN": poison,
        "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN": poison,
        "KOR_TRAVEL_MAP_MIGRATOR_PASSWORD": poison,
        "KOR_TRAVEL_MAP_POSTGRES_PASSWORD": poison,
        "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN": (
            "postgresql://api@example.invalid/ktm"
        ),
        "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN": (
            "postgresql://dagster@example.invalid/ktm"
        ),
        "KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL": (
            "postgresql://metadata@example.invalid/ktm_dagster"
        ),
    }
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(ROOT / "docker-compose.yml"),
            "-f",
            str(reset_overlay),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    services = json.loads(result.stdout)["services"]
    privileged_names = {
        "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE",
        "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN",
        "KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD",
        "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN",
        "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD",
        "KOR_TRAVEL_MAP_MIGRATOR_PASSWORD",
        "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN",
        "KOR_TRAVEL_MAP_POSTGRES_DB",
        "KOR_TRAVEL_MAP_POSTGRES_PASSWORD",
        "KOR_TRAVEL_MAP_POSTGRES_USER",
    }
    for service_name in ("dagster", "dagster-daemon", "dagster-storage-migrate"):
        service = services[service_name]
        assert privileged_names.isdisjoint(service.get("environment", {})), service_name
        assert poison not in json.dumps(service, sort_keys=True), service_name


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
        # n150 isolated run은 run-local map.env의 세 principal과 enabled boundary를
        # compose environment에서 API에만 명시 전달한다. 빈 기본값은 external
        # overlay의 profile-disabled API를 compose interpolation에서 막지 않는다.
        "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED",
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256",
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED",
        # T-VN-40C canonical curation은 PinVi 전용 token digest만 Map API에 둔다.
        # 원문 token은 어떤 Map runtime에도 전달하지 않는다.
        "KOR_TRAVEL_MAP_API_PINVI_CURATION_SNAPSHOT_TOKEN_SHA256",
        "KOR_TRAVEL_MAP_API_PINVI_CURATION_CUTOVER_MAPPING_TOKEN_SHA256",
        "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN",
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
    assert api["environment"]["KOR_TRAVEL_MAP_API_OPS_READ_TOKEN"] == (
        "${KOR_TRAVEL_MAP_API_OPS_READ_TOKEN:-}"
    )
    assert api["environment"]["KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN"] == (
        "${KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN:-}"
    )
    assert api["environment"]["KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN"] == (
        "${KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN:-}"
    )
    assert api["environment"]["KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED"] == (
        "${KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED:-false}"
    )
    for name in (
        "KOR_TRAVEL_MAP_API_PINVI_CURATION_SNAPSHOT_TOKEN_SHA256",
        "KOR_TRAVEL_MAP_API_PINVI_CURATION_CUTOVER_MAPPING_TOKEN_SHA256",
    ):
        assert api["environment"][name] == f"${{{name}:-}}"
        assert {
            service_name
            for service_name, service in services.items()
            if name in service.get("environment", {})
        } == {"api"}
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
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256",
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED",
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
        "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN",
        "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED",
        "KOR_TRAVEL_MAP_API_OPS_ACTOR",
    }
    assert ops_keys - {"KOR_TRAVEL_MAP_API_OPS_ACTOR"} <= set(api["environment"])
    assert "KOR_TRAVEL_MAP_API_OPS_ACTOR" not in api["environment"]
    # compose ``environment``는 package env_file을 이긴다. 그래서 이 키들을
    # api service에 둔 이상 **보간 소스는 root .env/host env뿐**이고, 문서가
    # "package env에만 둬라"라고 말하면 운영자가 그대로 따랐을 때 ops principal이
    # 빈 문자열로 꺼지고 OPS_PRINCIPAL_REQUIRED=true가 false로 내려앉는다
    # (headerless BFF 우회 재개방). 문서와 compose가 다시 갈라지지 못하게 묶는다.
    env_example = _script(".env.example")
    for key in sorted(ops_keys - {"KOR_TRAVEL_MAP_API_OPS_ACTOR"}):
        assert api["environment"][key] in (f"${{{key}:-}}", f"${{{key}:-false}}"), (
            f"{key}는 root .env/host env 보간으로만 채워야 한다"
        )
    assert "root .env(또는 host env)에" in env_example, (
        ".env.example이 ops principal 배치 위치를 compose 경계와 다르게 안내한다"
    )
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
        assert "env_file" not in services[service_name]

    assert "KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH" in services["dagster-daemon"]["environment"]

    frontend_environment = services["frontend"]["environment"]
    assert {
        "KOR_TRAVEL_MAP_API_INTERNAL_URL",
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET",
        "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN",
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
def test_tvn_m01_compose_keeps_manual_create_credentials_in_exact_runtimes() -> None:
    services = _compose()["services"]
    raw_name = "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN"
    digest_name = "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256"
    flag_name = "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED"
    credential_names = (raw_name, digest_name, flag_name)

    api_environment = services["api"]["environment"]
    frontend_environment = services["frontend"]["environment"]
    assert digest_name in api_environment
    assert "is required" in api_environment[digest_name]
    assert api_environment[flag_name] == f"${{{flag_name}:-false}}"
    assert raw_name not in api_environment
    assert raw_name in frontend_environment
    assert "is required" in frontend_environment[raw_name]
    assert digest_name not in frontend_environment
    assert flag_name not in frontend_environment

    for service_name, service in services.items():
        if service_name in {"api", "frontend"}:
            continue
        environment = service.get("environment", {})
        assert raw_name not in environment, service_name
        assert digest_name not in environment, service_name
        assert flag_name not in environment, service_name

    root_keys = _assigned_env_keys(_script(".env.example"), prefix="KOR_TRAVEL_MAP_")
    assert {raw_name, digest_name, flag_name}.isdisjoint(root_keys)
    api_keys = _assigned_env_keys(
        _script("packages/kor-travel-map-api/.env.example"),
        prefix="KOR_TRAVEL_MAP_",
    )
    frontend_keys = _assigned_env_keys(
        _script("packages/kor-travel-map-admin/frontend/.env.example"),
        prefix="KOR_TRAVEL_MAP_",
    )
    assert {digest_name, flag_name} <= api_keys
    assert raw_name not in api_keys
    assert raw_name in frontend_keys
    assert digest_name not in frontend_keys
    assert flag_name not in frontend_keys

    for dockerfile in (
        "docker/api.Dockerfile",
        "docker/frontend.Dockerfile",
        "docker/dagster.Dockerfile",
    ):
        text = _script(dockerfile)
        for credential_name in credential_names:
            assert credential_name not in text, dockerfile
    for build_script in (
        "scripts/frontend-build-inputs.mjs",
        "scripts/frontend-source-digest.mjs",
    ):
        text = _script(build_script)
        for credential_name in credential_names:
            assert credential_name not in text, build_script
    for build_script in ("scripts/docker-build.sh", "scripts/docker-buildx.sh"):
        text = _script(build_script)
        for credential_name in credential_names:
            assert f'--build-arg "{credential_name}=' not in text, build_script
            assert f"--secret id={credential_name}" not in text, build_script


@pytest.mark.unit
def test_application_300_compose_requires_explicit_fresh_bootstrap() -> None:
    """fresh bootstrap은 normal startup dependency가 아니어야 한다."""

    services = _compose()["services"]
    bootstrap = services["db-role-bootstrap-300"]
    assert bootstrap["profiles"] == ["fresh-init"]
    assert bootstrap["environment"]["KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_PHASE"] == (
        "baseline-300"
    )
    assert bootstrap["entrypoint"] == [
        "/bin/sh",
        "/usr/local/bin/postgres-role-bootstrap",
    ]
    assert bootstrap["volumes"] == [
        "./docker/postgres-role-bootstrap.sh:/usr/local/bin/postgres-role-bootstrap:ro"
    ]
    fresh_migration = services["db-application-schema-fresh-300"]
    assert fresh_migration["profiles"] == ["fresh-init"]
    assert fresh_migration["depends_on"]["db-role-bootstrap-300"]["condition"] == (
        "service_completed_successfully"
    )
    assert fresh_migration["entrypoint"] == [
        "/usr/local/bin/python",
        "-I",
        "/usr/local/bin/ktm-application-schema-fresh-300",
        "migrate",
    ]
    assert set(fresh_migration["environment"]) == {
        "KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE",
        "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN",
        "KOR_TRAVEL_MAP_PG_DSN",
    }
    assert fresh_migration["environment"][
        "KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE"
    ] == "local-dev"
    for removed_service in (
        "db-role-bootstrap",
        "db-migrate-to-m01-bootstrap-boundary",
        "db-role-bootstrap-m01",
        "db-migrate-to-m05-bootstrap-boundary",
        "db-role-bootstrap-m05-pre",
        "db-migrate-m05",
        "db-role-bootstrap-m05-repair",
    ):
        assert removed_service not in services
    for runtime_name in ("api", "dagster", "dagster-daemon"):
        assert "db-role-bootstrap-300" not in services[runtime_name]["depends_on"]

    phase_script = _script("docker/postgres-role-bootstrap.sh")
    assert "must be exactly baseline-300" in phase_script
    assert "baseline-300 bootstrap requires a fresh DB" in phase_script
    assert "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_PHASE:-baseline-300" in phase_script

    launcher = _script("scripts/docker-up.sh")
    assert "--profile fresh-init run --rm db-application-schema-fresh-300" in launcher
    assert "services=(postgres dagster-db-init db-role-bootstrap-300" not in launcher

    dockerfile = _script("docker/api.Dockerfile")
    assert "transition-application-schema-0236-to-300.py" in dockerfile
    assert "ktm-application-schema-handoff" in dockerfile
    assert "application-schema-fresh-300.py" in dockerfile
    assert "ktm-application-schema-fresh-300" in dockerfile
    assert "application-schema-fresh-finalize.py" in dockerfile
    assert "ktm-application-schema-fresh-finalize" in dockerfile
    assert "application-schema-final-permit.py" in dockerfile
    assert "ktm-application-schema-final-permit" in dockerfile
    for removed_image_path in (
        "migrate-to-m01-bootstrap-boundary.sh",
        "migrate-to-m05-bootstrap-boundary.sh",
        "migrate-m05.sh",
        "pre-squash-revisions.txt",
    ):
        assert removed_image_path not in dockerfile


@pytest.mark.unit
@pytest.mark.parametrize(
    "build_script",
    ["scripts/docker-build.sh", "scripts/docker-buildx.sh"],
)
def test_build_wrappers_remove_manual_create_credentials_before_git_child(
    build_script: str,
) -> None:
    script = _script(build_script)
    guard = script.index("for manual_create_key in")
    unset_boundary = script.index('unset "$manual_create_key"', guard)
    git_boundary = script.index("git ", unset_boundary)

    assert guard < unset_boundary < git_boundary
    if build_script.endswith("docker-build.sh"):
        compose_build = script.index('"${compose[@]}" build')
        placeholder = script.index("manual-feature-create-build-placeholder")
        assert git_boundary < placeholder < compose_build


@pytest.mark.unit
@pytest.mark.parametrize(
    ("build_script", "key"),
    [
        ("scripts/docker-build.sh", "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN"),
        (
            "scripts/docker-buildx.sh",
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256",
        ),
    ],
)
def test_build_wrappers_reject_manual_create_keys_in_root_dotenv(
    tmp_path: Path,
    build_script: str,
    key: str,
) -> None:
    root_env = tmp_path / "root.env"
    sensitive_value = "manual-create-build-boundary-value"
    root_env.write_text(f"{key}={sensitive_value}\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", build_script],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"{key} must not be configured in root env" in result.stderr
    assert sensitive_value not in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("build_script", "credential_name", "credential_value"),
    [
        (
            "scripts/docker-build.sh",
            "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN",
            _MANUAL_FEATURE_CREATE_TOKEN,
        ),
        (
            "scripts/docker-buildx.sh",
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256",
            _MANUAL_FEATURE_CREATE_DIGEST,
        ),
    ],
)
def test_build_wrappers_reject_manual_create_credential_alias(
    tmp_path: Path,
    build_script: str,
    credential_name: str,
    credential_value: str,
) -> None:
    root_env = tmp_path / "root.env"
    root_env.write_text(
        f"GITHUB_TOKEN=build-secret-{credential_value}-suffix\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", build_script],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            credential_name: credential_value,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "manual Feature create credentials must be distinct from exported environment values"
        in result.stderr
    )
    assert credential_value not in result.stdout + result.stderr


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
def test_dagster_image_config_captures_provider_retry_warnings() -> None:
    config = yaml.safe_load((ROOT / "docker" / "dagster.yaml").read_text(encoding="utf-8"))

    assert config["python_logs"] == {
        "managed_python_loggers": ["kortravelmap.dagster.provider_fetchers"],
        "python_log_level": "WARNING",
    }


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
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256="
        f"{_MANUAL_FEATURE_CREATE_DIGEST}\n"
        f"KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET={_CURSOR_SIGNING_SECRET}\n",
        encoding="utf-8",
    )
    frontend_env.write_text(
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n",
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
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
            "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.unit
def test_manual_feature_create_launcher_validates_scoped_credential_parity(
    tmp_path: Path,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256="
        f"{_MANUAL_FEATURE_CREATE_DIGEST}\n",
        encoding="utf-8",
    )
    frontend_env.write_text(
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n",
        encoding="utf-8",
    )
    process_env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
        "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
        "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
        "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
    }

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
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false\n"
        f"KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256={'0' * 64}\n",
        encoding="utf-8",
    )
    mismatch = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert mismatch.returncode != 0
    assert "raw token SHA-256 must match the API digest" in mismatch.stderr
    combined_output = mismatch.stdout + mismatch.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
def test_admin_launcher_unsets_secret_store_manual_create_env_before_children(
    tmp_path: Path,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n",
        encoding="utf-8",
    )
    frontend_env.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
            "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
            "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN": (
                _MANUAL_FEATURE_CREATE_TOKEN
            ),
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256": (
                _MANUAL_FEATURE_CREATE_DIGEST
            ),
            "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED": "false",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "admin stack environment is valid"
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output

    launcher = _script("scripts/run-admin-stack.sh")
    raw_capture = launcher.index(
        'FRONTEND_PROCESS_ENV+=("$name=${!name}")'
    )
    digest_capture = launcher.index(
        'API_SCOPED_ENV+=("$manual_api_key=${!manual_api_key}")'
    )
    unset_boundary = launcher.index(
        "unset \\\n  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN"
    )
    validate_only = launcher.index("KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY")
    preflight_ports = launcher.index('"$ROOT_DIR/scripts/preflight-ports.sh"')
    migration = launcher.index('echo "alembic upgrade head"')
    assert max(raw_capture, digest_capture) < unset_boundary
    assert unset_boundary < min(validate_only, preflight_ports, migration)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("alias_name", "alias_value"),
    [
        (
            "KOR_TRAVEL_MAP_OBJECT_STORE_ACCESS_KEY_ID",
            f"prefix-{_MANUAL_FEATURE_CREATE_TOKEN}-suffix",
        ),
        (
            "KOR_TRAVEL_MAP_OBJECT_STORE_SECRET_ACCESS_KEY",
            f"prefix-{_MANUAL_FEATURE_CREATE_DIGEST}-suffix",
        ),
    ],
)
def test_admin_launcher_rejects_process_only_manual_create_alias(
    tmp_path: Path,
    alias_name: str,
    alias_value: str,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n",
        encoding="utf-8",
    )
    frontend_env.write_text("", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
            "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
            "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN": (
                _MANUAL_FEATURE_CREATE_TOKEN
            ),
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256": (
                _MANUAL_FEATURE_CREATE_DIGEST
            ),
            "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED": "false",
            alias_name: alias_value,
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "manual Feature create credentials must be distinct from exported environment values"
        in result.stderr
    )
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
def test_admin_launcher_rejects_api_scoped_manual_create_alias(
    tmp_path: Path,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256="
        f"{_MANUAL_FEATURE_CREATE_DIGEST}\n"
        "KOR_TRAVEL_MAP_API_BACKUP_ROOT="
        f"prefix-{_MANUAL_FEATURE_CREATE_TOKEN}-suffix\n",
        encoding="utf-8",
    )
    frontend_env.write_text(
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n",
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
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
            "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "manual Feature create credentials are not allowed in api runtime aliases" in (
        result.stderr
    )
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
def test_manual_feature_create_launcher_rejects_root_env_and_ambiguous_flag(
    tmp_path: Path,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n"
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n",
        encoding="utf-8",
    )
    api_env.write_text("", encoding="utf-8")
    frontend_env.write_text("", encoding="utf-8")
    process_env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
        "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
        "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
        "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
    }
    root_leak = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert root_leak.returncode != 0
    assert "must not be configured in root env because Dagster reads that file" in (
        root_leak.stderr
    )
    assert _MANUAL_FEATURE_CREATE_TOKEN not in root_leak.stderr

    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=FALSE\n",
        encoding="utf-8",
    )
    ambiguous_flag = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env=process_env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert ambiguous_flag.returncode != 0
    assert "must be exactly true or false" in ambiguous_flag.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("key", "value"),
    [
        (
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256",
            _MANUAL_FEATURE_CREATE_DIGEST,
        ),
        ("KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED", "false"),
    ],
)
def test_admin_launcher_rejects_api_only_manual_create_key_in_frontend_dotenv(
    tmp_path: Path,
    key: str,
    value: str,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text("", encoding="utf-8")
    frontend_env.write_text(f"{key}={value}\n", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/run-admin-stack.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
            "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert f"API-only key is not allowed in frontend env: {key}" in result.stderr
    assert value not in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("public_assignment", "expected_error"),
    [
        (
            f"NEXT_PUBLIC_REUSED_CREDENTIAL={_MANUAL_FEATURE_CREATE_TOKEN}\n",
            "manual Feature create credential must be distinct from public frontend values",
        ),
        (
            "NEXT_PUBLIC_REUSED_CREDENTIAL="
            "${KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN}\n",
            "public frontend env must not reference the manual Feature create credential",
        ),
    ],
)
def test_admin_launcher_rejects_public_manual_create_credential_alias(
    tmp_path: Path,
    public_assignment: str,
    expected_error: str,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_PROFILE=production\n"
        "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256="
        f"{_MANUAL_FEATURE_CREATE_DIGEST}\n",
        encoding="utf-8",
    )
    frontend_env.write_text(
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n"
        + public_assignment,
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
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
            "KOR_TRAVEL_MAP_ADMIN_STACK_VALIDATE_ONLY": "1",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("dotenv_contents", "expected_error"),
    [
        (
            "   export   KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED "
            " = true # accepted by Next\n",
            "API-only key is not allowed in frontend env",
        ),
        (
            f"PRIVATE_CREATE_VALUE={_MANUAL_FEATURE_CREATE_TOKEN}\n"
            "NEXT_PUBLIC_REUSED_CREDENTIAL=prefix-$PRIVATE_CREATE_VALUE-suffix\n",
            "manual Feature create credentials are not allowed in frontend runtime aliases",
        ),
        (
            f"PRIVATE_CREATE_DIGEST={_MANUAL_FEATURE_CREATE_DIGEST}\n"
            "NEXT_PUBLIC_REUSED_DIGEST=prefix-${PRIVATE_CREATE_DIGEST}-suffix\n",
            "manual Feature create credentials are not allowed in frontend runtime aliases",
        ),
        (
            f"PRIVATE_FRONTEND_ALIAS=prefix-{_MANUAL_FEATURE_CREATE_DIGEST}-suffix\n",
            "manual Feature create credentials are not allowed in frontend runtime aliases",
        ),
    ],
)
def test_frontend_dotenv_validator_uses_next_parser_and_expansion(
    tmp_path: Path,
    dotenv_contents: str,
    expected_error: str,
) -> None:
    (tmp_path / ".env.development.local").write_text(
        dotenv_contents,
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "node",
            "scripts/validate-frontend-manual-create-env.mjs",
            str(tmp_path),
        ],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "NODE_ENV": "development",
        },
        input=(
            f"{_MANUAL_FEATURE_CREATE_TOKEN}\0"
            f"{_MANUAL_FEATURE_CREATE_DIGEST}\0"
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
def test_frontend_dotenv_validator_uses_auto_loaded_raw_for_public_check(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.development.local").write_text(
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n"
        "NEXT_PUBLIC_REUSED_CREDENTIAL="
        "prefix-${KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN}-suffix\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "node",
            "scripts/validate-frontend-manual-create-env.mjs",
            str(tmp_path),
        ],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "NODE_ENV": "development",
        },
        input="\0\0",
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "manual Feature create credentials must be distinct from public frontend values"
        in result.stderr
    )
    assert _MANUAL_FEATURE_CREATE_TOKEN not in result.stdout + result.stderr


@pytest.mark.unit
def test_frontend_dotenv_validator_replays_private_process_env_expansion(
    tmp_path: Path,
) -> None:
    (tmp_path / ".env.development.local").write_text(
        "NEXT_PUBLIC_REUSED_CREDENTIAL=$KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET\n",
        encoding="utf-8",
    )
    private_alias = (
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET="
        "prefix-$KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN-suffix"
    )

    result = subprocess.run(
        [
            "node",
            "scripts/validate-frontend-manual-create-env.mjs",
            str(tmp_path),
        ],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "NODE_ENV": "development",
        },
        input=(
            f"{_MANUAL_FEATURE_CREATE_TOKEN}\0"
            f"{_MANUAL_FEATURE_CREATE_DIGEST}\0"
            f"{private_alias}\0"
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "manual Feature create credentials must be distinct from public frontend values"
        in result.stderr
    )
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
def test_admin_launcher_runs_exact_next_dotenv_validator_before_children() -> None:
    launcher = _script("scripts/run-admin-stack.sh")
    validator = launcher.index("validate-frontend-manual-create-env.mjs")
    credential_unset = launcher.index(
        "unset \\\n  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN"
    )
    preflight = launcher.index('"$ROOT_DIR/scripts/preflight-ports.sh"')

    assert validator < credential_unset < preflight


@pytest.mark.unit
def test_docker_up_rejects_public_manual_create_credential_reuse(
    tmp_path: Path,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false\n"
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256="
        f"{_MANUAL_FEATURE_CREATE_DIGEST}\n",
        encoding="utf-8",
    )
    frontend_env.write_text(
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/docker-up.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
            "NEXT_PUBLIC_REUSED_CREDENTIAL": (
                f"prefix-{_MANUAL_FEATURE_CREATE_TOKEN}-suffix"
            ),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert (
        "manual Feature create credentials must be distinct from public frontend values"
        in result.stderr
    )
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
def test_docker_up_rejects_raw_manual_create_token_in_api_env(
    tmp_path: Path,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text("", encoding="utf-8")
    api_env.write_text(
        "  export  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN "
        f" = {_MANUAL_FEATURE_CREATE_TOKEN}\n",
        encoding="utf-8",
    )
    frontend_env.write_text("", encoding="utf-8")

    result = subprocess.run(
        ["bash", "scripts/docker-up.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "raw manual Feature create token is not allowed in API env" in result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in result.stdout + result.stderr


@pytest.mark.unit
@pytest.mark.parametrize(
    ("leak_target", "expected_error"),
    [
        (
            "root",
            "manual Feature create credentials must be distinct from exported environment values",
        ),
        ("api", "raw manual Feature create token must not appear in API env"),
    ],
)
def test_docker_up_rejects_manual_create_bytes_under_unrelated_env_key(
    tmp_path: Path,
    leak_target: str,
    expected_error: str,
) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_lines = [
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters",
    ]
    api_lines = [
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false",
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256="
        f"{_MANUAL_FEATURE_CREATE_DIGEST}",
    ]
    leak_line = (
        "UNRELATED_RUNTIME_VALUE="
        f"prefix-{_MANUAL_FEATURE_CREATE_TOKEN}-suffix"
    )
    if leak_target == "root":
        root_lines.append(leak_line)
    else:
        api_lines.append(leak_line)
    root_env.write_text("\n".join(root_lines) + "\n", encoding="utf-8")
    api_env.write_text("\n".join(api_lines) + "\n", encoding="utf-8")
    frontend_env.write_text(
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", "scripts/docker-up.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected_error in result.stderr
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
def test_docker_up_rejects_manual_create_mismatch_before_build(tmp_path: Path) -> None:
    root_env = tmp_path / "root.env"
    api_env = tmp_path / "api.env"
    frontend_env = tmp_path / "frontend.env"
    root_env.write_text(
        "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET=shared-secret-at-least-32-characters\n",
        encoding="utf-8",
    )
    api_env.write_text(
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED=false\n"
        f"KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256={'0' * 64}\n",
        encoding="utf-8",
    )
    frontend_env.write_text(
        f"KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN={_MANUAL_FEATURE_CREATE_TOKEN}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["bash", "scripts/docker-up.sh"],
        cwd=ROOT,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "KOR_TRAVEL_MAP_ENV_FILE": str(root_env),
            "KOR_TRAVEL_MAP_API_ENV_FILE": str(api_env),
            "KOR_TRAVEL_MAP_FRONTEND_ENV_FILE": str(frontend_env),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "raw token SHA-256 must match the API digest" in result.stderr
    assert "docker compose" not in result.stdout
    combined_output = result.stdout + result.stderr
    assert _MANUAL_FEATURE_CREATE_TOKEN not in combined_output
    assert _MANUAL_FEATURE_CREATE_DIGEST not in combined_output


@pytest.mark.unit
def test_docker_up_keeps_real_manual_create_credentials_out_of_build_children() -> None:
    launcher = _script("scripts/docker-up.sh")
    capture_boundary = launcher.index(
        'manual_create_raw="$KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN"'
    )
    unset_boundary = launcher.index(
        "unset \\\n  KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN"
    )
    git_boundary = launcher.index('git -C "$ROOT_DIR" rev-parse HEAD')
    preflight_boundary = launcher.index('"$ROOT_DIR/scripts/preflight-ports.sh"')
    build_boundary = launcher.index(
        'KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN='
        'manual-feature-create-build-placeholder'
    )
    runtime_boundary = launcher.index(
        'KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN="$manual_create_raw"',
        build_boundary,
    )
    no_build_boundary = launcher.index('up -d --no-build', runtime_boundary)
    clear_boundary = launcher.index('manual_create_raw=""')
    status_boundary = launcher.index(
        'KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN='
        'manual-feature-create-build-placeholder',
        clear_boundary,
    )

    assert capture_boundary < unset_boundary < git_boundary < preflight_boundary
    assert preflight_boundary < build_boundary < runtime_boundary < no_build_boundary
    assert no_build_boundary < clear_boundary
    assert clear_boundary < status_boundary
    assert "manual-feature-create-build-placeholder" in launcher
    assert "up -d --build" not in launcher


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
@pytest.mark.parametrize("raw_value", ["", _MANUAL_FEATURE_CREATE_TOKEN])
def test_api_container_rejects_manual_create_raw_token_before_migration(
    raw_value: str,
) -> None:
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            **_API_IMAGE_ENV,
            "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN": raw_value,
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "raw manual Feature create token must not enter API container" in (
        result.stderr
    )
    assert raw_value not in result.stderr or raw_value == ""
    assert "alembic" not in result.stderr


@pytest.mark.unit
def test_api_container_requires_manual_create_digest_with_false_production_flag() -> None:
    result = subprocess.run(
        ["sh", "docker/api-entrypoint.sh"],
        cwd=ROOT,
        env={
            **_API_IMAGE_ENV,
            "KOR_TRAVEL_MAP_API_PROFILE": "production",
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
                "shared-secret-at-least-32-characters"
            ),
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED": "false",
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert (
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256 must be configured"
        in result.stderr
    )
    assert "alembic" not in result.stderr


@pytest.mark.unit
def test_api_entrypoint_settings_credential_preflight_precedes_migration() -> None:
    entrypoint = _script("docker/api-entrypoint.sh")
    raw_rejection = entrypoint.index(
        "raw manual Feature create token must not enter API container"
    )
    settings_preflight = entrypoint.index("API runtime settings credential preflight failed")
    credential_unset = entrypoint.index(
        "unset \\\n  KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256"
    )
    migration = entrypoint.index("alembic upgrade head")
    runtime_privileges = entrypoint.index("kortravelmap.infra.runtime_privileges")
    credential_restore = entrypoint.index(
        'export KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256='
    )
    uvicorn = entrypoint.index("kortravelmap.api.app:app")
    assert raw_rejection < settings_preflight < credential_unset < migration
    assert migration < runtime_privileges < credential_restore < uvicorn


@pytest.mark.unit
def test_api_entrypoint_exposes_manual_create_settings_only_to_app_runtime(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    evidence = tmp_path / "child-env.txt"
    recorder = (
        'digest_state=unset\n'
        'digest_value=""\n'
        'flag_state=unset\n'
        'flag_value=""\n'
        'if [ "${KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256+x}" = x ]; then\n'
        '  digest_state=set\n'
        '  digest_value="$KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256"\n'
        'fi\n'
        'if [ "${KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED+x}" = x ]; then\n'
        '  flag_state=set\n'
        '  flag_value="$KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED"\n'
        'fi\n'
        'printf "%s|%s|%s|%s|%s\\n" "$label" "$digest_state" '
        '"$digest_value" "$flag_state" "$flag_value" >>"$EVIDENCE"\n'
    )
    alembic_stub = bin_dir / "alembic"
    alembic_stub.write_text(
        "#!/bin/sh\n"
        'label="alembic-${1:-unknown}"\n'
        f"{recorder}"
        'if [ "${1:-}" = "current" ]; then echo "0224_c7_external_system_scope"; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    python_stub = bin_dir / "python"
    python_stub.write_text(
        "#!/bin/sh\n"
        'if [ "${1:-}" = "-I" ]; then shift; fi\n'
        'if [ "${1:-}" = "-m" ] && [ "${2:-}" = "alembic" ]; then\n'
        "  shift 2\n"
        f"  exec '{alembic_stub}' \"$@\"\n"
        "fi\n"
        'if [ "${1:-}" = "-" ]; then\n'
        "  label=settings-preflight\n"
        "  cat >/dev/null\n"
        'elif [ "${1:-}" = "-m" ] '
        '&& [ "${2:-}" = "kortravelmap.infra.runtime_privileges" ]; then\n'
        "  label=runtime-privileges\n"
        'elif [ "${1:-}" = "-m" ] && [ "${2:-}" = "uvicorn" ]; then\n'
        "  label=uvicorn\n"
        "else\n"
        "  label=python-other\n"
        "fi\n"
        f"{recorder}"
        "exit 0\n",
        encoding="utf-8",
    )
    python_stub.chmod(0o755)
    alembic_stub.chmod(0o755)

    result = _run_entrypoint(
        f"{bin_dir}:{os.environ['PATH']}",
        {
            "EVIDENCE": str(evidence),
            "KOR_TRAVEL_MAP_API_PROFILE": "local-dev",
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": (
                "shared-secret-at-least-32-characters"
            ),
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256": (
                _MANUAL_FEATURE_CREATE_DIGEST
            ),
            "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED": "false",
            "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN": "postgresql://migrator/db",
            "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN": "postgresql://api/db",
        },
    )

    assert result.returncode == 0, result.stderr
    rows = [line.split("|") for line in evidence.read_text(encoding="utf-8").splitlines()]
    by_label = {row[0]: row[1:] for row in rows}
    assert by_label["settings-preflight"] == [
        "set",
        _MANUAL_FEATURE_CREATE_DIGEST,
        "set",
        "false",
    ]
    for label in ("alembic-current", "alembic-upgrade", "runtime-privileges"):
        assert by_label[label] == ["unset", "", "unset", ""]
    assert by_label["uvicorn"] == [
        "set",
        _MANUAL_FEATURE_CREATE_DIGEST,
        "set",
        "false",
    ]


@pytest.mark.unit
def test_api_container_rejects_stale_provider_env_even_when_empty() -> None:
    process_env = {
        **_API_IMAGE_ENV,
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
            **_API_IMAGE_ENV,
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
    process_env = dict(_API_IMAGE_ENV)
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
            **_API_IMAGE_ENV,
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
            **_API_IMAGE_ENV,
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
    for name in ("alembic", "python", "ktm-application-schema-final-permit"):
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
    # Alembic와 API runtime은 같은 DB에도 서로 다른 LOGIN DSN을 반드시 쓴다.
    # Entrypoint unit stub은 접속하지 않으므로 식별자만 있는 dummy를 준다.
    "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN": "postgresql://migrator@example.invalid/ktm",
    "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN": "postgresql://api@example.invalid/ktm",
}


def _migration_stub_path(
    tmp_path: Path,
    *,
    image_head: str,
    heads_script: str | None = None,
    current_script: str | None = None,
    final_permit_script: str = "exit 0",
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
    python.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = -I ] "
        "&& [ \"${2##*/}\" = ktm-application-schema-final-permit ]; then\n"
        "  shift 2\n"
        "  exec \"$(dirname \"$0\")/ktm-application-schema-final-permit\" \"$@\"\n"
        "fi\n"
        "if [ \"${1:-}\" = -I ] && [ \"${2:-}\" = -m ] "
        "&& [ \"${3:-}\" = alembic ]; then\n"
        "  shift 3\n"
        "  exec \"$(dirname \"$0\")/alembic\" \"$@\"\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    final_permit = bin_dir / "ktm-application-schema-final-permit"
    final_permit.write_text(
        f"#!/bin/sh\n{final_permit_script}\n",
        encoding="utf-8",
    )
    final_permit.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}", marker


def _run_entrypoint(path: str, extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    stub_bin = Path(path.split(":", 1)[0])
    entrypoint = stub_bin.parent / "api-entrypoint-under-test.sh"
    source = (ROOT / "docker" / "api-entrypoint.sh").read_text(encoding="utf-8")
    source = source.replace("/usr/local/bin/", f"{stub_bin}/").replace(
        "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
        path,
    )
    entrypoint.write_text(source, encoding="utf-8")
    base_env = dict(_MIGRATION_BASE_ENV)
    if extra.get("KOR_TRAVEL_MAP_API_PROFILE") == "production":
        base_env.pop("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", None)
    return subprocess.run(
        ["sh", str(entrypoint)],
        cwd=ROOT,
        env={
            "PATH": path,
            "PYTHONNOUSERSITE": "1",
            **base_env,
            **extra,
        },
        check=False,
        capture_output=True,
        text=True,
    )


def _image_layout_300_only(tmp_path: Path) -> Path:
    """최종 API image처럼 active root 300만 둔다."""
    image_root = tmp_path / "image"
    (image_root / "docker").mkdir(parents=True)
    (image_root / "alembic" / "versions").mkdir(parents=True)
    (image_root / "docker" / "api-entrypoint.sh").write_bytes(
        (ROOT / "docker" / "api-entrypoint.sh").read_bytes()
    )
    (image_root / "alembic" / "versions" / "300_schema_baseline.py").touch()
    return image_root


def _run_image_layout_entrypoint(
    image_root: Path,
    path: str,
    extra: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    stub_bin = Path(path.split(":", 1)[0])
    entrypoint = stub_bin.parent / "image-api-entrypoint-under-test.sh"
    entrypoint.write_text(
        (image_root / "docker" / "api-entrypoint.sh")
        .read_text(encoding="utf-8")
        .replace("/usr/local/bin/", f"{stub_bin}/"),
        encoding="utf-8",
    )
    return subprocess.run(
        ["sh", str(entrypoint)],
        cwd=image_root,
        env={"PATH": path, **_MIGRATION_BASE_ENV, **extra},
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.unit
def test_api_container_bounds_generic_upgrade_failure_retries(
    tmp_path: Path,
) -> None:
    """active 300 경로 밖의 historic failure 분류를 runtime에 남기지 않는다."""
    head = "0225_tvn40c_physical_removal"
    path, marker = _migration_stub_path(tmp_path, image_head=head)
    alembic = tmp_path / "bin" / "alembic"
    alembic.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  heads) echo '{head} (head)' ;;\n"
        "  current) true ;;\n"
        "  upgrade)\n"
        f"    echo ran >> '{marker}'\n"
        "    echo 'sqlalchemy.exc.InternalError: tvn40 identity mapping: unmapped/ambiguous "
        "legacy rows - detached=1 no_candidate=0 multi_candidate=0 no_evidence=0"
        " item_claimed_twice=0 (legacy_total=4424).' >&2\n"
        "    exit 1 ;;\n"
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
    )
    result = _run_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": head,
            "KOR_TRAVEL_MAP_MIGRATION_RETRIES": "5",
            "KOR_TRAVEL_MAP_MIGRATION_RETRY_SLEEP_SECONDS": "0",
        },
    )
    assert result.returncode != 0
    assert marker.read_text(encoding="utf-8").count("ran") == 5
    assert "retrying (1/5)" in result.stderr, result.stderr
    assert "failed after 5 attempts" in result.stderr
    # 원문 stderr(원인별 count)가 그대로 보인다.
    assert "detached=1" in result.stderr


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
def test_production_api_refuses_failed_final_permit_without_generic_upgrade(
    tmp_path: Path,
) -> None:
    """production DB 상태 판정은 final permit에 맡기고 generic mutation은 하지 않는다."""

    path, marker = _migration_stub_path(
        tmp_path,
        image_head="300",
        current_script="true",
        final_permit_script="exit 1",
    )
    result = _run_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_API_PROFILE": "production",
            "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": "300",
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256": "a" * 64,
        },
    )

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "production blank DB에서 generic upgrade가 실행됐다."
    assert "requires a valid Docker Manager application final permit" in result.stderr


@pytest.mark.unit
def test_production_api_with_final_permit_never_runs_generic_upgrade(tmp_path: Path) -> None:
    """final permit + exact raw 300은 runtime start만 허용하고 upgrade는 하지 않는다."""

    path, marker = _migration_stub_path(
        tmp_path,
        image_head="300",
        current_script="echo '300 (head)'",
    )
    result = _run_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_API_PROFILE": "production",
            "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": "300",
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256": "a" * 64,
        },
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists(), "production final permit 경로에서 generic upgrade가 실행됐다."


@pytest.mark.unit
def test_production_api_rejects_migrator_credential_before_permit(
    tmp_path: Path,
) -> None:
    path, marker = _migration_stub_path(tmp_path, image_head="300")
    result = _run_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_API_PROFILE": "production",
            "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN": (
                "postgresql://migrator@example.invalid/forbidden"
            ),
            "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD": "300",
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256": "a" * 64,
        },
    )

    assert result.returncode != 0
    assert "production API forbids KOR_TRAVEL_MAP_MIGRATOR_PG_DSN" in result.stderr
    assert not marker.exists()


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
def test_api_container_fails_fast_for_unknown_active_graph_revision(tmp_path: Path) -> None:
    """active 300 image 밖 revision은 retry나 archive replay 없이 거부한다."""
    path, marker = _migration_stub_path(
        tmp_path,
        image_head="0104_tvn36_final_fence",
        current_script=(
            "echo \"FAILED: Can't locate revision identified by "
            "'0300_future_generation'\"; exit 255"
        ),
    )
    result = _run_entrypoint(path, {})

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "unsupported revision인데 upgrade가 실행됐다."
    assert "unsupported by the active 300-only image" in result.stderr
    assert "Can't locate revision" in result.stderr, (
        "실제 alembic 오류 원문이 로그에 없다 — 운영자가 원인을 추적할 수 없다."
    )
    assert "retrying" not in result.stderr, "영구 오류를 retry 루프로 두드렸다."


@pytest.mark.unit
def test_api_container_requires_controlled_handoff_for_exact_0236(tmp_path: Path) -> None:
    """exact 0236은 normal startup이 아닌 controlled handoff만 허용한다."""
    path, marker = _migration_stub_path(
        tmp_path,
        image_head="0104_tvn36_final_fence",
        current_script=(
            "echo \"FAILED: Can't locate revision identified by "
            "'0236_tvn41s_compaction_drained'\"; exit 255"
        ),
    )
    result = _run_entrypoint(path, {})

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "controlled handoff 전인데 upgrade가 실행됐다."
    assert "requires the controlled application-schema 0236-to-300 handoff" in result.stderr
    assert "ktm-application-schema-handoff" in result.stderr
    assert "retrying" not in result.stderr, "영구 오류를 retry 루프로 두드렸다."


@pytest.mark.unit
def test_api_image_with_only_300_root_rejects_archived_revision(
    tmp_path: Path,
) -> None:
    """최종 image는 executable archive 없이 unsupported revision을 차단한다."""
    path, marker = _migration_stub_path(
        tmp_path,
        image_head="300",
        current_script=(
            "echo \"FAILED: Can't locate revision identified by "
            "'0078_cache_target_gc_observe'\"; exit 255"
        ),
    )
    image_root = _image_layout_300_only(tmp_path)

    result = _run_image_layout_entrypoint(image_root, path, {})

    assert result.returncode != 0, result.stdout
    assert not marker.exists(), "unsupported revision인데 upgrade가 실행됐다."
    assert "unsupported by the active 300-only image" in result.stderr
    assert not (image_root / "alembic" / "retired_versions").exists()


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
    path = _entrypoint_stub_path(tmp_path)
    result = _run_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_API_PROFILE": "local-dev",
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": ("shared-secret-at-least-32-characters"),
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "false",
        },
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
            **_API_IMAGE_ENV,
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
    path = _entrypoint_stub_path(tmp_path)
    result = _run_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": ("shared-secret-at-least-32-characters"),
            "KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED": "false",
            "KOR_TRAVEL_MAP_API_OPS_READ_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_CANCEL_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN": "",
            "KOR_TRAVEL_MAP_API_OPS_PRINCIPAL_REQUIRED": "false",
            "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET": _CURSOR_SIGNING_SECRET,
        },
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
        **_API_IMAGE_ENV,
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
            **_API_IMAGE_ENV,
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
    path = _entrypoint_stub_path(tmp_path)
    result = _run_entrypoint(
        path,
        {
            "KOR_TRAVEL_MAP_ADMIN_PROXY_SECRET": ("shared-secret-at-least-32-characters"),
            "KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED": "false",
        },
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
            **_API_IMAGE_ENV,
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
    key: str, tmp_path: Path,
) -> None:
    result = _run_dagster_entrypoint(
        tmp_path,
        f"{Path(sys.executable).parent}:{os.environ['PATH']}",
        ["sh", "-c", "exit 0"],
        {key: ""},
    )

    assert result.returncode != 0
    assert f"API-only ops principal key must not enter Dagster process: {key}" in (
        result.stderr
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "key",
    [
        "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN",
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256",
        "KOR_TRAVEL_MAP_API_ADMIN_MANUAL_FEATURE_CREATE_ENABLED",
    ],
)
def test_dagster_entrypoint_rejects_manual_create_keys_even_when_empty(
    key: str, tmp_path: Path,
) -> None:
    result = _run_dagster_entrypoint(
        tmp_path,
        f"{Path(sys.executable).parent}:{os.environ['PATH']}",
        ["sh", "-c", "exit 0"],
        {key: ""},
    )

    assert result.returncode != 0
    assert (
        f"manual Feature create credential key must not enter Dagster process: {key}"
        in result.stderr
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("command", "key"),
    [
        (
            [
                "/usr/local/bin/dagster-webserver",
                "-m",
                "kortravelmap.dagster.definitions",
                "-h",
                "0.0.0.0",
                "-p",
                "12702",
            ],
            "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN",
        ),
        (
            [
                "/usr/local/bin/dagster-daemon",
                "run",
                "-m",
                "kortravelmap.dagster.definitions",
            ],
            "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN",
        ),
        (
            ["/usr/local/bin/ktm-dagster-storage", "migrate"],
            "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_PHASE",
        ),
    ],
)
def test_dagster_entrypoint_rejects_application_privileged_keys_even_when_empty(
    tmp_path: Path,
    command: list[str],
    key: str,
) -> None:
    """webserver·daemon·metadata one-shot에는 application 특권 자격이 없다."""

    path = f"{Path(sys.executable).parent}:{os.environ['PATH']}"
    result = _run_dagster_entrypoint(
        tmp_path,
        path,
        command,
        {
            "KOR_TRAVEL_MAP_DAGSTER_PROFILE": "production",
            key: "",
        },
    )

    assert result.returncode != 0
    assert (
        "application migration/bootstrap credential key must not enter "
        f"Dagster process: {key}"
    ) in result.stderr

    entrypoint = _script("docker/dagster-entrypoint.sh")
    for forbidden_name in (
        "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE",
        "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN",
        "KOR_TRAVEL_MAP_API_RUNTIME_PASSWORD",
        "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN",
        "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PASSWORD",
        "KOR_TRAVEL_MAP_MIGRATOR_PASSWORD",
        "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN",
        "KOR_TRAVEL_MAP_POSTGRES_DB",
        "KOR_TRAVEL_MAP_POSTGRES_PASSWORD",
        "KOR_TRAVEL_MAP_POSTGRES_USER",
        "KOR_TRAVEL_MAP_DB_ROLE_BOOTSTRAP_",
    ):
        assert forbidden_name in entrypoint


@pytest.mark.unit
def test_dagster_entrypoint_executes_command_without_api_ops_keys(
    tmp_path: Path,
) -> None:
    result = _run_dagster_entrypoint(
        tmp_path,
        f"{Path(sys.executable).parent}:{os.environ['PATH']}",
        ["sh", "-c", "echo dagster-started"],
        {"KOR_TRAVEL_MAP_DAGSTER_PROFILE": "local-dev"},
    )

    assert result.returncode == 0, result.stderr
    assert "dagster-started" in result.stdout


def _run_dagster_entrypoint(
    tmp_path: Path,
    path: str,
    command: list[str],
    extra: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """이미지의 고정 executable 경계를 test-only stub directory로 옮긴다."""

    stub_bin = Path(path.split(":", 1)[0])
    entrypoint = tmp_path / "dagster-entrypoint-under-test.sh"
    source = (ROOT / "docker" / "dagster-entrypoint.sh").read_text(encoding="utf-8")
    source = source.replace("/usr/local/bin/", f"{stub_bin}/").replace(
        "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
        path,
    )
    entrypoint.write_text(source, encoding="utf-8")
    resolved_command = [
        part.replace("/usr/local/bin/", f"{stub_bin}/", 1)
        if part.startswith("/usr/local/bin/")
        else part
        for part in command
    ]
    return subprocess.run(
        ["sh", str(entrypoint), *resolved_command],
        cwd=ROOT,
        env={"PATH": path, "PYTHONNOUSERSITE": "1", **extra},
        check=False,
        capture_output=True,
        text=True,
    )


def _dagster_runtime_command_stub_path(tmp_path: Path) -> str:
    """runtime preflight 호출과 exec target을 구분하는 disposable PATH를 만든다."""

    bin_dir = tmp_path / "dagster-runtime-bin"
    bin_dir.mkdir()
    (bin_dir / "python").write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-I\" ]; then\n"
        f"  case \"${{2:-}}\" in '{bin_dir}'/*) exec '{sys.executable}' \"$@\" ;; esac\n"
        "fi\n"
        "if [ \"${1:-}\" = \"-I\" ]; then shift; fi\n"
        "if [ \"${1:-}\" = \"-m\" ] "
        "&& [ \"${2:-}\" = \"kortravelmap.dagster.runtime_preflight\" ]; then\n"
        "  echo runtime-preflight\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = \"-c\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 70\n",
        encoding="utf-8",
    )
    for command in ("dagster-webserver", "dagster-daemon", "ktm-dagster-storage"):
        target = bin_dir / command
        target.write_text(
            f"#!{sys.executable}\nprint('{command}-started')\n",
            encoding="utf-8",
        )
        target.chmod(0o755)
    (bin_dir / "python").chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}"


def _dagster_production_runtime_stub_path(
    tmp_path: Path,
) -> tuple[str, Path, Path]:
    """production permit argv와 실제 runtime DSN을 함께 기록하는 PATH다."""

    bin_dir = tmp_path / "dagster-production-bin"
    bin_dir.mkdir()
    permit_marker = tmp_path / "dagster-final-permit-argv"
    runtime_dsn_marker = tmp_path / "dagster-runtime-dsn"
    final_permit = bin_dir / "ktm-application-schema-final-permit"
    (bin_dir / "python").write_text(
        "#!/bin/sh\n"
        f"if [ \"${{1:-}}\" = \"-I\" ] "
        f"&& [ \"${{2:-}}\" = \"{final_permit}\" ]; then\n"
        "  shift 2\n"
        f"  exec '{final_permit}' \"$@\"\n"
        "fi\n"
        "if [ \"${1:-}\" = \"-I\" ]; then\n"
        f"  case \"${{2:-}}\" in '{bin_dir}'/*) exec '{sys.executable}' \"$@\" ;; esac\n"
        "fi\n"
        "if [ \"${1:-}\" = \"-I\" ]; then shift; fi\n"
        "if [ \"${1:-}\" = \"-m\" ] "
        "&& [ \"${2:-}\" = \"kortravelmap.dagster.runtime_preflight\" ]; then\n"
        "  if [ \"${KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN+x}\" = \"x\" ]; then\n"
        "    echo named-runtime-dsn-leaked >&2\n"
        "    exit 71\n"
        "  fi\n"
        f"  printf '%s' \"$KOR_TRAVEL_MAP_PG_DSN\" > '{runtime_dsn_marker}'\n"
        "  echo runtime-preflight\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"${1:-}\" = \"-c\" ]; then\n"
        "  exit 0\n"
        "fi\n"
        "exit 70\n",
        encoding="utf-8",
    )
    final_permit.write_text(
        "#!/bin/sh\n"
        "if [ \"$#\" -ne 1 ] || [ \"${1:-}\" != \"verify-dagster\" ]; then\n"
        "  echo unexpected-final-permit-argv >&2\n"
        "  exit 72\n"
        "fi\n"
        f"printf '%s\\n' \"$1\" > '{permit_marker}'\n"
        "exit 0\n",
        encoding="utf-8",
    )
    for command in ("dagster-webserver", "dagster-daemon"):
        target = bin_dir / command
        target.write_text(
            f"#!{sys.executable}\nprint('{command}-started')\n",
            encoding="utf-8",
        )
        target.chmod(0o755)
    (bin_dir / "python").chmod(0o755)
    final_permit.chmod(0o755)
    return f"{bin_dir}:{os.environ['PATH']}", permit_marker, runtime_dsn_marker


@pytest.mark.unit
@pytest.mark.parametrize(
    ("command", "requires_preflight"),
    [
        (
            ["dagster-webserver", "-m", "kortravelmap.dagster.definitions"],
            True,
        ),
        (
            ["dagster-daemon", "run", "-m", "kortravelmap.dagster.definitions"],
            True,
        ),
        (
            ["sh", "-c", "dagster-webserver -m kortravelmap.dagster.definitions"],
            True,
        ),
        (["dagster-daemon", "--help"], False),
        (["ktm-dagster-storage", "migrate"], False),
        (["sh", "-c", "echo dagster-webserver"], False),
    ],
)
def test_dagster_entrypoint_preflights_only_actual_runtime_commands(
    tmp_path: Path,
    command: list[str],
    *,
    requires_preflight: bool,
) -> None:
    path = _dagster_runtime_command_stub_path(tmp_path)
    result = _run_dagster_entrypoint(
        tmp_path,
        path,
        command,
        {"KOR_TRAVEL_MAP_DAGSTER_PROFILE": "local-dev"},
    )

    assert result.returncode == 0, result.stderr
    assert ("runtime-preflight" in result.stdout) is requires_preflight


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        [
            "/usr/local/bin/dagster-webserver",
            "-m",
            "kortravelmap.dagster.definitions",
            "-h",
            "0.0.0.0",
            "-p",
            "12702",
        ],
        [
            "/usr/local/bin/dagster-daemon",
            "run",
            "-m",
            "kortravelmap.dagster.definitions",
        ],
    ],
)
def test_dagster_production_rejects_runtime_dsn_split_brain(
    tmp_path: Path,
    command: list[str],
) -> None:
    """permit가 본 DB와 Dagster가 쓰는 DB가 갈라지는 우회를 막는다."""

    verified_dsn = "postgresql://dagster@example.invalid/verified"
    path = _dagster_runtime_command_stub_path(tmp_path)
    result = _run_dagster_entrypoint(
        tmp_path,
        path,
        command,
        {
            "KOR_TRAVEL_MAP_DAGSTER_PROFILE": "production",
            "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN": verified_dsn,
            "KOR_TRAVEL_MAP_PG_DSN": "postgresql://dagster@example.invalid/different",
        },
    )

    assert result.returncode != 0
    assert (
        "KOR_TRAVEL_MAP_PG_DSN must exactly equal "
        "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN in production" in result.stderr
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        [
            "/usr/local/bin/dagster-webserver",
            "-m",
            "kortravelmap.dagster.definitions",
            "-h",
            "0.0.0.0",
            "-p",
            "12702",
        ],
        [
            "/usr/local/bin/dagster-daemon",
            "run",
            "-m",
            "kortravelmap.dagster.definitions",
        ],
    ],
)
def test_dagster_production_uses_verified_runtime_dsn_for_preflight_and_runtime(
    tmp_path: Path,
    command: list[str],
) -> None:
    """같은 DSN으로 verifier와 Dagster runtime을 순서대로 결박한다."""

    path, permit_marker, runtime_dsn_marker = _dagster_production_runtime_stub_path(
        tmp_path
    )
    verified_dsn = "postgresql://dagster@example.invalid/verified"
    result = _run_dagster_entrypoint(
        tmp_path,
        path,
        command,
        {
            "KOR_TRAVEL_MAP_DAGSTER_PROFILE": "production",
            "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN": verified_dsn,
            # 직접 실행/overlay도 compose와 똑같이 맞춘 경우에는 허용한다.
            "KOR_TRAVEL_MAP_PG_DSN": verified_dsn,
        },
    )

    assert result.returncode == 0, result.stderr
    assert permit_marker.read_text(encoding="utf-8") == "verify-dagster\n"
    assert runtime_dsn_marker.read_text(encoding="utf-8") == verified_dsn


@pytest.mark.unit
def test_dagster_entrypoint_does_not_read_map_application_alembic() -> None:
    entrypoint = _script("docker/dagster-entrypoint.sh")

    assert "python -I -m alembic" not in entrypoint
    assert "alembic current" not in entrypoint
    assert "alembic heads" not in entrypoint
    assert "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD" not in entrypoint
    assert "KOR_TRAVEL_MAP_MIGRATION_MODE" not in entrypoint


@pytest.mark.unit
def test_dagster_image_ships_storage_command_without_map_alembic_chain() -> None:
    dagster = _dockerfile("dagster.Dockerfile")

    assert "docker/dagster-storage-migrate.py /usr/local/bin/ktm-dagster-storage" in dagster
    assert "COPY --chown=appuser:appuser alembic.ini ./" not in dagster
    assert "COPY --chown=appuser:appuser alembic ./alembic" not in dagster


@pytest.mark.unit
def test_api_image_ships_static_application_schema_head_command() -> None:
    """candidate image는 head/fresh/permit 전용 executable을 함께 봉인한다."""
    api = _dockerfile("api.Dockerfile")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert (
        "docker/application-schema-head.py /usr/local/bin/ktm-application-schema" in api
    )
    assert "/usr/local/bin/ktm-application-schema" in api
    assert (
        "docker/application-schema-fresh-300.py "
        "/usr/local/bin/ktm-application-schema-fresh-300" in api
    )
    assert (
        "docker/application-schema-final-permit.py "
        "/usr/local/bin/ktm-application-schema-final-permit" in api
    )
    assert (
        "docker/application-schema-contract.py "
        "/usr/local/bin/ktm-application-schema-contract" in api
    )
    assert "_application_migration_graph.json" in pyproject["tool"]["setuptools"][
        "package-data"
    ]["kortravelmap"]


@pytest.mark.unit
def test_docker_compose_runs_storage_migration_before_dagster_services() -> None:
    services = _compose()["services"]
    migration = services["dagster-storage-migrate"]

    assert migration["build"]["dockerfile"] == "docker/dagster.Dockerfile"
    assert migration["command"] == [
        "/usr/local/bin/ktm-dagster-storage",
        "migrate",
    ]
    assert migration["environment"]["DAGSTER_HOME"] == "/opt/dagster/dagster_home"
    assert migration["environment"]["KOR_TRAVEL_MAP_DAGSTER_PG_URL"]
    assert migration["depends_on"]["dagster-db-init"]["condition"] == (
        "service_completed_successfully"
    )

    for service_name in ("dagster", "dagster-daemon"):
        depends_on = services[service_name]["depends_on"]
        assert depends_on["dagster-storage-migrate"]["condition"] == (
            "service_completed_successfully"
        )
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

    assert "FROM python@sha256:" in api
    assert " AS builder" in api
    assert " AS runtime" in api
    assert "USER appuser" in api
    assert _script("docker/api-entrypoint.sh").startswith("#!/bin/sh\n")
    assert "-e ." not in api

    assert "FROM python@sha256:" in dagster
    assert " AS builder" in dagster
    assert " AS runtime" in dagster
    assert "USER appuser" in dagster
    assert _script("docker/dagster-entrypoint.sh").startswith("#!/bin/sh\n")
    assert 'ENTRYPOINT ["/usr/local/bin/dagster-entrypoint.sh"]' in dagster
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
def test_external_overlays_keep_candidate_storage_migration_ordering(
    overlay: str, tmp_path: Path
) -> None:
    """외부 infra에서도 같은 후보 image가 storage migration을 완료한 뒤 기동한다."""

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
        "KOR_TRAVEL_MAP_ADMIN_FEATURE_CREATE_TOKEN": _MANUAL_FEATURE_CREATE_TOKEN,
        "KOR_TRAVEL_MAP_API_ADMIN_FEATURE_CREATE_TOKEN_SHA256": (
            _MANUAL_FEATURE_CREATE_DIGEST
        ),
        "KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH": "resolver-dummy",
        "KOR_TRAVEL_MAP_UI_SESSION_SECRET": "resolver-dummy",
        "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN": "postgresql://migrator@example.invalid/ktm",
        "KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN": "postgresql://api@example.invalid/ktm",
        "KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN": "postgresql://dagster@example.invalid/ktm",
        "KOR_TRAVEL_MAP_EXTERNAL_DOCKER_DAGSTER_PG_URL": (
            "postgresql://metadata@example.invalid/ktm_dagster"
        ),
        "KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL": (
            "postgresql://metadata@example.invalid/ktm_dagster"
        ),
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
    migration = services["dagster-storage-migrate"]
    assert migration["command"] == [
        "/usr/local/bin/ktm-dagster-storage",
        "migrate",
    ]
    assert migration["environment"]["KOR_TRAVEL_MAP_DAGSTER_PG_URL"]
    if overlay in {
        "docker-compose.external-db.yml",
        "docker-compose.external-infra.yml",
    }:
        assert "host.docker.internal=host-gateway" in migration["extra_hosts"]
    for name in ("dagster", "dagster-daemon"):
        depends = services[name].get("depends_on") or {}
        # external DB/infra overlay는 ownership transfer bootstrap을 profile로
        # 비활성화한다. 따라서 runtime은 운영자가 사전 provision한 전용 DB에만
        # 연결하며, profile-disabled service를 readiness edge로 참조하지 않는다.
        assert "db-role-bootstrap-300" not in depends, (overlay, name, depends)
        assert depends.get("dagster-storage-migrate", {}).get("condition") == (
            "service_completed_successfully"
        ), (overlay, name, depends)
        assert depends.get("api", {}).get("condition") == "service_healthy", (
            overlay,
            name,
            depends,
        )


@pytest.mark.unit
def test_tvn_m05_external_db_overlays_do_not_start_local_phase_services() -> None:
    """공유 DB는 같은 phase 절차를 운영자가 별도로 실행한다."""

    for overlay in (
        "docker-compose.external-infra.yml",
        "docker-compose.external-db.yml",
    ):
        text = _script(overlay)
        for service_name in (
            "db-role-bootstrap-300:",
        ):
            assert (
                f'{service_name}\n    profiles: ["local-infra"]' in text
            ), (overlay, service_name)

    object_store = _script("docker-compose.external-object-store.yml")
    assert "db-role-bootstrap-300:" not in object_store

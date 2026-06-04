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

    assert dagster["environment"]["KRTOUR_MAP_DAGSTER_PG_URL"]
    assert daemon["environment"]["KRTOUR_MAP_DAGSTER_PG_URL"]
    assert "dagster-db-init" in dagster["depends_on"]
    assert "dagster-db-init" in daemon["depends_on"]


@pytest.mark.unit
def test_dagster_image_config_points_storage_to_postgres() -> None:
    config = yaml.safe_load((ROOT / "docker" / "dagster.yaml").read_text(encoding="utf-8"))

    assert config["telemetry"] == {"enabled": False}
    assert config["storage"]["postgres"]["postgres_url"] == {
        "env": "KRTOUR_MAP_DAGSTER_PG_URL"
    }


@pytest.mark.unit
def test_dagster_package_installs_postgres_storage_plugin() -> None:
    pyproject = tomllib.loads(
        (ROOT / "packages" / "krtour-map-dagster" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    dependencies = pyproject["project"]["dependencies"]
    assert any(dep.startswith("dagster-postgres") for dep in dependencies)

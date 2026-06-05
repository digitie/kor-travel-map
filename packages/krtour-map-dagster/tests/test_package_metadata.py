"""Dagster 패키지 메타데이터 회귀 테스트."""

from __future__ import annotations

import tomllib
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict[str, object]:
    return tomllib.loads((_PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_runtime_dependencies_include_direct_s3_requirements() -> None:
    project = _pyproject()["project"]
    dependencies = project["dependencies"]

    assert "python-krtour-map" not in dependencies
    assert "python-krtour-map==0.2.0-dev" in dependencies
    assert "boto3>=1.34,<2" in dependencies
    assert "botocore>=1.34,<2" in dependencies


def test_package_pytest_enables_asyncio_auto_mode() -> None:
    tool = _pyproject()["tool"]
    pytest_config = tool["pytest"]["ini_options"]

    assert pytest_config["asyncio_mode"] == "auto"

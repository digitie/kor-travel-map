"""0200 squash 뒤 H35/legacy 실행 코드가 candidate image에서 격리되는지 검증한다."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_candidate_image_excludes_h35_and_legacy_migration_code() -> None:
    dockerfile = (_ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert "ARG KOR_TRAVEL_MAP_GIT_COMMIT=development" in dockerfile
    assert 'LABEL org.opencontainers.image.revision="$KOR_TRAVEL_MAP_GIT_COMMIT"' in dockerfile
    assert "KOR_TRAVEL_MAP_IMAGE_REVISION=\"$KOR_TRAVEL_MAP_GIT_COMMIT\"" in dockerfile
    assert "COPY alembic ./alembic" not in dockerfile
    assert "COPY alembic/legacy_versions" not in dockerfile
    assert "COPY alembic/versions ./alembic/versions" in dockerfile
    assert "rm -f src/kortravelmap/cli/_h35_*.py" in dockerfile
    assert "src/kortravelmap/cli/h35_cutover.py" in dockerfile
    assert "scripts/h35/h35_cutover.py" not in dockerfile
    assert (
        "COPY --chown=appuser:appuser resources/curations ./resources/curations"
        in dockerfile
    )
    assert "USER appuser" in dockerfile


def test_main_wheel_excludes_historical_h35_execution_modules(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            shutil.which("uv") or "uv",
            "build",
            "--wheel",
            "--out-dir",
            str(tmp_path),
            str(_ROOT),
        ],
        cwd=_ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    wheels = tuple(tmp_path.glob("kor_travel_map-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = set(archive.namelist())

    forbidden = {
        "kortravelmap/cli/_h35_cache_target.py",
        "kortravelmap/cli/_h35_catalog.py",
        "kortravelmap/cli/_h35_contract.py",
        "kortravelmap/cli/_h35_csv5.py",
        "kortravelmap/cli/_h35_schema.py",
        "kortravelmap/cli/_h35_schema_version.py",
        "kortravelmap/cli/h35_cutover.py",
    }
    assert names.isdisjoint(forbidden)
    assert "kortravelmap/client/__init__.py" in names


def test_api_and_dagster_builders_use_the_h35_excluding_build_hook() -> None:
    for name in ("api.Dockerfile", "dagster.Dockerfile"):
        dockerfile = (_ROOT / "docker" / name).read_text(encoding="utf-8")
        assert "COPY pyproject.toml setup.py README.md" in dockerfile


def test_helper_image_contract_has_no_host_fixture_copy() -> None:
    dockerfile = (_ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert "*.dump" not in dockerfile
    assert "*.local.md" not in dockerfile
    assert ".env" not in dockerfile
    assert "/home/" not in dockerfile

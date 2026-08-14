"""0200 squash 뒤 H35/legacy 실행 코드가 candidate image에서 격리되는지 검증한다."""

from __future__ import annotations

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


def test_helper_image_contract_has_no_host_fixture_copy() -> None:
    dockerfile = (_ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert "*.dump" not in dockerfile
    assert "*.local.md" not in dockerfile
    assert ".env" not in dockerfile
    assert "/home/" not in dockerfile

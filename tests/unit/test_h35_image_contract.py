"""H35 helper가 candidate API image에 고정되는지 검증한다."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_candidate_image_includes_helper_and_canonical_bundle() -> None:
    dockerfile = (_ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")

    assert "ARG KOR_TRAVEL_MAP_GIT_COMMIT=development" in dockerfile
    assert 'LABEL org.opencontainers.image.revision="$KOR_TRAVEL_MAP_GIT_COMMIT"' in dockerfile
    assert "KOR_TRAVEL_MAP_IMAGE_REVISION=\"$KOR_TRAVEL_MAP_GIT_COMMIT\"" in dockerfile
    assert (
        "COPY --chown=appuser:appuser scripts/h35/h35_cutover.py "
        "./scripts/h35/h35_cutover.py"
    ) in dockerfile
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

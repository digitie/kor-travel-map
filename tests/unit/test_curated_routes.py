"""curated REST 라우터 app mount 단위 테스트."""

from __future__ import annotations

import pytest
from krtour.map_admin.app import create_app

pytestmark = pytest.mark.unit


def test_curated_routes_are_in_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "/v1/curated-themes" in paths
    assert "/v1/curated-sources" in paths
    assert "/v1/curated-features" in paths
    assert "/v1/curated-features/{curated_feature_id}/tripmate-copy" in paths
    assert "/v1/admin/curated-features/{curated_feature_id}/select" in paths
    assert "/v1/admin/curated-source-rules/{rule_id}/apply" in paths

"""``kortravelmap.providers`` re-export 검증 (T-213g) — knps/krheritage 추가."""

from __future__ import annotations

import pytest

from kortravelmap import providers

pytestmark = pytest.mark.unit


def test_providers_reexports_knps_krheritage() -> None:
    expected = {
        # knps
        "knps_point_records_to_bundles",
        "knps_geometry_records_to_bundles",
        "resolve_cultural_resource_category",
        "KNPS_PROVIDER_NAME",
        "KNPS_PLACE_DATASETS",
        "KNPS_GEOMETRY_DATASETS",
        # krheritage
        "heritage_items_to_bundles",
        "heritage_events_to_bundles",
        "classify_heritage_kind",
        "resolve_heritage_category",
        "KRHERITAGE_PROVIDER_NAME",
        "KRHERITAGE_DATASET_KEY_HERITAGE",
        "KRHERITAGE_DATASET_KEY_EVENT",
    }
    for name in expected:
        assert name in providers.__all__, f"{name} not in providers.__all__"
        assert hasattr(providers, name), f"providers.{name} missing"
    assert providers.KNPS_PROVIDER_NAME == "python-knps-api"
    assert providers.KRHERITAGE_PROVIDER_NAME == "python-krheritage-api"

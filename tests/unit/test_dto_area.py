"""``AreaDetail`` (ADR-027 hazard_zone)."""

from __future__ import annotations

import pytest

from krtour.map.dto import AREA_KINDS, AreaDetail


@pytest.mark.unit
def test_area_kinds_includes_hazard_zone() -> None:
    """ADR-027 — area_kind에 'hazard_zone' 포함."""
    assert "hazard_zone" in AREA_KINDS


@pytest.mark.unit
def test_area_kinds_count() -> None:
    """AREA_KINDS 12종 (원본 11 + ADR-027 'hazard_zone')."""
    assert len(AREA_KINDS) == 12


@pytest.mark.unit
def test_area_detail_hazard_zone() -> None:
    """ADR-027 — hazard_zone area + payload domain/hazard_type."""
    detail = AreaDetail(
        feature_id="area:knps_hazard_001",
        area_kind="hazard_zone",
        payload={"domain": "forest", "hazard_type": "rockfall"},
    )
    assert detail.area_kind == "hazard_zone"
    assert detail.payload["hazard_type"] == "rockfall"


@pytest.mark.unit
def test_area_detail_national_park() -> None:
    """기본 area_kind들도 정상 동작."""
    detail = AreaDetail(
        feature_id="area:bukhansan",
        area_kind="national_park",
        boundary_source="knps_park_boundaries",
    )
    assert detail.area_kind == "national_park"


@pytest.mark.unit
def test_area_detail_invalid_kind_raises() -> None:
    """Literal에 없는 area_kind는 ValidationError."""
    with pytest.raises(Exception):
        AreaDetail(feature_id="x", area_kind="not_a_valid_kind")

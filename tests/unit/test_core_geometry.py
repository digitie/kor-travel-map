"""``test_core_geometry`` — WKT 파싱 + centroid + 한국 경계 검증 (ADR-012).

``krtour.map.core.geometry``의 순수 함수 — DB/shapely 외 의존 없음.
"""

from __future__ import annotations

import pytest

from krtour.map.core.geometry import (
    AREA_GEOMETRY_TYPES,
    ROUTE_GEOMETRY_TYPES,
    GeometryError,
    geometry_centroid,
    normalize_geometry,
    parse_wkt,
)
from krtour.map.dto import Coordinate

_LINE = "LINESTRING(127.0 37.5, 127.1 37.6)"
_POLY = "POLYGON((127 37, 127.1 37, 127.1 37.1, 127 37.1, 127 37))"


def test_parse_wkt_linestring() -> None:
    g = parse_wkt(_LINE)
    assert g.geom_type == "LineString"


def test_parse_wkt_invalid_raises() -> None:
    with pytest.raises(GeometryError, match="WKT 파싱 실패"):
        parse_wkt("NOT A WKT")


def test_parse_wkt_empty_raises() -> None:
    with pytest.raises(GeometryError, match="빈 geometry"):
        parse_wkt("LINESTRING EMPTY")


def test_parse_wkt_disallowed_type_raises() -> None:
    with pytest.raises(GeometryError, match="허용되지 않은 geometry type"):
        parse_wkt(_POLY, allowed_types=ROUTE_GEOMETRY_TYPES)


def test_parse_wkt_allowed_type_ok() -> None:
    assert parse_wkt(_LINE, allowed_types=ROUTE_GEOMETRY_TYPES).geom_type == "LineString"
    assert parse_wkt(_POLY, allowed_types=AREA_GEOMETRY_TYPES).geom_type == "Polygon"


def test_geometry_centroid_returns_coordinate() -> None:
    c = geometry_centroid(parse_wkt(_LINE))
    assert isinstance(c, Coordinate)
    assert float(c.lon) == pytest.approx(127.05)
    assert float(c.lat) == pytest.approx(37.55)


def test_geometry_centroid_out_of_korea_raises() -> None:
    # 경도 0 → 한국 경계 밖.
    with pytest.raises(GeometryError, match="한국 경계 밖"):
        geometry_centroid(parse_wkt("LINESTRING(0 0, 1 1)"))


def test_normalize_geometry_returns_wkt_and_centroid() -> None:
    wkt_out, centroid = normalize_geometry(_LINE, allowed_types=ROUTE_GEOMETRY_TYPES)
    assert "LINESTRING" in wkt_out
    assert float(centroid.lon) == pytest.approx(127.05)


def test_normalize_geometry_polygon() -> None:
    wkt_out, centroid = normalize_geometry(_POLY, allowed_types=AREA_GEOMETRY_TYPES)
    assert wkt_out.startswith("POLYGON")
    assert float(centroid.lon) == pytest.approx(127.05)
    assert float(centroid.lat) == pytest.approx(37.05)


def test_geometry_type_sets() -> None:
    assert "LineString" in ROUTE_GEOMETRY_TYPES
    assert "MultiLineString" in ROUTE_GEOMETRY_TYPES
    assert "Polygon" in AREA_GEOMETRY_TYPES
    assert "MultiPolygon" in AREA_GEOMETRY_TYPES

"""``test_core_geometry`` — WKT 파싱 + centroid + 한국 경계 검증 (ADR-012).

``kortravelmap.core.geometry``의 순수 함수 — DB/shapely 외 의존 없음.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from kortravelmap.core.geometry import (
    AREA_GEOMETRY_TYPES,
    ROUTE_GEOMETRY_TYPES,
    GeometryError,
    geometry_area_square_meters,
    geometry_centroid,
    normalize_geometry,
    parse_wkt,
)
from kortravelmap.dto import Coordinate

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


# -- 측지 면적 (area_square_meters, GIS spca) ---------------------------------


def test_geometry_area_polygon_square_meters() -> None:
    # 0.1°×0.1° 폴리곤 @37°N ≈ 8.8km×11.1km ≈ 9~10e7 m².
    area = geometry_area_square_meters(_POLY)
    assert isinstance(area, Decimal)
    assert 5e7 < float(area) < 1.5e8


def test_geometry_area_multipolygon() -> None:
    mpoly = (
        "MULTIPOLYGON(((127 37, 127.1 37, 127.1 37.1, 127 37.1, 127 37)),"
        "((128 37, 128.1 37, 128.1 37.1, 128 37.1, 128 37)))"
    )
    assert float(geometry_area_square_meters(mpoly)) > 1e8


def test_geometry_area_zero_for_non_area() -> None:
    assert geometry_area_square_meters(_LINE) == Decimal("0")  # LineString
    assert geometry_area_square_meters("POINT(127 37)") == Decimal("0")


def test_geometry_area_zero_for_invalid() -> None:
    assert geometry_area_square_meters("NOT WKT") == Decimal("0")
    assert geometry_area_square_meters("POLYGON EMPTY") == Decimal("0")

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
    area_anchor_points,
    geometry_area_square_meters,
    geometry_centroid,
    normalize_geometry,
    parse_wkt,
    repair_area_geometry,
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


# -- 면 수리·역지오 후보점 (2026-11-27 국립공원 경계 재적재) --------------------

_BOWTIE = "POLYGON((126.9 37.6, 127.0 37.7, 127.0 37.6, 126.9 37.7, 126.9 37.6))"


def test_repair_area_geometry_keeps_valid_input_identical() -> None:
    geom = parse_wkt(_POLY)
    assert repair_area_geometry(geom) is geom


def test_repair_area_geometry_fixes_self_intersection_to_polygons_only() -> None:
    geom = parse_wkt(_BOWTIE)
    assert not geom.is_valid
    fixed = repair_area_geometry(geom)
    assert fixed.is_valid
    assert fixed.geom_type == "MultiPolygon"
    assert len(fixed.geoms) == 2


def test_repair_area_geometry_rejects_non_area() -> None:
    with pytest.raises(GeometryError):
        repair_area_geometry(parse_wkt(_LINE))


def test_normalize_geometry_repairs_invalid_area() -> None:
    wkt, _centroid = normalize_geometry(_BOWTIE, allowed_types=AREA_GEOMETRY_TYPES)
    assert parse_wkt(wkt).is_valid


def test_normalize_geometry_leaves_valid_area_wkt_unchanged() -> None:
    """valid 면의 직렬화는 종전과 같다 — 수리가 기존 행의 payload를 흔들지 않는다."""
    wkt, _centroid = normalize_geometry(_POLY, allowed_types=AREA_GEOMETRY_TYPES)
    assert wkt == parse_wkt(_POLY).wkt


def test_area_anchor_points_start_with_centroid_then_surface_then_ring() -> None:
    geom = parse_wkt(
        "MULTIPOLYGON(((126.0 34.0, 126.2 34.0, 126.2 34.2, 126.0 34.2, 126.0 34.0)),"
        "((127.0 35.0, 127.05 35.0, 127.05 35.05, 127.0 35.05, 127.0 35.0)))"
    )
    anchors = area_anchor_points(geom, max_parts=2, ring_samples=4)
    assert anchors[0] == geometry_centroid(geom)
    assert len(anchors) == len(set(anchors))
    lons = [float(anchor.lon) for anchor in anchors]
    # 큰 part(126.0~126.2)의 ring 꼭짓점이 작은 part(127.0~127.05)의 ring 꼭짓점보다 먼저다.
    big_vertex = next(i for i, lon in enumerate(lons) if lon in (126.0, 126.2))
    small_vertex = next(i for i, lon in enumerate(lons) if lon in (127.0, 127.05))
    assert big_vertex < small_vertex
    # centroid 다음 후보들은 모두 면 위(경계 포함)다.
    surface = geom.buffer(1e-9)
    assert all(
        surface.covers(parse_wkt(f"POINT({anchor.lon} {anchor.lat})")) for anchor in anchors[1:]
    )


def test_area_anchor_points_rejects_bad_limits() -> None:
    with pytest.raises(ValueError, match="1 이상"):
        area_anchor_points(parse_wkt(_POLY), max_parts=0)


@pytest.mark.parametrize(
    ("wkt", "expected_area"),
    [
        # 겹치는 part 2개 — 겹친 0.01이 구멍이 되면 안 된다(합집합 0.07).
        (
            "MULTIPOLYGON(((127.0 37.0, 127.2 37.0, 127.2 37.2, 127.0 37.2, 127.0 37.0)),"
            "((127.1 37.1, 127.3 37.1, 127.3 37.3, 127.1 37.3, 127.1 37.1)))",
            0.07,
        ),
        # shell과 변을 공유하는 hole — hole은 남는다.
        (
            "POLYGON((127.0 37.0, 127.2 37.0, 127.2 37.2, 127.0 37.2, 127.0 37.0),"
            "(127.0 37.0, 127.1 37.0, 127.1 37.1, 127.0 37.1, 127.0 37.0))",
            0.03,
        ),
    ],
)
def test_repair_area_geometry_keeps_overlaps_covered(wkt: str, expected_area: float) -> None:
    """``structure`` 수리 — even-odd(linework)처럼 두 번 덮인 곳을 구멍으로 만들지 않는다."""
    geom = parse_wkt(wkt)
    assert not geom.is_valid
    fixed = repair_area_geometry(geom)
    assert fixed.is_valid
    assert fixed.area == pytest.approx(expected_area)

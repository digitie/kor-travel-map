"""``kortravelmap.core.geometry`` — geometry(WKT) 검증 + centroid 추출 (route/area).

route(LINESTRING/MULTILINESTRING)·area(POLYGON/MULTIPOLYGON) feature는 Point
``coord`` 외에 면/선 geometry를 ``Feature.geom``(WKT, EPSG:4326)에 보관한다
(``docs/architecture/feature-model.md`` §RouteDetail/§AreaDetail, ``features.geom`` 컬럼).

본 모듈은 **순수 함수** (ADR-002 core 계층 — DB/HTTP 의존 없음). shapely로 WKT를
파싱·검증하고, centroid를 ``Coordinate``로 돌려준다. provider 변환 함수
(``providers/knps`` 등)가 geometry feature를 만들 때 사용.

ADR 참조
--------
- ADR-002 — core는 순수 함수 (Protocol/stdlib/shapely만)
- ADR-012 — 입력/저장 geometry는 WGS84 (4326). coord_5179는 DB generated
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final

from shapely import wkt as _wkt
from shapely.errors import GEOSException, ShapelyError
from shapely.geometry.base import BaseGeometry

from kortravelmap.dto import Coordinate

if TYPE_CHECKING:
    pass

__all__ = [
    "ROUTE_GEOMETRY_TYPES",
    "AREA_GEOMETRY_TYPES",
    "GeometryError",
    "parse_wkt",
    "geometry_centroid",
    "normalize_geometry",
    "geometry_area_square_meters",
]

# kind별 허용 geometry type (shapely ``geom_type``).
ROUTE_GEOMETRY_TYPES: Final[frozenset[str]] = frozenset(
    {"LineString", "MultiLineString"}
)
AREA_GEOMETRY_TYPES: Final[frozenset[str]] = frozenset({"Polygon", "MultiPolygon"})

# 한국 본토 경계 (dto.Coordinate와 동일 — centroid 검증용).
_KOREA_LON_MIN: Final[float] = 124.0
_KOREA_LON_MAX: Final[float] = 132.0
_KOREA_LAT_MIN: Final[float] = 33.0
_KOREA_LAT_MAX: Final[float] = 39.5


class GeometryError(ValueError):
    """WKT 파싱 실패 / 빈 geometry / 허용되지 않은 type."""


def parse_wkt(wkt_str: str, *, allowed_types: frozenset[str] | None = None) -> BaseGeometry:
    """WKT 문자열 → shapely geometry. 파싱 실패/빈 geometry는 ``GeometryError``.

    Parameters
    ----------
    wkt_str
        EPSG:4326 WKT (예: ``"LINESTRING(127.0 37.5, 127.1 37.6)"``).
    allowed_types
        허용 geom_type 집합 (예: ``ROUTE_GEOMETRY_TYPES``). ``None``이면 type 무관.
    """
    try:
        geom = _wkt.loads(wkt_str)
    except (ShapelyError, GEOSException, TypeError, ValueError) as exc:
        raise GeometryError(f"WKT 파싱 실패: {exc}") from exc
    if geom.is_empty:
        raise GeometryError("빈 geometry (empty WKT).")
    if allowed_types is not None and geom.geom_type not in allowed_types:
        raise GeometryError(
            f"허용되지 않은 geometry type {geom.geom_type!r} "
            f"(허용: {sorted(allowed_types)})."
        )
    return geom


def geometry_centroid(geom: BaseGeometry) -> Coordinate:
    """geometry centroid → ``Coordinate`` (WGS84). 한국 경계 밖이면 ``GeometryError``.

    면/선 feature의 대표 좌표 (지도 마커/검색용). ``Coordinate`` validator가 한국
    경계를 강제하므로, 경계 밖 centroid는 ``GeometryError``로 변환해 호출자가 처리.
    """
    c = geom.centroid
    lon, lat = c.x, c.y
    if not (_KOREA_LON_MIN <= lon <= _KOREA_LON_MAX) or not (
        _KOREA_LAT_MIN <= lat <= _KOREA_LAT_MAX
    ):
        raise GeometryError(
            f"centroid ({lon:.5f}, {lat:.5f})가 한국 경계 밖."
        )
    return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))


def normalize_geometry(
    wkt_str: str, *, allowed_types: frozenset[str] | None = None
) -> tuple[str, Coordinate]:
    """WKT → ``(정규화 WKT, centroid Coordinate)``.

    provider 변환 함수가 route/area feature를 만들 때 한 번에 사용:
    파싱·검증 후 shapely가 재직렬화한 canonical WKT와 centroid를 함께 반환.

    Raises
    ------
    GeometryError
        파싱 실패 / 빈 geometry / 허용 type 위반 / centroid 경계 밖.
    """
    geom = parse_wkt(wkt_str, allowed_types=allowed_types)
    centroid = geometry_centroid(geom)
    return geom.wkt, centroid


def geometry_area_square_meters(wkt_str: str) -> Decimal:
    """area(POLYGON/MULTIPOLYGON) WKT → 측지 면적(m², ge=0). 비-면/불량은 ``0``.

    WGS84 lon/lat 위에서 pyproj ``Geod(ellps='WGS84')`` 측지 면적을 계산한다 —
    EPSG:5179 투영 단계 없이 한국 영역에서 충분히 정확(ADR-012 입력은 4326).
    POINT/LINESTRING 등 면적 0 geometry나 파싱 실패는 ``Decimal('0')``.
    소수점 2자리 반올림 (``AreaDetail.area_square_meters``, ge=0).
    """
    from pyproj import Geod

    try:
        geom = _wkt.loads(wkt_str)
    except (ShapelyError, GEOSException, TypeError, ValueError):
        return Decimal("0")
    if geom.is_empty:
        return Decimal("0")
    try:
        area, _perimeter = Geod(ellps="WGS84").geometry_area_perimeter(geom)
    except (ShapelyError, GEOSException, ValueError, AttributeError):
        return Decimal("0")
    return Decimal(str(round(abs(float(area)), 2)))

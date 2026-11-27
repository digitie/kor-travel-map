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

from shapely import make_valid as _make_valid
from shapely import wkt as _wkt
from shapely.errors import GEOSException, ShapelyError
from shapely.geometry import MultiPolygon, Polygon
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
    "repair_area_geometry",
    "area_anchor_points",
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


def repair_area_geometry(geom: BaseGeometry) -> BaseGeometry:
    """면(POLYGON/MULTIPOLYGON)이 OGC invalid면 ``make_valid``로 고쳐 면 부분만 남긴다.

    원천 SHP에는 자기교차 ring(``Ring Self-intersection``)이 섞여 온다 — 2026-11-27 prod 실측
    한국보호지역 401건 중 14건(팔공산 도립공원·남한산성 도립공원·낙동강 하구 철새도래지 …).
    invalid 면은 ``ST_Covers``/``ST_Intersects`` 결과가 정의되지 않아(GEOS가 틀린 답이나
    TopologyException을 낸다) "이 장소는 어느 면 안인가" 질의를 깨뜨리므로 저장 전에 고친다.

    ``make_valid``는 자기교차 부분에서 선·점 조각을 함께 낼 수 있다 — 면 계약을 지키려고
    Polygon 조각만 모은다. valid 입력은 그대로 돌려준다(정규화가 기존 행을 흔들지 않는다).

    Raises
    ------
    GeometryError
        면이 아닌 입력, 또는 고친 결과에 면이 하나도 남지 않음.
    """
    if geom.geom_type not in AREA_GEOMETRY_TYPES:
        raise GeometryError(f"면 geometry가 아님: {geom.geom_type!r}")
    if geom.is_valid:
        return geom
    fixed = _make_valid(geom)
    polygons: list[Polygon] = []
    pending: list[BaseGeometry] = [fixed]
    while pending:
        part = pending.pop()
        if isinstance(part, Polygon):
            if not part.is_empty:
                polygons.append(part)
        elif hasattr(part, "geoms"):
            pending.extend(part.geoms)
    if not polygons:
        raise GeometryError("make_valid 결과에 면이 남지 않음.")
    if len(polygons) == 1:
        return polygons[0]
    # pop 순서로 뒤집힌 조각 순서를 원래 순서로 되돌린다(결정적 WKT).
    return MultiPolygon(list(reversed(polygons)))


def area_anchor_points(
    geom: BaseGeometry, *, max_parts: int = 3, ring_samples: int = 6
) -> tuple[Coordinate, ...]:
    """면의 역지오코딩 후보점 — centroid가 바다인 해상·연안 면을 육지 주소에 묶는다.

    순서가 계약이다(호출자는 첫 성공을 쓴다):

    1. centroid(:func:`geometry_centroid`와 같은 값 — 기존 feature의 대표점을 바꾸지 않는다),
    2. 면 전체의 ``representative_point``(면 안이 보장된 점),
    3. 넓은 part 순으로 ``max_parts``개 part의 ``representative_point``,
    4. 같은 part들의 바깥 ring 꼭짓점을 고르게 ``ring_samples``개씩.

    2026-11-27 prod geo 실측: 해상 국립공원(다도해해상·태안해안)은 1~3이 전부 바다라 빈 답이고,
    바깥 ring 꼭짓점(해안선)에서 처음 법정동이 나온다. 한국 경계 밖 점과 중복 점은 뺀다.
    """
    if max_parts < 1 or ring_samples < 1:
        raise ValueError("max_parts와 ring_samples는 1 이상이어야 한다")
    parts = sorted(
        (part for part in getattr(geom, "geoms", (geom,)) if isinstance(part, Polygon)),
        key=lambda part: -part.area,
    )[:max_parts]
    raw: list[tuple[float, float]] = [
        (geom.centroid.x, geom.centroid.y),
        (geom.representative_point().x, geom.representative_point().y),
    ]
    raw.extend((part.representative_point().x, part.representative_point().y) for part in parts)
    for part in parts:
        ring = list(part.exterior.coords)[:-1]
        if not ring:
            continue
        step = max(1, len(ring) // ring_samples)
        raw.extend((x, y) for x, y, *_ in ring[::step][:ring_samples])
    seen: set[tuple[float, float]] = set()
    anchors: list[Coordinate] = []
    for lon, lat in raw:
        key = (round(lon, 7), round(lat, 7))
        if key in seen:
            continue
        seen.add(key)
        if not (_KOREA_LON_MIN <= lon <= _KOREA_LON_MAX) or not (
            _KOREA_LAT_MIN <= lat <= _KOREA_LAT_MAX
        ):
            continue
        anchors.append(Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat))))
    return tuple(anchors)


def normalize_geometry(
    wkt_str: str, *, allowed_types: frozenset[str] | None = None
) -> tuple[str, Coordinate]:
    """WKT → ``(정규화 WKT, centroid Coordinate)``.

    provider 변환 함수가 route/area feature를 만들 때 한 번에 사용:
    파싱·검증 후 shapely가 재직렬화한 canonical WKT와 centroid를 함께 반환.
    면(POLYGON/MULTIPOLYGON)은 :func:`repair_area_geometry`로 OGC valid하게 고친 뒤
    직렬화한다 — invalid 면을 저장하지 않는다.

    Raises
    ------
    GeometryError
        파싱 실패 / 빈 geometry / 허용 type 위반 / 고칠 수 없는 면 / centroid 경계 밖.
    """
    geom = parse_wkt(wkt_str, allowed_types=allowed_types)
    if geom.geom_type in AREA_GEOMETRY_TYPES:
        geom = repair_area_geometry(geom)
        if allowed_types is not None and geom.geom_type not in allowed_types:
            raise GeometryError(
                f"수리 뒤 허용되지 않은 geometry type {geom.geom_type!r} "
                f"(허용: {sorted(allowed_types)})."
            )
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

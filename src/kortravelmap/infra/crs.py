"""``kortravelmap.infra.crs`` — pyproj.Transformer singleton (ADR-012 + ADR-030).

좌표계 변환은 **서버 측 PostGIS ``ST_Transform``이 1차 도구**다 (공간 쿼리
인덱스 활용을 위해 — ADR-012). 본 모듈은 Python 측에서 변환이 필요한
narrow case (예: 좌표 검증, 디버그 좌표 표시, GeoPandas 통합)에만 사용한다.

ADR-030 narrow 예외에 따라 ``pyproj.Transformer``는 모듈 레벨 singleton으로
보관 (``@functools.cache``). ``Transformer.from_crs(..., always_xy=True)``는
internal C++ 객체를 만드는 비용이 100ms+ 수준 — singleton이 곧 정답.
``Transformer``는 immutable + thread-safe이므로 cache는 안전하다.

ADR 참조
--------
- ADR-012 — 공간 쿼리는 입력 좌표 1회 변환, 반경은 ``coord_5179``(meter).
  서버 측 ``ST_Transform`` 사용이 1차이며 본 모듈은 보조.
- ADR-030 — in-memory 캐시 금지, ``functools.cache`` narrow 예외만 허용
  (``pyproj.Transformer`` singleton 명시).
- ADR-007 — pyproj 라이브러리 채택.

좌표계
------
- **EPSG:4326** — WGS84 (lon, lat, degrees). DTO ``Coordinate`` 표준.
- **EPSG:5179** — UTM-K (Korea 2000, meters). 반경 검색용
  (``feature.features.coord_5179`` STORED column).

API
---
- ``transformer_4326_to_5179()`` — Transformer singleton (4326 → 5179).
- ``transformer_5179_to_4326()`` — Transformer singleton (5179 → 4326).
- ``project_to_5179(lon, lat)`` — convenience helper (returns ``(x_m, y_m)``).
- ``project_to_4326(x_m, y_m)`` — convenience helper (returns ``(lon, lat)``).
"""

from __future__ import annotations

from functools import cache

from pyproj import Transformer

__all__ = [
    "transformer_4326_to_5179",
    "transformer_5179_to_4326",
    "project_to_5179",
    "project_to_4326",
    "EPSG_WGS84",
    "EPSG_UTM_K",
]


EPSG_WGS84: int = 4326
"""WGS84 — DTO ``Coordinate`` 표준 (lon, lat degrees)."""

EPSG_UTM_K: int = 5179
"""UTM-K (Korea 2000) — 반경 검색용 (``coord_5179`` meter)."""


@cache
def transformer_4326_to_5179() -> Transformer:
    """``EPSG:4326`` → ``EPSG:5179`` Transformer singleton (ADR-030 narrow cache).

    ``always_xy=True`` — 호출 시 ``(x, y)`` 순서로 통일 (lon, lat 순서).
    pyproj의 기본 축 순서(EPSG에 따라 lat/lon 또는 lon/lat 혼재)를 사용하지
    않고 명시적으로 통일한다.

    Returns
    -------
    Transformer
        모듈 레벨 cached singleton. 호출 간 동일 객체.
    """
    return Transformer.from_crs(
        f"EPSG:{EPSG_WGS84}",
        f"EPSG:{EPSG_UTM_K}",
        always_xy=True,
    )


@cache
def transformer_5179_to_4326() -> Transformer:
    """``EPSG:5179`` → ``EPSG:4326`` Transformer singleton (ADR-030 narrow cache).

    Returns
    -------
    Transformer
        모듈 레벨 cached singleton. ``transformer_4326_to_5179()``와 다른
        instance.
    """
    return Transformer.from_crs(
        f"EPSG:{EPSG_UTM_K}",
        f"EPSG:{EPSG_WGS84}",
        always_xy=True,
    )


def project_to_5179(lon: float, lat: float) -> tuple[float, float]:
    """``(lon, lat)`` (degrees, EPSG:4326) → ``(x_m, y_m)`` (meters, EPSG:5179).

    Parameters
    ----------
    lon
        경도 (degrees, WGS84). Korea 권역 [124, 132].
    lat
        위도 (degrees, WGS84). Korea 권역 [33, 39.5].

    Returns
    -------
    tuple[float, float]
        ``(x, y)`` UTM-K meters.

    Notes
    -----
    ``always_xy=True``이므로 입력/출력 모두 ``(x, y)`` 순서. lon=x, lat=y.
    공간 쿼리 자체는 PostGIS ``ST_Transform``을 사용해야 인덱스가 잡힌다
    (ADR-012). 본 함수는 검증/디버그/Python 측 후처리용.
    """
    transformer = transformer_4326_to_5179()
    x, y = transformer.transform(lon, lat)
    return x, y


def project_to_4326(x_m: float, y_m: float) -> tuple[float, float]:
    """``(x_m, y_m)`` (meters, EPSG:5179) → ``(lon, lat)`` (degrees, EPSG:4326).

    Parameters
    ----------
    x_m
        UTM-K X (meters, EPSG:5179).
    y_m
        UTM-K Y (meters, EPSG:5179).

    Returns
    -------
    tuple[float, float]
        ``(lon, lat)`` WGS84 degrees.
    """
    transformer = transformer_5179_to_4326()
    lon, lat = transformer.transform(x_m, y_m)
    return lon, lat

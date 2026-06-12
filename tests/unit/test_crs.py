"""``test_crs`` — ``kortravelmap.infra.crs`` pyproj.Transformer singleton 검증.

ADR-012 (공간 쿼리 1회 변환) + ADR-030 (functools.cache narrow 예외 —
``pyproj.Transformer`` singleton)의 동작 보증. PostGIS ``ST_Transform`` 검증은
``tests/integration/``에서 별도 실행.
"""

from __future__ import annotations

import math

import pytest

from kortravelmap.infra.crs import (
    EPSG_UTM_K,
    EPSG_WGS84,
    project_to_4326,
    project_to_5179,
    transformer_4326_to_5179,
    transformer_5179_to_4326,
)

# -- ADR-030 narrow cache: singleton identity ------------------------------


def test_transformer_4326_to_5179_is_singleton() -> None:
    """``@functools.cache``로 같은 인스턴스 반환 (ADR-030 narrow cache)."""
    a = transformer_4326_to_5179()
    b = transformer_4326_to_5179()
    assert a is b


def test_transformer_5179_to_4326_is_singleton() -> None:
    """역방향 Transformer도 singleton."""
    a = transformer_5179_to_4326()
    b = transformer_5179_to_4326()
    assert a is b


def test_forward_and_inverse_are_distinct_instances() -> None:
    """4326→5179과 5179→4326은 다른 instance여야 한다."""
    fwd = transformer_4326_to_5179()
    inv = transformer_5179_to_4326()
    assert fwd is not inv


# -- EPSG 상수 ---------------------------------------------------------------


def test_epsg_constants_match_postgis() -> None:
    """EPSG 상수가 docs/data-model.md SRID와 일치한다."""
    assert EPSG_WGS84 == 4326
    assert EPSG_UTM_K == 5179


# -- round-trip 정밀도 -----------------------------------------------------


@pytest.mark.parametrize(
    ("lon", "lat", "label"),
    [
        (126.9784, 37.5666, "서울 시청"),
        (129.0756, 35.1796, "부산 시청"),
        (126.4495, 33.4996, "제주 시청"),
        (128.6014, 35.8714, "대구"),
        (124.5, 39.0, "서북단 경계"),
        (131.9, 33.1, "남동단 경계"),
    ],
)
def test_round_trip_within_centimeter(lon: float, lat: float, label: str) -> None:
    """4326 → 5179 → 4326 round-trip의 오차가 cm 단위.

    pyproj/PROJ 변환은 측지학적으로 결정적 — round-trip 오차는
    floating point precision (≲ 1e-7 degree ≈ 1cm)이다.
    """
    x_m, y_m = project_to_5179(lon, lat)
    lon2, lat2 = project_to_4326(x_m, y_m)
    assert math.isclose(lon, lon2, abs_tol=1e-6), f"{label}: lon drift"
    assert math.isclose(lat, lat2, abs_tol=1e-6), f"{label}: lat drift"


# -- 좌표 변환 합리성 -----------------------------------------------------


def test_seoul_5179_in_known_range() -> None:
    """서울 시청(126.9784, 37.5666) → 5179은 약 (953000, 1952000) 근방.

    EPSG:5179 UTM-K의 한국 권역 X는 보통 90만~120만 m, Y는 130만~210만 m.
    """
    x_m, y_m = project_to_5179(126.9784, 37.5666)
    assert 900_000 < x_m < 1_100_000, f"x_m={x_m} out of Seoul UTM-K range"
    assert 1_900_000 < y_m < 2_000_000, f"y_m={y_m} out of Seoul UTM-K range"


def test_distance_between_seoul_and_busan_is_realistic() -> None:
    """서울-부산 직선거리는 약 325km. UTM-K meter 단위로 측정.

    한국 본토 내 거리는 UTM-K(meter)에서 Euclidean으로 측정 가능 — 이게
    바로 ADR-012가 ``coord_5179``를 반경 검색에 쓰는 이유.
    """
    seoul_x, seoul_y = project_to_5179(126.9784, 37.5666)
    busan_x, busan_y = project_to_5179(129.0756, 35.1796)
    dx = seoul_x - busan_x
    dy = seoul_y - busan_y
    dist_m = math.hypot(dx, dy)
    # 서울-부산 직선 ≈ 325km (321~330km 범위)
    assert 320_000 < dist_m < 335_000, (
        f"Seoul-Busan distance {dist_m / 1000:.1f}km out of expected ~325km"
    )


# -- always_xy=True 보증 --------------------------------------------------


def test_always_xy_order_is_consistent() -> None:
    """``always_xy=True``로 입력/출력 모두 ``(x, y)`` = ``(lon, lat)`` 순서.

    pyproj 기본은 EPSG axis order를 따라가서 lat/lon 또는 lon/lat 혼재. 본
    싱글톤은 명시적으로 ``always_xy=True``를 강제하므로 항상 ``(lon, lat)``
    이다.
    """
    # 서울 (lon=126.97, lat=37.57)을 lon=127, lat=37로 약간 변형해 테스트
    transformer = transformer_4326_to_5179()
    x_lat_first, y_lat_first = transformer.transform(127.0, 37.0)
    # 만약 axis order가 lat/lon이면 결과가 황당해짐 — 검증
    assert 900_000 < x_lat_first < 1_100_000, f"x={x_lat_first} axis order broken"
    assert 1_700_000 < y_lat_first < 1_900_000, f"y={y_lat_first} axis order broken"

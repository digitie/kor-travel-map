from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from krtour_map.db import (
    feature_place_details,
    feature_route_details,
    features,
    initialize_feature_db,
    price_points,
    price_values,
)
from krtour_map.enums import FeatureKind
from krtour_map.forest import (
    KRFOREST_RECREATION_FOREST_DATASET_KEY,
    collect_krforest_recreation_features,
    collect_krforest_spatial_features,
    load_krforest_result,
)
from krtour_map.highways import (
    KREX_REST_AREA_CATEGORY,
    collect_krex_rest_area_features,
    collect_krex_rest_area_prices,
    load_highway_result,
)
from krtour_map.models import ROUTE_TYPE_HIKING_TRAIL, Coordinate


@dataclass(frozen=True)
class FakeForestPlace:
    institution_id: str
    name: str
    coordinate: Coordinate
    raw: dict[str, object]
    phone_number: str | None = None
    homepage_url: str | None = None
    reference_date: str | None = None


@dataclass(frozen=True)
class FakeForestSpatial:
    dataset_id: str
    dataset_name: str
    name: str
    geometry_type: str
    geometry: dict[str, object] | None
    coordinate: Coordinate | None
    raw: dict[str, object]


@dataclass(frozen=True)
class FakeRestArea:
    name: str
    route_name: str
    direction: str
    lat: float
    lon: float
    has_gas_station: bool
    has_lpg_station: bool
    has_ev_charger: bool
    phone_number: str
    raw: dict[str, object]
    coordinate: Coordinate | None = None


@dataclass(frozen=True)
class FakeRestAreaFuelPrice:
    service_area_code: str
    service_area_code2: str | None
    service_area_name: str
    route_name: str
    direction: str
    gasoline_price: int
    diesel_price: int
    lpg_price: int | None
    raw: dict[str, object]


def test_collect_krforest_recreation_feature_and_load() -> None:
    result = collect_krforest_recreation_features(
        [
            FakeForestPlace(
                institution_id="RF-1",
                name="국립자연휴양림",
                coordinate=Coordinate(lat=37.1, lon=127.1),
                phone_number="02-123-4567",
                homepage_url="forest.example.com",
                reference_date="2026-05-01",
                raw={"institution_id": "RF-1", "name": "국립자연휴양림"},
            )
        ],
        reverse_geocoder=lambda _coord: {"legal_dong_code": "4182025021"},
    )

    assert result.dataset_key == KRFOREST_RECREATION_FOREST_DATASET_KEY
    assert result.features[0].kind == FeatureKind.PLACE
    assert result.features[0].address.legal_dong_code == "4182025021"
    assert result.place_details[0].phones == ["02-123-4567"]

    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            load = load_krforest_result(session, result)
            session.commit()
        with context.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(features)) == 1
            assert session.scalar(select(func.count()).select_from(feature_place_details)) == 1
        assert load.features == 1
    finally:
        context.dispose()


def test_collect_krforest_spatial_line_becomes_route_and_polygon_becomes_area() -> None:
    result = collect_krforest_spatial_features(
        [
            FakeForestSpatial(
                dataset_id="PBD0000041",
                dataset_name="등산로정보",
                name="백두대간길",
                geometry_type="LineString",
                geometry={"type": "LineString", "coordinates": [[127.0, 37.0], [127.1, 37.1]]},
                coordinate=Coordinate(lat=37.0, lon=127.0),
                raw={"dataset_id": "PBD0000041", "name": "백두대간길"},
            ),
            FakeForestSpatial(
                dataset_id="NP-1",
                dataset_name="국립공원",
                name="설악산 국립공원",
                geometry_type="Polygon",
                geometry={"type": "Polygon", "coordinates": []},
                coordinate=Coordinate(lat=38.1, lon=128.4),
                raw={"dataset_id": "NP-1", "name": "설악산 국립공원"},
            ),
        ]
    )

    assert result.features[0].kind == FeatureKind.ROUTE
    assert result.features[1].kind == FeatureKind.AREA
    assert result.route_details[0].route_type == ROUTE_TYPE_HIKING_TRAIL
    assert result.route_details[0].geometry_status == "provided"
    assert result.area_details[0].area_kind == "forest_area"

    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            load = load_krforest_result(session, result)
            session.commit()
        with context.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(feature_route_details)) == 1
        assert load.route_details == 1
    finally:
        context.dispose()


def test_collect_krex_rest_area_features_and_prices() -> None:
    rest_area = FakeRestArea(
        name="문경휴게소",
        route_name="중부내륙선",
        direction="양평",
        lat=36.7,
        lon=128.1,
        has_gas_station=True,
        has_lpg_station=False,
        has_ev_charger=True,
        phone_number="054-123-4567",
        raw={"restAreaNm": "문경휴게소", "routeNm": "중부내륙선"},
    )
    feature_result = collect_krex_rest_area_features((rest_area,))
    feature_id = feature_result.features[0].feature_id
    service_key = "SA-1|문경휴게소|중부내륙선|양평"
    price_result = collect_krex_rest_area_prices(
        (
            FakeRestAreaFuelPrice(
                service_area_code="SA-1",
                service_area_code2=None,
                service_area_name="문경휴게소",
                route_name="중부내륙선",
                direction="양평",
                gasoline_price=1699,
                diesel_price=1549,
                lpg_price=None,
                raw={"serviceAreaCode": "SA-1", "serviceAreaName": "문경휴게소"},
            ),
        ),
        feature_id_by_service_area_key={service_key: feature_id},
        observed_at=datetime(2026, 5, 20, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert feature_result.features[0].category == KREX_REST_AREA_CATEGORY
    assert feature_result.place_details[0].facility_info["has_gas_station"] is True
    assert price_result.price_points[0].feature_id == feature_id
    assert len(price_result.price_values) == 2

    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            load_highway_result(session, feature_result)
            load = load_highway_result(session, price_result)
            session.commit()
        with context.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(price_points)) == 1
            assert session.scalar(select(func.count()).select_from(price_values)) == 2
        assert load.price_values == 2
    finally:
        context.dispose()

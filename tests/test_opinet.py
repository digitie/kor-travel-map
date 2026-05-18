from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from krtour_map.db import (
    feature_place_details,
    features,
    initialize_feature_db,
    price_points,
    price_values,
)
from krtour_map.enums import FeatureKind
from krtour_map.models import Coordinate, FeatureOpeningHours
from krtour_map.opinet import (
    OPINET_PRICE_CATEGORY,
    load_opinet_station_detail,
    opinet_station_detail_to_feature_bundle,
)


@dataclass(frozen=True)
class FakeOpinetPrice:
    provider_product_code: str
    fuel_type: str
    price: float | None
    trade_date: date
    trade_time: time
    raw: dict[str, object]

    def trade_datetime(self) -> datetime:
        return datetime.combine(
            self.trade_date,
            self.trade_time,
            tzinfo=ZoneInfo("Asia/Seoul"),
        )


@dataclass(frozen=True)
class FakeOpinetStationDetail:
    provider_station_id: str
    provider_station_name: str
    provider_endpoint: str
    brand_code: str
    sub_brand_code: str | None
    station_type: str
    sigun_code: str
    address_jibun: str | None
    address_road: str | None
    tel: str | None
    coordinate: Coordinate
    katec_x: float
    katec_y: float
    has_maintenance: bool
    has_carwash: bool
    has_cvs: bool
    is_kpetro: bool
    prices: tuple[FakeOpinetPrice, ...]
    raw: dict[str, object]
    business_hours: FeatureOpeningHours | dict[str, object] | None = None


def test_opinet_station_detail_to_feature_bundle() -> None:
    detail = _fake_station_detail()

    bundle = opinet_station_detail_to_feature_bundle(detail)

    assert bundle.feature.kind == FeatureKind.PLACE
    assert bundle.feature.category == "fuel"
    assert bundle.feature.coord == Coordinate(lat=37.5001, lon=127.0001)
    assert bundle.place_detail.place_kind == "fuel_station"
    assert bundle.place_detail.phones == ["02-123-4567"]
    assert bundle.place_detail.facility_info["car_wash"] is True
    assert bundle.price_point.price_category == OPINET_PRICE_CATEGORY
    assert len(bundle.price_values) == 2
    assert bundle.price_values[0].item_key == "gasoline"
    assert bundle.source_link.source_record_key == bundle.source_record.key()


def test_opinet_station_detail_enriches_address_from_coordinate() -> None:
    detail = _fake_station_detail(
        business_hours={
            "periods": [
                {
                    "open": {"day": 1, "time": "0000"},
                    "close": {"day": 2, "time": "0000"},
                }
            ],
            "weekday_text": ["월 24시간"],
        }
    )

    bundle = opinet_station_detail_to_feature_bundle(
        detail,
        reverse_geocoder=lambda _coord: {
            "road_address": "서울 강남구 테헤란로 1",
            "legal_dong_code": "1168010100",
        },
    )

    assert bundle.feature.address.legal_dong_code == "1168010100"
    assert bundle.address_match_report.match_level == "coordinate_legal_dong"
    assert bundle.place_detail.business_hours is not None
    assert bundle.place_detail.business_hours.weekday_text == ["월 24시간"]


def test_load_opinet_station_detail_writes_place_and_price_rows() -> None:
    context = initialize_feature_db("sqlite+pysqlite:///:memory:")
    try:
        with context.session_factory() as session:
            result = load_opinet_station_detail(session, _fake_station_detail())
            session.commit()

        with context.session_factory() as session:
            feature_count = session.scalar(select(func.count()).select_from(features))
            place_count = session.scalar(select(func.count()).select_from(feature_place_details))
            price_point_count = session.scalar(select(func.count()).select_from(price_points))
            price_value_count = session.scalar(select(func.count()).select_from(price_values))

        assert result.features == 1
        assert result.place_details == 1
        assert result.price_points == 1
        assert result.price_values == 2
        assert feature_count == 1
        assert place_count == 1
        assert price_point_count == 1
        assert price_value_count == 2
    finally:
        context.dispose()


def _fake_station_detail(
    *,
    business_hours: FeatureOpeningHours | dict[str, object] | None = None,
) -> FakeOpinetStationDetail:
    return FakeOpinetStationDetail(
        provider_station_id="A0010207",
        provider_station_name="샘플주유소",
        provider_endpoint="detailById.do",
        brand_code="SKE",
        sub_brand_code=None,
        station_type="gas_station",
        sigun_code="0113",
        address_jibun="서울 강남구 역삼동 1",
        address_road="서울 강남구 테헤란로 1",
        tel="02-123-4567",
        coordinate=Coordinate(lat=37.5001, lon=127.0001),
        katec_x=314871.8,
        katec_y=544012.0,
        has_maintenance=True,
        has_carwash=True,
        has_cvs=False,
        is_kpetro=True,
        prices=(
            FakeOpinetPrice(
                provider_product_code="B027",
                fuel_type="gasoline",
                price=1699.0,
                trade_date=date(2026, 5, 18),
                trade_time=time(13, 30),
                raw={"PRODCD": "B027", "PRICE": "1699"},
            ),
            FakeOpinetPrice(
                provider_product_code="D047",
                fuel_type="diesel",
                price=1549.0,
                trade_date=date(2026, 5, 18),
                trade_time=time(13, 30),
                raw={"PRODCD": "D047", "PRICE": "1549"},
            ),
        ),
        raw={"UNI_ID": "A0010207", "OS_NM": "샘플주유소"},
        business_hours=business_hours,
    )

"""``test_providers_krex`` — Sprint 2 §2.4 휴게소 multi-kind (PR#45)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

import pytest

from kortravelmap.dto import (
    FeatureBundle,
    FeatureKind,
    ForecastStyle,
    PriceDomain,
    SourceRole,
    TimelineBucket,
    WeatherDomain,
)
from kortravelmap.providers.krex import (
    REST_AREA_CATEGORY,
    REST_AREA_DATASET_KEY,
    REST_AREA_MARKER_ICON,
    REST_AREA_PRICES_DATASET_KEY,
    REST_AREA_WEATHER_DATASET_KEY,
    TRAFFIC_NOTICE_CATEGORY,
    TRAFFIC_NOTICES_DATASET_KEY,
    build_rest_area_place_locator,
    rest_area_fuel_price_records_to_features_and_values,
    rest_area_place_locator_from_rows,
    rest_area_prices_to_values,
    rest_area_weather_records_to_values,
    rest_area_weather_to_values,
)
from kortravelmap.providers.krex import (
    rest_area_weather_records_to_bundles as _rest_area_weather_records_to_bundles_async,
)
from kortravelmap.providers.krex import (
    rest_areas_to_bundles as _rest_areas_to_bundles_async,
)
from kortravelmap.providers.krex import (
    traffic_notices_to_bundles as _traffic_notices_to_bundles_async,
)

KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 5, 28, 5, 0, tzinfo=KST)


def rest_areas_to_bundles(items: Iterable[Any], **kwargs: Any) -> list[FeatureBundle]:
    """sync 테스트 ergonomics — 실제 async 변환을 asyncio.run으로 구동."""
    return asyncio.run(_rest_areas_to_bundles_async(items, **kwargs))


def traffic_notices_to_bundles(
    items: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    """sync 테스트 ergonomics — 실제 async 변환을 asyncio.run으로 구동."""
    return asyncio.run(_traffic_notices_to_bundles_async(items, **kwargs))


# ── rest_areas → place FeatureBundle ─────────────────────────────────


@dataclass(frozen=True)
class _RestArea:
    """`KrexRestAreaItem` Protocol 준수 (provider ``krex.models.RestArea`` 정합).

    안정 식별자(uni_id)·주소 컬럼 없음 — 자연키는 변환부에서
    name+route_name+direction으로 파생(ADR-044). lat/lon은 provider처럼 float.
    """

    name: str
    route_name: str | None
    direction: str | None
    lat: float | None
    lon: float | None
    phone_number: str | None


_RA_SEOSAN = _RestArea(
    name="서산휴게소",
    route_name="서해안고속도로",
    direction="부산방향",
    lat=36.7800,
    lon=126.6500,
    phone_number="041-1234-5678",
)
_RA_GYEONGJU = _RestArea(
    name="경주휴게소",
    route_name="경부고속도로",
    direction="서울방향",
    lat=35.8400,
    lon=129.2200,
    phone_number="054-7491234",
)

# 파생 자연키 = name::route_name::direction (strip→lower→'::' join, ADR-009 '|' 예약 회피).
_NK_SEOSAN = "서산휴게소::서해안고속도로::부산방향"
_NK_GYEONGJU = "경주휴게소::경부고속도로::서울방향"


@pytest.mark.unit
def test_rest_areas_bundle_count_and_order() -> None:
    bundles = rest_areas_to_bundles([_RA_SEOSAN, _RA_GYEONGJU], fetched_at=_NOW)
    assert len(bundles) == 2
    assert [b.source_record.source_entity_id for b in bundles] == [
        _NK_SEOSAN,
        _NK_GYEONGJU,
    ]


@pytest.mark.unit
def test_rest_areas_skips_blank_name_record() -> None:
    """placeholder(표시필드 null) 행은 skip (PR#61).

    실측: source가 ``name=null``인 행을 반환 → name="" → 이전엔 Feature(name 1자
    이상) ValidationError + 파생 자연키도 의미 없음. 이제 방어적으로 거른다.
    """
    blank = _RestArea(
        name="", route_name=None, direction=None,
        lat=None, lon=None, phone_number=None,
    )
    bundles = rest_areas_to_bundles([blank, _RA_SEOSAN], fetched_at=_NOW)
    assert len(bundles) == 1
    assert bundles[0].source_record.source_entity_id == _NK_SEOSAN


@pytest.mark.unit
def test_rest_areas_derived_natural_key_collision_and_stability() -> None:
    """파생 자연키(name+route+direction)는 결정적 — strip/lower 정규화 후 동일
    3필드는 좌표·전화가 달라도 같은 feature_id로 충돌, 다른 휴게소는 분리
    (ADR-044 승인 tradeoff)."""
    twin = _RestArea(
        name="  서산휴게소 ",  # strip/lower 정규화 → _RA_SEOSAN과 동일 자연키.
        route_name="서해안고속도로",
        direction="부산방향",
        lat=None,  # 좌표가 달라도 자연키 기반 identity는 동일.
        lon=None,
        phone_number=None,
    )
    [b_seosan, b_twin, b_gyeongju] = rest_areas_to_bundles(
        [_RA_SEOSAN, twin, _RA_GYEONGJU], fetched_at=_NOW
    )
    # 동일 name+route+direction → 동일 feature_id + 동일 source_entity_id(자연키).
    assert b_twin.feature.feature_id == b_seosan.feature.feature_id
    assert b_twin.source_record.source_entity_id == _NK_SEOSAN
    assert b_seosan.source_record.source_entity_id == _NK_SEOSAN
    # 서로 다른 휴게소는 분리.
    assert b_gyeongju.feature.feature_id != b_seosan.feature.feature_id


@pytest.mark.unit
def test_rest_areas_identical_payload_same_source_record_key() -> None:
    """byte-identical payload → 동일 source_record_key (payload_hash 포함) +
    동일 feature_id."""
    dup = _RestArea(
        name="서산휴게소",
        route_name="서해안고속도로",
        direction="부산방향",
        lat=36.7800,
        lon=126.6500,
        phone_number="041-1234-5678",
    )
    [b1, b2] = rest_areas_to_bundles([_RA_SEOSAN, dup], fetched_at=_NOW)
    assert (
        b1.source_record.source_record_key
        == b2.source_record.source_record_key
    )
    assert b1.feature.feature_id == b2.feature.feature_id


@pytest.mark.unit
def test_rest_areas_feature_metadata() -> None:
    [bundle] = rest_areas_to_bundles([_RA_SEOSAN], fetched_at=_NOW)
    f = bundle.feature
    assert f.kind == FeatureKind.PLACE
    assert f.category == REST_AREA_CATEGORY  # "06040101"
    assert f.marker_icon == REST_AREA_MARKER_ICON  # "fast-food"
    assert f.name == "서산휴게소"
    assert f.coord is not None
    detail = f.detail
    assert detail is not None
    assert detail.place_kind == "rest_area"  # type: ignore[union-attr]
    assert detail.phones == ["041-1234-5678"]  # type: ignore[union-attr]
    facility = detail.facility_info  # type: ignore[union-attr]
    assert facility["direction"] == "부산방향"
    assert facility["highway_name"] == "서해안고속도로"


@pytest.mark.unit
def test_rest_areas_source_record_provider_dataset() -> None:
    [bundle] = rest_areas_to_bundles([_RA_SEOSAN], fetched_at=_NOW)
    src = bundle.source_record
    assert src.provider == "python-krex-api"
    assert src.dataset_key == REST_AREA_DATASET_KEY
    assert src.source_entity_type == "rest_area"
    assert src.fetched_at == _NOW


@pytest.mark.unit
def test_rest_areas_phone_normalized_long_form() -> None:
    """10자리 → 'XXX-XXX-XXXX'."""
    [bundle] = rest_areas_to_bundles([_RA_GYEONGJU], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.phones == ["054-749-1234"]  # type: ignore[union-attr]


@pytest.mark.unit
def test_rest_areas_bundle_fk_consistency() -> None:
    bundles = rest_areas_to_bundles([_RA_SEOSAN, _RA_GYEONGJU], fetched_at=_NOW)
    for bundle in bundles:
        assert bundle.feature.feature_id == bundle.source_link.feature_id
        assert (
            bundle.source_record.source_record_key
            == bundle.source_link.source_record_key
        )


# ── rest_area_prices → PriceValue ──────────────────────────────────


@dataclass(frozen=True)
class _Price:
    uni_id: str
    category: Literal["food", "fuel"]
    product_key: str
    product_name: str | None
    price: str | Decimal | int | float
    observed_at: datetime


_PRICE_FUEL = _Price(
    uni_id="RA-001",
    category="fuel",
    product_key="gasoline",
    product_name="휘발유",
    price="1820",
    observed_at=_NOW,
)
_PRICE_FOOD = _Price(
    uni_id="RA-001",
    category="food",
    product_key="menu_001",
    product_name="우동",
    price="5500",
    observed_at=_NOW,
)
_FEATURE_ID_RA_SEOSAN = "f_global_p_ra_seosan_demo"


@dataclass(frozen=True)
class _FuelPriceRecord:
    service_area_code: str
    route_name: str | None
    direction: str | None
    oil_company: str | None
    service_area_name: str | None
    phone_number: str | None
    address: str | None
    gasoline_price: int | None
    diesel_price: int | None
    lpg_price: int | None
    raw: dict[str, Any]


@pytest.mark.unit
def test_prices_fuel_kw_per_l() -> None:
    [v] = rest_area_prices_to_values(
        [_PRICE_FUEL], feature_id=_FEATURE_ID_RA_SEOSAN
    )
    assert v.price_domain == PriceDomain.REST_AREA_FUEL
    assert v.unit == "KRW/L"
    assert v.value_number == Decimal("1820")
    assert v.product_key == "gasoline"
    assert v.product_name == "휘발유"


@pytest.mark.unit
def test_prices_food_krw() -> None:
    [v] = rest_area_prices_to_values(
        [_PRICE_FOOD], feature_id=_FEATURE_ID_RA_SEOSAN
    )
    assert v.price_domain == PriceDomain.REST_AREA_FOOD
    assert v.unit == "KRW"
    assert v.value_number == Decimal("5500")


@pytest.mark.unit
def test_prices_bad_category_raises() -> None:
    bad = _Price(
        uni_id="X",
        category="other",  # type: ignore[arg-type]
        product_key="x",
        product_name=None,
        price="100",
        observed_at=_NOW,
    )
    with pytest.raises(ValueError, match="'food' or 'fuel'"):
        rest_area_prices_to_values([bad], feature_id=_FEATURE_ID_RA_SEOSAN)


@pytest.mark.unit
def test_prices_non_numeric_raises() -> None:
    bad = _Price(
        uni_id="X",
        category="food",
        product_key="x",
        product_name=None,
        price="문자열입니다",
        observed_at=_NOW,
    )
    with pytest.raises(ValueError, match="numeric이 아님"):
        rest_area_prices_to_values([bad], feature_id=_FEATURE_ID_RA_SEOSAN)


@pytest.mark.unit
def test_fuel_price_records_create_price_feature_and_values() -> None:
    record = _FuelPriceRecord(
        service_area_code="A0001",
        route_name="경부고속도로",
        direction="부산방향",
        oil_company="EX-OIL",
        service_area_name="죽전휴게소",
        phone_number="031-000-0000",
        address="경기 용인시 수지구",
        gasoline_price=1710,
        diesel_price=1599,
        lpg_price=None,
        raw={"serviceAreaCode": "A0001"},
    )

    bundles, values = rest_area_fuel_price_records_to_features_and_values(
        [record], fetched_at=_NOW
    )

    assert len(bundles) == 1
    assert len(values) == 2
    bundle = bundles[0]
    assert bundle.feature.kind == FeatureKind.PRICE
    assert bundle.feature.category == REST_AREA_CATEGORY
    assert bundle.feature.name == "죽전휴게소 유가"
    assert bundle.feature.coord is None
    assert bundle.feature.address.road == "경기 용인시 수지구"
    assert bundle.source_record.dataset_key == REST_AREA_PRICES_DATASET_KEY
    assert [value.product_key for value in values] == ["gasoline", "diesel"]
    assert {value.feature_id for value in values} == {bundle.feature.feature_id}


# ── #547 휴게소 유가 feature 좌표/계층 상속 (렌더 가능성 회귀) ──────────


def _fuel_record_for(
    place: _RestArea, *, service_area_code: str
) -> _FuelPriceRecord:
    """place와 동일한 휴게소명/노선/방향을 갖는 유가 record (이름 매칭 대상)."""
    return _FuelPriceRecord(
        service_area_code=service_area_code,
        route_name=place.route_name,
        direction=place.direction,
        oil_company="EX-OIL",
        service_area_name=place.name,
        phone_number=place.phone_number,
        address="충남 서산시",  # row엔 주소만, lon/lat 없음.
        gasoline_price=1710,
        diesel_price=1599,
        lpg_price=None,
        raw={"serviceAreaCode": service_area_code},
    )


@pytest.mark.unit
def test_fuel_price_inherits_place_coord_and_parent() -> None:
    """#547 — place locator 매칭 시 유가 feature가 place 좌표·parent를 상속.

    `restarea.fuel_prices` row엔 lon/lat가 없어 coord=None이면 모든 bbox/map
    쿼리(coord IS NOT NULL)에서 누락된다. 휴게소명·노선·방향 이름 매칭으로
    place 좌표를 상속하면 coord가 채워져 렌더 가능해지고, parent_feature_id로
    place feature에 연결된다.
    """
    place_bundles = rest_areas_to_bundles([_RA_SEOSAN], fetched_at=_NOW)
    place_feature = place_bundles[0].feature
    locator = build_rest_area_place_locator(place_bundles)
    assert _NK_SEOSAN in locator

    record = _fuel_record_for(_RA_SEOSAN, service_area_code="A0001")
    bundles, values = rest_area_fuel_price_records_to_features_and_values(
        [record], fetched_at=_NOW, place_locator=locator
    )
    [bundle] = bundles
    price_feature = bundle.feature
    # 좌표 상속 → coord IS NOT NULL → bbox/map 쿼리에 노출(렌더 가능).
    assert price_feature.coord is not None
    assert price_feature.coord.lon == place_feature.coord.lon
    assert price_feature.coord.lat == place_feature.coord.lat
    # 계층 연결.
    assert price_feature.parent_feature_id == place_feature.feature_id
    # source_record raw 좌표도 상속 좌표로 채워짐(추적성).
    assert bundle.source_record.raw_longitude == place_feature.coord.lon
    assert bundle.source_record.raw_latitude == place_feature.coord.lat
    # PriceValue는 그대로(좌표 상속과 무관하게 유가값 생성).
    assert [v.product_key for v in values] == ["gasoline", "diesel"]


@pytest.mark.unit
def test_fuel_price_coordless_when_no_place_match() -> None:
    """매칭 place가 없으면 coordless fallback — PriceValue는 그대로 적재.

    place locator를 안 주거나(``None``) 키가 안 맞으면 기존 동작(coord=None,
    parent 없음)을 유지한다. 유가값(PriceValue)은 좌표와 무관하게 생성되어
    좌표는 후속 place 적재로 회복 가능하다.
    """
    place_bundles = rest_areas_to_bundles([_RA_GYEONGJU], fetched_at=_NOW)
    locator = build_rest_area_place_locator(place_bundles)
    # 서산 유가 record인데 locator엔 경주만 있음 → 매칭 실패.
    record = _fuel_record_for(_RA_SEOSAN, service_area_code="A0001")

    bundles, values = rest_area_fuel_price_records_to_features_and_values(
        [record], fetched_at=_NOW, place_locator=locator
    )
    [bundle] = bundles
    assert bundle.feature.coord is None
    assert bundle.feature.parent_feature_id is None
    assert [v.product_key for v in values] == ["gasoline", "diesel"]

    # locator 미주입(None)이면 기존 동작과 동일(coordless).
    bundles_none, _ = rest_area_fuel_price_records_to_features_and_values(
        [record], fetched_at=_NOW
    )
    assert bundles_none[0].feature.coord is None
    assert bundles_none[0].feature.parent_feature_id is None


@pytest.mark.unit
def test_fuel_price_match_key_normalizes_like_place_key() -> None:
    """매칭 키는 place 자연키와 동일 정규화(strip→lower) — 표기 흔들림 흡수."""
    place_bundles = rest_areas_to_bundles([_RA_SEOSAN], fetched_at=_NOW)
    locator = build_rest_area_place_locator(place_bundles)
    # 대소문자/공백만 다른 휴게소명/노선/방향도 같은 키로 매칭.
    noisy = _FuelPriceRecord(
        service_area_code="A0001",
        route_name=" 서해안고속도로 ",
        direction="부산방향",
        oil_company=None,
        service_area_name=" 서산휴게소 ",
        phone_number=None,
        address="충남 서산시",
        gasoline_price=1700,
        diesel_price=None,
        lpg_price=None,
        raw={},
    )
    [bundle], _ = rest_area_fuel_price_records_to_features_and_values(
        [noisy], fetched_at=_NOW, place_locator=locator
    )
    assert bundle.feature.coord is not None
    assert bundle.feature.parent_feature_id == place_bundles[0].feature.feature_id


@pytest.mark.unit
def test_rest_area_place_locator_from_rows_builds_coordinate() -> None:
    """DB row(`(source_entity_id, feature_id, lon, lat)`) → locator 변환.

    `AsyncKorTravelMapClient.list_primary_place_locator`가 반환하는 행을
    유가 변환 locator로 변환하고, 그 locator로 유가 feature가 좌표를 상속하는지.
    """
    rows = [(_NK_SEOSAN, "f_seosan_place", 126.6500, 36.7800)]
    locator = rest_area_place_locator_from_rows(rows)
    assert _NK_SEOSAN in locator
    feature_id, coord = locator[_NK_SEOSAN]
    assert feature_id == "f_seosan_place"
    assert coord.lon == Decimal("126.65")
    assert coord.lat == Decimal("36.78")

    record = _fuel_record_for(_RA_SEOSAN, service_area_code="A0001")
    [bundle], _ = rest_area_fuel_price_records_to_features_and_values(
        [record], fetched_at=_NOW, place_locator=locator
    )
    assert bundle.feature.coord is not None
    assert bundle.feature.coord.lon == Decimal("126.65")
    assert bundle.feature.parent_feature_id == "f_seosan_place"


@pytest.mark.unit
def test_build_locator_skips_coordless_place() -> None:
    """좌표 없는 place는 locator에서 제외(상속할 좌표가 없음)."""
    coordless = _RestArea(
        name="무좌표휴게소",
        route_name="중부고속도로",
        direction="하행",
        lat=None,
        lon=None,
        phone_number=None,
    )
    place_bundles = rest_areas_to_bundles([coordless, _RA_SEOSAN], fetched_at=_NOW)
    locator = build_rest_area_place_locator(place_bundles)
    assert _NK_SEOSAN in locator
    assert "무좌표휴게소::중부고속도로::하행" not in locator


# ── rest_area_weather → WeatherValue (observed) ────────────────────


@dataclass(frozen=True)
class _Weather:
    uni_id: str
    metric_key: str
    value: str | Decimal | int | float
    observed_at: datetime
    unit: str | None


_W_T1H = _Weather(
    uni_id="RA-001",
    metric_key="T1H",
    value="22.5",
    observed_at=_NOW,
    unit="deg_c",
)
_W_REH = _Weather(
    uni_id="RA-001",
    metric_key="REH",
    value="60",
    observed_at=_NOW,
    unit="%",
)


@pytest.mark.unit
def test_weather_observed_metadata() -> None:
    [v] = rest_area_weather_to_values(
        [_W_T1H], feature_id=_FEATURE_ID_RA_SEOSAN
    )
    assert v.weather_domain == WeatherDomain.REST_AREA_WEATHER
    assert v.forecast_style == ForecastStyle.OBSERVED
    assert v.timeline_bucket == TimelineBucket.ULTRA_SHORT
    assert v.value_number == Decimal("22.5")
    assert v.unit == "deg_c"
    assert v.observed_at == _NOW
    assert v.valid_at is None


@pytest.mark.unit
def test_weather_count_per_metric() -> None:
    values = rest_area_weather_to_values(
        [_W_T1H, _W_REH], feature_id=_FEATURE_ID_RA_SEOSAN
    )
    assert len(values) == 2
    assert {v.metric_key for v in values} == {"T1H", "REH"}


# ── rest_area_weather records → weather Feature + WeatherValue ─────


@dataclass(frozen=True)
class _WeatherRecord:
    """`KrexRestAreaWeatherRecord` Protocol 준수 (provider ``RestAreaWeather`` 정합)."""

    unit_code: str
    unit_name: str
    route_name: str | None
    direction_code: str | None
    lat: float | None
    lon: float | None
    observed_at: datetime
    temperature: float | None
    humidity: float | None
    wind_speed: float | None
    rainfall: float | None


def rest_area_weather_records_to_bundles(
    records: Iterable[Any], **kwargs: Any
) -> list[FeatureBundle]:
    """sync 테스트 ergonomics — 실제 async 변환을 asyncio.run으로 구동."""
    return asyncio.run(_rest_area_weather_records_to_bundles_async(records, **kwargs))


_WR_SEOSAN = _WeatherRecord(
    unit_code="EX-1001",
    unit_name="서산휴게소",
    route_name="서해안고속도로",
    direction_code="E",
    lat=36.7800,
    lon=126.6500,
    observed_at=_NOW,
    temperature=22.5,
    humidity=60.0,
    wind_speed=3.2,
    rainfall=None,  # 결측 → metric 행 생성 안 함.
)
_WR_GANGNEUNG = _WeatherRecord(
    unit_code="EX-2002",
    unit_name="강릉휴게소",
    route_name="영동고속도로",
    direction_code="W",
    lat=37.7510,
    lon=128.8760,
    observed_at=_NOW,
    temperature=-99.0,  # sentinel → drop.
    humidity=80.0,
    wind_speed=1.1,
    rainfall=2.5,
)


@pytest.mark.unit
def test_weather_records_bundle_is_weather_kind() -> None:
    [bundle] = rest_area_weather_records_to_bundles([_WR_SEOSAN], fetched_at=_NOW)
    assert bundle.feature.kind is FeatureKind.WEATHER
    assert bundle.feature.detail is None  # weather kind는 detail 불가(ADR-018).
    assert bundle.feature.category == REST_AREA_CATEGORY
    assert bundle.feature.coord is not None
    # 안정키 = unit_code (파생 불필요).
    assert bundle.source_record.source_entity_id == "EX-1001"
    assert bundle.source_record.dataset_key == REST_AREA_WEATHER_DATASET_KEY


@pytest.mark.unit
def test_weather_records_dedup_by_unit_code() -> None:
    """같은 unit_code 중복 행 → 1 bundle. 좌표/unit_code 부재 행은 skip."""
    dup = _WeatherRecord(
        unit_code="EX-1001",  # _WR_SEOSAN과 동일 → dedup.
        unit_name="서산휴게소",
        route_name="서해안고속도로",
        direction_code="E",
        lat=36.7800,
        lon=126.6500,
        observed_at=_NOW,
        temperature=23.0,
        humidity=None,
        wind_speed=None,
        rainfall=None,
    )
    no_coord = _WeatherRecord(
        unit_code="EX-9999",
        unit_name="좌표없음휴게소",
        route_name=None,
        direction_code=None,
        lat=None,
        lon=None,
        observed_at=_NOW,
        temperature=10.0,
        humidity=None,
        wind_speed=None,
        rainfall=None,
    )
    bundles = rest_area_weather_records_to_bundles(
        [_WR_SEOSAN, dup, no_coord, _WR_GANGNEUNG], fetched_at=_NOW
    )
    ids = [b.source_record.source_entity_id for b in bundles]
    assert ids == ["EX-1001", "EX-2002"]  # dup 병합 + 무좌표 skip.


@pytest.mark.unit
def test_weather_records_values_melt_and_metadata() -> None:
    """wide → metric별 melt. 결측(rainfall=None)/sentinel(-99) drop, observed/ULTRA_SHORT."""
    bundles = rest_area_weather_records_to_bundles(
        [_WR_SEOSAN, _WR_GANGNEUNG], fetched_at=_NOW
    )
    feature_ids = {
        b.source_record.source_entity_id: b.feature.feature_id for b in bundles
    }
    values = rest_area_weather_records_to_values(
        [_WR_SEOSAN, _WR_GANGNEUNG], station_feature_ids=feature_ids
    )
    by_feature: dict[str, set[str]] = {}
    for v in values:
        by_feature.setdefault(v.feature_id, set()).add(v.metric_key)
        assert v.weather_domain is WeatherDomain.REST_AREA_WEATHER
        assert v.forecast_style is ForecastStyle.OBSERVED
        assert v.timeline_bucket is TimelineBucket.ULTRA_SHORT
        assert v.observed_at == _NOW
    # 서산: temperature/humidity/wind_speed (rainfall 결측 drop) → T1H/REH/WSD.
    assert by_feature[feature_ids["EX-1001"]] == {"T1H", "REH", "WSD"}
    # 강릉: temperature=-99 sentinel drop → REH/WSD/RN1 (T1H 없음).
    assert by_feature[feature_ids["EX-2002"]] == {"REH", "WSD", "RN1"}


@pytest.mark.unit
def test_weather_records_temperature_maps_to_t1h() -> None:
    """기온 → metric_key=T1H (build_weather_card nearest-temp 'T1H/TMP' 조회 대상)."""
    bundles = rest_area_weather_records_to_bundles([_WR_SEOSAN], fetched_at=_NOW)
    fid = bundles[0].feature.feature_id
    values = rest_area_weather_records_to_values(
        [_WR_SEOSAN], station_feature_ids={"EX-1001": fid}
    )
    [t1h] = [v for v in values if v.metric_key == "T1H"]
    assert t1h.value_number == Decimal("22.5")
    assert t1h.source_metric_key == "temperature"


@pytest.mark.unit
def test_weather_records_skip_unmapped_unit_code() -> None:
    """station_feature_ids에 없는 unit_code 행은 값 생성 안 함."""
    values = rest_area_weather_records_to_values(
        [_WR_SEOSAN], station_feature_ids={}
    )
    assert values == []


# ── traffic_notices → notice FeatureBundle ─────────────────────────


@dataclass(frozen=True)
class _Notice:
    """`KrexTrafficNoticeItem` Protocol 준수 (provider ``krex.models.Incident`` 정합).

    realTimeSms(#378) shape — notice_id/title/notice_type/valid/severity/
    source_agency는 provider에 **없다**(변환부 파생, ADR-044 reconciliation).
    좌표(latitude/longitude)는 일부 row에만 있다.
    """

    occurred_date: str | None = None
    occurred_time: str | None = None
    incident_type: str | None = None
    incident_type_code: str | None = None
    direction: str | None = None
    message: str | None = None
    point_name: str | None = None
    route_no: str | None = None
    route_name: str | None = None
    process_status: str | None = None
    process_status_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    congestion_length: float | None = None
    series_no: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


_N_ROADWORK = _Notice(
    occurred_date="2026.05.28",
    occurred_time="05:00:00",
    incident_type="공사",  # alias → normalize_notice_type → roadwork
    incident_type_code="3",
    direction="부산방향",
    message="서해안고속도로 105km 지점 도로공사",
    point_name="서산나들목",
    route_no="0150",
    route_name="서해안고속도로",
    process_status="진행",
    process_status_code="1",
    raw={
        "accDate": "2026.05.28",
        "accHour": "05:00:00",
        "accType": "공사",
        "accTypeCode": "3",
        "startEndTypeCode": "부산방향",
        "smsText": "서해안고속도로 105km 지점 도로공사",
        "accPointNM": "서산나들목",
        "nosunNM": "0150",
        "roadNM": "서해안고속도로",
        "accProcessNM": "진행",
        "accProcessCode": "1",
    },
)
_N_ACCIDENT_ALIAS = _Notice(
    occurred_date="2026.05.28",
    occurred_time="09:11:24",
    incident_type="교통사고",  # alias → normalize_notice_type → traffic_accident
    incident_type_code="1",
    direction="서울방향",
    message="경부고속도로 200km 교통사고",
    route_no="0010",
    route_name="경부고속도로",
    # 좌표 보유 row (실측 36/99) — 원천 키 altitude가 경도(provider 매핑).
    latitude=36.1234,
    longitude=127.5678,
    raw={
        "accDate": "2026.05.28",
        "accHour": "09:11:24",
        "accType": "교통사고",
        "smsText": "경부고속도로 200km 교통사고",
        "latitude": 36.1234,
        "altitude": 127.5678,
    },
)
_N_UNKNOWN_TYPE = _Notice(
    incident_type="알수없는돌발",  # NOTICE_TYPES/alias에 없음 → 'traffic' fallback
    message="원인 미상 지정체",
    occurred_date="not-a-date",  # 파싱 불가 → valid_from None
    occurred_time=None,
    raw={"accType": "알수없는돌발", "smsText": "원인 미상 지정체"},
)


@pytest.mark.unit
def test_traffic_notice_bundle_metadata() -> None:
    [bundle] = traffic_notices_to_bundles([_N_ROADWORK], fetched_at=_NOW)
    f = bundle.feature
    assert f.kind == FeatureKind.NOTICE
    assert f.category == TRAFFIC_NOTICE_CATEGORY  # "99000000" placeholder
    # title 합성: [route_name] incident_type.
    assert f.name == "[서해안고속도로] 공사"
    detail = f.detail
    assert detail is not None
    assert detail.notice_type == "roadwork"  # type: ignore[union-attr]
    # severity는 Incident에 없음 → None (변환부 고정).
    assert detail.severity is None  # type: ignore[union-attr]
    # occurred_date "2026.05.28" + occurred_time "05:00:00" → KST aware.
    assert detail.valid_start_time == datetime(  # type: ignore[union-attr]
        2026, 5, 28, 5, 0, tzinfo=KST
    )
    # realTimeSms에는 종료 시각 컬럼이 없음 → 항상 None (#378).
    assert detail.valid_end_time is None  # type: ignore[union-attr]
    # source_agency는 변환부 고정값(krex EX = 한국도로공사).
    assert detail.source_agency == "한국도로공사"  # type: ignore[union-attr]
    assert detail.payload["domain"] == "highway"  # type: ignore[union-attr]
    # description = message(smsText).
    assert (
        detail.payload["description"]  # type: ignore[union-attr]
        == "서해안고속도로 105km 지점 도로공사"
    )
    # 신규 필드 payload 보존.
    assert detail.payload["point_name"] == "서산나들목"  # type: ignore[union-attr]
    assert detail.payload["process_status"] == "진행"  # type: ignore[union-attr]
    assert detail.payload["process_status_code"] == "1"  # type: ignore[union-attr]
    assert detail.payload["incident_type_code"] == "3"  # type: ignore[union-attr]


@pytest.mark.unit
def test_traffic_notice_title_falls_back_to_point_then_message() -> None:
    """route/type가 모두 비면 point_name → message 순으로 title 사용."""
    point = _Notice(
        message="원인 미상 지정체 발생",
        point_name="동대구분기점",
        raw={"smsText": "원인 미상 지정체 발생", "accPointNM": "동대구분기점"},
    )
    [bundle] = traffic_notices_to_bundles([point], fetched_at=_NOW)
    assert bundle.feature.name == "동대구분기점"

    message_only = _Notice(
        message="원인 미상 지정체 발생",
        raw={"smsText": "원인 미상 지정체 발생"},
    )
    [bundle] = traffic_notices_to_bundles([message_only], fetched_at=_NOW)
    assert bundle.feature.name == "원인 미상 지정체 발생"


@pytest.mark.unit
def test_traffic_notice_alias_normalized_to_traffic_accident() -> None:
    """`'교통사고'` alias → canonical `'traffic_accident'`."""
    [bundle] = traffic_notices_to_bundles([_N_ACCIDENT_ALIAS], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.notice_type == "traffic_accident"  # type: ignore[union-attr]


@pytest.mark.unit
def test_traffic_notice_unknown_type_falls_back_to_traffic() -> None:
    """NOTICE_TYPES/alias에 없는 incident_type → generic 'traffic'."""
    [bundle] = traffic_notices_to_bundles([_N_UNKNOWN_TYPE], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.notice_type == "traffic"  # type: ignore[union-attr]


@pytest.mark.unit
def test_traffic_notice_unparseable_datetime_is_none() -> None:
    """occurred_date 파싱 실패 → valid_start_time None (방어적 파싱)."""
    [bundle] = traffic_notices_to_bundles([_N_UNKNOWN_TYPE], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.valid_start_time is None  # type: ignore[union-attr]
    assert detail.valid_end_time is None  # type: ignore[union-attr]


@pytest.mark.unit
def test_traffic_notice_time_missing_falls_back_to_midnight() -> None:
    """occurred_time 부재/파싱 실패 → 해당 일자 KST 자정으로 강등."""
    notice = _Notice(
        occurred_date="2026.05.28",
        occurred_time=None,
        incident_type="공사",
        route_no="0150",
        raw={"accDate": "2026.05.28", "accType": "공사"},
    )
    [bundle] = traffic_notices_to_bundles([notice], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.valid_start_time == datetime(  # type: ignore[union-attr]
        2026, 5, 28, 0, 0, tzinfo=KST
    )


@pytest.mark.unit
def test_traffic_notice_natural_key_stable_and_collision() -> None:
    """파생 자연키는 결정적 — 동일 입력은 동일 feature_id/자연키(충돌),
    서로 다른 사건은 분리."""
    twin = _Notice(  # _N_ROADWORK과 byte-identical → 동일 자연키.
        occurred_date="2026.05.28",
        occurred_time="05:00:00",
        incident_type="공사",
        incident_type_code="3",
        direction="부산방향",
        message="서해안고속도로 105km 지점 도로공사",
        point_name="서산나들목",
        route_no="0150",
        route_name="서해안고속도로",
        process_status="진행",
        process_status_code="1",
        raw=dict(_N_ROADWORK.raw),
    )
    [b1, b2, b3] = traffic_notices_to_bundles(
        [_N_ROADWORK, twin, _N_ACCIDENT_ALIAS], fetched_at=_NOW
    )
    assert b1.feature.feature_id == b2.feature.feature_id
    assert (
        b1.source_record.source_entity_id == b2.source_record.source_entity_id
    )
    assert (
        b1.source_record.source_entity_id
        == "2026.05.28::05:00:00::0150::부산방향::서산나들목::3"
    )
    # 자연키 구분자는 '|' 미포함(ADR-009), '::' 사용.
    assert "|" not in b1.source_record.source_entity_id
    # 서로 다른 incident는 분리.
    assert b3.feature.feature_id != b1.feature.feature_id


@pytest.mark.unit
def test_traffic_notice_payload_change_keeps_feature_identity() -> None:
    """같은 사건의 본문 변경은 feature를 나누지 않고 source_record 이력으로 남긴다."""
    base = _N_ROADWORK
    variant = _Notice(
        occurred_date=base.occurred_date,
        occurred_time=base.occurred_time,
        incident_type=base.incident_type,
        incident_type_code=base.incident_type_code,
        direction=base.direction,
        message="서해안고속도로 105km 지점 공사 내용 수정",
        point_name=base.point_name,
        route_no=base.route_no,
        route_name=base.route_name,
        process_status=base.process_status,
        process_status_code=base.process_status_code,
        raw={**base.raw, "smsText": "서해안고속도로 105km 지점 공사 내용 수정"},
    )
    [b1, b2] = traffic_notices_to_bundles([base, variant], fetched_at=_NOW)
    assert b1.source_record.source_entity_id == b2.source_record.source_entity_id
    assert b1.feature.feature_id == b2.feature.feature_id
    assert b1.source_record.raw_payload_hash != b2.source_record.raw_payload_hash
    assert b1.source_record.source_record_key != b2.source_record.source_record_key


@pytest.mark.unit
def test_traffic_notice_no_coord_global_fallback() -> None:
    [bundle] = traffic_notices_to_bundles([_N_ROADWORK], fetched_at=_NOW)
    # 좌표 없는 row → coordless.
    assert bundle.feature.coord is None
    # coord=None → bjd_code 미상 → feature_id global.
    assert bundle.feature.feature_id.startswith("f_global_n_")
    # coordless 위치 단서(raw_address): 노선명 + 돌발지점명 + 방향.
    assert (
        bundle.source_record.raw_address == "서해안고속도로 서산나들목 부산방향"
    )


@pytest.mark.unit
def test_traffic_notice_with_coord_builds_coordinate() -> None:
    """좌표 보유 row(실측 36/99) → Coordinate (Decimal(str(float))) + raw 좌표 보존."""
    [bundle] = traffic_notices_to_bundles([_N_ACCIDENT_ALIAS], fetched_at=_NOW)
    coord = bundle.feature.coord
    assert coord is not None
    assert coord.lat == Decimal("36.1234")
    assert coord.lon == Decimal("127.5678")
    assert bundle.source_record.raw_latitude == Decimal("36.1234")
    assert bundle.source_record.raw_longitude == Decimal("127.5678")
    # reverse_geocoder 미주입 → bjd_code 미상 → 여전히 global feature_id.
    assert bundle.feature.feature_id.startswith("f_global_n_")


@pytest.mark.unit
def test_traffic_notice_source_record_provider() -> None:
    [bundle] = traffic_notices_to_bundles([_N_ROADWORK], fetched_at=_NOW)
    src = bundle.source_record
    assert src.provider == "python-krex-api"
    assert src.dataset_key == TRAFFIC_NOTICES_DATASET_KEY
    assert src.source_entity_type == "traffic_notice"


@pytest.mark.unit
def test_traffic_notice_source_link_primary() -> None:
    [bundle] = traffic_notices_to_bundles([_N_ROADWORK], fetched_at=_NOW)
    link = bundle.source_link
    assert link.source_role == SourceRole.PRIMARY
    assert link.is_primary_source is True


# ── 4 kind 통합 검증 ────────────────────────────────────────────────


@pytest.mark.unit
def test_multi_kind_pipeline_uses_same_feature_id() -> None:
    """rest_areas → bundles → 그 feature_id로 prices/weather 호출이 일관."""
    [station_bundle] = rest_areas_to_bundles([_RA_SEOSAN], fetched_at=_NOW)
    fid = station_bundle.feature.feature_id

    prices = rest_area_prices_to_values(
        [_PRICE_FUEL, _PRICE_FOOD], feature_id=fid
    )
    weather = rest_area_weather_to_values([_W_T1H, _W_REH], feature_id=fid)

    assert all(p.feature_id == fid for p in prices)
    assert all(w.feature_id == fid for w in weather)


@pytest.mark.unit
def test_empty_iterables() -> None:
    assert rest_areas_to_bundles([], fetched_at=_NOW) == []
    assert (
        rest_area_prices_to_values([], feature_id=_FEATURE_ID_RA_SEOSAN) == []
    )
    assert (
        rest_area_weather_to_values([], feature_id=_FEATURE_ID_RA_SEOSAN) == []
    )
    assert traffic_notices_to_bundles([], fetched_at=_NOW) == []

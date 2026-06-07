"""``test_providers_krex`` — Sprint 2 §2.4 휴게소 multi-kind (PR#45)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

import pytest

from krtour.map.dto import (
    FeatureBundle,
    FeatureKind,
    ForecastStyle,
    PriceDomain,
    SourceRole,
    TimelineBucket,
    WeatherDomain,
)
from krtour.map.providers.krex import (
    REST_AREA_CATEGORY,
    REST_AREA_DATASET_KEY,
    REST_AREA_MARKER_ICON,
    TRAFFIC_NOTICE_CATEGORY,
    TRAFFIC_NOTICES_DATASET_KEY,
    rest_area_prices_to_values,
    rest_area_weather_to_values,
)
from krtour.map.providers.krex import (
    rest_areas_to_bundles as _rest_areas_to_bundles_async,
)
from krtour.map.providers.krex import (
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


# ── traffic_notices → notice FeatureBundle ─────────────────────────


@dataclass(frozen=True)
class _Notice:
    notice_id: str
    title: str
    notice_type: str
    description: str | None
    longitude: Decimal | None
    latitude: Decimal | None
    valid_from: datetime | None
    valid_until: datetime | None
    severity: int | None
    source_agency: str | None


_N_ROADWORK = _Notice(
    notice_id="N-001",
    title="서해안고속도로 105km 지점 도로공사",
    notice_type="roadwork",
    description="2026-05-28 ~ 2026-05-30 야간 차로 변경.",
    longitude=Decimal("126.6500"),
    latitude=Decimal("36.7800"),
    valid_from=_NOW,
    valid_until=_NOW + timedelta(days=2),
    severity=2,
    source_agency="한국도로공사",
)
_N_ACCIDENT_ALIAS = _Notice(
    notice_id="N-002",
    title="경부고속도로 200km 교통사고",
    notice_type="교통사고",  # alias — normalize_notice_type → traffic_accident
    description=None,
    longitude=None,
    latitude=None,
    valid_from=None,
    valid_until=None,
    severity=3,
    source_agency="한국도로공사",
)


@pytest.mark.unit
def test_traffic_notice_bundle_metadata() -> None:
    [bundle] = traffic_notices_to_bundles([_N_ROADWORK], fetched_at=_NOW)
    f = bundle.feature
    assert f.kind == FeatureKind.NOTICE
    assert f.category == TRAFFIC_NOTICE_CATEGORY  # "99000000" placeholder
    assert f.name == "서해안고속도로 105km 지점 도로공사"
    detail = f.detail
    assert detail is not None
    assert detail.notice_type == "roadwork"  # type: ignore[union-attr]
    assert detail.severity == 2  # type: ignore[union-attr]
    assert detail.valid_start_time == _NOW  # type: ignore[union-attr]
    assert detail.source_agency == "한국도로공사"  # type: ignore[union-attr]
    assert detail.payload["domain"] == "highway"  # type: ignore[union-attr]


@pytest.mark.unit
def test_traffic_notice_alias_normalized_to_traffic_accident() -> None:
    """`'교통사고'` alias → canonical `'traffic_accident'`."""
    [bundle] = traffic_notices_to_bundles([_N_ACCIDENT_ALIAS], fetched_at=_NOW)
    detail = bundle.feature.detail
    assert detail is not None
    assert detail.notice_type == "traffic_accident"  # type: ignore[union-attr]


@pytest.mark.unit
def test_traffic_notice_no_coord_global_fallback() -> None:
    [bundle] = traffic_notices_to_bundles([_N_ACCIDENT_ALIAS], fetched_at=_NOW)
    assert bundle.feature.coord is None
    # reverse_geocoder=None + coord=None → bjd_code 미상 → feature_id global.
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

"""산림청 산악기상·산불위험·산사태 예보를 map DTO로 정규화한다.

`python-krforest-api`는 provider typed model과 원문을 소유하고, 이 모듈은 그
모델을 `FeatureBundle`·`WeatherValue`·notice `FeatureBundle`로 바꾸는 순수
변환만 담당한다. API 호출이나 provider wrapper는 두지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Protocol, runtime_checkable

from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    ForecastStyle,
    NoticeDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
    WeatherDomain,
    WeatherValue,
)
from kortravelmap.dto.notice import NOTICE_TYPE_LANDSLIDE

__all__ = [
    "LANDSLIDE_FORECAST_DATASET_KEY",
    "MOUNTAIN_WEATHER_DATASET_KEY",
    "WILDFIRE_RISK_DATASET_KEY",
    "LandslideForecastIssueItem",
    "MountainWeatherItem",
    "WildfireRiskForecastItem",
    "LANDSLIDE_FORECAST_SOURCE_ENTITY_TYPE",
    "MOUNTAIN_WEATHER_SOURCE_ENTITY_TYPE",
    "WILDFIRE_RISK_SOURCE_ENTITY_TYPE",
    "landslide_forecast_issues_to_bundles",
    "landslide_active_lineage_keys",
    "mountain_weather_stations_to_bundles",
    "mountain_weather_to_values",
    "wildfire_risk_forecasts_to_bundles",
    "wildfire_risk_region_key",
    "wildfire_risk_to_values",
    "KRFOREST_PROVIDER_NAME",
]


KRFOREST_PROVIDER_NAME: Final[str] = "python-krforest-api"
MOUNTAIN_WEATHER_DATASET_KEY: Final[str] = "krforest_mountain_weather"
WILDFIRE_RISK_DATASET_KEY: Final[str] = "krforest_wildfire_risk_forecast"
LANDSLIDE_FORECAST_DATASET_KEY: Final[str] = "krforest_landslide_forecast_issues"

MOUNTAIN_WEATHER_SOURCE_ENTITY_TYPE: Final[str] = "mountain_weather_station"
WILDFIRE_RISK_SOURCE_ENTITY_TYPE: Final[str] = "wildfire_risk_area"
LANDSLIDE_FORECAST_SOURCE_ENTITY_TYPE: Final[str] = "landslide_forecast_issue"

FOREST_SAFETY_CATEGORY: Final[str] = "99000000"
MOUNTAIN_WEATHER_MARKER_ICON: Final[str] = "mountain-weather"
MOUNTAIN_WEATHER_MARKER_COLOR: Final[str] = "P-06"
WILDFIRE_RISK_MARKER_ICON: Final[str] = "fire-station"
WILDFIRE_RISK_MARKER_COLOR: Final[str] = "P-12"
LANDSLIDE_FORECAST_MARKER_ICON: Final[str] = "warning"
LANDSLIDE_FORECAST_MARKER_COLOR: Final[str] = "P-13"
KRFOREST_SAFETY_NORMALIZATION_VERSION: Final[str] = "krforest-safety-v1.0"

_KST: Final[timezone] = timezone(timedelta(hours=9))


@runtime_checkable
class MountainWeatherItem(Protocol):
    """`python-krforest-api`의 `MountainWeather` 입력 shape."""

    obs_id: str | None
    obs_name: str | None
    local_area: str | None
    observed_at: datetime | None
    temperature_10m: float | None
    temperature_2m: float | None
    humidity_10m: float | None
    humidity_2m: float | None
    pressure: float | None
    rainfall_tipping: float | None
    rainfall_weight: float | None
    ground_temperature: float | None
    wind_direction_10m: float | None
    wind_direction_10m_name: str | None
    wind_direction_2m: float | None
    wind_direction_2m_name: str | None
    wind_speed_10m: float | None
    wind_speed_2m: float | None
    latitude: float | None
    longitude: float | None
    raw: Mapping[str, Any]


@runtime_checkable
class WildfireRiskForecastItem(Protocol):
    """`python-krforest-api`의 `WildfireRiskForecast` 입력 shape."""

    scope: str
    analysis_at: datetime | None
    area: str | None
    region_code: str | None
    region_name: str | None
    upper_region_code: str | None
    d1: float | None
    d2: float | None
    d3: float | None
    d4: float | None
    maximum: float | None
    mean_average: float | None
    minimum: float | None
    standard_deviation: float | None
    raw: Mapping[str, Any]


@runtime_checkable
class LandslideForecastIssueItem(Protocol):
    """`python-krforest-api`의 `LandslideForecastIssue` 입력 shape."""

    issue_kind_code: str | None
    issue_kind_name: str | None
    issuing_institution: str | None
    status: str | None
    issued_at: datetime | None
    raw: Mapping[str, Any]


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=_KST)


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _coord(latitude: object, longitude: object) -> Coordinate | None:
    lat = _decimal(latitude)
    lon = _decimal(longitude)
    if lat is None or lon is None:
        return None
    try:
        return Coordinate(lat=lat, lon=lon)
    except ValueError:
        return None


def _jsonable(value: object) -> Any:
    """provider raw/typed 값을 SourceRecord가 받을 JSON 값으로 만든다."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return str(value)


def _raw_data(item: object, typed: Mapping[str, object]) -> dict[str, Any]:
    raw = getattr(item, "raw", {})
    raw_payload = _jsonable(raw if isinstance(raw, Mapping) else {})
    return {
        "provider_raw": raw_payload,
        "typed": {key: _jsonable(value) for key, value in typed.items()},
    }


def _source_record(
    *,
    dataset_key: str,
    source_entity_type: str,
    source_entity_id: str,
    raw_data: dict[str, Any],
    fetched_at: datetime,
) -> SourceRecord:
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    return SourceRecord(
        provider=normalize_provider_name(KRFOREST_PROVIDER_NAME),
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )


def _weather_anchor_bundle(
    *,
    name: str,
    natural_key: str,
    dataset_key: str,
    source_entity_type: str,
    coord: Coordinate | None,
    marker_icon: str,
    marker_color: str,
    raw_data: dict[str, Any],
    fetched_at: datetime,
) -> FeatureBundle:
    source_record = _source_record(
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=natural_key,
        raw_data=raw_data,
        fetched_at=fetched_at,
    )
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.WEATHER.value,
        category=FOREST_SAFETY_CATEGORY,
        source_type=f"{KRFOREST_PROVIDER_NAME}:{dataset_key}",
        source_natural_key=natural_key,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.WEATHER,
        name=name,
        coord=coord,
        address=Address(),
        category=FOREST_SAFETY_CATEGORY,
        marker_icon=marker_icon,
        marker_color=marker_color,
        detail=None,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=SourceLink(
            feature_id=feature_id,
            source_record_key=source_record.source_record_key,
            source_role=SourceRole.PRIMARY,
            match_method="natural_key",
            confidence=100,
        ),
    )


def _mountain_key(item: MountainWeatherItem) -> str | None:
    return _text(item.obs_id)


def _mountain_typed(item: MountainWeatherItem) -> dict[str, object]:
    return {
        "obs_id": item.obs_id,
        "obs_name": item.obs_name,
        "local_area": item.local_area,
        "observed_at": item.observed_at,
        "temperature_10m": item.temperature_10m,
        "temperature_2m": item.temperature_2m,
        "humidity_10m": item.humidity_10m,
        "humidity_2m": item.humidity_2m,
        "pressure": item.pressure,
        "rainfall_tipping": item.rainfall_tipping,
        "rainfall_weight": item.rainfall_weight,
        "ground_temperature": item.ground_temperature,
        "wind_direction_10m": item.wind_direction_10m,
        "wind_direction_10m_name": item.wind_direction_10m_name,
        "wind_direction_2m": item.wind_direction_2m,
        "wind_direction_2m_name": item.wind_direction_2m_name,
        "wind_speed_10m": item.wind_speed_10m,
        "wind_speed_2m": item.wind_speed_2m,
        "latitude": item.latitude,
        "longitude": item.longitude,
    }


def mountain_weather_stations_to_bundles(
    items: Iterable[MountainWeatherItem],
    *,
    fetched_at: datetime,
) -> list[FeatureBundle]:
    """산악기상 관측소를 weather-kind anchor로 만든다."""

    bundles: list[FeatureBundle] = []
    seen: set[str] = set()
    for item in items:
        natural_key = _mountain_key(item)
        if natural_key is None or natural_key in seen:
            continue
        seen.add(natural_key)
        name = _text(item.obs_name) or _text(item.local_area) or natural_key
        bundles.append(
            _weather_anchor_bundle(
                name=name,
                natural_key=natural_key,
                dataset_key=MOUNTAIN_WEATHER_DATASET_KEY,
                source_entity_type=MOUNTAIN_WEATHER_SOURCE_ENTITY_TYPE,
                coord=_coord(item.latitude, item.longitude),
                marker_icon=MOUNTAIN_WEATHER_MARKER_ICON,
                marker_color=MOUNTAIN_WEATHER_MARKER_COLOR,
                raw_data=_raw_data(item, _mountain_typed(item)),
                fetched_at=fetched_at,
            )
        )
    return bundles


_MOUNTAIN_NUMERIC_METRICS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("temperature_2m", "TMP", "기온(2m)", "deg_c"),
    ("temperature_10m", "TMP10M", "기온(10m)", "deg_c"),
    ("humidity_2m", "REH", "습도(2m)", "%"),
    ("humidity_10m", "REH10M", "습도(10m)", "%"),
    ("pressure", "PRS", "기압", "hPa"),
    ("rainfall_tipping", "RN1", "강수량(전도식)", "mm"),
    ("rainfall_weight", "RNW", "강수량(무게식)", "mm"),
    ("ground_temperature", "TS", "지면온도", "deg_c"),
    ("wind_direction_2m", "VEC", "풍향(2m)", "deg"),
    ("wind_direction_10m", "VEC10M", "풍향(10m)", "deg"),
    ("wind_speed_2m", "WSD", "풍속(2m)", "m/s"),
    ("wind_speed_10m", "WSD10M", "풍속(10m)", "m/s"),
)


def mountain_weather_to_values(
    items: Iterable[MountainWeatherItem],
    *,
    feature_id_by_obs_id: Mapping[str, str],
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """산악기상 wide row를 관측 지표별 `WeatherValue`로 펼친다."""

    values: list[WeatherValue] = []
    for item in items:
        obs_id = _mountain_key(item)
        feature_id = feature_id_by_obs_id.get(obs_id or "")
        observed_at = _aware(item.observed_at)
        if feature_id is None or observed_at is None:
            continue
        typed = _mountain_typed(item)
        for attribute, metric_key, metric_name, unit in _MOUNTAIN_NUMERIC_METRICS:
            value_number = _decimal(getattr(item, attribute, None))
            if value_number is None:
                continue
            values.append(
                WeatherValue(
                    feature_id=feature_id,
                    provider=normalize_provider_name(KRFOREST_PROVIDER_NAME),
                    weather_domain=WeatherDomain.FOREST_MOUNTAIN_WEATHER,
                    forecast_style=ForecastStyle.OBSERVED,
                    timeline_bucket=None,
                    metric_key=metric_key,
                    source_metric_key=attribute,
                    metric_name=metric_name,
                    unit=unit,
                    observed_at=observed_at,
                    value_number=value_number,
                    normalization_version=KRFOREST_SAFETY_NORMALIZATION_VERSION,
                    payload={
                        "domain": "forest",
                        "obs_id": obs_id,
                        "typed": {key: _jsonable(value) for key, value in typed.items()},
                        "metric": metric_key,
                    },
                    source_record_key=source_record_key,
                )
            )
        for attribute, metric_key, metric_name in (
            ("wind_direction_2m_name", "VEC_NAME", "풍향(2m) 문자"),
            ("wind_direction_10m_name", "VEC10M_NAME", "풍향(10m) 문자"),
        ):
            value_text = _text(getattr(item, attribute, None))
            if value_text is None:
                continue
            values.append(
                WeatherValue(
                    feature_id=feature_id,
                    provider=normalize_provider_name(KRFOREST_PROVIDER_NAME),
                    weather_domain=WeatherDomain.FOREST_MOUNTAIN_WEATHER,
                    forecast_style=ForecastStyle.OBSERVED,
                    metric_key=metric_key,
                    source_metric_key=attribute,
                    metric_name=metric_name,
                    unit="code",
                    observed_at=observed_at,
                    value_text=value_text,
                    normalization_version=KRFOREST_SAFETY_NORMALIZATION_VERSION,
                    payload={"domain": "forest", "obs_id": obs_id, "metric": metric_key},
                    source_record_key=source_record_key,
                )
            )
    return values


def wildfire_risk_region_key(item: WildfireRiskForecastItem) -> str:
    """위험 예보 row와 anchor/value가 공유하는 안정 자연키."""

    scope = _text(item.scope) or "national"
    region_code = _text(item.region_code)
    region_name = _text(item.region_name)
    area = _text(item.area)
    upper_code = _text(item.upper_region_code)
    identity = region_code or area or region_name or "national"
    if scope == "sigungu" and upper_code:
        identity = f"{upper_code}::{identity}"
    return f"{scope}::{identity}"


def _wildfire_typed(item: WildfireRiskForecastItem) -> dict[str, object]:
    return {
        "scope": item.scope,
        "analysis_at": item.analysis_at,
        "area": item.area,
        "region_code": item.region_code,
        "region_name": item.region_name,
        "upper_region_code": item.upper_region_code,
        "d1": item.d1,
        "d2": item.d2,
        "d3": item.d3,
        "d4": item.d4,
        "maximum": item.maximum,
        "mean_average": item.mean_average,
        "minimum": item.minimum,
        "standard_deviation": item.standard_deviation,
    }


def wildfire_risk_forecasts_to_bundles(
    items: Iterable[WildfireRiskForecastItem],
    *,
    fetched_at: datetime,
) -> list[FeatureBundle]:
    """산불위험 지역 row를 coordless weather anchor로 만든다."""

    bundles: list[FeatureBundle] = []
    seen: set[str] = set()
    for item in items:
        natural_key = wildfire_risk_region_key(item)
        if natural_key in seen:
            continue
        seen.add(natural_key)
        name = (
            _text(item.region_name)
            or _text(item.area)
            or f"산불위험 {item.scope}"
        )
        bundles.append(
            _weather_anchor_bundle(
                name=name,
                natural_key=natural_key,
                dataset_key=WILDFIRE_RISK_DATASET_KEY,
                source_entity_type=WILDFIRE_RISK_SOURCE_ENTITY_TYPE,
                coord=None,
                marker_icon=WILDFIRE_RISK_MARKER_ICON,
                marker_color=WILDFIRE_RISK_MARKER_COLOR,
                raw_data=_raw_data(item, _wildfire_typed(item)),
                fetched_at=fetched_at,
            )
        )
    return bundles


def _wildfire_value(
    *,
    item: WildfireRiskForecastItem,
    feature_id: str,
    metric_key: str,
    metric_name: str,
    value: object,
    source_metric_key: str,
    issued_at: datetime,
    source_record_key: str | None,
) -> WeatherValue | None:
    value_number = _decimal(value)
    if value_number is None:
        return None
    return WeatherValue(
        feature_id=feature_id,
        provider=normalize_provider_name(KRFOREST_PROVIDER_NAME),
        weather_domain=WeatherDomain.FOREST_FIRE_RISK,
        forecast_style=ForecastStyle.INDEX,
        timeline_bucket=None,
        metric_key=metric_key,
        source_metric_key=source_metric_key,
        metric_name=metric_name,
        unit="score",
        issued_at=issued_at,
        valid_at=issued_at,
        value_number=value_number,
        normalization_version=KRFOREST_SAFETY_NORMALIZATION_VERSION,
        payload={
            "domain": "forest",
            "scope": item.scope,
            "region_code": item.region_code,
            "region_name": item.region_name,
            "typed": {key: _jsonable(value) for key, value in _wildfire_typed(item).items()},
            "metric": metric_key,
        },
        source_record_key=source_record_key,
    )


def wildfire_risk_to_values(
    items: Iterable[WildfireRiskForecastItem],
    *,
    feature_id_by_region_key: Mapping[str, str],
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """산불위험 통계와 72시간 d1~d4 지수를 `WeatherValue`로 만든다."""

    values: list[WeatherValue] = []
    for item in items:
        feature_id = feature_id_by_region_key.get(wildfire_risk_region_key(item))
        issued_at = _aware(item.analysis_at)
        if feature_id is None or issued_at is None:
            continue
        aggregate = item.mean_average
        aggregate_key = "meanavg"
        if aggregate is None:
            aggregate = item.maximum if item.maximum is not None else item.minimum
            aggregate_key = "maxi" if item.maximum is not None else "mini"
        aggregate_value = _wildfire_value(
            item=item,
            feature_id=feature_id,
            metric_key="FIRE_RISK",
            metric_name="산불위험지수 평균",
            value=aggregate,
            source_metric_key=aggregate_key,
            issued_at=issued_at,
            source_record_key=source_record_key,
        )
        if aggregate_value is not None:
            values.append(aggregate_value)
        for index, value in enumerate((item.d1, item.d2, item.d3, item.d4), start=1):
            forecast_value = _wildfire_value(
                item=item,
                feature_id=feature_id,
                metric_key=f"FIRE_RISK_D{index}",
                metric_name=f"산불위험지수 D{index}",
                value=value,
                source_metric_key=f"d{index}",
                issued_at=issued_at,
                source_record_key=source_record_key,
            )
            if forecast_value is not None:
                values.append(forecast_value)
    return values


def _landslide_key(item: LandslideForecastIssueItem) -> str:
    kind = _text(item.issue_kind_code) or _text(item.issue_kind_name) or "unknown"
    institution = _text(item.issuing_institution) or "unknown"
    # status는 같은 issue의 발령→해제 전이를 같은 Feature에 남겨야 하므로
    # 자연키에서 제외한다. provider가 별도 사건 ID를 주지 않으므로 같은
    # 종류·발령기관의 최신 상태만 snapshot에 남기고, 상태 변경은 source
    # record/lifecycle로 표현한다.
    return f"{kind}::{institution}"


def _landslide_is_active(item: LandslideForecastIssueItem) -> bool:
    status = (_text(item.status) or "").lower()
    return not any(
        token in status for token in ("해제", "종료", "해소", "취소", "release", "close")
    )


def _landslide_typed(item: LandslideForecastIssueItem) -> dict[str, object]:
    return {
        "issue_kind_code": item.issue_kind_code,
        "issue_kind_name": item.issue_kind_name,
        "issuing_institution": item.issuing_institution,
        "status": item.status,
        "issued_at": item.issued_at,
    }


def landslide_forecast_issues_to_bundles(
    items: Iterable[LandslideForecastIssueItem],
    *,
    fetched_at: datetime,
) -> list[FeatureBundle]:
    """산사태 예보발령·해제 row를 notice snapshot bundle로 만든다."""

    selected = _select_landslide_items(items)
    bundles: list[FeatureBundle] = []
    for natural_key, item in selected.items():
        issued_at = _aware(item.issued_at) or fetched_at
        name = _text(item.issue_kind_name) or _text(item.issue_kind_code) or "산사태 예보"
        raw_data = _raw_data(item, _landslide_typed(item))
        source_record = _source_record(
            dataset_key=LANDSLIDE_FORECAST_DATASET_KEY,
            source_entity_type=LANDSLIDE_FORECAST_SOURCE_ENTITY_TYPE,
            source_entity_id=natural_key,
            raw_data=raw_data,
            fetched_at=fetched_at,
        )
        feature_id = make_feature_id(
            bjd_code=None,
            kind=FeatureKind.NOTICE.value,
            category=FOREST_SAFETY_CATEGORY,
            source_type=f"{KRFOREST_PROVIDER_NAME}:{LANDSLIDE_FORECAST_DATASET_KEY}",
            source_natural_key=natural_key,
        )
        active = _landslide_is_active(item)
        feature = Feature(
            feature_id=feature_id,
            kind=FeatureKind.NOTICE,
            name=name,
            coord=None,
            address=Address(),
            category=FOREST_SAFETY_CATEGORY,
            marker_icon=LANDSLIDE_FORECAST_MARKER_ICON,
            marker_color=LANDSLIDE_FORECAST_MARKER_COLOR,
            detail=NoticeDetail(
                feature_id=feature_id,
                notice_type=NOTICE_TYPE_LANDSLIDE,
                severity=2 if active else 0,
                valid_start_time=issued_at,
                valid_end_time=None if active else issued_at,
                source_agency=_text(item.issuing_institution),
                payload={
                    "domain": "forest",
                    "issue_kind_code": item.issue_kind_code,
                    "issue_kind_name": item.issue_kind_name,
                    "status": item.status,
                    "active": active,
                    "issued_at": issued_at.isoformat(),
                    "provider_raw": raw_data["provider_raw"],
                },
            ),
        )
        bundles.append(
            FeatureBundle(
                feature=feature,
                source_record=source_record,
                source_link=SourceLink(
                    feature_id=feature_id,
                    source_record_key=source_record.source_record_key,
                    source_role=SourceRole.PRIMARY,
                    match_method="natural_key",
                    confidence=100,
                ),
            )
        )
    return bundles


def _select_landslide_items(
    items: Iterable[LandslideForecastIssueItem],
) -> dict[str, LandslideForecastIssueItem]:
    """같은 issue의 중복 응답 중 가장 최신 발령 시각을 선택한다."""

    selected: dict[str, LandslideForecastIssueItem] = {}
    for item in items:
        key = _landslide_key(item)
        current = selected.get(key)
        issued_at = _aware(item.issued_at)
        current_at = _aware(current.issued_at) if current is not None else None
        if current is None or (
            issued_at is not None and (current_at is None or issued_at >= current_at)
        ):
            selected[key] = item
    return selected


def landslide_active_lineage_keys(
    items: Iterable[LandslideForecastIssueItem],
) -> set[str]:
    """notice snapshot에서 발령 상태로 남길 lineage key를 계산한다."""

    return {
        _landslide_key(item)
        for item in _select_landslide_items(items).values()
        if _landslide_is_active(item)
    }

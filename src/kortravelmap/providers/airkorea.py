"""``kortravelmap.providers.airkorea`` — 대기질 측정소/측정값 정규화 (ADR-034 보조).

``python-airkorea-api``(``import airkorea``)의 대기질 데이터를 두 갈래로 정규화한다:

1. **측정소(station)** → ``weather`` kind ``FeatureBundle``. 대기질은 장소가 아니라
   측정값이므로(ADR-010), 측정소를 weather-kind Feature로 만들고 측정값은 별도
   ``WeatherValue``(``feature.feature_weather_values``)로 적재한다. weather-kind는
   ``detail``을 못 가지므로 category는 부차적(``99000000``, KMA 특보와 동일 관례).
2. **측정값(measurement)** → ``list[WeatherValue]``(오염물질별 1행). 한 측정 row
   (PM10/PM2.5/O3/NO2/SO2/CO/CAI)를 오염물질당 ``WeatherValue``로 펼친다
   (``weather_domain=air_quality``, ``forecast_style=observed``). KMA weather value
   변환과 동일 패턴(``providers/kma.py``) — feature_id는 호출자가 매핑.

좌표는 station ``lat``/``lon``(WGS84 float). feature_id가 bjd_code에 의존하므로
(ADR-009) station 변환은 async이고 좌표 reverse로 행정코드를 보강한다.

ADR 참조: ADR-006 / ADR-009 / ADR-010 / ADR-012 / ADR-019 / ADR-024 / ADR-034.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Protocol, runtime_checkable

from kortravelmap.category import mapbox_maki_icon_or_none
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
)
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
    SourceLink,
    SourceRecord,
    SourceRole,
    WeatherDomain,
    WeatherValue,
)
from kortravelmap.geocoding import ReverseGeocoder, cached_reverse_geocoder

__all__ = [
    "AirQualityStationItem",
    "AirQualityMeasurementItem",
    "air_quality_stations_to_bundles",
    "air_quality_to_weather_values",
    "AIRKOREA_PROVIDER_NAME",
    "DATASET_KEY_STATIONS",
    "DATASET_KEY_AIR_QUALITY",
    "AIR_QUALITY_STATION_CATEGORY",
    "AIR_QUALITY_MARKER_COLOR",
    "AIRKOREA_POLLUTANTS",
    "AIRKOREA_NORMALIZATION_VERSION",
]

AIRKOREA_PROVIDER_NAME: Final[str] = "python-airkorea-api"
"""canonical provider name (ADR-024)."""

DATASET_KEY_STATIONS: Final[str] = "airkorea_stations"
"""측정소 weather feature dataset key."""
DATASET_KEY_AIR_QUALITY: Final[str] = "airkorea_air_quality"
"""대기질 측정값(WeatherValue) dataset key."""

_STATION_ENTITY_TYPE: Final[str] = "air_quality_station"
AIR_QUALITY_STATION_CATEGORY: Final[str] = "99000000"
"""weather kind는 NoticeDetail/PlaceDetail이 없어 category가 부차적 — KMA 특보와
동일하게 ``99000000`` placeholder를 쓴다(ADR-018 weather=detail 없음)."""
AIR_QUALITY_MARKER_COLOR: Final[str] = "P-16"
_DEFAULT_STATION_ICON: Final[str] = "marker"
AIRKOREA_NORMALIZATION_VERSION: Final[str] = "airkorea-v1.0"

_KST: Final[timezone] = timezone(timedelta(hours=9))

# AirKorea 등급(1~4) → severity 라벨.
_GRADE_LABELS: Final[dict[int, str]] = {
    1: "좋음",
    2: "보통",
    3: "나쁨",
    4: "매우나쁨",
}

# 시도명 정규화 — station ``addr`` 첫 토큰(전체/약식)과 measurement ``sido_name``
# (약식)을 같은 canonical 시도로 모은다. composite 안정키 충돌 방지(#300).
_SIDO_CANONICAL: Final[dict[str, str]] = {
    "서울": "서울", "서울특별시": "서울",
    "부산": "부산", "부산광역시": "부산",
    "대구": "대구", "대구광역시": "대구",
    "인천": "인천", "인천광역시": "인천",
    "광주": "광주", "광주광역시": "광주",
    "대전": "대전", "대전광역시": "대전",
    "울산": "울산", "울산광역시": "울산",
    "세종": "세종", "세종시": "세종", "세종특별자치시": "세종",
    "경기": "경기", "경기도": "경기",
    "강원": "강원", "강원도": "강원", "강원특별자치도": "강원",
    "충북": "충북", "충청북도": "충북",
    "충남": "충남", "충청남도": "충남",
    "전북": "전북", "전라북도": "전북", "전북특별자치도": "전북",
    "전남": "전남", "전라남도": "전남",
    "경북": "경북", "경상북도": "경북",
    "경남": "경남", "경상남도": "경남",
    "제주": "제주", "제주도": "제주", "제주특별자치도": "제주",
}


def _canonical_sido(value: str | None) -> str | None:
    """주소/시도명 문자열 → canonical 약식 시도(예: ``"서울특별시 중구" → "서울"``).

    첫 토큰을 ``_SIDO_CANONICAL``로 매핑. 미지의 형태는 첫 토큰을 그대로 쓴다.
    """
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    first = stripped.split()[0]
    return _SIDO_CANONICAL.get(first, first)


def _station_key(station_name: str, sido: str | None) -> str:
    """측정소 composite 안정키 ``station_name::<sido>`` (sido 없으면 이름 단독).

    ``::``는 ADR-009 derived key separator(``|`` 예약 회피).
    """
    name = (station_name or "").strip()
    if sido:
        return f"{name}::{sido}"
    return name


@runtime_checkable
class AirQualityStationItem(Protocol):
    """대기질 측정소 1건 입력 shape (``airkorea`` ``Station``).

    ``station_name``은 전국적으로 유일하지 않다(예: ``중구``가 여러 시도에 존재).
    안정키는 ``addr``에서 추출한 시도와의 composite(``station_name::<sido>``)다.
    """

    station_name: str
    """측정소명(시도 내 식별)."""

    addr: str | None
    """측정소 주소(raw) — 첫 토큰에서 시도를 추출해 composite key/조인에 쓴다."""

    lat: float | None
    lon: float | None


@runtime_checkable
class AirQualityMeasurementItem(Protocol):
    """대기질 측정값 1건 입력 shape (``airkorea`` ``AirQualityMeasurement``).

    한 row에 오염물질별 값이 컬럼으로 들어있다(PM10/PM2.5/O3/NO2/SO2/CO/CAI). 변환
    시 오염물질당 ``WeatherValue`` 1행으로 펼친다. ``data_time``은 관측 시각.
    ``(sido_name, station_name)`` composite로 측정소 feature에 조인한다(이름 충돌 방지).
    """

    station_name: str
    sido_name: str | None
    """시도명 — station ``addr`` 시도와 함께 composite 조인 키를 이룬다."""
    data_time: datetime | None

    khai_value: int | None
    """통합대기환경지수(CAI)."""
    khai_grade: int | None

    pm10_value: float | None
    pm10_grade: int | None
    pm25_value: float | None
    pm25_grade: int | None
    o3_value: float | None
    o3_grade: int | None
    no2_value: float | None
    no2_grade: int | None
    so2_value: float | None
    so2_grade: int | None
    co_value: float | None
    co_grade: int | None


class _Pollutant:
    """오염물질 1종의 metric 매핑(value/grade 속성명 + 표준 metric_key/단위/이름)."""

    __slots__ = ("value_attr", "grade_attr", "metric_key", "unit", "metric_name")

    def __init__(
        self,
        *,
        value_attr: str,
        grade_attr: str,
        metric_key: str,
        unit: str,
        metric_name: str,
    ) -> None:
        self.value_attr = value_attr
        self.grade_attr = grade_attr
        self.metric_key = metric_key
        self.unit = unit
        self.metric_name = metric_name


# 오염물질 매핑 — `docs/etl/weather-feature-normalization.md §2`(PM10/PM2_5/CAI 등).
AIRKOREA_POLLUTANTS: Final[tuple[_Pollutant, ...]] = (
    _Pollutant(
        value_attr="pm10_value", grade_attr="pm10_grade",
        metric_key="PM10", unit="μg/m³", metric_name="미세먼지(PM10)",
    ),
    _Pollutant(
        value_attr="pm25_value", grade_attr="pm25_grade",
        metric_key="PM2_5", unit="μg/m³", metric_name="초미세먼지(PM2.5)",
    ),
    _Pollutant(
        value_attr="o3_value", grade_attr="o3_grade",
        metric_key="O3", unit="ppm", metric_name="오존",
    ),
    _Pollutant(
        value_attr="no2_value", grade_attr="no2_grade",
        metric_key="NO2", unit="ppm", metric_name="이산화질소",
    ),
    _Pollutant(
        value_attr="so2_value", grade_attr="so2_grade",
        metric_key="SO2", unit="ppm", metric_name="아황산가스",
    ),
    _Pollutant(
        value_attr="co_value", grade_attr="co_grade",
        metric_key="CO", unit="ppm", metric_name="일산화탄소",
    ),
    _Pollutant(
        value_attr="khai_value", grade_attr="khai_grade",
        metric_key="CAI", unit="score", metric_name="통합대기환경지수",
    ),
)


def _coord_of(lat: float | None, lon: float | None) -> Coordinate | None:
    if lat is None or lon is None:
        return None
    return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))


async def _station_to_bundle(
    item: AirQualityStationItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None,
) -> FeatureBundle:
    name = normalize_korean_text(item.station_name) or item.station_name
    coord = _coord_of(item.lat, item.lon)
    addr = normalize_korean_text(item.addr)

    geo: Address | None = None
    if coord is not None and reverse_geocoder is not None:
        geo = await reverse_geocoder(coord)
    bjd_code = geo.bjd_code if geo is not None else None
    sigungu_code = (
        (geo.sigungu_code if geo is not None else None) or extract_sigungu_code(bjd_code)
    )
    sido_code = (
        (geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code)
    )
    address = Address(
        admin=(geo.admin if geo is not None else None) or addr,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )

    # composite 안정키 — station_name은 전국 비유일이라 addr 시도와 묶는다(#300).
    sido = _canonical_sido(item.addr)
    natural_key = _station_key(item.station_name, sido)
    raw_data: dict[str, Any] = {
        "station_name": item.station_name,
        "sido": sido,
        "addr": item.addr,
        "latitude": str(coord.lat) if coord is not None else None,
        "longitude": str(coord.lon) if coord is not None else None,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=AIRKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_STATIONS,
        source_entity_type=_STATION_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=bjd_code,
        kind=FeatureKind.WEATHER.value,
        category=AIR_QUALITY_STATION_CATEGORY,
        source_type=f"{AIRKOREA_PROVIDER_NAME}:{DATASET_KEY_STATIONS}",
        source_natural_key=natural_key,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.WEATHER,
        name=name,
        coord=coord,
        address=address,
        category=AIR_QUALITY_STATION_CATEGORY,
        marker_icon=(
            mapbox_maki_icon_or_none(AIR_QUALITY_STATION_CATEGORY)
            or _DEFAULT_STATION_ICON
        ),
        marker_color=AIR_QUALITY_MARKER_COLOR,
        detail=None,  # weather kind는 detail 불가(ADR-018) — 값은 WeatherValue.
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(AIRKOREA_PROVIDER_NAME),
        dataset_key=DATASET_KEY_STATIONS,
        source_entity_type=_STATION_ENTITY_TYPE,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=item.station_name,
        raw_address=item.addr,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature, source_record=source_record, source_link=source_link
    )


async def air_quality_stations_to_bundles(
    items: Iterable[AirQualityStationItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """대기질 측정소 items → ``list[FeatureBundle]`` (weather kind).

    각 측정소가 weather-kind Feature가 되고, 측정값은 별도
    ``air_quality_to_weather_values``로 변환한다. 안정키는 측정소명.
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    return [
        await _station_to_bundle(item, fetched_at=fetched_at, reverse_geocoder=geocoder)
        for item in items
    ]


def _aware_kst(value: datetime | None) -> datetime | None:
    """관측 시각을 KST aware로 보정(ADR-019). naive면 KST 부여."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=_KST)
    return value


def _decimal_or_none(value: float | int | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _measurement_to_values(
    item: AirQualityMeasurementItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> list[WeatherValue]:
    observed_at = _aware_kst(item.data_time)
    provider = normalize_provider_name(AIRKOREA_PROVIDER_NAME)
    values: list[WeatherValue] = []
    for pollutant in AIRKOREA_POLLUTANTS:
        raw_value = getattr(item, pollutant.value_attr, None)
        value_number = _decimal_or_none(raw_value)
        if value_number is None:
            continue  # 결측 오염물질은 행 생성 안 함.
        grade = getattr(item, pollutant.grade_attr, None)
        severity = _GRADE_LABELS.get(grade) if isinstance(grade, int) else None
        values.append(
            WeatherValue(
                feature_id=feature_id,
                provider=provider,
                weather_domain=WeatherDomain.AIR_QUALITY,
                forecast_style=ForecastStyle.OBSERVED,
                timeline_bucket=None,
                metric_key=pollutant.metric_key,
                source_metric_key=pollutant.value_attr,
                metric_name=pollutant.metric_name,
                unit=pollutant.unit,
                observed_at=observed_at,
                value_number=value_number,
                severity=severity,
                normalization_version=AIRKOREA_NORMALIZATION_VERSION,
                payload={
                    "station_name": item.station_name,
                    "metric": pollutant.metric_key,
                    "grade": grade,
                },
                source_record_key=source_record_key,
            )
        )
    return values


def air_quality_to_weather_values(
    items: Iterable[AirQualityMeasurementItem],
    *,
    station_feature_ids: Mapping[str, str],
    source_record_key: str | None = None,
) -> list[WeatherValue]:
    """대기질 측정값 items → ``list[WeatherValue]`` (오염물질별 1행, observed).

    Parameters
    ----------
    items
        ``AirQualityMeasurementItem`` Protocol iterable(측정소×시각별 1 row).
    station_feature_ids
        **composite 키**(``station_name::<sido>``, ``air_quality_stations_to_bundles``의
        ``source_entity_id``) → weather feature_id 매핑. 측정값은 ``(sido_name,
        station_name)``로 같은 composite를 만들어 조회한다 — 측정소명이 전국 비유일이라
        시도를 함께 봐야 다른 지역 feature에 값이 잘못 붙지 않는다(#300). 매핑에 없는
        측정소 row는 건너뛴다.
    source_record_key
        provider raw 추적용(권장). KMA value 변환과 동일.

    Returns
    -------
    list[WeatherValue]
        ``weather_domain=air_quality``, ``forecast_style=observed``. 결측 오염물질
        및 미매핑 측정소는 제외.
    """
    out: list[WeatherValue] = []
    for item in items:
        key = _station_key(item.station_name, _canonical_sido(item.sido_name))
        feature_id = station_feature_ids.get(key)
        if feature_id is None:
            continue
        out.extend(
            _measurement_to_values(
                item, feature_id=feature_id, source_record_key=source_record_key
            )
        )
    return out

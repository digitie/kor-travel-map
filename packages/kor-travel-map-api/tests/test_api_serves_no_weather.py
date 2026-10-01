"""Map API가 weather를 다시 서빙하지 않게 한다(ADR-105).

2026-10-01 소유자 결정: Map은 ``weather`` kind Feature의 모든 기능(KMA·AirKorea·KREX
휴게소 기상·산림청 산악기상·산불위험예보)과 **기상 원천 notice**(KMA 기상특보)를
제거한다. 날씨 정본은 kor-travel-weather다. ``kind='weather'`` 정의(enum·DTO·CHECK 값)는
남는다 — 이 검사는 정의가 아니라 **서빙 표면**만 본다.

각 검사는 이름 나열이 아니라 정체성에 결박한다.

1. ``test_no_openapi_schema_carries_a_weather_value_axis`` — 축은
   ``kortravelmap.dto.WeatherValue`` 필드 중 annotation이 weather 전용 enum
   (``WeatherDomain``/``ForecastStyle``/``TimelineBucket``)을 참조하는 것으로 **유도**한다.
   응답·요청 schema 어디에든 그 축이 property로 있으면 weather 값을 내보내는 것이다.
   main(이 브랜치 직전)에서 빨갛다: ``routers/features.py``의 ``WeatherMetricOut``·
   ``WeatherSummaryOut``과 ``routers/weather.py``의 ``PublicWeatherValueItem``이
   ``weather_domain``/``forecast_style``/``timeline_bucket``을 가진다.
2. ``test_no_route_schema_or_property_is_named_for_the_weather_kind`` — 토큰은
   ``FeatureKind.WEATHER.value``에서 유도한다. 경로 segment, component schema 이름,
   property 이름의 단어로 그 토큰이 나오면 실패한다(enum *값*으로 나오는 것은 kind
   정의라 허용 — 이름만 본다). main에서 빨갛다: ``POST /v1/features/weather/batch``
   (``features.get_feature_weather_batch``), ``WeatherBatchResponse``,
   ``FeatureSummary.weather_summary``, ``BeachPublicView.latest_weather``
   (``routers/public_views.py``), ``/v1/admin/features/{feature_id}/weather``
   (``admin_features.get_admin_feature_weather``).
3. ``test_etl_preview_serves_no_weather_and_no_weather_sourced_notice`` — 효과에 결박한다.
   ``FIXTURE_REGISTRY``의 모든 preview 변환을 실제로 돌려 산출물이 ``WeatherValue``로
   검증되거나, Feature ``kind``가 weather이거나, notice인데 원천 provider가 KMA
   (``normalize_provider_name("kma")`` — canonical provider 카탈로그에서 유도)이면 실패한다.
   main에서 빨갛다: ``etl_fixtures``의 ``kma_short_forecast``/``kma_ultra_short_nowcast``/
   ``kma_ultra_short_forecast``·``krex_rest_area_weather``·``krforest_mountain_weather``·
   ``krforest_wildfire_risk_forecast``·``airkorea_air_quality``(WeatherValue),
   ``airkorea_stations``(weather kind), ``kma_weather_alerts``(KMA notice).

양성 검사 ``test_kept_notice_previews_still_convert``는 제거가 notice 일반을 끌고 가지
않았음을 본다 — 비기상 notice preview(교통 돌발·산사태)가 여전히 notice bundle을 낸다.
Map에는 notice 전용 route가 없고 notice는 일반 ``/v1/features*`` 조회로 나가므로, 양성
축은 route가 아니라 notice를 만드는 preview 변환이다.

DB 쪽(카탈로그 비활성·데이터 삭제)은 이 파일의 범위가 아니다 — 402 migration 통합 검사
(``tests/integration/test_weather_removal_migration.py``)와
``tests/integration/test_provider_catalog.py::test_head_serves_no_weather_dataset``가 맡는다.
"""

from __future__ import annotations

import asyncio
import json
import re
import typing
from collections.abc import Iterator
from typing import Any

from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    FeatureKind,
    ForecastStyle,
    TimelineBucket,
    WeatherDomain,
    WeatherValue,
)
from pydantic import ValidationError

from kortravelmap.api.app import create_app
from kortravelmap.api.etl_fixtures import FIXTURE_REGISTRY, EtlFixtureEntry
from kortravelmap.api.settings import ApiSettings

_WEATHER_ONLY_TYPES: frozenset[type] = frozenset({WeatherDomain, ForecastStyle, TimelineBucket})
_WEATHER_TOKEN = FeatureKind.WEATHER.value
_NOTICE_KIND = FeatureKind.NOTICE.value
#: KMA는 weather provider다 — 그 notice는 기상 원천 notice다. canonical 카탈로그가 정본.
_KMA_PROVIDER = normalize_provider_name("kma")


def _references(annotation: Any, targets: frozenset[type]) -> bool:
    if annotation in targets:
        return True
    return any(_references(arg, targets) for arg in typing.get_args(annotation))


def _weather_value_axes() -> frozenset[str]:
    """``WeatherValue``에서 weather 전용 enum을 annotation으로 갖는 필드."""
    return frozenset(
        name
        for name, info in WeatherValue.model_fields.items()
        if _references(info.annotation, _WEATHER_ONLY_TYPES)
    )


def _openapi() -> dict[str, Any]:
    return create_app(ApiSettings()).openapi()


def _walk_properties(node: Any, where: str) -> Iterator[tuple[str, str]]:
    """schema 트리 어디든 ``properties`` 키를 (위치, property 이름)으로 낸다."""
    if isinstance(node, dict):
        properties = node.get("properties")
        if isinstance(properties, dict):
            for name in properties:
                yield where, name
        for key, child in node.items():
            yield from _walk_properties(child, f"{where}/{key}")
    elif isinstance(node, list):
        for index, child in enumerate(node):
            yield from _walk_properties(child, f"{where}[{index}]")


def _words(name: str) -> set[str]:
    """``WeatherBatchResponse``/``latest_weather``/``{feature_id}`` → 소문자 단어 집합."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    return {word.lower() for word in re.split(r"[^A-Za-z0-9]+", spaced) if word}


def test_weather_value_axes_are_derived_not_empty() -> None:
    """항진명제 방지 — 유도가 비면 아래 axis 검사가 아무것도 재지 않는다."""
    axes = _weather_value_axes()
    assert len(axes) >= 2, f"WeatherValue에서 weather 축을 유도하지 못했다: {sorted(axes)}"


def test_no_openapi_schema_carries_a_weather_value_axis() -> None:
    axes = _weather_value_axes()
    spec = _openapi()
    seen = list(_walk_properties(spec, "#"))
    assert len(seen) > 100, "OpenAPI property 순회가 거의 아무것도 보지 못했다"
    offenders = sorted({f"{where}.{name}" for where, name in seen if name in axes})
    assert not offenders, (
        "API schema가 WeatherValue 축(weather_domain/forecast_style/timeline_bucket 계열)을 "
        f"다시 내보낸다(ADR-105): {offenders}"
    )


def test_no_route_schema_or_property_is_named_for_the_weather_kind() -> None:
    # route 목록은 OpenAPI의 paths에서 읽는다. ``app.routes``는 settings profile에 따라
    # router가 sub-app으로 mount돼 APIRoute가 거의 보이지 않는다(n150 실측: ``/metrics``
    # 하나) — 공개 표면의 정본은 OpenAPI다.
    spec = _openapi()
    route_paths = list(spec.get("paths", {}))
    assert len(route_paths) > 50, "route 순회가 거의 아무것도 보지 못했다"
    schema_names = list(spec.get("components", {}).get("schemas", {}))
    property_names = {name for _, name in _walk_properties(spec, "#")}

    offenders = sorted(
        {f"path {path}" for path in route_paths if _WEATHER_TOKEN in _words(path)}
        | {f"schema {name}" for name in schema_names if _WEATHER_TOKEN in _words(name)}
        | {f"property {name}" for name in property_names if _WEATHER_TOKEN in _words(name)}
    )
    assert not offenders, (
        f"weather kind({_WEATHER_TOKEN!r})를 서빙하는 이름이 다시 생겼다(ADR-105): {offenders}"
    )


def _converted(entry: EtlFixtureEntry) -> list[Any]:
    return asyncio.run(entry.convert(entry.build_fixture()))


def _is_weather_value(item: Any) -> bool:
    try:
        WeatherValue.model_validate_json(json.dumps(item))
    except ValidationError:
        return False
    return True


def _feature_kind_and_provider(item: Any) -> tuple[str | None, str | None]:
    if not isinstance(item, dict):
        return None, None
    feature = item.get("feature")
    record = item.get("source_record")
    kind = feature.get("kind") if isinstance(feature, dict) else None
    provider = record.get("provider") if isinstance(record, dict) else None
    return kind, provider


def test_etl_preview_serves_no_weather_and_no_weather_sourced_notice() -> None:
    assert len(FIXTURE_REGISTRY) >= 10, "preview registry가 비었다 — 검사가 아무것도 보지 않는다"
    offenders: list[str] = []
    converted_items = 0
    for entry in FIXTURE_REGISTRY:
        label = f"{entry.provider}/{entry.dataset}"
        for item in _converted(entry):
            converted_items += 1
            if _is_weather_value(item):
                offenders.append(f"{label}: WeatherValue")
                continue
            kind, provider = _feature_kind_and_provider(item)
            if kind == _WEATHER_TOKEN:
                offenders.append(f"{label}: kind={kind}")
            elif kind == _NOTICE_KIND and provider == _KMA_PROVIDER:
                offenders.append(f"{label}: notice from {provider}")
    assert converted_items > len(FIXTURE_REGISTRY), "preview 변환이 거의 아무것도 내지 않았다"
    assert not offenders, f"preview가 weather/기상 원천 notice를 다시 낸다(ADR-105): {offenders}"


def test_kept_notice_previews_still_convert() -> None:
    """비기상 notice preview가 남아 있어야 한다 — 하한은 '본 것'에 건다.

    2026-10-01 기준 교통 돌발(``python-krex-api``)과 산사태 예보(``python-krforest-api``)
    두 dataset이 notice를 낸다.
    """
    notice_datasets: set[str] = set()
    for entry in FIXTURE_REGISTRY:
        for item in _converted(entry):
            kind, provider = _feature_kind_and_provider(item)
            if kind == _NOTICE_KIND and provider != _KMA_PROVIDER:
                notice_datasets.add(f"{entry.provider}/{entry.dataset}")
    assert len(notice_datasets) >= 2, (
        f"비기상 notice preview가 사라졌다 — notice 일반까지 지운 것이 아닌지 확인할 것: "
        f"{sorted(notice_datasets)}"
    )

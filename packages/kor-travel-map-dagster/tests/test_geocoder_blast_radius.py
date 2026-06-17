"""geocoder 필수화(ADR-058/F-01) blast radius 정적 회귀 테스트.

``reverse_geocoder_resource``는 ``KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL`` 미설정 시
``RuntimeError``를 낸다(geocoder 필수, feature_id 결정성). ``reverse_geocoder``는
``_COMMON_RESOURCE_KEYS``에 들어 있어 ~20개 feature-load asset의
``required_resource_keys``에 붙으므로, base URL이 비면 그 asset 전부가 resource
init에서 실패한다. 반대로 4개 KMA 예보 asset은 ``_KMA_WEATHER_RESOURCE_KEYS``/
``_KMA_MID_RESOURCE_KEYS``를 쓰며 ``reverse_geocoder``를 포함하지 않는다.

이 테스트는 ``required_resource_keys`` 멤버십만 정적으로 검사한다 — live DB도,
materialize도 없는 import-only 결정적 회귀다(#446).
"""

from __future__ import annotations

import pytest
from dagster import AssetsDefinition

from kortravelmap.dagster.assets import FEATURE_LOAD_ASSETS
from kortravelmap.dagster.kma_weather import (
    feature_notice_kma_weather_alerts,
    feature_weather_kma_mid_forecast,
    feature_weather_kma_short_forecast,
    feature_weather_kma_ultra_short_forecast,
    feature_weather_kma_ultra_short_nowcast,
)
from kortravelmap.dagster.mcst_features import feature_place_mcst_culture

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)

# geocoder에 의존하는 대표 feature-load asset(provider 적재 asset 전체 +
# _COMMON_RESOURCE_KEYS를 쓰는 KMA 특보/MCST asset). 전부 base URL 미설정 시
# resource init에서 함께 실패한다.
_GEOCODER_DEPENDENT_ASSETS = [
    *FEATURE_LOAD_ASSETS,
    feature_notice_kma_weather_alerts,
    feature_place_mcst_culture,
]

# 예외: reverse_geocoder를 포함하지 않는 4개 KMA 예보 asset.
_KMA_FORECAST_ASSETS = [
    feature_weather_kma_ultra_short_nowcast,
    feature_weather_kma_ultra_short_forecast,
    feature_weather_kma_short_forecast,
    feature_weather_kma_mid_forecast,
]


@pytest.mark.parametrize(
    "asset_def",
    _GEOCODER_DEPENDENT_ASSETS,
    ids=lambda asset_def: asset_def.key.to_user_string(),
)
def test_feature_load_assets_require_reverse_geocoder(asset_def: AssetsDefinition) -> None:
    """_COMMON_RESOURCE_KEYS 기반 feature-load asset은 reverse_geocoder를 요구한다."""
    assert "reverse_geocoder" in asset_def.required_resource_keys


@pytest.mark.parametrize(
    "asset_def",
    _KMA_FORECAST_ASSETS,
    ids=lambda asset_def: asset_def.key.to_user_string(),
)
def test_kma_forecast_assets_do_not_require_reverse_geocoder(
    asset_def: AssetsDefinition,
) -> None:
    """4개 KMA 예보 asset은 reverse_geocoder를 요구하지 않는다(blast radius 제외)."""
    assert "reverse_geocoder" not in asset_def.required_resource_keys

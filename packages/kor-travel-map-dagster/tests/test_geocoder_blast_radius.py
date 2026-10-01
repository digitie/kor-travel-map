"""geocoder 필수화(ADR-058/F-01) blast radius 정적 회귀 테스트.

``reverse_geocoder_resource``는 ``KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL`` 미설정 시
``RuntimeError``를 낸다(geocoder 필수, feature_id 결정성). ``reverse_geocoder``는
``_COMMON_RESOURCE_KEYS``에 들어 있어 ~20개 feature-load asset의
``required_resource_keys``에 붙으므로, base URL이 비면 그 asset 전부가 resource
init에서 실패한다.

(종전의 예외였던 KMA 중기예보 값-only asset은 KMA 적재 경로와 함께 Map Dagster에서
제거됐다 — ADR-104.)

이 테스트는 ``required_resource_keys`` 멤버십만 정적으로 검사한다 — live DB도,
materialize도 없는 import-only 결정적 회귀다(#446).
"""

from __future__ import annotations

import pytest
from dagster import AssetsDefinition

from kortravelmap.dagster.assets import FEATURE_LOAD_ASSETS
from kortravelmap.dagster.mcst_features import feature_place_mcst_culture

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)

# geocoder에 의존하는 대표 feature-load asset(provider 적재 asset 전체 +
# _COMMON_RESOURCE_KEYS를 쓰는 MCST asset). 전부 base URL 미설정 시
# resource init에서 함께 실패한다.
_GEOCODER_DEPENDENT_ASSETS = [
    *FEATURE_LOAD_ASSETS,
    feature_place_mcst_culture,
]


@pytest.mark.parametrize(
    "asset_def",
    _GEOCODER_DEPENDENT_ASSETS,
    ids=lambda asset_def: asset_def.key.to_user_string(),
)
def test_feature_load_assets_require_reverse_geocoder(asset_def: AssetsDefinition) -> None:
    """_COMMON_RESOURCE_KEYS 기반 feature-load asset은 reverse_geocoder를 요구한다."""
    assert "reverse_geocoder" in asset_def.required_resource_keys

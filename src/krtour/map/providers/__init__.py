"""``krtour.map.providers`` — provider별 raw → DTO 변환 모듈.

각 provider 라이브러리(``python-*-api``)의 typed model을 본 라이브러리의
``FeatureBundle``로 정규화하는 **순수 함수 namespace**. wrapper/adapter/
gateway 신규 생성 금지 (ADR-006).

**Sprint 2~5에서 provider별 모듈 점진 추가** — ADR-034 9단계 순서:

| Sprint | provider 모듈 |
|--------|--------------|
| 2 | ``visitkorea`` / ``kma`` / ``airkorea`` / ``krforest_weather`` |
|   | / ``khoa_weather`` / ``opinet`` / ``krex`` |
| 3 | ``knps`` (14 dataset) / ``krforest_trails`` / ``krheritage`` |
| 4 | ``mois`` (4단계 lifecycle) |
| 5 | ``krforest`` (휴양림/수목원) / ``standard_data`` (5종) |

ADR 참조
--------
- ADR-006 — provider wrapper/adapter 금지 (public client 직접 사용)
- ADR-024 — canonical provider name (``python-mois-api``, ``python-knps-api``,
  등)
- ADR-034 — 구현 9단계 순서
"""

from __future__ import annotations

from krtour.map.providers.kma import (
    KMA_METRIC_NAMES,
    KMA_METRIC_UNITS,
    KMA_PROVIDER_NAME,
    KmaShortForecastItem,
    short_forecast_to_weather_values,
)
from krtour.map.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    FESTIVAL_CATEGORY,
    FESTIVAL_MARKER_COLOR,
    FESTIVAL_MARKER_ICON,
    CulturalFestivalItem,
    ReverseGeocoder,
    ReverseGeocodeResult,
    cultural_festivals_to_bundles,
)

__all__ = [
    # standard_data (PR#34, ADR-042 — datagokr 표준데이터)
    "CulturalFestivalItem",
    "ReverseGeocoder",
    "ReverseGeocodeResult",
    "cultural_festivals_to_bundles",
    "DATASET_KEY_CULTURAL_FESTIVALS",
    "FESTIVAL_CATEGORY",
    "FESTIVAL_MARKER_ICON",
    "FESTIVAL_MARKER_COLOR",
    # kma (PR#38, ADR-010 short forecast 1차)
    "KmaShortForecastItem",
    "short_forecast_to_weather_values",
    "KMA_PROVIDER_NAME",
    "KMA_METRIC_UNITS",
    "KMA_METRIC_NAMES",
]

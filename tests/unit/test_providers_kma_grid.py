"""``test_providers_kma_grid`` — KMA DFS 격자 → weather FeatureBundle.

KMA 예보는 격자(nx,ny) 단위라 '관측소'가 없다. 격자 자체를 weather-kind Feature
(격자 중심 좌표)로 만들어 airkorea 측정소와 **별개** 마커로 뜨게 한다. 초단기/단기는
같은 격자라도 ``dataset_key``가 달라 **별개** feature가 된다(갱신 주기 분리). 격자당 1
feature·1 값세트라 #496 anti-replication은 유지된다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kortravelmap.dto import FeatureKind, SourceRole
from kortravelmap.providers.kma import (
    KMA_GRID_CATEGORY,
    KMA_GRID_MARKER_COLOR,
    KMA_PROVIDER_NAME,
    KMA_SHORT_GRID_DATASET_KEY,
    KMA_ULTRA_SHORT_GRID_DATASET_KEY,
    grid_to_weather_bundle,
)

KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 6, 29, 6, 0, tzinfo=KST)


async def test_grid_to_weather_bundle_basic() -> None:
    bundle = await grid_to_weather_bundle(
        60,
        127,
        37.5665,
        126.9780,
        dataset_key=KMA_ULTRA_SHORT_GRID_DATASET_KEY,
        name_label="기상청 초단기",
        fetched_at=_NOW,
    )
    feature = bundle.feature

    assert feature.kind is FeatureKind.WEATHER
    assert KMA_GRID_CATEGORY == "99000000"
    assert feature.category == KMA_GRID_CATEGORY
    assert feature.detail is None  # weather kind는 detail 불가(ADR-018)
    assert feature.marker_color == KMA_GRID_MARKER_COLOR

    # 좌표 = 호출자가 넘긴 격자 중심(`kma.grid.to_latlon`)
    assert feature.coord is not None
    assert abs(float(feature.coord.lat) - 37.5665) < 1e-9
    assert abs(float(feature.coord.lon) - 126.9780) < 1e-9

    # geocoder 없으면 이름은 name_label + 격자 fallback
    assert feature.name == "기상청 초단기 격자 60,127"

    # primary source = KMA 초단기 격자 dataset, 안정키 = "{nx}_{ny}"
    assert bundle.source_link.source_role is SourceRole.PRIMARY
    assert bundle.source_link.is_primary_source is True
    assert bundle.source_record.provider == KMA_PROVIDER_NAME
    assert bundle.source_record.dataset_key == KMA_ULTRA_SHORT_GRID_DATASET_KEY
    assert bundle.source_record.source_entity_id == "60_127"


async def test_grid_to_weather_bundle_deterministic() -> None:
    """같은 격자+dataset은 항상 같은 ``feature_id`` (ADR-009), 다른 격자는 다른 id."""
    a = await grid_to_weather_bundle(
        55,
        124,
        35.1,
        129.0,
        dataset_key=KMA_ULTRA_SHORT_GRID_DATASET_KEY,
        name_label="기상청 초단기",
        fetched_at=_NOW,
    )
    b = await grid_to_weather_bundle(
        55,
        124,
        35.1,
        129.0,
        dataset_key=KMA_ULTRA_SHORT_GRID_DATASET_KEY,
        name_label="기상청 초단기",
        fetched_at=_NOW + timedelta(hours=5),
    )
    assert a.feature.feature_id == b.feature.feature_id

    other = await grid_to_weather_bundle(
        56,
        125,
        35.2,
        129.1,
        dataset_key=KMA_ULTRA_SHORT_GRID_DATASET_KEY,
        name_label="기상청 초단기",
        fetched_at=_NOW,
    )
    assert other.feature.feature_id != a.feature.feature_id


async def test_ultra_short_and_short_distinct_features_same_grid() -> None:
    """같은 격자라도 초단기/단기는 ``dataset_key``가 달라 **별개** feature·source."""
    ultra = await grid_to_weather_bundle(
        60,
        127,
        37.5665,
        126.9780,
        dataset_key=KMA_ULTRA_SHORT_GRID_DATASET_KEY,
        name_label="기상청 초단기",
        fetched_at=_NOW,
    )
    short = await grid_to_weather_bundle(
        60,
        127,
        37.5665,
        126.9780,
        dataset_key=KMA_SHORT_GRID_DATASET_KEY,
        name_label="기상청 단기",
        fetched_at=_NOW,
    )
    # 별개 feature_id + 별개 source_record_key
    assert ultra.feature.feature_id != short.feature.feature_id
    assert short.feature.feature_id  # non-empty
    assert ultra.source_record.dataset_key == KMA_ULTRA_SHORT_GRID_DATASET_KEY
    assert short.source_record.dataset_key == KMA_SHORT_GRID_DATASET_KEY
    assert (
        ultra.source_record.source_record_key != short.source_record.source_record_key
    )
    # 같은 격자 → 같은 natural_key·같은 좌표 (마커는 겹치지만 별개 feature)
    assert (
        ultra.source_record.source_entity_id
        == short.source_record.source_entity_id
        == "60_127"
    )
    assert ultra.feature.coord == short.feature.coord
    assert ultra.feature.name == "기상청 초단기 격자 60,127"
    assert short.feature.name == "기상청 단기 격자 60,127"

"""``test_infra_feature_repo`` — ``feature_repo`` param 빌더 + 결과 집계 (DB 무관).

DB 적재 경로는 ``tests/integration/test_feature_repo_load.py``(testcontainers).
본 모듈은 ``Feature``/``SourceRecord``/``SourceLink`` DTO → bind params 변환과
``FeatureLoadResult`` 기본값만 단위 검증 (coord None / detail None 분기 포함).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from krtour.map.dto import (
    Coordinate,
    Feature,
    PlaceDetail,
    SourceLink,
    SourceRecord,
)
from krtour.map.dto._enums import FeatureKind, SourceRole
from krtour.map.infra import feature_repo
from krtour.map.infra.feature_repo import (
    FeatureLoadResult,
    FeatureSearchRow,
    NearbyFeatureRow,
    _feature_params,
    _source_link_params,
    _source_record_params,
)

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 5, 29, 9, 0, tzinfo=_KST)


def _place(coord: Coordinate | None, detail: PlaceDetail | None) -> Feature:
    return Feature(
        feature_id="place:abc123",
        kind=FeatureKind.PLACE,
        name="홍대 카페",
        category="02020101",
        coord=coord,
        marker_icon="cafe",
        marker_color="P-03",
        detail=detail,
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_feature_params_with_coord_and_detail() -> None:
    feature = _place(
        Coordinate(lon=Decimal("126.92"), lat=Decimal("37.55")),
        PlaceDetail(feature_id="place:abc123", place_kind="cafe"),
    )
    params = _feature_params(feature)

    assert params["feature_id"] == "place:abc123"
    assert params["kind"] == "place"
    assert params["lon"] == 126.92
    assert params["lat"] == 37.55
    # detail/address/urls/raw_refs는 JSON 문자열 (CAST AS jsonb)
    assert isinstance(params["detail"], str)
    assert json.loads(params["detail"])["place_kind"] == "cafe"
    assert isinstance(params["address"], str)
    assert json.loads(params["raw_refs"]) == []
    assert params["status"] == "active"


def test_feature_params_without_coord_is_none() -> None:
    feature = _place(None, None)
    params = _feature_params(feature)

    assert params["lon"] is None
    assert params["lat"] is None
    # detail None이면 빈 JSONB 객체 문자열
    assert params["detail"] == "{}"


def test_source_record_params_serializes_raw_data() -> None:
    record = SourceRecord(
        source_record_key="sr_key1",
        provider="python-datagokr-api",
        dataset_key="cultural_festivals",
        source_entity_type="festival",
        source_entity_id="E001",
        raw_payload_hash="hash1",
        raw_data={"a": 1, "b": "값"},
        fetched_at=_NOW,
    )
    params = _source_record_params(record)

    assert params["source_record_key"] == "sr_key1"
    assert params["provider"] == "python-datagokr-api"
    loaded = json.loads(params["raw_data"])
    assert loaded == {"a": 1, "b": "값"}


def test_source_link_params_maps_enum_value() -> None:
    link = SourceLink(
        feature_id="place:abc123",
        source_record_key="sr_key1",
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
        created_at=_NOW,
    )
    params = _source_link_params(link)

    assert params["source_role"] == "primary"
    assert params["confidence"] == 100
    assert params["is_primary_source"] is True


def test_feature_load_result_defaults_zero() -> None:
    result = FeatureLoadResult()
    assert result.bundles_total == 0
    assert result.features_inserted == 0
    assert result.source_links_updated == 0


def test_module_exports_load_helpers() -> None:
    for name in (
        "load_bundle",
        "load_bundles",
        "upsert_feature",
        "get_feature_row",
        "features_nearby_poi_cache_target",
    ):
        assert hasattr(feature_repo, name)


def test_nearby_feature_sql_guards_required_lon_lat_contract() -> None:
    sql = feature_repo._NEARBY_TARGET_CTE_SQL

    assert "x_extension.ST_X(f.coord) AS lon" in sql
    assert "x_extension.ST_Y(f.coord) AS lat" in sql
    assert "f.coord IS NOT NULL" in sql
    assert "f.coord_5179 IS NOT NULL" in sql


def test_nearby_cursor_round_trips_distance_name_and_updated_at() -> None:
    row = NearbyFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="A first",
        category="06020000",
        status="active",
        lon=126.978,
        lat=37.5665,
        distance_m=12.5,
        primary_provider="python-opinet-api",
        primary_dataset_key="opinet_stations",
        last_updated_at=_NOW,
    )

    distance = feature_repo._encode_nearby_cursor(row, sort="distance")
    assert feature_repo._nearby_cursor_params(distance, sort="distance") == {
        "cursor_distance_m": 12.5,
        "cursor_name": None,
        "cursor_last_updated_at": None,
        "cursor_feature_id": "feature-1",
    }

    name = feature_repo._encode_nearby_cursor(row, sort="name")
    assert feature_repo._nearby_cursor_params(name, sort="name")[
        "cursor_name"
    ] == "A first"

    updated = feature_repo._encode_nearby_cursor(row, sort="last_updated_at")
    assert feature_repo._nearby_cursor_params(updated, sort="last_updated_at")[
        "cursor_last_updated_at"
    ] == _NOW


def test_nearby_cursor_rejects_malformed_or_wrong_sort() -> None:
    row = NearbyFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="A first",
        category="06020000",
        status="active",
        lon=126.978,
        lat=37.5665,
        distance_m=12.5,
        primary_provider=None,
        primary_dataset_key=None,
        last_updated_at=_NOW,
    )
    cursor = feature_repo._encode_nearby_cursor(row, sort="distance")

    with pytest.raises(ValueError, match="invalid nearby cursor"):
        feature_repo._nearby_cursor_params("not-base64", sort="distance")
    with pytest.raises(ValueError, match="invalid nearby cursor"):
        feature_repo._nearby_cursor_params(cursor, sort="name")


def test_feature_search_cursor_round_trips_score_and_id_modes() -> None:
    row = FeatureSearchRow(
        feature_id="feature-1",
        kind="place",
        name="경복궁",
        category="01070100",
        lon=126.977,
        lat=37.5796,
        marker_icon="monument",
        marker_color="P-01",
        status="active",
        score=0.95,
        score_cursor="0.9500000476837158",
    )

    score_cursor = feature_repo._encode_search_cursor(row, q_enabled=True)
    assert feature_repo._search_cursor_params(score_cursor, q_enabled=True) == {
        "cursor_score": "0.9500000476837158",
        "cursor_feature_id": "feature-1",
    }

    id_cursor = feature_repo._encode_search_cursor(row, q_enabled=False)
    assert feature_repo._search_cursor_params(id_cursor, q_enabled=False) == {
        "cursor_score": None,
        "cursor_feature_id": "feature-1",
    }

    with pytest.raises(ValueError, match="invalid feature search cursor"):
        feature_repo._search_cursor_params(score_cursor, q_enabled=False)


@pytest.mark.asyncio
async def test_features_nearby_target_validates_before_db_call() -> None:
    class _Session:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("validation should happen before DB execute")

    with pytest.raises(ValueError, match="sort must be one of"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            sort="bad",
        )
    with pytest.raises(ValueError, match="radius_km must be greater than 0"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            radius_km=0,
        )
    with pytest.raises(ValueError, match="limit must be greater than 0"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            limit=0,
        )


@pytest.mark.asyncio
async def test_search_features_validates_before_db_call() -> None:
    class _Session:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("validation should happen before DB execute")

    with pytest.raises(ValueError, match="q 또는 bbox"):
        await feature_repo.search_features(_Session())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="limit must be greater than 0"):
        await feature_repo.search_features(
            _Session(),  # type: ignore[arg-type]
            q="경복궁",
            limit=0,
        )
    with pytest.raises(ValueError, match="invalid bbox"):
        await feature_repo.search_features(
            _Session(),  # type: ignore[arg-type]
            bbox=(127, 37, 126, 38),
        )

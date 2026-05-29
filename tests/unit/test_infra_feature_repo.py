"""``test_infra_feature_repo`` — ``feature_repo`` param 빌더 + 결과 집계 (DB 무관).

DB 적재 경로는 ``tests/integration/test_feature_repo_load.py``(testcontainers).
본 모듈은 ``Feature``/``SourceRecord``/``SourceLink`` DTO → bind params 변환과
``FeatureLoadResult`` 기본값만 단위 검증 (coord None / detail None 분기 포함).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

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
    for name in ("load_bundle", "load_bundles", "upsert_feature", "get_feature_row"):
        assert hasattr(feature_repo, name)

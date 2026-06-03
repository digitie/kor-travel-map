"""offline upload parser 단위 테스트."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from krtour.map.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from krtour.map.dto import (
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from krtour.map.offline_upload import parse_offline_feature_bundles

pytestmark = pytest.mark.unit

_KST = timezone(timedelta(hours=9))
_FETCHED_AT = datetime(2026, 6, 3, 14, 0, tzinfo=_KST)


def test_parse_offline_feature_bundles_jsonl() -> None:
    bundle = _bundle("jsonl-001")
    payload = bundle.model_dump_json().encode("utf-8")

    parsed = parse_offline_feature_bundles(
        payload,
        detected_format="jsonl",
        detected_encoding="utf-8",
        original_filename="features.jsonl",
    )

    assert len(parsed) == 1
    assert parsed[0].feature.feature_id == bundle.feature.feature_id
    assert parsed[0].source_link.source_record_key == (
        bundle.source_record.source_record_key
    )


def test_parse_offline_feature_bundles_json_items() -> None:
    bundle = _bundle("json-001")
    payload = {"items": [bundle.model_dump(mode="json")]}

    parsed = parse_offline_feature_bundles(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        original_filename="features.json",
    )

    assert parsed[0].feature.name == "오프라인 테스트 장소"


def test_parse_offline_feature_bundles_rejects_csv_for_now() -> None:
    with pytest.raises(ValueError, match="JSON/JSONL FeatureBundle"):
        parse_offline_feature_bundles(
            b"name,lon,lat\nA,126.9,37.5\n",
            detected_format="csv",
            original_filename="features.csv",
        )


def _bundle(source_id: str) -> FeatureBundle:
    raw_payload = {
        "source_id": source_id,
        "name": "오프라인 테스트 장소",
        "lon": "126.9780",
        "lat": "37.5665",
    }
    payload_hash = make_payload_hash(raw_payload)
    source_record_key = make_source_record_key(
        provider="offline-test-provider",
        dataset_key="offline_jsonl",
        source_entity_type="offline_feature_bundle",
        source_entity_id=source_id,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code="1111010100",
        kind="place",
        category="02020101",
        source_type="offline_test",
        source_natural_key=source_id,
    )
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name="오프라인 테스트 장소",
        coord=Coordinate(lon=Decimal("126.9780"), lat=Decimal("37.5665")),
        category="02020101",
        marker_icon="marker",
        marker_color="P-01",
        detail=PlaceDetail(feature_id=feature_id, place_kind="offline_test"),
    )
    source_record = SourceRecord(
        provider="offline-test-provider",
        dataset_key="offline_jsonl",
        source_entity_type="offline_feature_bundle",
        source_entity_id=source_id,
        raw_payload_hash=payload_hash,
        raw_name=feature.name,
        raw_longitude=Decimal("126.9780"),
        raw_latitude=Decimal("37.5665"),
        raw_data=raw_payload,
        fetched_at=_FETCHED_AT,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="offline_upload",
        confidence=100,
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )

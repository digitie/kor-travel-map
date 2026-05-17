from __future__ import annotations

from krtour_map.enums import FeatureKind
from krtour_map.ids import make_feature_id, make_payload_hash, make_source_record_key


def test_payload_hash_is_stable_for_key_order_changes() -> None:
    first = make_payload_hash({"b": 2, "a": {"x": 1}})
    second = make_payload_hash({"a": {"x": 1}, "b": 2})

    assert first == second


def test_feature_id_normalizes_provider_alias_and_whitespace() -> None:
    first = make_feature_id(
        provider="pykma",
        source_type=" short forecast ",
        source_natural_key=" NX=60 NY=127 ",
        kind=FeatureKind.WEATHER,
        category="weather",
        legal_dong_code="1111010100",
        content_hash="same",
    )
    second = make_feature_id(
        provider="python-kma-api",
        source_type="short   forecast",
        source_natural_key="nx=60 ny=127",
        kind="weather",
        category="weather",
        legal_dong_code="1111010100",
        content_hash="same",
    )

    assert first == second
    assert first.startswith("f_1111010100_w_")


def test_source_record_key_changes_when_payload_hash_changes() -> None:
    first = make_source_record_key(
        provider="opinet",
        dataset_key="fuel_lowest_station",
        source_entity_type="price",
        source_entity_id="A0010207",
        raw_payload_hash="hash-a",
    )
    second = make_source_record_key(
        provider="opinet",
        dataset_key="fuel_lowest_station",
        source_entity_type="price",
        source_entity_id="A0010207",
        raw_payload_hash="hash-b",
    )

    assert first != second
    assert first.startswith("sr_")

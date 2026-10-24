"""full domain은 순서·실제 Geo/retire 입력과 aggregate 상한을 지킨다."""

from uuid import uuid4

import pytest

from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra import exclusive_provider_refresh as full
from tests.integration.test_scoped_provider_batch import _dataset_bundle


def _inputs():
    key = uuid4().hex
    bundles = [_dataset_bundle(key, uuid4().hex, str(i), hours=0) for i in range(2)]
    kwargs = dict(
        dataset_id=1,
        provider=bundles[0].source_record.provider,
        dataset_key=key,
        source_entity_type=bundles[0].source_record.source_entity_type,
        active_targets={uuid4(): 1},
    )
    return bundles, kwargs


def test_full_domain_preserves_input_order_and_binds_geo_retirement():
    bundles, kwargs = _inputs()
    original = full.exclusive_provider_snapshot_input_digest(bundles, **kwargs)
    assert original != full.exclusive_provider_snapshot_input_digest(reversed(bundles), **kwargs)
    assert original != full.exclusive_provider_snapshot_input_digest(
        bundles, **kwargs, retire_geometryless_areas=True
    )
    geo = GeoLoadContext(
        geo_applied=GeoApplied(reverse=True, geocode=False),
        current_dataset=DatasetRef(version_token="dv1-" + "a" * 32, data_token="dd1-" + "b" * 32),
        observed_data_tokens=frozenset({"dd1-" + "b" * 32}),
    )
    assert original != full.exclusive_provider_snapshot_input_digest(bundles, **kwargs, geo=geo)


def test_infinite_input_stops_at_max_plus_one_before_item_validation():
    bundles, kwargs = _inputs()
    consumed = 0

    def infinite():
        nonlocal consumed
        while True:
            consumed += 1
            yield bundles[0]

    with pytest.raises(ValueError, match="2730"):
        full.exclusive_provider_snapshot_input_digest(infinite(), **kwargs)
    assert consumed == 2731


def test_whole_byte_budget_precedes_raw_hash(monkeypatch):
    bundles, kwargs = _inputs()
    bundles[1].source_record.raw_data["huge"] = "x" * 1048577

    def forbidden(*args, **kwargs):
        raise AssertionError("raw hash executed before aggregate budget")

    monkeypatch.setattr(full, "make_payload_hash", forbidden)
    with pytest.raises(ValueError, match="1 MiB"):
        full.exclusive_provider_snapshot_input_digest(bundles, **kwargs)


def test_duplicate_entity_is_rejected():
    bundles, kwargs = _inputs()
    with pytest.raises(ValueError, match="duplicate"):
        full.exclusive_provider_snapshot_input_digest([bundles[0], bundles[0]], **kwargs)

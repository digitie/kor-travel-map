"""Rest opt-in만 검증한다. OFF는 IO0이고 같은 전체 installed receipt만 신뢰한다."""

import pytest

from kortravelmap.dagster import rest_snapshot_runtime as target


def test_off_requires_no_inventory_or_receipt_io(monkeypatch):
    monkeypatch.delenv("KOR_TRAVEL_MAP_REST_SNAPSHOT_ENABLED", raising=False)
    monkeypatch.setattr(
        target, "installed_airport_inventory", lambda: pytest.fail("OFF inventory read")
    )
    monkeypatch.setattr(target, "_RECEIPT", None)
    assert target.load_rest_snapshot_runtime() is None
    monkeypatch.setenv("KOR_TRAVEL_MAP_REST_SNAPSHOT_ENABLED", "0")
    assert target.load_rest_snapshot_runtime() is None


def test_on_verifies_shared_whole_installation_and_exact_rest_pins(monkeypatch, tmp_path):
    inventory = {
        "version": 1,
        "packages": {"kor-travel-map-dagster": {"rest_snapshot_runtime.py": "a" * 64}},
    }
    receipt = tmp_path / "shared-build-receipt.json"
    receipt.write_bytes(
        target._canonical({"version": 1, "code_revision": "c" * 40, "inventory": inventory})
    )
    monkeypatch.setenv("KOR_TRAVEL_MAP_REST_SNAPSHOT_ENABLED", "1")
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "c" * 40)
    monkeypatch.setattr(target, "_RECEIPT", receipt)
    monkeypatch.setattr(target, "installed_airport_inventory", lambda: inventory)
    pins = target.load_rest_snapshot_runtime().pins
    assert pins.dataset_key == "transport_rest_areas"
    assert pins.source_entity_type == "rest_area"
    assert pins.normalizer_revision == "transport-rest-area-name-phones-v1"
    inventory["version"] = 2
    with pytest.raises(RuntimeError, match="differs"):
        target.load_rest_snapshot_runtime()


@pytest.mark.parametrize("flag", ["true", "", "2"])
def test_ambiguous_opt_in_fails_closed(monkeypatch, flag):
    monkeypatch.setenv("KOR_TRAVEL_MAP_REST_SNAPSHOT_ENABLED", flag)
    with pytest.raises(RuntimeError, match="0 or 1"):
        target.load_rest_snapshot_runtime()

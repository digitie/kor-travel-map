"""운영 pin은 실제 설치본에서만 만들고 같은 버전의 파일 변경도 거부한다."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from kortravelmap.dagster import airport_snapshot_runtime as runtime


def _installed(monkeypatch, tmp_path):
    source = tmp_path / "module.py"
    source.write_text("original source")
    native = tmp_path / "module.so"
    native.write_bytes(b"compiled code")
    dist = SimpleNamespace(
        version="1.0",
        files=[PurePosixPath("module.py"), PurePosixPath("module.so")],
        locate_file=lambda relative: tmp_path / relative,
    )
    monkeypatch.setattr(runtime.importlib.metadata, "distribution", lambda name: dist)
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(runtime, "_RECEIPT", receipt)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    monkeypatch.setenv("KOR_TRAVEL_MAP_AIRPORT_SNAPSHOT_ENABLED", "1")
    runtime.write_airport_runtime_receipt(receipt)
    return source, native, receipt


def test_disabled_does_not_scan_packages_or_require_a_build_receipt(monkeypatch):
    monkeypatch.delenv("KOR_TRAVEL_MAP_AIRPORT_SNAPSHOT_ENABLED", raising=False)
    scan = Mock(side_effect=AssertionError("unexpected scan"))
    monkeypatch.setattr(runtime, "installed_airport_inventory", scan)
    assert runtime.load_airport_snapshot_runtime() is None
    scan.assert_not_called()


def test_real_source_pin_is_stable_and_rejects_same_version_code_drift(monkeypatch, tmp_path):
    source, _, _ = _installed(monkeypatch, tmp_path)
    first = runtime.load_airport_snapshot_runtime()
    assert first is not None
    assert first.pins.code_revision == "a" * 40
    inventory = runtime.installed_airport_inventory()
    assert (
        first.pins.sdk_inventory_sha256 == hashlib.sha256(runtime._canonical(inventory)).hexdigest()
    )
    assert runtime.load_airport_snapshot_runtime() == first
    source.write_text("modified source with unchanged distribution version")
    with pytest.raises(RuntimeError, match="differs"):
        runtime.load_airport_snapshot_runtime()


def test_native_dependency_drift_is_also_rejected(monkeypatch, tmp_path):
    _, native, _ = _installed(monkeypatch, tmp_path)
    native.write_bytes(b"modified native serializer")
    with pytest.raises(RuntimeError, match="differs"):
        runtime.load_airport_snapshot_runtime()


@pytest.mark.parametrize("revision", ["", "development", "a" * 39, "A" * 40])
def test_opt_in_rejects_unpinned_revision(monkeypatch, revision):
    monkeypatch.setenv("KOR_TRAVEL_MAP_AIRPORT_SNAPSHOT_ENABLED", "1")
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", revision)
    with pytest.raises(RuntimeError, match="immutable"):
        runtime.load_airport_snapshot_runtime()


def test_receipt_revision_mismatch_and_noncanonical_json_are_rejected(monkeypatch, tmp_path):
    _, _, receipt = _installed(monkeypatch, tmp_path)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "b" * 40)
    with pytest.raises(RuntimeError, match="differs"):
        runtime.load_airport_snapshot_runtime()
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    raw = receipt.read_bytes()
    receipt.chmod(0o644)
    receipt.write_bytes(raw.replace(b'"version":1', b'"version":true'))
    with pytest.raises(RuntimeError, match="differs"):
        runtime.load_airport_snapshot_runtime()


def test_installed_file_list_required_and_budget_checked_before_read(monkeypatch, tmp_path):
    source, _, _ = _installed(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "_MAX_BYTES", source.stat().st_size - 1)
    with pytest.raises(RuntimeError, match="budget"):
        runtime.installed_airport_inventory()
    monkeypatch.setattr(
        runtime.importlib.metadata, "distribution", lambda name: SimpleNamespace(files=None)
    )
    with pytest.raises(RuntimeError, match="file lists"):
        runtime.installed_airport_inventory()

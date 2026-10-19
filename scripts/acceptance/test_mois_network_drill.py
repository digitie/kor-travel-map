"""네트워크 조작 전에 소유 namespace를 검증한다."""

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "mois_drill", Path(__file__).with_name("mois_network_drill.py")
)
drill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drill)


@pytest.mark.parametrize("same_kind", ["net", "user"])
def test_reject_parent_namespace(monkeypatch, same_kind):
    monkeypatch.setattr(drill, "namespace", lambda kind: "parent" if kind == same_kind else "owned")
    monkeypatch.setattr(drill.os, "getuid", lambda: 0)
    with pytest.raises(RuntimeError, match="isolated namespace"):
        drill.guard("parent", "parent")


def test_reject_root_owner_mapping(monkeypatch):
    monkeypatch.setattr(drill, "namespace", lambda kind: "owned")
    monkeypatch.setattr(drill.os, "getuid", lambda: 0)
    monkeypatch.setattr(drill.Path, "read_text", lambda self: "0 0 1")
    with pytest.raises(RuntimeError, match="non-root owner"):
        drill.guard("parent", "parent")


def test_accept_owned_unprivileged_mapping(monkeypatch):
    monkeypatch.setattr(drill, "namespace", lambda kind: "owned")
    monkeypatch.setattr(drill.os, "getuid", lambda: 0)
    monkeypatch.setattr(drill.Path, "read_text", lambda self: "0 1000 1")
    drill.guard("parent", "parent")

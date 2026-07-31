"""Restore swap cache-target fence helper의 host DB 경계 테스트."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlsplit

import pytest

pytestmark = pytest.mark.unit


def _load_helper() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "fence-cache-target-restored-db.py"
    )
    spec = importlib.util.spec_from_file_location(
        "fence_cache_target_restored_db",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_restored_dsn_changes_only_database_and_preserves_encoded_credentials() -> None:
    helper = _load_helper()

    result = helper.restored_dsn(
        "postgresql+asyncpg://user%3Aname:p%40ss@127.0.0.1:55432/live",
        "live_restore",
    )
    parsed = urlsplit(result)

    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 55432
    assert unquote(parsed.username or "") == "user:name"
    assert unquote(parsed.password or "") == "p@ss"
    assert parsed.path == "/live_restore"


def test_restored_dsn_rejects_live_database_and_invalid_identifier() -> None:
    helper = _load_helper()
    dsn = "postgresql://user:password@127.0.0.1/live"

    with pytest.raises(ValueError, match="달라야"):
        helper.restored_dsn(dsn, "live")
    with pytest.raises(ValueError, match="식별자"):
        helper.restored_dsn(dsn, "bad/database")

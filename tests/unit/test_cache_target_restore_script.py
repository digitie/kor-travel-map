"""과거 restore cache-target host helper의 fail-close 정책 테스트."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

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


def test_restore_cache_target_helper_is_disabled_before_dsn_or_argument_handling(
    capsys: pytest.CaptureFixture[str],
) -> None:
    helper = _load_helper()

    assert helper.main(
        [
            "--restored-database",
            "bad/database",
            "--command-id",
            "not-an-integer",
            "--input-digest",
            "not-a-digest",
        ]
    )
    assert capsys.readouterr().err.startswith("restore cache-target fence is disabled")


def test_restore_cache_target_helper_has_no_live_dsn_or_mutation_import_surface() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "fence-cache-target-restored-db.py"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "KOR_TRAVEL_MAP_PG_DSN",
        "make_async_engine",
        "fence_restored_cache_target_streams",
        "list_cache_target_restore_references",
        "argparse",
    ):
        assert forbidden not in source

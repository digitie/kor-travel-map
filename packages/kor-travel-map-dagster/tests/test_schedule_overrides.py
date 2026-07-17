"""cron_for_schedule override lookup 단위 회귀(#613)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kortravelmap.dagster import schedule_overrides

REPO_ROOT = Path(__file__).resolve().parents[3]
DAGSTER_SRC = REPO_ROOT / "packages" / "kor-travel-map-dagster" / "src"
MAIN_SRC = REPO_ROOT / "src"
SENTINEL_PASSWORD = "schedule-override-secret-sentinel"


def _definitions_import(*, required: bool) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    python_path = [str(DAGSTER_SRC), str(MAIN_SRC)]
    if existing_python_path := environment.get("PYTHONPATH"):
        python_path.append(existing_python_path)
    environment["PYTHONPATH"] = os.pathsep.join(python_path)
    environment["KOR_TRAVEL_MAP_PG_DSN"] = (
        "postgresql+psycopg://schedule-test:"
        f"{SENTINEL_PASSWORD}@127.0.0.1:1/kor_travel_map"
    )
    if required:
        environment["KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED"] = "true"
    else:
        environment.pop(
            "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED",
            None,
        )
    return subprocess.run(
        [sys.executable, "-c", "import kortravelmap.dagster.definitions"],
        check=False,
        capture_output=True,
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        timeout=30,
    )


def _connection_with_rows(rows: list[tuple[str, str]]) -> MagicMock:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor_context = MagicMock()
    cursor = MagicMock()
    cursor_context.__enter__.return_value = cursor
    cursor.fetchall.return_value = rows
    connection.cursor.return_value = cursor_context
    return connection


def test_cron_for_schedule_prefers_db_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        schedule_overrides,
        "load_schedule_cron_overrides",
        lambda: {"sched_a": "5 4 * * *"},
    )
    # override가 있으면 DB 값을 쓴다.
    assert schedule_overrides.cron_for_schedule("sched_a", "0 0 * * *") == "5 4 * * *"
    # override가 없으면 코드 기본값으로 fallback한다.
    assert schedule_overrides.cron_for_schedule("sched_b", "0 0 * * *") == "0 0 * * *"


def test_load_schedule_cron_overrides_fails_closed_when_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_overrides.load_schedule_cron_overrides.cache_clear()
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED",
        "true",
    )

    def _raise_connect(*_args: object, **_kwargs: object) -> object:
        raise OSError("schedule override database unavailable")

    monkeypatch.setattr(schedule_overrides.psycopg, "connect", _raise_connect)
    with pytest.raises(OSError, match="database unavailable"):
        schedule_overrides.load_schedule_cron_overrides()
    schedule_overrides.load_schedule_cron_overrides.cache_clear()


def test_load_schedule_cron_overrides_uses_defaults_when_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_overrides.load_schedule_cron_overrides.cache_clear()
    monkeypatch.delenv(
        "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED",
        raising=False,
    )

    def _raise_connect(*_args: object, **_kwargs: object) -> object:
        raise OSError("schedule override database unavailable")

    monkeypatch.setattr(schedule_overrides.psycopg, "connect", _raise_connect)
    assert schedule_overrides.load_schedule_cron_overrides() == {}
    schedule_overrides.load_schedule_cron_overrides.cache_clear()


def test_load_schedule_cron_overrides_rejects_invalid_required_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_overrides.load_schedule_cron_overrides.cache_clear()
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED",
        "sometimes",
    )

    def _raise_connect(*_args: object, **_kwargs: object) -> object:
        raise OSError("schedule override database unavailable")

    monkeypatch.setattr(schedule_overrides.psycopg, "connect", _raise_connect)
    with pytest.raises(ValueError, match="must be a boolean value"):
        schedule_overrides.load_schedule_cron_overrides()
    schedule_overrides.load_schedule_cron_overrides.cache_clear()


def test_optional_failure_cache_is_shared_until_definitions_build_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schedule_overrides.load_schedule_cron_overrides.cache_clear()
    monkeypatch.delenv(
        "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED",
        raising=False,
    )
    calls = 0

    def _connect(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("schedule override database unavailable")
        return _connection_with_rows([("sched_a", "5 4 * * *")])

    monkeypatch.setattr(schedule_overrides.psycopg, "connect", _connect)
    assert schedule_overrides.load_schedule_cron_overrides() == {}
    assert schedule_overrides.load_schedule_cron_overrides() == {}
    assert calls == 1

    schedule_overrides.load_schedule_cron_overrides.cache_clear()
    assert schedule_overrides.load_schedule_cron_overrides() == {
        "sched_a": "5 4 * * *"
    }
    assert calls == 2
    schedule_overrides.load_schedule_cron_overrides.cache_clear()


def test_required_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    schedule_overrides.load_schedule_cron_overrides.cache_clear()
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED",
        "true",
    )
    calls = 0

    def _raise_connect(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise OSError("schedule override database unavailable")

    monkeypatch.setattr(schedule_overrides.psycopg, "connect", _raise_connect)
    for _ in range(2):
        with pytest.raises(OSError, match="database unavailable"):
            schedule_overrides.load_schedule_cron_overrides()
    assert calls == 2
    schedule_overrides.load_schedule_cron_overrides.cache_clear()


def test_definitions_import_fails_closed_without_override_storage() -> None:
    result = _definitions_import(required=True)

    assert result.returncode != 0
    assert "psycopg.OperationalError" in result.stderr
    assert SENTINEL_PASSWORD not in result.stdout
    assert SENTINEL_PASSWORD not in result.stderr


def test_definitions_import_uses_code_cron_when_override_storage_is_optional() -> None:
    result = _definitions_import(required=False)

    assert result.returncode == 0, result.stderr
    assert "using code defaults" in result.stderr
    assert SENTINEL_PASSWORD not in result.stdout
    assert SENTINEL_PASSWORD not in result.stderr

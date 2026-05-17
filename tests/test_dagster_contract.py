from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from krtour_map.dagster import (
    KST,
    default_identity,
    execution_from_config,
    json_ready,
    parse_logical_datetime,
    resolve_download_dir,
    schedule_requires_any_env,
    source_year_month_override_from_config,
)


def test_parse_logical_datetime_normalizes_to_kst() -> None:
    parsed = parse_logical_datetime("2026-05-17T00:00:00Z")

    assert parsed.tzinfo == KST
    assert parsed.hour == 9


def test_execution_from_config_rejects_unknown_run_type() -> None:
    with pytest.raises(ValueError):
        execution_from_config({"run_type": "daemon"})


def test_source_year_month_override_validates_yyyymm() -> None:
    assert source_year_month_override_from_config({"source_year_month": "202605"}) == "202605"

    with pytest.raises(ValueError):
        source_year_month_override_from_config({"source_year_month": "202613"})


def test_default_identity_uses_logical_time() -> None:
    execution = execution_from_config(
        {"run_type": "scheduled", "logical_datetime": "2026-05-17T09:30:00+09:00"}
    )

    identity = default_identity(None, "dataset", execution)

    assert identity.run_key == "20260517T093000"
    assert identity.run_type == "scheduled"
    assert identity.trigger_date == date(2026, 5, 17)


def test_json_ready_converts_common_result_values() -> None:
    @dataclass
    class Result:
        amount: Decimal
        when: datetime
        path: Path

    assert json_ready(
        Result(
            amount=Decimal("1.20"),
            when=datetime(2026, 5, 17, 0, 0, tzinfo=UTC),
            path=Path("x/y"),
        )
    ) == {
        "amount": "1.20",
        "when": "2026-05-17T00:00:00+00:00",
        "path": str(Path("x/y")),
    }


def test_dagster_path_and_schedule_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIPMATE_DAGSTER_DOWNLOAD_DIR", "/tmp/downloads")
    monkeypatch.setenv("TRIPMATE_KHOA_API_KEY", "key")

    assert resolve_download_dir("weather") == Path("/tmp/downloads/weather")
    assert schedule_requires_any_env("TRIPMATE_KHOA_API_KEY")()
    assert not schedule_requires_any_env("TRIPMATE_MISSING_KEY")()

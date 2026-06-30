"""cron_for_schedule override lookup 단위 회귀(#613)."""

from __future__ import annotations

import pytest

from kortravelmap.dagster import schedule_overrides


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

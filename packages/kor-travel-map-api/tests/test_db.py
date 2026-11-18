"""FastAPI DB engine 연결 정책 테스트."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kortravelmap.api import db as api_db


@pytest.mark.unit
def test_api_engine_disables_postgres_jit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """짧은 API OLTP query에만 JIT를 끄고 engine을 재사용한다."""
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_make_async_engine(dsn: object, **kwargs: object) -> object:
        captured["dsn"] = dsn
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(
        api_db,
        "KorTravelMapSettings",
        lambda: SimpleNamespace(pg_dsn="postgresql://example.invalid/db"),
    )
    monkeypatch.setattr(api_db, "make_async_engine", fake_make_async_engine)
    monkeypatch.setattr(api_db, "_prometheus_metrics", None)
    # cursor 이벤트는 지표 flag와 무관하게 걸린다(T-READ-02) — 가짜 engine에는 걸 곳이 없다.
    monkeypatch.setattr(api_db, "_instrument_engine_if_needed", lambda _engine: None)
    api_db.reset_engine()
    try:
        first = api_db._get_engine()
        second = api_db._get_engine()
    finally:
        api_db.reset_engine()

    assert first is sentinel
    assert second is sentinel
    assert captured["server_settings"] == {"jit": "off"}
    assert captured["poolclass"] is api_db.TimedAsyncQueuePool

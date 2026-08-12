"""API lifespan이 ADR-090 runtime DB privilege preflight를 **실제로** 건다는 보증.

preflight 함수 자체는 실 DB 통합 테스트(`tests/integration/
test_tvn34_runtime_privilege_preflight.py`)가 검증한다. 검증되지 않던 것은 **배선**이다 —
`create_app`의 lifespan에서 호출 자체를 지워도 api 1112건과 관련 unit이 전부 green이었다
(2026-08-12 적대 리뷰가 실제로 그 변이를 통과시켰다). 함수가 옳아도 아무도 부르지 않으면
경계는 없는 것과 같으므로, 여기서는 세 축만 고정한다.

1. flag가 꺼져 있으면(로컬 기본값) 부르지 않는다 — 로컬 기동에 DB를 요구하지 않는다.
2. flag가 켜져 있으면 runtime login 이름을 명시해 부른다.
3. preflight가 실패하면 **기동이 막힌다** — fail-closed. 여기가 핵심이다.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.db import RuntimeDbPrivilegeBoundaryError

from kortravelmap.api.app import create_app
from kortravelmap.api.settings import ApiSettings

_PREFLIGHT_ENV = "KOR_TRAVEL_MAP_RUNTIME_DB_PREFLIGHT_REQUIRED"


class _Recorder:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    async def __call__(self, engine: Any, *, expected_login: str) -> None:
        self.calls.append({"engine": engine, "expected_login": expected_login})
        if self._error is not None:
            raise self._error


def _install(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    from kortravelmap.api import app as app_module
    from kortravelmap.api import db as api_db

    async def _engine() -> object:
        return object()

    monkeypatch.setattr(api_db, "get_engine", _engine)
    monkeypatch.setattr(
        app_module, "assert_runtime_db_privilege_boundary", recorder
    )


@pytest.mark.unit
def test_lifespan_skips_preflight_when_not_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(_PREFLIGHT_ENV, raising=False)
    recorder = _Recorder()
    _install(monkeypatch, recorder)

    with TestClient(create_app(ApiSettings())):
        pass

    assert recorder.calls == []


@pytest.mark.unit
def test_lifespan_runs_preflight_with_the_api_runtime_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_PREFLIGHT_ENV, "true")
    recorder = _Recorder()
    _install(monkeypatch, recorder)

    with TestClient(create_app(ApiSettings())):
        pass

    assert [call["expected_login"] for call in recorder.calls] == [
        "ktm_feature_api_runtime"
    ]


@pytest.mark.unit
def test_lifespan_fails_closed_when_preflight_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_PREFLIGHT_ENV, "true")
    recorder = _Recorder(
        error=RuntimeDbPrivilegeBoundaryError("runtime login has raw state DML")
    )
    _install(monkeypatch, recorder)

    with (
        pytest.raises(RuntimeDbPrivilegeBoundaryError),
        TestClient(create_app(ApiSettings())),
    ):
        pass

    assert len(recorder.calls) == 1

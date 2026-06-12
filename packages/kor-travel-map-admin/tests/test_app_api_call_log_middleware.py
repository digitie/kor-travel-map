"""opt-in ``api_call_log`` 미들웨어 단위 테스트 (T-212c).

미들웨어가 DB 세션을 여는 ``_record_api_call_safe`` 헬퍼를 monkeypatch해 DB 없이
호출 캡처만 검증한다. ``api_call_log_enabled`` 기본 off일 때는 미들웨어 자체가
등록되지 않아 헬퍼가 호출되지 않음을 확인한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from kortravelmap.admin import app as app_mod
from kortravelmap.admin.app import create_app
from kortravelmap.admin.settings import AdminSettings


@pytest.mark.unit
def test_api_call_log_records_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    async def _capture(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(app_mod, "_record_api_call_safe", _capture)

    app = create_app(
        AdminSettings(api_call_log_enabled=True, features_routes_enabled=False)
    )
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200

    assert len(captured) == 1
    call = captured[0]
    assert call["method"] == "GET"
    assert call["path"] == "/health"
    assert call["status_code"] == 200
    assert "duration_ms" in call
    assert "request_id" in call


@pytest.mark.unit
def test_api_call_log_not_recorded_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    async def _capture(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(app_mod, "_record_api_call_safe", _capture)

    # 기본값 api_call_log_enabled=False → 미들웨어 미등록.
    app = create_app(AdminSettings(features_routes_enabled=False))
    client = TestClient(app)

    response = client.get("/health")
    assert response.status_code == 200
    assert captured == []

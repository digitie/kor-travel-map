"""``log_repo`` DB 무관 단위 테스트 (T-212c).

PostGIS 없이 raw SQL 분기/파라미터 조립 + cursor 인코딩을 검증한다 — 실제 SQL
실행은 ``tests/integration/test_log_repo.py``가 PostGIS에서 실측한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from kortravelmap.infra import log_repo as repo


class _Row:
    def __init__(self, data: dict[str, Any]) -> None:
        self.__dict__.update(data)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def one(self) -> _Row:
        assert len(self._rows) == 1
        return _Row(self._rows[0])

    def all(self) -> list[_Row]:
        return [_Row(row) for row in self._rows]


class _Session:
    def __init__(self, results: list[list[dict[str, Any]]]) -> None:
        self._results = results
        self.calls: list[dict[str, Any]] = []

    async def execute(self, statement: object, params: dict[str, Any]) -> _Result:
        self.calls.append({"sql": str(statement), "params": params})
        return _Result(self._results.pop(0))


_NOW = datetime(2026, 6, 7, 12, 0, tzinfo=UTC)


def _sys_row(**over: Any) -> dict[str, Any]:
    base = {
        "system_log_id": "11111111-1111-1111-1111-111111111111",
        "level": "info",
        "source": "offline_upload",
        "event": "upload_done",
        "message": "업로드 완료",
        "detail": {"count": 3},
        "request_id": "req-1",
        "created_at": _NOW,
    }
    base.update(over)
    return base


def _api_row(**over: Any) -> dict[str, Any]:
    base = {
        "api_call_log_id": "22222222-2222-2222-2222-222222222222",
        "method": "GET",
        "path": "/ops/metrics",
        "status_code": 200,
        "duration_ms": 12,
        "request_id": "req-2",
        "error_code": None,
        "created_at": _NOW,
    }
    base.update(over)
    return base


async def test_record_system_log_valid() -> None:
    session = _Session([[_sys_row()]])
    row = await repo.record_system_log(
        session,  # type: ignore[arg-type]
        level="info",
        source="offline_upload",
        event="upload_done",
        message="업로드 완료",
        detail={"count": 3},
        request_id="req-1",
    )
    assert row.system_log_id == "11111111-1111-1111-1111-111111111111"
    assert row.level == "info"
    assert row.detail == {"count": 3}
    # detail은 jsonb 문자열로 직렬화돼 파라미터에 들어간다.
    assert session.calls[0]["params"]["detail"] == '{"count":3}'


async def test_record_system_log_parses_json_string_detail() -> None:
    # detail이 jsonb 문자열로 돌아와도 dict로 역직렬화.
    session = _Session([[_sys_row(detail='{"count":7}')]])
    row = await repo.record_system_log(
        session,  # type: ignore[arg-type]
        level="info",
        source="admin",
        event="e",
        message="m",
        detail={"count": 7},
    )
    assert row.detail == {"count": 7}


async def test_record_system_log_invalid_level_raises() -> None:
    session = _Session([])
    with pytest.raises(ValueError, match="level must be one of"):
        await repo.record_system_log(
            session,  # type: ignore[arg-type]
            level="trace",
            source="admin",
            event="x",
            message="y",
        )
    # 검증 실패 → execute 호출 없음.
    assert session.calls == []


async def test_record_system_log_default_detail() -> None:
    session = _Session([[_sys_row(detail={})]])
    row = await repo.record_system_log(
        session,  # type: ignore[arg-type]
        level="warning",
        source="geocoding",
        event="reverse_fail",
        message="역지오코딩 실패",
    )
    assert row.detail == {}
    assert session.calls[0]["params"]["detail"] == "{}"
    assert session.calls[0]["params"]["request_id"] is None


async def test_record_api_call() -> None:
    session = _Session([[_api_row()]])
    row = await repo.record_api_call(
        session,  # type: ignore[arg-type]
        method="GET",
        path="/ops/metrics",
        status_code=200,
        duration_ms=12,
        request_id="req-2",
    )
    assert row.api_call_log_id == "22222222-2222-2222-2222-222222222222"
    assert row.status_code == 200
    assert row.duration_ms == 12
    assert row.error_code is None
    assert session.calls[0]["params"]["error_code"] is None


async def test_list_system_logs_filters_and_cursor() -> None:
    # page_size=1, 2 rows 반환 → next_cursor 존재, items 1건.
    session = _Session([[_sys_row(), _sys_row(system_log_id="33")]])
    page = await repo.list_system_logs(
        session,  # type: ignore[arg-type]
        level="info",
        source="offline_upload",
        q="완료",
        limit=1,
    )
    assert len(page.items) == 1
    assert page.next_cursor is not None
    params = session.calls[0]["params"]
    assert params["level"] == "info"
    assert params["source"] == "offline_upload"
    assert params["q_like"] == "%완료%"
    assert params["limit"] == 2  # page_size + 1


async def test_list_system_logs_no_extra_row_no_cursor() -> None:
    session = _Session([[_sys_row()]])
    page = await repo.list_system_logs(session, limit=10)  # type: ignore[arg-type]
    assert len(page.items) == 1
    assert page.next_cursor is None
    assert session.calls[0]["params"]["q_like"] is None


async def test_list_system_logs_invalid_cursor() -> None:
    with pytest.raises(ValueError, match="invalid system_logs cursor"):
        await repo.list_system_logs(
            _Session([]),  # type: ignore[arg-type]
            cursor="!!!not-base64!!!",
        )


async def test_list_api_call_logs_min_status_and_path() -> None:
    session = _Session([[_api_row(status_code=500), _api_row(api_call_log_id="44")]])
    page = await repo.list_api_call_logs(
        session,  # type: ignore[arg-type]
        method="GET",
        min_status=500,
        path="/ops",
        limit=1,
    )
    assert len(page.items) == 1
    assert page.next_cursor is not None
    params = session.calls[0]["params"]
    assert params["method"] == "GET"
    assert params["min_status"] == 500
    assert params["path_like"] == "%/ops%"


async def test_list_api_call_logs_invalid_cursor() -> None:
    with pytest.raises(ValueError, match="invalid api_call_logs cursor"):
        await repo.list_api_call_logs(
            _Session([]),  # type: ignore[arg-type]
            cursor="zzz",
        )


def test_cursor_round_trip() -> None:
    cursor = repo._encode_cursor("system_logs", at=_NOW, key="abc")
    at, key = repo._decode_cursor(cursor, kind="system_logs")
    assert at == _NOW
    assert key == "abc"


def test_decode_cursor_none() -> None:
    assert repo._decode_cursor(None, kind="system_logs") == (None, None)


def test_decode_cursor_wrong_kind() -> None:
    cursor = repo._encode_cursor("system_logs", at=_NOW, key="abc")
    with pytest.raises(ValueError, match="invalid api_call_logs cursor"):
        repo._decode_cursor(cursor, kind="api_call_logs")

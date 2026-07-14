"""``kortravelmap.infra.pipeline_repo`` cursor/입력 검증 단위 테스트 (ADR-064)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from kortravelmap.infra import pipeline_repo
from kortravelmap.infra.pipeline_repo import (
    PIPELINE_EXECUTION_KINDS,
    list_pipeline_executions,
)

pytestmark = pytest.mark.unit


class _NoQuerySession:
    """SQL 실행에 도달하면 안 되는 검증 경로 테스트용 세션."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("검증 실패 경로는 SQL을 실행하면 안 된다")


def test_execution_kinds_match_contract() -> None:
    assert PIPELINE_EXECUTION_KINDS == {"import_job", "update_request"}


def test_cursor_round_trip_preserves_keyset() -> None:
    at = datetime(2026, 7, 14, 12, 34, 56, 789000, tzinfo=UTC)
    cursor = pipeline_repo._encode_cursor(
        at=at, key="11111111-1111-1111-1111-111111111111"
    )

    decoded_at, decoded_key = pipeline_repo._decode_cursor(cursor)

    assert decoded_at == at
    assert decoded_key == "11111111-1111-1111-1111-111111111111"


def test_decode_cursor_none_returns_empty_keyset() -> None:
    assert pipeline_repo._decode_cursor(None) == (None, None)


@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64!!!",
        "aGVsbG8",  # base64지만 JSON 아님
    ],
)
def test_decode_cursor_rejects_malformed_values(cursor: str) -> None:
    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        pipeline_repo._decode_cursor(cursor)


def test_decode_cursor_rejects_foreign_kind() -> None:
    # 다른 목록(import_jobs 등)의 cursor를 흘려 넣으면 거부한다.
    import base64
    import json

    raw = json.dumps(
        {"v": 1, "kind": "import_jobs", "at": "2026-07-14T00:00:00+00:00", "key": "k"},
        separators=(",", ":"),
    ).encode("utf-8")
    foreign = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        pipeline_repo._decode_cursor(foreign)


async def test_list_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="kind must be one of"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            kind="dagster_run",
        )


async def test_list_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="limit must be greater than 0"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            limit=0,
        )


async def test_list_rejects_invalid_cursor_before_query() -> None:
    with pytest.raises(ValueError, match="pipeline_executions cursor"):
        await list_pipeline_executions(
            _NoQuerySession(),  # type: ignore[arg-type]
            cursor="broken",
        )

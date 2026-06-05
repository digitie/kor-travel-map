"""``poi_cache_target_repo`` keyset cursor 단위 테스트."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from krtour.map.infra.poi_cache_target_repo import (
    PoiCacheTargetPage,
    list_poi_cache_targets,
)


class _Result:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _Session:
    def __init__(self, *results: _Result) -> None:
        self._results = list(results)
        self.params: list[dict[str, Any]] = []

    async def execute(
        self,
        _statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        self.params.append(dict(params or {}))
        return self._results.pop(0)


def _row(target_id: str, *, at: datetime) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "external_system": "tripmate",
        "target_key": f"poi-{target_id[:8]}",
        "name": "서울시청",
        "lon": 126.978,
        "lat": 37.5665,
        "coord_precision_digits": 6,
        "coord_key": "126.978000:37.566500:p6",
        "radius_km": 5.0,
        "scope_mode": "center_radius",
        "update_enabled": True,
        "refresh_policy": "provider_default",
        "provider_overrides": "{}",
        "metadata": '{"tripmate_poi_id":"poi-1"}',
        "last_seen_at": at,
        "last_requested_at": None,
        "last_refreshed_at": None,
        "last_failed_at": None,
        "next_eligible_refresh_at": None,
        "deleted_at": None,
        "created_at": at,
        "updated_at": at,
    }


def _cursor(payload: object) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.mark.unit
async def test_list_poi_cache_targets_builds_next_cursor() -> None:
    at = datetime(2026, 6, 5, 12, 0, tzinfo=UTC)
    first_id = "11111111-1111-1111-1111-111111111111"
    second_id = "22222222-2222-2222-2222-222222222222"
    session = _Session(
        _Result([_row(first_id, at=at), _row(second_id, at=at)]),
        _Result([_row(second_id, at=at)]),
    )
    db = cast(Any, session)

    page = await list_poi_cache_targets(
        db,
        external_system="tripmate",
        update_enabled=True,
        include_deleted=False,
        limit=1,
    )
    assert isinstance(page, PoiCacheTargetPage)
    assert len(page.items) == 1
    assert page.items[0].target_id == first_id
    assert page.next_cursor is not None
    assert session.params[0]["limit_plus_one"] == 2
    assert session.params[0]["cursor_updated_at"] is None
    assert session.params[0]["cursor_target_id"] is None

    page2 = await list_poi_cache_targets(db, limit=1, cursor=page.next_cursor)

    assert len(page2.items) == 1
    assert page2.items[0].target_id == second_id
    assert session.params[1]["cursor_updated_at"] == at
    assert session.params[1]["cursor_target_id"] == first_id


@pytest.mark.unit
@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64",
        _cursor(["not", "mapping"]),
        _cursor({"v": 1, "kind": "wrong", "updated_at": "2026-06-05T00:00:00+00:00"}),
        _cursor(
            {
                "v": 1,
                "kind": "poi_cache_targets",
                "updated_at": "not-datetime",
                "target_id": "11111111-1111-1111-1111-111111111111",
            }
        ),
        _cursor(
            {
                "v": 1,
                "kind": "poi_cache_targets",
                "updated_at": "2026-06-05T00:00:00+00:00",
                "target_id": "not-uuid",
            }
        ),
    ],
)
async def test_list_poi_cache_targets_rejects_invalid_cursor(cursor: str) -> None:
    session = _Session()
    db = cast(Any, session)

    with pytest.raises(ValueError, match="invalid poi cache target cursor"):
        await list_poi_cache_targets(db, cursor=cursor)

    assert session.params == []

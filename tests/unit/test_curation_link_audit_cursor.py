"""curation unsafe-link 감사 cursor 계약."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from kortravelmap.infra.curation_repo import (
    decode_link_audit_cursor,
    encode_link_audit_cursor,
    list_unattributed_curation_links_page,
)

COLLECTION_ID = "11111111-1111-4111-8111-111111111111"
ITEM_ID = "22222222-2222-4222-8222-222222222222"
SECOND_ITEM_ID = "33333333-3333-4333-8333-333333333333"


class _Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _Rows:
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows


@pytest.mark.unit
def test_link_audit_cursor_round_trips_stable_total_order_key() -> None:
    cursor = encode_link_audit_cursor(COLLECTION_ID, ITEM_ID)

    assert COLLECTION_ID not in cursor
    assert ITEM_ID not in cursor
    assert decode_link_audit_cursor(cursor) == (COLLECTION_ID, ITEM_ID)


@pytest.mark.unit
@pytest.mark.parametrize(
    "cursor",
    [
        "not-base64***",
        "e30",
        "eyJ2IjoyfQ",
    ],
)
def test_link_audit_cursor_rejects_invalid_or_unknown_payload(cursor: str) -> None:
    with pytest.raises(ValueError, match="invalid curation link audit cursor"):
        decode_link_audit_cursor(cursor)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_link_audit_page_uses_limit_plus_one_and_last_visible_key() -> None:
    def row(item_id: str) -> dict[str, object]:
        return {
            "collection_id": COLLECTION_ID,
            "curation_item_id": item_id,
            "collection_key": "official:test",
            "external_item_id": item_id,
            "external_component_id": "primary",
            "feature_id": "feature:test",
            "place_name": "테스트",
            "address_hint": None,
            "match_basis": "legacy_unattributed",
            "resolver_version": "legacy",
            "decided_at": datetime(2026, 7, 31, tzinfo=UTC),
        }

    session = AsyncMock()
    session.execute.return_value = _Rows([row(ITEM_ID), row(SECOND_ITEM_ID)])

    rows, next_cursor = await list_unattributed_curation_links_page(
        session,
        limit=1,
    )

    assert [item.curation_item_id for item in rows] == [ITEM_ID]
    assert next_cursor is not None
    assert decode_link_audit_cursor(next_cursor) == (COLLECTION_ID, ITEM_ID)
    assert session.execute.await_args.args
    assert session.execute.await_args.args[1] == {
        "limit": 2,
        "cursor_collection_id": None,
        "cursor_curation_item_id": None,
    }

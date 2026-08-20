"""``curation_repo`` DB 비의존 계약·분기 단위 테스트."""

from __future__ import annotations

import base64
import json
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from kortravelmap.infra import curation_repo as repo

_COLLECTION_ID = "00000000-0000-4000-8000-000000000001"
_CURATION_ITEM_ID = "00000000-0000-4000-8000-000000000002"
_THEME_ID = "00000000-0000-4000-8000-000000000003"
_SOURCE_ID = "00000000-0000-4000-8000-000000000004"
_NOW = datetime(2026, 7, 13, 1, 2, 3, tzinfo=UTC)
_UNSET = object()


class _FakeResult:
    def __init__(
        self,
        *,
        rows: list[Any] | tuple[Any, ...] = (),
        scalar: Any = _UNSET,
        first: Any = _UNSET,
    ) -> None:
        self._rows = list(rows)
        self._scalar = scalar
        self._first = first

    def mappings(self) -> _FakeResult:
        return self

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any:
        if self._first is not _UNSET:
            return self._first
        return self._rows[0] if self._rows else None

    def one(self) -> Any:
        if not self._rows:
            raise AssertionError("fake result has no row")
        return self._rows[0]

    def scalar_one(self) -> Any:
        if self._scalar is _UNSET:
            raise AssertionError("fake result has no scalar")
        return self._scalar

    def scalar_one_or_none(self) -> Any:
        return None if self._scalar is _UNSET else self._scalar


class _FakeSession:
    def __init__(self, *results: _FakeResult) -> None:
        self._results = deque(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        statement: Any,
        params: Mapping[str, Any] | None = None,
    ) -> _FakeResult:
        self.calls.append((str(statement), dict(params or {})))
        if not self._results:
            raise AssertionError(f"unexpected execute: {statement}")
        return self._results.popleft()

    def assert_exhausted(self) -> None:
        assert not self._results


def _collection_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "collection_id": _COLLECTION_ID,
        "collection_key": "tourism-100:2025-2026",
        "theme_id": _THEME_ID,
        "theme_slug": "tourism-100",
        "theme_name": "한국관광 100선",
        "theme_group": "official",
        "source_id": _SOURCE_ID,
        "provider_dataset_id": 101,
        "provider": "python-mcst-api",
        "dataset_key": "tourism-100",
        "source_name": "문화체육관광부",
        "source_url": "https://example.test/source",
        "title": "2025~2026 한국관광 100선",
        "edition_key": "2025-2026",
        "description": "공식 목록",
        "status": "published",
        "visibility": "public",
        "metadata": {"official": True},
        "item_count": 2,
        "public_item_count": 1,
        "row_revision": 1,
        "created_by": "creator",
        "updated_by": "editor",
        "created_at": _NOW,
        "updated_at": _NOW,
        "archived_at": None,
    }
    row.update(overrides)
    return row


def _item_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "curation_item_id": _CURATION_ITEM_ID,
        "collection_id": _COLLECTION_ID,
        "collection_key": "tourism-100:2025-2026",
        "title": "2025~2026 한국관광 100선",
        "edition_key": "2025-2026",
        "theme_slug": "tourism-100",
        "theme_name": "한국관광 100선",
        "theme_group": "official",
        "provider_dataset_id": 101,
        "provider": "python-mcst-api",
        "dataset_key": "tourism-100",
        "source_name": "문화체육관광부",
        "source_url": "https://example.test/source",
        "feature_id": "feature:one",
        "feature_name": "테스트 장소",
        "feature_kind": "place",
        "feature_category": "01010100",
        "lon": 126.98,
        "lat": 37.56,
        "address": {"road": "서울"},
        "linked_feature_is_public": True,
        "source_record_key": "source-record:one",
        "external_item_id": "official:one",
        "external_component_id": "primary",
        "place_name": "테스트 장소",
        "address_hint": "서울",
        "source_present": True,
        "status": "included",
        "sort_order": 1,
        "item_title": "추천 장소",
        "item_summary": "요약",
        "curation_relation": "primary_stop",
        "reuse_policy": "allowed",
        "metadata": {"ordinal": 1},
        "row_revision": 1,
        "created_by": "creator",
        "updated_by": "editor",
        "created_at": _NOW,
        "updated_at": _NOW,
        "archived_at": None,
    }
    row.update(overrides)
    return row


def _feature_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "feature_id": "feature:one",
        "name": "테스트 장소",
        "kind": "place",
        "category": "01010100",
        "lon": 126.98,
        "lat": 37.56,
        "address": {"road": "서울"},
        "lifecycle_state": "active",
        "publication_state": "published",
        "quality_state": "valid",
    }
    row.update(overrides)
    return row


def _resolved_row(**overrides: Any) -> repo.ResolvedCurationImportRow:
    values: dict[str, Any] = {
        "row_number": 2,
        "collection_key": "tourism-100:2025-2026",
        "theme_slug": "tourism-100",
        "theme_name": "한국관광 100선",
        "theme_group": "official",
        "title": "2025~2026 한국관광 100선",
        "edition_key": "2025-2026",
        "provider_dataset_id": 101,
        "source_name": "문화체육관광부",
        "source_url": "https://example.test/source",
        "source_item_key": "official:one",
        "source_component_key": "primary",
        "feature_id": "feature:one",
        "place_name": "테스트 장소",
        "address_hint": "서울",
        "sort_order": 1,
        "item_title": None,
        "item_summary": None,
        "metadata": {"ordinal": 1},
    }
    values.update(overrides)
    return repo.ResolvedCurationImportRow(**values)


def _collection() -> repo.CurationCollection:
    return repo._collection(_collection_row())


def _item(**overrides: Any) -> repo.CurationItem:
    return repo._item(_item_row(**overrides))


def _encoded(value: Any) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_row_projection() -> None:
    collection = repo._collection(_collection_row(source_id=None, metadata='{"from_json":true}'))
    assert collection.source_id is None
    assert collection.metadata == {"from_json": True}

    linked = repo._item(_item_row())
    assert linked.feature_id == "feature:one"
    assert linked.lon == 126.98

    unresolved = repo._item(
        _item_row(
            feature_id=None,
            feature_name=None,
            feature_kind=None,
            feature_category=None,
            lon=None,
            lat=None,
            address=None,
            linked_feature_is_public=False,
        )
    )
    assert unresolved.feature_id is None
    assert unresolved.lon is None
    assert repo._object({"x": 1}) == {"x": 1}
    assert repo._object(1) == {}

    match = repo._feature_match(
        {"feature_id": "feature:one", "name": "장소", "address": None, "lon": None, "lat": None}
    )
    assert match.address == {}
    assert match.lon is None


def test_collection_and_group_cursor_round_trip_and_none() -> None:
    cursor = repo.encode_collection_cursor(_NOW, _COLLECTION_ID)
    assert repo.decode_collection_cursor(cursor) == (_NOW, _COLLECTION_ID)
    assert repo.decode_collection_cursor(None) is None

    group_cursor = repo.encode_group_cursor("feature:one")
    assert repo.decode_group_cursor(group_cursor) == "feature:one"
    assert repo.decode_group_cursor(None) is None


@pytest.mark.parametrize(
    "cursor",
    [
        "not-json",
        _encoded([]),
        _encoded({"updated_at": 1, "collection_id": _COLLECTION_ID}),
        _encoded({"updated_at": "2026-07-13T00:00:00", "collection_id": _COLLECTION_ID}),
        _encoded({"updated_at": _NOW.isoformat(), "collection_id": "not-a-uuid"}),
        _encoded({"updated_at": "", "collection_id": ""}),
    ],
)
def test_collection_cursor_rejects_invalid_payload(cursor: str) -> None:
    with pytest.raises(ValueError, match="invalid curation collection cursor"):
        repo.decode_collection_cursor(cursor)


@pytest.mark.parametrize("cursor", ["not-json", _encoded([]), _encoded({"feature_id": ""})])
def test_group_cursor_rejects_invalid_payload(cursor: str) -> None:
    with pytest.raises(ValueError, match="invalid curation group cursor"):
        repo.decode_group_cursor(cursor)


async def test_upsert_id_immediate_fallback_and_disappeared() -> None:
    immediate = _FakeSession(_FakeResult(scalar=_THEME_ID))
    assert (
        await repo._upsert_id_with_fallback(
            immediate,
            upsert_sql="SELECT 1",
            lookup_sql="SELECT 2",
            params={"key": "x"},
            entity="theme",
        )
        == _THEME_ID
    )
    assert len(immediate.calls) == 1

    fallback = _FakeSession(_FakeResult(scalar=None), _FakeResult(scalar=_THEME_ID))
    assert (
        await repo._upsert_id_with_fallback(
            fallback,
            upsert_sql="SELECT 1",
            lookup_sql="SELECT 2",
            params={},
            entity="theme",
        )
        == _THEME_ID
    )

    disappeared = _FakeSession(_FakeResult(scalar=None), _FakeResult(scalar=None))
    with pytest.raises(RuntimeError, match="concurrent theme upsert row disappeared"):
        await repo._upsert_id_with_fallback(
            disappeared,
            upsert_sql="SELECT 1",
            lookup_sql="SELECT 2",
            params={},
            entity="theme",
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"status": "bad"}, "status"),
        ({"visibility": "bad"}, "visibility"),
    ],
)
async def test_list_collections_rejects_invalid_filters(
    kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await repo.list_curation_collections(_FakeSession(), **kwargs)


async def test_list_collections_applies_filters_clamps_limit_and_pages() -> None:
    first = _collection_row(collection_id=_COLLECTION_ID)
    second = _collection_row(collection_id="00000000-0000-4000-8000-000000000099")
    session = _FakeSession(_FakeResult(rows=[first, second]))
    page, cursor = await repo.list_curation_collections(
        session,
        status="published",
        visibility="public",
        theme_slug="tourism-100",
        edition_key="2025-2026",
        provider_dataset_id=101,
        q="  관광  ",
        include_archived=True,
        limit=1,
    )
    assert len(page) == 1
    assert cursor is not None
    assert repo.decode_collection_cursor(cursor) == (_NOW, _COLLECTION_ID)
    assert session.calls[0][1]["q"] == "%관광%"
    assert session.calls[0][1]["limit"] == 2

    empty = _FakeSession(_FakeResult(rows=[]))
    assert await repo.list_curation_collections(empty, q="  ", limit=0) == ((), None)
    assert empty.calls[0][1]["q"] is None
    assert empty.calls[0][1]["limit"] == 2


async def test_get_collection_found_missing_and_public_projection() -> None:
    missing = _FakeSession(_FakeResult(rows=[]))
    assert await repo.get_curation_collection(missing, collection_id=_COLLECTION_ID) is None

    found = _FakeSession(
        _FakeResult(rows=[_collection_row()]),
        _FakeResult(rows=[]),
    )
    result = await repo.get_curation_collection(
        found,
        collection_id=_COLLECTION_ID,
        include_archived=True,
        public_only=True,
    )
    assert result is not None
    assert result[0].collection_id == _COLLECTION_ID
    assert result[1] == ()
    assert found.calls[0][1]["public_only"] is True
    assert found.calls[1][1]["public_only"] is True


def test_public_projection_excludes_archived_parent_catalog() -> None:
    public_sql = (
        repo._LIST_COLLECTIONS_SQL,
        repo._GET_COLLECTION_SQL,
        repo._GET_COLLECTION_BY_KEY_SQL,
        repo._LIST_COLLECTION_ITEMS_SQL,
        repo._LIST_FEATURE_ITEMS_SQL,
        repo._LIST_FEATURE_ITEMS_BATCH_SQL,
        repo._LIST_GROUP_KEYS_SQL,
    )

    assert all("archived_at IS NULL" in statement for statement in public_sql)
    assert all("source_id IS NULL" in statement for statement in public_sql)


async def test_get_item_found_and_missing() -> None:
    found = _FakeSession(_FakeResult(rows=[_item_row()]))
    item = await repo.get_curation_item(
        found,
        collection_id=_COLLECTION_ID,
        curation_item_id=_CURATION_ITEM_ID,
    )
    assert item is not None
    assert item.feature_id == "feature:one"

    missing = _FakeSession(_FakeResult(rows=[]))
    assert (
        await repo.get_curation_item(
            missing,
            collection_id=_COLLECTION_ID,
            curation_item_id=_CURATION_ITEM_ID,
        )
        is None
    )


async def test_lock_and_touch_collection_execute_contract() -> None:
    locked = _FakeSession(_FakeResult(first=(object(),)), _FakeResult())
    assert await repo._lock_collection(locked, _COLLECTION_ID)
    await repo._touch_collection(locked, collection_id=_COLLECTION_ID, actor="admin")
    locked.assert_exhausted()
    assert locked.calls[1][1] == {"collection_id": _COLLECTION_ID, "actor": "admin"}

    missing = _FakeSession(_FakeResult(first=None))
    assert not await repo._lock_collection(missing, _COLLECTION_ID)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "bad"},
        {"visibility": "bad"},
        {"collection_key": " "},
        {"title": " "},
    ],
)
async def test_create_collection_validates_state_and_required_text(kwargs: dict[str, Any]) -> None:
    values = {
        "collection_key": "key",
        "theme_id": _THEME_ID,
        "source_id": _SOURCE_ID,
        "title": "title",
        **kwargs,
    }
    with pytest.raises(ValueError, match="invalid|required"):
        await repo.create_curation_collection(_FakeSession(), **values)


async def test_create_collection_normalizes_and_returns_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession(
        _FakeResult(),
        _FakeResult(),
        _FakeResult(scalar=_COLLECTION_ID),
    )
    get_collection = AsyncMock(return_value=(_collection(), ()))
    monkeypatch.setattr(repo, "get_curation_collection", get_collection)

    created = await repo.create_curation_collection(
        session,
        collection_key="  collection:key  ",
        theme_id=_THEME_ID,
        source_id=None,
        title="  제목  ",
        edition_key="  2026  ",
        metadata={"x": 1},
        actor="admin",
    )
    assert created.collection_id == _COLLECTION_ID
    assert "pg_advisory_xact_lock" in session.calls[0][0]
    assert "curation-import" in session.calls[0][0]
    assert session.calls[1][1] == {"collection_keys": ["collection:key"]}
    params = session.calls[2][1]
    assert params["collection_key"] == "collection:key"
    assert params["title"] == "제목"
    assert params["edition_key"] == "2026"
    assert json.loads(params["metadata"]) == {"x": 1}


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"unknown": 1}, "unsupported"),
        ({"status": "bad"}, "status"),
        ({"visibility": "bad"}, "visibility"),
    ],
)
async def test_update_collection_rejects_invalid_fields(
    updates: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await repo.update_curation_collection(
            _FakeSession(), collection_id=_COLLECTION_ID, updates=updates
        )


async def test_update_collection_noop_missing_and_all_field_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_collection = AsyncMock(return_value=(_collection(), ()))
    monkeypatch.setattr(repo, "get_curation_collection", get_collection)
    assert (
        await repo.update_curation_collection(
            _FakeSession(), collection_id=_COLLECTION_ID, updates={}
        )
        == _collection()
    )
    get_collection.return_value = None
    assert (
        await repo.update_curation_collection(
            _FakeSession(), collection_id=_COLLECTION_ID, updates={}
        )
        is None
    )

    get_collection.return_value = (_collection(), ())
    updated_session = _FakeSession(_FakeResult(first=(_COLLECTION_ID,)))
    updated = await repo.update_curation_collection(
        updated_session,
        collection_id=_COLLECTION_ID,
        updates={
            "theme_id": _THEME_ID,
            "source_id": None,
            "title": "변경",
            "edition_key": "2027",
            "description": None,
            "status": "archived",
            "visibility": "admin_only",
            "metadata": {"changed": True},
            "updated_by": "admin",
        },
    )
    assert updated is not None
    sql, params = updated_session.calls[0]
    assert "metadata = CAST(:metadata AS jsonb)" in sql
    assert params["archive"] is True
    assert params["unarchive"] is False
    assert json.loads(params["metadata"]) == {"changed": True}

    missing_session = _FakeSession(_FakeResult(first=None))
    assert (
        await repo.update_curation_collection(
            missing_session,
            collection_id=_COLLECTION_ID,
            updates={"status": "draft"},
        )
        is None
    )
    assert missing_session.calls[0][1]["unarchive"] is True


async def test_archive_collection_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    update = AsyncMock(return_value=_collection())
    monkeypatch.setattr(repo, "update_curation_collection", update)
    archived = await repo.archive_curation_collection(
        _FakeSession(), collection_id=_COLLECTION_ID, actor="admin"
    )
    assert archived is not None
    assert update.await_args.kwargs["updates"] == {
        "status": "archived",
        "updated_by": "admin",
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": "bad"},
        {"curation_relation": "bad"},
        {"reuse_policy": "bad"},
        {"sort_order": -1},
        {"sort_order": 2_147_483_648},
        {"external_item_id": " "},
        {"external_component_id": " "},
    ],
)
async def test_add_item_rejects_invalid_input(kwargs: dict[str, Any]) -> None:
    values = {
        "collection_id": _COLLECTION_ID,
        "feature_id": None,
        "external_item_id": "external",
        "place_name": "장소",
        **kwargs,
    }
    with pytest.raises(ValueError, match="invalid"):
        await repo.add_curation_item(_FakeSession(), **values)


async def test_add_item_rejects_missing_collection_and_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = AsyncMock(return_value=False)
    monkeypatch.setattr(repo, "_lock_collection", lock)
    with pytest.raises(LookupError, match="collection"):
        await repo.add_curation_item(
            _FakeSession(),
            collection_id=_COLLECTION_ID,
            feature_id=None,
            external_item_id="external",
            place_name="장소",
        )

    lock.return_value = True
    with pytest.raises(ValueError, match="place_name"):
        await repo.add_curation_item(
            _FakeSession(),
            collection_id=_COLLECTION_ID,
            feature_id=None,
            external_item_id="external",
        )


async def test_add_item_rejects_hidden_feature_duplicate_target_and_archived_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "_lock_collection", AsyncMock(return_value=True))
    hidden = _FakeSession(_FakeResult(scalar=None))
    with pytest.raises(ValueError, match="active Feature"):
        await repo.add_curation_item(
            hidden,
            collection_id=_COLLECTION_ID,
            feature_id="feature:hidden",
            external_item_id="external",
        )

    duplicate_target = _FakeSession(
        _FakeResult(scalar="Feature 이름"),
        _FakeResult(scalar=None),
        _FakeResult(scalar=1),
    )
    with pytest.raises(ValueError, match="다른 component가 이미"):
        await repo.add_curation_item(
            duplicate_target,
            collection_id=_COLLECTION_ID,
            feature_id="feature:one",
            external_item_id="external",
            external_component_id="component-02",
        )

    archived_identity = _FakeSession(_FakeResult(scalar=1))
    with pytest.raises(ValueError, match="archive된"):
        await repo.add_curation_item(
            archived_identity,
            collection_id=_COLLECTION_ID,
            feature_id=None,
            external_item_id="external",
            place_name="장소",
        )


@pytest.mark.parametrize(
    ("feature_id", "inserted"),
    [("feature:one", True), (None, False)],
)
async def test_add_item_success_normalizes_and_touches_collection(
    monkeypatch: pytest.MonkeyPatch,
    feature_id: str | None,
    inserted: bool,
) -> None:
    monkeypatch.setattr(repo, "_lock_collection", AsyncMock(return_value=True))
    touch = AsyncMock()
    monkeypatch.setattr(repo, "_touch_collection", touch)
    prefix = (
        [
            _FakeResult(scalar="DB Feature 이름"),
            _FakeResult(scalar=None),
            _FakeResult(scalar=None),
        ]
        if feature_id is not None
        else [_FakeResult(scalar=None)]
    )
    results = [
        *prefix,
        _FakeResult(
            rows=[
                {
                    "curation_item_id": _CURATION_ITEM_ID,
                    "inserted": inserted,
                }
            ]
        ),
        _FakeResult(rows=[{"decision_id": None, "feature_id": None}]),
    ]
    if feature_id is not None:
        results.extend(
            [
                _FakeResult(scalar="00000000-0000-4000-8000-000000000099"),
                _FakeResult(),
            ]
        )
    results.append(_FakeResult(rows=[_item_row(feature_id=feature_id)]))
    session = _FakeSession(*results)
    item, was_inserted = await repo.add_curation_item(
        session,
        collection_id=_COLLECTION_ID,
        feature_id=feature_id,
        external_item_id="  external  ",
        external_component_id="  component-01  ",
        place_name=None if feature_id else "  직접 장소  ",
        address_hint="  서울  ",
        metadata={"x": 1},
        actor="admin",
    )
    assert was_inserted is inserted
    assert item.curation_item_id == _CURATION_ITEM_ID
    upsert_params = next(
        params
        for sql, params in session.calls
        if "INSERT INTO feature.curation_items" in sql
    )
    assert upsert_params["external_item_id"] == "external"
    assert upsert_params["external_component_id"] == "component-01"
    assert upsert_params["place_name"] == ("DB Feature 이름" if feature_id else "직접 장소")
    assert upsert_params["address_hint"] == "서울"
    touch.assert_awaited_once()


async def _update_item_with_current(
    monkeypatch: pytest.MonkeyPatch,
    *,
    updates: Mapping[str, Any],
    results: tuple[_FakeResult, ...] = (),
    actor: str | None = None,
) -> repo.CurationItem | None:
    monkeypatch.setattr(repo, "_lock_collection", AsyncMock(return_value=True))
    monkeypatch.setattr(repo, "get_curation_item", AsyncMock(return_value=_item()))
    return await repo.update_curation_item(
        _FakeSession(*results),
        collection_id=_COLLECTION_ID,
        curation_item_id=_CURATION_ITEM_ID,
        updates=updates,
        actor=actor,
    )


async def test_update_item_returns_none_for_missing_collection_or_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "_lock_collection", AsyncMock(return_value=False))
    assert (
        await repo.update_curation_item(
            _FakeSession(),
            collection_id=_COLLECTION_ID,
            curation_item_id=_CURATION_ITEM_ID,
            updates={},
        )
        is None
    )

    monkeypatch.setattr(repo, "_lock_collection", AsyncMock(return_value=True))
    monkeypatch.setattr(repo, "get_curation_item", AsyncMock(return_value=None))
    assert (
        await repo.update_curation_item(
            _FakeSession(),
            collection_id=_COLLECTION_ID,
            curation_item_id=_CURATION_ITEM_ID,
            updates={},
        )
        is None
    )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"unknown": 1}, "unsupported"),
        ({"status": "bad"}, "status"),
        ({"curation_relation": "bad"}, "relation"),
        ({"reuse_policy": "bad"}, "reuse"),
        ({"sort_order": -1}, "sort order"),
        ({"sort_order": 2_147_483_648}, "sort order"),
        ({"sort_order": "1"}, "sort order"),
        ({"external_item_id": " "}, "external_item_id"),
        ({"external_component_id": " "}, "external_component_id"),
        ({"place_name": None}, "place_name"),
        ({"metadata": []}, "metadata"),
    ],
)
async def test_update_item_rejects_invalid_fields(
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        await _update_item_with_current(monkeypatch, updates=updates)


async def test_update_item_rejects_missing_feature_duplicate_target_and_archived_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="Feature가 없습니다"):
        await _update_item_with_current(
            monkeypatch,
            updates={"feature_id": "feature:missing"},
            results=(_FakeResult(scalar=None),),
        )

    with pytest.raises(ValueError, match="다른 component가 이미"):
        await _update_item_with_current(
            monkeypatch,
            updates={"external_component_id": "component-02"},
            results=(_FakeResult(scalar=None), _FakeResult(scalar=1)),
        )

    with pytest.raises(ValueError, match="identity는 재사용"):
        await _update_item_with_current(
            monkeypatch,
            updates={"external_item_id": "archived"},
            results=(_FakeResult(scalar=1),),
        )


async def test_update_item_noop_update_miss_and_full_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current = _item()
    monkeypatch.setattr(repo, "_lock_collection", AsyncMock(return_value=True))
    get_item = AsyncMock(return_value=current)
    monkeypatch.setattr(repo, "get_curation_item", get_item)

    noop = _FakeSession(_FakeResult(scalar=None))
    assert (
        await repo.update_curation_item(
            noop,
            collection_id=_COLLECTION_ID,
            curation_item_id=_CURATION_ITEM_ID,
            updates={},
        )
        == current
    )
    get_item.return_value = _item(status="archived", archived_at=_NOW)
    assert (
        await repo.update_curation_item(
            _FakeSession(),
            collection_id=_COLLECTION_ID,
            curation_item_id=_CURATION_ITEM_ID,
            updates={},
        )
        is None
    )
    get_item.return_value = current

    update_miss = _FakeSession(_FakeResult(scalar=None), _FakeResult(first=None))
    assert (
        await repo.update_curation_item(
            update_miss,
            collection_id=_COLLECTION_ID,
            curation_item_id=_CURATION_ITEM_ID,
            updates={"address_hint": "  "},
        )
        is None
    )

    final_item = _item(status="archived", archived_at=_NOW)
    get_item.side_effect = [current, final_item]
    touch = AsyncMock()
    monkeypatch.setattr(repo, "_touch_collection", touch)
    success = _FakeSession(
        _FakeResult(scalar=1),
        _FakeResult(scalar=None),
        _FakeResult(scalar=None),
        _FakeResult(first=(_CURATION_ITEM_ID,)),
        _FakeResult(scalar="00000000-0000-4000-8000-000000000099"),
        _FakeResult(),
        _FakeResult(),
    )
    updated = await repo.update_curation_item(
        success,
        collection_id=_COLLECTION_ID,
        curation_item_id=_CURATION_ITEM_ID,
        updates={
            "feature_id": "feature:two",
            "source_record_key": None,
            "external_item_id": "  changed  ",
            "place_name": "  변경 장소  ",
            "address_hint": "  부산  ",
            "status": "archived",
            "sort_order": 3,
            "item_title": "제목",
            "item_summary": None,
            "curation_relation": "nearby_option",
            "reuse_policy": "manual_review",
            "metadata": {"changed": True},
        },
        actor="admin",
    )
    assert updated == final_item
    assert "FOR KEY SHARE" in success.calls[0][0]
    sql, params = success.calls[3]
    assert "archived_at = now()" in sql
    assert params["external_item_id"] == "changed"
    assert params["place_name"] == "변경 장소"
    assert params["address_hint"] == "부산"
    assert json.loads(params["metadata"]) == {"changed": True}
    touch.assert_awaited_once()


async def test_update_item_allows_source_absent_but_rejects_archived_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "_lock_collection", AsyncMock(return_value=True))
    source_absent = _item(source_present=False)
    archived = _item(status="archived", archived_at=_NOW)
    get_item = AsyncMock(side_effect=[source_absent, archived, archived])
    monkeypatch.setattr(repo, "get_curation_item", get_item)
    touch = AsyncMock()
    monkeypatch.setattr(repo, "_touch_collection", touch)

    session = _FakeSession(
        _FakeResult(first=(_CURATION_ITEM_ID,)),
        _FakeResult(),
    )
    result = await repo.update_curation_item(
        session,
        collection_id=_COLLECTION_ID,
        curation_item_id=_CURATION_ITEM_ID,
        updates={"status": "archived"},
    )
    assert result == archived
    assert get_item.await_args_list[0].kwargs["include_archived"] is True
    touch.assert_awaited_once()

    assert (
        await repo.update_curation_item(
            _FakeSession(),
            collection_id=_COLLECTION_ID,
            curation_item_id=_CURATION_ITEM_ID,
            updates={"status": "included"},
        )
        is None
    )


async def test_archive_item_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    update = AsyncMock(return_value=_item(status="archived"))
    monkeypatch.setattr(repo, "update_curation_item", update)
    archived = await repo.archive_curation_item(
        _FakeSession(),
        collection_id=_COLLECTION_ID,
        curation_item_id=_CURATION_ITEM_ID,
        actor="admin",
    )
    assert archived is not None
    assert update.await_args.kwargs["updates"] == {"status": "archived"}


async def test_get_feature_group_missing_empty_and_success() -> None:
    missing = _FakeSession(_FakeResult(rows=[]))
    assert await repo.get_feature_curation_group(missing, feature_id="feature:one") is None

    empty = _FakeSession(_FakeResult(rows=[_feature_row()]), _FakeResult(rows=[]))
    assert await repo.get_feature_curation_group(empty, feature_id="feature:one") is None

    success = _FakeSession(
        _FakeResult(rows=[_feature_row(lon=None, lat=None, address='{"road":"서울"}')]),
        _FakeResult(rows=[_item_row()]),
    )
    group = await repo.get_feature_curation_group(
        success, feature_id="feature:one", public_only=False
    )
    assert group is not None
    assert group.lon is None
    assert group.address == {"road": "서울"}
    assert len(group.curations) == 1


async def test_list_items_by_feature_ids_empty_deduplicates_and_groups() -> None:
    assert await repo.list_curation_items_by_feature_ids(_FakeSession(), feature_ids=[]) == {}

    session = _FakeSession(
        _FakeResult(rows=[_item_row(), _item_row(feature_id=None, feature_name=None)])
    )
    grouped = await repo.list_curation_items_by_feature_ids(
        session,
        feature_ids=["feature:one", "feature:one"],
        public_only=False,
    )
    assert list(grouped) == ["feature:one"]
    assert session.calls[0][1]["feature_ids"] == ["feature:one"]


async def test_list_feature_groups_validates_bbox_and_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="provided together"):
        await repo.list_feature_curation_groups(_FakeSession(), min_lon=126.0)

    items_by_feature = AsyncMock(return_value={"feature:one": (_item(),)})
    monkeypatch.setattr(repo, "list_curation_items_by_feature_ids", items_by_feature)
    session = _FakeSession(
        _FakeResult(rows=[{"feature_id": "feature:one"}, {"feature_id": "feature:two"}]),
        _FakeResult(rows=[_feature_row()]),
    )
    groups, cursor = await repo.list_feature_curation_groups(
        session,
        public_only=False,
        theme_slug="tourism-100",
        edition_key="2025-2026",
        provider_dataset_id=101,
        q="  관광  ",
        min_lon=126.0,
        min_lat=37.0,
        max_lon=127.0,
        max_lat=38.0,
        page_size=1,
    )
    assert len(groups) == 1
    assert cursor is not None
    assert repo.decode_group_cursor(cursor) == "feature:one"
    assert session.calls[0][1]["bbox_enabled"] is True
    assert session.calls[0][1]["q"] == "%관광%"

    items_by_feature.return_value = {}
    missing_feature = _FakeSession(
        _FakeResult(rows=[{"feature_id": "feature:missing"}]),
        _FakeResult(rows=[]),
    )
    groups, cursor = await repo.list_feature_curation_groups(missing_feature, page_size=10, q=" ")
    assert groups == ()
    assert cursor is None

    empty = _FakeSession(_FakeResult(rows=[]))
    assert await repo.list_feature_curation_groups(empty) == ((), None)


async def test_resolve_feature_matches_empty_batch_and_single() -> None:
    assert await repo.resolve_feature_matches(_FakeSession(), requests=[]) == {}

    session = _FakeSession(
        _FakeResult(
            rows=[
                {
                    "row_number": 2,
                    "feature_id": "feature:one",
                    "name": "장소",
                    "address": {"road": "서울"},
                    "lon": 126.0,
                    "lat": 37.0,
                }
            ]
        )
    )
    requests = (
        repo.FeatureMatchRequest(2, " feature:one ", None, None),
        repo.FeatureMatchRequest(3, None, " 장소 ", " 서울 "),
    )
    matches = await repo.resolve_feature_matches(session, requests=requests)
    assert matches[2][0].feature_id == "feature:one"
    assert matches[3] == ()
    payload = json.loads(session.calls[0][1]["requests"])
    assert payload[0]["feature_id"] == "feature:one"
    assert payload[1]["place_name"] == "장소"
    assert payload[1]["address_hint"] == "서울"

    single = _FakeSession(_FakeResult(rows=[]))
    assert (
        await repo.resolve_feature_match(
            single, feature_id=None, place_name="없는 장소", address_hint=None
        )
        == ()
    )


async def test_upsert_theme_requires_an_exact_retained_catalog_match() -> None:
    for values in [("", "이름", "그룹"), ("slug", "", "그룹"), ("slug", "이름", "")]:
        with pytest.raises(ValueError, match="required"):
            await repo.upsert_curation_theme(
                _FakeSession(),
                theme_slug=values[0],
                theme_name=values[1],
                theme_group=values[2],
            )

    session = _FakeSession(_FakeResult(), _FakeResult(scalar=_THEME_ID))
    assert (
        await repo.upsert_curation_theme(
            session,
            theme_slug="  slug  ",
            theme_name="  이름  ",
            theme_group="  그룹  ",
        )
        == _THEME_ID
    )
    assert session.calls[1][1] == {
        "theme_slug": "slug",
        "theme_name": "이름",
        "theme_group": "그룹",
    }
    assert "curation-import" in session.calls[0][0]
    with pytest.raises(ValueError, match="retained catalog"):
        await repo.upsert_curation_theme(
            _FakeSession(_FakeResult(), _FakeResult()),
            theme_slug="missing",
            theme_name="없음",
            theme_group="test",
        )


def test_resolved_identity_validation_reports_component_and_feature_duplicates() -> None:
    valid = (_resolved_row(), _resolved_row(row_number=3, source_item_key="official:two"))
    assert repo.validate_resolved_curation_identities(valid) == ()

    mixed_is_valid = (
        _resolved_row(
            row_number=2,
            source_component_key="component-01",
            feature_id=None,
        ),
        _resolved_row(
            row_number=3,
            source_component_key="component-02",
        ),
    )
    assert repo.validate_resolved_curation_identities(mixed_is_valid) == ()

    duplicates = (
        _resolved_row(row_number=2, source_component_key="component-01"),
        _resolved_row(row_number=3, source_component_key="component-01"),
        _resolved_row(row_number=4, source_component_key="component-02"),
    )
    issues = repo.validate_resolved_curation_identities(duplicates)
    assert [(issue.row_number, issue.code) for issue in issues] == [
        (2, "duplicate_component_identity"),
        (2, "duplicate_resolved_feature"),
        (3, "duplicate_component_identity"),
        (3, "duplicate_resolved_feature"),
        (4, "duplicate_resolved_feature"),
    ]
    with pytest.raises(ValueError, match="Feature 해소 후"):
        repo._ensure_resolved_curation_identities(duplicates)
    with pytest.raises(ValueError, match="PostgreSQL integer"):
        repo._ensure_resolved_curation_identities((_resolved_row(sort_order=2_147_483_648),))


async def test_preview_import_empty_counts_updates_and_removals() -> None:
    assert await repo.preview_curation_import(_FakeSession(), rows=[]) == repo.CurationImportPlan(
        collections=0, inserted=0, updated=0, removals=()
    )

    rows = (
        _resolved_row(),
        _resolved_row(
            row_number=3,
            collection_key="heritage:2026",
            source_item_key="official:two",
            feature_id=None,
        ),
    )
    session = _FakeSession(
        _FakeResult(),
        _FakeResult(rows=[{"inserted": 1, "updated": 1}]),
        _FakeResult(rows=[_item_row()]),
    )
    plan = await repo.preview_curation_import(session, rows=rows)
    assert plan.collections == 2
    assert plan.inserted == 1
    assert plan.updated == 1
    assert plan.removals == (_item(),)
    payload = json.loads(session.calls[0][1]["items"])
    assert len(payload) == 2


async def test_import_rows_empty_changed_and_no_change(monkeypatch: pytest.MonkeyPatch) -> None:
    provenance = AsyncMock(
        side_effect=[
            "00000000-0000-4000-8000-000000000090",
            "00000000-0000-4000-8000-000000000091",
            "00000000-0000-4000-8000-000000000092",
        ]
    )
    monkeypatch.setattr(repo, "_record_import_provenance", provenance)
    assert await repo.import_curation_rows(_FakeSession(), rows=[]) == {
        "rows": 0,
        "collections": 0,
        "inserted": 0,
        "updated": 0,
        "removed": 0,
        "removals": (),
        "import_batch_id": "00000000-0000-4000-8000-000000000090",
    }

    rows = (
        _resolved_row(collection_key="z:key"),
        _resolved_row(
            row_number=3,
            collection_key="a:key",
            source_item_key="official:two",
            feature_id=None,
        ),
        _resolved_row(row_number=4, collection_key="z:key", source_item_key="official:three"),
    )
    foundations = AsyncMock(
        side_effect=[
            "00000000-0000-4000-8000-000000000010",
            "00000000-0000-4000-8000-000000000011",
        ]
    )
    monkeypatch.setattr(repo, "_upsert_id_with_fallback", foundations)
    changed = _FakeSession(
        _FakeResult(),
        _FakeResult(),
        _FakeResult(rows=["feature:one"]),
        _FakeResult(),
        _FakeResult(),
        _FakeResult(scalar=_THEME_ID),
        _FakeResult(scalar=_SOURCE_ID),
        _FakeResult(scalar=_THEME_ID),
        _FakeResult(scalar=_SOURCE_ID),
        _FakeResult(),
        _FakeResult(rows=[_item_row()]),
        _FakeResult(scalar=0),
        _FakeResult(rows=[{"inserted": 2, "updated": 1}]),
        _FakeResult(),
    )
    result = await repo.import_curation_rows(changed, rows=rows, actor="admin")
    assert result["rows"] == 3
    assert result["collections"] == 2
    assert result["inserted"] == 2
    assert result["updated"] == 1
    assert result["removed"] == 1
    assert result["removals"] == (_item(),)
    assert result["import_batch_id"] == "00000000-0000-4000-8000-000000000091"
    assert "pg_advisory_xact_lock" in changed.calls[0][0]
    assert "UPDATE feature.curation_collections" in changed.calls[-1][0]
    foundations.reset_mock(side_effect=True)
    foundations.side_effect = ["00000000-0000-4000-8000-000000000012"]
    unchanged = _FakeSession(
        _FakeResult(),
        _FakeResult(),
        _FakeResult(rows=["feature:one"]),
        _FakeResult(),
        _FakeResult(),
        _FakeResult(scalar=_THEME_ID),
        _FakeResult(scalar=_SOURCE_ID),
        _FakeResult(),
        _FakeResult(rows=[]),
        _FakeResult(scalar=0),
        _FakeResult(rows=[{"inserted": 0, "updated": 0}]),
    )
    no_change = await repo.import_curation_rows(unchanged, rows=(rows[0],))
    assert no_change["inserted"] == no_change["updated"] == no_change["removed"] == 0
    assert no_change["import_batch_id"] == "00000000-0000-4000-8000-000000000092"
    assert len(unchanged.calls) == 11


@pytest.mark.parametrize(
    ("frozen_h35_schema", "overrides", "message"),
    [
        # 현행 스키마: surrogate만 들어야 한다.
        (False, {"provider_dataset_id": None}, "surrogate만"),
        (
            False,
            {"provider_dataset_id": 101, "frozen_h35_dataset": ("p", "d")},
            "surrogate만",
        ),
        (False, {"provider_dataset_id": None, "frozen_h35_dataset": ("p", "d")}, "surrogate만"),
        # 0063~0079 고정 세대: 자연키만 들어야 한다.
        (True, {"provider_dataset_id": 101, "frozen_h35_dataset": None}, "자연키만"),
        (
            True,
            {"provider_dataset_id": 101, "frozen_h35_dataset": ("p", "d")},
            "자연키만",
        ),
        (True, {"provider_dataset_id": None, "frozen_h35_dataset": None}, "자연키만"),
    ],
)
def test_curation_dataset_identity_requires_exactly_one_generation_key(
    frozen_h35_schema: bool,
    overrides: dict[str, Any],
    message: str,
) -> None:
    """세대별 dataset identity는 **정확히 한 쪽만** 채워야 한다.

    ``provider_dataset_id``를 ``int | None``으로 푼 것은 고정 세대에 그 열이 없기
    때문일 뿐이다. 현행 스키마 분기(``elif``)를 무르게 하면 NOT NULL surrogate
    자리에 NULL이, 또는 삭제된 자연키 사본이 함께 흘러간다.
    """
    with pytest.raises(ValueError, match=message):
        repo._ensure_curation_dataset_identity(
            (_resolved_row(**overrides),),
            frozen_h35_schema=frozen_h35_schema,
        )


@pytest.mark.parametrize(
    ("frozen_h35_schema", "overrides"),
    [
        (False, {"provider_dataset_id": 101, "frozen_h35_dataset": None}),
        (True, {"provider_dataset_id": None, "frozen_h35_dataset": ("p", "d")}),
    ],
)
def test_curation_dataset_identity_accepts_the_matching_generation_key(
    frozen_h35_schema: bool,
    overrides: dict[str, Any],
) -> None:
    repo._ensure_curation_dataset_identity(
        (_resolved_row(**overrides),),
        frozen_h35_schema=frozen_h35_schema,
    )


def test_service_snapshot_rejects_over_cap_collection_before_public_joins() -> None:
    sql = repo._GET_SERVICE_CURATION_COLLECTION_PAGE_SQL
    key_position = sql.index("bounded_eligible_item_key AS MATERIALIZED")
    rich_projection_position = sql.index(") AS item_payload_hash")

    assert "JOIN feature.curation_link_decisions AS trusted_decision" in sql
    assert "JOIN feature.public_features AS pf" in sql
    assert "item.accepted_link_decision_id" in sql
    assert "LIMIT 2001" in sql
    assert "SELECT count(*) <= 2000" in sql
    assert "SELECT count(*) > 2000" in sql
    assert "FROM bounded_eligible_item_key" in sql
    assert key_position < rich_projection_position

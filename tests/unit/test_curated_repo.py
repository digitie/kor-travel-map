"""``curated_repo`` 단위 테스트."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from krtour.map.infra import curated_repo

pytestmark = pytest.mark.unit

_KST = timezone(timedelta(hours=9))
_THEME_ID = "11111111-1111-1111-1111-111111111111"
_SOURCE_ID = "22222222-2222-2222-2222-222222222222"
_RULE_ID = "33333333-3333-3333-3333-333333333333"
_CURATED_ID = "44444444-4444-4444-4444-444444444444"
_FEATURE_ID = "place::datagokr::bookstore::1"
_NOW = datetime(2026, 6, 12, 18, 0, tzinfo=_KST)


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def one(self) -> dict[str, Any]:
        assert len(self._rows) == 1
        return self._rows[0]


class _FakeSession:
    def __init__(self, *results: list[dict[str, Any]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append((str(statement), params or {}))
        assert self._results, f"unexpected execute: {statement}"
        return _FakeResult(self._results.pop(0))


def _theme_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "theme_id": _THEME_ID,
        "theme_slug": "bookstores",
        "theme_name": "책방 여행",
        "theme_description": "책방 후보",
        "theme_group": "books",
        "default_curated": False,
        "visibility": "tripmate",
        "metadata": {"icon": "book-open"},
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row


def _source_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source_id": _SOURCE_ID,
        "provider": "python-datagokr-api",
        "dataset_key": "datagokr_seoul_bookstores",
        "source_name": "서울특별시 책방",
        "source_url": "https://example.test/source",
        "source_kind": "filedata",
        "license": None,
        "update_cycle": "one_time",
        "last_source_modified_at": date(2025, 12, 2),
        "last_checked_at": _NOW,
        "next_expected_at": None,
        "row_count": 555,
        "freshness_note": "fixture",
        "provider_status": "implemented",
        "metadata": {"surface": "fileData"},
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row


def _rule_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "rule_id": _RULE_ID,
        "theme_id": _THEME_ID,
        "theme_slug": "bookstores",
        "source_id": _SOURCE_ID,
        "provider": "python-datagokr-api",
        "dataset_key": "datagokr_seoul_bookstores",
        "place_kind": "seoul_bookstore",
        "category": None,
        "region_scope": {},
        "default_action": "candidate",
        "priority": 70,
        "enabled": True,
        "metadata": {"tripmate_relation": "bookstore_stop"},
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row


def _feature_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "curated_feature_id": _CURATED_ID,
        "theme_id": _THEME_ID,
        "theme_slug": "bookstores",
        "theme_name": "책방 여행",
        "theme_group": "books",
        "feature_id": _FEATURE_ID,
        "feature_name": "테스트 책방",
        "feature_category": "culture",
        "feature_kind": "place",
        "lon": Decimal("127.007754"),
        "lat": Decimal("37.568533"),
        "sido_code": "11",
        "sigungu_code": "11140",
        "legal_dong_code": "1114016200",
        "address": {"admin": "서울특별시 중구"},
        "detail": {"place_kind": "seoul_bookstore"},
        "source_id": _SOURCE_ID,
        "provider": "python-datagokr-api",
        "dataset_key": "datagokr_seoul_bookstores",
        "source_name": "서울특별시 책방",
        "source_url": "https://example.test/source",
        "source_record_key": "python-datagokr-api::datagokr_seoul_bookstores::1",
        "curation_status": "curated",
        "selection_origin": "admin",
        "selected_by": "pytest",
        "selected_at": _NOW,
        "rejected_by": None,
        "rejected_at": None,
        "rejection_reason": None,
        "rank_score": Decimal("70.0"),
        "display_title": None,
        "display_summary": "책방 요약",
        "tripmate_relation": "bookstore_stop",
        "tripmate_copy_policy": "copy_allowed",
        "copy_version": 2,
        "metadata": {"summary": "metadata 요약"},
        "created_at": _NOW,
        "updated_at": _NOW,
        "archived_at": None,
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_curated_repo_read_paths_with_fake_session() -> None:
    later = _NOW + timedelta(minutes=1)
    session = _FakeSession(
        [_theme_row(metadata='{"icon":"book-open"}')],
        [_source_row()],
        [_rule_row()],
        [
            _feature_row(updated_at=later),
            _feature_row(
                curated_feature_id="55555555-5555-5555-5555-555555555555",
                updated_at=_NOW,
            ),
        ],
        [_feature_row(display_summary=None, metadata={"summary": "메타 요약"})],
        [_feature_row()],
    )

    [theme] = await curated_repo.list_curated_themes(
        session,
        visibility="tripmate",
        theme_group="books",
        limit=999,
    )
    assert theme.metadata == {"icon": "book-open"}
    assert session.calls[-1][1]["limit"] == 500

    [source] = await curated_repo.list_curated_sources(
        session,
        provider="python-datagokr-api",
        provider_status="implemented",
    )
    assert source.row_count == 555

    [rule] = await curated_repo.list_curated_source_rules(
        session,
        theme_slug="bookstores",
        enabled=True,
    )
    assert rule.place_kind == "seoul_bookstore"

    page = await curated_repo.list_curated_features(
        session,
        theme_slug="bookstores",
        curation_status="curated",
        region_code="11140",
        min_lon=126.0,
        min_lat=37.0,
        max_lon=128.0,
        max_lat=38.0,
        q="책방",
        page_size=1,
    )
    assert len(page.items) == 1
    assert page.next_cursor is not None
    assert session.calls[-1][1]["bbox_enabled"] is True
    assert session.calls[-1][1]["q_pattern"] == "%책방%"

    feature = await curated_repo.get_curated_feature(
        session,
        curated_feature_id=_CURATED_ID,
    )
    assert feature is not None
    assert feature.lon == 127.007754

    snapshot = await curated_repo.get_curated_tripmate_copy_snapshot(
        session,
        curated_feature_id=_CURATED_ID,
    )
    assert snapshot is not None
    assert snapshot.etag.startswith("sha256:")
    assert snapshot.plan["summary"] == "책방 요약"
    assert snapshot.plan["destination_name"] == "서울특별시 중구"
    assert snapshot.items[0].relation == "bookstore_stop"


@pytest.mark.asyncio
async def test_curated_repo_write_paths_with_fake_session() -> None:
    session = _FakeSession(
        [{"curated_feature_id": _CURATED_ID}],
        [_feature_row()],
        [_feature_row()],
        [{"curated_feature_id": _CURATED_ID}],
        [_feature_row(copy_version=3)],
        [{"curated_feature_id": _CURATED_ID}],
        [_feature_row(curation_status="curated", copy_version=4)],
        [{"curated_feature_id": _CURATED_ID}],
        [_feature_row(curation_status="rejected", copy_version=5)],
        [{"curated_feature_id": _CURATED_ID}],
        [_feature_row(curation_status="candidate", copy_version=6)],
        [{"curated_feature_id": _CURATED_ID}],
        [_feature_row(curation_status="archived", archived_at=_NOW, copy_version=7)],
        [{"affected_count": 3}],
        [_theme_row()],
        [_theme_row(theme_name="수정 책방")],
        [_source_row()],
        [_source_row(source_name="수정 source")],
        [{"rule_id": _RULE_ID}],
        [_rule_row()],
        [{"rule_id": _RULE_ID}],
        [_rule_row(priority=99)],
    )

    created = await curated_repo.create_curated_feature(
        session,
        theme_id=_THEME_ID,
        feature_id=_FEATURE_ID,
        source_id=_SOURCE_ID,
        curation_status="curated",
        selected_by="pytest",
        tripmate_relation="bookstore_stop",
        tripmate_copy_policy="copy_allowed",
        metadata={"manual": True},
    )
    assert created.curated_feature_id == _CURATED_ID
    assert session.calls[0][1]["selected_now"] is True

    same = await curated_repo.update_curated_feature(
        session,
        curated_feature_id=_CURATED_ID,
        updates={},
    )
    assert same is not None

    patched = await curated_repo.update_curated_feature(
        session,
        curated_feature_id=_CURATED_ID,
        updates={
            "display_summary": "patched",
            "metadata": {"patched": True},
            "tripmate_relation": "bookstore_stop",
        },
    )
    assert patched is not None
    assert "copy_version = copy_version + 1" in session.calls[3][0]

    for status_name in ("curated", "rejected", "candidate"):
        changed = await curated_repo.set_curated_feature_status(
            session,
            curated_feature_id=_CURATED_ID,
            curation_status=status_name,
            actor="pytest",
            reason="reason",
        )
        assert changed is not None
        assert changed.curation_status == status_name

    archived = await curated_repo.archive_curated_feature(
        session,
        curated_feature_id=_CURATED_ID,
        actor="pytest",
    )
    assert archived is not None
    assert archived.archived_at == _NOW

    applied = await curated_repo.apply_curated_source_rule(session, rule_id=_RULE_ID)
    assert applied.inserted_or_updated == 3

    theme = await curated_repo.create_curated_theme(
        session,
        theme_slug="bookstores",
        theme_name="책방 여행",
        theme_group="books",
        visibility="tripmate",
    )
    assert theme.theme_slug == "bookstores"

    updated_theme = await curated_repo.update_curated_theme(
        session,
        theme_id=_THEME_ID,
        updates={"theme_name": "수정 책방"},
    )
    assert updated_theme is not None
    assert updated_theme.theme_name == "수정 책방"

    source = await curated_repo.create_curated_source(
        session,
        provider="python-datagokr-api",
        dataset_key="datagokr_seoul_bookstores",
        source_name="서울특별시 책방",
        source_kind="filedata",
    )
    assert source.source_kind == "filedata"

    updated_source = await curated_repo.update_curated_source(
        session,
        source_id=_SOURCE_ID,
        updates={"source_name": "수정 source", "provider_status": "implemented"},
    )
    assert updated_source is not None
    assert updated_source.source_name == "수정 source"

    rule = await curated_repo.create_curated_source_rule(
        session,
        theme_id=_THEME_ID,
        source_id=_SOURCE_ID,
        dataset_key="datagokr_seoul_bookstores",
        region_scope={"sido_code": "11"},
        metadata={"tripmate_relation": "bookstore_stop"},
    )
    assert rule.rule_id == _RULE_ID

    updated_rule = await curated_repo.update_curated_source_rule(
        session,
        rule_id=_RULE_ID,
        updates={"priority": 99, "region_scope": {"sigungu_code": "11140"}},
    )
    assert updated_rule is not None
    assert updated_rule.priority == 99


@pytest.mark.asyncio
async def test_curated_repo_validation_and_empty_paths() -> None:
    with pytest.raises(ValueError, match="visibility"):
        await curated_repo.list_curated_themes(_FakeSession(), visibility="private")
    with pytest.raises(ValueError, match="provider_status"):
        await curated_repo.list_curated_sources(_FakeSession(), provider_status="bad")
    with pytest.raises(ValueError, match="curation_status"):
        await curated_repo.list_curated_features(_FakeSession(), curation_status="bad")
    with pytest.raises(ValueError, match="bbox requires"):
        await curated_repo.list_curated_features(_FakeSession(), min_lon=126.0)
    with pytest.raises(ValueError, match="bbox min values"):
        await curated_repo.list_curated_features(
            _FakeSession(),
            min_lon=128.0,
            min_lat=38.0,
            max_lon=127.0,
            max_lat=37.0,
        )
    with pytest.raises(ValueError, match="invalid curated feature cursor"):
        await curated_repo.list_curated_features(_FakeSession(), cursor="not-base64")
    with pytest.raises(ValueError, match="selection_origin"):
        await curated_repo.create_curated_feature(
            _FakeSession(),
            theme_id=_THEME_ID,
            feature_id=_FEATURE_ID,
            source_id=_SOURCE_ID,
            selection_origin="bad",
        )
    with pytest.raises(ValueError, match="unsupported curated_feature update field"):
        await curated_repo.update_curated_feature(
            _FakeSession(),
            curated_feature_id=_CURATED_ID,
            updates={"bad": True},
        )
    with pytest.raises(ValueError, match="tripmate_copy_policy"):
        await curated_repo.update_curated_feature(
            _FakeSession(),
            curated_feature_id=_CURATED_ID,
            updates={"tripmate_copy_policy": "bad"},
        )
    with pytest.raises(ValueError, match="curation_status"):
        await curated_repo.set_curated_feature_status(
            _FakeSession(),
            curated_feature_id=_CURATED_ID,
            curation_status="bad",
        )

    missing_session = _FakeSession([], [])
    assert (
        await curated_repo.get_curated_feature(
            missing_session,
            curated_feature_id=_CURATED_ID,
        )
        is None
    )
    assert (
        await curated_repo.get_curated_tripmate_copy_snapshot(
            missing_session,
            curated_feature_id=_CURATED_ID,
        )
        is None
    )

    assert (
        await curated_repo.update_curated_theme(
            _FakeSession(),
            theme_id=_THEME_ID,
            updates={},
        )
        is None
    )
    with pytest.raises(ValueError, match="unsupported update field"):
        await curated_repo.update_curated_source(
            _FakeSession(),
            source_id=_SOURCE_ID,
            updates={"provider": "bad"},
        )
    with pytest.raises(ValueError, match="source_kind"):
        await curated_repo.create_curated_source(
            _FakeSession(),
            provider="p",
            dataset_key="d",
            source_name="s",
            source_kind="bad",
        )

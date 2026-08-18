"""``curated_repo`` 단위 테스트.

주의: `_FakeSession`/`_feature_row`/`_CURATED_ID`는 API 패키지 suite
(`packages/kor-travel-map-api/tests/test_admin_curated_snapshot_contract.py`, T-VN-H07D)도
공유한다 — 생성부 payload를 두 번 구현하지 않기 위함이다. 이름/시그니처 변경 시 그쪽도 함께 고친다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.infra import curated_repo
from kortravelmap.infra.legacy_write_fence import LegacyWriteFenceError

pytestmark = pytest.mark.unit

_KST = timezone(timedelta(hours=9))
_THEME_ID = "11111111-1111-1111-1111-111111111111"
_SOURCE_ID = "22222222-2222-2222-2222-222222222222"
_RULE_ID = "33333333-3333-3333-3333-333333333333"
_CURATED_ID = "44444444-4444-4444-4444-444444444444"
_FEATURE_ID = "place::datagokr::bookstore::1"
_FEATURE_UUID = "77777777-7777-4777-8777-777777777777"
_NOW = datetime(2026, 6, 12, 18, 0, tzinfo=_KST)


def test_legacy_public_projection_excludes_archived_catalog() -> None:
    assert "t.archived_at IS NULL" in curated_repo._PUBLIC_FEATURE_FILTERS_SQL
    assert "s.archived_at IS NULL" in curated_repo._PUBLIC_FEATURE_FILTERS_SQL


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
        "visibility": "public",
        "metadata": {"icon": "book-open"},
        "created_at": _NOW,
        "updated_at": _NOW,
        "row_revision": 1,
        "archived_at": None,
        "owner_kind": "operator",
        "owner_provider_dataset_id": None,
    }
    row.update(overrides)
    return row


def _source_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "source_id": _SOURCE_ID,
        "provider_dataset_id": 101,
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
        "row_revision": 1,
        "observation_revision": 1,
        "archived_at": None,
    }
    row.update(overrides)
    return row


def _rule_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "rule_id": _RULE_ID,
        "theme_id": _THEME_ID,
        "theme_slug": "bookstores",
        "source_id": _SOURCE_ID,
        "provider_dataset_id": 101,
        "provider": "python-datagokr-api",
        "dataset_key": "datagokr_seoul_bookstores",
        "place_kind": "seoul_bookstore",
        "category": None,
        "region_scope": {},
        "detail_selector": None,
        "default_action": "candidate",
        "priority": 70,
        "enabled": True,
        "metadata": {"curation_relation": "bookstore_stop"},
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
        "feature_uuid": _FEATURE_UUID,
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
        "provider_dataset_id": 101,
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
        "curation_relation": "bookstore_stop",
        "reuse_policy": "allowed",
        "content_version": 2,
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
        visibility="public",
        theme_group="books",
        limit=999,
    )
    assert theme.metadata == {"icon": "book-open"}
    assert session.calls[-1][1]["limit"] == 500

    [source] = await curated_repo.list_curated_sources(
        session,
        provider_dataset_id=101,
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
        feature_name="서점",
        display_title="서울 책방",
        page_size=1,
    )
    assert len(page.items) == 1
    assert page.next_cursor is not None
    assert session.calls[-1][1]["bbox_enabled"] is True
    assert session.calls[-1][1]["q_pattern"] == "%책방%"
    assert session.calls[-1][1]["feature_name_pattern"] == "%서점%"
    assert session.calls[-1][1]["display_title"] == "서울 책방"

    feature = await curated_repo.get_curated_feature(
        session,
        curated_feature_id=_CURATED_ID,
    )
    assert feature is not None
    assert feature.lon == 127.007754

    snapshot = await curated_repo.get_curated_feature_detail_snapshot(
        session,
        curated_feature_id=_CURATED_ID,
    )
    assert snapshot is not None
    assert snapshot.etag.startswith("sha256:")
    assert snapshot.content["summary"] == "책방 요약"
    assert snapshot.content["destination_name"] == "서울특별시 중구"
    assert snapshot.items[0].relation == "bookstore_stop"
    # T-VN-32C PR-2 — snapshot의 feature 참조는 UUID 정본으로 물질화된다.
    assert snapshot.items[0].feature_id == _FEATURE_UUID
    assert snapshot.items[0].feature_snapshot["feature_id"] == _FEATURE_UUID


@pytest.mark.asyncio
async def test_curated_repo_legacy_writes_are_fenced_before_any_sql() -> None:
    """T-VN-40A — legacy write 4함수는 SQL을 조립하기 **전에** static fence에서 죽는다.

    원래 이 테스트는 그 4함수가 fake session에 내는 SQL 문자열을 검증했다(`FOR KEY SHARE`,
    `content_version = content_version + 1` 등). fence 뒤로는 첫 줄에서 예외라 SQL이
    조립되지 않는다 — 검증 대상 자체가 사라졌다.

    대신 여기서 보는 것: **fake session에 아무 호출도 닿지 않는다.** 그것이 static 층이
    ACL 층보다 먼저 죽는다는 증거다. static이 뚫려 SQL이 나가면 `session.calls`가 비지
    않는다.
    """
    from kortravelmap.infra.legacy_write_fence import LegacyWriteFenceError

    session = _FakeSession()

    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.create_curated_feature(
            session,
            theme_id=_THEME_ID,
            feature_id=_FEATURE_ID,
            source_id=_SOURCE_ID,
            curation_status="curated",
            selected_by="pytest",
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.update_curated_feature(
            session, curated_feature_id=_CURATED_ID, updates={"reuse_policy": "allowed"}
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.set_curated_feature_status(
            session, curated_feature_id=_CURATED_ID, curation_status="rejected"
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.archive_curated_feature(session, curated_feature_id=_CURATED_ID)

    assert session.calls == [], (
        f"fence 뒤에서 SQL이 나갔다 — static 층이 첫 줄에 있지 않다: {session.calls[:2]}"
    )


@pytest.mark.asyncio
async def test_retained_rule_commands_use_full_desired_cas_inputs() -> None:
    session = _FakeSession(
        [{"o_rule_id": _RULE_ID, "o_rule_revision": 1, "o_generation_id": "gen-1"}],
        [_rule_row(row_revision=1)],
        [_rule_row(row_revision=1)],
        [{"o_rule_id": _RULE_ID, "o_rule_revision": 2, "o_generation_id": "gen-2"}],
        [_rule_row(row_revision=2, priority=90, default_action="ignore")],
        [_rule_row(row_revision=2, priority=90, default_action="ignore")],
        [{"o_rule_id": _RULE_ID, "o_rule_revision": 3, "o_generation_id": "gen-3"}],
        [
            _rule_row(
                row_revision=3,
                priority=90,
                default_action="ignore",
                archived_at=_NOW,
            )
        ],
    )

    created = await curated_repo.create_curated_source_rule_command(
        session,
        theme_id=_THEME_ID,
        source_id=_SOURCE_ID,
        region_scope={"sido_code": "11"},
        command_id=101,
        principal="admin:rule-test",
    )
    patched = await curated_repo.patch_curated_source_rule_command(
        session,
        rule_id=_RULE_ID,
        expected_revision=1,
        updates={"priority": 90, "default_action": "ignore"},
        command_id=102,
        principal="admin:rule-test",
    )
    archived = await curated_repo.archive_curated_source_rule_command(
        session,
        rule_id=_RULE_ID,
        expected_revision=2,
        command_id=103,
        reason_code="operator_retired",
        principal="admin:rule-test",
    )

    assert created.row_revision == 1
    assert patched is not None
    assert (patched.row_revision, patched.priority, patched.default_action) == (
        2,
        90,
        "ignore",
    )
    assert archived is not None
    assert (archived.row_revision, archived.archived_at) == (3, _NOW)
    command_calls = [call for call in session.calls if "CALL feature." in call[0]]
    assert [
        "create_curated_source_rule_command" in call[0]
        or "patch_curated_source_rule_command" in call[0]
        or "archive_curated_source_rule_command" in call[0]
        for call in command_calls
    ] == [True, True, True]
    assert command_calls[1][1]["expected_revision"] == 1
    assert command_calls[1][1]["priority"] == 90
    assert command_calls[1][1]["region_scope_json"] == "{}"
    assert command_calls[2][1]["expected_revision"] == 2




@pytest.mark.asyncio
async def test_curated_detail_snapshot_uses_concierge_source_title() -> None:
    session = _FakeSession(
        [
            _feature_row(
                provider="kor-travel-concierge-youtube",
                dataset_key="youtube_place_candidates",
                source_name="kor-travel-concierge YouTube 장소 후보",
                display_title=None,
                detail={
                    "place_kind": "youtube_place_candidate",
                    "payload": {
                        "kor_travel_concierge": {
                            "youtube": {
                                "source_title": "제주 동쪽 영상 묶음",
                                "playlist_title": "제주 플레이리스트",
                            }
                        }
                    },
                    "facility_info": {
                        "youtube_channel_title": "여행 채널",
                        "youtube_playlist_title": "제주 플레이리스트",
                    },
                },
            )
        ]
    )

    snapshot = await curated_repo.get_curated_feature_detail_snapshot(
        session,
        curated_feature_id=_CURATED_ID,
    )

    assert snapshot is not None
    assert snapshot.content["title"] == "제주 동쪽 영상 묶음"


@pytest.mark.asyncio
async def test_curated_detail_snapshot_uses_provider_title_for_public_source() -> None:
    session = _FakeSession([_feature_row(display_title=None)])

    snapshot = await curated_repo.get_curated_feature_detail_snapshot(
        session,
        curated_feature_id=_CURATED_ID,
    )

    assert snapshot is not None
    assert snapshot.content["title"] == "python-datagokr-api"


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
    # T-VN-40A: 이 ValueError 검증은 create 함수 **안**에 있어 fence 뒤다.
    # 도달 불가이므로 fence 예외를 단언한다. (그 검증 자체는 canonical 경로에
    # 같은 것이 있는지가 진짜 질문이고 이 파일 범위 밖이다.)
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.create_curated_feature(
            _FakeSession(),
            theme_id=_THEME_ID,
            feature_id=_FEATURE_ID,
            source_id=_SOURCE_ID,
            selection_origin="bad",
        )
    # T-VN-40A: 이 ValueError 검증은 create 함수 **안**에 있어 fence 뒤다.
    # 도달 불가이므로 fence 예외를 단언한다. (그 검증 자체는 canonical 경로에
    # 같은 것이 있는지가 진짜 질문이고 이 파일 범위 밖이다.)
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.create_curated_feature(
            _FakeSession([]),
            theme_id=_THEME_ID,
            feature_id=_FEATURE_ID,
            source_id=_SOURCE_ID,
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.update_curated_feature(
            _FakeSession(),
            curated_feature_id=_CURATED_ID,
            updates={"bad": True},
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.update_curated_feature(
            _FakeSession(),
            curated_feature_id=_CURATED_ID,
            updates={"reuse_policy": "bad"},
        )
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.set_curated_feature_status(
            _FakeSession(),
            curated_feature_id=_CURATED_ID,
            curation_status="bad",
        )
    # T-VN-40A: 원래 "detached row update는 None"을 검증했다. fence 뒤로는 그보다 앞에서
    # 예외다. 검증 대상(update 함수 안의 detached 판정)이 도달 불가라 fence 단언으로.
    detached = _FakeSession()
    with pytest.raises(LegacyWriteFenceError):
        await curated_repo.update_curated_feature(
            detached,
            curated_feature_id=_CURATED_ID,
            updates={},
        )
    assert detached.calls == []

    missing_session = _FakeSession([], [])
    assert (
        await curated_repo.get_curated_feature(
            missing_session,
            curated_feature_id=_CURATED_ID,
        )
        is None
    )
    assert (
        await curated_repo.get_curated_feature_detail_snapshot(
            missing_session,
            curated_feature_id=_CURATED_ID,
        )
        is None
    )

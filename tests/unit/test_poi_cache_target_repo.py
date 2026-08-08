"""``poi_cache_target_repo`` keyset cursor 단위 테스트."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTargetDeleteResult,
    PoiCacheTargetFeatureLinkCandidate,
    PoiCacheTargetPage,
    delete_poi_cache_target,
    get_dataset_projection_revision,
    has_active_poi_cache_targets_for_external_system,
    list_active_poi_cache_target_external_systems,
    list_active_target_coords,
    list_poi_cache_targets,
    poi_cache_target_entity_tag,
    sync_poi_cache_target_feature_links,
    upsert_poi_cache_target,
    upsert_poi_cache_target_feature_link,
)


class _Result:
    def __init__(self, rows: list[Any], *, scalar: object | None = None) -> None:
        self._rows = rows
        self._scalar = scalar

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def one(self) -> Any:
        return self._rows[0]

    def one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self

    def scalar_one(self) -> object:
        return self._scalar


class _Session:
    def __init__(self, *results: _Result) -> None:
        self._results = list(results)
        self.params: list[dict[str, Any]] = []
        self.statements: list[str] = []

    async def execute(
        self,
        _statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        self.statements.append(str(_statement))
        self.params.append(dict(params or {}))
        return self._results.pop(0)


def _row(target_id: str, *, at: datetime) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "lock_version": 1,
        "external_system": "external-app",
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
        "metadata": '{"external_poi_id":"poi-1"}',
        "last_seen_at": at,
        "last_requested_at": None,
        "last_refreshed_at": None,
        "last_failed_at": None,
        "next_eligible_refresh_at": None,
        "deleted_at": None,
        "created_at": at,
        "updated_at": at,
    }


def _link_row(target_id: str, feature_id: str, *, at: datetime) -> dict[str, Any]:
    return {
        "target_id": target_id,
        "feature_id": feature_id,
        "provider_dataset_id": 101,
        "distance_m": 12.5,
        "relation": "within_radius",
        "active": True,
        "first_seen_at": at,
        "last_seen_at": at,
        "last_refreshed_at": None,
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
        external_system="external-app",
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


@pytest.mark.unit
async def test_list_active_target_coords_applies_exact_external_system_filter() -> None:
    session = _Session(
        _Result(
            [
                SimpleNamespace(lon=126.9, lat=37.5),
                SimpleNamespace(lon=129.1, lat=35.2),
            ]
        )
    )

    coords = await list_active_target_coords(
        cast(Any, session),
        external_system="tripmate",
    )

    assert coords == [(126.9, 37.5), (129.1, 35.2)]
    assert session.params == [{"external_system": "tripmate"}]


@pytest.mark.unit
async def test_list_active_target_coords_without_filter_uses_all_active_targets() -> None:
    session = _Session(_Result([SimpleNamespace(lon=126.9, lat=37.5)]))

    coords = await list_active_target_coords(cast(Any, session))

    assert coords == [(126.9, 37.5)]
    assert session.params == [{}]


@pytest.mark.unit
async def test_active_external_system_reads_are_canonical_and_exact() -> None:
    session = _Session(
        _Result(
            [
                SimpleNamespace(external_system="concierge"),
                SimpleNamespace(external_system="tripmate"),
            ]
        ),
        _Result([], scalar=True),
    )

    systems = await list_active_poi_cache_target_external_systems(cast(Any, session))
    exists = await has_active_poi_cache_targets_for_external_system(
        cast(Any, session),
        "tripmate",
    )

    assert systems == ["concierge", "tripmate"]
    assert exists is True
    assert session.params == [{}, {"external_system": "tripmate"}]


@pytest.mark.unit
@pytest.mark.parametrize(
    "external_system",
    ["", " ", "tripmate ", "\ttripmate", "x" * 113],
)
async def test_active_external_system_reads_reject_non_exact_name(
    external_system: str,
) -> None:
    session = _Session()

    with pytest.raises(ValueError, match="external_system"):
        await has_active_poi_cache_targets_for_external_system(
            cast(Any, session),
            external_system,
        )

    assert session.params == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "external_system",
    ["", " pinvi", "pinvi ", "pinvi\t", "x" * 113],
)
async def test_poi_target_writer_rejects_noncanonical_external_system(
    external_system: str,
) -> None:
    session = _Session()

    with pytest.raises(ValueError, match="external_system"):
        await upsert_poi_cache_target(
            cast(Any, session),
            external_system=external_system,
            target_key="poi-1",
            lon=126.978,
            lat=37.5665,
            radius_km=5,
        )

    assert session.params == []


@pytest.mark.unit
async def test_upsert_create_race_loser_relocks_before_do_update() -> None:
    """create 경합의 패자는 재-lock으로 active row를 잡은 뒤에만 DO UPDATE한다."""
    at = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    target_id = "11111111-1111-4111-8111-111111111111"
    row = _row(target_id, at=at)
    session = _Session(
        _Result([]),  # FOR UPDATE lock — active row 없음
        _Result([]),  # DO NOTHING create — 경합 패배(0 row)
        _Result(
            [
                {
                    "target_id": target_id,
                    "lock_version": 1,
                    "coord_key": row["coord_key"],
                }
            ]
        ),  # 재-lock — winner row 확보
        _Result([row]),  # lock 보유 상태의 DO UPDATE upsert
    )

    target = await upsert_poi_cache_target(
        cast(Any, session),
        external_system="external-app",
        target_key="poi-1",
        lon=126.978,
        lat=37.5665,
        radius_km=5,
    )

    assert target.target_id == target_id
    assert "FOR UPDATE" in session.statements[0]
    assert "DO NOTHING" in session.statements[1]
    assert "DO UPDATE" not in session.statements[1]
    assert "FOR UPDATE" in session.statements[2]
    assert "DO UPDATE" in session.statements[3]


@pytest.mark.unit
async def test_upsert_create_race_bounded_retry_fails_closed_without_lock() -> None:
    """재-lock이 계속 비면 유한 재시도 뒤 실패한다 — 잠금 없는 DO UPDATE 금지.

    winner commit 직후 동시 soft-delete가 반복되는 3자 경합은 winner commit과
    패자 재-lock 사이에 delete를 결정적으로 끼워 넣을 관측점이 없어 통합
    테스트로 재현하기 어렵다. 여기서는 unit 수준에서 "DO UPDATE tail은 active
    row FOR UPDATE 보유 없이는 절대 실행되지 않는다"는 계약을 고정한다.
    """
    # 초기 lock 1회 + (create + 재-lock) × 상한 3회 = 7개 statement, 전부 빈 결과.
    session = _Session(*[_Result([]) for _ in range(7)])

    with pytest.raises(RuntimeError, match="create race"):
        await upsert_poi_cache_target(
            cast(Any, session),
            external_system="external-app",
            target_key="poi-1",
            lon=126.978,
            lat=37.5665,
            radius_km=5,
        )

    assert len(session.statements) == 7
    assert all("DO UPDATE" not in statement for statement in session.statements)
    assert sum("DO NOTHING" in statement for statement in session.statements) == 3
    assert sum("FOR UPDATE" in statement for statement in session.statements) == 4


@pytest.mark.unit
async def test_external_system_accepts_exact_112_character_limit() -> None:
    external_system = "x" * 112
    session = _Session(_Result([], scalar=False))

    exists = await has_active_poi_cache_targets_for_external_system(
        cast(Any, session),
        external_system,
    )

    assert exists is False
    assert session.params == [{"external_system": external_system}]


@pytest.mark.unit
async def test_delete_poi_cache_target_uses_uuid_precondition_and_deactivates_links() -> None:
    at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    target_id = "11111111-1111-4111-8111-111111111111"
    deleted_row = {
        **_row(target_id, at=at),
        "active_target_id": target_id,
        "deleted_at": at,
        "lock_version": 2,
        "update_enabled": False,
    }
    session = _Session(
        _Result([{"target_id": target_id, "lock_version": 1}]),
        _Result([deleted_row]),
        _Result([1]),
    )

    result = await delete_poi_cache_target(
        cast(Any, session),
        external_system="external-app",
        target_key="poi-1",
        expected_target_id=target_id,
        expected_lock_version=1,
    )

    assert result.status == "deleted"
    assert result.target is not None
    assert result.target.target_id == target_id
    assert result.target.deleted_at == at
    assert session.params == [
        {
            "external_system": "external-app",
            "target_key": "poi-1",
        },
        {
            "external_system": "external-app",
            "target_key": "poi-1",
            "expected_target_id": target_id,
            "expected_lock_version": 1,
        },
        {"target_id": target_id},
    ]


@pytest.mark.unit
async def test_delete_poi_cache_target_distinguishes_absent_from_uuid_mismatch() -> None:
    active_target_id = "11111111-1111-4111-8111-111111111111"
    expected_target_id = "22222222-2222-4222-8222-222222222222"
    mismatch = _Session(
        _Result([{"target_id": active_target_id, "lock_version": 2}])
    )
    absent = _Session(_Result([]), _Result([]))

    mismatch_result = await delete_poi_cache_target(
        cast(Any, mismatch),
        external_system="external-app",
        target_key="poi-1",
        expected_target_id=expected_target_id,
        expected_lock_version=1,
    )
    absent_result = await delete_poi_cache_target(
        cast(Any, absent),
        external_system="external-app",
        target_key="poi-1",
        expected_target_id=expected_target_id,
        expected_lock_version=1,
    )

    assert mismatch_result == PoiCacheTargetDeleteResult(
        status="precondition_failed"
    )
    assert absent_result == PoiCacheTargetDeleteResult(status="not_found")


@pytest.mark.unit
async def test_delete_poi_cache_target_recheck_maps_concurrent_recreate_to_412() -> None:
    expected_target_id = "11111111-1111-4111-8111-111111111111"
    recreated_target_id = "22222222-2222-4222-8222-222222222222"
    session = _Session(
        _Result([]),
        _Result([{"target_id": recreated_target_id, "lock_version": 1}]),
    )

    result = await delete_poi_cache_target(
        cast(Any, session),
        external_system="external-app",
        target_key="poi-1",
        expected_target_id=expected_target_id,
        expected_lock_version=1,
    )

    assert result == PoiCacheTargetDeleteResult(status="precondition_failed")


@pytest.mark.unit
async def test_get_dataset_projection_revision_requires_canonical_topic_row() -> None:
    session = _Session(_Result([], scalar=42))

    revision = await get_dataset_projection_revision(cast(Any, session))

    assert revision == 42
    assert session.params == [{}]


@pytest.mark.unit
async def test_link_upsert_skips_inactive_parent() -> None:
    session = _Session(_Result([]))

    link = await upsert_poi_cache_target_feature_link(
        cast(Any, session),
        target_id="11111111-1111-4111-8111-111111111111",
        feature_id="feature-1",
    )

    assert link is None
    assert "relation = EXCLUDED.relation" in session.statements[0]


@pytest.mark.unit
async def test_link_sync_locks_all_parents_before_link_writes_in_uuid_order() -> None:
    at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    first_id = "11111111-1111-4111-8111-111111111111"
    second_id = "22222222-2222-4222-8222-222222222222"
    session = _Session(
        _Result([first_id, second_id]),
        _Result([]),
        _Result([1]),
        _Result([_link_row(first_id, "feature-a", at=at)]),
        _Result([_link_row(second_id, "feature-b", at=at)]),
    )

    links = await sync_poi_cache_target_feature_links(
        cast(Any, session),
        target_ids=(second_id, first_id, second_id),
        candidates=(
            PoiCacheTargetFeatureLinkCandidate(
                target_id=second_id,
                feature_id="feature-b",
                provider_dataset_id=101,
                distance_m=12.5,
            ),
            PoiCacheTargetFeatureLinkCandidate(
                target_id=first_id,
                feature_id="feature-a",
                provider_dataset_id=101,
                distance_m=12.5,
            ),
        ),
    )

    assert [link.target_id for link in links] == [first_id, second_id]
    assert "ORDER BY target_id" in session.statements[0]
    assert "FOR KEY SHARE" in session.statements[0]
    assert "ORDER BY target_id, feature_id" in session.statements[1]
    assert "FOR UPDATE" in session.statements[1]
    assert "UPDATE ops.poi_cache_target_feature_links" in session.statements[2]
    # snapshot sync는 resolver link만 비활성화한다 — 운영자 manual link 보존(#699).
    assert "relation <> 'manual'" in session.statements[2]
    assert "INSERT INTO ops.poi_cache_target_feature_links" in session.statements[3]
    assert "poi_cache_target_feature_links.active" in session.statements[3]
    assert "poi_cache_target_feature_links.relation = 'manual'" in session.statements[3]
    assert session.params == [
        {"target_ids": [first_id, second_id]},
        {"target_ids": [first_id, second_id]},
        {"target_ids": [first_id, second_id]},
        {
            "target_id": first_id,
            "feature_id": "feature-a",
            "provider_dataset_id": 101,
            "distance_m": 12.5,
            "relation": "within_radius",
        },
        {
            "target_id": second_id,
            "feature_id": "feature-b",
            "provider_dataset_id": 101,
            "distance_m": 12.5,
            "relation": "within_radius",
        },
    ]


@pytest.mark.unit
def test_poi_cache_target_entity_tag_is_canonical_and_versioned() -> None:
    assert (
        poi_cache_target_entity_tag(
            "11111111-1111-4111-8111-111111111111",
            7,
        )
        == '"11111111-1111-4111-8111-111111111111:7"'
    )
    with pytest.raises(ValueError, match="positive"):
        poi_cache_target_entity_tag(
            "11111111-1111-4111-8111-111111111111",
            0,
        )

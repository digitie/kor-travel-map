"""``admin_feature_repo`` DB 무관 단위 테스트."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from kortravelmap.infra import admin_feature_repo as repo
from kortravelmap.infra.merge_repo import MergeError, MergeOutcome

_NOW = datetime(2026, 6, 3, tzinfo=UTC)
_REVIEW_KEY_1 = "00000000-0000-0000-0000-000000000001"
_REVIEW_KEY_2 = "00000000-0000-0000-0000-000000000002"


class _Mappings:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def one(self) -> dict[str, Any]:
        return self._rows[0]


class _Result:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def mappings(self) -> _Mappings:
        return _Mappings(self._rows)

    def first(self) -> object | None:
        return object() if self._rows else None

    def one_or_none(self) -> Any:
        if not self._rows:
            return None
        return type("Row", (), self._rows[0])()

    def scalar_one(self) -> Any:
        return next(iter(self._rows[0].values()))


class _Session:
    def __init__(self, results: list[_Result]) -> None:
        self._results = results
        self.calls: list[dict[str, Any]] = []

    async def execute(self, statement: object, params: dict[str, Any]) -> _Result:
        self.calls.append({"statement": str(statement), "params": params})
        return self._results.pop(0)


def _feature_row(feature_id: str = "feature-1") -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "kind": "place",
        "name": "광화문",
        "category": "01070300",
        "status": "active",
        "lon": 126.9769,
        "lat": 37.5759,
        "address_label": "서울특별시 종로구",
        "primary_provider": "python-mois-api",
        "primary_dataset_key": "mois_license_features_bulk",
        "issue_count": 1,
        "issues": json.dumps(
            [
                {
                    "issue_id": "issue-1",
                    "violation_type": "missing_address",
                    "severity": "warning",
                    "message": "주소 검토 필요",
                }
            ],
            ensure_ascii=False,
        ),
        "created_at": _NOW,
        "updated_at": _NOW,
    }


def _dedup_row(review_id: str = _REVIEW_KEY_1) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "status": "pending",
        "total_score": 90,
        "name_score": 95,
        "spatial_score": 85,
        "category_score": 100,
        "feature_id_a": "feature-a",
        "name_a": "장소 A",
        "kind_a": "place",
        "category_a": "01070300",
        "lon_a": 126.9,
        "lat_a": 37.5,
        "provider_a": "python-mois-api",
        "dataset_key_a": "mois_license_features_bulk",
        "feature_id_b": "feature-b",
        "name_b": "장소 B",
        "kind_b": "place",
        "category_b": "01070300",
        "lon_b": None,
        "lat_b": None,
        "provider_b": None,
        "dataset_key_b": None,
        "distance_m": None,
        "decision_reason": "manual_review",
        "reviewed_by": None,
        "reviewed_at": None,
        "created_at": _NOW,
    }


def test_admin_feature_cursor_round_trip_all_sorts() -> None:
    item = repo._admin_feature_row(_feature_row())

    for sort, order in (
        ("name", "asc"),
        ("kind", "asc"),
        ("status", "desc"),
        ("provider", "asc"),
        ("updated_at", "desc"),
        ("created_at", "asc"),
        ("issue_count", "desc"),
    ):
        cursor = repo._encode_cursor(item, sort=sort, order=order)
        params = repo._cursor_params(cursor, sort=sort, order=order)
        assert params["cursor_feature_id"] == "feature-1"

    with pytest.raises(ValueError, match="invalid admin features cursor"):
        repo._cursor_params("not-base64", sort="name", order="asc")
    with pytest.raises(ValueError, match="invalid admin features cursor"):
        repo._cursor_params(cursor, sort="name", order="asc")


def test_admin_feature_row_and_json_helpers() -> None:
    assert repo._normalize_values(["a", "", "b"]) == ["a", "b"]
    assert repo._normalize_values([]) is None
    assert repo._normalize_query("  Ａ  ") == "A"
    assert repo._json_array('[{"a": 1}, 2]') == ({"a": 1},)

    row = repo._admin_feature_row(_feature_row())
    assert row.feature_id == "feature-1"
    assert row.lon == 126.9769
    assert row.issue_count == 1
    assert row.issues[0]["violation_type"] == "missing_address"


@pytest.mark.asyncio
async def test_list_admin_features_builds_params_and_next_cursor() -> None:
    session = _Session([_Result([_feature_row("feature-1"), _feature_row("feature-2")])])

    page = await repo.list_admin_features(
        session,  # type: ignore[arg-type]
        q=" 광화문 ",
        providers=["python-mois-api"],
        has_issue=True,
        page_size=1,
        sort="issue_count",
        order="desc",
    )

    assert len(page.items) == 1
    assert page.next_cursor is not None
    params = session.calls[0]["params"]
    assert params["q_like"] == "%광화문%"
    assert params["providers"] == ["python-mois-api"]
    assert params["has_issue"] is True


@pytest.mark.asyncio
async def test_get_admin_feature_detail_aggregates_rows_without_feature_files_table() -> None:
    feature_row = {
        "feature_id": "feature-1",
        "kind": "place",
        "name": "광화문",
        "category": "01070300",
        "status": "active",
        "lon": 126.9769,
        "lat": 37.5759,
        "coord_precision_digits": 5,
        "address": '{"road": "서울특별시 종로구 세종대로 1"}',
        "detail": '{"place_kind": "attraction"}',
        "urls": '{"homepage": "https://example.test"}',
        "raw_refs": '[{"source": "fixture"}]',
        "legal_dong_code": "1111010100",
        "road_name_code": None,
        "road_address_management_no": None,
        "admin_dong_code": "1111051500",
        "sido_code": "11",
        "sigungu_code": "11110",
        "marker_icon": "landmark",
        "marker_color": "P-01",
        "parent_feature_id": None,
        "sibling_group_id": None,
        "data_origin": "provider",
        "data_version": 0,
        "user_change_kind": None,
        "user_change_status": None,
        "user_change_request_id": None,
        "user_deleted_at": None,
        "user_deleted_by": None,
        "user_change_reason": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "deleted_at": None,
    }
    source_row = {
        "source_record_key": "sr-feature-1",
        "provider": "python-mois-api",
        "dataset_key": "mois_license_features_bulk",
        "source_entity_type": "license_place",
        "source_entity_id": "sr-feature-1",
        "source_version": "20260603",
        "source_role": "primary",
        "match_method": "natural_key",
        "confidence": 100,
        "is_primary_source": True,
        "raw_name": "광화문",
        "raw_address": "서울특별시 종로구 세종대로 1",
        "raw_longitude": 126.9769,
        "raw_latitude": 37.5759,
        "raw_payload_hash": "hash-1",
        "raw_data": '{"id": "sr-feature-1"}',
        "fetched_at": _NOW,
        "imported_at": _NOW,
        "expires_at": None,
        "linked_at": _NOW,
    }
    issue_row = {
        "issue_id": "issue-1",
        "provider": "python-mois-api",
        "dataset_key": "mois_license_features_bulk",
        "source_record_key": "sr-feature-1",
        "violation_type": "missing_address",
        "severity": "warning",
        "message": "주소 누락",
        "payload": '{"field": "address"}',
        "status": "open",
        "detected_at": _NOW,
        "resolved_at": None,
    }
    override_row = {
        "override_id": "override-1",
        "source_record_key": None,
        "field_path": "status",
        "source_value": '"active"',
        "override_value": '"inactive"',
        "prevent_provider_reactivation": True,
        "status": "active",
        "reason": "운영상 제외",
        "created_by": "local-admin",
        "created_at": _NOW,
    }
    version_row = {
        "feature_id": "feature-1",
        "version": 0,
        "origin": "provider",
        "change_kind": "load",
        "payload": '{"name": "광화문"}',
        "request_id": None,
        "created_by": "provider",
        "created_at": _NOW,
    }
    change_row = {
        "request_id": "change-1",
        "feature_id": "feature-1",
        "action": "update",
        "state": "applied",
        "review_mode": "immediate",
        "payload": '{"name": "광화문"}',
        "reason": "사용자 수정",
        "requested_by": "local-admin",
        "reviewed_by": None,
        "reviewed_at": None,
        "applied_at": _NOW,
        "created_at": _NOW,
    }
    session = _Session(
        [
            _Result([feature_row]),
            _Result([source_row]),
            _Result([issue_row]),
            _Result([override_row]),
            _Result([version_row]),
            _Result([change_row]),
            _Result([{"exists": False}]),
        ]
    )

    detail = await repo.get_admin_feature_detail(
        session,  # type: ignore[arg-type]
        "feature-1",
    )

    assert detail is not None
    assert detail.feature.raw_refs == [{"source": "fixture"}]
    assert detail.sources[0].raw_data == {"id": "sr-feature-1"}
    assert detail.issues[0].payload == {"field": "address"}
    assert detail.overrides[0].override_value == "inactive"
    assert detail.versions[0].payload == {"name": "광화문"}
    assert detail.change_requests[0].payload == {"name": "광화문"}
    assert detail.files == ()
    assert "feature.feature_files" in session.calls[-1]["statement"]


@pytest.mark.asyncio
async def test_deactivate_feature_with_and_without_override() -> None:
    override_row = {
        "override_id": "override-1",
        "feature_id": "feature-1",
        "field_path": "status",
        "override_value": '"inactive"',
        "prevent_provider_reactivation": True,
        "reason": "운영상 제외",
        "created_by": "local-admin",
        "created_at": _NOW,
    }
    session = _Session(
        [
            _Result(
                [
                    {
                        "feature_id": "feature-1",
                        "previous_status": "active",
                        "status": "inactive",
                    }
                ]
            ),
            _Result([override_row]),
        ]
    )

    result = await repo.deactivate_feature(
        session,  # type: ignore[arg-type]
        "feature-1",
        reason="운영상 제외",
        operator="local-admin",
        prevent_provider_reactivation=True,
    )

    assert result is not None
    assert result.override is not None
    assert result.override.override_value == "inactive"
    assert result.override_created is True

    no_override = await repo.deactivate_feature(
        _Session(
            [
                _Result(
                    [
                        {
                            "feature_id": "feature-2",
                            "previous_status": "hidden",
                            "status": "inactive",
                        }
                    ]
                )
            ]
        ),  # type: ignore[arg-type]
        "feature-2",
        reason="운영상 제외",
        prevent_provider_reactivation=False,
    )
    assert no_override is not None
    assert no_override.override_created is False

    missing = await repo.deactivate_feature(
        _Session([_Result([]), _Result([])]),  # type: ignore[arg-type]
        "missing",
        reason="없음",
    )
    assert missing is None

    with pytest.raises(repo.FeatureStateConflict) as exc_info:
        await repo.deactivate_feature(
            _Session(
                [
                    _Result([]),
                    _Result(
                        [
                            {
                                "feature_id": "feature-deleted",
                                "status": "deleted",
                                "deleted_at": _NOW,
                            }
                        ]
                    ),
                ]
            ),  # type: ignore[arg-type]
            "feature-deleted",
            reason="삭제됨",
        )
    assert exc_info.value.current_status == "deleted"
    assert exc_info.value.target_status == "inactive"


def test_dedup_cursor_and_row_mapping() -> None:
    item = repo._dedup_review_row(_dedup_row())
    cursor = repo._encode_dedup_cursor(item)

    assert repo._dedup_cursor_params(cursor) == {
        "cursor_score": "90",
        "cursor_review_id": _REVIEW_KEY_1,
    }
    assert item.total_score_cursor == "90"
    assert item.feature_a.feature_id == "feature-a"
    assert item.feature_b.lon is None
    assert item.distance_m is None

    with pytest.raises(ValueError, match="invalid dedup review cursor"):
        repo._dedup_cursor_params("bad")


@pytest.mark.asyncio
async def test_list_dedup_reviews_and_decision() -> None:
    session = _Session(
        [
            _Result([{"total_count": 2}]),
            _Result([_dedup_row(_REVIEW_KEY_1), _dedup_row(_REVIEW_KEY_2)]),
        ]
    )

    page = await repo.list_dedup_reviews(
        session,  # type: ignore[arg-type]
        providers=["python-mois-api"],
        min_score=80,
        page_size=1,
    )

    assert len(page.items) == 1
    assert page.next_cursor is not None
    assert page.total_count == 2
    assert session.calls[0]["statement"] == repo._DEDUP_REVIEW_COUNT_SQL
    params = session.calls[1]["params"]
    assert params["providers"] == ["python-mois-api"]
    assert params["min_score"] == 80
    assert params["limit_plus_one"] == 2
    assert params["offset_rows"] == 0

    changed = await repo.set_dedup_review_decision(
        _Session([_Result([{"review_id": _REVIEW_KEY_1}])]),  # type: ignore[arg-type]
        _REVIEW_KEY_1,
        decision="accepted",
        reviewed_by="local-admin",
    )
    assert changed is True


@pytest.mark.asyncio
async def test_list_dedup_reviews_uses_fast_count_without_expansion_filters() -> None:
    session = _Session(
        [
            _Result([{"total_count": 1}]),
            _Result([_dedup_row(_REVIEW_KEY_1)]),
        ]
    )

    page = await repo.list_dedup_reviews(
        session,  # type: ignore[arg-type]
        min_score=80,
        page_size=1,
    )

    assert page.total_count == 1
    assert session.calls[0]["statement"] == repo._DEDUP_REVIEW_FAST_COUNT_SQL
    assert "JOIN feature.features" not in session.calls[0]["statement"]

    unchanged = await repo.set_dedup_review_decision(
        _Session([_Result([])]),  # type: ignore[arg-type]
        _REVIEW_KEY_1,
        decision="ignored",
    )
    assert unchanged is False


@pytest.mark.asyncio
async def test_merge_dedup_review_auto_and_explicit_master(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _merge_from_review(
        _session: object,
        review_id: str,
        *,
        merged_by: str | None = None,
        reason: str | None = None,
    ) -> MergeOutcome:
        assert review_id == _REVIEW_KEY_1
        assert merged_by == "local-admin"
        assert reason == "dup"
        return MergeOutcome("feature-a", "feature-b", 1, 0, "merge-1", True)

    async def _apply_feature_merge(
        _session: object,
        *,
        master_id: str,
        loser_id: str,
        score: float | None = None,
        review_id: str | None = None,
        merged_by: str | None = None,
        reason: str | None = None,
    ) -> MergeOutcome:
        assert master_id == "feature-b"
        assert loser_id == "feature-a"
        assert score == 90.0
        assert review_id == _REVIEW_KEY_1
        return MergeOutcome(master_id, loser_id, 0, 0, "merge-2", True)

    monkeypatch.setattr(repo, "merge_from_review", _merge_from_review)
    monkeypatch.setattr(repo, "apply_feature_merge", _apply_feature_merge)

    auto = await repo.merge_dedup_review(
        object(),  # type: ignore[arg-type]
        _REVIEW_KEY_1,
        merged_by="local-admin",
        reason="dup",
    )
    assert auto.merge_id == "merge-1"

    explicit = await repo.merge_dedup_review(
        _Session([_Result([_dedup_row(_REVIEW_KEY_1)])]),  # type: ignore[arg-type]
        _REVIEW_KEY_1,
        master_feature_id="feature-b",
    )
    assert explicit.master_feature_id == "feature-b"

    with pytest.raises(MergeError, match="master_feature_id"):
        await repo.merge_dedup_review(
            _Session([_Result([_dedup_row(_REVIEW_KEY_1)])]),  # type: ignore[arg-type]
            _REVIEW_KEY_1,
            master_feature_id="other",
        )

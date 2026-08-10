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
        "lifecycle_state": "active",
        "publication_state": "published",
        "quality_state": "valid",
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
        "feature_uuid_a": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "name_a": "장소 A",
        "kind_a": "place",
        "category_a": "01070300",
        "lon_a": 126.9,
        "lat_a": 37.5,
        "provider_a": "python-mois-api",
        "dataset_key_a": "mois_license_features_bulk",
        "feature_id_b": "feature-b",
        "feature_uuid_b": None,
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


def test_user_override_payload_rejects_provider_owned_detail_and_keeps_null_coord() -> None:
    with pytest.raises(ValueError, match="provider-owned detail field"):
        repo._override_payload_for_change(
            feature_id="feature-user-override",
            feature_uuid="00000000-0000-4000-8000-000000000099",
            kind="place",
            payload={"detail": {"payload": {"provider_raw": "cannot-edit"}}},
            include_required_create_fields=False,
        )

    values, geometry_wkt = repo._override_payload_for_change(
        feature_id="feature-user-override",
        feature_uuid="00000000-0000-4000-8000-000000000099",
        kind="place",
        payload={"coord": None},
        include_required_create_fields=False,
    )
    assert values == {"core.coord_precision_digits": None}
    assert geometry_wkt == {"core.coord": None}
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
        provider_dataset_id=42,
        has_issue=True,
        page_size=1,
        sort="issue_count",
        order="desc",
    )

    assert len(page.items) == 1
    assert page.next_cursor is not None
    params = session.calls[0]["params"]
    assert params["q_like"] == "%광화문%"
    assert params["q_exact"] is None
    assert params["provider_dataset_id"] == 42
    assert params["has_issue"] is True
    # 일반 검색어는 q-필터 상관 서브쿼리(source_records AS qsr, ILIKE 경로)를 그대로 탄다.
    assert "AS qsr" in session.calls[0]["statement"]


def test_feature_id_exact_query_detects_full_feature_ids() -> None:
    # 완전한 feature_id(f_{bjd}_{kind}_{sha1[:16]})는 그대로 반환 → PK fast-path.
    assert (
        repo._feature_id_exact_query("f_1168010100_p_a1b2c3d4e5f6a7b8")
        == "f_1168010100_p_a1b2c3d4e5f6a7b8"
    )
    assert (
        repo._feature_id_exact_query("f_global_e_0123456789abcdef") == "f_global_e_0123456789abcdef"
    )
    # 부분 검색어·비-feature_id는 None → 기존 ILIKE 경로 유지.
    assert repo._feature_id_exact_query("광화문") is None
    assert repo._feature_id_exact_query("f_1168010100_p_a1b2c3") is None
    assert repo._feature_id_exact_query("a1b2c3d4e5f6a7b8") is None
    assert repo._feature_id_exact_query("f_1168010100_p_a1b2c3d4e5f6a7b8x") is None
    assert repo._feature_id_exact_query(None) is None


@pytest.mark.asyncio
async def test_list_admin_features_full_id_uses_pk_fast_path() -> None:
    feature_id = "f_1168010100_p_a1b2c3d4e5f6a7b8"
    session = _Session([_Result([_feature_row(feature_id)])])

    await repo.list_admin_features(
        session,  # type: ignore[arg-type]
        q=f"  {feature_id}  ",
        page_size=20,
        sort="updated_at",
        order="desc",
    )

    call = session.calls[0]
    # PK 등가 파라미터만 바인딩, ILIKE substring은 비활성.
    assert call["params"]["q_exact"] == feature_id
    assert call["params"]["q_like"] is None
    # SQL은 PK 등가절만 쓰고, q-필터 상관 서브쿼리(source_records AS qsr)·:q_like는 타지 않는다.
    # (기본 소스 조회용 source_records AS sr projection은 두 경로 모두 남아 있으므로 qsr로 구분.)
    assert "f.feature_id = CAST(:q_exact AS text)" in call["statement"]
    assert "AS qsr" not in call["statement"]
    assert ":q_like" not in call["statement"]


@pytest.mark.asyncio
async def test_get_admin_feature_detail_aggregates_rows_without_feature_files_table() -> None:
    feature_row = {
        "feature_id": "feature-1",
        "kind": "place",
        "name": "광화문",
        "category": "01070300",
        "lifecycle_state": "active",
        "publication_state": "published",
        "quality_state": "valid",
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
        "row_revision": 1,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    source_row = {
        "source_entity_key": "se-feature-1",
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
        "observed_at": _NOW,
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
        "field_path": "lifecycle_state",
        "source_value": '"active"',
        "override_value": '"retired"',
        "prevent_provider_reactivation": True,
        "status": "active",
        "reason": "운영상 제외",
        "created_by": "local-admin",
        "created_at": _NOW,
    }
    transition_row = {
        "transition_id": 41,
        "from_lifecycle_state": "active",
        "from_publication_state": "published",
        "from_quality_state": "valid",
        "to_lifecycle_state": "retired",
        "to_publication_state": "suppressed",
        "to_quality_state": "valid",
        "transition_kind": "admin_retire",
        "reason_code": "operator_retire",
        "principal": "local-admin",
        "causation_ref": None,
        "provider_dataset_id": None,
        "source_entity_key": None,
        "source_record_key": None,
        "occurred_at": _NOW,
        "row_revision": 2,
    }
    session = _Session(
        [
            _Result([feature_row]),
            _Result([source_row]),
            _Result([issue_row]),
            _Result([override_row]),
            _Result([{"exists": False}]),
            _Result([transition_row]),
        ]
    )

    detail = await repo.get_admin_feature_detail(
        session,  # type: ignore[arg-type]
        "feature-1",
    )

    assert detail is not None
    assert detail.feature.row_revision == 1
    assert detail.feature.raw_refs == [{"source": "fixture"}]
    assert detail.sources[0].raw_data == {"id": "sr-feature-1"}
    assert detail.issues[0].payload == {"field": "address"}
    assert detail.overrides[0].override_value == "retired"
    assert detail.files == ()
    assert detail.state_transitions[0].transition_id == 41
    assert "feature.feature_state_transitions" in session.calls[-1]["statement"]


@pytest.mark.asyncio
async def test_admin_state_commands_call_named_procedures_and_return_receipts() -> None:
    session = _Session(
        [
            _Result(
                [
                    {
                        "feature_id": "feature-1",
                        "row_revision": 8,
                        "o_feature_id": "feature-1",
                        "o_row_revision": 8,
                        "o_transition_id": 41,
                    }
                ]
            ),
            _Result(
                [
                    {
                        "feature_id": "feature-1",
                        "lifecycle_state": "active",
                        "publication_state": "suppressed",
                        "quality_state": "valid",
                        "row_revision": 8,
                    }
                ]
            ),
        ]
    )

    result = await repo.transition_admin_feature_state(
        session,  # type: ignore[arg-type]
        "feature-1",
        publication_state="suppressed",
        expected_row_revision=7,
        reason_code="operator_suppress",
        operator="local-admin",
        action="patch",
    )

    assert result.audit_transition_id == 41
    assert result.publication_state == "suppressed"
    command = session.calls[0]
    assert "feature.transition_admin_feature_state" in command["statement"]
    assert command["params"]["action"] == "patch"
    assert command["params"]["reason_code"] == "operator_suppress"


@pytest.mark.asyncio
async def test_admin_reactivation_passes_source_evidence_to_named_procedure() -> None:
    session = _Session(
        [
            _Result(
                [
                    {
                        "o_feature_id": "feature-1",
                        "o_row_revision": 12,
                        "o_transition_id": 42,
                    }
                ]
            ),
            _Result(
                [
                    {
                        "feature_id": "feature-1",
                        "lifecycle_state": "active",
                        "publication_state": "suppressed",
                        "quality_state": "valid",
                        "row_revision": 12,
                    }
                ]
            ),
        ]
    )

    result = await repo.reactivate_admin_feature_state(
        session,  # type: ignore[arg-type]
        "feature-1",
        expected_row_revision=11,
        reason_code="source_revalidated",
        operator="local-admin",
        provider_dataset_id=17,
        source_entity_key="entity:17",
        source_record_key="record:17",
    )

    assert result.audit_transition_id == 42
    command = session.calls[0]
    assert "feature.reactivate_admin_feature_state" in command["statement"]
    assert command["params"]["provider_dataset_id"] == 17
    assert command["params"]["source_entity_key"] == "entity:17"

def test_dedup_row_mapping() -> None:
    item = repo._dedup_review_row(_dedup_row())

    assert item.feature_a.feature_id == "feature-a"
    assert item.feature_a.feature_uuid == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert item.feature_b.feature_uuid is None
    assert item.feature_b.lon is None
    assert item.distance_m is None


@pytest.mark.asyncio
async def test_list_dedup_reviews_and_decision() -> None:
    session = _Session(
        [
            _Result([{"total_count": 2}]),
            _Result([_dedup_row(_REVIEW_KEY_1)]),
        ]
    )

    page = await repo.list_dedup_reviews(
        session,  # type: ignore[arg-type]
        providers=["python-mois-api"],
        min_score=80,
        page_size=1,
    )

    assert len(page.items) == 1
    assert page.total_count == 2
    assert session.calls[0]["statement"] == repo._DEDUP_REVIEW_COUNT_SQL
    params = session.calls[1]["params"]
    assert params["providers"] == ["python-mois-api"]
    assert params["min_score"] == 80
    assert params["limit_plus_one"] == 2
    assert params["cursor_review_id"] is None
    assert params["cursor_score"] is None

    changed = await repo.set_dedup_review_decision(
        _Session([_Result([{"review_id": _REVIEW_KEY_1}])]),  # type: ignore[arg-type]
        _REVIEW_KEY_1,
        decision="accepted",
        reviewed_by="local-admin",
    )
    assert changed is True

    unchanged = await repo.set_dedup_review_decision(
        _Session([_Result([])]),  # type: ignore[arg-type]
        _REVIEW_KEY_1,
        decision="ignored",
    )
    assert unchanged is False


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


def test_review_cursor_rejects_bad_uuid_and_non_finite_score() -> None:
    """유효 fingerprint를 통과해도 비-UUID review_id·비유한 score cursor는 ValueError.

    이 값들이 SQL의 CAST(... AS uuid)/numeric까지 새면 DataError(→500)이거나 NaN이
    최대로 정렬돼 keyset이 top으로 조용히 리셋되므로 Python 측에서 fail-closed한다.
    라우터는 이 ValueError를 422로 매핑한다(500 아님).
    """
    fingerprint = repo._review_filter_fingerprint(
        "dedup_review", {"statuses": ["pending"]}
    )
    bad_uuid = repo._encode_review_cursor(
        kind="dedup_review",
        fingerprint=fingerprint,
        review_id="not-a-uuid",
        score="1.0",
    )
    with pytest.raises(ValueError, match="invalid dedup_review cursor"):
        repo._review_cursor_params(
            bad_uuid, kind="dedup_review", fingerprint=fingerprint
        )
    for bad_score in ("NaN", "Infinity", "-Infinity"):
        cursor = repo._encode_review_cursor(
            kind="dedup_review",
            fingerprint=fingerprint,
            review_id="00000000-0000-0000-0000-000000000001",
            score=bad_score,
        )
        with pytest.raises(ValueError, match="invalid dedup_review cursor"):
            repo._review_cursor_params(
                cursor, kind="dedup_review", fingerprint=fingerprint
            )
    # 정상 cursor는 그대로 keyset 파라미터로 통과한다.
    good = repo._encode_review_cursor(
        kind="dedup_review",
        fingerprint=fingerprint,
        review_id="00000000-0000-0000-0000-000000000001",
        score="90.5",
    )
    params = repo._review_cursor_params(
        good, kind="dedup_review", fingerprint=fingerprint
    )
    assert params["cursor_review_id"] == "00000000-0000-0000-0000-000000000001"
    assert params["cursor_score"] == "90.5"


def test_review_fingerprint_is_multiselect_order_independent() -> None:
    """multi-select 필터 값 순서가 바뀌어도 같은 fingerprint여야 cursor가 유지된다."""
    forward = repo._review_filter_fingerprint(
        "dedup_review",
        {"providers": ["python-mois-api", "python-visitkorea-api"]},
    )
    reversed_ = repo._review_filter_fingerprint(
        "dedup_review",
        {"providers": ["python-visitkorea-api", "python-mois-api"]},
    )
    assert forward == reversed_
    # 값 집합 자체가 달라지면 fingerprint도 달라진다.
    subset = repo._review_filter_fingerprint(
        "dedup_review", {"providers": ["python-mois-api"]}
    )
    assert forward != subset

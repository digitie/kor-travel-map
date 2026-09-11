"""ADR-090 post-Alembic runtime ACL inventory 단위 테스트."""

from __future__ import annotations

import pytest

from kortravelmap.infra.runtime_privileges import (
    _CORE_FEATURE_GRANTS,
    _DECLARED_ROUTINES,
    _MANUAL_FEATURE_TABLE_ACL,
    _MANUAL_FEATURE_WRITER_ACL,
    _OPTIONAL_ROUTINES,
    _ROUTE_AREA_RUNTIME_GRANTS,
    RuntimePrivilegeReconciliationError,
    _render_acl_statement,
    _resolve_declared_routines,
    _ResolvedRoutine,
    _runtime_relation_grants,
)


@pytest.mark.unit
def test_runtime_acl_inventory_keeps_state_audit_and_its_sequence_ungranted() -> None:
    """state/audit relation은 explicit runtime DML grant 후보가 될 수 없다."""

    grants, unknown = _runtime_relation_grants(
        [
            {
                "schema_name": "feature",
                "relation_name": "features",
                "relation_kind": "r",
            },
            {
                "schema_name": "feature",
                "relation_name": "feature_state_transitions",
                "relation_kind": "r",
            },
            {
                "schema_name": "feature",
                "relation_name": "manual_feature_identity_claims",
                "relation_kind": "r",
            },
            {
                "schema_name": "feature",
                "relation_name": "feature_creation_origins",
                "relation_kind": "r",
            },
            {
                "schema_name": "feature",
                "relation_name": "feature_base_field_values",
                "relation_kind": "r",
            },
            {
                "schema_name": "feature",
                "relation_name": "feature_state_transitions_transition_id_seq",
                # asyncpg returns pg_class.relkind (PostgreSQL "char") as bytes.
                "relation_kind": b"S",
            },
            {
                "schema_name": "feature",
                "relation_name": "theme_feature_candidates",
                "relation_kind": "r",
            },
            {
                "schema_name": "feature",
                "relation_name": "theme_feature_candidate_transitions",
                "relation_kind": "r",
            },
            {
                "schema_name": "feature",
                "relation_name": "theme_feature_candidate_transitions_transition_id_seq",
                "relation_kind": b"S",
            },
            {
                "schema_name": "feature",
                "relation_name": "public_features",
                "relation_kind": "v",
            },
            {
                "schema_name": "provider_sync",
                "relation_name": "source_records",
                "relation_kind": "r",
            },
            {
                "schema_name": "ops",
                "relation_name": "feature_override_field_paths",
                "relation_kind": "r",
            },
            {
                "schema_name": "ops",
                "relation_name": "feature_overrides",
                "relation_kind": "r",
            },
            {
                "schema_name": "ops",
                "relation_name": "curation_rule_reconcile_operations",
                "relation_kind": "r",
            },
            {
                "schema_name": "ops",
                "relation_name": "curation_cutover_identity_mappings",
                "relation_kind": "r",
            },
            {
                "schema_name": "ops",
                "relation_name": "curation_rule_reconcile_scope_members",
                "relation_kind": "r",
            },
        ]
    )

    assert unknown == []
    rendered = "\n".join(grants)
    assert "feature_state_transitions" not in rendered
    assert "manual_feature_identity_claims" not in rendered
    assert "feature_creation_origins" not in rendered
    assert "feature_base_field_values" not in rendered
    assert "theme_feature_candidates" not in rendered
    assert "theme_feature_candidate_transitions" not in rendered
    assert "curation_rule_reconcile_operations" not in rendered
    assert "curation_rule_reconcile_scope_members" not in rendered
    assert (
        'GRANT SELECT ON TABLE "ops"."curation_cutover_identity_mappings"'
        in rendered
    )
    core_grants = "\n".join(_CORE_FEATURE_GRANTS)
    assert "feature_versions" not in core_grants
    assert (
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "provider_sync"."source_records"' in rendered
    )
    assert "feature_change_requests" not in rendered
    assert 'GRANT SELECT ON TABLE "ops"."feature_overrides"' in rendered
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "ops"."feature_overrides"' not in rendered
    assert 'GRANT SELECT ON TABLE "ops"."feature_override_field_paths"' in rendered
    assert (
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE '
        '"ops"."feature_override_field_paths"'
    ) not in rendered
    assert 'GRANT SELECT ON TABLE "feature"."public_features"' in rendered


@pytest.mark.unit
def test_manual_evidence_relation_acl_stays_with_schema_owner() -> None:
    """manual procedure owner는 table owner가 아니므로 relation ACL을 재설정하지 않는다."""

    table_acl = "\n".join(_MANUAL_FEATURE_TABLE_ACL)
    writer_acl = "\n".join(_MANUAL_FEATURE_WRITER_ACL)

    assert "manual_feature_identity_claims" in table_acl
    assert "feature_creation_origins" in table_acl
    assert "ON TABLE" not in writer_acl
    assert "create_admin_manual_feature_with_initial_state" in writer_acl
    assert "read_admin_manual_feature_provenance" in writer_acl
    assert "reject_manual_feature_hard_purge" in writer_acl


@pytest.mark.unit
def test_runtime_acl_inventory_rejects_a_new_feature_table_until_policy_is_reviewed() -> None:
    """future feature state/audit table이 default privilege로 새지 않게 한다."""

    grants, unknown = _runtime_relation_grants(
        [
            {
                "schema_name": "feature",
                "relation_name": "feature_future_state_evidence",
                "relation_kind": "r",
            }
        ]
    )

    assert grants == []
    assert unknown == ["feature.feature_future_state_evidence"]


@pytest.mark.unit
def test_runtime_acl_inventory_rejects_an_unreviewed_feature_view() -> None:
    """새 view도 table처럼 closed ACL 정책 없이는 기동을 차단한다."""

    grants, unknown = _runtime_relation_grants(
        [
            {
                "schema_name": "feature",
                "relation_name": "feature_future_read_projection",
                "relation_kind": "v",
            }
        ]
    )

    assert grants == []
    assert unknown == ["feature.feature_future_read_projection"]


@pytest.mark.unit
def test_runtime_subtype_column_grants_name_the_target_relation() -> None:
    """column-list UPDATE는 대상 table을 명시해 fresh migration에서도 실행된다."""

    rendered = "\n".join(_ROUTE_AREA_RUNTIME_GRANTS)
    assert (
        "GRANT UPDATE (geom, route_type, geometry_source, geometry_status, "
        "total_distance_meters, expected_duration_minutes, difficulty, begin_name, "
        "begin_address, end_name, end_address, payload) ON feature.feature_routes "
        "TO ktm_feature_runtime"
    ) in rendered
    assert (
        "GRANT UPDATE (geom, area_kind, boundary_source, area_square_meters, "
        "regulation_scope, administrative_office, description, payload) "
        "ON feature.feature_areas TO ktm_feature_runtime"
    ) in rendered


# ── routine 참조 해석 (T-VN-39 재키가 두 시점의 시그니처를 갈라놓은 뒤) ──────────
#
# 이 인벤토리는 `0236 → 300` handoff(baseline root)와 head 두 시점에서 돈다. 인자
# 목록은 소스가 아니라 `pg_proc`에서 온다. 그러면 "부여 대상이 모호하면 실패한다"와
# "아직 없는 것만 건너뛴다"가 코드로 지켜져야 하고, 그것을 여기서 잰다.


def _resolved(keyword: str = "PROCEDURE", argument_types: str = "uuid") -> _ResolvedRoutine:
    return _ResolvedRoutine(keyword=keyword, argument_types=argument_types)


@pytest.mark.unit
def test_the_inventory_names_every_routine_without_a_signature() -> None:
    """이름은 닫힌 채로 남고 시그니처만 파생값이 됐는지 본다."""

    assert len(_DECLARED_ROUTINES) >= 40
    assert "feature.transition_feature_state" in _DECLARED_ROUTINES
    assert set(_OPTIONAL_ROUTINES) <= _DECLARED_ROUTINES


@pytest.mark.unit
def test_an_overloaded_name_fails_instead_of_granting_to_a_guess() -> None:
    """이름이 둘로 해석되면 어느 쪽에 주는지 모호하다 — 주지 않고 멈춘다.

    편의가 아니라 방어다. governed schema에 CREATE를 가진 자가 오버로드를 심으면 이름
    해석이 그쪽으로 갈 수 있고, 이 규칙이 그 포획을 원천 차단한다.
    """

    with pytest.raises(RuntimePrivilegeReconciliationError, match="more than one overload"):
        _resolve_declared_routines(
            [
                {
                    "schema_name": "feature",
                    "routine_name": "transition_feature_state",
                    "routine_kind": "p",
                    "argument_types": "uuid, text, text, text, bigint, jsonb",
                },
                {
                    "schema_name": "feature",
                    "routine_name": "transition_feature_state",
                    # asyncpg는 ``prokind``를 build에 따라 bytes로 준다.
                    "routine_kind": b"p",
                    "argument_types": "text, text, text, text, bigint, jsonb",
                },
            ]
        )


@pytest.mark.unit
def test_a_catalog_argument_list_that_is_not_a_plain_type_list_fails() -> None:
    """인자 문자열이 이 조정기가 실행하는 SQL 중 유일한 DB 파생 텍스트다."""

    with pytest.raises(RuntimePrivilegeReconciliationError, match="not a plain type list"):
        _resolve_declared_routines(
            [
                {
                    "schema_name": "feature",
                    "routine_name": "transition_feature_state",
                    "routine_kind": "p",
                    "argument_types": "uuid) TO ktm_feature_runtime; --",
                }
            ]
        )


@pytest.mark.unit
def test_an_unsupported_routine_kind_fails() -> None:
    """aggregate/window는 이 인벤토리의 대상이 아니다 — 조용히 통과시키지 않는다."""

    with pytest.raises(RuntimePrivilegeReconciliationError, match="prokind"):
        _resolve_declared_routines(
            [
                {
                    "schema_name": "feature",
                    "routine_name": "transition_feature_state",
                    "routine_kind": "a",
                    "argument_types": "uuid",
                }
            ]
        )


@pytest.mark.unit
def test_the_catalog_signature_fills_the_reference_at_both_states() -> None:
    """같은 인벤토리 문장이 `300`에서는 text로, head에서는 uuid로 rendering된다."""

    statement = "REVOKE ALL ON PROCEDURE feature.transition_feature_state(...) FROM PUBLIC"
    head = _render_acl_statement(
        statement,
        {
            "feature.transition_feature_state": _resolved(
                argument_types="uuid, text, text, text, bigint, jsonb"
            )
        },
    )
    baseline_root = _render_acl_statement(
        statement,
        {
            "feature.transition_feature_state": _resolved(
                argument_types="text, text, text, text, bigint, jsonb"
            )
        },
    )
    assert head == (
        "REVOKE ALL ON PROCEDURE "
        "feature.transition_feature_state(uuid, text, text, text, bigint, jsonb) FROM PUBLIC"
    )
    assert baseline_root == (
        "REVOKE ALL ON PROCEDURE "
        "feature.transition_feature_state(text, text, text, text, bigint, jsonb) FROM PUBLIC"
    )


@pytest.mark.unit
def test_a_zero_argument_routine_renders_empty_parentheses() -> None:
    """인자 없는 trigger function도 같은 자리표시자를 쓴다."""

    assert (
        _render_acl_statement(
            "REVOKE ALL ON FUNCTION feature.write_feature_state_transition(...) FROM PUBLIC",
            {
                "feature.write_feature_state_transition": _resolved(
                    keyword="FUNCTION", argument_types=""
                )
            },
        )
        == "REVOKE ALL ON FUNCTION feature.write_feature_state_transition() FROM PUBLIC"
    )


@pytest.mark.unit
def test_an_absent_required_routine_fails_instead_of_being_skipped() -> None:
    """조용한 건너뜀은 `_OPTIONAL_ROUTINES`에 적힌 것에만 허용된다."""

    with pytest.raises(RuntimePrivilegeReconciliationError, match="does not exist"):
        _render_acl_statement(
            "REVOKE ALL ON PROCEDURE feature.transition_feature_state(...) FROM PUBLIC", {}
        )


@pytest.mark.unit
def test_an_absent_optional_routine_skips_only_its_own_statement() -> None:
    """`300` 시점에 없는 307/304 산물은 건너뛰되, 섞인 문장은 실패로 잡는다.

    문장 하나를 통째로 건너뛰면 같은 문장에 있던 present 루틴의 ACL이 **조용히**
    사라진다. 그것이 이 fence가 막는 형태다.
    """

    assert (
        _render_acl_statement(
            "REVOKE ALL ON FUNCTION feature.reject_manual_feature_truncate(...) FROM PUBLIC", {}
        )
        is None
    )
    with pytest.raises(RuntimePrivilegeReconciliationError, match="mixes absent optional"):
        _render_acl_statement(
            "REVOKE ALL ON FUNCTION feature.reject_manual_feature_truncate(...), "
            "feature.write_feature_state_transition(...) FROM PUBLIC",
            {
                "feature.write_feature_state_transition": _resolved(
                    keyword="FUNCTION", argument_types=""
                )
            },
        )


@pytest.mark.unit
def test_a_routine_kind_that_drifted_from_the_declaration_fails() -> None:
    """사이드카가 함수를 프로시저로 바꾸면 리터럴 키워드가 조용히 틀린다."""

    with pytest.raises(RuntimePrivilegeReconciliationError, match="wrong routine kind"):
        _render_acl_statement(
            "REVOKE ALL ON PROCEDURE feature.transition_feature_state(...) FROM PUBLIC",
            {"feature.transition_feature_state": _resolved(keyword="FUNCTION")},
        )


@pytest.mark.unit
def test_statements_without_a_routine_reference_pass_through_untouched() -> None:
    """표/시퀀스 문장은 해석 대상이 아니다 — 손대지 않고 그대로 실행한다."""

    statement = 'GRANT SELECT ON TABLE "ops"."feature_overrides" TO ktm_feature_runtime'
    assert _render_acl_statement(statement, {}) == statement

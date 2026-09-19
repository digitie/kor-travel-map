"""ADR-090 post-Alembic runtime ACL inventory 단위 테스트."""

from __future__ import annotations

import re

import pytest

from kortravelmap.infra import curation_candidate_repo
from kortravelmap.infra.runtime_privileges import (
    _ACL_ROLE_WINDOWS,
    _CORE_FEATURE_GRANTS,
    _CURATION_CANDIDATE_READ_ACL,
    _CURATION_CANDIDATE_READ_RELATIONS,
    _DECLARED_ROUTINES,
    _FEATURE_TABLE_PRIVILEGES,
    _MANUAL_FEATURE_TABLE_ACL,
    _MANUAL_FEATURE_WRITER_ACL,
    _OPTIONAL_ROUTINES,
    _PROTECTED_FEATURE_TABLES,
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
    # 후보 축 둘은 **인벤토리 경로로는** 열지 않는다. 그 경로는 `0236 -> 300`
    # handoff에서도 돌고, 이 표들은 300 baseline에 이미 있어서 거기서 GRANT가
    # 나가면 봉인된 destination catalog가 어긋난다(CI PostGIS 실측).
    # 읽기는 `_CURATION_CANDIDATE_READ_ACL`이 **head에서만** 조건부로 연다 —
    # 아래 전용 검사가 그 조건까지 센다.
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
    # route는 ADR-099 2단계에서 `geom`이 보조 relation으로 갔다. 목록에서 빠졌지만
    # ACL이 사라지면 안 된다 — revision 300에는 컬럼이 아직 있고 handoff가 그
    # catalog를 immutable reference와 대조한다. 그래서 **컬럼이 있을 때만** 거는
    # 조건부 블록으로 남는다.
    assert (
        "GRANT UPDATE (route_type, geometry_source, geometry_status, "
        "total_distance_meters, expected_duration_minutes, difficulty, begin_name, "
        "begin_address, end_name, end_address, payload) ON feature.feature_routes "
        "TO ktm_feature_runtime"
    ) in rendered
    assert "attname = 'geom'" in rendered, (
        "`feature_routes.geom` ACL이 조건부로도 남아 있지 않다 — revision 300 "
        "handoff가 destination catalog 불일치로 멎는다(2026-09-10 `feature_uuid` 사고)."
    )
    assert (
        "GRANT INSERT (geom), UPDATE (geom) ON feature.feature_routes"
        " TO ktm_feature_runtime"
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


#: admin 큐레이션 읽기 SQL이 참조하는 `feature.<표>`. 손으로 적지 않는다 — repo의
#: SQL 문자열에서 뽑는다. 새 표를 join하면 이 집합이 저절로 넓어지고, 그것이 보호
#: 목록에 있는데 grant가 없으면 아래 검사가 빨개진다.
_FEATURE_RELATION = re.compile(r"(?<![A-Za-z0-9_])feature[.]([a-z_][a-z0-9_]*)")


def _admin_curation_read_relations() -> frozenset[str]:
    sources = (
        curation_candidate_repo._CANDIDATE_FROM,
        curation_candidate_repo._LIST_SQL,
        curation_candidate_repo._GET_SQL,
        curation_candidate_repo._TRANSITIONS_SQL,
    )
    return frozenset(
        name for sql in sources for name in _FEATURE_RELATION.findall(sql)
    )


def _relations_granted_select_to_runtime() -> frozenset[str]:
    """런타임 롤이 SELECT를 갖게 되는 `feature` relation.

    두 경로를 **모두** 본다 — 정적/조건부 ACL 창(`_ACL_ROLE_WINDOWS`)과 인벤토리
    표(`_FEATURE_TABLE_PRIVILEGES`). 한쪽만 보면 다른 쪽으로 옮기는 변경이 조용히
    통과한다(실제로 이 파일에서 두 번 옮겼다).

    ACL 창의 문장은 `DO $$ ... EXECUTE 'GRANT ...' ... $$`로 감싸일 수 있으므로
    문자열을 쪼개지 않고 패턴으로 찾는다.
    """

    granted: set[str] = set()
    pattern = re.compile(
        r"GRANT\s+SELECT[^']*?\s+ON\s+(?:TABLE\s+)?feature\.(\w+)\s+TO\s+ktm_feature_runtime"
    )
    for _role, statements in _ACL_ROLE_WINDOWS:
        for statement in statements:
            granted.update(pattern.findall(statement))
    for relation, privileges in _FEATURE_TABLE_PRIVILEGES.items():
        if "SELECT" in privileges and relation not in _PROTECTED_FEATURE_TABLES:
            granted.add(relation)
    return frozenset(granted)


@pytest.mark.unit
def test_every_protected_relation_the_admin_read_path_touches_is_granted() -> None:
    """admin 큐레이션 읽기가 **읽을 수 없는** 표를 join하면 그 자리에서 빨개진다.

    T-VN-40이 후보 표 넷을 보호 목록에 넣으면서 일괄 grant 경로를 끊었는데, admin
    읽기 경로가 쓰는 둘에 명시 grant를 주지 않았다. prod에서
    `GET /v1/admin/theme-feature-candidates`가
    `permission denied for table theme_feature_candidates`로 **500**이었고
    (2026-09-18 n150 실측), 저장소의 어떤 검사도 빨개지지 않았다 — 통합 테스트는
    superuser로 돌기 때문이다.

    그래서 이름을 적지 않고 **SQL에서 뽑는다.** 새 보호 표를 join하는 순간 이
    검사가 그 이름을 들고 실패한다.
    """

    touched = _admin_curation_read_relations()
    assert "theme_feature_candidates" in touched, touched

    granted = _relations_granted_select_to_runtime()
    blocked = sorted(
        name
        for name in touched
        if name in _PROTECTED_FEATURE_TABLES and name not in granted
    )
    assert not blocked, (
        "admin 읽기 경로가 런타임 롤에 보이지 않는 보호 표를 참조한다: "
        + ", ".join(blocked)
    )


@pytest.mark.unit
def test_the_candidate_read_grant_is_conditional_and_read_only() -> None:
    """후보 축 읽기 grant는 **head에서만** 걸리고, 읽기만 연다.

    조건이 없으면 `0236 -> 300` handoff가 멎는다 — 이 조정기는 revision 300에서도
    돌고 그 직후 catalog가 image에 봉인된 immutable reference와 대조되는데,
    T-VN-40 표는 retired 마이그레이션이 300 baseline에 접어 넣어 **300에도 있다.**
    CI PostGIS가 이것을 두 번 잡았다.

    `_SHADOW_COLUMN_GRANTS`가 쓰는 신호를 반대로 쓴다 — shadow 컬럼 `feature_uuid`는
    300에 있고 309가 지운다. 그래서 `IF NOT EXISTS(... feature_uuid ...)`다.
    """

    assert _CURATION_CANDIDATE_READ_ACL
    assert len(_CURATION_CANDIDATE_READ_ACL) == len(_CURATION_CANDIDATE_READ_RELATIONS)

    for statement in _CURATION_CANDIDATE_READ_ACL:
        # 조건부여야 한다 — 이 두 조각이 곧 300 안전성의 논증이다.
        assert "IF NOT EXISTS" in statement, statement
        assert "feature_uuid" in statement, statement
        # 읽기만 연다.
        assert "GRANT SELECT ON" in statement, statement
        assert "INSERT" not in statement, statement
        assert "UPDATE" not in statement, statement
        assert "DELETE" not in statement, statement
        assert "TO ktm_feature_runtime" in statement, statement

    granted = _relations_granted_select_to_runtime()
    for relation in _CURATION_CANDIDATE_READ_RELATIONS:
        assert relation in granted, relation
        # 일괄 grant 경로에는 남겨 두지 않는다(300에서 돌기 때문).
        assert relation in _PROTECTED_FEATURE_TABLES, relation
        assert relation not in _FEATURE_TABLE_PRIVILEGES, relation

    #: 생성 축 둘은 열지 않는다 — admin 읽기 SQL이 참조하지 않는다.
    for relation in ("theme_candidate_generations", "theme_candidate_generation_observations"):
        assert relation in _PROTECTED_FEATURE_TABLES, relation
        assert relation not in granted, relation

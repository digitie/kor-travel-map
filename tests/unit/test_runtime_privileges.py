"""ADR-090 post-Alembic runtime ACL inventory 단위 테스트."""

from __future__ import annotations

import pytest

from kortravelmap.infra.runtime_privileges import (
    _CORE_FEATURE_GRANTS,
    _ROUTE_AREA_RUNTIME_GRANTS,
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
                "relation_name": "feature_versions",
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
                "relation_name": "feature_change_requests",
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
        ]
    )

    assert unknown == []
    rendered = "\n".join(grants)
    assert "feature_state_transitions" not in rendered
    assert "feature_base_field_values" not in rendered
    core_grants = "\n".join(_CORE_FEATURE_GRANTS)
    assert "GRANT SELECT ON feature.feature_versions TO ktm_feature_runtime" in core_grants
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON feature.feature_versions" not in core_grants
    assert (
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "provider_sync"."source_records"' in rendered
    )
    assert (
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "ops"."feature_change_requests"' in rendered
    )
    assert 'GRANT SELECT ON TABLE "ops"."feature_overrides"' in rendered
    assert 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "ops"."feature_overrides"' not in rendered
    assert 'GRANT SELECT ON TABLE "ops"."feature_override_field_paths"' in rendered
    assert (
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE '
        '"ops"."feature_override_field_paths"'
    ) not in rendered
    assert 'GRANT SELECT ON TABLE "feature"."public_features"' in rendered


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

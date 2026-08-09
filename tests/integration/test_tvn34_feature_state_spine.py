"""T-VN-34A 직교 Feature 상태 DB spine의 집중 PostgreSQL 계약."""

from __future__ import annotations

import json
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_LEGAL_TUPLES: Sequence[tuple[str, str, str]] = (
    ("active", "draft", "valid"),
    ("active", "draft", "quarantined"),
    ("active", "published", "valid"),
    ("active", "published", "quarantined"),
    ("active", "suppressed", "valid"),
    ("active", "suppressed", "quarantined"),
    ("retired", "suppressed", "valid"),
    ("retired", "suppressed", "quarantined"),
)


def _payload(feature_id: str, *, name: str) -> str:
    """0095 create procedure가 받는 provider core payload (legacy status 없음)."""

    return json.dumps(
        {
            "feature_id": feature_id,
            "kind": "place",
            "name": name,
            "category": "tvn34-state",
            "address": {},
            "urls": {},
            "raw_refs": [],
        }
    )


async def _call_create(
    session: AsyncSession,
    *,
    feature_id: str,
    state: tuple[str, str, str],
    context: dict[str, Any],
) -> None:
    await session.execute(
        text(
            """
            CALL feature.create_feature_with_initial_state(
                CAST(:payload AS jsonb), :lifecycle_state, :publication_state,
                :quality_state, CAST(:context AS jsonb),
                NULL, NULL, NULL, NULL
            )
            """
        ),
        {
            "payload": _payload(feature_id, name=feature_id),
            "lifecycle_state": state[0],
            "publication_state": state[1],
            "quality_state": state[2],
            "context": json.dumps(context),
        },
    )


async def _call_transition(
    session: AsyncSession,
    *,
    feature_id: str,
    state: tuple[str, str, str],
    expected_revision: int,
    context: dict[str, Any],
) -> None:
    await session.execute(
        text(
            """
            CALL feature.transition_feature_state(
                :feature_id, :lifecycle_state, :publication_state, :quality_state,
                :expected_revision, CAST(:context AS jsonb), NULL, NULL
            )
            """
        ),
        {
            "feature_id": feature_id,
            "lifecycle_state": state[0],
            "publication_state": state[1],
            "quality_state": state[2],
            "expected_revision": expected_revision,
            "context": json.dumps(context),
        },
    )


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _constraint_name(error: DBAPIError) -> str | None:
    """SQLAlchemy asyncpg adapter 아래의 PostgreSQL constraint metadata를 찾는다."""

    candidate: BaseException | None = error.orig
    while candidate is not None:
        constraint_name = getattr(candidate, "constraint_name", None)
        if isinstance(constraint_name, str):
            return constraint_name
        candidate = candidate.__cause__
    return None


async def test_tvn34_all_legal_tuples_procedure_audit_and_runtime_fence(
    migrated_session: AsyncSession,
) -> None:
    """8 tuple, provider initial provenance, one-row audit, privilege fence를 함께 고정."""

    provider_dataset_id = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.provider_datasets (
                    provider, dataset_key, display_name, source_kind
                ) VALUES ('tvn34', 'initial', 'T-VN-34 initial', 'manual')
                RETURNING provider_dataset_id
                """
            )
        )
    ).scalar_one()

    privilege_receipt = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    has_schema_privilege(
                        'ktm_feature_state_procedure_owner', 'x_extension', 'USAGE'
                    ) AS state_owner_x_extension_usage,
                    has_schema_privilege(
                        'ktm_feature_runtime', 'x_extension', 'USAGE'
                    ) AS runtime_x_extension_usage,
                    has_table_privilege(
                        'ktm_feature_state_procedure_owner', 'feature.features', 'SELECT'
                    ) AS state_owner_feature_select,
                    has_table_privilege(
                        'ktm_feature_state_procedure_owner', 'feature.features', 'INSERT'
                    ) AS state_owner_feature_insert,
                    has_column_privilege(
                        'ktm_feature_state_procedure_owner', 'feature.features',
                        'lifecycle_state', 'UPDATE'
                    ) AS state_owner_axis_update,
                    has_column_privilege(
                        'ktm_feature_state_procedure_owner', 'feature.features',
                        'updated_at', 'UPDATE'
                    ) AS state_owner_transition_timestamp_update,
                    has_table_privilege(
                        'ktm_feature_state_procedure_owner',
                        'feature.feature_aliases',
                        'SELECT, INSERT'
                    ) AS state_owner_alias_probe_and_insert,
                    procedure_row.prosecdef AS procedure_security_definer,
                    owner_role.rolname AS procedure_owner
                FROM pg_catalog.pg_proc AS procedure_row
                JOIN pg_catalog.pg_roles AS owner_role ON owner_role.oid = procedure_row.proowner
                WHERE procedure_row.oid =
                    'feature.create_feature_with_initial_state(jsonb,text,text,text,jsonb)'::regprocedure
                """
            )
        )
    ).mappings().one()
    assert dict(privilege_receipt) == {
        "state_owner_x_extension_usage": True,
        "runtime_x_extension_usage": False,
        "state_owner_feature_select": True,
        "state_owner_feature_insert": True,
        "state_owner_axis_update": True,
        "state_owner_transition_timestamp_update": True,
        "state_owner_alias_probe_and_insert": True,
        "procedure_security_definer": True,
        "procedure_owner": "ktm_feature_state_procedure_owner",
    }

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        for index, state in enumerate(_LEGAL_TUPLES, start=1):
            if index == 1:
                context: dict[str, Any] = {
                    "transition_kind": "provider_sync",
                    "reason_code": "provider_initial",
                    "provider_dataset_id": provider_dataset_id,
                }
            else:
                context = {
                    "transition_kind": "initial",
                    "reason_code": "fixture_initial",
                    "principal": "system:tvn34-test",
                }
            await _call_create(
                migrated_session,
                feature_id=f"tvn34-state-{index}",
                state=state,
                context=context,
            )

        states = (
            await migrated_session.execute(
                text(
                    """
                    SELECT lifecycle_state, publication_state, quality_state
                    FROM feature.features
                    WHERE feature_id LIKE 'tvn34-state-%'
                    ORDER BY feature_id
                    """
                )
            )
        ).all()
        assert set(states) == set(_LEGAL_TUPLES)
        audit_rows = (
            await migrated_session.execute(
                text(
                    """
                    SELECT transition_kind, principal,
                           feature_uuid,
                           from_lifecycle_state, from_publication_state, from_quality_state,
                           state_procedure_definer, audit_writer_definer
                    FROM feature.feature_state_transitions
                    WHERE feature_id LIKE 'tvn34-state-%'
                    ORDER BY feature_id
                    """
                )
            )
        ).mappings().all()
        assert len(audit_rows) == len(_LEGAL_TUPLES)
        assert audit_rows[0]["transition_kind"] == "provider_sync"
        assert audit_rows[0]["principal"] == "provider:tvn34/initial"
        assert all(row["feature_uuid"] is not None for row in audit_rows)
        assert all(row["from_lifecycle_state"] is None for row in audit_rows)
        assert all(row["from_publication_state"] is None for row in audit_rows)
        assert all(row["from_quality_state"] is None for row in audit_rows)
        assert {row["state_procedure_definer"] for row in audit_rows} == {
            "ktm_feature_state_procedure_owner"
        }
        assert {row["audit_writer_definer"] for row in audit_rows} == {
            "ktm_feature_audit_writer"
        }

        await _call_transition(
            migrated_session,
            feature_id="tvn34-state-1",
            state=("active", "published", "valid"),
            expected_revision=1,
            context={
                "transition_kind": "admin",
                "reason_code": "publish_after_review",
                "principal": "admin:tvn34-test",
            },
        )
        transition = (
            await migrated_session.execute(
                text(
                    """
                    SELECT from_lifecycle_state, from_publication_state, from_quality_state,
                           to_lifecycle_state, to_publication_state, to_quality_state,
                           row_revision
                    FROM feature.feature_state_transitions
                    WHERE feature_id = 'tvn34-state-1'
                    ORDER BY transition_id DESC
                    LIMIT 1
                    """
                )
            )
        ).mappings().one()
        assert dict(transition) == {
            "from_lifecycle_state": "active",
            "from_publication_state": "draft",
            "from_quality_state": "valid",
            "to_lifecycle_state": "active",
            "to_publication_state": "published",
            "to_quality_state": "valid",
            "row_revision": 2,
        }

        with pytest.raises(DBAPIError) as direct_insert:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        """
                        INSERT INTO feature.features (
                            feature_id, kind, name, category, lifecycle_state,
                            publication_state, quality_state
                        ) VALUES ('tvn34-direct-insert', 'place', 'direct', 'tvn34-state',
                                  'active', 'draft', 'valid')
                        """
                    )
                )
        assert _sqlstate(direct_insert.value) == "42501"

        with pytest.raises(DBAPIError) as direct_axis_update:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        """
                        UPDATE feature.features
                        SET publication_state = 'suppressed'
                        WHERE feature_id = 'tvn34-state-1'
                        """
                    )
                )
        assert _sqlstate(direct_axis_update.value) == "42501"

        with pytest.raises(DBAPIError) as direct_audit_insert:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        """
                        INSERT INTO feature.feature_state_transitions (
                            feature_id, to_lifecycle_state, to_publication_state, to_quality_state,
                            feature_uuid,
                            transition_kind, reason_code, principal, occurred_at, row_revision,
                            invoker_role, state_procedure_definer, audit_writer_definer
                        ) VALUES (
                            'tvn34-direct-audit', 'active', 'draft', 'valid',
                            '00000000-0000-0000-0000-000000000034', 'initial',
                            'direct', 'runtime:forbidden', now(), 1,
                            session_user::text, 'x', 'x'
                        )
                        """
                    )
                )
        assert _sqlstate(direct_audit_insert.value) == "42501"
    finally:
        # 예상 밖 CALL 실패의 원래 SQLSTATE/statement를 RESET ROLE 실패가 가리지 않는다.
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    # Feature hard purge가 audit evidence를 지우지 않는다 (no Feature FK/cascade).
    await migrated_session.execute(
        text("DELETE FROM feature.features WHERE feature_id = 'tvn34-state-8'")
    )
    audit_identity = (
        await migrated_session.execute(
            text(
                "SELECT feature_id, feature_uuid FROM feature.feature_state_transitions "
                "WHERE feature_id = 'tvn34-state-8'"
            )
        )
    ).one()
    assert audit_identity.feature_id == "tvn34-state-8"
    assert audit_identity.feature_uuid is not None


async def test_tvn34_provider_reactivation_override_is_db_fenced(
    migrated_session: AsyncSession,
) -> None:
    """provider 재등장은 active lifecycle override를 해제하거나 audit하지 못한다."""

    provider_dataset_id = (
        await migrated_session.execute(
            text(
                """
                INSERT INTO provider_sync.provider_datasets (
                    provider, dataset_key, display_name, source_kind
                ) VALUES ('tvn34', 'reactivation', 'T-VN-34 reactivation', 'manual')
                RETURNING provider_dataset_id
                """
            )
        )
    ).scalar_one()
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
                first_seen_at, last_seen_at
            ) VALUES ('tvn34-reactivation-entity', :provider_dataset_id, 'place',
                      'tvn34-reactivation-source', now(), now())
            """
        ),
        {"provider_dataset_id": provider_dataset_id},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
            ) VALUES ('tvn34-reactivation-record', 'tvn34-reactivation-entity',
                      '{}'::jsonb, 'd34', now())
            """
        )
    )

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await _call_create(
            migrated_session,
            feature_id="tvn34-reactivation-feature",
            state=("retired", "suppressed", "valid"),
            context={
                "transition_kind": "provider_sync",
                "reason_code": "provider_initial_retired",
                "provider_dataset_id": provider_dataset_id,
            },
        )
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_overrides (
                feature_id, field_path, override_value, prevent_provider_reactivation,
                status, created_by
            ) VALUES (
                'tvn34-reactivation-feature', 'lifecycle_state', '"retired"'::jsonb,
                true, 'active', 'admin:tvn34-test'
            )
            """
        )
    )

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        with pytest.raises(DBAPIError) as fenced:
            async with migrated_session.begin_nested():
                await _call_transition(
                    migrated_session,
                    feature_id="tvn34-reactivation-feature",
                    state=("active", "suppressed", "valid"),
                    expected_revision=1,
                    context={
                        "transition_kind": "provider_sync",
                        "reason_code": "provider_reappeared",
                        "provider_dataset_id": provider_dataset_id,
                        "source_record_key": "tvn34-reactivation-record",
                        "reactivation_evidence": "current_source_record",
                    },
                )
        assert _sqlstate(fenced.value) == "23514"
        assert _constraint_name(fenced.value) == "ck_feature_provider_reactivation_override"
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    assert (
        await migrated_session.scalar(
            text(
                "SELECT count(*) FROM feature.feature_state_transitions "
                "WHERE feature_id = 'tvn34-reactivation-feature'"
            )
        )
        == 1
    )

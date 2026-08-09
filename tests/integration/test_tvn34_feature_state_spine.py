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
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_entities (
                source_entity_key, provider_dataset_id, source_entity_type, source_entity_id,
                first_seen_at, last_seen_at
            ) VALUES ('tvn34-initial-entity', :provider_dataset_id, 'place',
                      'tvn34-initial-source', now(), now())
            """
        ),
        {"provider_dataset_id": provider_dataset_id},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_records (
                source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
            ) VALUES ('tvn34-initial-record', 'tvn34-initial-entity',
                      '{}'::jsonb, 'd340', now())
            """
        )
    )

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
                    has_table_privilege(
                        'ktm_feature_state_procedure_owner',
                        'feature.features_detailed', 'SELECT'
                    ) AS state_owner_detailed_snapshot_select,
                    has_table_privilege(
                        'ktm_feature_state_procedure_owner',
                        'feature.feature_versions', 'SELECT, INSERT'
                    ) AS state_owner_version_snapshot_write,
                    has_table_privilege(
                        'ktm_feature_runtime', 'feature.features_detailed', 'SELECT'
                    ) AS runtime_detailed_snapshot_select,
                    has_table_privilege(
                        'ktm_feature_runtime', 'feature.feature_versions', 'SELECT, INSERT'
                    ) AS runtime_version_snapshot_write,
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
        "runtime_x_extension_usage": True,
        "state_owner_feature_select": True,
        "state_owner_feature_insert": True,
        "state_owner_axis_update": True,
        "state_owner_transition_timestamp_update": True,
        "state_owner_alias_probe_and_insert": True,
        "state_owner_detailed_snapshot_select": True,
        "state_owner_version_snapshot_write": True,
        "runtime_detailed_snapshot_select": False,
        "runtime_version_snapshot_write": False,
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
                    "source_entity_key": "tvn34-initial-entity",
                    "source_record_key": "tvn34-initial-record",
                    "provider_evidence": {"authoritative_receipt": "tvn34-initial"},
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
                           provider_dataset_id, source_entity_key, source_record_key,
                           provider_evidence,
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
        assert audit_rows[0]["provider_dataset_id"] == provider_dataset_id
        assert audit_rows[0]["source_entity_key"] == "tvn34-initial-entity"
        assert audit_rows[0]["source_record_key"] == "tvn34-initial-record"
        assert audit_rows[0]["provider_evidence"] == {"authoritative_receipt": "tvn34-initial"}
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
        text("DELETE FROM feature.features WHERE feature_id = 'tvn34-state-1'")
    )
    audit_identity = (
        await migrated_session.execute(
            text(
                "SELECT feature_id, feature_uuid, provider_dataset_id, source_entity_key, "
                "source_record_key, provider_evidence FROM feature.feature_state_transitions "
                "WHERE feature_id = 'tvn34-state-1' AND transition_kind = 'provider_sync'"
            )
        )
    ).one()
    assert audit_identity.feature_id == "tvn34-state-1"
    assert audit_identity.feature_uuid is not None
    assert audit_identity.provider_dataset_id == provider_dataset_id
    assert audit_identity.source_entity_key == "tvn34-initial-entity"
    assert audit_identity.source_record_key == "tvn34-initial-record"
    assert audit_identity.provider_evidence == {"authoritative_receipt": "tvn34-initial"}


async def test_tvn34_provider_reactivation_override_is_db_fenced(
    migrated_session: AsyncSession,
) -> None:
    """provider retire/reactivate는 link receipt을 요구하고 retired override만 막는다."""

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
                "source_entity_key": "tvn34-reactivation-entity",
                "source_record_key": "tvn34-reactivation-record",
                "provider_evidence": {"authoritative_receipt": "initial-retired"},
            },
        )
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        with pytest.raises(DBAPIError) as unlinked:
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
                        "source_entity_key": "tvn34-reactivation-entity",
                        "source_record_key": "tvn34-reactivation-record",
                        "provider_evidence": {"authoritative_receipt": "unlinked"},
                    },
                )
        assert _sqlstate(unlinked.value) == "23514"
        assert _constraint_name(unlinked.value) == "ck_feature_provider_source_provenance"
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))
    await migrated_session.execute(
        text(
            """
            INSERT INTO provider_sync.source_links (
                feature_id, source_entity_key, source_role, match_method, confidence
            ) VALUES (
                'tvn34-reactivation-feature', 'tvn34-reactivation-entity',
                'primary', 'fixture', 100
            )
            """
        )
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_overrides (
                feature_id, field_path, override_value, prevent_provider_reactivation,
                status, created_by
            ) VALUES (
                'tvn34-reactivation-feature', 'lifecycle_state', '"active"'::jsonb,
                true, 'active', 'admin:tvn34-test'
            )
            """
        )
    )

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        # active value override는 provider reingest를 막지 않는다.
        await _call_transition(
            migrated_session,
            feature_id="tvn34-reactivation-feature",
            state=("active", "suppressed", "valid"),
            expected_revision=1,
            context={
                "transition_kind": "provider_sync",
                "reason_code": "provider_reappeared",
                "provider_dataset_id": provider_dataset_id,
                "source_entity_key": "tvn34-reactivation-entity",
                "source_record_key": "tvn34-reactivation-record",
                "provider_evidence": {"authoritative_receipt": "reappeared"},
            },
        )
        # provider tombstone도 same feature→link→entity→record receipt 없이는 못 간다.
        await _call_transition(
            migrated_session,
            feature_id="tvn34-reactivation-feature",
            state=("retired", "suppressed", "valid"),
            expected_revision=2,
            context={
                "transition_kind": "provider_sync",
                "reason_code": "provider_retire",
                "provider_dataset_id": provider_dataset_id,
                "source_entity_key": "tvn34-reactivation-entity",
                "source_record_key": "tvn34-reactivation-record",
                "provider_evidence": {"authoritative_receipt": "tombstone-receipt"},
            },
        )
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    await migrated_session.execute(
        text(
            """
            UPDATE ops.feature_overrides
            SET override_value = '"retired"'::jsonb
            WHERE feature_id = 'tvn34-reactivation-feature'
              AND field_path = 'lifecycle_state'
              AND status = 'active'
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
                    expected_revision=3,
                    context={
                        "transition_kind": "provider_sync",
                        "reason_code": "provider_reappeared",
                        "provider_dataset_id": provider_dataset_id,
                        "source_entity_key": "tvn34-reactivation-entity",
                        "source_record_key": "tvn34-reactivation-record",
                        "provider_evidence": {"authoritative_receipt": "reappeared"},
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
        == 3
    )


@pytest.mark.parametrize(
    ("forbidden_key", "forbidden_value"),
    [
        ("status", "active"),
        ("deleted_at", "2026-08-09T00:00:00Z"),
        ("user_deleted_at", "2026-08-09T00:00:00Z"),
        ("user_deleted_by", "admin:tvn34"),
        ("user_change_kind", "update"),
        ("user_change_status", "applied"),
        ("user_change_request_id", "00000000-0000-0000-0000-000000003495"),
        ("user_change_reason", "forbidden runtime input"),
    ],
)
async def test_tvn34_runtime_create_rejects_legacy_and_user_provenance_payload_keys(
    migrated_session: AsyncSession,
    forbidden_key: str,
    forbidden_value: str,
) -> None:
    """SECDEF create는 legacy/user state surrogate를 절대 payload에서 받지 않는다."""

    payload = json.loads(_payload(f"tvn34-forbidden-{forbidden_key}", name="forbidden"))
    payload[forbidden_key] = forbidden_value

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        with pytest.raises(DBAPIError) as rejected:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        """
                        CALL feature.create_feature_with_initial_state(
                            CAST(:payload AS jsonb), 'active', 'draft', 'valid',
                            CAST(:context AS jsonb), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {
                        "payload": json.dumps(payload),
                        "context": json.dumps(
                            {
                                "transition_kind": "initial",
                                "reason_code": "forbidden_payload_fixture",
                                "principal": "system:tvn34-test",
                            }
                        ),
                    },
                )
        assert _sqlstate(rejected.value) == "23514"
        assert _constraint_name(rejected.value) == "ck_feature_create_payload"
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))


async def test_tvn34_runtime_materializes_typed_user_change_provenance(
    migrated_session: AsyncSession,
) -> None:
    """runtime은 direct legacy provenance UPDATE 없이 typed SECDEF routine만 호출한다."""

    feature_id = "tvn34-user-provenance"
    request_id = "00000000-0000-0000-0000-000000003496"
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await _call_create(
            migrated_session,
            feature_id=feature_id,
            state=("active", "draft", "valid"),
            context={
                "transition_kind": "initial",
                "reason_code": "user_provenance_fixture",
                "principal": "system:tvn34-test",
            },
        )
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_change_requests (
                request_id, feature_id, action, state, review_mode,
                base_row_revision, payload, reason, requested_by
            ) VALUES (
                CAST(:request_id AS uuid), :feature_id, 'update', 'applied', 'immediate',
                1, '{}'::jsonb, 'typed provenance fixture', 'admin:tvn34-test'
            )
            """
        ),
        {"request_id": request_id, "feature_id": feature_id},
    )

    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        with pytest.raises(DBAPIError) as direct_write:
            async with migrated_session.begin_nested():
                await migrated_session.execute(
                    text(
                        "UPDATE feature.features "
                        "SET user_change_kind = 'update' WHERE feature_id = :feature_id"
                    ),
                    {"feature_id": feature_id},
                )
        assert _sqlstate(direct_write.value) == "42501"

        result = (
            await migrated_session.execute(
                text(
                    """
                    CALL feature.materialize_user_feature_change_provenance(
                        :feature_id, 'update', CAST(:request_id AS uuid),
                        'typed provenance fixture', 'admin:tvn34-test', 1, NULL, NULL
                    )
                    """
                ),
                {"feature_id": feature_id, "request_id": request_id},
            )
        ).one()
        assert result.o_feature_id == feature_id
        assert result.o_row_revision == 2
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    materialized = (
        await migrated_session.execute(
            text(
                """
                SELECT data_origin, data_version, user_change_kind, user_change_status,
                       user_change_request_id::text, user_change_reason
                FROM feature.features WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).one()
    assert tuple(materialized) == (
        "user_request",
        1,
        "update",
        "applied",
        request_id,
        "typed provenance fixture",
    )
    snapshot = (
        await migrated_session.execute(
            text(
                """
                SELECT version, origin, change_kind, request_id::text, created_by,
                       payload ->> 'data_origin' AS payload_data_origin
                FROM feature.feature_versions
                WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": feature_id},
        )
    ).one()
    assert tuple(snapshot) == (
        1,
        "user_request",
        "update",
        request_id,
        "admin:tvn34-test",
        "user_request",
    )


async def test_tvn34_typed_provenance_snapshots_add_after_subtype_and_delete(
    migrated_session: AsyncSession,
) -> None:
    """add/update/delete 모두 typed routine의 단일 provenance/version 경로를 쓴다."""

    add_feature_id = "tvn34-user-add-provenance"
    add_request_id = "00000000-0000-0000-0000-000000003497"
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await _call_create(
            migrated_session,
            feature_id=add_feature_id,
            state=("active", "draft", "valid"),
            context={
                "transition_kind": "initial",
                "reason_code": "user_add_fixture",
                "principal": "system:tvn34-test",
            },
        )
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    # writer가 add의 subtype write를 먼저 끝낸 뒤 typed provenance routine을 호출해야
    # response-shape snapshot이 detail까지 같은 revision으로 고정된다.
    await migrated_session.execute(
        text(
            """
            INSERT INTO feature.feature_places (feature_id, feature_uuid, kind, place_kind)
            SELECT feature_id, feature_uuid, kind, 'tvn34-fixture'
            FROM feature.features WHERE feature_id = :feature_id
            """
        ),
        {"feature_id": add_feature_id},
    )
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_change_requests (
                request_id, feature_id, action, state, review_mode,
                base_row_revision, payload, reason, requested_by
            ) VALUES (
                CAST(:request_id AS uuid), :feature_id, 'add', 'applied', 'immediate',
                1, '{}'::jsonb, 'typed add fixture', 'admin:tvn34-test'
            )
            """
        ),
        {"request_id": add_request_id, "feature_id": add_feature_id},
    )
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        add_result = (
            await migrated_session.execute(
                text(
                    """
                    CALL feature.materialize_user_feature_change_provenance(
                        :feature_id, 'add', CAST(:request_id AS uuid),
                        'typed add fixture', 'admin:tvn34-test', 1, NULL, NULL
                    )
                    """
                ),
                {"feature_id": add_feature_id, "request_id": add_request_id},
            )
        ).one()
        assert add_result.o_row_revision == 2
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    add_snapshot = (
        await migrated_session.execute(
            text(
                """
                SELECT version, change_kind, request_id::text,
                       payload #>> '{detail,place_kind}' AS place_kind
                FROM feature.feature_versions WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": add_feature_id},
        )
    ).one()
    assert tuple(add_snapshot) == (1, "add", add_request_id, "tvn34-fixture")

    delete_feature_id = "tvn34-user-delete-provenance"
    delete_request_id = "00000000-0000-0000-0000-000000003498"
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        await _call_create(
            migrated_session,
            feature_id=delete_feature_id,
            state=("active", "published", "valid"),
            context={
                "transition_kind": "initial",
                "reason_code": "user_delete_fixture",
                "principal": "system:tvn34-test",
            },
        )
        await _call_transition(
            migrated_session,
            feature_id=delete_feature_id,
            state=("retired", "suppressed", "valid"),
            expected_revision=1,
            context={
                "transition_kind": "user_request",
                "reason_code": "user_delete_state",
                "principal": "admin:tvn34-test",
            },
        )
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))
    await migrated_session.execute(
        text(
            """
            INSERT INTO ops.feature_change_requests (
                request_id, feature_id, action, state, review_mode,
                base_row_revision, payload, reason, requested_by
            ) VALUES (
                CAST(:request_id AS uuid), :feature_id, 'delete', 'applied', 'immediate',
                1, '{}'::jsonb, 'typed delete fixture', 'admin:tvn34-test'
            )
            """
        ),
        {"request_id": delete_request_id, "feature_id": delete_feature_id},
    )
    await migrated_session.execute(text("SET ROLE ktm_feature_runtime"))
    try:
        delete_result = (
            await migrated_session.execute(
                text(
                    """
                    CALL feature.materialize_user_feature_change_provenance(
                        :feature_id, 'delete', CAST(:request_id AS uuid),
                        'typed delete fixture', 'admin:tvn34-test', 2, NULL, NULL
                    )
                    """
                ),
                {"feature_id": delete_feature_id, "request_id": delete_request_id},
            )
        ).one()
        assert delete_result.o_row_revision == 3
    finally:
        with suppress(DBAPIError):
            await migrated_session.execute(text("RESET ROLE"))

    delete_snapshot = (
        await migrated_session.execute(
            text(
                """
                SELECT version, change_kind, request_id::text, created_by
                FROM feature.feature_versions WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": delete_feature_id},
        )
    ).one()
    assert tuple(delete_snapshot) == (1, "delete", delete_request_id, "admin:tvn34-test")
    deleted = (
        await migrated_session.execute(
            text(
                """
                SELECT lifecycle_state, publication_state, user_deleted_at IS NOT NULL,
                       user_deleted_by, user_change_kind, user_change_status
                FROM feature.features WHERE feature_id = :feature_id
                """
            ),
            {"feature_id": delete_feature_id},
        )
    ).one()
    assert tuple(deleted) == (
        "retired",
        "suppressed",
        True,
        "admin:tvn34-test",
        "delete",
        "applied",
    )

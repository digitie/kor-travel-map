"""T-VN-M05 전용 candidate/판정 writer의 role·evidence 경계."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import make_async_engine

pytestmark = pytest.mark.integration

_RUNTIME_PASSWORD = "tvn40-test-only-runtime-password"
_SCORES = {
    "name_score": 0.95,
    "spatial_score": 0.97,
    "category_score": 0.80,
    "total_score": 0.93,
    "distance_meters": 12.345,
    "scorer_input_sha256": "a" * 64,
}
_CAUSATION = {"scope": "integration", "input_count": 1}
_ROOT = Path(__file__).resolve().parents[2]


def _restore_lease_rebuild_sql() -> str:
    """운영 restore verifier가 실행하는 M05 reconciliation SQL을 그대로 검증한다."""

    script = (_ROOT / "scripts/docker-restore-verify.sh").read_text(encoding="utf-8")
    marker = "rebuild_feature_reference_reconciliation_leases() {"
    fragment = script.split(marker, 1)[1]
    return fragment.split("<<'SQL'\n", 1)[1].split("\nSQL\n", 1)[0]


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def _open_command(engine: AsyncEngine, *, actor: str, operation: str) -> int:
    async with engine.begin() as connection:
        return int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.domain_commands (
                      actor, operation, idempotency_key, request_fingerprint
                    ) VALUES (
                      :actor, :operation, x_extension.gen_random_uuid(),
                      repeat('d', 64)
                    ) RETURNING command_id
                    """
                ),
                {"actor": actor, "operation": operation},
            )
        )


async def _seed_manual_provider_pair(engine: AsyncEngine) -> dict[str, object]:
    """manual origin/claim과 provider current source proof를 모두 심는다."""

    suffix = uuid4().hex
    manual_feature_id = f"f_global_p_m05manual{suffix[:10]}"
    provider_feature_id = f"f_global_p_m05provider{suffix[:10]}"
    source_entity_key = f"se_m05_{suffix[:12]}"
    source_record_key = f"sr_m05_{suffix[:12]}_a"
    actor = f"admin:tvn-m05-{suffix}"
    manual_command_id = await _open_command(
        engine,
        actor=actor,
        operation="admin.manual-feature-create.manual-v1",
    )
    async with engine.begin() as connection:
        for feature_id, name, lon, lat in (
            (manual_feature_id, "M05 수동 후보", 127.111111, 37.511111),
            (provider_feature_id, "M05 Provider 후보", 127.111222, 37.511222),
        ):
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.features (
                      feature_id, kind, name, category, coord, coord_precision_digits
                    ) VALUES (
                      :feature_id, 'place', :name, '01070300',
                      x_extension.ST_SetSRID(x_extension.ST_MakePoint(:lon, :lat), 4326), 6
                    )
                    """
                ),
                {"feature_id": feature_id, "name": name, "lon": lon, "lat": lat},
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO feature.feature_places (
                      feature_id, feature_uuid, kind, place_kind, facility_info,
                      reviews_link, payload
                    ) SELECT feature_id, feature_uuid, kind, 'attraction',
                             '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
                      FROM feature.features WHERE feature_id = :feature_id
                    """
                ),
                {"feature_id": feature_id},
            )
        manual_uuid = UUID(
            str(
                await connection.scalar(
                    text(
                        "SELECT feature_uuid FROM feature.features WHERE feature_id = :feature_id"
                    ),
                    {"feature_id": manual_feature_id},
                )
            )
        )
        provider_uuid = UUID(
            str(
                await connection.scalar(
                    text(
                        "SELECT feature_uuid FROM feature.features WHERE feature_id = :feature_id"
                    ),
                    {"feature_id": provider_feature_id},
                )
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.manual_feature_identity_claims (
                  feature_id, feature_kind, name_key, lon_e6, lat_e6,
                  claimed_by_command_id, claim_basis, claimed_at
                ) VALUES (
                  :feature_uuid, 'place', 'm05 수동 후보', 127111111, 37511111,
                  :command_id, 'manual_create', clock_timestamp()
                )
                """
            ),
            {"feature_uuid": manual_uuid, "command_id": manual_command_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO feature.feature_creation_origins (
                  feature_id, origin_kind, creation_command_id, creator_principal_id,
                  created_by_actor, created_at, invoker_role, procedure_definer
                ) VALUES (
                  :feature_uuid, 'manual_admin', :command_id,
                  'admin-ui-bff.manual-feature-create.v1', :actor, clock_timestamp(),
                  'ktm_feature_api_runtime', 'ktm_manual_feature_procedure_owner'
                )
                """
            ),
            {
                "feature_uuid": manual_uuid,
                "command_id": manual_command_id,
                "actor": actor,
            },
        )
        dataset_id = int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                      provider, dataset_key, display_name, source_kind, is_active,
                      capabilities
                    ) VALUES (
                      :provider, :dataset_key, 'M05 integration', 'system', true,
                      jsonb_build_object(
                        'schema_version', 1, 'produces', '[]'::jsonb,
                        'extensions', '{}'::jsonb
                      )
                    ) RETURNING provider_dataset_id
                    """
                ),
                {
                    "provider": f"python-m05-{suffix[:8]}",
                    "dataset_key": f"m05-{suffix[:8]}",
                },
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.source_entities (
                  source_entity_key, provider_dataset_id, source_entity_type,
                  source_entity_id, first_seen_at, last_seen_at
                ) VALUES (
                  :key, :dataset_id, 'place', :entity_id,
                  clock_timestamp(), clock_timestamp()
                )
                """
            ),
            {
                "key": source_entity_key,
                "dataset_id": dataset_id,
                "entity_id": f"m05-{suffix[:8]}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.source_records (
                  source_record_key, source_entity_key, raw_payload_hash, raw_data,
                  fetched_at, imported_at
                ) VALUES (:record_key, :entity_key, repeat('b', 64), '{}'::jsonb,
                          clock_timestamp(), clock_timestamp())
                """
            ),
            {"record_key": source_record_key, "entity_key": source_entity_key},
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.source_entity_heads (
                  source_entity_key, current_source_record_key, observed_at, lineage_key
                ) VALUES (:entity_key, :record_key, clock_timestamp(), :lineage_key)
                """
            ),
            {
                "entity_key": source_entity_key,
                "record_key": source_record_key,
                "lineage_key": f"m05-{suffix[:8]}",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO provider_sync.source_links (
                  feature_id, source_entity_key, source_role, match_method, confidence
                ) VALUES (:feature_id, :entity_key, 'primary', 'm05-integration', 100)
                """
            ),
            {"feature_id": provider_feature_id, "entity_key": source_entity_key},
        )
    return {
        "actor": actor,
        "manual_feature_id": manual_feature_id,
        "manual_uuid": manual_uuid,
        "provider_feature_id": provider_feature_id,
        "provider_uuid": provider_uuid,
        "source_entity_key": source_entity_key,
    }


async def _record_candidate(
    engine: AsyncEngine, *, manual_feature_id: str, provider_feature_id: str
) -> dict[str, object]:
    async with engine.begin() as connection:
        await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        return dict(
            (
                await connection.execute(
                    text(
                        """
                        CALL feature.record_manual_provider_dedup_candidate(
                          CAST(:manual_feature_id AS text), CAST(:provider_feature_id AS text),
                          CAST(:scores AS jsonb), CAST(:causation AS jsonb),
                          NULL::uuid, NULL::text
                        )
                        """
                    ),
                    {
                        "manual_feature_id": manual_feature_id,
                        "provider_feature_id": provider_feature_id,
                        "scores": json.dumps(_SCORES),
                        "causation": json.dumps(_CAUSATION),
                    },
                )
            )
            .mappings()
            .one()
        )


async def _lease_event(
    engine: AsyncEngine, *, principal_id: str, worker_id: UUID
) -> dict[str, object]:
    async with engine.begin() as connection:
        await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        return dict(
            (
                await connection.execute(
                    text(
                        """
                        CALL feature.lease_feature_reference_reconciliation_event(
                          CAST(:principal_id AS text), CAST(:worker_id AS uuid),
                          NULL::text, NULL::bigint, NULL::timestamptz, NULL::uuid,
                          NULL::bigint, NULL::uuid, NULL::uuid, NULL::text, NULL::jsonb,
                          NULL::text, NULL::timestamptz
                        )
                        """
                    ),
                    {"principal_id": principal_id, "worker_id": worker_id},
                )
            )
            .mappings()
            .one()
        )


async def _ack_event(
    engine: AsyncEngine,
    *,
    principal_id: str,
    event_id: UUID,
    worker_id: UUID,
    lease_epoch: int,
    event_sha256: str,
    local_receipt_sha256: str,
    command_id: int,
) -> dict[str, object]:
    async with engine.begin() as connection:
        await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        return dict(
            (
                await connection.execute(
                    text(
                        """
                        CALL feature.ack_feature_reference_reconciliation_event(
                          CAST(:principal_id AS text), CAST(:event_id AS uuid),
                          CAST(:worker_id AS uuid), CAST(:lease_epoch AS bigint),
                          CAST(:event_sha256 AS text), CAST(:local_receipt_sha256 AS text),
                          CAST(:command_id AS bigint), NULL::text, NULL::bigint
                        )
                        """
                    ),
                    {
                        "principal_id": principal_id,
                        "event_id": event_id,
                        "worker_id": worker_id,
                        "lease_epoch": lease_epoch,
                        "event_sha256": event_sha256,
                        "local_receipt_sha256": local_receipt_sha256,
                        "command_id": command_id,
                    },
                )
            )
            .mappings()
            .one()
        )


async def _preflight_ack(
    engine: AsyncEngine,
    *,
    principal_id: str,
    event_id: UUID,
    event_sha256: str,
    local_receipt_sha256: str,
) -> dict[str, object]:
    async with engine.begin() as connection:
        await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
        return dict(
            (
                await connection.execute(
                    text(
                        """
                        SELECT * FROM feature.preflight_feature_reference_reconciliation_ack(
                          CAST(:principal_id AS text), CAST(:event_id AS uuid),
                          CAST(:event_sha256 AS text), CAST(:local_receipt_sha256 AS text)
                        )
                        """
                    ),
                    {
                        "principal_id": principal_id,
                        "event_id": str(event_id),
                        "event_sha256": event_sha256,
                        "local_receipt_sha256": local_receipt_sha256,
                    },
                )
            )
            .mappings()
            .one()
        )


async def test_manual_provider_candidate_is_executor_only_and_merge_is_append_only(
    migrated_engine: AsyncEngine,
) -> None:
    pair = await _seed_manual_provider_pair(migrated_engine)
    api = _runtime_engine(migrated_engine, login="ktm_feature_api_runtime")
    dagster = _runtime_engine(migrated_engine, login="ktm_feature_dagster_runtime")
    try:
        async with api.connect() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            with pytest.raises(DBAPIError) as denied:
                await connection.execute(
                    text(
                        "CALL feature.record_manual_provider_dedup_candidate("
                        "CAST(:manual_feature_id AS text), CAST(:provider_feature_id AS text), "
                        "CAST(:scores AS jsonb), CAST(:causation AS jsonb), "
                        "NULL::uuid, NULL::text)"
                    ),
                    {
                        "manual_feature_id": pair["manual_feature_id"],
                        "provider_feature_id": pair["provider_feature_id"],
                        "scores": json.dumps(_SCORES),
                        "causation": json.dumps(_CAUSATION),
                    },
                )
            await connection.rollback()
        assert getattr(denied.value.orig, "sqlstate", None) == "42501"

        async with migrated_engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT has_table_privilege("
                        "'ktm_manual_provider_dedup_procedure_owner', "
                        "'feature.feature_creation_origins', 'SELECT')"
                    )
                )
                is True
            )
            assert (
                await connection.scalar(
                    text(
                        "SELECT pg_get_userbyid(proowner) FROM pg_catalog.pg_proc "
                        "WHERE oid = "
                        "'feature.record_manual_provider_dedup_candidate("
                        "text,text,jsonb,jsonb)'::regprocedure"
                    )
                )
                == "ktm_manual_provider_dedup_procedure_owner"
            )

        first = await _record_candidate(
            dagster,
            manual_feature_id=str(pair["manual_feature_id"]),
            provider_feature_id=str(pair["provider_feature_id"]),
        )
        assert first["o_outcome"] == "created"
        case_id = UUID(str(first["o_case_id"]))
        second = await _record_candidate(
            dagster,
            manual_feature_id=str(pair["manual_feature_id"]),
            provider_feature_id=str(pair["provider_feature_id"]),
        )
        assert second == {"o_case_id": case_id, "o_outcome": "idempotent"}

        async with migrated_engine.begin() as connection:
            case = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT evidence_fingerprint, manual_feature_row_revision,
                               provider_feature_row_revision
                        FROM ops.manual_provider_dedup_cases WHERE case_id = :case_id
                        """
                        ),
                        {"case_id": case_id},
                    )
                )
                .mappings()
                .one()
            )
        decision_command = await _open_command(
            migrated_engine,
            actor=str(pair["actor"]),
            operation="admin.manual-provider-dedup-case.resolve.v1",
        )
        async with api.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED"))
            resolved = dict(
                (
                    await connection.execute(
                        text(
                            """
                            CALL feature.resolve_manual_provider_dedup_case(
                              CAST(:case_id AS uuid), 'merged', CAST(:fingerprint AS text),
                              CAST(:manual_revision AS bigint), CAST(:provider_revision AS bigint),
                              CAST(:survivor_feature_id AS text), 'same location confirmed',
                              CAST(:actor AS text), CAST(:command_id AS bigint),
                              NULL::text, NULL::uuid, NULL::uuid, NULL::text, NULL::bigint
                            )
                            """
                        ),
                        {
                            "case_id": case_id,
                            "fingerprint": case["evidence_fingerprint"],
                            "manual_revision": case["manual_feature_row_revision"],
                            "provider_revision": case["provider_feature_row_revision"],
                            "survivor_feature_id": pair["provider_feature_id"],
                            "actor": pair["actor"],
                            "command_id": decision_command,
                        },
                    )
                )
                .mappings()
                .one()
            )
        assert resolved["o_outcome"] == "merged"
        assert resolved["o_manual_feature_id"] == pair["manual_feature_id"]
        assert resolved["o_manual_feature_row_revision"] == 2
        assert resolved["o_event_id"] is not None

        async with migrated_engine.connect() as connection:
            evidence = (
                (
                    await connection.execute(
                        text(
                            """
                               SELECT resolution.decision, event.action, event.event_sequence,
                                   event.occurred_at,
                               event.old_feature_uuid,
                               event.replacement_feature_uuid, event.event_payload,
                               event.event_sha256,
                               encode(x_extension.digest(
                                 convert_to(event.event_payload::text, 'UTF8'), 'sha256'
                               ), 'hex') AS recomputed_event_sha256,
                               manual.lifecycle_state AS manual_lifecycle_state,
                               provider.lifecycle_state AS provider_lifecycle_state,
                               (SELECT count(*) FROM provider_sync.source_links
                                WHERE feature_id = :manual_feature_id) AS manual_source_links,
                               (SELECT count(*) FROM provider_sync.source_links
                                WHERE feature_id = :provider_feature_id) AS provider_source_links
                        FROM ops.manual_provider_dedup_resolutions AS resolution
                        JOIN ops.feature_reference_reconciliation_events AS event
                          ON event.resolution_id = resolution.resolution_id
                        JOIN feature.features AS manual
                          ON manual.feature_id = :manual_feature_id
                        JOIN feature.features AS provider
                          ON provider.feature_id = :provider_feature_id
                        WHERE resolution.case_id = :case_id
                        """
                        ),
                        {
                            "case_id": case_id,
                            "manual_feature_id": pair["manual_feature_id"],
                            "provider_feature_id": pair["provider_feature_id"],
                        },
                    )
                )
                .mappings()
                .one()
            )
        assert evidence["decision"] == "merged"
        assert evidence["action"] == "rebind"
        event_sequence = int(evidence["event_sequence"])
        assert evidence["event_payload"]["event_sequence"] == event_sequence
        assert evidence["event_payload"]["occurred_at"] == evidence[
            "occurred_at"
        ].isoformat(timespec="microseconds").replace("+00:00", "Z")
        assert evidence["old_feature_uuid"] == pair["manual_uuid"]
        assert evidence["replacement_feature_uuid"] == pair["provider_uuid"]
        assert evidence["event_payload"]["action"] == "rebind"
        assert len(evidence["event_sha256"]) == 64
        assert evidence["event_sha256"] == evidence["recomputed_event_sha256"]
        assert evidence["manual_lifecycle_state"] == "retired"
        assert evidence["provider_lifecycle_state"] == "active"
        assert evidence["manual_source_links"] == 0
        assert evidence["provider_source_links"] == 1

        principal_id = f"service:m05-{uuid4().hex}"
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_reference_reconciliation_subscriptions (
                      principal_id, initial_event_sequence, read_scope, ack_scope
                    ) VALUES (
                      :principal_id, :initial_event_sequence,
                      'feature-reference-reconciliation:read',
                      'feature-reference-reconciliation:ack'
                    )
                    """
                ),
                {
                    "principal_id": principal_id,
                    "initial_event_sequence": event_sequence - 1,
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_reference_reconciliation_leases (
                      principal_id, acked_through_sequence, worker_id, lease_epoch,
                      lease_expires_at
                    ) VALUES (:principal_id, :initial_event_sequence, NULL, 0, NULL)
                    """
                ),
                {
                    "principal_id": principal_id,
                    "initial_event_sequence": event_sequence - 1,
                },
            )
        async with migrated_engine.begin() as connection:
            invalid_lease_principal = f"{principal_id}:invalid"
            await connection.execute(
                text(
                    """
                    INSERT INTO ops.feature_reference_reconciliation_subscriptions (
                      principal_id, initial_event_sequence, read_scope, ack_scope
                    ) VALUES (
                      :principal_id, :initial_event_sequence,
                      'feature-reference-reconciliation:read',
                      'feature-reference-reconciliation:ack'
                    )
                    """
                ),
                {
                    "principal_id": invalid_lease_principal,
                    "initial_event_sequence": event_sequence,
                },
            )
        async with migrated_engine.connect() as connection:
            with pytest.raises(
                DBAPIError, match="precedes its subscription cursor"
            ) as invalid_lease:
                await connection.execute(
                    text(
                        """
                        INSERT INTO ops.feature_reference_reconciliation_leases (
                          principal_id, acked_through_sequence, worker_id, lease_epoch,
                          lease_expires_at
                        ) VALUES (:principal_id, 0, NULL, 0, NULL)
                        """
                    ),
                    {"principal_id": invalid_lease_principal},
                )
            assert getattr(invalid_lease.value.orig, "sqlstate", None) == "23514"
            await connection.rollback()
        worker_id = uuid4()
        leased = await _lease_event(api, principal_id=principal_id, worker_id=worker_id)
        assert leased["o_outcome"] == "leased"
        assert leased["o_event_id"] == resolved["o_event_id"]
        assert leased["o_event_sequence"] == event_sequence
        assert leased["o_action"] == "rebind"
        assert leased["o_event_sha256"] == evidence["event_sha256"]
        assert leased["o_event_payload"] == evidence["event_payload"]
        competing = await _lease_event(api, principal_id=principal_id, worker_id=uuid4())
        assert competing["o_outcome"] == "lease_conflict"
        assert competing["o_lease_epoch"] == leased["o_lease_epoch"]

        ack_command_id = await _open_command(
            migrated_engine,
            actor=principal_id,
            operation="service.feature-reference-reconciliation.ack.v1",
        )
        local_receipt_sha256 = "c" * 64
        acked = await _ack_event(
            api,
            principal_id=principal_id,
            event_id=UUID(str(leased["o_event_id"])),
            worker_id=worker_id,
            lease_epoch=int(leased["o_lease_epoch"]),
            event_sha256=str(leased["o_event_sha256"]),
            local_receipt_sha256=local_receipt_sha256,
            command_id=ack_command_id,
        )
        assert acked == {
            "o_outcome": "acked",
            "o_acked_through_sequence": event_sequence,
        }
        empty = await _lease_event(api, principal_id=principal_id, worker_id=worker_id)
        assert empty["o_outcome"] == "empty"
        assert empty["o_lease_epoch"] == leased["o_lease_epoch"]

        async with migrated_engine.begin() as connection:
            await connection.execute(text(_restore_lease_rebuild_sql()))
        async with migrated_engine.connect() as connection:
            rebuilt_lease = (
                (
                    await connection.execute(
                        text(
                            """
                        SELECT acked_through_sequence, worker_id, lease_epoch,
                               lease_expires_at
                        FROM ops.feature_reference_reconciliation_leases
                        WHERE principal_id = :principal_id
                        """
                        ),
                        {"principal_id": principal_id},
                    )
                )
                .mappings()
                .one()
            )
        assert rebuilt_lease == {
            "acked_through_sequence": event_sequence,
            "worker_id": None,
            "lease_epoch": int(leased["o_lease_epoch"]) + 1,
            "lease_expires_at": None,
        }
        async with migrated_engine.begin() as connection:
            await connection.execute(text(_restore_lease_rebuild_sql()))
        async with migrated_engine.connect() as connection:
            assert (
                await connection.scalar(
                    text(
                        "SELECT lease_epoch FROM ops.feature_reference_reconciliation_leases "
                        "WHERE principal_id = :principal_id"
                    ),
                    {"principal_id": principal_id},
                )
                == rebuilt_lease["lease_epoch"]
            )

        replayed = await _ack_event(
            api,
            principal_id=principal_id,
            event_id=UUID(str(leased["o_event_id"])),
            worker_id=worker_id,
            lease_epoch=int(leased["o_lease_epoch"]),
            event_sha256=str(leased["o_event_sha256"]),
            local_receipt_sha256=local_receipt_sha256,
            command_id=ack_command_id,
        )
        assert replayed == {
            "o_outcome": "replayed",
            "o_acked_through_sequence": event_sequence,
        }
        preflight_replayed = await _preflight_ack(
            api,
            principal_id=principal_id,
            event_id=UUID(str(leased["o_event_id"])),
            event_sha256=str(leased["o_event_sha256"]),
            local_receipt_sha256=local_receipt_sha256,
        )
        assert preflight_replayed == {
            "o_outcome": "replayed",
            "o_acked_through_sequence": event_sequence,
        }
        preflight_conflict = await _preflight_ack(
            api,
            principal_id=principal_id,
            event_id=UUID(str(leased["o_event_id"])),
            event_sha256=str(leased["o_event_sha256"]),
            local_receipt_sha256="e" * 64,
        )
        assert preflight_conflict == {
            "o_outcome": "conflict",
            "o_acked_through_sequence": event_sequence,
        }
    finally:
        await api.dispose()
        await dagster.dispose()

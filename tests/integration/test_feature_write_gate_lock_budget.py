"""큰 dataset의 root 완결이 공유 lock table을 고갈시키지 않는다(ADR-111).

2026-10-12 n150 공용 PostgreSQL(``max_locks_per_transaction=64``)에서
``feature.finalize_provider_curation_root``가 dataset 하나(11,820 Feature)를 완결하려고
Feature마다 advisory lock을 잡다가 SQLSTATE 53200(``out of shared memory``)으로 죽었다.

이 검사는 그 조건을 **설정에서 유도해** 재현한다. 공유 lock table의 칸 수는
``max_locks_per_transaction × (max_connections + max_prepared_transactions + 보조 프로세스)``
이고, 그 두 배의 Feature를 한 dataset에 링크한 뒤 root를 완결한다. 406 전에는 53200으로
빨갛고, 뒤에는 gate 하나로 초록이다. 숫자를 박지 않는 이유는 CI 컨테이너 설정이 바뀌면
박은 숫자가 조용히 표 안에 들어와 검사가 항진명제가 되기 때문이다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import make_async_engine

pytestmark = pytest.mark.integration

_RUNTIME_PASSWORD = "tvn34-test-only-service-password"

_LOCK_TABLE_SLOTS_SQL = """
SELECT current_setting('max_locks_per_transaction')::bigint * (
  current_setting('max_connections')::bigint
  + current_setting('max_prepared_transactions')::bigint
  + current_setting('max_worker_processes')::bigint
  + current_setting('autovacuum_max_workers')::bigint
  + current_setting('max_wal_senders')::bigint
  + 1
)
"""


def _runtime_engine(engine: AsyncEngine, *, login: str) -> AsyncEngine:
    dsn = engine.url.set(username=login, password=_RUNTIME_PASSWORD).render_as_string(
        hide_password=False
    )
    return make_async_engine(dsn, pool_size=1)


async def test_root_finalize_over_a_dataset_larger_than_the_lock_table(
    migrated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    async with migrated_engine.connect() as connection:
        slots = int(await connection.scalar(text(_LOCK_TABLE_SLOTS_SQL)))
    feature_count = 2 * slots
    # 2026-10-12 prod 실패가 11,820건이었다 — 기본 설정에서는 그보다 크게 잡힌다.
    assert feature_count > 10_000, f"lock table slots={slots}"

    async with migrated_engine.begin() as connection:
        dataset_id = int(
            await connection.scalar(
                text(
                    """
                    INSERT INTO provider_sync.provider_datasets (
                      provider, dataset_key, display_name, source_kind,
                      is_active, capabilities
                    ) VALUES (
                      'adr111-lock-budget', :dataset_key, 'ADR-111 lock budget',
                      'system', true,
                      jsonb_build_object(
                        'schema_version', 1,
                        'produces', '[]'::jsonb,
                        'extensions', '{}'::jsonb
                      )
                    ) RETURNING provider_dataset_id
                    """
                ),
                {"dataset_key": f"lock-budget-{suffix}"},
            )
        )
        params = {"dataset_id": dataset_id, "suffix": suffix, "n": feature_count}
        for statement in (
            """
            CREATE TEMPORARY TABLE adr111_seed ON COMMIT DROP AS
            SELECT x_extension.gen_random_uuid() AS feature_id,
                   'adr111:' || :suffix || ':' || i AS entity_key,
                   'adr111-record:' || :suffix || ':' || i AS record_key,
                   i
            FROM generate_series(1, :n) AS i
            """,
            """
            INSERT INTO provider_sync.source_entities (
              source_entity_key, provider_dataset_id, source_entity_type,
              source_entity_id, first_seen_at, last_seen_at
            )
            SELECT entity_key, :dataset_id, 'lock-budget', :suffix || ':' || i,
                   clock_timestamp(), clock_timestamp()
            FROM adr111_seed
            """,
            """
            INSERT INTO provider_sync.source_records (
              source_record_key, source_entity_key, raw_data,
              raw_payload_hash, fetched_at
            )
            SELECT record_key, entity_key, '{}'::jsonb, repeat('a', 64), clock_timestamp()
            FROM adr111_seed
            """,
            """
            INSERT INTO provider_sync.source_entity_heads (
              source_entity_key, current_source_record_key, observed_at, lineage_key
            )
            SELECT entity_key, record_key, clock_timestamp(), :suffix || ':' || i
            FROM adr111_seed
            """,
            """
            INSERT INTO feature.features (
              feature_id, kind, name, category, coord, address,
              marker_icon, marker_color
            )
            SELECT feature_id, 'place', 'lock budget ' || i, '01070100',
                   x_extension.ST_SetSRID(
                     x_extension.ST_MakePoint(126.0 + (i % 1000) * 0.0001, 34.0), 4326
                   ),
                   '{}'::jsonb, 'place', 'P-01'
            FROM adr111_seed
            """,
            """
            INSERT INTO feature.feature_places (
              feature_id, kind, place_kind, facility_info, reviews_link, payload
            )
            SELECT feature_id, 'place', 'attraction', '{}'::jsonb, '{}'::jsonb, '{}'::jsonb
            FROM adr111_seed
            """,
            """
            INSERT INTO provider_sync.source_links (
              feature_id, source_entity_key, source_role, match_method, confidence
            )
            SELECT feature_id, entity_key, 'primary', 'exact', 100
            FROM adr111_seed
            """,
            """
            INSERT INTO provider_sync.provider_dataset_operations (
              provider_dataset_id, operation_key, operation_kind, is_enabled, config
            ) VALUES (:dataset_id, 'load', 'refresh', true, '{}'::jsonb)
            """,
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes (
              provider_dataset_id, sync_scope, operation_key, operation_kind
            ) VALUES (:dataset_id, 'dataset_wide', 'load', 'refresh')
            """,
        ):
            await connection.execute(text(statement), params)
        root_job_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      kind, payload, status, progress, current_stage,
                      dagster_run_id, dataset_membership_mode, trigger_kind,
                      operation_key, dagster_run_status, created_at
                    ) VALUES (
                      'provider_feature_load_run', '{}'::jsonb, 'done', 100,
                      'completed', :run_id, 'root', 'schedule', 'load', 'SUCCESS',
                      clock_timestamp() - interval '2 hours'
                    ) RETURNING job_id
                    """
                ),
                {"run_id": f"adr111-{suffix}"},
            )
        )
        source_job_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO ops.import_jobs (
                      kind, parent_job_id, payload, status, progress,
                      current_stage, dagster_run_id, dataset_membership_mode,
                      finished_at, created_at
                    ) VALUES (
                      'provider_feature_load', CAST(:root_job_id AS uuid),
                      jsonb_build_object(
                        'authoritative_snapshot_complete', true,
                        'source_observation', jsonb_build_object(
                          'schema_version', 1,
                          'row_count', CAST(:n AS integer),
                          'last_source_modified_at', current_date::text,
                          'input_set_hash', repeat('e', 64)
                        )
                      ),
                      'done', 100, 'completed', :run_id, 'single', clock_timestamp(),
                      (SELECT created_at FROM ops.import_jobs
                       WHERE job_id = CAST(:root_job_id AS uuid))
                    ) RETURNING job_id
                    """
                ),
                {"root_job_id": root_job_id, "run_id": f"adr111-{suffix}", "n": feature_count},
            )
        )
        await connection.execute(
            text(
                """
                INSERT INTO ops.import_job_datasets (
                  job_id, provider_dataset_id, sync_scope, operation_key
                ) VALUES (CAST(:job_id AS uuid), :dataset_id, 'dataset_wide', 'load')
                """
            ),
            {"dataset_id": dataset_id, "job_id": source_job_id},
        )

    async with migrated_engine.begin() as connection:
        await connection.execute(text("SET ROLE ktm_curation_command_owner"))
        await connection.execute(
            text(
                """
                INSERT INTO ops.curation_provider_snapshot_receipts (
                  source_job_id, root_job_id, provider_dataset_id,
                  sync_scope, operation_key, observed_at,
                  source_entity_count, input_member_count,
                  last_source_modified_at, source_input_set_hash
                )
                SELECT CAST(:job_id AS uuid), CAST(:root_job_id AS uuid),
                       :dataset_id, 'dataset_wide', 'load', job.finished_at,
                       input.source_entity_count, input.input_member_count,
                       input.last_source_modified_at, input.source_input_set_hash
                FROM ops.import_jobs AS job
                CROSS JOIN LATERAL feature.current_provider_curation_input_set(
                  :dataset_id
                ) AS input
                WHERE job.job_id = CAST(:job_id AS uuid)
                """
            ),
            {"dataset_id": dataset_id, "job_id": source_job_id, "root_job_id": root_job_id},
        )
        await connection.execute(text("RESET ROLE"))

    dagster = _runtime_engine(migrated_engine, login="ktm_feature_service")
    try:
        async with dagster.begin() as connection:
            await connection.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            finalized = (
                await connection.execute(
                    text(
                        """
                        CALL feature.finalize_provider_curation_root(
                          CAST(:root_job_id AS uuid), NULL, NULL, NULL, NULL
                        )
                        """
                    ),
                    {"root_job_id": root_job_id},
                )
            ).mappings().one()
            # 효과: 이 트랜잭션이 든 advisory lock 수가 dataset 크기를 따라 자라지 않는다.
            held = int(
                await connection.scalar(
                    text(
                        """
                        SELECT count(*) FROM pg_catalog.pg_locks
                        WHERE locktype = 'advisory' AND pid = pg_backend_pid()
                        """
                    )
                )
            )
        assert finalized["o_replayed"] is False
        assert finalized["o_stale_input"] is False
        assert held < 16, f"advisory locks held by one root finalize: {held}"
    finally:
        await dagster.dispose()

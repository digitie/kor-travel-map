"""큰 dataset의 root 완결이 공유 lock table을 고갈시키지 않는다(ADR-111).

2026-10-12 n150 공용 PostgreSQL(``max_locks_per_transaction=64``)에서
``feature.finalize_provider_curation_root``가 dataset 하나(11,820 Feature)를 완결하려고
Feature마다 advisory lock을 잡다가 SQLSTATE 53200(``out of shared memory``)으로 죽었다.

이 검사는 그 조건을 **설정에서 유도해** 재현한다. 공유 lock table의 칸 수는
``max_locks_per_transaction × (max_connections + max_prepared_transactions + 보조 프로세스)``
이고, 그 두 배의 Feature를 한 dataset에 링크하고 active rule 하나를 걸어 root를 완결한다
(중첩 ``materialize_theme_candidate_generation``도 같은 규모로 돈다). 406 전에는 53200으로
빨갛고, 뒤에는 gate 하나로 초록이다. 숫자를 박지 않는 이유는 CI 컨테이너 설정이 바뀌면
박은 숫자가 조용히 표 안에 들어와 검사가 항진명제가 되기 때문이다.

**격리.** 이 모듈은 세션 공유 DB(``migrated_engine``)를 쓰지 않는다. 1.5만 Feature와 active
dataset·done import job은 뒤따르는 검사(MOIS loader 등)의 세계를 바꾼다(2026-10-13 glibc lane
2건). 같은 컨테이너 안에 이 모듈만의 DB를 만들어 head까지 올리고 끝나면 지운다.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.feature_operation_repo import abandon_dagster_feature_run
from tests.integration._application_300_bootstrap import (
    _TEST_MIGRATOR_PASSWORD,
    upgrade_head_with_application_300_bootstrap,
)

pytestmark = pytest.mark.integration

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


@pytest.fixture(scope="module")
async def isolated_engine(pg_container: Any) -> AsyncIterator[AsyncEngine]:
    """이 모듈만의 head DB. 세션 공유 DB에 아무것도 남기지 않는다."""
    from alembic.config import Config

    from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

    raw_dsn = pg_container.get_connection_url()
    database = f"adr111_lock_budget_{uuid4().hex}"
    server_dsn = (
        make_url(raw_dsn).set(drivername="postgresql", database="postgres").render_as_string(False)
    )
    with psycopg.connect(server_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(database))
        )
    admin_dsn = normalize_async_dsn(
        make_url(raw_dsn).set(database=database).render_as_string(False)
    )
    root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    engine: AsyncEngine | None = None
    try:
        await upgrade_head_with_application_300_bootstrap(config, admin_dsn)
        migrator_dsn = (
            make_url(admin_dsn)
            .set(username="ktm_feature_service", password=_TEST_MIGRATOR_PASSWORD)
            .render_as_string(hide_password=False)
        )
        previous = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
        os.environ["KOR_TRAVEL_MAP_PG_DSN"] = migrator_dsn
        try:
            await reconcile_runtime_privileges()
        finally:
            if previous is None:
                os.environ.pop("KOR_TRAVEL_MAP_PG_DSN", None)
            else:
                os.environ["KOR_TRAVEL_MAP_PG_DSN"] = previous
        engine = make_async_engine(admin_dsn)
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        with psycopg.connect(server_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database))
            )


def _runtime_engine(engine: AsyncEngine) -> AsyncEngine:
    dsn = engine.url.set(
        username="ktm_feature_service", password=_TEST_MIGRATOR_PASSWORD
    ).render_as_string(hide_password=False)
    return make_async_engine(dsn, pool_size=1)


async def _seed_dataset(connection: Any, *, suffix: str, feature_count: int) -> int:
    dataset_id = int(
        await connection.scalar(
            text(
                """
                INSERT INTO provider_sync.provider_datasets (
                  provider, dataset_key, display_name, source_kind, is_active, capabilities
                ) VALUES (
                  'adr111-lock-budget', :dataset_key, 'ADR-111 lock budget', 'system', true,
                  jsonb_build_object(
                    'schema_version', 1, 'produces', '[]'::jsonb, 'extensions', '{}'::jsonb
                  )
                ) RETURNING provider_dataset_id
                """
            ),
            {"dataset_key": f"lock-budget-{suffix}"},
        )
    )
    params = {"dataset_id": dataset_id, "suffix": suffix, "n": feature_count}
    statements = [
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
    ]
    if feature_count:
        statements = [
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
              source_record_key, source_entity_key, raw_data, raw_payload_hash, fetched_at
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
              feature_id, kind, name, category, coord, address, marker_icon, marker_color
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
            *statements,
        ]
    for statement in statements:
        await connection.execute(text(statement), params)
    return dataset_id


async def _seed_root(
    connection: Any, *, dataset_id: int, run_id: str, root_status: str, rows: int
) -> tuple[str, str]:
    root_job_id = str(
        await connection.scalar(
            text(
                """
                INSERT INTO ops.import_jobs (
                  kind, payload, status, progress, current_stage, dagster_run_id,
                  dataset_membership_mode, trigger_kind, operation_key, dagster_run_status,
                  created_at, started_at
                ) VALUES (
                  'provider_feature_load_run', '{}'::jsonb, :status,
                  CASE WHEN :status = 'done' THEN 100 ELSE 0 END,
                  CASE WHEN :status = 'done' THEN 'completed' ELSE 'running' END,
                  :run_id, 'root', 'schedule', 'load',
                  CASE WHEN :status = 'done' THEN 'SUCCESS' ELSE 'STARTED' END,
                  now() - interval '2 hours', now() - interval '2 hours'
                ) RETURNING job_id
                """
            ),
            {"run_id": run_id, "status": root_status},
        )
    )
    source_job_id = str(
        await connection.scalar(
            text(
                """
                INSERT INTO ops.import_jobs (
                  kind, parent_job_id, payload, status, progress, current_stage,
                  dagster_run_id, dataset_membership_mode, started_at, finished_at, created_at
                ) VALUES (
                  'provider_feature_load', CAST(:root_job_id AS uuid),
                  jsonb_build_object(
                    'authoritative_snapshot_complete', true,
                    'source_observation', jsonb_build_object(
                      'schema_version', 1,
                      'row_count', CAST(:rows AS integer),
                      'last_source_modified_at', current_date::text,
                      'input_set_hash', repeat('e', 64)
                    )
                  ),
                  'done', 100, 'completed', :run_id, 'single',
                  clock_timestamp() - interval '1 hour', clock_timestamp(),
                  (SELECT created_at FROM ops.import_jobs WHERE job_id = CAST(:root_job_id AS uuid))
                ) RETURNING job_id
                """
            ),
            {"root_job_id": root_job_id, "run_id": run_id, "rows": rows},
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
    return root_job_id, source_job_id


async def test_root_finalize_over_a_dataset_larger_than_the_lock_table(
    isolated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    async with isolated_engine.connect() as connection:
        slots = int(await connection.scalar(text(_LOCK_TABLE_SLOTS_SQL)))
    feature_count = 2 * slots
    # 2026-10-12 prod 실패가 11,820건이었다 — 기본 설정에서는 그보다 크게 잡힌다.
    assert feature_count > 10_000, f"lock table slots={slots}"

    async with isolated_engine.begin() as connection:
        dataset_id = await _seed_dataset(connection, suffix=suffix, feature_count=feature_count)
        theme_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_themes (
                      theme_slug, theme_name, theme_group, visibility, owner_kind
                    ) VALUES (:slug, 'Lock budget', 'test', 'admin_only', 'operator')
                    RETURNING theme_id
                    """
                ),
                {"slug": f"lock-budget-{suffix}"},
            )
        )
        source_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_sources (
                      provider_dataset_id, source_name, source_kind, provider_status
                    ) VALUES (:dataset_id, 'Lock budget source', 'manual', 'implemented')
                    RETURNING source_id
                    """
                ),
                {"dataset_id": dataset_id},
            )
        )
        rule_id = str(
            await connection.scalar(
                text(
                    """
                    INSERT INTO feature.curated_source_rules (
                      theme_id, source_id, region_scope, default_action, priority, enabled,
                      metadata, owner_kind
                    ) VALUES (
                      CAST(:theme_id AS uuid), CAST(:source_id AS uuid), '{}'::jsonb,
                      'candidate', 0, true, '{}'::jsonb, 'operator'
                    ) RETURNING rule_id
                    """
                ),
                {"source_id": source_id, "theme_id": theme_id},
            )
        )
        root_job_id, source_job_id = await _seed_root(
            connection,
            dataset_id=dataset_id,
            run_id=f"adr111-{suffix}",
            root_status="done",
            rows=feature_count,
        )

    async with isolated_engine.begin() as connection:
        await connection.execute(text("SET LOCAL ROLE ktm_curation_command_owner"))
        await connection.execute(
            text(
                """
                INSERT INTO ops.curation_provider_snapshot_receipts (
                  source_job_id, root_job_id, provider_dataset_id, sync_scope, operation_key,
                  observed_at, source_entity_count, input_member_count,
                  last_source_modified_at, source_input_set_hash
                )
                SELECT CAST(:job_id AS uuid), CAST(:root_job_id AS uuid),
                       :dataset_id, 'dataset_wide', 'load', job.finished_at,
                       input.source_entity_count, input.input_member_count,
                       input.last_source_modified_at, input.source_input_set_hash
                FROM ops.import_jobs AS job
                CROSS JOIN LATERAL feature.current_provider_curation_input_set(:dataset_id) AS input
                WHERE job.job_id = CAST(:job_id AS uuid)
                """
            ),
            {"dataset_id": dataset_id, "job_id": source_job_id, "root_job_id": root_job_id},
        )

    dagster = _runtime_engine(isolated_engine)
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
    finally:
        await dagster.dispose()
    assert finalized["o_replayed"] is False
    assert finalized["o_stale_input"] is False
    assert int(finalized["o_generation_count"]) == 1
    assert held < 16, f"advisory locks held by one root finalize: {held}"

    async with isolated_engine.connect() as connection:
        observed = int(
            await connection.scalar(
                text(
                    """
                    SELECT generation.observed_candidate_count
                    FROM feature.theme_candidate_generations AS generation
                    WHERE generation.rule_id = CAST(:rule_id AS uuid)
                      AND generation.generation_kind = 'provider_full_snapshot'
                    """
                ),
                {"rule_id": rule_id},
            )
        )
    # 중첩 materialize가 같은 규모를 실제로 훑었다(규칙이 아무것도 안 봤다면 위 잠금 수도 공허하다).
    assert observed == feature_count


async def test_abandon_closes_the_root_once_and_leaves_done_members(
    isolated_engine: AsyncEngine,
) -> None:
    suffix = uuid4().hex
    run_id = f"adr111-abandon-{suffix}"
    async with isolated_engine.begin() as connection:
        dataset_id = await _seed_dataset(connection, suffix=suffix, feature_count=0)
        root_job_id, member_job_id = await _seed_root(
            connection, dataset_id=dataset_id, run_id=run_id, root_status="running", rows=0
        )

    finished_at = datetime.now(UTC)
    runtime = _runtime_engine(isolated_engine)
    try:
        async with AsyncSession(runtime) as session, session.begin():
            closed = await abandon_dagster_feature_run(
                session,
                dagster_run_id=run_id,
                terminal_status="SUCCESS",
                engine_finished_at=finished_at,
                failure="SQLSTATE 23514",
                attempts=5,
            )
        async with AsyncSession(runtime) as session, session.begin():
            again = await abandon_dagster_feature_run(
                session,
                dagster_run_id=run_id,
                terminal_status="SUCCESS",
                engine_finished_at=finished_at,
                failure="SQLSTATE 23514",
                attempts=6,
            )
    finally:
        await runtime.dispose()

    assert closed.outcome == "applied"
    assert (again.outcome, again.block_reason) == ("blocked", "terminal")
    async with isolated_engine.connect() as connection:
        jobs = {
            str(row.job_id): (row.status, row.current_stage)
            for row in await connection.execute(
                text(
                    "SELECT job_id, status, current_stage FROM ops.import_jobs "
                    "WHERE job_id IN (CAST(:root AS uuid), CAST(:member AS uuid))"
                ),
                {"root": root_job_id, "member": member_job_id},
            )
        }
        logs = (
            await connection.execute(
                text(
                    """
                    SELECT detail FROM ops.system_log
                    WHERE event = 'feature_operation.reconcile_abandoned'
                      AND detail ->> 'dagster_run_id' = :run_id
                    """
                ),
                {"run_id": run_id},
            )
        ).scalars().all()
    assert jobs[root_job_id] == ("failed", "failed")
    assert jobs[member_job_id] == ("done", "completed")
    assert len(logs) == 1
    assert logs[0]["provider_dataset_ids"] == [dataset_id]
    assert logs[0]["action"] == "re-run the dataset"
    assert logs[0]["failure"] == "SQLSTATE 23514"

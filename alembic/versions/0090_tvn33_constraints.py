"""T-VN-33B — canonical dataset ownership FK/index convergence.

Revision ID: 0090_tvn33_constraints
Revises: 0089_tvn33_expand_seed

Large FK는 모두 ``NOT VALID``로 연결한 뒤 이 revision에서 검증한다. writer는
maintenance boundary에서 drain되어 있으므로, 여기서는 compatibility shadow나
dual-write를 만들지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.util.concurrency import await_only

from alembic import op

revision: str = "0090_tvn33_constraints"
down_revision: str | Sequence[str] | None = "0089_tvn33_expand_seed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_sql_script(sql: str) -> None:
    """asyncpg prepared statement가 거부하는 복수 DDL을 현재 transaction에서 실행한다."""
    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


def _preflight_or_raise(label: str, probe_sql: str, remedy: str) -> None:
    quoted_label = label.replace("'", "''")
    quoted_remedy = remedy.replace("'", "''")
    op.execute(
        f"""
        DO $preflight$
        DECLARE total bigint;
        BEGIN
            SELECT count(*) INTO total FROM ({probe_sql}) AS probe;
            IF total <> 0 THEN
                RAISE EXCEPTION 'T-VN-33B preflight: % (% row(s))',
                    '{quoted_label}', total
                    USING HINT = '{quoted_remedy}';
            END IF;
        END
        $preflight$;
        """
    )


def _preflight() -> None:
    _preflight_or_raise(
        "expanded ownership column remains NULL",
        """
        SELECT source_entity_key FROM provider_sync.source_entities
        WHERE provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(provider_dataset_id AS text) FROM provider_sync.provider_sync_state
        WHERE provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(notice_lifecycle_scope_id AS text)
        FROM provider_sync.notice_lifecycle_scopes WHERE provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(source_id AS text) FROM feature.curated_sources
        WHERE provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(upload_id AS text) FROM ops.offline_uploads
        WHERE provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(provider_dataset_id AS text) FROM ops.provider_refresh_policies
        WHERE provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(integrity_observation_scope_id AS text)
        FROM ops.integrity_observation_scopes WHERE provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(observation_run_id AS text) FROM ops.integrity_observation_runs
        WHERE integrity_observation_scope_id IS NULL
        """,
        "Repair the pair mapping, or rebuild development data with the final ETL.",
    )
    _preflight_or_raise(
        "canonical scope is missing for an operational row",
        """
        SELECT CAST(state.provider_dataset_id AS text)
        FROM provider_sync.provider_sync_state AS state
        LEFT JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = state.provider_dataset_id
         AND scope.sync_scope = state.sync_scope
        WHERE scope.provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(upload.upload_id AS text)
        FROM ops.offline_uploads AS upload
        LEFT JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = upload.provider_dataset_id
         AND scope.sync_scope = upload.sync_scope
        WHERE scope.provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(member.import_job_dataset_id AS text)
        FROM ops.import_job_datasets AS member
        LEFT JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = member.provider_dataset_id
         AND scope.sync_scope = member.sync_scope
        WHERE scope.provider_dataset_id IS NULL
        UNION ALL
        SELECT CAST(member.feature_update_request_dataset_id AS text)
        FROM ops.feature_update_request_datasets AS member
        LEFT JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = member.provider_dataset_id
         AND scope.sync_scope = member.sync_scope
        WHERE scope.provider_dataset_id IS NULL
        """,
        "Register a concrete seed operation/scope or recreate the operational row.",
    )
    _preflight_or_raise(
        "job mode does not match its canonical member count",
        """
        SELECT job.job_id
        FROM ops.import_jobs AS job
        LEFT JOIN ops.import_job_datasets AS member ON member.job_id = job.job_id
        GROUP BY job.job_id, job.dataset_membership_mode
        HAVING (job.dataset_membership_mode = 'root' AND count(member.*) <> 0)
            OR (job.dataset_membership_mode = 'single' AND count(member.*) <> 1)
            OR (job.dataset_membership_mode = 'multiple' AND count(member.*) = 0)
        """,
        "Recreate malformed legacy jobs through the canonical membership writer.",
    )
    _preflight_or_raise(
        "feature update request does not have canonical members",
        """
        SELECT request.request_id
        FROM ops.feature_update_requests AS request
        LEFT JOIN ops.feature_update_request_datasets AS member
          ON member.request_id = request.request_id
        GROUP BY request.request_id, request.dataset_membership_mode
        HAVING (request.dataset_membership_mode = 'single' AND count(member.*) <> 1)
            OR (request.dataset_membership_mode = 'multiple' AND count(member.*) = 0)
        """,
        "Recreate the request after resolving its active dataset snapshot.",
    )
    _preflight_or_raise(
        "pair-specific event is not a member of its own job",
        """
        SELECT event.event_id
        FROM ops.import_job_events AS event
        WHERE (event.provider IS NOT NULL OR event.dataset_key IS NOT NULL)
          AND event.import_job_dataset_id IS NULL
        UNION ALL
        SELECT event.event_id
        FROM ops.import_job_events AS event
        LEFT JOIN ops.import_job_datasets AS member
          ON member.job_id = event.job_id
         AND member.import_job_dataset_id = event.import_job_dataset_id
        WHERE event.import_job_dataset_id IS NOT NULL
          AND member.import_job_dataset_id IS NULL
        """,
        "Recreate the event with a member captured from the same job.",
    )
    _preflight_or_raise(
        "enrichment review cannot resolve its canonical source record",
        """
        SELECT review_id
        FROM ops.enrichment_review_queue
        WHERE source_entity_key IS NULL OR source_record_key IS NULL
        """,
        "Recreate the enrichment candidate from a canonical source entity and record.",
    )


def _constraints() -> None:
    # **재실행 안전.** 이 revision은 중간에 ``autocommit_block``으로 concurrent
    # index를 만들기 때문에, 그 뒤에서 실패하면 여기까지의 DDL이 **0089 stamp 아래
    # 커밋된 채** 남는다(`alembic/env.py`가 chain 전체를 한 트랜잭션으로 감싼다).
    # 그 상태에서 재실행하면 종전에는 `DuplicateTableError`로 죽었고, `downgrade`는
    # 설계상 예외를 던지므로 복구 경로가 없었다 — 적대 리뷰가 재현했다.
    # 그래서 붙이기 전에 같은 이름을 먼저 걷어낸다. PK는 여기서 손대지 않는다 —
    # 아래 ALTER가 같은 문장 안에서 교체하고, 선삭제하면 의존 FK가 막는다.
    _execute_sql_script(
        """
        ALTER TABLE provider_sync.source_entities
            DROP CONSTRAINT IF EXISTS fk_source_entities_provider_dataset;
        ALTER TABLE provider_sync.source_entities
            DROP CONSTRAINT IF EXISTS uq_source_entities_provider_identity;
        ALTER TABLE provider_sync.source_records
            DROP CONSTRAINT IF EXISTS uq_source_records_entity_payload;
        ALTER TABLE provider_sync.source_records
            DROP CONSTRAINT IF EXISTS ck_source_records_raw_data_object;
        ALTER TABLE provider_sync.source_records
            DROP CONSTRAINT IF EXISTS ck_source_records_payload_hash_canonical;
        ALTER TABLE provider_sync.provider_sync_state
            DROP CONSTRAINT IF EXISTS fk_provider_sync_state_scope;
        ALTER TABLE provider_sync.notice_lifecycle_scopes
            DROP CONSTRAINT IF EXISTS uq_notice_lifecycle_scopes_identity;
        ALTER TABLE provider_sync.notice_lifecycle_scopes
            DROP CONSTRAINT IF EXISTS fk_notice_lifecycle_scopes_dataset;
        ALTER TABLE provider_sync.notice_lineage_states
            DROP CONSTRAINT IF EXISTS fk_notice_lineage_states_scope;
        ALTER TABLE feature.curated_sources
            DROP CONSTRAINT IF EXISTS uq_curated_sources_dataset;
        ALTER TABLE feature.curated_sources
            DROP CONSTRAINT IF EXISTS fk_curated_sources_dataset;
        ALTER TABLE ops.import_jobs
            DROP CONSTRAINT IF EXISTS ck_import_jobs_membership_mode;
        ALTER TABLE ops.import_job_datasets
            DROP CONSTRAINT IF EXISTS fk_import_job_datasets_job;
        ALTER TABLE ops.import_job_datasets
            DROP CONSTRAINT IF EXISTS fk_import_job_datasets_scope;
        ALTER TABLE ops.import_job_events
            DROP CONSTRAINT IF EXISTS fk_import_job_events_job_member;
        ALTER TABLE ops.feature_update_requests
            DROP CONSTRAINT IF EXISTS ck_feature_update_requests_membership_mode;
        ALTER TABLE ops.feature_update_request_datasets
            DROP CONSTRAINT IF EXISTS fk_feature_update_request_datasets_request;
        ALTER TABLE ops.feature_update_request_datasets
            DROP CONSTRAINT IF EXISTS fk_feature_update_request_datasets_scope;
        ALTER TABLE ops.offline_uploads
            DROP CONSTRAINT IF EXISTS fk_offline_uploads_scope;
        ALTER TABLE ops.offline_uploads
            DROP CONSTRAINT IF EXISTS uq_offline_uploads_dataset_scope_checksum;
        ALTER TABLE ops.provider_refresh_policies
            DROP CONSTRAINT IF EXISTS fk_provider_refresh_policies_dataset;
        ALTER TABLE ops.integrity_observation_scopes
            DROP CONSTRAINT IF EXISTS uq_integrity_observation_scopes_dataset;
        ALTER TABLE ops.integrity_observation_scopes
            DROP CONSTRAINT IF EXISTS fk_integrity_observation_scopes_dataset;
        ALTER TABLE ops.integrity_observation_runs
            DROP CONSTRAINT IF EXISTS fk_integrity_observation_runs_scope;
        ALTER TABLE ops.integrity_observation_runs
            DROP CONSTRAINT IF EXISTS uq_integrity_observation_runs_generation_v2;
        ALTER TABLE ops.integrity_observation_runs
            DROP CONSTRAINT IF EXISTS uq_integrity_observation_runs_external_run_v2;
        ALTER TABLE ops.data_integrity_violations
            DROP CONSTRAINT IF EXISTS fk_data_integrity_violations_dataset;
        ALTER TABLE ops.poi_cache_target_feature_links
            DROP CONSTRAINT IF EXISTS fk_poi_cache_target_feature_links_dataset;
        ALTER TABLE ops.enrichment_review_queue
            DROP CONSTRAINT IF EXISTS uq_enrichment_review_candidate;
        ALTER TABLE ops.enrichment_review_queue
            DROP CONSTRAINT IF EXISTS fk_enrichment_review_queue_source_entity;
        ALTER TABLE ops.enrichment_review_queue
            DROP CONSTRAINT IF EXISTS fk_enrichment_review_queue_source_record;
        ALTER TABLE ops.managed_files
            DROP CONSTRAINT IF EXISTS fk_managed_files_dataset;
        ALTER TABLE ops.managed_files
            DROP CONSTRAINT IF EXISTS ck_managed_files_owner_v2;
        """
    )
    _execute_sql_script(
        """
        ALTER TABLE provider_sync.source_entities
            ADD CONSTRAINT fk_source_entities_provider_dataset
            FOREIGN KEY (provider_dataset_id)
            REFERENCES provider_sync.provider_datasets (provider_dataset_id) NOT VALID,
            ADD CONSTRAINT uq_source_entities_provider_identity
            UNIQUE (provider_dataset_id, source_entity_type, source_entity_id);
        ALTER TABLE provider_sync.source_records
            ADD CONSTRAINT uq_source_records_entity_payload
            UNIQUE (source_entity_key, raw_payload_hash),
            ADD CONSTRAINT ck_source_records_raw_data_object
            CHECK (jsonb_typeof(raw_data) = 'object') NOT VALID,
            ADD CONSTRAINT ck_source_records_payload_hash_canonical
            CHECK (raw_payload_hash ~ '^[0-9a-f]{1,64}$') NOT VALID;

        ALTER TABLE provider_sync.provider_sync_state
            ALTER COLUMN provider_dataset_id SET NOT NULL,
            DROP CONSTRAINT IF EXISTS pk_provider_sync_state,
            ADD CONSTRAINT pk_provider_sync_state PRIMARY KEY (provider_dataset_id, sync_scope),
            ADD CONSTRAINT fk_provider_sync_state_scope
            FOREIGN KEY (provider_dataset_id, sync_scope)
            REFERENCES provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope
            ) NOT VALID;

        ALTER TABLE provider_sync.notice_lineage_states
            DROP CONSTRAINT IF EXISTS fk_notice_lineage_states_scope;
        ALTER TABLE provider_sync.notice_lifecycle_scopes
            ALTER COLUMN notice_lifecycle_scope_id SET NOT NULL,
            ALTER COLUMN provider_dataset_id SET NOT NULL,
            DROP CONSTRAINT IF EXISTS pk_notice_lifecycle_scopes,
            ADD CONSTRAINT pk_notice_lifecycle_scopes
                PRIMARY KEY (notice_lifecycle_scope_id),
            ADD CONSTRAINT uq_notice_lifecycle_scopes_identity
                UNIQUE (provider_dataset_id, source_entity_type),
            ADD CONSTRAINT fk_notice_lifecycle_scopes_dataset
                FOREIGN KEY (provider_dataset_id)
                REFERENCES provider_sync.provider_datasets (provider_dataset_id) NOT VALID;
        ALTER TABLE provider_sync.notice_lineage_states
            ADD COLUMN IF NOT EXISTS notice_lifecycle_scope_id bigint;
        UPDATE provider_sync.notice_lineage_states AS lineage
        SET notice_lifecycle_scope_id = scope.notice_lifecycle_scope_id
        FROM provider_sync.notice_lifecycle_scopes AS scope
        WHERE scope.provider = lineage.provider
          AND scope.dataset_key = lineage.dataset_key
          AND scope.source_entity_type = lineage.source_entity_type;
        ALTER TABLE provider_sync.notice_lineage_states
            ALTER COLUMN notice_lifecycle_scope_id SET NOT NULL,
            DROP CONSTRAINT IF EXISTS pk_notice_lineage_states,
            ADD CONSTRAINT pk_notice_lineage_states
                PRIMARY KEY (notice_lifecycle_scope_id, lineage_key),
            ADD CONSTRAINT fk_notice_lineage_states_scope
                FOREIGN KEY (notice_lifecycle_scope_id)
                REFERENCES provider_sync.notice_lifecycle_scopes (notice_lifecycle_scope_id)
                ON DELETE CASCADE NOT VALID;

        ALTER TABLE feature.curated_sources
            ALTER COLUMN provider_dataset_id SET NOT NULL,
            DROP CONSTRAINT IF EXISTS uq_curated_sources_provider_dataset,
            ADD CONSTRAINT uq_curated_sources_dataset UNIQUE (provider_dataset_id),
            ADD CONSTRAINT fk_curated_sources_dataset FOREIGN KEY (provider_dataset_id)
                REFERENCES provider_sync.provider_datasets (provider_dataset_id) NOT VALID;

        ALTER TABLE ops.import_jobs
            ADD CONSTRAINT ck_import_jobs_membership_mode
            CHECK (dataset_membership_mode IN ('root', 'single', 'multiple')) NOT VALID;
        ALTER TABLE ops.import_job_datasets
            ADD CONSTRAINT fk_import_job_datasets_job FOREIGN KEY (job_id)
                REFERENCES ops.import_jobs (job_id) ON DELETE CASCADE NOT VALID,
            ADD CONSTRAINT fk_import_job_datasets_scope
            FOREIGN KEY (provider_dataset_id, sync_scope)
            REFERENCES provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope
            ) NOT VALID;
        ALTER TABLE ops.import_job_events
            ADD CONSTRAINT fk_import_job_events_job_member
            FOREIGN KEY (job_id, import_job_dataset_id)
            REFERENCES ops.import_job_datasets (job_id, import_job_dataset_id)
            ON DELETE RESTRICT NOT VALID;

        ALTER TABLE ops.feature_update_requests
            ADD CONSTRAINT ck_feature_update_requests_membership_mode
            CHECK (dataset_membership_mode IN ('single', 'multiple')) NOT VALID;
        ALTER TABLE ops.feature_update_request_datasets
            ADD CONSTRAINT fk_feature_update_request_datasets_request
            FOREIGN KEY (request_id)
            REFERENCES ops.feature_update_requests (request_id) ON DELETE CASCADE NOT VALID,
            ADD CONSTRAINT fk_feature_update_request_datasets_scope
            FOREIGN KEY (provider_dataset_id, sync_scope)
            REFERENCES provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope
            ) NOT VALID;

        ALTER TABLE ops.offline_uploads
            ALTER COLUMN provider_dataset_id SET NOT NULL,
            ADD CONSTRAINT fk_offline_uploads_scope
            FOREIGN KEY (provider_dataset_id, sync_scope)
            REFERENCES provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope
            ) NOT VALID,
            ADD CONSTRAINT uq_offline_uploads_dataset_scope_checksum
            UNIQUE (provider_dataset_id, sync_scope, checksum_sha256);
        ALTER TABLE ops.provider_refresh_policies
            ALTER COLUMN provider_dataset_id SET NOT NULL,
            DROP CONSTRAINT IF EXISTS pk_provider_refresh_policies,
            ADD CONSTRAINT pk_provider_refresh_policies PRIMARY KEY (provider_dataset_id),
            ADD CONSTRAINT fk_provider_refresh_policies_dataset
            FOREIGN KEY (provider_dataset_id)
            REFERENCES provider_sync.provider_datasets (provider_dataset_id) NOT VALID;

        ALTER TABLE ops.integrity_observation_runs
            DROP CONSTRAINT IF EXISTS fk_integrity_observation_runs_scope;
        ALTER TABLE ops.integrity_observation_scopes
            ALTER COLUMN integrity_observation_scope_id SET NOT NULL,
            ALTER COLUMN provider_dataset_id SET NOT NULL,
            DROP CONSTRAINT IF EXISTS pk_integrity_observation_scopes,
            ADD CONSTRAINT pk_integrity_observation_scopes
                PRIMARY KEY (integrity_observation_scope_id),
            ADD CONSTRAINT uq_integrity_observation_scopes_dataset
                UNIQUE (provider_dataset_id),
            ADD CONSTRAINT fk_integrity_observation_scopes_dataset
            FOREIGN KEY (provider_dataset_id)
            REFERENCES provider_sync.provider_datasets (provider_dataset_id) NOT VALID;
        ALTER TABLE ops.integrity_observation_runs
            ALTER COLUMN integrity_observation_scope_id SET NOT NULL,
            ADD CONSTRAINT fk_integrity_observation_runs_scope
            FOREIGN KEY (integrity_observation_scope_id)
            REFERENCES ops.integrity_observation_scopes (integrity_observation_scope_id)
            ON DELETE CASCADE NOT VALID,
            ADD CONSTRAINT uq_integrity_observation_runs_generation_v2
            UNIQUE (integrity_observation_scope_id, generation),
            ADD CONSTRAINT uq_integrity_observation_runs_external_run_v2
            UNIQUE (integrity_observation_scope_id, external_run_id);

        ALTER TABLE ops.data_integrity_violations
            ADD CONSTRAINT fk_data_integrity_violations_dataset
            FOREIGN KEY (provider_dataset_id)
            REFERENCES provider_sync.provider_datasets (provider_dataset_id) NOT VALID;
        ALTER TABLE ops.poi_cache_target_feature_links
            ADD CONSTRAINT fk_poi_cache_target_feature_links_dataset
            FOREIGN KEY (provider_dataset_id)
            REFERENCES provider_sync.provider_datasets (provider_dataset_id) NOT VALID;
        ALTER TABLE ops.enrichment_review_queue
            ALTER COLUMN source_entity_key SET NOT NULL,
            ALTER COLUMN source_record_key SET NOT NULL,
            DROP CONSTRAINT IF EXISTS uq_enrichment_review_candidate,
            ADD CONSTRAINT uq_enrichment_review_candidate
                UNIQUE (target_feature_id, source_entity_key),
            ADD CONSTRAINT fk_enrichment_review_queue_source_entity
            FOREIGN KEY (source_entity_key)
            REFERENCES provider_sync.source_entities (source_entity_key)
            ON DELETE RESTRICT NOT VALID,
            ADD CONSTRAINT fk_enrichment_review_queue_source_record
            FOREIGN KEY (source_entity_key, source_record_key)
            REFERENCES provider_sync.source_records (source_entity_key, source_record_key)
            ON DELETE RESTRICT NOT VALID;
        ALTER TABLE ops.managed_files
            ADD CONSTRAINT fk_managed_files_dataset
            FOREIGN KEY (provider_dataset_id)
            REFERENCES provider_sync.provider_datasets (provider_dataset_id) NOT VALID,
            ADD CONSTRAINT ck_managed_files_owner_v2 CHECK (
                (provider_dataset_id IS NOT NULL AND provider_name IS NULL)
                OR (provider_dataset_id IS NULL AND provider_name IS NOT NULL)
                OR (provider_dataset_id IS NULL AND provider_name IS NULL)
            ) NOT VALID;
        """
    )


def _validate_constraints() -> None:
    for table, name in (
        ("provider_sync.source_entities", "fk_source_entities_provider_dataset"),
        ("provider_sync.source_records", "ck_source_records_raw_data_object"),
        ("provider_sync.source_records", "ck_source_records_payload_hash_canonical"),
        ("provider_sync.provider_sync_state", "fk_provider_sync_state_scope"),
        ("provider_sync.notice_lifecycle_scopes", "fk_notice_lifecycle_scopes_dataset"),
        ("provider_sync.notice_lineage_states", "fk_notice_lineage_states_scope"),
        ("feature.curated_sources", "fk_curated_sources_dataset"),
        ("ops.import_jobs", "ck_import_jobs_membership_mode"),
        ("ops.import_job_datasets", "fk_import_job_datasets_job"),
        ("ops.import_job_datasets", "fk_import_job_datasets_scope"),
        ("ops.import_job_events", "fk_import_job_events_job_member"),
        ("ops.feature_update_requests", "ck_feature_update_requests_membership_mode"),
        ("ops.feature_update_request_datasets", "fk_feature_update_request_datasets_request"),
        ("ops.feature_update_request_datasets", "fk_feature_update_request_datasets_scope"),
        ("ops.offline_uploads", "fk_offline_uploads_scope"),
        ("ops.provider_refresh_policies", "fk_provider_refresh_policies_dataset"),
        ("ops.integrity_observation_scopes", "fk_integrity_observation_scopes_dataset"),
        ("ops.integrity_observation_runs", "fk_integrity_observation_runs_scope"),
        ("ops.data_integrity_violations", "fk_data_integrity_violations_dataset"),
        ("ops.poi_cache_target_feature_links", "fk_poi_cache_target_feature_links_dataset"),
        ("ops.enrichment_review_queue", "fk_enrichment_review_queue_source_entity"),
        ("ops.enrichment_review_queue", "fk_enrichment_review_queue_source_record"),
        ("ops.managed_files", "fk_managed_files_dataset"),
        ("ops.managed_files", "ck_managed_files_owner_v2"),
    ):
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def _create_indexes_concurrently() -> None:
    # PostgreSQL transaction 밖에서만 concurrent index DDL을 실행한다. 실패한
    # invalid index는 rerun 전에 같은 이름으로 제거한다.
    with op.get_context().autocommit_block():
        for index_name in (
            "provider_sync.idx_provider_dataset_operations_enabled",
            "provider_sync.idx_provider_dataset_operation_scopes_operation",
            "provider_sync.idx_source_entities_provider_dataset",
            "provider_sync.idx_provider_sync_state_next_run",
            "provider_sync.idx_notice_lineage_states_scope_present",
            "ops.idx_import_job_datasets_exact_operation_job",
            "ops.idx_import_job_events_member_time",
            "ops.idx_feature_update_request_datasets_dataset_request",
            "ops.idx_offline_uploads_dataset_created",
            "ops.idx_provider_refresh_enabled",
            "ops.idx_integrity_observation_runs_scope_status",
            "ops.idx_data_integrity_violations_dataset_status",
            "ops.idx_poi_cache_target_feature_links_dataset",
            "ops.idx_enrichment_review_queue_source_entity_record",
            "ops.idx_managed_files_provider_dataset",
            "ops.idx_managed_files_provider_name",
        ):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {index_name}")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_provider_dataset_operations_enabled
            ON provider_sync.provider_dataset_operations (provider_dataset_id, operation_key)
            WHERE is_enabled
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_provider_dataset_operation_scopes_operation
            ON provider_sync.provider_dataset_operation_scopes (provider_dataset_id, operation_key)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_source_entities_provider_dataset
            ON provider_sync.source_entities (provider_dataset_id)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_provider_sync_state_next_run
            ON provider_sync.provider_sync_state (next_run_after)
            WHERE status = 'active'
            """
        )
        # 위 index는 0002의 ``idx_sync_state_next_run``을 T-VN-33 이름 규약
        # (``idx_<table>_…``, contracts/vnext/tvn33-reference-ownership-v1.sql)으로
        # 개명한 것이다. 옛 이름을 남겨두면 술어·열이 완전히 같은 index 두 개가
        # 공존해 쓰기 비용과 저장 공간을 두 번 낸다. 새 index를 만든 뒤에 지워
        # 폴링 경로가 index 없는 구간을 겪지 않게 한다.
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS provider_sync.idx_sync_state_next_run")
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_notice_lineage_states_scope_present
            ON provider_sync.notice_lineage_states (
                notice_lifecycle_scope_id, present, changed_at DESC
            )
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_import_job_datasets_exact_operation_job
            ON ops.import_job_datasets (
                provider_dataset_id, sync_scope, operation_key, job_id
            )
            """
        )
        # 0091이 지운 ``idx_import_job_events_provider_dataset_scope_time``의
        # 대체 경로다. scope 정본이 membership으로 옮겨갔으므로 event 감사
        # 조회(``ops_repo._scoped_import_job_events_sql``)는 member 마다 상위
        # ``limit``만 뽑아 합친다. ``level``을 INCLUDE에 두는 이유는 그 per-member
        # scan을 level filter가 붙어도 index-only로 유지하기 위해서다 — heap을
        # 때리기 시작하면 member 수에 비례한 random I/O가 그대로 돌아온다
        # (실측: 300k event / 300 member scope에서 61,422 → 1,533 buffer).
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_import_job_events_member_time
            ON ops.import_job_events (
                import_job_dataset_id, occurred_at DESC, event_id DESC
            )
            INCLUDE (level)
            WHERE import_job_dataset_id IS NOT NULL AND quarantined_at IS NULL
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_feature_update_request_datasets_dataset_request
            ON ops.feature_update_request_datasets (provider_dataset_id, request_id)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_offline_uploads_dataset_created
            ON ops.offline_uploads (provider_dataset_id, created_at DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_provider_refresh_enabled
            ON ops.provider_refresh_policies (enabled, provider_dataset_id)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_integrity_observation_runs_scope_status
            ON ops.integrity_observation_runs (
                integrity_observation_scope_id, status, generation DESC
            )
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_data_integrity_violations_dataset_status
            ON ops.data_integrity_violations (
                provider_dataset_id, status, last_seen_at DESC
            ) WHERE provider_dataset_id IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_poi_cache_target_feature_links_dataset
            ON ops.poi_cache_target_feature_links (provider_dataset_id)
            WHERE active AND provider_dataset_id IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_enrichment_review_queue_source_entity_record
            ON ops.enrichment_review_queue (source_entity_key, source_record_key)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_managed_files_provider_dataset
            ON ops.managed_files (provider_dataset_id)
            WHERE provider_dataset_id IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_managed_files_provider_name
            ON ops.managed_files (provider_name)
            WHERE provider_name IS NOT NULL
            """
        )


def upgrade() -> None:
    _preflight()
    _constraints()
    _validate_constraints()
    _create_indexes_concurrently()


def downgrade() -> None:
    raise RuntimeError("T-VN-33 is forward-only: rebuild the development database from final ETL.")

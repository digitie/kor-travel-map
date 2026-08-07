"""T-VN-33C — canonical writer cutover와 final physical schema.

Revision ID: 0091_tvn33_cutover_fence
Revises: 0090_tvn33_constraints

이 revision 이후 provider/dataset pair shadow는 운영 테이블에 남기지 않는다.
normal write는 canonical ID·scope·membership만 쓴다. rollback은 지원하지 않으며
final-schema DB는 ETL로 재생성한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.util.concurrency import await_only

from alembic import op

revision: str = "0091_tvn33_cutover_fence"
down_revision: str | Sequence[str] | None = "0090_tvn33_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _execute_sql_script(sql: str) -> None:
    """asyncpg prepared statement가 거부하는 복수 DDL을 현재 transaction에서 실행한다."""
    raw_connection = op.get_bind().connection.driver_connection
    await_only(raw_connection.execute(sql))


def _preflight_or_raise(label: str, probe_sql: str, remedy: str) -> None:
    """모호한 legacy snapshot은 추측으로 보정하지 않고 cutover를 중단한다."""
    quoted_label = label.replace("'", "''")
    quoted_remedy = remedy.replace("'", "''")
    op.execute(
        f"""
        DO $preflight$
        DECLARE total bigint;
        BEGIN
            SELECT count(*) INTO total FROM ({probe_sql}) AS probe;
            IF total <> 0 THEN
                RAISE EXCEPTION 'T-VN-33C preflight: % (% row(s))',
                    '{quoted_label}', total
                    USING HINT = '{quoted_remedy}';
            END IF;
        END
        $preflight$;
        """
    )


def _detach_legacy_constraints() -> None:
    """물리 삭제 전에 pair/array shadow에 매달린 제약과 index를 해체한다."""
    _execute_sql_script(
        """
        ALTER TABLE provider_sync.source_entities
            DROP CONSTRAINT IF EXISTS fk_source_entities_current_record,
            DROP CONSTRAINT IF EXISTS uq_source_entities_identity;
        DROP INDEX IF EXISTS provider_sync.idx_source_entities_current_record;
        ALTER TABLE provider_sync.source_records
            DROP CONSTRAINT IF EXISTS uq_source_records;
        DROP INDEX IF EXISTS provider_sync.idx_source_records_provider_dataset_entity;
        DROP INDEX IF EXISTS provider_sync.idx_source_records_entity_history;
        DROP INDEX IF EXISTS provider_sync.idx_source_records_kma_alert_history;
        DROP INDEX IF EXISTS provider_sync.idx_source_records_last_seen_at_brin;
        DROP INDEX IF EXISTS provider_sync.idx_source_records_expires_at;
        DROP INDEX IF EXISTS provider_sync.idx_source_links_primary;
        CREATE INDEX idx_source_links_primary
            ON provider_sync.source_links (feature_id)
            WHERE source_role = 'primary';
        DROP INDEX IF EXISTS feature.idx_curated_sources_provider;
        ALTER TABLE ops.import_jobs
            DROP CONSTRAINT IF EXISTS ck_import_jobs_provider_dataset_pair,
            DROP CONSTRAINT IF EXISTS ck_import_jobs_update_request_shape,
            DROP CONSTRAINT IF EXISTS ck_import_jobs_feature_tracking_shape;
        DROP INDEX IF EXISTS ops.uq_import_jobs_active_feature_update_scope;
        DROP INDEX IF EXISTS ops.uq_import_jobs_feature_run_pair;
        DROP INDEX IF EXISTS ops.idx_import_jobs_provider_dataset_created;
        DROP INDEX IF EXISTS ops.idx_import_jobs_dataset_created;
        DROP INDEX IF EXISTS ops.idx_import_jobs_provider_created;
        ALTER TABLE ops.import_job_events
            DROP CONSTRAINT IF EXISTS ck_import_job_events_provider_dataset_pair,
            DROP CONSTRAINT IF EXISTS ck_import_job_events_sync_scope;
        DROP INDEX IF EXISTS ops.idx_import_job_events_provider_time;
        DROP INDEX IF EXISTS ops.idx_import_job_events_provider_dataset_time;
        DROP INDEX IF EXISTS ops.idx_import_job_events_provider_dataset_scope_time;
        ALTER TABLE ops.feature_update_requests
            DROP CONSTRAINT IF EXISTS ck_feature_update_requests_providers_shape,
            DROP CONSTRAINT IF EXISTS ck_feature_update_requests_dataset_keys_shape,
            DROP CONSTRAINT IF EXISTS ck_feature_update_requests_direct_filters_empty;
        DROP INDEX IF EXISTS ops.idx_feature_update_providers_gin;
        DROP INDEX IF EXISTS ops.idx_feature_update_dataset_keys_gin;
        ALTER TABLE ops.offline_uploads
            DROP CONSTRAINT IF EXISTS uq_offline_uploads_provider_dataset_scope_checksum;
        DROP INDEX IF EXISTS ops.idx_offline_uploads_provider_dataset;
        ALTER TABLE ops.integrity_observation_scopes
            DROP CONSTRAINT IF EXISTS ck_integrity_observation_scopes_provider,
            DROP CONSTRAINT IF EXISTS ck_integrity_observation_scopes_dataset;
        ALTER TABLE ops.integrity_observation_runs
            DROP CONSTRAINT IF EXISTS uq_integrity_observation_runs_generation,
            DROP CONSTRAINT IF EXISTS uq_integrity_observation_runs_external_run;
        DROP INDEX IF EXISTS ops.idx_violations_provider_status_seen;
        DROP INDEX IF EXISTS ops.idx_violations_provider_status_detected;
        DROP INDEX IF EXISTS ops.idx_poi_cache_links_provider_dataset;
        DROP INDEX IF EXISTS ops.idx_managed_files_provider;
        DROP INDEX IF EXISTS ops.idx_enrichment_review_provider_status_score;
        """
    )


def _replace_pre_tvn33_ownership_guards() -> None:
    """삭제할 pair/array column을 읽는 기존 trigger를 canonical guard로 교체한다."""
    _execute_sql_script(
        """
        DROP TRIGGER IF EXISTS trg_import_jobs_identity_immutable ON ops.import_jobs;
        DROP TRIGGER IF EXISTS trg_import_jobs_feature_update_pair ON ops.import_jobs;
        DROP TRIGGER IF EXISTS ck_import_jobs_feature_operation_identity_immutable
            ON ops.import_jobs;
        DROP TRIGGER IF EXISTS trg_import_job_events_identity ON ops.import_job_events;
        DROP TRIGGER IF EXISTS trg_feature_update_requests_job_identity
            ON ops.feature_update_requests;
        DROP TRIGGER IF EXISTS trg_feature_update_requests_mutation_guard
            ON ops.feature_update_requests;

        DROP FUNCTION IF EXISTS ops.enforce_import_job_event_identity();
        DROP FUNCTION IF EXISTS ops.enforce_feature_update_job_pair();
        DROP FUNCTION IF EXISTS ops.assert_feature_update_job_pair(uuid);
        DROP FUNCTION IF EXISTS ops.reject_feature_operation_identity_mutation();

        CREATE OR REPLACE FUNCTION ops.reject_import_job_identity_change()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.kind IS DISTINCT FROM OLD.kind
               OR NEW.dataset_membership_mode
                  IS DISTINCT FROM OLD.dataset_membership_mode
               OR NEW.root_id IS DISTINCT FROM OLD.root_id
               OR NEW.root_kind IS DISTINCT FROM OLD.root_kind
               OR (
                   OLD.kind = 'feature_update_request'
                   AND NEW.payload IS DISTINCT FROM OLD.payload
               ) THEN
                RAISE EXCEPTION 'import job canonical identity is immutable: %', OLD.job_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_job_identity_immutable';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_import_jobs_identity_immutable
            BEFORE UPDATE OF kind, dataset_membership_mode, root_id, root_kind, payload
            ON ops.import_jobs
            FOR EACH ROW EXECUTE FUNCTION ops.reject_import_job_identity_change();

        CREATE OR REPLACE FUNCTION ops.enforce_feature_update_request_job_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE linked_kind text; linked_quarantined_at timestamptz;
        BEGIN
            SELECT job.kind, job.quarantined_at
              INTO linked_kind, linked_quarantined_at
            FROM ops.import_jobs AS job
            WHERE job.job_id = NEW.job_id
            FOR KEY SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'feature update request job does not exist: %', NEW.job_id
                    USING ERRCODE = '23503';
            END IF;
            IF linked_kind IS DISTINCT FROM 'feature_update_request' THEN
                RAISE EXCEPTION
                    'feature update request must link a canonical feature_update_request job'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_job_kind';
            END IF;
            IF linked_quarantined_at IS NOT NULL THEN
                RAISE EXCEPTION 'feature update request cannot link a quarantined import job'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_job_quarantine';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_feature_update_requests_job_identity
            BEFORE INSERT ON ops.feature_update_requests
            FOR EACH ROW EXECUTE FUNCTION ops.enforce_feature_update_request_job_identity();

        CREATE OR REPLACE FUNCTION ops.guard_feature_update_request_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE linked_status text; linked_cancellation_id uuid;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'feature update request is append-only: %', OLD.request_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_append_only';
            END IF;
            IF NEW.request_id IS DISTINCT FROM OLD.request_id
               OR NEW.job_id IS DISTINCT FROM OLD.job_id
               OR NEW.scope_type IS DISTINCT FROM OLD.scope_type
               OR NEW.scope IS DISTINCT FROM OLD.scope
               OR NEW.dataset_membership_mode
                  IS DISTINCT FROM OLD.dataset_membership_mode
               OR NEW.update_policy IS DISTINCT FROM OLD.update_policy
               OR NEW.run_mode IS DISTINCT FROM OLD.run_mode
               OR NEW.priority IS DISTINCT FROM OLD.priority
               OR NEW.operator IS DISTINCT FROM OLD.operator
               OR NEW.reason IS DISTINCT FROM OLD.reason
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'feature update request input/audit identity is immutable: %',
                    OLD.request_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_identity_immutable';
            END IF;
            IF NEW.generation IS DISTINCT FROM OLD.generation
               AND NEW.generation <> OLD.generation + 1 THEN
                RAISE EXCEPTION
                    'feature update request generation must increase by exactly one: %',
                    OLD.request_id
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_generation';
            END IF;
            IF NEW.matched_scope IS DISTINCT FROM OLD.matched_scope
               OR NEW.generation IS DISTINCT FROM OLD.generation THEN
                SELECT job.status, job.cancellation_id
                  INTO linked_status, linked_cancellation_id
                FROM ops.import_jobs AS job
                WHERE job.job_id = OLD.job_id
                FOR UPDATE;
                IF NOT FOUND
                   OR linked_status NOT IN ('queued', 'running')
                   OR linked_cancellation_id IS NOT NULL THEN
                    RAISE EXCEPTION
                        'feature update request mutable fields require active unmarked job: %',
                        OLD.request_id
                        USING ERRCODE = '23514',
                            CONSTRAINT = 'ck_feature_update_request_mutable_fields';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_feature_update_requests_mutation_guard
            BEFORE UPDATE OR DELETE ON ops.feature_update_requests
            FOR EACH ROW EXECUTE FUNCTION ops.guard_feature_update_request_mutation();
        """
    )


def _rename_runtime_operation_key() -> None:
    """정적 registry version shadow를 DB handler ``operation_key``로 hard-cut한다."""
    _execute_sql_script(
        """
        ALTER TABLE ops.import_jobs
            DROP CONSTRAINT IF EXISTS ck_import_jobs_registry_version_owner;
        ALTER TABLE ops.import_jobs
            RENAME COLUMN operation_registry_version TO operation_key;
        ALTER TABLE ops.import_jobs
            ADD CONSTRAINT ck_import_jobs_operation_key_shape CHECK (
                (kind = 'provider_feature_load_run'
                    AND operation_key IS NOT NULL
                    AND operation_key = btrim(operation_key)
                    AND operation_key <> '')
                OR
                (kind <> 'provider_feature_load_run' AND operation_key IS NULL)
            );
        """
    )


def _freeze_feature_update_operation_memberships() -> None:
    """Request snapshot을 exact refresh operation에 FK로 결박한다.

    ``sync_scope``는 operation key를 해석하는 입력이 아니라 snapshot의 일부다.
    이 column을 남기면 operation scope가 나중에 다른 handler로 재결박될 때 과거
    update request의 실행 의미가 바뀌는 것을 FK가 막는다.
    """
    _preflight_or_raise(
        "historical feature update member has an ambiguous operation scope",
        """
        SELECT member.feature_update_request_dataset_id
        FROM ops.feature_update_request_datasets AS member
        JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = member.provider_dataset_id
         AND scope.sync_scope = member.sync_scope
        GROUP BY member.feature_update_request_dataset_id
        HAVING count(*) <> 1
        """,
        "Rebuild historical feature-update requests with an explicit operation snapshot.",
    )
    _preflight_or_raise(
        "historical sync state has an ambiguous refresh operation scope",
        """
        SELECT state.provider_dataset_id, state.sync_scope
        FROM provider_sync.provider_sync_state AS state
        JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = state.provider_dataset_id
         AND scope.sync_scope = state.sync_scope
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = scope.provider_dataset_id
         AND operation.operation_key = scope.operation_key
         AND operation.operation_kind = scope.operation_kind
        WHERE operation.operation_kind = 'refresh'
        GROUP BY state.provider_dataset_id, state.sync_scope
        HAVING count(*) <> 1
        """,
        "Rebuild historical sync state through one explicit refresh operation.",
    )
    _preflight_or_raise(
        "historical import job member has an ambiguous operation scope",
        """
        SELECT member.import_job_dataset_id
        FROM ops.import_job_datasets AS member
        JOIN provider_sync.provider_dataset_operation_scopes AS scope
          ON scope.provider_dataset_id = member.provider_dataset_id
         AND scope.sync_scope = member.sync_scope
        GROUP BY member.import_job_dataset_id
        HAVING count(*) <> 1
        """,
        "Rebuild historical import jobs with an explicit operation snapshot.",
    )
    _execute_sql_script(
        """
        -- 실행 membership identity는 triple이다(ADR-088 §결정 2). 여기서 scope PK를
        -- 승격한다 — 0089/0090은 membership 열이 아직 없어 pair PK를 쓴다.
        -- pair PK로 남기면 한 dataset의 한 scope에 refresh operation을 **하나만**
        -- 등록할 수 있고, UNIQUE로 triple을 걸어도 더 강한 PK가 이긴다.
        -- pair PK를 참조하는 중간 FK를 먼저 떼야 PK를 바꿀 수 있다. 아래에서
        -- 각 테이블이 triple FK로 다시 붙는다.
        ALTER TABLE provider_sync.provider_sync_state
            DROP CONSTRAINT IF EXISTS fk_provider_sync_state_scope;
        ALTER TABLE ops.import_job_datasets
            DROP CONSTRAINT IF EXISTS fk_import_job_datasets_scope;
        ALTER TABLE ops.feature_update_request_datasets
            DROP CONSTRAINT IF EXISTS fk_feature_update_request_datasets_scope;
        ALTER TABLE ops.offline_uploads
            DROP CONSTRAINT IF EXISTS fk_offline_uploads_scope;

        ALTER TABLE provider_sync.provider_dataset_operation_scopes
            DROP CONSTRAINT IF EXISTS pk_provider_dataset_operation_scopes,
            ADD CONSTRAINT pk_provider_dataset_operation_scopes
                PRIMARY KEY (provider_dataset_id, sync_scope, operation_key);

        -- offline upload도 실행 membership이므로 같은 triple을 참조한다.
        ALTER TABLE ops.offline_uploads
            ALTER COLUMN operation_key SET NOT NULL,
            ADD CONSTRAINT fk_offline_uploads_exact_operation_scope
            FOREIGN KEY (provider_dataset_id, sync_scope, operation_key)
            REFERENCES provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key
            ) ON DELETE RESTRICT;

        -- 멱등 키도 같은 triple로 올린다. pair로 남기면 같은 파일을 서로 다른
        -- operation에 올리는 정상 흐름이 충돌로 막힌다 (cutover 전에는 operation
        -- 구분이 없었으므로 잃는 보증은 없다).
        ALTER TABLE ops.offline_uploads
            DROP CONSTRAINT IF EXISTS uq_offline_uploads_dataset_scope_checksum,
            ADD CONSTRAINT uq_offline_uploads_dataset_scope_checksum
            UNIQUE (provider_dataset_id, sync_scope, operation_key, checksum_sha256);

        ALTER TABLE provider_sync.provider_sync_state
            ADD COLUMN operation_key text;
        UPDATE provider_sync.provider_sync_state AS state
           SET operation_key = scope.operation_key
          FROM provider_sync.provider_dataset_operation_scopes AS scope
          JOIN provider_sync.provider_dataset_operations AS operation
            ON operation.provider_dataset_id = scope.provider_dataset_id
           AND operation.operation_key = scope.operation_key
           AND operation.operation_kind = scope.operation_kind
         WHERE scope.provider_dataset_id = state.provider_dataset_id
           AND scope.sync_scope = state.sync_scope
           AND operation.operation_kind = 'refresh';
        ALTER TABLE provider_sync.provider_sync_state
            ALTER COLUMN operation_key SET NOT NULL,
            DROP CONSTRAINT IF EXISTS fk_provider_sync_state_scope,
            DROP CONSTRAINT IF EXISTS pk_provider_sync_state,
            ADD CONSTRAINT pk_provider_sync_state
                PRIMARY KEY (provider_dataset_id, sync_scope, operation_key),
            ADD CONSTRAINT fk_provider_sync_state_exact_operation_scope
                FOREIGN KEY (provider_dataset_id, sync_scope, operation_key)
                REFERENCES provider_sync.provider_dataset_operation_scopes (
                    provider_dataset_id, sync_scope, operation_key
                )
                ON DELETE RESTRICT;

        ALTER TABLE ops.feature_update_request_datasets
            ADD COLUMN operation_key text;
        UPDATE ops.feature_update_request_datasets AS member
           SET operation_key = scope.operation_key
          FROM provider_sync.provider_dataset_operation_scopes AS scope
         WHERE scope.provider_dataset_id = member.provider_dataset_id
           AND scope.sync_scope = member.sync_scope;
        ALTER TABLE ops.feature_update_request_datasets
            ALTER COLUMN operation_key SET NOT NULL,
            DROP CONSTRAINT IF EXISTS fk_feature_update_request_datasets_scope,
            ADD CONSTRAINT fk_feature_update_request_datasets_exact_operation_scope
                FOREIGN KEY (provider_dataset_id, sync_scope, operation_key)
                REFERENCES provider_sync.provider_dataset_operation_scopes (
                    provider_dataset_id, sync_scope, operation_key
                )
                ON DELETE RESTRICT;

        UPDATE ops.import_job_datasets AS job_member
           SET operation_key = scope.operation_key
          FROM provider_sync.provider_dataset_operation_scopes AS scope
         WHERE scope.provider_dataset_id = job_member.provider_dataset_id
           AND scope.sync_scope = job_member.sync_scope;

        ALTER TABLE ops.import_job_datasets
            ALTER COLUMN operation_key SET NOT NULL,
            DROP CONSTRAINT IF EXISTS fk_import_job_datasets_scope,
            ADD CONSTRAINT fk_import_job_datasets_exact_operation_scope
            FOREIGN KEY (provider_dataset_id, sync_scope, operation_key)
            REFERENCES provider_sync.provider_dataset_operation_scopes (
                provider_dataset_id, sync_scope, operation_key
            )
            ON DELETE RESTRICT;
        """
    )


def _rewrite_final_curation_source_rule_trigger() -> None:
    """0090 뒤 삭제되는 source-record pair shadow를 trigger에서 제거한다."""
    _execute_sql_script(
        """
        CREATE OR REPLACE FUNCTION feature.issue_curation_source_rule_decision()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            projection feature.curated_features%ROWTYPE;
            source_provider text;
            source_dataset text;
            new_decision_id uuid;
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM feature.curation_link_decisions AS existing
                WHERE existing.decision_id = NEW.accepted_link_decision_id
                  AND existing.curation_item_id = NEW.curation_item_id
                  AND existing.feature_id = NEW.feature_id
                  AND existing.decision_kind = 'accepted'
                  AND existing.match_basis <> 'legacy_unattributed'
            ) THEN
                RETURN NULL;
            END IF;

            IF EXISTS (
                SELECT 1
                FROM feature.curation_link_decisions AS revocation
                WHERE revocation.curation_item_id = NEW.curation_item_id
                  AND revocation.decision_kind = 'revoked'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM feature.curation_link_decisions AS successor
                      WHERE successor.supersedes_decision_id = revocation.decision_id
                  )
            ) THEN
                RETURN NULL;
            END IF;

            SELECT * INTO projection
              FROM feature.curated_features AS cf
             WHERE cf.curated_feature_id =
                   COALESCE(NEW.legacy_projection_id, NEW.curation_item_id);
            IF NOT FOUND
               OR projection.selection_origin IS DISTINCT FROM 'source_rule'
               OR projection.feature_id IS DISTINCT FROM NEW.feature_id
               OR projection.source_record_key IS DISTINCT FROM NEW.source_record_key
            THEN
                RETURN NULL;
            END IF;

            SELECT dataset.provider, dataset.dataset_key
              INTO source_provider, source_dataset
              FROM provider_sync.source_records AS record
              JOIN provider_sync.source_entities AS entity
                ON entity.source_entity_key = record.source_entity_key
              JOIN provider_sync.provider_datasets AS dataset
                ON dataset.provider_dataset_id = entity.provider_dataset_id
             WHERE record.source_record_key = projection.source_record_key;
            IF source_provider IS NULL THEN
                RETURN NULL;
            END IF;

            INSERT INTO feature.curation_link_decisions (
                curation_item_id, feature_id, decision_kind, match_basis,
                resolver_version, evidence, actor, decided_at, supersedes_decision_id
            ) VALUES (
                NEW.curation_item_id, NEW.feature_id, 'accepted', 'source_rule',
                'source-rule-v' || projection.content_version::text,
                jsonb_build_object(
                    'writer', 'issue_curation_source_rule_decision',
                    'source_record_key', projection.source_record_key,
                    'selection_origin', projection.selection_origin,
                    'content_version', projection.content_version,
                    'provider', source_provider,
                    'dataset_key', source_dataset
                ),
                COALESCE(NULLIF(btrim(projection.selected_by), ''),
                         'source_rule:' || source_provider),
                COALESCE(NEW.updated_at, now()),
                NEW.accepted_link_decision_id
            ) RETURNING decision_id INTO new_decision_id;

            UPDATE feature.curation_items
               SET accepted_link_decision_id = new_decision_id
             WHERE curation_item_id = NEW.curation_item_id;
            RETURN NULL;
        END;
        $$;
        """
    )


def _move_notice_lineage_to_head() -> None:
    """notice 계보 물화를 ``source_records``에서 ``source_entity_heads``로 옮긴다.

    T-VN-37(ADR-087)은 계보 key를 ``source_records.lineage_key``에 물화하고
    ``(COALESCE(lineage_key, source_entity_id), last_seen_at DESC,
    source_record_key DESC)`` 표현식 인덱스로 경쟁자를 찾았다. 그 세 입력
    (``source_entity_id``·``last_seen_at``·scope 3열)을 이 revision이 전부
    폐기하므로 그대로 둘 수 없다 — 실제로 트리거의 ``UPDATE OF`` 열 목록이
    ``DROP COLUMN provider``를 막는다.

    옮길 자리는 head다. 이유가 두 가지다.

    1. **깊이 무관.** ``source_records``는 payload **이력 전체**를 담는데 한 계보에서
       실제로 경쟁하는 것은 entity당 current 하나뿐이다. 인덱스를 record에 두면
       스캔이 이력 깊이에 비례하고, KMA 계보 key에는 시간 성분이 없어 그 깊이가
       영원히 증가한다. head는 entity당 정확히 한 행이라 그 축이 사라진다.
    2. **순서 축이 이미 여기 있다.** 승자 판정 축은 ``observed_at``이고 그것을
       소유하는 것이 head다(ADR-088). record의 ``last_seen_at``은 폐기된다.

    계보 값 자체는 여전히 record의 불변 ``raw_data``에서 나온다 — head가 가리키는
    current record에서 계산해 head에 캐시한다. head가 움직이면 트리거가 다시
    계산하므로 낡지 않는다.
    """
    _execute_sql_script(
        """
        DROP TRIGGER IF EXISTS trg_source_record_lineage_key
            ON provider_sync.source_records;
        DROP FUNCTION IF EXISTS provider_sync.set_source_record_lineage_key();
        DROP INDEX IF EXISTS provider_sync.idx_source_records_lineage;
        DROP FUNCTION IF EXISTS provider_sync.notice_lineage_key(
            provider_sync.source_records
        );
        ALTER TABLE provider_sync.source_records DROP COLUMN IF EXISTS lineage_key;

        ALTER TABLE provider_sync.source_entity_heads
            ADD COLUMN lineage_key varchar;

        CREATE FUNCTION provider_sync.notice_lineage_key(
            head provider_sync.source_entity_heads
        ) RETURNS text
        LANGUAGE sql STABLE
        AS $fn$
            SELECT CASE
              WHEN dataset.provider = 'python-krex-api'
               AND dataset.dataset_key = 'krex_traffic_notices'
               AND entity.source_entity_type = 'traffic_notice'
              THEN COALESCE(
                NULLIF(
                  concat_ws(
                    '::',
                    NULLIF(lower(btrim(record.raw_data->>'occurred_date')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'occurred_time')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'route_no')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'direction')), ''),
                    NULLIF(lower(btrim(record.raw_data->>'point_name')), ''),
                    NULLIF(
                      lower(btrim(record.raw_data->>'incident_type_code')), ''
                    )
                  ),
                  ''
                ),
                entity.source_entity_id
              )
              WHEN dataset.provider = 'python-kma-api'
               AND dataset.dataset_key = 'kma_weather_alerts'
               AND entity.source_entity_type = 'weather_alert'
              THEN COALESCE(
                NULLIF(
                  concat_ws(
                    '::',
                    NULLIF(btrim(record.raw_data->>'region_code'), ''),
                    NULLIF(
                      btrim(
                        COALESCE(
                          record.raw_data->>'phenomenon',
                          record.raw_data->>'alert_type'
                        )
                      ),
                      ''
                    )
                  ),
                  ''
                ),
                entity.source_entity_id
              )
              -- out-of-scope도 값을 갖는다. 읽는 쪽이
              -- COALESCE(head.lineage_key, entity.source_entity_id)로 물러나면
              -- **두 테이블에 걸친 식**이 되어 어떤 단일 인덱스도 받지 못한다.
              ELSE entity.source_entity_id
            END
            FROM provider_sync.source_entities AS entity
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = entity.provider_dataset_id
            JOIN provider_sync.source_records AS record
              ON record.source_record_key = head.current_source_record_key
            WHERE entity.source_entity_key = head.source_entity_key
        $fn$;

        UPDATE provider_sync.source_entity_heads AS head
        SET lineage_key = provider_sync.notice_lineage_key(head);
        ALTER TABLE provider_sync.source_entity_heads
            ALTER COLUMN lineage_key SET NOT NULL;

        CREATE FUNCTION provider_sync.set_source_entity_head_lineage_key()
        RETURNS trigger LANGUAGE plpgsql AS $tg$
        BEGIN
            NEW.lineage_key := provider_sync.notice_lineage_key(NEW);
            RETURN NEW;
        END
        $tg$;

        CREATE TRIGGER trg_source_entity_head_lineage_key
          BEFORE INSERT OR UPDATE OF current_source_record_key, lineage_key
          ON provider_sync.source_entity_heads
          FOR EACH ROW
          EXECUTE FUNCTION provider_sync.set_source_entity_head_lineage_key();
        ALTER TABLE provider_sync.source_entity_heads
          ENABLE ALWAYS TRIGGER trg_source_entity_head_lineage_key;

        CREATE INDEX idx_source_entity_heads_lineage
          ON provider_sync.source_entity_heads (
            lineage_key, observed_at DESC, current_source_record_key DESC
          );

        ANALYZE provider_sync.source_entity_heads;
        """
    )


def _drop_legacy_columns() -> None:
    _execute_sql_script(
        """
        ALTER TABLE provider_sync.source_entities
            DROP COLUMN provider,
            DROP COLUMN dataset_key,
            DROP COLUMN current_source_record_key;
        ALTER TABLE provider_sync.source_records
            DROP COLUMN provider,
            DROP COLUMN dataset_key,
            DROP COLUMN source_entity_type,
            DROP COLUMN source_entity_id,
            DROP COLUMN source_version,
            DROP COLUMN raw_name,
            DROP COLUMN raw_address,
            DROP COLUMN raw_longitude,
            DROP COLUMN raw_latitude,
            DROP COLUMN last_seen_at,
            DROP COLUMN expires_at;
        ALTER TABLE provider_sync.source_links DROP COLUMN is_primary_source;
        ALTER TABLE provider_sync.provider_sync_state
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE provider_sync.notice_lifecycle_scopes
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE provider_sync.notice_lineage_states
            DROP COLUMN provider,
            DROP COLUMN dataset_key,
            DROP COLUMN source_entity_type;
        ALTER TABLE feature.curated_sources
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE feature.curated_source_rules
            DROP COLUMN dataset_key;
        ALTER TABLE ops.import_jobs
            DROP COLUMN provider,
            DROP COLUMN dataset_key,
            DROP COLUMN sync_scope;
        ALTER TABLE ops.import_job_events
            DROP COLUMN provider,
            DROP COLUMN dataset_key,
            DROP COLUMN sync_scope;
        ALTER TABLE ops.feature_update_requests
            DROP COLUMN providers,
            DROP COLUMN dataset_keys;
        ALTER TABLE ops.offline_uploads
            ALTER COLUMN sync_scope SET DEFAULT 'dataset_wide',
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE ops.provider_refresh_policies
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE ops.integrity_observation_scopes
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE ops.integrity_observation_runs
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE ops.data_integrity_violations
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE ops.poi_cache_target_feature_links
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        ALTER TABLE ops.enrichment_review_queue
            DROP COLUMN source_provider,
            DROP COLUMN source_dataset_key,
            DROP COLUMN source_entity_id,
            DROP COLUMN source_record;
        ALTER TABLE ops.managed_files
            DROP COLUMN provider,
            DROP COLUMN dataset_key;
        """
    )


def _create_dataset_guard_functions() -> None:
    _execute_sql_script(
        """
        CREATE FUNCTION provider_sync.reject_provider_dataset_identity_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.provider IS DISTINCT FROM OLD.provider
               OR NEW.dataset_key IS DISTINCT FROM OLD.dataset_key THEN
                RAISE EXCEPTION 'provider dataset identity is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_datasets_identity_immutable';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.touch_provider_dataset()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_active_provider_dataset(dataset_id bigint)
        RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF dataset_id IS NULL THEN
                RETURN;
            END IF;
            PERFORM 1
            FROM provider_sync.provider_datasets AS dataset
            WHERE dataset.provider_dataset_id = dataset_id AND dataset.is_active
            FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive normal writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_provider_dataset()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.provider_dataset_id IS DISTINCT FROM NEW.provider_dataset_id THEN
                RAISE EXCEPTION 'provider dataset ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_ownership_immutable';
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_provider_dataset(OLD.provider_dataset_id);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_provider_dataset(NEW.provider_dataset_id);
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_active_provider_dataset_scope(
            dataset_id bigint, scope_value text
        ) RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            PERFORM 1
            FROM provider_sync.provider_dataset_operation_scopes AS scope
            JOIN provider_sync.provider_dataset_operations AS operation
              ON operation.provider_dataset_id = scope.provider_dataset_id
             AND operation.operation_key = scope.operation_key
             AND operation.operation_kind = scope.operation_kind
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE scope.provider_dataset_id = dataset_id
              AND scope.sync_scope = scope_value
              AND operation.is_enabled AND dataset.is_active
            FOR SHARE OF dataset, operation;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'dataset scope is absent or disabled for normal writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_scope_active_write';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_provider_dataset_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND (OLD.provider_dataset_id, OLD.sync_scope)
                   IS DISTINCT FROM (NEW.provider_dataset_id, NEW.sync_scope) THEN
                RAISE EXCEPTION 'provider dataset scope ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_scope_ownership_immutable';
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_provider_dataset_scope(
                    OLD.provider_dataset_id, OLD.sync_scope
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_provider_dataset_scope(
                    NEW.provider_dataset_id, NEW.sync_scope
                );
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.touch_provider_dataset_operation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$;
        """
    )


def _create_lineage_guard_functions() -> None:
    _execute_sql_script(
        """
        CREATE FUNCTION provider_sync.assert_active_source_entity_dataset(entity_key text)
        RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            PERFORM 1
            FROM provider_sync.source_entities AS entity
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = entity.provider_dataset_id
            WHERE entity.source_entity_key = entity_key AND dataset.is_active
            FOR SHARE OF dataset;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive lineage writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_source_entity_dataset()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.source_entity_key IS DISTINCT FROM NEW.source_entity_key THEN
                RAISE EXCEPTION 'source entity ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entity_ownership_immutable';
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_source_entity_dataset(OLD.source_entity_key);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_source_entity_dataset(NEW.source_entity_key);
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.enforce_source_entity_identity_and_seen_at()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF NEW.provider_dataset_id IS DISTINCT FROM OLD.provider_dataset_id
               OR NEW.source_entity_type IS DISTINCT FROM OLD.source_entity_type
               OR NEW.source_entity_id IS DISTINCT FROM OLD.source_entity_id THEN
                RAISE EXCEPTION 'source entity identity is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entities_identity_immutable';
            END IF;
            IF NEW.first_seen_at IS DISTINCT FROM OLD.first_seen_at
               OR NEW.last_seen_at < OLD.last_seen_at THEN
                RAISE EXCEPTION 'source entity observed time cannot move backwards'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entities_seen_freshness';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_source_record_update()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            RAISE EXCEPTION 'provider_sync.source_records is immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_source_records_immutable';
        END;
        $$;

        CREATE FUNCTION provider_sync.enforce_source_entity_head_freshness()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            IF (NEW.observed_at, NEW.current_source_record_key)
               < (OLD.observed_at, OLD.current_source_record_key) THEN
                RAISE EXCEPTION 'source entity head freshness cannot move backwards'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entity_heads_freshness';
            END IF;
            IF NEW.observed_at = OLD.observed_at
               AND NEW.current_source_record_key = OLD.current_source_record_key
               AND NEW.expires_at IS DISTINCT FROM OLD.expires_at THEN
                RAISE EXCEPTION 'head expiry needs a newer observation'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entity_heads_expiry_freshness';
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_source_entity_head_completeness()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        DECLARE
            entity_key text;
            record_count bigint;
            head_count bigint;
        BEGIN
            entity_key := CASE WHEN TG_OP = 'DELETE' THEN OLD.source_entity_key
                               ELSE NEW.source_entity_key END;
            SELECT count(*) INTO record_count
            FROM provider_sync.source_records WHERE source_entity_key = entity_key;
            SELECT count(*) INTO head_count
            FROM provider_sync.source_entity_heads WHERE source_entity_key = entity_key;
            IF (record_count = 0 AND head_count <> 0)
               OR (record_count > 0 AND head_count <> 1) THEN
                RAISE EXCEPTION 'source entity head must exist exactly once for records'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_source_entity_heads_complete';
            END IF;
            RETURN NULL;
        END;
        $$;

        """
    )


def _create_membership_guard_functions() -> None:
    _execute_sql_script(
        """
        CREATE FUNCTION provider_sync.assert_import_job_members_active(target_job_id uuid)
        RETURNS void
        LANGUAGE plpgsql
        SET search_path = pg_catalog
        AS $$
        BEGIN
            PERFORM 1
            FROM ops.import_job_datasets AS member
            JOIN provider_sync.provider_dataset_operation_scopes AS scope
              ON scope.provider_dataset_id = member.provider_dataset_id
             AND scope.sync_scope = member.sync_scope
             AND (
                 member.operation_key IS NULL
                 OR scope.operation_key = member.operation_key
             )
            JOIN provider_sync.provider_dataset_operations AS operation
              ON operation.provider_dataset_id = scope.provider_dataset_id
             AND operation.operation_key = scope.operation_key
             AND operation.operation_kind = scope.operation_kind
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE member.job_id = target_job_id
            FOR SHARE OF dataset, operation;
            IF EXISTS (
                SELECT 1
                FROM ops.import_job_datasets AS member
                JOIN provider_sync.provider_dataset_operation_scopes AS scope
                  ON scope.provider_dataset_id = member.provider_dataset_id
                 AND scope.sync_scope = member.sync_scope
                 AND (
                     member.operation_key IS NULL
                     OR scope.operation_key = member.operation_key
                 )
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE member.job_id = target_job_id
                  AND (NOT dataset.is_active OR NOT operation.is_enabled)
            ) THEN
                RAISE EXCEPTION 'inactive dataset member cannot receive import job writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_import_job_members()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM provider_sync.assert_import_job_members_active(OLD.job_id);
            RETURN OLD;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_import_job_dataset_membership()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target_dataset_id bigint :=
            COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
            target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
            target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.provider_dataset_id = target_dataset_id
                  AND scope.sync_scope = target_scope
                  AND (target_operation_key IS NULL OR scope.operation_key = target_operation_key)
                  AND dataset.is_active
                  AND operation.is_enabled
            ) THEN
                RAISE EXCEPTION 'inactive dataset member cannot receive import job writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_import_job_membership_complete()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target_job_id uuid := COALESCE(NEW.job_id, OLD.job_id);
            mode_value text; job_kind text; member_count bigint;
        BEGIN
            SELECT dataset_membership_mode, kind INTO mode_value, job_kind
            FROM ops.import_jobs WHERE job_id = target_job_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT count(*) INTO member_count
            FROM ops.import_job_datasets WHERE job_id = target_job_id;
            IF (mode_value = 'root' AND member_count <> 0)
               OR (mode_value = 'single' AND member_count <> 1)
               OR (mode_value = 'multiple' AND member_count = 0) THEN
                RAISE EXCEPTION 'import job membership cardinality does not match mode'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_job_membership_complete';
            END IF;
            IF job_kind = 'feature_update_request' AND EXISTS (
                SELECT 1
                FROM ops.import_job_datasets AS member
                WHERE member.job_id = target_job_id
                  AND member.operation_key IS NULL
            ) THEN
                RAISE EXCEPTION 'feature update job requires exact operation membership'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_job_exact_membership';
            END IF;
            RETURN NULL;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_import_job_event_member(
            target_job_id uuid, target_member_id uuid
        ) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE mode_value text;
        BEGIN
            SELECT dataset_membership_mode INTO mode_value
            FROM ops.import_jobs WHERE job_id = target_job_id;
            IF target_member_id IS NULL THEN
                IF mode_value <> 'root' THEN
                    RAISE EXCEPTION 'dataset job event requires a dataset member'
                        USING ERRCODE = '23514',
                            CONSTRAINT = 'ck_import_job_event_member_required';
                END IF;
                RETURN;
            END IF;
            IF mode_value = 'root' THEN
                RAISE EXCEPTION 'root import job event cannot carry a dataset member'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_job_event_member_root';
            END IF;
            PERFORM provider_sync.assert_import_job_members_active(target_job_id);
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_import_job_dataset()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND (OLD.job_id, OLD.import_job_dataset_id)
                   IS DISTINCT FROM (NEW.job_id, NEW.import_job_dataset_id) THEN
                RAISE EXCEPTION 'import job event ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_import_job_event_ownership_immutable';
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_import_job_event_member(
                    OLD.job_id, OLD.import_job_dataset_id
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_import_job_event_member(
                    NEW.job_id, NEW.import_job_dataset_id
                );
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_feature_update_request_members_active(
            target_request_id uuid
        ) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM 1
            FROM ops.feature_update_request_datasets AS member
            JOIN provider_sync.provider_dataset_operation_scopes AS scope
              ON scope.provider_dataset_id = member.provider_dataset_id
             AND scope.sync_scope = member.sync_scope
             AND scope.operation_key = member.operation_key
            JOIN provider_sync.provider_dataset_operations AS operation
              ON operation.provider_dataset_id = scope.provider_dataset_id
             AND operation.operation_key = scope.operation_key
             AND operation.operation_kind = scope.operation_kind
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE member.request_id = target_request_id
            FOR SHARE OF dataset, operation;
            IF EXISTS (
                SELECT 1 FROM ops.feature_update_request_datasets AS member
                JOIN provider_sync.provider_dataset_operation_scopes AS scope
                  ON scope.provider_dataset_id = member.provider_dataset_id
                 AND scope.sync_scope = member.sync_scope
                 AND scope.operation_key = member.operation_key
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE member.request_id = target_request_id
                  AND (NOT dataset.is_active OR NOT operation.is_enabled)
            ) THEN
                RAISE EXCEPTION 'inactive dataset member cannot receive update request writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_feature_update_request_members()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM provider_sync.assert_feature_update_request_members_active(OLD.request_id);
            RETURN OLD;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_feature_update_request_dataset_membership()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target_dataset_id bigint :=
            COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
            target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
            target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.provider_dataset_id = target_dataset_id
                  AND scope.sync_scope = target_scope
                  AND scope.operation_key = target_operation_key
                  AND dataset.is_active
                  AND operation.is_enabled
            ) THEN
                RAISE EXCEPTION 'inactive dataset member cannot receive update request writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_sync_state_operation()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target_dataset_id bigint :=
            COALESCE(NEW.provider_dataset_id, OLD.provider_dataset_id);
            target_scope text := COALESCE(NEW.sync_scope, OLD.sync_scope);
            target_operation_key text := COALESCE(NEW.operation_key, OLD.operation_key);
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM provider_sync.provider_dataset_operation_scopes AS scope
                JOIN provider_sync.provider_dataset_operations AS operation
                  ON operation.provider_dataset_id = scope.provider_dataset_id
                 AND operation.operation_key = scope.operation_key
                 AND operation.operation_kind = scope.operation_kind
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = scope.provider_dataset_id
                WHERE scope.provider_dataset_id = target_dataset_id
                  AND scope.sync_scope = target_scope
                  AND scope.operation_key = target_operation_key
                  AND scope.operation_kind = 'refresh'
                  AND dataset.is_active
                  AND operation.is_enabled
            ) THEN
                RAISE EXCEPTION 'inactive refresh operation cannot receive sync state writes'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_feature_update_request_member_available(
            target_request_id uuid,
            target_dataset_id bigint,
            target_scope text,
            target_operation_key text
        ) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target_is_active boolean;
        BEGIN
            SELECT job.status IN ('queued', 'running')
                   AND job.quarantined_at IS NULL
              INTO target_is_active
            FROM ops.feature_update_requests AS request
            JOIN ops.import_jobs AS job ON job.job_id = request.job_id
            WHERE request.request_id = target_request_id;
            IF NOT FOUND OR NOT target_is_active THEN
                RETURN;
            END IF;

            -- 같은 canonical scope의 경쟁 요청은 이 row lock으로 직렬화한다.
            -- membership pair/array shadow나 별도 lease table을 만들지 않는다.
            PERFORM 1
            FROM provider_sync.provider_dataset_operation_scopes AS scope
            WHERE scope.provider_dataset_id = target_dataset_id
              AND scope.sync_scope = target_scope
              AND scope.operation_key = target_operation_key
            FOR UPDATE;

            IF EXISTS (
                SELECT 1
                FROM ops.feature_update_request_datasets AS competing_member
                JOIN ops.feature_update_requests AS competing_request
                  ON competing_request.request_id = competing_member.request_id
                JOIN ops.import_jobs AS competing_job
                  ON competing_job.job_id = competing_request.job_id
                WHERE competing_member.provider_dataset_id = target_dataset_id
                  AND competing_member.sync_scope = target_scope
                  AND competing_member.operation_key = target_operation_key
                  AND competing_member.request_id <> target_request_id
                  AND competing_job.status IN ('queued', 'running')
                  AND competing_job.quarantined_at IS NULL
            ) THEN
                RAISE EXCEPTION
                    'active feature update already owns dataset operation (% / % / %)',
                    target_dataset_id, target_scope, target_operation_key
                    USING ERRCODE = '23505',
                        CONSTRAINT = 'uq_feature_update_request_active_member';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_active_feature_update_request_member_overlap()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM provider_sync.assert_feature_update_request_member_available(
                NEW.request_id, NEW.provider_dataset_id, NEW.sync_scope, NEW.operation_key
            );
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.lock_feature_update_request_member_scopes(
            target_request_id uuid
        ) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            -- terminal transition도 같은 lock을 잡아 release와 새 acquire가
            -- 같은 scope에서 선행 순서를 갖게 한다.
            PERFORM 1
            FROM provider_sync.provider_dataset_operation_scopes AS scope
            JOIN ops.feature_update_request_datasets AS member
              ON member.provider_dataset_id = scope.provider_dataset_id
             AND member.sync_scope = scope.sync_scope
             AND member.operation_key = scope.operation_key
            WHERE member.request_id = target_request_id
            ORDER BY scope.provider_dataset_id, scope.sync_scope, scope.operation_key
            FOR UPDATE OF scope;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_feature_update_request_activation_overlap()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE request_uuid uuid;
            old_is_active boolean;
            new_is_active boolean;
        BEGIN
            SELECT request.request_id INTO request_uuid
            FROM ops.feature_update_requests AS request
            WHERE request.job_id = NEW.job_id;
            IF NOT FOUND THEN
                RETURN NEW;
            END IF;

            old_is_active := OLD.status IN ('queued', 'running')
                AND OLD.quarantined_at IS NULL;
            new_is_active := NEW.status IN ('queued', 'running')
                AND NEW.quarantined_at IS NULL;
            IF old_is_active OR new_is_active THEN
                PERFORM provider_sync.lock_feature_update_request_member_scopes(request_uuid);
            END IF;
            IF new_is_active THEN
                PERFORM provider_sync.assert_feature_update_request_members_active(request_uuid);
                PERFORM provider_sync.assert_feature_update_request_membership_available(
                    request_uuid
                );
            END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_feature_update_request_membership_available(
            target_request_id uuid
        ) RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE member_row record;
        BEGIN
            FOR member_row IN
                SELECT provider_dataset_id, sync_scope, operation_key
                FROM ops.feature_update_request_datasets
                WHERE request_id = target_request_id
                ORDER BY provider_dataset_id, sync_scope, operation_key
            LOOP
                PERFORM provider_sync.assert_feature_update_request_member_available(
                    target_request_id,
                    member_row.provider_dataset_id,
                    member_row.sync_scope,
                    member_row.operation_key
                );
            END LOOP;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_feature_update_request_membership_complete()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE target_request_id uuid := COALESCE(NEW.request_id, OLD.request_id);
            mode_value text; member_count bigint;
        BEGIN
            SELECT dataset_membership_mode INTO mode_value
            FROM ops.feature_update_requests WHERE request_id = target_request_id;
            IF NOT FOUND THEN RETURN NULL; END IF;
            SELECT count(*) INTO member_count
            FROM ops.feature_update_request_datasets WHERE request_id = target_request_id;
            IF (mode_value = 'single' AND member_count <> 1)
               OR (mode_value = 'multiple' AND member_count = 0) THEN
                RAISE EXCEPTION 'feature update request membership cardinality does not match mode'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_feature_update_request_membership_complete';
            END IF;
            RETURN NULL;
        END;
        $$;
        """
    )


def _create_indirect_guards() -> None:
    _execute_sql_script(
        """
        CREATE FUNCTION provider_sync.assert_active_notice_lifecycle_scope(scope_id bigint)
        RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM 1 FROM provider_sync.notice_lifecycle_scopes AS scope
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE scope.notice_lifecycle_scope_id = scope_id AND dataset.is_active
            FOR SHARE OF dataset;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive notice lineage writes'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_notice_lifecycle_scope()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.notice_lifecycle_scope_id
                   IS DISTINCT FROM NEW.notice_lifecycle_scope_id THEN
                RAISE EXCEPTION 'notice lineage ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_notice_lineage_ownership_immutable';
            END IF;
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM provider_sync.notice_lifecycle_scopes
                WHERE notice_lifecycle_scope_id = OLD.notice_lifecycle_scope_id
            ) THEN RETURN OLD; END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_notice_lifecycle_scope(
                    OLD.notice_lifecycle_scope_id
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_notice_lifecycle_scope(
                    NEW.notice_lifecycle_scope_id
                );
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_active_curated_source_dataset(source_uuid uuid)
        RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM 1 FROM feature.curated_sources AS source
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = source.provider_dataset_id
            WHERE source.source_id = source_uuid AND dataset.is_active
            FOR SHARE OF dataset;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive curation rule writes'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_curated_source_dataset()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND OLD.source_id IS DISTINCT FROM NEW.source_id THEN
                RAISE EXCEPTION 'curated source ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_curated_source_rule_ownership_immutable';
            END IF;
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM feature.curated_sources WHERE source_id = OLD.source_id
            ) THEN RETURN OLD; END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_curated_source_dataset(OLD.source_id);
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_curated_source_dataset(NEW.source_id);
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_active_integrity_observation_scope(scope_id bigint)
        RETURNS void LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            PERFORM 1 FROM ops.integrity_observation_scopes AS scope
            JOIN provider_sync.provider_datasets AS dataset
              ON dataset.provider_dataset_id = scope.provider_dataset_id
            WHERE scope.integrity_observation_scope_id = scope_id AND dataset.is_active
            FOR SHARE OF dataset;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'inactive provider dataset cannot receive integrity writes'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_provider_dataset_active_write';
            END IF;
        END;
        $$;

        CREATE FUNCTION provider_sync.reject_inactive_integrity_observation_scope()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.integrity_observation_scope_id
                   IS DISTINCT FROM NEW.integrity_observation_scope_id THEN
                RAISE EXCEPTION 'integrity observation ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_integrity_observation_ownership_immutable';
            END IF;
            IF TG_OP = 'DELETE' AND NOT EXISTS (
                SELECT 1 FROM ops.integrity_observation_scopes
                WHERE integrity_observation_scope_id = OLD.integrity_observation_scope_id
            ) THEN RETURN OLD; END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_integrity_observation_scope(
                    OLD.integrity_observation_scope_id
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_integrity_observation_scope(
                    NEW.integrity_observation_scope_id
                );
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;

        CREATE FUNCTION provider_sync.assert_active_source_record_dataset(record_key text)
        RETURNS bigint LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE resolved_dataset_id bigint;
        BEGIN
            IF record_key IS NULL THEN RETURN NULL; END IF;
            SELECT entity.provider_dataset_id INTO resolved_dataset_id
            FROM provider_sync.source_records AS record
            JOIN provider_sync.source_entities AS entity
              ON entity.source_entity_key = record.source_entity_key
            WHERE record.source_record_key = record_key;
            IF NOT FOUND THEN RETURN NULL; END IF;
            PERFORM provider_sync.assert_active_provider_dataset(resolved_dataset_id);
            RETURN resolved_dataset_id;
        END;
        $$;

        CREATE FUNCTION provider_sync.validate_data_integrity_violation_dataset()
        RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE new_record_dataset_id bigint; old_record_dataset_id bigint;
        BEGIN
            IF TG_OP = 'UPDATE'
               AND (OLD.provider_dataset_id, OLD.source_record_key)
                   IS DISTINCT FROM (NEW.provider_dataset_id, NEW.source_record_key) THEN
                RAISE EXCEPTION 'integrity violation ownership is immutable'
                    USING ERRCODE = '23514',
                        CONSTRAINT = 'ck_data_integrity_violation_ownership_immutable';
            END IF;
            IF TG_OP <> 'INSERT' THEN
                PERFORM provider_sync.assert_active_provider_dataset(OLD.provider_dataset_id);
                old_record_dataset_id := provider_sync.assert_active_source_record_dataset(
                    OLD.source_record_key
                );
            END IF;
            IF TG_OP <> 'DELETE' THEN
                PERFORM provider_sync.assert_active_provider_dataset(NEW.provider_dataset_id);
                new_record_dataset_id := provider_sync.assert_active_source_record_dataset(
                    NEW.source_record_key
                );
                IF NEW.provider_dataset_id IS NOT NULL
                   AND new_record_dataset_id IS NOT NULL
                   AND NEW.provider_dataset_id <> new_record_dataset_id THEN
                    RAISE EXCEPTION 'integrity violation dataset must match source record dataset'
                        USING ERRCODE = '23514',
                            CONSTRAINT = 'ck_data_integrity_violations_dataset_source_record';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END;
        $$;
        """
    )


def _create_triggers() -> None:
    _execute_sql_script(
        """
        DROP TRIGGER IF EXISTS trg_provider_dataset_identity_immutable
            ON provider_sync.provider_datasets;
        CREATE TRIGGER trg_provider_dataset_identity_immutable
            BEFORE UPDATE ON provider_sync.provider_datasets
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_provider_dataset_identity_update();
        DROP TRIGGER IF EXISTS trg_provider_dataset_touch ON provider_sync.provider_datasets;
        CREATE TRIGGER trg_provider_dataset_touch
            BEFORE UPDATE ON provider_sync.provider_datasets
            FOR EACH ROW EXECUTE FUNCTION provider_sync.touch_provider_dataset();
        CREATE TRIGGER trg_provider_dataset_operations_active_write
            BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.provider_dataset_operations
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        CREATE TRIGGER trg_provider_dataset_operations_touch
            BEFORE UPDATE ON provider_sync.provider_dataset_operations
            FOR EACH ROW EXECUTE FUNCTION provider_sync.touch_provider_dataset_operation();
        CREATE TRIGGER trg_provider_dataset_operation_scopes_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.provider_dataset_operation_scopes
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();

        CREATE TRIGGER trg_source_entities_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.source_entities
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        CREATE TRIGGER trg_source_entities_identity_and_seen_at
            BEFORE UPDATE ON provider_sync.source_entities
            FOR EACH ROW EXECUTE FUNCTION
                provider_sync.enforce_source_entity_identity_and_seen_at();
        CREATE TRIGGER trg_source_records_immutable
            BEFORE UPDATE ON provider_sync.source_records
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_source_record_update();
        CREATE TRIGGER trg_source_records_active_dataset_write
            BEFORE INSERT OR DELETE ON provider_sync.source_records
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();
        CREATE TRIGGER trg_source_entity_heads_freshness
            BEFORE UPDATE ON provider_sync.source_entity_heads
            FOR EACH ROW EXECUTE FUNCTION provider_sync.enforce_source_entity_head_freshness();
        CREATE TRIGGER trg_source_entity_heads_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.source_entity_heads
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();
        CREATE CONSTRAINT TRIGGER trg_source_records_head_completeness
            AFTER INSERT OR DELETE OR UPDATE ON provider_sync.source_records
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION provider_sync.assert_source_entity_head_completeness();
        CREATE CONSTRAINT TRIGGER trg_source_entity_heads_completeness
            AFTER INSERT OR DELETE OR UPDATE ON provider_sync.source_entity_heads
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION provider_sync.assert_source_entity_head_completeness();
        CREATE TRIGGER trg_source_links_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.source_links
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();

        CREATE TRIGGER trg_provider_sync_state_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.provider_sync_state
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_sync_state_operation();
        CREATE TRIGGER trg_notice_lifecycle_scopes_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.notice_lifecycle_scopes
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        CREATE TRIGGER trg_notice_lineage_states_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON provider_sync.notice_lineage_states
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_notice_lifecycle_scope();
        CREATE TRIGGER trg_curated_sources_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON feature.curated_sources
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        CREATE TRIGGER trg_curated_source_rules_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON feature.curated_source_rules
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_curated_source_dataset();

        CREATE TRIGGER trg_import_job_datasets_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_datasets
            FOR EACH ROW EXECUTE FUNCTION
                provider_sync.reject_inactive_import_job_dataset_membership();
        CREATE CONSTRAINT TRIGGER trg_import_jobs_membership_complete
            AFTER INSERT OR UPDATE OF dataset_membership_mode OR DELETE ON ops.import_jobs
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION provider_sync.assert_import_job_membership_complete();
        CREATE CONSTRAINT TRIGGER trg_import_job_datasets_membership_complete
            AFTER INSERT OR UPDATE OR DELETE ON ops.import_job_datasets
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION provider_sync.assert_import_job_membership_complete();
        CREATE TRIGGER trg_import_jobs_active_member_write
            BEFORE UPDATE OR DELETE ON ops.import_jobs
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_import_job_members();
        CREATE TRIGGER trg_import_job_events_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_events
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_import_job_dataset();

        CREATE TRIGGER trg_feature_update_request_datasets_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.feature_update_request_datasets
            FOR EACH ROW EXECUTE FUNCTION
                provider_sync.reject_inactive_feature_update_request_dataset_membership();
        DROP TRIGGER IF EXISTS trg_feature_update_request_membership_overlap
            ON ops.feature_update_request_datasets;
        CREATE TRIGGER trg_feature_update_request_membership_overlap
            BEFORE INSERT OR UPDATE OF request_id, provider_dataset_id, sync_scope, operation_key
            ON ops.feature_update_request_datasets
            FOR EACH ROW EXECUTE FUNCTION
                provider_sync.reject_active_feature_update_request_member_overlap();
        CREATE CONSTRAINT TRIGGER trg_feature_update_requests_membership_complete
            AFTER INSERT OR UPDATE OF dataset_membership_mode OR DELETE
            ON ops.feature_update_requests DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION provider_sync.assert_feature_update_request_membership_complete();
        CREATE CONSTRAINT TRIGGER trg_feature_update_request_datasets_membership_complete
            AFTER INSERT OR UPDATE OR DELETE ON ops.feature_update_request_datasets
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION provider_sync.assert_feature_update_request_membership_complete();
        CREATE TRIGGER trg_feature_update_requests_active_member_write
            BEFORE UPDATE OR DELETE ON ops.feature_update_requests
            FOR EACH ROW EXECUTE FUNCTION
                provider_sync.reject_inactive_feature_update_request_members();
        DROP TRIGGER IF EXISTS trg_import_jobs_feature_update_activation_overlap
            ON ops.import_jobs;
        CREATE TRIGGER trg_import_jobs_feature_update_activation_overlap
            BEFORE UPDATE OF status, quarantined_at ON ops.import_jobs
            FOR EACH ROW EXECUTE FUNCTION
                provider_sync.reject_feature_update_request_activation_overlap();

        CREATE TRIGGER trg_provider_refresh_policies_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.provider_refresh_policies
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        CREATE TRIGGER trg_offline_uploads_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.offline_uploads
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset_scope();
        CREATE TRIGGER trg_integrity_observation_scopes_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.integrity_observation_scopes
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        CREATE TRIGGER trg_integrity_observation_runs_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.integrity_observation_runs
            FOR EACH ROW EXECUTE FUNCTION
                provider_sync.reject_inactive_integrity_observation_scope();
        CREATE TRIGGER trg_data_integrity_violations_dataset_source_record
            BEFORE INSERT OR UPDATE OR DELETE ON ops.data_integrity_violations
            FOR EACH ROW EXECUTE FUNCTION provider_sync.validate_data_integrity_violation_dataset();
        CREATE TRIGGER trg_poi_cache_target_feature_links_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.poi_cache_target_feature_links
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        CREATE TRIGGER trg_enrichment_review_queue_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.enrichment_review_queue
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_source_entity_dataset();
        CREATE TRIGGER trg_managed_files_active_dataset_write
            BEFORE INSERT OR UPDATE OR DELETE ON ops.managed_files
            FOR EACH ROW EXECUTE FUNCTION provider_sync.reject_inactive_provider_dataset();
        """
    )


def upgrade() -> None:
    _detach_legacy_constraints()
    _replace_pre_tvn33_ownership_guards()
    _rename_runtime_operation_key()
    _freeze_feature_update_operation_memberships()
    _move_notice_lineage_to_head()
    _drop_legacy_columns()
    _rewrite_final_curation_source_rule_trigger()
    _create_dataset_guard_functions()
    _create_lineage_guard_functions()
    _create_membership_guard_functions()
    _create_indirect_guards()
    _create_triggers()


def downgrade() -> None:
    raise RuntimeError("T-VN-33 is forward-only: rebuild the development database from final ETL.")

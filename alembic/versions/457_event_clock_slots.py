"""event clock을 단일 행에서 slot 행 집합으로 — 긴 적재가 다른 event 기록을 막지 않는다.

Revision ID: 457_event_clock_slots
Revises: 456_feature_update_retry

왜 필요한가(감사 ``docs/reports/2026-11-23-collection-failure-audit.md`` §1.2, #1544의 남은 구조
문제).

``ops.import_job_event_clock``은 ``/v1/ops/live``가 import job event의 late commit과 최근 page 밖
UPDATE/DELETE를 놓치지 않으려고 둔 **전역 단일 행** revision이다(0052). event DML statement마다
AFTER STATEMENT trigger가 그 행을 ``revision + 1``로 올리고, 그 row lock은 transaction commit까지
남는다. 그래서 event를 한 줄이라도 쓴 transaction이 길어지면 그동안 **다른 모든** event 기록이 그
행을 기다린다.

prod 실측(n150 Map DB, 읽기 전용): 2026-10-22 한꺼번에 넣은 큐 요청 12건 중 8건이
``LockNotAvailableError: canceling statement due to lock timeout`` + ``INSERT INTO
ops.import_job_events``로 끝났다. 8건 모두 04:55~05:04Z에 claim하자마자 약 30초(Dagster 엔진
``lock_timeout``) 만에 실패했고, 그 창은 04:47:51~06:04:08Z에 76분 동안 refresh transaction을 연
앞 요청 하나와 정확히 겹친다(그 transaction이 04:47:52Z ``job.heartbeat`` event를 쓴 뒤 provider
적재를 같은 transaction에서 이어 갔다).

무엇을 하는가.

- 새 표 ``ops.import_job_event_clock_slots(slot_id identity PK, revision, updated_at)``. event DML
  statement는 여전히 statement마다 정확히 1을 더하지만, **다른 transaction이 잡고 있지 않은 slot**
  (``FOR UPDATE SKIP LOCKED``, 가장 작은 ``slot_id``)에 더한다. 모든 slot이 잡혀 있으면 새 slot을
  만든다 (identity라 unique 충돌·대기가 없다). 그래서 event 기록은 어느 slot에서도 **기다리지
  않는다**.
- 읽는 쪽은 ``SUM(revision)``이다. 값의 의미는 종전 singleton ``revision``과 같다 — "지금
  snapshot에 보이는, commit된 event DML statement 수(+0052 이전 기준값)". revision은 줄지 않고(행
  DELETE·감소 금지), commit된 event statement마다 정확히 1 늘어나므로, 두 snapshot 사이에 event
  transaction이 하나라도 commit하면 합이 반드시 바뀐다. late commit도 그 commit 시점에 합을
  바꾼다. rollback은 slot 증가도 함께 되감는다.
- 옛 singleton 값은 slot 1의 시작 revision으로 옮긴다 — ``event_clock_revision`` 값이 끊기지 않는다.
- slot 수는 "동시에 event를 쓴 transaction 수의 최대"를 넘지 않는다(모두 잡혀 있을 때만 하나
  늘린다). slot은 지우지 않는다(지우면 합이 줄어 변경 감지가 깨진다).
- guard: slot 행은 event AFTER STATEMENT trigger 안에서만(``pg_trigger_depth() >= 2``)
  INSERT(revision 1)· UPDATE(정확히 +1, slot_id 불변)할 수 있고 DELETE·TRUNCATE는 거부한다(0052
  singleton guard와 같은 강도).
- 옛 표·guard 함수·guard trigger는 지운다. ``ops.bump_import_job_event_clock()``은 이름을 유지하고
  본문만 바꾼다 — event 표의 ``trg_import_job_events_clock``은 그대로다.

고른 이유와 버린 후보는 ``docs/architecture/data-model.md`` §9.1.1(event clock)에 있다. 요약:
sequence ``last_value``는 commit 전에 보이고 rollback으로 되감기지 않아 late commit을 놓친다.
event 기록을 적재 transaction 밖(별도 짧은 transaction)으로 빼면 rollback된 적재의 event가 남고,
쓰는 곳 전부를 고쳐야 한다. job별 행으로 나누면 전역 topic(``import_jobs``)이 매 polling마다 전
job을 합해야 한다.

잠금·시간. ``LOCK TABLE ops.import_job_event_clock IN ACCESS EXCLUSIVE MODE``를 먼저 잡아 진행
중인 event transaction(그 행을 쥔 것)이 없을 때만 옮긴다 — 값 이관이 정확해지는 조건이다. 긴
적재가 event를 쓴 채 돌고 있으면 ``lock_timeout`` 1초로 실패한다(데이터 변화 없음). 그때는 적재가
끝난 뒤 다시 올린다. 표는 한 행이라 나머지 문장은 즉시 끝난다. 이 migration이 commit하는 순간 옛
표를 기다리던 event 문장은 사라진 표를 보고 한 번 실패할 수 있다(그 창은 migration 자체의 수
ms이고, 큐 요청은 #1544 재발행이 받는다).

권한. runtime(``ktm_feature_runtime``)은 ``runtime_privileges``가 새 표 이름으로 조정한다(배포
entrypoint가 migration 직후 실행). provider attempt event procedure의 소유자
``ktm_curation_command_owner``는 0211이 옛 표에 준 ``SELECT, INSERT, UPDATE``를 새 표에 그대로
준다. identity 열의 sequence는 INSERT 권한만으로 쓴다(PostgreSQL은 identity의 nextval에 sequence
권한을 따로 묻지 않는다).

receipt head CHECK에 457을 더한다(452~456과 같다).

마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다(alembic_version UPDATE가 그 롤로 돈다 —
RESET ROLE 금지). forward-only — 되돌릴 일이 생기면 forward revision이 singleton을 다시 만든다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "457_event_clock_slots"
down_revision: str | Sequence[str] | None = "456_feature_update_retry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: 진행 중인 event transaction(옛 singleton 행을 쥔 것)이 없을 때만 옮긴다.
_LOCK_OLD_CLOCK_SQL: Final[str] = (
    "LOCK TABLE ops.import_job_event_clock IN ACCESS EXCLUSIVE MODE"
)

_CREATE_SLOTS_SQL: Final[str] = """
CREATE TABLE ops.import_job_event_clock_slots (
    slot_id integer GENERATED ALWAYS AS IDENTITY,
    revision bigint DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT pk_import_job_event_clock_slots PRIMARY KEY (slot_id),
    CONSTRAINT ck_import_job_event_clock_slots_revision_nonnegative CHECK (revision >= 0)
)
"""

#: 옛 singleton 값을 slot 1의 시작값으로. 행이 없던 DB(0052 seed 전)면 0.
_SEED_SLOT_SQL: Final[str] = """
INSERT INTO ops.import_job_event_clock_slots (revision, updated_at)
SELECT COALESCE(MAX(clock.revision), 0), clock_timestamp()
  FROM ops.import_job_event_clock AS clock
"""

_BUMP_FUNCTION_SQL: Final[str] = """
CREATE OR REPLACE FUNCTION ops.bump_import_job_event_clock() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          -- 다른 transaction이 잡지 않은 가장 작은 slot에 1을 더한다. SKIP LOCKED라
          -- 긴 적재 transaction이 slot 하나를 commit까지 쥐어도 기다리지 않는다.
          UPDATE ops.import_job_event_clock_slots AS slot
             SET revision = slot.revision + 1,
                 updated_at = clock_timestamp()
           WHERE slot.slot_id = (
                 SELECT free.slot_id
                   FROM ops.import_job_event_clock_slots AS free
                  ORDER BY free.slot_id
                  LIMIT 1
                    FOR UPDATE SKIP LOCKED
                 );
          IF NOT FOUND THEN
            -- 모든 slot이 다른 transaction에 잡혀 있다. identity라 새 slot은 누구와도
            -- 충돌하지 않는다 — slot 수는 동시 event transaction 수의 최대로 묶인다.
            INSERT INTO ops.import_job_event_clock_slots (revision, updated_at)
            VALUES (1, clock_timestamp());
          END IF;
          RETURN NULL;
        END;
        $$
"""

_GUARD_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION ops.guard_import_job_event_clock_slot_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
            RAISE EXCEPTION 'import job event clock slot cannot be %', TG_OP
              USING ERRCODE = 'check_violation';
          END IF;
          IF pg_trigger_depth() < 2 THEN
            RAISE EXCEPTION 'import job event clock slot is event-trigger-owned: %', TG_OP
              USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.revision IS DISTINCT FROM 1 THEN
              RAISE EXCEPTION
                'import job event clock slot must start at revision 1, not %', NEW.revision
                USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.slot_id IS DISTINCT FROM OLD.slot_id
             OR NEW.revision IS DISTINCT FROM OLD.revision + 1 THEN
            RAISE EXCEPTION
              'import job event clock slot is event-trigger-owned: slot % revision % -> %',
              OLD.slot_id, OLD.revision, NEW.revision
              USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END;
        $$
"""

_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK(destination_head IN (
        '300',
        '301_m03_import_children',
        '302_m03_child_issuance',
        '303_m05_payload_hash_domain',
        '304_m05_detector_manuals',
        '305_m05_relitigation_fence',
        '306_m02_manual_feature_purge',
        '307_m02_truncate_fence',
        '308_t39_provider_identities',
        '309_t39_feature_id_rekey',
        '310_seoul_source_move',
        '311_seal_member_digest',
        '312_route_geometry_sidecar',
        '313_single_service_role',
        '400',
        '401_retire_map_kma_refresh',
        '402_remove_map_weather_data',
        '403_drop_kma_notice_lineage',
        '404_transport_provider_identity',
        '405_mois_freshness_sla',
        '406_feature_write_gate',
        '407_feature_geocode_stamps',
        '408_kor_travel_geo_releases',
        '409_geo_release_item_reasons',
        '410_provider_field_shadow',
        '411_scoped_feature_write_kernel',
        '412_provider_scalar_projection',
        '413_legacy_sql_protocol_entry',
        '414_manual_dedup_protocol',
        '415_state_lifecycle_protocol',
        '416_field_override_protocol',
        '417_protocol_ex_reentry',
        '418_creation_protocol',
        '419_retire_pg_transport_values',
        '420_exclusive_provider_refresh',
        '421_stamp_writer_boundary',
        '422_heritage_evidence_reader',
        '423_exclusive_context_select',
        '424_tracking_protocol_prefix',
        '425_provider_base_update_first',
        '426_provider_patch_protocol',
        '427_transport_airport_reader',
        '428_bounded_curation_capture',
        '429_strict_sh_data_guards',
        '430_provider_snapshot_recovery',
        '431_transport_rest_reader',
        '432_rest_snapshot_atomic',
        '433_snapshot_ready_plan_reset',
        '434_protocol_entry_narrowing',
        '435_retire_sh_snapshot_path',
        '436_feature_search_aliases',
        '437_feature_command_fingerprints',
        '438_transport_reference_places',
        '439_traditional_market_dataset',
        '441_tourapi_attraction_dataset',
        '442_mois_brand_search_aliases',
        '444_trip_search_aliases',
        '446_mcst_place_attributes',
        '447_admin_search_trgm_indexes',
        '448_mcst_theme_transition',
        '449_tourapi_festivals_primary',
        '450_incheon_airport_search_alias',
        '451_feature_search_prominence',
        '452_lotte_hotel_search_alias',
        '453_features_autovacuum',
        '454_route_cluster_markers',
        '455_feature_cluster_points',
        '456_feature_update_retry',
        '457_event_clock_slots'
    ))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(456과 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _LOCK_OLD_CLOCK_SQL,
    _CREATE_SLOTS_SQL,
    _SEED_SLOT_SQL,
    _BUMP_FUNCTION_SQL,
    _GUARD_FUNCTION_SQL,
    # seed 뒤에 guard를 단다 — seed INSERT는 trigger 밖(depth 0)이다.
    "CREATE TRIGGER trg_import_job_event_clock_slots_mutation_guard "
    "BEFORE INSERT OR UPDATE OR DELETE ON ops.import_job_event_clock_slots "
    "FOR EACH ROW EXECUTE FUNCTION ops.guard_import_job_event_clock_slot_mutation()",
    "CREATE TRIGGER trg_import_job_event_clock_slots_truncate_guard "
    "BEFORE TRUNCATE ON ops.import_job_event_clock_slots "
    "FOR EACH STATEMENT EXECUTE FUNCTION ops.guard_import_job_event_clock_slot_mutation()",
    "GRANT SELECT, INSERT, UPDATE ON TABLE ops.import_job_event_clock_slots "
    "TO ktm_curation_command_owner",
    # 옛 singleton과 그 guard. DROP TABLE이 표의 trigger를 함께 지운다.
    "DROP TABLE ops.import_job_event_clock",
    "DROP FUNCTION ops.guard_import_job_event_clock_mutation()",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)
_LOCK_TIMEOUT_MS: Final[int] = 1000
_STATEMENT_TIMEOUT_CAP_MS: Final[int] = 30000


def upgrade() -> None:
    """singleton event clock을 slot 행 집합으로 바꾸고 값을 옮긴다."""
    bind = op.get_bind()
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    }

    def cap(name: str, limit: int) -> None:
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, limit) if prior else limit)},
        )

    cap("statement_timeout", _STATEMENT_TIMEOUT_CAP_MS)
    cap("lock_timeout", _LOCK_TIMEOUT_MS)
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    """되돌리지 않는다 — singleton이 다시 필요하면 forward revision이 만든다."""
    raise RuntimeError(
        "457_event_clock_slots is forward-only: singleton은 forward revision으로만 되살린다."
    )

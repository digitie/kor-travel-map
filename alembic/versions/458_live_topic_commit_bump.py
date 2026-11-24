"""live topic revision을 commit 직전에 올린다 — 긴 transaction이 topic 행을 쥐지 않게 한다.

Revision ID: 458_live_topic_commit_bump
Revises: 457_event_clock_slots

왜 필요한가(#1548 적대 리뷰 실측).

``ops.ops_live_topic_revisions``(``provider_sync``·``dataset_projection``·``dagster_schedules``)는
원본 표 statement trigger가 같은 transaction에서 ``revision + 1``을 upsert하는 topic별 단일
행이다. 그 row lock은 commit까지 남는다. 큐 적재는 executor transaction 하나에 runner
전체(받기·변환·쓰기·꼬리)를 묶으므로, 그 transaction 안에서 topic 원본을 한 번이라도 쓰면 행이
commit까지 잡힌다.

- 쓰기 단계 중간: ``load_bundle``이 bundle마다 ``record_override_geo_stale``을 부르고, 그것이
  ``ops.data_integrity_violations``에 INSERT한다(geo 릴리스 뒤 override가 있는 Feature를 다시
  해석할 때). ``dataset_projection`` 행이 남은 쓰기 내내(큰 적재는 수십 분) 잡힌다.
- 꼬리: 주소 검증 finding 기록(``dataset_projection``) → sync state(``provider_sync``) → stale
  close → executor checkpoint → commit. finding이 한 건이라도 있으면 그 사이 행이 잡힌다.

그동안 PinVi POI target PUT/DELETE(API ``lock_timeout`` 5초 → 503), 다른 큐 요청의 resolve 단계
(``poi_cache_targets`` 갱신, Dagster ``lock_timeout`` 30초 → 재발행), 관리자 issue 쓰기가 막힌다.
실측(리뷰): finding 1건인 적재를 꼬리에서 멈추면 ``topics_held = ['dataset_projection']``이고
resolve 문장이 lock timeout.

무엇을 하는가.

- 새 표 ``ops.ops_live_topic_pending(txid bigint, topic, PK(txid, topic))``. 원본 statement
  trigger (``ops.bump_ops_live_topic_revision(topic)``, 이름·인자 그대로)는 이제 topic 행을
  건드리지 않고 ``(pg_current_xact_id(), topic)``(bigint로 저장 — SQLAlchemy가 ``xid8``을 반영하지
  못한다) 표식을 ``ON CONFLICT DO NOTHING``으로 남긴다. 표식은 transaction·topic마다 하나라 행
  수와 무관하고, 같은 transaction의 표식끼리는 충돌만 하고 기다리지 않는다.
- 표식 표에 ``DEFERRABLE INITIALLY DEFERRED`` constraint
  trigger(``trg_ops_live_topic_pending_apply``)를 건다. commit 직전 deferred 단계에서 이
  transaction의 표식을 **topic 이름 순서로** 모두 적용(``revision + 1``)하고 지운다. 첫 발화가
  전부 처리하므로 나머지 발화는 할 일이 없다. topic 행은 commit 직전부터 commit까지만 잡힌다.
- 표식의 첫 deferred 발화는 표식을 한 번 줄 맨 뒤로 다시 넣는다(``ready``). 그래서 표식이 쓰기
  중간에 생겼어도 그 뒤에 쌓인 다른 deferred 검사(``source_records`` completeness 등, 쓰기 행
  수만큼)가 먼저 돌고 topic 행은 그 뒤에 잡힌다(#1548 재리뷰 실측: 다시 넣지 않으면 3초짜리
  deferred 검사 동안 행이 잡혔다).
- 순서를 고정하므로 commit 단계의 증가끼리 교착하지 않는다(``dagster_schedules`` <
  ``dataset_projection`` < ``provider_sync``).

지키는 것.

- **late commit 감지**: 증가는 commit과 함께 보인다. 먼저 시작해 나중에 commit한 transaction도 그
  commit에서 값을 올린다. rollback이면 표식과 deferred 발화가 함께 사라진다. 값은 이제 statement가
  아니라 "topic을 바꾼 commit 하나당 1"씩 오른다 — reader는 변경 감지에만 쓴다(값 크기는 계약이
  아니다).
- **ADR-065 causal receipt**: POI target PUT/DELETE는 receipt를 읽기 전에 ``SET CONSTRAINTS
  ops.trg_ops_live_topic_pending_apply IMMEDIATE``로 표식을 먼저 적용한다(그 행을 commit까지 쥔다
  — 짧은 API transaction이다). 그래서 receipt보다 큰 값은 그 commit 뒤에만 보인다는 종전 성질이
  그대로다. 읽은 뒤 ``DEFERRED``로 되돌린다.
- 432 snapshot 후처리의 topic 잠금(``_lock_snapshot_postprocess_topic_revisions``)은 435가 SH
  경로와 함께 퇴역시켰다 — 지금 이 행을 미리 잡는 루틴은 없다.

권한. runtime(``ktm_feature_runtime``)에 표식 표 ``SELECT, INSERT, DELETE``를 여기서 직접
준다(457과 같은 이유 — ACL 조정은 별도 process라 그 사이 모든 원본 쓰기가 42501로 실패한다).
조정기 인벤토리에도 같은 이름을 둔다. topic 행 권한은 종전 그대로다.

잠금·시간. 새 표·함수·trigger를 만들고 trigger 함수 본문을 바꾼다. 원본 표 잠금은 잡지
않는다(``CREATE OR REPLACE FUNCTION``). migration 직전에 시작해 아직 commit하지 않은 transaction은
옛 본문으로 이미 topic 행을 올렸을 수 있다 — 그것은 종전처럼 commit에서 끝난다(표식과 섞이지
않는다). receipt head CHECK에 458을 더한다.

마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다. forward-only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "458_live_topic_commit_bump"
down_revision: str | Sequence[str] | None = "457_event_clock_slots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

_CREATE_PENDING_SQL: Final[str] = """
CREATE TABLE ops.ops_live_topic_pending (
    txid bigint NOT NULL,
    topic text NOT NULL,
    ready boolean DEFAULT false NOT NULL,
    CONSTRAINT pk_ops_live_topic_pending PRIMARY KEY (txid, topic),
    CONSTRAINT ck_ops_live_topic_pending_topic
        CHECK (btrim(topic) <> '' AND char_length(topic) <= 100)
)
"""

#: 원본 statement trigger — topic 행 대신 이 transaction의 표식을 남긴다.
_BUMP_FUNCTION_SQL: Final[str] = """
CREATE OR REPLACE FUNCTION ops.bump_ops_live_topic_revision() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
          IF TG_NARGS <> 1 OR btrim(TG_ARGV[0]) = '' THEN
            RAISE EXCEPTION 'ops live revision trigger requires one topic argument';
          END IF;
          -- topic 행은 commit 직전에 올린다(trg_ops_live_topic_pending_apply). 여기서 행을
          -- 올리면 이 transaction이 끝날 때까지 그 topic의 다른 writer가 모두 기다린다.
          INSERT INTO ops.ops_live_topic_pending (txid, topic)
          VALUES (pg_current_xact_id()::text::bigint, TG_ARGV[0])
          ON CONFLICT (txid, topic) DO NOTHING;
          RETURN NULL;
        END;
        $$
"""

#: 표식 적용 — deferred constraint trigger와 ``SET CONSTRAINTS … IMMEDIATE``가 부른다.
_APPLY_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION ops.apply_ops_live_topic_pending() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        DECLARE
          v_txid bigint := pg_current_xact_id()::text::bigint;
          v_topic text;
        BEGIN
          IF NOT NEW.ready THEN
            -- 한 번만 줄 맨 뒤로 보낸다. deferred 발화는 사건 순서라, 표식이 쓰기 중간에
            -- 생겼으면 그 뒤에 쌓인 다른 deferred 검사(쓰기 행 수만큼)가 표식 적용 **뒤에**
            -- 돌며 topic 행을 그만큼 더 쥐게 한다. 다시 넣은 표식의 사건은 그 검사들 뒤에 온다.
            DELETE FROM ops.ops_live_topic_pending AS pending
             WHERE pending.txid = NEW.txid
               AND pending.topic = NEW.topic
               AND NOT pending.ready;
            IF FOUND THEN
              INSERT INTO ops.ops_live_topic_pending (txid, topic, ready)
              VALUES (NEW.txid, NEW.topic, true)
              ON CONFLICT (txid, topic) DO NOTHING;
            END IF;
            RETURN NULL;
          END IF;
          -- 이 transaction의 표식을 topic 이름 순서로 한꺼번에 적용한다. 순서가 고정이라
          -- commit 단계의 증가끼리 교착하지 않는다. 첫 적용이 전부 처리하고 지우므로 같은
          -- transaction의 나머지 발화는 할 일이 없다.
          FOR v_topic IN
            SELECT pending.topic
              FROM ops.ops_live_topic_pending AS pending
             WHERE pending.txid = v_txid
             ORDER BY pending.topic COLLATE "C"
          LOOP
            INSERT INTO ops.ops_live_topic_revisions AS live_revision (
              topic, revision, updated_at
            )
            VALUES (v_topic, 1, clock_timestamp())
            ON CONFLICT (topic) DO UPDATE
            SET revision = live_revision.revision + 1,
                updated_at = clock_timestamp();
          END LOOP;
          DELETE FROM ops.ops_live_topic_pending AS pending
           WHERE pending.txid = v_txid;
          RETURN NULL;
        END;
        $$
"""

_APPLY_TRIGGER_SQL: Final[str] = """
CREATE CONSTRAINT TRIGGER trg_ops_live_topic_pending_apply
    AFTER INSERT ON ops.ops_live_topic_pending
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ops.apply_ops_live_topic_pending()
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
        '457_event_clock_slots',
        '458_live_topic_commit_bump'
    ))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _CREATE_PENDING_SQL,
    _APPLY_FUNCTION_SQL,
    _APPLY_TRIGGER_SQL,
    _BUMP_FUNCTION_SQL,
    # ACL 조정기(별도 process)를 기다리지 않는다 — 이 commit부터 원본 trigger가 표식 표를 쓴다.
    "GRANT SELECT, INSERT, DELETE ON TABLE ops.ops_live_topic_pending "
    "TO ktm_feature_runtime",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)
_LOCK_TIMEOUT_MS: Final[int] = 1000
_STATEMENT_TIMEOUT_CAP_MS: Final[int] = 30000


def upgrade() -> None:
    """원본 trigger가 표식을 남기고, commit 직전에 topic 행을 올리게 한다."""
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
    """되돌리지 않는다 — 종전 trigger 본문이 필요하면 forward revision이 되살린다."""
    raise RuntimeError(
        "458_live_topic_commit_bump is forward-only: forward revision으로만 되돌린다."
    )

"""MCST 테마 목록 전환 장부와 M05 사건의 두 번째 출처(ADR-121 R4).

Revision ID: 447_mcst_theme_transition
Revises: 446_mcst_place_attributes

왜 필요한가. ADR-121 R4는 기존 MCST Feature를 master로 병합(attach·collapse)하거나 퇴역(반려 업종,
retire)시킨다. 퇴역한 Feature를 참조하는 PinVi 행은 M05 사건(``rebind``/``detach``)으로 옮겨야
한다. 그런데 사건 표는 지금 manual-provider dedup 출처만 받는다 — ``case_id``·``resolution_id``가
그 두 표를 가리키는 NOT NULL FK다.

무엇을 하는가.

- ``ops.mcst_theme_transition_batches``·``ops.mcst_theme_transition_items``: 전환 실행 장부.
  batch마다 domain command 하나, item마다 퇴역 transition·병합 이력·되돌림용 전 상태
  (``before_state``). ``feature_id`` UNIQUE라 같은 Feature를 두 번 전환하지 않는다. 런타임은
  SELECT·INSERT만 받는다(고치거나 지우지 않는다).
- 사건 표: ``origin_kind``(``manual_provider_dedup``|``mcst_theme_transition``, 기본값은 앞)와
  출처별 **생성 열** 넷을 더해 출처마다 FK를 건다. ``case_id``·``resolution_id`` 열과 payload
  모양은 그대로다 — MCST 출처는 거기에 batch_id·item_id를 싣는다(PinVi는 불투명 UUID로 쓴다).
  기존 행은 고치지 않는다(생성 열은 표 재작성으로 채워지고 append-only 트리거는 돌지 않는다).
  떨어뜨리는 FK 둘 — ``fk_feature_reference_reconciliation_events_case``와
  ``fk_feature_reference_reconciliation_events_resolution`` — 은 같은 대상·같은
  ``ON DELETE RESTRICT``로 생성 열(``manual_case_ref``·``manual_resolution_ref``) 위에 이름을
  바꿔 다시 건다. manual 출처 행의 참조 무결성은 그대로이고, MCST 출처 행은 장부 FK가 받는다.
- ``feature.record_mcst_theme_transition_event(uuid)``: 사건 writer. M05 procedure owner 소유,
  manual 경로와 같은 잠금·sequence·payload·hash 규칙.
- receipt head CHECK에 447.

잠금. 사건 표 재작성(``ACCESS EXCLUSIVE``, 행 수 작음)과 receipt CHECK. protocol EX를 잡고
``lock_timeout`` 1초·``statement_timeout`` 30초로 묶는다.

forward-only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "447_mcst_theme_transition"
down_revision: str | None = "446_mcst_place_attributes"
branch_labels: str | None = None
depends_on: str | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"
_M05_OWNER: Final[str] = "ktm_manual_provider_dedup_procedure_owner"


def _sidecar(name: str) -> str:
    return Path(__file__).with_name(name).read_text(encoding="utf-8")


_CREATE_BATCHES_SQL: Final[str] = """
CREATE TABLE ops.mcst_theme_transition_batches (
    batch_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    command_id bigint NOT NULL,
    plan_sha256 text NOT NULL,
    rule_version text NOT NULL,
    batch_size integer NOT NULL,
    batch_index integer NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT pk_mcst_theme_transition_batches PRIMARY KEY (batch_id),
    CONSTRAINT uq_mcst_theme_transition_batches_command UNIQUE (command_id),
    CONSTRAINT uq_mcst_theme_transition_batches_plan_index
        UNIQUE (plan_sha256, batch_size, batch_index),
    CONSTRAINT ck_mcst_theme_transition_batches_plan CHECK (
        plan_sha256 ~ '^[0-9a-f]{64}$' AND batch_size > 0 AND batch_index >= 0
        AND rule_version <> ''
    ),
    CONSTRAINT fk_mcst_theme_transition_batches_command
        FOREIGN KEY (command_id) REFERENCES ops.domain_commands (command_id) ON DELETE RESTRICT
)
"""

_CREATE_ITEMS_SQL: Final[str] = """
CREATE TABLE ops.mcst_theme_transition_items (
    item_id uuid DEFAULT x_extension.gen_random_uuid() NOT NULL,
    batch_id uuid NOT NULL,
    feature_id uuid NOT NULL,
    dataset_key text NOT NULL,
    action text NOT NULL,
    target_feature_id uuid,
    old_row_revision bigint NOT NULL,
    transition_id bigint NOT NULL,
    row_revision_after bigint NOT NULL,
    merge_id uuid,
    before_state jsonb NOT NULL,
    evidence jsonb DEFAULT '{}'::jsonb NOT NULL,
    executed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT pk_mcst_theme_transition_items PRIMARY KEY (item_id),
    CONSTRAINT uq_mcst_theme_transition_items_feature UNIQUE (feature_id),
    CONSTRAINT uq_mcst_theme_transition_items_batch_item UNIQUE (batch_id, item_id),
    CONSTRAINT ck_mcst_theme_transition_items_action CHECK (
        action IN ('retire', 'attach', 'collapse')
    ),
    CONSTRAINT ck_mcst_theme_transition_items_target CHECK (
        (action = 'retire') = (target_feature_id IS NULL)
        AND (action = 'retire') = (merge_id IS NULL)
        AND (target_feature_id IS NULL OR target_feature_id <> feature_id)
    ),
    CONSTRAINT ck_mcst_theme_transition_items_revisions CHECK (
        old_row_revision >= 1 AND row_revision_after > old_row_revision
    ),
    CONSTRAINT ck_mcst_theme_transition_items_json CHECK (
        jsonb_typeof(before_state) = 'object' AND jsonb_typeof(evidence) = 'object'
    ),
    CONSTRAINT fk_mcst_theme_transition_items_batch
        FOREIGN KEY (batch_id) REFERENCES ops.mcst_theme_transition_batches (batch_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_mcst_theme_transition_items_feature
        FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE RESTRICT,
    CONSTRAINT fk_mcst_theme_transition_items_target
        FOREIGN KEY (target_feature_id) REFERENCES feature.features (feature_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_mcst_theme_transition_items_transition
        FOREIGN KEY (transition_id) REFERENCES feature.feature_state_transitions (transition_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_mcst_theme_transition_items_merge
        FOREIGN KEY (merge_id) REFERENCES ops.feature_merge_history (merge_id)
        ON DELETE RESTRICT
)
"""

_EVENT_ORIGIN_SQL: Final[str] = """
ALTER TABLE ops.feature_reference_reconciliation_events
    ADD COLUMN origin_kind text DEFAULT 'manual_provider_dedup' NOT NULL,
    ADD COLUMN manual_case_ref uuid GENERATED ALWAYS AS (
        CASE WHEN origin_kind = 'manual_provider_dedup' THEN case_id END
    ) STORED,
    ADD COLUMN manual_resolution_ref uuid GENERATED ALWAYS AS (
        CASE WHEN origin_kind = 'manual_provider_dedup' THEN resolution_id END
    ) STORED,
    ADD COLUMN mcst_batch_ref uuid GENERATED ALWAYS AS (
        CASE WHEN origin_kind = 'mcst_theme_transition' THEN case_id END
    ) STORED,
    ADD COLUMN mcst_item_ref uuid GENERATED ALWAYS AS (
        CASE WHEN origin_kind = 'mcst_theme_transition' THEN resolution_id END
    ) STORED,
    ADD CONSTRAINT ck_feature_reference_reconciliation_events_origin CHECK (
        origin_kind IN ('manual_provider_dedup', 'mcst_theme_transition')
    )
"""

_EVENT_FK_SQL: Final[str] = """
ALTER TABLE ops.feature_reference_reconciliation_events
    DROP CONSTRAINT fk_feature_reference_reconciliation_events_case,
    DROP CONSTRAINT fk_feature_reference_reconciliation_events_resolution,
    ADD CONSTRAINT fk_feature_reference_reconciliation_events_manual_case
        FOREIGN KEY (manual_case_ref) REFERENCES ops.manual_provider_dedup_cases (case_id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT fk_feature_reference_reconciliation_events_manual_resolution
        FOREIGN KEY (manual_resolution_ref)
        REFERENCES ops.manual_provider_dedup_resolutions (resolution_id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT fk_feature_reference_reconciliation_events_mcst_item
        FOREIGN KEY (mcst_batch_ref, mcst_item_ref)
        REFERENCES ops.mcst_theme_transition_items (batch_id, item_id)
        ON DELETE RESTRICT
"""

_OWNER_SQL: Final[tuple[str, ...]] = (
    "ALTER TABLE ops.mcst_theme_transition_batches OWNER TO " + _SCHEMA_OWNER,
    "ALTER TABLE ops.mcst_theme_transition_items OWNER TO " + _SCHEMA_OWNER,
    # 사건 writer(M05 owner)가 장부를 읽는다. 배포 조정기도 같은 grant를 다시 건다.
    "GRANT SELECT ON TABLE ops.mcst_theme_transition_batches, ops.mcst_theme_transition_items, "
    "feature.feature_state_transitions, ops.feature_merge_history TO " + _M05_OWNER,
)

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
        '447_mcst_theme_transition'
    ))
"""
_EVENT_PROCEDURE_SIGNATURE: Final[str] = (
    "feature.record_mcst_theme_transition_event(uuid)"
)

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _CREATE_BATCHES_SQL,
    _CREATE_ITEMS_SQL,
    *_OWNER_SQL,
    _EVENT_ORIGIN_SQL,
    _EVENT_FK_SQL,
    "SET ROLE " + _M05_OWNER,
    _sidecar("_447_record_mcst_theme_transition_event.sql"),
    "REVOKE ALL ON PROCEDURE " + _EVENT_PROCEDURE_SIGNATURE + " FROM PUBLIC",
    "GRANT EXECUTE ON PROCEDURE " + _EVENT_PROCEDURE_SIGNATURE
    + " TO ktm_manual_provider_dedup_admin_executor",
    "SET ROLE " + _SCHEMA_OWNER,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """전환 장부·사건 출처·사건 writer를 만들고 receipt head CHECK에 447을 더한다."""
    bind = op.get_bind()
    prior: dict[str, str] = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings WHERE name IN "
                "('lock_timeout','statement_timeout')"
            )
        ).all()
    }
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        value = int(prior[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(value, cap) if value else cap)},
        )
    bind.execute(text("SET ROLE ktm_feature_state_procedure_owner"))
    bind.execute(text("SELECT ops.lock_scoped_feature_write_protocol(true)"))
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))
    prior_create = bool(
        bind.scalar(
            text("SELECT has_schema_privilege(:role,'feature','CREATE')"),
            {"role": _M05_OWNER},
        )
    )
    if not prior_create:
        bind.execute(text("GRANT CREATE ON SCHEMA feature TO " + _M05_OWNER))
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    if not prior_create:
        bind.execute(text("REVOKE CREATE ON SCHEMA feature FROM " + _M05_OWNER))
    for name, restored in prior.items():
        bind.execute(
            text("SELECT set_config(:name,:value,true)"), {"name": name, "value": restored}
        )
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    """되돌리지 않는다."""
    raise RuntimeError("447_mcst_theme_transition is forward-only")

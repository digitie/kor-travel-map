"""ADR115 기본 OFF shadow 후보 원장. winner/effective·잠금 세분화 활성화는 하지 않는다."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "410_provider_field_shadow"
down_revision: str | None = "409_geo_release_item_reasons"
branch_labels: str | None = None
depends_on: str | None = None

# ruff: noqa: E501
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps', '408_kor_travel_geo_releases', '409_geo_release_item_reasons', '410_provider_field_shadow'))
"""


def _sidecar(routine: str) -> str:
    return Path(__file__).with_name(f"_410_{routine}.sql").read_text(encoding="utf-8")


# 기존406과 같은 실행 tuple: 각 원소는 PG statement 하나이며 역할/receipt lint가
# 실제 실행 순서를 읽는다. 함수 본문은 dollar quote를 보존한 개별 sidecar다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    """-- ADR115: shadow 후보만 기록하며 effective/base/policy 활성 상태는 바꾸지 않는다.
CREATE TABLE feature.provider_field_shadow_policies (
    policy_revision bigint NOT NULL CHECK (policy_revision >= 1),
    provider_dataset_id bigint NOT NULL REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE RESTRICT,
    normalizer_revision text NOT NULL CHECK (normalizer_revision = btrim(normalizer_revision) AND normalizer_revision <> '' AND length(normalizer_revision) <= 128),
    fields jsonb NOT NULL CHECK (jsonb_typeof(fields) = 'array' AND jsonb_array_length(fields) BETWEEN 1 AND 256),
    CONSTRAINT pk_provider_field_shadow_policies PRIMARY KEY (policy_revision, provider_dataset_id)
);
""",
    """ALTER TABLE feature.provider_field_shadow_policies OWNER TO ktm_feature_schema_owner;
""",
    """CREATE INDEX idx_provider_field_shadow_policies_dataset ON feature.provider_field_shadow_policies(provider_dataset_id);

-- 전체 fieldset은 등록 진입점 한 번에 고정한다. 행별 수정 트리거에서 global fence를
-- 기다리면 collector(global -> policy)와 admin(policy -> global)의 순서가 역전된다.
""",
    _sidecar("register_provider_field_shadow_policy"),
    """ALTER PROCEDURE feature.register_provider_field_shadow_policy(bigint,bigint,text,jsonb) OWNER TO ktm_feature_schema_owner;
""",
    """REVOKE ALL ON PROCEDURE feature.register_provider_field_shadow_policy(bigint,bigint,text,jsonb) FROM PUBLIC;
-- 정책 등록은 schema 관리자만 한다. runtime/typed recorder owner에게 EXECUTE를 주지 않는다.
""",
    _sidecar("guard_provider_field_shadow_policy"),
    """ALTER FUNCTION feature.guard_provider_field_shadow_policy() OWNER TO ktm_feature_schema_owner;
""",
    """REVOKE ALL ON FUNCTION feature.guard_provider_field_shadow_policy() FROM PUBLIC;
""",
    """CREATE TRIGGER trg_provider_field_shadow_policy_immutable BEFORE UPDATE OR DELETE
ON feature.provider_field_shadow_policies FOR EACH ROW EXECUTE FUNCTION feature.guard_provider_field_shadow_policy();

""",
    """CREATE TABLE feature.provider_field_shadow_candidates (
    feature_id uuid NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
    policy_revision bigint NOT NULL,
    provider_dataset_id bigint NOT NULL,
    field_path text NOT NULL REFERENCES ops.feature_override_field_paths(field_path) ON DELETE RESTRICT,
    source_entity_key text NOT NULL REFERENCES provider_sync.source_entities(source_entity_key) ON DELETE RESTRICT,
    value_source_record_key text REFERENCES provider_sync.source_records(source_record_key) ON DELETE RESTRICT,
    value_source_hash text,
    validated_source_record_key text NOT NULL REFERENCES provider_sync.source_records(source_record_key) ON DELETE RESTRICT,
    validated_source_hash text NOT NULL CHECK (btrim(validated_source_hash) <> ''),
    value_json jsonb,
    value_geometry x_extension.geometry(Geometry,4326),
    availability text NOT NULL CHECK (availability IN ('value', 'removed', 'unresolved')),
    reason text NOT NULL CHECK (reason IN ('supplied', 'explicit_null', 'omitted_carry', 'omitted_remove', 'missing_initial_value', 'presence_unknown', 'geo_evidence_unsupported')),
    value_observed_at timestamptz,
    validated_at timestamptz NOT NULL,
    normalizer_revision text,
    CONSTRAINT pk_provider_field_shadow_candidates PRIMARY KEY (feature_id, field_path, provider_dataset_id, source_entity_key, policy_revision),
    CONSTRAINT fk_provider_field_shadow_candidates_policy FOREIGN KEY(policy_revision, provider_dataset_id)
        REFERENCES feature.provider_field_shadow_policies(policy_revision, provider_dataset_id) ON DELETE RESTRICT,
    CONSTRAINT ck_provider_field_shadow_candidates_single_value CHECK (value_json IS NULL OR value_geometry IS NULL),
    CONSTRAINT ck_provider_field_shadow_candidates_value CHECK (
        availability <> 'value' OR (value_source_record_key IS NOT NULL AND value_source_hash IS NOT NULL
        AND value_observed_at IS NOT NULL AND (value_json IS NOT NULL OR value_geometry IS NOT NULL))
    ),
    CONSTRAINT ck_provider_field_shadow_candidates_record_hash CHECK (
        (value_source_record_key IS NULL) = (value_source_hash IS NULL)
    )
);
""",
    """ALTER TABLE feature.provider_field_shadow_candidates OWNER TO ktm_feature_schema_owner;
""",
    """CREATE INDEX idx_provider_field_shadow_candidates_policy ON feature.provider_field_shadow_candidates(policy_revision, provider_dataset_id, field_path);
""",
    """CREATE INDEX idx_provider_field_shadow_candidates_entity ON feature.provider_field_shadow_candidates(source_entity_key);
""",
    """CREATE INDEX idx_provider_field_shadow_candidates_value_record ON feature.provider_field_shadow_candidates(value_source_record_key);
""",
    """CREATE INDEX idx_provider_field_shadow_candidates_validated_record ON feature.provider_field_shadow_candidates(validated_source_record_key);

""",
    _sidecar("record_provider_field_candidates"),
    """ALTER PROCEDURE feature.record_provider_field_candidates(uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb) OWNER TO ktm_feature_state_procedure_owner;
""",
    """SET ROLE ktm_feature_state_procedure_owner;
""",
    """REVOKE ALL ON PROCEDURE feature.record_provider_field_candidates(uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb) FROM PUBLIC;
""",
    """GRANT EXECUTE ON PROCEDURE feature.record_provider_field_candidates(uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb) TO ktm_feature_runtime;
""",
    """SET ROLE ktm_feature_schema_owner;
""",
    """GRANT SELECT ON feature.provider_field_shadow_policies TO ktm_feature_state_procedure_owner;
""",
    """GRANT SELECT,INSERT,UPDATE ON feature.provider_field_shadow_candidates TO ktm_feature_state_procedure_owner;
""",
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """기존 짧은 DDL 대기 상한을 보존하고 additive shadow 구조를 만든다."""
    bind = op.get_bind()
    bind.execute(text(_UPGRADE_STATEMENTS[0]))
    settings = dict(
        bind.execute(
            text(
                "SELECT name,setting FROM pg_settings WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    )
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    for statement in _UPGRADE_STATEMENTS[1:]:
        bind.execute(text(statement))
    for name, prior in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": prior})


def downgrade() -> None:
    raise RuntimeError("forward-only migration")

"""ADR115 additive scope kernel. 기존 writer는 아직 이 경로로 전환하지 않는다."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501
revision: str = "411_scoped_feature_write_kernel"
down_revision: str | None = "410_provider_field_shadow"
branch_labels: str | None = None
depends_on: str | None = None


_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity', '405_mois_freshness_sla', '406_feature_write_gate', '407_feature_geocode_stamps', '408_kor_travel_geo_releases', '409_geo_release_item_reasons', '410_provider_field_shadow', '411_scoped_feature_write_kernel'))
"""

def _sidecar(name: str) -> str:
    return Path(__file__).with_name(f"_411_{name}.sql").read_text(encoding="utf-8")


_SCHEMA_STATEMENTS: Final[tuple[str, ...]] = (
    """-- Scope는 coverage 예약일 뿐 Feature identity나 전역 소실 증거가 아니다.
CREATE TABLE ops.feature_write_dataset_scopes (
    provider_dataset_id bigint CONSTRAINT pk_fw_dataset PRIMARY KEY CONSTRAINT fk_fw_dataset_provider REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE RESTRICT,
    epoch bigint NOT NULL DEFAULT 0 CONSTRAINT ck_fw_dataset_epoch CHECK (epoch >= 0),
    owner uuid,
    lease_until timestamptz,
    CONSTRAINT ck_fw_dataset_owner CHECK ((owner IS NULL) = (lease_until IS NULL))
)""",
    """CREATE TABLE ops.feature_write_region_scopes (
    provider_dataset_id bigint NOT NULL CONSTRAINT fk_fw_region_dataset REFERENCES ops.feature_write_dataset_scopes(provider_dataset_id) ON DELETE RESTRICT,
    scope_version integer NOT NULL CONSTRAINT ck_fw_region_version CHECK (scope_version > 0),
    region_key text COLLATE "C" NOT NULL CONSTRAINT ck_fw_region_key CHECK (region_key ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    epoch bigint NOT NULL DEFAULT 0 CONSTRAINT ck_fw_region_epoch CHECK (epoch >= 0),
    owner uuid,
    lease_until timestamptz,
    CONSTRAINT pk_fw_region PRIMARY KEY (provider_dataset_id, scope_version, region_key),
    CONSTRAINT ck_fw_region_owner CHECK ((owner IS NULL) = (lease_until IS NULL))
)""",
    """CREATE INDEX idx_feature_write_region_scopes_lease ON ops.feature_write_region_scopes(lease_until, provider_dataset_id) WHERE owner IS NOT NULL""",
    """CREATE TABLE ops.feature_write_attempts (
    attempt_id uuid CONSTRAINT pk_fw_attempt PRIMARY KEY,
    provider_dataset_id bigint NOT NULL CONSTRAINT fk_fw_attempt_dataset REFERENCES ops.feature_write_dataset_scopes(provider_dataset_id) ON DELETE RESTRICT,
    idempotency_key text COLLATE "C" NOT NULL CONSTRAINT ck_fw_attempt_key CHECK (idempotency_key ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    owner uuid NOT NULL,
    dataset_epoch bigint NOT NULL CONSTRAINT ck_fw_attempt_epoch CHECK (dataset_epoch >= 0),
    region_epochs bigint[] NOT NULL,
    regions jsonb NOT NULL CONSTRAINT ck_fw_attempt_regions CHECK (jsonb_typeof(regions) = 'array' AND jsonb_array_length(regions) <= 256 AND cardinality(region_epochs)=jsonb_array_length(regions)),
    exclusive_protocol boolean NOT NULL,
    input_digest text COLLATE "C" NOT NULL CONSTRAINT ck_fw_attempt_input CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    expected_members integer NOT NULL CONSTRAINT ck_fw_attempt_members CHECK (expected_members BETWEEN 0 AND 8192),
    manifest_digest text COLLATE "C",
    status text COLLATE "C" NOT NULL DEFAULT 'preparing' CONSTRAINT ck_fw_attempt_status CHECK (status IN ('preparing','ready','applying','completed','cancelled')),
    apply_txid bigint,
    result_digest text COLLATE "C",
    lease_until timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_fw_attempt_idempotency UNIQUE (provider_dataset_id, idempotency_key),
    CONSTRAINT ck_fw_attempt_manifest CHECK (manifest_digest IS NULL OR manifest_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_fw_attempt_result CHECK (result_digest IS NULL OR result_digest ~ '^[0-9a-f]{64}$')
)""",
    """CREATE INDEX idx_feature_write_attempts_terminal ON ops.feature_write_attempts(updated_at, attempt_id) WHERE status IN ('completed','cancelled')""",
    """CREATE INDEX idx_feature_write_attempts_expired ON ops.feature_write_attempts(lease_until, provider_dataset_id) WHERE status IN ('preparing','ready','applying')""",
    """CREATE TABLE ops.feature_write_manifests (
    attempt_id uuid NOT NULL CONSTRAINT fk_fw_manifest_attempt REFERENCES ops.feature_write_attempts(attempt_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CONSTRAINT ck_fw_manifest_ordinal CHECK (ordinal BETWEEN 0 AND 8191),
    dependency_kind text COLLATE "C" NOT NULL CONSTRAINT ck_fw_manifest_kind CHECK (dependency_kind IN ('feature','source_head')),
    dependency_key text COLLATE "C" NOT NULL CONSTRAINT ck_fw_manifest_key CHECK (octet_length(dependency_key) BETWEEN 1 AND 128),
    expected_value text COLLATE "C" NOT NULL CONSTRAINT ck_fw_manifest_expected CHECK (octet_length(expected_value) BETWEEN 1 AND 128),
    member_digest text COLLATE "C" NOT NULL CONSTRAINT ck_fw_manifest_digest CHECK (member_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT pk_fw_manifest PRIMARY KEY (attempt_id, ordinal),
    CONSTRAINT uq_fw_manifest_dependency UNIQUE (attempt_id, dependency_kind, dependency_key)
)""",
    """-- 직접 DML은 runtime에 열지 않는다. 후속 reconcile inventory에도 동일 권한을 선언해야 한다.
REVOKE ALL ON ops.feature_write_dataset_scopes, ops.feature_write_region_scopes, ops.feature_write_attempts, ops.feature_write_manifests FROM PUBLIC, ktm_feature_runtime""",
    """GRANT SELECT,INSERT,UPDATE,DELETE ON ops.feature_write_dataset_scopes, ops.feature_write_region_scopes, ops.feature_write_attempts, ops.feature_write_manifests TO ktm_feature_state_procedure_owner""",
)

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    *_SCHEMA_STATEMENTS,
    "GRANT CREATE ON SCHEMA ops TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("scoped_feature_write_protocol"),
    "ALTER FUNCTION ops.lock_scoped_feature_write_protocol(boolean) OWNER TO ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean) FROM PUBLIC",
    "SET ROLE ktm_feature_state_procedure_owner",
    "GRANT EXECUTE ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean) TO ktm_feature_runtime",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("arm_deadline"),
    "ALTER FUNCTION ops._arm_scoped_feature_write_deadline() OWNER TO ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops._arm_scoped_feature_write_deadline() FROM PUBLIC",
    _sidecar("lock_scope"),
    "ALTER FUNCTION ops._lock_scoped_feature_write_scope(bigint,jsonb,boolean) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops._lock_scoped_feature_write_scope(bigint,jsonb,boolean) FROM PUBLIC",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("locked_attempt"),
    "ALTER FUNCTION ops._locked_scoped_feature_write_attempt(uuid,uuid) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops._locked_scoped_feature_write_attempt(uuid,uuid) FROM PUBLIC",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("claim"),
    "ALTER FUNCTION ops.claim_scoped_feature_write(uuid,uuid,bigint,text,jsonb,text,integer,integer,boolean) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.claim_scoped_feature_write(uuid,uuid,bigint,text,jsonb,text,integer,integer,boolean) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.claim_scoped_feature_write(uuid,uuid,bigint,text,jsonb,text,integer,integer,boolean) TO ktm_feature_runtime",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("append_manifest"),
    "ALTER FUNCTION ops.append_scoped_feature_write_manifest(uuid,uuid,jsonb) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.append_scoped_feature_write_manifest(uuid,uuid,jsonb) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.append_scoped_feature_write_manifest(uuid,uuid,jsonb) TO ktm_feature_runtime",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("seal_manifest"),
    "ALTER FUNCTION ops.seal_scoped_feature_write_manifest(uuid,uuid) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.seal_scoped_feature_write_manifest(uuid,uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.seal_scoped_feature_write_manifest(uuid,uuid) TO ktm_feature_runtime",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("begin_attempt"),
    "ALTER FUNCTION ops.begin_scoped_feature_write(uuid,uuid,text) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.begin_scoped_feature_write(uuid,uuid,text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.begin_scoped_feature_write(uuid,uuid,text) TO ktm_feature_runtime",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("finish_attempt"),
    "ALTER FUNCTION ops.finish_scoped_feature_write(uuid,uuid,text) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.finish_scoped_feature_write(uuid,uuid,text) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.finish_scoped_feature_write(uuid,uuid,text) TO ktm_feature_runtime",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("cancel_attempt"),
    "ALTER FUNCTION ops.cancel_scoped_feature_write(uuid,uuid) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.cancel_scoped_feature_write(uuid,uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.cancel_scoped_feature_write(uuid,uuid) TO ktm_feature_runtime",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("prune_attempts"),
    "ALTER FUNCTION ops.prune_scoped_feature_write_attempts(timestamp with time zone,integer) OWNER TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.prune_scoped_feature_write_attempts(timestamp with time zone,integer) FROM PUBLIC",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("expire_attempt"),
    "ALTER FUNCTION ops.expire_scoped_feature_write_attempt(uuid) OWNER TO ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.expire_scoped_feature_write_attempt(uuid) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops.expire_scoped_feature_write_attempt(uuid) TO ktm_feature_runtime",
    _sidecar("guard_apply_completion"),
    "ALTER FUNCTION ops._guard_scoped_feature_write_completion() OWNER TO ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops._guard_scoped_feature_write_completion() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION ops._guard_scoped_feature_write_completion() TO ktm_feature_schema_owner",
    "SET ROLE ktm_feature_schema_owner",
    "CREATE CONSTRAINT TRIGGER trg_fw_attempt_complete AFTER INSERT OR UPDATE ON ops.feature_write_attempts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ops._guard_scoped_feature_write_completion()",
    "SET ROLE ktm_feature_state_procedure_owner",
    "REVOKE EXECUTE ON FUNCTION ops._guard_scoped_feature_write_completion() FROM ktm_feature_schema_owner",
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_CHECK_SQL,
    "RESET ROLE",
)


def upgrade() -> None:
    bind = op.get_bind()
    prior_create = bool(
        bind.scalar(
            text("SELECT has_schema_privilege('ktm_feature_state_procedure_owner','ops','CREATE')")
        )
    )
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
    if not prior_create:
        bind.execute(text("SET ROLE ktm_feature_schema_owner"))
        bind.execute(text("REVOKE CREATE ON SCHEMA ops FROM ktm_feature_state_procedure_owner"))
        bind.execute(text("RESET ROLE"))
    for name, prior in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": prior})
    # Alembic의 version 표 쓰기는 원래 schema owner 창에서 계속해야 한다.
    # ops CREATE 임시 권한을 회수하며 RESET ROLE한 상태를 밖으로 누출하지 않는다.
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")

"""ADR115 name/phones 후보의 원자적 활성화·투영. 운영 정책은 seed하지 않는다."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "412_provider_scalar_projection"
down_revision: str | None = "411_scoped_feature_write_kernel"
branch_labels: str | None = None
depends_on: str | None = None


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
        '412_provider_scalar_projection'
    ))
"""


def _sidecar(name: str) -> str:
    return Path(__file__).with_name(f"_412_{name}.sql").read_text(encoding="utf-8")


_SCHEMA_STATEMENTS: Final[tuple[str, ...]] = (
    """CREATE TABLE feature.provider_field_policy_epoch (
        singleton boolean CONSTRAINT pk_pfp_epoch PRIMARY KEY DEFAULT true
            CONSTRAINT ck_pfp_singleton CHECK(singleton),
        epoch bigint NOT NULL DEFAULT 0 CONSTRAINT ck_pfp_epoch CHECK(epoch >= 0)
    )""",
    "INSERT INTO feature.provider_field_policy_epoch(singleton,epoch) VALUES (true,0)",
    """CREATE TABLE feature.provider_field_active_policies (
        feature_id uuid CONSTRAINT pk_pfp_active PRIMARY KEY
            CONSTRAINT fk_pfp_active_feature REFERENCES feature.features(feature_id)
            ON DELETE RESTRICT,
        policy_revision bigint NOT NULL CONSTRAINT ck_pfp_active_revision
            CHECK(policy_revision >= 1),
        field_paths text[] NOT NULL CONSTRAINT ck_pfp_active_fields CHECK(field_paths IN (
            ARRAY['core.name']::text[], ARRAY['place.phones']::text[],
            ARRAY['core.name','place.phones']::text[]
        ))
    )""",
    """REVOKE ALL ON feature.provider_field_policy_epoch,
        feature.provider_field_active_policies FROM PUBLIC,ktm_feature_runtime""",
    """GRANT SELECT,UPDATE ON feature.provider_field_policy_epoch
        TO ktm_feature_state_procedure_owner""",
    """GRANT SELECT,INSERT,UPDATE ON feature.provider_field_active_policies
        TO ktm_feature_state_procedure_owner""",
)


def _replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError("410 typed recorder 변경을 검토한 뒤 412 변환을 갱신해야 합니다.")
    return source.replace(old, new, 1)


def _record_core_sql() -> str:
    # 검토한 410 validation의 단일 정본을 재사용한다. 일반 문자열 전체 치환은 하지 않는다.
    source = (
        Path(__file__)
        .with_name("_410_record_provider_field_candidates.sql")
        .read_text(encoding="utf-8")
    )
    source = _replace_once(
        source,
        "CREATE PROCEDURE feature.record_provider_field_candidates(\n",
        "CREATE PROCEDURE feature._record_provider_field_candidates(\n    IN p_attempt uuid,\n",
    )
    return _replace_once(
        source,
        "    PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));",
        """    IF p_attempt IS NULL THEN
        PERFORM ops.lock_scoped_feature_write_protocol(true);
        PERFORM feature.lock_provider_field_policy_epoch();
        PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write',0));
        IF EXISTS (SELECT 1 FROM feature.provider_field_active_policies
            WHERE feature_id=p_feature_id) THEN
            RAISE EXCEPTION 'active scalar Feature requires scoped capture' USING ERRCODE='23514';
        END IF;
    ELSE
        PERFORM feature.assert_scoped_provider_scalar_target(
            p_attempt,p_feature_id,p_provider_dataset_id,p_source_entity_key,p_policy_revision);
    END IF;""",
    )


# runtime은 명시 entry만 호출한다. activate와 private core는 공개하지 않는다.
_ROUTINES: Final[tuple[tuple[str, str, bool], ...]] = (
    ("FUNCTION", "feature.lock_provider_field_policy_epoch()", True),
    ("FUNCTION", "feature.provider_field_policy_statement_barrier()", False),
    ("FUNCTION", "feature.assert_scoped_candidate_write(uuid,uuid)", False),
    (
        "FUNCTION",
        "feature.assert_scoped_provider_scalar_target(uuid,uuid,bigint,text,bigint)",
        True,
    ),
    ("FUNCTION", "feature.provider_field_scalar_winners(uuid,bigint,text[])", False),
    (
        "PROCEDURE",
        "feature._record_provider_field_candidates(uuid,uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb)",
        False,
    ),
    (
        "PROCEDURE",
        "feature.record_provider_field_candidates(uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb)",
        True,
    ),
    (
        "PROCEDURE",
        "feature.record_scoped_provider_field_candidates(uuid,uuid,bigint,text,text,bigint,text,boolean,jsonb,jsonb)",
        True,
    ),
    ("FUNCTION", "feature._project_provider_field_candidates(uuid)", False),
    ("PROCEDURE", "feature.recompute_provider_field_candidates(uuid,uuid,bigint)", True),
    ("PROCEDURE", "feature.activate_provider_field_policy(uuid,bigint,text[])", False),
    ("FUNCTION", "feature.validate_active_provider_base_field_value()", False),
    ("FUNCTION", "feature._assert_provider_field_projection(uuid)", False),
    ("FUNCTION", "feature.guard_provider_field_projection()", False),
    ("FUNCTION", "feature._provider_field_projection_dependency_active(text,text)", True),
    ("FUNCTION", "feature.reject_unsupported_active_scalar_mutation()", False),
)
_BARRIER_TABLES: Final[tuple[str, ...]] = (
    "feature.features",
    "feature.feature_places",
    "feature.feature_geocode_stamps",
    "feature.feature_base_field_values",
    "feature.provider_field_shadow_candidates",
    "provider_sync.source_links",
    "provider_sync.source_entities",
    "provider_sync.source_entity_heads",
    "provider_sync.provider_datasets",
    "ops.feature_overrides",
)
_REJECT_TABLES: Final[tuple[str, ...]] = (
    "feature.features",
    "feature.feature_places",
    "feature.feature_geocode_stamps",
    "provider_sync.source_links",
    "provider_sync.source_entities",
    "provider_sync.provider_datasets",
    "ops.feature_overrides",
)
_TRIGGER_FUNCTIONS: Final[tuple[str, ...]] = (
    "feature.provider_field_policy_statement_barrier()",
    "feature.guard_provider_field_projection()",
    "feature.reject_unsupported_active_scalar_mutation()",
)
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    *_SCHEMA_STATEMENTS,
    "GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner",
    "SET ROLE ktm_feature_state_procedure_owner",
    _sidecar("lock_provider_field_policy_epoch"),
    _sidecar("provider_field_policy_statement_barrier"),
    _sidecar("assert_scoped_candidate_write"),
    _sidecar("assert_scoped_provider_scalar_target"),
    _sidecar("provider_field_scalar_winners"),
    _record_core_sql(),
    _sidecar("legacy_record_wrapper"),
    _sidecar("scoped_record_wrapper"),
    _sidecar("_project_provider_field_candidates"),
    _sidecar("recompute_provider_field_candidates"),
    _sidecar("activate_provider_field_policy"),
    _sidecar("validate_feature_base_field_value"),
    _sidecar("_assert_provider_field_projection"),
    _sidecar("guard_provider_field_projection"),
    _sidecar("projection_dependency_active"),
    _sidecar("reject_unsupported_active_scalar_mutation"),
    *(
        f"REVOKE ALL ON {kind} {signature} FROM PUBLIC,ktm_feature_runtime"
        for kind, signature, _ in _ROUTINES
    ),
    *(
        f"GRANT EXECUTE ON {kind} {signature} TO ktm_feature_runtime"
        for kind, signature, public in _ROUTINES
        if public
    ),
    # 등록은 runtime에 열지 않는다. schema 관리자는 명시적인 격리 검증에만 사용한다.
    "GRANT EXECUTE ON PROCEDURE feature.activate_provider_field_policy(uuid,bigint,text[]) "
    "TO ktm_feature_schema_owner",
    # 이 권한은 private installer의 CREATE TRIGGER 검증에만 필요하다.
    *(
        f"GRANT EXECUTE ON FUNCTION {signature} TO ktm_feature_schema_owner"
        for signature in (
            *_TRIGGER_FUNCTIONS,
            "feature._provider_field_projection_dependency_active(text,text)",
            "feature.validate_active_provider_base_field_value()",
        )
    ),
    "SET ROLE ktm_feature_schema_owner",
    _sidecar("install_projection_guards"),
    "REVOKE ALL ON FUNCTION feature._install_provider_field_projection_guards() "
    "FROM PUBLIC,ktm_feature_runtime",
    "GRANT EXECUTE ON FUNCTION feature._install_provider_field_projection_guards() "
    "TO ktm_feature_state_procedure_owner",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE ktm_feature_schema_owner",
)


def upgrade() -> None:
    bind = op.get_bind()
    prior_create = bool(
        bind.scalar(
            text(
                "SELECT has_schema_privilege("
                "'ktm_feature_state_procedure_owner','feature','CREATE')"
            )
        )
    )
    settings = dict(
        bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    )
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    if not prior_create:
        bind.execute(text("SET ROLE ktm_feature_schema_owner"))
        bind.execute(text("REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner"))
        bind.execute(text("RESET ROLE"))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE ktm_feature_schema_owner"))


def downgrade() -> None:
    raise RuntimeError("forward-only migration")

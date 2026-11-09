"""TourAPI 관광지(contentTypeId 12) dataset을 provider 카탈로그에 넣는다(#1459).

Revision ID: 441_tourapi_attraction_dataset
Revises: 439_traditional_market_dataset

왜 필요한가. 운영 Map에 산막이옛길·고군산군도·부산타워·광안대교·아부오름 같은 대표 관광지가
없다(#1459). 원천은 한국관광공사 국문 관광정보 서비스(KorService2, 공공데이터포털 15101578)
``areaBasedList2``의 관광지 목록이다. **실행 가능 집합의 정본은 DB 카탈로그다**(T-VN-33,
ADR-088): 코드에 handler만 두면 큐와 ``POST /ops/pipeline/requests``가 그 dataset을 모른다.
그래서 dataset·operation·scope 행을 여기서 넣는다(439와 같은 모양).

번호. 440은 MOIS 숙박 PR이 예약했다 — 이 revision은 441이고 439 뒤에 선다. 440이 먼저
머지되면 ``down_revision``을 440으로 옮기고 아래 CHECK에 440을 더한다.

무엇을 하는가(실행 순서 = ``_UPGRADE_STATEMENTS``)
--------------------------------------------------

1. ``python-visitkorea-api`` / ``visitkorea_tourist_attractions`` dataset(``openapi``, 활성).
2. ``refresh`` operation ``feature_place_visitkorea_tourist_attractions_job``(= Dagster job 이름)과
   fixture ``preview`` operation, ``dataset_wide`` operation scope.
3. receipt head CHECK에 이 revision을 더한다.

막는 것(preflight): 같은 dataset이 이미 있으면(일부만 적용된 DB) 아무것도 바꾸지 않고 중단한다.

forward-only. downgrade는 두지 않는다(ADR-021).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "441_tourapi_attraction_dataset"
down_revision: str | Sequence[str] | None = "439_traditional_market_dataset"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: migration은 import 시점 앱 코드에 기대지 않으므로 값을 여기 둔다
#: (``kortravelmap.providers.visitkorea_attractions.DATASET_KEY_VISITKOREA_ATTRACTIONS``·
#: ``feature_operation_registry``와 같은 값).
PROVIDER: Final[str] = "python-visitkorea-api"
DATASET_KEY: Final[str] = "visitkorea_tourist_attractions"
DISPLAY_NAME: Final[str] = "TourAPI 관광지(국문 관광정보 서비스, contentTypeId 12)"
OPERATION_KEY: Final[str] = "feature_place_visitkorea_tourist_attractions_job"

_DATASET_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = '{PROVIDER}' AND dataset.dataset_key = '{DATASET_KEY}'
"""

_INSERT_DATASET_SQL: Final[str] = (
    "INSERT INTO provider_sync.provider_datasets (provider, dataset_key, display_name, source_kind, is_active, capabilities) VALUES "
    f"('{PROVIDER}', '{DATASET_KEY}', '{DISPLAY_NAME}', 'openapi', true, "
    """'{"produces": ["place"], "extensions": {}, "schema_version": 1}'::jsonb)"""
)

_INSERT_OPERATIONS_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_dataset_operations (provider_dataset_id, operation_key, operation_kind, is_enabled, config)
SELECT dataset.provider_dataset_id, '{OPERATION_KEY}', 'refresh', true, '{{}}'::jsonb
  FROM ({_DATASET_SQL}) AS dataset
UNION ALL
SELECT dataset.provider_dataset_id, '{OPERATION_KEY}.preview', 'preview', true, '{{"handler": "fixture"}}'::jsonb
  FROM ({_DATASET_SQL}) AS dataset
"""

_INSERT_OPERATION_SCOPES_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_dataset_operation_scopes (provider_dataset_id, sync_scope, operation_key, operation_kind)
SELECT dataset.provider_dataset_id, 'dataset_wide', '{OPERATION_KEY}', 'refresh'
  FROM ({_DATASET_SQL}) AS dataset
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
        '441_tourapi_attraction_dataset'
    ))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _INSERT_DATASET_SQL,
    _INSERT_OPERATIONS_SQL,
    _INSERT_OPERATION_SCOPES_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """TourAPI 관광지 dataset·operation·scope를 넣고 receipt head를 허용한다."""
    bind = op.get_bind()
    existing = bind.execute(text(_DATASET_SQL)).first()
    if existing is not None:
        raise RuntimeError(
            f"441_tourapi_attraction_dataset: {PROVIDER}/{DATASET_KEY}가 이미 있다 "
            f"(provider_dataset_id={existing[0]}) — 일부만 적용된 DB다. 사람이 확인한 뒤 다시 돌린다."
        )
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    }
    for name, cap in (("lock_timeout", 1000), ("statement_timeout", 30000)):
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, cap) if prior else cap)},
        )
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    raise RuntimeError("441_tourapi_attraction_dataset is forward-only")

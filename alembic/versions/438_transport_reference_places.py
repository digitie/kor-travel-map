"""transport 철도역·항구 기준정보를 place dataset으로 카탈로그에 넣는다(ADR-120).

Revision ID: 438_transport_reference_places
Revises: 437_feature_command_fingerprints

왜 필요한가. 2026-11-08 PinVi 여행 시나리오 검증(#1459)에서 기차역·여객선 터미널·휴게소가 Map
검색에 거의 나오지 않았다. 소유자 결정(2026-11-09): Map이 이미 소비하는 kor-travel-transport의
기준정보로 채운다. 철도역(``/v1/service/exports/rail-stations``)·항구(``/ferry-ports``)는 새
dataset이다. **실행 가능 집합의 정본은 DB 카탈로그다**(T-VN-33, ADR-088) — 코드에만 job을 두면
큐가 handler 없는 dataset을 모르고, 카탈로그에만 두면 handler 없는 key를 받는다. 404가
transport dataset 여섯을 넣은 모양과 같다.

무엇을 하는가(실행 순서 = ``_UPGRADE_STATEMENTS``)
--------------------------------------------------

1. 소유자 롤 창을 연다.
2. ``kor-travel-transport``(``source_kind=internal``) dataset 둘을 넣는다.
3. dataset마다 ``refresh`` operation(= Dagster job 이름)과 fixture ``preview`` operation,
   ``dataset_wide`` operation scope를 넣는다.
4. receipt head CHECK에 이 revision을 더한다.
5. 같은 소유자 롤로 끝난다(alembic의 ``UPDATE alembic_version``이 산다).

데이터 행(Feature)은 만들지 않는다 — 첫 적재는 Dagster job이 한다. 새 dataset이 이미 있으면
(일부만 적용된 DB) ``INSERT``가 ``uq_provider_datasets_identity``로 실패해 아무것도 바꾸지 않는다.

forward-only. downgrade는 두지 않는다(ADR-021).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "438_transport_reference_places"
down_revision: str | Sequence[str] | None = "437_feature_command_fingerprints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSPORT_PROVIDER: Final[str] = "kor-travel-transport"
_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: (dataset_key, 표시 이름, refresh operation key). migration은 import 시점 앱 코드에 기대지
#: 않으므로 값을 여기 둔다(``kortravelmap.providers.kor_travel_transport``·
#: ``feature_operation_registry``와 같은 값 — 통합 테스트가 대조한다).
NEW_DATASETS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "transport_rail_stations",
        "도시·광역철도 역 (place Feature, kor-travel-transport)",
        "feature_place_transport_rail_stations_job",
    ),
    (
        "transport_ferry_ports",
        "여객선 항구 (place Feature, kor-travel-transport)",
        "feature_place_transport_ferry_ports_job",
    ),
)

_INSERT_DATASETS_SQL: Final[str] = (
    "INSERT INTO provider_sync.provider_datasets "
    "(provider, dataset_key, display_name, source_kind, is_active, capabilities) VALUES "
    + ", ".join(
        f"('{TRANSPORT_PROVIDER}', '{dataset_key}', '{label}', 'internal', true, "
        "'{\"produces\": [\"place\"], \"extensions\": {}, \"schema_version\": 1}'::jsonb)"
        for dataset_key, label, _ in NEW_DATASETS
    )
)

_NEW_OPERATIONS_VALUES: Final[str] = ", ".join(
    f"('{dataset_key}', '{job}')" for dataset_key, _, job in NEW_DATASETS
)

_INSERT_OPERATIONS_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_dataset_operations
    (provider_dataset_id, operation_key, operation_kind, is_enabled, config)
SELECT dataset.provider_dataset_id, new.operation_key, 'refresh', true, '{{}}'::jsonb
  FROM (VALUES {_NEW_OPERATIONS_VALUES}) AS new(dataset_key, operation_key)
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider = '{TRANSPORT_PROVIDER}' AND dataset.dataset_key = new.dataset_key
UNION ALL
SELECT dataset.provider_dataset_id, new.operation_key || '.preview', 'preview', true,
       '{{"handler": "fixture"}}'::jsonb
  FROM (VALUES {_NEW_OPERATIONS_VALUES}) AS new(dataset_key, operation_key)
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider = '{TRANSPORT_PROVIDER}' AND dataset.dataset_key = new.dataset_key
"""

_INSERT_OPERATION_SCOPES_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_dataset_operation_scopes
    (provider_dataset_id, sync_scope, operation_key, operation_kind)
SELECT dataset.provider_dataset_id, 'dataset_wide', new.operation_key, 'refresh'
  FROM (VALUES {_NEW_OPERATIONS_VALUES}) AS new(dataset_key, operation_key)
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider = '{TRANSPORT_PROVIDER}' AND dataset.dataset_key = new.dataset_key
"""

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
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
        '438_transport_reference_places'
    ))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _INSERT_DATASETS_SQL,
    _INSERT_OPERATIONS_SQL,
    _INSERT_OPERATION_SCOPES_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)


def upgrade() -> None:
    """dataset·operation·scope 행과 receipt head를 잠금/문장 제한 안에서 넣는다."""
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
    raise RuntimeError("438_transport_reference_places is forward-only")

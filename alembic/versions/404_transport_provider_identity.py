"""OpiNet·KREX·공항 적재의 provider 정체성을 ``kor-travel-transport``로 옮긴다(ADR-106).

Revision ID: 404_transport_provider_identity
Revises: 403_drop_kma_notice_lineage

왜 필요한가. 2026-10-02 소유자 결정으로 Map은 OpiNet 주유소·유가, 한국도로공사 휴게소·휴게소
유가·고속도로 돌발, 공항 메타데이터를 provider 라이브러리로 직접 받지 않고
kor-travel-transport의 ``/v1/service/exports/*``에서 받는다. 원천이 바뀌었으므로 provider
정체성도 ``kor-travel-transport``(``source_kind=internal``)로 새로 둔다 — kor-travel-concierge
export와 같은 부류다. **실행 가능 집합의 정본은 DB 카탈로그다**(T-VN-33, ADR-088): 코드만
바꾸면 옛 operation이 카탈로그에 enabled로 남아 큐가 handler 없는 key를 받는다.

무엇을 하는가(실행 순서 = ``_UPGRADE_STATEMENTS``)
--------------------------------------------------

0. 함수 소유자 롤 창을 연다(403과 같다 — 계보 함수 ``CREATE OR REPLACE``가 필요로 한다).
1. 새 dataset 여섯을 넣는다. 옛 dataset과의 대응은 :data:`DATASET_MOVES`가 정본이다.
2. 새 dataset마다 ``refresh`` operation(= Dagster job 이름)과 fixture ``preview`` operation,
   ``dataset_wide`` operation scope를 넣는다. 옛 카탈로그와 같은 모양이다.
3. **identity 재지정(보험)**: 옛 dataset의 ``provider_feature_identities`` 행을 같은
   ``(feature_kind, natural_key)``로 새 dataset에 옮긴다. ADR-098 identity는
   ``(dataset, kind, natural_key)``이므로 이것이 없으면 옛 Feature가 있는 DB에서 새 적재가 같은
   대상을 두 번째 Feature로 주조한다. 자연키는 원천의 것 그대로다(주유소 uni_id, 휴게소
   ``name::route::direction``·휴게소 코드, IATA 코드). 2026-10-02 prod는 0행이다.
4. 옛 dataset의 operation을 **종류 불문**(``refresh``·``feature_load``·``preview``) 끄고 dataset을
   비활성으로 내린다(402와 같다 — preview만 켜 두면 은퇴한 dataset이 운영 화면에서 미리보기로
   살아 있다). **행은 지우지 않는다** — 이력이 exact FK로 가리킨다(401/402와 같은 규율).
5. ``provider_sync.notice_lineage_key``의 돌발 분기를 새 dataset으로 옮긴다.
   ``feature_repo._notice_lineage_sql``이 글자 단위로 같은 규칙을 따른다.
6. receipt head CHECK에 이 revision을 더한다.

막는 것(preflight, 하나라도 있으면 아무것도 바꾸지 않고 중단)
--------------------------------------------------------------

- 끌 operation(종류 불문)을 member로 둔 queued/running job(401과 같은 이유 — 영영 종결로 못 간다).
- 옛 돌발 notice dataset의 source entity. 돌발 계보(lineage)는 dataset 범위의 활성 집합으로
  닫히는데(``supersede_stale_notice_features``), identity만 옮기면 옛 dataset의 열린 계보는
  어느 reconcile도 닫지 않아 영구 active로 남는다. 2026-10-02 prod는 0행이다 — 남아 있으면
  사람이 정리한 뒤 다시 돌린다.
- 새 dataset이 이미 있다(이 revision의 일부만 적용된 DB).

forward-only. downgrade는 두지 않는다(ADR-021) — 옛 provider로 되돌리는 것은 새 결정이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501

revision: str = "404_transport_provider_identity"
down_revision: str | Sequence[str] | None = "403_drop_kma_notice_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSPORT_PROVIDER: Final[str] = "kor-travel-transport"

#: 함수 소유자. ``alembic/head-schema.sql``의 ``ALTER FUNCTION ... OWNER TO``와 같다.
_OWNER_ROLE: Final[str] = "ktm_feature_schema_owner"

#: (옛 provider, 옛 dataset_key) → (새 dataset_key, 표시 이름, kind, refresh operation key).
#: migration은 import 시점 앱 코드에 기대지 않으므로 값을 여기 둔다
#: (``kortravelmap.providers.kor_travel_transport``·``feature_operation_registry``와 같은 값).
DATASET_MOVES: Final[tuple[tuple[str, str, str, str, str, str], ...]] = (
    ("python-opinet-api", "opinet_fuel_station_details", "transport_fuel_stations",
     "주유소 (place Feature, kor-travel-transport)", "place", "feature_place_transport_fuel_stations_job"),
    ("python-opinet-api", "opinet_gas_station_prices", "transport_fuel_prices",
     "주유소 유가 (PriceValue, kor-travel-transport)", "price", "feature_price_transport_fuel_stations_job"),
    ("python-krex-api", "krex_rest_areas", "transport_rest_areas",
     "고속도로 휴게소 (place Feature, kor-travel-transport)", "place", "feature_place_transport_rest_areas_job"),
    ("python-krex-api", "krex_rest_area_prices", "transport_rest_area_fuel_prices",
     "휴게소 주유소 유가 (PriceValue, kor-travel-transport)", "price", "feature_price_transport_rest_areas_job"),
    ("python-krex-api", "krex_traffic_notices", "transport_highway_incidents",
     "고속도로 돌발/통제 (notice Feature, kor-travel-transport)", "notice", "feature_notice_transport_highway_incidents_job"),
    ("python-krairport-api", "krairport_airports", "transport_airports",
     "공항 (place Feature, kor-travel-transport)", "place", "feature_place_transport_airports_job"),
)

_OLD_PAIRS_SQL: Final[str] = ", ".join(f"('{old_p}', '{old_d}')" for old_p, old_d, *_ in DATASET_MOVES)
_OLD_DATASETS_SQL: Final[str] = f"""
SELECT dataset.provider_dataset_id
  FROM provider_sync.provider_datasets AS dataset
 WHERE (dataset.provider, dataset.dataset_key) IN ({_OLD_PAIRS_SQL})
"""

_SET_OWNER_ROLE_SQL: Final[str] = f"SET ROLE {_OWNER_ROLE}"

_INSERT_DATASETS_SQL: Final[str] = (
    "INSERT INTO provider_sync.provider_datasets (provider, dataset_key, display_name, source_kind, is_active, capabilities) VALUES "
    + ", ".join(
        f"('{TRANSPORT_PROVIDER}', '{new_d}', '{label}', 'internal', true, "
        f"'{{\"produces\": [\"{kind}\"], \"extensions\": {{}}, \"schema_version\": 1}}'::jsonb)"
        for _, _, new_d, label, kind, _ in DATASET_MOVES
    )
)

_NEW_OPERATIONS_VALUES: Final[str] = ", ".join(
    f"('{new_d}', '{job}')" for _, _, new_d, _, _, job in DATASET_MOVES
)

_INSERT_OPERATIONS_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_dataset_operations (provider_dataset_id, operation_key, operation_kind, is_enabled, config)
SELECT dataset.provider_dataset_id, move.operation_key, 'refresh', true, '{{}}'::jsonb
  FROM (VALUES {_NEW_OPERATIONS_VALUES}) AS move(dataset_key, operation_key)
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider = '{TRANSPORT_PROVIDER}' AND dataset.dataset_key = move.dataset_key
UNION ALL
SELECT dataset.provider_dataset_id, move.operation_key || '.preview', 'preview', true, '{{"handler": "fixture"}}'::jsonb
  FROM (VALUES {_NEW_OPERATIONS_VALUES}) AS move(dataset_key, operation_key)
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider = '{TRANSPORT_PROVIDER}' AND dataset.dataset_key = move.dataset_key
"""

_INSERT_OPERATION_SCOPES_SQL: Final[str] = f"""
INSERT INTO provider_sync.provider_dataset_operation_scopes (provider_dataset_id, sync_scope, operation_key, operation_kind)
SELECT dataset.provider_dataset_id, 'dataset_wide', move.operation_key, 'refresh'
  FROM (VALUES {_NEW_OPERATIONS_VALUES}) AS move(dataset_key, operation_key)
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider = '{TRANSPORT_PROVIDER}' AND dataset.dataset_key = move.dataset_key
"""

_MOVE_PAIRS_VALUES: Final[str] = ", ".join(
    f"('{old_p}', '{old_d}', '{new_d}')" for old_p, old_d, new_d, *_ in DATASET_MOVES
)

_REPOINT_IDENTITIES_SQL: Final[str] = f"""
UPDATE provider_sync.provider_feature_identities AS identity
   SET provider_dataset_id = new_dataset.provider_dataset_id
  FROM (VALUES {_MOVE_PAIRS_VALUES}) AS move(old_provider, old_dataset_key, new_dataset_key)
  JOIN provider_sync.provider_datasets AS old_dataset
    ON old_dataset.provider = move.old_provider AND old_dataset.dataset_key = move.old_dataset_key
  JOIN provider_sync.provider_datasets AS new_dataset
    ON new_dataset.provider = '{TRANSPORT_PROVIDER}' AND new_dataset.dataset_key = move.new_dataset_key
 WHERE identity.provider_dataset_id = old_dataset.provider_dataset_id
"""

_DISABLE_OLD_LOAD_OPERATIONS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_dataset_operations AS operation
   SET is_enabled = false
 WHERE operation.provider_dataset_id IN ({_OLD_DATASETS_SQL})
   AND operation.is_enabled
"""

_DEACTIVATE_OLD_DATASETS_SQL: Final[str] = f"""
UPDATE provider_sync.provider_datasets AS dataset
   SET is_active = false
 WHERE dataset.provider_dataset_id IN ({_OLD_DATASETS_SQL})
   AND dataset.is_active
"""

#: 본문은 403이 쓴 함수에서 돌발 분기의 provider/dataset 리터럴만 바꾼 것이다.
_REPLACE_NOTICE_LINEAGE_KEY_SQL: Final[str] = f"""CREATE OR REPLACE FUNCTION provider_sync.notice_lineage_key(head provider_sync.source_entity_heads) RETURNS text
    LANGUAGE sql STABLE
    AS $$
            SELECT CASE
              WHEN dataset.provider = '{TRANSPORT_PROVIDER}'
               AND dataset.dataset_key = 'transport_highway_incidents'
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
        $$"""

#: receipt head 값 열거 CHECK — graph의 **모든** revision(401과 같은 계약).
_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK (destination_head IN ('300', '301_m03_import_children', '302_m03_child_issuance', '303_m05_payload_hash_domain', '304_m05_detector_manuals', '305_m05_relitigation_fence', '306_m02_manual_feature_purge', '307_m02_truncate_fence', '308_t39_provider_identities', '309_t39_feature_id_rekey', '310_seoul_source_move', '311_seal_member_digest', '312_route_geometry_sidecar', '313_single_service_role', '400', '401_retire_map_kma_refresh', '402_remove_map_weather_data', '403_drop_kma_notice_lineage', '404_transport_provider_identity'))
"""

# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------

_IN_FLIGHT_OLD_LOAD_JOBS_SQL: Final[str] = f"""
SELECT in_flight.job_id
  FROM (
      SELECT job.job_id::text AS job_id
        FROM ops.import_jobs AS job
        JOIN ops.import_job_datasets AS member
          ON member.job_id = job.job_id
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = member.provider_dataset_id
         AND operation.operation_key = member.operation_key
       WHERE job.status IN ('queued', 'running')
         AND operation.provider_dataset_id IN ({_OLD_DATASETS_SQL})
         AND operation.is_enabled
      UNION
      SELECT job.job_id::text AS job_id
        FROM ops.feature_update_request_datasets AS member
        JOIN ops.feature_update_requests AS request
          ON request.request_id = member.request_id
        JOIN ops.import_jobs AS job
          ON job.job_id = request.job_id
        JOIN provider_sync.provider_dataset_operations AS operation
          ON operation.provider_dataset_id = member.provider_dataset_id
         AND operation.operation_key = member.operation_key
       WHERE job.status IN ('queued', 'running')
         AND operation.provider_dataset_id IN ({_OLD_DATASETS_SQL})
         AND operation.is_enabled
  ) AS in_flight
 ORDER BY in_flight.job_id
 LIMIT 10
"""

_OLD_NOTICE_ENTITIES_SQL: Final[str] = """
SELECT entity.source_entity_key
  FROM provider_sync.source_entities AS entity
  JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = entity.provider_dataset_id
 WHERE dataset.provider = 'python-krex-api'
   AND dataset.dataset_key = 'krex_traffic_notices'
 ORDER BY entity.source_entity_key
 LIMIT 10
"""

_EXISTING_TRANSPORT_DATASETS_SQL: Final[str] = f"""
SELECT dataset.dataset_key
  FROM provider_sync.provider_datasets AS dataset
 WHERE dataset.provider = '{TRANSPORT_PROVIDER}'
 ORDER BY dataset.dataset_key
"""

_ENABLED_OLD_LOAD_OPERATIONS_SQL: Final[str] = f"""
SELECT operation.operation_key
  FROM provider_sync.provider_dataset_operations AS operation
 WHERE operation.provider_dataset_id IN ({_OLD_DATASETS_SQL})
   AND operation.is_enabled
 ORDER BY operation.operation_key
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _SET_OWNER_ROLE_SQL,
    _INSERT_DATASETS_SQL,
    _INSERT_OPERATIONS_SQL,
    _INSERT_OPERATION_SCOPES_SQL,
    _REPOINT_IDENTITIES_SQL,
    _DISABLE_OLD_LOAD_OPERATIONS_SQL,
    _DEACTIVATE_OLD_DATASETS_SQL,
    _REPLACE_NOTICE_LINEAGE_KEY_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
)


def upgrade() -> None:
    """preflight를 통과하면 새 카탈로그를 넣고 identity를 옮기고 옛 적재를 닫는다."""
    bind = op.get_bind()
    blockers: list[str] = []
    in_flight = [str(job_id) for job_id in bind.execute(text(_IN_FLIGHT_OLD_LOAD_JOBS_SQL)).scalars()]
    if in_flight:
        blockers.append(f"queued/running job on an old operation: {in_flight!r}")
    notice_entities = [str(key) for key in bind.execute(text(_OLD_NOTICE_ENTITIES_SQL)).scalars()]
    if notice_entities:
        blockers.append(f"old KREX notice source entities would stay open forever: {notice_entities!r}")
    existing = [str(key) for key in bind.execute(text(_EXISTING_TRANSPORT_DATASETS_SQL)).scalars()]
    if existing:
        blockers.append(f"{TRANSPORT_PROVIDER} datasets already exist: {existing!r}")
    if blockers:
        raise RuntimeError("404: 아무것도 바꾸지 않았다 — " + "; ".join(blockers))
    for statement in _UPGRADE_STATEMENTS:
        bind.execute(text(statement))
    remaining = list(bind.execute(text(_ENABLED_OLD_LOAD_OPERATIONS_SQL)).scalars())
    if remaining:
        raise RuntimeError(f"404: 옛 provider의 enabled operation이 남았다: {remaining!r}")


def downgrade() -> None:
    """되돌리지 않는다 — Map이 OpiNet·KREX·krairport를 다시 직접 부르는 것은 새 결정이다."""
    raise RuntimeError(
        "404_transport_provider_identity is forward-only: 원천은 kor-travel-transport다(ADR-106)."
    )

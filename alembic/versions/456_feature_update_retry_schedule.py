"""큐 요청 재발행 일정 — ``ops.feature_update_requests``에 재시도 횟수와 다음 발행 시각을 둔다.

Revision ID: 456_feature_update_retry_schedule
Revises: 455_feature_cluster_points

왜 필요한가(감사 ``docs/reports/2026-11-23-collection-failure-audit.md`` §1.3 P1·§4 #15).

- **시작 전 실패의 재발행에 상한·backoff가 없었다.** worker run이 claim 전에 실패하면(launch 실패 —
  n150 code-server fd 고갈 1,888건이 그 꼴이다) failure sensor가 generation만 +1했고, 15초 뒤
  큐 sensor가 곧바로 새 run을 냈다. 원인이 지속되면 끝없이 run을 만든다.
- **일시 DB 오류가 곧바로 종결이었다.** 10-22에 한꺼번에 넣은 13건이 ``import_job_events`` INSERT의
  lock timeout(``import_job_event_clock`` 단일 행)으로 그대로 ``failed``가 됐다.

무엇을 하는가. 두 열을 더한다.

- ``retry_count integer NOT NULL DEFAULT 0`` (``>= 0``) — 재발행 횟수. 상한은 코드
  (``FEATURE_UPDATE_MAX_RETRIES``)가 갖고, 넘으면 request를 ``failed``로 닫는다.
- ``next_dispatch_at timestamptz`` — 이 시각 전에는 큐 sensor가 집지 않는다(지수 backoff + jitter,
  ``NULL``이면 즉시). 큐 peek 술어에만 쓰인다.

``ops.guard_feature_update_request_mutation``은 이 두 열을 막지 않는다(입력·감사 식별자만 막는다).
재발행은 generation +1과 같은 문장에서 일어나므로 기존 generation 규칙(정확히 +1, 활성 job)을
그대로 지난다.

잠금·시간. 상수 DEFAULT의 ``ADD COLUMN``은 표를 다시 쓰지 않는다(PG 11+ fast default). 잡는 잠금은
``ACCESS EXCLUSIVE``(작은 표, prod 수십 행)라 ``lock_timeout`` 1초, 문장 상한 30초. receipt head
CHECK 교체는 452~455와 같다.

마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다(alembic_version UPDATE가 그 롤로 돈다 —
RESET ROLE 금지). forward-only — 되돌릴 일이 생기면 forward revision이 열을 걷는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "456_feature_update_retry_schedule"
down_revision: str | Sequence[str] | None = "455_feature_cluster_points"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

_ADD_COLUMNS_SQL: Final[str] = """
ALTER TABLE ops.feature_update_requests
    ADD COLUMN retry_count integer NOT NULL DEFAULT 0,
    ADD COLUMN next_dispatch_at timestamp with time zone,
    ADD CONSTRAINT ck_feature_update_requests_retry_count_nonnegative CHECK (retry_count >= 0)
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
        '456_feature_update_retry_schedule'
    ))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(453과 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _ADD_COLUMNS_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)
_LOCK_TIMEOUT_MS: Final[int] = 1000
_STATEMENT_TIMEOUT_CAP_MS: Final[int] = 30000


def upgrade() -> None:
    """재시도 열 둘을 더하고 receipt head CHECK에 456을 더한다."""
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
    """되돌리지 않는다 — 열은 forward revision으로만 걷는다."""
    raise RuntimeError(
        "456_feature_update_retry_schedule is forward-only: 열은 forward revision으로만 걷는다."
    )

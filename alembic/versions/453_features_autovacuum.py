"""``feature.features``에 표 단위 autovacuum 문턱을 건다 — 읽기 성능 계획 T-READ-08.

Revision ID: 453_features_autovacuum
Revises: 452_lotte_hotel_search_alias

왜 필요한가. ``feature.features``에는 reloptions가 없어 autovacuum이 클러스터 기본 문턱
(50 + dead 20% — prod 약 44.2만 행이면 약 8.8만 행)에서야 돈다. prod 2026-11-17 실측(읽기
전용, 계획 ``docs/reports/2026-11-17-read-performance-plan.md`` §4.1·F-14): 통계 창(3.6일 이하)
동안 autovacuum 0회, dead 약 6.3만 행, all-visible page 58%. all-visible이 아닌 page에서는
index-only scan이 heap을 다시 읽는다 — 지역 검색의 공개 행 수 세기(``_SEARCH_REGION_ROW_COUNT_SQL``,
"index-only count"로 설계)와 bbox·집계 탐색이 그 영향을 받는다.

무엇을 하는가. 표 하나의 storage parameter 셋(계획 §8의 제안값).

- ``autovacuum_vacuum_scale_factor = 0.02`` — dead 50 + 2%(약 8.9천 행)에서 VACUUM.
- ``autovacuum_vacuum_insert_scale_factor = 0.05`` — 삽입 1,000 + 5%(약 2.3만 행)에서 VACUUM
  (새 page를 all-visible로 만든다).
- ``autovacuum_analyze_scale_factor = 0.02`` — 변경 50 + 2%에서 ANALYZE.

잠금·시간. ``ALTER TABLE … SET (autovacuum_…)``은 catalog만 바꾸고 표를 다시 쓰지 않는다
(relfilenode 불변). 잡는 잠금은 ``SHARE UPDATE EXCLUSIVE``라 읽기·쓰기(적재 포함)를 막지 않고
VACUUM·ANALYZE·``CREATE INDEX CONCURRENTLY``와만 충돌한다. 그 표에 autovacuum이 돌고 있으면
PostgreSQL이 ``deadlock_timeout``(기본 1초) 뒤 그 worker를 취소하므로 이 ``ALTER``만
``lock_timeout``을 5초로 둔다(다른 revision의 1초로는 취소 전에 먼저 포기할 수 있다).
수동 VACUUM·ANALYZE나 **취소되지 않는 anti-wraparound autovacuum**이 그 표에 돌고 있으면 5초 뒤
실패하고 배포가 멈춘다 — 그것이 끝난 뒤 다시 돌리면 된다. receipt 표 CHECK 교체는
``ACCESS EXCLUSIVE``(작은 표)라 452와 같은 1초로 되돌린 뒤에 한다. ``statement_timeout`` 30초.

배포 직후의 효과. 새 문턱으로는 dead가 이미 넘쳐 있을 가능성이 크므로 다음 autovacuum
naptime(기본 1분) 안에 그 표의 VACUUM이 한 번 돈다 — heap 약 379 MB와 색인 18개 약 720 MB를
훑는다(2026-11-17 크기). autovacuum의 비용 상한(``autovacuum_vacuum_cost_*``)이 속도를 묶어
읽기를 막지 않지만, 그 동안 디스크 읽기·쓰기가 는다. 그 뒤로는 적재마다 작은 VACUUM이 더 자주
돈다(계획 §8 T-READ-08 위험).

마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다(alembic_version UPDATE가 그 롤로 돈다 —
RESET ROLE 금지).

forward-only. 되돌릴 일이 생기면 forward revision이 ``ALTER TABLE feature.features RESET (…)``을
한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "453_features_autovacuum"
down_revision: str | Sequence[str] | None = "452_lotte_hotel_search_alias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: 표 단위 autovacuum 설정(이름, 값). 계획 §8 T-READ-08의 제안값이다.
FEATURES_AUTOVACUUM_OPTIONS: Final[tuple[tuple[str, str], ...]] = (
    ("autovacuum_vacuum_scale_factor", "0.02"),
    ("autovacuum_vacuum_insert_scale_factor", "0.05"),
    ("autovacuum_analyze_scale_factor", "0.02"),
)

_SET_FEATURES_AUTOVACUUM_SQL: Final[str] = (
    "ALTER TABLE feature.features SET ("
    + ", ".join(f"{name} = {value}" for name, value in FEATURES_AUTOVACUUM_OPTIONS)
    + ")"
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
        '447_admin_search_trgm_indexes',
        '448_mcst_theme_transition',
        '449_tourapi_festivals_primary',
        '450_incheon_airport_search_alias',
        '451_feature_search_prominence',
        '452_lotte_hotel_search_alias',
        '453_features_autovacuum'
    ))
"""


#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(452와 같다).
#: (문장, 그 문장 앞에 걸 lock_timeout 상한 ms). ALTER만 5초 — autovacuum 취소
#: (deadlock_timeout 1초)를 기다린다. CHECK 교체(ACCESS EXCLUSIVE)는 452와 같은 1초.
_UPGRADE_STATEMENTS: Final[tuple[tuple[str, int], ...]] = (
    ("SET ROLE " + _SCHEMA_OWNER, 1000),
    (_SET_FEATURES_AUTOVACUUM_SQL, 5000),
    (_RECEIPT_HEAD_CHECK_SQL, 1000),
    ("SET ROLE " + _SCHEMA_OWNER, 1000),
)
_STATEMENT_TIMEOUT_CAP_MS: Final[int] = 30000


def upgrade() -> None:
    """``feature.features``에 autovacuum 문턱을 걸고 receipt head CHECK에 453을 더한다."""
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
    for statement, lock_limit in _UPGRADE_STATEMENTS:
        cap("lock_timeout", lock_limit)
        bind.execute(text(statement))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    """되돌리지 않는다 — 설정은 forward revision의 ``RESET``으로만 걷는다."""
    raise RuntimeError(
        "453_features_autovacuum is forward-only: 설정은 forward revision의 RESET으로만 걷는다."
    )

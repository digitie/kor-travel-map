"""route geometry에 저배율 집계용 대표점·정확 범위 생성 컬럼을 단다 — 읽기 성능 계획 T-READ-10.

Revision ID: 454_route_cluster_markers
Revises: 453_features_autovacuum

왜 필요한가. 전 kind 저배율 집계(``feature_repo._cluster_bbox_sql``의 geometry arm)는 요청마다
bbox에 걸린 route geometry(전국 bbox면 prod 약 5.8만 개, 평균 118점·최대 4.9만 점, 표 232 MB)를
전부 풀어 ``ST_Intersects``·``ST_XMin`` 등·``ST_PointOnSurface``를 계산했다. prod 2026-11-19
``EXPLAIN (ANALYZE, BUFFERS)``(읽기 전용, jit=off): 집계 1.6 s 중 geometry 후보 CTE가 0.68 s였다.
그 값들은 geometry만의 함수다 — 행이 쓰일 때 한 번 계산해 두면 된다.

무엇을 하는가. ``feature.feature_route_geometries``에 **STORED 생성 컬럼** 다섯.

- ``marker_point geometry(Point,4326)`` = ``ST_PointOnSurface(geom)``
- ``geom_xmin``·``geom_xmax``·``geom_ymin``·``geom_ymax double precision`` = ``ST_XMin(geom)`` 등
  (geometry→box3d 변환은 좌표로 계산한 double이다 — ``&&``의 float4 캐시 bbox가 아니다).

생성 컬럼이라 동기화 코드가 없고, 프로시저를 우회한 ``UPDATE … SET geom``까지 DB가 같은 행·같은
transaction에서 덮는다(같은 표의 ``geom_digest``와 같은 방식). 식은 집계 SQL이 종전에 요청마다
계산하던 식과 **같다** — 그래서 집계 결과(개수·대표점)가 바뀌지 않는다(통합 시험이 종전 SQL과
비교한다). 런타임 권한은 바꾸지 않는다(생성 컬럼에는 쓰지 않고, 읽기는 표 단위 SELECT다).

``feature.feature_areas``에는 달지 않는다. 그 행은 ``current_provider_curation_input_set`` 등이
``to_jsonb(area_row)``로 통째 해시하므로 열을 더하면 area dataset의 입력 해시가 바뀐다(route
geometry는 ``geom_digest``만 해시에 들어간다). area는 prod 422행이라 요청 때 계산해도 약 28 ms다.

잠금·시간. STORED 생성 컬럼 추가는 표를 **다시 쓴다** — ``ACCESS EXCLUSIVE``를 잡고 행마다 다섯
식을 계산한다. 그 동안 route geometry를 읽는 요청(route/area를 포함하는 in-bounds·상세)이
기다린다. 시간은 PR 본문·``docs/journal.md``의 실측을 본다. 잠금 대기는 ``lock_timeout`` 5초다
— 줄 선 ``ACCESS EXCLUSIVE``가 뒤 읽기를 막으므로 길게 기다리지 않는다. route 적재(쓰기
transaction)가 돌고 있으면 5초 뒤 실패하고 배포가 멈춘다 — 적재를 멈춘 뒤 다시 돌리면 된다.
``statement_timeout``은 다시 쓰기를 감당하도록 300초로 묶는다. receipt 표 CHECK 교체는
``ACCESS EXCLUSIVE``(작은 표)라 1초.

마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다(alembic_version UPDATE가 그 롤로 돈다 —
RESET ROLE 금지).

forward-only. 되돌릴 일이 생기면 forward revision이 열을 지운다(집계 SQL을 먼저 되돌린다).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "454_route_cluster_markers"
down_revision: str | Sequence[str] | None = "453_features_autovacuum"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: (열 이름, 타입, 생성식). 식은 ``feature_repo._cluster_bbox_sql``이 종전에 요청마다 계산하던
#: 식이다 — 바꾸면 집계 결과가 바뀐다.
ROUTE_CLUSTER_MARKER_COLUMNS: Final[tuple[tuple[str, str, str], ...]] = (
    ("marker_point", "x_extension.geometry(Point,4326)", "x_extension.ST_PointOnSurface(geom)"),
    ("geom_xmin", "double precision", "x_extension.ST_XMin(geom)"),
    ("geom_xmax", "double precision", "x_extension.ST_XMax(geom)"),
    ("geom_ymin", "double precision", "x_extension.ST_YMin(geom)"),
    ("geom_ymax", "double precision", "x_extension.ST_YMax(geom)"),
)

_ADD_MARKER_COLUMNS_SQL: Final[str] = "ALTER TABLE feature.feature_route_geometries\n    " + (
    ",\n    ".join(
        f"ADD COLUMN {name} {column_type} GENERATED ALWAYS AS ({expression}) STORED"
        for name, column_type, expression in ROUTE_CLUSTER_MARKER_COLUMNS
    )
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
        '453_features_autovacuum',
        '454_route_cluster_markers'
    ))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(453과 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _ADD_MARKER_COLUMNS_SQL,
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)
#: lock_timeout 상한(ms). 다시 쓰기의 ``ACCESS EXCLUSIVE``는 5초, CHECK 교체는 1초.
_ALTER_LOCK_TIMEOUT_MS: Final[int] = 5000
_LOCK_TIMEOUT_MS: Final[int] = 1000
#: 다시 쓰기(prod 약 5.8만 행·232 MB)를 감당하는 문장 상한.
_STATEMENT_TIMEOUT_CAP_MS: Final[int] = 300000


def upgrade() -> None:
    """route geometry에 생성 컬럼 다섯을 달고 receipt head CHECK에 454를 더한다."""
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
    for statement in _UPGRADE_STATEMENTS:
        lock_limit = (
            _ALTER_LOCK_TIMEOUT_MS if statement == _ADD_MARKER_COLUMNS_SQL else _LOCK_TIMEOUT_MS
        )
        cap("lock_timeout", lock_limit)
        bind.execute(text(statement))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    """되돌리지 않는다 — 열은 forward revision으로만 걷는다."""
    raise RuntimeError(
        "454_route_cluster_markers is forward-only: 열은 forward revision으로만 걷는다."
    )

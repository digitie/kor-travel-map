"""저배율 집계 전용 좁은 표 ``feature.feature_cluster_points`` — 읽기 성능 계획 T-READ-10 후속.

Revision ID: 455_feature_cluster_points
Revises: 454_route_cluster_markers

왜 필요한가. 전국 sido 전 kind 집계(zoom ≤ 7)는 454 뒤에도 n150 합성 42만 행에서 p50 약 0.48~0.7
s였다. 남은 비용은 둘이다 — ① 넓은 ``feature.features`` heap(prod 379 MB)을 행마다 읽는 point
후보, ② route 5.8만 행마다 ``features``를 PK로 하나씩 찾아 지역 코드를 붙이는 조인과 넓은 route
heap(232 MB) 읽기. 소유자가 2026-11-19 사전 집계 제외(T-101)를 풀었고, 결과가 기존 질의와 같아야
한다(개수 정확히, 평균 좌표 1e-9도 이내).

무엇을 하는가. 집계가 읽는 열만 담은 좁은 표 하나와, 그것을 **같은 transaction에서** 맞추는
trigger 셋.

- ``feature.feature_cluster_points`` — Feature 하나에 한 행. ``features``
  몫(``kind``·``category``·지역 코드 셋·``coord``·공개 3축 곱 ``public``)과 geometry
  몫(``marker_point`` = ``ST_PointOnSurface(geom)``, ``geom_xmin``…``geom_ymax`` =
  ``ST_XMin(geom)``…; route는 454의 생성 컬럼, area는 같은 식)을 둔다. 집계 SQL은 이 표를 Gather
  아래에서 병렬로 훑는다. notice는 행이 있지만 집계가 쓰지 않는다(notice는 종료·구버전 감산이
  시각과 계보에 매여 종전처럼 공개 view에서 읽는다).
- trigger — ``features`` INSERT/관련 열 UPDATE/DELETE,
  ``feature_route_geometries``·``feature_areas`` INSERT/``geom`` UPDATE/DELETE. 각 trigger는
  **자기 몫의 열만** upsert한다. 한 Feature의 core와 geometry를 두 transaction이 동시에 바꿔도
  같은 행의 서로 다른 열을 쓰므로 행 잠금 뒤 재평가(READ COMMITTED)로 둘 다 남는다. 새 표는 core
  writer와 geometry writer가 함께 잡는 잠금 자리다 — 순서를 하나로 맞춘다: geometry 쓰기는
  subtype 행 → 이 표 행, 상태 전이는 ``features`` 행 → subtype
  행(``trg_features_sync_subtype_public_ready``) → 이 표 행. 그래서 ``features`` trigger 이름을
  ``trg_features_zz_cluster_point``로 두어 같은 시점의 AFTER trigger 중 맨 뒤(이름순)에 돈다.
  부모(``features``) 잠금은 새로 잡지 않는다.
- FK는 두지 않는다. purge 증거 포획은 ``confrelid='feature.features'``인 자식을 훑는다 — 이
  표를 자식으로 만들면 포획 모양이 바뀐다. 삭제는 ``features`` DELETE trigger가 한다.

반영 시점. **동기식**이다 — 쓰기 transaction이 commit되는 순간 집계에 보인다(같은 transaction
안에서도 보인다). 지연이 없다. ``tests/integration/test_cluster_points_sync.py``가 쓰기 종류마다
고정한다.

영향.
- 큐레이션 해시: 바뀌지 않는다. ``features``·subtype 행의 열을 바꾸지 않고, 새 표는 어떤
  ``to_jsonb`` 입력 집합에도 없다.
- HOT(T-READ-07): ``features``에 색인·열을 더하지 않는다 — ``features`` 갱신의 HOT 여부는
  그대로다 (prod ``n_tup_hot_upd`` 0, ``updated_at`` 색인 때문). 새 표의 갱신은 새 표의 색인만
  건드린다.
- 적재 쓰기 비용: 관련 열이 바뀐 ``features`` 행마다 좁은 표 upsert 한 번. 실측은 PR·journal.

잠금·시간. ``CREATE TRIGGER``가 세 표에 ``SHARE ROW EXCLUSIVE``를 잡아 commit까지 쓰기를
막는다(읽기는 막지 않는다). 그 사이 backfill(``features`` 전부 + route/area geometry)과 색인
둘을 만든다. 잠금 대기는 ``lock_timeout`` 5초(진행 중인 적재가 있으면 실패 — 멈춘 뒤 다시
돌린다), 문장 상한 300초. 시간은 journal의 실측을 본다.

마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다(alembic_version UPDATE가 그 롤로 돈다 —
RESET ROLE 금지). forward-only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "455_feature_cluster_points"
down_revision: str | Sequence[str] | None = "454_route_cluster_markers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

_CREATE_TABLE_SQL: Final[str] = """
CREATE TABLE feature.feature_cluster_points (
    feature_id uuid NOT NULL,
    kind character varying NOT NULL,
    category character varying NOT NULL,
    sido_code character varying(2),
    sigungu_code character varying(5),
    legal_dong_code character varying(10),
    coord x_extension.geometry(Point,4326),
    public boolean NOT NULL,
    marker_point x_extension.geometry(Point,4326),
    geom_xmin double precision,
    geom_xmax double precision,
    geom_ymin double precision,
    geom_ymax double precision,
    geom_bounds x_extension.geometry(Polygon,4326) GENERATED ALWAYS AS (
        x_extension.ST_MakeEnvelope(geom_xmin, geom_ymin, geom_xmax, geom_ymax, 4326)
    ) STORED,
    CONSTRAINT pk_feature_cluster_points PRIMARY KEY (feature_id)
)
"""

#: core 몫 — ``features`` 한 행에서 계산한다. ``public``은 공개 view의 술어와 같은 3축 곱이다.
_CORE_SYNC_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION feature.sync_feature_cluster_point_core() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM feature.feature_cluster_points WHERE feature_id = OLD.feature_id;
        RETURN NULL;
    END IF;
    IF TG_OP = 'UPDATE'
       AND NEW.kind IS NOT DISTINCT FROM OLD.kind
       AND NEW.category IS NOT DISTINCT FROM OLD.category
       AND NEW.sido_code IS NOT DISTINCT FROM OLD.sido_code
       AND NEW.sigungu_code IS NOT DISTINCT FROM OLD.sigungu_code
       AND NEW.legal_dong_code IS NOT DISTINCT FROM OLD.legal_dong_code
       AND x_extension.ST_AsEWKB(NEW.coord) IS NOT DISTINCT FROM x_extension.ST_AsEWKB(OLD.coord)
       AND NEW.lifecycle_state IS NOT DISTINCT FROM OLD.lifecycle_state
       AND NEW.publication_state IS NOT DISTINCT FROM OLD.publication_state
       AND NEW.quality_state IS NOT DISTINCT FROM OLD.quality_state THEN
        RETURN NULL;
    END IF;
    INSERT INTO feature.feature_cluster_points AS cp (
        feature_id, kind, category, sido_code, sigungu_code, legal_dong_code, coord, public
    )
    VALUES (
        NEW.feature_id, NEW.kind, NEW.category, NEW.sido_code, NEW.sigungu_code,
        NEW.legal_dong_code, NEW.coord,
        NEW.lifecycle_state = 'active' AND NEW.publication_state = 'published'
            AND NEW.quality_state = 'valid'
    )
    ON CONFLICT (feature_id) DO UPDATE SET
        kind = EXCLUDED.kind,
        category = EXCLUDED.category,
        sido_code = EXCLUDED.sido_code,
        sigungu_code = EXCLUDED.sigungu_code,
        legal_dong_code = EXCLUDED.legal_dong_code,
        coord = EXCLUDED.coord,
        public = EXCLUDED.public;
    RETURN NULL;
END;
$$
"""

#: geometry 몫 — route는 454 생성 컬럼을, area는 같은 식을 그 자리에서 쓴다. 행이 아직 없으면
#: (core trigger보다 먼저 올 수는 없지만 방어적으로) 부모 행에서 core 몫을 채워 만든다.
_GEOMETRY_SYNC_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION feature.sync_feature_cluster_point_geometry() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_feature_id uuid;
    v_marker x_extension.geometry;
    v_xmin double precision;
    v_xmax double precision;
    v_ymin double precision;
    v_ymax double precision;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_feature_id := OLD.feature_id;
    ELSE
        v_feature_id := NEW.feature_id;
        IF TG_TABLE_NAME = 'feature_route_geometries' THEN
            v_marker := NEW.marker_point;
            v_xmin := NEW.geom_xmin;
            v_xmax := NEW.geom_xmax;
            v_ymin := NEW.geom_ymin;
            v_ymax := NEW.geom_ymax;
        ELSE
            v_marker := x_extension.ST_PointOnSurface(NEW.geom);
            v_xmin := x_extension.ST_XMin(NEW.geom);
            v_xmax := x_extension.ST_XMax(NEW.geom);
            v_ymin := x_extension.ST_YMin(NEW.geom);
            v_ymax := x_extension.ST_YMax(NEW.geom);
        END IF;
    END IF;
    UPDATE feature.feature_cluster_points
       SET marker_point = v_marker,
           geom_xmin = v_xmin,
           geom_xmax = v_xmax,
           geom_ymin = v_ymin,
           geom_ymax = v_ymax
     WHERE feature_id = v_feature_id;
    IF NOT FOUND AND TG_OP <> 'DELETE' THEN
        INSERT INTO feature.feature_cluster_points AS cp (
            feature_id, kind, category, sido_code, sigungu_code, legal_dong_code, coord, public,
            marker_point, geom_xmin, geom_xmax, geom_ymin, geom_ymax
        )
        SELECT f.feature_id, f.kind, f.category, f.sido_code, f.sigungu_code, f.legal_dong_code,
               f.coord,
               f.lifecycle_state = 'active' AND f.publication_state = 'published'
                   AND f.quality_state = 'valid',
               v_marker, v_xmin, v_xmax, v_ymin, v_ymax
          FROM feature.features AS f
         WHERE f.feature_id = v_feature_id
        ON CONFLICT (feature_id) DO UPDATE SET
            marker_point = EXCLUDED.marker_point,
            geom_xmin = EXCLUDED.geom_xmin,
            geom_xmax = EXCLUDED.geom_xmax,
            geom_ymin = EXCLUDED.geom_ymin,
            geom_ymax = EXCLUDED.geom_ymax;
    END IF;
    RETURN NULL;
END;
$$
"""

#: TRUNCATE는 행 trigger를 부르지 않는다 — 문장 trigger로 같은 효과를 낸다.
#: ``features``는 운영에서
#: TRUNCATE fence가 막지만(307), fence를 끈 정리 경로(통합 시험)도 표를 어긋나게 두지 않는다.
_TRUNCATE_SYNC_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION feature.truncate_feature_cluster_point_parts() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_TABLE_NAME = 'features' THEN
        TRUNCATE feature.feature_cluster_points;
    ELSE
        UPDATE feature.feature_cluster_points
           SET marker_point = NULL,
               geom_xmin = NULL,
               geom_xmax = NULL,
               geom_ymin = NULL,
               geom_ymax = NULL
         WHERE kind = CASE TG_TABLE_NAME
                          WHEN 'feature_route_geometries' THEN 'route'
                          ELSE 'area'
                      END;
    END IF;
    RETURN NULL;
END;
$$
"""

#: trigger 함수는 실행 권한 없이도 발화한다 — 런타임 login이 직접 부를 수 없게
#: PUBLIC 실행권을 걷는다
#: (런타임 preflight가 예상 밖 SECURITY DEFINER 실행권을 거부한다).
_REVOKE_FUNCTION_SQL: Final[tuple[str, ...]] = (
    "REVOKE ALL ON FUNCTION feature.sync_feature_cluster_point_core() FROM PUBLIC",
    "REVOKE ALL ON FUNCTION feature.sync_feature_cluster_point_geometry() FROM PUBLIC",
    "REVOKE ALL ON FUNCTION feature.truncate_feature_cluster_point_parts() FROM PUBLIC",
)

_TRIGGER_SQL: Final[tuple[str, ...]] = (
    "CREATE TRIGGER trg_features_zz_cluster_point "
    "AFTER INSERT OR DELETE OR UPDATE OF kind, category, sido_code, sigungu_code, "
    "legal_dong_code, coord, lifecycle_state, publication_state, quality_state "
    "ON feature.features FOR EACH ROW "
    "EXECUTE FUNCTION feature.sync_feature_cluster_point_core()",
    "CREATE TRIGGER trg_feature_route_geometries_cluster_point "
    "AFTER INSERT OR DELETE OR UPDATE OF geom ON feature.feature_route_geometries "
    "FOR EACH ROW EXECUTE FUNCTION feature.sync_feature_cluster_point_geometry()",
    "CREATE TRIGGER trg_feature_areas_cluster_point "
    "AFTER INSERT OR DELETE OR UPDATE OF geom ON feature.feature_areas "
    "FOR EACH ROW EXECUTE FUNCTION feature.sync_feature_cluster_point_geometry()",
    "CREATE TRIGGER trg_features_zz_cluster_point_truncate AFTER TRUNCATE ON feature.features "
    "FOR EACH STATEMENT EXECUTE FUNCTION feature.truncate_feature_cluster_point_parts()",
    "CREATE TRIGGER trg_feature_route_geometries_cluster_point_truncate "
    "AFTER TRUNCATE ON feature.feature_route_geometries "
    "FOR EACH STATEMENT EXECUTE FUNCTION feature.truncate_feature_cluster_point_parts()",
    "CREATE TRIGGER trg_feature_areas_cluster_point_truncate "
    "AFTER TRUNCATE ON feature.feature_areas "
    "FOR EACH STATEMENT EXECUTE FUNCTION feature.truncate_feature_cluster_point_parts()",
)

#: 파생 상태라 ``session_replication_role = replica``에서도 돌아야 한다(``ENABLE ALWAYS``) —
#: 복제 역할로
#: 쓰는 경로(정리·복구 도구)가 표를 어긋나게 두지 않는다. 307의 TRUNCATE fence와 같은 선택이다.
_ENABLE_ALWAYS_SQL: Final[tuple[str, ...]] = (
    "ALTER TABLE feature.features ENABLE ALWAYS TRIGGER trg_features_zz_cluster_point",
    "ALTER TABLE feature.features ENABLE ALWAYS TRIGGER trg_features_zz_cluster_point_truncate",
    "ALTER TABLE feature.feature_route_geometries "
    "ENABLE ALWAYS TRIGGER trg_feature_route_geometries_cluster_point",
    "ALTER TABLE feature.feature_route_geometries "
    "ENABLE ALWAYS TRIGGER trg_feature_route_geometries_cluster_point_truncate",
    "ALTER TABLE feature.feature_areas ENABLE ALWAYS TRIGGER trg_feature_areas_cluster_point",
    "ALTER TABLE feature.feature_areas "
    "ENABLE ALWAYS TRIGGER trg_feature_areas_cluster_point_truncate",
)

#: trigger가 잡은 잠금 아래에서 채운다 — 그 뒤 쓰기는 trigger가 맞춘다.
_BACKFILL_SQL: Final[str] = """
INSERT INTO feature.feature_cluster_points (
    feature_id, kind, category, sido_code, sigungu_code, legal_dong_code, coord, public,
    marker_point, geom_xmin, geom_xmax, geom_ymin, geom_ymax
)
SELECT
    f.feature_id, f.kind, f.category, f.sido_code, f.sigungu_code, f.legal_dong_code, f.coord,
    f.lifecycle_state = 'active' AND f.publication_state = 'published'
        AND f.quality_state = 'valid',
    COALESCE(r.marker_point, x_extension.ST_PointOnSurface(a.geom)),
    COALESCE(r.geom_xmin, x_extension.ST_XMin(a.geom)),
    COALESCE(r.geom_xmax, x_extension.ST_XMax(a.geom)),
    COALESCE(r.geom_ymin, x_extension.ST_YMin(a.geom)),
    COALESCE(r.geom_ymax, x_extension.ST_YMax(a.geom))
FROM feature.features AS f
LEFT JOIN feature.feature_route_geometries AS r ON r.feature_id = f.feature_id
LEFT JOIN feature.feature_areas AS a ON a.feature_id = f.feature_id
"""

#: 집계가 쓰는 두 공간 색인. 술어는 ``feature_repo._cluster_bbox_sql``의 술어와 같아야 한다.
_INDEX_SQL: Final[tuple[str, ...]] = (
    "CREATE INDEX idx_feature_cluster_points_coord_gist ON feature.feature_cluster_points "
    "USING gist (coord) WHERE public AND kind NOT IN ('route', 'area', 'notice')",
    "CREATE INDEX idx_feature_cluster_points_bounds_gist ON feature.feature_cluster_points "
    "USING gist (geom_bounds) "
    "WHERE public AND kind IN ('route', 'area')",
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
        '454_route_cluster_markers',
        '455_feature_cluster_points'
    ))
"""

#: 실행 순서대로의 upgrade 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(454와 같다).
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _CREATE_TABLE_SQL,
    _CORE_SYNC_FUNCTION_SQL,
    _GEOMETRY_SYNC_FUNCTION_SQL,
    _TRUNCATE_SYNC_FUNCTION_SQL,
    *_REVOKE_FUNCTION_SQL,
    *_TRIGGER_SQL,
    *_ENABLE_ALWAYS_SQL,
    _BACKFILL_SQL,
    *_INDEX_SQL,
    "ANALYZE feature.feature_cluster_points",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)
#: lock_timeout 상한(ms). 세 표의 trigger 생성(SHARE ROW EXCLUSIVE)은 5초, 나머지는 1초.
_TRIGGER_LOCK_TIMEOUT_MS: Final[int] = 5000
_LOCK_TIMEOUT_MS: Final[int] = 1000
_STATEMENT_TIMEOUT_CAP_MS: Final[int] = 300000


def upgrade() -> None:
    """좁은 집계 표·trigger를 만들고 채운 뒤 receipt head CHECK에 455를 더한다."""
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
        cap(
            "lock_timeout",
            _TRIGGER_LOCK_TIMEOUT_MS
            if statement in _TRIGGER_SQL or statement in _ENABLE_ALWAYS_SQL
            else _LOCK_TIMEOUT_MS,
        )
        bind.execute(text(statement))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    """되돌리지 않는다 — 표·trigger는 forward revision으로만 걷는다."""
    raise RuntimeError(
        "455_feature_cluster_points is forward-only: 표·trigger는 forward revision으로만 걷는다."
    )

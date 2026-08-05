"""typed subtype 분해 ③ — route·area subtype + geometry 정본 이동 (T-VN-35C, ADR-084).

무엇이 달라지나
---------------

core ``features.geom``(느슨한 ``GEOMETRY(GENERIC, 4326)``)을 **route/area
subtype으로 옮기고 core에서 제거**한다. subtype에서는 geometry 계약이 정확해진다:

- ``feature_routes.geom`` — ``MULTILINESTRING(4326)`` **NOT NULL**.
- ``feature_areas.geom`` — ``MULTIPOLYGON(4326)`` **NOT NULL**.

이로써 "geometry가 필수인 kind"와 "geometry가 없어야 하는 kind"가 술어가 아니라
**테이블 구조**로 갈린다. 지금 코드가 흩어서 검사하던 것들(예:
``_INACTIVATE_GEOMETRYLESS_AREA_BY_SOURCE_SQL``의 ``kind='area' AND geom IS NULL``
보정, bbox 후보 술어의 ``kind IN ('route','area') AND geom IS NOT NULL``)이
구조적으로 불필요해진다.

왜 지금 옮겨도 안전한가 (prod 실측)
-----------------------------------

route/area 행 **0건**, ``geom IS NOT NULL`` 행 **0건**. 즉 데이터 이관량이
0이고, 이동 후에도 모든 read는 종전과 같은 결과(NULL/빈 목록)를 낸다 —
LEFT JOIN이 없는 행을 만들지 않는다. geometry를 쓰는 read(bbox
``include_geometry``, contained-features ``ST_Covers``, ``area_square_meters``)는
같은 PR의 35D cutover에서 subtype LEFT JOIN으로 재작성된다.

``parent_feature_id``/``sibling_group_id``는 **core에 남긴다** — prod 사용
0행이고(실측), place도 장래 부모를 가질 수 있어 route/area 전용으로 내릴 근거가
없다. 35C 원문의 "parent/sibling 관계"는 이 판단으로 종결한다(ADR-084 §결정).

``idx_features_geom_gist``는 core geom과 함께 사라지고, subtype 각각이 자기
GiST 인덱스를 갖는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0086_route_area_subtypes"
down_revision: str | Sequence[str] | None = "0085_event_notice_subtypes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feature.feature_routes (
            feature_id varchar NOT NULL,
            feature_uuid uuid NOT NULL,
            kind varchar NOT NULL,
            geom x_extension.geometry(MultiLineString, 4326) NOT NULL,
            route_type varchar NOT NULL,
            geometry_source varchar,
            geometry_status varchar,
            total_distance_meters numeric(12, 2),
            expected_duration_minutes integer,
            difficulty varchar,
            begin_name varchar,
            begin_address varchar,
            end_name varchar,
            end_address varchar,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_feature_routes PRIMARY KEY (feature_id),
            CONSTRAINT ck_feature_routes_kind CHECK (kind = 'route'),
            CONSTRAINT fk_feature_routes_feature_kind
                FOREIGN KEY (feature_id, kind)
                REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
            CONSTRAINT fk_feature_routes_identity_pair
                FOREIGN KEY (feature_id, feature_uuid)
                REFERENCES feature.features (feature_id, feature_uuid)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE feature.feature_areas (
            feature_id varchar NOT NULL,
            feature_uuid uuid NOT NULL,
            kind varchar NOT NULL,
            geom x_extension.geometry(MultiPolygon, 4326) NOT NULL,
            area_kind varchar NOT NULL,
            boundary_source varchar,
            area_square_meters numeric(16, 2),
            regulation_scope varchar,
            administrative_office varchar,
            description text,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_feature_areas PRIMARY KEY (feature_id),
            CONSTRAINT ck_feature_areas_kind CHECK (kind = 'area'),
            CONSTRAINT fk_feature_areas_feature_kind
                FOREIGN KEY (feature_id, kind)
                REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
            CONSTRAINT fk_feature_areas_identity_pair
                FOREIGN KEY (feature_id, feature_uuid)
                REFERENCES feature.features (feature_id, feature_uuid)
                ON DELETE CASCADE
        )
        """
    )
    # 데이터 이관 — prod에서는 0행이지만 다른 환경(테스트 시드·복원본)에 route/area
    # 행이 있을 수 있으므로 조건 없이 옮긴다. ST_Multi로 단일 geometry도 수용한다.
    op.execute(
        """
        INSERT INTO feature.feature_routes (
            feature_id, feature_uuid, kind, geom, route_type, geometry_source,
            geometry_status, total_distance_meters, expected_duration_minutes,
            difficulty, begin_name, begin_address, end_name, end_address, payload
        )
        SELECT
            f.feature_id,
            f.feature_uuid,
            f.kind,
            x_extension.ST_Multi(f.geom)::x_extension.geometry(MultiLineString, 4326),
            COALESCE(f.detail->>'route_type', 'route'),
            f.detail->>'geometry_source',
            f.detail->>'geometry_status',
            CASE
                WHEN f.detail->>'total_distance_meters' ~ '^[0-9]+(\\.[0-9]+)?$'
                THEN (f.detail->>'total_distance_meters')::numeric
            END,
            CASE
                WHEN f.detail->>'expected_duration_minutes' ~ '^[0-9]+$'
                THEN (f.detail->>'expected_duration_minutes')::integer
            END,
            f.detail->>'difficulty',
            f.detail->>'begin_name',
            f.detail->>'begin_address',
            f.detail->>'end_name',
            f.detail->>'end_address',
            COALESCE(f.detail->'payload', '{}'::jsonb)
        FROM feature.features AS f
        WHERE f.kind = 'route' AND f.geom IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO feature.feature_areas (
            feature_id, feature_uuid, kind, geom, area_kind, boundary_source,
            area_square_meters, regulation_scope, administrative_office,
            description, payload
        )
        SELECT
            f.feature_id,
            f.feature_uuid,
            f.kind,
            x_extension.ST_Multi(f.geom)::x_extension.geometry(MultiPolygon, 4326),
            COALESCE(f.detail->>'area_kind', 'area'),
            f.detail->>'boundary_source',
            CASE
                WHEN f.detail->>'area_square_meters' ~ '^[0-9]+(\\.[0-9]+)?$'
                THEN (f.detail->>'area_square_meters')::numeric
            END,
            f.detail->>'regulation_scope',
            f.detail->>'administrative_office',
            f.detail->>'description',
            COALESCE(f.detail->'payload', '{}'::jsonb)
        FROM feature.features AS f
        WHERE f.kind = 'area' AND f.geom IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_feature_routes_geom_gist
            ON feature.feature_routes USING gist (geom)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_feature_areas_geom_gist
            ON feature.feature_areas USING gist (geom)
        """
    )
    # geometry 정본이 옮겨졌으므로 core에서 제거한다. 공개 뷰가 컬럼을 명시
    # 열거하므로 뷰를 먼저 드롭하고 새 정의로 재생성한다.
    op.execute("DROP VIEW IF EXISTS feature.public_features")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_geom_gist")
    op.execute("ALTER TABLE feature.features DROP COLUMN geom")
    op.execute(
        """
        CREATE VIEW feature.public_features AS
        SELECT
            feature_id, kind, name, category, coord, coord_5179,
            address, legal_dong_code, road_name_code, road_address_management_no,
            admin_dong_code, sido_code, sigungu_code, urls, marker_icon,
            marker_color, parent_feature_id, sibling_group_id, detail, raw_refs,
            status, created_at, updated_at, deleted_at, coord_precision_digits,
            data_origin, data_version, user_change_kind, user_change_status,
            user_change_request_id, user_deleted_at, user_deleted_by,
            user_change_reason, row_revision, feature_uuid
        FROM feature.features
        WHERE status = 'active' AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS feature.public_features")
    op.execute(
        "ALTER TABLE feature.features "
        "ADD COLUMN geom x_extension.geometry(Geometry, 4326)"
    )
    op.execute(
        """
        UPDATE feature.features AS f
           SET geom = s.geom
          FROM (
            SELECT feature_id, geom FROM feature.feature_routes
            UNION ALL
            SELECT feature_id, geom FROM feature.feature_areas
          ) AS s
         WHERE s.feature_id = f.feature_id
        """
    )
    op.execute(
        """
        CREATE INDEX idx_features_geom_gist
            ON feature.features USING gist (geom)
            WHERE deleted_at IS NULL AND geom IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE VIEW feature.public_features AS
        SELECT
            feature_id, kind, name, category, coord, coord_5179, geom,
            address, legal_dong_code, road_name_code, road_address_management_no,
            admin_dong_code, sido_code, sigungu_code, urls, marker_icon,
            marker_color, parent_feature_id, sibling_group_id, detail, raw_refs,
            status, created_at, updated_at, deleted_at, coord_precision_digits,
            data_origin, data_version, user_change_kind, user_change_status,
            user_change_request_id, user_deleted_at, user_deleted_by,
            user_change_reason, row_revision, feature_uuid
        FROM feature.features
        WHERE status = 'active' AND deleted_at IS NULL
        """
    )
    op.execute("DROP TABLE IF EXISTS feature.feature_areas")
    op.execute("DROP TABLE IF EXISTS feature.feature_routes")

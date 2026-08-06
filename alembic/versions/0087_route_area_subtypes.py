"""typed subtype 분해 ③ — route·area subtype + geometry 정본 이동 (T-VN-35C, ADR-085).

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
없다. 35C 원문의 "parent/sibling 관계"는 이 판단으로 종결한다(ADR-085 §결정).

``idx_features_geom_gist``는 core geom과 함께 사라지고, subtype 각각이 자기
GiST 인덱스를 갖는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0087_route_area_subtypes"
down_revision: str | Sequence[str] | None = "0086_event_notice_subtypes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ``feature.features_detailed`` — core + subtype 조립의 **단일 정본**.
#
# core에서 ``detail``/``geom``을 제거한 뒤, 응답이 요구하는 그 두 값을 여기서
# subtype으로부터 재구성한다. read 경로는 ``FROM feature.features``를 이 뷰로
# 바꾸는 것만으로 종전과 같은 모양을 얻는다 — 조립 규칙이 흩어지지 않는다.
#
# 조립은 **원본 바이트와 동등**해야 한다(전수 md5 대조로 고정). 실측 결과
# 종전 detail은 NULL 키를 **보존**하므로(``"biz_number": null``) strip 하지
# 않는다 — 특히 ``jsonb_strip_nulls``는 재귀적이라 ``payload``/``facility_info``
# 내부의 정당한 null까지 지워 provider 원본을 훼손한다. ``feature_id``는 DTO
# detail이 항상 갖던 키라 조립에도 포함한다. price/weather는 CASE 미매치 →
# NULL → ``COALESCE``로 ``{}``가 되어 종전과 같다.
_FEATURES_DETAILED_SQL = """
SELECT
    f.feature_id,
    f.feature_uuid,
    f.kind,
    f.name,
    f.category,
    f.coord,
    f.coord_5179,
    f.coord_precision_digits,
    f.address,
    f.legal_dong_code,
    f.road_name_code,
    f.road_address_management_no,
    f.admin_dong_code,
    f.sido_code,
    f.sigungu_code,
    f.urls,
    f.marker_icon,
    f.marker_color,
    f.parent_feature_id,
    f.sibling_group_id,
    f.raw_refs,
    f.status,
    f.created_at,
    f.updated_at,
    f.deleted_at,
    f.data_origin,
    f.data_version,
    f.user_change_kind,
    f.user_change_status,
    f.user_change_request_id,
    f.user_deleted_at,
    f.user_deleted_by,
    f.user_change_reason,
    f.row_revision,
    COALESCE(r.geom, a.geom) AS geom,
    COALESCE(
        (
            CASE f.kind
                WHEN 'place' THEN CASE WHEN p.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', f.feature_id,
                    'place_kind', p.place_kind,
                    'phones', to_jsonb(p.phones),
                    'biz_number', p.biz_number,
                    'license_date', to_jsonb(p.license_date),
                    'business_hours', p.business_hours,
                    'facility_info', p.facility_info,
                    'reviews_link', p.reviews_link,
                    'payload', p.payload
                ) END
                WHEN 'event' THEN CASE WHEN e.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', f.feature_id,
                    'event_kind', e.event_kind,
                    'starts_on', to_jsonb(e.starts_on),
                    'ends_on', to_jsonb(e.ends_on),
                    'timezone', e.timezone,
                    'opening_hours', e.opening_hours,
                    'venue_name', e.venue_name,
                    'tel', e.tel,
                    'content_id', e.content_id,
                    'content_type_id', e.content_type_id,
                    'area_code', e.area_code,
                    'sigungu_code', e.sigungu_code,
                    'payload', e.payload
                ) END
                WHEN 'notice' THEN CASE WHEN n.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', f.feature_id,
                    'notice_type', n.notice_type,
                    'severity', n.severity,
                    -- timestamptz를 그냥 to_jsonb 하면 문자열이 **세션 TimeZone
                    -- GUC에 의존**한다(실측: 같은 행이 Asia/Seoul 세션에서
                    -- '...+09:00', UTC 세션에서 '...+00:00'). 서버 설정이 다른
                    -- 인스턴스가 같은 공지에 다른 문자열을 돌려주게 된다.
                    -- KST 고정 렌더로 세션 비의존을 만든다(SKILL.md 규칙 17 —
                    -- 모든 datetime은 KST aware). 마이크로초가 0이면 생략해
                    -- Python ``datetime.isoformat()``과 바이트까지 같다(prod
                    -- valid_start_time 145/145 무변경).
                    'valid_start_time', to_jsonb(
                        to_char(
                            n.valid_start_time AT TIME ZONE 'Asia/Seoul',
                            CASE
                                WHEN EXTRACT(microsecond FROM n.valid_start_time)::bigint
                                     % 1000000 = 0
                                THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'
                                ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"'
                            END
                        )
                    ),
                    'valid_end_time', to_jsonb(
                        to_char(
                            n.valid_end_time AT TIME ZONE 'Asia/Seoul',
                            CASE
                                WHEN EXTRACT(microsecond FROM n.valid_end_time)::bigint
                                     % 1000000 = 0
                                THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'
                                ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"'
                            END
                        )
                    ),
                    'source_agency', n.source_agency,
                    'officer_name', n.officer_name,
                    'payload', n.payload
                ) END
                WHEN 'route' THEN CASE WHEN r.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', f.feature_id,
                    'route_type', r.route_type,
                    'geometry_source', r.geometry_source,
                    'geometry_status', r.geometry_status,
                    'total_distance_meters', to_jsonb(r.total_distance_meters::text),
                    'expected_duration_minutes', r.expected_duration_minutes,
                    'difficulty', r.difficulty,
                    'begin_name', r.begin_name,
                    'begin_address', r.begin_address,
                    'end_name', r.end_name,
                    'end_address', r.end_address,
                    'payload', r.payload
                ) END
                WHEN 'area' THEN CASE WHEN a.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                    'feature_id', f.feature_id,
                    'area_kind', a.area_kind,
                    'boundary_source', a.boundary_source,
                    'area_square_meters', to_jsonb(a.area_square_meters::text),
                    'regulation_scope', a.regulation_scope,
                    'administrative_office', a.administrative_office,
                    'description', a.description,
                    'payload', a.payload
                ) END
            END
        ),
        '{}'::jsonb
    ) AS detail
FROM feature.features AS f
LEFT JOIN feature.feature_places AS p ON p.feature_id = f.feature_id
LEFT JOIN feature.feature_events AS e ON e.feature_id = f.feature_id
LEFT JOIN feature.feature_notices AS n ON n.feature_id = f.feature_id
LEFT JOIN feature.feature_routes AS r ON r.feature_id = f.feature_id
LEFT JOIN feature.feature_areas AS a ON a.feature_id = f.feature_id
"""


def preflight_or_raise(label: str, probe_sql: str, remedy: str) -> None:
    """이관 불가 행을 feature_id와 함께 알리고 멈춘다 (근거는 0084의 같은 함수).

    0086에서 특히 중요하다 — 여기서 건너뛴 행은 곧바로 오는
    ``DROP COLUMN detail``/``geom``으로 **복구 불가능하게** 사라진다.
    downgrade도 subtype에서 역조립하므로 되살릴 수 없다.
    """
    quoted_label = label.replace("'", "''")
    quoted_remedy = remedy.replace("'", "''")
    op.execute(
        f"""
        DO $preflight$
        DECLARE
            offenders text;
            total bigint;
        BEGIN
            SELECT count(*) INTO total FROM ({probe_sql}) AS probe;
            IF total = 0 THEN
                RETURN;
            END IF;
            SELECT string_agg(feature_id, ', ' ORDER BY feature_id)
              INTO offenders
              FROM (
                  SELECT feature_id FROM ({probe_sql}) AS probe
                  ORDER BY feature_id LIMIT 20
              ) AS sample;
            RAISE EXCEPTION
                'T-VN-35 preflight: % (% row(s)); sample: %',
                '{quoted_label}', total, offenders
              USING HINT = '{quoted_remedy}';
        END
        $preflight$;
        """
    )


def upgrade() -> None:
    # geometry가 subtype의 NOT NULL 컬럼이 되므로, geometry 없는 route/area는
    # 새 모델에서 **표현 불가능**하다(결정 5의 요점 — "geometry가 필수인 kind"가
    # 술어가 아니라 구조로 갈린다). 그런 행을 조용히 건너뛰면 detail이 통째로
    # 소실되므로 fail-close한다. 이 상태는 과거에 실재했다 —
    # ``inactivate_geometryless_area_features_by_source``가 그것 때문에 있고,
    # 그 정리 경로는 area·특정 source_link·non-user_request만 훑어 전부를 지우지
    # 못한다. prod 실측 0건.
    preflight_or_raise(
        "route/area rows without geometry cannot be represented after 0086",
        "SELECT feature_id FROM feature.features "
        "WHERE kind IN ('route', 'area') AND geom IS NULL",
        "Delete them, or supply geometry, then re-run. "
        "kortravelmap.client.inactivate_geometryless_area_features_by_source "
        "handles the provider-sourced area subset.",
    )
    # 반대 방향 — geometry 정본이 route/area subtype으로 옮겨가므로 다른 kind의
    # geom은 담을 곳이 없다. DTO도 이 PR에서 같은 계약으로 좁힌다.
    preflight_or_raise(
        "geometry on kinds other than route/area has no destination after 0086",
        "SELECT feature_id FROM feature.features "
        "WHERE kind NOT IN ('route', 'area') AND geom IS NOT NULL",
        "Clear geom on these rows (geometry belongs to route/area only), "
        "then re-run the upgrade.",
    )
    # subtype의 typed geometry(MULTILINESTRING/MULTIPOLYGON)로 cast되지 않는
    # geometry는 ``ST_Multi(...)::geometry(...)``가 통째로 abort시킨다 — 실측:
    # ``ST_Multi('POINT(127 37)')::geometry(MultiLineString,4326)`` → type mismatch.
    # core는 GENERIC이라 kind별 타입을 강제한 적이 없다.
    preflight_or_raise(
        "route geometry must be (MULTI)LINESTRING to become feature_routes.geom",
        "SELECT feature_id FROM feature.features "
        "WHERE kind = 'route' AND geom IS NOT NULL "
        "AND x_extension.GeometryType(geom) "
        "NOT IN ('LINESTRING', 'MULTILINESTRING')",
        "Fix or remove the geometry on these rows, then re-run the upgrade.",
    )
    preflight_or_raise(
        "area geometry must be (MULTI)POLYGON to become feature_areas.geom",
        "SELECT feature_id FROM feature.features "
        "WHERE kind = 'area' AND geom IS NOT NULL "
        "AND x_extension.GeometryType(geom) NOT IN ('POLYGON', 'MULTIPOLYGON')",
        "Fix or remove the geometry on these rows, then re-run the upgrade.",
    )
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
            total_distance_meters numeric,
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
            area_square_meters numeric,
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
    # 행이 있을 수 있으므로 조건 없이 옮긴다. ST_Multi로 단일 geometry도 수용하고,
    # 이관 불가 행은 위 preflight가 이미 걸러냈다(조용한 skip 없음).
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
        WHERE f.kind = 'route'
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
        WHERE f.kind = 'area'
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
    # ── 단일 정본 전환: core detail·geom 제거 ────────────────────────────
    #
    # subtype이 kind별 값의 **유일한 정본**이 된다(shadow 병행 폐기 — ADR-085
    # 결정 4 개정). 이중 쓰기·drift 관측이라는 우회 복잡도가 통째로 사라지고,
    # "DB가 kind 계약을 모른다"는 문제의 뿌리(자유 JSONB)가 제거된다.
    #
    # 응답의 ``detail``/``geom``은 아래 ``features_detailed`` 뷰가 subtype에서
    # 조립한다 — read 경로는 ``FROM feature.features``를 이 뷰로 바꾸면 종전과
    # 같은 모양을 얻는다(조립 규칙의 단일 정본).
    op.execute("DROP VIEW IF EXISTS feature.public_features")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_geom_gist")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_opening_hours_keyset")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_yt_channel_id")
    op.execute("DROP INDEX IF EXISTS feature.idx_features_yt_playlist_id")
    op.execute("ALTER TABLE feature.features DROP COLUMN geom")
    op.execute("ALTER TABLE feature.features DROP COLUMN detail")

    op.execute(f"CREATE VIEW feature.features_detailed AS {_FEATURES_DETAILED_SQL}")
    op.execute(
        """
        CREATE VIEW feature.public_features AS
        SELECT *
        FROM feature.features_detailed
        WHERE status = 'active' AND deleted_at IS NULL
        """
    )


def downgrade() -> None:
    """core detail/geom 복원 — subtype 값을 되돌려 담는다.

    subtype이 정본이 된 뒤이므로 downgrade는 **역조립**이다: 뷰가 만들던
    detail JSONB를 그대로 core 컬럼에 물질화하고 geom을 되돌린다. 무손실이다
    (뷰의 조립 규칙과 같은 식을 쓴다).
    """
    op.execute("DROP VIEW IF EXISTS feature.public_features")
    op.execute("DROP VIEW IF EXISTS feature.features_detailed")
    op.execute(
        "ALTER TABLE feature.features "
        "ADD COLUMN detail jsonb NOT NULL DEFAULT '{}'::jsonb, "
        "ADD COLUMN geom x_extension.geometry(Geometry, 4326)"
    )
    op.execute(
        f"""
        UPDATE feature.features AS f
           SET detail = d.detail, geom = d.geom
          FROM ({_FEATURES_DETAILED_SQL}) AS d
         WHERE d.feature_id = f.feature_id
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
        CREATE INDEX idx_features_opening_hours_keyset
            ON feature.features (feature_id)
            WHERE deleted_at IS NULL
              AND detail IS NOT NULL
              AND detail <> '{}'::jsonb
              AND detail ?| ARRAY['business_hours','opening_hours']
        """
    )
    op.execute(
        """
        CREATE INDEX idx_features_yt_channel_id
            ON feature.features
               ((detail #>> '{payload,kor_travel_concierge,youtube,channel_id}'))
            WHERE (detail #>> '{payload,kor_travel_concierge,youtube,channel_id}')
                  IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_features_yt_playlist_id
            ON feature.features
               ((detail #>> '{payload,kor_travel_concierge,youtube,playlist_id}'))
            WHERE (detail #>> '{payload,kor_travel_concierge,youtube,playlist_id}')
                  IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE VIEW feature.public_features AS
        SELECT * FROM feature.features
        WHERE status = 'active' AND deleted_at IS NULL
        """
    )
    op.execute("DROP TABLE IF EXISTS feature.feature_areas")
    op.execute("DROP TABLE IF EXISTS feature.feature_routes")

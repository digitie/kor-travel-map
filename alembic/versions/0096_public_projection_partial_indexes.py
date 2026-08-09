# ruff: noqa: E501
"""T-VN-34B 공개 projection·부분 index·route/area ready spine.

Revision ID: 0096_tvn34_public_projection
Revises: 0095_tvn34_state_spine

공개 여부의 유일한 정본은 ``feature.features``의 세 상태축이다. point/core의
공개 access path는 그 술어를 직접 partial predicate로 쓰고, state가 다른
relation에 있는 route/area geometry만 DB 소유 ``public_ready`` cache를 쓴다.
``public_ready``는 visibility 정본이 아니며 public view의 core predicate가
마지막 fence를 계속 맡는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0096_tvn34_public_projection"
down_revision: str | Sequence[str] | None = "0095_tvn34_state_spine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PUBLIC_STATE_PREDICATE = """
lifecycle_state = 'active'
  AND publication_state = 'published'
  AND quality_state = 'valid'
""".strip()


_SUBTYPE_READY_FUNCTION_SQL = r"""
CREATE FUNCTION feature.derive_subtype_public_ready()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_lifecycle_state text;
    v_publication_state text;
    v_quality_state text;
BEGIN
    -- parent lock ordering is always feature row → subtype row.  This makes a
    -- state transition racing a subtype insert/reattachment serialize before
    -- the cached flag is derived.
    SELECT lifecycle_state, publication_state, quality_state
      INTO v_lifecycle_state, v_publication_state, v_quality_state
      FROM feature.features
     WHERE feature_id = NEW.feature_id
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'route/area public projection requires parent feature %', NEW.feature_id
            USING ERRCODE = '23503', CONSTRAINT = 'fk_feature_subtype_public_ready_parent';
    END IF;

    -- Never accept a caller supplied cache value, including a direct UPDATE by
    -- a privileged migration session.  Core state remains the sole source.
    NEW.public_ready := v_lifecycle_state = 'active'
        AND v_publication_state = 'published'
        AND v_quality_state = 'valid';
    RETURN NEW;
END;
$$;
"""


_SYNC_SUBTYPE_READY_FUNCTION_SQL = r"""
CREATE FUNCTION feature.sync_subtype_public_ready()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    v_public_ready boolean;
BEGIN
    -- The UPDATE which invoked this trigger already holds NEW's parent row
    -- lock.  Keep it until the two subtype cache rows have been refreshed.
    v_public_ready := NEW.lifecycle_state = 'active'
        AND NEW.publication_state = 'published'
        AND NEW.quality_state = 'valid';

    UPDATE feature.feature_routes
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    UPDATE feature.feature_areas
       SET public_ready = v_public_ready
     WHERE feature_id = NEW.feature_id
       AND public_ready IS DISTINCT FROM v_public_ready;
    RETURN NULL;
END;
$$;
"""


def upgrade() -> None:
    # ``features_detailed`` is the typed-subtype assembly surface.  Do not use
    # SELECT * here: state/provenance columns must never silently become public.
    op.execute(
        """
        CREATE OR REPLACE VIEW feature.public_features AS
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
            f.geom,
            f.detail
        FROM feature.features_detailed AS f
        JOIN feature.features AS state ON state.feature_id = f.feature_id
        WHERE state.lifecycle_state = 'active'
          AND state.publication_state = 'published'
          AND state.quality_state = 'valid'
        """
    )

    # All public core access paths use the exact same three-axis predicate.
    # Existing names are preserved because readers and prewarm configuration
    # intentionally name their physical hot path.
    for index_name in (
        "idx_features_coord_gist",
        "idx_features_coord_5179_gist",
        "idx_features_public_weather_coord_5179_gist",
        "idx_features_kind_category",
        "idx_features_updated_keyset",
        "idx_features_lower_name_keyset",
        "idx_features_name_trgm",
        "idx_features_sigungu",
    ):
        op.execute(f"DROP INDEX IF EXISTS feature.{index_name}")

    op.execute(
        f"""
        CREATE INDEX idx_features_coord_gist
            ON feature.features USING gist (coord)
            WHERE {_PUBLIC_STATE_PREDICATE}
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_features_coord_5179_gist
            ON feature.features USING gist (coord_5179)
            WHERE {_PUBLIC_STATE_PREDICATE}
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_features_public_weather_coord_5179_gist
            ON feature.features USING gist (coord_5179)
            WHERE {_PUBLIC_STATE_PREDICATE}
              AND kind = 'weather'
              AND coord_5179 IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_features_kind_category
            ON feature.features (kind, category)
            WHERE {_PUBLIC_STATE_PREDICATE}
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_features_updated_keyset
            ON feature.features (updated_at DESC, feature_id DESC)
            WHERE {_PUBLIC_STATE_PREDICATE}
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_features_lower_name_keyset
            ON feature.features (lower(name), feature_id)
            WHERE {_PUBLIC_STATE_PREDICATE}
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_features_name_trgm
            ON feature.features USING gin (name x_extension.gin_trgm_ops)
            WHERE {_PUBLIC_STATE_PREDICATE}
        """
    )
    op.execute(
        f"""
        CREATE INDEX idx_features_sigungu
            ON feature.features (sigungu_code, kind)
            WHERE {_PUBLIC_STATE_PREDICATE}
              AND sigungu_code IS NOT NULL
        """
    )

    # Geometry lies on route/area subtype relations while state lives on their
    # parent.  PostgreSQL partial indexes cannot join the parent predicate, so
    # these two (and only these two) relations receive a derived cache flag.
    for table_name in ("feature_routes", "feature_areas"):
        op.execute(
            f"ALTER TABLE feature.{table_name} "
            "ADD COLUMN public_ready boolean NOT NULL DEFAULT false"
        )
    op.execute(
        """
        UPDATE feature.feature_routes AS subtype
           SET public_ready = feature.lifecycle_state = 'active'
               AND feature.publication_state = 'published'
               AND feature.quality_state = 'valid'
          FROM feature.features AS feature
         WHERE feature.feature_id = subtype.feature_id
        """
    )
    op.execute(
        """
        UPDATE feature.feature_areas AS subtype
           SET public_ready = feature.lifecycle_state = 'active'
               AND feature.publication_state = 'published'
               AND feature.quality_state = 'valid'
          FROM feature.features AS feature
         WHERE feature.feature_id = subtype.feature_id
        """
    )
    for index_name in ("idx_feature_routes_geom_gist", "idx_feature_areas_geom_gist"):
        op.execute(f"DROP INDEX IF EXISTS feature.{index_name}")
    op.execute(
        "CREATE INDEX idx_feature_routes_geom_gist "
        "ON feature.feature_routes USING gist (geom) WHERE public_ready"
    )
    op.execute(
        "CREATE INDEX idx_feature_areas_geom_gist "
        "ON feature.feature_areas USING gist (geom) WHERE public_ready"
    )

    op.execute(_SUBTYPE_READY_FUNCTION_SQL)
    op.execute(_SYNC_SUBTYPE_READY_FUNCTION_SQL)
    op.execute(
        "ALTER FUNCTION feature.derive_subtype_public_ready() "
        "OWNER TO ktm_feature_state_procedure_owner"
    )
    op.execute(
        "ALTER FUNCTION feature.sync_subtype_public_ready() "
        "OWNER TO ktm_feature_state_procedure_owner"
    )
    for table_name in ("feature_routes", "feature_areas"):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_public_ready "
            f"BEFORE INSERT OR UPDATE ON feature.{table_name} "
            "FOR EACH ROW EXECUTE FUNCTION feature.derive_subtype_public_ready()"
        )
    op.execute(
        "CREATE TRIGGER trg_features_sync_subtype_public_ready "
        "AFTER UPDATE OF lifecycle_state, publication_state, quality_state "
        "ON feature.features FOR EACH ROW "
        "WHEN (OLD.lifecycle_state IS DISTINCT FROM NEW.lifecycle_state "
        "OR OLD.publication_state IS DISTINCT FROM NEW.publication_state "
        "OR OLD.quality_state IS DISTINCT FROM NEW.quality_state) "
        "EXECUTE FUNCTION feature.sync_subtype_public_ready()"
    )

    # Runtime gets only business columns.  A column grant deliberately does
    # not make table-level UPDATE true, and the DB-owned projection flag is not
    # in either list.
    route_columns = (
        "feature_id, feature_uuid, kind, geom, route_type, geometry_source, "
        "geometry_status, total_distance_meters, expected_duration_minutes, "
        "difficulty, begin_name, begin_address, end_name, end_address, payload"
    )
    area_columns = (
        "feature_id, feature_uuid, kind, geom, area_kind, boundary_source, "
        "area_square_meters, regulation_scope, administrative_office, description, payload"
    )
    for table_name, columns in (("feature_routes", route_columns), ("feature_areas", area_columns)):
        op.execute(f"REVOKE ALL ON feature.{table_name} FROM PUBLIC, ktm_feature_runtime")
        op.execute(f"GRANT SELECT ON feature.{table_name} TO ktm_feature_runtime")
        op.execute(f"GRANT INSERT ({columns}) ON feature.{table_name} TO ktm_feature_runtime")
        op.execute(f"GRANT UPDATE ({columns}) ON feature.{table_name} TO ktm_feature_runtime")
        op.execute(f"GRANT DELETE ON feature.{table_name} TO ktm_feature_runtime")
        op.execute(
            f"GRANT SELECT (feature_id, public_ready), UPDATE (public_ready) "
            f"ON feature.{table_name} "
            "TO ktm_feature_state_procedure_owner"
        )
    op.execute(
        "REVOKE ALL ON FUNCTION feature.derive_subtype_public_ready() "
        "FROM PUBLIC, ktm_feature_runtime"
    )
    op.execute(
        "REVOKE ALL ON FUNCTION feature.sync_subtype_public_ready() "
        "FROM PUBLIC, ktm_feature_runtime"
    )


def downgrade() -> None:
    raise RuntimeError("0096 is forward-only; rebuild with provider ETL")

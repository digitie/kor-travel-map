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
    IF TG_OP = 'UPDATE' THEN
        -- Reattachment would make one UPDATE hold a subtype tuple before it
        -- waits on a different parent.  No normal writer supports it, so make
        -- the 1:1 subtype identity immutable instead of inventing a broad
        -- relation lock or a retry protocol.
        IF NEW.feature_id IS DISTINCT FROM OLD.feature_id
           OR NEW.feature_uuid IS DISTINCT FROM OLD.feature_uuid
           OR NEW.kind IS DISTINCT FROM OLD.kind THEN
            RAISE EXCEPTION 'route/area subtype identity is immutable'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_feature_subtype_identity_immutable';
        END IF;

        -- Payload/geometry updates need no parent read: a core axis transition
        -- is the sole writer that changes an existing cache row.  This removes
        -- the former subtype tuple → parent tuple edge.  A direct privileged
        -- public_ready attempt is still overwritten below when it differs.
        IF NEW.public_ready IS NOT DISTINCT FROM OLD.public_ready THEN
            RETURN NEW;
        END IF;
    END IF;

    -- INSERT must serialize with a concurrent parent state transition so a
    -- newly attached route/area gets the current tuple.  An existing subtype
    -- update reaches here only for a supplied cache mutation; its lock-free
    -- parent read recomputes the DB-owned value, while core sync sees its own
    -- updated parent row in the same transaction.
    IF TG_OP = 'INSERT' THEN
        SELECT lifecycle_state, publication_state, quality_state
          INTO v_lifecycle_state, v_publication_state, v_quality_state
          FROM feature.features
         WHERE feature_id = NEW.feature_id
         FOR UPDATE;
    ELSE
        SELECT lifecycle_state, publication_state, quality_state
          INTO v_lifecycle_state, v_publication_state, v_quality_state
          FROM feature.features
         WHERE feature_id = NEW.feature_id;
    END IF;
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
    # Keep the core alias that has the three-axis predicate as the alias that
    # supplies coord/text/category/keyset columns.  Joining ``features_detailed``
    # to a second state alias made actual public reader predicates non-implying
    # for the core partial indexes.  Detail/geom still come from the one typed
    # assembly view, but all core output is selected from the predicate alias.
    # Do not use SELECT *: state/provenance columns must never silently become
    # public.
    op.execute(
        """
        CREATE OR REPLACE VIEW feature.public_features AS
        SELECT
            core.feature_id,
            core.feature_uuid,
            core.kind,
            core.name,
            core.category,
            core.coord,
            core.coord_5179,
            core.coord_precision_digits,
            core.address,
            core.legal_dong_code,
            core.road_name_code,
            core.road_address_management_no,
            core.admin_dong_code,
            core.sido_code,
            core.sigungu_code,
            core.urls,
            core.marker_icon,
            core.marker_color,
            core.parent_feature_id,
            core.sibling_group_id,
            core.raw_refs,
            core.status,
            core.created_at,
            core.updated_at,
            core.deleted_at,
            core.data_origin,
            core.data_version,
            core.user_change_kind,
            core.user_change_status,
            core.user_change_request_id,
            core.user_deleted_at,
            core.user_deleted_by,
            core.user_change_reason,
            core.row_revision,
            detailed.geom,
            detailed.detail
        FROM feature.features AS core
        JOIN feature.features_detailed AS detailed
          ON detailed.feature_id = core.feature_id
        WHERE core.lifecycle_state = 'active'
          AND core.publication_state = 'published'
          AND core.quality_state = 'valid'
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

    # Runtime gets only business columns.  INSERT needs the immutable subtype
    # identity, but ordinary UPDATE must not reattach/delete a subtype row.  A
    # column grant deliberately does not make table-level UPDATE true, and the
    # DB-owned projection flag is not in either list.
    route_insert_columns = (
        "feature_id, feature_uuid, kind, geom, route_type, geometry_source, "
        "geometry_status, total_distance_meters, expected_duration_minutes, "
        "difficulty, begin_name, begin_address, end_name, end_address, payload"
    )
    route_update_columns = (
        "geom, route_type, geometry_source, geometry_status, total_distance_meters, "
        "expected_duration_minutes, difficulty, begin_name, begin_address, end_name, "
        "end_address, payload"
    )
    area_insert_columns = (
        "feature_id, feature_uuid, kind, geom, area_kind, boundary_source, "
        "area_square_meters, regulation_scope, administrative_office, description, payload"
    )
    area_update_columns = (
        "geom, area_kind, boundary_source, area_square_meters, regulation_scope, "
        "administrative_office, description, payload"
    )
    for table_name, insert_columns, update_columns in (
        ("feature_routes", route_insert_columns, route_update_columns),
        ("feature_areas", area_insert_columns, area_update_columns),
    ):
        op.execute(f"REVOKE ALL ON feature.{table_name} FROM PUBLIC, ktm_feature_runtime")
        op.execute(f"GRANT SELECT ON feature.{table_name} TO ktm_feature_runtime")
        op.execute(
            f"GRANT INSERT ({insert_columns}) ON feature.{table_name} "
            "TO ktm_feature_runtime"
        )
        op.execute(
            f"GRANT UPDATE ({update_columns}) ON feature.{table_name} "
            "TO ktm_feature_runtime"
        )
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
    # Reconciliation revokes all feature relations after every migration.
    # These two views are the only reader boundary and must be regranted here
    # as well as in the closed runtime inventory.
    op.execute(
        "GRANT SELECT ON feature.public_features, feature.features_detailed "
        "TO ktm_feature_runtime"
    )


def downgrade() -> None:
    raise RuntimeError("0096 is forward-only; rebuild with provider ETL")

CREATE FUNCTION feature.derive_subtype_public_ready() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
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


ALTER FUNCTION feature.derive_subtype_public_ready() OWNER TO ktm_feature_state_procedure_owner;

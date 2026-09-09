-- 이 사이드카는 자기 역할 창을 스스로 연다.
--
-- 바깥에서 `SET ROLE`로 묶으면 순서에 결박된다 — 자기 창을 가진 사이드카가 끝에서
-- 스키마 소유자로 되돌리는 순간, 뒤따르는 파일은 바깥 그룹이 지정한 롤이 아니라
-- 스키마 소유자로 실행된다. 2026-09-09 n150 실행이 그것을 잡았다
-- (`must be owner of function derive_subtype_public_ready`).
--
-- 롤은 NOINHERIT라 멤버십만으로는 소유자 검사를 통과하지 못한다. `feature` 스키마는
-- 모든 소유자 롤이 `ALL`을 가지므로(alembic/head-schema.sql:24731-24737) 이 창 안에서
-- DROP·CREATE·GRANT가 모두 성립한다.
SET ROLE ktm_feature_state_procedure_owner;

CREATE OR REPLACE FUNCTION feature.derive_subtype_public_ready() RETURNS trigger
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


DO $t39_owner$
DECLARE
    had_create boolean;
BEGIN
    -- 소유권 이전은 새 소유자가 담는 스키마의 CREATE 권한을 요구한다.
    -- 302_m03_child_issuance.py:324-330이 `ops`에서 같은 함정을 만났다. 다만 그
    -- 형태는 이미 CREATE를 가진 롤에서 권한을 빼앗으므로, 여기서는 **자기 상태를
    -- 보고** 되돌린다. 2026-09-09 n150 첫 실행이 이것을 잡았다
    -- (`permission denied for schema ops`).
    had_create := has_schema_privilege('ktm_feature_state_procedure_owner', 'feature', 'CREATE');
    IF NOT had_create THEN
        EXECUTE 'GRANT CREATE ON SCHEMA feature TO ktm_feature_state_procedure_owner';
    END IF;
    EXECUTE 'ALTER FUNCTION feature.derive_subtype_public_ready() OWNER TO ktm_feature_state_procedure_owner';
    IF NOT had_create THEN
        EXECUTE 'REVOKE CREATE ON SCHEMA feature FROM ktm_feature_state_procedure_owner';
    END IF;
END
$t39_owner$;

SET ROLE ktm_feature_schema_owner;

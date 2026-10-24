CREATE FUNCTION ops.prune_scoped_feature_write_attempts(p_before timestamptz,p_limit integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
DECLARE v_members integer; v_attempts integer;
BEGIN
    PERFORM ops._arm_scoped_feature_write_deadline();
    PERFORM ops.lock_scoped_feature_write_protocol(false);
    IF p_before IS NULL OR p_before>clock_timestamp()-interval '1 day' OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 256 THEN
        RAISE EXCEPTION 'invalid bounded terminal retention' USING ERRCODE='23514';
    END IF;
    WITH candidates AS MATERIALIZED (
        SELECT m.attempt_id,m.ordinal FROM ops.feature_write_manifests m JOIN ops.feature_write_attempts a USING(attempt_id)
        WHERE a.status IN ('completed','cancelled') AND a.updated_at<p_before
        ORDER BY a.updated_at,a.attempt_id,m.ordinal LIMIT p_limit FOR UPDATE OF m SKIP LOCKED
    ), deleted AS (DELETE FROM ops.feature_write_manifests m USING candidates c WHERE m.attempt_id=c.attempt_id AND m.ordinal=c.ordinal RETURNING 1)
    SELECT count(*) INTO v_members FROM deleted;
    WITH candidates AS MATERIALIZED (
        SELECT a.attempt_id FROM ops.feature_write_attempts a WHERE a.status IN ('completed','cancelled') AND a.updated_at<p_before
        AND NOT EXISTS(SELECT 1 FROM ops.feature_write_manifests m WHERE m.attempt_id=a.attempt_id)
        ORDER BY a.updated_at,a.attempt_id LIMIT 8 FOR UPDATE SKIP LOCKED
    ), deleted AS (DELETE FROM ops.feature_write_attempts a USING candidates c WHERE a.attempt_id=c.attempt_id RETURNING 1)
    SELECT count(*) INTO v_attempts FROM deleted;
    RETURN jsonb_build_object('manifest_rows',v_members,'attempt_rows',v_attempts);
END;
$$;

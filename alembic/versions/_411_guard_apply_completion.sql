CREATE FUNCTION ops._guard_scoped_feature_write_completion()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path TO pg_catalog AS $$
BEGIN
    IF EXISTS(SELECT 1 FROM ops.feature_write_attempts WHERE attempt_id=NEW.attempt_id AND status='applying') THEN
        RAISE EXCEPTION 'apply transaction must finish before commit' USING ERRCODE='23514';
    END IF;
    RETURN NULL;
END;
$$;

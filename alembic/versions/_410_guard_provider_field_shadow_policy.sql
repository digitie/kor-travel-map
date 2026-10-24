CREATE FUNCTION feature.guard_provider_field_shadow_policy() RETURNS trigger
LANGUAGE plpgsql SET search_path TO pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'shadow policy revision and complete fieldset are immutable' USING ERRCODE='23514';
END;
$$;

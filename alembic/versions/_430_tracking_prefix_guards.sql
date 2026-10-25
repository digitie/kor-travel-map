-- SchemaOwner 정의. typed owner 우회보다 먼저 held-prefix만 검사한다.
-- migrationwrapper/REVOKE/활성화는 Root의 D/복구 합성과 같은 수용 단위다.
CREATE OR REPLACE FUNCTION ops.reject_provider_feature_operation_raw_dml() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
DECLARE
  v_provider boolean;
  v_need_final boolean;
  v_protocol_held boolean;
  v_protocol_exclusive boolean;
  v_lineage_held boolean;
  v_kind text;
BEGIN
  v_kind := CASE WHEN TG_OP = 'DELETE' THEN OLD.kind ELSE NEW.kind END;
  v_provider := v_kind IN ('provider_feature_load_run','provider_feature_load');
  IF TG_OP='UPDATE' THEN
    v_provider := v_provider OR OLD.kind IN ('provider_feature_load_run','provider_feature_load');
  END IF;
  v_need_final := TG_OP='DELETE';
  IF TG_OP<>'DELETE' THEN
    v_need_final := v_need_final OR NEW.status IN ('done','failed','cancelled');
  END IF;
  IF TG_OP<>'INSERT' THEN
    v_need_final := v_need_final OR OLD.status IN ('done','failed','cancelled');
  END IF;
  IF v_provider THEN
    -- 관측만 한다. tuple 뒤 새 blocking L/P를 요청하지 않는다.
    SELECT COALESCE(bool_or(mode IN ('ShareLock','ExclusiveLock')),false),
           COALESCE(bool_or(mode='ExclusiveLock'),false)
      INTO v_protocol_held,v_protocol_exclusive
      FROM pg_catalog.pg_locks
     WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
       AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
       AND classid=1369104691 AND objid=115 AND objsubid=2;
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_locks
         WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
           AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
           AND classid=1590807301 AND objid=1746797985 AND objsubid=1
           AND mode='ExclusiveLock'
    ) INTO v_lineage_held;
    IF NOT v_lineage_held
       OR (v_protocol_held AND NOT v_protocol_exclusive)
       OR (v_need_final AND NOT v_protocol_exclusive) THEN
        RAISE EXCEPTION 'provider tracking write requires its existing lineage/protocol prefix'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_write_prefix';
    END IF;
  END IF;
  IF current_user = 'ktm_curation_command_owner'
     OR EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  v_kind := CASE WHEN TG_OP = 'DELETE' THEN OLD.kind ELSE NEW.kind END;
  IF v_kind IN ('provider_feature_load_run', 'provider_feature_load')
     OR (TG_OP = 'UPDATE' AND OLD.kind IN (
       'provider_feature_load_run', 'provider_feature_load'
     )) THEN
    IF TG_OP = 'UPDATE'
       AND session_user = 'ktm_feature_service'
       AND NEW.cancellation_id IS NOT NULL
       AND EXISTS (
         SELECT 1
         FROM ops.pipeline_cancellation_members AS member
         JOIN ops.pipeline_cancellations AS attempt
           ON attempt.cancellation_id = member.cancellation_id
         WHERE member.cancellation_id = NEW.cancellation_id
           AND member.job_id = NEW.job_id
           AND attempt.status = 'in_progress'
       )
       AND to_jsonb(NEW) - ARRAY[
         'cancellation_id','cancellation_requested_at',
         'cancellation_requested_by','cancellation_reason'
       ]::text[]
       = to_jsonb(OLD) - ARRAY[
         'cancellation_id','cancellation_requested_at',
         'cancellation_requested_by','cancellation_reason'
       ]::text[] THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'provider feature operations require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_operation_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;

CREATE OR REPLACE FUNCTION ops.reject_provider_feature_membership_raw_dml() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
DECLARE
  v_provider boolean;
  v_need_final boolean;
  v_protocol_held boolean;
  v_protocol_exclusive boolean;
  v_lineage_held boolean;
  v_job_id uuid;
BEGIN
  v_job_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.job_id ELSE NEW.job_id END;
  SELECT EXISTS (SELECT 1 FROM ops.import_jobs job WHERE job.job_id=v_job_id
    AND job.kind IN ('provider_feature_load_run','provider_feature_load')) INTO v_provider;
  IF TG_OP='UPDATE' THEN
    v_provider := v_provider OR EXISTS (SELECT 1 FROM ops.import_jobs job
      WHERE job.job_id=OLD.job_id AND job.kind IN ('provider_feature_load_run','provider_feature_load'));
  END IF;
  v_need_final := TG_OP<>'INSERT';
  IF v_provider THEN
    -- 관측만 한다. tuple 뒤 새 blocking L/P를 요청하지 않는다.
    SELECT COALESCE(bool_or(mode IN ('ShareLock','ExclusiveLock')),false),
           COALESCE(bool_or(mode='ExclusiveLock'),false)
      INTO v_protocol_held,v_protocol_exclusive
      FROM pg_catalog.pg_locks
     WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
       AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
       AND classid=1369104691 AND objid=115 AND objsubid=2;
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_locks
         WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
           AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
           AND classid=1590807301 AND objid=1746797985 AND objsubid=1
           AND mode='ExclusiveLock'
    ) INTO v_lineage_held;
    IF NOT v_lineage_held
       OR (v_protocol_held AND NOT v_protocol_exclusive)
       OR (v_need_final AND NOT v_protocol_exclusive) THEN
        RAISE EXCEPTION 'provider tracking write requires its existing lineage/protocol prefix'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_write_prefix';
    END IF;
  END IF;
  IF current_user = 'ktm_curation_command_owner'
     OR EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  v_job_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.job_id ELSE NEW.job_id END;
  IF EXISTS (
    SELECT 1 FROM ops.import_jobs AS job
    WHERE job.job_id = v_job_id
      AND job.kind = 'provider_feature_load'
  ) OR (TG_OP = 'UPDATE' AND EXISTS (
    SELECT 1 FROM ops.import_jobs AS job
    WHERE job.job_id = OLD.job_id
      AND job.kind = 'provider_feature_load'
  )) THEN
    RAISE EXCEPTION 'provider feature memberships require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_membership_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;

CREATE OR REPLACE FUNCTION ops.reject_provider_feature_event_raw_dml() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'ops'
    AS $$
DECLARE
  v_provider boolean;
  v_need_final boolean;
  v_protocol_held boolean;
  v_protocol_exclusive boolean;
  v_lineage_held boolean;
  v_job_id uuid;
BEGIN
  v_job_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.job_id ELSE NEW.job_id END;
  SELECT EXISTS (SELECT 1 FROM ops.import_jobs job WHERE job.job_id=v_job_id
    AND job.kind IN ('provider_feature_load_run','provider_feature_load')) INTO v_provider;
  IF TG_OP='UPDATE' THEN
    v_provider := v_provider OR EXISTS (SELECT 1 FROM ops.import_jobs job
      WHERE job.job_id=OLD.job_id AND job.kind IN ('provider_feature_load_run','provider_feature_load'));
  END IF;
  v_need_final := TG_OP<>'INSERT';
  IF v_provider THEN
    -- 관측만 한다. tuple 뒤 새 blocking L/P를 요청하지 않는다.
    SELECT COALESCE(bool_or(mode IN ('ShareLock','ExclusiveLock')),false),
           COALESCE(bool_or(mode='ExclusiveLock'),false)
      INTO v_protocol_held,v_protocol_exclusive
      FROM pg_catalog.pg_locks
     WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
       AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
       AND classid=1369104691 AND objid=115 AND objsubid=2;
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_locks
         WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
           AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
           AND classid=1590807301 AND objid=1746797985 AND objsubid=1
           AND mode='ExclusiveLock'
    ) INTO v_lineage_held;
    IF NOT v_lineage_held
       OR (v_protocol_held AND NOT v_protocol_exclusive)
       OR (v_need_final AND NOT v_protocol_exclusive) THEN
        RAISE EXCEPTION 'provider tracking write requires its existing lineage/protocol prefix'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_write_prefix';
    END IF;
  END IF;
  IF current_user = 'ktm_curation_command_owner'
     OR EXISTS (
       SELECT 1 FROM pg_catalog.pg_roles AS role
       WHERE role.rolname = session_user AND role.rolsuper
     ) THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  v_job_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.job_id ELSE NEW.job_id END;
  -- OLD가 provider인 event를 generic job으로 옮겨 typed 경계를 피하지 못한다.
  IF v_provider THEN
    RAISE EXCEPTION 'provider feature events require a typed command'
      USING ERRCODE = '42501', CONSTRAINT = 'ck_tvn40_provider_event_typed_command';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$$;

CREATE FUNCTION ops.reject_pipeline_cancellation_prefix() RETURNS trigger
LANGUAGE plpgsql SET search_path TO pg_catalog AS $$
DECLARE
  v_need_final boolean:=true;
  v_protocol_held boolean;
  v_protocol_exclusive boolean;
  v_lineage_held boolean;
BEGIN
  IF TG_LEVEL<>'STATEMENT' OR TG_TABLE_SCHEMA<>'ops'
     OR TG_TABLE_NAME NOT IN ('pipeline_cancellations','pipeline_cancellation_members','pipeline_cancellation_runs') THEN
    RAISE EXCEPTION 'unknown cancellation prefix guard relation'
      USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_write_prefix';
  END IF;
    -- 관측만 한다. tuple 뒤 새 blocking L/P를 요청하지 않는다.
    SELECT COALESCE(bool_or(mode IN ('ShareLock','ExclusiveLock')),false),
           COALESCE(bool_or(mode='ExclusiveLock'),false)
      INTO v_protocol_held,v_protocol_exclusive
      FROM pg_catalog.pg_locks
     WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
       AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
       AND classid=1369104691 AND objid=115 AND objsubid=2;
    SELECT EXISTS (
        SELECT 1 FROM pg_catalog.pg_locks
         WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted
           AND database=(SELECT oid FROM pg_catalog.pg_database WHERE datname=current_database())
           AND classid=1590807301 AND objid=1746797985 AND objsubid=1
           AND mode='ExclusiveLock'
    ) INTO v_lineage_held;
    IF NOT v_lineage_held
       OR (v_protocol_held AND NOT v_protocol_exclusive)
       OR (v_need_final AND NOT v_protocol_exclusive) THEN
        RAISE EXCEPTION 'provider tracking write requires its existing lineage/protocol prefix'
            USING ERRCODE='23514',CONSTRAINT='ck_provider_tracking_write_prefix';
    END IF;
  RETURN NULL;
END;
$$;

CREATE TRIGGER trg_00_provider_tracking_protocol BEFORE INSERT OR UPDATE OR DELETE ON ops.pipeline_cancellations FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_pipeline_cancellation_prefix();
CREATE TRIGGER trg_00_provider_tracking_protocol BEFORE INSERT OR UPDATE OR DELETE ON ops.pipeline_cancellation_members FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_pipeline_cancellation_prefix();
CREATE TRIGGER trg_00_provider_tracking_protocol BEFORE INSERT OR UPDATE OR DELETE ON ops.pipeline_cancellation_runs FOR EACH STATEMENT EXECUTE FUNCTION ops.reject_pipeline_cancellation_prefix();

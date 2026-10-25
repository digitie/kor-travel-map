-- 독립 설치 금지: 명령/ACL/RC finalizer/whole collector와 같은430에서 합성한다.
-- immutable 입력과 자주 갱신하는 작은 lease 행을 분리한다. 일반 runtime raw권한0.
CREATE TABLE ops.provider_snapshot_artifacts (
    snapshot_id uuid PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
    root_job_id uuid NOT NULL REFERENCES ops.import_jobs(job_id),
    source_job_id uuid NOT NULL,
    import_job_dataset_id uuid NOT NULL UNIQUE,
    provider_dataset_id bigint NOT NULL REFERENCES provider_sync.provider_datasets(provider_dataset_id),
    sync_scope text NOT NULL CHECK(octet_length(sync_scope) BETWEEN 1 AND 128 AND sync_scope=btrim(sync_scope)),
    operation_key text NOT NULL CHECK(octet_length(operation_key) BETWEEN 1 AND 256 AND operation_key=btrim(operation_key)),
    dagster_run_id text NOT NULL CHECK(octet_length(dagster_run_id) BETWEEN 1 AND 128 AND dagster_run_id=btrim(dagster_run_id)),
    capture_profile text NOT NULL CHECK(capture_profile='bounded-place-v1'),
    artifact_payload bytea NOT NULL CHECK(octet_length(artifact_payload) BETWEEN 1 AND 1048576),
    artifact_sha256 text GENERATED ALWAYS AS (encode(x_extension.digest(artifact_payload,'sha256'),'hex')) STORED,
    native_input_digest text NOT NULL CHECK(native_input_digest ~ '^[0-9a-f]{64}$'),
    observation_context bytea NOT NULL CHECK(octet_length(observation_context) BETWEEN 1 AND 8192),
    context_sha256 text GENERATED ALWAYS AS (encode(x_extension.digest(observation_context,'sha256'),'hex')) STORED,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT fk_provider_snapshot_artifact_member FOREIGN KEY(source_job_id,import_job_dataset_id)
        REFERENCES ops.import_job_datasets(job_id,import_job_dataset_id)
);

CREATE TABLE ops.provider_snapshot_controls (
    snapshot_id uuid PRIMARY KEY REFERENCES ops.provider_snapshot_artifacts(snapshot_id),
    executor_generation bigint NOT NULL CHECK(executor_generation>0),
    executor_fence uuid NOT NULL,
    lease_expires_at timestamptz NOT NULL,
    status text NOT NULL CHECK(status IN ('prepared','applied','postprocessed','child_sealed')),
    attempt_id uuid UNIQUE REFERENCES ops.feature_write_attempts(attempt_id),
    attempt_owner uuid,
    manifest_digest text CHECK(manifest_digest ~ '^[0-9a-f]{64}$'),
    applied_result bytea CHECK(octet_length(applied_result) BETWEEN 1 AND 4096),
    result_sha256 text GENERATED ALWAYS AS (encode(x_extension.digest(applied_result,'sha256'),'hex')) STORED,
    applied_generation bigint,
    applied_fence uuid,
    applied_at timestamptz,
    postprocess_receipt bytea CHECK(octet_length(postprocess_receipt) BETWEEN 1 AND 4096),
    postprocessed_at timestamptz,
    postprocess_txid bigint,
    postprocess_intent_sha256 text,
    child_sealed_at timestamptz,
    seal_txid bigint,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_provider_snapshot_attempt_pair CHECK(
        (attempt_id IS NULL AND attempt_owner IS NULL AND manifest_digest IS NULL)
        OR (attempt_id IS NOT NULL AND attempt_owner IS NOT NULL AND manifest_digest IS NOT NULL)),
    CONSTRAINT ck_provider_snapshot_applied_result CHECK(
        (status='prepared' AND applied_result IS NULL AND applied_generation IS NULL
         AND applied_fence IS NULL AND applied_at IS NULL)
        OR (status IN ('applied','postprocessed','child_sealed') AND applied_result IS NOT NULL
            AND applied_generation IS NOT NULL AND applied_generation>0
            AND applied_generation<=executor_generation AND applied_fence IS NOT NULL
            AND applied_at IS NOT NULL AND attempt_id IS NOT NULL)),
    CONSTRAINT ck_provider_snapshot_postprocess CHECK(
        (status IN ('prepared','applied') AND postprocess_receipt IS NULL AND postprocessed_at IS NULL)
        OR (status IN ('postprocessed','child_sealed') AND postprocess_receipt IS NOT NULL
            AND postprocessed_at IS NOT NULL)),
    CONSTRAINT ck_provider_snapshot_private_postprocess CHECK(
        (postprocess_txid IS NULL AND postprocess_intent_sha256 IS NULL)
        OR (status='applied' AND postprocess_txid>0 AND postprocess_intent_sha256 IS NOT NULL
            AND postprocess_intent_sha256 ~ '^[0-9a-f]{64}$')),
    CONSTRAINT ck_provider_snapshot_private_seal CHECK(
        seal_txid IS NULL OR (status='postprocessed' AND seal_txid>0)),
    CONSTRAINT ck_provider_snapshot_child_seal CHECK(
        (status='child_sealed')=(child_sealed_at IS NOT NULL))
);

CREATE FUNCTION ops.reject_provider_snapshot_artifact_update() RETURNS trigger
LANGUAGE plpgsql SET search_path TO pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'registered snapshot input is immutable'
        USING ERRCODE='23514',CONSTRAINT='ck_provider_snapshot_immutable_input';
END;
$$;
CREATE TRIGGER trg_provider_snapshot_immutable_input BEFORE UPDATE ON ops.provider_snapshot_artifacts
    FOR EACH ROW EXECUTE FUNCTION ops.reject_provider_snapshot_artifact_update();

-- quota 예약/GC/typed 명령은 별도 sidecar다. 이 저장 조각에는 runtime grant가 없다.

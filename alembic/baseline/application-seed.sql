-- immutable `300` handoff seed receipt. fresh root의 `seed.sql` 전체와는 다른
-- 계약이다: fresh root는 curated/provider default catalog를 넣지만 그 행들은 admin과
-- 운영 command가 바꿀 수 있다. handoff는 그런 정상 운영 데이터를 exact hash로 freeze하지
-- 않고, 실제로 code-owned allow-list인 field-path registry만 비교한다.
-- 과거 `0236` graph의 registry 보정 migration은 `updated_at = now()`를 썼다.
-- handoff는 그 실행 시각이 아니라 code-owned registry의 semantic row를 보존해야 하므로
-- 생성·갱신 시각은 receipt에서 정규화한다.
--
-- `ops.import_job_event_clock`와 `ops.ops_live_topic_revisions`는 seed가 아니다.
-- 둘은 운영 DML이 늘리는 live revision projection이므로 exact-value hash에 넣으면
-- 정상 운영 뒤 `0236 → 300` metadata handoff까지 거절한다. fresh `300`은 migration의
-- runtime 초기화로 필요한 singleton/topic 행을 만들고, handoff는 별도 structural
-- invariant로 존재·카디널리티·범위만 확인한다.
SELECT table_name || chr(31) || row_json AS item
FROM (
    SELECT
        'ops.feature_override_field_paths'::text AS table_name,
        (to_jsonb(row) - ARRAY['created_at', 'updated_at'])::text AS row_json
    FROM ops.feature_override_field_paths AS row
) AS seed_rows
ORDER BY table_name COLLATE "C", row_json COLLATE "C";

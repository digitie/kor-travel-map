-- `0236 → 300` handoff의 live revision projection invariant.
--
-- 이 query는 immutable seed receipt가 아니다. `ops.import_job_event_clock` 및
-- `ops.ops_live_topic_revisions`의 revision/updated_at은 정상 운영 write마다 변한다.
-- handoff는 그 값을 baseline 값으로 되돌리거나 exact hash로 비교하지 않고, `300`이
-- 의존하는 singleton/topic row의 존재·카디널리티·형식만 검증한다. 행이 한 개도 없거나
-- 음수 revision 같은 구조 손상은 metadata stamp 전에 fail-close한다.
WITH violations AS (
    SELECT 'import_job_event_clock:singleton'::text AS invariant
    WHERE (
        SELECT count(*)
        FROM ops.import_job_event_clock
    ) <> 1
       OR EXISTS (
           SELECT 1
           FROM ops.import_job_event_clock
           WHERE clock_id IS DISTINCT FROM true
              OR revision < 0
              OR updated_at IS NULL
       )
    UNION ALL
    SELECT 'ops_live_topic_revisions:row-shape'
    WHERE EXISTS (
        SELECT 1
        FROM ops.ops_live_topic_revisions
        WHERE btrim(topic) = ''
           OR char_length(topic) > 100
           OR revision < 0
           OR updated_at IS NULL
    )
    UNION ALL
    SELECT 'ops_live_topic_revisions:required-topic:' || required.topic
    FROM (
        VALUES
            ('dagster_schedules'::text),
            ('dataset_projection'::text),
            ('provider_sync'::text)
    ) AS required(topic)
    LEFT JOIN ops.ops_live_topic_revisions AS live_revision
      ON live_revision.topic = required.topic
    GROUP BY required.topic
    HAVING count(live_revision.topic) <> 1
)
SELECT invariant
FROM violations
ORDER BY invariant;

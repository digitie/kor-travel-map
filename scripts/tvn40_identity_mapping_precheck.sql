-- T-VN-40 인수 ① 직전 read-only precheck (설계 §5, docs/tasks.md ①).
-- prod map DB(head 0104)에서 psql -At로 실행. 모든 count가 0이어야 0223 loader가 통과한다.
-- 0223은 0104→0223 단일 트랜잭션 안에서 RAISE하므로, 여기서 0이 아니면 ①을 시작하지 않는다.
--
--   ssh n150 'docker exec kor-travel-map-postgres sh -c '"'"'PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")" \
--     psql -h 127.0.0.1 -p 12700 -U kor_travel_map -d kor_travel_map -At -f /tmp/precheck.sql'"'"''

\echo detached (A):
SELECT count(*) FROM feature.curated_features WHERE metadata @> '{"merge_projection_detached": true}'::jsonb;

\echo no_candidate (E — projection 0이고 same-theme·feature 미보관·비projection item도 0):
WITH projection AS (
  SELECT legacy_projection_id AS legacy_id FROM feature.curation_items WHERE legacy_projection_id IS NOT NULL
)
SELECT count(*)
FROM feature.curated_features AS legacy
WHERE NOT EXISTS (SELECT 1 FROM projection p WHERE p.legacy_id = legacy.curated_feature_id)
  AND NOT EXISTS (
    SELECT 1 FROM feature.curation_collections c
    JOIN feature.curation_items i ON i.collection_id = c.collection_id
    WHERE c.theme_id = legacy.theme_id AND i.feature_id = legacy.feature_id
      AND i.archived_at IS NULL AND i.legacy_projection_id IS NULL);

\echo multi_candidate (E — projection 0이고 membership 후보 2+):
WITH projection AS (
  SELECT legacy_projection_id AS legacy_id FROM feature.curation_items WHERE legacy_projection_id IS NOT NULL
), membership AS (
  SELECT legacy.curated_feature_id AS legacy_id, count(*) AS n
  FROM feature.curated_features AS legacy
  JOIN feature.curation_collections c ON c.theme_id = legacy.theme_id
  JOIN feature.curation_items i ON i.collection_id = c.collection_id
    AND i.feature_id = legacy.feature_id AND i.archived_at IS NULL AND i.legacy_projection_id IS NULL
  WHERE NOT EXISTS (SELECT 1 FROM projection p WHERE p.legacy_id = legacy.curated_feature_id)
  GROUP BY 1
)
SELECT count(*) FROM membership WHERE n >= 2;

\echo no_evidence (E — membership 후보 1인데 import row도 admin 표시도 없음):
WITH projection AS (
  SELECT legacy_projection_id AS legacy_id FROM feature.curation_items WHERE legacy_projection_id IS NOT NULL
), membership AS (
  SELECT legacy.curated_feature_id AS legacy_id, count(*) AS n,
         bool_or(i.current_import_row_id IS NOT NULL OR i.created_by IS NOT NULL OR i.operator_updated_by IS NOT NULL) AS evidence
  FROM feature.curated_features AS legacy
  JOIN feature.curation_collections c ON c.theme_id = legacy.theme_id
  JOIN feature.curation_items i ON i.collection_id = c.collection_id
    AND i.feature_id = legacy.feature_id AND i.archived_at IS NULL AND i.legacy_projection_id IS NULL
  WHERE NOT EXISTS (SELECT 1 FROM projection p WHERE p.legacy_id = legacy.curated_feature_id)
  GROUP BY 1
)
SELECT count(*) FROM membership WHERE n = 1 AND NOT evidence;

\echo item_claimed_twice (E — 한 item을 legacy 2행이 잡음; projection은 UNIQUE라 membership 경로만):
WITH projection AS (
  SELECT legacy_projection_id AS legacy_id FROM feature.curation_items WHERE legacy_projection_id IS NOT NULL
), membership AS (
  SELECT legacy.curated_feature_id AS legacy_id, min(i.curation_item_id::text) AS item_id, count(*) AS n
  FROM feature.curated_features AS legacy
  JOIN feature.curation_collections c ON c.theme_id = legacy.theme_id
  JOIN feature.curation_items i ON i.collection_id = c.collection_id
    AND i.feature_id = legacy.feature_id AND i.archived_at IS NULL AND i.legacy_projection_id IS NULL
  WHERE NOT EXISTS (SELECT 1 FROM projection p WHERE p.legacy_id = legacy.curated_feature_id)
  GROUP BY 1
)
SELECT count(*) FROM (SELECT item_id FROM membership WHERE n = 1 GROUP BY item_id HAVING count(*) >= 2) d;

\echo pipe_in_hash_fields (설계 §4 — '|' 결합 유일성):
SELECT count(*) FROM feature.curated_features
WHERE feature_id LIKE '%|%' OR coalesce(source_record_key,'') LIKE '%|%';

\echo temp_privilege_schema_owner (0223은 SET ROLE ktm_feature_schema_owner로 CREATE TEMP TABLE):
SELECT CASE WHEN has_database_privilege('ktm_feature_schema_owner', current_database(), 'TEMP') THEN 0 ELSE 1 END;

\echo active_writers_on_legacy_tables (0이 아니면 lock 대기 — 30s lock_timeout 뒤 전체 롤백):
SELECT count(*) FROM pg_stat_activity
WHERE state <> 'idle' AND pid <> pg_backend_pid()
  AND query ~* 'curated_features|curation_items|curation_collections';

\echo summary (참고: legacy_total, projection 1:1):
SELECT (SELECT count(*) FROM feature.curated_features) AS legacy_total,
       (SELECT count(*) FROM feature.curation_items WHERE legacy_projection_id IS NOT NULL) AS projection_items;

-- `0236 → 300` handoff의 privileged residue contract.
--
-- 이 query는 Docker Manager/source/fresh oracle의 database-superuser session에서만
-- 실행한다. `pg_user_mapping`은 schema-owner/migrator에 visibility를 넓히지 않는다.
-- credential option·mapping identity를 기록하지 않고, baseline에 허용되지 않는
-- extensibility object의 **count만** 결정론적으로 receipt화한다.
SELECT 'pg_event_trigger:' || count(*)::text
FROM pg_catalog.pg_event_trigger
UNION ALL
SELECT 'pg_publication:' || count(*)::text
FROM pg_catalog.pg_publication
UNION ALL
SELECT 'pg_subscription_current_database:' || count(*)::text
FROM pg_catalog.pg_subscription AS subscription
WHERE subscription.subdbid = (
    SELECT oid FROM pg_catalog.pg_database WHERE datname = current_database()
)
UNION ALL
SELECT 'pg_user_mapping:' || count(*)::text
FROM pg_catalog.pg_user_mapping
UNION ALL
-- Large objects are database-wide and can carry a PUBLIC ACL even when application
-- schemas are empty.  Emit rows only when present so the certified zero-residue
-- baseline digest remains stable while any owner/ACL residue fails closed.
SELECT 'pg_largeobject_metadata:' || metadata.oid::text || ':' ||
       metadata.lomowner::regrole::text || ':' ||
       COALESCE(metadata.lomacl::text, '')
FROM pg_catalog.pg_largeobject_metadata AS metadata
ORDER BY 1;

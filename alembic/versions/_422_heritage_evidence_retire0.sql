-- dataset 전체의 별도 EXISTS 부정 증거다. payload 집합을 반환/집계하지 않는다.
CREATE FUNCTION feature._heritage_evidence_retire0(p_dataset bigint)
RETURNS boolean LANGUAGE sql STABLE SET search_path TO pg_catalog AS $$
SELECT NOT EXISTS (
    SELECT 1 FROM provider_sync.source_entities e
    WHERE e.provider_dataset_id=p_dataset AND (
        e.source_entity_key IS NULL OR pg_column_compression(e.source_entity_key) IS NOT NULL
        OR pg_column_size(e.source_entity_key)>128
        OR e.source_entity_type IS NULL OR pg_column_compression(e.source_entity_type) IS NOT NULL
        OR pg_column_size(e.source_entity_type)>64
    )
) AND NOT EXISTS (
    SELECT 1 FROM provider_sync.source_entities e
    JOIN provider_sync.source_links l ON CASE
        WHEN e.source_entity_key IS NOT NULL
          AND pg_column_compression(e.source_entity_key) IS NULL
          AND pg_column_size(e.source_entity_key)<=128
          AND l.source_entity_key IS NOT NULL
          AND pg_column_compression(l.source_entity_key) IS NULL
          AND pg_column_size(l.source_entity_key)<=128
        THEN e.source_entity_key=l.source_entity_key ELSE false END
    JOIN feature.features f ON f.feature_id=l.feature_id
    WHERE e.provider_dataset_id=p_dataset
      AND CASE WHEN e.source_entity_type IS NOT NULL
          AND pg_column_compression(e.source_entity_type) IS NULL
          AND pg_column_size(e.source_entity_type)<=64
        THEN e.source_entity_type='heritage' ELSE true END
      AND CASE WHEN l.source_role IS NOT NULL
          AND pg_column_compression(l.source_role) IS NULL AND pg_column_size(l.source_role)<=64
        THEN l.source_role='primary' ELSE true END
      AND CASE WHEN f.kind IS NOT NULL AND f.lifecycle_state IS NOT NULL
          AND pg_column_compression(f.kind) IS NULL AND pg_column_size(f.kind)<=64
          AND pg_column_compression(f.lifecycle_state) IS NULL
          AND pg_column_size(f.lifecycle_state)<=64
        THEN f.kind='area' AND f.lifecycle_state='active'
          AND NOT EXISTS(SELECT 1 FROM feature.feature_areas a WHERE a.feature_id=f.feature_id)
        ELSE true END
);
$$;

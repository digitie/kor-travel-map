CREATE OR REPLACE PROCEDURE feature.sync_concierge_theme_catalog(IN p_provider_dataset_id bigint, IN p_import_job_id uuid, OUT o_themes_created bigint, OUT o_themes_updated bigint, OUT o_rules_created bigint, OUT o_rules_updated bigint, OUT o_rules_archived bigint)
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'provider_sync', 'ops', 'x_extension'
    AS $$
DECLARE
  v_source_id uuid;
  v_group record;
  v_theme feature.curated_themes%ROWTYPE;
  v_rule feature.curated_source_rules%ROWTYPE;
  v_generation_id uuid;
  v_observed bigint;
  v_removed bigint;
  v_input_hash text;
  v_replayed boolean;
  v_metadata jsonb;
  v_selector jsonb;
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'concierge catalog sync requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF current_user <> 'ktm_curation_command_owner'
     OR NOT pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'concierge catalog sync is an internal provider command'
      USING ERRCODE = '42501';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM ops.curation_provider_snapshot_receipts AS receipt
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = receipt.provider_dataset_id
    WHERE receipt.source_job_id = p_import_job_id
      AND receipt.provider_dataset_id = p_provider_dataset_id
      AND dataset.provider = 'kor-travel-concierge-youtube'
      AND dataset.dataset_key = 'youtube_place_candidates'
  ) THEN
    o_themes_created := 0;
    o_themes_updated := 0;
    o_rules_created := 0;
    o_rules_updated := 0;
    o_rules_archived := 0;
    RETURN;
  END IF;

  SELECT source.source_id INTO STRICT v_source_id
  FROM feature.curated_sources AS source
  WHERE source.provider_dataset_id = p_provider_dataset_id
    AND source.archived_at IS NULL
  FOR UPDATE;

  CREATE TEMPORARY TABLE IF NOT EXISTS pg_temp.tvn40_concierge_groups (
    grouping_kind text NOT NULL,
    grouping_id text NOT NULL,
    grouping_title text NOT NULL,
    theme_slug text NOT NULL,
    detail_selector jsonb NOT NULL,
    feature_count bigint NOT NULL,
    PRIMARY KEY (grouping_kind, grouping_id),
    UNIQUE (theme_slug)
  ) ON COMMIT DROP;
  TRUNCATE pg_temp.tvn40_concierge_groups;

  INSERT INTO pg_temp.tvn40_concierge_groups (
    grouping_kind, grouping_id, grouping_title, theme_slug,
    detail_selector, feature_count
  )
  WITH current_features AS (
    SELECT DISTINCT feature.feature_id, place.payload
    FROM provider_sync.source_entities AS entity
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS record
      ON record.source_entity_key = head.source_entity_key
     AND record.source_record_key = head.current_source_record_key
    JOIN provider_sync.source_links AS link
      ON link.source_entity_key = entity.source_entity_key
    JOIN feature.features AS feature ON feature.feature_id = link.feature_id
    JOIN feature.feature_places AS place ON place.feature_id = feature.feature_id
    WHERE entity.provider_dataset_id = p_provider_dataset_id
      AND feature.lifecycle_state = 'active'
      AND feature.publication_state = 'published'
      AND feature.quality_state = 'valid'
  ), expanded AS (
    SELECT feature_id, 'channel'::text AS grouping_kind,
           payload #>> '{kor_travel_concierge,youtube,channel_id}' AS grouping_id,
           payload #>> '{kor_travel_concierge,youtube,channel_title}' AS grouping_title,
           'concierge-yt-'::text AS slug_prefix,
           ARRAY['payload','kor_travel_concierge','youtube','channel_id']::text[] AS selector_path
    FROM current_features
    UNION ALL
    SELECT feature_id, 'playlist'::text,
           payload #>> '{kor_travel_concierge,youtube,playlist_id}',
           payload #>> '{kor_travel_concierge,youtube,playlist_title}',
           'concierge-pl-'::text,
           ARRAY['payload','kor_travel_concierge','youtube','playlist_id']::text[]
    FROM current_features
  )
  SELECT grouping_kind, grouping_id,
         COALESCE(max(NULLIF(btrim(grouping_title), '')), min(slug_prefix) || grouping_id),
         min(slug_prefix) || grouping_id,
         jsonb_build_object('path', min(selector_path), 'value', grouping_id),
         count(DISTINCT feature_id)::bigint
  FROM expanded
  WHERE NULLIF(btrim(grouping_id), '') IS NOT NULL
  GROUP BY grouping_kind, grouping_id;

  -- Only exact legacy rows produced by the retired synchronizer may acquire
  -- provider ownership.  A manually-created prefix collision remains fatal.
  UPDATE feature.curated_themes AS theme
  SET owner_kind = 'provider_dataset',
      owner_provider_dataset_id = p_provider_dataset_id,
      row_revision = theme.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE theme.owner_kind IS NULL
    AND theme.owner_provider_dataset_id IS NULL
    AND EXISTS (
      SELECT 1 FROM ops.curation_concierge_legacy_owner_manifest AS manifest
      WHERE manifest.entity_kind = 'theme' AND manifest.entity_id = theme.theme_id
        AND manifest.before_row_revision = theme.row_revision
        AND manifest.before_input_hash = encode(x_extension.digest(convert_to(
          jsonb_build_array(theme.theme_id::text, theme.row_revision,
                            theme.theme_slug, theme.metadata)::text,
          'UTF8'), 'sha256'), 'hex')
    );
  UPDATE feature.curated_source_rules AS rule
  SET owner_kind = 'provider_dataset',
      owner_provider_dataset_id = p_provider_dataset_id,
      row_revision = rule.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE rule.owner_kind IS NULL
    AND rule.owner_provider_dataset_id IS NULL
    AND rule.source_id = v_source_id
    AND EXISTS (
      SELECT 1 FROM ops.curation_concierge_legacy_owner_manifest AS manifest
      WHERE manifest.entity_kind = 'rule' AND manifest.entity_id = rule.rule_id
        AND manifest.before_row_revision = rule.row_revision
        AND manifest.before_input_hash = encode(x_extension.digest(convert_to(
          jsonb_build_array(rule.rule_id::text, rule.row_revision,
                            rule.theme_id::text, rule.source_id::text,
                            rule.metadata)::text,
          'UTF8'), 'sha256'), 'hex')
    )
    AND EXISTS (
      SELECT 1 FROM feature.curated_themes AS theme
      WHERE theme.theme_id = rule.theme_id
        AND theme.owner_kind = 'provider_dataset'
        AND theme.owner_provider_dataset_id = p_provider_dataset_id
    );

  o_themes_created := 0;
  o_themes_updated := 0;
  o_rules_created := 0;
  o_rules_updated := 0;
  o_rules_archived := 0;
  FOR v_group IN
    SELECT * FROM pg_temp.tvn40_concierge_groups
    ORDER BY grouping_kind, grouping_id
  LOOP
    v_metadata := jsonb_build_object(
      'concierge_kind', v_group.grouping_kind,
      'concierge_value', v_group.grouping_id,
      'poi_count', v_group.feature_count,
      'seed', 'sync_concierge_themes'
    );
    v_selector := v_group.detail_selector;
    SELECT theme.* INTO v_theme
    FROM feature.curated_themes AS theme
    WHERE theme.theme_slug = v_group.theme_slug
    FOR UPDATE;
    IF NOT FOUND THEN
      INSERT INTO feature.curated_themes (
        theme_slug, theme_name, theme_description, theme_group,
        default_curated, visibility, metadata, row_revision, archived_at,
        owner_kind, owner_provider_dataset_id, updated_at
      ) VALUES (
        v_group.theme_slug, v_group.grouping_title, '', 'media', false, 'public',
        v_metadata, 1, NULL, 'provider_dataset', p_provider_dataset_id,
        clock_timestamp()
      ) RETURNING * INTO STRICT v_theme;
      o_themes_created := o_themes_created + 1;
    ELSE
      IF v_theme.owner_kind IS DISTINCT FROM 'provider_dataset'
         OR v_theme.owner_provider_dataset_id IS DISTINCT FROM p_provider_dataset_id THEN
        RAISE EXCEPTION 'concierge theme slug collides with another owner: %', v_group.theme_slug
          USING ERRCODE = '23505', CONSTRAINT = 'uq_tvn40_concierge_theme_owner';
      END IF;
      IF (v_theme.theme_name, v_theme.theme_group, v_theme.visibility,
          v_theme.metadata, v_theme.archived_at IS NULL)
         IS DISTINCT FROM
         (v_group.grouping_title, 'media'::text, 'public'::text,
          v_metadata, true) THEN
        UPDATE feature.curated_themes AS theme
        SET theme_name = v_group.grouping_title,
            theme_group = 'media', visibility = 'public', metadata = v_metadata,
            archived_at = NULL, row_revision = theme.row_revision + 1,
            updated_at = clock_timestamp()
        WHERE theme.theme_id = v_theme.theme_id
        RETURNING * INTO STRICT v_theme;
        o_themes_updated := o_themes_updated + 1;
      END IF;
    END IF;

    IF (SELECT count(*) FROM feature.curated_source_rules AS rule
        WHERE rule.theme_id = v_theme.theme_id AND rule.source_id = v_source_id) > 1 THEN
      RAISE EXCEPTION 'concierge theme has ambiguous source rules: %', v_theme.theme_id
        USING ERRCODE = '23505', CONSTRAINT = 'uq_tvn40_concierge_theme_rule';
    END IF;
    SELECT rule.* INTO v_rule
    FROM feature.curated_source_rules AS rule
    WHERE rule.theme_id = v_theme.theme_id AND rule.source_id = v_source_id
    FOR UPDATE;
    IF NOT FOUND THEN
      INSERT INTO feature.curated_source_rules (
        theme_id, source_id, place_kind, category, region_scope,
        detail_selector, default_action, priority, enabled, metadata,
        row_revision, archived_at, owner_kind, owner_provider_dataset_id, updated_at
      ) VALUES (
        v_theme.theme_id, v_source_id, 'youtube_place_candidate', NULL, '{}'::jsonb,
        v_selector, 'candidate',
        LEAST(v_group.feature_count, 2147483647)::integer, true,
        jsonb_build_object('curation_relation', 'theme_area_anchor'),
        1, NULL, 'provider_dataset', p_provider_dataset_id, clock_timestamp()
      ) RETURNING * INTO STRICT v_rule;
      o_rules_created := o_rules_created + 1;
    ELSE
      IF v_rule.owner_kind IS DISTINCT FROM 'provider_dataset'
         OR v_rule.owner_provider_dataset_id IS DISTINCT FROM p_provider_dataset_id THEN
        RAISE EXCEPTION 'concierge rule collides with another owner: %', v_rule.rule_id
          USING ERRCODE = '23505', CONSTRAINT = 'uq_tvn40_concierge_rule_owner';
      END IF;
      IF (v_rule.place_kind, v_rule.category, v_rule.region_scope,
          v_rule.detail_selector, v_rule.default_action, v_rule.priority,
          v_rule.enabled, v_rule.archived_at IS NULL)
         IS DISTINCT FROM
         ('youtube_place_candidate'::text, NULL::text, '{}'::jsonb,
          v_selector, 'candidate'::text,
          LEAST(v_group.feature_count, 2147483647)::integer,
          true, true) THEN
        UPDATE feature.curated_source_rules AS rule
        SET place_kind = 'youtube_place_candidate', category = NULL,
            region_scope = '{}'::jsonb, detail_selector = v_selector,
            default_action = 'candidate',
            priority = LEAST(v_group.feature_count, 2147483647)::integer,
            enabled = true, archived_at = NULL,
            row_revision = rule.row_revision + 1, updated_at = clock_timestamp()
        WHERE rule.rule_id = v_rule.rule_id;
        o_rules_updated := o_rules_updated + 1;
      END IF;
    END IF;
  END LOOP;

  -- Removed authoritative groups first materialize an empty expected set so
  -- candidate eligibility is audited before their catalog rows are archived.
  FOR v_rule IN
    SELECT rule.*
    FROM feature.curated_source_rules AS rule
    JOIN feature.curated_themes AS theme ON theme.theme_id = rule.theme_id
    WHERE rule.source_id = v_source_id
      AND rule.owner_kind = 'provider_dataset'
      AND rule.owner_provider_dataset_id = p_provider_dataset_id
      AND rule.archived_at IS NULL
      AND theme.owner_kind = 'provider_dataset'
      AND theme.owner_provider_dataset_id = p_provider_dataset_id
      AND NOT EXISTS (
        SELECT 1 FROM pg_temp.tvn40_concierge_groups AS desired
        WHERE desired.theme_slug = theme.theme_slug
      )
    ORDER BY rule.rule_id
  LOOP
    CALL feature.materialize_theme_candidate_generation(
      v_rule.rule_id, 'provider_full_snapshot', p_import_job_id,
      NULL, NULL, NULL, jsonb_build_object(
        'schema_version', 1, 'reason_code', 'catalog_archived'
      ), v_generation_id, v_observed, v_removed, v_input_hash, v_replayed
    );
    UPDATE feature.curated_source_rules AS rule
    SET enabled = false, archived_at = clock_timestamp(),
        row_revision = rule.row_revision + 1, updated_at = clock_timestamp()
    WHERE rule.rule_id = v_rule.rule_id;
    o_rules_archived := o_rules_archived + 1;
  END LOOP;
  UPDATE feature.curated_themes AS theme
  SET archived_at = clock_timestamp(), row_revision = theme.row_revision + 1,
      updated_at = clock_timestamp()
  WHERE theme.owner_kind = 'provider_dataset'
    AND theme.owner_provider_dataset_id = p_provider_dataset_id
    AND theme.archived_at IS NULL
    AND NOT EXISTS (
      SELECT 1 FROM pg_temp.tvn40_concierge_groups AS desired
      WHERE desired.theme_slug = theme.theme_slug
    );
END
$$;

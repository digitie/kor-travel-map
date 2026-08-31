CREATE PROCEDURE feature.apply_curation_import_items_command(IN p_items jsonb, IN p_content_sha256 text, IN p_batch_kind text, IN p_command_id bigint, IN p_principal text, OUT o_import_batch_id uuid, OUT o_inserted integer, OUT o_updated integer, OUT o_removed_item_ids uuid[])
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'feature', 'ops', 'x_extension'
    AS $_$
DECLARE
  v_command ops.domain_commands%ROWTYPE;
  v_adopted integer := 0;
  v_collection_id uuid;
  v_collection_revision bigint;
  v_changed_collection_ids uuid[];
  v_changed_item_ids uuid[] := ARRAY[]::uuid[];
BEGIN
  IF current_setting('transaction_isolation') <> 'serializable' THEN
    RAISE EXCEPTION 'curation import command requires SERIALIZABLE transaction'
      USING ERRCODE = '25001';
  END IF;
  IF NOT pg_has_role(session_user, 'ktm_curation_admin_executor', 'member')
     OR pg_has_role(session_user, 'ktm_curation_provider_executor', 'member') THEN
    RAISE EXCEPTION 'curation import command requires the admin executor'
      USING ERRCODE = '42501';
  END IF;
  IF jsonb_typeof(p_items) <> 'array'
     OR p_content_sha256 !~ '^[0-9a-f]{64}$'
     OR p_batch_kind NOT IN ('csv_upload','normalized_rows')
     OR p_principal IS NULL OR p_principal <> btrim(p_principal) OR p_principal = '' THEN
    RAISE EXCEPTION 'curation import item input is not canonical'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_item_input';
  END IF;
  SELECT command.* INTO STRICT v_command
  FROM ops.domain_commands AS command WHERE command.command_id = p_command_id
  FOR UPDATE;
  IF v_command.actor <> p_principal OR v_command.operation <> 'admin.curation.import'
     OR EXISTS (SELECT 1 FROM ops.domain_command_results AS result
                WHERE result.command_id = p_command_id) THEN
    RAISE EXCEPTION 'domain command does not match active curation import'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_domain_command';
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM ops.curation_import_plan_claims AS claim
    JOIN feature.curation_import_plans AS plan
      ON plan.import_plan_id = claim.import_plan_id
    WHERE claim.command_id = p_command_id
      AND plan.actor = p_principal
      AND plan.content_sha256 = p_content_sha256
  ) THEN
    RAISE EXCEPTION 'curation import plan must be claimed before apply'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_claim';
  END IF;
  IF (
    SELECT COALESCE(jsonb_agg(
      jsonb_set(
        row.normalized_payload,
        '{provenance}',
        COALESCE(
          NULLIF(row.normalized_payload -> 'provenance', 'null'::jsonb),
          '{}'::jsonb
        ),
        true
      ) ORDER BY row.row_number
    ), '[]'::jsonb)
    FROM feature.curation_import_plan_rows AS row
    JOIN ops.curation_import_plan_claims AS claim
      ON claim.import_plan_id = row.import_plan_id
    WHERE claim.command_id = p_command_id
      AND row.normalized_payload IS NOT NULL
  ) IS DISTINCT FROM (
    SELECT COALESCE(jsonb_agg(
      value.row_payload || jsonb_build_object(
        'provenance', COALESCE(value.provenance, '{}'::jsonb)
      ) ORDER BY value.row_number
    ), '[]'::jsonb)
    FROM jsonb_to_recordset(p_items) AS value(
      row_number integer, row_payload jsonb, provenance jsonb
    )
  ) THEN
    RAISE EXCEPTION 'curation import rows differ from the immutable claimed plan'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_plan_row_set';
  END IF;
  IF (SELECT count(*) FROM jsonb_array_elements(p_items)) <> (
       SELECT count(DISTINCT value.row_number)
       FROM jsonb_to_recordset(p_items) AS value(row_number integer)
     ) OR (SELECT count(*) FROM jsonb_array_elements(p_items)) <> (
       SELECT count(DISTINCT (value.collection_id, value.external_item_id,
                              value.external_component_id))
       FROM jsonb_to_recordset(p_items) AS value(
         collection_id uuid, external_item_id text, external_component_id text
       )
     ) THEN
    RAISE EXCEPTION 'curation import rows are not a unique closed set'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_item_unique_set';
  END IF;
  IF EXISTS (
    SELECT 1
    FROM jsonb_to_recordset(p_items) AS value(collection_id uuid)
    LEFT JOIN ops.curation_import_collection_effects AS effect
      ON effect.command_id = p_command_id
     AND effect.collection_id = value.collection_id
    WHERE effect.collection_id IS NULL
  ) THEN
    RAISE EXCEPTION 'import collection effect set is incomplete'
      USING ERRCODE = '23514', CONSTRAINT = 'ck_tvn40_import_collection_effect_set';
  END IF;

  PERFORM item.curation_item_id
  FROM feature.curation_items AS item
  WHERE item.collection_id = ANY(ARRAY(
    SELECT DISTINCT value.collection_id
    FROM jsonb_to_recordset(p_items) AS value(collection_id uuid)
  ))
  ORDER BY item.curation_item_id FOR UPDATE;

  WITH incoming AS MATERIALIZED (
    SELECT * FROM jsonb_to_recordset(p_items) AS value(
      row_number integer, collection_id uuid, collection_key text,
      feature_id text, external_item_id text, external_component_id text,
      place_name text, address_hint text, sort_order integer,
      item_title text, item_summary text, metadata jsonb,
      provenance jsonb, row_payload jsonb
    )
  ), candidates AS MATERIALIZED (
    SELECT existing.curation_item_id
    FROM feature.curation_items AS existing
    WHERE existing.collection_id = ANY(SELECT DISTINCT collection_id FROM incoming)
      AND existing.archived_at IS NULL AND existing.source_present
      AND NOT EXISTS (
        SELECT 1 FROM incoming
        WHERE incoming.collection_id = existing.collection_id
          AND incoming.external_item_id = existing.external_item_id
          AND (
            incoming.external_component_id = existing.external_component_id
            OR (incoming.feature_id IS NOT NULL
                AND existing.feature_id = incoming.feature_id
                AND existing.external_component_id LIKE 'legacy:%'
                AND NOT EXISTS (
                  SELECT 1 FROM feature.curation_items AS exact_identity
                  WHERE exact_identity.collection_id = existing.collection_id
                    AND exact_identity.external_item_id = incoming.external_item_id
                    AND exact_identity.external_component_id = incoming.external_component_id
                ))
          )
      )
  ), removed AS (
    UPDATE feature.curation_items AS existing
    SET source_present = false, source_updated_at = clock_timestamp(),
        updated_by = p_principal, row_revision = existing.row_revision + 1,
        updated_at = clock_timestamp()
    WHERE existing.curation_item_id = ANY(SELECT curation_item_id FROM candidates)
    RETURNING existing.curation_item_id, existing.collection_id
  )
  SELECT COALESCE(array_agg(curation_item_id ORDER BY curation_item_id), ARRAY[]::uuid[]),
         COALESCE(array_agg(DISTINCT collection_id ORDER BY collection_id), ARRAY[]::uuid[])
  INTO STRICT o_removed_item_ids, v_changed_collection_ids
  FROM removed;
  v_changed_item_ids := o_removed_item_ids;

  WITH incoming AS MATERIALIZED (
    SELECT * FROM jsonb_to_recordset(p_items) AS value(
      collection_id uuid, feature_id text, external_item_id text,
      external_component_id text, place_name text, address_hint text,
      sort_order integer, item_title text, item_summary text, metadata jsonb
    )
  ), matched AS MATERIALIZED (
    SELECT legacy.curation_item_id, incoming.*
    FROM incoming
    JOIN feature.curation_items AS legacy
      ON legacy.collection_id = incoming.collection_id
     AND legacy.external_item_id = incoming.external_item_id
     AND legacy.feature_id = incoming.feature_id
     AND legacy.external_component_id LIKE 'legacy:%'
    WHERE incoming.feature_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM feature.curation_items AS exact_identity
        WHERE exact_identity.collection_id = legacy.collection_id
          AND exact_identity.external_item_id = legacy.external_item_id
          AND exact_identity.external_component_id = incoming.external_component_id
      )
  ), written AS (
    UPDATE feature.curation_items AS legacy
    SET external_component_id = matched.external_component_id,
        place_name = CASE WHEN legacy.archived_at IS NULL THEN matched.place_name ELSE legacy.place_name END,
        address_hint = CASE WHEN legacy.archived_at IS NULL THEN matched.address_hint ELSE legacy.address_hint END,
        source_present = CASE WHEN legacy.archived_at IS NULL THEN true ELSE legacy.source_present END,
        source_updated_at = CASE WHEN legacy.archived_at IS NULL THEN clock_timestamp() ELSE legacy.source_updated_at END,
        sort_order = CASE WHEN legacy.archived_at IS NULL THEN matched.sort_order ELSE legacy.sort_order END,
        item_title = CASE WHEN legacy.archived_at IS NULL THEN matched.item_title ELSE legacy.item_title END,
        item_summary = CASE WHEN legacy.archived_at IS NULL THEN matched.item_summary ELSE legacy.item_summary END,
        metadata = CASE WHEN legacy.archived_at IS NULL THEN matched.metadata ELSE legacy.metadata END,
        updated_by = p_principal, row_revision = legacy.row_revision + 1,
        updated_at = clock_timestamp()
    FROM matched WHERE legacy.curation_item_id = matched.curation_item_id
    RETURNING legacy.curation_item_id, legacy.collection_id
  )
  SELECT count(*)::integer,
         array_cat(v_changed_collection_ids,
                   COALESCE(array_agg(DISTINCT collection_id), ARRAY[]::uuid[])),
         array_cat(v_changed_item_ids,
                   COALESCE(array_agg(curation_item_id), ARRAY[]::uuid[]))
  INTO STRICT v_adopted, v_changed_collection_ids, v_changed_item_ids FROM written;

  WITH incoming AS MATERIALIZED (
    SELECT * FROM jsonb_to_recordset(p_items) AS value(
      collection_id uuid, feature_id text, external_item_id text,
      external_component_id text, place_name text, address_hint text,
      sort_order integer, item_title text, item_summary text, metadata jsonb
    )
  ), written AS (
    INSERT INTO feature.curation_items (
      collection_id, feature_id, external_item_id, external_component_id,
      place_name, address_hint, source_present, source_updated_at, status,
      sort_order, item_title, item_summary, curation_relation, reuse_policy,
      metadata, created_by, updated_by, updated_at
    )
    SELECT collection_id, feature_id, external_item_id, external_component_id,
           place_name, address_hint, true, clock_timestamp(), 'included',
           sort_order, item_title, item_summary, 'nearby_option', 'manual_review',
           metadata, p_principal, p_principal, clock_timestamp()
    FROM incoming
    WHERE NOT EXISTS (
      SELECT 1 FROM feature.curation_items AS tombstone
      WHERE tombstone.collection_id = incoming.collection_id
        AND tombstone.external_item_id = incoming.external_item_id
        AND tombstone.external_component_id = incoming.external_component_id
        AND tombstone.archived_at IS NOT NULL
    )
    ON CONFLICT (collection_id, external_item_id, external_component_id)
    DO UPDATE SET feature_id = EXCLUDED.feature_id, place_name = EXCLUDED.place_name,
      address_hint = EXCLUDED.address_hint, source_present = true,
      source_updated_at = clock_timestamp(), sort_order = EXCLUDED.sort_order,
      item_title = EXCLUDED.item_title, item_summary = EXCLUDED.item_summary,
      metadata = EXCLUDED.metadata, updated_by = EXCLUDED.updated_by,
      row_revision = feature.curation_items.row_revision + 1,
      updated_at = clock_timestamp()
    WHERE (feature.curation_items.feature_id, feature.curation_items.source_present,
           feature.curation_items.place_name, feature.curation_items.address_hint,
           feature.curation_items.sort_order, feature.curation_items.item_title,
           feature.curation_items.item_summary, feature.curation_items.metadata)
      IS DISTINCT FROM
          (EXCLUDED.feature_id, true, EXCLUDED.place_name, EXCLUDED.address_hint,
           EXCLUDED.sort_order, EXCLUDED.item_title, EXCLUDED.item_summary,
           EXCLUDED.metadata)
    RETURNING curation_item_id, collection_id, (xmax = 0) AS inserted
  )
  SELECT count(*) FILTER (WHERE inserted)::integer,
         v_adopted + count(*) FILTER (WHERE NOT inserted)::integer,
         array_cat(v_changed_collection_ids,
                   COALESCE(array_agg(DISTINCT collection_id), ARRAY[]::uuid[])),
         array_cat(v_changed_item_ids,
                   COALESCE(array_agg(curation_item_id), ARRAY[]::uuid[]))
  INTO STRICT o_inserted, o_updated, v_changed_collection_ids, v_changed_item_ids
  FROM written;

  INSERT INTO feature.curation_import_batches (
    content_sha256, batch_kind, row_count, actor, metadata, command_id
  ) VALUES (
    p_content_sha256, p_batch_kind, jsonb_array_length(p_items), p_principal,
    jsonb_build_object(
      'schema_version', 1,
      'address_resolver', 'curation-address-v1'
    ),
    p_command_id
  ) RETURNING import_batch_id INTO STRICT o_import_batch_id;

  WITH incoming AS MATERIALIZED (
    SELECT * FROM jsonb_to_recordset(p_items) AS value(
      row_number integer, collection_id uuid, feature_id text,
      external_item_id text, external_component_id text,
      provenance jsonb, row_payload jsonb
    )
  ), identities AS MATERIALIZED (
    SELECT incoming.*, item.curation_item_id, item.accepted_link_decision_id,
           previous.feature_id AS previous_feature_id,
           current_row.row_payload AS previous_row_payload,
           current_row.provenance AS previous_provenance
    FROM incoming JOIN feature.curation_items AS item
      ON item.collection_id = incoming.collection_id
     AND item.external_item_id = incoming.external_item_id
     AND item.external_component_id = incoming.external_component_id
    LEFT JOIN feature.curation_link_decisions AS previous
      ON previous.decision_id = item.accepted_link_decision_id
    LEFT JOIN feature.curation_import_rows AS current_row
      ON current_row.import_row_id = item.current_import_row_id
  ), inserted_rows AS MATERIALIZED (
    INSERT INTO feature.curation_import_rows (
      import_batch_id, curation_item_id, row_number, source_row_sha256,
      row_payload, provenance
    )
    SELECT o_import_batch_id, curation_item_id, row_number,
           encode(x_extension.digest(row_payload::text, 'sha256'), 'hex'),
           row_payload, COALESCE(provenance, '{}'::jsonb)
    FROM identities
    RETURNING import_row_id, curation_item_id, row_number
  ), decisions AS MATERIALIZED (
    INSERT INTO feature.curation_link_decisions (
      curation_item_id, feature_id, import_row_id, decision_kind, match_basis,
      resolver_version, evidence, actor, supersedes_decision_id
    )
    SELECT identity.curation_item_id,
           COALESCE(identity.feature_id, identity.previous_feature_id),
           inserted.import_row_id,
           CASE WHEN identity.feature_id IS NULL THEN 'revoked' ELSE 'accepted' END,
           'csv_explicit_feature_id', 'explicit-feature-id-v1',
           jsonb_build_object(
             'source_row_sha256', encode(x_extension.digest(identity.row_payload::text, 'sha256'), 'hex'),
             'requested_feature_id', identity.feature_id
           ), p_principal, identity.accepted_link_decision_id
    FROM identities AS identity
    JOIN inserted_rows AS inserted
      ON inserted.curation_item_id = identity.curation_item_id
     AND inserted.row_number = identity.row_number
    WHERE (identity.feature_id IS NOT NULL OR identity.accepted_link_decision_id IS NOT NULL)
      AND (identity.previous_row_payload, identity.previous_provenance)
          IS DISTINCT FROM (identity.row_payload, COALESCE(identity.provenance, '{}'::jsonb))
    RETURNING decision_id, curation_item_id, decision_kind
  ), pointer_updates AS (
  UPDATE feature.curation_items AS item
  SET current_import_row_id = inserted.import_row_id,
      accepted_link_decision_id = CASE
        WHEN decision.decision_kind = 'accepted' THEN decision.decision_id ELSE NULL END,
      updated_by = p_principal,
      row_revision = item.row_revision + CASE
        WHEN item.curation_item_id = ANY(v_changed_item_ids) THEN 0 ELSE 1 END,
      updated_at = clock_timestamp()
  FROM inserted_rows AS inserted
  LEFT JOIN decisions AS decision ON decision.curation_item_id = inserted.curation_item_id
  WHERE item.curation_item_id = inserted.curation_item_id
    AND EXISTS (
      SELECT 1
      FROM identities AS identity
      WHERE identity.curation_item_id = inserted.curation_item_id
        AND (identity.previous_row_payload, identity.previous_provenance)
            IS DISTINCT FROM (
              identity.row_payload,
              COALESCE(identity.provenance, '{}'::jsonb)
            )
    )
  RETURNING item.curation_item_id, item.collection_id,
            NOT (item.curation_item_id = ANY(v_changed_item_ids)) AS provenance_only
  )
  SELECT o_updated + count(*) FILTER (WHERE provenance_only)::integer,
         array_cat(v_changed_collection_ids,
                   COALESCE(array_agg(DISTINCT collection_id), ARRAY[]::uuid[])),
         array_cat(v_changed_item_ids,
                   COALESCE(array_agg(curation_item_id), ARRAY[]::uuid[]))
  INTO STRICT o_updated, v_changed_collection_ids, v_changed_item_ids
  FROM pointer_updates;

  FOR v_collection_id IN
    SELECT DISTINCT changed_id FROM unnest(v_changed_collection_ids) AS changed_id
  LOOP
    CALL feature.touch_curation_import_collection_command(
      v_collection_id, p_command_id, p_principal, v_collection_revision
    );
  END LOOP;
END
$_$;
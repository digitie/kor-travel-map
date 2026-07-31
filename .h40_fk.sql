\set ON_ERROR_STOP 0
CREATE SCHEMA IF NOT EXISTS feature;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DROP TABLE IF EXISTS feature.curation_link_decisions CASCADE;
DROP TABLE IF EXISTS feature.curation_items CASCADE;

CREATE TABLE feature.curation_items (
  curation_item_id uuid PRIMARY KEY,
  feature_id text,
  current_import_row_id uuid,
  accepted_link_decision_id uuid
);

CREATE TABLE feature.curation_link_decisions (
  decision_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  curation_item_id uuid NOT NULL,
  feature_id text NOT NULL,
  decision_kind text NOT NULL,
  match_basis text NOT NULL,
  resolver_version text NOT NULL,
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  actor text NOT NULL,
  decided_at timestamptz NOT NULL DEFAULT now(),
  supersedes_decision_id uuid,
  CONSTRAINT ck_kind CHECK (decision_kind IN ('accepted','revoked')),
  CONSTRAINT ck_basis CHECK (match_basis IN ('csv_explicit_feature_id','admin_review','legacy_unattributed','forward_recovery')),
  CONSTRAINT ck_resolver CHECK (resolver_version = btrim(resolver_version) AND resolver_version <> ''),
  CONSTRAINT ck_evidence CHECK (jsonb_typeof(evidence) = 'object'),
  CONSTRAINT ck_actor CHECK (actor = btrim(actor) AND actor <> ''),
  CONSTRAINT fk_item FOREIGN KEY (curation_item_id)
    REFERENCES feature.curation_items(curation_item_id) ON DELETE RESTRICT,
  CONSTRAINT uq_item_target UNIQUE (decision_id, curation_item_id, feature_id)
);

ALTER TABLE feature.curation_items
  ADD CONSTRAINT fk_accepted FOREIGN KEY (accepted_link_decision_id, curation_item_id, feature_id)
  REFERENCES feature.curation_link_decisions(decision_id, curation_item_id, feature_id)
  ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

-- seed: 0072 backfill shape
INSERT INTO feature.curation_items (curation_item_id, feature_id)
VALUES ('11111111-1111-1111-1111-111111111111','F_OLD');
WITH ins AS (
  INSERT INTO feature.curation_link_decisions
    (curation_item_id, feature_id, decision_kind, match_basis, resolver_version, actor)
  VALUES ('11111111-1111-1111-1111-111111111111','F_OLD','accepted','legacy_unattributed','pre-0072-unknown','migration:0072')
  RETURNING decision_id
)
UPDATE feature.curation_items SET accepted_link_decision_id = ins.decision_id
FROM ins WHERE curation_item_id='11111111-1111-1111-1111-111111111111';

\echo '=== T_A: rotate curation_items PK (merge _DETACH...) ==='
BEGIN;
SET CONSTRAINTS ALL DEFERRED;
UPDATE feature.curation_items SET curation_item_id = gen_random_uuid()
WHERE curation_item_id='11111111-1111-1111-1111-111111111111';
COMMIT;

\echo '=== T_B: 0065 trigger changes item.feature_id, pointer untouched ==='
BEGIN;
UPDATE feature.curation_items SET feature_id='F_NEW'
WHERE curation_item_id='11111111-1111-1111-1111-111111111111';
\echo '--- statement survived (deferred); now COMMIT ---'
COMMIT;

\echo '=== state after T_B ==='
SELECT feature_id, accepted_link_decision_id IS NOT NULL AS has_ptr FROM feature.curation_items;

\echo '=== T_C: same-txn issue new decision + advance pointer + change feature_id ==='
BEGIN;
WITH ins AS (
  INSERT INTO feature.curation_link_decisions
    (curation_item_id, feature_id, decision_kind, match_basis, resolver_version, actor, supersedes_decision_id)
  SELECT i.curation_item_id, 'F_NEW', 'accepted', 'forward_recovery', 'v1', 'trigger:sync', i.accepted_link_decision_id
  FROM feature.curation_items i WHERE i.curation_item_id='11111111-1111-1111-1111-111111111111'
  RETURNING decision_id, curation_item_id
)
UPDATE feature.curation_items SET feature_id='F_NEW', accepted_link_decision_id=ins.decision_id
FROM ins WHERE feature.curation_items.curation_item_id = ins.curation_item_id;
COMMIT;
SELECT feature_id, (SELECT count(*) FROM feature.curation_link_decisions) AS decisions FROM feature.curation_items;

\echo '=== T_D: NULL actor / empty actor ==='
BEGIN;
INSERT INTO feature.curation_link_decisions (curation_item_id, feature_id, decision_kind, match_basis, resolver_version, actor)
SELECT curation_item_id,'F_NEW','accepted','forward_recovery','v1',NULL FROM feature.curation_items;
ROLLBACK;
BEGIN;
INSERT INTO feature.curation_link_decisions (curation_item_id, feature_id, decision_kind, match_basis, resolver_version, actor)
SELECT curation_item_id,'F_NEW','accepted','forward_recovery','v1','' FROM feature.curation_items;
ROLLBACK;

\echo '=== T_E: new match_basis value rejected by CHECK ==='
BEGIN;
INSERT INTO feature.curation_link_decisions (curation_item_id, feature_id, decision_kind, match_basis, resolver_version, actor)
SELECT curation_item_id,'F_NEW','accepted','source_rule_projection','v1','x' FROM feature.curation_items;
ROLLBACK;

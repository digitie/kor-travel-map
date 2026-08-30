"""T-VN-M03 — import 행별 manual Feature child command linkage.

Revision ID: 301_m03_import_children
Revises: 300

single-item admin editing은 ``feature.create_manual_curation_item_with_feature_command``
하나로 닫힌다(`0228`). import는 부모 ``admin.curation.import`` command가 batch의
preview/commit lifecycle을 소유하고, 실제 manual Feature 생성은 plan row마다 private
child command로 분리한다(설계 §6).

본 revision은 그 **linkage만** 선언적으로 만든다. 부모/import-row/child-command의
immutable 결박과 one-row/one-child uniqueness가 DB 제약이어야, 부모 summary를 요청
JSON이 아니라 이 표에서 순서대로 구성할 수 있다.

이 linkage는 claim/origin의 command FK를 대체하지 않는다. 어느 경로에서도
``admin.curation.import`` 하나에 여러 claim/origin을 직접 묶거나 manual row를
추론해서는 안 된다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# ruff: noqa: E501

revision: str = "301_m03_import_children"
down_revision: str | Sequence[str] | None = "300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DDL_SQL = r"""
-- child linkage가 참조할 두 축을 먼저 unique로 만든다. 둘 다 additive이며 기존
-- 제약을 바꾸지 않는다.
--
-- (1) plan claim은 `import_plan_id`가 PK지만, child는 **어느 plan 내용(sha)에
--     대한 claim이었는지**까지 결박해야 한다. plan이 재해소되면 sha가 달라지므로
--     child가 다른 내용의 plan에 붙는 일이 생겨선 안 된다.
ALTER TABLE ops.curation_import_plan_claims
    ADD CONSTRAINT uq_curation_import_plan_claims_plan_sha256
        UNIQUE (import_plan_id, plan_sha256);

-- (2) link decision은 `(decision_id, curation_item_id)`와
--     `(decision_id, curation_item_id, feature_id)`가 이미 unique다. child는
--     **어느 import row가 만든 decision인지**를 결박해야 하므로 그 triple을 더한다.
ALTER TABLE feature.curation_link_decisions
    ADD CONSTRAINT uq_curation_link_decisions_import_row_pointer
        UNIQUE (decision_id, curation_item_id, import_row_id);


CREATE TABLE ops.curation_import_manual_feature_children (
    import_plan_id        uuid        NOT NULL,
    plan_row_number       integer     NOT NULL,
    plan_sha256           text        NOT NULL,
    manual_payload_sha256 text        NOT NULL,
    child_command_id      bigint      NOT NULL,
    feature_uuid          uuid        NOT NULL,
    import_row_id         uuid        NOT NULL,
    curation_item_id      uuid        NOT NULL,
    link_decision_id      uuid        NOT NULL,
    recorded_at           timestamptz NOT NULL DEFAULT clock_timestamp(),

    -- 한 plan row는 정확히 하나의 child를 갖는다.
    CONSTRAINT pk_curation_import_manual_feature_children
        PRIMARY KEY (import_plan_id, plan_row_number),
    -- 한 child command는 정확히 하나의 row에만 쓰인다. 외부가 child key를 제공하거나
    -- child를 단독 replay하는 route가 없다는 계약의 DB 측 표현이다.
    CONSTRAINT uq_curation_import_manual_feature_children_command
        UNIQUE (child_command_id),
    -- 한 import row는 정확히 하나의 child가 만든다.
    CONSTRAINT uq_curation_import_manual_feature_children_import_row
        UNIQUE (import_row_id),

    CONSTRAINT ck_curation_import_manual_feature_children_plan_sha256
        CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_curation_import_manual_feature_children_payload_sha256
        CHECK (manual_payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_curation_import_manual_feature_children_row_number
        CHECK (plan_row_number >= 2),

    -- plan claim + 그 claim이 본 plan 내용
    CONSTRAINT fk_curation_import_manual_feature_children_plan_claim
        FOREIGN KEY (import_plan_id, plan_sha256)
        REFERENCES ops.curation_import_plan_claims (import_plan_id, plan_sha256)
        ON DELETE RESTRICT,
    -- immutable plan row
    CONSTRAINT fk_curation_import_manual_feature_children_plan_row
        FOREIGN KEY (import_plan_id, plan_row_number)
        REFERENCES feature.curation_import_plan_rows (import_plan_id, row_number)
        ON DELETE RESTRICT,
    -- child command 자체
    CONSTRAINT fk_curation_import_manual_feature_children_command
        FOREIGN KEY (child_command_id)
        REFERENCES ops.domain_commands (command_id)
        ON DELETE RESTRICT,
    -- claim causation: 이 Feature를 claim한 것이 **이 child command**여야 한다
    CONSTRAINT fk_curation_import_manual_feature_children_claim
        FOREIGN KEY (feature_uuid, child_command_id)
        REFERENCES feature.manual_feature_identity_claims (feature_id, claimed_by_command_id)
        ON DELETE RESTRICT,
    -- receipt: import row와 curation item이 서로를 가리켜야 한다
    CONSTRAINT fk_curation_import_manual_feature_children_receipt
        FOREIGN KEY (import_row_id, curation_item_id)
        REFERENCES feature.curation_import_rows (import_row_id, curation_item_id)
        ON DELETE RESTRICT,
    -- decision evidence: accepted link decision이 그 item과 그 import row의 것이어야 한다
    CONSTRAINT fk_curation_import_manual_feature_children_decision
        FOREIGN KEY (link_decision_id, curation_item_id, import_row_id)
        REFERENCES feature.curation_link_decisions (decision_id, curation_item_id, import_row_id)
        ON DELETE RESTRICT
);

COMMENT ON TABLE ops.curation_import_manual_feature_children IS
    'T-VN-M03: import plan row -> manual Feature child command의 immutable linkage. '
    '부모 summary는 요청 JSON이 아니라 이 표에서 순서대로 구성한다.';

-- 부모 summary를 plan row 순서로 읽는 경로.
CREATE INDEX idx_curation_import_manual_feature_children_plan
    ON ops.curation_import_manual_feature_children (import_plan_id, plan_row_number);


-- append-only 봉인. 이 표는 command evidence이므로 정정하지 않는다 — 잘못된 child가
-- 있으면 부모 command 전체가 rollback돼야 하고, 그것이 SERIALIZABLE 단일 transaction
-- 계약의 존재 이유다.
CREATE OR REPLACE FUNCTION ops.curation_import_manual_feature_children_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'ops.curation_import_manual_feature_children is append-only (%)', TG_OP
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_curation_import_manual_feature_children_append_only
    BEFORE UPDATE OR DELETE OR TRUNCATE
    ON ops.curation_import_manual_feature_children
    FOR EACH STATEMENT
    EXECUTE FUNCTION ops.curation_import_manual_feature_children_append_only();
"""


_DOWNGRADE_SQL = r"""
DROP TRIGGER IF EXISTS trg_curation_import_manual_feature_children_append_only
    ON ops.curation_import_manual_feature_children;
DROP FUNCTION IF EXISTS ops.curation_import_manual_feature_children_append_only();
DROP TABLE IF EXISTS ops.curation_import_manual_feature_children;
ALTER TABLE feature.curation_link_decisions
    DROP CONSTRAINT IF EXISTS uq_curation_link_decisions_import_row_pointer;
ALTER TABLE ops.curation_import_plan_claims
    DROP CONSTRAINT IF EXISTS uq_curation_import_plan_claims_plan_sha256;
"""


_POSTCONDITION_SQL = r"""
DO $$
DECLARE
    missing text;
BEGIN
    SELECT string_agg(expected, ', ')
      INTO missing
      FROM (
        VALUES
          ('pk_curation_import_manual_feature_children'),
          ('uq_curation_import_manual_feature_children_command'),
          ('uq_curation_import_manual_feature_children_import_row'),
          ('fk_curation_import_manual_feature_children_plan_claim'),
          ('fk_curation_import_manual_feature_children_plan_row'),
          ('fk_curation_import_manual_feature_children_command'),
          ('fk_curation_import_manual_feature_children_claim'),
          ('fk_curation_import_manual_feature_children_receipt'),
          ('fk_curation_import_manual_feature_children_decision')
      ) AS wanted(expected)
     WHERE NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = wanted.expected
     );
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'M03 child linkage 제약이 만들어지지 않았다: %', missing;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgname = 'trg_curation_import_manual_feature_children_append_only'
           AND NOT tgisinternal
    ) THEN
        RAISE EXCEPTION 'M03 child linkage append-only trigger가 없다';
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.execute(_DDL_SQL)
    op.execute(_POSTCONDITION_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)

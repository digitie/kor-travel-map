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

DDL은 **문장 하나씩** 실행한다. asyncpg는 prepared statement에 여러 문장을 넣지 못해
(`cannot insert multiple commands into a prepared statement`) 통합 테스트의 migration
fixture가 실패한다. `0231`도 같은 이유로 문장마다 ``op.execute``를 호출한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

# ruff: noqa: E501

revision: str = "301_m03_import_children"
down_revision: str | Sequence[str] | None = "300"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# child linkage가 참조할 두 축을 먼저 unique로 만든다. 둘 다 additive이며 기존
# 제약을 바꾸지 않는다.
#
# (1) plan claim은 `import_plan_id`가 PK지만, child는 **어느 plan 내용(sha)에 대한
#     claim이었는지**까지 결박해야 한다. plan이 재해소되면 sha가 달라지므로 child가
#     다른 내용의 plan에 붙는 일이 생겨선 안 된다.
_CLAIM_PLAN_SHA_UNIQUE: Final = """
ALTER TABLE ops.curation_import_plan_claims
    ADD CONSTRAINT uq_curation_import_plan_claims_plan_sha256
        UNIQUE (import_plan_id, plan_sha256)
"""

# (2) link decision은 `(decision_id, curation_item_id)`와 `+feature_id`가 이미
#     unique다. child는 **어느 import row가 만든 decision인지**를 결박해야 하므로
#     그 triple을 더한다.
_DECISION_IMPORT_ROW_UNIQUE: Final = """
ALTER TABLE feature.curation_link_decisions
    ADD CONSTRAINT uq_curation_link_decisions_import_row_pointer
        UNIQUE (decision_id, curation_item_id, import_row_id)
"""

_CREATE_TABLE: Final = """
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

    CONSTRAINT pk_curation_import_manual_feature_children
        PRIMARY KEY (import_plan_id, plan_row_number),
    CONSTRAINT uq_curation_import_manual_feature_children_command
        UNIQUE (child_command_id),
    CONSTRAINT uq_curation_import_manual_feature_children_import_row
        UNIQUE (import_row_id),

    CONSTRAINT ck_curation_import_manual_feature_children_plan_sha256
        CHECK (plan_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_curation_import_manual_feature_children_payload_sha256
        CHECK (manual_payload_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_curation_import_manual_feature_children_row_number
        CHECK (plan_row_number >= 2),

    CONSTRAINT fk_curation_import_manual_feature_children_plan_claim
        FOREIGN KEY (import_plan_id, plan_sha256)
        REFERENCES ops.curation_import_plan_claims (import_plan_id, plan_sha256)
        ON DELETE RESTRICT,
    CONSTRAINT fk_curation_import_manual_feature_children_plan_row
        FOREIGN KEY (import_plan_id, plan_row_number)
        REFERENCES feature.curation_import_plan_rows (import_plan_id, row_number)
        ON DELETE RESTRICT,
    CONSTRAINT fk_curation_import_manual_feature_children_command
        FOREIGN KEY (child_command_id)
        REFERENCES ops.domain_commands (command_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_curation_import_manual_feature_children_claim
        FOREIGN KEY (feature_uuid, child_command_id)
        REFERENCES feature.manual_feature_identity_claims (feature_id, claimed_by_command_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_curation_import_manual_feature_children_receipt
        FOREIGN KEY (import_row_id, curation_item_id)
        REFERENCES feature.curation_import_rows (import_row_id, curation_item_id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_curation_import_manual_feature_children_decision
        FOREIGN KEY (link_decision_id, curation_item_id, import_row_id)
        REFERENCES feature.curation_link_decisions (decision_id, curation_item_id, import_row_id)
        ON DELETE RESTRICT
)
"""

_TABLE_OWNER: Final = """
ALTER TABLE ops.curation_import_manual_feature_children
    OWNER TO ktm_feature_schema_owner
"""

# 형제 receipt 표와 같은 권한. command owner만 쓰고 runtime role은 읽지 않는다
# (`runtime_privileges.py`의 이 표 선언이 `()`인 것과 짝을 이룬다).
_TABLE_GRANT: Final = """
GRANT SELECT, INSERT ON TABLE ops.curation_import_manual_feature_children
    TO ktm_curation_command_owner
"""

_TABLE_COMMENT: Final = """
COMMENT ON TABLE ops.curation_import_manual_feature_children IS
    'T-VN-M03: import plan row -> manual Feature child command의 immutable linkage. 부모 summary는 요청 JSON이 아니라 이 표에서 순서대로 구성한다.'
"""

# append-only 봉인. 이 표는 command evidence이므로 정정하지 않는다 — 잘못된 child가
# 있으면 부모 command 전체가 rollback돼야 하고, 그것이 SERIALIZABLE 단일 transaction
# 계약의 존재 이유다.
_APPEND_ONLY_FUNCTION: Final = """
CREATE OR REPLACE FUNCTION ops.curation_import_manual_feature_children_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'ops.curation_import_manual_feature_children is append-only (%)', TG_OP
        USING ERRCODE = '55000';
END;
$$
"""

_APPEND_ONLY_TRIGGER: Final = """
CREATE TRIGGER trg_curation_import_manual_feature_children_append_only
    BEFORE UPDATE OR DELETE OR TRUNCATE
    ON ops.curation_import_manual_feature_children
    FOR EACH STATEMENT
    EXECUTE FUNCTION ops.curation_import_manual_feature_children_append_only()
"""

# `ops.application_schema_operation_receipts`의 head CHECK는 baseline이 `300`만
# 허용하도록 만들었다. child migration이 붙은 뒤 fresh 설치는 자신의 head를 receipt에
# 적으므로 그대로 두면 DB CHECK 위반으로 막힌다.
#
# 값을 **열거**한다. 형식만 검사하도록 푸는 편이 간단하지만, 그러면 DB 층의
# fail-close 하나가 사라진다 — 정확한 head 동등성은 executable·finalize·permit 셋이
# 이미 강제하지만 중복 방어를 스스로 줄이지 않는다. migration마다 자기 head를 더한다.
#
# 그 "더한다"를 사람 기억에 맡기지 않는다.
# `tests/lint/test_receipt_head_check_covers_the_graph_head.py`가 현재 graph head가
# 이 열거에 없으면 실패한다 — 잊으면 CI에서 잡히고, 프로덕션 fresh 설치가 CHECK
# 위반으로 죽는 일은 생기지 않는다.
_RECEIPT_HEAD_CHECK: Final = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head
        CHECK (destination_head IN ('300', '301_m03_import_children'))
"""

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    _CLAIM_PLAN_SHA_UNIQUE,
    _DECISION_IMPORT_ROW_UNIQUE,
    _CREATE_TABLE,
    _TABLE_OWNER,
    _TABLE_GRANT,
    _TABLE_COMMENT,
    _APPEND_ONLY_FUNCTION,
    _APPEND_ONLY_TRIGGER,
    _RECEIPT_HEAD_CHECK,
)

_DOWNGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    # receipt CHECK를 baseline 전용으로 되돌린다. 되돌린 뒤 head가 `300`이 아닌
    # receipt 행이 남아 있으면 이 문장이 실패한다 — 그게 맞다. 조용히 넘어가면
    # CHECK가 거짓이 된 표를 남긴다.
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head = '300')",
    "DROP TRIGGER IF EXISTS trg_curation_import_manual_feature_children_append_only"
    " ON ops.curation_import_manual_feature_children",
    "DROP FUNCTION IF EXISTS ops.curation_import_manual_feature_children_append_only()",
    "DROP TABLE IF EXISTS ops.curation_import_manual_feature_children",
    "ALTER TABLE feature.curation_link_decisions"
    " DROP CONSTRAINT IF EXISTS uq_curation_link_decisions_import_row_pointer",
    "ALTER TABLE ops.curation_import_plan_claims"
    " DROP CONSTRAINT IF EXISTS uq_curation_import_plan_claims_plan_sha256",
)

_POSTCONDITION: Final = """
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
        SELECT 1 FROM pg_constraint WHERE conname = wanted.expected
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
$$
"""


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    op.execute(_POSTCONDITION)


def downgrade() -> None:
    for statement in _DOWNGRADE_STATEMENTS:
        op.execute(statement)

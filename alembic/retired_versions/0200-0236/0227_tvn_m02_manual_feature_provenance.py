"""T-VN-M02 — manual Feature provenance reader와 hard-purge fence.

Revision ID: 0227_m02_feature_provenance
Revises: 0226_m01_manual_feature_create

claim/origin base relation의 direct runtime SELECT는 계속 금지한다. 이 revision은
현재 Feature가 존재할 때만 한 row를 내는 API-only SECURITY DEFINER reader와,
manual evidence가 있는 Feature의 hard delete를 막는 trigger를 추가한다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from alembic import op

# ruff: noqa: E501

revision: str = "0227_m02_feature_provenance"
down_revision: str | Sequence[str] | None = "0226_m01_manual_feature_create"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DDL_SQL = r"""
CREATE FUNCTION feature.read_admin_manual_feature_provenance(p_feature_uuid uuid)
RETURNS TABLE(
    feature_id uuid,
    feature_kind text,
    name_key text,
    lon_e6 integer,
    lat_e6 integer,
    claim_basis text,
    claimed_at timestamp with time zone,
    claimed_by_command_id bigint,
    origin_kind text,
    creation_command_id bigint,
    creator_principal_id text,
    created_by_actor text,
    origin_created_at timestamp with time zone,
    invoker_role text,
    procedure_definer text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $m02_provenance_reader$
BEGIN
    IF p_feature_uuid IS NULL THEN
        RAISE EXCEPTION 'manual Feature provenance requires a canonical UUID'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_provenance_input';
    END IF;

    -- ``features``를 driving relation으로 고정한다. purge 뒤 evidence는 남아도
    -- 일반 admin detail/read route로 그 snapshot을 탐색할 수 없다.
    RETURN QUERY
    SELECT
        core.feature_uuid,
        claim.feature_kind,
        claim.name_key,
        claim.lon_e6,
        claim.lat_e6,
        claim.claim_basis,
        claim.claimed_at,
        claim.claimed_by_command_id,
        origin.origin_kind,
        origin.creation_command_id,
        origin.creator_principal_id,
        origin.created_by_actor,
        origin.created_at,
        origin.invoker_role,
        origin.procedure_definer
    FROM feature.features AS core
    LEFT JOIN feature.manual_feature_identity_claims AS claim
      ON claim.feature_id = core.feature_uuid
    LEFT JOIN feature.feature_creation_origins AS origin
      ON origin.feature_id = claim.feature_id
     AND origin.creation_command_id = claim.claimed_by_command_id
    WHERE core.feature_uuid = p_feature_uuid;
END
$m02_provenance_reader$;

CREATE FUNCTION feature.reject_manual_feature_hard_purge()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $m02_purge_fence$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM feature.manual_feature_identity_claims AS claim
        WHERE claim.feature_id = OLD.feature_uuid
    ) THEN
        RAISE EXCEPTION 'manual Feature hard purge is not ready'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_manual_feature_purge_not_ready';
    END IF;
    RETURN OLD;
END
$m02_purge_fence$;

CREATE TRIGGER trg_features_manual_feature_hard_purge_fence
    BEFORE DELETE ON feature.features
    FOR EACH ROW EXECUTE FUNCTION feature.reject_manual_feature_hard_purge();

ALTER FUNCTION feature.read_admin_manual_feature_provenance(uuid)
    OWNER TO ktm_manual_feature_procedure_owner;
ALTER FUNCTION feature.reject_manual_feature_hard_purge()
    OWNER TO ktm_manual_feature_procedure_owner;

REVOKE ALL ON FUNCTION feature.read_admin_manual_feature_provenance(uuid)
    FROM PUBLIC, ktm_feature_runtime, ktm_feature_dagster_runtime,
    ktm_feature_create_provider_executor;
GRANT EXECUTE ON FUNCTION feature.read_admin_manual_feature_provenance(uuid)
    TO ktm_manual_feature_admin_executor;
REVOKE ALL ON FUNCTION feature.reject_manual_feature_hard_purge()
    FROM PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime,
    ktm_feature_dagster_runtime, ktm_manual_feature_procedure_owner,
    ktm_manual_feature_admin_executor, ktm_feature_create_provider_executor;
"""


def _top_level_statements(sql: str) -> tuple[str, ...]:
    """static M02 DDL을 asyncpg prepare 단위로 나눈다."""

    statements: list[str] = []
    start = 0
    index = 0
    dollar_tag: str | None = None
    quoted = False
    while index < len(sql):
        char = sql[index]
        if dollar_tag is not None:
            if sql.startswith(dollar_tag, index):
                index += len(dollar_tag)
                dollar_tag = None
                continue
            index += 1
            continue
        if quoted:
            if char == "'":
                if index + 1 < len(sql) and sql[index + 1] == "'":
                    index += 2
                    continue
                quoted = False
            index += 1
            continue
        if char == "'":
            quoted = True
            index += 1
            continue
        if char == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[index:])
            if match is not None:
                dollar_tag = match.group(0)
                index += len(dollar_tag)
                continue
        if char == ";":
            statement = sql[start : index + 1].strip()
            if statement:
                statements.append(statement)
            start = index + 1
        index += 1
    trailing = sql[start:].strip()
    if trailing:
        statements.append(trailing)
    return tuple(statements)


def upgrade() -> None:
    for statement in _top_level_statements(_DDL_SQL):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("0227_m02_feature_provenance is forward-only")

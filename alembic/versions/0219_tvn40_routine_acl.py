"""T-VN-40B application routine EXECUTE 경계를 exact catalog로 닫는다.

Revision ID: 0219_tvn40_routine_acl
Revises: 0218_tvn40_metadata_check
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0219_tvn40_routine_acl"
down_revision: str | Sequence[str] | None = "0218_tvn40_metadata_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNTIME_IDENTITIES = (
    "PUBLIC, ktm_feature_runtime, ktm_feature_api_runtime, "
    "ktm_feature_dagster_runtime, ktm_curation_admin_executor, "
    "ktm_curation_provider_executor"
)

_SCHEMA_OWNER_FUNCTIONS = (
    "feature.current_provider_curation_input_set(bigint)",
)

_STATE_OWNER_FUNCTIONS = (
    "feature.lock_current_provider_feature_source_evidence(text,bigint,text,text)",
    "feature.lock_current_provider_source_evidence(bigint,text,text)",
)

_AUDIT_WRITER_FUNCTIONS = (
    "feature.reject_curation_provider_receipt_mutation()",
    "ops.reject_curation_import_collection_effect_mutation()",
    "ops.reject_curation_import_collection_effect_truncate()",
    "ops.reject_curation_import_plan_mutation()",
    "ops.reject_curation_import_plan_truncate()",
)

_API_COMMAND_FUNCTIONS = (
    "ops.fill_provider_cancellation_starts_command(uuid,text,timestamptz)",
    (
        "ops.transition_provider_cancellation_job_command("
        "uuid,uuid,text,text[],text,text,text,timestamptz,timestamptz,boolean,text,text[])"
    ),
)


def _revoke_direct_execute(*, owner: str, signatures: tuple[str, ...]) -> None:
    op.execute(f"SET ROLE {owner}")
    for signature in signatures:
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM {_RUNTIME_IDENTITIES}"
        )
    op.execute("SET ROLE ktm_feature_schema_owner")


def upgrade() -> None:
    _revoke_direct_execute(
        owner="ktm_feature_schema_owner",
        signatures=_SCHEMA_OWNER_FUNCTIONS,
    )
    _revoke_direct_execute(
        owner="ktm_feature_state_procedure_owner",
        signatures=_STATE_OWNER_FUNCTIONS,
    )
    _revoke_direct_execute(
        owner="ktm_curation_audit_writer",
        signatures=_AUDIT_WRITER_FUNCTIONS,
    )

    op.execute("SET ROLE ktm_curation_command_owner")
    for signature in _API_COMMAND_FUNCTIONS:
        op.execute(
            f"REVOKE ALL ON FUNCTION {signature} FROM {_RUNTIME_IDENTITIES}"
        )
        op.execute(
            f"GRANT EXECUTE ON FUNCTION {signature} TO ktm_feature_api_runtime"
        )
    op.execute("SET ROLE ktm_feature_schema_owner")


def downgrade() -> None:
    raise RuntimeError(
        "0219_tvn40_routine_acl is forward-only; rebuild with the T-VN-40 release head"
    )

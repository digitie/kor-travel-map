"""integrity finding 최신 관측 시각·durable FK 정정.

``detected_at``은 최초 탐지 시각으로 보존하고 recurrence는 ``last_seen_at``으로 정렬한다.
Feature 삭제가 ledger를 지우지 않도록 FK를 ``ON DELETE SET NULL``로 바꾼다. 구
``address_validation:...`` key는 source entity type을 생략하고 길이가 무제한이므로 기존
열린 행을 이력으로 닫고, 다음 적재부터 고정 길이 ``av2_<sha256>`` key로 재생성한다.

Revision ID: 0068_integrity_last_seen
Revises: 0067_integrity_dedupe_key
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0068_integrity_last_seen"
down_revision: str | Sequence[str] | None = "0067_integrity_dedupe_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "data_integrity_violations"
_SCHEMA = "ops"
_FEATURE_FK = "fk_data_integrity_violations_feature_id_features"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        schema=_SCHEMA,
    )
    op.execute(
        """
        UPDATE ops.data_integrity_violations
        SET last_seen_at = COALESCE(
                (payload ->> 'last_seen_at')::timestamp AT TIME ZONE 'UTC',
                detected_at
            ),
            payload = payload - 'last_seen_at'
        """
    )
    op.alter_column(
        _TABLE,
        "last_seen_at",
        nullable=False,
        server_default=sa.text("now()"),
        schema=_SCHEMA,
    )

    op.execute(
        """
        UPDATE ops.data_integrity_violations
        SET status = 'resolved',
            resolved_at = COALESCE(resolved_at, statement_timestamp()),
            payload = payload || jsonb_build_object(
                'dedupe_key_migration',
                jsonb_build_object(
                    'from', 'address_validation_v1',
                    'to', 'av2',
                    'resolved_at', to_jsonb(statement_timestamp())
                )
            )
        WHERE status IN ('open', 'acknowledged')
          AND payload ->> 'dedupe_key' LIKE 'address_validation:%'
        """
    )

    op.drop_constraint(_FEATURE_FK, _TABLE, schema=_SCHEMA, type_="foreignkey")
    op.create_foreign_key(
        _FEATURE_FK,
        _TABLE,
        "features",
        ["feature_id"],
        ["feature_id"],
        source_schema=_SCHEMA,
        referent_schema="feature",
        ondelete="SET NULL",
    )

    op.drop_index("idx_violations_status_detected", table_name=_TABLE, schema=_SCHEMA)
    op.drop_index(
        "idx_violations_provider_status_detected",
        table_name=_TABLE,
        schema=_SCHEMA,
    )
    op.drop_index(
        "idx_violations_feature_detected",
        table_name=_TABLE,
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_violations_status_seen",
        _TABLE,
        ["status", sa.text("last_seen_at DESC"), sa.text("issue_id DESC")],
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_violations_provider_status_seen",
        _TABLE,
        [
            "provider",
            "status",
            sa.text("last_seen_at DESC"),
            sa.text("issue_id DESC"),
        ],
        schema=_SCHEMA,
        postgresql_where=sa.text("provider IS NOT NULL"),
    )
    op.create_index(
        "idx_violations_feature_seen",
        _TABLE,
        ["feature_id", sa.text("last_seen_at DESC"), sa.text("issue_id DESC")],
        schema=_SCHEMA,
        postgresql_where=sa.text("feature_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_violations_feature_seen", table_name=_TABLE, schema=_SCHEMA)
    op.drop_index(
        "idx_violations_provider_status_seen",
        table_name=_TABLE,
        schema=_SCHEMA,
    )
    op.drop_index("idx_violations_status_seen", table_name=_TABLE, schema=_SCHEMA)
    op.create_index(
        "idx_violations_status_detected",
        _TABLE,
        ["status", sa.text("detected_at DESC"), sa.text("issue_id DESC")],
        schema=_SCHEMA,
    )
    op.create_index(
        "idx_violations_provider_status_detected",
        _TABLE,
        [
            "provider",
            "status",
            sa.text("detected_at DESC"),
            sa.text("issue_id DESC"),
        ],
        schema=_SCHEMA,
        postgresql_where=sa.text("provider IS NOT NULL"),
    )
    op.create_index(
        "idx_violations_feature_detected",
        _TABLE,
        ["feature_id", sa.text("detected_at DESC"), sa.text("issue_id DESC")],
        schema=_SCHEMA,
        postgresql_where=sa.text("feature_id IS NOT NULL"),
    )

    op.drop_constraint(_FEATURE_FK, _TABLE, schema=_SCHEMA, type_="foreignkey")
    op.create_foreign_key(
        _FEATURE_FK,
        _TABLE,
        "features",
        ["feature_id"],
        ["feature_id"],
        source_schema=_SCHEMA,
        referent_schema="feature",
        ondelete="CASCADE",
    )
    op.drop_column(_TABLE, "last_seen_at", schema=_SCHEMA)

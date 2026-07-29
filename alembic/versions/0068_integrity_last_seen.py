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
_SET_NULL_FEATURE_FK = "fk_data_integrity_violations_feature_id_set_null"
_LAST_SEEN_NOT_NULL = "ck_data_integrity_violations_last_seen_not_null"


def upgrade() -> None:
    # ADD COLUMN의 ACCESS EXCLUSIVE lock을 대용량 backfill과 분리한다.
    with op.get_context().autocommit_block():
        op.add_column(
            _TABLE,
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            schema=_SCHEMA,
        )

    # ``payload``는 자유형 사용자 증거다. 과거 구현이 내부적으로 쓴 동명 키도
    # 신뢰할 수 있는 타입 계약이 없으므로 cast하거나 삭제하지 않고 최초 탐지 시각으로
    # 결정적으로 backfill한다.
    op.execute(
        """
        UPDATE ops.data_integrity_violations
        SET last_seen_at = detected_at
        WHERE last_seen_at IS NULL
        """
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

    # NOT NULL/FK scan 동안 ADD CONSTRAINT의 ACCESS EXCLUSIVE lock을 유지하지 않는다.
    op.execute(
        f"""
        ALTER TABLE {_SCHEMA}.{_TABLE}
        ADD CONSTRAINT {_LAST_SEEN_NOT_NULL}
        CHECK (last_seen_at IS NOT NULL)
        NOT VALID
        """
    )
    op.execute(
        f"""
        ALTER TABLE {_SCHEMA}.{_TABLE}
        ADD CONSTRAINT {_SET_NULL_FEATURE_FK}
        FOREIGN KEY (feature_id)
        REFERENCES feature.features(feature_id)
        ON DELETE SET NULL
        NOT VALID
        """
    )
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TABLE {_SCHEMA}.{_TABLE} "
            f"VALIDATE CONSTRAINT {_LAST_SEEN_NOT_NULL}"
        )
        op.execute(
            f"ALTER TABLE {_SCHEMA}.{_TABLE} "
            f"VALIDATE CONSTRAINT {_SET_NULL_FEATURE_FK}"
        )

    op.alter_column(
        _TABLE,
        "last_seen_at",
        nullable=False,
        server_default=sa.text("now()"),
        schema=_SCHEMA,
    )
    op.drop_constraint(_FEATURE_FK, _TABLE, schema=_SCHEMA, type_="foreignkey")
    op.execute(
        f"ALTER TABLE {_SCHEMA}.{_TABLE} "
        f"RENAME CONSTRAINT {_SET_NULL_FEATURE_FK} TO {_FEATURE_FK}"
    )
    op.execute(
        f"ALTER TABLE {_SCHEMA}.{_TABLE} "
        f"DROP CONSTRAINT {_LAST_SEEN_NOT_NULL}"
    )

    # 대용량 큐에서도 writer를 막지 않도록 교체 index는 concurrent DDL로 만든다.
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_violations_status_seen
            ON ops.data_integrity_violations
              (status, last_seen_at DESC, issue_id DESC)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_violations_provider_status_seen
            ON ops.data_integrity_violations
              (provider, status, last_seen_at DESC, issue_id DESC)
            WHERE provider IS NOT NULL
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_violations_feature_seen
            ON ops.data_integrity_violations
              (feature_id, last_seen_at DESC, issue_id DESC)
            WHERE feature_id IS NOT NULL
            """
        )
        op.execute(
            "DROP INDEX CONCURRENTLY ops.idx_violations_status_detected"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY "
            "ops.idx_violations_provider_status_detected"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY ops.idx_violations_feature_detected"
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

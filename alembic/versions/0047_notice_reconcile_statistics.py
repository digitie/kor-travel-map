"""notice reconcile join table의 planner 통계를 갱신한다.

Revision ID: 0047_notice_reconcile_stats
Revises: 0046_notice_snapshot_state
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0047_notice_reconcile_stats"
down_revision: str | Sequence[str] | None = "0046_notice_snapshot_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 0044 entity migration과 대량 provider 적재 뒤 feature.features 통계가 한 번도
    # 생성되지 않은 운영 DB에서 실제 102만 행을 약 970행으로 추정했다. notice
    # lifecycle query의 join 순서가 이 통계에 민감하므로 관련 정본 table을 한 번에
    # 갱신한다. 이후 변경분은 PostgreSQL autoanalyze가 유지한다.
    # PostgreSQL은 ANALYZE 권한이 없으면 오류 대신 WARNING 후 건너뛸 수 있으므로,
    # revision만 전진하는 조용한 실패를 먼저 차단한다.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM (
                    VALUES
                        ('feature', 'features'),
                        ('provider_sync', 'source_entities'),
                        ('provider_sync', 'source_records'),
                        ('provider_sync', 'source_links'),
                        ('provider_sync', 'notice_lifecycle_scopes'),
                        ('provider_sync', 'notice_lineage_states')
                ) AS required(schema_name, table_name)
                JOIN pg_namespace AS namespace
                  ON namespace.nspname = required.schema_name
                JOIN pg_class AS relation
                  ON relation.relnamespace = namespace.oid
                 AND relation.relname = required.table_name
                WHERE NOT (
                    pg_has_role(current_user, relation.relowner, 'USAGE')
                    OR pg_has_role(
                        current_user,
                        (
                            SELECT database.datdba
                            FROM pg_database AS database
                            WHERE database.datname = current_database()
                        ),
                        'USAGE'
                    )
                )
            ) THEN
                RAISE EXCEPTION
                    '0047 requires ownership of notice reconcile tables';
            END IF;
        END
        $$
        """
    )
    for table in (
        "feature.features",
        "provider_sync.source_entities",
        "provider_sync.source_records",
        "provider_sync.source_links",
        "provider_sync.notice_lifecycle_scopes",
        "provider_sync.notice_lineage_states",
    ):
        op.execute(f"ANALYZE {table}")


def downgrade() -> None:
    # planner 통계는 schema/data 계약이 아니며 PostgreSQL이 계속 갱신한다.
    pass

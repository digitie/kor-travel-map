"""provider refresh policy에 명시적 freshness SLA를 추가한다.

``system_interval_seconds``와 ``min_interval_seconds``는 각각 시스템 호출 주기와
rate-limit floor다. 둘 중 어느 것도 데이터가 stale이 되는 운영 SLA와 같지 않으므로
``stale_after_minutes``를 별도 nullable 필드로 둔다. 기존 정책은 추론 없이 NULL
(freshness unknown)로 유지한다.

Revision ID: 0049_refresh_stale_after
Revises: 0048_import_jobs_dagster_run_id
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0049_refresh_stale_after"
down_revision: str | Sequence[str] | None = "0048_import_jobs_dagster_run_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_refresh_policies",
        sa.Column("stale_after_minutes", sa.Integer(), nullable=True),
        schema="ops",
    )
    op.create_check_constraint(
        "ck_provider_refresh_stale_after",
        "provider_refresh_policies",
        "stale_after_minutes IS NULL OR stale_after_minutes > 0",
        schema="ops",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_provider_refresh_stale_after",
        "provider_refresh_policies",
        schema="ops",
        type_="check",
    )
    op.drop_column(
        "provider_refresh_policies",
        "stale_after_minutes",
        schema="ops",
    )

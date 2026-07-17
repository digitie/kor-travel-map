"""provider refresh policy에 단조 revision CAS를 추가한다.

Revision ID: 0056_provider_refresh_policy_revision
Revises: 0055_ops_live_ticket_claims
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0056_provider_refresh_policy_revision"
down_revision: str | Sequence[str] | None = "0055_ops_live_ticket_claims"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_refresh_policies",
        sa.Column(
            "revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema="ops",
    )
    op.create_check_constraint(
        "ck_provider_refresh_revision",
        "provider_refresh_policies",
        "revision > 0",
        schema="ops",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_provider_refresh_revision",
        "provider_refresh_policies",
        schema="ops",
        type_="check",
    )
    op.drop_column(
        "provider_refresh_policies",
        "revision",
        schema="ops",
    )

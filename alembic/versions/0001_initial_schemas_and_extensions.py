"""initial schemas + extensions (ADR-007 / ADR-008).

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-26 00:00:00.000000

4 schema (`feature` / `provider_sync` / `ops` / `x_extension`) + 3 extension
(`postgis` / `pg_trgm` / `pgcrypto`)을 `x_extension`에 격리해서 생성한다.
모든 후속 migration은 본 revision을 기반으로 한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SCHEMAS = ("feature", "provider_sync", "ops", "x_extension")
_EXTENSIONS = ("postgis", "pg_trgm", "pgcrypto")


def upgrade() -> None:
    # 4 schema 생성 (idempotent).
    for schema in _SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # 3 extension을 x_extension에 격리 (ADR-008). 이미 public에 박혀 있다면
    # DROP CASCADE 후 재생성 (testcontainers postgis image 호환).
    op.execute("DROP EXTENSION IF EXISTS postgis_topology CASCADE")
    op.execute("DROP EXTENSION IF EXISTS postgis CASCADE")
    for ext in _EXTENSIONS:
        op.execute(
            f"CREATE EXTENSION IF NOT EXISTS {ext} WITH SCHEMA x_extension"
        )


def downgrade() -> None:
    # extension drop (CASCADE).
    for ext in reversed(_EXTENSIONS):
        op.execute(f"DROP EXTENSION IF EXISTS {ext} CASCADE")
    # schema는 비어 있으면 drop, 데이터 있으면 보존 (CASCADE 금지).
    for schema in reversed(_SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} RESTRICT")

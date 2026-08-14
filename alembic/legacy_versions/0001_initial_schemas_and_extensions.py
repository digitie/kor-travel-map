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


def _drop_extension_if_current_user_can(ext_name: str, *, unless_schema: str | None = None) -> None:
    """Drop an existing extension only when the migration user owns it.

    Shared development Postgres can pre-provision PostGIS under an infra owner.
    In that case the application role must not try to relocate/drop the
    extension; it should reuse the already-provisioned extension instead.
    """

    schema_filter = ""
    if unless_schema is not None:
        schema_filter = f"AND n.nspname <> '{unless_schema}'"

    op.execute(
        f"""
        DO $$
        DECLARE
            extension_owner_is_current boolean;
        BEGIN
            SELECT e.extowner = current_user::regrole
              INTO extension_owner_is_current
              FROM pg_extension e
              JOIN pg_namespace n ON n.oid = e.extnamespace
             WHERE e.extname = '{ext_name}'
             {schema_filter};

            IF extension_owner_is_current THEN
                EXECUTE 'DROP EXTENSION IF EXISTS {ext_name} CASCADE';
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    # 4 schema 생성 (idempotent).
    for schema in _SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")

    # 3 extension을 x_extension에 격리 (ADR-008). testcontainers postgis image처럼
    # migration user가 public extension을 소유하는 경우에만 DROP CASCADE 후 재생성한다.
    # kor-travel-docker-manager 공유 Postgres처럼 infra owner가 미리 설치한 extension은 재사용한다.
    _drop_extension_if_current_user_can("postgis_topology")
    _drop_extension_if_current_user_can("postgis", unless_schema="x_extension")
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

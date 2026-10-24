"""ADR115 additive scope kernel. 기존 writer는 아직 이 경로로 전환하지 않는다."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from sqlalchemy import text

from alembic import op

# ruff: noqa: E501
revision: str = "411_scoped_feature_write_kernel"
down_revision: str | None = "410_provider_field_shadow"
branch_labels: str | None = None
depends_on: str | None = None


def _sidecar(name: str) -> str:
    return Path(__file__).with_name(f"_411_{name}.sql").read_text(encoding="utf-8")


_SCHEMA_STATEMENTS: Final[tuple[str, ...]] = (
    """-- Scope는 coverage 예약일 뿐 Feature identity나 전역 소실 증거가 아니다.
CREATE TABLE ops.feature_write_dataset_scopes (
    provider_dataset_id bigint PRIMARY KEY REFERENCES provider_sync.provider_datasets(provider_dataset_id) ON DELETE RESTRICT,
    epoch bigint NOT NULL DEFAULT 0 CHECK (epoch >= 0),
    owner uuid,
    lease_until timestamptz,
    CHECK ((owner IS NULL) = (lease_until IS NULL))
)""",
    """CREATE TABLE ops.feature_write_region_scopes (
    provider_dataset_id bigint NOT NULL REFERENCES ops.feature_write_dataset_scopes(provider_dataset_id) ON DELETE RESTRICT,
    scope_version integer NOT NULL CHECK (scope_version > 0),
    region_key text COLLATE "C" NOT NULL CHECK (region_key ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    epoch bigint NOT NULL DEFAULT 0 CHECK (epoch >= 0),
    owner uuid,
    lease_until timestamptz,
    PRIMARY KEY (provider_dataset_id, scope_version, region_key),
    CHECK ((owner IS NULL) = (lease_until IS NULL))
)""",
    """CREATE INDEX idx_feature_write_region_scopes_lease ON ops.feature_write_region_scopes(lease_until, provider_dataset_id) WHERE owner IS NOT NULL""",
    """CREATE TABLE ops.feature_write_attempts (
    attempt_id uuid PRIMARY KEY,
    provider_dataset_id bigint NOT NULL REFERENCES ops.feature_write_dataset_scopes(provider_dataset_id) ON DELETE RESTRICT,
    idempotency_key text COLLATE "C" NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9_.:-]{1,128}$'),
    owner uuid NOT NULL,
    dataset_epoch bigint NOT NULL CHECK (dataset_epoch >= 0),
    regions jsonb NOT NULL CHECK (jsonb_typeof(regions) = 'array' AND jsonb_array_length(regions) <= 256),
    exclusive_protocol boolean NOT NULL,
    input_digest text COLLATE "C" NOT NULL CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    expected_members integer NOT NULL CHECK (expected_members BETWEEN 0 AND 8192),
    manifest_digest text COLLATE "C",
    status text COLLATE "C" NOT NULL DEFAULT 'preparing' CHECK (status IN ('preparing','ready','applying','completed','cancelled')),
    apply_txid bigint,
    result_digest text COLLATE "C",
    lease_until timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (provider_dataset_id, idempotency_key),
    CHECK (manifest_digest IS NULL OR manifest_digest ~ '^[0-9a-f]{64}$'),
    CHECK (result_digest IS NULL OR result_digest ~ '^[0-9a-f]{64}$')
)""",
    """CREATE INDEX idx_feature_write_attempts_terminal ON ops.feature_write_attempts(updated_at, attempt_id) WHERE status IN ('completed','cancelled')""",
    """CREATE INDEX idx_feature_write_attempts_expired ON ops.feature_write_attempts(lease_until, provider_dataset_id) WHERE status IN ('preparing','ready','applying')""",
    """CREATE TABLE ops.feature_write_manifests (
    attempt_id uuid NOT NULL REFERENCES ops.feature_write_attempts(attempt_id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal BETWEEN 0 AND 8191),
    dependency_kind text COLLATE "C" NOT NULL CHECK (dependency_kind IN ('feature','source_head')),
    dependency_key text COLLATE "C" NOT NULL CHECK (octet_length(dependency_key) BETWEEN 1 AND 128),
    expected_value text COLLATE "C" NOT NULL CHECK (octet_length(expected_value) BETWEEN 1 AND 128),
    member_digest text COLLATE "C" NOT NULL CHECK (member_digest ~ '^[0-9a-f]{64}$'),
    PRIMARY KEY (attempt_id, ordinal),
    UNIQUE (attempt_id, dependency_kind, dependency_key)
)""",
    """-- 직접 DML은 runtime에 열지 않는다. 후속 reconcile inventory에도 동일 권한을 선언해야 한다.
REVOKE ALL ON ops.feature_write_dataset_scopes, ops.feature_write_region_scopes, ops.feature_write_attempts, ops.feature_write_manifests FROM PUBLIC, ktm_feature_runtime""",
    """GRANT SELECT,INSERT,UPDATE,DELETE ON ops.feature_write_dataset_scopes, ops.feature_write_region_scopes, ops.feature_write_attempts, ops.feature_write_manifests TO ktm_feature_state_procedure_owner""",
)

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    *_SCHEMA_STATEMENTS,
    _sidecar("scoped_feature_write_protocol"),
    "ALTER FUNCTION ops.lock_scoped_feature_write_protocol(boolean) OWNER TO ktm_feature_state_procedure_owner",
    "REVOKE ALL ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean) FROM PUBLIC",
    "SET ROLE ktm_feature_state_procedure_owner",
    "GRANT EXECUTE ON FUNCTION ops.lock_scoped_feature_write_protocol(boolean) TO ktm_feature_runtime",
    "RESET ROLE",
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(text(statement))


def downgrade() -> None:
    op.execute(text("SET ROLE ktm_feature_schema_owner"))
    op.execute(text("DROP FUNCTION ops.lock_scoped_feature_write_protocol(boolean)"))
    for table in (
        "feature_write_manifests",
        "feature_write_attempts",
        "feature_write_region_scopes",
        "feature_write_dataset_scopes",
    ):
        op.execute(text(f"DROP TABLE ops.{table}"))
    op.execute(text("RESET ROLE"))

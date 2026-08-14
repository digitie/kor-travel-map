"""admin login audit events and public API keys.

Revision ID: 0028_admin_auth_keys
Revises: 0027_khoa_recategorize_cleanup
Create Date: 2026-06-23
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0028_admin_auth_keys"
down_revision: str | Sequence[str] | None = "0027_khoa_recategorize_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS ops.public_api_keys (
  public_api_key_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  key_hash          TEXT NOT NULL UNIQUE CHECK (key_hash ~ '^[0-9a-f]{64}$'),
  key_hint          TEXT NOT NULL CHECK (char_length(key_hint) BETWEEN 6 AND 12),
  label             TEXT CHECK (label IS NULL OR char_length(label) BETWEEN 1 AND 80),
  state             TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','revoked')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by        TEXT,
  revoked_at        TIMESTAMPTZ,
  revoked_by        TEXT,
  CHECK (
    (state = 'active' AND revoked_at IS NULL AND revoked_by IS NULL)
    OR (state = 'revoked' AND revoked_at IS NOT NULL)
  )
)
"""
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS idx_public_api_keys_active_hash
  ON ops.public_api_keys (key_hash)
  WHERE state = 'active'
"""
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS idx_public_api_keys_created_at
  ON ops.public_api_keys (created_at DESC, public_api_key_id DESC)
"""
    )
    op.execute(
        """
CREATE TABLE IF NOT EXISTS ops.admin_auth_events (
  auth_event_id      UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  event_type         TEXT NOT NULL CHECK (event_type IN ('login','logout')),
  outcome            TEXT NOT NULL CHECK (outcome IN ('succeeded','failed','denied')),
  attempted_username TEXT CHECK (
    attempted_username IS NULL OR char_length(attempted_username) <= 80
  ),
  actor              TEXT CHECK (actor IS NULL OR char_length(actor) <= 120),
  reason             TEXT CHECK (reason IS NULL OR char_length(reason) <= 120),
  next_path          TEXT CHECK (next_path IS NULL OR char_length(next_path) <= 2048),
  client_ip          TEXT CHECK (client_ip IS NULL OR char_length(client_ip) <= 128),
  user_agent         TEXT CHECK (user_agent IS NULL OR char_length(user_agent) <= 512),
  request_id         TEXT CHECK (request_id IS NULL OR char_length(request_id) <= 128),
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS idx_admin_auth_events_created_at
  ON ops.admin_auth_events (created_at DESC, auth_event_id DESC)
"""
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS idx_admin_auth_events_outcome_time
  ON ops.admin_auth_events (outcome, created_at DESC, auth_event_id DESC)
"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops.admin_auth_events")
    op.execute("DROP TABLE IF EXISTS ops.public_api_keys")

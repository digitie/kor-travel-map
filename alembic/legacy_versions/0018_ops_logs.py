"""ops 로그 surface 테이블 (T-212c, ADR-008/019/045).

운영 화면이 보여줄 두 로그 stream을 ``ops`` schema에 적재한다.

- ``ops.system_log`` — 적재/지오코딩/오프라인 업로드/admin 동작의 구조화된
  운영 로그(level + source + event + message + JSONB detail).
- ``ops.api_call_log`` — opt-in API 호출 로그(메서드/경로/상태/지연). admin
  app의 ``api_call_log_enabled`` 미들웨어가 best-effort로 기록한다.

UUID PK 기본값은 pgcrypto를 격리한 ``x_extension.gen_random_uuid()``를 schema
한정으로 호출한다(ADR-008/0014). 시간은 모두 ``TIMESTAMPTZ``(ADR-019). 목록은
``(created_at DESC, <pk> DESC)`` keyset cursor로 조회하므로 그 정렬축 인덱스 +
필터(level/source/status_code)별 보조 인덱스를 둔다.

Revision ID: 0018_ops_logs
Revises: 0017_feature_weather_values
Create Date: 2026-06-07
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018_ops_logs"
down_revision: str | Sequence[str] | None = "0017_feature_weather_values"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ops.system_log (
            system_log_key  UUID PRIMARY KEY
                DEFAULT x_extension.gen_random_uuid(),
            level           TEXT NOT NULL,
            source          TEXT NOT NULL,
            event           TEXT NOT NULL,
            message         TEXT NOT NULL,
            detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
            request_id      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_system_log_level
                CHECK (level IN ('debug','info','warning','error','critical'))
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_system_log_keyset
        ON ops.system_log (created_at DESC, system_log_key DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_system_log_level
        ON ops.system_log (level, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_system_log_source
        ON ops.system_log (source, created_at DESC)
        """
    )

    op.execute(
        """
        CREATE TABLE ops.api_call_log (
            api_call_log_key  UUID PRIMARY KEY
                DEFAULT x_extension.gen_random_uuid(),
            method            TEXT NOT NULL,
            path              TEXT NOT NULL,
            status_code       INTEGER NOT NULL,
            duration_ms       INTEGER NOT NULL,
            request_id        TEXT,
            error_code        TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_api_call_log_keyset
        ON ops.api_call_log (created_at DESC, api_call_log_key DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX idx_api_call_log_status
        ON ops.api_call_log (status_code, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops.api_call_log")
    op.execute("DROP TABLE IF EXISTS ops.system_log")

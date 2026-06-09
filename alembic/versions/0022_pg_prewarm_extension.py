"""pg_prewarm 확장(부팅 후 warm-up, T-102).

Revision ID: 0022_pg_prewarm_extension
Revises: 0021_user_feature_versions
Create Date: 2026-06-09

`pg_prewarm` contrib 확장을 `x_extension` 스키마에 격리 생성한다(ADR-008). 이 확장은
두 가지를 제공한다:

- `x_extension.pg_prewarm(regclass)` — 명시적 buffer warm-up 함수(부팅/배포 직후 hot
  relation을 shared_buffers/OS cache로 끌어올림). `krtour.map.infra.prewarm` 헬퍼가 호출.
- autoprewarm background worker — `shared_preload_libraries='pg_prewarm'` +
  `pg_prewarm.autoprewarm=on`(서버 config, docker-compose)일 때만 동작. 주기적으로 buffer
  목록을 dump하고 재기동 시 자동 reload("부팅 후 warm-up").

확장 생성 자체는 저비용이라 항상 둔다. autoprewarm 활성화는 도입 조건(명시적 P99 SLO +
shared_buffers가 hot 데이터 fit)이 충족될 때 config로 켠다(T-102, `docs/performance.md §9.5`).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0022_pg_prewarm_extension"
down_revision: str | Sequence[str] | None = "0021_user_feature_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_prewarm WITH SCHEMA x_extension")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_prewarm")

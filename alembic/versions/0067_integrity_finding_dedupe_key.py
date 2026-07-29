"""integrity finding dedupe key (T-VN-H30A).

주소/좌표 검증 결과를 ``ops.data_integrity_violations``에 durable하게 남기려면 **재실행 시
같은 이슈가 무한히 쌓이지 않아야** 한다. Dagster materialize는 같은 provider export를 매번
전량 재생하므로, 중복 억제 없이는 run 수 × 이슈 수만큼 행이 늘어난다.

``payload->>'dedupe_key'``에 부분 unique index를 걸어 **열린 이슈에 한해** 1건으로 접는다.
resolved/ignored로 닫힌 과거 이슈는 제약 밖이라 이력이 보존되고, 같은 문제가 재발하면 새 행이
생긴다(닫은 뒤 재발했다는 사실 자체가 신호다).

dedupe_key가 없는 기존/타 경로 행은 ``payload ? 'dedupe_key'`` 조건으로 제약에서 빠진다.

Revision ID: 0067_integrity_finding_dedupe_key
Revises: 0066_curation_component_identity
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0067_integrity_finding_dedupe_key"
down_revision: str | Sequence[str] | None = "0066_curation_component_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_violations_open_dedupe_key"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
        ON ops.data_integrity_violations ((payload ->> 'dedupe_key'))
        WHERE status IN ('open', 'acknowledged')
          AND payload ? 'dedupe_key'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS ops.{_INDEX}")

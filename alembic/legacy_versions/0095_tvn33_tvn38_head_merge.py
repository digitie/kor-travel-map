"""T-VN-33/T-VN-38 migration head를 단일 순서로 수렴한다.

Revision ID: 0095_tvn33_tvn38_head_merge
Revises: 0092_tvn33_offline_cleanup, 0094_drop_weather_metric_series

T-VN-38A가 0091 뒤에서 시작한 동안 T-VN-33은 같은 0091에서 후속 정리 migration을
추가했다. stacked PR을 재배치하면 둘 다 적용돼야 하므로, 이 빈 merge revision이
Alembic의 head를 하나로 고정한다. 두 branch는 서로 다른 relation을 변경하므로
순서 의존 DDL은 없다.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0095_tvn33_tvn38_head_merge"
down_revision: str | Sequence[str] | None = (
    "0092_tvn33_offline_cleanup",
    "0094_drop_weather_metric_series",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """두 선행 head가 모두 적용됐음을 Alembic history에 기록한다."""


def downgrade() -> None:
    raise RuntimeError("T-VN-33/T-VN-38 merge는 forward-only history다")

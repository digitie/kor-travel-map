"""T-VN-38C — retired weather series catalog를 제거한다.

Revision ID: 0094_drop_weather_metric_series
Revises: 0093_price_current_summary

``weather_metric_series``는 0069의 mutable latest-row batch reader를 위한 보조
catalog였다. T-VN-38의 immutable fact/window-ranked reader는 canonical dataset과
source revision을 직접 순위화하므로 catalog와 writer trigger는 정본이 아니다.
서비스 전 cutover에서는 재적재가 가능하므로 forward-only로 완전히 제거한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0094_drop_weather_metric_series"
down_revision: str | Sequence[str] | None = "0093_price_current_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS feature.register_weather_metric_series()")
    op.execute("DROP TABLE IF EXISTS feature.weather_metric_series")


def downgrade() -> None:
    raise RuntimeError("0094 is destructive and forward-only; rebuild with provider ETL")

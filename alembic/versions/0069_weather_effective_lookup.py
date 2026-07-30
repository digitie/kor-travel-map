"""weather batch effective-time 복합 인덱스.

Revision ID: 0069_weather_effective_lookup
Revises: 0068_integrity_last_seen
Create Date: 2026-07-30

T-VN-16A의 batch는 선택된 weather source마다
``forecast_style × metric_key``의 ``target_at`` 직전 current와 24시간 timeline을
읽는다. 기존 인덱스는 ``valid_at``만 다루므로 ``valid_at``·``observed_at``·
``valid_from``·``issued_at``을 합친 effective-time 정렬에서 대량의 heap row를
읽었다. 아래 인덱스는 source/metric exact prefix와 effective-time 범위·역순 조회를
한 경로로 고정한다.

운영 weather table은 대용량이므로 생성·삭제는 autocommit
``CONCURRENTLY``로 수행한다. 실패 뒤 남은 INVALID index를 forward 재실행할 수
있도록 생성 전에 같은 이름을 concurrent drop한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0069_weather_effective_lookup"
down_revision: str | Sequence[str] | None = "0068_integrity_last_seen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "idx_weather_values_feature_effective"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS feature.{_INDEX}")
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY {_INDEX}
            ON feature.feature_weather_values (
                feature_id,
                forecast_style,
                metric_key,
                (
                    COALESCE(
                        valid_at,
                        observed_at,
                        valid_from,
                        issued_at
                    )
                ) DESC,
                issued_at DESC NULLS LAST,
                collected_at DESC,
                weather_value_key
            )
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS feature.{_INDEX}")

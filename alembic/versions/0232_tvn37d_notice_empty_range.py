"""T-VN-37D — notice 효력 범위의 empty 상태를 typed range로 표현한다.

`feature.feature_notices.valid_end_time`은 예정 종료일이 아니라 feed에서
효력이 끝났다고 관측한 시각이다. 따라서 미래 발효 공지가 발효 전에 철회되면
`valid_end_time < valid_start_time`이 될 수 있고, 이 상태는 오류가 아니다.

`valid_during`은 두 typed timestamp에서 자동 생성되는 저장 컬럼이다. 정상
범위는 `[start, end)`로, 발효 전 철회는 PostgreSQL의 `empty` range로 나타낸다.
두 시각이 모두 없으면 기존의 "기간 정보 없음" 의미를 보존하기 위해 NULL이다.
공개 notice read는 미래 발효 경고를 숨기지 않도록 기존 `valid_end_time` 술어를
유지한다. 이 migration은 표현을 추가할 뿐 read contract를 바꾸지 않는다.

stored generated column 추가는 기존 행을 다시 계산하고 테이블 잠금을 얻으므로
writer fence/maintenance window에서 실행한다. 잠금 대기는 30초에서 fail-closed해
운영 요청이 무기한 대기하지 않게 한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0232_tvn37d_notice_empty_range"
down_revision: str | Sequence[str] | None = "0231_tvn41s_snapshot_material"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_VALID_DURING_EXPRESSION = """
CASE
    WHEN valid_start_time IS NULL AND valid_end_time IS NULL
        THEN NULL::tstzrange
    WHEN valid_start_time IS NOT NULL
         AND valid_end_time IS NOT NULL
         AND valid_end_time < valid_start_time
        THEN 'empty'::tstzrange
    ELSE tstzrange(valid_start_time, valid_end_time, '[)'::text)
END
"""


def upgrade() -> None:
    op.execute("SET ROLE ktm_feature_schema_owner")
    op.execute("SET LOCAL lock_timeout = '30s'")
    op.execute(
        f"""
        ALTER TABLE feature.feature_notices
        ADD COLUMN valid_during tstzrange
        GENERATED ALWAYS AS ({_VALID_DURING_EXPRESSION}) STORED
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "0232_tvn37d_notice_empty_range is forward-only; "
        "notice validity representation is part of the application schema head"
    )

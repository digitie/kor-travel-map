"""T-VN-40B — source rule의 `curated` action을 퇴역시킨다.

왜. ADR-092(설계 문서 §184 항목 2)가 source rule의 `curated` action을 **automatic public
membership이 아니라 candidate creation**으로 재해석했다. 그래서 `curated`와 `candidate`는
같은 뜻이 됐고, 두 값이 공존하면 읽는 사람마다 다르게 해석한다. write 경로는 이미
`candidate|ignore`만 받는다(`curated_repo._TYPED_RULE_ACTIONS`) — DB만 옛 값을 허용한 채
남아 있어, 값이 다시 들어올 문은 닫혀 있는데 이미 들어온 값은 그대로다.

무엇. 남은 `curated` 행을 `candidate`로 정규화하고 CHECK에서 그 값을 지운다.

무엇이 아닌가. "legacy candidate rows backfill"은 이 migration의 일이 아니다. 그 legacy
행은 `feature.curated_features`에 있었고 `0225`(T-VN-40C)가 canonical collection/item으로
옮긴 뒤 물리 삭제했다. 2026-08-20 prod 실측으로 `theme_feature_candidates`는 0행이고
`curated` rule이 만든 candidate도 0이다 — backfill 대상 자체가 없다.

trigger. `feature.curated_source_rules`에는 BEFORE UPDATE trigger
`trg_curated_source_rules_active_dataset_write`가 있어 inactive provider dataset에 걸린 rule의
write를 막는다. 이 migration은 그 fence를 **끄지 않는다**. 막히면 실패하고 어느 rule인지
말한다 — 조용히 건너뛰면 남은 `curated` 행이 아래 CHECK에서 다시 막히고 원인이 감춰진다.

번호. `0226`은 산림청 C05 catalog를 기존 DB에 보충하는 이 PR의 선행 migration이다.
따라서 이 migration은 `0226` 뒤에 연결해, C05 catalog와 source-rule 정규화가 하나의
application graph를 이루도록 한다. revision id의 숫자 순서와 실제 체인 순서는 다를 수
있으며, 이 경우에도 `down_revision`이 실행 순서를 정한다.

forward-only. downgrade는 두지 않는다(ADR-021). 되돌리려면 `curated`가 무엇을 뜻했는지
행마다 알아야 하는데 그 구분은 이 migration 뒤에 존재하지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "0229_tvn40b_source_rule_action"
down_revision: str | Sequence[str] | None = "0226_tvn_c05_krforest_datasets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT: Final[str] = "ck_curated_source_rules_action"
_TABLE: Final[str] = "feature.curated_source_rules"

_BLOCKED_RULES_SQL: Final[str] = """
SELECT rule.rule_id
  FROM feature.curated_source_rules AS rule
  JOIN feature.curated_sources AS source ON source.source_id = rule.source_id
  LEFT JOIN provider_sync.provider_datasets AS dataset
    ON dataset.provider_dataset_id = source.provider_dataset_id
 WHERE rule.default_action = 'curated'
   AND dataset.is_active IS NOT TRUE
 ORDER BY rule.rule_id
"""

_NORMALIZE_SQL: Final[str] = """
UPDATE feature.curated_source_rules
   SET default_action = 'candidate',
       updated_at = now()
 WHERE default_action = 'curated'
"""

_REMAINING_SQL: Final[str] = """
SELECT count(*) FROM feature.curated_source_rules WHERE default_action = 'curated'
"""


def upgrade() -> None:
    connection = op.get_bind()

    # 먼저 막힐 행을 이름으로 말한다. UPDATE가 첫 행에서 터지면 나머지가 몇 개인지
    # 알 수 없어 운영자가 같은 실패를 반복해서 만난다.
    blocked = [str(row[0]) for row in connection.execute(text(_BLOCKED_RULES_SQL))]
    if blocked:
        raise RuntimeError(
            "inactive provider dataset에 걸린 curated rule이 있어 정규화할 수 없습니다. "
            "dataset을 다시 활성화하거나 rule을 archive한 뒤 재실행하세요: "
            f"{', '.join(blocked)}"
        )

    normalized = connection.execute(text(_NORMALIZE_SQL)).rowcount
    remaining = connection.execute(text(_REMAINING_SQL)).scalar_one()
    if remaining:
        raise RuntimeError(
            f"curated action 행이 {remaining}개 남았습니다 — CHECK를 좁힐 수 없습니다"
        )

    op.execute(text(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {_CONSTRAINT}"))
    op.execute(
        text(
            f"ALTER TABLE {_TABLE} ADD CONSTRAINT {_CONSTRAINT} "
            "CHECK (default_action IN ('candidate','ignore'))"
        )
    )

    print(f"0229 tvn40b source rule action normalized: curated -> candidate {normalized}행")


def downgrade() -> None:
    raise RuntimeError(
        "0229_tvn40b_source_rule_action is forward-only; "
        "`curated`가 뜻하던 구분은 이 migration 뒤에 존재하지 않으므로 "
        "되돌리면 값을 발명하게 된다(ADR-021)."
    )

"""통합 테스트가 쓰는 **실재하는** canonical membership을 시드에서 읽어 온다.

T-VN-33 전에는 테스트가 ``ProviderDatasetOperationKey("provider", "done")``처럼
자연키 문자열을 즉석에서 지어냈다. 지금은 identity가 triple이고 실행 레코드가
``provider_dataset_operation_scopes``를 FK로 참조하므로, **카탈로그에 없는 조합은
만들 수 없다**. 그래서 지어내는 대신 시드에서 고른다.

``feature_place_mcst_culture_job``은 13개 dataset에 걸쳐 있어(실측) 한 operation이
여러 member를 갖는 시나리오를 그대로 표현한다 — 예전 테스트의 "pair 두 개" 모양이
여기에 대응한다.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership

#: dataset 여러 개를 한 operation으로 묶는 시드 operation(실측 13 membership).
MULTI_MEMBER_OPERATION = "feature_place_mcst_culture_job"

#: dataset 1개 = membership 1개인 시드 operation(실측: provider_dataset_id=30,
#: sync_scope='dataset_wide'). single-member wrapper 경로가 요구하는 전제
#: (``_single_membership_for_asset``)를 우회 없이 그대로 표현한다.
SINGLE_MEMBER_OPERATION = "feature_place_mois_licenses_job"

_SCOPES_SQL = """
SELECT provider_dataset_id, sync_scope, operation_key
FROM provider_sync.provider_dataset_operation_scopes
WHERE operation_key = :operation_key
  AND operation_kind = 'refresh'
ORDER BY provider_dataset_id, sync_scope
"""


async def memberships_for_operation(
    session: AsyncSession,
    *,
    operation_key: str = MULTI_MEMBER_OPERATION,
    limit: int | None = None,
) -> tuple[ProviderDatasetOperationMembership, ...]:
    """``operation_key``에 결박된 canonical membership을 순서 결정적으로 돌려준다."""

    rows = (
        await session.execute(text(_SCOPES_SQL), {"operation_key": operation_key})
    ).all()
    memberships = tuple(
        ProviderDatasetOperationMembership(
            provider_dataset_id=int(row.provider_dataset_id),
            sync_scope=str(row.sync_scope),
            operation_key=str(row.operation_key),
        )
        for row in rows
    )
    if not memberships:
        raise AssertionError(
            f"시드에 operation_key={operation_key!r}의 refresh scope가 없다"
        )
    return memberships if limit is None else memberships[:limit]


#: Dagster run tag key. 프로덕션 상수를 그대로 읽는다 — 테스트가 자기 사본을 들면
#: 태그 이름이 갈려도 조용히 통과한다.
def launch_tags(
    *, operation_key: str, trigger_kind: str | None = "schedule"
) -> dict[str, str]:
    """예전 ``feature_operation_launch_tags``의 대체.

    T-VN-33 전에는 registry가 job 이름에서 identity와 tag를 만들었다. 지금은 DB의
    ``operation_key``가 정본이고 Dagster tag는 그 key만 나른다 — 그래서 이 헬퍼는
    registry를 부르지 않고 key를 그대로 싣는다.
    """

    from kortravelmap.dagster.feature_operation_sensors import (
        _OPERATION_KEY_TAG,
        _TRIGGER_KIND_TAG,
    )

    tags = {_OPERATION_KEY_TAG: operation_key}
    if trigger_kind is not None:
        tags[_TRIGGER_KIND_TAG] = trigger_kind
    # ``trigger_kind=None``은 **trigger tag가 아예 없는 run**을 만든다. 프로덕션에서
    # 실제로 있는 모양이고(`_trigger_kind()`가 operation tag만 보고 "schedule"로
    # 추론한다), 그 fallback을 아무 테스트도 잡지 않고 있었다 — mutant로 실증됐다
    # (fallback을 `return None`으로 바꿔도 34 passed).
    return tags

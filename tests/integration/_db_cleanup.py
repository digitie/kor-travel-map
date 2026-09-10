"""Append-only production trigger를 보존하는 통합 테스트 전용 정리 도우미."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_IMMUTABLE_HISTORY_TABLES = (
    "curation_import_batches",
    "curation_import_rows",
    "curation_link_decisions",
)

#: 307이 `ENABLE ALWAYS`로 단 TRUNCATE 가드들. `session_replication_role = replica`는
#: **이것들을 끄지 못한다** — 그게 ALWAYS를 고른 이유다(실수로 인한 TRUNCATE를 막는
#: 유일한 변형). 그래서 여기서 이름으로 끈다.
#:
#: 이 명시가 비용이 아니라 개선인 이유: 종전에는 `replica` 한 줄이 **무엇을** 우회하는지
#: 말하지 않은 채 전부 껐다. 이제는 우회 대상이 코드에 적힌다.
_ALWAYS_TRUNCATE_GUARDS = (
    ("feature.features", "trg_features_manual_feature_truncate_fence"),
    ("ops.feature_requests", "trg_feature_requests_no_truncate"),
    ("ops.feature_requests", "trg_feature_requests_no_delete"),
    ("ops.feature_update_requests", "trg_feature_update_requests_no_truncate"),
    (
        "ops.feature_update_request_datasets",
        "trg_feature_update_request_datasets_no_truncate",
    ),
)
#: provider identity claim은 `feature.features`로 가는 FK가 **없다**(T-VN-39,
#: dataset FK 하나뿐). 그래서 `TRUNCATE feature.features ... CASCADE`가 claim을
#: 데려가지 않고, commit하는 테스트가 지나간 자리에 부모 없는 claim이 남는다.
#:
#: 그 상태는 조용하지 않다 — `count_features_missing_identity`의 둘째 축이
#: "주소 없는 claim"으로 세므로, **다른 파일의** identity 불변식 테스트가 빨개진다.
#: 실측(2026-09-10): 전량 통합 런에서 `test_feature_identity_boundary` 4건이
#: `(0, 21, 0, 0)`으로 죽었고, 그 21건은 전부 dagster asset 테스트가 commit한
#: claim이었다. 묶음으로 쪼개 돌면 보이지 않는 부류다.
#:
#: 호출부마다 목록에 이름을 더하게 하지 않는다 — 잊는 것이 기본값이 되기 때문이다.
#: 대신 여기서 **부모 없는 claim만** 거둔다. feature가 살아 있는 claim은 건드리지
#: 않으므로 어떤 테스트의 의미 있는 상태도 잃지 않고, "feature는 있는데 주소가
#: 없다"는 진짜 결함은 불변식이 계속 잡는다.
_ORPHAN_CLAIM_SWEEP_SQL = """
DELETE FROM provider_sync.provider_feature_identities AS claim
WHERE NOT EXISTS (
    SELECT 1 FROM feature.features AS f WHERE f.feature_id = claim.feature_id
)
"""

_CURATION_RESET_SQL = """
TRUNCATE
    feature.curation_link_decisions,
    feature.curation_import_rows,
    feature.curation_import_batches,
    feature.curation_items,
    feature.curation_collections
RESTART IDENTITY CASCADE
"""


async def truncate_committed_test_rows(
    session: AsyncSession,
    statement: str,
) -> None:
    """테스트 savepoint 안에서 curation 전체와 committed fixture를 원자적으로 비운다.

    운영 append-only trigger는 그대로 유지한다. cleanup 도중 실패하면 savepoint
    rollback이 ``DISABLE TRIGGER``까지 되돌리므로 trigger가 비활성화된 채 남지 않는다.

    호출부가 준 ``statement`` 뒤에 **부모 없는 provider identity claim**을 함께
    거둔다(:data:`_ORPHAN_CLAIM_SWEEP_SQL`). 그 표는 FK가 없어 CASCADE를 타지
    않으므로, 그러지 않으면 commit한 테스트가 지나간 자리마다 고아 claim이 쌓이고
    **다른 파일의** identity 불변식이 대신 죽는다.
    """

    savepoint = await session.begin_nested()
    try:
        for table_name in _IMMUTABLE_HISTORY_TABLES:
            await session.execute(
                text(
                    f"ALTER TABLE feature.{table_name} "
                    f"DISABLE TRIGGER trg_{table_name}_append_only"
                )
            )
            await session.execute(
                text(
                    f"ALTER TABLE feature.{table_name} "
                    f"DISABLE TRIGGER trg_{table_name}_no_truncate"
                )
            )

        for relation, trigger in _ALWAYS_TRUNCATE_GUARDS:
            await session.execute(
                text(f"ALTER TABLE {relation} DISABLE TRIGGER {trigger}")
            )

        # 기존 committed fixture cleanup에는 curation 외 append-only ledger도
        # cascade될 수 있다. 복제 role은 이 savepoint 안에서만 열고 성공 경로에서도
        # 즉시 origin으로 복원한다.
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(text(_CURATION_RESET_SQL))
        await session.execute(text(statement))
        # 호출부의 TRUNCATE가 지나간 **뒤**에 쓸어야 한다 — 그 전에는 아직 부모가
        # 살아 있어서 고아가 아니다.
        await session.execute(text(_ORPHAN_CLAIM_SWEEP_SQL))
        await session.execute(text("SET LOCAL session_replication_role = origin"))

        # **`ENABLE ALWAYS`로 되돌린다.** 그냥 `ENABLE TRIGGER`면 origin으로
        # 내려앉아, 남은 세션 내내 `replica` 한 줄로 우회 가능한 상태가 된다 —
        # 정리 도우미가 운영 fence를 조용히 약화시키는 셈이다.
        for relation, trigger in reversed(_ALWAYS_TRUNCATE_GUARDS):
            await session.execute(
                text(f"ALTER TABLE {relation} ENABLE ALWAYS TRIGGER {trigger}")
            )

        for table_name in reversed(_IMMUTABLE_HISTORY_TABLES):
            await session.execute(
                text(
                    f"ALTER TABLE feature.{table_name} "
                    f"ENABLE TRIGGER trg_{table_name}_no_truncate"
                )
            )
            await session.execute(
                text(
                    f"ALTER TABLE feature.{table_name} "
                    f"ENABLE TRIGGER trg_{table_name}_append_only"
                )
            )
    except BaseException:
        await savepoint.rollback()
        raise
    else:
        await savepoint.commit()

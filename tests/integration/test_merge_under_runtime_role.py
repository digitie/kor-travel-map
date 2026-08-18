"""Feature merge가 **실제 API runtime role**로 돈다.

PR #994(T-VN-40A fence)의 적대 리뷰가 잡은 것: ACL 층이 `curated_features`에서 runtime의
write 권한을 뺐는데, `merge_repo.apply_feature_merge`가 legacy 표를 `FOR UPDATE`로 잠그고
3번 UPDATE한다. PostgreSQL은 `FOR UPDATE`에도 UPDATE 권한을 요구하므로 merge가 42501로
죽는다 — dedup review 병합(`PATCH /v1/admin/dedup-reviews/{id}` decision=merged)과
`ktmctl dedup-merge` 둘 다.

**CI가 못 잡은 이유**: 모든 merge 통합 테스트가 `migrated_session`(컨테이너 superuser)으로
돈다. superuser는 ACL을 안 본다. 그래서 이 파일은 `as_api_runtime`으로 **권한이 있는 role**이
돼서 merge를 실행한다 — ACL 회귀를 잡는 유일한 자리다.

이 테스트가 red인 채로 fence PR을 머지했다면 **CI 초록·prod 빨강**이었다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.merge_repo import apply_feature_merge
from tests.integration import test_merge_repo as _merge_repo_tests
from tests.integration.conftest import as_api_runtime

pytestmark = pytest.mark.integration

# test_merge_repo의 `seeded` fixture(master/loser pair + dedup review + teardown TRUNCATE)를
# 이 모듈에 등록한다. 모듈 속성으로 재바인딩하는 것이 pytest의 cross-module fixture 재사용
# 형식이다 — `from ... import seeded`는 아래 테스트 인자와 이름이 겹쳐 F811이다.
seeded = _merge_repo_tests.seeded


async def test_apply_feature_merge_succeeds_as_api_runtime(
    seeded: str,
    migrated_engine: AsyncEngine,
) -> None:
    """runtime role로 merge가 **끝까지** 돈다.

    superuser로 도는 다른 merge 테스트는 ACL을 안 본다. 여기서 red면 prod의 dedup 병합이
    500이다 — `dedup_review.py` 라우터는 `MergeError`만 잡고 `InsufficientPrivilegeError`는
    catch-all로 샌다.
    """
    async with AsyncSession(migrated_engine) as session, session.begin():
        async with as_api_runtime(session):
            await apply_feature_merge(
                session,
                master_id="f_master",
                loser_id="f_loser",
                review_id=seeded,
                merged_by="runtime-role-test",
                reason="ACL 회귀 가드",
            )
        # 병합 결과가 실제로 반영됐는지 — 예외만 안 나고 아무것도 안 한 것이면 안 된다.
        row = (
            await session.execute(
                text(
                    "SELECT lifecycle_state FROM feature.features WHERE feature_id = 'f_loser'"
                )
            )
        ).one_or_none()
        assert row is not None
        assert row[0] != "active", "loser가 여전히 active — merge가 실행되지 않았다"


@pytest.mark.parametrize(
    "call",
    [
        "CALL feature.merge_lock_legacy_curated_features('f_master', 'f_loser')",
        "CALL feature.merge_lock_curation_collections('f_master', 'f_loser')",
        "CALL feature.merge_move_legacy_curated_features('f_master', 'f_loser')",
    ],
)
async def test_dagster_runtime_cannot_call_merge_procedures(
    migrated_engine: AsyncEngine, call: str
) -> None:
    """provider ETL identity(dagster runtime)는 merge procedure를 부를 수 없다.

    2차 적대 리뷰 P1: 처음엔 EXECUTE를 공유 그룹 `ktm_feature_runtime`에 줘서 dagster가
    legacy row를 임의로 옮길 수 있었다. 0214 형태로 고쳤다 — EXECUTE는 admin executor에만,
    본문에 `session_user` 게이트. 둘 중 하나만 남아도 여기서 42501이어야 한다.
    """
    from sqlalchemy.exc import DBAPIError

    from tests.integration.conftest import as_dagster_runtime

    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        # pytest.raises가 CM 바깥이어야 한다 — 안쪽이면 실패한 CALL로 aborted된 트랜잭션에서
        # CM 종료가 `SET LOCAL SESSION AUTHORIZATION DEFAULT`를 내려 InFailedSQLTransaction이다.
        with pytest.raises(DBAPIError) as info:
            async with as_dagster_runtime(session):
                await session.execute(text(call))
        message = str(info.value.orig)
        assert "permission denied" in message.lower() or "admin executor" in message, (
            message[:200]
        )
        await session.rollback()

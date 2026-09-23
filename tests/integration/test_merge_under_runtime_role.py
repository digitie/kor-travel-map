"""Feature merge가 **실제 API runtime role**로 돈다.

PR #994(T-VN-40A fence)의 적대 리뷰가 잡은 것: ACL 층이 legacy overlay에서 runtime의
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
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra.merge_repo import apply_feature_merge
from tests.integration import test_merge_repo as _merge_repo_tests
from tests.integration.conftest import as_api_runtime

pytestmark = pytest.mark.integration

# test_merge_repo의 `seeded` fixture(master/loser pair + dedup review + teardown TRUNCATE)를
# 이 모듈에 등록한다. 모듈 속성으로 재바인딩하는 것이 pytest의 cross-module fixture 재사용
# 형식이다 — `from ... import seeded`는 아래 테스트 인자와 이름이 겹쳐 F811이다.
seeded = _merge_repo_tests.seeded

#: 시드가 쓰는 정본 키. T-VN-39 뒤 feature 식별자는 uuid다 — 이 파일이 문자열
#: 리터럴을 따로 들면 시드와 조용히 어긋난다.
_F_MASTER = _merge_repo_tests._F_MASTER
_F_LOSER = _merge_repo_tests._F_LOSER
_MERGE_IDS = {"master": _F_MASTER, "loser": _F_LOSER}


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
                master_id=_F_MASTER,
                loser_id=_F_LOSER,
                review_id=seeded,
                merged_by="runtime-role-test",
                reason="ACL 회귀 가드",
            )
        # 병합 결과가 실제로 반영됐는지 — 예외만 안 나고 아무것도 안 한 것이면 안 된다.
        row = (
            await session.execute(
                text(
                    "SELECT lifecycle_state FROM feature.features "
                    "WHERE feature_id = CAST(:loser AS uuid)"
                ),
                {"loser": _F_LOSER},
            )
        ).one_or_none()
        assert row is not None
        assert row[0] != "active", "loser가 여전히 active — merge가 실행되지 않았다"


@pytest.mark.parametrize(
    "call",
    [
        "CALL feature.merge_lock_curation_collections("
        "CAST(:master AS uuid), CAST(:loser AS uuid))",
    ],
)
async def test_merge_procedures_stay_narrow_to_the_admin_executor(
    migrated_engine: AsyncEngine, call: str
) -> None:
    """merge procedure의 EXECUTE는 admin executor에만 가야 한다.

    2차 적대 리뷰 P1: 처음엔 EXECUTE를 공유 그룹 `ktm_feature_runtime`에 줘서 적재
    identity가 legacy row를 임의로 옮길 수 있었다. 0214 형태로 고쳤다 — EXECUTE는 admin
    executor에만, 본문에 `session_user` 게이트.

    ADR-100 이전에는 그 두 층을 "Dagster login으로 부르면 42501"로 함께 쟀다. LOGIN이
    `ktm_feature_service` 하나로 합쳐지면서 `as_dagster_runtime`과 `as_api_runtime`이
    같은 role을 열게 됐고, 그 하나가 admin executor의 member라 42501은 더 나오지
    않는다 — 그대로 두면 거부를 재는 대신 merge를 한 번 더 실행하고 끝난다.

    남은 경계는 grant 층이고 ADR-100은 그것을 건드리지 않았다. executor role끼리는
    membership이 없으므로(bootstrap의 role graph는 평평하다) 이 술어는 여전히 갈린다.
    """

    procedure = call.split("CALL ", 1)[1].split("(", 1)[0]
    schema, _, name = procedure.partition(".")

    async with AsyncSession(migrated_engine) as session:
        grantees = (
            await session.execute(
                text(
                    "SELECT "
                    "has_function_privilege("
                    "'ktm_curation_provider_executor', oid, 'EXECUTE') AS provider_side, "
                    "has_function_privilege("
                    "'ktm_curation_admin_executor', oid, 'EXECUTE') AS admin_side, "
                    "proacl::text AS acl "
                    "FROM pg_catalog.pg_proc "
                    "WHERE pronamespace = CAST(:schema AS regnamespace) "
                    "  AND proname = :name"
                ),
                {"schema": schema, "name": name},
            )
        ).mappings().one()
    # 양성 대조가 없으면 "grant가 통째로 사라진" 상태도 초록이 된다.
    assert grantees["provider_side"] is False, grantees["acl"]
    assert grantees["admin_side"] is True, grantees["acl"]

    # 그리고 본문 게이트가 살아 있는지 — grant만 재면 `session_user` 절을 지워도 초록이다.
    #
    # 이름이 소스에 보이는지로 재지 않는다. 그건 게이트를 뒤집거나(`IF NOT` → `IF`)
    # 이름만 주석에 남겨도 통과한다 — 효과가 아니라 문자열을 재는 것이다.
    #
    # 본문에 **닿으면서** 게이트에 걸리는 principal은 세 조건을 모두 만족해야 한다:
    # schema `feature`에 USAGE, 이 procedure에 EXECUTE, 그리고 admin executor의
    # member가 아닐 것. 실측으로 후보 7개 중 하나만 그렇다 —
    # `ktm_curation_command_owner`(이 procedure의 소유자). executor role들은 schema
    # USAGE 자체가 없어 resolver에서 먼저 막히고, 다른 owner들은 EXECUTE가 없다.
    # SECURITY DEFINER는 **닿은 뒤에** 적용되므로 USAGE가 없으면 본문을 못 본다.
    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        await session.execute(
            text("SET LOCAL SESSION AUTHORIZATION 'ktm_curation_command_owner'")
        )
        with pytest.raises(DBAPIError) as denied:
            await session.execute(text(call), _MERGE_IDS)
        await session.rollback()
    orig = denied.value.orig
    assert getattr(orig, "sqlstate", None) == "42501", repr(orig)[:200]
    assert "admin executor" in str(orig)

    # 통합 login이 실제로 이 CALL을 할 수 있어야 한다 — 위 두 단언이
    # "procedure가 아예 깨졌다"와 구분되게 하는 자리다.
    async with AsyncSession(migrated_engine) as session:
        await session.begin()
        async with as_api_runtime(session):
            await session.execute(text(call), _MERGE_IDS)
        await session.rollback()

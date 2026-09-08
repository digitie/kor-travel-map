"""TRUNCATE fence를 **실 DB로** 잰다 (migration 307).

## 이 파일의 게이트가 공허해지기 쉬운 이유

`TRUNCATE feature.features CASCADE`는 **307 이전에도 이미 거부됐다** — 폐포 안의 이웃
가드 열 개 중 하나가 먼저 raise하기 때문이다. 그래서 "TRUNCATE가 실패한다"만 재면 307을
통째로 되돌려도 초록이다. 조문이 그 함정을 명시한다.

그러므로 이 파일의 모든 단언은 **고유 제약 이름**을 본다. 무엇이 막았는지가 요지다.
"""

from __future__ import annotations

from typing import Final

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.integration._db_cleanup import (
    _ALWAYS_TRUNCATE_GUARDS,
    truncate_committed_test_rows,
)

pytestmark = [pytest.mark.integration]

_MANUAL_FEATURE_TRUNCATE: Final[str] = "ck_manual_feature_truncate_forbidden"
_REQUEST_EVIDENCE: Final[str] = "ck_feature_request_evidence_append_only"


def _constraint(error: DBAPIError) -> str | None:
    """asyncpg는 constraint 이름을 `orig`가 아니라 그 `__cause__`에 둔다."""

    candidate: BaseException | None = error.orig
    while candidate is not None:
        name = getattr(candidate, "constraint_name", None)
        if isinstance(name, str) and name:
            return name
        candidate = candidate.__cause__
    return None


async def _truncate(engine: AsyncEngine, statement: str) -> DBAPIError:
    with pytest.raises(DBAPIError) as refused:
        async with engine.begin() as connection:
            await connection.execute(text(statement))
    return refused.value


async def test_truncating_features_names_the_manual_feature_fence(
    migrated_engine: AsyncEngine,
) -> None:
    """**어느 가드가 막았는지**를 본다 — "막혔다"만으로는 307이 없어도 초록이다.

    307 이전에도 `CASCADE` 폐포의 이웃 가드가 먼저 raise해 TRUNCATE는 실패했다. 다만
    호출자가 받는 진단은 `feature_aliases TRUNCATE 금지`라 manual Feature와 무관했고,
    운영자는 그것을 읽고 다음 행동을 정할 수 없었다. 그것이 이 항목이 고치는 결함이다.
    """

    error = await _truncate(
        migrated_engine, "TRUNCATE feature.features RESTART IDENTITY CASCADE"
    )
    assert _constraint(error) == _MANUAL_FEATURE_TRUNCATE
    # 무엇을 대신 쓰라는 것까지 말한다.
    assert "purge_manual_feature" in str(error.orig)


async def test_replica_role_does_not_lift_the_features_fence(
    migrated_engine: AsyncEngine,
) -> None:
    """`ENABLE ALWAYS`를 고른 이유를 직접 잰다.

    origin-enabled였다면 `SET session_replication_role = replica` 한 줄로 사라진다. 그
    한 줄은 이 표를 TRUNCATE할 수 있는 유일한 행위자(superuser)가 언제든 쓸 수 있으므로,
    origin 트리거는 보안 바닥을 0만큼 올린다. 실수를 막는 유일한 변형이 ALWAYS다.
    """

    async def _truncate_as_replica() -> None:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("SET LOCAL session_replication_role = replica")
            )
            await connection.execute(
                text("TRUNCATE feature.features RESTART IDENTITY CASCADE")
            )

    with pytest.raises(DBAPIError) as refused:
        await _truncate_as_replica()
    assert _constraint(refused.value) == _MANUAL_FEATURE_TRUNCATE


@pytest.mark.parametrize(
    "relation",
    [
        "ops.feature_requests",
        "ops.feature_update_requests",
        "ops.feature_update_request_datasets",
    ],
)
async def test_m04_request_evidence_refuses_truncate(
    migrated_engine: AsyncEngine, relation: str
) -> None:
    """원장이 몰랐던 구멍 — `ops.feature_requests`에는 가드가 **아예** 없었다.

    M04 외부 제출은 재생성 불가능한 사용자 입력이다. 나머지 둘은 DELETE 가드만 있고
    TRUNCATE 가드가 없었다.
    """

    error = await _truncate(migrated_engine, f"TRUNCATE {relation} CASCADE")
    assert _constraint(error) == _REQUEST_EVIDENCE


async def test_feature_requests_refuses_delete_but_still_allows_the_status_update(
    migrated_engine: AsyncEngine,
) -> None:
    """DELETE는 막되 **UPDATE는 막지 않는다.**

    라우터가 `status`/`resolved_at`/`resolved_by_actor`를 정당하게 갱신한다 —
    `_FEATURE_REQUEST_TABLE_ACL`이 그 컬럼만 GRANT하는 것이 그 증거다. 여기서 UPDATE까지
    막으면 M04 해결 경로가 통째로 죽는다. 이 축이 없으면 그 과잉을 아무도 못 잡는다.
    """

    async with migrated_engine.begin() as connection:
        command_id = await connection.scalar(
            text(
                "INSERT INTO ops.domain_commands ("
                " actor, operation, idempotency_key, request_fingerprint"
                ") VALUES ('service:feature-request',"
                " 'service.feature-request.submit.v1',"
                " x_extension.gen_random_uuid(), repeat('7', 64))"
                " RETURNING command_id"
            )
        )
        request_id = await connection.scalar(
            text(
                "INSERT INTO ops.feature_requests ("
                " request_id, submitted_by_principal, request_payload, status,"
                " submission_command_id"
                ") VALUES (x_extension.gen_random_uuid(), 'service:feature-request',"
                " jsonb_build_object('kind', 'place', 'name', 'truncate fence probe'),"
                " 'pending', :command_id) RETURNING request_id"
            ),
            {"command_id": command_id},
        )

    async def _delete_request() -> None:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM ops.feature_requests WHERE request_id = :rid"),
                {"rid": request_id},
            )

    with pytest.raises(DBAPIError) as refused:
        await _delete_request()
    assert _constraint(refused.value) == _REQUEST_EVIDENCE

    # 정당한 갱신은 그대로 된다. `ck_feature_requests_resolution`이 해결 필드를 함께
    # 요구하므로 라우터가 쓰는 것과 같은 모양으로 갱신한다 — 그 제약은 307과 무관하고,
    # 여기서 반쪽만 갱신하면 이 축이 "UPDATE가 막힌다"를 잘못 증명하게 된다.
    async with migrated_engine.begin() as connection:
        resolution_command = await connection.scalar(
            text(
                "INSERT INTO ops.domain_commands ("
                " actor, operation, idempotency_key, request_fingerprint"
                ") VALUES ('admin:truncate-fence-probe',"
                " 'admin.feature-request.resolve.v1',"
                " x_extension.gen_random_uuid(), repeat('8', 64))"
                " RETURNING command_id"
            )
        )
        await connection.execute(
            text(
                "UPDATE ops.feature_requests"
                " SET status = 'rejected', resolved_at = clock_timestamp(),"
                "     resolved_by_actor = 'admin:truncate-fence-probe',"
                "     resolution_command_id = :command_id,"
                "     rejection_reason = 'truncate fence probe'"
                " WHERE request_id = :rid"
            ),
            {"rid": request_id, "command_id": resolution_command},
        )
    async with migrated_engine.connect() as connection:
        assert (
            await connection.scalar(
                text("SELECT status FROM ops.feature_requests WHERE request_id = :rid"),
                {"rid": request_id},
            )
            == "rejected"
        )


async def test_the_cleanup_helper_restores_the_guards_as_always_not_origin(
    migrated_engine: AsyncEngine,
) -> None:
    """정리 도우미가 운영 fence를 **조용히 약화시키면 안 된다.**

    `ENABLE TRIGGER`로 되돌리면 origin으로 내려앉아, 남은 세션 내내 `replica` 한 줄로
    우회 가능해진다. 그 상태는 겉보기에 정상이고 어떤 테스트도 실패하지 않는다 —
    그래서 여기서 잰다.
    """

    async with AsyncSession(migrated_engine) as session, session.begin():
        await truncate_committed_test_rows(
            session, "TRUNCATE feature.features RESTART IDENTITY CASCADE"
        )

    async with migrated_engine.connect() as connection:
        for relation, trigger in _ALWAYS_TRUNCATE_GUARDS:
            # `tgenabled`는 `"char"`라 드라이버가 bytes로 준다. 텍스트로 캐스팅해서
            # 비교 대상을 명확히 한다 — 이 저장소가 `provolatile`에서 같은 함정을 겪었다.
            enabled = await connection.scalar(
                text(
                    "SELECT tgenabled::text FROM pg_catalog.pg_trigger"
                    " WHERE tgrelid = CAST(:relation AS regclass) AND tgname = :trigger"
                ),
                {"relation": relation, "trigger": trigger},
            )
            assert enabled == "A", f"{relation}.{trigger} = {enabled}"

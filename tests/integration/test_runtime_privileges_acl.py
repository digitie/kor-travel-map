"""`_FEATURE_TABLE_PRIVILEGES` ACL 표가 실제 DB와 맞는지.

T-VN-40C가 `tests/integration/test_tvn40a_legacy_write_fence_acl.py`를 legacy
`curated_features` 표와 함께 지웠는데, 그 파일에는 **fence와 무관한** 검사가 둘
섞여 있었다. 표의 phantom 항목을 잡는 검사와, catalog(theme/source/rule)가 fence
대상이 아님을 못박는 검사다. 둘 다 40C 이후에도 지켜야 하므로 여기로 옮긴다.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra import runtime_privileges

pytestmark = pytest.mark.integration


async def test_every_declared_feature_relation_exists(
    migrated_session: AsyncSession,
) -> None:
    """ACL 표에 선언된 feature relation이 전부 실제로 존재한다.

    reconcile은 DB에 **있는** relation만 순회하므로 표의 phantom 항목(예: legacy 0032가
    rename해 사라진 `curated_tripmate_copy_snapshots`)은 아무 것도 지키지 않으면서 표를
    읽는 사람에게 "권한이 관리된다"는 인상만 준다. 40C처럼 표를 통째로 지우는 작업
    직후가 phantom이 가장 생기기 쉬운 시점이다.
    """
    from kortravelmap.infra import runtime_privileges

    rows = await migrated_session.execute(
        text(
            "SELECT relname FROM pg_catalog.pg_class AS c "
            "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'feature' AND c.relkind IN ('r', 'p', 'v')"
        )
    )
    existing = {row[0] for row in rows}
    declared = set(runtime_privileges._FEATURE_TABLE_PRIVILEGES)  # noqa: SLF001
    phantom = sorted(declared - existing)
    assert not phantom, f"ACL 표에 있지만 DB에 없는 feature relation: {phantom}"


#: reconciler의 inventory와 **같은 relkind 집합**이어야 한다. 넓게 잡으면 fail-close
#: 대상이 아닌 relation(materialized view 등)에까지 선언을 요구해, 실제로 배포를 막지
#: 않는 것을 막힌다고 읽게 만든다.
_OPS_RELATION_SQL = (
    "SELECT relname FROM pg_catalog.pg_class AS c "
    "JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace "
    "WHERE n.nspname = 'ops' AND c.relkind IN ('r', 'p', 'v')"
)


async def test_every_ops_relation_in_the_database_is_declared(
    migrated_session: AsyncSession,
) -> None:
    """`ops`도 `feature`처럼 선언 없이는 권한이 생기지 않는다 — 그 목록을 DB로 잰다.

    선언이 빠진 relation은 배포를 막는다(`RuntimePrivilegeReconciliationError`). 그래서
    이 게이트가 없으면 새 ops 표를 만든 사람이 배포 시점에야 알게 된다. `Base.metadata`로
    재면 안 된다 — 모델에 없는 ops 표가 실제로 있다.
    """
    from kortravelmap.infra import runtime_privileges

    rows = await migrated_session.execute(text(_OPS_RELATION_SQL))
    existing = {row[0] for row in rows}
    declared = set(runtime_privileges._OPS_TABLE_PRIVILEGES)  # noqa: SLF001
    undeclared = sorted(existing - declared)

    assert not undeclared, (
        "ops relation에 runtime ACL 선언이 없습니다. `_OPS_TABLE_PRIVILEGES`에 "
        "명시하세요 — 선언이 없으면 reconcile이 배포를 막습니다: "
        + ", ".join(undeclared)
    )


async def test_every_declared_ops_relation_exists(
    migrated_session: AsyncSession,
) -> None:
    """반대 방향. 없는 표를 가리키는 선언은 그 표가 아직 있다고 읽히게 만든다."""
    from kortravelmap.infra import runtime_privileges

    rows = await migrated_session.execute(text(_OPS_RELATION_SQL))
    existing = {row[0] for row in rows}
    declared = set(runtime_privileges._OPS_TABLE_PRIVILEGES)  # noqa: SLF001
    phantom = sorted(declared - existing)

    assert not phantom, f"ACL 표에 있지만 DB에 없는 ops relation: {phantom}"


async def test_theme_catalog_procedure_stays_executable(
    migrated_session: AsyncSession,
) -> None:
    """theme/source/rule catalog는 legacy가 아니다 — executor가 계속 써야 한다.

    plan:28이 그 셋을 "catalog input만 유지"로 정했고 T-VN-40의 procedure가 그 표에 쓴다.
    그 procedure의 EXECUTE는 `ktm_feature_runtime`이 아니라 **`ktm_curation_admin_executor`**가
    갖는다(`0207_tvn40_theme_catalog.py:533`). principal을 잘못 짚으면 이 테스트는 늘 red다.
    """
    result = await migrated_session.execute(
        text(
            """
            SELECT has_function_privilege(
                'ktm_curation_admin_executor',
                'feature.create_curated_theme_command(text,text,text,text,text,jsonb,bigint,text)',
                'EXECUTE'
            )
            """
        )
    )
    assert result.scalar_one() is True, "theme catalog procedure까지 막혔다 — plan:28 위반"


@pytest.mark.integration
def test_undeclared_relation_failure_names_the_sanctioned_escape() -> None:
    """fence가 배포를 막을 때 메시지가 **무엇을 하라**를 말해야 한다.

    예전 문구는 관계 이름만 나열했다. 새벽에 그것만 보면 "코드를 고쳐 재배포한다" 말고는
    길이 없어 보이고, 하필 위험한 migration 직전이 그 상황이다. 실제 탈출구는 fence를
    여는 것이 아니라 **관장 밖에 두는 것**이다 — 이 조정기는 세 schema만 훑으므로
    운영자의 임시·백업 표는 `public`에 두면 애초에 걸리지 않는다.

    이 테스트가 없으면 메시지가 조용히 옛 나열형으로 돌아가도 아무도 모른다.
    """

    message = runtime_privileges._undeclared_relation_message(  # noqa: SLF001
        ["ops.tvn36_legacy_freeze_preflight_manifest", "ops.backup_20260821"]
    )

    # 무엇이 걸렸는지는 그대로 나와야 한다.
    assert "ops.backup_20260821" in message
    # 그리고 두 갈래 조치가 모두 있어야 한다.
    assert "선언 목록" in message, message
    assert "public" in message, message
    # env allowlist는 채택하지 않았다 — 그런 길을 암시하면 안 된다.
    assert "allowlist" not in message.lower(), message


@pytest.mark.integration
def test_reconciler_governs_exactly_three_schemas() -> None:
    """위 탈출구가 성립하려면 `public`이 관장 밖이어야 한다.

    조정기가 훑는 schema 집합이 넓어지면 "public에 두면 된다"는 안내가 거짓이 된다.
    그때는 안내와 코드가 함께 바뀌어야 하므로 여기서 함께 묶어 둔다.
    """

    # 문자열 부분일치로 보면 안 된다. `IN ('feature','provider_sync','ops','staging')`은
    # 두 단언을 모두 통과한다 — 잡으려던 확장이 바로 그 모양이다. 반대로 줄바꿈이나
    # `= ANY(ARRAY[...])`로 바꾸기만 해도 거짓 red가 난다. 그래서 SQL이 아니라 **정본
    # 튜플**을 본다(SQL은 그 튜플에서 만들어진다).
    assert runtime_privileges._GOVERNED_SCHEMAS == (  # noqa: SLF001
        "feature",
        "provider_sync",
        "ops",
    ), (
        "관장 schema 집합이 바뀌었다. 실패 메시지의 `public` 안내가 여전히 참인지 "
        "확인하고 두 곳을 함께 고쳐라."
    )
    assert "public" not in runtime_privileges._GOVERNED_SCHEMAS  # noqa: SLF001
    # SQL이 그 튜플에서 만들어지는지도 본다 — 튜플만 두고 SQL에 손으로 적으면 갈라진다.
    sql = str(runtime_privileges._APPLICATION_RELATIONS_SQL)  # noqa: SLF001
    for schema in runtime_privileges._GOVERNED_SCHEMAS:  # noqa: SLF001
        assert f"'{schema}'" in sql, sql

"""`_FEATURE_TABLE_PRIVILEGES` ACL 표가 실제 DB와 맞는지.

T-VN-40C가 `tests/integration/test_tvn40a_legacy_write_fence_acl.py`를 legacy
`curated_features` 표와 함께 지웠는데, 그 파일에는 **fence와 무관한** 검사가 둘
섞여 있었다. 표의 phantom 항목을 잡는 검사와, catalog(theme/source/rule)가 fence
대상이 아님을 못박는 검사다. 둘 다 40C 이후에도 지켜야 하므로 여기로 옮긴다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.infra import runtime_privileges
from kortravelmap.infra.feature_repo import capture_provider_curation_input

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
async def test_provider_curation_seal_is_executable_by_the_loader_login(
    migrated_session: AsyncSession,
) -> None:
    """적재 login이 seal 함수를 **실제로** 실행할 수 있어야 한다.

    `capture_provider_curation_input`은 `client.load_feature_bundles`가
    `curation_dataset`을 받을 때 불리고, `dagster/etl.py`는 snapshot이 아닌 **모든**
    적재에 그것을 넘긴다. 그래서 이 EXECUTE가 없으면 그 부류 적재가 전부 선다 —
    2026-09-11 prod에서 실제로 그렇게 멈췄다(`permission denied for function
    current_provider_curation_input_set`).

    대상 principal은 **로그인 role**이다. 그룹(`ktm_feature_runtime`)에만 물으면
    멤버십·상속이 끊겨도 초록이라, 이 검사가 지키려는 바로 그 사실을 놓친다.
    자매 함수(`resolve_provider_feature_id`)를 함께 재는 것은 둘이 한 쌍으로 쓰이기
    때문이다 — claim으로 존재를 묻고, 적재 뒤 seal로 무엇을 썼는지 봉인한다.

    **이 검사가 보지 못하는 축이 둘 있다.** 여기서는 migrator session이 카탈로그
    술어를 묻는 것뿐이다.

    1. 적재 login이 **실제로 접속해** ADR-090 기동 preflight
       (`assert_runtime_db_privilege_boundary`)를 통과하는지. 그 축은
       `test_tvn34_runtime_privilege_preflight.py`의
       `test_tvn34_api_and_dagster_runtime_logins_pass_actual_catalog_preflight`가
       소유한다 — SECURITY DEFINER 함수에 EXECUTE를 주면 `infra/db.py`의 per-login
       허용목록에도 등록해야 하고, 빠뜨리면 그 테스트가 빨개진다(그리고 배포하면 모든
       Dagster 프로세스가 기동에서 죽는다).
    2. 그 권한으로 **실제 적재 경로를 태웠을 때** 함수가 도는지. 아래
       `test_provider_curation_seal_runs_on_the_loader_path_as_the_real_logins`가
       소유한다 — 카탈로그 술어는 EXECUTE만 보고, 함수가 읽는 표의 권한이나
       호출부가 함께 거는 `provider_sync.provider_datasets` 조회는 보지 못한다.
    """
    result = await migrated_session.execute(
        text(
            """
            SELECT
              has_function_privilege(
                'ktm_feature_service',
                'feature.current_provider_curation_input_set(bigint)',
                'EXECUTE'
              ) AS seal,
              has_function_privilege(
                'ktm_feature_service',
                'feature.resolve_provider_feature_id(bigint,text,text)',
                'EXECUTE'
              ) AS claim,
              has_function_privilege(
                'ktm_curation_admin_executor',
                'feature.current_provider_curation_input_set(bigint)',
                'EXECUTE'
              ) AS admin_executor_seal,
              -- 양성 대조를 통합 login에 걸면 안 된다: 그 하나가 아홉 executor 전부를
              -- 상속하므로 grant가 **다른 executor로 옮겨가도** 참이다. 의도한
              -- grantee를 이름으로 못박아야 이동을 잡는다.
              has_function_privilege(
                'ktm_curation_provider_executor',
                'feature.current_provider_curation_input_set(bigint)',
                'EXECUTE'
              ) AS provider_executor_seal
            """
        )
    )
    row = result.mappings().one()
    assert row["claim"] is True, (
        "claim 해석기가 적재 login에서 막혔다 — 이 검사의 전제가 깨졌다"
    )
    assert row["seal"] is True, (
        "seal 함수가 적재 login에서 막혔다 — curation_dataset을 받는 모든 적재가 선다"
    )
    # "적재는 할 수 있다"만 재면 "그리고 다른 모두도 할 수 있다"를 놓친다. ADR-100
    # 이후 LOGIN은 `ktm_feature_service` 하나뿐이고 그 하나가 9개 executor 전부의
    # inheriting member다 — 그래서 "다른 login은 못 한다"는 더는 잴 수 없다. 좁히는
    # 축은 이제 executor 층 하나이고 그 층은 ADR-100이 건드리지 않았다: 이 함수의
    # grant는 `ktm_curation_provider_executor`에만 가야 하고, admin 쪽으로 새면 그것이
    # 곧 넓어졌다는 뜻이다. executor role 사이에는 membership이 없으므로(bootstrap의
    # role graph는 평평하다) 이 술어는 여전히 갈린다.
    assert row["provider_executor_seal"] is True, (
        "seal의 grant가 `ktm_curation_provider_executor`에 없다 — 다른 executor로 "
        "옮겨갔거나 사라졌다"
    )
    assert row["admin_executor_seal"] is False, (
        "admin executor까지 seal을 실행할 수 있다 — grant가 의도보다 넓다"
    )


@pytest.mark.integration
async def test_provider_curation_seal_runs_on_the_loader_path_as_the_real_login(
    migrated_engine: AsyncEngine,
    dagster_runtime_engine: AsyncEngine,
) -> None:
    """적재 login으로 **접속해서** 적재가 부르는 그 함수를 실제로 실행한다.

    위 검사는 migrator가 `has_function_privilege`를 묻는다. 2026-09-11 prod 사고는
    그 술어로도 잡혔겠지만, 술어가 초록인데 적재가 서는 형태가 따로 있다 — 술어는
    EXECUTE **하나만** 본다. `capture_provider_curation_input`은 그 함수를
    `provider_sync.provider_datasets` 조회와 **한 문장으로 묶어** 부르므로, 표
    SELECT가 없으면 EXECUTE가 있어도 적재는 42501로 선다. 그 조합은 카탈로그
    술어가 구조적으로 관측하지 못한다.

    그래서 여기서는 raw SQL을 다시 쓰지 않고 **적재가 쓰는 바로 그 헬퍼**를 부른다.
    호출 문장이 바뀌면(표가 하나 더 붙는다든지) 이 검사가 따라 움직이지만, SQL을
    베껴 두면 사본만 초록인 채로 실물이 설 수 있다.

    ADR-100 이전에는 반대편(API login)도 여기서 함께 쟀다. LOGIN이 하나로 합쳐지면서
    그 축이 사라졌으므로 이 검사는 적재 경로 하나만 본다 — 넓어짐을 재는 일은 위
    카탈로그 검사의 executor 축이 맡는다.
    """

    provider = f"acl-seal-{uuid4().hex[:12]}"
    dataset_key = "loader-path"

    async with migrated_engine.begin() as seed:
        await seed.execute(
            text(
                """
                INSERT INTO provider_sync.provider_datasets (
                    provider, dataset_key, display_name, source_kind,
                    is_active, capabilities
                )
                VALUES (:provider, :dataset_key, :provider, 'system', true,
                        jsonb_build_object('schema_version', 1,
                                           'produces', '[]'::jsonb,
                                           'extensions', '{}'::jsonb))
                """
            ),
            {"provider": provider, "dataset_key": dataset_key},
        )

    try:
        async with AsyncSession(dagster_runtime_engine) as loader:
            assert (
                await loader.scalar(text("SELECT session_user::text"))
            ) == "ktm_feature_service", (
                "적재 login으로 접속하지 못했다 — 이 검사의 전제가 깨졌다"
            )
            sealed = await capture_provider_curation_input(
                loader, provider=provider, dataset_key=dataset_key
            )
            await loader.rollback()

        # 빈 dataset이므로 member는 0이지만, seal은 **그 사실 자체를 해시로 봉인한다.**
        # 값이 None이면 함수가 돌지 않은 것이고, 적재는 seal을 결과에 merge하므로
        # 그 상태로는 적재가 성립하지 않는다.
        assert sealed.curation_input_member_count == 0
        assert sealed.curation_input_set_hash, "seal이 해시를 돌려주지 않았다"

        # ADR-100 이전에는 여기서 API login으로 같은 헬퍼를 불러 42501을 봤다. LOGIN이
        # 하나로 합쳐진 지금 그 반대편은 존재하지 않는다 — `api_runtime_engine`과
        # `dagster_runtime_engine`이 같은 `ktm_feature_service`를 연다. 남은 경계는
        # executor 층이고, 그것은 위 카탈로그 테스트가 잰다. 이 자리에 같은 login을
        # 다시 열어 두면 "반대편도 잰다"는 인상만 남고 아무것도 지키지 않는다.
    finally:
        async with migrated_engine.begin() as cleanup:
            await cleanup.execute(
                text(
                    "DELETE FROM provider_sync.provider_datasets "
                    "WHERE provider = :provider"
                ),
                {"provider": provider},
            )


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

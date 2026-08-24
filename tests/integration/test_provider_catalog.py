"""``provider_catalog`` projection을 **실 DB**에 대고 고정하는 회귀 (T-VN-33, ADR-088).

이 모듈의 SQL은 지금까지 어떤 테스트에서도 실행되지 않았다. 유일한 테스트
(``packages/kor-travel-map-api/tests/test_provider_catalog.py``)는 SQL 문자열로 분기해
고정 dict를 돌려주는 ``_FakeSession``을 쓰고, 나머지 호출자는 전부
``monkeypatch.setattr(..., "list_provider_dataset_catalog", ...)``로 함수를 갈아끼운다.
감사 변이 스윕은 8개 변이(``is_active`` 필터 / ``is_enabled`` 필터 /
``default_refresh_scope`` 우선순위 / ``is_refreshable``의 ``is_active`` 항 /
``refresh_scopes`` 정렬 / ``enabled_refresh_operations`` / ``has_fixture_preview`` /
exact-set의 stale 분기)를 **동시에** 심고도 api 게이트가 통과한다고 보고했다.

여기서는 그 8축을 alembic head DB에 대고 각각 죽인다(같은 변이를 하나씩 심어
이 파일이 실제로 잡는 것을 확인했다). 카탈로그 행은
``seed_session``(테스트 종료 시 rollback) 안에서만 만든다 — 시드를 건드리지 않고
스키마가 실제로 허용하는 상태만 만든다.

추가로 두 경계상태를 고정한다. 둘 다 스키마 허용이고, 앞 판에서는 카탈로그 projection이
``ValueError``로 죽어 ``/ops/datasets`` 그리드 루프 전체가 500이 됐다.

* 상태 ①: enabled refresh operation은 있는데 scope 행이 0개
  (``provider_dataset_operation_scopes``에 "operation당 최소 1행" 제약이 없다).
* 상태 ②: 유일한 scope가 ``external_system:*``
  (``is_valid_provider_dataset_sync_scope``가 그 형태를 허용한다).

저장소 전체에 **refresh kind에 ``sync_scopes=()``를 주는 fixture가 없었고**
(``rg 'sync_scopes=\\(\\)'`` 히트는 전부 ``operation_kind="preview"``다), 그 공백이 위
결함이 적대 리뷰 11라운드를 살아남은 이유다.

마지막으로 **한 응답의 자기모순** 축을 닫는다. ``GET /v1/ops/datasets``가 낸 모든
canonical 행에 대해 "그 행의 ``sync_scope``를 그 행의 capability가 제출 가능이라
말하는 것"과 "DB가 그 dataset의 그 scope로 요청을 받는 것"이 동치여야 한다
(``test_grid_capability_never_contradicts_its_own_membership_rows``). 형제 refresh
operation이 ``dataset_wide``와 ``external_system:*``를 나눠 선언한 dataset이 그 축을
가르는 fixture다 — 앞 판은 ``target_grids``가 없다는 이유로 capability를 "전체 dataset
단위로만 갱신합니다"로 접었고, 같은 응답이 낸 ``external_system:*`` 행이 그 거짓 사유로
막혔다.

이 파일은 ``migrated_engine``(conftest.py, session-scope 공유 DB)을 쓰지 않고
**전용 database**를 하나 더 만들어 거기에만 alembic head를 적용한다(``seed_engine``).
아래 게이트들이 카탈로그의 **전역** 성질을 단언하는데, 공유 DB에는 형제 테스트가
commit한 행이 그대로 남아 결과가 실행 순서에 매이기 때문이다. 그 오염이 실재한다는
증거는 수치가 아니라 실행이다 —
``test_exact_set_gate_is_immune_to_operations_committed_by_other_tests``가 공유 DB에
handler 없는 활성 refresh operation을 직접 commit해 (a) 공유 DB로 돌린 게이트가 red,
(b) 같은 순간 전용 DB로 돌린 게이트가 green임을 함께 단언한다. 전용 DB를 쓰는 지금은
``pytest tests/integration/test_offline_upload_load.py tests/integration/test_provider_catalog.py``
가 전건 통과한다(2026-08-11 실측). 개수는 형제 파일이 바뀌면 달라지므로 적지 않는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
import pytest
from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.ops_dataset_service import (
    _catalog_info,
    _catalog_state_memberships,
    _scope_refresh_capability,
)
from kortravelmap.api.provider_catalog import (
    ActiveOperationHandlerDriftError,
    ProviderDatasetCatalogEntry,
    assert_active_operation_handler_exact_set,
    find_provider_dataset_catalog_entry,
    list_active_refresh_operation_bindings,
    list_provider_dataset_catalog,
)
from kortravelmap.api.settings import ApiSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.providers.feature_operation_registry import (
    feature_operation_handler_keys,
)

pytestmark = pytest.mark.integration

#: 시드와 겹치지 않는 probe provider. 카탈로그 전체를 읽은 뒤 이 provider로만 좁힌다.
_PROBE_PROVIDER = "python-catalog-axis-probe-api"

_CAPABILITIES = '{"schema_version": 1, "produces": ["place"], "extensions": {}}'

_INSERT_DATASET_SQL = """
INSERT INTO provider_sync.provider_datasets (
    provider, dataset_key, display_name, source_kind, is_active, capabilities
) VALUES (
    :provider, :dataset_key, :display_name, 'openapi', true,
    CAST(:capabilities AS jsonb)
)
RETURNING provider_dataset_id
"""

_INSERT_OPERATION_SQL = """
INSERT INTO provider_sync.provider_dataset_operations (
    provider_dataset_id, operation_key, operation_kind, is_enabled, config
) VALUES (
    :provider_dataset_id, :operation_key, :operation_kind, :is_enabled,
    CAST(:config AS jsonb)
)
"""

_INSERT_SCOPE_SQL = """
INSERT INTO provider_sync.provider_dataset_operation_scopes (
    provider_dataset_id, sync_scope, operation_key, operation_kind
) VALUES (:provider_dataset_id, :sync_scope, :operation_key, 'refresh')
"""


@pytest.fixture(scope="module")
async def seed_engine(pg_container: Any) -> AsyncIterator[AsyncEngine]:
    """이 파일 전용 database에 ``alembic upgrade head``만 적용한 engine.

    ``conftest.py``의 ``migrated_engine``은 session-scope 공유 DB라 형제 테스트가
    commit한 행이 그대로 보인다. 이 파일의 게이트는 "**시드가 선언한** 카탈로그"의
    전역 성질을 단언하므로 그 DB를 읽으면 결과가 실행 순서에 매인다(모듈 docstring의
    실측). 테스트가 만든 operation은 시드가 아니다 — 그래서 같은 컨테이너에 database를
    새로 만들고 migration만 적용해, 어떤 테스트도 write하지 않는 상태를 읽는다.
    ``test_vnext_target_freeze.py``의 ``_freeze_contract``가 빈 DB에 계약을 적용하는
    것과 같은 방식이다.

    module-scope인 이유는 alembic 적용이 이 파일당 한 번만 돌게 하기 위해서다.

    `300` fresh bootstrap이 final role graph와 schema ownership을 함께 만든 뒤
    restricted migrator로 root를 적용하므로, module fixture와 공유 fixture가 같은
    deployment 경계를 사용한다.
    """
    from pathlib import Path

    from alembic.config import Config
    from sqlalchemy import event
    from sqlalchemy.engine import make_url

    from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
    from tests.integration._application_300_bootstrap import (
        upgrade_head_with_application_300_bootstrap,
    )

    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"catalog_seed_{uuid4().hex}"

    async def _run_on_admin(statement: str) -> None:
        admin_engine = make_async_engine(admin_dsn)
        try:
            async with admin_engine.connect() as raw_connection:
                autocommit = await raw_connection.execution_options(
                    isolation_level="AUTOCOMMIT"
                )
                await autocommit.execute(text(statement))
        finally:
            await admin_engine.dispose()

    await _run_on_admin(f'CREATE DATABASE "{database}"')
    seed_dsn = (
        make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)
    )

    root = Path(__file__).resolve().parents[2]  # noqa: ASYNC240  # sync path-arith
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    await upgrade_head_with_application_300_bootstrap(cfg, seed_dsn)

    # 읽기용 engine은 계속 컨테이너 admin 자격이다. migrator LOGIN은 아무것도 소유하지
    # 않고(소유자는 ``ktm_feature_schema_owner``) runtime ACL도 받지 않으므로, 이 파일이
    # 카탈로그를 읽고 probe 행을 넣는 데 쓸 자격이 아니다.
    engine = make_async_engine(seed_dsn)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_search_path(dbapi_conn: Any, _conn_record: Any) -> None:
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("SET search_path = public, x_extension")
        finally:
            cursor.close()

    try:
        yield engine
    finally:
        await engine.dispose()
        await _run_on_admin(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')


@pytest.fixture
async def seed_session(seed_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """``seed_engine``의 per-test 세션. 종료 시 rollback이라 시드가 오염되지 않는다."""
    async with (
        AsyncSession(seed_engine, expire_on_commit=False) as session,
        session.begin(),
    ):
        yield session
        await session.rollback()


async def _insert_dataset(
    session: AsyncSession,
    *,
    dataset_key: str,
) -> int:
    return int(
        (
            await session.execute(
                text(_INSERT_DATASET_SQL),
                {
                    "provider": _PROBE_PROVIDER,
                    "dataset_key": dataset_key,
                    "display_name": f"probe {dataset_key}",
                    "capabilities": _CAPABILITIES,
                },
            )
        ).scalar_one()
    )


async def _insert_operation(
    session: AsyncSession,
    *,
    provider_dataset_id: int,
    operation_key: str,
    operation_kind: str,
    is_enabled: bool = True,
    config: str = "{}",
    sync_scopes: tuple[str, ...] = (),
) -> None:
    await session.execute(
        text(_INSERT_OPERATION_SQL),
        {
            "provider_dataset_id": provider_dataset_id,
            "operation_key": operation_key,
            "operation_kind": operation_kind,
            "is_enabled": is_enabled,
            "config": config,
        },
    )
    for sync_scope in sync_scopes:
        await session.execute(
            text(_INSERT_SCOPE_SQL),
            {
                "provider_dataset_id": provider_dataset_id,
                "sync_scope": sync_scope,
                "operation_key": operation_key,
            },
        )


async def _seed_axis_datasets(session: AsyncSession) -> dict[str, int]:
    """8축을 각각 가르는 최소 카탈로그를 만든다(모두 스키마 허용 상태다)."""

    ids: dict[str, int] = {}

    # (1) 여러 scope + 형제 **비활성** refresh operation + fixture preview.
    multi = await _insert_dataset(session, dataset_key="axis_multi_scope")
    ids["axis_multi_scope"] = multi
    await _insert_operation(
        session,
        provider_dataset_id=multi,
        operation_key="axis_multi_scope_job",
        operation_kind="refresh",
        sync_scopes=("dataset_wide", "target_grids", "external_system:pinvi"),
    )
    # 같은 dataset·같은 ``dataset_wide`` scope에 결박된 **비활성** 형제 operation.
    # 0091이 scope PK를 triple로 올린 목적이 정확히 이 모양이다. 고유 scope를 하나
    # 더 줘서 ``enabled_refresh_operations``의 ``is_enabled`` 항이 빠지면
    # ``refresh_scopes``에 그 scope가 새어 나오게 만든다.
    await _insert_operation(
        session,
        provider_dataset_id=multi,
        operation_key="axis_disabled_sibling_job",
        operation_kind="refresh",
        is_enabled=False,
        sync_scopes=("dataset_wide", "external_system:disabled-decoy"),
    )
    await _insert_operation(
        session,
        provider_dataset_id=multi,
        operation_key="axis_fixture_preview_job",
        operation_kind="preview",
        config='{"handler": "fixture"}',
    )

    # (2) dataset_wide만 선언 — default scope 우선순위의 대조군.
    wide = await _insert_dataset(session, dataset_key="axis_dataset_wide_only")
    ids["axis_dataset_wide_only"] = wide
    await _insert_operation(
        session,
        provider_dataset_id=wide,
        operation_key="axis_dataset_wide_only_job",
        operation_kind="refresh",
        sync_scopes=("dataset_wide",),
    )

    # (3) 비활성 dataset인데 enabled refresh operation과 scope는 그대로 있다.
    # ``reject_inactive_provider_dataset`` 트리거가 비활성 dataset으로의 normal write를
    # 거부하므로 **활성 상태에서 카탈로그를 만든 뒤 끄는** 순서여야 한다. 프로덕션에서
    # 비활성 dataset이 생기는 경로도 정확히 이것이다(운영자가 dataset을 끈다).
    inactive = await _insert_dataset(session, dataset_key="axis_inactive")
    ids["axis_inactive"] = inactive
    await _insert_operation(
        session,
        provider_dataset_id=inactive,
        operation_key="axis_inactive_job",
        operation_kind="refresh",
        sync_scopes=("target_grids",),
    )
    await session.execute(
        text(
            "UPDATE provider_sync.provider_datasets SET is_active = false "
            "WHERE provider_dataset_id = :provider_dataset_id"
        ),
        {"provider_dataset_id": inactive},
    )

    # (4) 상태 ① — enabled refresh operation, scope 행 0개.
    no_scope = await _insert_dataset(session, dataset_key="axis_no_scope_rows")
    ids["axis_no_scope_rows"] = no_scope
    await _insert_operation(
        session,
        provider_dataset_id=no_scope,
        operation_key="axis_no_scope_rows_job",
        operation_kind="refresh",
    )

    # (5) 상태 ② — 유일 scope가 external_system.
    external = await _insert_dataset(session, dataset_key="axis_external_only")
    ids["axis_external_only"] = external
    await _insert_operation(
        session,
        provider_dataset_id=external,
        operation_key="axis_external_only_job",
        operation_kind="refresh",
        sync_scopes=("external_system:pinvi",),
    )

    # (7) ``dataset_wide``(op a) + ``external_system:*``(op b) — 형제 refresh operation이
    # 서로 다른 scope를 선언한다. 0091이 scope PK를 triple로 올렸고
    # ``is_valid_provider_dataset_sync_scope``가 ``external_system:*``를 허용하므로
    # 스키마가 그대로 받는다. 이 모양이 capability↔membership 자기모순을 가르는 축이다 —
    # ``target_grids``가 없다는 이유로 capability를 "전체 dataset 단위로만"으로 접으면
    # 같은 응답이 낸 ``external_system:concierge`` 행이 거짓 사유로 막힌다.
    wide_plus_external = await _insert_dataset(
        session, dataset_key="axis_dataset_wide_plus_external"
    )
    ids["axis_dataset_wide_plus_external"] = wide_plus_external
    await _insert_operation(
        session,
        provider_dataset_id=wide_plus_external,
        operation_key="axis_wide_plus_external_wide_job",
        operation_kind="refresh",
        sync_scopes=("dataset_wide",),
    )
    await _insert_operation(
        session,
        provider_dataset_id=wide_plus_external,
        operation_key="axis_wide_plus_external_concierge_job",
        operation_kind="refresh",
        sync_scopes=("external_system:concierge",),
    )

    # (6) preview handler 축: 비활성 fixture preview + 활성 non-fixture preview.
    preview = await _insert_dataset(session, dataset_key="axis_preview_not_fixture")
    ids["axis_preview_not_fixture"] = preview
    await _insert_operation(
        session,
        provider_dataset_id=preview,
        operation_key="axis_disabled_fixture_preview_job",
        operation_kind="preview",
        is_enabled=False,
        config='{"handler": "fixture"}',
    )
    await _insert_operation(
        session,
        provider_dataset_id=preview,
        operation_key="axis_live_preview_job",
        operation_kind="preview",
        config='{"handler": "live"}',
    )

    await session.flush()
    return ids


@pytest.fixture
async def axis_catalog(
    seed_session: AsyncSession,
) -> tuple[AsyncSession, dict[str, int]]:
    """probe 카탈로그가 심긴 rollback 세션."""

    ids = await _seed_axis_datasets(seed_session)
    return seed_session, ids


def _probe_entries(
    catalog: tuple[ProviderDatasetCatalogEntry, ...],
) -> dict[str, ProviderDatasetCatalogEntry]:
    return {
        entry.dataset_key: entry for entry in catalog if entry.provider == _PROBE_PROVIDER
    }


async def test_catalog_active_only_filters_inactive_datasets(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """``_CATALOG_SQL``의 ``active_only`` WHERE 절 축."""

    session, _ = axis_catalog

    all_entries = _probe_entries(await list_provider_dataset_catalog(session))
    active_entries = _probe_entries(
        await list_provider_dataset_catalog(session, active_only=True)
    )

    assert "axis_inactive" in all_entries
    assert all_entries["axis_inactive"].is_active is False
    # 필터가 빠지면 여기서 죽는다.
    assert "axis_inactive" not in active_entries
    # 비활성 하나만 빠져야 한다 — 필터가 과하게 좁히는 것도 결함이다.
    assert set(all_entries) - set(active_entries) == {"axis_inactive"}


async def test_active_refresh_bindings_require_active_dataset_and_enabled_operation(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """``_ACTIVE_REFRESH_OPERATION_BINDINGS_SQL``의 ``is_active``/``is_enabled`` 축."""

    session, ids = axis_catalog

    bindings = await list_active_refresh_operation_bindings(session)
    probe = {
        (binding.dataset_key, binding.operation_key)
        for binding in bindings
        if binding.provider == _PROBE_PROVIDER
    }

    assert probe == {
        ("axis_multi_scope", "axis_multi_scope_job"),
        ("axis_dataset_wide_only", "axis_dataset_wide_only_job"),
        # scope 행이 없어도 operation은 활성이다 — binding 목록은 operation relation만
        # 본다. 이 축이 상태 ①을 만든다.
        ("axis_no_scope_rows", "axis_no_scope_rows_job"),
        ("axis_external_only", "axis_external_only_job"),
        (
            "axis_dataset_wide_plus_external",
            "axis_wide_plus_external_wide_job",
        ),
        (
            "axis_dataset_wide_plus_external",
            "axis_wide_plus_external_concierge_job",
        ),
    }
    # dataset 비활성 / operation 비활성이 각각 배제됐는지 따로 못박는다.
    assert ("axis_inactive", "axis_inactive_job") not in probe
    assert ("axis_multi_scope", "axis_disabled_sibling_job") not in probe
    # binding은 dataset identity를 그대로 나른다(handler registry가 모르는 축).
    multi = next(
        binding
        for binding in bindings
        if binding.operation_key == "axis_multi_scope_job"
    )
    assert multi.provider_dataset_id == ids["axis_multi_scope"]


async def test_refresh_scopes_are_sorted_and_come_only_from_enabled_operations(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """``refresh_scopes`` 정렬 축 + ``enabled_refresh_operations``의 ``is_enabled`` 축."""

    session, _ = axis_catalog
    entries = _probe_entries(await list_provider_dataset_catalog(session))

    multi = entries["axis_multi_scope"]
    assert [operation.operation_key for operation in multi.enabled_refresh_operations] == [
        "axis_multi_scope_job"
    ]
    # 오름차순이다. ``reverse=True`` 변이는 여기서 죽는다.
    assert multi.refresh_scopes == (
        "dataset_wide",
        "external_system:pinvi",
        "target_grids",
    )
    # 비활성 형제만 선언한 scope는 새어 나오지 않는다.
    assert "external_system:disabled-decoy" not in multi.refresh_scopes
    # 비활성 형제 자체는 카탈로그 행에 남아 있어야 한다(운영자가 볼 수 있어야 한다).
    assert {
        (operation.operation_key, operation.is_enabled) for operation in multi.operations
    } == {
        ("axis_multi_scope_job", True),
        ("axis_disabled_sibling_job", False),
        ("axis_fixture_preview_job", True),
    }


async def test_default_refresh_scope_prefers_target_grids(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """``default_refresh_scope`` 우선순위 축(target_grids > dataset_wide)."""

    session, _ = axis_catalog
    entries = _probe_entries(await list_provider_dataset_catalog(session))

    multi = entries["axis_multi_scope"]
    assert "dataset_wide" in multi.refresh_scopes
    assert multi.default_refresh_scope == "target_grids"
    assert multi.declares_default_refresh_scope is True
    assert multi.supports_targeted_refresh is True

    wide = entries["axis_dataset_wide_only"]
    assert wide.default_refresh_scope == "dataset_wide"
    assert wide.supports_targeted_refresh is False


async def test_is_refreshable_requires_active_dataset(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """``is_refreshable``의 ``is_active`` 항 축."""

    session, _ = axis_catalog
    entries = _probe_entries(await list_provider_dataset_catalog(session))

    inactive = entries["axis_inactive"]
    # operation은 그대로 활성이다 — 그래서 ``is_active`` 항이 빠지면 True가 된다.
    assert [
        operation.operation_key for operation in inactive.enabled_refresh_operations
    ] == ["axis_inactive_job"]
    assert inactive.refresh_scopes == ("target_grids",)
    assert inactive.is_refreshable is False
    # 비활성 dataset은 그리드에서 catalog 전용 행 하나로 접힌다.
    assert _catalog_state_memberships(inactive) == (("dataset_wide", None),)


async def test_has_fixture_preview_requires_enabled_fixture_handler(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """``has_fixture_preview``의 handler=="fixture" 축과 ``is_enabled`` 항."""

    session, _ = axis_catalog
    entries = _probe_entries(await list_provider_dataset_catalog(session))

    assert entries["axis_multi_scope"].has_fixture_preview is True
    # 비활성 fixture preview + 활성 non-fixture preview → 지원하지 않는다.
    not_fixture = entries["axis_preview_not_fixture"]
    assert {
        (operation.operation_key, operation.is_enabled, operation.config.get("handler"))
        for operation in not_fixture.operations
    } == {
        ("axis_disabled_fixture_preview_job", False, "fixture"),
        ("axis_live_preview_job", True, "live"),
    }
    assert not_fixture.has_fixture_preview is False


@pytest.mark.parametrize(
    (
        "dataset_key",
        "expected_scopes",
        "expected_is_refreshable",
        "expected_capability",
        "expected_memberships",
    ),
    [
        # 상태 ① — scope 행 0개. 결박할 membership이 없으므로 갱신 대상이 아니다.
        # 제출 가능 집합은 공집합이고, DB도 이 dataset의 어떤 triple도 받지 않는다.
        (
            "axis_no_scope_rows",
            (),
            False,
            {
                "supported": False,
                "selector": "none",
                "effect": "none",
                "default_sync_scope": "dataset_wide",
                "allowed_sync_scopes": [],
                "reason": (
                    "이 dataset의 refresh operation에 sync scope 선언이 없어 "
                    "걸 대상이 없습니다."
                ),
            },
            (("dataset_wide", None),),
        ),
        # 상태 ② — external_system 전용. membership은 실재하는 triple 그대로이고,
        # ``_ACTIVE_DATASET_MEMBERSHIPS_SQL``이 그 triple을 받는다(scope kind를 보지
        # 않는다). 그래서 capability도 그 scope를 제출 가능으로 내야 한다 —
        # ``effect="none"``으로 접던 앞 판은 같은 응답이 낸 행을 거짓 사유로 막았다.
        # ``default_sync_scope``는 표시용 degrade 값(``dataset_wide``)이 아니라 선언된
        # scope다. degrade 값을 내면 그것이 ``allowed_sync_scopes`` 밖이라 프론트
        # fail-closed 게이트가 계약 모순으로 읽는다.
        (
            "axis_external_only",
            ("external_system:pinvi",),
            True,
            {
                "supported": True,
                # ``selector``는 "scope **안의 대상**을 무엇이 고르는가"다. 이 dataset은
                # ``target_grids``를 선언하지 않았으므로 POI target selector가 없다.
                # ``poi_cache_targets``를 그대로 내면 화면이 "범위 계약: 활성 POI target"
                # 이라고 적고, 막힐 때 사유도 POI target을 근거로 든다 — 둘 다 거짓이다.
                "selector": "none",
                "effect": "sync_scope",
                "default_sync_scope": "external_system:pinvi",
                "allowed_sync_scopes": ["external_system:pinvi"],
                "reason": None,
            },
            (("external_system:pinvi", "axis_external_only_job"),),
        ),
    ],
)
async def test_refreshable_dataset_without_declared_default_scope_degrades(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
    dataset_key: str,
    expected_scopes: tuple[str, ...],
    expected_is_refreshable: bool,
    expected_capability: dict[str, object],
    expected_memberships: tuple[tuple[str, str | None], ...],
) -> None:
    """스키마 허용 경계상태 2종에서 카탈로그 projection이 죽지 않는다.

    앞 판은 ``default_refresh_scope``가 ``ValueError``였고 ``_catalog_info``가
    ``is_refreshable``인 행마다 무조건 그것을 읽었다 — 두 상태 중 하나라도 DB에 있으면
    ``/ops/datasets`` 그리드 루프 전체가 500이었다.

    두 상태의 **capability는 서로 다르다.** 상태 ①은 걸 수 있는 triple이 아예 없어
    ``effect="none"``이고, 상태 ②는 DB가 받는 triple이 실재하므로 그 scope를 제출
    가능으로 낸다. ``entry.declares_default_refresh_scope``는 둘 다 ``False``이지만
    그것은 **표시 기본값의 degrade 여부**일 뿐 제출 가능 여부가 아니다.
    """

    session, _ = axis_catalog
    entry = _probe_entries(await list_provider_dataset_catalog(session))[dataset_key]

    assert entry.is_refreshable is expected_is_refreshable
    assert entry.refresh_scopes == expected_scopes
    assert entry.declares_default_refresh_scope is False
    # 표시 기본값은 여전히 degrade한다 — capability가 그 값을 쓰지 않을 뿐이다.
    assert entry.default_refresh_scope == "dataset_wide"

    info = _catalog_info(entry)
    assert info.is_refreshable is expected_is_refreshable
    assert info.provider_state_default_scope == "dataset_wide"
    scope_refresh = info.scope_refresh
    assert {
        "supported": scope_refresh.supported,
        "selector": scope_refresh.selector,
        "effect": scope_refresh.effect,
        "default_sync_scope": scope_refresh.default_sync_scope,
        "allowed_sync_scopes": scope_refresh.allowed_sync_scopes,
        "reason": scope_refresh.reason,
    } == expected_capability
    # degrade가 실행 허용 목록을 넓히지 않는다 — 선언된 것만 그대로 실린다.
    assert "dataset_wide" not in scope_refresh.allowed_sync_scopes

    assert _catalog_state_memberships(entry) == expected_memberships


async def test_selector_tracks_target_grids_declaration(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """``selector``는 ``target_grids`` 선언과 동치다 — 분기 도달 여부가 아니다.

    ``selector``가 답하는 질문은 "scope **안의 대상**을 무엇이 고르는가"이고,
    ``poi_cache_targets``는 POI cache target 목록이 그 대상을 정한다는 뜻이다. 그 목록은
    ``target_grids`` scope에만 있다. ``effect="sync_scope"`` 분기를 ``target_grids``
    선언 밖으로 넓히면서 두 축이 갈렸고, 그때 ``selector``를 상수로 두면
    ``external_system:*``만 선언한 dataset이 화면에 "범위 계약: 활성 POI target"으로
    그려지고 막힐 때 사유도 POI target을 근거로 든다(둘 다 그 dataset에 거짓이다).

    그래서 개별 케이스가 아니라 **동치**를 못박는다. probe 카탈로그 전체를 돌며 두 축이
    한 건이라도 어긋나면 red다.
    """

    session, _ = axis_catalog
    entries = _probe_entries(await list_provider_dataset_catalog(session))

    observed = {}
    for key, entry in entries.items():
        capability = _catalog_info(entry).scope_refresh
        # 제출 가능한 scope가 없으면(``effect != "sync_scope"``) 고를 대상도 없으므로
        # selector는 언제나 ``none``이다 — 비활성 dataset은 ``target_grids``를 선언하고도
        # 여기 해당한다(실측: ``axis_inactive``).
        observed[key] = (
            capability.selector,
            capability.effect == "sync_scope" and "target_grids" in entry.refresh_scopes,
        )
    mismatched = {
        key: pair
        for key, pair in observed.items()
        if (pair[0] == "poi_cache_targets") != pair[1]
    }
    assert mismatched == {}, f"selector와 target_grids 선언이 어긋난다: {mismatched}"

    # 동치가 공허하지 않으려면 양쪽 값이 실제로 관측돼야 하고, 특히
    # ``effect="sync_scope"``인데 selector가 ``none``인 축(= external 전용)이 있어야 한다.
    assert "poi_cache_targets" in {selector for selector, _ in observed.values()}
    assert "none" in {selector for selector, _ in observed.values()}
    external_only = _catalog_info(entries["axis_external_only"]).scope_refresh
    assert (external_only.effect, external_only.selector) == ("sync_scope", "none")


async def test_declared_dataset_wide_capability_stays_distinguishable(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """대조군 — 정상 dataset-wide dataset은 ``effect="dataset_wide"`` 그대로다.

    위 두 경계상태와 **같은 필드값**을 내면 소비자가 구분할 수 없다. 여기서 두
    payload가 실제로 갈라지는지 못박는다.
    """

    session, _ = axis_catalog
    entries = _probe_entries(await list_provider_dataset_catalog(session))

    wide = _catalog_info(entries["axis_dataset_wide_only"]).scope_refresh
    assert wide.effect == "dataset_wide"
    assert wide.supported is False
    assert wide.selector == "none"
    assert wide.default_sync_scope == "dataset_wide"
    assert wide.allowed_sync_scopes == []

    degraded = _catalog_info(entries["axis_no_scope_rows"]).scope_refresh
    assert (wide.supported, wide.selector, wide.default_sync_scope, wide.allowed_sync_scopes) == (
        degraded.supported,
        degraded.selector,
        degraded.default_sync_scope,
        degraded.allowed_sync_scopes,
    ), "effect를 빼면 두 상태가 reason 말고는 완전히 같아진다 — 그래서 effect가 필요하다"
    assert degraded.effect != wide.effect


async def test_seed_has_catalog_only_datasets_without_refresh_operations(
    seed_session: AsyncSession,
) -> None:
    """``_catalog_state_memberships`` docstring이 "seed에 실재한다"고 적은 상태.

    개수는 DB마다 다르므로(0089가 legacy pair를 harvest한다) 개수는 박지 않고 성질만
    고정한다.
    """

    catalog = await list_provider_dataset_catalog(seed_session)
    catalog_only = [entry for entry in catalog if not entry.enabled_refresh_operations]

    assert catalog_only, "시드에 refresh operation이 없는 dataset이 하나도 없다"
    for entry in catalog_only:
        assert entry.refresh_scopes == ()
        assert entry.is_refreshable is False
        assert _catalog_state_memberships(entry) == (("dataset_wide", None),)


# ---------------------------------------------------------------------------
# 활성 operation ↔ handler exact-set 게이트
#
# ``assert_active_operation_handler_exact_set``에는 프로덕션 호출자가 없다. 이 파일이
# 유일한 강제 지점이고, CI의 pytest integration 게이트에서 alembic head DB에 대고 돈다.
# ---------------------------------------------------------------------------

#: Dagster handler가 없는 seed 활성 refresh operation. 각 key의 실행 주체:
#:
#: * ``mois_license_incremental_update`` — ``src/kortravelmap/mois.py``의
#:   ``_INCREMENTAL_JOB_KIND``(CLI 경로).
#: * ``mois_license_closed_update`` — 같은 모듈의 ``_CLOSED_JOB_KIND``(CLI 경로).
#: * ``mois_license_detail_update`` — 저장소 전수 grep에서 0089 seed와
#:   ``tests/integration/test_list_sync_states.py`` 두 곳에만 나온다. 실행 주체가 없다.
#:
#: 이 집합이 실제 차집합과 정확히 같은지는 아래 테스트가 따로 단언한다 — 목록이
#: 오래되면 새 drift가 조용히 통과하지 않는다.
_NON_DAGSTER_REFRESH_OPERATION_KEYS = frozenset(
    {
        "mois_license_incremental_update",
        "mois_license_closed_update",
        "mois_license_detail_update",
    }
)


#: `alembic/versions/0224_c7_external_system_scope.py`와 같은 값이어야 한다.
_C7_PROVIDER = "python-kma-api"
_C7_DATASET_KEY = "kma_ultra_short_nowcast"
_C7_SYNC_SCOPE = "external_system:c7-e2e"


async def test_seed_active_refresh_operations_match_dagster_handlers_exactly(
    seed_session: AsyncSession,
) -> None:
    """모듈 docstring이 약속한 exact-set 대조를 실제로 돌린다."""

    verified = await assert_active_operation_handler_exact_set(
        seed_session,
        handler_operation_keys=(
            set(feature_operation_handler_keys()) | _NON_DAGSTER_REFRESH_OPERATION_KEYS
        ),
    )

    assert verified >= _NON_DAGSTER_REFRESH_OPERATION_KEYS


async def test_seed_declares_the_c7_acceptance_external_system_scope(
    seed_session: AsyncSession,
) -> None:
    """C7 인수 scope 선언이 시드+migration 결과에 실제로 존재한다.

    ADR-088 이후 제출 가능한 ``sync_scope``의 정본은 이 선언이다 —
    ``infra/feature_update_repo._ACTIVE_DATASET_MEMBERSHIPS_SQL``이 exact join으로
    요구하고 ``feature_update_request_datasets``/``import_job_datasets``/
    ``provider_sync_state``/``offline_uploads``의 exact FK가 구조로 강제한다.

    이 행이 조용히 사라지면 C7 prod live 인수(``ops-c7-kma-*-write``)가 preview
    422로 죽는데, 그 실패는 **prod 실행에서만** 드러난다(실제로 그렇게 드러났다).
    선언을 여기서 잠가 CI가 먼저 잡게 한다.
    """

    entry = await find_provider_dataset_catalog_entry(
        seed_session,
        provider=_C7_PROVIDER,
        dataset_key=_C7_DATASET_KEY,
    )
    assert entry is not None, f"{_C7_PROVIDER}/{_C7_DATASET_KEY} 시드가 없다"
    assert _C7_SYNC_SCOPE in entry.refresh_scopes, (
        f"C7 인수 scope 선언이 없다 — 0224_c7_external_system_scope 확인 "
        f"(선언된 scope: {entry.refresh_scopes})"
    )
    # capability(=API의 allowed_sync_scopes)까지 나와야 화면·서버가 같은 집합을 본다.
    capability = _scope_refresh_capability(entry)
    assert _C7_SYNC_SCOPE in capability.allowed_sync_scopes
    # 선언이 늘어도 기본 scope는 여전히 target_grids다 — exact target은 좁힌 것이지
    # 기본이 아니다.
    assert entry.default_refresh_scope == "target_grids"


async def test_non_dagster_operation_allowlist_is_exactly_the_seed_difference(
    seed_session: AsyncSession,
) -> None:
    """제외 목록이 실제 차집합보다 넓지도 좁지도 않다.

    넓으면 사라진 operation을 계속 허용하고, 좁으면 위 게이트가 통과하지 못한다.
    """

    bindings = await list_active_refresh_operation_bindings(seed_session)
    active_keys = {binding.operation_key for binding in bindings}
    handler_keys = set(feature_operation_handler_keys())

    assert active_keys - handler_keys == _NON_DAGSTER_REFRESH_OPERATION_KEYS
    # handler에만 있는 key는 없어야 한다 — seed가 정본이다.
    assert handler_keys - active_keys == set()


async def test_exact_set_gate_reports_missing_handler_alone(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
) -> None:
    """seed에 operation을 넣고 handler를 빼먹은 경우만 단독으로 만든다."""

    session, _ = axis_catalog
    handler_keys = (
        set(feature_operation_handler_keys())
        | _NON_DAGSTER_REFRESH_OPERATION_KEYS
        # probe dataset이 만든 활성 operation 중 이 축과 무관한 것은 handler가 있는
        # 것으로 취급한다 — missing 축을 하나로 고립시킨다.
        | {
            "axis_multi_scope_job",
            "axis_dataset_wide_only_job",
            "axis_external_only_job",
            "axis_wide_plus_external_wide_job",
            "axis_wide_plus_external_concierge_job",
        }
    )

    with pytest.raises(ActiveOperationHandlerDriftError) as raised:
        await assert_active_operation_handler_exact_set(
            session,
            handler_operation_keys=handler_keys,
        )

    assert raised.value.missing_handler_operation_keys == {"axis_no_scope_rows_job"}
    # stale이 비어 있는데도 raise 돼야 한다 — ``if missing or stale``의 missing 항.
    assert raised.value.stale_handler_operation_keys == frozenset()


async def test_exact_set_gate_reports_stale_handler_alone(
    seed_session: AsyncSession,
) -> None:
    """제거된 operation의 handler가 남은 경우만 단독으로 만든다.

    유일했던 유닛 테스트는 missing과 stale을 **동시에** 만들어, stale 분기를 지워도
    통과했다(변이 실증). 그래서 두 축을 갈라 둔다.
    """

    with pytest.raises(ActiveOperationHandlerDriftError) as raised:
        await assert_active_operation_handler_exact_set(
            seed_session,
            handler_operation_keys=(
                set(feature_operation_handler_keys())
                | _NON_DAGSTER_REFRESH_OPERATION_KEYS
                | {"removed_operation_job"}
            ),
        )

    assert raised.value.missing_handler_operation_keys == frozenset()
    assert raised.value.stale_handler_operation_keys == {"removed_operation_job"}


async def test_exact_set_gate_is_immune_to_operations_committed_by_other_tests(
    migrated_engine: AsyncEngine,
    seed_session: AsyncSession,
) -> None:
    """형제 테스트가 공유 DB에 commit해도 이 게이트의 판정이 변하지 않는다.

    형제 파일이 ``migrated_engine``(session-scope 공유 DB)에 handler 없는 활성 refresh
    operation을 commit하는 상황을 그대로 재현한다. 세 가지를 한 테스트에서 함께
    단언해야 공허하지 않다.

    1. 오염이 공유 DB에 **실제로 보인다**(binding 목록에 나타난다).
    2. 그 공유 DB로 게이트를 돌리면 오염 때문에 **red다** — 이 파일이 전용 seed DB를
       쓰는 이유가 실재함을 보인다.
    3. 같은 순간 seed DB로 돌린 게이트는 **green이다**.

    이 성질이 깨지면 CI의 ``pytest tests/integration``이 실행 순서에 따라 red가 된다.
    """

    decoy_operation_key = "axis_shared_db_pollution_job"
    handler_keys = set(feature_operation_handler_keys()) | _NON_DAGSTER_REFRESH_OPERATION_KEYS

    async with migrated_engine.begin() as connection:
        decoy_dataset_id = int(
            (
                await connection.execute(
                    text(_INSERT_DATASET_SQL),
                    {
                        "provider": _PROBE_PROVIDER,
                        "dataset_key": "axis_shared_db_pollution",
                        "display_name": "probe shared-db pollution",
                        "capabilities": _CAPABILITIES,
                    },
                )
            ).scalar_one()
        )
        await connection.execute(
            text(_INSERT_OPERATION_SQL),
            {
                "provider_dataset_id": decoy_dataset_id,
                "operation_key": decoy_operation_key,
                "operation_kind": "refresh",
                "is_enabled": True,
                "config": "{}",
            },
        )

    try:
        async with AsyncSession(migrated_engine, expire_on_commit=False) as shared_session:
            shared_bindings = await list_active_refresh_operation_bindings(shared_session)
            assert decoy_operation_key in {
                binding.operation_key for binding in shared_bindings
            }, "공유 DB 오염이 재현되지 않았다 — 이 테스트는 아무것도 증명하지 못한다"

            with pytest.raises(ActiveOperationHandlerDriftError) as raised:
                await assert_active_operation_handler_exact_set(
                    shared_session,
                    handler_operation_keys=handler_keys,
                )
            assert decoy_operation_key in raised.value.missing_handler_operation_keys

        verified = await assert_active_operation_handler_exact_set(
            seed_session,
            handler_operation_keys=handler_keys,
        )
        assert decoy_operation_key not in verified
    finally:
        async with migrated_engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM provider_sync.provider_dataset_operations "
                    "WHERE provider_dataset_id = :provider_dataset_id"
                ),
                {"provider_dataset_id": decoy_dataset_id},
            )
            await connection.execute(
                text(
                    "DELETE FROM provider_sync.provider_datasets "
                    "WHERE provider_dataset_id = :provider_dataset_id"
                ),
                {"provider_dataset_id": decoy_dataset_id},
            )


# ---------------------------------------------------------------------------
# BLOCKER 회귀 — 경계상태가 있어도 ``GET /ops/datasets`` 그리드가 살아 있다.
# ---------------------------------------------------------------------------


def _empty_schedule_payload() -> dict[str, object]:
    return {
        "data": {
            "repositoriesOrError": {
                "__typename": "RepositoryConnection",
                "nodes": [{"schedules": []}],
            }
        }
    }


@asynccontextmanager
async def _seeded_ops_api(
    seed_engine: AsyncEngine,
) -> AsyncIterator[tuple[httpx.AsyncClient, AsyncSession, dict[str, int]]]:
    """probe 카탈로그를 심은 트랜잭션 안에서 ops API 클라이언트를 연다.

    요청 의존성으로 **같은 세션**을 넘긴다 — 응답이 본 상태와 이 컨텍스트 안에서 돌리는
    SQL이 본 상태가 같아야 "응답이 자기모순하지 않는다"를 DB 사실과 대조할 수 있다.
    종료 시 rollback이라 seed DB는 그대로다.
    """
    async with seed_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            ids = await _seed_axis_datasets(session)

            app = create_app(
                ApiSettings(
                    _env_file=None,
                    debug_routes_enabled=False,
                    features_routes_enabled=False,
                    admin_routes_enabled=False,
                    ops_routes_enabled=True,
                    api_call_log_enabled=False,
                    prometheus_metrics_enabled=False,
                    admin_proxy_secret=None,
                    dagster_url="http://127.0.0.1:12702",
                    dagster_graphql_url=None,
                    dagster_allowed_hosts=["127.0.0.1"],
                )
            )

            async def _request_session() -> AsyncIterator[AsyncSession]:
                yield session

            app.dependency_overrides[get_session] = _request_session

            def _dagster(_request: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json=_empty_schedule_payload())

            async with httpx.AsyncClient(
                transport=httpx.MockTransport(_dagster)
            ) as dagster_client:
                app.state.dagster_http_client = dagster_client
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://testserver",
                ) as client:
                    yield client, session, ids
        finally:
            await session.close()
            await transaction.rollback()


async def test_ops_datasets_grid_survives_schema_allowed_boundary_states(
    seed_engine: AsyncEngine,
) -> None:
    """상태 ①·②가 DB에 있어도 그리드 전체가 200이고 그 행들이 보인다.

    앞 판에서는 이 요청이 ``ValueError``로 500이었다 — 한 dataset의 scope 행이 지워지면
    운영자 화면 **전체**가 정지한다.
    """

    async with _seeded_ops_api(seed_engine) as (client, _session, ids):
        response = await client.get("/v1/ops/datasets")

    assert response.status_code == 200, response.text
    rows: list[Mapping[str, object]] = response.json()["data"]["items"]
    by_dataset_id: dict[int, list[Mapping[str, object]]] = {}
    for row in rows:
        by_dataset_id.setdefault(int(row["provider_dataset_id"]), []).append(row)

    # 상태 ① — scope 행이 없어도 행 자체는 사라지지 않는다(자리표시자).
    no_scope_rows = by_dataset_id[ids["axis_no_scope_rows"]]
    assert [
        (row["sync_scope"], row["operation_key"]) for row in no_scope_rows
    ] == [("dataset_wide", None)]
    no_scope_catalog = no_scope_rows[0]["catalog"]
    assert isinstance(no_scope_catalog, dict)
    # 결박할 membership이 없으므로 갱신 대상이 아니다.
    assert no_scope_catalog["is_refreshable"] is False
    assert no_scope_catalog["provider_state_default_scope"] == "dataset_wide"
    assert no_scope_catalog["scope_refresh"]["supported"] is False
    assert no_scope_catalog["scope_refresh"]["effect"] == "none"
    assert no_scope_catalog["scope_refresh"]["allowed_sync_scopes"] == []

    # 상태 ② — 선언된 external_system scope 행 그대로. DB가 그 triple을 받으므로
    # capability도 그 scope를 제출 가능으로 낸다(아래 자기모순 회귀가 그 동치를 못박는다).
    external_rows = by_dataset_id[ids["axis_external_only"]]
    assert [
        (row["sync_scope"], row["operation_key"]) for row in external_rows
    ] == [("external_system:pinvi", "axis_external_only_job")]
    external_catalog = external_rows[0]["catalog"]
    assert isinstance(external_catalog, dict)
    assert external_catalog["scope_refresh"]["effect"] == "sync_scope"
    assert external_catalog["scope_refresh"]["allowed_sync_scopes"] == [
        "external_system:pinvi"
    ]
    assert external_catalog["scope_refresh"]["default_sync_scope"] == (
        "external_system:pinvi"
    )

    # 정상 dataset은 그대로 보인다 — 그리드가 degrade 상태만 남기고 죽지 않았다.
    multi_rows = by_dataset_id[ids["axis_multi_scope"]]
    assert {
        (row["sync_scope"], row["operation_key"]) for row in multi_rows
    } == {
        ("dataset_wide", "axis_multi_scope_job"),
        ("target_grids", "axis_multi_scope_job"),
        ("external_system:pinvi", "axis_multi_scope_job"),
    }
    multi_catalog = multi_rows[0]["catalog"]
    assert isinstance(multi_catalog, dict)
    assert multi_catalog["scope_refresh"]["supported"] is True
    assert multi_catalog["scope_refresh"]["default_sync_scope"] == "target_grids"


# ---------------------------------------------------------------------------
# 자기모순 회귀 — 한 응답의 membership 행과 capability가 서로 어긋나지 않는다.
# ---------------------------------------------------------------------------

#: dataset이 활성일 때 서버가 실제로 받는 sync scope 집합.
#:
#: ``infra/feature_update_repo._ACTIVE_DATASET_MEMBERSHIPS_SQL``에서 "요청이 지목한
#: triple" join만 뺀 것이다 — 그 SQL이 ``POST /v1/ops/pipeline/requests``의 membership
#: 해석 정본이고, scope의 kind(``dataset_wide``/``target_grids``/``external_system:*``)를
#: 구분하지 않는다. 여기서 Python projection(``entry.refresh_scopes``)을 다시 부르지
#: 않는 이유는, 그러면 검사 대상과 기준이 같은 코드가 되어 아무것도 증명하지 못하기
#: 때문이다.
_DECLARED_REFRESH_SCOPE_SQL = """
SELECT DISTINCT scope.sync_scope
FROM provider_sync.provider_dataset_operations AS operation
JOIN provider_sync.provider_dataset_operation_scopes AS scope
  ON scope.provider_dataset_id = operation.provider_dataset_id
 AND scope.operation_key = operation.operation_key
 AND scope.operation_kind = operation.operation_kind
WHERE operation.provider_dataset_id = :provider_dataset_id
  AND operation.operation_kind = 'refresh'
  AND operation.is_enabled
"""

_DATASET_ACTIVE_SQL = """
SELECT
    dataset.is_active,
    EXISTS (
        SELECT 1
        FROM provider_sync.provider_dataset_operations AS operation
        WHERE operation.provider_dataset_id = dataset.provider_dataset_id
          AND operation.operation_kind = 'refresh'
          AND operation.is_enabled
    ) AS has_enabled_refresh_operation
FROM provider_sync.provider_datasets AS dataset
WHERE dataset.provider_dataset_id = :provider_dataset_id
"""


def _capability_submittable_scopes(capability: Mapping[str, Any]) -> frozenset[str]:
    """capability payload가 "제출할 수 있다"고 말하는 scope 집합.

    프론트 fail-closed 게이트(``frontend/src/api/datasets.ts``의
    ``resolveDatasetRefreshScope``)가 이 payload를 읽는 규칙 그대로다. 규칙이 갈라지면
    이 테스트는 화면이 실제로 내리는 판정을 검사하지 않는 셈이 된다.

    * ``effect="none"`` — 아무것도 제출할 수 없다.
    * ``effect="dataset_wide"`` — ``default_sync_scope`` 하나뿐이다. 그 게이트는
      ``allowed_sync_scopes``가 비어 있지 않으면 계약 모순으로 보고 막으므로, 여기서도
      그 모양을 함께 단언한다.
    * ``effect="sync_scope"`` — ``allowed_sync_scopes`` 전부.
    """
    effect = capability["effect"]
    if effect == "none":
        return frozenset()
    if effect == "dataset_wide":
        assert capability["allowed_sync_scopes"] == [], (
            "effect=dataset_wide인데 allowed_sync_scopes가 비어 있지 않다 — "
            "프론트 게이트가 계약 모순으로 읽어 갱신을 통째로 막는다"
        )
        assert capability["selector"] == "none"
        assert capability["supported"] is False
        return frozenset({str(capability["default_sync_scope"])})
    assert effect == "sync_scope", effect
    return frozenset(str(scope) for scope in capability["allowed_sync_scopes"])


async def _server_accepted_scopes(
    session: AsyncSession, *, provider_dataset_id: int
) -> tuple[frozenset[str], frozenset[str], bool, bool]:
    """(서버가 받는 scope, 선언된 scope, is_active, enabled refresh operation 유무)."""
    declared = frozenset(
        str(value)
        for value in (
            await session.execute(
                text(_DECLARED_REFRESH_SCOPE_SQL),
                {"provider_dataset_id": provider_dataset_id},
            )
        ).scalars()
    )
    row = (
        await session.execute(
            text(_DATASET_ACTIVE_SQL),
            {"provider_dataset_id": provider_dataset_id},
        )
    ).mappings().one()
    is_active = bool(row["is_active"])
    has_operation = bool(row["has_enabled_refresh_operation"])
    accepted = declared if is_active else frozenset()
    return accepted, declared, is_active, has_operation


async def test_grid_capability_never_contradicts_its_own_membership_rows(
    seed_engine: AsyncEngine,
) -> None:
    """``GET /v1/ops/datasets`` 한 응답 안에서 행과 capability가 서로 모순하지 않는다.

    성질(개별 케이스가 아니라 **모든 canonical 행**에 대해):

    1. 행의 ``sync_scope``가 그 행 capability의 제출 가능 집합에 있는 것과, DB가 그
       dataset의 그 scope로 요청을 받는 것이 **동치**다.
    2. capability의 제출 가능 집합은 DB가 받는 집합과 정확히 같다(넓지도 좁지도 않다).
    3. ``allowed_sync_scopes``에는 카탈로그가 선언하지 않은 값이 없다.
    4. 막는 쪽의 사유가 그 행에 대해 참이다.
       - ``effect="none"``이면 서버가 사유를 낸다. 그 문장은 실제 원인
         (비활성 / refresh operation 없음 / scope 선언 없음)과 일치해야 한다.
       - ``effect="dataset_wide"``의 "전체 dataset 단위로만 갱신합니다"는 그 dataset이
         받는 scope가 정말 ``dataset_wide`` 하나일 때만 참이다.
       - ``effect="sync_scope"``는 아무것도 막지 않으므로 서버 사유가 없다(``None``).
         거기서 막히는 행은 선언되지 않은 잔존 membership뿐이고, 그 사유는 클라이언트가
         ``allowed_sync_scopes``로 만든다.

    시드 dataset과 probe dataset을 **함께** 검사한다. probe는 스키마가 허용하지만
    시드에는 없는 조합(형제 operation이 ``dataset_wide``와 ``external_system:*``를 나눠
    선언, external 전용, scope 행 0개, 비활성)을 만들어 축을 연다.
    """

    async with _seeded_ops_api(seed_engine) as (client, session, ids):
        response = await client.get("/v1/ops/datasets")
        assert response.status_code == 200, response.text
        rows: list[Mapping[str, Any]] = response.json()["data"]["items"]

        canonical_rows = [row for row in rows if row["catalog"] is not None]
        assert canonical_rows, "canonical 행이 하나도 없다 — 이 테스트는 공허하다"

        accepted_by_dataset: dict[int, frozenset[str]] = {}
        checked_datasets: set[int] = set()
        for row in canonical_rows:
            provider_dataset_id = int(row["provider_dataset_id"])
            label = f"{row['provider']}/{row['dataset_key']}#{provider_dataset_id}"
            capability = row["catalog"]["scope_refresh"]
            submittable = _capability_submittable_scopes(capability)
            (
                accepted,
                declared,
                is_active,
                has_operation,
            ) = await _server_accepted_scopes(
                session, provider_dataset_id=provider_dataset_id
            )
            accepted_by_dataset[provider_dataset_id] = accepted
            checked_datasets.add(provider_dataset_id)

            # (2) 제출 가능 집합 == DB가 받는 집합.
            assert submittable == accepted, (
                f"{label}: capability가 제출 가능이라 말한 scope와 DB가 받는 scope가 "
                f"다르다 (capability={sorted(submittable)}, db={sorted(accepted)})"
            )
            # (1) 행 단위 동치. (2)에서 따라 나오지만, 어긋났을 때 **어느 행이** 모순인지
            # 실패 메시지에 남긴다 — 이 회귀의 목적이 그 행이다.
            row_scope = str(row["sync_scope"])
            assert (row_scope in submittable) == (row_scope in accepted), (
                f"{label}: 행 sync_scope={row_scope!r}의 capability 판정과 DB 판정이 "
                "다르다"
            )
            # (3) 없는 scope를 지어내지 않는다.
            assert frozenset(capability["allowed_sync_scopes"]) <= declared, (
                f"{label}: allowed_sync_scopes에 카탈로그가 선언하지 않은 값이 있다"
            )

            # (4) 막는 사유가 참이다.
            effect = capability["effect"]
            reason = capability["reason"]
            if effect == "none":
                assert isinstance(reason, str)
                assert reason, f"{label}: 제출 가능한 scope가 없는데 사유가 없다"
                expected_reason = (
                    "비활성 dataset이라 갱신할 수 없습니다."
                    if not is_active
                    else "이 dataset에는 실행 가능한 refresh runner가 없습니다."
                    if not has_operation
                    else "이 dataset의 refresh operation에 sync scope 선언이 없어 "
                    "걸 대상이 없습니다."
                )
                assert reason == expected_reason, (
                    f"{label}: 사유가 실제 원인과 다르다 "
                    f"(is_active={is_active}, has_operation={has_operation})"
                )
            elif effect == "dataset_wide":
                assert accepted == frozenset({"dataset_wide"}), (
                    f"{label}: '전체 dataset 단위로만 갱신합니다'라고 말했지만 DB는 "
                    f"{sorted(accepted)}를 받는다"
                )
                assert reason == "이 dataset은 전체 dataset 단위로만 갱신합니다."
            else:
                assert reason is None, (
                    f"{label}: 아무것도 막지 않는 capability에 사유가 실려 있다"
                )
                # 프론트 게이트는 default가 allowed 밖이면 계약 모순으로 막는다.
                assert capability["default_sync_scope"] in capability[
                    "allowed_sync_scopes"
                ], f"{label}: default_sync_scope가 allowed_sync_scopes 밖이다"

        # --- 축이 실제로 열렸는지 확인한다(공허 방지) ---
        probe_ids = {value: key for key, value in ids.items()}
        assert set(probe_ids) <= checked_datasets, "probe dataset이 그리드에 없다"
        effects_by_probe = {
            probe_ids[int(row["provider_dataset_id"])]: row["catalog"]["scope_refresh"][
                "effect"
            ]
            for row in canonical_rows
            if int(row["provider_dataset_id"]) in probe_ids
        }
        assert effects_by_probe == {
            "axis_multi_scope": "sync_scope",
            "axis_dataset_wide_only": "dataset_wide",
            "axis_inactive": "none",
            "axis_no_scope_rows": "none",
            "axis_external_only": "sync_scope",
            "axis_dataset_wide_plus_external": "sync_scope",
            "axis_preview_not_fixture": "none",
        }
        # B-1 재현 축: 형제 operation이 ``dataset_wide``와 ``external_system:*``를 나눠
        # 선언한 dataset. 그리드가 두 행을 내고, 둘 다 제출 가능해야 한다 —
        # ``target_grids``가 없다는 이유로 capability를 접던 앞 판은
        # ``external_system:concierge`` 행에 "전체 dataset 단위로만 갱신합니다"라는
        # 거짓 사유를 붙였다.
        split_rows = [
            row
            for row in canonical_rows
            if int(row["provider_dataset_id"]) == ids["axis_dataset_wide_plus_external"]
        ]
        assert {
            (row["sync_scope"], row["operation_key"]) for row in split_rows
        } == {
            ("dataset_wide", "axis_wide_plus_external_wide_job"),
            ("external_system:concierge", "axis_wide_plus_external_concierge_job"),
        }
        split_capability = split_rows[0]["catalog"]["scope_refresh"]
        assert _capability_submittable_scopes(split_capability) == {
            "dataset_wide",
            "external_system:concierge",
        }
        assert accepted_by_dataset[ids["axis_dataset_wide_plus_external"]] == {
            "dataset_wide",
            "external_system:concierge",
        }
        # 막히는 쪽도 실재해야 대칭이 검사된다.
        assert accepted_by_dataset[ids["axis_inactive"]] == frozenset()
        assert accepted_by_dataset[ids["axis_no_scope_rows"]] == frozenset()


async def test_dataset_detail_capability_allows_the_membership_it_was_opened_with(
    seed_engine: AsyncEngine,
) -> None:
    """상세 응답도 자기가 연 membership을 자기 capability로 막지 않는다.

    '지금 갱신' 패널은 그리드가 아니라 **상세** 응답의 ``catalog.scope_refresh``와 열려
    있는 ``sync_scope``로 판정한다(``datasets-client.tsx`` ``RefreshNowSection``).
    그리드만 고치면 이 경로는 그대로 거짓 사유를 낸다.

    형제 operation이 scope를 나눠 선언한 dataset의 **양쪽 membership**을 각각 열어,
    자기 scope가 capability의 제출 가능 집합에 있는지 본다.
    """

    async with _seeded_ops_api(seed_engine) as (client, session, ids):
        provider_dataset_id = ids["axis_dataset_wide_plus_external"]
        accepted, _declared, _is_active, _has_operation = await _server_accepted_scopes(
            session, provider_dataset_id=provider_dataset_id
        )
        assert accepted == {"dataset_wide", "external_system:concierge"}

        for sync_scope, operation_key in (
            ("dataset_wide", "axis_wide_plus_external_wide_job"),
            ("external_system:concierge", "axis_wide_plus_external_concierge_job"),
        ):
            response = await client.get(
                f"/v1/ops/datasets/{provider_dataset_id}",
                params={"sync_scope": sync_scope, "operation_key": operation_key},
            )
            assert response.status_code == 200, response.text
            data = response.json()["data"]
            assert [
                (scope["sync_scope"], scope["operation_key"])
                for scope in data["scopes"]
            ] == [(sync_scope, operation_key)]
            capability = data["catalog"]["scope_refresh"]
            assert sync_scope in _capability_submittable_scopes(capability), (
                f"상세가 연 membership({sync_scope}/{operation_key})을 그 상세의 "
                f"capability가 막는다: {capability}"
            )

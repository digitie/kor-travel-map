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

이 파일은 ``migrated_engine``(conftest.py, session-scope 공유 DB)을 쓰지 않고
**전용 database**를 하나 더 만들어 거기에만 alembic head를 적용한다(``seed_engine``).
아래 게이트들이 카탈로그의 **전역** 성질을 단언하는데, 공유 DB에는 형제 테스트가
commit한 행이 그대로 남아 결과가 실행 순서에 매이기 때문이다. 실측:
``pytest tests/integration/test_offline_upload_load.py tests/integration/test_provider_catalog.py``
= ``4 failed, 35 passed``(형제가 commit한 ``offline_fixture_offline_{csv,jsonl}_refresh``가
handler 없는 활성 refresh operation으로 잡힌다), 같은 파일 단독 실행 = ``14 passed``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any
from uuid import uuid4

import httpx
import pytest
from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.ops_dataset_service import (
    _catalog_info,
    _catalog_state_memberships,
)
from kortravelmap.api.provider_catalog import (
    ActiveOperationHandlerDriftError,
    ProviderDatasetCatalogEntry,
    assert_active_operation_handler_exact_set,
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
    """
    import asyncio
    from pathlib import Path

    from alembic.config import Config
    from sqlalchemy import event
    from sqlalchemy.engine import make_url

    from alembic import command
    from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

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
    cfg.set_main_option("sqlalchemy.url", seed_dsn)
    await asyncio.to_thread(command.upgrade, cfg, "head")

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
        "expected_reason",
        "expected_memberships",
    ),
    [
        # 상태 ① — scope 행 0개. 결박할 membership이 없으므로 갱신 대상이 아니다.
        (
            "axis_no_scope_rows",
            (),
            False,
            "이 dataset의 refresh operation에 sync scope 선언이 없어 걸 대상이 없습니다.",
            (("dataset_wide", None),),
        ),
        # 상태 ② — external_system 전용. membership은 실재하는 triple 그대로다.
        (
            "axis_external_only",
            ("external_system:pinvi",),
            True,
            "이 dataset의 refresh operation에 canonical sync scope"
            "(dataset_wide/target_grids) 선언이 없습니다.",
            (("external_system:pinvi", "axis_external_only_job"),),
        ),
    ],
)
async def test_refreshable_dataset_without_declared_default_scope_degrades(
    axis_catalog: tuple[AsyncSession, dict[str, int]],
    dataset_key: str,
    expected_scopes: tuple[str, ...],
    expected_is_refreshable: bool,
    expected_reason: str,
    expected_memberships: tuple[tuple[str, str | None], ...],
) -> None:
    """스키마 허용 경계상태 2종에서 카탈로그 projection이 죽지 않는다.

    앞 판은 ``default_refresh_scope``가 ``ValueError``였고 ``_catalog_info``가
    ``is_refreshable``인 행마다 무조건 그것을 읽었다 — 두 상태 중 하나라도 DB에 있으면
    ``/ops/datasets`` 그리드 루프 전체가 500이었다.

    두 상태 모두 ``effect="none"``이다. 그 값이 없던 앞 판은 정상 dataset-wide
    capability와 ``reason`` 문자열 하나만 다른 payload를 냈고, 프론트 게이트
    ``resolveDatasetRefreshScope``가 그 payload에 ``{allowed: true}``를 돌려줬다
    (``frontend/src/api/datasets.test.ts``가 양쪽 반환값을 함께 못박는다).
    """

    session, _ = axis_catalog
    entry = _probe_entries(await list_provider_dataset_catalog(session))[dataset_key]

    assert entry.is_refreshable is expected_is_refreshable
    assert entry.refresh_scopes == expected_scopes
    assert entry.declares_default_refresh_scope is False
    assert entry.default_refresh_scope == "dataset_wide"

    info = _catalog_info(entry)
    assert info.is_refreshable is expected_is_refreshable
    assert info.provider_state_default_scope == "dataset_wide"
    # degrade는 행 단위로 드러난다 — "전체 dataset 단위로만 갱신합니다"가 아니다.
    assert info.scope_refresh.supported is False
    # 정상 dataset-wide capability와 **구분 가능해야** 한다. 이 축이 프론트 게이트가
    # 읽는 유일한 축이다(``reason``은 허용 경로에서 읽지 않는다).
    assert info.scope_refresh.effect == "none"
    assert info.scope_refresh.reason == expected_reason
    # degrade가 실행 허용 목록을 넓히지 않는다 — 선언된 것만 그대로 실린다.
    assert info.scope_refresh.allowed_sync_scopes == list(expected_scopes)
    assert "dataset_wide" not in info.scope_refresh.allowed_sync_scopes

    assert _catalog_state_memberships(entry) == expected_memberships


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


async def test_ops_datasets_grid_survives_schema_allowed_boundary_states(
    seed_engine: AsyncEngine,
) -> None:
    """상태 ①·②가 DB에 있어도 그리드 전체가 200이고 그 행들이 보인다.

    앞 판에서는 이 요청이 ``ValueError``로 500이었다 — 한 dataset의 scope 행이 지워지면
    운영자 화면 **전체**가 정지한다. 요청은 seed를 커밋하지 않도록 테스트가 연 트랜잭션에
    묶인 세션 하나를 그대로 쓴다(끝에서 rollback).
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
                    response = await client.get("/v1/ops/datasets")
        finally:
            await session.close()
            await transaction.rollback()

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

    # 상태 ② — 선언된 external_system scope 행 그대로.
    external_rows = by_dataset_id[ids["axis_external_only"]]
    assert [
        (row["sync_scope"], row["operation_key"]) for row in external_rows
    ] == [("external_system:pinvi", "axis_external_only_job")]
    external_catalog = external_rows[0]["catalog"]
    assert isinstance(external_catalog, dict)
    assert external_catalog["scope_refresh"]["effect"] == "none"
    assert external_catalog["scope_refresh"]["allowed_sync_scopes"] == [
        "external_system:pinvi"
    ]

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

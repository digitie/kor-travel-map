"""``/ops/datasets`` refresh-policy 실세션 transaction 회귀 (#678).

unit 테스트의 ``_FakeSession``은 SQLAlchemy autobegin("SELECT가 시작한
transaction 위에서 ``session.begin()`` 금지")을 흉내내지 못해, 존재 검증
SELECT를 begin 밖에서 수행하던 결함(모든 잔존 조합 PUT이 500
``InvalidRequestError``)을 잡지 못했다. 본 파일은 프로덕션 ``get_session``과
동일한 **fresh ``AsyncSession``**(transaction 미시작)으로 라우터 핸들러를 직접
호출해, canonical catalog mutation과 orphan mutation 금지가 같은 transaction
경계에서 성립함을 실 DB로 고정한다.

시드 데이터는 fresh 세션에서 보이도록 **commit**하므로, 테스트 전용 provider
이름을 쓰고 finally에서 반드시 정리한다(공유 migrated_engine 오염 방지).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.provider_refresh_policy_repo import (
    get_provider_refresh_policy,
    upsert_provider_refresh_policy,
)
from kortravelmap.infra.sync_state_repo import record_sync_success

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


def _policy_body() -> Any:
    from kortravelmap.api.provider_refresh_schema import (
        ProviderRefreshPolicyUpsertRequest,
    )

    return ProviderRefreshPolicyUpsertRequest(
        source_kind="manual",
        targeted_policy="allow_targeted",
        max_concurrent=2,
        enabled=False,
        stale_after_minutes=90,
    )


async def _put_refresh_policy(
    engine: AsyncEngine, *, provider: str, dataset_key: str
) -> Any:
    """프로덕션 ``get_session``과 동일한 fresh 세션으로 service를 호출한다."""
    from kortravelmap.api.ops_dataset_service import upsert_dataset_refresh_policy

    async with AsyncSession(engine, expire_on_commit=False) as session:
        return await upsert_dataset_refresh_policy(
            session,
            provider=provider,
            dataset_key=dataset_key,
            body=_policy_body(),
        )


async def _cleanup(engine: AsyncEngine, provider: str) -> None:
    async with AsyncSession(engine) as session, session.begin():
        await session.execute(
            text("DELETE FROM ops.provider_refresh_policies WHERE provider = :p"),
            {"p": provider},
        )
        await session.execute(
            text("DELETE FROM provider_sync.provider_sync_state WHERE provider = :p"),
            {"p": provider},
        )


async def test_put_leftover_sync_state_combo_is_orphan_and_forbidden(
    migrated_engine: AsyncEngine,
) -> None:
    """카탈로그에 없고 sync state만 남은 조합은 이유가 있는 409 대상이다."""
    from kortravelmap.api.ops_dataset_service import OrphanMutationDisabledError

    provider = "it-legacy-provider"
    dataset_key = "it_legacy_dataset"
    try:
        async with AsyncSession(migrated_engine) as seed, seed.begin():
            await record_sync_success(
                seed, provider=provider, dataset_key=dataset_key, cursor={}
            )

        with pytest.raises(OrphanMutationDisabledError) as excinfo:
            await _put_refresh_policy(
                migrated_engine, provider=provider, dataset_key=dataset_key
            )
        assert excinfo.value.mutation_disabled_reason == "catalog_missing_with_sync_state"
        async with AsyncSession(migrated_engine) as verify:
            saved = await get_provider_refresh_policy(
                verify, provider=provider, dataset_key=dataset_key
            )
        assert saved is None
    finally:
        await _cleanup(migrated_engine, provider)


async def test_put_policy_only_combo_is_orphan_and_forbidden(
    migrated_engine: AsyncEngine,
) -> None:
    """policy-only 잔존 row도 조회는 가능하지만 mutation은 금지한다."""
    from kortravelmap.api.ops_dataset_service import OrphanMutationDisabledError

    provider = "it-policy-only-provider"
    dataset_key = "it_policy_only_dataset"
    try:
        async with AsyncSession(migrated_engine) as seed, seed.begin():
            await upsert_provider_refresh_policy(
                seed,
                provider=provider,
                dataset_key=dataset_key,
                source_kind="manual",
                enabled=True,
            )

        with pytest.raises(OrphanMutationDisabledError) as excinfo:
            await _put_refresh_policy(
                migrated_engine, provider=provider, dataset_key=dataset_key
            )
        assert excinfo.value.mutation_disabled_reason == "catalog_missing_with_policy"
        async with AsyncSession(migrated_engine) as verify:
            saved = await get_provider_refresh_policy(
                verify, provider=provider, dataset_key=dataset_key
            )
        assert saved is not None
        assert saved.enabled is True
        assert saved.max_concurrent == 1
    finally:
        await _cleanup(migrated_engine, provider)


async def test_put_unknown_combo_404_creates_no_policy_row(
    migrated_engine: AsyncEngine,
) -> None:
    """어디에도 없는 조합은 404 + transaction 롤백(유령 policy row 없음)."""
    provider = "it-ghost-provider"
    dataset_key = "it_ghost_dataset"
    try:
        from kortravelmap.api.ops_dataset_service import DatasetNotFoundError

        with pytest.raises(DatasetNotFoundError):
            await _put_refresh_policy(
                migrated_engine, provider=provider, dataset_key=dataset_key
            )

        async with AsyncSession(migrated_engine) as verify:
            saved = await get_provider_refresh_policy(
                verify, provider=provider, dataset_key=dataset_key
            )
        assert saved is None
    finally:
        await _cleanup(migrated_engine, provider)


async def test_put_catalog_combo_succeeds_on_fresh_session(
    migrated_engine: AsyncEngine,
) -> None:
    """카탈로그 조합(정상 경로)도 fresh 세션에서 한 transaction으로 성립한다."""
    provider = "python-mois-api"
    dataset_key = "mois_license_features_bulk"
    try:
        saved_response = await _put_refresh_policy(
            migrated_engine, provider=provider, dataset_key=dataset_key
        )

        assert saved_response.provider == provider
        assert saved_response.enabled is False
        async with AsyncSession(migrated_engine) as verify:
            saved = await get_provider_refresh_policy(
                verify, provider=provider, dataset_key=dataset_key
            )
        assert saved is not None
        assert saved.targeted_policy == "allow_targeted"
        assert saved.stale_after_minutes == 90
    finally:
        await _cleanup(migrated_engine, provider)

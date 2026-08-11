"""``infra.feature_operation_repo``의 identity triple 축 회귀 (T-VN-33, ADR-088).

이 파일이 고정하는 것은 **``operation_key`` 축**이다. 같은 SQL/함수의
``sync_scope`` 축은 KMA 격자 dataset(한 operation이 ``dataset_wide``와
``target_grids`` 두 member를 갖는다)이 이미 밟고 있지만, ``operation_key`` 축은
형제 operation을 실제로 seed하는 fixture가 저장소에 없어 무방비였다. 0091이 scope
PK를 pair에서 triple로 올린 명시적 목적이 그 형제 등록을 허용하는 것이므로,
여기서는 형제를 **직접 seed해** 축을 만든 뒤 검증한다.

``tests/integration/test_canonical_provider_operations.py``와 분리한 이유는 그
파일이 Dagster 쪽 회귀와 함께 쓰이고 있어 동시 편집이 겹치기 때문이다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from sqlalchemy import text

from kortravelmap.core.feature_operation import (
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationMembership,
)
from kortravelmap.infra.feature_operation_repo import (
    ensure_dagster_feature_operation,
    finish_dagster_feature_membership,
    list_feature_operation_memberships,
    resolve_feature_operation_dataset_membership,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from tests.integration._membership_seed import (
    MULTI_MEMBER_OPERATION,
    SINGLE_MEMBER_OPERATION,
    memberships_for_operation,
)

pytestmark = pytest.mark.integration

#: 형제 operation은 시드에 없다(실측: 한 (dataset, sync_scope)에 refresh operation이
#: 둘인 조합 0건). 스키마는 허용하므로 테스트가 직접 만든다.
_SIBLING_OPERATION_KEY = "feature_operation_sibling_probe_job"

_KMA_PROVIDER = "python-kma-api"
_KMA_DATASET = "kma_short_forecast"
_KMA_OPERATION = "feature_weather_kma_short_forecast_job"


async def _seed_sibling_operation(
    session: AsyncSession,
    membership: ProviderDatasetOperationMembership,
) -> ProviderDatasetOperationMembership:
    """같은 ``(provider_dataset_id, sync_scope)``에 형제 refresh operation을 붙인다."""
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operations
                (provider_dataset_id, operation_key, operation_kind, is_enabled)
            VALUES (:provider_dataset_id, :operation_key, 'refresh', true)
            """
        ),
        {
            "provider_dataset_id": membership.provider_dataset_id,
            "operation_key": _SIBLING_OPERATION_KEY,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO provider_sync.provider_dataset_operation_scopes
                (provider_dataset_id, sync_scope, operation_key, operation_kind)
            VALUES (:provider_dataset_id, :sync_scope, :operation_key, 'refresh')
            """
        ),
        {
            "provider_dataset_id": membership.provider_dataset_id,
            "sync_scope": membership.sync_scope,
            "operation_key": _SIBLING_OPERATION_KEY,
        },
    )
    await session.flush()
    return ProviderDatasetOperationMembership(
        provider_dataset_id=membership.provider_dataset_id,
        sync_scope=membership.sync_scope,
        operation_key=_SIBLING_OPERATION_KEY,
    )


async def _ensure_run(
    session: AsyncSession,
    *,
    operation_key: str,
    memberships: tuple[ProviderDatasetOperationMembership, ...],
) -> str:
    run_id = f"tvn33-sibling-{uuid4()}"
    created_at = datetime(2026, 8, 7, tzinfo=UTC)
    await ensure_dagster_feature_operation(
        session,
        dagster_run_id=run_id,
        trigger_kind="manual",
        selected_memberships=memberships,
        operation_key=operation_key,
        engine_created_at=created_at,
        engine_started_at=created_at,
        observed_status="STARTED",
    )
    return run_id


async def _member_statuses(
    session: AsyncSession, run_id: str
) -> dict[tuple[int, str, str], str]:
    rows = (
        await session.execute(
            text(
                """
                SELECT member.provider_dataset_id, member.sync_scope,
                       member.operation_key, job.status
                FROM ops.import_jobs AS job
                JOIN ops.import_job_datasets AS member ON member.job_id = job.job_id
                JOIN ops.import_jobs AS root ON root.job_id = job.parent_job_id
                WHERE root.dagster_run_id = :run_id
                """
            ),
            {"run_id": run_id},
        )
    ).all()
    return {
        (int(row.provider_dataset_id), str(row.sync_scope), str(row.operation_key)): str(
            row.status
        )
        for row in rows
    }


async def test_run_selection_must_use_the_root_operation_key(
    migrated_session: AsyncSession,
) -> None:
    """root operation과 다른 operation의 member를 한 run에 섞을 수 없다.

    이 검사가 없으면 A run이 B operation의 member 행을 만들고, 이후 A의 완료
    처리가 B의 실행 이력을 종결시킨다. ``_FINISH_MEMBERSHIP_SQL``이 이런 run을
    본 적 없는 이유가 바로 이 게이트다.
    """
    single = (
        await memberships_for_operation(
            migrated_session, operation_key=SINGLE_MEMBER_OPERATION
        )
    )[0]
    foreign = (
        await memberships_for_operation(
            migrated_session, operation_key=MULTI_MEMBER_OPERATION
        )
    )[0]
    assert foreign.operation_key != single.operation_key

    with pytest.raises(ValueError, match="selected_memberships must use the root operation_key"):
        await _ensure_run(
            migrated_session,
            operation_key=single.operation_key,
            memberships=(single, foreign),
        )

    with pytest.raises(ValueError, match="selected_memberships must use the root operation_key"):
        await _ensure_run(
            migrated_session,
            operation_key=single.operation_key,
            memberships=(foreign,),
        )


async def test_finish_rejects_a_sibling_operation_member_of_the_same_scope(
    migrated_session: AsyncSession,
) -> None:
    """형제 operation의 member를 지목한 완료 요청은 거부된다.

    triple 중 ``provider_dataset_id``·``sync_scope``가 같고 ``operation_key``만
    다른 membership이 실행 완료 경계에서 통과하면, A operation run이 B operation의
    실행 단위를 종결한 것으로 보인다.
    """
    single = (
        await memberships_for_operation(
            migrated_session, operation_key=SINGLE_MEMBER_OPERATION
        )
    )[0]
    sibling = await _seed_sibling_operation(migrated_session, single)
    assert (sibling.provider_dataset_id, sibling.sync_scope) == (
        single.provider_dataset_id,
        single.sync_scope,
    )

    run_id = await _ensure_run(
        migrated_session,
        operation_key=single.operation_key,
        memberships=(single,),
    )

    with pytest.raises(FeatureOperationInvariantConflict) as excinfo:
        await finish_dagster_feature_membership(
            migrated_session,
            dagster_run_id=run_id,
            membership=sibling,
        )
    assert excinfo.value.details["operation_key"] == _SIBLING_OPERATION_KEY
    assert excinfo.value.details["provider_dataset_id"] == single.provider_dataset_id
    assert excinfo.value.details["sync_scope"] == single.sync_scope

    # 거부는 partial mutation을 남기지 않는다 — 자기 member는 아직 running이다.
    statuses = await _member_statuses(migrated_session, run_id)
    assert statuses == {
        (single.provider_dataset_id, single.sync_scope, single.operation_key): "running"
    }


async def test_finish_closes_only_the_running_operations_own_member(
    migrated_session: AsyncSession,
) -> None:
    """형제 operation이 각자 run을 돌 때 한쪽 완료가 다른 쪽을 건드리지 않는다."""
    single = (
        await memberships_for_operation(
            migrated_session, operation_key=SINGLE_MEMBER_OPERATION
        )
    )[0]
    sibling = await _seed_sibling_operation(migrated_session, single)

    seed_run = await _ensure_run(
        migrated_session,
        operation_key=single.operation_key,
        memberships=(single,),
    )
    sibling_run = await _ensure_run(
        migrated_session,
        operation_key=_SIBLING_OPERATION_KEY,
        memberships=(sibling,),
    )

    finished = await finish_dagster_feature_membership(
        migrated_session,
        dagster_run_id=seed_run,
        membership=single,
    )

    assert finished.outcome == "applied"
    assert await _member_statuses(migrated_session, seed_run) == {
        (single.provider_dataset_id, single.sync_scope, single.operation_key): "done"
    }
    assert await _member_statuses(migrated_session, sibling_run) == {
        (sibling.provider_dataset_id, sibling.sync_scope, _SIBLING_OPERATION_KEY): "running"
    }


@pytest.mark.parametrize("axis", ["dataset", "operation"])
async def test_membership_snapshot_drops_deactivated_catalog_rows(
    migrated_session: AsyncSession,
    axis: str,
) -> None:
    """비활성 dataset·disabled operation은 run selection에 들어오지 않는다.

    이 필터가 사라지면 schedule dispatch가 비활성 member까지 얼려 실행하고,
    이후 sync-state write가 DB 가드에 걸려 run 전체가 죽는다.
    """
    memberships = await memberships_for_operation(
        migrated_session, operation_key=MULTI_MEMBER_OPERATION
    )
    assert len(memberships) > 1
    victim = memberships[0]

    if axis == "dataset":
        statement = """
            UPDATE provider_sync.provider_datasets
            SET is_active = false
            WHERE provider_dataset_id = :provider_dataset_id
        """
        params: dict[str, object] = {"provider_dataset_id": victim.provider_dataset_id}
    else:
        statement = """
            UPDATE provider_sync.provider_dataset_operations
            SET is_enabled = false
            WHERE provider_dataset_id = :provider_dataset_id
              AND operation_key = :operation_key
              AND operation_kind = 'refresh'
        """
        params = {
            "provider_dataset_id": victim.provider_dataset_id,
            "operation_key": victim.operation_key,
        }
    result = await migrated_session.execute(text(statement), params)
    assert result.rowcount == 1
    await migrated_session.flush()

    remaining = await list_feature_operation_memberships(
        migrated_session, operation_key=MULTI_MEMBER_OPERATION
    )

    assert victim not in remaining
    assert set(remaining) == set(memberships) - {victim}


async def test_runtime_dataset_lookup_requires_exactly_one_membership(
    migrated_session: AsyncSession,
) -> None:
    """``sync_scope``를 빼면 KMA 격자 dataset은 2건으로 갈려 exact lookup이 깨진다.

    ``!= 1``을 ``< 1``로 되돌리면 2건 중 첫 행을 임의로 골라 조용히 진행한다 —
    provider callback이 어느 scope의 cursor를 미는지 알 수 없게 된다.
    """
    with pytest.raises(FeatureOperationInvariantConflict) as ambiguous:
        await resolve_feature_operation_dataset_membership(
            migrated_session,
            operation_key=_KMA_OPERATION,
            provider=_KMA_PROVIDER,
            dataset_key=_KMA_DATASET,
        )
    assert ambiguous.value.details["match_count"] == 2
    assert ambiguous.value.details["sync_scope"] is None

    resolved = await resolve_feature_operation_dataset_membership(
        migrated_session,
        operation_key=_KMA_OPERATION,
        provider=_KMA_PROVIDER,
        dataset_key=_KMA_DATASET,
        sync_scope="target_grids",
    )
    assert resolved.sync_scope == "target_grids"
    assert resolved.operation_key == _KMA_OPERATION

    with pytest.raises(FeatureOperationInvariantConflict) as missing:
        await resolve_feature_operation_dataset_membership(
            migrated_session,
            operation_key=_KMA_OPERATION,
            provider=_KMA_PROVIDER,
            dataset_key=_KMA_DATASET,
            sync_scope="external_system:pinvi",
        )
    assert missing.value.details["match_count"] == 0


async def test_runtime_dataset_lookup_skips_disabled_sibling_operation(
    migrated_session: AsyncSession,
) -> None:
    """형제 operation이 disabled면 후보에서 빠져 exact lookup이 다시 성립한다."""
    single = (
        await memberships_for_operation(
            migrated_session, operation_key=SINGLE_MEMBER_OPERATION
        )
    )[0]
    sibling = await _seed_sibling_operation(migrated_session, single)
    provider, dataset_key = (
        await migrated_session.execute(
            text(
                """
                SELECT provider, dataset_key
                FROM provider_sync.provider_datasets
                WHERE provider_dataset_id = :provider_dataset_id
                """
            ),
            {"provider_dataset_id": single.provider_dataset_id},
        )
    ).one()

    # 형제가 enabled인 동안에도 두 operation은 서로 다른 key라 각각 1건으로 떨어진다.
    assert (
        await resolve_feature_operation_dataset_membership(
            migrated_session,
            operation_key=_SIBLING_OPERATION_KEY,
            provider=provider,
            dataset_key=dataset_key,
        )
        == sibling
    )

    await migrated_session.execute(
        text(
            """
            UPDATE provider_sync.provider_dataset_operations
            SET is_enabled = false
            WHERE provider_dataset_id = :provider_dataset_id
              AND operation_key = :operation_key
            """
        ),
        {
            "provider_dataset_id": single.provider_dataset_id,
            "operation_key": _SIBLING_OPERATION_KEY,
        },
    )
    await migrated_session.flush()

    with pytest.raises(FeatureOperationInvariantConflict) as excinfo:
        await resolve_feature_operation_dataset_membership(
            migrated_session,
            operation_key=_SIBLING_OPERATION_KEY,
            provider=provider,
            dataset_key=dataset_key,
        )
    assert excinfo.value.details["match_count"] == 0

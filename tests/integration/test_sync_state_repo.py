"""``test_sync_state_repo`` — provider 증분 cursor 추적 (Step B, Sprint 4a).

``provider_sync.provider_sync_state``를 ``get`` / ``record_sync_success`` /
``record_sync_failure``로 UPSERT하며 cursor 전진·연속 실패 카운트를 검증한다.
``migrated_session``(rollback 격리)으로 commit 없이.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import NoResultFound

from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.infra.sync_state_repo import (
    get_sync_state,
    get_sync_state_for_operation_membership,
    list_sync_states,
    list_sync_states_by_dataset_id,
    record_sync_failure,
    record_sync_failure_for_operation_membership,
    record_sync_success,
    record_sync_success_for_operation_membership,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_P = "python-mois-api"
_D = "mois_license_features_history"
_O = "mois_license_incremental_update"

# ``dataset_wide``/``target_grids`` 두 scope가 모두 catalog에 등록된 유일한 계열.
_SCOPED_P = "python-kma-api"
_SCOPED_D = "kma_short_forecast"
_SCOPED_O = "feature_weather_kma_short_forecast_job"


async def test_get_returns_none_when_absent(migrated_session: AsyncSession) -> None:
    state = await get_sync_state(migrated_session, provider=_P, dataset_key=_D, operation_key=_O)
    assert state is None


async def test_record_success_inserts_and_advances(
    migrated_session: AsyncSession,
) -> None:
    s1 = await record_sync_success(
        migrated_session,
        provider=_P,
        dataset_key=_D,
        operation_key=_O,
        cursor={"last_modified_date": "2026-01-01"},
    )
    assert s1.cursor == {"last_modified_date": "2026-01-01"}
    assert s1.status == "active"
    assert s1.consecutive_failures == 0
    assert s1.last_success_at is not None

    # 재호출 — cursor 전진(UPSERT).
    s2 = await record_sync_success(
        migrated_session,
        provider=_P,
        dataset_key=_D,
        operation_key=_O,
        cursor={"last_modified_date": "2026-02-01"},
    )
    assert s2.cursor == {"last_modified_date": "2026-02-01"}

    got = await get_sync_state(migrated_session, provider=_P, dataset_key=_D, operation_key=_O)
    assert got is not None
    assert got.cursor == {"last_modified_date": "2026-02-01"}


async def test_record_failure_increments(migrated_session: AsyncSession) -> None:
    f1 = await record_sync_failure(migrated_session, provider=_P, dataset_key=_D, operation_key=_O)
    assert f1.consecutive_failures == 1
    assert f1.last_failure_at is not None
    # cursor는 미전진 — 신규 행이라 빈 dict.
    assert f1.cursor == {}

    f2 = await record_sync_failure(migrated_session, provider=_P, dataset_key=_D, operation_key=_O)
    assert f2.consecutive_failures == 2


async def test_success_resets_consecutive_failures(
    migrated_session: AsyncSession,
) -> None:
    await record_sync_failure(migrated_session, provider=_P, dataset_key=_D, operation_key=_O)
    await record_sync_failure(migrated_session, provider=_P, dataset_key=_D, operation_key=_O)
    s = await record_sync_success(
        migrated_session,
        provider=_P,
        dataset_key=_D,
        operation_key=_O,
        cursor={"last_modified_date": "2026-03-01"},
    )
    assert s.consecutive_failures == 0
    # 실패가 누적돼 있던 행에 성공이 cursor를 채운다.
    assert s.cursor == {"last_modified_date": "2026-03-01"}


async def test_distinct_sync_scope_independent(
    migrated_session: AsyncSession,
) -> None:
    """같은 dataset·operation이라도 ``sync_scope``가 다르면 별개 cursor 행이다.

    T-VN-33 이후 PK는 ``(provider_dataset_id, sync_scope, operation_key)``이고
    ``sync_scope``는 catalog에 등록된 값(``dataset_wide``/``target_grids``)만
    FK로 허용된다 — 임의 문자열은 더 이상 쓸 수 없다(ADR-088).
    """
    await record_sync_success(
        migrated_session,
        provider=_SCOPED_P,
        dataset_key=_SCOPED_D,
        operation_key=_SCOPED_O,
        sync_scope="dataset_wide",
        cursor={"last_modified_date": "2026-01-01"},
    )
    await record_sync_success(
        migrated_session,
        provider=_SCOPED_P,
        dataset_key=_SCOPED_D,
        operation_key=_SCOPED_O,
        sync_scope="target_grids",
        cursor={"last_modified_date": "2026-09-09"},
    )
    a = await get_sync_state(
        migrated_session,
        provider=_SCOPED_P,
        dataset_key=_SCOPED_D,
        operation_key=_SCOPED_O,
        sync_scope="dataset_wide",
    )
    b = await get_sync_state(
        migrated_session,
        provider=_SCOPED_P,
        dataset_key=_SCOPED_D,
        operation_key=_SCOPED_O,
        sync_scope="target_grids",
    )
    assert a is not None
    assert b is not None
    assert a.cursor == {"last_modified_date": "2026-01-01"}
    assert b.cursor == {"last_modified_date": "2026-09-09"}


# --------------------------------------------------------------------------- #
# active dataset / enabled operation 가드 (T-VN-33)
#
# 아래 회귀가 없으면 이 모듈의 SQL 4개(record success/failure × 자연키/membership)와
# ``_GET_FOR_OPERATION_MEMBERSHIP_SQL``에서 ``AND dataset.is_active AND
# operation.is_enabled``를 지워도 어떤 테스트도 실패하지 않는다 — 즉 비활성
# dataset·disabled operation에 cursor를 쓰는 경로가 열린다.
# --------------------------------------------------------------------------- #

_MEMBERSHIP_SQL = """
SELECT scope.provider_dataset_id, scope.sync_scope, scope.operation_key
FROM provider_sync.provider_dataset_operation_scopes AS scope
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = scope.provider_dataset_id
WHERE dataset.provider = :provider
  AND dataset.dataset_key = :dataset_key
  AND scope.operation_key = :operation_key
  AND scope.sync_scope = :sync_scope
  AND scope.operation_kind = 'refresh'
"""


async def _membership(
    session: AsyncSession,
    *,
    provider: str = _P,
    dataset_key: str = _D,
    operation_key: str = _O,
    sync_scope: str = "dataset_wide",
) -> ProviderDatasetOperationMembership:
    """시드에 실재하는 exact triple을 읽는다 — 없으면 ``.one()``이 죽는다."""
    row = (
        await session.execute(
            text(_MEMBERSHIP_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "operation_key": operation_key,
                "sync_scope": sync_scope,
            },
        )
    ).one()
    return ProviderDatasetOperationMembership(
        provider_dataset_id=int(row.provider_dataset_id),
        sync_scope=str(row.sync_scope),
        operation_key=str(row.operation_key),
    )


async def _disable(
    session: AsyncSession,
    membership: ProviderDatasetOperationMembership,
    *,
    axis: str,
) -> None:
    """``dataset.is_active`` 또는 ``operation.is_enabled`` 한 축만 내린다."""
    if axis == "dataset":
        statement = """
            UPDATE provider_sync.provider_datasets
            SET is_active = false
            WHERE provider_dataset_id = :provider_dataset_id
        """
        params = {"provider_dataset_id": membership.provider_dataset_id}
    else:
        statement = """
            UPDATE provider_sync.provider_dataset_operations
            SET is_enabled = false
            WHERE provider_dataset_id = :provider_dataset_id
              AND operation_key = :operation_key
              AND operation_kind = 'refresh'
        """
        params = {
            "provider_dataset_id": membership.provider_dataset_id,
            "operation_key": membership.operation_key,
        }
    result = await session.execute(text(statement), params)
    assert result.rowcount == 1
    await session.flush()


@pytest.mark.parametrize("axis", ["dataset", "operation"])
@pytest.mark.parametrize("outcome", ["success", "failure"])
async def test_membership_cursor_write_requires_active_enabled_scope(
    migrated_session: AsyncSession,
    axis: str,
    outcome: str,
) -> None:
    """비활성 dataset·disabled operation에는 cursor를 쓸 수 없다.

    ``record_sync_*_for_operation_membership``은 exact membership CTE가 0행이면
    ``ValueError``로 끝난다. 그 CTE의 활성 술어가 사라지면 여기서 행이 하나 나와
    성공/실패가 그대로 기록된다.
    """
    membership = await _membership(migrated_session)
    await _disable(migrated_session, membership, axis=axis)

    async def _write() -> object:
        if outcome == "success":
            return await record_sync_success_for_operation_membership(
                migrated_session,
                membership=membership,
                cursor={"last_modified_date": "2026-01-01"},
            )
        return await record_sync_failure_for_operation_membership(
            migrated_session,
            membership=membership,
        )

    with pytest.raises(
        ValueError, match="operation membership is not an active enabled refresh scope"
    ):
        await _write()


@pytest.mark.parametrize("axis", ["dataset", "operation"])
@pytest.mark.parametrize("outcome", ["success", "failure"])
async def test_natural_key_cursor_write_requires_active_enabled_scope(
    migrated_session: AsyncSession,
    axis: str,
    outcome: str,
) -> None:
    """자연키 진입점도 같은 가드를 쓴다 — 여기서는 행이 0건이라 ``.one()``이 죽는다."""
    membership = await _membership(migrated_session)
    await _disable(migrated_session, membership, axis=axis)

    async def _write() -> object:
        if outcome == "success":
            return await record_sync_success(
                migrated_session,
                provider=_P,
                dataset_key=_D,
                operation_key=_O,
                cursor={"last_modified_date": "2026-01-01"},
            )
        return await record_sync_failure(
            migrated_session,
            provider=_P,
            dataset_key=_D,
            operation_key=_O,
        )

    with pytest.raises(NoResultFound):
        await _write()


@pytest.mark.parametrize("axis", ["dataset", "operation"])
async def test_get_for_membership_hides_deactivated_scope(
    migrated_session: AsyncSession,
    axis: str,
) -> None:
    """이미 쓰인 cursor라도 membership이 비활성이 되면 exact 조회는 ``None``이다."""
    membership = await _membership(migrated_session)
    written = await record_sync_success_for_operation_membership(
        migrated_session,
        membership=membership,
        cursor={"last_modified_date": "2026-01-01"},
    )
    assert written.operation_key == membership.operation_key
    assert (
        await get_sync_state_for_operation_membership(
            migrated_session, membership=membership
        )
    ) is not None

    await _disable(migrated_session, membership, axis=axis)

    assert (
        await get_sync_state_for_operation_membership(
            migrated_session, membership=membership
        )
    ) is None


_SIBLING_OPERATION_KEY = "sync_state_sibling_refresh_probe_job"


async def _seed_sibling_operation(
    session: AsyncSession,
    membership: ProviderDatasetOperationMembership,
) -> ProviderDatasetOperationMembership:
    """같은 (dataset, sync_scope)에 형제 refresh operation을 하나 더 등록한다.

    0091이 scope PK를 pair에서 triple로 올린 명시적 목적이 이 모양을 허용하는
    것이다. 형제가 없으면 ``operation_key`` 축은 어떤 행도 가르지 못해 필터를
    지워도 결과가 같다.
    """
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


async def test_operation_key_filter_separates_sibling_operations(
    migrated_session: AsyncSession,
) -> None:
    """``operation_key`` 필터는 같은 dataset·scope의 형제 state를 갈라야 한다."""
    seed_membership = await _membership(migrated_session)
    sibling = await _seed_sibling_operation(migrated_session, seed_membership)

    await record_sync_success_for_operation_membership(
        migrated_session,
        membership=seed_membership,
        cursor={"last_modified_date": "2026-01-01"},
    )
    await record_sync_success_for_operation_membership(
        migrated_session,
        membership=sibling,
        cursor={"last_modified_date": "2026-02-02"},
    )

    both = await list_sync_states(migrated_session, provider=_P, dataset_key=_D)
    assert sorted(state.operation_key for state in both) == sorted(
        [_O, _SIBLING_OPERATION_KEY]
    )

    only_seed = await list_sync_states(
        migrated_session, provider=_P, dataset_key=_D, operation_key=_O
    )
    assert [state.operation_key for state in only_seed] == [_O]
    assert [state.cursor for state in only_seed] == [{"last_modified_date": "2026-01-01"}]

    only_sibling = await list_sync_states_by_dataset_id(
        migrated_session,
        provider_dataset_id=sibling.provider_dataset_id,
        operation_key=_SIBLING_OPERATION_KEY,
    )
    assert [state.operation_key for state in only_sibling] == [_SIBLING_OPERATION_KEY]
    assert [state.cursor for state in only_sibling] == [{"last_modified_date": "2026-02-02"}]

    unfiltered = await list_sync_states_by_dataset_id(
        migrated_session, provider_dataset_id=sibling.provider_dataset_id
    )
    assert len(unfiltered) == 2

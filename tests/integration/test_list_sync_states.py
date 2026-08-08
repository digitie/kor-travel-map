"""``list_sync_states`` 통합 테스트 (T-213g)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kortravelmap.infra import sync_state_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

# T-VN-33 이후 sync state는 catalog에 실재하는 active dataset + enabled refresh
# operation scope에만 쓸 수 있다 — 임의 dataset_key("d1")는 더 이상 통하지 않는다.
_MOIS = "python-mois-api"
_MOIS_D1 = "mois_license_features_history"
_MOIS_O1 = "mois_license_incremental_update"
_MOIS_D2 = "mois_license_detail"
_MOIS_O2 = "mois_license_detail_update"
_KNPS = "python-knps-api"
_KNPS_D = "knps_campgrounds"
_KNPS_O = "feature_place_knps_points_job"


async def test_list_sync_states_filters_and_404_empty(
    migrated_session: AsyncSession,
) -> None:
    await sync_state_repo.record_sync_success(
        migrated_session,
        provider=_MOIS,
        dataset_key=_MOIS_D1,
        operation_key=_MOIS_O1,
        cursor={"k": 1},
    )
    await sync_state_repo.record_sync_success(
        migrated_session,
        provider=_MOIS,
        dataset_key=_MOIS_D2,
        operation_key=_MOIS_O2,
        cursor={"k": 2},
    )
    await sync_state_repo.record_sync_failure(
        migrated_session, provider=_KNPS, dataset_key=_KNPS_D, operation_key=_KNPS_O
    )

    mois = await sync_state_repo.list_sync_states(migrated_session, provider=_MOIS)
    assert {s.dataset_key for s in mois} == {_MOIS_D1, _MOIS_D2}

    filtered = await sync_state_repo.list_sync_states(
        migrated_session, provider=_MOIS, dataset_key=_MOIS_D1
    )
    assert [s.dataset_key for s in filtered] == [_MOIS_D1]

    knps = await sync_state_repo.list_sync_states(migrated_session, provider=_KNPS)
    assert len(knps) == 1
    assert knps[0].last_failure_at is not None
    assert knps[0].consecutive_failures == 1

    empty = await sync_state_repo.list_sync_states(
        migrated_session, provider="nonexistent-provider"
    )
    assert empty == []

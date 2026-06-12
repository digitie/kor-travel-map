"""``list_sync_states`` 통합 테스트 (T-213g)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kortravelmap.infra import sync_state_repo

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_list_sync_states_filters_and_404_empty(
    migrated_session: AsyncSession,
) -> None:
    await sync_state_repo.record_sync_success(
        migrated_session, provider="python-mois-api", dataset_key="d1", cursor={"k": 1}
    )
    await sync_state_repo.record_sync_success(
        migrated_session, provider="python-mois-api", dataset_key="d2", cursor={"k": 2}
    )
    await sync_state_repo.record_sync_failure(
        migrated_session, provider="python-knps-api", dataset_key="d3"
    )

    mois = await sync_state_repo.list_sync_states(
        migrated_session, provider="python-mois-api"
    )
    assert {s.dataset_key for s in mois} == {"d1", "d2"}

    filtered = await sync_state_repo.list_sync_states(
        migrated_session, provider="python-mois-api", dataset_key="d1"
    )
    assert [s.dataset_key for s in filtered] == ["d1"]

    knps = await sync_state_repo.list_sync_states(
        migrated_session, provider="python-knps-api"
    )
    assert len(knps) == 1
    assert knps[0].last_failure_at is not None
    assert knps[0].consecutive_failures == 1

    empty = await sync_state_repo.list_sync_states(
        migrated_session, provider="nonexistent-provider"
    )
    assert empty == []

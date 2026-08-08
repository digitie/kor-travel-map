"""``test_sync_state_repo`` — provider 증분 cursor 추적 (Step B, Sprint 4a).

``provider_sync.provider_sync_state``를 ``get`` / ``record_sync_success`` /
``record_sync_failure``로 UPSERT하며 cursor 전진·연속 실패 카운트를 검증한다.
``migrated_session``(rollback 격리)으로 commit 없이.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from kortravelmap.infra.sync_state_repo import (
    get_sync_state,
    record_sync_failure,
    record_sync_success,
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

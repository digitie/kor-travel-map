"""Dagster Feature asset helper unit test."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Final, cast

import pytest
from dagster import build_asset_context
from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership

from kortravelmap.dagster.assets import (
    _exact_sync_membership,
    _record_batches,
    _record_feature_sync_success,
)
from kortravelmap.dagster.etl import AddressFindingObservationReceipt
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
    FeatureOperationGuardUnavailable,
)

# T-VN-33: sync state 행은 provider/dataset label이 아니라
# ``provider_dataset_id + sync_scope + operation_key`` triple로 식별된다(ADR-088).
_OPERATION_KEY: Final = "feature_demo_job"
_MEMBERSHIP: Final = ProviderDatasetOperationMembership(
    provider_dataset_id=4242,
    sync_scope="dataset_wide",
    operation_key=_OPERATION_KEY,
)


class _Log:
    def warning(self, message: str) -> None:
        del message

    def info(self, message: str) -> None:
        del message


class _SyncClient:
    def __init__(self) -> None:
        self.sync_calls: list[dict[str, object]] = []
        self.close_calls: list[dict[str, object]] = []

    async def record_sync_success(self, **_kwargs: object) -> None:
        """legacy capability probe 전용.

        ``_record_feature_sync_success``는 지금도 이 이름의 존재로 "sync state를 쓸
        수 있는 client인가"를 판정한 뒤, 실제 기록은
        ``record_sync_success_for_operation_membership``으로 한다. double이 이 이름을
        지우면 asset이 조용히 기록을 건너뛰므로 남겨 둔다.
        """
        raise AssertionError("T-VN-33 이후 기록은 membership 경로로만 간다.")

    async def record_sync_success_for_operation_membership(
        self, **kwargs: object
    ) -> None:
        self.sync_calls.append(dict(kwargs))

    async def resolve_feature_operation_memberships(
        self, *, operation_key: str
    ) -> tuple[ProviderDatasetOperationMembership, ...]:
        assert operation_key == _OPERATION_KEY
        return (_MEMBERSHIP,)

    async def resolve_feature_operation_dataset_membership(
        self, *, operation_key: str, provider: str, dataset_key: str
    ) -> ProviderDatasetOperationMembership:
        assert (operation_key, provider, dataset_key) == (
            _OPERATION_KEY,
            "demo",
            "places",
        )
        return _MEMBERSHIP

    async def close_stale_address_validation_findings(
        self, **kwargs: object
    ) -> int:
        self.close_calls.append(dict(kwargs))
        return 1


def _guard(client: _SyncClient) -> FeatureOperationExecutionGuard:
    """asset이 sync-state를 쓰려면 feature-operation guard가 있어야 한다.

    프로덕션에서는 ``run_tracked_feature_asset``이 실행 시작 시 넣는다. label로는
    어느 sync state 행인지 결정되지 않으므로(ADR-088), helper를 직접 부르는
    테스트도 실행 대상 operation을 똑같이 선언한다.
    """
    return FeatureOperationExecutionGuard(
        client=cast("AsyncKorTravelMapClient", client),
        instance=None,
        operation_key=_OPERATION_KEY,
        memberships=(_MEMBERSHIP,),
        dagster_run_id="run-1",
        trigger_kind="schedule",
    )


def _context(client: _SyncClient) -> SimpleNamespace:
    return SimpleNamespace(
        resources=SimpleNamespace(
            fetched_at=datetime(2026, 7, 31, tzinfo=UTC),
            kor_travel_map_client=client,
            feature_operation_guard=_guard(client),
        ),
        asset_key=SimpleNamespace(to_user_string=lambda: "feature/demo"),
        run_id="run-1",
        log=_Log(),
    )


def _receipt(*, source_observations: int) -> AddressFindingObservationReceipt:
    return AddressFindingObservationReceipt(
        authoritative_snapshot_complete=True,
        source_observations=source_observations,
        findings_observed=0,
        findings_unique=0,
        findings_upserted=0,
        finding_persistence_complete=True,
    )


async def test_record_batches_chunks_iterable_resource() -> None:
    context = build_asset_context(resources={"demo_records": [1, 2, 3, 4, 5]})

    batches = [
        batch
        async for batch in _record_batches(context, "demo_records", batch_size=2)
    ]

    assert batches == [[1, 2], [3, 4], [5]]


async def test_record_batches_chunks_async_iterable_resource() -> None:
    async def _records() -> AsyncIterator[int]:
        for item in range(5):
            yield item

    context = build_asset_context(resources={"demo_records": _records})

    batches = [
        batch
        async for batch in _record_batches(context, "demo_records", batch_size=3)
    ]

    assert batches == [[0, 1, 2], [3, 4]]


async def test_sync_success_without_typed_receipt_does_not_close_findings() -> None:
    client = _SyncClient()

    await _record_feature_sync_success(
        _context(client),  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        cursor_extra={},
    )

    assert len(client.sync_calls) == 1
    # cursor는 label이 아니라 guard가 고정한 exact membership 행에 적힌다(ADR-088).
    assert client.sync_calls[0]["membership"] == _MEMBERSHIP
    assert client.close_calls == []


async def test_empty_snapshot_receipt_does_not_close_findings() -> None:
    client = _SyncClient()

    await _record_feature_sync_success(
        _context(client),  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        cursor_extra={},
        observation_receipt=_receipt(source_observations=0),
    )

    assert len(client.sync_calls) == 1
    assert client.close_calls == []


async def test_complete_nonempty_snapshot_receipt_closes_findings_once() -> None:
    client = _SyncClient()

    await _record_feature_sync_success(
        _context(client),  # type: ignore[arg-type]
        client,  # type: ignore[arg-type]
        provider="demo",
        dataset_key="places",
        cursor_extra={},
        observation_receipt=_receipt(source_observations=1),
    )

    assert len(client.sync_calls) == 1
    assert len(client.close_calls) == 1
    close_call = client.close_calls[0]
    assert close_call["provider"] == "demo"
    assert close_call["dataset_key"] == "places"
    assert close_call["run_id"] == "run-1"
    assert close_call["receipt"].permits_stale_close is True


async def test_sync_membership_rejects_a_guard_without_operation_key() -> None:
    """operation_key 없는 guard로는 sync-state 행을 고르지 않는다.

    trigger/operation tag가 없는 run은 guard가 ``operation_key=None``으로 만들어진다
    (``_guard_from_context_async``의 panel-only 경로). 그 guard로 계속 가면 남은
    선택지가 provider/dataset label 역산뿐인데, 이 함수는 그 fallback을 두지 않기로
    한 자리다 — 그러므로 조용히 진행하지 않고 죽어야 한다.
    """
    client = _SyncClient()
    context = _context(client)
    context.resources.feature_operation_guard = FeatureOperationExecutionGuard(
        client=cast("AsyncKorTravelMapClient", client),
        instance=None,
        operation_key=None,
        memberships=(),
        dagster_run_id="run-1",
        trigger_kind=None,
    )

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        await _exact_sync_membership(
            context,  # type: ignore[arg-type]
            client,  # type: ignore[arg-type]
            boundary="feature_sync_state",
            provider="demo",
            dataset_key="places",
        )

    assert excinfo.value.reason == "operation_key_missing"
    assert excinfo.value.boundary == "feature_sync_state"
    assert client.sync_calls == []


async def test_sync_membership_rejects_an_untyped_membership_resource() -> None:
    """queue worker가 넘긴 membership resource는 **typed**여야 한다.

    이 resource는 guard를 완전히 대체해 곧바로 cursor 대상 행이 된다. duck-typed
    대역이 통과하면 triple이 아닌 값이 sync-state 기록 경로로 그대로 흘러간다 —
    그래서 존재가 아니라 타입을 본다.
    """
    client = _SyncClient()
    context = _context(client)
    context.resources.feature_update_membership = SimpleNamespace(
        provider_dataset_id=_MEMBERSHIP.provider_dataset_id,
        sync_scope=_MEMBERSHIP.sync_scope,
        operation_key=_MEMBERSHIP.operation_key,
    )

    with pytest.raises(FeatureOperationGuardUnavailable) as excinfo:
        await _exact_sync_membership(
            context,  # type: ignore[arg-type]
            client,  # type: ignore[arg-type]
            boundary="feature_sync_state",
            provider="demo",
            dataset_key="places",
        )

    assert excinfo.value.reason == "feature_update_membership_wrong_type"
    # 대조: 같은 자리에 typed membership을 넣으면 그대로 통과한다 — 거부 사유가
    # "타입"임을 못 박는다.
    context.resources.feature_update_membership = _MEMBERSHIP
    assert (
        await _exact_sync_membership(
            context,  # type: ignore[arg-type]
            client,  # type: ignore[arg-type]
            boundary="feature_sync_state",
            provider="demo",
            dataset_key="places",
        )
        == _MEMBERSHIP
    )

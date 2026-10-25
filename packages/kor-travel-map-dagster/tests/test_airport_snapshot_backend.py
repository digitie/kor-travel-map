"""정본 후처리 intent가 전용 backend TX 한 번으로만 전달되는지 확인한다."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotExecutorToken
from test_airport_snapshot_postprocess import _input

from kortravelmap.dagster.airport_snapshot_backend import AirportSnapshotBackend
from kortravelmap.dagster.airport_snapshot_postprocess import (
    UnsupportedAirportPostprocess,
    prepare_airport_snapshot_postprocess,
)


async def _backend(*, partial=False, error=None):
    args, _, _ = await _input(count=1, geo=True, warning=True)
    intent = prepare_airport_snapshot_postprocess(**args)
    assert len(intent.findings) > 0
    bound = SimpleNamespace(
        record_address_validation_findings=AsyncMock(
            return_value=SimpleNamespace(
                observed_count=len(intent.findings),
                unique_count=len(intent.findings),
                upserted_count=0 if partial else len(intent.findings),
            )
        ),
        record_sync_success_for_operation_membership=AsyncMock(),
        close_stale_address_validation_findings=AsyncMock(return_value=0, side_effect=error),
    )

    async def transaction(token, receipt, work):
        await work(bound)
        return receipt

    client = SimpleNamespace(run_provider_snapshot_postprocess=AsyncMock(side_effect=transaction))
    backend = AirportSnapshotBackend(client, SnapshotExecutorToken(uuid4(), 1, uuid4()))
    return backend, bound, intent


async def test_three_effects_share_single_transaction_callback_and_original_generation():
    backend, bound, intent = await _backend()
    assert await backend.complete_provider_snapshot_postprocess(intent) == intent.receipt_candidate
    backend.client.run_provider_snapshot_postprocess.assert_awaited_once()
    finding_args = bound.record_address_validation_findings.await_args
    assert finding_args.kwargs["run_id"] == intent.observation.observation_generation
    assert finding_args.args[0] == intent.findings
    assert bound.record_sync_success_for_operation_membership.await_args.kwargs == {
        "membership": intent.member.membership,
        "cursor": intent.cursor,
    }
    assert bound.close_stale_address_validation_findings.await_args.kwargs[
        "receipt"
    ].permits_stale_close


async def test_partial_finding_write_does_not_advance_sync_or_close():
    backend, bound, intent = await _backend(partial=True)
    with pytest.raises(UnsupportedAirportPostprocess, match="full finding set"):
        await backend.complete_provider_snapshot_postprocess(intent)
    bound.record_sync_success_for_operation_membership.assert_not_awaited()
    bound.close_stale_address_validation_findings.assert_not_awaited()


async def test_stale_close_failure_is_not_swallowed_into_completion():
    failure = RuntimeError("injected close failure")
    backend, bound, intent = await _backend(error=failure)
    with pytest.raises(RuntimeError, match="injected close"):
        await backend.complete_provider_snapshot_postprocess(intent)
    bound.record_sync_success_for_operation_membership.assert_awaited_once()

"""저장된 Airport 후처리를 한 fenced client transaction에 연결한다."""

from __future__ import annotations

from dataclasses import dataclass

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client._snapshot_atomic import SnapshotPostprocessWork
from kortravelmap.infra.integrity_violation_repo import IntegrityObservationReceipt
from kortravelmap.infra.provider_snapshot_recovery_repo import SnapshotExecutorToken

from .airport_snapshot_postprocess import (
    AirportPostprocessIntent,
    UnsupportedAirportPostprocess,
    prepare_airport_snapshot_postprocess,
)


@dataclass(frozen=True)
class AirportSnapshotBackend:
    client: AsyncKorTravelMapClient
    token: SnapshotExecutorToken

    async def complete_provider_snapshot_postprocess(
        self, intent: AirportPostprocessIntent
    ) -> bytes:
        prepared = prepare_airport_postprocess_work(intent)
        return await self.client.run_provider_snapshot_postprocess(
            self.token, prepared.receipt_candidate, prepared.work
        )


def prepare_airport_postprocess_work(intent: AirportPostprocessIntent) -> SnapshotPostprocessWork:
    """원 intent를 재검증하고 같은 connection에서 실행할 작업만 준비한다."""
    canonical = prepare_airport_snapshot_postprocess(
        member=intent.member,
        artifact_bytes=intent.artifact_bytes,
        context_bytes=intent.context_bytes,
        result_bytes=intent.result_bytes,
        expected_pins=intent.pins,
        expected_root_run_id=intent.root_run_id,
    )
    if canonical.receipt_candidate != intent.receipt_candidate:
        raise UnsupportedAirportPostprocess("backend intent differs from original bytes")

    async def work(bound: AsyncKorTravelMapClient) -> None:
        written = await bound.record_address_validation_findings(
            canonical.findings,
            provider=canonical.pins.provider,
            dataset_key=canonical.pins.dataset_key,
            run_id=canonical.observation.observation_generation,
        )
        unique = len({finding.dedupe_key for finding in canonical.findings})
        if (
            written.observed_count != len(canonical.findings)
            or written.unique_count != unique
            or written.upserted_count != unique
        ):
            raise UnsupportedAirportPostprocess("backend did not persist the full finding set")
        await bound.record_sync_success_for_operation_membership(
            membership=canonical.member.membership, cursor=canonical.cursor
        )
        closed = await bound.close_stale_address_validation_findings(
            provider=canonical.pins.provider,
            dataset_key=canonical.pins.dataset_key,
            run_id=canonical.observation.observation_generation,
            receipt=IntegrityObservationReceipt(
                authoritative_snapshot_complete=True,
                source_observations=canonical.observation.source_observations,
                findings_observed=written.observed_count,
                findings_unique=written.unique_count,
                findings_upserted=written.upserted_count,
                finding_persistence_complete=True,
            ),
        )
        if type(closed) is not int or closed < 0:
            raise UnsupportedAirportPostprocess("backend did not finish stale finding close")

    return SnapshotPostprocessWork(canonical.receipt_candidate, work)

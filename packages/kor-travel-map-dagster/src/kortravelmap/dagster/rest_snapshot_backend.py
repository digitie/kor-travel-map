"""Rest의 원 bytes로 선택A 같은 TX의 필수 후처리 작업만 준비한다."""

from __future__ import annotations

from dataclasses import dataclass

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client._snapshot_atomic import SnapshotPostprocessWork
from kortravelmap.infra.integrity_violation_repo import IntegrityObservationReceipt
from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotRecoveryCorruption,
)

from .rest_snapshot_postprocess import (
    RestPostprocessMember,
    UnsupportedRestPostprocess,
    prepare_rest_snapshot_postprocess,
)


@dataclass(frozen=True)
class RestSnapshotBackend:
    """DB가 해석한 member/pins에 결박된 pure factory. commit/session/HTTP를 소유하지 않는다."""

    member: RestPostprocessMember
    pins: SnapshotArtifactPins
    root_run_id: str

    def prepare(self, observed: RecoveredProviderSnapshot) -> SnapshotPostprocessWork:
        if observed.applied_result_bytes is None:
            raise SnapshotRecoveryCorruption("rest snapshot has no original apply result")
        canonical = prepare_rest_snapshot_postprocess(
            member=self.member,
            artifact_bytes=observed.artifact_payload,
            context_bytes=observed.observation_context,
            result_bytes=observed.applied_result_bytes,
            expected_pins=self.pins,
            expected_root_run_id=self.root_run_id,
        )

        async def work(bound: AsyncKorTravelMapClient) -> None:
            # bind coordinator가 같은 physical connection의 rollback_only client만 전달한다.
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
                raise UnsupportedRestPostprocess("backend did not persist the full finding set")
            await bound.record_sync_success_for_operation_membership(
                membership=canonical.member.membership,
                cursor=canonical.cursor,
            )
            closed = await bound.close_stale_address_validation_findings(
                provider=canonical.pins.provider,
                dataset_key=canonical.pins.dataset_key,
                run_id=canonical.observation.observation_generation,
                receipt=IntegrityObservationReceipt(
                    authoritative_snapshot_complete=True,
                    source_observations=canonical.observation.source_observations,
                    findings_observed=written.observed_count,
                    findings_unique=unique,
                    findings_upserted=unique,
                    finding_persistence_complete=True,
                ),
            )
            if type(closed) is not int or closed < 0:
                raise UnsupportedRestPostprocess("backend did not complete stale finding close")

        return SnapshotPostprocessWork(canonical.receipt_candidate, work)

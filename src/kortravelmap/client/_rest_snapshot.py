"""Rest snapshot의 작은 client TX 경계. SDK·Dagster·공유 client 배선은 없다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.client._airport_snapshot import _kernel_replan, _transaction, _unbound
from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    RecoveredProviderSnapshot,
    SnapshotExecutorLease,
    SnapshotExecutorToken,
    SnapshotMember,
    SnapshotMemberSeal,
    SnapshotRegistration,
    _member_params,
    _token_params,
    bind_provider_snapshot_plan,
    claim_provider_snapshot_executor,
    read_provider_snapshot_for_member,
    register_provider_snapshot_artifact,
    seal_provider_snapshot_member,
)
from kortravelmap.infra.provider_snapshot_result import SnapshotApplyResult
from kortravelmap.infra.rest_area_snapshot_artifact import decode_rest_area_snapshot_artifact
from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    append_scoped_feature_write_manifest,
    claim_scoped_feature_write,
    seal_scoped_feature_write_manifest,
)
from kortravelmap.infra.transport_rest_evidence_reader import decode_transport_rest_evidence
from kortravelmap.providers.kor_travel_rest_apply import (
    _inputs,
    apply_stored_rest_area_reobservation,
)
from kortravelmap.providers.kor_travel_rest_evidence import (
    RestReobservationPreparation,
    assess_transport_rest_area_reobservation_evidence,
)

if TYPE_CHECKING:
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.client import AsyncKorTravelMapClient

LEASE_SECONDS = 300


class RestSnapshotUnavailable(ValueError):
    """기존 executor에 결합된 client는 새 독립 TX를 시작할 수 없다."""


async def read_rest_snapshot(
    client: AsyncKorTravelMapClient, member: SnapshotMember, *, pins: SnapshotArtifactPins | None
) -> RecoveredProviderSnapshot | None:
    """SDK보다 먼저 동일 statement의 원 입력/결과를 읽는다. 부재만 None이다."""
    async with _transaction(client, readonly=True) as session:
        if pins is None:
            present = await session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM ops.read_provider_snapshot_for_member("
                    ":root,:child,:member))"
                ),
                _member_params(member),
            )
            if type(present) is not bool or present:
                raise RestSnapshotUnavailable("registered snapshot requires verified runtime pins")
            return None
        return await read_provider_snapshot_for_member(session, member, expected_pins=pins)


async def register_rest_snapshot(
    client: AsyncKorTravelMapClient,
    member: SnapshotMember,
    *,
    payload: bytes,
    context: bytes,
    pins: SnapshotArtifactPins,
) -> SnapshotRegistration:
    """입력·원 관측을 한 번 등록한다. commit 응답 유실을 성공으로 추측하지 않는다."""
    async with _transaction(client) as session:
        return await register_provider_snapshot_artifact(
            session,
            member,
            artifact_payload=payload,
            observation_context=context,
            expected_pins=pins,
            lease_seconds=LEASE_SECONDS,
        )


async def claim_rest_snapshot(
    client: AsyncKorTravelMapClient,
    observed: RecoveredProviderSnapshot,
    *,
    previous: SnapshotExecutorToken | None = None,
) -> SnapshotExecutorLease:
    """DB의 실제 fence만 전달한다. read의 lease 시각으로 유효성을 판단하지 않는다."""
    async with _transaction(client) as session:
        return await claim_provider_snapshot_executor(
            session,
            observed.snapshot_id,
            artifact_sha256=observed.artifact_sha256,
            context_sha256=observed.context_sha256,
            lease_seconds=LEASE_SECONDS,
            previous=previous,
        )


async def seal_rest_snapshot(
    client: AsyncKorTravelMapClient,
    token: SnapshotExecutorToken,
    *,
    artifact_sha256: str,
    context_sha256: str,
    result_sha256: str,
    postprocess_sha256: str,
) -> SnapshotMemberSeal:
    """private marker·old seal/finish·control 전이를 원자 wrapper 한 번에 맡긴다."""
    async with _transaction(client) as session:
        return await seal_provider_snapshot_member(
            session,
            token,
            artifact_sha256=artifact_sha256,
            context_sha256=context_sha256,
            result_sha256=result_sha256,
            postprocess_sha256=postprocess_sha256,
        )


async def prepare_rest_snapshot_input(
    client: AsyncKorTravelMapClient, payload: bytes, *, pins: SnapshotArtifactPins, dataset_id: int
) -> RestReobservationPreparation:
    """등록 전에 같은 입력의 지원 여부만 진단한다. DB 변경·등록 권위는 없다."""
    _unbound(client)
    if type(dataset_id) is not int or not 1 <= dataset_id < 2**63:
        raise ValueError("canonical positive provider dataset required")
    artifact = decode_rest_area_snapshot_artifact(payload, expected_pins=pins)
    async with _transaction(client, readonly=True, repeatable=True) as session:
        evidence = decode_transport_rest_evidence(
            dataset_id,
            await session.scalar(
                text("SELECT feature.read_transport_rest_snapshot_evidence(:dataset)"),
                {"dataset": dataset_id},
            ),
        )
        return await assess_transport_rest_area_reobservation_evidence(
            artifact.bundles, evidence, pins=pins, geo=artifact.geo
        )


@dataclass(frozen=True)
class RestSnapshotPlan:
    """관측은 권위가 아니다. 실제 apply가 같은 원 입력과 잠금 뒤 evidence를 재검증한다."""

    preparation: RestReobservationPreparation
    attempt_id: UUID
    owner: UUID
    manifest_digest: str
    input_digest: str


class RestSnapshotReplanRequired(ValueError):
    """원 DB 사실이 바뀌었다. 등록 입력을 버리거나 다시 수집할 근거는 아니다."""


async def plan_rest_snapshot(
    client: AsyncKorTravelMapClient,
    observed: RecoveredProviderSnapshot,
    token: SnapshotExecutorToken,
    *,
    pins: SnapshotArtifactPins,
    dataset_id: int,
) -> RestSnapshotPlan:
    """RR의 전체 진단 뒤 독립 RC에서 claim/manifest/bind를 함께 commit한다."""
    _unbound(client)
    if type(dataset_id) is not int or not 1 <= dataset_id < 2**63:
        raise ValueError("canonical positive provider dataset required")
    if token.snapshot_id != observed.snapshot_id or observed.status != "prepared":
        raise RestSnapshotUnavailable("only the exact prepared snapshot can be planned")
    artifact = decode_rest_area_snapshot_artifact(observed.artifact_payload, expected_pins=pins)
    async with _transaction(client, readonly=True, repeatable=True) as session:
        evidence = decode_transport_rest_evidence(
            dataset_id,
            await session.scalar(
                text("SELECT feature.read_transport_rest_snapshot_evidence(:dataset)"),
                {"dataset": dataset_id},
            ),
        )
        preparation = await assess_transport_rest_area_reobservation_evidence(
            artifact.bundles, evidence, pins=pins, geo=artifact.geo
        )
        if preparation.eligible is not True:
            raise RestSnapshotUnavailable(
                "registered rest input requires EX: " + preparation.reason
            )
        _, digest, _, _ = _inputs(artifact, preparation)
        dependencies: list[ScopedWriteDependency] = []
        for raw in evidence.items:
            item = cast("dict[str, Any]", raw)
            feature = item["feature"]
            fid = UUID(feature["feature_id"])
            membership = await session.scalar(
                text("SELECT ops.scoped_feature_write_membership_digest(:feature)"),
                {"feature": fid},
            )
            offset = len(dependencies)
            dependencies.extend(
                (
                    ScopedWriteDependency(
                        offset, "feature", str(fid), str(feature["row_revision"])
                    ),
                    ScopedWriteDependency(
                        offset + 1,
                        "source_head",
                        item["source_entity"]["source_entity_key"],
                        item["source_head"]["current_source_record_key"],
                    ),
                    ScopedWriteDependency(offset + 2, "feature_membership", str(fid), membership),
                )
            )
    existing = observed.kernel_binding
    if existing is not None:
        if existing.status != "ready" or existing.input_digest != digest:
            raise RestSnapshotReplanRequired(
                "bound kernel plan requires a fresh SDK0 read or typed reset"
            )
        return RestSnapshotPlan(
            preparation, existing.attempt_id, existing.owner, existing.manifest_digest, digest
        )
    attempt, owner = uuid4(), uuid4()
    async with _transaction(client) as session:
        await claim_scoped_feature_write(
            session,
            attempt_id=attempt,
            owner=owner,
            dataset_id=dataset_id,
            idempotency_key="rest_snapshot:"
            + str(observed.snapshot_id)
            + ":"
            + str(token.generation)
            + ":"
            + str(attempt),
            regions=(),
            input_digest=digest,
            expected_members=len(dependencies),
            lease_seconds=LEASE_SECONDS,
            exclusive_protocol=False,
        )
        for start in range(0, len(dependencies), 256):
            await append_scoped_feature_write_manifest(
                session, attempt_id=attempt, owner=owner, members=dependencies[start : start + 256]
            )
        manifest = await seal_scoped_feature_write_manifest(
            session, attempt_id=attempt, owner=owner
        )
        await bind_provider_snapshot_plan(
            session,
            token,
            attempt_id=attempt,
            owner=owner,
            manifest_digest=manifest,
            kernel_input_digest=digest,
        )
    return RestSnapshotPlan(preparation, attempt, owner, manifest, digest)


async def apply_rest_snapshot_in_session(
    session: AsyncSession,
    observed: RecoveredProviderSnapshot,
    token: SnapshotExecutorToken,
    plan: RestSnapshotPlan,
    *,
    pins: SnapshotArtifactPins,
) -> SnapshotApplyResult:
    """선택A coordinator가 소유한 같은 TX에 적용한다. TX 시작/commit/seal은 하지 않는다."""
    if not session.in_transaction():
        raise RestSnapshotUnavailable("explicit caller transaction required")
    if token.snapshot_id != observed.snapshot_id or observed.status != "prepared":
        raise RestSnapshotUnavailable("only the exact prepared snapshot can be applied")
    try:
        return await apply_stored_rest_area_reobservation(
            session,
            observed.artifact_payload,
            plan.preparation,
            pins=pins,
            snapshot_id=token.snapshot_id,
            generation=token.generation,
            fence=token.fence,
            attempt_id=plan.attempt_id,
            owner=plan.owner,
            manifest_digest=plan.manifest_digest,
        )
    except DBAPIError as error:
        if _kernel_replan(error):
            raise RestSnapshotReplanRequired("kernel requires a fresh plan") from error
        raise
    except ValueError as error:
        if str(error) == "rest-area evidence changed after locking; replan":
            raise RestSnapshotReplanRequired(str(error)) from error
        raise


async def reset_rest_snapshot_plan(
    client: AsyncKorTravelMapClient,
    observed: RecoveredProviderSnapshot,
    token: SnapshotExecutorToken,
) -> str:
    """만료 여부는 서버가 결정한다. 완료 결과나 임의 attempt를 버리지 않는다."""
    _unbound(client)
    binding = observed.kernel_binding
    if (
        token.snapshot_id != observed.snapshot_id
        or observed.status != "prepared"
        or binding is None
    ):
        raise RestSnapshotUnavailable("exact prepared snapshot kernel binding required for reset")
    params = _token_params(token)
    params.update(attempt=binding.attempt_id, owner=binding.owner, manifest=binding.manifest_digest)
    async with _transaction(client) as session:
        result = await session.scalar(
            text(
                "SELECT ops.reset_expired_provider_snapshot_plan("
                ":snapshot,:generation,:fence,:attempt,:owner,:manifest)"
            ),
            params,
        )
        if type(result) is not str or result not in {"reset", "needs_read"}:
            raise RestSnapshotUnavailable("invalid snapshot reset response")
        return result


async def reset_rolled_back_rest_snapshot_plan(
    client: AsyncKorTravelMapClient,
    observed: RecoveredProviderSnapshot,
    token: SnapshotExecutorToken,
    plan: RestSnapshotPlan,
) -> str:
    """atomic apply의 선택 stale rollback 뒤 원 plan만 정리한다. ACK 불명에는 호출하지 않는다."""
    _unbound(client)
    if token.snapshot_id != observed.snapshot_id or observed.status != "prepared":
        raise RestSnapshotUnavailable("exact prepared snapshot required for rolled-back reset")
    binding = observed.kernel_binding
    if binding is not None and (
        binding.attempt_id != plan.attempt_id
        or binding.owner != plan.owner
        or binding.manifest_digest != plan.manifest_digest
    ):
        raise RestSnapshotUnavailable("rolled-back snapshot plan binding changed")
    params = _token_params(token)
    params.update(attempt=plan.attempt_id, owner=plan.owner, manifest=plan.manifest_digest)
    async with _transaction(client) as session:
        result = await session.scalar(
            text(
                "SELECT ops.reset_ready_provider_snapshot_plan("
                ":snapshot,:generation,:fence,:attempt,:owner,:manifest)"
            ),
            params,
        )
        if type(result) is not str or result not in {"reset", "needs_read"}:
            raise RestSnapshotUnavailable("invalid rolled-back snapshot reset response")
        return result


async def collect_expired_rest_snapshots(client: AsyncKorTravelMapClient) -> int:
    """미등록 opt-in 실행 직전 한 번만 최대16개를 정리한다. terminal+7일은 SD 권위다."""
    async with _transaction(client) as session:
        removed = await session.scalar(text("SELECT ops.collect_expired_provider_snapshots(16)"))
        if type(removed) is not int or not 0 <= removed <= 16:
            raise RestSnapshotUnavailable("invalid bounded snapshot collection response")
        return removed

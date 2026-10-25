"""Airport snapshot의 작은 client TX 경계. SDK·Dagster·공유 client 배선은 없다."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from sqlalchemy import text

from kortravelmap.infra.provider_snapshot_artifact import (
    SnapshotArtifactPins,
    decode_provider_snapshot_artifact,
)
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
from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    append_scoped_feature_write_manifest,
    claim_scoped_feature_write,
    seal_scoped_feature_write_manifest,
)
from kortravelmap.infra.transaction_limits import apply_bounded_transaction_limits
from kortravelmap.infra.transport_airport_evidence_reader import decode_transport_airport_evidence
from kortravelmap.providers.kor_travel_transport_apply import (
    _inputs,
    apply_stored_airport_reobservation,
)
from kortravelmap.providers.kor_travel_transport_evidence import (
    AirportReobservationPreparation,
    assess_transport_airport_reobservation_evidence,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from typing import Any

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.client import AsyncKorTravelMapClient

LEASE_SECONDS = 300


class AirportSnapshotUnavailable(ValueError):
    """기존 executor에 결합된 client는 새 독립 TX를 시작할 수 없다."""


def _unbound(client: AsyncKorTravelMapClient) -> None:
    if client._transaction_bound is not False:
        raise AirportSnapshotUnavailable("airport snapshot requires the original unbound client")


@asynccontextmanager
async def _transaction(
    client: AsyncKorTravelMapClient, *, readonly: bool = False, repeatable: bool = False
) -> AsyncIterator[AsyncSession]:
    _unbound(client)
    async with asyncio.timeout(30):
        async with client._session_factory() as session, session.begin():
            if repeatable and not readonly:
                raise ValueError("airport planning snapshot must be read only")
            mode = "REPEATABLE READ" if repeatable else "READ COMMITTED"
            access = "READ ONLY" if readonly else "READ WRITE"
            await session.execute(text(f"SET TRANSACTION ISOLATION LEVEL {mode}, {access}"))
            await apply_bounded_transaction_limits(
                session, statement_timeout_ms=3000 if repeatable else 30000
            )
            yield session


async def read_airport_snapshot(
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
                raise AirportSnapshotUnavailable(
                    "registered snapshot requires verified runtime pins"
                )
            return None
        return await read_provider_snapshot_for_member(session, member, expected_pins=pins)


async def register_airport_snapshot(
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


async def claim_airport_snapshot(
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


async def seal_airport_snapshot(
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


@dataclass(frozen=True)
class AirportSnapshotPlan:
    """관측은 권위가 아니다. 실제 apply가 같은 원 입력과 잠금 뒤 evidence를 재검증한다."""

    preparation: AirportReobservationPreparation
    attempt_id: UUID
    owner: UUID
    manifest_digest: str
    input_digest: str


class AirportSnapshotReplanRequired(ValueError):
    """원 DB 사실이 바뀌었다. 등록 입력을 버리거나 다시 수집할 근거는 아니다."""


async def plan_airport_snapshot(
    client: AsyncKorTravelMapClient,
    observed: RecoveredProviderSnapshot,
    token: SnapshotExecutorToken,
    *,
    pins: SnapshotArtifactPins,
    dataset_id: int,
) -> AirportSnapshotPlan:
    """RR의 전체 진단 뒤 독립 RC에서 claim/manifest/bind를 함께 commit한다."""
    _unbound(client)
    if type(dataset_id) is not int or not 1 <= dataset_id < 2**63:
        raise ValueError("canonical positive provider dataset required")
    if token.snapshot_id != observed.snapshot_id or observed.status != "prepared":
        raise AirportSnapshotUnavailable("only the exact prepared snapshot can be planned")
    artifact = decode_provider_snapshot_artifact(observed.artifact_payload, expected_pins=pins)
    async with _transaction(client, readonly=True, repeatable=True) as session:
        evidence = decode_transport_airport_evidence(
            dataset_id,
            await session.scalar(
                text("SELECT feature.read_transport_airport_snapshot_evidence(:dataset)"),
                {"dataset": dataset_id},
            ),
        )
        preparation = await assess_transport_airport_reobservation_evidence(
            artifact.bundles, evidence, geo=artifact.geo
        )
        if preparation.eligible is not True:
            raise AirportSnapshotUnavailable(
                "registered airport input requires EX: " + preparation.reason
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
            raise AirportSnapshotReplanRequired(
                "bound kernel plan requires a fresh SDK0 read or typed reset"
            )
        return AirportSnapshotPlan(
            preparation, existing.attempt_id, existing.owner, existing.manifest_digest, digest
        )
    attempt, owner = uuid4(), uuid4()
    async with _transaction(client) as session:
        await claim_scoped_feature_write(
            session,
            attempt_id=attempt,
            owner=owner,
            dataset_id=dataset_id,
            idempotency_key="airport_snapshot:"
            + str(observed.snapshot_id)
            + ":"
            + str(token.generation),
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
    return AirportSnapshotPlan(preparation, attempt, owner, manifest, digest)


async def apply_airport_snapshot(
    client: AsyncKorTravelMapClient,
    observed: RecoveredProviderSnapshot,
    token: SnapshotExecutorToken,
    plan: AirportSnapshotPlan,
    *,
    pins: SnapshotArtifactPins,
) -> SnapshotApplyResult:
    """원 14counter/retired를 같은 native apply TX에서 저장한다. 응답 유실은 전파한다."""
    _unbound(client)
    if token.snapshot_id != observed.snapshot_id:
        raise AirportSnapshotUnavailable("snapshot token differs from its original input")
    async with _transaction(client) as session:
        try:
            return await apply_stored_airport_reobservation(
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
        except ValueError as error:
            if str(error) == "airport evidence changed after locking; replan":
                raise AirportSnapshotReplanRequired(str(error)) from error
            raise


async def reset_airport_snapshot_plan(
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
        raise AirportSnapshotUnavailable(
            "exact prepared snapshot kernel binding required for reset"
        )
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
            raise AirportSnapshotUnavailable("invalid snapshot reset response")
        return result

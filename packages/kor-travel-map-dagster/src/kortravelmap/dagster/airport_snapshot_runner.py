"""예약 Airport만 저장 입력으로 재개한다. queue/direct context는 기존 EX 경로다."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _airport_snapshot as io
from kortravelmap.core.feature_projection import within_place_projection_budget
from kortravelmap.dto import FeatureBundle
from kortravelmap.dto.geo_dataset import GeoApplied
from kortravelmap.infra.provider_snapshot_artifact import (
    UnsupportedSnapshotArtifact,
    encode_provider_snapshot_artifact,
)
from kortravelmap.infra.provider_snapshot_postprocess_repo import ProviderSnapshotSuperseded
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    SnapshotExecutorToken,
    SnapshotMember,
    SnapshotRecoveryCorruption,
)
from kortravelmap.providers.kor_travel_transport_native import _presence
from kortravelmap.providers.krairport import airports_to_bundles
from sqlalchemy.exc import DBAPIError

from dagster import Failure

from .airport_snapshot_backend import AirportSnapshotBackend
from .airport_snapshot_observation import (
    UnsupportedAirportObservation,
    encode_airport_observation_context,
)
from .airport_snapshot_postprocess import (
    AirportPostprocessIntent,
    AirportPostprocessMember,
    UnsupportedAirportPostprocess,
    complete_airport_snapshot_postprocess,
    prepare_airport_snapshot_postprocess,
)
from .airport_snapshot_runtime import AirportSnapshotRuntime
from .etl import DagsterFeatureLoadResult, _dagster_run_id, _geo_load_context
from .feature_operation_tracking import (
    FeatureOperationExecutionGuard,
    ensure_authoritative_feature_operation_guard,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

    from kortravelmap.infra.provider_snapshot_recovery_repo import RecoveredProviderSnapshot

    from dagster import AssetExecutionContext

_PROVIDER = "kor-travel-transport"
_DATASET = "transport_airports"
_MAX_ITEMS = 2730
_MAX_REPLANS = 3


@dataclass(frozen=True)
class _StoredSealedReceipt:
    """같은 statement의 durable child_sealed read proof만 사용한다. 새 완료 생성은 없다."""

    receipt: bytes

    async def complete_provider_snapshot_postprocess(
        self, intent: AirportPostprocessIntent
    ) -> bytes:
        if intent.receipt_candidate != self.receipt:
            raise UnsupportedAirportPostprocess("sealed receipt differs from the original input")
        return self.receipt


def _intent(
    observed: RecoveredProviderSnapshot,
    member: AirportPostprocessMember,
    runtime: AirportSnapshotRuntime,
    root_run_id: str,
) -> AirportPostprocessIntent:
    if observed.applied_result_bytes is None:
        raise SnapshotRecoveryCorruption("snapshot has no original complete apply result")
    return prepare_airport_snapshot_postprocess(
        member=member,
        artifact_bytes=observed.artifact_payload,
        context_bytes=observed.observation_context,
        result_bytes=observed.applied_result_bytes,
        expected_pins=runtime.pins,
        expected_root_run_id=root_run_id,
    )


async def _resume(
    client: AsyncKorTravelMapClient,
    identity: SnapshotMember,
    member: AirportPostprocessMember,
    runtime: AirportSnapshotRuntime,
    root_run_id: str,
    observed: RecoveredProviderSnapshot,
    previous: SnapshotExecutorToken | None = None,
) -> DagsterFeatureLoadResult:
    for _ in range(_MAX_REPLANS):
        if observed.status == "child_sealed":
            if observed.postprocess_receipt is None:
                raise SnapshotRecoveryCorruption("sealed snapshot has no postprocess receipt")
            intent = _intent(observed, member, runtime, root_run_id)
            complete = await complete_airport_snapshot_postprocess(
                _StoredSealedReceipt(observed.postprocess_receipt), intent
            )
            return complete.result
        lease = await io.claim_airport_snapshot(client, observed, previous=previous)
        previous = lease.token
        if observed.status == "prepared":
            try:
                plan = await io.plan_airport_snapshot(
                    client,
                    observed,
                    lease.token,
                    pins=runtime.pins,
                    dataset_id=member.membership.provider_dataset_id,
                )
                await io.apply_airport_snapshot(
                    client, observed, lease.token, plan, pins=runtime.pins
                )
            except io.AirportSnapshotReplanRequired:
                # 증명된 rollback 뒤에도 현재 binding을 다시 읽는다. active plan의
                # reset 55P03은 step에 전파하며 임의 cancel/owner 교체로 우회하지 않는다.
                fresh = await io.read_airport_snapshot(client, identity, pins=runtime.pins)
                if fresh is None:
                    raise SnapshotRecoveryCorruption("registered snapshot disappeared") from None
                await io.reset_airport_snapshot_plan(client, fresh, lease.token)
                fresh = await io.read_airport_snapshot(client, identity, pins=runtime.pins)
                if fresh is None:
                    raise SnapshotRecoveryCorruption("registered snapshot disappeared") from None
                observed = fresh
                continue
            fresh = await io.read_airport_snapshot(client, identity, pins=runtime.pins)
            if fresh is None:
                raise SnapshotRecoveryCorruption("applied snapshot disappeared")
            observed = fresh
        intent = _intent(observed, member, runtime, root_run_id)
        complete = await complete_airport_snapshot_postprocess(
            AirportSnapshotBackend(client, lease.token), intent
        )
        await io.seal_airport_snapshot(
            client,
            lease.token,
            artifact_sha256=observed.artifact_sha256,
            context_sha256=observed.context_sha256,
            result_sha256=hashlib.sha256(intent.result_bytes).hexdigest(),
            postprocess_sha256=hashlib.sha256(complete.receipt).hexdigest(),
        )
        return complete.result
    raise io.AirportSnapshotUnavailable("airport snapshot replan budget exhausted")


async def _collect_or_legacy(
    context: AssetExecutionContext,
    client: AsyncKorTravelMapClient,
    member: AirportPostprocessMember,
    runtime: AirportSnapshotRuntime,
) -> tuple[bytes | None, bytes | None, DagsterFeatureLoadResult | None]:
    # assets는 entry에서 이 모듈을 지연 import한다. 원 converter/Geo/fallback을 그대로 쓴다.
    from . import assets

    fetched_at = await assets._fetched_at(context)
    batches = assets._record_batches(context, _DATASET, batch_size=100).__aiter__()
    legacy: list[FeatureBundle] = []

    async def converted() -> AsyncIterator[Sequence[FeatureBundle]]:
        async for records in batches:
            yield await assets._transform_reusing_geo(
                context,
                airports_to_bundles,
                records,
                fetched_at=fetched_at,
                reverse_geocoder=assets._reverse_geocoder(context),
            )

    stream = converted().__aiter__()

    async def fallback() -> DagsterFeatureLoadResult:
        async def replay() -> AsyncIterator[Sequence[FeatureBundle]]:
            if legacy:
                yield legacy
            async for batch in stream:
                yield batch

        return await assets._load_snapshot_batches(
            context,
            provider=_PROVIDER,
            dataset_key=_DATASET,
            batches=replay(),
            geo_applied=GeoApplied(reverse=True, geocode=False),
        )

    async for batch in stream:
        legacy.extend(batch)
        if len(legacy) > _MAX_ITEMS or not within_place_projection_budget(tuple(legacy)):
            return None, None, await fallback()
    # presence는 같은 Transport 정본 normalizer 선언만 재사용한다. 원 EX tuple은 보존한다.
    native = tuple(
        b.model_copy(update={"provider_field_presence": _presence(_DATASET)}) for b in legacy
    )
    geo_inputs = await assets._geo_run_inputs(context, GeoApplied(reverse=True, geocode=False))
    geo = _geo_load_context(**geo_inputs)
    generation = _dagster_run_id(context)
    if generation is None:
        return None, None, await fallback()
    try:
        payload = encode_provider_snapshot_artifact(native, geo, pins=runtime.pins)
        observation = encode_airport_observation_context(
            payload,
            pins=runtime.pins,
            root_run_id=context.run_id,
            observation_generation=generation,
            upstream_eof=True,
            geo_stats=geo_inputs["geo_stats"],
        )
    except (UnsupportedSnapshotArtifact, UnsupportedAirportObservation):
        return None, None, await fallback()
    preparation = await io.prepare_airport_snapshot_input(
        client, payload, pins=runtime.pins, dataset_id=member.membership.provider_dataset_id
    )
    if preparation.eligible is not True:
        return None, None, await fallback()
    return payload, observation, None


async def _run(context: AssetExecutionContext) -> DagsterFeatureLoadResult | None:
    from . import assets

    client = cast(
        AsyncKorTravelMapClient, assets._resource_object(context, "kor_travel_map_client")
    )
    if getattr(client, "_transaction_bound", None) is not False:
        return None
    guard = assets._resource_object(context, "feature_operation_guard", default=None)
    if not isinstance(guard, FeatureOperationExecutionGuard) or guard.operation_key is None:
        return None
    if guard.trigger_kind != "schedule":
        return None
    if not getattr(context, "run_id", None):
        return None
    guard = await ensure_authoritative_feature_operation_guard(context, boundary="airport_snapshot")
    mutation = await guard.ensure()
    if mutation is None or mutation.operation.dagster_run_id != context.run_id:
        raise io.AirportSnapshotUnavailable("canonical scheduled snapshot root required")
    membership = await assets._exact_sync_membership(
        context,
        client,
        boundary="airport_snapshot",
        provider=_PROVIDER,
        dataset_key=_DATASET,
    )
    matches = [m for m in mutation.operation.members if m.membership == membership]
    if len(matches) != 1:
        raise io.AirportSnapshotUnavailable("canonical single airport member required")
    child = matches[0]
    member = AirportPostprocessMember(
        UUID(mutation.operation.root_job_id),
        UUID(child.job_id),
        UUID(child.import_job_dataset_id),
        membership,
    )
    identity = SnapshotMember(
        member.root_job_id, member.source_job_id, member.import_job_dataset_id
    )
    runtime = assets._resource_object(context, "airport_snapshot_runtime", default=None)
    if runtime is not None and type(runtime) is not AirportSnapshotRuntime:
        raise io.AirportSnapshotUnavailable("verified Airport runtime required")
    # 부재 확인이 새 시계·SDK generator/Geo 소비보다 먼저다. 기본 OFF도 이 조회를 생략하지 않는다.
    observed = await io.read_airport_snapshot(
        client, identity, pins=runtime.pins if runtime else None
    )
    previous = None
    if observed is None:
        if runtime is None:
            return None
        strict = await assets._resource_value(context, "strict_address", default="strict")
        if strict is not True and strict != "strict":
            return None
        await io.collect_expired_airport_snapshots(client)
        payload, observation, fallback_result = await _collect_or_legacy(
            context, client, member, runtime
        )
        if fallback_result is not None:
            return fallback_result
        if payload is None or observation is None:
            raise io.AirportSnapshotUnavailable("complete immutable airport input required")
        registered = await io.register_airport_snapshot(
            client, identity, payload=payload, context=observation, pins=runtime.pins
        )
        previous = registered.token
        # commit 응답 유실은 전파한다. 정상 응답 뒤에도 실제 read 상태만 권위로 쓴다.
        observed = await io.read_airport_snapshot(client, identity, pins=runtime.pins)
        if observed is None:
            raise SnapshotRecoveryCorruption("registered snapshot disappeared")
    if runtime is None:
        raise io.AirportSnapshotUnavailable("registered snapshot requires verified runtime")
    return await _resume(client, identity, member, runtime, context.run_id, observed, previous)


async def run_airport_snapshot_if_supported(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult | None:
    """등록 후에는 오류·취소를 EX/refetch로 바꾸지 않는다. 공식 wrapper가 실패를 기록한다."""
    try:
        return await _run(context)
    except DBAPIError as error:
        cause = getattr(error.orig, "__cause__", None)
        if getattr(cause, "sqlstate", None) == "40001" and getattr(cause, "message", None) == (
            "snapshot executor fence is stale"
        ):
            raise Failure(
                "Airport snapshot executor fence is stale", allow_retries=False
            ) from error
        raise
    except (
        io.AirportSnapshotUnavailable,
        SnapshotRecoveryCorruption,
        UnsupportedSnapshotArtifact,
        UnsupportedAirportObservation,
        UnsupportedAirportPostprocess,
        ProviderSnapshotSuperseded,
    ) as error:
        raise Failure(
            "Airport snapshot requires an official new run", allow_retries=False
        ) from error

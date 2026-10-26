"""Rest의 immutable 단일 window를 선택A로 적용한다. 기본 OFF이며 기존입력은 SDK0 재개한다."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, cast
from uuid import UUID

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client import _rest_snapshot as io
from kortravelmap.client._snapshot_atomic import run_snapshot_apply_postprocess
from kortravelmap.dto.geo_dataset import GeoApplied
from kortravelmap.infra.provider_snapshot_artifact import (
    UnsupportedSnapshotArtifact,
)
from kortravelmap.infra.provider_snapshot_postprocess_repo import ProviderSnapshotSuperseded
from kortravelmap.infra.provider_snapshot_recovery_repo import (
    SnapshotExecutorToken,
    SnapshotMember,
    SnapshotRecoveryCorruption,
)
from kortravelmap.infra.rest_area_snapshot_artifact import encode_rest_area_snapshot_artifact
from kortravelmap.providers.kor_travel_transport_native import _presence
from kortravelmap.providers.krex import rest_areas_to_bundles
from sqlalchemy.exc import DBAPIError

from dagster import Failure

from .etl import DagsterFeatureLoadResult, _dagster_run_id, _geo_load_context
from .feature_operation_tracking import (
    FeatureOperationExecutionGuard,
    _context_run_id,
    ensure_authoritative_feature_operation_guard,
)
from .provider_fetchers import TransportRestExportCapture
from .rest_snapshot_backend import RestSnapshotBackend
from .rest_snapshot_observation import (
    UnsupportedRestObservation,
    encode_rest_observation_context,
)
from .rest_snapshot_postprocess import (
    RestPostprocessIntent,
    RestPostprocessMember,
    UnsupportedRestPostprocess,
    complete_rest_snapshot_postprocess,
    prepare_rest_snapshot_postprocess,
)
from .rest_snapshot_runtime import RestSnapshotRuntime

if TYPE_CHECKING:
    from kortravelmap.infra.provider_snapshot_recovery_repo import RecoveredProviderSnapshot

    from dagster import AssetExecutionContext

_PROVIDER = "kor-travel-transport"
_DATASET = "transport_rest_areas"
_MAX_REPLANS = 3


@dataclass(frozen=True)
class _StoredSealedReceipt:
    """같은 statement의 durable child_sealed read proof만 사용한다. 새 완료 생성은 없다."""

    receipt: bytes

    async def complete_provider_snapshot_postprocess(self, intent: RestPostprocessIntent) -> bytes:
        if intent.receipt_candidate != self.receipt:
            raise UnsupportedRestPostprocess("sealed receipt differs from the original input")
        return self.receipt


def _intent(
    observed: RecoveredProviderSnapshot,
    member: RestPostprocessMember,
    runtime: RestSnapshotRuntime,
    root_run_id: str,
) -> RestPostprocessIntent:
    if observed.applied_result_bytes is None:
        raise SnapshotRecoveryCorruption("snapshot has no original complete apply result")
    return prepare_rest_snapshot_postprocess(
        member=member,
        artifact_bytes=observed.artifact_payload,
        context_bytes=observed.observation_context,
        result_bytes=observed.applied_result_bytes,
        expected_pins=runtime.pins,
        expected_root_run_id=root_run_id,
    )


def _same_snapshot(left: RecoveredProviderSnapshot, right: RecoveredProviderSnapshot) -> bool:
    return (
        left.snapshot_id == right.snapshot_id
        and left.artifact_sha256 == right.artifact_sha256
        and left.context_sha256 == right.context_sha256
    )


def _claim_member_inactive(error: DBAPIError) -> bool:
    cause = getattr(error.orig, "__cause__", None)
    return (
        getattr(error.orig, "sqlstate", None) == "23514"
        and getattr(cause, "sqlstate", None) == "23514"
        and getattr(cause, "constraint_name", None) == "ck_provider_snapshot_member_binding"
        and getattr(cause, "message", None) == "snapshot executor member is no longer active"
    )


async def _sealed_result(
    observed: RecoveredProviderSnapshot,
    member: RestPostprocessMember,
    runtime: RestSnapshotRuntime,
    root_run_id: str,
) -> DagsterFeatureLoadResult:
    if (
        observed.status != "child_sealed"
        or observed.root_status not in {"running", "done"}
        or observed.child_status != "done"
        or observed.cancellation_present
    ):
        raise SnapshotRecoveryCorruption("sealed snapshot is not an active unblocked run member")
    if observed.postprocess_receipt is None:
        raise SnapshotRecoveryCorruption("sealed snapshot has no postprocess receipt")
    intent = _intent(observed, member, runtime, root_run_id)
    complete = await complete_rest_snapshot_postprocess(
        _StoredSealedReceipt(observed.postprocess_receipt), intent
    )
    return complete.result


async def _resume(
    client: AsyncKorTravelMapClient,
    identity: SnapshotMember,
    member: RestPostprocessMember,
    runtime: RestSnapshotRuntime,
    root_run_id: str,
    observed: RecoveredProviderSnapshot,
    previous: SnapshotExecutorToken | None = None,
) -> DagsterFeatureLoadResult:
    for _ in range(_MAX_REPLANS):
        if observed.status == "child_sealed":
            return await _sealed_result(observed, member, runtime, root_run_id)
        try:
            lease = await io.claim_rest_snapshot(client, observed, previous=previous)
        except DBAPIError as error:
            # 다른 worker가 read→claim 사이에 child seal을 commit한 경계만 복구한다.
            # 취소/격리/domain 불일치를 같은 SQLSTATE라는 이유로 완료로 낮추지 않는다.
            if not _claim_member_inactive(error):
                raise
            fresh = await io.read_rest_snapshot(client, identity, pins=runtime.pins)
            if (
                fresh is None
                or not _same_snapshot(observed, fresh)
                or fresh.status != "child_sealed"
                or fresh.root_status not in {"running", "done"}
                or fresh.child_status != "done"
                or fresh.cancellation_present
            ):
                raise
            return await _sealed_result(fresh, member, runtime, root_run_id)
        previous = lease.token
        # claim 이전 관측은 phase/binding 권위가 아니다. 같은 status에서도 다른
        # worker의 reset/replan이 commit했을 수 있어 현재 SDK0 행을 항상 다시 읽는다.
        fresh = await io.read_rest_snapshot(client, identity, pins=runtime.pins)
        if fresh is None or not _same_snapshot(observed, fresh):
            raise SnapshotRecoveryCorruption(
                "claimed snapshot disappeared or input identity changed"
            )
        observed = fresh
        if observed.status == "child_sealed":
            return await _sealed_result(observed, member, runtime, root_run_id)
        if observed.status == "prepared":
            try:
                plan = await io.plan_rest_snapshot(
                    client,
                    observed,
                    lease.token,
                    pins=runtime.pins,
                    dataset_id=member.membership.provider_dataset_id,
                )

                apply = partial(
                    io.apply_rest_snapshot_in_session,
                    observed=observed,
                    token=lease.token,
                    plan=plan,
                    pins=runtime.pins,
                )

                backend = RestSnapshotBackend(member, runtime.pins, root_run_id)
                await run_snapshot_apply_postprocess(
                    client,
                    observed,
                    lease.token,
                    identity,
                    pins=runtime.pins,
                    apply=apply,
                    prepare=backend.prepare,
                )
            except io.RestSnapshotReplanRequired:
                # 증명된 rollback 뒤에도 현재 binding을 다시 읽는다. active plan의
                # reset 55P03은 step에 전파하며 임의 cancel/owner 교체로 우회하지 않는다.
                fresh = await io.read_rest_snapshot(client, identity, pins=runtime.pins)
                if fresh is None:
                    raise SnapshotRecoveryCorruption("registered snapshot disappeared") from None
                await io.reset_rest_snapshot_plan(client, fresh, lease.token)
                fresh = await io.read_rest_snapshot(client, identity, pins=runtime.pins)
                if fresh is None:
                    raise SnapshotRecoveryCorruption("registered snapshot disappeared") from None
                observed = fresh
                continue
            fresh = await io.read_rest_snapshot(client, identity, pins=runtime.pins)
            if fresh is None:
                raise SnapshotRecoveryCorruption("applied snapshot disappeared")
            observed = fresh
        if observed.status == "child_sealed":
            return await _sealed_result(observed, member, runtime, root_run_id)
        # Rest 선택A에서 외부로 보이는 applied-only는 정상 commit 경계가 아니다.
        if observed.status != "postprocessed" or observed.postprocess_receipt is None:
            raise SnapshotRecoveryCorruption("rest snapshot has no atomic postprocess result")
        intent = _intent(observed, member, runtime, root_run_id)
        complete = await complete_rest_snapshot_postprocess(
            _StoredSealedReceipt(observed.postprocess_receipt), intent
        )
        await io.seal_rest_snapshot(
            client,
            lease.token,
            artifact_sha256=observed.artifact_sha256,
            context_sha256=observed.context_sha256,
            result_sha256=hashlib.sha256(intent.result_bytes).hexdigest(),
            postprocess_sha256=hashlib.sha256(complete.receipt).hexdigest(),
        )
        return complete.result
    raise io.RestSnapshotUnavailable("rest snapshot replan budget exhausted")


async def _collect_rest_snapshot_input(
    context: AssetExecutionContext,
    client: AsyncKorTravelMapClient,
    member: RestPostprocessMember,
    runtime: RestSnapshotRuntime,
    *,
    root_run_id: str,
) -> tuple[bytes, bytes]:
    from . import assets
    from .assets import _transform_reusing_geo

    capture = await assets._resource_value(context, "rest_snapshot_input")
    if type(capture) is not TransportRestExportCapture:
        raise io.RestSnapshotUnavailable("typed one-page Rest capture required")
    records = capture.records
    if type(records) is not tuple or not 1 <= len(records) <= 256:
        raise io.RestSnapshotUnavailable("whole nonempty Rest input required")
    legacy = await _transform_reusing_geo(
        context,
        rest_areas_to_bundles,
        records,
        fetched_at=capture.export_window.captured_at,
        reverse_geocoder=assets._reverse_geocoder(context),
    )
    native = tuple(
        b.model_copy(update={"provider_field_presence": _presence(_DATASET)}) for b in legacy
    )
    geo_inputs = await assets._geo_run_inputs(context, GeoApplied(reverse=True, geocode=False))
    geo = _geo_load_context(**geo_inputs)
    generation = _dagster_run_id(context, resolved_run_id=root_run_id)
    if generation is None:
        raise io.RestSnapshotUnavailable("original Rest observation generation required")
    payload = encode_rest_area_snapshot_artifact(native, geo, pins=runtime.pins)
    observation = encode_rest_observation_context(
        payload,
        pins=runtime.pins,
        root_run_id=root_run_id,
        observation_generation=generation,
        upstream_eof=True,
        geo_stats=geo_inputs["geo_stats"],
        export_window=capture.export_window,
    )
    preparation = await io.prepare_rest_snapshot_input(
        client,
        payload,
        pins=runtime.pins,
        dataset_id=member.membership.provider_dataset_id,
    )
    if preparation.eligible is not True:
        raise io.RestSnapshotUnavailable("Rest requires unchanged whole DB membership")
    return payload, observation


async def _run_rest_snapshot(context: AssetExecutionContext) -> DagsterFeatureLoadResult | None:
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
    root_run_id = _context_run_id(context, require_native_run=True)
    if root_run_id is None:
        return None
    guard = await ensure_authoritative_feature_operation_guard(context, boundary="rest_snapshot")
    mutation = await guard.ensure()
    if mutation is None or mutation.operation.dagster_run_id != root_run_id:
        raise io.RestSnapshotUnavailable("canonical scheduled snapshot root required")
    membership = await assets._exact_sync_membership(
        context,
        client,
        boundary="rest_snapshot",
        provider=_PROVIDER,
        dataset_key=_DATASET,
    )
    matches = [m for m in mutation.operation.members if m.membership == membership]
    if len(matches) != 1:
        raise io.RestSnapshotUnavailable("canonical single rest member required")
    child = matches[0]
    member = RestPostprocessMember(
        UUID(mutation.operation.root_job_id),
        UUID(child.job_id),
        UUID(child.import_job_dataset_id),
        membership,
    )
    identity = SnapshotMember(
        member.root_job_id, member.source_job_id, member.import_job_dataset_id
    )
    runtime = assets._resource_object(context, "rest_snapshot_runtime", default=None)
    if runtime is not None and type(runtime) is not RestSnapshotRuntime:
        raise io.RestSnapshotUnavailable("verified Rest runtime required")
    # 부재 확인이 새 시계·SDK generator/Geo 소비보다 먼저다. 기본 OFF도 이 조회를 생략하지 않는다.
    observed = await io.read_rest_snapshot(client, identity, pins=runtime.pins if runtime else None)
    previous = None
    if observed is None:
        if runtime is None:
            return None
        strict = await assets._resource_value(context, "strict_address", default="strict")
        if strict is not True and strict != "strict":
            raise io.RestSnapshotUnavailable("Rest snapshot requires strict validation")
        await io.collect_expired_rest_snapshots(client)
        payload, observation = await _collect_rest_snapshot_input(
            context, client, member, runtime, root_run_id=root_run_id
        )
        registered = await io.register_rest_snapshot(
            client, identity, payload=payload, context=observation, pins=runtime.pins
        )
        previous = registered.token
        # commit 응답 유실은 전파한다. 정상 응답 뒤에도 실제 read 상태만 권위로 쓴다.
        observed = await io.read_rest_snapshot(client, identity, pins=runtime.pins)
        if observed is None:
            raise SnapshotRecoveryCorruption("registered snapshot disappeared")
    if runtime is None:
        raise io.RestSnapshotUnavailable("registered snapshot requires verified runtime")
    return await _resume(client, identity, member, runtime, root_run_id, observed, previous)


async def run_rest_snapshot_if_supported(
    context: AssetExecutionContext,
) -> DagsterFeatureLoadResult | None:
    """등록 후에는 오류·취소를 EX/refetch로 바꾸지 않는다. 공식 wrapper가 실패를 기록한다."""
    try:
        return await _run_rest_snapshot(context)
    except DBAPIError as error:
        cause = getattr(error.orig, "__cause__", None)
        if getattr(cause, "sqlstate", None) == "40001" and getattr(cause, "message", None) == (
            "snapshot executor fence is stale"
        ):
            raise Failure("Rest snapshot executor fence is stale", allow_retries=False) from error
        raise
    except (
        io.RestSnapshotUnavailable,
        SnapshotRecoveryCorruption,
        UnsupportedSnapshotArtifact,
        UnsupportedRestObservation,
        UnsupportedRestPostprocess,
        ProviderSnapshotSuperseded,
    ) as error:
        raise Failure("Rest snapshot requires an official new run", allow_retries=False) from error

"""Airport 재시작의 순수 후처리 intent와 단일 fenced backend 호출. SDK/적재는 없다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from kortravelmap.client import AddressValidationFinding
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.geocoding import GeoCallStats
from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.infra.provider_snapshot_result import (
    SnapshotApplyResult,
    decode_snapshot_apply_result,
)
from kortravelmap.infra.scoped_provider_refresh import _artifact_digest

from .airport_snapshot_observation import (
    RestoredAirportObservation,
    decode_airport_observation_context,
)
from .etl import (
    AddressFindingObservationReceipt,
    DagsterFeatureLoadResult,
    _address_validation_findings,
)

_MAX_BIGINT = 2**63 - 1
_DOMAIN = "airport-snapshot-postprocess-v1"
_ASSET_KEY = "feature_place_transport_airports"


class UnsupportedAirportPostprocess(ValueError):
    """입력/후처리 proof 불일치. 새 완료를 발명하지 않는다."""


@dataclass(frozen=True)
class AirportPostprocessMember:
    """DB가 해석한 canonical IDs. 이 타입 자체는 DB 소속의 증명이 아니다."""

    root_job_id: UUID
    source_job_id: UUID
    import_job_dataset_id: UUID
    membership: ProviderDatasetOperationMembership


@dataclass(frozen=True)
class AirportPostprocessIntent:
    """예상 작업과 receipt 후보이며 완료 증명이 아니다. 내부 mutable 값은 독점 소유한다."""

    member: AirportPostprocessMember
    pins: SnapshotArtifactPins
    root_run_id: str
    artifact_bytes: bytes
    context_bytes: bytes
    result_bytes: bytes
    observation: RestoredAirportObservation
    apply_result: SnapshotApplyResult
    findings: tuple[AddressValidationFinding, ...]
    cursor: dict[str, Any]
    receipt_candidate: bytes


@dataclass(frozen=True)
class AirportPostprocessCompletion:
    """backend의 같은 TX 완료 확인 뒤에만 생성한다. child/root seal은 별도다."""

    receipt: bytes
    result: DagsterFeatureLoadResult
    retired: int
    geo_stats: GeoCallStats | None


class AirportPostprocessCoordinator(Protocol):
    """Root의 snapshot/fence에 결박된 단일 backend transaction 경계."""

    async def complete_provider_snapshot_postprocess(
        self, intent: AirportPostprocessIntent
    ) -> bytes:
        """fence/latest 확인→findings→sync→stale close→typed mark를 같은 TX에 commit한다.

        기존 applied/observation 세대의 최신성은 DB가 확인한다. 이미 postprocessed이면
        같은 receipt를 반환하고 side effect0이다. superseded는 비재시도 오류로 전파한다.
        기존 세 client 메서드를 세 TX로 이어붙이는 구현은 이 계약을 만족하지 않는다.
        """
        ...


def _number(value: Any, *, positive: bool = False) -> int:
    if type(value) is not int or not (int(positive) <= value <= _MAX_BIGINT):
        raise UnsupportedAirportPostprocess("nonnegative PG bigint required")
    return value


def _member(value: AirportPostprocessMember) -> None:
    if type(value) is not AirportPostprocessMember or any(
        type(item) is not UUID
        for item in (value.root_job_id, value.source_job_id, value.import_job_dataset_id)
    ):
        raise UnsupportedAirportPostprocess("canonical UUID binding required")
    member = value.membership
    if type(member) is not ProviderDatasetOperationMembership:
        raise UnsupportedAirportPostprocess("canonical operation membership required")
    _number(member.provider_dataset_id, positive=True)
    if (
        type(member.sync_scope) is not str
        or member.sync_scope != "dataset_wide"
        or type(member.operation_key) is not str
        or not member.operation_key
        or len(member.operation_key) > 256
        or len(member.operation_key.encode("utf-8")) > 256
        or member.operation_key != member.operation_key.strip()
        or not member.operation_key.isprintable()
    ):
        raise UnsupportedAirportPostprocess("bounded Airport whole membership required")


def _finding_set(findings: Sequence[AddressValidationFinding]) -> tuple[int, str]:
    # 정본 client와 같이 마지막 동일 dedupe key를 사용하고 정렬한다. 임의 serializer0.
    unique = {item.dedupe_key: item for item in findings}
    projection = [
        {
            "dedupe_key": item.dedupe_key,
            "violation_type": item.violation_type,
            "severity": item.severity,
            "message": item.message,
            "provider": item.provider,
            "dataset_key": item.dataset_key,
            "source_record_key": item.source_record_key,
            "feature_id": item.feature_id,
            "linked": item.linked,
            "payload": dict(item.payload),
        }
        for _, item in sorted(unique.items())
    ]
    return len(unique), _artifact_digest(["airport-postprocess-findings-v1", projection])


def prepare_airport_snapshot_postprocess(
    *,
    member: AirportPostprocessMember,
    artifact_bytes: bytes,
    context_bytes: bytes,
    result_bytes: bytes,
    expected_pins: SnapshotArtifactPins,
    expected_root_run_id: str,
) -> AirportPostprocessIntent:
    """기존 두 decoder로 원 관측/적용값을 복원한다. 반환 receipt는 아직 후보다."""
    _member(member)
    observation = decode_airport_observation_context(
        context_bytes,
        artifact_bytes,
        expected_pins=expected_pins,
        expected_root_run_id=expected_root_run_id,
    )
    applied = decode_snapshot_apply_result(result_bytes)
    if applied.load.bundles_total != observation.source_observations:
        raise UnsupportedAirportPostprocess(
            "applied bundle count differs from original observation"
        )
    provider = expected_pins.provider
    dataset = expected_pins.dataset_key
    identities = {
        bundle.source_record.source_record_key: (
            bundle.source_record.source_entity_type,
            bundle.source_record.source_entity_id,
        )
        for bundle in observation.artifact.bundles
    }
    findings = tuple(
        _address_validation_findings(
            observation.validation,
            provider=provider,
            dataset_key=dataset,
            loaded_feature_ids={
                bundle.feature.feature_id for bundle in observation.artifact.bundles
            },
            dropped_feature_ids=frozenset(),
            source_identities=identities,
        )
    )
    unique, finding_digest = _finding_set(findings)
    # assets._feature_result_cursor_extra와 같은 여섯 원 counter만 cursor에 사용한다.
    cursor = {
        "loaded_at": observation.fetched_at.isoformat(),
        "asset_key": _ASSET_KEY,
        **{
            name: getattr(applied.load, name)
            for name in (
                "bundles_total",
                "features_inserted",
                "features_updated",
                "source_records_inserted",
                "source_links_inserted",
                "source_links_updated",
            )
        },
    }
    receipt = {
        "version": 1,
        "domain": _DOMAIN,
        "root_job_id": str(member.root_job_id),
        "source_job_id": str(member.source_job_id),
        "import_job_dataset_id": str(member.import_job_dataset_id),
        "root_run_id": observation.root_run_id,
        "artifact_sha256": observation.artifact_sha256,
        "context_sha256": hashlib.sha256(context_bytes).hexdigest(),
        "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "provider_dataset_id": member.membership.provider_dataset_id,
        "sync_scope": member.membership.sync_scope,
        "operation_key": member.membership.operation_key,
        "observation_generation": observation.observation_generation,
        "fetched_at": observation.fetched_at.isoformat(),
        "source_observations": observation.source_observations,
        "findings_observed": len(findings),
        "findings_unique": unique,
        "findings_set_sha256": finding_digest,
        "sync_recorded": True,
        "stale_close_completed": True,
    }
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(
        "ascii"
    )
    if len(raw) > 4096:
        raise UnsupportedAirportPostprocess("postprocess receipt exceeds4096 bytes")
    return AirportPostprocessIntent(
        member,
        expected_pins,
        observation.root_run_id,
        artifact_bytes,
        context_bytes,
        result_bytes,
        observation,
        applied,
        findings,
        cursor,
        raw,
    )


async def complete_airport_snapshot_postprocess(
    coordinator: AirportPostprocessCoordinator,
    intent: AirportPostprocessIntent,
) -> AirportPostprocessCompletion:
    """canonical intent를 새로 복원해 단일 coordinator에 보낸다. 실패/취소는 그대로 전파한다."""
    if type(intent) is not AirportPostprocessIntent:
        raise UnsupportedAirportPostprocess("canonical postprocess intent required")
    if type(intent.receipt_candidate) is not bytes:
        raise UnsupportedAirportPostprocess("canonical receipt candidate bytes required")
    # caller가 변경한 nested DTO/Stats/cursor/finding을 backend에 넘기지 않는다.
    canonical = prepare_airport_snapshot_postprocess(
        member=intent.member,
        artifact_bytes=intent.artifact_bytes,
        context_bytes=intent.context_bytes,
        result_bytes=intent.result_bytes,
        expected_pins=intent.pins,
        expected_root_run_id=intent.root_run_id,
    )
    if canonical.receipt_candidate != intent.receipt_candidate:
        raise UnsupportedAirportPostprocess("postprocess binding changed before backend")
    actual = await coordinator.complete_provider_snapshot_postprocess(canonical)
    if type(actual) is not bytes or actual != canonical.receipt_candidate:
        raise UnsupportedAirportPostprocess("backend did not prove exact postprocess receipt")
    # backend에 준 가변 DTO/Stats와 완료 반환값도 alias를 공유하지 않는다.
    canonical = prepare_airport_snapshot_postprocess(
        member=intent.member,
        artifact_bytes=intent.artifact_bytes,
        context_bytes=intent.context_bytes,
        result_bytes=intent.result_bytes,
        expected_pins=intent.pins,
        expected_root_run_id=intent.root_run_id,
    )
    observation = canonical.observation
    unique, _ = _finding_set(canonical.findings)
    result = DagsterFeatureLoadResult(
        provider=canonical.pins.provider,
        dataset_key=canonical.pins.dataset_key,
        feature_ids=tuple(bundle.feature.feature_id for bundle in observation.artifact.bundles),
        load=canonical.apply_result.load,
        address_validation=observation.validation,
        observation_receipt=AddressFindingObservationReceipt(
            authoritative_snapshot_complete=True,
            source_observations=observation.source_observations,
            findings_observed=len(canonical.findings),
            findings_unique=unique,
            findings_upserted=unique,
            finding_persistence_complete=True,
        ),
    )
    return AirportPostprocessCompletion(
        actual,
        result,
        canonical.apply_result.retired,
        observation.geo_stats,
    )

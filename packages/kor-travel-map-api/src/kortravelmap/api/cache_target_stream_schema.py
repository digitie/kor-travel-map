"""Pydantic schemas for ADR-081 cache-target service and ops APIs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from kortravelmap.api.response import Meta

MERKLE_ROOT_PATTERN = r"^[0-9a-f]{64}$"

__all__ = [
    "CacheTargetAckRequest",
    "CacheTargetAckRecord",
    "CacheTargetActiveReconciliation",
    "CacheTargetAppliedReceipt",
    "CacheTargetClaimRequest",
    "CacheTargetClaimRecord",
    "CacheTargetClaimResponse",
    "CacheTargetDeadLetterDetailResponse",
    "CacheTargetDeadLetterListResponse",
    "CacheTargetDeadLetterListData",
    "CacheTargetDeadLetterRecord",
    "CacheTargetDeadLetterReplayRequest",
    "CacheTargetDeliveryResponse",
    "CacheTargetDeliveryRecord",
    "CacheTargetEventRecord",
    "CacheTargetNackRequest",
    "CacheTargetOperationResponse",
    "CacheTargetReconciledPayload",
    "CacheTargetRecoveryOperationRecord",
    "CacheTargetReconciliationBeginRequest",
    "CacheTargetReconciliationRequest",
    "CacheTargetReconciliationCompletionRequest",
    "CacheTargetReconciliationPreparing",
    "CacheTargetReconciliationRunning",
    "CacheTargetReconciliationSealRequest",
    "CacheTargetRefreshRequest",
    "CacheTargetRefreshRequestRecord",
    "CacheTargetRefreshRequestResponse",
    "CacheTargetSnapshotResponse",
    "CacheTargetSnapshotData",
    "CacheTargetSnapshotRow",
    "CacheTargetSnapshotStatus",
    "CacheTargetSourceDeleteRequest",
    "CacheTargetSourceMutationResponse",
    "CacheTargetSourceRecord",
    "CacheTargetSourceUpsertRequest",
    "CacheTargetStreamControlResponse",
    "CacheTargetStreamStatusListResponse",
    "CacheTargetStreamStatusListData",
    "CacheTargetStreamStatusRecord",
    "CacheTargetRestoreFenceRequest",
    "CacheTargetRestoreFenceResponse",
]

CacheTargetEventType = Literal[
    "cache_target.state_applied",
    "cache_target.links_reconciled",
    "refresh_request.status_changed",
    "cache_target.reconciled",
]
CacheTargetEventScope = Literal["target", "stream"]
CacheTargetSourceState = Literal["active", "deleted"]
CacheTargetStreamState = Literal[
    "active",
    "blocked",
    "disabled",
    "fenced",
    "ready",
    "restore_fenced",
]
CacheTargetNackDisposition = Literal["transient", "permanent"]


def _reject_float(value: object, *, field: str) -> object:
    if isinstance(value, float):
        raise ValueError(f"{field}는 float JSON number가 아니라 10진 문자열이어야 합니다.")
    return value


class CacheTargetDecimalCoordinate(BaseModel):
    """Input-only lon/lat values for canonical source hashing."""

    model_config = ConfigDict(extra="forbid")

    lon: Decimal | int | str
    lat: Decimal | int | str

    @field_validator("lon", "lat", mode="before")
    @classmethod
    def _validate_decimal_input(cls, value: object) -> object:
        return _reject_float(value, field="coord")


class CacheTargetSourceUpsertRequest(BaseModel):
    """Service desired-state active source event."""

    model_config = ConfigDict(extra="forbid")

    source_event_id: UUID
    restore_epoch: int = Field(ge=1)
    source_generation: int = Field(ge=1)
    coord: CacheTargetDecimalCoordinate
    radius_km: Decimal | int | str
    update_enabled: bool = True
    occurred_at: datetime

    @field_validator("radius_km", mode="before")
    @classmethod
    def _validate_radius_input(cls, value: object) -> object:
        return _reject_float(value, field="radius_km")


class CacheTargetSourceDeleteRequest(BaseModel):
    """Service desired-state tombstone source event."""

    model_config = ConfigDict(extra="forbid")

    source_event_id: UUID
    restore_epoch: int = Field(ge=1)
    source_generation: int = Field(ge=1)
    occurred_at: datetime


class CacheTargetSourceRecord(BaseModel):
    """Target source projection representation."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    target_key: str
    state: CacheTargetSourceState
    restore_epoch: int = Field(ge=1)
    source_generation: int = Field(ge=1)
    source_payload_fingerprint: str = Field(min_length=64, max_length=64)
    entity_tag: str | None = None
    target_id: str | None = None
    target_sequence: int | None = Field(default=None, ge=0)
    occurred_at: datetime | None = None
    updated_at: datetime | None = None


class CacheTargetSourceMutationResponse(BaseModel):
    """Service target PUT/DELETE response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetSourceRecord
    meta: Meta


class CacheTargetReconciliationPreparing(BaseModel):
    """Snapshot seal 전 recovery request descriptor."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: Literal["preparing"]
    restore_epoch: int = Field(ge=1)
    entity_tag: str
    stream_entity_tag: str
    created_at: datetime


class CacheTargetReconciliationRunning(BaseModel):
    """Consumer가 request-bound fixed snapshot을 찾는 active descriptor."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: Literal["running"]
    snapshot_id: UUID
    restore_epoch: int = Field(ge=1)
    count: int = Field(ge=0)
    merkle_root: str = Field(
        min_length=64,
        max_length=64,
        pattern=MERKLE_ROOT_PATTERN,
    )
    high_watermark_cursor: str
    entity_tag: str
    stream_entity_tag: str
    created_at: datetime


CacheTargetActiveReconciliation = Annotated[
    CacheTargetReconciliationPreparing | CacheTargetReconciliationRunning,
    Field(discriminator="status"),
]


class CacheTargetStreamControlRecord(BaseModel):
    """External-system stream control."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    restore_epoch: int = Field(ge=1)
    control_version: int = Field(ge=1)
    entity_tag: str
    state: CacheTargetStreamState = "active"
    consumer_id: str | None = None
    blocked_event_id: UUID | None = None
    active_reconciliation: CacheTargetActiveReconciliation | None = None
    updated_at: datetime | None = None


class CacheTargetStreamControlResponse(BaseModel):
    """Service stream control response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetStreamControlRecord
    meta: Meta


class CacheTargetRestoreFenceRequest(BaseModel):
    """Restore-fence command body."""

    model_config = ConfigDict(extra="forbid")

    consumer_id: str
    expected_restore_epoch: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class CacheTargetRestoreFenceResponse(BaseModel):
    """Restore-fence command result."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetStreamControlRecord
    meta: Meta


class CacheTargetRefreshRequest(BaseModel):
    """Service refresh request creation body."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    target_keys: list[str] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)


class CacheTargetRefreshRequestRecord(BaseModel):
    """Refresh request status."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    status: str
    status_url: str
    retry_after_seconds: int | None = Field(default=None, ge=1)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CacheTargetRefreshRequestResponse(BaseModel):
    """Service refresh request response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetRefreshRequestRecord
    meta: Meta


class CacheTargetEventCoordinate(BaseModel):
    """Canonical fixed-point coordinate in a target source event."""

    model_config = ConfigDict(extra="forbid")

    lon_e6: int
    lat_e6: int


class CacheTargetStateAppliedTarget(BaseModel):
    """Applied active target projection embedded in an outbox event."""

    model_config = ConfigDict(extra="forbid")

    target_id: UUID
    entity_tag: str
    coord: CacheTargetEventCoordinate
    radius_m: int = Field(ge=0)
    update_enabled: bool


class CacheTargetStateAppliedPayload(BaseModel):
    """Exact payload for ``cache_target.state_applied``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["cache-target-event-v1"]
    state: Literal["active", "deleted"]
    source_event_id: UUID
    target: CacheTargetStateAppliedTarget | None

    @model_validator(mode="after")
    def _validate_target_state(self) -> CacheTargetStateAppliedPayload:
        if self.state == "active" and self.target is None:
            raise ValueError("active state event에는 target이 필요합니다.")
        if self.state == "deleted" and self.target is not None:
            raise ValueError("deleted state event의 target은 null이어야 합니다.")
        return self


class CacheTargetLinksReconciledPayload(BaseModel):
    """Exact payload for ``cache_target.links_reconciled``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["cache-target-event-v1"]
    request_id: UUID
    job_id: UUID
    status: Literal["reconciled"]
    target_id: UUID
    active_link_count: int = Field(ge=0)


class CacheTargetRefreshStatusChangedPayload(BaseModel):
    """Exact payload for ``refresh_request.status_changed``."""

    model_config = ConfigDict(extra="forbid")

    version: Literal["cache-target-event-v1"]
    request_id: UUID
    job_id: UUID
    status: Literal["queued", "running", "done", "failed", "cancelled"]
    target_id: UUID
    error_code: str | None


class CacheTargetReconciledPayload(BaseModel):
    """Exact request-bound fixed snapshot reconciliation receipt."""

    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    snapshot_id: UUID
    actual_merkle_root: str = Field(
        min_length=64,
        max_length=64,
        pattern=MERKLE_ROOT_PATTERN,
    )
    expected_merkle_root: str = Field(
        min_length=64,
        max_length=64,
        pattern=MERKLE_ROOT_PATTERN,
    )
    status: Literal["succeeded"]
    version: Literal["cache-target-reconciliation-v1"]


CacheTargetEventPayload = (
    CacheTargetStateAppliedPayload
    | CacheTargetLinksReconciledPayload
    | CacheTargetRefreshStatusChangedPayload
    | CacheTargetReconciledPayload
)


def _validate_cache_target_event_scope(
    *,
    event_scope: CacheTargetEventScope,
    event_type: CacheTargetEventType,
    target_key: str | None,
    target_id: str | None,
    source_generation: int | None,
    target_sequence: int | None,
) -> None:
    if event_scope == "stream":
        if event_type != "cache_target.reconciled":
            raise ValueError("stream-scoped cache target events must be reconciled events.")
        if (
            target_key is not None
            or target_id is not None
            or source_generation is not None
            or target_sequence is not None
        ):
            raise ValueError(
                "stream-scoped cache target events cannot include target tuple fields."
            )
        return

    if event_type == "cache_target.reconciled":
        raise ValueError("reconciled cache target events must be stream-scoped.")
    if (
        target_key is None
        or target_id is None
        or source_generation is None
        or target_sequence is None
    ):
        raise ValueError("target-scoped cache target events require target tuple fields.")


class CacheTargetEventRecord(BaseModel):
    """Outbox event delivered to a consumer."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_scope: CacheTargetEventScope
    event_type: CacheTargetEventType
    external_system: str
    target_key: str | None = None
    target_id: str | None = None
    restore_epoch: int = Field(ge=1)
    source_generation: int | None = Field(default=None, ge=1)
    target_sequence: int | None = Field(default=None, ge=0)
    relay_order: int = Field(ge=1)
    cursor: str
    source_payload_fingerprint: str = Field(min_length=64, max_length=64)
    payload_fingerprint: str = Field(min_length=64, max_length=64)
    payload: CacheTargetEventPayload
    occurred_at: datetime

    @model_validator(mode="after")
    def _validate_event_scope(self) -> CacheTargetEventRecord:
        _validate_cache_target_event_scope(
            event_scope=self.event_scope,
            event_type=self.event_type,
            target_key=self.target_key,
            target_id=self.target_id,
            source_generation=self.source_generation,
            target_sequence=self.target_sequence,
        )
        payload_types: dict[CacheTargetEventType, type[BaseModel]] = {
            "cache_target.state_applied": CacheTargetStateAppliedPayload,
            "cache_target.links_reconciled": CacheTargetLinksReconciledPayload,
            "refresh_request.status_changed": CacheTargetRefreshStatusChangedPayload,
            "cache_target.reconciled": CacheTargetReconciledPayload,
        }
        if not isinstance(self.payload, payload_types[self.event_type]):
            raise ValueError("event_type과 payload contract가 일치하지 않습니다.")
        return self


class CacheTargetClaimRequest(BaseModel):
    """Consumer pull claim request."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    consumer_id: str
    limit: int = Field(default=100, ge=1, le=500)
    lease_seconds: int = Field(default=60, ge=1, le=300)


class CacheTargetClaimRecord(BaseModel):
    """Claim lease and event page."""

    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    external_system: str
    consumer_id: str
    lease_token: str
    status: str
    first_relay_order: int | None = None
    last_relay_order: int | None = None
    acked_through: str | None = None
    lease_expires_at: datetime
    events: list[CacheTargetEventRecord]
    idempotent_replay: bool = False


class CacheTargetClaimResponse(BaseModel):
    """Consumer claim response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetClaimRecord | None
    meta: Meta


class CacheTargetAppliedReceipt(BaseModel):
    """Consumer-applied event receipt."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    payload_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class CacheTargetAckRequest(BaseModel):
    """ACK contiguous global prefix for a claim."""

    model_config = ConfigDict(extra="forbid")

    consumer_id: str
    claim_id: UUID
    lease_token: UUID
    through_cursor: str
    applied: list[CacheTargetAppliedReceipt] = Field(default_factory=list, max_length=500)

    @field_validator("through_cursor")
    @classmethod
    def _validate_event_cursor(cls, value: str) -> str:
        from kortravelmap.infra import parse_cache_target_event_cursor

        parse_cache_target_event_cursor(value)
        return value


class CacheTargetAckRecord(BaseModel):
    """ACK result."""

    model_config = ConfigDict(extra="forbid")

    claim_id: UUID
    consumer_id: str
    acked_through: str
    accepted_count: int = Field(ge=0)
    status: str


class CacheTargetAckResponse(BaseModel):
    """ACK response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetAckRecord
    meta: Meta


class CacheTargetNackRequest(BaseModel):
    """NACK a claimed event."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    consumer_id: str
    claim_id: UUID
    lease_token: UUID
    event_id: UUID
    disposition: CacheTargetNackDisposition = "transient"
    error_class: str = Field(min_length=1, max_length=128)
    error_code: str | None = Field(default=None, min_length=1, max_length=128)
    error_fingerprint: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    backoff_seconds: int = Field(default=30, ge=1, le=3600)
    max_attempts: int = Field(default=5, ge=1, le=100)


class CacheTargetDeliveryRecord(BaseModel):
    """Mutable delivery state after NACK/replay."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    status: str
    relay_order: int | None = Field(default=None, ge=1)
    delivery_version: int = Field(ge=1)
    entity_tag: str
    retry_after_seconds: int | None = Field(default=None, ge=1)


class CacheTargetDeliveryResponse(BaseModel):
    """NACK/replay service response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetDeliveryRecord
    meta: Meta


class CacheTargetDeadLetterRecord(BaseModel):
    """Dead-letter event detail for service and ops reads."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_scope: CacheTargetEventScope
    event_type: CacheTargetEventType
    external_system: str | None = None
    relay_order: int = Field(ge=1)
    target_key: str | None = None
    target_id: str | None = None
    restore_epoch: int = Field(ge=1)
    source_generation: int | None = Field(default=None, ge=1)
    target_sequence: int | None = Field(default=None, ge=0)
    attempt_count: int = Field(ge=0)
    error_class: str | None = None
    error_code: str | None = None
    payload_fingerprint: str = Field(min_length=64, max_length=64)
    delivery_version: int = Field(ge=1)
    entity_tag: str
    occurred_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _validate_event_scope(self) -> CacheTargetDeadLetterRecord:
        _validate_cache_target_event_scope(
            event_scope=self.event_scope,
            event_type=self.event_type,
            target_key=self.target_key,
            target_id=self.target_id,
            source_generation=self.source_generation,
            target_sequence=self.target_sequence,
        )
        return self



class CacheTargetDeadLetterListData(BaseModel):
    """Dead-letter list data."""

    model_config = ConfigDict(extra="forbid")

    items: list[CacheTargetDeadLetterRecord]


class CacheTargetDeadLetterListResponse(BaseModel):
    """Dead-letter list response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetDeadLetterListData
    meta: Meta


class CacheTargetDeadLetterDetailResponse(BaseModel):
    """Dead-letter detail response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetDeadLetterRecord
    meta: Meta


class CacheTargetDeadLetterReplayRequest(BaseModel):
    """Replay command body."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)


class CacheTargetSnapshotRow(BaseModel):
    """Fixed snapshot leaf row."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    target_key: str
    state: CacheTargetSourceState
    source_generation: int = Field(ge=1)
    source_payload_fingerprint: str = Field(min_length=64, max_length=64)


class CacheTargetSnapshotData(BaseModel):
    """Fixed snapshot page."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    restore_epoch: int = Field(ge=1)
    high_watermark_cursor: str
    count: int = Field(ge=0)
    merkle_root: str = Field(
        min_length=64,
        max_length=64,
        pattern=MERKLE_ROOT_PATTERN,
    )
    items: list[CacheTargetSnapshotRow]


class CacheTargetSnapshotResponse(BaseModel):
    """Service snapshot response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetSnapshotData
    meta: Meta


class CacheTargetSnapshotStatus(BaseModel):
    """Ops stream status nested snapshot summary."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    count: int = Field(ge=0)
    merkle_root: str = Field(
        min_length=64,
        max_length=64,
        pattern=MERKLE_ROOT_PATTERN,
    )
    high_watermark_cursor: str
    created_at: datetime


class CacheTargetStreamStatusRecord(BaseModel):
    """Ops stream status row."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    restore_epoch: int = Field(ge=1)
    control_version: int = Field(ge=1)
    consumer_enabled: bool
    state: str
    pending_count: int = Field(ge=0)
    leased_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    dead_count: int = Field(ge=0)
    delivered_count: int = Field(ge=0)
    blocked_event_id: UUID | None = None
    last_snapshot: CacheTargetSnapshotStatus | None = None
    updated_at: datetime


class CacheTargetStreamStatusListData(BaseModel):
    """Ops stream status list data."""

    model_config = ConfigDict(extra="forbid")

    items: list[CacheTargetStreamStatusRecord]


class CacheTargetStreamStatusListResponse(BaseModel):
    """Ops stream status list response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetStreamStatusListData
    meta: Meta


class CacheTargetReconciliationRequest(BaseModel):
    """Admin reconciliation command body."""

    model_config = ConfigDict(extra="forbid")

    external_system: str
    reason: str = Field(min_length=1, max_length=1000)


class CacheTargetReconciliationBeginRequest(BaseModel):
    """Service two-phase cutover begin command."""

    model_config = ConfigDict(extra="forbid")

    external_system: str = Field(min_length=1, max_length=112)
    consumer_id: str = Field(min_length=1, max_length=128)
    expected_restore_epoch: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)


class CacheTargetReconciliationSealRequest(BaseModel):
    """Service two-phase cutover seal command."""

    model_config = ConfigDict(extra="forbid")

    external_system: str = Field(min_length=1, max_length=112)
    consumer_id: str = Field(min_length=1, max_length=128)
    expected_restore_epoch: int = Field(ge=1)
    expected_item_count: int = Field(ge=0)
    expected_merkle_root: str = Field(
        min_length=64,
        max_length=64,
        pattern=MERKLE_ROOT_PATTERN,
    )


class CacheTargetReconciliationCompletionRequest(BaseModel):
    """Consumer fixed-snapshot checksum completion receipt."""

    model_config = ConfigDict(extra="forbid")

    external_system: str = Field(min_length=1, max_length=112)
    consumer_id: str = Field(min_length=1, max_length=128)
    snapshot_id: UUID
    expected_restore_epoch: int = Field(ge=1)
    actual_merkle_root: str = Field(
        min_length=64,
        max_length=64,
        pattern=MERKLE_ROOT_PATTERN,
    )


class CacheTargetRecoveryOperationRecord(BaseModel):
    """Accepted recovery operation receipt."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    status: str
    snapshot_id: UUID | None = None
    status_url: str | None = None
    entity_tag: str | None = None
    stream_entity_tag: str | None = None


class CacheTargetOperationResponse(BaseModel):
    """Recovery operation response."""

    model_config = ConfigDict(extra="forbid")

    data: CacheTargetRecoveryOperationRecord
    meta: Meta

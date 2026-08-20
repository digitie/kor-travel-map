"""M05 Feature 참조 reconciliation의 procedure-only adapter.

Runtime login은 M05 evidence relation을 직접 읽거나 쓰지 않는다. 이 module은
SECURITY DEFINER lease/ACK/preflight receipt를 좁은 typed 값으로 해석한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, NoReturn, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureReferenceReconciliationAck",
    "ManualProviderDedupCase",
    "ManualProviderDedupCaseDetail",
    "ManualProviderDedupCaseResolution",
    "FeatureReferenceReconciliationError",
    "FeatureReferenceReconciliationLease",
    "FeatureReferenceReconciliationPreflight",
    "FeatureReferenceReconciliationUnavailable",
    "FeatureReferenceReconciliationValidationError",
    "ack_feature_reference_reconciliation_event",
    "get_manual_provider_dedup_case",
    "lease_feature_reference_reconciliation_event",
    "list_manual_provider_dedup_cases",
    "preflight_feature_reference_reconciliation_ack",
    "provision_feature_reference_reconciliation_subscription",
    "resolve_manual_provider_dedup_case",
]


class FeatureReferenceReconciliationError(RuntimeError):
    """M05 procedure 결과가 API 계약을 위반했다."""


class FeatureReferenceReconciliationValidationError(ValueError):
    """allow-list된 M05 input/lease conflict 진단이다."""


class FeatureReferenceReconciliationUnavailable(RuntimeError):
    """paired consumer subscription이 아직 provision되지 않았다."""


@dataclass(frozen=True, slots=True)
class FeatureReferenceReconciliationLease:
    outcome: str
    lease_epoch: int | None
    lease_expires_at: datetime | None
    event_id: UUID | None
    event_sequence: int | None
    case_id: UUID | None
    resolution_id: UUID | None
    action: str | None
    event_payload: Mapping[str, Any] | None
    event_sha256: str | None
    occurred_at: datetime | None


@dataclass(frozen=True, slots=True)
class FeatureReferenceReconciliationPreflight:
    outcome: str
    acked_through_sequence: int | None


@dataclass(frozen=True, slots=True)
class FeatureReferenceReconciliationAck:
    outcome: str
    acked_through_sequence: int | None


@dataclass(frozen=True, slots=True)
class FeatureReferenceReconciliationSubscriptionProvision:
    outcome: str
    initial_event_sequence: int | None


@dataclass(frozen=True, slots=True)
class ManualProviderDedupCase:
    case_id: UUID
    status: str
    created_at: datetime
    evidence_fingerprint: str
    manual_feature: Mapping[str, Any]
    provider_feature: Mapping[str, Any]
    scores: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ManualProviderDedupCaseDetail:
    data: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ManualProviderDedupCaseResolution:
    outcome: str
    resolution_id: UUID | None
    event_id: UUID | None
    manual_feature_id: str | None
    manual_feature_row_revision: int | None


_LEASE_SQL: Final = """
CALL feature.lease_feature_reference_reconciliation_event_v2(
    CAST(:principal_id AS text), CAST(:worker_id AS uuid),
    NULL::text, NULL::bigint, NULL::timestamptz, NULL::uuid,
    NULL::bigint, NULL::uuid, NULL::uuid, NULL::text, NULL::jsonb,
    NULL::text, NULL::timestamptz
)
"""
_ACK_PREFLIGHT_SQL: Final = """
SELECT * FROM feature.preflight_feature_reference_reconciliation_ack_v2(
    CAST(:principal_id AS text), CAST(:event_id AS uuid),
    CAST(:event_sha256 AS text), CAST(:local_receipt_sha256 AS text)
)
"""
_ACK_SQL: Final = """
CALL feature.ack_feature_reference_reconciliation_event_v2(
    CAST(:principal_id AS text), CAST(:event_id AS uuid), CAST(:worker_id AS uuid),
    CAST(:lease_epoch AS bigint), CAST(:event_sha256 AS text),
    CAST(:local_receipt_sha256 AS text), CAST(:command_id AS bigint),
    NULL::text, NULL::bigint
)
"""
_SUBSCRIPTION_PROVISION_SQL: Final = """
CALL feature.provision_feature_reference_reconciliation_subscription(
    CAST(:principal_id AS text), CAST(:initial_event_sequence AS bigint),
    CAST(:actor AS text), CAST(:command_id AS bigint), NULL::text, NULL::bigint
)
"""
_LIST_CASES_SQL: Final = """
SELECT * FROM feature.list_manual_provider_dedup_cases(
    CAST(:status AS text), CAST(:after_created_at AS timestamptz),
    CAST(:after_case_id AS uuid), CAST(:limit AS integer)
)
"""
_READ_CASE_SQL: Final = """
SELECT * FROM feature.read_manual_provider_dedup_case(CAST(:case_id AS uuid))
"""
_RESOLVE_CASE_SQL: Final = """
CALL feature.resolve_manual_provider_dedup_case(
    CAST(:case_id AS uuid), CAST(:decision AS text),
    CAST(:expected_case_fingerprint AS text),
    CAST(:expected_manual_row_revision AS bigint),
    CAST(:expected_provider_row_revision AS bigint),
    CAST(:survivor_feature_id AS text), CAST(:reason AS text), CAST(:actor AS text),
    CAST(:command_id AS bigint), NULL::text, NULL::uuid, NULL::uuid, NULL::text,
    NULL::bigint
)
"""


def _procedure_error(error: DBAPIError) -> NoReturn:
    """DB detail을 노출하지 않는 M05 error allow-list."""

    sqlstate = getattr(getattr(error, "orig", None), "sqlstate", None)
    constraint = getattr(
        getattr(getattr(error, "orig", None), "diag", None), "constraint_name", None
    )
    if sqlstate == "P0002":
        raise FeatureReferenceReconciliationUnavailable(
            "Feature 참조 reconciliation subscription이 아직 provision되지 않았습니다."
        ) from error
    if constraint in {
        "ck_m05_reconciliation_ack_input",
        "ck_m05_reconciliation_lease_input",
        "ck_m05_reconciliation_ack_isolation",
        "ck_m05_reconciliation_lease_isolation",
        "ck_m05_reconciliation_ack_command",
        "ck_m05_case_read_input",
        "ck_m05_decision_input",
        "ck_m05_decision_command",
        "ck_m05_subscription_provision_input",
        "ck_m05_subscription_provision_command",
    } or sqlstate in {"22003", "22P02"}:
        raise FeatureReferenceReconciliationValidationError(
            "Feature 참조 reconciliation 요청 값이 올바르지 않습니다."
        ) from error
    raise FeatureReferenceReconciliationError(
        "Feature 참조 reconciliation writer가 내부 계약을 위반했습니다."
    ) from error


def _uuid_or_none(value: object) -> UUID | None:
    return UUID(str(value)) if value is not None else None


def _int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


async def lease_feature_reference_reconciliation_event(
    session: AsyncSession,
    *,
    principal_id: str,
    worker_id: UUID,
) -> FeatureReferenceReconciliationLease:
    try:
        row = (
            (
                await session.execute(
                    text(_LEASE_SQL),
                    {"principal_id": principal_id, "worker_id": str(worker_id)},
                )
            )
            .mappings()
            .one()
        )
    except DBAPIError as error:
        _procedure_error(error)
    outcome = row.get("o_outcome")
    if outcome not in {"leased", "empty", "lease_conflict", "not_ready"}:
        raise FeatureReferenceReconciliationError("lease receipt outcome이 올바르지 않습니다.")
    payload = row.get("o_event_payload")
    if payload is not None and not isinstance(payload, Mapping):
        raise FeatureReferenceReconciliationError("lease event payload가 올바르지 않습니다.")
    return FeatureReferenceReconciliationLease(
        outcome=outcome,
        lease_epoch=_int_or_none(row.get("o_lease_epoch")),
        lease_expires_at=(
            row.get("o_lease_expires_at")
            if isinstance(row.get("o_lease_expires_at"), datetime)
            else None
        ),
        event_id=_uuid_or_none(row.get("o_event_id")),
        event_sequence=_int_or_none(row.get("o_event_sequence")),
        case_id=_uuid_or_none(row.get("o_case_id")),
        resolution_id=_uuid_or_none(row.get("o_resolution_id")),
        action=str(row["o_action"]) if row.get("o_action") is not None else None,
        event_payload=cast(Mapping[str, Any] | None, payload),
        event_sha256=(
            str(row["o_event_sha256"]) if row.get("o_event_sha256") is not None else None
        ),
        occurred_at=(
            row.get("o_occurred_at") if isinstance(row.get("o_occurred_at"), datetime) else None
        ),
    )


async def preflight_feature_reference_reconciliation_ack(
    session: AsyncSession,
    *,
    principal_id: str,
    event_id: UUID,
    event_sha256: str,
    local_receipt_sha256: str,
) -> FeatureReferenceReconciliationPreflight:
    try:
        row = (
            (
                await session.execute(
                    text(_ACK_PREFLIGHT_SQL),
                    {
                        "principal_id": principal_id,
                        "event_id": str(event_id),
                        "event_sha256": event_sha256,
                        "local_receipt_sha256": local_receipt_sha256,
                    },
                )
            )
            .mappings()
            .one()
        )
    except DBAPIError as error:
        _procedure_error(error)
    outcome = row.get("o_outcome")
    if outcome not in {"absent", "replayed", "conflict"}:
        raise FeatureReferenceReconciliationError("ACK preflight receipt가 올바르지 않습니다.")
    return FeatureReferenceReconciliationPreflight(
        outcome=outcome,
        acked_through_sequence=_int_or_none(row.get("o_acked_through_sequence")),
    )


async def ack_feature_reference_reconciliation_event(
    session: AsyncSession,
    *,
    principal_id: str,
    event_id: UUID,
    worker_id: UUID,
    lease_epoch: int,
    event_sha256: str,
    local_receipt_sha256: str,
    command_id: int,
) -> FeatureReferenceReconciliationAck:
    try:
        row = (
            (
                await session.execute(
                    text(_ACK_SQL),
                    {
                        "principal_id": principal_id,
                        "event_id": str(event_id),
                        "worker_id": str(worker_id),
                        "lease_epoch": lease_epoch,
                        "event_sha256": event_sha256,
                        "local_receipt_sha256": local_receipt_sha256,
                        "command_id": command_id,
                    },
                )
            )
            .mappings()
            .one()
        )
    except DBAPIError as error:
        _procedure_error(error)
    outcome = row.get("o_outcome")
    if outcome not in {"acked", "replayed", "conflict", "lease_conflict", "not_next"}:
        raise FeatureReferenceReconciliationError("ACK receipt outcome이 올바르지 않습니다.")
    return FeatureReferenceReconciliationAck(
        outcome=outcome,
        acked_through_sequence=_int_or_none(row.get("o_acked_through_sequence")),
    )


async def provision_feature_reference_reconciliation_subscription(
    session: AsyncSession,
    *,
    principal_id: str,
    initial_event_sequence: int,
    actor: str,
    command_id: int,
) -> FeatureReferenceReconciliationSubscriptionProvision:
    try:
        row = (
            (
                await session.execute(
                    text(_SUBSCRIPTION_PROVISION_SQL),
                    {
                        "principal_id": principal_id,
                        "initial_event_sequence": initial_event_sequence,
                        "actor": actor,
                        "command_id": command_id,
                    },
                )
            )
            .mappings()
            .one()
        )
    except DBAPIError as error:
        _procedure_error(error)
    outcome = row.get("o_outcome")
    if outcome not in {"provisioned", "already_provisioned"}:
        raise FeatureReferenceReconciliationError(
            "Feature 참조 reconciliation subscription receipt가 올바르지 않습니다."
        )
    return FeatureReferenceReconciliationSubscriptionProvision(
        outcome=outcome,
        initial_event_sequence=_int_or_none(row.get("o_initial_event_sequence")),
    )


def _case_from_row(row: Mapping[str, Any]) -> ManualProviderDedupCase:
    created_at = row.get("o_created_at")
    manual_feature = row.get("o_manual_feature")
    provider_feature = row.get("o_provider_feature")
    scores = row.get("o_scores")
    status = row.get("o_status")
    fingerprint = row.get("o_evidence_fingerprint")
    if (
        not isinstance(created_at, datetime)
        or not isinstance(manual_feature, Mapping)
        or not isinstance(provider_feature, Mapping)
        or not isinstance(scores, Mapping)
        or status not in {"pending", "terminal"}
        or not isinstance(fingerprint, str)
    ):
        raise FeatureReferenceReconciliationError(
            "manual/provider dedup case receipt가 불완전합니다."
        )
    return ManualProviderDedupCase(
        case_id=UUID(str(row["o_case_id"])),
        status=status,
        created_at=created_at,
        evidence_fingerprint=fingerprint,
        manual_feature=cast(Mapping[str, Any], manual_feature),
        provider_feature=cast(Mapping[str, Any], provider_feature),
        scores=cast(Mapping[str, Any], scores),
    )


async def list_manual_provider_dedup_cases(
    session: AsyncSession,
    *,
    status: str | None,
    after_created_at: datetime | None,
    after_case_id: UUID | None,
    limit: int,
) -> tuple[ManualProviderDedupCase, ...]:
    try:
        rows = (
            (
                await session.execute(
                    text(_LIST_CASES_SQL),
                    {
                        "status": status,
                        "after_created_at": after_created_at,
                        "after_case_id": str(after_case_id) if after_case_id else None,
                        "limit": limit,
                    },
                )
            )
            .mappings()
            .all()
        )
    except DBAPIError as error:
        _procedure_error(error)
    return tuple(_case_from_row(cast(Mapping[str, Any], row)) for row in rows)


async def get_manual_provider_dedup_case(
    session: AsyncSession, *, case_id: UUID
) -> ManualProviderDedupCaseDetail | None:
    try:
        row = (
            (await session.execute(text(_READ_CASE_SQL), {"case_id": str(case_id)}))
            .mappings()
            .one_or_none()
        )
    except DBAPIError as error:
        _procedure_error(error)
    if row is None:
        return None
    data = row.get("o_data")
    if not isinstance(data, Mapping):
        raise FeatureReferenceReconciliationError(
            "manual/provider dedup case detail이 불완전합니다."
        )
    return ManualProviderDedupCaseDetail(data=cast(Mapping[str, Any], data))


async def resolve_manual_provider_dedup_case(
    session: AsyncSession,
    *,
    case_id: UUID,
    decision: str,
    expected_case_fingerprint: str,
    expected_manual_row_revision: int,
    expected_provider_row_revision: int,
    survivor_feature_id: str | None,
    reason: str,
    actor: str,
    command_id: int,
) -> ManualProviderDedupCaseResolution:
    try:
        row = (
            (
                await session.execute(
                    text(_RESOLVE_CASE_SQL),
                    {
                        "case_id": str(case_id),
                        "decision": decision,
                        "expected_case_fingerprint": expected_case_fingerprint,
                        "expected_manual_row_revision": expected_manual_row_revision,
                        "expected_provider_row_revision": expected_provider_row_revision,
                        "survivor_feature_id": survivor_feature_id,
                        "reason": reason,
                        "actor": actor,
                        "command_id": command_id,
                    },
                )
            )
            .mappings()
            .one()
        )
    except DBAPIError as error:
        _procedure_error(error)
    outcome = row.get("o_outcome")
    if outcome not in {"kept", "merged", "manual_retired", "stale"}:
        raise FeatureReferenceReconciliationError(
            "manual/provider dedup decision receipt가 올바르지 않습니다."
        )
    return ManualProviderDedupCaseResolution(
        outcome=outcome,
        resolution_id=_uuid_or_none(row.get("o_resolution_id")),
        event_id=_uuid_or_none(row.get("o_event_id")),
        manual_feature_id=(
            str(row["o_manual_feature_id"]) if row.get("o_manual_feature_id") is not None else None
        ),
        manual_feature_row_revision=_int_or_none(row.get("o_manual_feature_row_revision")),
    )

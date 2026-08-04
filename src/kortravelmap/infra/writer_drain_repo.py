"""cache-target writer-drain lease의 raw SQL repository.

Dagster mutation과 poll은 API image service가 소유하고, 이 모듈은 짧은 DB
transaction 안의 lease/snapshot/run CAS만 소유한다. raw identity는 이 DB에만
저장하며 command stdout으로 반환하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "WriterDrainConflict",
    "WriterDrainInstigation",
    "WriterDrainInstigationSnapshot",
    "WriterDrainLease",
    "WriterDrainRun",
    "create_writer_drain_lease",
    "get_active_writer_drain_lease",
    "get_writer_drain_instigations",
    "get_writer_drain_lease",
    "get_writer_drain_runs",
    "mark_writer_drain_instigation_paused",
    "mark_writer_drain_instigation_restored",
    "mark_writer_drain_run_dispatched",
    "mark_writer_drain_run_outcome_uncertain",
    "mark_writer_drain_run_terminal",
    "record_writer_drain_failure",
    "reset_writer_drain_begin_receipt",
    "refresh_writer_drain_receipt",
    "reserve_writer_drain_run_cancel",
    "set_writer_drain_receipt",
    "set_writer_drain_state",
    "upsert_writer_drain_run",
]

WriterDrainLeaseState = Literal["draining", "drained", "restoring", "restored"]
WriterDrainReceiptOperation = Literal["begin", "attest", "restore"]
WriterDrainInstigationKind = Literal["schedule", "sensor"]


class WriterDrainConflict(RuntimeError):
    """다른 owner의 active lease 또는 snapshot CAS 충돌."""


@dataclass(frozen=True)
class WriterDrainLease:
    lease_id: UUID
    owner_kind: str
    owner_id: UUID
    state: WriterDrainLeaseState
    snapshot_sha256: str
    receipt_sha256: str | None
    receipt_operation: WriterDrainReceiptOperation | None
    receipt_prior_sha256: str | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    restored_at: datetime | None


@dataclass(frozen=True)
class WriterDrainInstigation:
    lease_id: UUID
    kind: WriterDrainInstigationKind
    selector_id: str
    state_id: str
    origin_id: str
    instigation_name: str
    repository_name: str
    repository_location_name: str
    was_running: bool
    pause_result: str
    paused_at: datetime | None
    restore_result: str
    restored_at: datetime | None


@dataclass(frozen=True)
class WriterDrainInstigationSnapshot:
    """lease 생성 전 수집한 immutable instigation identity/state."""

    kind: WriterDrainInstigationKind
    selector_id: str
    state_id: str
    origin_id: str
    instigation_name: str
    repository_name: str
    repository_location_name: str
    was_running: bool
    pause_result: str
    restore_result: str


@dataclass(frozen=True)
class WriterDrainRun:
    lease_id: UUID
    dagster_run_id: str
    initial_status: str
    cancel_result: str
    cancel_reserved_at: datetime | None
    cancel_dispatched_at: datetime | None
    terminal_status: str | None
    updated_at: datetime


def _lease_from_row(row: Any) -> WriterDrainLease:
    raw_receipt_operation = (
        str(row.receipt_operation) if row.receipt_operation is not None else None
    )
    receipt_operation: WriterDrainReceiptOperation | None = (
        cast(WriterDrainReceiptOperation, raw_receipt_operation)
        if raw_receipt_operation in {"begin", "attest", "restore"}
        else None
    )
    return WriterDrainLease(
        lease_id=UUID(str(row.lease_id)),
        owner_kind=str(row.owner_kind),
        owner_id=UUID(str(row.owner_id)),
        state=cast(WriterDrainLeaseState, str(row.state)),
        snapshot_sha256=str(row.snapshot_sha256),
        receipt_sha256=(str(row.receipt_sha256) if row.receipt_sha256 is not None else None),
        receipt_operation=receipt_operation,
        receipt_prior_sha256=(
            str(row.receipt_prior_sha256) if row.receipt_prior_sha256 is not None else None
        ),
        failure_code=(str(row.failure_code) if row.failure_code is not None else None),
        created_at=row.created_at,
        updated_at=row.updated_at,
        restored_at=row.restored_at,
    )


def _instigation_from_row(row: Any) -> WriterDrainInstigation:
    return WriterDrainInstigation(
        lease_id=UUID(str(row.lease_id)),
        kind=cast(WriterDrainInstigationKind, str(row.kind)),
        selector_id=str(row.selector_id),
        state_id=str(row.state_id),
        origin_id=str(row.origin_id),
        instigation_name=str(row.instigation_name),
        repository_name=str(row.repository_name),
        repository_location_name=str(row.repository_location_name),
        was_running=bool(row.was_running),
        pause_result=str(row.pause_result),
        paused_at=row.paused_at,
        restore_result=str(row.restore_result),
        restored_at=row.restored_at,
    )


def _run_from_row(row: Any) -> WriterDrainRun:
    return WriterDrainRun(
        lease_id=UUID(str(row.lease_id)),
        dagster_run_id=str(row.dagster_run_id),
        initial_status=str(row.initial_status),
        cancel_result=str(row.cancel_result),
        cancel_reserved_at=row.cancel_reserved_at,
        cancel_dispatched_at=row.cancel_dispatched_at,
        terminal_status=(str(row.terminal_status) if row.terminal_status is not None else None),
        updated_at=row.updated_at,
    )


def _one_row_changed(result: CursorResult[Any]) -> bool:
    return result.rowcount == 1


async def get_active_writer_drain_lease(
    session: AsyncSession,
    *,
    lock: bool = False,
) -> WriterDrainLease | None:
    """전역 active lease 하나를 조회한다 (필요하면 row lock)."""

    suffix = " FOR UPDATE" if lock else ""
    result = await session.execute(
        text(
            """
            SELECT lease_id, owner_kind, owner_id, state, snapshot_sha256,
                   receipt_sha256, receipt_operation, receipt_prior_sha256,
                   failure_code, created_at, updated_at, restored_at
            FROM ops.cache_target_writer_drain_leases
            WHERE state IN ('draining', 'drained', 'restoring')
            ORDER BY created_at
            """
            + suffix
        )
    )
    row = result.one_or_none()
    return _lease_from_row(row) if row is not None else None


async def get_writer_drain_lease(
    session: AsyncSession,
    *,
    lease_id: UUID,
    lock: bool = False,
) -> WriterDrainLease | None:
    suffix = " FOR UPDATE" if lock else ""
    result = await session.execute(
        text(
            """
            SELECT lease_id, owner_kind, owner_id, state, snapshot_sha256,
                   receipt_sha256, receipt_operation, receipt_prior_sha256,
                   failure_code, created_at, updated_at, restored_at
            FROM ops.cache_target_writer_drain_leases
            WHERE lease_id = CAST(:lease_id AS uuid)
            """
            + suffix
        ),
        {"lease_id": str(lease_id)},
    )
    row = result.one_or_none()
    return _lease_from_row(row) if row is not None else None


async def create_writer_drain_lease(
    session: AsyncSession,
    *,
    owner_kind: str,
    owner_id: UUID,
    snapshot_sha256: str,
    instigations: tuple[WriterDrainInstigationSnapshot, ...],
) -> WriterDrainLease:
    """draining lease와 immutable instigation snapshot을 한 transaction에 기록한다."""

    inserted = await session.execute(
        text(
            """
            INSERT INTO ops.cache_target_writer_drain_leases (
              owner_kind, owner_id, state, snapshot_sha256
            ) VALUES (
              :owner_kind, CAST(:owner_id AS uuid), 'draining', :snapshot_sha256
            )
            RETURNING lease_id, owner_kind, owner_id, state, snapshot_sha256,
                      receipt_sha256, receipt_operation, receipt_prior_sha256,
                      failure_code, created_at, updated_at, restored_at
            """
        ),
        {
            "owner_kind": owner_kind,
            "owner_id": str(owner_id),
            "snapshot_sha256": snapshot_sha256,
        },
    )
    row = inserted.one()
    lease = _lease_from_row(row)
    if instigations:
        await session.execute(
            text(
                """
                INSERT INTO ops.cache_target_writer_drain_instigations (
                  lease_id, kind, selector_id, state_id, origin_id, instigation_name,
                  repository_name, repository_location_name, was_running,
                  pause_result, restore_result
                ) VALUES (
                  CAST(:lease_id AS uuid), :kind, :selector_id, :state_id, :origin_id,
                  :instigation_name, :repository_name, :repository_location_name,
                  :was_running, :pause_result, :restore_result
                )
                """
            ),
            [
                {
                    "lease_id": str(lease.lease_id),
                    "kind": instigation.kind,
                    "selector_id": instigation.selector_id,
                    "state_id": instigation.state_id,
                    "origin_id": instigation.origin_id,
                    "instigation_name": instigation.instigation_name,
                    "repository_name": instigation.repository_name,
                    "repository_location_name": instigation.repository_location_name,
                    "was_running": instigation.was_running,
                    "pause_result": instigation.pause_result,
                    "restore_result": instigation.restore_result,
                }
                for instigation in instigations
            ],
        )
    return lease


async def get_writer_drain_instigations(
    session: AsyncSession,
    *,
    lease_id: UUID,
) -> tuple[WriterDrainInstigation, ...]:
    result = await session.execute(
        text(
            """
            SELECT lease_id, kind, selector_id, state_id, origin_id, instigation_name,
                   repository_name, repository_location_name, was_running,
                   pause_result, paused_at, restore_result, restored_at
            FROM ops.cache_target_writer_drain_instigations
            WHERE lease_id = CAST(:lease_id AS uuid)
            ORDER BY kind, selector_id
            """
        ),
        {"lease_id": str(lease_id)},
    )
    return tuple(_instigation_from_row(row) for row in result)


async def mark_writer_drain_instigation_paused(
    session: AsyncSession,
    *,
    lease_id: UUID,
    kind: WriterDrainInstigationKind,
    selector_id: str,
    result: Literal["paused", "already_stopped"],
) -> bool:
    changed = await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_instigations
            SET pause_result = :result, paused_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND kind = :kind
              AND selector_id = :selector_id
              AND was_running
              AND pause_result = 'pending'
            """
        ),
        {
            "lease_id": str(lease_id),
            "kind": kind,
            "selector_id": selector_id,
            "result": result,
        },
    )
    return _one_row_changed(cast(CursorResult[Any], changed))


async def mark_writer_drain_instigation_restored(
    session: AsyncSession,
    *,
    lease_id: UUID,
    kind: WriterDrainInstigationKind,
    selector_id: str,
    result: Literal["restored", "already_running"],
) -> bool:
    changed = await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_instigations
            SET restore_result = :result, restored_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND kind = :kind
              AND selector_id = :selector_id
              AND was_running
              AND restore_result = 'not_requested'
            """
        ),
        {
            "lease_id": str(lease_id),
            "kind": kind,
            "selector_id": selector_id,
            "result": result,
        },
    )
    return _one_row_changed(cast(CursorResult[Any], changed))


async def upsert_writer_drain_run(
    session: AsyncSession,
    *,
    lease_id: UUID,
    dagster_run_id: str,
    initial_status: str,
) -> WriterDrainRun:
    result = await session.execute(
        text(
            """
            INSERT INTO ops.cache_target_writer_drain_runs (
              lease_id, dagster_run_id, initial_status
            ) VALUES (
              CAST(:lease_id AS uuid), :dagster_run_id, :initial_status
            )
            ON CONFLICT (lease_id, dagster_run_id) DO UPDATE
            SET updated_at = clock_timestamp()
            RETURNING lease_id, dagster_run_id, initial_status, cancel_result,
                      cancel_reserved_at, cancel_dispatched_at, terminal_status,
                      updated_at
            """
        ),
        {
            "lease_id": str(lease_id),
            "dagster_run_id": dagster_run_id,
            "initial_status": initial_status,
        },
    )
    return _run_from_row(result.one())


async def get_writer_drain_runs(
    session: AsyncSession,
    *,
    lease_id: UUID,
) -> tuple[WriterDrainRun, ...]:
    result = await session.execute(
        text(
            """
            SELECT lease_id, dagster_run_id, initial_status, cancel_result,
                   cancel_reserved_at, cancel_dispatched_at, terminal_status,
                   updated_at
            FROM ops.cache_target_writer_drain_runs
            WHERE lease_id = CAST(:lease_id AS uuid)
            ORDER BY dagster_run_id
            """
        ),
        {"lease_id": str(lease_id)},
    )
    return tuple(_run_from_row(row) for row in result)


async def reserve_writer_drain_run_cancel(
    session: AsyncSession,
    *,
    lease_id: UUID,
    dagster_run_id: str,
) -> bool:
    """terminal cancel의 유일한 dispatch 권한을 CAS로 예약한다."""

    result = await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_runs
            SET cancel_result = 'reserved', cancel_reserved_at = clock_timestamp(),
                updated_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND dagster_run_id = :dagster_run_id
              AND terminal_status IS NULL
              AND cancel_reserved_at IS NULL
              AND cancel_result = 'pending'
            """
        ),
        {"lease_id": str(lease_id), "dagster_run_id": dagster_run_id},
    )
    return _one_row_changed(cast(CursorResult[Any], result))


async def mark_writer_drain_run_terminal(
    session: AsyncSession,
    *,
    lease_id: UUID,
    dagster_run_id: str,
    terminal_status: str,
    dispatched: bool = False,
) -> None:
    await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_runs
            SET terminal_status = :terminal_status,
                cancel_result = 'terminal',
                cancel_dispatched_at = CASE
                  WHEN :dispatched THEN COALESCE(cancel_dispatched_at, clock_timestamp())
                  ELSE cancel_dispatched_at
                END,
                updated_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND dagster_run_id = :dagster_run_id
            """
        ),
        {
            "lease_id": str(lease_id),
            "dagster_run_id": dagster_run_id,
            "terminal_status": terminal_status,
            "dispatched": dispatched,
        },
    )


async def mark_writer_drain_run_dispatched(
    session: AsyncSession,
    *,
    lease_id: UUID,
    dagster_run_id: str,
) -> bool:
    """예약된 one-shot cancel이 Dagster success union을 반환했음을 기록한다."""

    result = await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_runs
            SET cancel_result = 'dispatched', cancel_dispatched_at = clock_timestamp(),
                updated_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND dagster_run_id = :dagster_run_id
              AND cancel_result = 'reserved'
              AND cancel_dispatched_at IS NULL
            """
        ),
        {"lease_id": str(lease_id), "dagster_run_id": dagster_run_id},
    )
    return _one_row_changed(cast(CursorResult[Any], result))


async def mark_writer_drain_run_outcome_uncertain(
    session: AsyncSession,
    *,
    lease_id: UUID,
    dagster_run_id: str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_runs
            SET cancel_result = 'outcome_uncertain', updated_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND dagster_run_id = :dagster_run_id
              AND cancel_result = 'reserved'
            """
        ),
        {"lease_id": str(lease_id), "dagster_run_id": dagster_run_id},
    )


async def set_writer_drain_state(
    session: AsyncSession,
    *,
    lease_id: UUID,
    expected_state: WriterDrainLeaseState,
    state: WriterDrainLeaseState,
) -> bool:
    result = await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_leases
            SET state = :state, updated_at = clock_timestamp(),
                restored_at = CASE WHEN :state = 'restored' THEN clock_timestamp()
                                   ELSE restored_at END,
                failure_code = NULL
            WHERE lease_id = CAST(:lease_id AS uuid) AND state = :expected_state
            """
        ),
        {
            "lease_id": str(lease_id),
            "expected_state": expected_state,
            "state": state,
        },
    )
    return _one_row_changed(cast(CursorResult[Any], result))


async def record_writer_drain_failure(
    session: AsyncSession,
    *,
    lease_id: UUID,
    failure_code: str,
) -> None:
    await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_leases
            SET failure_code = :failure_code, updated_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND state IN ('draining', 'restoring')
            """
        ),
        {"lease_id": str(lease_id), "failure_code": failure_code},
    )


async def set_writer_drain_receipt(
    session: AsyncSession,
    *,
    lease_id: UUID,
    state: Literal["drained", "restored"],
    receipt_sha256: str,
    operation: WriterDrainReceiptOperation,
    prior_receipt_sha256: str | None,
) -> bool:
    expected_state: WriterDrainLeaseState = "draining" if state == "drained" else "restoring"
    result = await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_leases
            SET state = :state,
                receipt_sha256 = :receipt_sha256,
                receipt_operation = :operation,
                receipt_prior_sha256 = :prior_receipt_sha256,
                restored_at = CASE WHEN :state = 'restored' THEN clock_timestamp()
                                   ELSE restored_at END,
                failure_code = NULL,
                updated_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid) AND state = :expected_state
            """
        ),
        {
            "lease_id": str(lease_id),
            "state": state,
            "expected_state": expected_state,
            "receipt_sha256": receipt_sha256,
            "operation": operation,
            "prior_receipt_sha256": prior_receipt_sha256,
        },
    )
    return _one_row_changed(cast(CursorResult[Any], result))


async def refresh_writer_drain_receipt(
    session: AsyncSession,
    *,
    lease_id: UUID,
    receipt_sha256: str,
    operation: WriterDrainReceiptOperation,
    prior_receipt_sha256: str,
) -> bool:
    """drained lease의 attest receipt chain을 원자적으로 전진한다."""

    result = await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_leases
            SET receipt_sha256 = :receipt_sha256,
                receipt_operation = :operation,
                receipt_prior_sha256 = :prior_receipt_sha256,
                failure_code = NULL,
                updated_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND state = 'drained'
              AND receipt_sha256 = :prior_receipt_sha256
            """
        ),
        {
            "lease_id": str(lease_id),
            "receipt_sha256": receipt_sha256,
            "operation": operation,
            "prior_receipt_sha256": prior_receipt_sha256,
        },
    )
    return _one_row_changed(cast(CursorResult[Any], result))


async def reset_writer_drain_begin_receipt(
    session: AsyncSession,
    *,
    lease_id: UUID,
    expected_receipt_sha256: str,
    receipt_sha256: str,
) -> bool:
    """응답 유실 후 같은 owner가 재시작할 begin receipt chain을 원자적으로 재시작한다."""

    result = await session.execute(
        text(
            """
            UPDATE ops.cache_target_writer_drain_leases
            SET receipt_sha256 = :receipt_sha256,
                receipt_operation = 'begin',
                receipt_prior_sha256 = NULL,
                failure_code = NULL,
                updated_at = clock_timestamp()
            WHERE lease_id = CAST(:lease_id AS uuid)
              AND state = 'drained'
              AND receipt_sha256 = :expected_receipt_sha256
            """
        ),
        {
            "lease_id": str(lease_id),
            "expected_receipt_sha256": expected_receipt_sha256,
            "receipt_sha256": receipt_sha256,
        },
    )
    return _one_row_changed(cast(CursorResult[Any], result))

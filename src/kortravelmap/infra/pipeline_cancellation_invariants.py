"""Pipeline cancellation의 정규화 결과와 attempt 종결 불변식."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from kortravelmap.core.pipeline_cancellation_states import PipelineCancellationStatus
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationDetail,
    PipelineCancellationInvariantError,
    PipelineCancellationMember,
    PipelineCancellationRun,
    PipelineCancellationScopeMember,
)

_BASE_TERMINAL_STATUSES = frozenset({"done", "failed", "cancelled"})
_RETRYABLE_ERROR_CODES = frozenset(
    {
        "DAGSTER_TERMINATE_FAILED",
        "DAGSTER_TERMINATION_TIMEOUT",
        "DAGSTER_UNAVAILABLE",
    }
)
_FAILED_ERROR_CODES = frozenset(
    {
        "DAGSTER_RECONCILE_FAILED",
        "PIPELINE_CANCELLATION_INVARIANT",
        "PIPELINE_CANCELLATION_UNSAFE",
    }
)


def _structured_error_code(
    error: Mapping[str, Any] | None,
    *,
    allowed_codes: frozenset[str] | None = None,
) -> str:
    if error is None:
        raise PipelineCancellationInvariantError("structured error is required")
    code = error.get("code")
    message = error.get("message")
    if not isinstance(code, str) or not code.strip():
        raise PipelineCancellationInvariantError(
            "structured error requires a non-empty code"
        )
    if not isinstance(message, str) or not message.strip():
        raise PipelineCancellationInvariantError(
            "structured error requires a non-empty message"
        )
    if allowed_codes is not None and code not in allowed_codes:
        raise PipelineCancellationInvariantError(
            f"error code {code!r} does not match the attempt policy"
        )
    details = error.get("details")
    if details is not None and not isinstance(details, Mapping):
        raise PipelineCancellationInvariantError(
            "structured error details must be an object"
        )
    return code


def _validate_normalized_shapes(detail: PipelineCancellationDetail) -> None:
    member_run_ids = {
        member.dagster_run_id
        for member in detail.members
        if member.dagster_run_id is not None
    }
    run_by_id = {run.dagster_run_id: run for run in detail.runs}
    if member_run_ids != set(run_by_id):
        raise PipelineCancellationInvariantError(
            "normalized cancellation member/run correspondence diverged"
        )
    for member in detail.members:
        if member.result == "pending":
            if member.terminal_status is not None or member.error is not None:
                raise PipelineCancellationInvariantError(
                    "pending member cannot have terminal status or error"
                )
        elif member.result == "cancelled":
            if member.terminal_status != "cancelled" or member.error is not None:
                raise PipelineCancellationInvariantError(
                    "cancelled member requires terminal_status=cancelled and no error"
                )
        elif member.result == "already_terminal":
            if (
                member.terminal_status not in _BASE_TERMINAL_STATUSES
                or member.error is not None
            ):
                raise PipelineCancellationInvariantError(
                    "already_terminal member requires a base terminal status and no error"
                )
        elif member.result == "cancel_failed":
            if member.terminal_status is not None:
                raise PipelineCancellationInvariantError(
                    "cancel_failed member cannot have a terminal status"
                )
            _structured_error_code(member.error)
    for run in detail.runs:
        if run.termination_reserved_at is not None and run.initial_status is None:
            raise PipelineCancellationInvariantError(
                "reserved run requires its first observed status"
            )
        if run.result == "pending":
            if run.terminal_status is not None or run.error is not None:
                raise PipelineCancellationInvariantError(
                    "pending run cannot have terminal status or error"
                )
        elif run.result == "cancelled":
            if run.terminal_status != "CANCELED" or run.error is not None:
                raise PipelineCancellationInvariantError(
                    "cancelled run requires Dagster CANCELED and no error"
                )
        elif run.result == "already_terminal":
            if run.terminal_status not in {None, "SUCCESS", "FAILURE"} or run.error:
                raise PipelineCancellationInvariantError(
                    "already_terminal run has an invalid terminal status/error"
                )
        elif run.result == "cancel_failed":
            if run.terminal_status is not None:
                raise PipelineCancellationInvariantError(
                    "cancel_failed run cannot have a terminal status"
                )
            _structured_error_code(run.error)


def _run_base_mapping(run: PipelineCancellationRun) -> tuple[str, str] | None:
    mapping: dict[tuple[str, str | None], tuple[str, str]] = {
        ("cancelled", "CANCELED"): ("cancelled", "cancelled"),
        ("already_terminal", "SUCCESS"): ("done", "already_terminal"),
        ("already_terminal", "FAILURE"): ("failed", "already_terminal"),
    }
    return mapping.get((run.result, run.terminal_status))


def _validate_resolved_member(
    member: PipelineCancellationMember,
    base: PipelineCancellationScopeMember,
    run_by_id: Mapping[str, PipelineCancellationRun],
    success_tracking_run_ids: frozenset[str],
) -> None:
    if member.result == "cancelled":
        if base.initial_status != "cancelled" or member.terminal_status != "cancelled":
            raise PipelineCancellationInvariantError(
                "cancelled member/base status diverged"
            )
    elif member.result == "already_terminal":
        if base.initial_status != member.terminal_status:
            raise PipelineCancellationInvariantError(
                "already_terminal member/base status diverged"
            )
    else:
        raise PipelineCancellationInvariantError("member is not resolved")

    if member.requires_run_termination:
        if member.dagster_run_id is None:
            raise PipelineCancellationInvariantError(
                "resolved run-backed member requires a frozen Dagster run"
            )
        run = run_by_id[member.dagster_run_id]
        mapping = _run_base_mapping(run)
        if (
            run.result == "already_terminal"
            and run.terminal_status == "SUCCESS"
            and member.terminal_status == "failed"
            and (
                (
                    member.operation_kind == "provider_feature_load"
                    and member.dagster_run_id in success_tracking_run_ids
                )
                or (
                    member.operation_kind == "provider_feature_load_run"
                    and base.current_stage in {"stale_input", "tracking_invariant"}
                )
            )
        ):
            mapping = ("failed", "already_terminal")
        if mapping != (base.initial_status, member.result):
            raise PipelineCancellationInvariantError(
                "run-backed member/base result does not match Dagster terminal result"
            )
    elif member.initial_status == "queued":
        if member.result != "cancelled":
            raise PipelineCancellationInvariantError(
                "queued cancellation requires the explicit no-run DB path"
            )
    elif member.initial_status in _BASE_TERMINAL_STATUSES:
        if (
            member.result != "already_terminal"
            or member.terminal_status != member.initial_status
        ):
            raise PipelineCancellationInvariantError(
                "initially terminal member must remain already_terminal"
            )


def _retry_capable_member(
    member: PipelineCancellationMember,
    run_by_id: Mapping[str, PipelineCancellationRun],
) -> bool:
    if member.dagster_run_id is None:
        return False
    run = run_by_id[member.dagster_run_id]
    if run.result != "cancel_failed":
        return False
    try:
        _structured_error_code(member.error, allowed_codes=_RETRYABLE_ERROR_CODES)
        _structured_error_code(run.error, allowed_codes=_RETRYABLE_ERROR_CODES)
    except PipelineCancellationInvariantError:
        return False
    return True


def _base_matches_frozen_member(
    detail: PipelineCancellationDetail,
    member: PipelineCancellationMember,
    base: PipelineCancellationScopeMember,
) -> bool:
    return (
        base.cancellation_id == detail.attempt.cancellation_id
        and base.initial_status
        in (
            {"queued", "running"}
            if member.initial_status == "queued"
            else {member.initial_status}
        )
        and base.dagster_run_id == member.dagster_run_id
        and base.operation_kind == member.operation_kind
    )


def _definitive_failure_member(
    detail: PipelineCancellationDetail,
    member: PipelineCancellationMember,
    base: PipelineCancellationScopeMember,
    run_by_id: Mapping[str, PipelineCancellationRun],
) -> bool:
    if member.initial_status != "running" and not member.requires_run_termination:
        return False
    try:
        _structured_error_code(member.error, allowed_codes=_FAILED_ERROR_CODES)
    except PipelineCancellationInvariantError:
        return False
    base_mismatch = not _base_matches_frozen_member(detail, member, base)
    if member.dagster_run_id is None:
        return True
    if base_mismatch:
        return True
    run = run_by_id[member.dagster_run_id]
    if run.result != "cancel_failed":
        return False
    try:
        _structured_error_code(run.error, allowed_codes=_FAILED_ERROR_CODES)
    except PipelineCancellationInvariantError:
        return False
    return True


def _validate_finish_invariants(
    detail: PipelineCancellationDetail,
    base_by_key: Mapping[str, PipelineCancellationScopeMember],
    *,
    status: PipelineCancellationStatus,
    error: Mapping[str, Any] | None,
) -> None:
    _validate_normalized_shapes(detail)
    run_by_id = {run.dagster_run_id: run for run in detail.runs}
    pending_members = tuple(
        member for member in detail.members if member.result == "pending"
    )
    failed_members = tuple(
        member for member in detail.members if member.result == "cancel_failed"
    )
    pending_runs = tuple(run for run in detail.runs if run.result == "pending")
    failed_runs = tuple(run for run in detail.runs if run.result == "cancel_failed")
    resolved_members = tuple(
        member
        for member in detail.members
        if member.result in {"cancelled", "already_terminal"}
    )
    success_tracking_run_ids = frozenset(
        member.dagster_run_id
        for member in detail.members
        if member.dagster_run_id is not None
        and member.operation_kind == "provider_feature_load"
        and member.initial_status != "done"
    )
    for member in resolved_members:
        base = base_by_key[member.job_id]
        if (
            base.cancellation_id != detail.attempt.cancellation_id
            or base.dagster_run_id != member.dagster_run_id
        ):
            raise PipelineCancellationInvariantError(
                "resolved member base marker/run mapping diverged"
            )
        _validate_resolved_member(
            member,
            base,
            run_by_id,
            success_tracking_run_ids,
        )

    if status == "completed":
        if error is not None:
            raise PipelineCancellationInvariantError(
                "completed cancellation cannot persist an attempt error"
            )
        if pending_members or failed_members or pending_runs or failed_runs:
            raise PipelineCancellationInvariantError(
                "completed cancellation requires fully terminal member/run results"
            )
        return

    if status == "retryable":
        _structured_error_code(error, allowed_codes=_RETRYABLE_ERROR_CODES)
        if pending_members or pending_runs:
            raise PipelineCancellationInvariantError(
                "retryable cancellation cannot retain pending results"
            )
        if not failed_members:
            raise PipelineCancellationInvariantError(
                "retryable cancellation requires unresolved members"
            )
        if any(not member.requires_run_termination for member in failed_members):
            raise PipelineCancellationInvariantError(
                "cancel_failed is restricted to run-backed active members"
            )
        failed_run_ids = {run.dagster_run_id for run in failed_runs}
        referenced_failed_run_ids = {
            member.dagster_run_id
            for member in failed_members
            if member.dagster_run_id is not None
        }
        if not failed_run_ids.issubset(referenced_failed_run_ids):
            raise PipelineCancellationInvariantError(
                "retryable run failure has no unresolved member"
            )
        if not all(
            _base_matches_frozen_member(
                detail,
                member,
                base_by_key[member.job_id],
            )
            and _retry_capable_member(member, run_by_id)
            for member in failed_members
        ):
            raise PipelineCancellationInvariantError(
                "retryable cancellation requires exact running base/run failures"
            )
        return

    if status == "failed":
        _structured_error_code(error, allowed_codes=_FAILED_ERROR_CODES)
        # Unexpected close may happen between durable phases. Preserve pending rows
        # as the truthful "not authoritatively observed" snapshot. Existing
        # cancel_failed rows may mix retryable transport evidence with a separate
        # definitive mismatch; failed attempts are never automatic retry sources.
        for run in failed_runs:
            code = _structured_error_code(run.error)
            if code not in _RETRYABLE_ERROR_CODES | _FAILED_ERROR_CODES:
                raise PipelineCancellationInvariantError(
                    "failed cancellation contains an unknown run failure policy"
                )
        for member in failed_members:
            if member.initial_status != "running" and not member.requires_run_termination:
                raise PipelineCancellationInvariantError(
                    "cancel_failed is restricted to running or run-backed active members"
                )
            base = base_by_key[member.job_id]
            if _retry_capable_member(member, run_by_id) and _base_matches_frozen_member(
                detail,
                member,
                base,
            ):
                continue
            if _definitive_failure_member(detail, member, base, run_by_id):
                continue
            raise PipelineCancellationInvariantError(
                "failed cancellation has a definitive member mismatch"
            )
        return

    raise PipelineCancellationInvariantError("attempt must close to a terminal workflow status")

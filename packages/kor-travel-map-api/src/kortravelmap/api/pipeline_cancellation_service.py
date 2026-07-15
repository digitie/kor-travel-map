"""Pipeline 계층형 취소 application coordinator.

DB repository는 transaction-local CAS만 소유한다. 이 모듈은 canonical-root lease,
짧은 DB phase, Dagster SAFE_TERMINATE와 crash resume 순서를 소유한다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING, Any, Final

import httpx
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.pipeline_cancellation_repo import (
    PipelineCancellationConflict,
    PipelineCancellationDetail,
    PipelineCancellationInvariantError,
    PipelineCancellationMember,
    cancel_queued_pipeline_cancellation_member,
    create_pipeline_cancellation_attempt,
    finish_pipeline_cancellation_attempt,
    get_current_pipeline_cancellation_summary,
    get_pipeline_cancellation_detail,
    mark_pipeline_cancellation_run_termination_reserved,
    resolve_pipeline_cancellation_scope,
    retry_pipeline_cancellation_attempt,
    set_pipeline_cancellation_member_result,
    set_pipeline_cancellation_run_result,
    transition_pipeline_cancellation_member,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api import dagster_graphql
from kortravelmap.api.pipeline_cancellation_schema import (
    PipelineCancellationDetailRecord,
    PipelineCancellationRootRecord,
    cancellation_detail_record,
)
from kortravelmap.api.settings import ApiSettings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

__all__ = [
    "DagsterTerminateFailed",
    "DagsterTerminationTimeout",
    "DagsterUnavailable",
    "PipelineCancellationInProgress",
    "PipelineCancellationServiceError",
    "PipelineCancellationUnsafe",
    "PipelineExecutionNotFound",
    "cancel_pipeline_execution",
]

_LOG = logging.getLogger(__name__)

_TERMINAL_DAGSTER_STATUSES: Final[frozenset[str]] = frozenset(
    {"CANCELED", "SUCCESS", "FAILURE"}
)
_COORDINATOR_LEASE_PREFIX = "pipeline-cancellation:coordinator"

_RUN_STATUS_QUERY = """
query KorTravelMapCancellationRunStatus($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run { runId status }
    ... on RunNotFoundError { runId message }
    ... on PythonError { message }
  }
}
"""

_TERMINATE_RUN_MUTATION = """
mutation KorTravelMapTerminateRun(
  $runId: String!, $terminatePolicy: TerminateRunPolicy
) {
  terminateRun(runId: $runId, terminatePolicy: $terminatePolicy) {
    __typename
    ... on TerminateRunSuccess { run { runId status } }
    ... on TerminateRunFailure { run { runId status } message }
    ... on RunNotFoundError { runId message }
    ... on UnauthorizedError { message }
    ... on PythonError { message }
  }
}
"""


@dataclass(frozen=True)
class _Failure:
    code: str
    message: str
    details: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass(frozen=True)
class _RunObservation:
    run_id: str
    status: str


class _DagsterFailure(RuntimeError):
    def __init__(self, failure: _Failure) -> None:
        super().__init__(failure.message)
        self.failure = failure


class _DagsterDispatchAmbiguous(_DagsterFailure):
    """terminate request transport가 끊겨 dispatch 여부를 판정할 수 없다."""


class _CoordinatorOwnershipLost(RuntimeError):
    """lease/reservation/CAS ownership이 더 이상 증명되지 않는 내부 중단 신호."""

    def __init__(self, cancellation_id: str | None, message: str) -> None:
        super().__init__(message)
        self.cancellation_id = cancellation_id


def _require_cancellation_write(
    changed: bool,
    *,
    cancellation_id: str,
    message: str,
) -> None:
    if not changed:
        raise _CoordinatorOwnershipLost(cancellation_id, message)


class PipelineCancellationServiceError(Exception):
    """HTTP adapter가 안정적으로 분류할 application error."""

    code = "PIPELINE_CANCELLATION_ERROR"

    def __init__(
        self,
        message: str,
        *,
        root: PipelineCancellationRootRecord | None = None,
        detail: PipelineCancellationDetailRecord | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.root = root
        self.detail = detail
        self.retry_after_seconds = retry_after_seconds


class PipelineExecutionNotFound(PipelineCancellationServiceError):
    code = "PIPELINE_EXECUTION_NOT_FOUND"


class PipelineCancellationInProgress(PipelineCancellationServiceError):
    code = "PIPELINE_CANCELLATION_IN_PROGRESS"


class PipelineCancellationUnsafe(PipelineCancellationServiceError):
    code = "PIPELINE_CANCELLATION_UNSAFE"


class DagsterTerminateFailed(PipelineCancellationServiceError):
    code = "DAGSTER_TERMINATE_FAILED"


class DagsterUnavailable(PipelineCancellationServiceError):
    code = "DAGSTER_UNAVAILABLE"


class DagsterTerminationTimeout(PipelineCancellationServiceError):
    code = "DAGSTER_TERMINATION_TIMEOUT"


def _root_record(kind: str, root_id: str) -> PipelineCancellationRootRecord:
    return PipelineCancellationRootRecord.model_validate({"kind": kind, "id": root_id})


def _detail_record(detail: PipelineCancellationDetail) -> PipelineCancellationDetailRecord:
    record = cancellation_detail_record(detail)
    if record is None:  # pragma: no cover - non-null input의 타입 방어
        raise PipelineCancellationInvariantError("cancellation detail mapping failed")
    return record


def _failure(
    code: str,
    message: str,
    *,
    cancellation_id: str,
    dagster_run_id: str | None = None,
    phase: str,
    typename: str | None = None,
) -> _Failure:
    details: dict[str, Any] = {
        "cancellation_id": cancellation_id,
        "phase": phase,
    }
    if dagster_run_id is not None:
        details["dagster_run_id"] = dagster_run_id
    if typename is not None:
        details["typename"] = typename
    return _Failure(code=code, message=message, details=details)


def _coordinator_lease_key(*, root_kind: str, root_id: str) -> int:
    return advisory_lock_key(
        f"{_COORDINATOR_LEASE_PREFIX}:{root_kind}:{root_id}"
    )


def _assert_no_transaction(session: AsyncSession) -> None:
    if session.in_transaction():
        raise PipelineCancellationInvariantError(
            "external cancellation phase cannot keep a DB transaction open"
        )


async def _rollback_quietly(session: AsyncSession) -> None:
    try:
        if session.in_transaction():
            await session.rollback()
    except BaseException:  # pragma: no cover - broken/cancelled cleanup
        _LOG.warning("pipeline cancellation session rollback failed", exc_info=True)


async def _acquire_coordinator_lease(
    session: AsyncSession,
    *,
    lease_key: int,
) -> bool:
    _assert_no_transaction(session)
    try:
        result = await session.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lease_key},
        )
        acquired = bool(result.scalar_one())
        await session.commit()
        return acquired
    except BaseException:
        await _rollback_quietly(session)
        raise


async def _release_coordinator_lease(
    session: AsyncSession,
    connection: AsyncConnection,
    *,
    lease_key: int,
) -> None:
    """exact-key unlock을 검증하며 불확실한 backend에서 성공을 반환하지 않는다."""
    release_error: BaseException | None = None
    try:
        _assert_no_transaction(session)
        result = await session.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"),
            {"lock_id": lease_key},
        )
        unlocked = bool(result.scalar_one())
        await session.commit()
        if unlocked:
            return
        release_error = PipelineCancellationInvariantError(
            "pipeline cancellation coordinator lease was not owned at unlock"
        )
    except BaseException as exc:
        await _rollback_quietly(session)
        release_error = exc
    assert release_error is not None
    _LOG.error(
        "pipeline cancellation coordinator lease release failed",
        exc_info=(
            type(release_error),
            release_error,
            release_error.__traceback__,
        ),
    )
    await _hard_invalidate_connection(connection, cause=release_error)
    if not isinstance(release_error, Exception):
        raise release_error
    raise PipelineCancellationUnsafe(
        "pipeline cancellation coordinator lease release could not be verified"
    ) from release_error


async def _hard_invalidate_connection(
    connection: AsyncConnection,
    *,
    cause: BaseException,
) -> None:
    """async invalidate 실패에도 pool proxy/driver를 hard terminate한다."""
    pool_proxy: Any = None
    try:
        sync_connection = connection.sync_connection
        if sync_connection is not None:
            candidate = sync_connection.connection
            if candidate is not None:
                pool_proxy = candidate
    except Exception:
        _LOG.warning("failed to capture cancellation lease pool proxy", exc_info=True)

    try:
        await connection.invalidate(cause)
        if connection.invalidated:
            return
    except BaseException:
        _LOG.error("async cancellation lease invalidation failed", exc_info=True)

    if pool_proxy is not None:
        try:
            pool_proxy.invalidate(cause, soft=False)
            return
        except BaseException:
            _LOG.critical("sync hard invalidation failed", exc_info=True)

        try:
            driver_connection = getattr(pool_proxy, "driver_connection", None)
            if driver_connection is None:
                dbapi_connection = getattr(pool_proxy, "dbapi_connection", None)
                driver_connection = getattr(
                    dbapi_connection,
                    "driver_connection",
                    None,
                )
            terminate = getattr(driver_connection, "terminate", None)
            if not callable(terminate):
                raise RuntimeError("physical driver terminate is unavailable")
            terminated = terminate()
            if inspect.isawaitable(terminated):
                await terminated
            return
        except Exception as exc:
            _LOG.critical("physical cancellation backend terminate failed", exc_info=True)
            raise PipelineCancellationUnsafe(
                "failed to hard-invalidate the cancellation coordinator backend"
            ) from exc

    raise PipelineCancellationUnsafe(
        "failed to hard-invalidate the cancellation coordinator backend"
    ) from cause


def _ordered_members(
    detail: PipelineCancellationDetail,
) -> tuple[PipelineCancellationMember, ...]:
    """repo의 request→job writer 순서와 같은 deterministic member 순서."""
    kind_order = {"update_request": 0, "import_job": 1}
    return tuple(
        sorted(
            detail.members,
            key=lambda member: (kind_order[member.member_kind], member.member_id),
        )
    )


async def _current_detail_for_root(
    session: AsyncSession,
    *,
    root_kind: str,
    root_id: str,
) -> PipelineCancellationDetail | None:
    summary = await get_current_pipeline_cancellation_summary(
        session,
        root_kind=root_kind,
        root_id=root_id,
    )
    if summary is None:
        return None
    return await get_pipeline_cancellation_detail(session, summary.cancellation_id)


async def _bounded_current_detail(
    session: AsyncSession,
    *,
    root_kind: str,
    root_id: str,
    settings: ApiSettings,
) -> PipelineCancellationDetail | None:
    detail: PipelineCancellationDetail | None = None
    for index in range(settings.pipeline_cancellation_lease_reload_attempts):
        async with session.begin():
            detail = await _current_detail_for_root(
                session,
                root_kind=root_kind,
                root_id=root_id,
            )
        if detail is not None:
            return detail
        if index + 1 < settings.pipeline_cancellation_lease_reload_attempts:
            await asyncio.sleep(
                settings.pipeline_cancellation_lease_reload_interval_seconds
            )
    return None


async def _prepare_attempt(
    session: AsyncSession,
    *,
    kind: str,
    execution_id: str,
    root_kind: str,
    root_id: str,
    requested_by: str,
    reason: str | None,
    retry_after_seconds: int,
) -> PipelineCancellationDetail | None:
    """lease 아래 canonical root를 재검증하고 attempt를 생성/replay/resume한다."""
    scope = await resolve_pipeline_cancellation_scope(
        session,
        kind=kind,
        execution_id=execution_id,
    )
    if scope is None:
        raise PipelineExecutionNotFound(
            f"pipeline execution not found: {kind}/{execution_id}"
        )
    if (scope.root_kind, scope.root_id) != (root_kind, root_id):
        return None

    current = await _current_detail_for_root(
        session,
        root_kind=root_kind,
        root_id=root_id,
    )
    if current is None:
        return await create_pipeline_cancellation_attempt(
            session,
            scope=scope,
            requested_by=requested_by,
            reason=reason,
        )
    if current.attempt.status == "completed":
        return current
    if current.attempt.status == "in_progress":
        return current
    if current.attempt.status == "retryable":
        return await retry_pipeline_cancellation_attempt(
            session,
            previous_cancellation_id=current.attempt.cancellation_id,
            requested_by=requested_by,
            reason=reason,
        )
    raise PipelineCancellationUnsafe(
        "definitive cancellation failure requires operator intervention",
        root=_root_record(root_kind, root_id),
        detail=_detail_record(current),
        retry_after_seconds=retry_after_seconds,
    )


def _graphql_typename(payload: Mapping[str, Any], field: str) -> tuple[str, dict[str, Any]]:
    raw_errors = payload.get("errors")
    if isinstance(raw_errors, list) and raw_errors:
        raise ValueError("Dagster GraphQL returned top-level errors")
    data = dagster_graphql.as_dict(payload.get("data"))
    value = dagster_graphql.as_dict(data.get(field))
    typename = dagster_graphql.optional_string(value.get("__typename"))
    if typename is None:
        raise ValueError(f"Dagster GraphQL {field} union is malformed")
    return typename, value


async def _post_graphql(
    *,
    http_client: httpx.AsyncClient,
    graphql_url: str,
    query: str,
    variables: dict[str, object],
    failure: _Failure,
    transport_is_ambiguous: bool = False,
) -> Mapping[str, Any]:
    try:
        return await dagster_graphql.post_graphql(
            client=http_client,
            graphql_url=graphql_url,
            query=query,
            variables=variables,
        )
    except httpx.TimeoutException as exc:
        timeout_failure = _Failure(
            code="DAGSTER_TERMINATION_TIMEOUT",
            message="Dagster GraphQL request timed out",
            details=failure.details,
        )
        failure_type = (
            _DagsterDispatchAmbiguous
            if transport_is_ambiguous
            else _DagsterFailure
        )
        raise failure_type(timeout_failure) from exc
    except httpx.RequestError as exc:
        unavailable = _Failure(
            code="DAGSTER_UNAVAILABLE",
            message="Dagster GraphQL is unavailable",
            details=failure.details,
        )
        failure_type = (
            _DagsterDispatchAmbiguous
            if transport_is_ambiguous
            else _DagsterFailure
        )
        raise failure_type(unavailable) from exc
    except (httpx.HTTPStatusError, ValueError) as exc:
        raise _DagsterFailure(failure) from exc


async def _query_run_status(
    *,
    http_client: httpx.AsyncClient,
    graphql_url: str,
    cancellation_id: str,
    run_id: str,
    phase: str,
) -> _RunObservation:
    protocol_failure = _failure(
        "DAGSTER_TERMINATE_FAILED",
        "Dagster run status response is invalid",
        cancellation_id=cancellation_id,
        dagster_run_id=run_id,
        phase=phase,
    )
    payload = await _post_graphql(
        http_client=http_client,
        graphql_url=graphql_url,
        query=_RUN_STATUS_QUERY,
        variables={"runId": run_id},
        failure=protocol_failure,
    )
    try:
        typename, value = _graphql_typename(payload, "runOrError")
    except ValueError as exc:
        raise _DagsterFailure(protocol_failure) from exc
    if typename != "Run":
        raise _DagsterFailure(
            _failure(
                "DAGSTER_TERMINATE_FAILED",
                "Dagster run could not be resolved",
                cancellation_id=cancellation_id,
                dagster_run_id=run_id,
                phase=phase,
                typename=typename,
            )
        )
    observed_id = dagster_graphql.optional_string(value.get("runId"))
    observed_status = dagster_graphql.optional_string(value.get("status"))
    if observed_id != run_id or observed_status is None:
        raise _DagsterFailure(protocol_failure)
    return _RunObservation(run_id=observed_id, status=observed_status.upper())


async def _terminate_run_once(
    *,
    http_client: httpx.AsyncClient,
    graphql_url: str,
    cancellation_id: str,
    run_id: str,
) -> _Failure | None:
    """SAFE_TERMINATE를 한 번 보내고 모호한 transport 원인만 반환한다."""
    protocol_failure = _failure(
        "DAGSTER_TERMINATE_FAILED",
        "Dagster SAFE_TERMINATE failed",
        cancellation_id=cancellation_id,
        dagster_run_id=run_id,
        phase="terminate",
    )
    try:
        payload = await _post_graphql(
            http_client=http_client,
            graphql_url=graphql_url,
            query=_TERMINATE_RUN_MUTATION,
            variables={
                "runId": run_id,
                "terminatePolicy": "SAFE_TERMINATE",
            },
            failure=protocol_failure,
            transport_is_ambiguous=True,
        )
    except _DagsterDispatchAmbiguous as exc:
        # mutation request를 보낸 뒤 응답을 신뢰할 수 없으면 dispatch 여부가 모호하다.
        # 같은 attempt에서 재호출하지 않고 반드시 status poll로 합류한다.
        return exc.failure
    try:
        typename, value = _graphql_typename(payload, "terminateRun")
    except ValueError as exc:
        raise _DagsterFailure(protocol_failure) from exc
    if typename != "TerminateRunSuccess":
        raise _DagsterFailure(
            _failure(
                "DAGSTER_TERMINATE_FAILED",
                "Dagster SAFE_TERMINATE did not succeed",
                cancellation_id=cancellation_id,
                dagster_run_id=run_id,
                phase="terminate",
                typename=typename,
            )
        )
    run = dagster_graphql.as_dict(value.get("run"))
    if dagster_graphql.optional_string(run.get("runId")) != run_id:
        raise _DagsterFailure(protocol_failure)
    return None


async def _poll_terminal_status(
    *,
    http_client: httpx.AsyncClient,
    graphql_url: str,
    cancellation_id: str,
    run_id: str,
    settings: ApiSettings,
) -> _RunObservation:
    deadline = monotonic() + settings.dagster_termination_timeout_seconds
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise _DagsterFailure(
                _failure(
                    "DAGSTER_TERMINATION_TIMEOUT",
                    "Dagster run did not reach a terminal state before the deadline",
                    cancellation_id=cancellation_id,
                    dagster_run_id=run_id,
                    phase="terminal_poll",
                )
            )
        try:
            async with asyncio.timeout(remaining):
                observation = await _query_run_status(
                    http_client=http_client,
                    graphql_url=graphql_url,
                    cancellation_id=cancellation_id,
                    run_id=run_id,
                    phase="terminal_poll",
                )
        except TimeoutError as exc:
            raise _DagsterFailure(
                _failure(
                    "DAGSTER_TERMINATION_TIMEOUT",
                    "Dagster run did not reach a terminal state before the deadline",
                    cancellation_id=cancellation_id,
                    dagster_run_id=run_id,
                    phase="terminal_poll",
                )
            ) from exc
        if observation.status in _TERMINAL_DAGSTER_STATUSES:
            return observation
        remaining = deadline - monotonic()
        await asyncio.sleep(
            min(
                settings.dagster_termination_poll_interval_seconds,
                max(remaining, 0.0),
            )
        )


def _terminal_mapping(status: str) -> tuple[str, str, str, str | None]:
    mappings = {
        "CANCELED": ("cancelled", "CANCELED", "cancelled", None),
        "SUCCESS": ("already_terminal", "SUCCESS", "done", None),
        "FAILURE": (
            "already_terminal",
            "FAILURE",
            "failed",
            "Dagster run finished with FAILURE before cancellation completed",
        ),
    }
    try:
        return mappings[status]
    except KeyError as exc:
        raise PipelineCancellationInvariantError(
            f"unsupported terminal Dagster status: {status}"
        ) from exc


async def _reload_attempt(
    session: AsyncSession,
    cancellation_id: str,
) -> PipelineCancellationDetail:
    detail = await get_pipeline_cancellation_detail(session, cancellation_id)
    if detail is None:
        raise PipelineCancellationInvariantError("cancellation attempt disappeared")
    return detail


async def _cancel_queued_members(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
) -> PipelineCancellationDetail:
    for member in _ordered_members(detail):
        if member.initial_status == "queued" and member.result == "pending":
            async with session.begin():
                changed = await cancel_queued_pipeline_cancellation_member(
                    session,
                    cancellation_id=detail.attempt.cancellation_id,
                    member_kind=member.member_kind,
                    member_id=member.member_id,
                )
                _require_cancellation_write(
                    changed,
                    cancellation_id=detail.attempt.cancellation_id,
                    message="queued cancellation member CAS ownership was lost",
                )
    async with session.begin():
        return await _reload_attempt(session, detail.attempt.cancellation_id)


async def _record_run_failure(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
    *,
    run_id: str,
    initial_status: str | None,
    failure: _Failure,
) -> PipelineCancellationDetail:
    existing_run = next(item for item in detail.runs if item.dagster_run_id == run_id)
    if existing_run.result == "pending":
        async with session.begin():
            changed = await set_pipeline_cancellation_run_result(
                session,
                cancellation_id=detail.attempt.cancellation_id,
                dagster_run_id=run_id,
                result="cancel_failed",
                initial_status=initial_status,
                terminal_status=None,
                error=failure.payload(),
                expected_results=("pending",),
            )
            _require_cancellation_write(
                changed,
                cancellation_id=detail.attempt.cancellation_id,
                message="Dagster run failure CAS ownership was lost",
            )
    elif existing_run.result != "cancel_failed":
        raise _CoordinatorOwnershipLost(
            detail.attempt.cancellation_id,
            "Dagster run changed before failure recording",
        )

    # run→member를 한 transaction에 누적해 잠그지 않는다. 각 public writer의
    # attempt→member→run→base 순서를 그대로 쓰고 crash resume가 나머지를 복사한다.
    for member in _ordered_members(detail):
        if (
            member.dagster_run_id == run_id
            and member.initial_status == "running"
            and member.result == "pending"
        ):
            async with session.begin():
                changed = await set_pipeline_cancellation_member_result(
                    session,
                    cancellation_id=detail.attempt.cancellation_id,
                    member_kind=member.member_kind,
                    member_id=member.member_id,
                    result="cancel_failed",
                    terminal_status=None,
                    error=failure.payload(),
                    expected_results=("pending",),
                )
                _require_cancellation_write(
                    changed,
                    cancellation_id=detail.attempt.cancellation_id,
                    message="cancellation member failure CAS ownership was lost",
                )
    async with session.begin():
        return await _reload_attempt(session, detail.attempt.cancellation_id)


async def _record_terminal_run(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
    *,
    run_id: str,
    initial_status: str | None,
    terminal_status: str,
) -> tuple[PipelineCancellationDetail, _Failure | None]:
    run_result, stored_terminal, target_status, error_message = _terminal_mapping(
        terminal_status
    )
    definitive: _Failure | None = None
    existing_run = next(item for item in detail.runs if item.dagster_run_id == run_id)
    async with session.begin():
        if existing_run.result in {"pending", "cancel_failed"}:
            changed = await set_pipeline_cancellation_run_result(
                session,
                cancellation_id=detail.attempt.cancellation_id,
                dagster_run_id=run_id,
                result=run_result,
                initial_status=initial_status,
                terminal_status=stored_terminal,
                error=None,
            )
            _require_cancellation_write(
                changed,
                cancellation_id=detail.attempt.cancellation_id,
                message="Dagster terminal run CAS ownership was lost",
            )
        elif (
            existing_run.result != run_result
            or existing_run.terminal_status != stored_terminal
        ):
            raise PipelineCancellationInvariantError(
                "recorded Dagster terminal result changed during orphan resume"
            )

    async with session.begin():
        detail = await _reload_attempt(session, detail.attempt.cancellation_id)
    for member in _ordered_members(detail):
        if (
            member.dagster_run_id != run_id
            or member.initial_status != "running"
            or member.result not in {"pending", "cancel_failed"}
        ):
            continue
        async with session.begin():
            try:
                changed = await transition_pipeline_cancellation_member(
                    session,
                    cancellation_id=detail.attempt.cancellation_id,
                    member_kind=member.member_kind,
                    member_id=member.member_id,
                    dagster_run_id=run_id,
                    expected_status="running",
                    target_status=target_status,
                    result=run_result,
                    error_message=error_message,
                )
            except PipelineCancellationConflict:
                changed = False
            if changed:
                continue
            current = await get_pipeline_cancellation_detail(
                session,
                detail.attempt.cancellation_id,
            )
            if current is None:
                raise _CoordinatorOwnershipLost(
                    detail.attempt.cancellation_id,
                    "cancellation attempt disappeared during member reconcile",
                )
            current_member = next(
                (
                    item
                    for item in current.members
                    if item.member_kind == member.member_kind
                    and item.member_id == member.member_id
                ),
                None,
            )
            if current_member is None:
                raise _CoordinatorOwnershipLost(
                    detail.attempt.cancellation_id,
                    "cancellation member disappeared during reconcile",
                )
            if (
                current_member.result == run_result
                and current_member.terminal_status == target_status
            ):
                continue
            if current_member.result not in {"pending", "cancel_failed"}:
                raise _CoordinatorOwnershipLost(
                    detail.attempt.cancellation_id,
                    "cancellation member changed during reconcile",
                )
            definitive = _failure(
                "PIPELINE_CANCELLATION_UNSAFE",
                "frozen member no longer matches the authoritative Dagster run",
                cancellation_id=detail.attempt.cancellation_id,
                dagster_run_id=run_id,
                phase="reconcile",
            )
            failure_changed = await set_pipeline_cancellation_member_result(
                session,
                cancellation_id=detail.attempt.cancellation_id,
                member_kind=member.member_kind,
                member_id=member.member_id,
                result="cancel_failed",
                terminal_status=None,
                error=definitive.payload(),
            )
            _require_cancellation_write(
                failure_changed,
                cancellation_id=detail.attempt.cancellation_id,
                message="definitive member failure CAS ownership was lost",
            )
    async with session.begin():
        refreshed = await _reload_attempt(session, detail.attempt.cancellation_id)
    return refreshed, definitive


async def _propagate_recorded_run(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
    *,
    run_id: str,
) -> tuple[PipelineCancellationDetail, _Failure | None]:
    run = next(item for item in detail.runs if item.dagster_run_id == run_id)
    if run.result in {"cancelled", "already_terminal"}:
        if run.terminal_status is None:
            has_unresolved_running_member = any(
                member.dagster_run_id == run_id
                and member.initial_status == "running"
                and member.result in {"pending", "cancel_failed"}
                for member in detail.members
            )
            if not has_unresolved_running_member:
                return detail, None
            raise PipelineCancellationInvariantError(
                "resolved cancellation run has no terminal status"
            )
        return await _record_terminal_run(
            session,
            detail,
            run_id=run_id,
            initial_status=run.initial_status,
            terminal_status=run.terminal_status,
        )
    if run.result != "cancel_failed" or run.error is None:
        return detail, None
    failure = _Failure(
        code=str(run.error["code"]),
        message=str(run.error["message"]),
        details=dict(run.error.get("details") or {}),
    )
    return (
        await _record_run_failure(
            session,
            detail,
            run_id=run_id,
            initial_status=run.initial_status,
            failure=failure,
        ),
        failure,
    )


async def _reserve_run(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
    *,
    run_id: str,
    initial_status: str,
) -> bool:
    async with session.begin():
        return await mark_pipeline_cancellation_run_termination_reserved(
            session,
            cancellation_id=detail.attempt.cancellation_id,
            dagster_run_id=run_id,
            initial_status=initial_status,
        )


async def _join_reserved_run_after_cas_loss(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
    *,
    run_id: str,
) -> PipelineCancellationDetail:
    """reservation CAS loser가 fresh same-attempt reservation에 poll로 합류한다."""
    async with session.begin():
        current = await _reload_attempt(session, detail.attempt.cancellation_id)
    current_run = next(
        (item for item in current.runs if item.dagster_run_id == run_id),
        None,
    )
    if (
        current.attempt.status == "in_progress"
        and current_run is not None
        and current_run.result == "pending"
        and current_run.termination_reserved_at is not None
    ):
        return current
    raise _CoordinatorOwnershipLost(
        detail.attempt.cancellation_id,
        "Dagster termination reservation ownership changed",
    )


async def _process_pending_run(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
    *,
    run_id: str,
    settings: ApiSettings,
    http_client: httpx.AsyncClient,
    graphql_url: str,
) -> tuple[PipelineCancellationDetail, _Failure | None]:
    _assert_no_transaction(session)
    try:
        observation = await _query_run_status(
            http_client=http_client,
            graphql_url=graphql_url,
            cancellation_id=detail.attempt.cancellation_id,
            run_id=run_id,
            phase="initial_status",
        )
    except _DagsterFailure as exc:
        return (
            await _record_run_failure(
                session,
                detail,
                run_id=run_id,
                initial_status=None,
                failure=exc.failure,
            ),
            exc.failure,
        )

    if observation.status in _TERMINAL_DAGSTER_STATUSES:
        return await _record_terminal_run(
            session,
            detail,
            run_id=run_id,
            initial_status=observation.status,
            terminal_status=observation.status,
        )

    run = next(item for item in detail.runs if item.dagster_run_id == run_id)
    reserved_by_this_call = False
    if run.termination_reserved_at is None:
        reserved_by_this_call = await _reserve_run(
            session,
            detail,
            run_id=run_id,
            initial_status=observation.status,
        )
        if not reserved_by_this_call:
            detail = await _join_reserved_run_after_cas_loss(
                session,
                detail,
                run_id=run_id,
            )

    ambiguous_dispatch_failure: _Failure | None = None
    if reserved_by_this_call:
        _assert_no_transaction(session)
        try:
            ambiguous_dispatch_failure = await _terminate_run_once(
                http_client=http_client,
                graphql_url=graphql_url,
                cancellation_id=detail.attempt.cancellation_id,
                run_id=run_id,
            )
        except _DagsterFailure as exc:
            return (
                await _record_run_failure(
                    session,
                    detail,
                    run_id=run_id,
                    initial_status=observation.status,
                    failure=exc.failure,
                ),
                exc.failure,
            )

    _assert_no_transaction(session)
    try:
        terminal = await _poll_terminal_status(
            http_client=http_client,
            graphql_url=graphql_url,
            cancellation_id=detail.attempt.cancellation_id,
            run_id=run_id,
            settings=settings,
        )
    except _DagsterFailure as exc:
        observed_failure = ambiguous_dispatch_failure or exc.failure
        return (
            await _record_run_failure(
                session,
                detail,
                run_id=run_id,
                initial_status=observation.status,
                failure=observed_failure,
            ),
            observed_failure,
        )
    return await _record_terminal_run(
        session,
        detail,
        run_id=run_id,
        initial_status=observation.status,
        terminal_status=terminal.status,
    )


async def _record_missing_run_members(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
) -> tuple[PipelineCancellationDetail, _Failure | None]:
    failure: _Failure | None = None
    for member in _ordered_members(detail):
        if (
            member.initial_status != "running"
            or member.dagster_run_id is not None
            or member.result not in {"pending", "cancel_failed"}
        ):
            continue
        if member.result == "cancel_failed":
            if member.error is None:
                raise PipelineCancellationInvariantError(
                    "missing-run member failure has no structured error"
                )
            failure = _Failure(
                code=str(member.error["code"]),
                message=str(member.error["message"]),
                details=dict(member.error.get("details") or {}),
            )
            continue
        failure = _failure(
            "PIPELINE_CANCELLATION_UNSAFE",
            "active local member has no Dagster run id",
            cancellation_id=detail.attempt.cancellation_id,
            phase="reconcile",
        )
        async with session.begin():
            changed = await set_pipeline_cancellation_member_result(
                session,
                cancellation_id=detail.attempt.cancellation_id,
                member_kind=member.member_kind,
                member_id=member.member_id,
                result="cancel_failed",
                terminal_status=None,
                error=failure.payload(),
            )
            _require_cancellation_write(
                changed,
                cancellation_id=detail.attempt.cancellation_id,
                message="missing-run member failure CAS ownership was lost",
            )
    async with session.begin():
        refreshed = await _reload_attempt(session, detail.attempt.cancellation_id)
    return refreshed, failure


async def _finish_attempt(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
    *,
    status: str,
    failure: _Failure | None,
) -> PipelineCancellationDetail:
    async with session.begin():
        finished = await finish_pipeline_cancellation_attempt(
            session,
            cancellation_id=detail.attempt.cancellation_id,
            status=status,
            error=failure.payload() if failure is not None else None,
        )
    if finished is None:
        async with session.begin():
            finished = await _reload_attempt(session, detail.attempt.cancellation_id)
    if finished.attempt.status != status:
        raise _CoordinatorOwnershipLost(
            detail.attempt.cancellation_id,
            "cancellation finish CAS ownership was lost",
        )
    return finished


async def _close_attempt_unsafe(
    session: AsyncSession,
    *,
    cancellation_id: str,
) -> tuple[PipelineCancellationDetail, _Failure]:
    """unexpected close 시 미관측 normalized/base 결과를 위조하지 않는다."""
    failure = _failure(
        "PIPELINE_CANCELLATION_UNSAFE",
        "pipeline cancellation invariant diverged from its frozen scope",
        cancellation_id=cancellation_id,
        phase="reconcile",
    )
    async with session.begin():
        detail = await _reload_attempt(session, cancellation_id)
        if detail.attempt.status != "in_progress":
            return detail, failure
    if detail.attempt.status == "in_progress":
        detail = await _finish_attempt(
            session,
            detail,
            status="failed",
            failure=failure,
        )
    return detail, failure


def _service_error_for_failure(
    failure: _Failure,
    detail: PipelineCancellationDetail,
    *,
    retry_after_seconds: int,
) -> PipelineCancellationServiceError:
    root = _root_record(detail.attempt.root_kind, detail.attempt.root_id)
    record = _detail_record(detail)
    if failure.code == "DAGSTER_TERMINATION_TIMEOUT":
        return DagsterTerminationTimeout(
            failure.message,
            root=root,
            detail=record,
            retry_after_seconds=retry_after_seconds,
        )
    if failure.code == "DAGSTER_UNAVAILABLE":
        return DagsterUnavailable(
            failure.message,
            root=root,
            detail=record,
            retry_after_seconds=retry_after_seconds,
        )
    if failure.code == "DAGSTER_TERMINATE_FAILED":
        return DagsterTerminateFailed(
            failure.message,
            root=root,
            detail=record,
            retry_after_seconds=retry_after_seconds,
        )
    return PipelineCancellationUnsafe(
        failure.message,
        root=root,
        detail=record,
        retry_after_seconds=retry_after_seconds,
    )


def _attempt_failure(detail: PipelineCancellationDetail) -> _Failure:
    error = detail.attempt.error
    if error is None:
        return _failure(
            "PIPELINE_CANCELLATION_UNSAFE",
            "cancellation ownership changed without a terminal error snapshot",
            cancellation_id=detail.attempt.cancellation_id,
            phase="ownership_reload",
        )
    code = error.get("code")
    message = error.get("message")
    details = error.get("details")
    if not isinstance(code, str) or not isinstance(message, str):
        return _failure(
            "PIPELINE_CANCELLATION_UNSAFE",
            "cancellation ownership changed with an invalid error snapshot",
            cancellation_id=detail.attempt.cancellation_id,
            phase="ownership_reload",
        )
    return _Failure(
        code=code,
        message=message,
        details=dict(details) if isinstance(details, Mapping) else {},
    )


async def _reload_after_ownership_loss(
    *,
    engine: AsyncEngine,
    cancellation_id: str | None,
    kind: str,
    execution_id: str,
    fallback_root: PipelineCancellationRootRecord,
    settings: ApiSettings,
) -> PipelineCancellationDetailRecord:
    """canonical current를 우선하고 old exact attempt는 마지막 fallback으로 쓴다."""
    async with (
        AsyncSession(bind=engine, expire_on_commit=False) as fresh_session,
        fresh_session.begin(),
    ):
        canonical_scope = await resolve_pipeline_cancellation_scope(
            fresh_session,
            kind=kind,
            execution_id=execution_id,
        )
        current_root = fallback_root
        detail = None
        if canonical_scope is not None:
            current_root = _root_record(
                canonical_scope.root_kind,
                canonical_scope.root_id,
            )
            detail = await _current_detail_for_root(
                fresh_session,
                root_kind=canonical_scope.root_kind,
                root_id=canonical_scope.root_id,
            )
        if detail is None and cancellation_id is not None:
            detail = await get_pipeline_cancellation_detail(
                fresh_session,
                cancellation_id,
            )
    if detail is None:
        raise PipelineCancellationUnsafe(
            "cancellation ownership changed and no durable attempt was found",
            root=current_root,
            retry_after_seconds=settings.pipeline_cancellation_retry_after_seconds,
        )
    record = _detail_record(detail)
    if detail.attempt.status == "completed":
        return record
    if detail.attempt.status == "in_progress":
        raise PipelineCancellationInProgress(
            "pipeline cancellation coordinator ownership changed",
            root=current_root,
            detail=record,
            retry_after_seconds=settings.pipeline_cancellation_retry_after_seconds,
        )
    raise _service_error_for_failure(
        _attempt_failure(detail),
        detail,
        retry_after_seconds=settings.pipeline_cancellation_retry_after_seconds,
    )


async def _coordinate_attempt(
    session: AsyncSession,
    detail: PipelineCancellationDetail,
    *,
    settings: ApiSettings,
    http_client: httpx.AsyncClient,
) -> PipelineCancellationDetailRecord:
    if detail.attempt.status == "completed":
        return _detail_record(detail)

    detail = await _cancel_queued_members(session, detail)
    last_failure: _Failure | None = None
    definitive_failure: _Failure | None = None

    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError:
        urls = None

    for run in detail.runs:
        if run.result != "pending":
            detail, failure = await _propagate_recorded_run(
                session,
                detail,
                run_id=run.dagster_run_id,
            )
        elif urls is None:
            failure = _failure(
                "DAGSTER_TERMINATE_FAILED",
                "Dagster GraphQL URL configuration is invalid",
                cancellation_id=detail.attempt.cancellation_id,
                dagster_run_id=run.dagster_run_id,
                phase="configuration",
            )
            detail = await _record_run_failure(
                session,
                detail,
                run_id=run.dagster_run_id,
                initial_status=None,
                failure=failure,
            )
        else:
            detail, failure = await _process_pending_run(
                session,
                detail,
                run_id=run.dagster_run_id,
                settings=settings,
                http_client=http_client,
                graphql_url=urls.graphql_url,
            )
        if failure is None:
            continue
        last_failure = failure
        if failure.code in {
            "PIPELINE_CANCELLATION_UNSAFE",
            "DAGSTER_RECONCILE_FAILED",
            "PIPELINE_CANCELLATION_INVARIANT",
        }:
            definitive_failure = failure

    detail, missing_run_failure = await _record_missing_run_members(session, detail)
    if missing_run_failure is not None:
        last_failure = missing_run_failure
        definitive_failure = missing_run_failure

    pending = [member for member in detail.members if member.result == "pending"]
    if pending:
        raise PipelineCancellationInvariantError(
            "coordinator left pending cancellation members after run processing"
        )
    unresolved = [
        member for member in detail.members if member.result == "cancel_failed"
    ]
    if not unresolved:
        finished = await _finish_attempt(
            session,
            detail,
            status="completed",
            failure=None,
        )
        return _detail_record(finished)

    if last_failure is None:
        raise PipelineCancellationInvariantError(
            "unresolved cancellation has no structured failure"
        )
    if definitive_failure is not None:
        finished = await _finish_attempt(
            session,
            detail,
            status="failed",
            failure=definitive_failure,
        )
        raise _service_error_for_failure(
            definitive_failure,
            finished,
            retry_after_seconds=settings.pipeline_cancellation_retry_after_seconds,
        )

    finished = await _finish_attempt(
        session,
        detail,
        status="retryable",
        failure=last_failure,
    )
    raise _service_error_for_failure(
        last_failure,
        finished,
        retry_after_seconds=settings.pipeline_cancellation_retry_after_seconds,
    )


async def cancel_pipeline_execution(
    *,
    engine: AsyncEngine,
    settings: ApiSettings,
    http_client: httpx.AsyncClient,
    kind: str,
    execution_id: str,
    requested_by: str,
    reason: str | None,
) -> PipelineCancellationDetailRecord:
    """canonical hierarchy를 marker-first로 취소하고 durable detail을 반환한다."""
    if not requested_by.strip():
        raise ValueError("requested_by must not be empty")

    async with (
        engine.connect() as connection,
        AsyncSession(bind=connection, expire_on_commit=False) as session,
    ):
        last_root: PipelineCancellationRootRecord | None = None
        for _ in range(settings.pipeline_cancellation_root_retry_limit):
            async with session.begin():
                preliminary = await resolve_pipeline_cancellation_scope(
                    session,
                    kind=kind,
                    execution_id=execution_id,
                )
            if preliminary is None:
                raise PipelineExecutionNotFound(
                    f"pipeline execution not found: {kind}/{execution_id}"
                )
            last_root = _root_record(
                preliminary.root_kind,
                preliminary.root_id,
            )
            lease_key = _coordinator_lease_key(
                root_kind=preliminary.root_kind,
                root_id=preliminary.root_id,
            )
            acquired = await _acquire_coordinator_lease(
                session,
                lease_key=lease_key,
            )
            if not acquired:
                current = await _bounded_current_detail(
                    session,
                    root_kind=preliminary.root_kind,
                    root_id=preliminary.root_id,
                    settings=settings,
                )
                raise PipelineCancellationInProgress(
                    "pipeline cancellation coordinator is already active",
                    root=last_root,
                    detail=_detail_record(current) if current is not None else None,
                    retry_after_seconds=(
                        settings.pipeline_cancellation_retry_after_seconds
                    ),
                )

            retry_root = False
            ownership_lost: _CoordinatorOwnershipLost | None = None
            detail: PipelineCancellationDetail | None = None
            try:
                try:
                    async with session.begin():
                        detail = await _prepare_attempt(
                            session,
                            kind=kind,
                            execution_id=execution_id,
                            root_kind=preliminary.root_kind,
                            root_id=preliminary.root_id,
                            requested_by=requested_by,
                            reason=reason,
                            retry_after_seconds=(
                                settings.pipeline_cancellation_retry_after_seconds
                            ),
                        )
                    if detail is None:
                        retry_root = True
                    else:
                        return await _coordinate_attempt(
                            session,
                            detail,
                            settings=settings,
                            http_client=http_client,
                        )
                except PipelineCancellationServiceError:
                    raise
                except (
                    PipelineCancellationConflict,
                    PipelineCancellationInvariantError,
                ):
                    _LOG.error(
                        "pipeline cancellation reconciliation diverged",
                        exc_info=True,
                    )
                    if detail is None:
                        retry_root = True
                    else:
                        failed, failure = await _close_attempt_unsafe(
                            session,
                            cancellation_id=detail.attempt.cancellation_id,
                        )
                        raise _service_error_for_failure(
                            failure,
                            failed,
                            retry_after_seconds=(
                                settings.pipeline_cancellation_retry_after_seconds
                            ),
                        ) from None
            except _CoordinatorOwnershipLost as exc:
                ownership_lost = exc
            finally:
                await _release_coordinator_lease(
                    session,
                    connection,
                    lease_key=lease_key,
                )
            if ownership_lost is not None:
                return await _reload_after_ownership_loss(
                    engine=engine,
                    cancellation_id=ownership_lost.cancellation_id,
                    kind=kind,
                    execution_id=execution_id,
                    fallback_root=last_root,
                    settings=settings,
                )
            if retry_root:
                continue

        raise PipelineCancellationUnsafe(
            "canonical cancellation root changed repeatedly",
            root=last_root,
            retry_after_seconds=settings.pipeline_cancellation_retry_after_seconds,
        )

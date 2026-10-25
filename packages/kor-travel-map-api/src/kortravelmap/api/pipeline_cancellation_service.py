"""Pipeline 계층형 취소 application coordinator.

DB repository는 transaction-local CAS만 소유한다. 이 모듈은 canonical-root lease,
짧은 DB phase, Dagster SAFE_TERMINATE와 crash resume 순서를 소유한다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import sys
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import TYPE_CHECKING, Any, Final

import anyio
import httpx
from kortravelmap.core.feature_operation import FEATURE_OPERATION_RESERVED_KINDS
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.c6c_cancel_probe_fixture_repo import (
    mark_c6c_cancel_probe_consumed,
)
from kortravelmap.infra.cache_target_event_repo import (
    CacheTargetRefreshProtocolViolation,
    CacheTargetRefreshStatus,
    append_cache_target_refresh_status_events,
)
from kortravelmap.infra.feature_update_executor import (
    suppresses_relay_finalization,
)
from kortravelmap.infra.feature_update_repo import get_update_request_by_job_id
from kortravelmap.infra.log_repo import record_system_log
from kortravelmap.infra.pipeline_cancellation_repo import (
    PipelineCancellationConflict,
    PipelineCancellationDetail,
    PipelineCancellationInvariantError,
    PipelineCancellationMember,
    PipelineCancellationTimelineConflict,
    cancel_queued_pipeline_cancellation_member,
    create_pipeline_cancellation_attempt,
    fill_pipeline_cancellation_canonical_starts,
    finish_pipeline_cancellation_attempt,
    get_current_pipeline_cancellation_summary,
    get_pipeline_cancellation_detail,
    lock_provider_feature_finalization,
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
    "PipelineCancellationDatabaseUnavailable",
    "PipelineCancellationInProgress",
    "PipelineCancellationServiceError",
    "PipelineCancellationUnsafe",
    "PipelineExecutionNotFound",
    "cancel_pipeline_execution",
]

_LOG = logging.getLogger(__name__)

_TERMINAL_DAGSTER_STATUSES: Final[frozenset[str]] = frozenset({"CANCELED", "SUCCESS", "FAILURE"})
_COORDINATOR_LEASE_PREFIX = "pipeline-cancellation:coordinator"
_CONNECTION_CHECK_MILLISECONDS = 100
_CLEANUP_SECONDS = 0.6
_OBSERVER_STATEMENT_SECONDS = 0.1
_BACKEND_INFO_KEY = "pipeline_cancellation_exact_backend"


_RUN_STATUS_QUERY = """
query KorTravelMapCancellationRunStatus($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run { runId status startTime endTime }
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
    started_at: datetime | None = None
    finished_at: datetime | None = None


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


class PipelineCancellationDatabaseUnavailable(PipelineCancellationServiceError):
    code = "PIPELINE_CANCELLATION_DATABASE_UNAVAILABLE"


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
    extra_details: Mapping[str, Any] | None = None,
) -> _Failure:
    details: dict[str, Any] = {
        "cancellation_id": cancellation_id,
        "phase": phase,
    }
    if dagster_run_id is not None:
        details["dagster_run_id"] = dagster_run_id
    if typename is not None:
        details["typename"] = typename
    if extra_details is not None:
        details.update(dict(extra_details))
    return _Failure(code=code, message=message, details=details)


def _coordinator_lease_key(*, root_kind: str, root_id: str) -> int:
    return advisory_lock_key(f"{_COORDINATOR_LEASE_PREFIX}:{root_kind}:{root_id}")


def _assert_no_transaction(session: AsyncSession) -> None:
    if session.in_transaction():
        raise PipelineCancellationInvariantError(
            "external cancellation phase cannot keep a DB transaction open"
        )


@dataclass
class _CoordinatorBackend:
    connection: AsyncConnection
    engine: AsyncEngine
    pool_proxy: Any
    driver: Any
    pid: int
    backend_start: datetime | None = None
    original_connection_check: str | None = None
    discarded: bool = False
    termination_confirmed: bool = False
    cleanup_attempted: bool = False
    lease_possible: bool = False


def _session_backend(session: AsyncSession) -> _CoordinatorBackend | None:
    value = getattr(session, "info", {}).get(_BACKEND_INFO_KEY)
    return value if isinstance(value, _CoordinatorBackend) else None


def _capture_backend(connection: AsyncConnection, engine: AsyncEngine) -> _CoordinatorBackend:
    # 첫 SQL/K 시도 전에만 읽는다. invalidated connection에는 이 함수를 재호출하지 않는다.
    if connection.invalidated or connection.closed:
        raise PipelineCancellationUnsafe("cannot capture an unavailable cancellation backend")
    sync_connection = connection.sync_connection
    if sync_connection is None:
        raise PipelineCancellationUnsafe("cancellation connection was not started")
    proxy = sync_connection.connection
    driver = proxy.driver_connection
    if driver is None or not callable(getattr(driver, "terminate", None)):
        raise PipelineCancellationUnsafe("physical cancellation driver is unavailable")
    return _CoordinatorBackend(connection, engine, proxy, driver, driver.get_server_pid())


def _discard_exact_backend(backend: _CoordinatorBackend, cause: BaseException) -> None:
    """원 driver를 종료하고 pool slot을 회수한다. 새 backend로 reconnect하지 않는다."""
    if backend.discarded:
        return
    current_driver = backend.pool_proxy.driver_connection
    owned_live_proxy = current_driver is backend.driver and not backend.connection.closed
    interrupted_invalidation = (
        current_driver is None and backend.connection.invalidated and not backend.connection.closed
    )
    if not (owned_live_proxy or interrupted_invalidation):
        # 정상 반환된 proxy나 다른 checkout의 driver는 원 driver가 닫혔어도 건드리지 않는다.
        raise PipelineCancellationUnsafe("physical cancellation backend ownership was released")
    backend.discarded = True
    failures: list[BaseException] = []
    try:
        result = backend.driver.terminate()
        if inspect.isawaitable(result):
            if inspect.iscoroutine(result):
                result.close()
            raise PipelineCancellationUnsafe("physical driver terminate must be synchronous")
    except BaseException as exc:
        failures.append(exc)
    sync_connection = backend.connection.sync_connection
    assert sync_connection is not None
    for target, action in (
        (backend.pool_proxy, "invalidate"),
        (sync_connection, "invalidate"),
        (sync_connection, "close"),
    ):
        try:
            if target is backend.pool_proxy:
                # SQLAlchemy가 취소 중 이미 비운 proxy는 record를 다시 건드리지 않는다.
                if target.dbapi_connection is not None:
                    target.invalidate(cause, soft=False)
            elif action == "invalidate":
                target.invalidate(cause)
            else:
                target.close()
        except BaseException as exc:
            failures.append(exc)
    if failures:
        raise PipelineCancellationUnsafe("exact cancellation backend discard failed") from failures[
            0
        ]


async def _confirm_backend_termination(backend: _CoordinatorBackend, *, deadline: float) -> bool:
    """같은 LOGIN의 새 readonly observer로 원 backend의 소멸을 확인한다."""
    if backend.backend_start is None:
        # 첫 metadata SQL 전에는 K/업무 SQL을 실행하지 않았다. 소멸을 추측하지 않는다.
        return False
    observer: _CoordinatorBackend | None = None
    connection = backend.engine.connect()
    try:
        async with asyncio.timeout_at(deadline):
            await connection.start()
            observer = _capture_backend(connection, backend.engine)
            driver = observer.driver
            await driver.execute(
                "SET default_transaction_read_only = on",
                timeout=min(_OBSERVER_STATEMENT_SECONDS, max(0.0, deadline - monotonic())),
            )
            while monotonic() < deadline:
                # 각 native autocommit SELECT는 새 snapshot이다. query 본문/다른 세션은 읽지 않는다.
                row = await driver.fetchrow(
                    """SELECT EXISTS (
                        SELECT 1 FROM pg_catalog.pg_stat_activity
                        WHERE pid=$1 AND backend_start=$2
                    ) AS backend_present, EXISTS (
                        SELECT 1 FROM pg_catalog.pg_locks AS l
                        WHERE l.pid=$1 AND l.locktype='advisory'
                    ) AS advisory_present""",
                    backend.pid,
                    backend.backend_start,
                    timeout=min(_OBSERVER_STATEMENT_SECONDS, max(0.0, deadline - monotonic())),
                )
                if not row["backend_present"] and not row["advisory_present"]:
                    return True
                await asyncio.sleep(min(0.02, max(0.0, deadline - monotonic())))
    except Exception as exc:
        # 외부 cancel은 이 scope 밖에서 재전파한다. 확인 실패를 성공으로 승격하지 않는다.
        _LOG.warning(
            "pipeline cancellation backend termination readback failed: error_type=%s",
            type(exc).__name__,
        )
    finally:
        if observer is not None:
            _discard_exact_backend(
                observer, PipelineCancellationUnsafe("readonly cancellation observer disposed")
            )
        elif connection.sync_connection is not None:
            connection.sync_connection.invalidate()
            connection.sync_connection.close()
    return False


async def _hard_invalidate_connection(
    backend: _CoordinatorBackend, *, cause: BaseException
) -> None:
    """level 취소를 막고 exact terminate→유한 readback을 수행한다."""
    if backend.cleanup_attempted:
        return
    backend.cleanup_attempted = True
    started = monotonic()
    try:
        with anyio.CancelScope(shield=True):
            _discard_exact_backend(backend, cause)
            backend.termination_confirmed = await _confirm_backend_termination(
                backend, deadline=started + _CLEANUP_SECONDS
            )
    finally:
        _LOG.log(
            logging.INFO if backend.termination_confirmed else logging.ERROR,
            "pipeline cancellation backend cleanup: confirmed=%s elapsed_ms=%d",
            backend.termination_confirmed,
            round((monotonic() - started) * 1000),
        )


@asynccontextmanager
async def _coordinator_session(
    engine: AsyncEngine,
) -> AsyncIterator[tuple[AsyncConnection, AsyncSession]]:
    """정상 업무의 기존 시간 예산은 보존하고 연결 수명만 명시적으로 회수한다."""
    connection = engine.connect()
    backend: _CoordinatorBackend | None = None
    session: AsyncSession | None = None
    primary: BaseException | None = None
    try:
        await connection.start()
        backend = _capture_backend(connection, engine)
        metadata = (
            await connection.execute(
                text("""WITH config AS MATERIALIZED (
                        SELECT current_setting('client_connection_check_interval') AS previous
                    )
                    SELECT a.backend_start, config.previous,
                        set_config('client_connection_check_interval',
                            CASE WHEN config.previous::interval = interval '0' THEN '100ms'
                            ELSE LEAST(
                                EXTRACT(epoch FROM config.previous::interval)*1000,
                                :check_ms)::bigint::text END, false)
                    FROM pg_catalog.pg_stat_activity AS a CROSS JOIN config
                    WHERE a.pid=pg_backend_pid()"""),
                {"check_ms": _CONNECTION_CHECK_MILLISECONDS},
            )
        ).one()
        backend.backend_start = metadata[0]
        backend.original_connection_check = str(metadata[1])
        await connection.commit()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        session.info[_BACKEND_INFO_KEY] = backend
        yield connection, session
    except BaseException as exc:
        primary = exc
        raise
    finally:
        try:
            with anyio.CancelScope(shield=True):
                if backend is not None and (
                    isinstance(primary, asyncio.CancelledError)
                    or backend.lease_possible
                    or connection.invalidated
                    or session is None
                ):
                    await _hard_invalidate_connection(
                        backend,
                        cause=primary or PipelineCancellationUnsafe("connection setup failed"),
                    )
                    if primary is None:
                        raise PipelineCancellationDatabaseUnavailable(
                            "cancellation backend could not be safely returned",
                            retry_after_seconds=1,
                        )
                elif backend is not None and not backend.discarded:
                    async with asyncio.timeout(_CLEANUP_SECONDS):
                        if session is not None:
                            await session.close()
                        if backend.original_connection_check is not None:
                            await connection.execute(
                                text(
                                    "SELECT set_config("
                                    "'client_connection_check_interval', :previous, false)"
                                ),
                                {"previous": backend.original_connection_check},
                            )
                            await connection.commit()
                        await connection.close()
                elif backend is None and connection.sync_connection is not None:
                    connection.sync_connection.invalidate(primary)
                    connection.sync_connection.close()
        except BaseException as cleanup_error:
            if backend is not None:
                try:
                    await _hard_invalidate_connection(backend, cause=cleanup_error)
                except BaseException:
                    _LOG.error("pipeline cancellation exact backend cleanup failed", exc_info=True)
            if isinstance(primary, asyncio.CancelledError):
                # cleanup 중 새 취소가 생겨도 이미 받은 원 caller 취소 객체가 우선이다.
                raise primary from None
            if isinstance(cleanup_error, asyncio.CancelledError):
                # restore/close가 처음 취소된 경우 domain 오류나 503으로 덮지 않는다.
                raise
            if primary is None:
                raise PipelineCancellationDatabaseUnavailable(
                    "cancellation connection cleanup could not be verified",
                    retry_after_seconds=1,
                ) from cleanup_error
            _LOG.error("pipeline cancellation cleanup failed while propagating caller error")
        # pending AnyIO level 취소를 정상 응답/도메인 오류보다 우선한다.
        if primary is None or isinstance(primary, Exception):
            await anyio.lowlevel.checkpoint()


async def _rollback_quietly(session: AsyncSession) -> None:
    try:
        if session.in_transaction():
            await session.rollback()
    except BaseException:
        _LOG.warning("pipeline cancellation session rollback failed", exc_info=True)


async def _acquire_coordinator_lease(
    session: AsyncSession,
    *,
    lease_key: int,
) -> bool:
    _assert_no_transaction(session)
    # 이 await 자체의 반환 전에 취소/commit 오류가 나도 K 소유 가능성을 버리지 않는다.
    backend = _session_backend(session)
    if backend is not None:
        backend.lease_possible = True
    try:
        result = await session.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lease_key},
        )
        acquired = bool(result.scalar_one())
        await session.commit()
        if backend is not None and not acquired:
            backend.lease_possible = False
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
    """원 연결에서만 exact-key unlock을 검증한다."""
    backend = _session_backend(session)
    original_error = sys.exception()
    # caller 취소/invalidated/unknown은 unlock SQL을 새 backend에 보내지 않는다.
    if isinstance(original_error, asyncio.CancelledError) or connection.invalidated:
        if backend is None:
            raise PipelineCancellationUnsafe("exact cancellation backend was not captured")
        try:
            await _hard_invalidate_connection(
                backend, cause=original_error or PipelineCancellationUnsafe("backend invalidated")
            )
        except BaseException as cleanup_error:
            if not isinstance(original_error, asyncio.CancelledError):
                raise
            _LOG.error(
                "pipeline cancellation cleanup failed; original caller cancel retained: "
                "error_type=%s",
                type(cleanup_error).__name__,
            )
        if not isinstance(original_error, asyncio.CancelledError):
            raise PipelineCancellationDatabaseUnavailable(
                "cancellation backend was invalidated during coordination",
                retry_after_seconds=1,
            )
        return
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
            if backend is not None:
                backend.lease_possible = False
            return
        release_error = PipelineCancellationInvariantError(
            "pipeline cancellation coordinator lease was not owned at unlock"
        )
    except BaseException as exc:
        release_error = exc
    assert release_error is not None
    _LOG.error(
        "pipeline cancellation coordinator lease release failed",
        exc_info=(type(release_error), release_error, release_error.__traceback__),
    )
    if backend is None:
        raise PipelineCancellationUnsafe("exact cancellation backend was not captured")
    await _hard_invalidate_connection(backend, cause=release_error)
    if not isinstance(release_error, Exception):
        raise release_error
    raise PipelineCancellationUnsafe(
        "pipeline cancellation coordinator lease release could not be verified"
    ) from release_error


def _ordered_members(
    detail: PipelineCancellationDetail,
) -> tuple[PipelineCancellationMember, ...]:
    """canonical import job member를 UUID 순서로 반환한다."""
    return tuple(sorted(detail.members, key=lambda member: member.job_id))


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
            await asyncio.sleep(settings.pipeline_cancellation_lease_reload_interval_seconds)
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
        raise PipelineExecutionNotFound(f"pipeline execution not found: {kind}/{execution_id}")
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
        failure_type = _DagsterDispatchAmbiguous if transport_is_ambiguous else _DagsterFailure
        raise failure_type(timeout_failure) from exc
    except httpx.RequestError as exc:
        unavailable = _Failure(
            code="DAGSTER_UNAVAILABLE",
            message="Dagster GraphQL is unavailable",
            details=failure.details,
        )
        failure_type = _DagsterDispatchAmbiguous if transport_is_ambiguous else _DagsterFailure
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

    def timestamp(value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (TypeError, ValueError, OverflowError) as exc:
            raise _DagsterFailure(protocol_failure) from exc

    return _RunObservation(
        run_id=observed_id,
        status=observed_status.upper(),
        started_at=timestamp(value.get("startTime")),
        finished_at=timestamp(value.get("endTime")),
    )


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


def _terminal_mapping(
    status: str,
) -> tuple[str, str, CacheTargetRefreshStatus, str | None]:
    """Dagster terminal status를 (run_result, stored_terminal, target_status, error)로 푼다.

    세 번째 값은 그대로 relay status event로 나간다. 처음에는 `str`이라 호출부에서
    `done`을 `failed`로 접어도 타입이 잡지 못했다(적대 리뷰 P1). `CacheTargetRefreshStatus`로
    좁혀 "세 값 전부가 유효한 relay status"를 타입이 강제하게 한다.
    """

    mappings: dict[str, tuple[str, str, CacheTargetRefreshStatus, str | None]] = {
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
        if (
            member.initial_status == "queued"
            and not member.requires_run_termination
            and member.result == "pending"
        ):
            async with session.begin():
                changed = await cancel_queued_pipeline_cancellation_member(
                    session,
                    cancellation_id=detail.attempt.cancellation_id,
                    job_id=member.job_id,
                )
                _require_cancellation_write(
                    changed,
                    cancellation_id=detail.attempt.cancellation_id,
                    message="queued cancellation member CAS ownership was lost",
                )
                await _append_cache_target_terminal_relay_event(
                    session,
                    job_id=member.job_id,
                    status="cancelled",
                    origin="cancelled after queue",
                )
    async with session.begin():
        return await _reload_attempt(session, detail.attempt.cancellation_id)


async def _append_cache_target_terminal_relay_event(
    session: AsyncSession,
    *,
    job_id: str,
    status: CacheTargetRefreshStatus,
    origin: str,
) -> None:
    """취소/실패로 종결된 member의 cache-target relay status event를 같은 transaction에 남긴다.

    queued 경로와 running 경로가 같은 규칙을 쓰게 하려고 뽑았다(#975 적대 재리뷰 P2-b).
    running member는 Dagster terminate + ledger 전이로 봉인되는데, 여기에 event가 없으면
    PinVi는 요청의 **끝을 영영 보지 못한다** — 실행자 프로세스 안에서 죽는 경로
    (`feature_update_executor`의 CancelledError)와는 별개 경로다.

    savepoint로 감싸는 이유는 append 실패가 취소 자체(ledger CAS)를 되돌리면 안 되기
    때문이다. 삼키는 것은 restore fence 이동뿐이다 — 그때만 옛 epoch event가 설계상
    거부된다(runbook §5-5). 다른 reason은 원인을 잃지 않도록 그대로 올린다.
    """

    request = await get_update_request_by_job_id(session, job_id)
    if request is None or request.scope_type != "cache_target_keys":
        return
    try:
        async with session.begin_nested():
            await append_cache_target_refresh_status_events(
                session,
                request_id=request.request_id,
                job_id=request.job_id,
                status=status,
            )
    except CacheTargetRefreshProtocolViolation as violation:
        if not suppresses_relay_finalization(violation):
            raise
        _LOG.warning(
            "cache target refresh %s without relay event — restore fence moved "
            "(%s): request_id=%s reason=%s detail=%s",
            status,
            origin,
            request.request_id,
            violation.reason,
            violation,
        )


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
            and member.requires_run_termination
            and member.result == "pending"
        ):
            async with session.begin():
                changed = await set_pipeline_cancellation_member_result(
                    session,
                    cancellation_id=detail.attempt.cancellation_id,
                    job_id=member.job_id,
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
    engine_started_at: datetime | None = None,
    engine_finished_at: datetime | None = None,
) -> tuple[PipelineCancellationDetail, _Failure | None]:
    run_result, stored_terminal, target_status, error_message = _terminal_mapping(terminal_status)
    definitive: _Failure | None = None
    existing_run = next(item for item in detail.runs if item.dagster_run_id == run_id)
    canonical_members = tuple(
        member
        for member in detail.members
        if member.dagster_run_id == run_id
        and member.requires_run_termination
        and member.operation_kind in FEATURE_OPERATION_RESERVED_KINDS
        and member.result in {"pending", "cancel_failed"}
    )
    if canonical_members and engine_finished_at is None:
        failure = _failure(
            "DAGSTER_RECONCILE_FAILED",
            "Dagster terminal observation has no authoritative end time",
            cancellation_id=detail.attempt.cancellation_id,
            dagster_run_id=run_id,
            phase="terminal_timestamp",
            extra_details={"terminal_status": terminal_status},
        )
        return (
            await _record_run_failure(
                session,
                detail,
                run_id=run_id,
                initial_status=initial_status,
                failure=failure,
            ),
            failure,
        )
    stored_engine_started_at = engine_started_at if engine_finished_at is not None else None
    stored_engine_finished_at = engine_finished_at
    try:
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
                    engine_started_at=stored_engine_started_at,
                    engine_finished_at=stored_engine_finished_at,
                )
                _require_cancellation_write(
                    changed,
                    cancellation_id=detail.attempt.cancellation_id,
                    message="Dagster terminal run CAS ownership was lost",
                )
            elif (
                existing_run.result != run_result
                or existing_run.terminal_status != stored_terminal
                or existing_run.engine_started_at != stored_engine_started_at
                or existing_run.engine_finished_at != stored_engine_finished_at
            ):
                raise PipelineCancellationInvariantError(
                    "recorded Dagster terminal result changed during orphan resume"
                )
    except PipelineCancellationTimelineConflict:
        failure = _failure(
            "DAGSTER_RECONCILE_FAILED",
            "Dagster terminal timeline conflicts with the frozen operation",
            cancellation_id=detail.attempt.cancellation_id,
            dagster_run_id=run_id,
            phase="terminal_timeline",
            extra_details={"terminal_status": terminal_status},
        )
        return (
            await _record_run_failure(
                session,
                detail,
                run_id=run_id,
                initial_status=initial_status,
                failure=failure,
            ),
            failure,
        )

    async with session.begin():
        detail = await _reload_attempt(session, detail.attempt.cancellation_id)
    recorded_run = next(item for item in detail.runs if item.dagster_run_id == run_id)
    effective_engine_started_at = recorded_run.engine_started_at
    if effective_engine_started_at is not None and canonical_members:
        async with session.begin():
            await fill_pipeline_cancellation_canonical_starts(
                session,
                cancellation_id=detail.attempt.cancellation_id,
                dagster_run_id=run_id,
                engine_started_at=effective_engine_started_at,
            )
        async with session.begin():
            detail = await _reload_attempt(session, detail.attempt.cancellation_id)
    success_tracking_invariant = terminal_status == "SUCCESS" and any(
        member.dagster_run_id == run_id
        and member.operation_kind == "provider_feature_load"
        and member.initial_status != "done"
        for member in detail.members
    )
    pending_tracking_invariant = success_tracking_invariant and any(
        member.dagster_run_id == run_id
        and member.requires_run_termination
        and member.operation_kind in FEATURE_OPERATION_RESERVED_KINDS
        and member.result in {"pending", "cancel_failed"}
        for member in detail.members
    )
    if pending_tracking_invariant:
        async with session.begin():
            for member in _ordered_members(detail):
                if (
                    member.dagster_run_id != run_id
                    or not member.requires_run_termination
                    or member.operation_kind not in FEATURE_OPERATION_RESERVED_KINDS
                    or member.result not in {"pending", "cancel_failed"}
                ):
                    continue
                changed = await transition_pipeline_cancellation_member(
                    session,
                    cancellation_id=detail.attempt.cancellation_id,
                    job_id=member.job_id,
                    dagster_run_id=run_id,
                    expected_status=member.initial_status,
                    target_status="failed",
                    result=run_result,
                    error_message=("provider feature operation tracking invariant failed"),
                    dagster_terminal_status=stored_terminal,
                    engine_started_at=effective_engine_started_at,
                    engine_finished_at=engine_finished_at,
                    success_tracking_invariant=True,
                )
                _require_cancellation_write(
                    changed,
                    cancellation_id=detail.attempt.cancellation_id,
                    message="SUCCESS tracking invariant member CAS was lost",
                )
            await record_system_log(
                session,
                level="error",
                source="pipeline_cancellation",
                event="feature_operation.tracking_invariant",
                message="Dagster SUCCESS observed with unresolved feature pairs",
                detail={
                    "cancellation_id": detail.attempt.cancellation_id,
                    "dagster_run_id": run_id,
                    "mismatches": {
                        "non_done_members": {
                            "expected": 0,
                            "actual": [
                                member.job_id
                                for member in detail.members
                                if member.dagster_run_id == run_id
                                and member.operation_kind == "provider_feature_load"
                                and member.initial_status != "done"
                            ],
                        }
                    },
                },
            )
        async with session.begin():
            detail = await _reload_attempt(session, detail.attempt.cancellation_id)
    for member in _ordered_members(detail):
        if (
            member.dagster_run_id != run_id
            or not member.requires_run_termination
            or member.result not in {"pending", "cancel_failed"}
        ):
            continue
        async with session.begin():
            if (
                terminal_status == "SUCCESS"
                and member.operation_kind == "provider_feature_load_run"
            ):
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            await lock_provider_feature_finalization(session)
            try:
                changed = await transition_pipeline_cancellation_member(
                    session,
                    cancellation_id=detail.attempt.cancellation_id,
                    job_id=member.job_id,
                    dagster_run_id=run_id,
                    expected_status=member.initial_status,
                    target_status=target_status,
                    result=run_result,
                    error_message=error_message,
                    dagster_terminal_status=stored_terminal,
                    engine_started_at=effective_engine_started_at,
                    engine_finished_at=engine_finished_at,
                    success_tracking_invariant=False,
                )
            except PipelineCancellationConflict:
                changed = False
            if changed:
                # #975 적대 재리뷰 P2-b: running member는 Dagster terminate + ledger 전이로
                # 봉인되는데 여기에 relay event가 없으면 PinVi가 요청의 끝을 못 본다.
                # `target_status`는 `_terminal_mapping`이 주는 {cancelled, done, failed}
                # 셋뿐이고 셋 다 `CacheTargetRefreshStatus`에 있다. 처음에 `done`을 `failed`로
                # 접었다가 적대 리뷰에서 잡혔다 — Dagster SUCCESS로 ledger가 `done`을 커밋한
                # 같은 transaction에서 PinVi에 `failed`를 보내 종결 상태가 정면으로 어긋났다.
                await _append_cache_target_terminal_relay_event(
                    session,
                    job_id=member.job_id,
                    status=target_status,
                    origin="running member reconcile",
                )
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
                (item for item in current.members if item.job_id == member.job_id),
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
                job_id=member.job_id,
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
                and member.requires_run_termination
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
            engine_started_at=run.engine_started_at,
            engine_finished_at=run.engine_finished_at,
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
            engine_started_at=observation.started_at,
            engine_finished_at=observation.finished_at,
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
        engine_started_at=terminal.started_at or observation.started_at,
        engine_finished_at=terminal.finished_at,
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
                job_id=member.job_id,
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
        if (
            finished is not None
            and status == "failed"
            and failure is not None
            and failure.code == "PIPELINE_CANCELLATION_UNSAFE"
            and detail.attempt.root_kind == "import_job"
        ):
            await mark_c6c_cancel_probe_consumed(
                session,
                job_id=detail.attempt.root_id,
                cancellation_id=detail.attempt.cancellation_id,
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
        _coordinator_session(engine) as (_, fresh_session),
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
    unresolved = [member for member in detail.members if member.result == "cancel_failed"]
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

    async with _coordinator_session(engine) as (connection, session):
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
                    retry_after_seconds=(settings.pipeline_cancellation_retry_after_seconds),
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

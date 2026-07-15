"""Pipeline cancellation DTO, Dagster parser와 HTTP adapter 단위 계약."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from kortravelmap.infra.pipeline_cancellation_types import (
    PipelineCancellationAttempt,
    PipelineCancellationDetail,
    PipelineCancellationInvariantError,
    PipelineCancellationMember,
    PipelineCancellationRun,
    PipelineCancellationScope,
    PipelineCancellationTimelineConflict,
)
from pydantic import ValidationError

from kortravelmap.api import pipeline_cancellation_service as service
from kortravelmap.api.pipeline_cancellation_http import to_http_exception
from kortravelmap.api.pipeline_cancellation_schema import (
    PipelineCancellationDetailRecord,
    PipelineCancellationRequest,
    PipelineCancellationRootRecord,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 15, tzinfo=UTC)


def _infra_detail(
    *, reserved: bool = False, initial_status: str = "running"
) -> PipelineCancellationDetail:
    cancellation_id = "11111111-1111-4111-8111-111111111111"
    root_id = "22222222-2222-4222-8222-222222222222"
    return PipelineCancellationDetail(
        attempt=PipelineCancellationAttempt(
            cancellation_id=cancellation_id,
            previous_cancellation_id=None,
            root_kind="import_job",
            root_id=root_id,
            status="in_progress",
            requested_by="admin:test",
            reason=None,
            error=None,
            requested_at=_NOW,
            updated_at=_NOW,
            finished_at=None,
        ),
        members=(
            PipelineCancellationMember(
                cancellation_id=cancellation_id,
                job_id=root_id,
                dagster_run_id="run-1",
                operation_kind="provider_feature_load_run",
                requires_run_termination=True,
                initial_status=initial_status,
                result="pending",
                terminal_status=None,
                error=None,
                updated_at=_NOW,
            ),
        ),
        runs=(
            PipelineCancellationRun(
                cancellation_id=cancellation_id,
                dagster_run_id="run-1",
                initial_status="STARTED" if reserved else None,
                termination_reserved_at=_NOW if reserved else None,
                result="pending",
                terminal_status=None,
                error=None,
                updated_at=_NOW,
            ),
        ),
    )


class _NoTransactionSession:
    def in_transaction(self) -> bool:
        return False


class _TransactionSession:
    @asynccontextmanager
    async def begin(self) -> Any:
        yield


def _detail_payload(*, status: str = "completed", result: str = "cancelled") -> dict:
    return {
        "cancellation_id": "11111111-1111-4111-8111-111111111111",
        "previous_cancellation_id": None,
        "root": {
            "kind": "import_job",
            "id": "22222222-2222-4222-8222-222222222222",
        },
        "status": status,
        "requested_at": _NOW,
        "requested_by": "admin:test",
        "reason": "operator request",
        "error": None,
        "updated_at": _NOW,
        "finished_at": _NOW if status != "in_progress" else None,
        "retryable": status == "retryable",
        "unresolved_member_count": int(result in {"pending", "cancel_failed"}),
        "members": [
            {
                "job_id": "22222222-2222-4222-8222-222222222222",
                "dagster_run_id": "run-1",
                "operation_kind": "provider_feature_load_run",
                "requires_run_termination": True,
                "initial_status": "running",
                "result": result,
                "terminal_status": "cancelled" if result == "cancelled" else None,
                "error": None,
                "updated_at": _NOW,
            }
        ],
        "dagster_runs": [
            {
                "dagster_run_id": "run-1",
                "engine_started_at": _NOW,
                "engine_finished_at": _NOW,
                "initial_status": "STARTED",
                "termination_reserved_at": _NOW,
                "result": result,
                "terminal_status": "CANCELED" if result == "cancelled" else None,
                "error": None,
                "updated_at": _NOW,
            }
        ],
        "committed_data_rolled_back": False,
        "warnings": ["already committed data is retained"],
    }


def test_request_is_reason_only_and_rejects_actor_fields() -> None:
    assert PipelineCancellationRequest(reason="operator request").reason == "operator request"
    with pytest.raises(ValidationError):
        PipelineCancellationRequest.model_validate(
            {"reason": "operator request", "operator": "body-user"}
        )


def test_completed_dto_rejects_unresolved_results() -> None:
    with pytest.raises(ValidationError, match="unresolved"):
        PipelineCancellationDetailRecord.model_validate(
            _detail_payload(status="completed", result="pending")
        )


def test_root_keeps_request_correlation_but_members_are_import_jobs_only() -> None:
    payload = _detail_payload()
    payload["root"] = {
        "kind": "update_request",
        "id": "44444444-4444-4444-8444-444444444444",
    }
    detail = PipelineCancellationDetailRecord.model_validate(payload)

    assert detail.root.kind == "update_request"
    assert {str(member.job_id) for member in detail.members} == {
        "22222222-2222-4222-8222-222222222222"
    }

    payload["members"][0]["member_kind"] = "update_request"
    with pytest.raises(ValidationError):
        PipelineCancellationDetailRecord.model_validate(payload)


def test_run_dto_exposes_dispatch_reservation() -> None:
    detail = PipelineCancellationDetailRecord.model_validate(_detail_payload())

    assert detail.dagster_runs[0].termination_reserved_at == _NOW
    assert detail.dagster_runs[0].engine_started_at == _NOW
    assert detail.dagster_runs[0].engine_finished_at == _NOW
    assert detail.committed_data_rolled_back is False
    assert detail.warnings


def test_service_member_batches_follow_canonical_job_id_order() -> None:
    detail = _infra_detail()
    earlier_job = replace(
        detail.members[0],
        job_id="33333333-3333-4333-8333-333333333333",
    )
    mixed = replace(detail, members=(detail.members[0], earlier_job))

    assert [member.job_id for member in service._ordered_members(mixed)] == [
        "22222222-2222-4222-8222-222222222222",
        "33333333-3333-4333-8333-333333333333",
    ]


@pytest.mark.asyncio
async def test_run_status_parser_rejects_mismatched_run_id() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "runOrError": {
                        "__typename": "Run",
                        "runId": "other-run",
                        "status": "STARTED",
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(service._DagsterFailure) as raised:
            await service._query_run_status(
                http_client=client,
                graphql_url="http://dagster.example/graphql",
                cancellation_id="11111111-1111-4111-8111-111111111111",
                run_id="run-1",
                phase="initial_status",
            )

    assert raised.value.failure.code == "DAGSTER_TERMINATE_FAILED"
    assert "other-run" not in raised.value.failure.payload().values()


@pytest.mark.asyncio
async def test_terminate_parser_always_sends_safe_policy() -> None:
    seen_variables: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read()
        decoded = __import__("json").loads(payload)
        seen_variables.update(decoded["variables"])
        return httpx.Response(
            200,
            json={
                "data": {
                    "terminateRun": {
                        "__typename": "TerminateRunSuccess",
                        "run": {"runId": "run-1", "status": "STARTED"},
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        dispatch_failure = await service._terminate_run_once(
            http_client=client,
            graphql_url="http://dagster.example/graphql",
            cancellation_id="11111111-1111-4111-8111-111111111111",
            run_id="run-1",
        )

    assert dispatch_failure is None
    assert seen_variables == {
        "runId": "run-1",
        "terminatePolicy": "SAFE_TERMINATE",
    }


@pytest.mark.asyncio
async def test_terminate_transport_loss_is_ambiguous_not_a_second_dispatch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadError("response lost", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        dispatch_failure = await service._terminate_run_once(
            http_client=client,
            graphql_url="http://dagster.example/graphql",
            cancellation_id="11111111-1111-4111-8111-111111111111",
            run_id="run-1",
        )

    assert dispatch_failure is not None
    assert dispatch_failure.code == "DAGSTER_UNAVAILABLE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "payload"),
    [
        (500, {"error": "definitive"}),
        (200, {"data": {"terminateRun": {"bad": "shape"}}}),
    ],
)
async def test_terminate_http_and_protocol_failures_are_not_ambiguous(
    status_code: int,
    payload: dict[str, Any],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(service._DagsterFailure) as raised:
            await service._terminate_run_once(
                http_client=client,
                graphql_url="http://dagster.example/graphql",
                cancellation_id="11111111-1111-4111-8111-111111111111",
                run_id="run-1",
            )

    assert raised.value.failure.code == "DAGSTER_TERMINATE_FAILED"


@pytest.mark.asyncio
async def test_reservation_cas_loser_joins_poll_without_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale = _infra_detail()
    reserved = _infra_detail(reserved=True)
    calls = {"mutation": 0, "poll": 0, "join": 0}

    async def query_status(**_kwargs: Any) -> service._RunObservation:
        return service._RunObservation(run_id="run-1", status="STARTED")

    async def lose_reservation(*_args: Any, **_kwargs: Any) -> bool:
        return False

    async def join(*_args: Any, **_kwargs: Any) -> PipelineCancellationDetail:
        calls["join"] += 1
        return reserved

    async def terminate(**_kwargs: Any) -> None:
        calls["mutation"] += 1

    async def poll(**_kwargs: Any) -> service._RunObservation:
        calls["poll"] += 1
        return service._RunObservation(run_id="run-1", status="CANCELED")

    async def record_terminal(
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[PipelineCancellationDetail, None]:
        return reserved, None

    monkeypatch.setattr(service, "_query_run_status", query_status)
    monkeypatch.setattr(service, "_reserve_run", lose_reservation)
    monkeypatch.setattr(service, "_join_reserved_run_after_cas_loss", join)
    monkeypatch.setattr(service, "_terminate_run_once", terminate)
    monkeypatch.setattr(service, "_poll_terminal_status", poll)
    monkeypatch.setattr(service, "_record_terminal_run", record_terminal)

    async with httpx.AsyncClient() as client:
        await service._process_pending_run(
            _NoTransactionSession(),  # type: ignore[arg-type]
            stale,
            run_id="run-1",
            settings=service.ApiSettings(),
            http_client=client,
            graphql_url="http://dagster.example/graphql",
        )

    assert calls == {"mutation": 0, "poll": 1, "join": 1}


@pytest.mark.asyncio
async def test_ambiguous_dispatch_preserves_original_cause_when_poll_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = _infra_detail()
    dispatch_failure = service._Failure(
        code="DAGSTER_UNAVAILABLE",
        message="terminate response was lost",
        details={"phase": "terminate"},
    )
    poll_failure = service._Failure(
        code="DAGSTER_TERMINATION_TIMEOUT",
        message="terminal poll timed out",
        details={"phase": "terminal_poll"},
    )
    recorded: list[service._Failure] = []

    async def query_status(**_kwargs: Any) -> service._RunObservation:
        return service._RunObservation(run_id="run-1", status="STARTED")

    async def reserve(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def terminate(**_kwargs: Any) -> service._Failure:
        return dispatch_failure

    async def poll(**_kwargs: Any) -> service._RunObservation:
        raise service._DagsterFailure(poll_failure)

    async def record_failure(
        *_args: Any,
        failure: service._Failure,
        **_kwargs: Any,
    ) -> PipelineCancellationDetail:
        recorded.append(failure)
        return detail

    monkeypatch.setattr(service, "_query_run_status", query_status)
    monkeypatch.setattr(service, "_reserve_run", reserve)
    monkeypatch.setattr(service, "_terminate_run_once", terminate)
    monkeypatch.setattr(service, "_poll_terminal_status", poll)
    monkeypatch.setattr(service, "_record_run_failure", record_failure)

    async with httpx.AsyncClient() as client:
        _updated, failure = await service._process_pending_run(
            _NoTransactionSession(),  # type: ignore[arg-type]
            detail,
            run_id="run-1",
            settings=service.ApiSettings(),
            http_client=client,
            graphql_url="http://dagster.example/graphql",
        )

    assert failure is dispatch_failure
    assert recorded == [dispatch_failure]


@pytest.mark.asyncio
async def test_run_backed_queued_member_uses_single_terminate_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = _infra_detail(initial_status="queued")
    started_at = _NOW
    finished_at = datetime(2026, 7, 15, 0, 0, 3, tzinfo=UTC)
    calls = {"reserve": 0, "terminate": 0}
    recorded: dict[str, Any] = {}

    async def query_status(**_kwargs: Any) -> service._RunObservation:
        return service._RunObservation(run_id="run-1", status="STARTING")

    async def reserve(*_args: Any, **_kwargs: Any) -> bool:
        calls["reserve"] += 1
        return True

    async def terminate(**_kwargs: Any) -> None:
        calls["terminate"] += 1

    async def poll(**_kwargs: Any) -> service._RunObservation:
        return service._RunObservation(
            run_id="run-1",
            status="CANCELED",
            started_at=started_at,
            finished_at=finished_at,
        )

    async def record_terminal(
        *_args: Any,
        **kwargs: Any,
    ) -> tuple[PipelineCancellationDetail, None]:
        recorded.update(kwargs)
        return detail, None

    monkeypatch.setattr(service, "_query_run_status", query_status)
    monkeypatch.setattr(service, "_reserve_run", reserve)
    monkeypatch.setattr(service, "_terminate_run_once", terminate)
    monkeypatch.setattr(service, "_poll_terminal_status", poll)
    monkeypatch.setattr(service, "_record_terminal_run", record_terminal)

    async with httpx.AsyncClient() as client:
        await service._process_pending_run(
            _NoTransactionSession(),  # type: ignore[arg-type]
            detail,
            run_id="run-1",
            settings=service.ApiSettings(),
            http_client=client,
            graphql_url="http://dagster.example/graphql",
        )

    assert calls == {"reserve": 1, "terminate": 1}
    assert recorded["terminal_status"] == "CANCELED"
    assert recorded["engine_started_at"] == started_at
    assert recorded["engine_finished_at"] == finished_at


@pytest.mark.asyncio
async def test_terminal_timeline_conflict_routes_to_durable_reconcile_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = _infra_detail()
    recorded: list[service._Failure] = []

    async def timeline_conflict(*_args: Any, **_kwargs: Any) -> bool:
        raise PipelineCancellationTimelineConflict("frozen timeline conflict")

    async def record_failure(
        *_args: Any,
        failure: service._Failure,
        **_kwargs: Any,
    ) -> PipelineCancellationDetail:
        recorded.append(failure)
        return detail

    monkeypatch.setattr(
        service, "set_pipeline_cancellation_run_result", timeline_conflict
    )
    monkeypatch.setattr(service, "_record_run_failure", record_failure)

    updated, failure = await service._record_terminal_run(
        _TransactionSession(),  # type: ignore[arg-type]
        detail,
        run_id="run-1",
        initial_status="STARTED",
        terminal_status="CANCELED",
        engine_started_at=_NOW,
        engine_finished_at=_NOW,
    )

    assert updated is detail
    assert failure is recorded[0]
    assert failure.code == "DAGSTER_RECONCILE_FAILED"
    assert failure.details["phase"] == "terminal_timeline"


@pytest.mark.asyncio
async def test_orphan_terminal_identity_drift_remains_invariant_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = _infra_detail()

    async def programmer_invariant(*_args: Any, **_kwargs: Any) -> bool:
        raise PipelineCancellationInvariantError("recorded orphan result drift")

    async def unexpected(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("generic invariant must not be reclassified")

    monkeypatch.setattr(
        service, "set_pipeline_cancellation_run_result", programmer_invariant
    )
    monkeypatch.setattr(service, "_record_run_failure", unexpected)

    with pytest.raises(
        PipelineCancellationInvariantError, match="recorded orphan result drift"
    ):
        await service._record_terminal_run(
            _TransactionSession(),  # type: ignore[arg-type]
            detail,
            run_id="run-1",
            initial_status="STARTED",
            terminal_status="CANCELED",
            engine_started_at=_NOW,
            engine_finished_at=_NOW,
        )


@pytest.mark.asyncio
async def test_prepare_detects_canonical_root_drift_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    drifted = PipelineCancellationScope(
        root_kind="update_request",
        root_id="33333333-3333-4333-8333-333333333333",
        members=(),
    )

    async def resolve(*_args: Any, **_kwargs: Any) -> PipelineCancellationScope:
        return drifted

    async def unexpected(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("root drift must stop before attempt mutation")

    monkeypatch.setattr(service, "resolve_pipeline_cancellation_scope", resolve)
    monkeypatch.setattr(service, "create_pipeline_cancellation_attempt", unexpected)

    prepared = await service._prepare_attempt(
        _NoTransactionSession(),  # type: ignore[arg-type]
        kind="import_job",
        execution_id="22222222-2222-4222-8222-222222222222",
        root_kind="import_job",
        root_id="22222222-2222-4222-8222-222222222222",
        requested_by="admin:test",
        reason=None,
        retry_after_seconds=3,
    )

    assert prepared is None


class _LeaseResult:
    def __init__(self, value: bool) -> None:
        self.value = value

    def scalar_one(self) -> bool:
        return self.value


class _LeaseSession:
    def __init__(self, *, unlocked: bool = False, error: Exception | None = None) -> None:
        self.unlocked = unlocked
        self.error = error

    def in_transaction(self) -> bool:
        return False

    async def execute(self, *_args: Any, **_kwargs: Any) -> _LeaseResult:
        if self.error is not None:
            raise self.error
        return _LeaseResult(self.unlocked)

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class _PoolProxy:
    def __init__(self, *, fail_hard: bool = False) -> None:
        self.fail_hard = fail_hard
        self.hard_invalidated = False
        self.terminated = False
        driver = SimpleNamespace(terminate=self._terminate)
        self.driver_connection = driver
        self.dbapi_connection = SimpleNamespace(driver_connection=driver)

    def invalidate(self, *_args: Any, **_kwargs: Any) -> None:
        if self.fail_hard:
            raise RuntimeError("hard invalidate failed")
        self.hard_invalidated = True

    def _terminate(self) -> None:
        self.terminated = True


class _LeaseConnection:
    def __init__(self, *, fail_async: bool = False, fail_hard: bool = False) -> None:
        self.fail_async = fail_async
        self.invalidated = False
        self.proxy = _PoolProxy(fail_hard=fail_hard)
        self.sync_connection = SimpleNamespace(connection=self.proxy)

    async def invalidate(self, _cause: BaseException | None = None) -> None:
        if self.fail_async:
            raise RuntimeError("async invalidate failed")
        self.invalidated = True


@pytest.mark.asyncio
@pytest.mark.parametrize("unlock_error", [None, RuntimeError("unlock failed")])
async def test_unlock_false_or_exception_never_returns_success(
    unlock_error: Exception | None,
) -> None:
    session = _LeaseSession(unlocked=False, error=unlock_error)
    connection = _LeaseConnection()

    with pytest.raises(service.PipelineCancellationUnsafe):
        await service._release_coordinator_lease(
            session,  # type: ignore[arg-type]
            connection,  # type: ignore[arg-type]
            lease_key=1,
        )

    assert connection.invalidated is True


@pytest.mark.asyncio
async def test_unlock_uses_sync_then_physical_hard_invalidate_fallbacks() -> None:
    sync_connection = _LeaseConnection(fail_async=True)
    with pytest.raises(service.PipelineCancellationUnsafe):
        await service._release_coordinator_lease(
            _LeaseSession(),  # type: ignore[arg-type]
            sync_connection,  # type: ignore[arg-type]
            lease_key=1,
        )
    assert sync_connection.proxy.hard_invalidated is True

    physical_connection = _LeaseConnection(fail_async=True, fail_hard=True)
    with pytest.raises(service.PipelineCancellationUnsafe):
        await service._release_coordinator_lease(
            _LeaseSession(),  # type: ignore[arg-type]
            physical_connection,  # type: ignore[arg-type]
            lease_key=1,
        )
    assert physical_connection.proxy.terminated is True


def test_http_adapter_preserves_pre_marker_lease_shape() -> None:
    root = PipelineCancellationRootRecord(
        kind="import_job",
        id="22222222-2222-4222-8222-222222222222",
    )
    error = service.PipelineCancellationInProgress(
        "coordinator busy",
        root=root,
        retry_after_seconds=3,
    )

    mapped = to_http_exception(error)

    assert mapped.status_code == 409
    assert mapped.headers == {"Retry-After": "3"}
    assert mapped.detail["details"] == {
        "root": root.model_dump(mode="json"),
        "cancellation": None,
    }

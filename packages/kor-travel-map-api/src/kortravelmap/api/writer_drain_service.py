"""Private cache-target writer-drain command service.

이 모듈은 one-shot API image command만 호출한다. public REST/router/token에
연결하지 않으며, Dagster raw identity는 Map DB에만 보관한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from time import monotonic
from typing import Final, Literal, cast
from uuid import UUID

import httpx
from kortravelmap.infra.writer_drain_repo import (
    WriterDrainInstigation,
    WriterDrainInstigationSnapshot,
    WriterDrainLease,
    create_writer_drain_lease,
    get_active_writer_drain_lease,
    get_writer_drain_instigations,
    get_writer_drain_lease,
    get_writer_drain_runs,
    mark_writer_drain_instigation_paused,
    mark_writer_drain_instigation_restored,
    mark_writer_drain_run_dispatched,
    mark_writer_drain_run_outcome_uncertain,
    mark_writer_drain_run_terminal,
    record_writer_drain_failure,
    refresh_writer_drain_receipt,
    reserve_writer_drain_run_cancel,
    reset_writer_drain_begin_receipt,
    set_writer_drain_receipt,
    set_writer_drain_state,
    upsert_writer_drain_run,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kortravelmap.api import dagster_graphql
from kortravelmap.api.settings import ApiSettings

__all__ = [
    "CONTRACT_VERSION",
    "WriterDrainCommandError",
    "WriterDrainReceipt",
    "WriterDrainRequest",
    "execute_writer_drain",
]

CONTRACT_VERSION: Final = "ktm-cache-target-writer-drain/v1"
_MAX_NONTERMINAL_RUNS: Final = 1_000
_NONTERMINAL_RUN_STATUSES: Final = (
    "QUEUED",
    "NOT_STARTED",
    "STARTED",
    "MANAGED",
    "CANCELING",
)
_TERMINAL_RUN_STATUSES: Final = frozenset({"SUCCESS", "FAILURE", "CANCELED"})

_INSTIGATIONS_QUERY: Final = """
query KorTravelMapWriterDrainInstigations {
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        name
        location { name }
        schedules {
          name
          scheduleState {
            id selectorId status repositoryName repositoryLocationName
          }
        }
        sensors {
          name
          sensorState {
            id selectorId status repositoryName repositoryLocationName
          }
        }
      }
    }
    ... on PythonError { message }
  }
}
"""

_NONTERMINAL_RUNS_QUERY: Final = """
query KorTravelMapWriterDrainRuns($limit: Int!) {
  runsOrError(
    filter: {statuses: [QUEUED, NOT_STARTED, STARTED, MANAGED, CANCELING]},
    limit: $limit
  ) {
    __typename
    ... on Runs { results { runId status } }
    ... on PythonError { message }
  }
}
"""

_RUN_STATUS_QUERY: Final = """
query KorTravelMapWriterDrainRunStatus($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run { runId status }
    ... on RunNotFoundError { runId message }
    ... on PythonError { message }
  }
}
"""

_TERMINATE_RUN_MUTATION: Final = """
mutation KorTravelMapWriterDrainTerminateRun($runId: String!) {
  terminateRun(runId: $runId, terminatePolicy: SAFE_TERMINATE) {
    __typename
    ... on TerminateRunSuccess { run { runId status } }
    ... on TerminateRunFailure { run { runId status } message }
    ... on RunNotFoundError { runId message }
    ... on UnauthorizedError { message }
    ... on PythonError { message }
  }
}
"""

_START_SCHEDULE_MUTATION: Final = """
mutation KorTravelMapWriterDrainStartSchedule($selector: ScheduleSelector!) {
  startSchedule(scheduleSelector: $selector) {
    __typename
    ... on ScheduleStateResult { scheduleState { status } }
    ... on ScheduleNotFoundError { message }
    ... on UnauthorizedError { message }
    ... on PythonError { message }
  }
}
"""

_STOP_SCHEDULE_MUTATION: Final = """
mutation KorTravelMapWriterDrainStopSchedule(
  $id: String!, $originId: String!, $selectorId: String!
) {
  stopRunningSchedule(
    id: $id, scheduleOriginId: $originId, scheduleSelectorId: $selectorId
  ) {
    __typename
    ... on ScheduleStateResult { scheduleState { status } }
    ... on ScheduleNotFoundError { message }
    ... on UnauthorizedError { message }
    ... on PythonError { message }
  }
}
"""

_START_SENSOR_MUTATION: Final = """
mutation KorTravelMapWriterDrainStartSensor($selector: SensorSelector!) {
  startSensor(sensorSelector: $selector) {
    __typename
    ... on SensorState { status }
    ... on SensorNotFoundError { message }
    ... on UnauthorizedError { message }
    ... on PythonError { message }
  }
}
"""

_STOP_SENSOR_MUTATION: Final = """
mutation KorTravelMapWriterDrainStopSensor(
  $id: String!, $originId: String!, $selectorId: String!
) {
  stopSensor(id: $id, sensorOriginId: $originId, sensorSelectorId: $selectorId) {
    __typename
    ... on SensorState { status }
    ... on SensorNotFoundError { message }
    ... on UnauthorizedError { message }
    ... on PythonError { message }
  }
}
"""


class WriterDrainCommandError(RuntimeError):
    """secret-free stable error code만 command entrypoint에 전달한다."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class WriterDrainRequest:
    operation: Literal["begin", "attest", "restore"]
    owner_kind: Literal["diagnostic", "cutover"]
    owner_id: UUID
    lease_id: UUID | None
    prior_receipt_sha256: str | None


@dataclass(frozen=True)
class WriterDrainReceipt:
    contract_version: str
    operation: Literal["begin", "attest", "restore"]
    owner_kind: Literal["diagnostic", "cutover"]
    owner_id: str
    lease_id: str
    state: Literal["drained", "restored"]
    prior_receipt_sha256: str | None
    snapshot_sha256: str
    run_count: int
    terminal_cancel_count: int
    receipt_sha256: str

    def json_bytes(self) -> bytes:
        return _canonical_json_bytes(asdict(self))


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _receipt_digest(fields: dict[str, object]) -> str:
    return hashlib.sha256(_canonical_json_bytes(fields)).hexdigest()


def _receipt(
    *,
    operation: Literal["begin", "attest", "restore"],
    lease: WriterDrainLease,
    state: Literal["drained", "restored"],
    prior_receipt_sha256: str | None,
    terminal_cancel_count: int,
) -> WriterDrainReceipt:
    fields: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "operation": operation,
        "owner_kind": lease.owner_kind,
        "owner_id": str(lease.owner_id),
        "lease_id": str(lease.lease_id),
        "state": state,
        "prior_receipt_sha256": prior_receipt_sha256,
        "snapshot_sha256": lease.snapshot_sha256,
        "run_count": 0,
        "terminal_cancel_count": terminal_cancel_count,
    }
    return WriterDrainReceipt(
        contract_version=CONTRACT_VERSION,
        operation=operation,
        owner_kind=cast(Literal["diagnostic", "cutover"], lease.owner_kind),
        owner_id=str(lease.owner_id),
        lease_id=str(lease.lease_id),
        state=state,
        prior_receipt_sha256=prior_receipt_sha256,
        snapshot_sha256=lease.snapshot_sha256,
        run_count=0,
        terminal_cancel_count=terminal_cancel_count,
        receipt_sha256=_receipt_digest(fields),
    )


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise WriterDrainCommandError(code)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() == value and value else None


def _status(value: object) -> str | None:
    raw = _text(value)
    return raw.upper() if raw is not None else None


def _origin_id(state_id: str) -> str:
    return state_id.split("::", 1)[0]


def _snapshot_digest(
    instigations: tuple[WriterDrainInstigation | WriterDrainInstigationSnapshot, ...],
) -> str:
    rows = [
        {
            "kind": item.kind,
            "selector_id": item.selector_id,
            "state_id": item.state_id,
            "origin_id": item.origin_id,
            "instigation_name": item.instigation_name,
            "repository_name": item.repository_name,
            "repository_location_name": item.repository_location_name,
            "was_running": item.was_running,
        }
        for item in instigations
    ]
    return hashlib.sha256(
        _canonical_json_bytes(sorted(rows, key=lambda item: (item["kind"], item["selector_id"])))
    ).hexdigest()


async def _post(
    *,
    http_client: httpx.AsyncClient,
    graphql_url: str,
    query: str,
    variables: dict[str, object],
) -> dict[str, object]:
    try:
        payload = await dagster_graphql.post_graphql(
            client=http_client,
            graphql_url=graphql_url,
            query=query,
            variables=variables,
        )
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        raise WriterDrainCommandError("DAGSTER_UNAVAILABLE") from exc
    if isinstance(payload.get("errors"), list) and payload["errors"]:
        raise WriterDrainCommandError("DAGSTER_PROTOCOL")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise WriterDrainCommandError("DAGSTER_PROTOCOL")
    return data


async def _list_instigations(
    *, http_client: httpx.AsyncClient, graphql_url: str
) -> tuple[WriterDrainInstigationSnapshot, ...]:
    data = await _post(
        http_client=http_client,
        graphql_url=graphql_url,
        query=_INSTIGATIONS_QUERY,
        variables={},
    )
    connection = data.get("repositoriesOrError")
    if not isinstance(connection, dict) or connection.get("__typename") != "RepositoryConnection":
        raise WriterDrainCommandError("DAGSTER_PROTOCOL")
    nodes = connection.get("nodes")
    if not isinstance(nodes, list):
        raise WriterDrainCommandError("DAGSTER_PROTOCOL")
    snapshots: list[WriterDrainInstigationSnapshot] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise WriterDrainCommandError("DAGSTER_PROTOCOL")
        repository_name = _text(node.get("name"))
        location = node.get("location")
        repository_location_name = (
            _text(location.get("name")) if isinstance(location, dict) else None
        )
        _require(
            repository_name is not None and repository_location_name is not None,
            "DAGSTER_PROTOCOL",
        )
        assert repository_name is not None
        assert repository_location_name is not None
        for kind, field, state_field in (
            ("schedule", "schedules", "scheduleState"),
            ("sensor", "sensors", "sensorState"),
        ):
            entries = node.get(field)
            if not isinstance(entries, list):
                raise WriterDrainCommandError("DAGSTER_PROTOCOL")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise WriterDrainCommandError("DAGSTER_PROTOCOL")
                state = entry.get(state_field)
                if not isinstance(state, dict):
                    raise WriterDrainCommandError("DAGSTER_PROTOCOL")
                name = _text(entry.get("name"))
                state_id = _text(state.get("id"))
                selector_id = _text(state.get("selectorId"))
                status = _status(state.get("status"))
                state_repository_name = _text(state.get("repositoryName")) or repository_name
                state_location_name = (
                    _text(state.get("repositoryLocationName")) or repository_location_name
                )
                _require(
                    name is not None
                    and state_id is not None
                    and selector_id is not None
                    and status in {"RUNNING", "STOPPED"},
                    "DAGSTER_PROTOCOL",
                )
                assert name is not None
                assert state_id is not None
                assert selector_id is not None
                assert status in {"RUNNING", "STOPPED"}
                snapshots.append(
                    WriterDrainInstigationSnapshot(
                        kind=cast(Literal["schedule", "sensor"], kind),
                        selector_id=selector_id,
                        state_id=state_id,
                        origin_id=_origin_id(state_id),
                        instigation_name=name,
                        repository_name=state_repository_name,
                        repository_location_name=state_location_name,
                        was_running=status == "RUNNING",
                        pause_result="pending" if status == "RUNNING" else "not_required",
                        restore_result="not_requested",
                    )
                )
    key_set = {(item.kind, item.selector_id) for item in snapshots}
    _require(len(key_set) == len(snapshots), "DAGSTER_PROTOCOL")
    return tuple(sorted(snapshots, key=lambda item: (item.kind, item.selector_id)))


async def _list_nonterminal_runs(
    *, http_client: httpx.AsyncClient, graphql_url: str
) -> tuple[tuple[str, str], ...]:
    data = await _post(
        http_client=http_client,
        graphql_url=graphql_url,
        query=_NONTERMINAL_RUNS_QUERY,
        variables={"limit": _MAX_NONTERMINAL_RUNS},
    )
    result = data.get("runsOrError")
    if not isinstance(result, dict) or result.get("__typename") != "Runs":
        raise WriterDrainCommandError("DAGSTER_PROTOCOL")
    entries = result.get("results")
    if not isinstance(entries, list) or len(entries) >= _MAX_NONTERMINAL_RUNS:
        raise WriterDrainCommandError("RUN_DRAIN_LIMIT_REACHED")
    runs: list[tuple[str, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise WriterDrainCommandError("DAGSTER_PROTOCOL")
        run_id = _text(entry.get("runId"))
        status = _status(entry.get("status"))
        _require(run_id is not None and status in _NONTERMINAL_RUN_STATUSES, "DAGSTER_PROTOCOL")
        assert run_id is not None
        assert status is not None
        runs.append((run_id, status))
    _require(len({run_id for run_id, _status_value in runs}) == len(runs), "DAGSTER_PROTOCOL")
    return tuple(sorted(runs))


async def _query_run_status(
    *, http_client: httpx.AsyncClient, graphql_url: str, run_id: str
) -> str:
    data = await _post(
        http_client=http_client,
        graphql_url=graphql_url,
        query=_RUN_STATUS_QUERY,
        variables={"runId": run_id},
    )
    result = data.get("runOrError")
    if not isinstance(result, dict) or result.get("__typename") != "Run":
        raise WriterDrainCommandError("DAGSTER_PROTOCOL")
    observed_run_id = _text(result.get("runId"))
    status = _status(result.get("status"))
    _require(observed_run_id == run_id and status is not None, "DAGSTER_PROTOCOL")
    assert status is not None
    return status


def _selector(instigation: WriterDrainInstigation) -> dict[str, str]:
    base = {
        "repositoryName": instigation.repository_name,
        "repositoryLocationName": instigation.repository_location_name,
    }
    if instigation.kind == "schedule":
        return {**base, "scheduleName": instigation.instigation_name}
    return {**base, "sensorName": instigation.instigation_name}


async def _mutate_instigation(
    *,
    http_client: httpx.AsyncClient,
    graphql_url: str,
    instigation: WriterDrainInstigation,
    start: bool,
) -> None:
    if instigation.kind == "schedule":
        query = _START_SCHEDULE_MUTATION if start else _STOP_SCHEDULE_MUTATION
        key = "startSchedule" if start else "stopRunningSchedule"
        variables: dict[str, object] = (
            {"selector": _selector(instigation)}
            if start
            else {
                "id": instigation.state_id,
                "originId": instigation.origin_id,
                "selectorId": instigation.selector_id,
            }
        )
        success_types = {"ScheduleStateResult"}
        state_key = "scheduleState"
    else:
        query = _START_SENSOR_MUTATION if start else _STOP_SENSOR_MUTATION
        key = "startSensor" if start else "stopSensor"
        variables = (
            {"selector": _selector(instigation)}
            if start
            else {
                "id": instigation.state_id,
                "originId": instigation.origin_id,
                "selectorId": instigation.selector_id,
            }
        )
        success_types = {"SensorState"}
        state_key = "sensorState"
    data = await _post(
        http_client=http_client,
        graphql_url=graphql_url,
        query=query,
        variables=variables,
    )
    result = data.get(key)
    if not isinstance(result, dict) or result.get("__typename") not in success_types:
        raise WriterDrainCommandError("DAGSTER_MUTATION_FAILED")
    state = result.get(state_key) if state_key in result else result
    if not isinstance(state, dict):
        raise WriterDrainCommandError("DAGSTER_PROTOCOL")
    expected = "RUNNING" if start else "STOPPED"
    _require(_status(state.get("status")) == expected, "DAGSTER_MUTATION_FAILED")


async def _terminate_run_once(
    *, http_client: httpx.AsyncClient, graphql_url: str, run_id: str
) -> str:
    data = await _post(
        http_client=http_client,
        graphql_url=graphql_url,
        query=_TERMINATE_RUN_MUTATION,
        variables={"runId": run_id},
    )
    result = data.get("terminateRun")
    if not isinstance(result, dict) or result.get("__typename") != "TerminateRunSuccess":
        raise WriterDrainCommandError("RUN_CANCEL_OUTCOME_UNCERTAIN")
    run = result.get("run")
    if not isinstance(run, dict):
        raise WriterDrainCommandError("DAGSTER_PROTOCOL")
    observed_run_id = _text(run.get("runId"))
    status = _status(run.get("status"))
    _require(observed_run_id == run_id and status is not None, "DAGSTER_PROTOCOL")
    assert status is not None
    return status


async def _load_lease_for_request(
    *, session_factory: async_sessionmaker[AsyncSession], request: WriterDrainRequest
) -> WriterDrainLease:
    _require(request.lease_id is not None, "INVALID_COMMAND")
    assert request.lease_id is not None
    async with session_factory() as session, session.begin():
        lease = await get_writer_drain_lease(session, lease_id=request.lease_id, lock=True)
    _require(lease is not None, "WRITER_DRAIN_LEASE_NOT_FOUND")
    assert lease is not None
    _require(
        lease.owner_kind == request.owner_kind and lease.owner_id == request.owner_id,
        "WRITER_DRAIN_OWNER_MISMATCH",
    )
    return lease


async def _record_failure(
    *, session_factory: async_sessionmaker[AsyncSession], lease_id: UUID, code: str
) -> None:
    async with session_factory() as session, session.begin():
        await record_writer_drain_failure(session, lease_id=lease_id, failure_code=code)


async def _begin_lease(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    request: WriterDrainRequest,
    snapshot: tuple[WriterDrainInstigationSnapshot, ...],
) -> WriterDrainLease:
    async with session_factory() as session:
        try:
            async with session.begin():
                active = await get_active_writer_drain_lease(session, lock=True)
                if active is not None:
                    _require(
                        active.owner_kind == request.owner_kind
                        and active.owner_id == request.owner_id,
                        "WRITER_DRAIN_ACTIVE_OTHER_OWNER",
                    )
                    return active
                return await create_writer_drain_lease(
                    session,
                    owner_kind=request.owner_kind,
                    owner_id=request.owner_id,
                    snapshot_sha256=_snapshot_digest(snapshot),
                    instigations=snapshot,
                )
        except IntegrityError as exc:
            raise WriterDrainCommandError("WRITER_DRAIN_ACTIVE_OTHER_OWNER") from exc


async def _verify_snapshot(
    *, session_factory: async_sessionmaker[AsyncSession], lease: WriterDrainLease
) -> tuple[WriterDrainInstigation, ...]:
    async with session_factory() as session:
        instigations = await get_writer_drain_instigations(session, lease_id=lease.lease_id)
    _require(
        _snapshot_digest(instigations) == lease.snapshot_sha256,
        "WRITER_DRAIN_SNAPSHOT_MISMATCH",
    )
    return instigations


async def _pause_instigations(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    lease: WriterDrainLease,
) -> None:
    instigations = await _verify_snapshot(session_factory=session_factory, lease=lease)
    observed = {
        (item.kind, item.selector_id): item
        for item in await _list_instigations(http_client=http_client, graphql_url=graphql_url)
    }
    _require(
        set(observed) == {(item.kind, item.selector_id) for item in instigations},
        "DAGSTER_INSTIGATION_DRIFT",
    )
    for instigation in instigations:
        state = observed[(instigation.kind, instigation.selector_id)]
        if not instigation.was_running:
            _require(not state.was_running, "DAGSTER_INSTIGATION_DRIFT")
            continue
        if not state.was_running:
            async with session_factory() as session, session.begin():
                await mark_writer_drain_instigation_paused(
                    session,
                    lease_id=lease.lease_id,
                    kind=instigation.kind,
                    selector_id=instigation.selector_id,
                    result="already_stopped",
                )
            continue
        await _mutate_instigation(
            http_client=http_client,
            graphql_url=graphql_url,
            instigation=instigation,
            start=False,
        )
        async with session_factory() as session, session.begin():
            await mark_writer_drain_instigation_paused(
                session,
                lease_id=lease.lease_id,
                kind=instigation.kind,
                selector_id=instigation.selector_id,
                result="paused",
            )


async def _observe_nonterminal_runs(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    lease: WriterDrainLease,
) -> tuple[tuple[str, str], ...]:
    runs = await _list_nonterminal_runs(http_client=http_client, graphql_url=graphql_url)
    async with session_factory() as session, session.begin():
        for run_id, status in runs:
            await upsert_writer_drain_run(
                session,
                lease_id=lease.lease_id,
                dagster_run_id=run_id,
                initial_status=status,
            )
    return runs


async def _record_terminal_runs(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    lease: WriterDrainLease,
) -> None:
    async with session_factory() as session:
        runs = await get_writer_drain_runs(session, lease_id=lease.lease_id)
    for run in runs:
        if run.terminal_status is not None:
            continue
        status = await _query_run_status(
            http_client=http_client,
            graphql_url=graphql_url,
            run_id=run.dagster_run_id,
        )
        _require(status in _TERMINAL_RUN_STATUSES, "RUN_DRAIN_NOT_TERMINAL")
        async with session_factory() as session, session.begin():
            await mark_writer_drain_run_terminal(
                session,
                lease_id=lease.lease_id,
                dagster_run_id=run.dagster_run_id,
                terminal_status=status,
            )


async def _assert_drained(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    lease: WriterDrainLease,
) -> int:
    instigations = await _verify_snapshot(session_factory=session_factory, lease=lease)
    observed = {
        (item.kind, item.selector_id): item
        for item in await _list_instigations(http_client=http_client, graphql_url=graphql_url)
    }
    _require(
        set(observed) == {(item.kind, item.selector_id) for item in instigations},
        "DAGSTER_INSTIGATION_DRIFT",
    )
    _require(
        not any(item.was_running for item in observed.values()),
        "DAGSTER_INSTIGATION_NOT_PAUSED",
    )
    runs = await _observe_nonterminal_runs(
        session_factory=session_factory,
        http_client=http_client,
        graphql_url=graphql_url,
        lease=lease,
    )
    _require(not runs, "RUN_DRAIN_NOT_TERMINAL")
    await _record_terminal_runs(
        session_factory=session_factory,
        http_client=http_client,
        graphql_url=graphql_url,
        lease=lease,
    )
    async with session_factory() as session:
        persisted = await get_writer_drain_runs(session, lease_id=lease.lease_id)
    _require(
        all(item.terminal_status in _TERMINAL_RUN_STATUSES for item in persisted),
        "RUN_DRAIN_NOT_TERMINAL",
    )
    return sum(item.cancel_dispatched_at is not None for item in persisted)


async def _cancel_remaining_runs_once(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    lease: WriterDrainLease,
    runs: tuple[tuple[str, str], ...],
) -> None:
    for run_id, _status_value in runs:
        async with session_factory() as session, session.begin():
            reserved = await reserve_writer_drain_run_cancel(
                session,
                lease_id=lease.lease_id,
                dagster_run_id=run_id,
            )
        if not reserved:
            continue
        try:
            status = await _terminate_run_once(
                http_client=http_client,
                graphql_url=graphql_url,
                run_id=run_id,
            )
        except WriterDrainCommandError as exc:
            async with session_factory() as session, session.begin():
                await mark_writer_drain_run_outcome_uncertain(
                    session,
                    lease_id=lease.lease_id,
                    dagster_run_id=run_id,
                )
            raise exc
        async with session_factory() as session, session.begin():
            if status in _TERMINAL_RUN_STATUSES:
                await mark_writer_drain_run_terminal(
                    session,
                    lease_id=lease.lease_id,
                    dagster_run_id=run_id,
                    terminal_status=status,
                    dispatched=True,
                )
            else:
                changed = await mark_writer_drain_run_dispatched(
                    session,
                    lease_id=lease.lease_id,
                    dagster_run_id=run_id,
                )
                _require(changed, "WRITER_DRAIN_RUN_CAS_CONFLICT")


async def _drain_runs(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    settings: ApiSettings,
    lease: WriterDrainLease,
) -> None:
    grace_deadline = monotonic() + min(15.0, settings.dagster_termination_timeout_seconds / 2)
    while True:
        runs = await _observe_nonterminal_runs(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=graphql_url,
            lease=lease,
        )
        if not runs:
            return
        if monotonic() >= grace_deadline:
            break
        await asyncio.sleep(settings.dagster_termination_poll_interval_seconds)
    await _cancel_remaining_runs_once(
        session_factory=session_factory,
        http_client=http_client,
        graphql_url=graphql_url,
        lease=lease,
        runs=runs,
    )
    terminal_deadline = monotonic() + settings.dagster_termination_timeout_seconds
    while True:
        runs = await _observe_nonterminal_runs(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=graphql_url,
            lease=lease,
        )
        if not runs:
            return
        # schedule/sensor pause와 이미 큐에 들어간 run 생성은 원자적이지 않다.
        # grace 종료 뒤 처음 보이는 run도 동일한 lease의 run별 CAS로 한 번만
        # cancel dispatch한다. 이미 dispatch한 run은 reservation이 false라 재전송하지
        # 않는다.
        await _cancel_remaining_runs_once(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=graphql_url,
            lease=lease,
            runs=runs,
        )
        if monotonic() >= terminal_deadline:
            async with session_factory() as session:
                persisted = await get_writer_drain_runs(session, lease_id=lease.lease_id)
            _require(
                not any(item.cancel_result == "outcome_uncertain" for item in persisted),
                "RUN_CANCEL_OUTCOME_UNCERTAIN",
            )
            raise WriterDrainCommandError("RUN_DRAIN_TIMEOUT")
        await asyncio.sleep(settings.dagster_termination_poll_interval_seconds)


async def _finalize_drained(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    lease: WriterDrainLease,
    operation: Literal["begin", "attest"],
    prior_receipt_sha256: str | None,
    terminal_cancel_count: int,
) -> WriterDrainReceipt:
    receipt = _receipt(
        operation=operation,
        lease=lease,
        state="drained",
        prior_receipt_sha256=prior_receipt_sha256,
        terminal_cancel_count=terminal_cancel_count,
    )
    async with session_factory() as session, session.begin():
        if operation == "begin":
            changed = await set_writer_drain_receipt(
                session,
                lease_id=lease.lease_id,
                state="drained",
                receipt_sha256=receipt.receipt_sha256,
                operation=operation,
                prior_receipt_sha256=None,
            )
        else:
            _require(prior_receipt_sha256 is not None, "INVALID_COMMAND")
            assert prior_receipt_sha256 is not None
            changed = await refresh_writer_drain_receipt(
                session,
                lease_id=lease.lease_id,
                receipt_sha256=receipt.receipt_sha256,
                operation="attest",
                prior_receipt_sha256=prior_receipt_sha256,
            )
    _require(changed, "WRITER_DRAIN_RECEIPT_CONFLICT")
    return receipt


async def _restore_instigations(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    lease: WriterDrainLease,
) -> None:
    instigations = await _verify_snapshot(session_factory=session_factory, lease=lease)
    observed = {
        (item.kind, item.selector_id): item
        for item in await _list_instigations(http_client=http_client, graphql_url=graphql_url)
    }
    _require(
        set(observed) == {(item.kind, item.selector_id) for item in instigations},
        "DAGSTER_INSTIGATION_DRIFT",
    )
    for instigation in instigations:
        state = observed[(instigation.kind, instigation.selector_id)]
        if not instigation.was_running:
            _require(not state.was_running, "DAGSTER_INSTIGATION_DRIFT")
            continue
        if state.was_running:
            async with session_factory() as session, session.begin():
                await mark_writer_drain_instigation_restored(
                    session,
                    lease_id=lease.lease_id,
                    kind=instigation.kind,
                    selector_id=instigation.selector_id,
                    result="already_running",
                )
            continue
        await _mutate_instigation(
            http_client=http_client,
            graphql_url=graphql_url,
            instigation=instigation,
            start=True,
        )
        async with session_factory() as session, session.begin():
            await mark_writer_drain_instigation_restored(
                session,
                lease_id=lease.lease_id,
                kind=instigation.kind,
                selector_id=instigation.selector_id,
                result="restored",
            )


async def _assert_restored(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    lease: WriterDrainLease,
) -> int:
    instigations = await _verify_snapshot(session_factory=session_factory, lease=lease)
    observed = {
        (item.kind, item.selector_id): item
        for item in await _list_instigations(http_client=http_client, graphql_url=graphql_url)
    }
    _require(
        set(observed) == {(item.kind, item.selector_id) for item in instigations},
        "DAGSTER_INSTIGATION_DRIFT",
    )
    _require(
        all(
            observed[(item.kind, item.selector_id)].was_running == item.was_running
            for item in instigations
        ),
        "DAGSTER_RESTORE_MISMATCH",
    )
    async with session_factory() as session:
        runs = await get_writer_drain_runs(session, lease_id=lease.lease_id)
    return sum(item.cancel_dispatched_at is not None for item in runs)


async def _execute_begin(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    settings: ApiSettings,
    request: WriterDrainRequest,
) -> WriterDrainReceipt:
    snapshot = await _list_instigations(http_client=http_client, graphql_url=graphql_url)
    lease = await _begin_lease(
        session_factory=session_factory,
        request=request,
        snapshot=snapshot,
    )
    _require(lease.state in {"draining", "drained"}, "WRITER_DRAIN_OPERATION_CONFLICT")
    if lease.state == "drained":
        async with session_factory() as session:
            runs = await get_writer_drain_runs(session, lease_id=lease.lease_id)
        receipt = _receipt(
            operation="begin",
            lease=lease,
            state="drained",
            prior_receipt_sha256=None,
            terminal_cancel_count=sum(item.cancel_dispatched_at is not None for item in runs),
        )
        if lease.receipt_operation == "begin":
            _require(
                receipt.receipt_sha256 == lease.receipt_sha256,
                "WRITER_DRAIN_RECEIPT_MISMATCH",
            )
            return receipt
        _require(lease.receipt_sha256 is not None, "WRITER_DRAIN_RECEIPT_MISMATCH")
        assert lease.receipt_sha256 is not None
        async with session_factory() as session, session.begin():
            changed = await reset_writer_drain_begin_receipt(
                session,
                lease_id=lease.lease_id,
                expected_receipt_sha256=lease.receipt_sha256,
                receipt_sha256=receipt.receipt_sha256,
            )
        _require(changed, "WRITER_DRAIN_RECEIPT_CONFLICT")
        return receipt
    try:
        await _pause_instigations(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=graphql_url,
            lease=lease,
        )
        await _drain_runs(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=graphql_url,
            settings=settings,
            lease=lease,
        )
        terminal_cancel_count = await _assert_drained(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=graphql_url,
            lease=lease,
        )
    except WriterDrainCommandError as exc:
        await _record_failure(
            session_factory=session_factory,
            lease_id=lease.lease_id,
            code=exc.code,
        )
        raise
    return await _finalize_drained(
        session_factory=session_factory,
        lease=lease,
        operation="begin",
        prior_receipt_sha256=None,
        terminal_cancel_count=terminal_cancel_count,
    )


async def _execute_attest(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    request: WriterDrainRequest,
) -> WriterDrainReceipt:
    lease = await _load_lease_for_request(session_factory=session_factory, request=request)
    _require(lease.state == "drained", "WRITER_DRAIN_OPERATION_CONFLICT")
    _require(request.prior_receipt_sha256 is not None, "INVALID_COMMAND")
    async with session_factory() as session:
        runs = await get_writer_drain_runs(session, lease_id=lease.lease_id)
    if (
        lease.receipt_operation == "attest"
        and lease.receipt_prior_sha256 == request.prior_receipt_sha256
    ):
        receipt = _receipt(
            operation="attest",
            lease=lease,
            state="drained",
            prior_receipt_sha256=request.prior_receipt_sha256,
            terminal_cancel_count=sum(item.cancel_dispatched_at is not None for item in runs),
        )
        _require(receipt.receipt_sha256 == lease.receipt_sha256, "WRITER_DRAIN_RECEIPT_MISMATCH")
        return receipt
    _require(lease.receipt_sha256 == request.prior_receipt_sha256, "WRITER_DRAIN_RECEIPT_MISMATCH")
    terminal_cancel_count = await _assert_drained(
        session_factory=session_factory,
        http_client=http_client,
        graphql_url=graphql_url,
        lease=lease,
    )
    return await _finalize_drained(
        session_factory=session_factory,
        lease=lease,
        operation="attest",
        prior_receipt_sha256=request.prior_receipt_sha256,
        terminal_cancel_count=terminal_cancel_count,
    )


async def _execute_restore(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    http_client: httpx.AsyncClient,
    graphql_url: str,
    request: WriterDrainRequest,
) -> WriterDrainReceipt:
    lease = await _load_lease_for_request(session_factory=session_factory, request=request)
    _require(request.prior_receipt_sha256 is not None, "INVALID_COMMAND")
    async with session_factory() as session:
        runs = await get_writer_drain_runs(session, lease_id=lease.lease_id)
    if lease.state == "restored":
        _require(
            lease.receipt_operation == "restore"
            and lease.receipt_prior_sha256 == request.prior_receipt_sha256,
            "WRITER_DRAIN_RECEIPT_MISMATCH",
        )
        receipt = _receipt(
            operation="restore",
            lease=lease,
            state="restored",
            prior_receipt_sha256=request.prior_receipt_sha256,
            terminal_cancel_count=sum(item.cancel_dispatched_at is not None for item in runs),
        )
        _require(receipt.receipt_sha256 == lease.receipt_sha256, "WRITER_DRAIN_RECEIPT_MISMATCH")
        return receipt
    _require(lease.state in {"drained", "restoring"}, "WRITER_DRAIN_OPERATION_CONFLICT")
    _require(lease.receipt_sha256 == request.prior_receipt_sha256, "WRITER_DRAIN_RECEIPT_MISMATCH")
    if lease.state == "drained":
        async with session_factory() as session, session.begin():
            changed = await set_writer_drain_state(
                session,
                lease_id=lease.lease_id,
                expected_state="drained",
                state="restoring",
            )
        _require(changed, "WRITER_DRAIN_RECEIPT_CONFLICT")
        lease = await _load_lease_for_request(session_factory=session_factory, request=request)
    try:
        await _restore_instigations(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=graphql_url,
            lease=lease,
        )
        terminal_cancel_count = await _assert_restored(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=graphql_url,
            lease=lease,
        )
    except WriterDrainCommandError as exc:
        await _record_failure(
            session_factory=session_factory,
            lease_id=lease.lease_id,
            code=exc.code,
        )
        raise
    receipt = _receipt(
        operation="restore",
        lease=lease,
        state="restored",
        prior_receipt_sha256=request.prior_receipt_sha256,
        terminal_cancel_count=terminal_cancel_count,
    )
    async with session_factory() as session, session.begin():
        changed = await set_writer_drain_receipt(
            session,
            lease_id=lease.lease_id,
            state="restored",
            receipt_sha256=receipt.receipt_sha256,
            operation="restore",
            prior_receipt_sha256=request.prior_receipt_sha256,
        )
    _require(changed, "WRITER_DRAIN_RECEIPT_CONFLICT")
    return receipt


async def execute_writer_drain(
    *,
    request: WriterDrainRequest,
    session_factory: async_sessionmaker[AsyncSession],
    settings: ApiSettings,
    http_client: httpx.AsyncClient,
) -> WriterDrainReceipt:
    """입력 검증을 통과한 private command 한 건을 실행한다."""

    try:
        urls = dagster_graphql.dagster_urls(settings)
    except dagster_graphql.DagsterUrlConfigurationError as exc:
        raise WriterDrainCommandError("DAGSTER_CONFIGURATION_INVALID") from exc
    if request.operation == "begin":
        return await _execute_begin(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=urls.graphql_url,
            settings=settings,
            request=request,
        )
    if request.operation == "attest":
        return await _execute_attest(
            session_factory=session_factory,
            http_client=http_client,
            graphql_url=urls.graphql_url,
            request=request,
        )
    return await _execute_restore(
        session_factory=session_factory,
        http_client=http_client,
        graphql_url=urls.graphql_url,
        request=request,
    )

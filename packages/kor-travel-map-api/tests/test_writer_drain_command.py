"""Private writer-drain command의 stdin/stdout boundary 회귀."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from kortravelmap.infra.writer_drain_repo import WriterDrainInstigation, WriterDrainLease

from kortravelmap.api import writer_drain_command as command
from kortravelmap.api import writer_drain_service as service
from kortravelmap.api.dagster_graphql import DagsterUrls

_DAGSTER = DagsterUrls(
    dagster_url="http://dagster",
    graphql_url="http://dagster/graphql",
    repository_name="__repository__",
    repository_location_name="kortravelmap.dagster.definitions",
)


def test_parse_request_requires_exact_private_schema() -> None:
    owner_id = "11111111-1111-4111-8111-111111111111"
    request = command.parse_request(
        json.dumps(
            {
                "contract_version": service.CONTRACT_VERSION,
                "operation": "begin",
                "owner_kind": "diagnostic",
                "owner_id": owner_id,
            }
        ).encode()
    )
    assert request.operation == "begin"
    assert request.lease_id is None
    assert request.prior_receipt_sha256 is None

    with pytest.raises(service.WriterDrainCommandError, match="INVALID_COMMAND"):
        command.parse_request(
            json.dumps(
                {
                    "contract_version": service.CONTRACT_VERSION,
                    "operation": "begin",
                    "owner_kind": "diagnostic",
                    "owner_id": owner_id,
                    "lease_id": owner_id,
                }
            ).encode()
        )


def test_receipt_matches_manager_schema_and_canonical_digest() -> None:
    owner_id = UUID("11111111-1111-4111-8111-111111111111")
    lease_id = UUID("22222222-2222-4222-8222-222222222222")
    lease = WriterDrainLease(
        lease_id=lease_id,
        owner_kind="cutover",
        owner_id=owner_id,
        state="drained",
        snapshot_sha256="a" * 64,
        receipt_sha256=None,
        receipt_operation=None,
        receipt_prior_sha256=None,
        failure_code=None,
        created_at=datetime(2026, 8, 4, tzinfo=UTC),
        updated_at=datetime(2026, 8, 4, tzinfo=UTC),
        restored_at=None,
    )
    receipt = service._receipt(
        operation="begin",
        lease=lease,
        state="drained",
        prior_receipt_sha256=None,
        terminal_cancel_count=2,
    )
    payload = json.loads(receipt.json_bytes())
    assert set(payload) == {
        "contract_version",
        "operation",
        "owner_kind",
        "owner_id",
        "lease_id",
        "state",
        "prior_receipt_sha256",
        "snapshot_sha256",
        "run_count",
        "terminal_cancel_count",
        "receipt_sha256",
    }
    assert payload["run_count"] == 0
    assert payload["terminal_cancel_count"] == 2
    digest_input = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    assert (
        payload["receipt_sha256"]
        == hashlib.sha256(
            json.dumps(
                digest_input,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    )


def test_command_failure_does_not_echo_stdin(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    secret_like_input = b'{"unexpected":"do-not-echo"}'
    monkeypatch.setattr(command.sys, "argv", ["writer-drain"])

    async def _fail(_raw: bytes) -> bytes:
        raise service.WriterDrainCommandError("INVALID_COMMAND")

    class _Input:
        def read(self, _size: int) -> bytes:
            return secret_like_input

    class _Stdin:
        buffer = _Input()

    monkeypatch.setattr(command.sys, "stdin", _Stdin())
    monkeypatch.setattr(command, "_run", _fail)

    assert command.main() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "writer-drain: INVALID_COMMAND\n"
    assert "do-not-echo" not in captured.err


@pytest.mark.asyncio
async def test_drain_cancels_a_run_observed_after_grace_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """late Dagster enqueue도 같은 lease의 CAS cancel path로 흡수한다."""

    lease = SimpleNamespace(lease_id=UUID("22222222-2222-4222-8222-222222222222"))
    observations = iter(
        (
            (("run-at-grace", "STARTED"),),
            (("late-run", "QUEUED"),),
            (),
        )
    )
    cancelled: list[tuple[tuple[str, str], ...]] = []

    async def observe(**_kwargs: object) -> tuple[tuple[str, str], ...]:
        return next(observations)

    async def cancel(*, runs: tuple[tuple[str, str], ...], **_kwargs: object) -> None:
        cancelled.append(runs)

    async def no_sleep(_seconds: float) -> None:
        return None

    monotonic_values = iter((0.0, 20.0, 20.0, 21.0))
    monkeypatch.setattr(service, "_observe_nonterminal_runs", observe)
    monkeypatch.setattr(service, "_cancel_remaining_runs_once", cancel)
    monkeypatch.setattr(service.asyncio, "sleep", no_sleep)
    monkeypatch.setattr(service, "monotonic", lambda: next(monotonic_values))

    await service._drain_runs(  # noqa: SLF001 - command boundary state machine.
        session_factory=SimpleNamespace(),
        http_client=SimpleNamespace(),
        dagster=_DAGSTER,
        settings=SimpleNamespace(
            dagster_termination_timeout_seconds=30,
            dagster_termination_poll_interval_seconds=0.1,
        ),
        lease=lease,
    )

    assert cancelled == [
        (("run-at-grace", "STARTED"),),
        (("late-run", "QUEUED"),),
    ]


@pytest.mark.asyncio
async def test_writer_drain_collects_schedule_and_sensor_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _graphql(**kwargs: object) -> dict[str, object]:
        # 공유 webserver에서 다른 프로젝트의 schedule/sensor를 멈추지 않는다.
        assert kwargs["variables"] == {"repositorySelector": _DAGSTER.repository_selector()}
        return {
            "data": {
                "repositoryOrError": {
                    "__typename": "Repository",
                    "name": "repo",
                    "location": {"name": "location"},
                    "schedules": [
                        {
                            "name": "schedule-internal-name",
                            "scheduleState": {
                                "id": "schedule-origin::state",
                                "selectorId": "schedule-selector",
                                "status": "RUNNING",
                            },
                        }
                    ],
                    "sensors": [
                        {
                            "name": "sensor-internal-name",
                            "sensorState": {
                                "id": "sensor-origin::state",
                                "selectorId": "sensor-selector",
                                "status": "STOPPED",
                            },
                        }
                    ],
                }
            }
        }

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    snapshot = await service._list_instigations(  # noqa: SLF001 - private command unit.
        http_client=None,  # type: ignore[arg-type]
        dagster=_DAGSTER,
    )

    assert [(item.kind, item.was_running) for item in snapshot] == [
        ("schedule", True),
        ("sensor", False),
    ]
    assert snapshot[0].origin_id == "schedule-origin"
    assert snapshot[0].pause_result == "pending"
    assert snapshot[1].pause_result == "not_required"


@pytest.mark.asyncio
async def test_writer_drain_observes_only_this_code_location_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """공유 webserver에서 다른 프로젝트의 진행 중 run을 끊지 않도록 run 조회를 좁힌다."""

    seen: list[object] = []

    async def _graphql(**kwargs: object) -> dict[str, object]:
        seen.append(kwargs["variables"])
        return {
            "data": {
                "repositoryOrError": {"__typename": "Repository"},
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [
                        {"runId": "run-1", "status": "STARTED"},
                        {"runId": "run-2", "status": "STARTING"},
                    ],
                },
            }
        }

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    runs = await service._list_nonterminal_runs(  # noqa: SLF001 - private command unit.
        http_client=None,  # type: ignore[arg-type]
        dagster=_DAGSTER,
    )

    assert runs == (("run-1", "STARTED"), ("run-2", "STARTING"))
    assert seen == [
        {
            "limit": 1_000,
            "repositorySelector": {
                "repositoryName": "__repository__",
                "repositoryLocationName": "kortravelmap.dagster.definitions",
            },
            "runsFilter": {
                # STARTING은 launcher가 프로세스를 띄우는 중인 run이다 — 끝나지 않았다.
                "statuses": [
                    "QUEUED",
                    "NOT_STARTED",
                    "STARTING",
                    "STARTED",
                    "MANAGED",
                    "CANCELING",
                ],
                "tags": [
                    {
                        "key": ".dagster/repository",
                        "value": "__repository__@kortravelmap.dagster.definitions",
                    }
                ],
            },
        }
    ]


@pytest.mark.asyncio
async def test_writer_drain_fails_loudly_when_the_code_location_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """location 이름이 틀리면 tag filter는 0건이다 — 빈 drain으로 통과하지 않는다."""

    async def _graphql(**_kwargs: object) -> dict[str, object]:
        return {
            "data": {
                "repositoryOrError": {
                    "__typename": "RepositoryNotFoundError",
                    "message": "Could not find Repository nope.__repository__",
                },
                "runsOrError": {"__typename": "Runs", "results": []},
            }
        }

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    with pytest.raises(service.WriterDrainCommandError) as excinfo:
        await service._list_nonterminal_runs(  # noqa: SLF001 - private command unit.
            http_client=None,  # type: ignore[arg-type]
            dagster=_DAGSTER,
        )
    assert str(excinfo.value) == "DAGSTER_PROTOCOL"


def _instigation(kind: str) -> WriterDrainInstigation:
    # Dagster 1.13의 InstigationState.id는 ``<origin id>::<selector id>``(CompoundID)다.
    return WriterDrainInstigation(
        lease_id=UUID("00000000-0000-0000-0000-000000000001"),
        kind=kind,  # type: ignore[arg-type]
        selector_id=f"{kind}-selector",
        state_id=f"{kind}-origin::{kind}-selector",
        origin_id=f"{kind}-origin",
        instigation_name=f"{kind}-name",
        repository_name="__repository__",
        repository_location_name="kortravelmap.dagster.definitions",
        was_running=True,
        pause_result="pending",
        paused_at=None,
        restore_result="not_requested",
        restored_at=None,
    )


# Dagster 1.13 webserver가 실제로 내는 성공 응답 모양(n150 introspection, 2026-11-25).
_MUTATION_RESPONSES: dict[tuple[str, bool], tuple[str, dict[str, object]]] = {
    ("schedule", False): (
        "stopRunningSchedule",
        {"__typename": "ScheduleStateResult", "scheduleState": {"status": "STOPPED"}},
    ),
    ("schedule", True): (
        "startSchedule",
        {"__typename": "ScheduleStateResult", "scheduleState": {"status": "RUNNING"}},
    ),
    ("sensor", False): (
        "stopSensor",
        {"__typename": "StopSensorMutationResult", "instigationState": {"status": "STOPPED"}},
    ),
    ("sensor", True): (
        "startSensor",
        {"__typename": "Sensor", "sensorState": {"status": "RUNNING"}},
    ),
}


@pytest.mark.asyncio
@pytest.mark.parametrize(("kind", "start"), list(_MUTATION_RESPONSES))
async def test_instigation_mutation_accepts_the_dagster_1_13_success_shape(
    monkeypatch: pytest.MonkeyPatch, kind: str, start: bool
) -> None:
    field, response = _MUTATION_RESPONSES[(kind, start)]
    seen: list[dict[str, object]] = []

    async def _graphql(**kwargs: object) -> dict[str, object]:
        seen.append(kwargs)
        return {"data": {field: response}}

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    await service._mutate_instigation(  # noqa: SLF001 - private command unit.
        http_client=None,  # type: ignore[arg-type]
        dagster=_DAGSTER,
        instigation=_instigation(kind),
        start=start,
    )

    assert len(seen) == 1
    query = str(seen[0]["query"])
    assert f"{field}(" in query
    if start:
        name_key = "scheduleName" if kind == "schedule" else "sensorName"
        assert seen[0]["variables"] == {
            "selector": {
                "repositoryName": "__repository__",
                "repositoryLocationName": "kortravelmap.dagster.definitions",
                name_key: f"{kind}-name",
            }
        }
    else:
        assert seen[0]["variables"] == {
            "id": f"{kind}-origin::{kind}-selector",
            "originId": f"{kind}-origin",
            "selectorId": f"{kind}-selector",
        }
    if kind == "sensor" and not start:
        # 1.13 stopSensor 인자는 jobOriginId·jobSelectorId다.
        assert "jobOriginId: $originId" in query
        assert "jobSelectorId: $selectorId" in query
        assert "sensorOriginId" not in query


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        # 옛 문서가 기대하던 모양 — 1.13에는 SensorState 타입이 없다.
        {"__typename": "SensorState", "status": "STOPPED"},
        {"__typename": "PythonError", "message": "boom"},
        {"__typename": "UnauthorizedError", "message": "no"},
    ],
)
async def test_stop_sensor_rejects_anything_but_stop_sensor_mutation_result(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, object]
) -> None:
    async def _graphql(**_kwargs: object) -> dict[str, object]:
        return {"data": {"stopSensor": response}}

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    with pytest.raises(service.WriterDrainCommandError) as excinfo:
        await service._mutate_instigation(  # noqa: SLF001 - private command unit.
            http_client=None,  # type: ignore[arg-type]
            dagster=_DAGSTER,
            instigation=_instigation("sensor"),
            start=False,
        )
    assert str(excinfo.value) == "DAGSTER_MUTATION_FAILED"


@pytest.mark.asyncio
async def test_stop_sensor_requires_the_returned_state_to_be_stopped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _graphql(**_kwargs: object) -> dict[str, object]:
        return {
            "data": {
                "stopSensor": {
                    "__typename": "StopSensorMutationResult",
                    "instigationState": {"status": "RUNNING"},
                }
            }
        }

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    with pytest.raises(service.WriterDrainCommandError) as excinfo:
        await service._mutate_instigation(  # noqa: SLF001 - private command unit.
            http_client=None,  # type: ignore[arg-type]
            dagster=_DAGSTER,
            instigation=_instigation("sensor"),
            start=False,
        )
    assert str(excinfo.value) == "DAGSTER_MUTATION_FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"__typename": "SensorState", "status": "RUNNING"},
        {"__typename": "SensorNotFoundError", "message": "missing"},
        {"__typename": "Sensor", "sensorState": {"status": "STOPPED"}},
    ],
)
async def test_start_sensor_rejects_anything_but_a_running_sensor(
    monkeypatch: pytest.MonkeyPatch, response: dict[str, object]
) -> None:
    async def _graphql(**_kwargs: object) -> dict[str, object]:
        return {"data": {"startSensor": response}}

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    with pytest.raises(service.WriterDrainCommandError) as excinfo:
        await service._mutate_instigation(  # noqa: SLF001 - private command unit.
            http_client=None,  # type: ignore[arg-type]
            dagster=_DAGSTER,
            instigation=_instigation("sensor"),
            start=True,
        )
    assert str(excinfo.value) == "DAGSTER_MUTATION_FAILED"


@pytest.mark.asyncio
async def test_stop_sensor_without_instigation_state_is_a_protocol_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 스키마상 instigationState는 nullable이다(1.13 구현은 늘 채우지만).
    async def _graphql(**_kwargs: object) -> dict[str, object]:
        return {
            "data": {
                "stopSensor": {"__typename": "StopSensorMutationResult", "instigationState": None}
            }
        }

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    with pytest.raises(service.WriterDrainCommandError) as excinfo:
        await service._mutate_instigation(  # noqa: SLF001 - private command unit.
            http_client=None,  # type: ignore[arg-type]
            dagster=_DAGSTER,
            instigation=_instigation("sensor"),
            start=False,
        )
    assert str(excinfo.value) == "DAGSTER_PROTOCOL"

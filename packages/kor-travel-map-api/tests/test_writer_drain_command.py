"""Private writer-drain command의 stdin/stdout boundary 회귀."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from kortravelmap.infra.writer_drain_repo import WriterDrainLease

from kortravelmap.api import writer_drain_command as command
from kortravelmap.api import writer_drain_service as service


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
        graphql_url="http://dagster/graphql",
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
    async def _graphql(**_kwargs: object) -> dict[str, object]:
        return {
            "data": {
                "repositoriesOrError": {
                    "__typename": "RepositoryConnection",
                    "nodes": [
                        {
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
                    ],
                }
            }
        }

    monkeypatch.setattr(service.dagster_graphql, "post_graphql", _graphql)
    snapshot = await service._list_instigations(  # noqa: SLF001 - private command unit.
        http_client=None,  # type: ignore[arg-type]
        graphql_url="http://dagster/graphql",
    )

    assert [(item.kind, item.was_running) for item in snapshot] == [
        ("schedule", True),
        ("sensor", False),
    ]
    assert snapshot[0].origin_id == "schedule-origin"
    assert snapshot[0].pause_result == "pending"
    assert snapshot[1].pause_result == "not_required"

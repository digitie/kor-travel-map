"""Dagster run 실패 이벤트 → Map DB에 남길 실패 원인 (감사 2026-11-23 §1.2·§4 #15)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dagster import DagsterInstance, Failure, job, op
from dagster._core.storage.dagster_run import DagsterRunStatus

from kortravelmap.dagster.feature_operation_sensors import _terminal_error
from kortravelmap.dagster.run_failure_detail import (
    describe_run_failure,
    failure_detail_text,
    run_failure_detail,
)


def _error(cls_name: str, message: str, cause: Any = None) -> SimpleNamespace:
    return SimpleNamespace(cls_name=cls_name, message=message, cause=cause)


def test_step_failure_is_read_from_the_run_failure_event() -> None:
    inner = _error("LockNotAvailableError", "canceling statement due to lock timeout")
    step = SimpleNamespace(
        step_key="feature_place_khoa_beaches",
        event_specific_data=SimpleNamespace(
            error=_error(
                "ProviderDatasetRefreshFailure",
                "provider refresh failed\nTraceback (most recent call last): ...",
                cause=inner,
            )
        ),
    )
    event = SimpleNamespace(
        message="Execution of run failed.",
        event_specific_data=SimpleNamespace(
            error=None,
            failure_reason=SimpleNamespace(value="STEP_FAILURE"),
            first_step_failure_event=step,
        ),
    )

    detail = run_failure_detail(event)

    assert detail == {
        "failure_reason": "STEP_FAILURE",
        "failed_step": "feature_place_khoa_beaches",
        "error_type": "ProviderDatasetRefreshFailure",
        "error": "provider refresh failed",
        "cause": "LockNotAvailableError: canceling statement due to lock timeout",
    }
    assert describe_run_failure("run-1", detail) == (
        "Dagster run run-1 실패 — step feature_place_khoa_beaches: "
        "ProviderDatasetRefreshFailure: provider refresh failed ← 원인 "
        "LockNotAvailableError: canceling statement due to lock timeout"
    )


def test_launch_failure_without_steps_uses_the_run_error() -> None:
    event = SimpleNamespace(
        message="Run failed to launch",
        event_specific_data=SimpleNamespace(
            error=_error("OSError", "[Errno 24] Too many open files"),
            failure_reason=SimpleNamespace(value="START_FAILURE"),
            first_step_failure_event=None,
        ),
    )
    detail = run_failure_detail(event)
    assert detail["failure_reason"] == "START_FAILURE"
    assert detail["error"] == "[Errno 24] Too many open files"
    assert "failed_step" not in detail
    assert failure_detail_text(detail) == "OSError: [Errno 24] Too many open files"


def test_secrets_never_reach_the_detail() -> None:
    event = SimpleNamespace(
        message="",
        event_specific_data=SimpleNamespace(
            error=_error("HTTPStatusError", "503 for url https://x/y?serviceKey=SECRET123"),
            failure_reason=None,
            first_step_failure_event=None,
        ),
    )
    detail = run_failure_detail(event)
    assert "SECRET123" not in detail["error"]


def test_garbage_input_never_raises() -> None:
    assert run_failure_detail(None) == {}
    assert run_failure_detail(object()) == {}
    assert failure_detail_text({}) == ""


def test_real_run_failure_event_carries_the_step_failure() -> None:
    @op
    def explode() -> None:
        raise Failure(description="upstream 503 for 국가유산 행사")

    @job
    def failing_job() -> None:
        explode()

    with DagsterInstance.ephemeral() as instance:
        result = failing_job.execute_in_process(instance=instance, raise_on_error=False)
        detail = run_failure_detail(result.get_run_failure_event())

    assert detail["failed_step"] == "explode"
    assert detail["error_type"] == "Failure"
    assert detail["error"] == "upstream 503 for 국가유산 행사"


def test_operation_root_terminal_error_carries_the_cause() -> None:
    run = SimpleNamespace(run_id="run-9", status=DagsterRunStatus.FAILURE)
    bare = _terminal_error(run)  # type: ignore[arg-type]
    assert bare == {"kind": "dagster_run_terminal", "run_id": "run-9", "status": "FAILURE"}

    enriched = _terminal_error(
        run,  # type: ignore[arg-type]
        {"failed_step": "s", "error_type": "E", "error": "boom", "ignored": "x"},
    )
    assert enriched == {
        "kind": "dagster_run_terminal",
        "run_id": "run-9",
        "status": "FAILURE",
        "failed_step": "s",
        "error_type": "E",
        "error": "boom",
    }
    cancelled = SimpleNamespace(run_id="run-9", status=DagsterRunStatus.CANCELED)
    assert "error" not in (_terminal_error(cancelled, {"error": "x"}) or {})  # type: ignore[arg-type]

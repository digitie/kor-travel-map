"""upstream_retry (T-VN-H45) — 분류·backoff·예산·원예외 보존·cancellation 통과."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kortravelmap.dagster.upstream_retry import (
    DEFAULT_UPSTREAM_ATTEMPTS,
    DEFAULT_UPSTREAM_BASE_DELAY_SECONDS,
    DEFAULT_UPSTREAM_MAX_DELAY_SECONDS,
    DEFAULT_UPSTREAM_RUN_RETRY_BUDGET,
    PROVIDER_CLIENT_INNER_RETRIES,
    RetryBudget,
    default_upstream_retryable,
    retry_upstream,
    retry_upstream_async,
)


class _RetryableError(Exception):
    retryable = True


class _NonRetryableError(Exception):
    retryable = False


class _UnclassifiedError(Exception):
    """retryable 속성 부재 — 미분류는 즉시 전파."""


class _QuotaError(Exception):
    """lib이 retryable=True로 분류하는 쿼터 소진 — 여기서는 재시도 금지."""

    retryable = True
    failure_kind = "quota"


class _RateLimitError(Exception):
    retryable = True
    failure_kind = "rate_limit"


class _Flaky:
    """앞 ``failures``회는 실패, 이후 성공하는 호출체."""

    def __init__(self, failures: int, exc: Exception) -> None:
        self.failures = failures
        self.exc = exc
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc
        return "ok"


def test_layer_reconciliation_constants_are_pinned() -> None:
    """리뷰 H(레이어 곱셈) 정산값 고정 — 외부 2 × 내부(1+1) = 경계당 HTTP 4 시도.

    이 상수를 올리는 변경은 run 최악 wall(6h 한도)·쿼터 소모 산식을 다시
    계산해 문서에 남겨야 한다(모듈 docstring).
    """

    assert DEFAULT_UPSTREAM_ATTEMPTS == 2
    assert PROVIDER_CLIENT_INNER_RETRIES == 1
    assert DEFAULT_UPSTREAM_BASE_DELAY_SECONDS == 2.0
    assert DEFAULT_UPSTREAM_MAX_DELAY_SECONDS == 20.0
    assert DEFAULT_UPSTREAM_RUN_RETRY_BUDGET == 8


def test_default_predicate_follows_retryable_attribute() -> None:
    assert default_upstream_retryable(_RetryableError()) is True
    assert default_upstream_retryable(_NonRetryableError()) is False
    assert default_upstream_retryable(_UnclassifiedError()) is False


def test_default_predicate_refuses_quota_and_rate_limit() -> None:
    """쿼터성 예외는 lib이 retryable=True여도 재시도 금지(일일 한도 보호)."""

    assert default_upstream_retryable(_QuotaError()) is False
    assert default_upstream_retryable(_RateLimitError()) is False


def test_sync_recovers_after_transient_failures_with_exponential_backoff() -> None:
    call = _Flaky(2, _RetryableError())
    delays: list[float] = []

    result = retry_upstream(
        call,
        label="t",
        attempts=4,
        base_delay=2.0,
        max_delay=20.0,
        sleep=delays.append,
    )

    assert result == "ok"
    assert call.calls == 3
    assert delays == [2.0, 4.0]


def test_sync_default_attempts_allow_single_retry() -> None:
    """기본값(attempts 2)은 정확히 1회 재시도 — 그 이상은 원예외 전파."""

    recovers = _Flaky(1, _RetryableError())
    delays: list[float] = []
    assert retry_upstream(recovers, label="t", sleep=delays.append) == "ok"
    assert recovers.calls == 2
    assert delays == [2.0]

    exhausts = _Flaky(2, _RetryableError())
    with pytest.raises(_RetryableError):
        retry_upstream(exhausts, label="t", sleep=delays.append)
    assert exhausts.calls == 2


def test_sync_nonretryable_raises_immediately_without_sleep() -> None:
    exc = _NonRetryableError()
    call = _Flaky(5, exc)
    delays: list[float] = []

    with pytest.raises(_NonRetryableError) as info:
        retry_upstream(call, label="t", sleep=delays.append)

    assert info.value is exc  # 원 예외 원형 보존
    assert call.calls == 1
    assert delays == []


def test_sync_quota_error_never_burns_extra_calls() -> None:
    """쿼터 소진 상태에서 재시도는 쿼터 구멍만 키운다 — 1회 호출 후 즉시 전파."""

    exc = _QuotaError()
    call = _Flaky(5, exc)
    delays: list[float] = []

    with pytest.raises(_QuotaError):
        retry_upstream(call, label="t", attempts=4, sleep=delays.append)

    assert call.calls == 1
    assert delays == []


def test_sync_exhausted_reraises_original_exception() -> None:
    exc = _RetryableError()
    call = _Flaky(99, exc)
    delays: list[float] = []

    with pytest.raises(_RetryableError) as info:
        retry_upstream(call, label="t", attempts=3, sleep=delays.append)

    assert info.value is exc
    assert call.calls == 3
    assert len(delays) == 2  # 마지막 시도 뒤에는 대기하지 않는다


def test_sync_backoff_is_capped_at_max_delay() -> None:
    call = _Flaky(5, _RetryableError())
    delays: list[float] = []

    retry_upstream(
        call,
        label="t",
        attempts=6,
        base_delay=2.0,
        max_delay=20.0,
        sleep=delays.append,
    )

    assert delays == [2.0, 4.0, 8.0, 16.0, 20.0]


def test_sync_rejects_nonpositive_attempts() -> None:
    with pytest.raises(ValueError, match="attempts"):
        retry_upstream(lambda: "ok", label="t", attempts=0)


def test_budget_is_shared_across_boundaries_and_aborts_early() -> None:
    """run 예산 소진 후에는 retryable 실패도 즉시 전파(early abort — 리뷰 H)."""

    budget = RetryBudget(limit=2)
    delays: list[float] = []
    messages: list[str] = []

    # 경계 1·2: 각각 재시도 1회 소모 → 예산 소진.
    for _ in range(2):
        call = _Flaky(1, _RetryableError())
        assert (
            retry_upstream(
                call,
                label="b",
                sleep=delays.append,
                budget=budget,
                on_retry=messages.append,
            )
            == "ok"
        )
    assert budget.used == 2

    # 경계 3: 분류상 retryable이지만 예산이 없다 — 재시도·sleep 없이 원예외.
    exhausted = _Flaky(1, _RetryableError())
    with pytest.raises(_RetryableError):
        retry_upstream(
            exhausted,
            label="b3",
            sleep=delays.append,
            budget=budget,
            on_retry=messages.append,
        )
    assert exhausted.calls == 1
    assert len(delays) == 2  # 경계 1·2의 backoff만
    assert any("budget exhausted" in message for message in messages)


def test_budget_not_consumed_by_nonretryable_failures() -> None:
    """분류 탈락 예외는 예산을 소모하지 않는다 — 예산은 재시도 실행에만 쓴다."""

    budget = RetryBudget(limit=1)
    call = _Flaky(1, _NonRetryableError())
    with pytest.raises(_NonRetryableError):
        retry_upstream(call, label="t", budget=budget, sleep=lambda _s: None)
    assert budget.used == 0


def test_on_retry_reports_label_attempt_and_exception() -> None:
    messages: list[str] = []
    call = _Flaky(1, _RetryableError("boom"))

    retry_upstream(
        call,
        label="kma grid 60,127",
        sleep=lambda _s: None,
        on_retry=messages.append,
    )

    assert len(messages) == 1
    assert "kma grid 60,127" in messages[0]
    assert "_RetryableError" in messages[0]
    assert "1/2" in messages[0]


def test_async_recovers_and_yields_backoff_to_loop() -> None:
    call = _Flaky(1, _RetryableError())
    delays: list[float] = []

    async def _sleep(seconds: float) -> None:
        delays.append(seconds)

    async def _run() -> str:
        return await retry_upstream_async(call, label="t", sleep=_sleep)

    assert asyncio.run(_run()) == "ok"
    assert call.calls == 2
    assert delays == [2.0]


def test_async_does_not_swallow_cancellation() -> None:
    """CancelledError는 BaseException — 재시도 분류에 진입하지 않고 즉시 전파.

    리뷰 1 M-6: 변이(except Exception → BaseException)를 죽이려면 호출 1회·
    sleep 무발생까지 함께 단언해야 한다.
    """

    calls = {"count": 0}
    delays: list[float] = []

    def _cancelled() -> Any:
        calls["count"] += 1
        raise asyncio.CancelledError()

    async def _sleep(seconds: float) -> None:
        delays.append(seconds)

    async def _run() -> None:
        await retry_upstream_async(
            _cancelled, label="t", is_retryable=lambda _exc: True, sleep=_sleep
        )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_run())

    assert calls["count"] == 1
    assert delays == []


def test_async_exhausted_reraises_original_exception() -> None:
    exc = _RetryableError()
    call = _Flaky(99, exc)
    delays: list[float] = []

    async def _sleep(seconds: float) -> None:
        delays.append(seconds)

    async def _run() -> None:
        await retry_upstream_async(call, label="t", attempts=2, sleep=_sleep)

    with pytest.raises(_RetryableError) as info:
        asyncio.run(_run())

    assert info.value is exc
    assert call.calls == 2
    assert delays == [2.0]


def test_async_budget_exhaustion_propagates_without_sleep() -> None:
    budget = RetryBudget(limit=0)
    exc = _RetryableError()
    call = _Flaky(1, exc)
    delays: list[float] = []

    async def _sleep(seconds: float) -> None:
        delays.append(seconds)

    async def _run() -> None:
        await retry_upstream_async(call, label="t", budget=budget, sleep=_sleep)

    with pytest.raises(_RetryableError) as info:
        asyncio.run(_run())

    assert info.value is exc
    assert call.calls == 1
    assert delays == []

"""Valkey 쓰기의 일시 실패(연결·timeout)는 교체 안에서 유한 재시도로 넘긴다 (ADR-114).

2026-11-07 n150: 디스크 flush 대기로 Valkey 응답이 2초 socket timeout을 넘겨
``weather_state_daily_summaries``가 step 재시도 세 번 모두 ``Valkey 세대 쓰기 실패: TimeoutError``로
죽었다. step 재시도는 원천을 처음부터 다시 받는다 — 같은 디스크 대기 속에서 같은 자리에서 다시 죽는다.
그래서 교체 쓰기(세대 묶음·meta·포인터 교체·잠금 해제) 하나하나를 그 자리에서 다시 한다.

- 세대 묶음·meta 쓰기는 같은 값을 다시 쓰는 것이라 반쯤 적용됐어도 안전하다.
- 포인터 교체는 기존 compare-and-set이 판정한다: 응답만 잃었다면 포인터가 이미 **이 세대**이고
  그것은 성공이다(이 세대 id는 이 적재만 만든다). 포인터가 그대로면 다시 교체하고, 다른 세대면 충돌이다.
- OOM(``noeviction``)·미설정은 기다려도 풀리지 않으므로 다시 하지 않는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import SecretStr
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from kortravelmap.infra import valkey_state
from kortravelmap.infra.valkey_state import (
    ShrinkGuard,
    StateItem,
    StateStoreOutOfMemory,
    StateStoreUnavailable,
    ValkeyStateStore,
    make_valkey_client,
    state_key,
)
from kortravelmap.settings import KorTravelMapSettings
from tests.integration._valkey import valkey_container

pytestmark = pytest.mark.integration

LENIENT = ShrinkGuard(min_ratio=0.01, baseline_min=1_000_000)
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def valkey_url() -> Iterator[str]:
    with valkey_container() as url:
        yield url


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """재시도 대기를 실제로 자지 않고 적는다."""
    recorded: list[float] = []

    async def _sleep(delay: float) -> None:
        recorded.append(delay)

    monkeypatch.setattr(valkey_state, "_retry_sleep", _sleep)
    return recorded


@pytest.fixture
async def store(valkey_url: str, sleeps: list[float]) -> AsyncIterator[ValkeyStateStore]:
    settings = KorTravelMapSettings.model_construct(
        valkey_url=SecretStr(valkey_url),
        valkey_connect_timeout_seconds=1.0,
        valkey_socket_timeout_seconds=2.0,
    )
    client = make_valkey_client(settings)
    await client.flushdb()
    await client.config_set("maxmemory", "64mb")
    active = ValkeyStateStore(client, build_ttl_seconds=120, retire_grace_seconds=60, write_batch=2)
    try:
        yield active
    finally:
        await client.aclose()


def _items(count: int) -> list[StateItem]:
    return [
        StateItem(id=f"r_{i:04d}", value=f'{{"n": {i}}}', coord=(127.0 + i * 0.001, 37.5))
        for i in range(count)
    ]


async def _swap(store: ValkeyStateStore, dataset: str, count: int) -> str:
    result = await store.swap(
        dataset,
        _items(count),
        guard=LENIENT,
        source_collected_at=NOW - timedelta(minutes=5),
        loaded_at=NOW,
    )
    return result.meta.generation


def _flaky_pipelines(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch, *, failures: int, apply_first: bool
) -> dict[str, int]:
    """pipeline ``execute``가 앞의 ``failures``번 timeout을 낸다. ``apply_first``면 적용한 뒤 응답만 잃는다."""
    state = {"left": failures, "calls": 0}
    original = store.client.pipeline

    def _pipeline(*args: Any, **kwargs: Any) -> Any:
        pipe = original(*args, **kwargs)
        execute = pipe.execute

        async def _execute(*eargs: Any, **ekwargs: Any) -> Any:
            state["calls"] += 1
            if state["left"] > 0:
                state["left"] -= 1
                if apply_first:
                    await execute(*eargs, **ekwargs)
                raise RedisTimeoutError("Timeout reading from 127.0.0.1:12704")
            return await execute(*eargs, **ekwargs)

        pipe.execute = _execute
        return pipe

    monkeypatch.setattr(store.client, "pipeline", _pipeline)
    return state


@pytest.mark.parametrize("apply_first", [False, True], ids=["not-applied", "applied-reply-lost"])
async def test_transient_generation_write_timeouts_are_retried(
    store: ValkeyStateStore,
    monkeypatch: pytest.MonkeyPatch,
    sleeps: list[float],
    apply_first: bool,
) -> None:
    previous = await _swap(store, "r.write", 3)
    state = _flaky_pipelines(store, monkeypatch, failures=2, apply_first=apply_first)
    generation = await _swap(store, "r.write", 5)
    meta = await store.current_meta("r.write")
    assert meta.generation == generation != previous
    assert (meta.count, meta.geo_count) == (5, 5)
    assert await store.get_values("r.write", generation, ["r_0004"]) == [b'{"n": 4}']
    assert state["left"] == 0
    assert len(sleeps) == 2
    assert sleeps == sorted(sleeps)  # 늘어나는 대기(지수 backoff)


async def test_lost_flip_reply_is_settled_by_the_pointer_cas(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """교체 스크립트는 돌았는데 응답을 잃었다 — 다시 물으면 포인터가 이 세대이므로 성공이다."""
    previous = await _swap(store, "r.flip", 3)
    original = store.client.eval
    lost = {"left": 1}

    async def _eval(script: str, *args: Any) -> Any:
        result = await original(script, *args)
        if script == valkey_state._FLIP_SCRIPT and lost["left"]:
            lost["left"] = 0
            raise RedisTimeoutError("Timeout reading from 127.0.0.1:12704")
        return result

    monkeypatch.setattr(store.client, "eval", _eval)
    result = await store.swap(
        "r.flip",
        _items(4),
        guard=LENIENT,
        source_collected_at=NOW,
        loaded_at=NOW,
    )
    assert result.previous_generation == previous
    meta = await store.current_meta("r.flip")
    assert meta.generation == result.meta.generation
    assert meta.count == 4
    # 교체가 한 번만 반영됐다 — 두 번이면 recent_counts에 4가 둘 쌓이고 previous가 자기 자신이 된다.
    assert await store.recent_counts("r.flip") == [4, 3]
    assert await store.client.get(state_key("r.flip", "previous")) == previous.encode()
    assert len(sleeps) == 1


async def test_flip_timeout_before_it_ran_is_retried(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    previous = await _swap(store, "r.flip2", 2)
    original = store.client.eval
    failures = {"left": 2}

    async def _eval(script: str, *args: Any) -> Any:
        if script == valkey_state._FLIP_SCRIPT and failures["left"]:
            failures["left"] -= 1
            raise RedisConnectionError("Error while reading from socket")
        return await original(script, *args)

    monkeypatch.setattr(store.client, "eval", _eval)
    generation = await _swap(store, "r.flip2", 3)
    assert generation != previous
    assert (await store.current_meta("r.flip2")).generation == generation
    assert await store.recent_counts("r.flip2") == [3, 2]
    assert len(sleeps) == 2


async def test_persistent_timeouts_fail_unavailable_after_a_bounded_number_of_tries(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    previous = await _swap(store, "r.down", 2)
    state = _flaky_pipelines(store, monkeypatch, failures=1_000, apply_first=False)
    with pytest.raises(StateStoreUnavailable) as excinfo:
        await _swap(store, "r.down", 3)
    assert excinfo.value.retryable is True  # 다음 step 재시도의 몫으로 남긴다
    assert state["calls"] == valkey_state.DEFAULT_WRITE_RETRIES + 1
    assert len(sleeps) == valkey_state.DEFAULT_WRITE_RETRIES
    assert max(sleeps) <= valkey_state.WRITE_RETRY_MAX_DELAY_SECONDS
    assert (await store.current_meta("r.down")).generation == previous


async def test_out_of_memory_is_not_retried(
    store: ValkeyStateStore, sleeps: list[float]
) -> None:
    first = await _swap(store, "r.oom", 2)
    await store.client.config_set("maxmemory", "1")
    try:
        with pytest.raises(StateStoreOutOfMemory):
            await _swap(store, "r.oom", 50)
    finally:
        await store.client.config_set("maxmemory", "64mb")
    assert sleeps == []
    assert (await store.current_meta("r.oom")).generation == first


async def test_lock_release_timeout_is_retried(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    """해제가 한 번 timeout나도 잠금이 TTL(run 상한+취소 유예)까지 남아 다음 step 재시도를 'locked'로
    건너뛰게 하지 않는다."""
    original = store.client.eval
    failures = {"left": 1}

    async def _eval(script: str, *args: Any) -> Any:
        if script == valkey_state._RELEASE_LOCK_SCRIPT and failures["left"]:
            failures["left"] -= 1
            raise RedisTimeoutError("Timeout reading from 127.0.0.1:12704")
        return await original(script, *args)

    monkeypatch.setattr(store.client, "eval", _eval)
    async with store.load_lock("r.lock", ttl_seconds=600) as acquired:
        assert acquired is True
    assert await store.client.exists(state_key("r.lock", "lock")) == 0
    assert len(sleeps) == 1

"""ADR-114 transport 상태 적재 job — 정의(STOPPED·tag)와 실패 분류(Valkey 없이)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime
from typing import Any, cast

import pytest
from dagster import DefaultScheduleStatus, Failure
from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateStoreNotConfigured,
    StateStoreUnavailable,
    StateSwapRefused,
    SwapResult,
    ValkeyStateStore,
)
from kortravelmap.providers.kor_travel_transport import (
    TransportExportEmpty,
    TransportExportNotCurrent,
)
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.transport_state import (
    TRANSPORT_STATE_SPECS,
    TransportStateJobSpec,
    load_transport_state,
    lock_ttl_seconds,
)


def test_every_dataset_has_a_stopped_schedule_and_no_operation_key() -> None:
    assert len(TRANSPORT_STATE_SPECS) == 5
    assert len({spec.dataset.name for spec in TRANSPORT_STATE_SPECS}) == 5
    for spec in TRANSPORT_STATE_SPECS:
        job = defs.resolve_job_def(spec.job_name)
        schedule = defs.resolve_schedule_def(spec.schedule_name)
        assert schedule.default_status == DefaultScheduleStatus.STOPPED, spec.schedule_name
        assert schedule.job_name == spec.job_name
        # feature operation이 아니다 — 큐·operation 추적이 이 run을 세지 않게 한다.
        assert "kor_travel_map.operation_key" not in job.tags
        assert job.tags["kor_travel_map.job_kind"] == "transport_state"
        assert int(job.tags["dagster/max_runtime"]) == spec.max_runtime_seconds


class _FakeStore:
    def __init__(self, *, locked: bool = False, swap_error: Exception | None = None) -> None:
        self.locked = locked
        self.swap_error = swap_error
        self.swapped: list[tuple[str, int, bool]] = []
        self.retired: list[str] = []

    @asynccontextmanager
    async def load_lock(self, _dataset: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
        # run 상한 + 취소 유예(600초) + 60초 — 상한보다 짧으면 실행 중에 풀리고,
        # 2시간이면 죽은 run이 다음 tick들을 막는다.
        assert ttl_seconds == lock_ttl_seconds(TRANSPORT_STATE_SPECS[0])
        assert ttl_seconds == TRANSPORT_STATE_SPECS[0].max_runtime_seconds + 660
        yield not self.locked

    async def swap(self, dataset: str, items: list[Any], **kwargs: Any) -> SwapResult:
        if self.swap_error is not None:
            raise self.swap_error
        self.swapped.append((dataset, len(items), kwargs["allow_shrink"]))
        meta = GenerationMeta(
            dataset=dataset,
            generation="20261023T000000Z-00000000",
            count=len(items),
            geo_count=0,
            lookup_count=0,
            duplicates=0,
            source_collected_at=kwargs["source_collected_at"],
            loaded_at=kwargs["loaded_at"],
            run_id=kwargs["run_id"],
            guard_override=kwargs["allow_shrink"],
        )
        return SwapResult(meta=meta, previous_generation=None, baseline=None)

    async def retire_other_versions(self, dataset: str) -> int:
        self.retired.append(dataset)
        return 0


def _spec(collect: Callable[..., Any]) -> TransportStateJobSpec:
    return replace(TRANSPORT_STATE_SPECS[0], collect=collect)


async def _collect_two(_settings: Any, on_collected_at: Callable[[datetime], None]) -> list[Any]:
    on_collected_at(datetime.fromisoformat("2026-10-23T01:00:00+00:00"))
    on_collected_at(datetime.fromisoformat("2026-10-23T00:30:00+00:00"))
    return [object(), object()]


async def _load(store: _FakeStore, collect: Callable[..., Any] = _collect_two) -> dict[str, Any]:
    return await load_transport_state(
        _spec(collect),
        settings=KorTravelMapSettings.model_construct(),
        run_id="run-x",
        allow_shrink=False,
        store=cast(ValkeyStateStore, store),
    )


async def test_success_reports_the_earliest_source_collection() -> None:
    store = _FakeStore()
    metadata = await _load(store)
    assert store.swapped == [(TRANSPORT_STATE_SPECS[0].dataset.name, 2, False)]
    assert metadata["count"] == 2
    assert metadata["source_collected_at"] == "2026-10-23T00:30:00+00:00"
    # 옛 스키마 버전 정리는 자기 데이터셋만(ADR-114 D2).
    assert store.retired == [TRANSPORT_STATE_SPECS[0].dataset.name]


async def test_a_held_lock_skips_without_fetching() -> None:
    async def _boom(*_args: Any) -> list[Any]:
        raise AssertionError("잠금을 못 잡았으면 받지 않는다")

    store = _FakeStore(locked=True)
    assert (await _load(store, _boom))["skipped"] == "locked"
    assert store.swapped == []


async def test_refusal_is_terminal_and_names_the_override() -> None:
    store = _FakeStore(swap_error=StateSwapRefused("거부", baseline=106, new_count=0))
    with pytest.raises(Failure) as excinfo:
        await _load(store)
    assert excinfo.value.allow_retries is False
    metadata = excinfo.value.metadata
    assert str(metadata["failure_kind"].value) == "state_swap_refused"
    assert "allow_shrink" in str(metadata["override"].value)


async def test_valkey_outage_stays_retryable() -> None:
    store = _FakeStore(swap_error=StateStoreUnavailable("연결 실패"))
    with pytest.raises(StateStoreUnavailable):
        await _load(store)


async def test_missing_valkey_configuration_is_terminal() -> None:
    with pytest.raises(Failure) as excinfo:
        await load_transport_state(
            TRANSPORT_STATE_SPECS[0],
            settings=KorTravelMapSettings.model_construct(valkey_url=None),
            run_id=None,
            allow_shrink=False,
        )
    assert excinfo.value.allow_retries is False
    assert isinstance(excinfo.value.__cause__, StateStoreNotConfigured)


async def test_transport_failures_follow_the_existing_classification() -> None:
    async def _empty(*_args: Any) -> list[Any]:
        raise TransportExportEmpty("0건")

    async def _not_current(*_args: Any) -> list[Any]:
        raise TransportExportNotCurrent("stale")

    with pytest.raises(Failure) as excinfo:
        await _load(_FakeStore(), _empty)
    assert excinfo.value.allow_retries is False
    with pytest.raises(TransportExportNotCurrent):
        await _load(_FakeStore(), _not_current)

"""ADR-114 transport 상태 적재 job — 정의(STOPPED·tag)와 실패 분류(Valkey 없이)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from dagster import DefaultScheduleStatus, Failure
from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateNotLoaded,
    StateStoreNotConfigured,
    StateStoreUnavailable,
    StateSwapRefused,
    SwapResult,
    ValkeyStateStore,
)
from kortravelmap.providers.kor_travel_transport import (
    TransportExportBusy,
    TransportExportDisabled,
    TransportExportEmpty,
    TransportExportNotCurrent,
    TransportSourceInconsistent,
    TransportSourceNotCurrent,
)
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster.definitions import defs
from kortravelmap.dagster.provider_fetchers import TransportExportUnchanged
from kortravelmap.dagster.transport_state import (
    FULL_WALK_INTERVAL,
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
    def __init__(
        self,
        *,
        locked: bool = False,
        swap_error: Exception | None = None,
        served: GenerationMeta | None = None,
    ) -> None:
        self.locked = locked
        self.swap_error = swap_error
        self.served = served
        self.swapped: list[tuple[str, int, bool]] = []
        self.retired: list[str] = []

    async def current_meta(self, dataset: str) -> GenerationMeta:
        if self.served is None:
            raise StateNotLoaded(f"{dataset}는 아직 적재되지 않았다.")
        return self.served

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


# ------------------------------------------------- 바뀌지 않은 집합 건너뛰기(감사 MC-04)

_COLLECTED = datetime.fromisoformat("2026-11-24T00:00:05+00:00")


def _served(*, loaded_ago: timedelta, collected: datetime | None = _COLLECTED) -> GenerationMeta:
    return GenerationMeta(
        dataset=TRANSPORT_STATE_SPECS[0].dataset.name,
        generation="20261124T000500Z-aaaaaaaa",
        count=12_000,
        geo_count=12_000,
        lookup_count=0,
        duplicates=0,
        source_collected_at=collected,
        loaded_at=datetime.now(UTC) - loaded_ago,
        run_id="run-old",
        guard_override=False,
    )


class _RecordingCollect:
    """``unchanged_since``를 기록하고, 같으면 fetcher처럼 :class:`TransportExportUnchanged`를
    낸다."""

    def __init__(self, first_page_success_at: datetime) -> None:
        self.first_page_success_at = first_page_success_at
        self.calls: list[datetime | None] = []

    async def __call__(
        self,
        _settings: Any,
        on_collected_at: Callable[[datetime], None],
        /,
        *,
        unchanged_since: datetime | None = None,
    ) -> list[Any]:
        self.calls.append(unchanged_since)
        if unchanged_since is not None and unchanged_since == self.first_page_success_at:
            raise TransportExportUnchanged("/v1/service/exports/fuel-stations", unchanged_since)
        on_collected_at(self.first_page_success_at)
        return [object(), object()]


def test_only_the_hourly_price_datasets_skip_an_unchanged_set() -> None:
    skipping = {spec.dataset.name for spec in TRANSPORT_STATE_SPECS if spec.skip_unchanged}
    assert skipping == {"transport.fuel_stations", "transport.rest_area_fuel_prices"}
    assert timedelta(hours=6) == FULL_WALK_INTERVAL


async def test_an_unchanged_collection_skips_the_walk_and_the_swap() -> None:
    store = _FakeStore(served=_served(loaded_ago=timedelta(hours=1)))
    collect = _RecordingCollect(_COLLECTED)
    metadata = await _load(store, collect)
    assert collect.calls == [_COLLECTED]
    assert store.swapped == []
    assert metadata["skipped"] == "unchanged"
    assert metadata["generation"] == "20261124T000500Z-aaaaaaaa"
    assert metadata["source_collected_at"] == _COLLECTED.isoformat()
    assert metadata["full_walk_interval_seconds"] == 6 * 3600
    assert 3500 <= metadata["generation_age_seconds"] <= 3700


async def test_a_new_collection_walks_everything_and_swaps() -> None:
    store = _FakeStore(served=_served(loaded_ago=timedelta(hours=1)))
    newer = _COLLECTED + timedelta(hours=8)
    collect = _RecordingCollect(newer)
    metadata = await _load(store, collect)
    assert collect.calls == [_COLLECTED]  # 기준은 보냈지만 첫 페이지가 달랐다
    assert store.swapped == [(TRANSPORT_STATE_SPECS[0].dataset.name, 2, False)]
    assert metadata["source_collected_at"] == newer.isoformat()


@pytest.mark.parametrize(
    "served",
    [
        # 전량 주기 — admin 주소는 last_success_at 없이 바뀐다.
        _served(loaded_ago=timedelta(hours=6)),
        # 원천 수집 시각 없는 세대.
        _served(loaded_ago=timedelta(minutes=5), collected=None),
        # 첫 적재 전.
        None,
    ],
    ids=["full-walk-due", "no-source-time", "not-loaded"],
)
async def test_a_full_walk_is_forced_when_skipping_is_not_safe(
    served: GenerationMeta | None,
) -> None:
    store = _FakeStore(served=served)
    collect = _RecordingCollect(_COLLECTED)
    metadata = await _load(store, collect)
    assert collect.calls == [None]
    assert store.swapped == [(TRANSPORT_STATE_SPECS[0].dataset.name, 2, False)]
    assert "skipped" not in metadata


async def test_datasets_without_skipping_never_read_the_served_meta() -> None:
    class _NoMeta(_FakeStore):
        async def current_meta(self, dataset: str) -> GenerationMeta:
            raise AssertionError("건너뛰기를 하지 않는 데이터셋은 meta를 미리 읽지 않는다")

        @asynccontextmanager
        async def load_lock(self, _dataset: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
            del ttl_seconds
            yield True

    spec = replace(TRANSPORT_STATE_SPECS[1], collect=_collect_two)
    assert spec.skip_unchanged is False
    metadata = await load_transport_state(
        spec,
        settings=KorTravelMapSettings.model_construct(),
        run_id="run-x",
        allow_shrink=False,
        store=cast(ValkeyStateStore, _NoMeta()),
    )
    assert metadata["count"] == 2


# ------------------------------------------------- transport 503 code(2026-11-24 계약, 감사 MC-01)


@pytest.mark.parametrize(
    ("code", "retry_after"),
    [
        ("EXPORT_SOURCE_NOT_CURRENT", 1800.0),
        ("EXPORT_NO_HISTORY", 3600.0),
        ("EXPORT_INCIDENTS_NOT_CURRENT", 300.0),
        ("EXPORT_EMPTY_SET", 300.0),
    ],
)
async def test_a_coded_not_current_503_fails_the_run_without_retries(
    code: str, retry_after: float
) -> None:
    """초록으로 건너뛰지 않는다 — Map에는 상류 장애 경보가 없어 빨간 run이 유일한 신호다."""

    async def _not_current(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise TransportSourceNotCurrent("503", code=code, retry_after=retry_after)

    store = _FakeStore(served=_served(loaded_ago=timedelta(hours=1)))
    with pytest.raises(Failure) as excinfo:
        await _load(store, _not_current)
    assert excinfo.value.allow_retries is False
    assert store.swapped == []
    metadata = {key: value.value for key, value in excinfo.value.metadata.items()}
    assert metadata["outcome"] == "skipped_upstream_not_current"
    assert metadata["transport_problem_code"] == code
    assert metadata["transport_retry_after_seconds"] == retry_after
    assert metadata["served_generation"] == "20261124T000500Z-aaaaaaaa"
    assert metadata["last_success_at"] == _COLLECTED.isoformat()
    assert int(str(metadata["served_age_seconds"])) > 0
    assert code in (excinfo.value.description or "")


async def test_a_coded_not_current_503_before_the_first_load_still_fails() -> None:
    async def _not_current(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise TransportSourceNotCurrent("503", code="EXPORT_NO_HISTORY", retry_after=3600.0)

    with pytest.raises(Failure) as excinfo:
        await _load(_FakeStore(served=None), _not_current)
    metadata = {key: value.value for key, value in excinfo.value.metadata.items()}
    assert metadata["served_generation"] == ""
    assert metadata["last_success_at"] == ""
    assert metadata["served_age_seconds"] == -1


async def test_a_busy_503_beyond_the_wait_cap_fails_without_retries() -> None:
    async def _busy(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise TransportExportBusy(
            "503", code="EXPORT_BUSY", retry_after=600.0, retry_after_cap=60.0
        )

    with pytest.raises(Failure) as excinfo:
        await _load(_FakeStore(), _busy)
    assert excinfo.value.allow_retries is False
    metadata = {key: value.value for key, value in excinfo.value.metadata.items()}
    assert metadata["transport_problem_code"] == "EXPORT_BUSY"
    assert metadata["failure_kind"] == "transport_busy"


async def test_a_short_busy_503_and_an_uncoded_503_keep_step_retries() -> None:
    """HTTP 층 재시도를 다 쓴 경합과 code 없는(또는 모르는 code) 503은 종전대로 step 재시도다."""
    busy = TransportExportBusy("503", code="TRANSIENT_DB", retry_after=15.0, retry_after_cap=60.0)
    unknown = TransportExportNotCurrent("503", code="SERVICE_UNAVAILABLE")

    async def _raise_busy(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise busy

    async def _raise_unknown(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise unknown

    with pytest.raises(TransportExportBusy):
        await _load(_FakeStore(), _raise_busy)
    with pytest.raises(TransportExportNotCurrent) as excinfo:
        await _load(_FakeStore(), _raise_unknown)
    assert excinfo.value is unknown


async def test_a_disabled_export_fails_without_retries_through_the_existing_terminal_path() -> None:
    async def _disabled(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise TransportExportDisabled("503", code="EXPORT_DISABLED", retry_after=3600.0)

    with pytest.raises(Failure) as excinfo:
        await _load(_FakeStore(), _disabled)
    assert excinfo.value.allow_retries is False
    metadata = {key: value.value for key, value in excinfo.value.metadata.items()}
    assert metadata["failure_kind"] == "transport_export_disabled"
    assert metadata["transport_problem_code"] == "EXPORT_DISABLED"
    assert "outcome" not in metadata  # 상류 수집 지연이 아니라 설정 문제다


async def test_an_inconsistent_source_keeps_step_retries() -> None:
    cause = TransportSourceInconsistent("503", code="EXPORT_SOURCE_INCONSISTENT")

    async def _inconsistent(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise cause

    with pytest.raises(TransportSourceInconsistent) as excinfo:
        await _load(_FakeStore(), _inconsistent)
    assert excinfo.value is cause

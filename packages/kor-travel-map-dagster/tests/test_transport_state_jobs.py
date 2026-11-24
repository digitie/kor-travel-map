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
    RETRY_TIME_SHARE,
    TRANSPORT_STATE_SPECS,
    TransportStateJobSpec,
    alert_after_seconds,
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
        self.last_swap_kwargs: dict[str, Any] = {}

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
        self.last_swap_kwargs = kwargs
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


# ------------------------------------------------- transport 503 code(2026-11-24 계약, 감사 MC-01)


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


# ------------------------------------------- 나이 기준 혼합(소유자 결정 2026-11-24)


def _served_at(
    *, source_age: timedelta, loaded_ago: timedelta = timedelta(hours=1)
) -> GenerationMeta:
    now = datetime.now(UTC)
    return GenerationMeta(
        dataset=TRANSPORT_STATE_SPECS[0].dataset.name,
        generation="20261124T000500Z-bbbbbbbb",
        count=12_000,
        geo_count=12_000,
        lookup_count=0,
        duplicates=0,
        source_collected_at=now - source_age,
        loaded_at=now - loaded_ago,
        run_id="run-old",
        guard_override=False,
    )


_HOLD_FAILURES = [
    TransportSourceNotCurrent("503", code="EXPORT_SOURCE_NOT_CURRENT", retry_after=1800.0),
    TransportExportBusy("503", code="EXPORT_BUSY", retry_after=10.0, retry_after_cap=60.0),
    TransportExportBusy(
        "503", code="EXPORT_PREPARE_TIMEOUT", retry_after=120.0, retry_after_cap=60.0
    ),
]
_HOLD_IDS = ["source-not-current", "busy-exhausted", "busy-over-cap"]
_HOLD_OUTCOMES = {
    "source-not-current": "upstream_source_not_current",
    "busy-exhausted": "upstream_busy_exhausted",
    "busy-over-cap": "upstream_busy_over_cap",
}


def _raising(exc: Exception) -> Callable[..., Any]:
    async def _collect(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise exc

    return _collect


@pytest.mark.parametrize("exc", _HOLD_FAILURES, ids=_HOLD_IDS)
async def test_a_fresh_served_generation_keeps_the_run_green(
    exc: Exception, request: pytest.FixtureRequest
) -> None:
    """주유소 경고 기준 16시간 — 서비스 세대 원천이 1시간이면 건너뛰고 초록.

    세대 유지, 재시도 없음.
    """
    store = _FakeStore(served=_served_at(source_age=timedelta(hours=1)))
    metadata = await _load(store, _raising(exc))
    assert store.swapped == []
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["upstream_state"] == "not_ready"
    assert metadata["outcome"] == _HOLD_OUTCOMES[request.node.callspec.id]
    assert metadata["stale_alert"] is False
    assert metadata["stale_alert_after_seconds"] == 16 * 3600
    assert 3500 <= metadata["served_age_seconds"] <= 3700
    assert metadata["served_generation"] == "20261124T000500Z-bbbbbbbb"
    assert "served_source_collected_at" in metadata
    assert metadata["transport_problem_code"] == exc.code  # type: ignore[attr-defined]
    assert "source not current" not in str(metadata).lower() or "busy" not in metadata["outcome"]


@pytest.mark.parametrize("exc", _HOLD_FAILURES, ids=_HOLD_IDS)
async def test_an_old_served_generation_turns_the_run_red_without_retries(
    exc: Exception, request: pytest.FixtureRequest
) -> None:
    store = _FakeStore(served=_served_at(source_age=timedelta(hours=17)))
    with pytest.raises(Failure) as excinfo:
        await _load(store, _raising(exc))
    assert excinfo.value.allow_retries is False
    metadata = {key: value.value for key, value in excinfo.value.metadata.items()}
    assert metadata["outcome"] == _HOLD_OUTCOMES[request.node.callspec.id]
    assert metadata["stale_alert"] is True
    assert "skipped" not in metadata
    assert int(str(metadata["served_age_seconds"])) > 16 * 3600
    assert store.swapped == []


async def test_no_served_generation_is_red_and_unknown_values_are_absent() -> None:
    exc = TransportSourceNotCurrent("503", code="EXPORT_NO_HISTORY", retry_after=None)
    with pytest.raises(Failure) as excinfo:
        await _load(_FakeStore(served=None), _raising(exc))
    metadata = {key: value.value for key, value in excinfo.value.metadata.items()}
    assert metadata["stale_alert"] is True
    for absent in (
        "served_generation",
        "served_source_collected_at",
        "served_age_seconds",
        "transport_retry_after_seconds",
    ):
        assert absent not in metadata


async def test_the_over_cap_busy_explains_the_cap_in_metadata() -> None:
    store = _FakeStore(served=_served_at(source_age=timedelta(hours=1)))
    metadata = await _load(store, _raising(_HOLD_FAILURES[2]))
    assert metadata["transport_retry_after_cap_seconds"] == 60.0
    assert "대기 상한" in metadata["transport_retry_after_cap_note"]
    assert metadata["transport_retry_after_seconds"] == 120.0


async def test_an_uncoded_503_and_an_inconsistent_source_keep_todays_step_retries() -> None:
    unknown = TransportExportNotCurrent("503", code="SERVICE_UNAVAILABLE")
    with pytest.raises(TransportExportNotCurrent) as excinfo:
        await _load(_FakeStore(served=_served_at(source_age=timedelta(hours=1))), _raising(unknown))
    assert excinfo.value is unknown


def test_alert_thresholds_stay_below_the_read_stale_limit() -> None:
    settings = KorTravelMapSettings.model_construct()
    for spec in TRANSPORT_STATE_SPECS:
        assert spec.alert_after_setting
        assert alert_after_seconds(spec, settings) < spec.dataset.max_age.total_seconds()
        field = KorTravelMapSettings.model_fields[spec.alert_after_setting]
        upper = next(m.lt for m in field.metadata if hasattr(m, "lt") and m.lt is not None)
        assert upper == spec.dataset.max_age.total_seconds(), spec.alert_after_setting


# ------------------------------------------- 전량 주기·force_full_walk·재시도 시간(적대 리뷰)


async def test_the_full_walk_interval_counts_from_the_walk_start() -> None:
    """교체 시각이 아니라 순회 시작 시각(``full_synced_at``)을 남긴다.

    매시 tick에서 6시간마다 전량.
    """
    store = _FakeStore(served=None)
    await _load(store)
    # _FakeStore.swap은 kwargs를 그대로 받는다 — full_synced_at이 loaded_at보다 늦지 않다.
    assert store.last_swap_kwargs["full_synced_at"] <= store.last_swap_kwargs["loaded_at"]


async def test_a_future_full_walk_basis_forces_a_full_walk() -> None:
    """시계가 뒤로 가 기준이 미래면 믿지 않는다."""
    served = _served(loaded_ago=timedelta(hours=1))
    future = replace(served, full_synced_at=datetime.now(UTC) + timedelta(hours=2))
    store = _FakeStore(served=future)
    collect = _RecordingCollect(_COLLECTED)
    await _load(store, collect)
    assert collect.calls == [None]


async def test_a_recent_walk_start_keeps_skipping_even_when_the_swap_was_late() -> None:
    served = _served(loaded_ago=timedelta(hours=5, minutes=50))
    started = replace(served, full_synced_at=datetime.now(UTC) - timedelta(hours=5, minutes=55))
    collect = _RecordingCollect(_COLLECTED)
    metadata = await _load(_FakeStore(served=started), collect)
    assert metadata["skipped"] == "unchanged"
    late = replace(served, full_synced_at=datetime.now(UTC) - timedelta(hours=6, minutes=1))
    collect = _RecordingCollect(_COLLECTED)
    await _load(_FakeStore(served=late), collect)
    assert collect.calls == [None]


async def test_force_full_walk_disables_the_unchanged_skip() -> None:
    store = _FakeStore(served=_served(loaded_ago=timedelta(hours=1)))
    collect = _RecordingCollect(_COLLECTED)
    await load_transport_state(
        _spec(collect),
        settings=KorTravelMapSettings.model_construct(),
        run_id="run-x",
        allow_shrink=False,
        store=cast(ValkeyStateStore, store),
        force_full_walk=True,
    )
    assert collect.calls == [None]
    assert len(store.swapped) == 1


async def test_retry_time_is_bounded_by_the_run_limit() -> None:
    seen: list[float | None] = []

    async def _collect(*_args: Any, **_kwargs: Any) -> list[Any]:
        from kortravelmap.dagster import upstream_retry

        budget = upstream_retry.active_run_retry_budget()
        seen.append(budget.max_seconds if budget is not None else None)
        return [object()]

    await _load(_FakeStore(), _collect)
    assert seen == [TRANSPORT_STATE_SPECS[0].max_runtime_seconds * RETRY_TIME_SHARE]

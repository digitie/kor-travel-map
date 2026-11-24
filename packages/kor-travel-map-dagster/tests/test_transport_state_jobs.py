"""ADR-114 transport 상태 적재 job — 정의(STOPPED·tag)와 실패 분류(Valkey 없이).

상류 미준비·거부 규칙(2026-11-24 개정)은 ``upstream_signal``이 정본이다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
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
    TransportExportHidden,
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
from kortravelmap.dagster.upstream_signal import raise_if_stale


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
        # Dagster는 retry policy가 있는 step이 run 상한 초과 취소로 끝나도 재시도를 요청한다 —
        # 상태 op에는 retry policy가 없어야 한다(Valkey 연결 실패만 op가 직접 요청한다).
        (node,) = job.nodes
        assert node.definition.retry_policy is None, spec.job_name


def _served(age: timedelta) -> GenerationMeta:
    collected = datetime.now(UTC) - age
    return GenerationMeta(
        dataset=TRANSPORT_STATE_SPECS[0].dataset.name,
        generation="g-served",
        count=12_000,
        geo_count=12_000,
        lookup_count=0,
        duplicates=0,
        source_collected_at=collected,
        loaded_at=collected,
        run_id="run-old",
        guard_override=False,
    )


class _FakeStore:
    def __init__(
        self,
        *,
        locked: bool = False,
        swap_error: Exception | None = None,
        current: GenerationMeta | None = None,
    ) -> None:
        self.locked = locked
        self.swap_error = swap_error
        self.current = current
        self.swapped: list[tuple[str, int, bool]] = []
        self.retired: list[str] = []

    async def current_meta(self, dataset: str) -> GenerationMeta:
        if self.current is None:
            raise StateNotLoaded(dataset)
        return self.current

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


async def _collect_two(
    _settings: Any, on_collected_at: Callable[[datetime], None], /, **_kwargs: Any
) -> list[Any]:
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
    # 교체한 세대가 곧 서비스 세대다 — 그 원천 나이를 남긴다(고정 시각이라 경고 나이를 넘는다).
    assert metadata["upstream_state"] == "ok"
    assert metadata["served_generation"] == "20261023T000000Z-00000000"
    assert metadata["served_age_seconds"] > 0
    assert metadata["stale_alert"] is True


async def test_fresh_success_is_not_an_alert() -> None:
    async def _fresh(
        _settings: Any, on_collected_at: Callable[[datetime], None], /, **_kwargs: Any
    ) -> list[Any]:
        on_collected_at(datetime.now(UTC) - timedelta(minutes=5))
        return [object()]

    metadata = await _load(_FakeStore(), _fresh)
    assert metadata["upstream_state"] == "ok"
    assert 0 <= metadata["served_age_seconds"] < 600
    assert metadata["stale_alert"] is False


async def test_a_held_lock_skips_without_fetching() -> None:
    async def _boom(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise AssertionError("잠금을 못 잡았으면 받지 않는다")

    store = _FakeStore(locked=True)
    assert (await _load(store, _boom))["skipped"] == "locked"
    assert store.swapped == []


async def test_refusal_while_the_served_generation_is_fresh_skips_with_a_warning() -> None:
    # 일시적인 상류 이상(14일 64건 대부분이 다음 tick에 풀렸다) — 세대를 지키고 run은 성공한다.
    store = _FakeStore(
        swap_error=StateSwapRefused("거부", baseline=106, new_count=0),
        current=_served(timedelta(hours=1)),
    )
    metadata = await _load(store)
    assert metadata["skipped"] == "refused"
    assert metadata["upstream_state"] == "refused"
    assert metadata["failure_kind"] == "state_swap_refused"
    assert metadata["baseline"] == 106
    assert metadata["new_count"] == 0
    assert metadata["served_generation"] == "g-served"
    assert metadata["stale_alert"] is False
    assert "allow_shrink" in metadata["override"]
    assert store.swapped == []


async def test_refusal_past_the_stale_age_fails_the_run_and_names_the_override() -> None:
    # 거부가 이어져 서비스 세대가 경고 임계(stale_alert_after)를 넘었다 — 사람이 판단할 차례다.
    spec = TRANSPORT_STATE_SPECS[0]
    store = _FakeStore(
        swap_error=StateSwapRefused("거부", baseline=106, new_count=0),
        current=_served(spec.stale_alert_after + timedelta(minutes=1)),
    )
    metadata = await _load(store)
    assert metadata["skipped"] == "refused"
    assert metadata["stale_alert"] is True
    with pytest.raises(Failure) as excinfo:
        raise_if_stale(metadata)  # op가 하는 일
    assert excinfo.value.allow_retries is False
    failure = excinfo.value.metadata
    assert str(failure["failure_kind"].value) == "state_swap_refused"
    assert "allow_shrink" in str(failure["override"].value)
    assert "allow_shrink" in str(excinfo.value.description)


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


def _raising(error: Exception) -> Callable[..., Any]:
    async def _collect(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise error

    return _collect


async def test_empty_export_follows_the_refusal_rule() -> None:
    # 0건 export는 교체 거부와 같은 데이터 보호다. 서비스 세대가 없으면(나이를 모른다) 경고다.
    first = await _load(_FakeStore(), _raising(TransportExportEmpty("0건")))
    assert first["skipped"] == "refused"
    assert first["failure_kind"] == "transport_empty"
    assert first["stale_alert"] is True
    fresh = await _load(
        _FakeStore(current=_served(timedelta(minutes=30))), _raising(TransportExportEmpty("0건"))
    )
    assert fresh["skipped"] == "refused"
    assert fresh["new_count"] == 0


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (TransportExportNotCurrent("503 — 근거 수집 stale"), "transport_not_current"),
        (httpx.ConnectError("refused"), "upstream_unreachable:ConnectError"),
        (httpx.ReadTimeout("slow"), "upstream_unreachable:ReadTimeout"),
    ],
)
async def test_upstream_not_ready_skips_the_tick_without_a_step_retry(
    error: Exception, kind: str
) -> None:
    # 몇 시간짜리 상류 장애를 30·60초 뒤 다시 묻지 않는다 — 이번 tick을 건너뛰고 서비스 세대의
    # 나이를 남긴다(2026-11-23 감사: 재시도 344건 중 성공 16%).
    store = _FakeStore(current=_served(timedelta(minutes=20)))
    metadata = await _load(store, _raising(error))
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["upstream_state"] == "not_ready"
    assert metadata["failure_kind"] == kind
    assert metadata["served_generation"] == "g-served"
    assert 1_100 < metadata["served_age_seconds"] < 1_300
    assert metadata["stale_alert"] is False
    raise_if_stale(metadata)  # stale 기준 안 — run은 성공
    assert store.swapped == []


async def test_not_ready_past_the_stale_age_fails_without_a_retry() -> None:
    # 몇 시간 이어진 상류 장애·설정 오류(주소·DNS)는 결국 빨갛게 된다 — 경보가 따로 없다.
    spec = TRANSPORT_STATE_SPECS[0]
    store = _FakeStore(current=_served(spec.stale_alert_after + timedelta(minutes=5)))
    metadata = await _load(store, _raising(httpx.ConnectError("DNS")))
    assert metadata["skipped"] == "upstream_not_ready"
    with pytest.raises(Failure) as excinfo:
        raise_if_stale(metadata)
    assert excinfo.value.allow_retries is False
    assert "upstream_unreachable:ConnectError" in str(excinfo.value.description)


async def test_misconfigured_base_url_is_not_an_upstream_outage() -> None:
    with pytest.raises(httpx.UnsupportedProtocol):
        await _load(_FakeStore(), _raising(httpx.UnsupportedProtocol("scheme 없음")))


@pytest.mark.parametrize(
    ("status", "kind"), [(500, "upstream_http_500"), (429, "upstream_http_429")]
)
async def test_transport_server_errors_are_not_ready_like_weather(status: int, kind: str) -> None:
    request = httpx.Request("GET", "http://transport/v1/service/exports/fuel-stations")
    error = httpx.HTTPStatusError(
        "status", request=request, response=httpx.Response(status, request=request)
    )
    metadata = await _load(_FakeStore(current=_served(timedelta(minutes=5))), _raising(error))
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["failure_kind"] == kind


async def test_not_ready_before_the_first_load_is_an_alert() -> None:
    metadata = await _load(_FakeStore(), _raising(TransportExportNotCurrent("503")))
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["served_generation"] == ""
    assert metadata["served_age_seconds"] == -1
    assert metadata["stale_alert"] is True


async def test_unrecoverable_transport_failure_stays_terminal() -> None:
    with pytest.raises(Failure) as excinfo:
        await _load(_FakeStore(), _raising(TransportExportHidden("404")))
    assert excinfo.value.allow_retries is False


def test_alert_thresholds_sit_below_the_read_side_max_age() -> None:
    # 소유자 결정(2026-11-24 "나이 기준 혼합"): 경고 임계는 데이터셋별, 읽기 쪽 max_age보다 낮다.
    expected = {
        "transport.fuel_stations": timedelta(hours=16),
        "transport.rest_area_fuel_prices": timedelta(hours=8),
        "transport.highway_incidents": timedelta(minutes=20),
        "transport.rest_areas": timedelta(days=2),
        "transport.airports": timedelta(days=2),
    }
    assert {spec.dataset.name: spec.stale_alert_after for spec in TRANSPORT_STATE_SPECS} == expected
    for spec in TRANSPORT_STATE_SPECS:
        assert spec.stale_alert_after < spec.dataset.max_age, spec.job_name


# ------------------------------------------------- 바뀌지 않은 집합 건너뛰기(감사 MC-04, #1549)

_COLLECTED = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)


def _served_at(
    *, loaded_ago: timedelta, collected: datetime | None = _COLLECTED
) -> GenerationMeta:
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
    store = _FakeStore(current=_served_at(loaded_ago=timedelta(hours=1)))
    collect = _RecordingCollect(_COLLECTED)
    metadata = await _load(store, collect)
    assert collect.calls == [_COLLECTED]
    assert store.swapped == []
    assert metadata["skipped"] == "unchanged"
    assert metadata["generation"] == "20261124T000500Z-aaaaaaaa"
    assert metadata["source_collected_at"] == _COLLECTED.isoformat()
    assert metadata["full_walk_interval_seconds"] == 6 * 3600
    assert 3500 <= metadata["generation_age_seconds"] <= 3700
    # 바뀌지 않았어도 서비스 세대 나이는 잰다 — 원천이 오래 그대로면 결국 빨갛게 된다.
    assert metadata["upstream_state"] == "ok"
    assert metadata["stale_alert"] is False


async def test_an_unchanged_but_old_collection_is_still_judged_by_its_age() -> None:
    old = datetime.now(UTC) - timedelta(hours=17)
    store = _FakeStore(current=_served_at(loaded_ago=timedelta(hours=1), collected=old))
    metadata = await _load(store, _RecordingCollect(old))
    assert metadata["skipped"] == "unchanged"
    assert metadata["stale_alert"] is True
    with pytest.raises(Failure):
        raise_if_stale(metadata)


async def test_a_new_collection_walks_everything_and_swaps() -> None:
    store = _FakeStore(current=_served_at(loaded_ago=timedelta(hours=1)))
    newer = _COLLECTED + timedelta(minutes=30)
    collect = _RecordingCollect(newer)
    metadata = await _load(store, collect)
    assert collect.calls == [_COLLECTED]  # 기준은 보냈지만 첫 페이지가 달랐다
    assert store.swapped == [(TRANSPORT_STATE_SPECS[0].dataset.name, 2, False)]
    assert metadata["source_collected_at"] == newer.isoformat()


@pytest.mark.parametrize(
    "served",
    [
        # 전량 주기 — admin 주소는 last_success_at 없이 바뀐다.
        _served_at(loaded_ago=timedelta(hours=6)),
        # 원천 수집 시각 없는 세대.
        _served_at(loaded_ago=timedelta(minutes=5), collected=None),
        # 첫 적재 전.
        None,
    ],
    ids=["full-walk-due", "no-source-time", "not-loaded"],
)
async def test_a_full_walk_is_forced_when_skipping_is_not_safe(
    served: GenerationMeta | None,
) -> None:
    store = _FakeStore(current=served)
    collect = _RecordingCollect(_COLLECTED)
    metadata = await _load(store, collect)
    assert collect.calls == [None]
    assert store.swapped == [(TRANSPORT_STATE_SPECS[0].dataset.name, 2, False)]
    assert "skipped" not in metadata


async def test_datasets_without_skipping_never_send_an_unchanged_basis() -> None:
    class _AnyTtl(_FakeStore):
        @asynccontextmanager
        async def load_lock(self, _dataset: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
            del ttl_seconds
            yield True

    spec = replace(TRANSPORT_STATE_SPECS[1], collect=_RecordingCollect(_COLLECTED))
    assert spec.skip_unchanged is False
    store = _AnyTtl(current=_served_at(loaded_ago=timedelta(minutes=5)))
    metadata = await load_transport_state(
        spec,
        settings=KorTravelMapSettings.model_construct(),
        run_id="run-x",
        allow_shrink=False,
        store=cast(ValkeyStateStore, store),
    )
    assert spec.collect.calls == [None]  # type: ignore[attr-defined]
    assert metadata["count"] == 2


# ------------------------------------------------- transport 503 code(transport #277, 감사 MC-01)
# 소유자 결정(2026-11-24 "나이 기준 혼합"): Valkey 상태 job은 code 503을 상류 미준비로 건너뛰고,
# 서비스 세대의 원천 나이가 경고 임계를 넘을 때만 재시도 없이 실패한다.


def _raising_problem(error: Exception) -> Callable[..., Any]:
    async def _collect(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise error

    return _collect


@pytest.mark.parametrize(
    ("code", "retry_after", "kind"),
    [
        ("EXPORT_SOURCE_NOT_CURRENT", 1800.0, "transport_source_not_current"),
        ("EXPORT_NO_HISTORY", 3600.0, "transport_no_history"),
        ("EXPORT_INCIDENTS_NOT_CURRENT", 300.0, "transport_incidents_not_current"),
        ("EXPORT_EMPTY_SET", 300.0, "transport_empty_set"),
    ],
)
async def test_a_coded_not_current_503_skips_within_the_alert_age(
    code: str, retry_after: float, kind: str
) -> None:
    error = TransportSourceNotCurrent("503", code=code, retry_after=retry_after)
    store = _FakeStore(current=_served_at(loaded_ago=timedelta(hours=1)))
    metadata = await _load(store, _raising_problem(error))
    assert store.swapped == []
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["failure_kind"] == kind
    assert metadata["transport_problem_code"] == code
    assert metadata["transport_retry_after_seconds"] == retry_after
    assert metadata["served_generation"] == "20261124T000500Z-aaaaaaaa"
    assert metadata["stale_alert"] is False
    raise_if_stale(metadata)  # 초록 — 세대를 지키고 다음 tick을 기다린다


async def test_a_coded_not_current_503_past_the_alert_age_fails_without_retries() -> None:
    error = TransportSourceNotCurrent("503", code="EXPORT_SOURCE_NOT_CURRENT", retry_after=1800.0)
    old = datetime.now(UTC) - timedelta(hours=17)  # 주유소 경고 임계 16시간
    store = _FakeStore(current=_served_at(loaded_ago=timedelta(hours=17), collected=old))
    metadata = await _load(store, _raising_problem(error))
    with pytest.raises(Failure) as excinfo:
        raise_if_stale(metadata)
    assert excinfo.value.allow_retries is False
    failure = {key: value.value for key, value in excinfo.value.metadata.items()}
    assert failure["transport_problem_code"] == "EXPORT_SOURCE_NOT_CURRENT"
    assert "transport_source_not_current" in (excinfo.value.description or "")


async def test_a_coded_not_current_503_before_the_first_load_fails() -> None:
    error = TransportSourceNotCurrent("503", code="EXPORT_NO_HISTORY", retry_after=3600.0)
    metadata = await _load(_FakeStore(), _raising_problem(error))
    assert metadata["served_generation"] == ""
    assert metadata["served_age_seconds"] == -1
    with pytest.raises(Failure):
        raise_if_stale(metadata)


@pytest.mark.parametrize(
    "error",
    [
        TransportExportBusy("503", code="EXPORT_BUSY", retry_after=600.0, retry_after_cap=60.0),
        TransportExportBusy("503", code="TRANSIENT_DB", retry_after=15.0, retry_after_cap=60.0),
        TransportExportNotCurrent("503", code="SERVICE_UNAVAILABLE"),
        TransportSourceInconsistent("503", code="EXPORT_SOURCE_INCONSISTENT"),
    ],
    ids=["busy-over-cap", "busy-exhausted", "unknown-code", "inconsistent"],
)
async def test_busy_and_other_waitable_503_skip_without_step_retries(error: Exception) -> None:
    store = _FakeStore(current=_served_at(loaded_ago=timedelta(minutes=30)))
    metadata = await _load(store, _raising_problem(error))
    assert metadata["skipped"] == "upstream_not_ready"
    assert metadata["transport_problem_code"] == error.code  # type: ignore[attr-defined]
    assert metadata["stale_alert"] is False


async def test_a_disabled_export_fails_without_retries_through_the_existing_terminal_path() -> None:
    async def _disabled(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise TransportExportDisabled("503", code="EXPORT_DISABLED", retry_after=3600.0)

    with pytest.raises(Failure) as excinfo:
        await _load(_FakeStore(), _disabled)
    assert excinfo.value.allow_retries is False
    metadata = {key: value.value for key, value in excinfo.value.metadata.items()}
    assert metadata["failure_kind"] == "transport_export_disabled"
    assert metadata["transport_problem_code"] == "EXPORT_DISABLED"
    assert "upstream_state" not in metadata  # 상류 수집 지연이 아니라 설정 문제다

"""ADR-122 — weather 예보 적재의 증분(``since``)·전량 재동기화 선택(Valkey 없이).

병합 자체의 정확성(증분 = 전량)은 ``tests/unit/test_weather_forecast_delta.py``가, 실제 Valkey의
교체 원자성(기준 세대 CAS·거부 기준 생략)은 ``tests/integration/test_valkey_weather_state.py``가
본다. 여기서는 job이 언제 무엇을 요청하고 어떤 cursor·세대로 교체하는지를 본다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import pytest
from kortravelmap.dto.weather_state import WeatherForecastGroupState, WeatherForecastState
from kortravelmap.infra.valkey_state import (
    GenerationMeta,
    StateItem,
    SwapResult,
    ValkeyStateStore,
)
from kortravelmap.providers.kor_travel_weather import WeatherExportContractError
from kortravelmap.providers.kor_travel_weather_state import (
    DATASET_FORECAST_EXTERNAL,
    DATASET_FORECAST_SHORT,
    DATASET_FORECAST_ULTRA_SHORT,
    forecast_membership_digest,
    weather_location_feature_id,
)
from kortravelmap.settings import KorTravelMapSettings
from pydantic import SecretStr

import kortravelmap.dagster.weather_state as weather_state
from kortravelmap.dagster.weather_state import (
    WEATHER_STATE_SPECS,
    WeatherStateJobSpec,
    fetch_weather_forecasts,
    forecast_sync_plan,
    load_weather_state,
    weather_lock_ttl_seconds,
)

TOKEN = "w" * 40
NOW = datetime.now(UTC).replace(microsecond=0)
W0 = NOW - timedelta(hours=3)
"""직전 적재가 받은 publication watermark(``next_since``)."""
W1 = NOW - timedelta(minutes=5)
"""이번 응답의 watermark."""


def _settings(**overrides: Any) -> KorTravelMapSettings:
    values: dict[str, Any] = {
        "kor_travel_weather_base_url": "http://127.0.0.1:14201/",
        "kor_travel_weather_service_token": SecretStr(TOKEN),
        "kor_travel_weather_page_size": 2,
    }
    values.update(overrides)
    return KorTravelMapSettings(**values)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(weather_state, "_WEATHER_RETRY_BASE_DELAY_SECONDS", 0.0)

    async def _record(_delay: float) -> None:
        return None

    monkeypatch.setattr(weather_state, "_page_retry_sleep", _record)


_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _install(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(recording), **kwargs)

    monkeypatch.setattr(weather_state.httpx, "AsyncClient", factory)
    return seen


def _page(items: list[dict[str, Any]], **meta: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "generated_at": NOW.isoformat(),
        "source_collected_at": (NOW - timedelta(minutes=10)).isoformat(),
        "source_status": "ok",
        "item_count": len(items),
        "snapshot_id": "snap-1",
        "next_cursor": None,
        "has_more": False,
        "next_since": W1.isoformat(),
    }
    values.update(meta)
    return {"items": items, "meta": values}


def _group(location_id: str, provider: str, published_at: datetime) -> dict[str, Any]:
    return {
        "location_id": location_id,
        "provider": provider,
        "forecast_style": "short",
        "known_at": published_at.isoformat(),
        "published_at": published_at.isoformat(),
        "target_at": [(NOW + timedelta(hours=6)).isoformat()],
        "metrics": {"TMP": [11.0]},
    }


def _stored(location_id: str, provider: str, published_at: datetime) -> StateItem:
    state = WeatherForecastState(
        feature_id=weather_location_feature_id(location_id),
        location_id=location_id,
        forecast_style="short",
        groups=[
            WeatherForecastGroupState(
                provider=provider,
                known_at=published_at,
                published_at=published_at,
                target_at=[NOW + timedelta(hours=9)],
                metrics={"TMP": [3.0]},
            )
        ],
    )
    return StateItem(id=state.feature_id, value=state.model_dump_json())


def _current(**overrides: Any) -> GenerationMeta:
    values: dict[str, Any] = {
        "dataset": "weather.forecast_short",
        "generation": "g-base",
        "count": 1,
        "geo_count": 0,
        "lookup_count": 0,
        "duplicates": 0,
        "source_collected_at": W0,
        "loaded_at": W0,
        "run_id": None,
        "guard_override": False,
        "source_status": "ok",
        "sync_mode": "full",
        "sync_cursor": W0,
        "full_synced_at": NOW - timedelta(hours=2),
        "row_duplicates": 0,
        "member_count": 1,
        "membership_verified": None,
        "clock_epoch": None,
    }
    values.update(overrides)
    return GenerationMeta(**values)


class _Store:
    def __init__(
        self,
        current: GenerationMeta | None,
        items: list[StateItem],
        members: dict[tuple[str, str], datetime] | None = None,
    ) -> None:
        self.current = current
        self.items = {item.id: item.value.encode() for item in items}
        if members is None:
            members = {}
            for item in items:
                try:
                    state = WeatherForecastState.model_validate_json(item.value)
                except ValueError:
                    continue
                for group in state.groups:
                    members[(state.location_id, group.provider)] = group.published_at
        self.members = members
        self.swapped: list[dict[str, Any]] = []
        self.read_generations: list[str] = []

    async def current_meta(self, dataset: str) -> GenerationMeta:
        from kortravelmap.infra.valkey_state import StateNotLoaded

        if self.current is None:
            raise StateNotLoaded(dataset)
        return self.current

    async def generation_members(
        self, _dataset: str, _generation: str
    ) -> dict[tuple[str, str], datetime]:
        return dict(self.members)

    async def generation_items(self, _dataset: str, generation: str) -> dict[str, bytes]:
        self.read_generations.append(generation)
        return dict(self.items)

    @asynccontextmanager
    async def load_lock(self, _dataset: str, *, ttl_seconds: int) -> AsyncIterator[bool]:
        yield True

    async def touch_checked(self, *_args: Any) -> bool:
        return True

    async def swap(self, dataset: str, items: list[StateItem], **kwargs: Any) -> SwapResult:
        self.swapped.append({"dataset": dataset, "items": items, **kwargs})
        meta = GenerationMeta(
            dataset=dataset,
            generation="g-new",
            count=len(items),
            geo_count=0,
            lookup_count=0,
            duplicates=0,
            source_collected_at=kwargs["source_collected_at"],
            loaded_at=kwargs["loaded_at"],
            run_id=kwargs["run_id"],
            guard_override=kwargs["allow_shrink"],
            source_status=kwargs["source_status"],
        )
        return SwapResult(meta=meta, previous_generation="g-base", baseline=None)

    async def retire_other_versions(self, _dataset: str) -> int:
        return 0


def _spec(dataset: Any = DATASET_FORECAST_SHORT) -> WeatherStateJobSpec:
    return next(spec for spec in WEATHER_STATE_SPECS if spec.dataset is dataset)


async def _run(
    store: _Store, *, settings: KorTravelMapSettings | None = None, **kwargs: Any
) -> dict[str, Any]:
    return await load_weather_state(
        _spec(),
        settings=settings or _settings(),
        run_id="run-d",
        allow_shrink=kwargs.pop("allow_shrink", False),
        store=cast(ValkeyStateStore, store),
        **kwargs,
    )


# -- 계획 -------------------------------------------------------------------------------


def test_plan_takes_a_delta_only_from_a_fresh_full_chain() -> None:
    def plan(current: GenerationMeta | None, **kwargs: Any) -> tuple[datetime | None, str]:
        result = forecast_sync_plan(
            current,
            now=NOW,
            full_resync_hours=kwargs.pop("hours", 24.0),
            allow_shrink=kwargs.pop("allow_shrink", False),
            full_resync=kwargs.pop("full_resync", False),
        )
        return result.since, result.reason

    assert plan(_current()) == (W0, "delta")
    assert plan(None) == (None, "not_loaded")
    assert plan(_current(sync_cursor=None)) == (None, "no_cursor")
    assert plan(_current(full_synced_at=None)) == (None, "no_cursor")
    assert plan(_current(row_duplicates=None)) == (None, "no_cursor")  # 옛 코드가 쓴 세대
    assert plan(_current(row_duplicates=2)) == (None, "base_row_duplicates")
    assert plan(_current(), hours=0) == (None, "delta_disabled")
    assert plan(_current(), allow_shrink=True) == (None, "allow_shrink")
    assert plan(_current(), full_resync=True) == (None, "requested")
    # 24시간 주기 — 같은 cron tick이 하루 뒤 다시 오면(몇 초 이르더라도) 전량이다.
    due = _current(full_synced_at=NOW - timedelta(hours=24) + timedelta(seconds=40))
    assert plan(due) == (None, "periodic")
    assert plan(_current(full_synced_at=NOW - timedelta(hours=23))) == (W0, "delta")
    # 미래의 전량 시각(시계 이상)은 믿지 않는다.
    assert plan(_current(full_synced_at=NOW + timedelta(hours=1))) == (None, "periodic")


# -- 적재 --------------------------------------------------------------------------------


async def test_first_load_is_a_full_pull_that_records_the_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install(
        monkeypatch, lambda _r: httpx.Response(200, json=_page([_group("a", "p", W0)]))
    )
    store = _Store(None, [])
    metadata = await _run(store)
    assert "since" not in seen[0].url.params
    (swap,) = store.swapped
    assert swap["apply_guard"] is True
    assert swap["require_base"] is None
    assert swap["sync_mode"] == "full"
    assert swap["sync_cursor"] == W1
    assert swap["row_duplicates"] == 0
    assert NOW - timedelta(minutes=5) < swap["full_synced_at"] <= datetime.now(UTC)
    assert metadata["sync_mode"] == "full"
    assert metadata["resync_reason"] == "not_loaded"
    assert metadata["next_since"] == W1.isoformat()


async def test_delta_asks_since_and_merges_into_the_generation_it_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    later = W0 + timedelta(minutes=30)
    seen = _install(
        monkeypatch,
        lambda _r: httpx.Response(200, json=_page([_group("b", "p", later)])),
    )
    base = _current()
    store = _Store(base, [_stored("a", "p", W0 - timedelta(hours=1))])
    metadata = await _run(store)
    assert len(seen) == 1
    assert datetime.fromisoformat(seen[0].url.params["since"]) == W0
    assert "if-none-match" not in seen[0].headers
    assert store.read_generations == ["g-base"]
    (swap,) = store.swapped
    assert swap["apply_guard"] is False  # 80% 거부 기준은 전량에만
    assert swap["require_base"] == "g-base"  # 읽은 세대가 아직 current일 때만 교체
    assert swap["sync_mode"] == "delta"
    assert swap["sync_cursor"] == W1
    assert swap["full_synced_at"] == base.full_synced_at  # 전량 시각은 이어진다
    assert swap["source_etag"] is None
    ids = sorted(item.id for item in swap["items"])
    assert ids == sorted([weather_location_feature_id("a"), weather_location_feature_id("b")])
    assert metadata["sync_mode"] == "delta"
    assert metadata["since"] == W0.isoformat()
    assert metadata["delta_rows"] == 1
    assert metadata["delta_added"] == 1
    assert metadata["carried"] == 1


async def test_empty_delta_still_advances_the_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, lambda _r: httpx.Response(200, json=_page([])))
    store = _Store(_current(), [_stored("a", "p", W0 - timedelta(hours=1))])
    metadata = await _run(store)
    (swap,) = store.swapped
    assert swap["sync_cursor"] == W1
    assert len(swap["items"]) == 1
    assert metadata["delta_rows"] == 0


async def test_periodic_resync_is_a_guarded_full_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(
        monkeypatch, lambda _r: httpx.Response(200, json=_page([_group("a", "p", W0)]))
    )
    store = _Store(
        _current(full_synced_at=NOW - timedelta(hours=25)), [_stored("a", "p", W0)]
    )
    metadata = await _run(store)
    assert "since" not in seen[0].url.params
    assert store.read_generations == []
    (swap,) = store.swapped
    assert swap["apply_guard"] is True
    assert swap["sync_mode"] == "full"
    assert metadata["resync_reason"] == "periodic"


def _since_then_full(
    delta: Callable[[httpx.Request], httpx.Response],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if "since" in request.url.params:
            return delta(request)
        return httpx.Response(200, json=_page([_group("a", "p", W1)]))

    return handler


@pytest.mark.parametrize(
    ("delta", "reason"),
    [
        # weather가 Map의 cursor를 모른다(DB 복원 등) — "아직 발급되지 않은 watermark" 422.
        (lambda _r: httpx.Response(422, json={"code": "EXPORT_CURSOR_INVALID"}), "cursor_rejected"),
        (
            lambda _r: httpx.Response(
                200, json=_page([], next_since=(W0 - timedelta(seconds=1)).isoformat())
            ),
            "cursor_regressed",
        ),
        (lambda _r: httpx.Response(200, json=_page([], next_since=None)), "no_next_since"),
        (
            lambda _r: httpx.Response(200, json=_page([_group("b", "p", W0)])),
            "delta_not_after_since",
        ),
        (
            lambda _r: httpx.Response(
                200, json=_page([_group("b", "p", W1), _group("b", "p", W1)])
            ),
            "delta_duplicates",
        ),
    ],
)
async def test_untrustworthy_delta_falls_back_to_a_full_pull_in_the_same_run(
    monkeypatch: pytest.MonkeyPatch,
    delta: Callable[[httpx.Request], httpx.Response],
    reason: str,
) -> None:
    seen = _install(monkeypatch, _since_then_full(delta))
    store = _Store(_current(), [_stored("a", "p", W0 - timedelta(hours=1))])
    metadata = await _run(store)
    assert ["since" in r.url.params for r in seen] == [True, False]
    (swap,) = store.swapped
    assert swap["sync_mode"] == "full"
    assert swap["apply_guard"] is True
    assert metadata["resync_reason"] == reason


async def test_base_generation_that_does_not_match_its_meta_forces_a_full_pull(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install(monkeypatch, _since_then_full(lambda _r: httpx.Response(200, json=_page([]))))
    store = _Store(_current(count=2), [_stored("a", "p", W0)])  # meta 2건, 세대 1건
    metadata = await _run(store)
    assert len(seen) == 2
    assert metadata["resync_reason"] == "base_count_mismatch"


async def test_unreadable_base_value_forces_a_full_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _since_then_full(lambda _r: httpx.Response(200, json=_page([]))))
    store = _Store(_current(), [StateItem(id="x", value="{not json")])
    metadata = await _run(store)
    assert metadata["resync_reason"] == "base_unreadable"


async def test_zero_resync_hours_turns_deltas_off(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(
        monkeypatch, lambda _r: httpx.Response(200, json=_page([_group("a", "p", W0)]))
    )
    store = _Store(_current(), [_stored("a", "p", W0)])
    metadata = await _run(store, settings=_settings(weather_forecast_full_resync_hours=0))
    assert "since" not in seen[0].url.params
    assert metadata["resync_reason"] == "delta_disabled"


async def test_full_resync_run_config_forces_a_full_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(
        monkeypatch, lambda _r: httpx.Response(200, json=_page([_group("a", "p", W0)]))
    )
    store = _Store(_current(), [_stored("a", "p", W0)])
    metadata = await _run(store, full_resync=True)
    assert "since" not in seen[0].url.params
    assert metadata["resync_reason"] == "requested"


async def test_pages_that_disagree_on_next_since_are_a_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        None: _page([_group("a", "p", W1)], has_more=True, next_cursor="c2"),
        "c2": _page([_group("b", "p", W1)], next_since=NOW.isoformat()),
    }
    _install(monkeypatch, lambda r: httpx.Response(200, json=pages[r.url.params.get("cursor")]))
    with pytest.raises(WeatherExportContractError, match="next_since"):
        await fetch_weather_forecasts(_settings(), "short", since=W0)


async def test_delta_request_carries_since_on_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        None: _page([_group("a", "p", W1)], has_more=True, next_cursor="c2"),
        "c2": _page([_group("b", "p", W1)]),
    }
    seen = _install(
        monkeypatch, lambda r: httpx.Response(200, json=pages[r.url.params.get("cursor")])
    )
    fetch = await fetch_weather_forecasts(_settings(), "short", since=W0)
    assert [datetime.fromisoformat(r.url.params["since"]) for r in seen] == [W0, W0]
    assert fetch.next_since == W1


def test_forecast_locks_expire_before_their_next_tick() -> None:
    # 전량 재동기화(odroid eMMC cold 단기 약 1,174초·외부 약 674초)가 run 상한 안에 들게 단기·외부
    # 상한을 올렸다. lock TTL(상한 + 취소 유예)은 다음 발화 전에 풀려야 한다.
    intervals = {
        DATASET_FORECAST_SHORT: 3 * 3_600,
        DATASET_FORECAST_EXTERNAL: 3 * 3_600,
        DATASET_FORECAST_ULTRA_SHORT: 3_600,
    }
    for dataset, interval in intervals.items():
        spec = _spec(dataset)
        assert weather_lock_ttl_seconds(spec) < interval
    assert _spec(DATASET_FORECAST_SHORT).max_runtime_seconds >= 3_000
    assert _spec(DATASET_FORECAST_EXTERNAL).max_runtime_seconds >= 2_400


async def test_delta_503_keeps_the_generation_and_cursor_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # weather는 새 since의 직전 snapshot이 없어 503이다. 전량이었다면 직전 전량 snapshot(이미 병합한
    # 것 이하)을 받았을 것이라 바꿀 것이 없다 — run은 실패하지 않는다(리뷰 M1).
    def unavailable(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503, json={"code": "EXPORT_NOT_READY"}, headers={"retry-after": "999"}
        )

    seen = _install(monkeypatch, unavailable)
    store = _Store(_current(), [_stored("a", "p", W0)])
    metadata = await _run(store)
    assert all("since" in r.url.params for r in seen)
    assert store.swapped == []
    assert metadata["unchanged"] == "delta_unavailable"
    assert metadata["generation"] == "g-base"


async def test_full_after_a_refused_delta_sends_no_etag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(
        monkeypatch,
        _since_then_full(lambda _r: httpx.Response(422, json={"code": "EXPORT_CURSOR_INVALID"})),
    )
    store = _Store(_current(source_etag='W/"old"'), [_stored("a", "p", W0)])
    await _run(store)
    assert "if-none-match" not in seen[1].headers
    assert store.swapped[0]["sync_mode"] == "full"

# -- ADR-122 개정: weather membership digest·clock epoch ---------------------------------

EPOCH = "pg:" + "a" * 32
OTHER_EPOCH = "pg:" + "b" * 32


def _digest_of(*rows: tuple[str, str, datetime]) -> str:
    return forecast_membership_digest({(loc, prov): at for loc, prov, at in rows})


async def test_full_records_membership_verification_and_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = _digest_of(("a", "p", W0))
    _install(monkeypatch, lambda _r: httpx.Response(200, json=_page(
        [_group("a", "p", W0)], membership_digest=digest, clock_epoch=EPOCH,
    )))
    store = _Store(None, [])
    metadata = await _run(store)
    (swap,) = store.swapped
    assert swap["members"] == {("a", "p"): W0}
    assert swap["membership_verified"] is True
    assert swap["clock_epoch"] == EPOCH
    assert metadata["membership_verified"] == "1"


async def test_full_with_unseen_manifest_rows_is_unverifiable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # omitted_expired를 내지 않는 weather가 미래 시각이 없는 (b, p)를 뺐다(stale 페이지)
    # — 재현할 수 없다.
    digest = _digest_of(("a", "p", W0), ("b", "p", W0))
    _install(monkeypatch, lambda _r: httpx.Response(200, json=_page(
        [_group("a", "p", W0)], membership_digest=digest, source_status="stale",
    )))
    store = _Store(None, [])
    await _run(store)
    assert store.swapped[0]["membership_verified"] is False


@pytest.mark.parametrize(
    "meta",
    [
        {"source_status": "ok"},  # 뺀 행이 없는데 다르다
        {"source_status": "stale", "omitted_expired": []},  # 뺀 행을 알렸는데도 다르다
    ],
)
async def test_full_mismatch_that_cannot_be_omissions_stays_unknown(
    monkeypatch: pytest.MonkeyPatch, meta: dict[str, Any]
) -> None:
    # 정의·계약 어긋남을 "검증 불가"로 두면 검사가 조용히 꺼진다 — 모름(None)으로 둔다(리뷰 M1).
    digest = _digest_of(("a", "p", W0), ("b", "p", W0))
    _install(monkeypatch, lambda _r: httpx.Response(200, json=_page(
        [_group("a", "p", W0)], membership_digest=digest, **meta,
    )))
    store = _Store(None, [])
    await _run(store)
    assert store.swapped[0]["membership_verified"] is None


async def test_unknown_digest_or_epoch_format_is_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, lambda _r: httpx.Response(200, json=_page(
        [_group("a", "p", W0)], membership_digest="blake3:zz", clock_epoch="mysql:1",
    )))
    store = _Store(None, [])
    await _run(store)
    (swap,) = store.swapped
    assert swap["membership_verified"] is None
    assert swap["clock_epoch"] is None


async def test_delta_whose_membership_matches_is_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    later = W0 + timedelta(minutes=30)
    old = W0 - timedelta(hours=1)
    digest = _digest_of(("a", "p", old), ("b", "p", later))
    _install(monkeypatch, lambda _r: httpx.Response(200, json=_page(
        [_group("b", "p", later)], membership_digest=digest, clock_epoch=EPOCH,
    )))
    store = _Store(
        _current(membership_verified=True, clock_epoch=EPOCH), [_stored("a", "p", old)]
    )
    metadata = await _run(store)
    (swap,) = store.swapped
    assert swap["sync_mode"] == "delta"
    assert swap["membership_verified"] is True
    assert swap["members"] == {("a", "p"): old, ("b", "p"): later}
    assert metadata["membership_verified"] == "1"


def _delta_then_full(
    delta_meta: dict[str, Any],
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if "since" in request.url.params:
            return httpx.Response(200, json=_page([], **delta_meta))
        return httpx.Response(200, json=_page([_group("a", "p", W1)], **delta_meta))

    return handler


async def test_membership_mismatch_on_a_verified_chain_is_a_full_resync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # weather manifest에서 (a, p)가 빠졌다(만료·비활성화) — 증분에는 흔적이 없다.
    gone = _digest_of(("z", "p", W1))
    seen = _install(monkeypatch, _delta_then_full({"membership_digest": gone}))
    store = _Store(_current(membership_verified=True), [_stored("a", "p", W0)])
    metadata = await _run(store)
    assert ["since" in r.url.params for r in seen] == [True, False]
    assert metadata["resync_reason"] == "membership_mismatch"
    assert store.swapped[0]["sync_mode"] == "full"


async def test_membership_mismatch_on_an_unknown_chain_is_a_full_resync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _install(monkeypatch, _delta_then_full({"membership_digest": _digest_of()}))
    store = _Store(_current(membership_verified=None), [_stored("a", "p", W0)])
    metadata = await _run(store)
    assert len(seen) == 2
    assert metadata["resync_reason"] == "membership_mismatch"


async def test_unverifiable_chain_keeps_taking_deltas(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _install(monkeypatch, _delta_then_full({"membership_digest": _digest_of()}))
    store = _Store(_current(membership_verified=False), [_stored("a", "p", W0)])
    metadata = await _run(store)
    assert len(seen) == 1
    assert metadata["sync_mode"] == "delta"
    assert store.swapped[0]["membership_verified"] is False


@pytest.mark.parametrize("stored", [OTHER_EPOCH, None])
async def test_changed_or_unknown_clock_epoch_is_a_full_resync(
    monkeypatch: pytest.MonkeyPatch, stored: str | None
) -> None:
    seen = _install(monkeypatch, _delta_then_full({"clock_epoch": EPOCH}))
    store = _Store(_current(clock_epoch=stored), [_stored("a", "p", W0)])
    metadata = await _run(store)
    assert len(seen) == 2
    assert metadata["resync_reason"] == "clock_epoch_changed"
    assert store.swapped[0]["clock_epoch"] == EPOCH


async def test_absent_membership_fields_keep_the_previous_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, lambda _r: httpx.Response(200, json=_page([])))
    store = _Store(_current(clock_epoch=EPOCH, membership_verified=True), [_stored("a", "p", W0)])
    metadata = await _run(store)
    (swap,) = store.swapped
    assert swap["sync_mode"] == "delta"
    assert swap["membership_verified"] is None
    assert swap["clock_epoch"] == EPOCH  # 응답에 없으면 저장된 epoch를 잇는다
    assert metadata["membership_verified"] == ""


async def test_base_members_that_do_not_match_meta_force_a_full_pull(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _delta_then_full({}))
    store = _Store(_current(member_count=3), [_stored("a", "p", W0)])
    metadata = await _run(store)
    assert metadata["resync_reason"] == "base_count_mismatch"


def test_plan_needs_a_membership_ledger() -> None:
    plan = forecast_sync_plan(
        _current(member_count=None), now=NOW, full_resync_hours=24.0,
        allow_shrink=False, full_resync=False,
    )
    assert (plan.since, plan.reason) == (None, "no_cursor")


def _member(location_id: str, provider: str, at: datetime) -> dict[str, Any]:
    return {"location_id": location_id, "provider": provider, "published_at": at.isoformat()}


async def test_full_counts_omitted_expired_as_value_less_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    digest = _digest_of(("a", "p", W0), ("b", "p", W0))
    pages = {
        None: _page([_group("a", "p", W0)], has_more=True, next_cursor="c2",
                    membership_digest=digest, omitted_expired=[]),
        "c2": _page([], membership_digest=digest, omitted_expired=[_member("b", "p", W0)]),
    }
    _install(monkeypatch, lambda r: httpx.Response(200, json=pages[r.url.params.get("cursor")]))
    store = _Store(None, [])
    await _run(store)
    (swap,) = store.swapped
    assert swap["members"] == {("a", "p"): W0, ("b", "p"): W0}
    assert swap["membership_verified"] is True
    assert len(swap["items"]) == 1


async def test_delta_omitted_expired_drops_the_stale_group(monkeypatch: pytest.MonkeyPatch) -> None:
    later = W0 + timedelta(minutes=30)
    digest = _digest_of(("a", "p", later))
    _install(monkeypatch, lambda _r: httpx.Response(200, json=_page(
        [], membership_digest=digest, omitted_expired=[_member("a", "p", later)],
    )))
    store = _Store(_current(membership_verified=True), [_stored("a", "p", W0 - timedelta(hours=1))])
    metadata = await _run(store)
    (swap,) = store.swapped
    assert swap["sync_mode"] == "delta"
    assert swap["items"] == []
    assert swap["members"] == {("a", "p"): later}
    assert swap["membership_verified"] is True
    assert metadata["expired_groups"] == 1


async def test_pages_that_disagree_on_omitted_expired_presence_are_a_contract_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        None: _page([_group("a", "p", W1)], has_more=True, next_cursor="c2", omitted_expired=[]),
        "c2": _page([_group("b", "p", W1)]),
    }
    _install(monkeypatch, lambda r: httpx.Response(200, json=pages[r.url.params.get("cursor")]))
    with pytest.raises(WeatherExportContractError, match="omitted_expired"):
        await fetch_weather_forecasts(_settings(), "short", since=W0)

async def test_forecast_pages_use_the_forecast_page_size(monkeypatch: pytest.MonkeyPatch) -> None:
    # 2026-11-11 운영: 단기 전량은 위치 약 1,450곳이 limit 2,000 페이지 하나에 들어, 그 요청 하나가
    # odroid eMMC에서 artifact 전부(약 1,174초)를 읽다가 read timeout(300초)에 끊겼다. 예보는 작은
    # 페이지로 나눠 요청마다 timeout 안에 들게 한다.
    seen = _install(monkeypatch, lambda _r: httpx.Response(200, json=_page([])))
    await fetch_weather_forecasts(
        _settings(kor_travel_weather_page_size=2_000), "short", since=W0
    )
    await fetch_weather_forecasts(
        _settings(kor_travel_weather_forecast_page_size=50), "short"
    )
    assert seen[0].url.params["limit"] == "200"
    assert seen[1].url.params["limit"] == "50"


def test_ultra_short_ceiling_fits_a_contended_delta() -> None:
    # 2026-11-11 운영: 초단기 증분이 weather 경합(artifact turnstile) 아래 580초,
    # 한 번은 600초 상한에서 잘렸다(506901ae). 매시 발화 간격 안에서 lock TTL이 풀리는 한 늘린다.
    spec = _spec(DATASET_FORECAST_ULTRA_SHORT)
    assert spec.max_runtime_seconds >= 1_800
    assert weather_lock_ttl_seconds(spec) < 3_600
"""ADR-114 1단계 — 실제 Valkey(일회용 컨테이너)로 세대 교체·거부·GEO·신선도·REST·적재 job을 잰다.

키 설계·교체 순서의 정본은 ADR-114 "구현 설계 — 1단계" D2~D6이다. 이 파일은 그 규약의 **효과**를
재는 자리다 — 교체 전 읽기는 옛 세대를 본다, 포인터가 움직였거나 새 세대가 덜 써졌으면 교체하지
않는다, 거부된 집합은 포인터를 건드리지 않는다, 옛 세대는 grace 뒤 사라진다.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from kortravelmap.infra.valkey_state import (
    STATE_KEY_NAMESPACE,
    ShrinkGuard,
    StateGenerationExpired,
    StateItem,
    StateNotLoaded,
    StateStoreOutOfMemory,
    StateStoreUnavailable,
    StateSwapConflict,
    StateSwapRefused,
    ValkeyStateStore,
    make_valkey_client,
    state_key,
)
from kortravelmap.providers.kor_travel_transport import (
    TransportFuelPrice,
    TransportFuelStation,
    TransportHighwayIncident,
    TransportRestArea,
    TransportRestAreaFuelPrice,
)
from kortravelmap.providers.kor_travel_transport_state import (
    DATASET_FUEL_STATIONS,
    DATASET_HIGHWAY_INCIDENTS,
    DATASET_REST_AREA_FUEL_PRICES,
    DATASET_REST_AREAS,
    fuel_station_state,
    highway_incident_state,
    rest_area_fuel_price_state,
    rest_area_state,
    to_state_item,
)
from kortravelmap.settings import KorTravelMapSettings
from tests.integration._valkey import valkey_container

pytestmark = pytest.mark.integration

LENIENT = ShrinkGuard(min_ratio=0.01, baseline_min=1_000_000)
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def valkey_url() -> Iterator[str]:
    with valkey_container() as url:
        yield url


def _settings(url: str) -> KorTravelMapSettings:
    return KorTravelMapSettings.model_construct(
        valkey_url=SecretStr(url),
        valkey_connect_timeout_seconds=1.0,
        valkey_socket_timeout_seconds=2.0,
    )


@pytest.fixture
async def store(valkey_url: str) -> AsyncIterator[ValkeyStateStore]:
    client = make_valkey_client(_settings(valkey_url))
    await client.flushdb()
    await client.config_set("maxmemory", "64mb")
    active = ValkeyStateStore(client, build_ttl_seconds=120, retire_grace_seconds=60)
    try:
        yield active
    finally:
        await client.aclose()


def _items(count: int, *, prefix: str = "f_test_", lon: float = 127.0) -> list[StateItem]:
    return [
        StateItem(
            id=f"{prefix}{i:05d}",
            value=json.dumps({"n": i}),
            coord=(lon + i * 0.001, 37.5),
        )
        for i in range(count)
    ]


async def _swap(
    store: ValkeyStateStore,
    dataset: str,
    items: list[StateItem],
    *,
    guard: ShrinkGuard = LENIENT,
    allow_shrink: bool = False,
) -> str:
    result = await store.swap(
        dataset,
        items,
        guard=guard,
        source_collected_at=NOW - timedelta(minutes=5),
        loaded_at=NOW,
        allow_shrink=allow_shrink,
    )
    return result.meta.generation


async def _ttl(store: ValkeyStateStore, key: str) -> int:
    return int(await store.client.ttl(key))


def _wrap_flip(
    store: ValkeyStateStore,
    before: Callable[[], Awaitable[None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = store._flip

    async def _patched(*args: Any, **kwargs: Any) -> None:
        await before()
        await original(*args, **kwargs)

    monkeypatch.setattr(store, "_flip", _patched)


# -- 세대 교체 ------------------------------------------------------------------


async def test_swap_publishes_a_complete_generation(store: ValkeyStateStore) -> None:
    with pytest.raises(StateNotLoaded):
        await store.current_meta("t.basic")
    generation = await _swap(store, "t.basic", _items(3))
    meta = await store.current_meta("t.basic")
    assert meta.generation == generation
    assert (meta.count, meta.geo_count, meta.duplicates) == (3, 3, 0)
    assert meta.source_collected_at == NOW - timedelta(minutes=5)
    ids, more = await store.page_ids("t.basic", generation, after=None, limit=2)
    assert ids == ["f_test_00000", "f_test_00001"]
    assert more is True
    ids, more = await store.page_ids("t.basic", generation, after=ids[-1], limit=2)
    assert (ids, more) == (["f_test_00002"], False)
    values = await store.get_values("t.basic", generation, ["f_test_00001", "missing"])
    assert values == [json.dumps({"n": 1}).encode(), None]
    # 지금 세대는 만료가 없다.
    for name in ("meta", "items", "ids", "geo"):
        assert await _ttl(store, state_key("t.basic", generation, name)) == -1
    assert await _ttl(store, state_key("t.basic", "current")) == -1


async def test_readers_see_the_old_generation_until_the_flip(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = await _swap(store, "t.atomic", _items(2))
    written = asyncio.Event()
    release = asyncio.Event()

    async def _pause() -> None:
        written.set()
        await release.wait()

    _wrap_flip(store, _pause, monkeypatch)
    task = asyncio.create_task(_swap(store, "t.atomic", _items(5, prefix="f_new_")))
    await written.wait()
    # 새 세대 키는 다 써졌지만 포인터는 그대로 — 읽는 쪽은 옛 세대 전체만 본다.
    meta = await store.current_meta("t.atomic")
    assert meta.generation == old
    assert meta.count == 2
    assert await store.page_ids("t.atomic", old, after=None, limit=10) == (
        ["f_test_00000", "f_test_00001"],
        False,
    )
    release.set()
    new = await task
    meta = await store.current_meta("t.atomic")
    assert (meta.generation, meta.count) == (new, 5)
    # 옛 세대는 grace TTL을 받고 previous로 남는다.
    assert 0 < await _ttl(store, state_key("t.atomic", old, "items")) <= 60
    assert await store.client.get(state_key("t.atomic", "previous")) == old.encode()


async def test_flip_refuses_when_another_swap_moved_the_pointer(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = await _swap(store, "t.cas", _items(2))

    async def _race() -> None:
        await store.client.set(state_key("t.cas", "current"), "someone-else")

    _wrap_flip(store, _race, monkeypatch)
    with pytest.raises(StateSwapConflict, match="동시 교체"):
        await _swap(store, "t.cas", _items(3))
    assert await store.client.get(state_key("t.cas", "current")) == b"someone-else"
    # 교체하지 못한 세대는 지웠다(지금 세대가 아님을 확인한 뒤).
    keys = [k async for k in store.client.scan_iter(match=f"{STATE_KEY_NAMESPACE}:*t.cas:2*")]
    assert keys
    assert all(first.encode() in key for key in keys)


async def test_flip_refuses_a_partially_written_generation(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = await _swap(store, "t.partial", _items(2))

    async def _lose_one() -> None:
        keys = [k async for k in store.client.scan_iter(match="*t.partial:*:items")]
        newest = max(k for k in keys if old.encode() not in k)
        await store.client.hdel(newest, "f_test_00001")

    _wrap_flip(store, _lose_one, monkeypatch)
    with pytest.raises(StateSwapConflict, match="items"):
        await _swap(store, "t.partial", _items(3))
    assert (await store.current_meta("t.partial")).generation == old


async def test_flip_refuses_an_unwritten_geo_index(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build TTL이 먼저 지난 키(여기서는 geo)를 가리키는 세대로 바꾸지 않는다."""
    old = await _swap(store, "t.geo_lost", _items(2))

    async def _expire_geo() -> None:
        keys = [k async for k in store.client.scan_iter(match="*t.geo_lost:*:geo")]
        await store.client.delete(*[k for k in keys if old.encode() not in k])

    _wrap_flip(store, _expire_geo, monkeypatch)
    with pytest.raises(StateSwapConflict, match="geo"):
        await _swap(store, "t.geo_lost", _items(3))
    assert (await store.current_meta("t.geo_lost")).generation == old


async def test_crashed_build_leaves_only_expiring_keys(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _crash(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("적재 프로세스가 교체 직전에 죽었다")

    async def _no_cleanup(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(store, "_flip", _crash)
    monkeypatch.setattr(store, "_discard_unless_current", _no_cleanup)
    with pytest.raises(RuntimeError):
        await _swap(store, "t.crash", _items(3))
    keys = [k async for k in store.client.scan_iter(match="*t.crash:*")]
    assert keys, "쓰던 키가 있어야 한다"
    for key in keys:
        ttl = await _ttl(store, key.decode())
        assert 0 < ttl <= 120, key
    with pytest.raises(StateNotLoaded):
        await store.current_meta("t.crash")


async def test_lost_flip_reply_does_not_delete_the_now_current_generation(
    store: ValkeyStateStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """교체 스크립트는 돌았는데 응답만 잃었다.

    정리가 새 지금 세대를 지우면 포인터가 허공을 가리킨다.
    """
    original = store._flip

    async def _flip_then_lose_reply(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        raise StateStoreUnavailable("응답을 읽기 전에 연결이 끊겼다")

    monkeypatch.setattr(store, "_flip", _flip_then_lose_reply)
    with pytest.raises(StateStoreUnavailable):
        await _swap(store, "t.lost_reply", _items(3))
    meta = await store.current_meta("t.lost_reply")
    assert meta.count == 3
    values = await store.get_values("t.lost_reply", meta.generation, ["f_test_00002"])
    assert values == [b'{"n": 2}']


async def test_duplicate_ids_keep_the_first_row(store: ValkeyStateStore) -> None:
    items = [*_items(2), StateItem(id="f_test_00000", value='"late"')]
    generation = await _swap(store, "t.dup", items)
    meta = await store.current_meta("t.dup")
    assert (meta.count, meta.duplicates) == (2, 1)
    assert (await store.get_values("t.dup", generation, ["f_test_00000"]))[0] == b'{"n": 0}'


# -- 비정상 집합 거부(D4) --------------------------------------------------------


async def test_krex_empty_response_does_not_replace_active_incidents(
    store: ValkeyStateStore,
) -> None:
    guard = DATASET_HIGHWAY_INCIDENTS.guard
    first = await _swap(store, "t.incidents", _items(106), guard=guard)
    with pytest.raises(StateSwapRefused) as excinfo:
        await _swap(store, "t.incidents", [], guard=guard)
    assert excinfo.value.failure_kind == "state_swap_refused"
    assert (excinfo.value.baseline, excinfo.value.new_count) == (106, 0)
    assert (await store.current_meta("t.incidents")).generation == first
    # 거부된 시도는 아무 키도 남기지 않는다.
    keys = [k async for k in store.client.scan_iter(match="*t.incidents:*")]
    assert all(first.encode() in k or b":current" in k or b"recent" in k for k in keys)


async def test_gradual_decline_is_refused_against_the_recent_maximum(
    store: ValkeyStateStore,
) -> None:
    guard = DATASET_HIGHWAY_INCIDENTS.guard
    await _swap(store, "t.decline", _items(106), guard=guard)
    second = await _swap(store, "t.decline", _items(27), guard=guard)
    with pytest.raises(StateSwapRefused):
        await _swap(store, "t.decline", _items(7), guard=guard)
    assert (await store.current_meta("t.decline")).generation == second
    assert await store.recent_counts("t.decline") == [27, 106]


async def test_operator_override_publishes_an_empty_generation(store: ValkeyStateStore) -> None:
    guard = DATASET_HIGHWAY_INCIDENTS.guard
    await _swap(store, "t.override", _items(40), guard=guard)
    generation = await _swap(store, "t.override", [], guard=guard, allow_shrink=True)
    meta = await store.current_meta("t.override")
    assert (meta.generation, meta.count, meta.guard_override) == (generation, 0, True)
    # 0건 세대: meta만 있고 읽기는 빈 결과다.
    assert await store.page_ids("t.override", generation, after=None, limit=5) == ([], False)
    # 한 번의 override로 충분하다 — 다음 정상 교체가 옛 최대(40)에 다시 막히지 않는다.
    await _swap(store, "t.override", [], guard=guard)
    assert await store.recent_counts("t.override") == [0, 0]
    assert await store.nearby(
        "t.override", generation, lon=127.0, lat=37.5, radius_m=1000, count=5
    ) == []


async def test_corrupt_pointer_is_not_treated_as_a_first_load(store: ValkeyStateStore) -> None:
    await store.client.set(state_key("t.corrupt", "current"), "20260101T000000Z-deadbeef")
    with pytest.raises(StateStoreUnavailable, match="없는 세대"):
        await _swap(store, "t.corrupt", _items(1))


# -- GEO ------------------------------------------------------------------------


async def test_nearby_is_sorted_by_distance_and_bounded_by_radius(
    store: ValkeyStateStore,
) -> None:
    items = [
        StateItem(id="far", value="0", coord=(127.10, 37.5)),
        StateItem(id="near", value="0", coord=(127.001, 37.5)),
        StateItem(id="mid", value="0", coord=(127.02, 37.5)),
        StateItem(id="nogeo", value="0", coord=None),
        StateItem(id="badgeo", value="0", coord=(127.0, 89.9)),
    ]
    generation = await _swap(store, "t.geo", items)
    assert (await store.current_meta("t.geo")).geo_count == 3
    hits = await store.nearby("t.geo", generation, lon=127.0, lat=37.5, radius_m=5_000, count=10)
    assert [h[0] for h in hits] == ["near", "mid"]
    assert hits[0][1] < hits[1][1] < 5_000


async def test_bbox_search_box_covers_all_four_corners(store: ValkeyStateStore) -> None:
    from kortravelmap.api.routers.service_transport import bbox_search_box

    min_lon, min_lat, max_lon, max_lat = 125.0, 33.0, 130.0, 38.6
    eps = 1e-4
    corners = {
        "sw": (min_lon + eps, min_lat + eps),
        "se": (max_lon - eps, min_lat + eps),
        "nw": (min_lon + eps, max_lat - eps),
        "ne": (max_lon - eps, max_lat - eps),
        "center": ((min_lon + max_lon) / 2, (min_lat + max_lat) / 2),
    }
    items = [StateItem(id=name, value="0", coord=coord) for name, coord in corners.items()]
    generation = await _swap(store, "t.box", items)
    center_lon, center_lat, width, height = bbox_search_box(min_lon, min_lat, max_lon, max_lat)
    found = await store.within_box(
        "t.box",
        generation,
        center_lon=center_lon,
        center_lat=center_lat,
        width_m=width,
        height_m=height,
        count=10,
    )
    assert set(found) == set(corners)
    assert found[0] == "center"


# -- 순회·만료 ---------------------------------------------------------------------


async def test_cursor_generation_must_be_current_or_previous(store: ValkeyStateStore) -> None:
    first = await _swap(store, "t.cursor", _items(3))
    assert (await store.readable_meta("t.cursor", first)).generation == first
    second = await _swap(store, "t.cursor", _items(4))
    # 교체 뒤에도 옛 세대(previous)는 grace 동안 읽힌다.
    assert (await store.readable_meta("t.cursor", first)).generation == first
    ids, _ = await store.page_ids("t.cursor", first, after="f_test_00000", limit=10)
    assert ids == ["f_test_00001", "f_test_00002"]
    third = await _swap(store, "t.cursor", _items(5))
    with pytest.raises(StateGenerationExpired):
        await store.readable_meta("t.cursor", first)  # current도 previous도 아니다
    assert (await store.readable_meta("t.cursor", second)).generation == second
    await store.client.delete(state_key("t.cursor", second, "meta"))
    with pytest.raises(StateGenerationExpired):
        await store.readable_meta("t.cursor", second)  # grace가 지나 사라졌다
    with pytest.raises(StateGenerationExpired):
        await store.readable_meta("t.cursor", "bad:gen")
    assert (await store.current_meta("t.cursor")).generation == third


async def test_load_lock_admits_one_loader(store: ValkeyStateStore) -> None:
    async with store.load_lock("t.lock") as first:
        assert first is True
        async with store.load_lock("t.lock") as second:
            assert second is False
    async with store.load_lock("t.lock") as again:
        assert again is True


async def test_other_schema_versions_are_retired(store: ValkeyStateStore) -> None:
    await store.client.set("ktm:state:v0:t.version:current", "old")
    await store.client.set("ktm:state:v0:t.version:20250101T000000Z-aa:items", "old")
    await store.client.set("ktm:state:v0:t.other:current", "old-other")
    await store.client.set("ktm:state:v2:t.version:current", "newer")
    await store.client.set("unrelated:key", "keep")
    await _swap(store, "t.version", _items(1))
    assert await store.retire_other_versions("t.version") == 2
    assert 0 < await _ttl(store, "ktm:state:v0:t.version:current") <= 60
    assert 0 < await _ttl(store, "ktm:state:v0:t.version:20250101T000000Z-aa:items") <= 60
    # 다른 데이터셋의 옛 키는 그 데이터셋이 새 버전으로 교체될 때까지 둔다.
    assert await _ttl(store, "ktm:state:v0:t.other:current") == -1
    assert await _ttl(store, "unrelated:key") == -1
    # 더 새 버전은 건드리지 않는다(롤링·롤백 중 서로 만료시키지 않게).
    assert await _ttl(store, "ktm:state:v2:t.version:current") == -1
    assert await _ttl(store, state_key("t.version", "current")) == -1


# -- 실패 분류 ----------------------------------------------------------------------


async def test_out_of_memory_is_terminal_and_keeps_the_pointer(store: ValkeyStateStore) -> None:
    first = await _swap(store, "t.oom", _items(2))
    await store.client.config_set("maxmemory", "1")
    try:
        with pytest.raises(StateStoreOutOfMemory) as excinfo:
            await _swap(store, "t.oom", _items(50))
        assert excinfo.value.retryable is False
    finally:
        await store.client.config_set("maxmemory", "64mb")
    assert (await store.current_meta("t.oom")).generation == first


async def test_unreachable_valkey_fails_fast_as_unavailable() -> None:
    client = make_valkey_client(_settings("redis://:x@127.0.0.1:1/0"))
    down = ValkeyStateStore(client)
    started = time.monotonic()
    try:
        with pytest.raises(StateStoreUnavailable) as excinfo:
            await down.current_meta("transport.airports")
    finally:
        await client.aclose()
    assert time.monotonic() - started < 3.0
    assert excinfo.value.retryable is True
    assert "x@" not in str(excinfo.value)


# -- REST(D6) -----------------------------------------------------------------------


def _incident(i: int, *, lon: float = 127.0, lat: float = 37.5) -> TransportHighwayIncident:
    return TransportHighwayIncident(
        occurred_date="2026.10.23",
        occurred_time=f"09:{i // 60:02d}:{i % 60:02d}",
        incident_type="작업",
        incident_type_code="03",
        direction="하행",
        message=f"작업 {i}",
        point_name=f"지점 {i}",
        route_no="0010",
        route_name="경부선",
        process_status="진행",
        process_status_code="1",
        latitude=lat,
        longitude=lon + i * 0.01,
        congestion_length=None,
        series_no=i,
        raw={"seriesNM": str(i)},
    )


def _station(i: int) -> TransportFuelStation:
    when = NOW - timedelta(hours=1)
    return TransportFuelStation(
        uni_id=f"A{i:07d}",
        name=f"주유소 {i}",
        brand="SKE",
        brand_name="SK에너지",
        address_road=f"서울 어딘가 {i}",
        address_jibun=None,
        lon=127.0 + i * 0.001,
        lat=37.5,
        tel="02-000-0000",
        lpg_yn=None,
        is_self=True,
        is_24h=None,
        has_carwash=None,
        has_maintenance=None,
        has_cvs=None,
        last_seen_at=when,
        prices=(
            TransportFuelPrice(
                product_code="B027",
                price=None if i % 2 else Decimal("1689"),
                provider_updated_at=when,
                observed_at=when,
                collected_at=when,
                raw={},
            ),
        ),
        raw={},
    )


@pytest.fixture
async def api(store: ValkeyStateStore) -> AsyncIterator[httpx.AsyncClient]:
    from kortravelmap.api.app import create_app
    from kortravelmap.api.settings import ApiSettings
    from kortravelmap.api.transport_state_service import get_state_store

    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    app.dependency_overrides[get_state_store] = lambda: store
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://map.test"
    ) as client:
        yield client


async def test_rest_lists_pages_and_finds_nearby_incidents(
    store: ValkeyStateStore, api: httpx.AsyncClient
) -> None:
    states = [highway_incident_state(_incident(i)) for i in range(5)]
    await store.swap(
        DATASET_HIGHWAY_INCIDENTS.name,
        [to_state_item(s) for s in states],
        guard=LENIENT,
        source_collected_at=datetime.now(UTC) - timedelta(minutes=3),
        loaded_at=datetime.now(UTC),
    )
    first = await api.get("/v1/service/transport/highway-incidents", params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["data"]["items"]) == 2
    assert body["data"]["freshness"]["stale"] is False
    assert body["data"]["freshness"]["item_count"] == 5
    cursor = body["meta"]["page"]["next_cursor"]
    assert cursor
    seen = [item["feature_id"] for item in body["data"]["items"]]
    while cursor:
        page = await api.get(
            "/v1/service/transport/highway-incidents", params={"limit": 2, "cursor": cursor}
        )
        assert page.status_code == 200, page.text
        seen += [item["feature_id"] for item in page.json()["data"]["items"]]
        cursor = page.json()["meta"]["page"]["next_cursor"]
    assert sorted(seen) == sorted(s.feature_id for s in states)

    near = await api.get(
        "/v1/service/transport/highway-incidents",
        params={"lon": 127.0, "lat": 37.5, "radius_m": 1_500, "limit": 1},
    )
    near_body = near.json()["data"]
    assert [i["feature_id"] for i in near_body["items"]] == [states[0].feature_id]
    assert near_body["items"][0]["distance_m"] == pytest.approx(0.0, abs=1.0)
    assert near_body["truncated"] is True

    box = await api.get(
        "/v1/service/transport/highway-incidents",
        params={"min_lon": 127.005, "min_lat": 37.4, "max_lon": 127.025, "max_lat": 37.6},
    )
    assert {i["feature_id"] for i in box.json()["data"]["items"]} == {
        states[1].feature_id,
        states[2].feature_id,
    }

    detail = await api.get(f"/v1/service/transport/highway-incidents/{states[3].feature_id}")
    assert detail.json()["data"]["item"]["title"] == states[3].title
    missing = await api.get("/v1/service/transport/highway-incidents/f_global_n_0000")
    assert missing.status_code == 404


async def test_rest_cursor_on_an_expired_generation_is_409(
    store: ValkeyStateStore, api: httpx.AsyncClient
) -> None:
    items = [to_state_item(highway_incident_state(_incident(i))) for i in range(3)]

    async def _publish(batch: list[StateItem]) -> None:
        await store.swap(
            DATASET_HIGHWAY_INCIDENTS.name,
            batch,
            guard=LENIENT,
            source_collected_at=None,
            loaded_at=datetime.now(UTC),
        )

    await _publish(items)
    first = await api.get("/v1/service/transport/highway-incidents", params={"limit": 1})
    cursor = first.json()["meta"]["page"]["next_cursor"]
    await _publish(items[:2])
    # 한 번 교체된 뒤에는(previous) 이어서 읽힌다.
    resumed = await api.get(
        "/v1/service/transport/highway-incidents", params={"limit": 1, "cursor": cursor}
    )
    assert resumed.status_code == 200, resumed.text
    await _publish(items[:2])
    gone = await api.get(
        "/v1/service/transport/highway-incidents", params={"limit": 1, "cursor": cursor}
    )
    assert gone.status_code == 409
    assert gone.json()["code"] == "TRANSPORT_STATE_GENERATION_EXPIRED"


async def test_rest_marks_stale_sets_and_reports_not_loaded(
    store: ValkeyStateStore, api: httpx.AsyncClient
) -> None:
    not_loaded = await api.get("/v1/service/transport/airports")
    assert not_loaded.status_code == 503
    assert not_loaded.json()["code"] == "TRANSPORT_STATE_NOT_LOADED"
    await store.swap(
        DATASET_HIGHWAY_INCIDENTS.name,
        [to_state_item(highway_incident_state(_incident(1)))],
        guard=LENIENT,
        source_collected_at=datetime.now(UTC) - timedelta(hours=2),
        loaded_at=datetime.now(UTC),
    )
    stale = await api.get("/v1/service/transport/highway-incidents")
    freshness = stale.json()["data"]["freshness"]
    assert freshness["stale"] is True
    assert freshness["max_age_seconds"] == 1_800
    assert freshness["age_seconds"] >= 7_000
    status_body = (await api.get("/v1/service/transport/status")).json()["data"]
    loaded = {d["dataset"]: d["loaded"] for d in status_body["datasets"]}
    assert loaded[DATASET_HIGHWAY_INCIDENTS.name] is True
    assert loaded[DATASET_FUEL_STATIONS.name] is False


async def test_rest_attaches_rest_area_fuel_prices(
    store: ValkeyStateStore, api: httpx.AsyncClient
) -> None:
    area = rest_area_state(
        TransportRestArea(
            natural_key="행담도휴게소::서해안고속도로::목포방향",
            name="행담도휴게소",
            route_name="서해안고속도로",
            direction="목포방향",
            lon=126.8,
            lat=36.9,
            phone_number=None,
            has_gas_station=True,
            has_lpg_station=False,
            has_ev_charger=True,
            raw={},
        )
    )
    await store.swap(
        DATASET_REST_AREAS.name,
        [to_state_item(area)],
        guard=LENIENT,
        source_collected_at=None,
        loaded_at=datetime.now(UTC),
    )
    no_prices = (await api.get("/v1/service/transport/rest-areas")).json()["data"]
    assert no_prices["items"][0]["fuel_prices"] is None
    assert no_prices["fuel_price_freshness"] is None
    price = rest_area_fuel_price_state(
        TransportRestAreaFuelPrice(
            service_area_code="A00001",
            route_name="서해안고속도로",
            direction="목포방향",
            oil_company="SK",
            service_area_name="행담도휴게소",
            phone_number=None,
            address=None,
            gasoline_price=1700,
            diesel_price=1600,
            lpg_price=None,
            observed_at=datetime.now(UTC),
            raw={},
        )
    )
    await store.swap(
        DATASET_REST_AREA_FUEL_PRICES.name,
        [to_state_item(price, lookup_keys=(price.match_key or "",))],
        guard=LENIENT,
        source_collected_at=None,
        loaded_at=datetime.now(UTC),
    )
    body = (await api.get(f"/v1/service/transport/rest-areas/{area.feature_id}")).json()["data"]
    assert body["item"]["fuel_prices"]["gasoline_price"] == 1700
    assert body["fuel_price_freshness"]["dataset"] == DATASET_REST_AREA_FUEL_PRICES.name


async def test_rest_price_history_falls_back_without_losing_current_prices(
    store: ValkeyStateStore, api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import service_transport
    from kortravelmap.api.transport_state_service import fetch_price_history

    station = fuel_station_state(_station(0))
    await store.swap(
        DATASET_FUEL_STATIONS.name,
        [to_state_item(station)],
        guard=LENIENT,
        source_collected_at=None,
        loaded_at=datetime.now(UTC),
    )
    url = f"/v1/service/transport/fuel-stations/{station.feature_id}/price-history"
    disabled = (await api.get(url)).json()["data"]
    assert disabled["history"] == {
        "status": "unavailable",
        "reason": "disabled",
        "generated_at": None,
        "source_collected_at": None,
        "source_status": None,
        "has_more": False,
        "next_cursor": None,
        "truncated": False,
        "items": [],
    }
    assert disabled["current_prices"][0]["price"] == 1689.0

    requests: list[httpx.Request] = []

    def _transport_404(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404, json={"detail": "Not Found"})

    enabled = KorTravelMapSettings.model_construct(
        transport_price_history_enabled=True,
        transport_price_history_timeout_seconds=2.0,
        kor_travel_transport_base_url="http://transport.test",
        kor_travel_transport_service_token=SecretStr("t" * 40),
        kor_travel_transport_connect_timeout_seconds=1.0,
    )

    async def _fetch(_settings: Any, station_key: str, **kwargs: Any) -> Any:
        return await fetch_price_history(
            enabled, station_key, transport=httpx.MockTransport(_transport_404), **kwargs
        )

    monkeypatch.setattr(service_transport, "fetch_price_history", _fetch)
    old_transport = (await api.get(url, params={"product_code": "B027"})).json()["data"]
    assert old_transport["history"]["reason"] == "upstream_not_found"
    assert old_transport["current_prices"]
    assert requests[0].url.path == (
        f"/v1/service/exports/fuel-stations/{station.natural_key}/price-history"
    )
    assert requests[0].url.params["product"] == "B027"
    assert "product_code" not in requests[0].url.params
    assert requests[0].headers["X-Kor-Travel-Transport-Service-Token"] == "t" * 40


async def test_rest_valkey_down_is_503_only_for_this_surface() -> None:
    from kortravelmap.api.app import create_app
    from kortravelmap.api.settings import ApiSettings
    from kortravelmap.api.transport_state_service import get_state_store

    client = make_valkey_client(_settings("redis://:x@127.0.0.1:1/0"))
    down = ValkeyStateStore(client)
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))
    app.dependency_overrides[get_state_store] = lambda: down
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://map.test"
        ) as http:
            for path in (
                "/v1/service/transport/fuel-stations",
                "/v1/service/transport/status",
                "/v1/service/transport/airports/f_global_p_0000",
            ):
                response = await http.get(path)
                assert response.status_code == 503, path
                assert response.json()["code"] == "TRANSPORT_STATE_UNAVAILABLE"
            assert (await http.get("/health")).status_code == 200
    finally:
        await client.aclose()


# -- Dagster 적재 op ------------------------------------------------------------------


async def test_dagster_loader_swaps_and_refuses_the_empty_incident_set(
    store: ValkeyStateStore,
) -> None:
    from dagster import Failure
    from kortravelmap.dagster.transport_state import TRANSPORT_STATE_SPECS, load_transport_state

    spec = next(s for s in TRANSPORT_STATE_SPECS if s.dataset is DATASET_HIGHWAY_INCIDENTS)
    collected_at = datetime.now(UTC) - timedelta(minutes=4)
    payload: list[list[StateItem]] = [
        [to_state_item(highway_incident_state(_incident(i))) for i in range(30)],
        [],
    ]

    async def _collect(_settings: Any, on_collected_at: Callable[[datetime], None]) -> list[Any]:
        on_collected_at(collected_at)
        return payload.pop(0)

    fake_spec = replace(spec, collect=_collect)
    metadata = await load_transport_state(
        fake_spec,
        settings=KorTravelMapSettings.model_construct(),
        run_id="run-1",
        allow_shrink=False,
        store=store,
    )
    assert metadata["count"] == 30
    assert metadata["source_collected_at"] == collected_at.isoformat()
    meta = await store.current_meta(DATASET_HIGHWAY_INCIDENTS.name)
    assert meta.run_id == "run-1"
    with pytest.raises(Failure) as excinfo:
        await load_transport_state(
            fake_spec,
            settings=KorTravelMapSettings.model_construct(),
            run_id="run-2",
            allow_shrink=False,
            store=store,
        )
    assert excinfo.value.allow_retries is False
    assert str(excinfo.value.metadata["failure_kind"].value) == "state_swap_refused"
    assert (await store.current_meta(DATASET_HIGHWAY_INCIDENTS.name)).count == 30


async def test_rest_cursor_whose_generation_vanishes_mid_read_is_409(
    store: ValkeyStateStore, api: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``readable_meta`` 뒤·값 읽기 전에 grace가 끝나도 빈 "끝" 페이지가 아니라 409다."""
    items = [to_state_item(highway_incident_state(_incident(i))) for i in range(3)]
    await store.swap(
        DATASET_HIGHWAY_INCIDENTS.name,
        items,
        guard=LENIENT,
        source_collected_at=None,
        loaded_at=datetime.now(UTC),
    )
    first = await api.get("/v1/service/transport/highway-incidents", params={"limit": 1})
    cursor = first.json()["meta"]["page"]["next_cursor"]
    original = store.page_ids

    async def _page_then_expire(dataset: str, generation: str, **kwargs: Any) -> Any:
        page = await original(dataset, generation, **kwargs)
        await store.client.delete(
            *(state_key(dataset, generation, name) for name in ("meta", "items", "ids", "geo"))
        )
        return page

    monkeypatch.setattr(store, "page_ids", _page_then_expire)
    gone = await api.get(
        "/v1/service/transport/highway-incidents", params={"limit": 1, "cursor": cursor}
    )
    assert gone.status_code == 409, gone.text
    assert gone.json()["code"] == "TRANSPORT_STATE_GENERATION_EXPIRED"


async def test_one_broken_dataset_does_not_take_down_status_or_rest_areas(
    store: ValkeyStateStore, api: httpx.AsyncClient
) -> None:
    area = rest_area_state(
        TransportRestArea(
            natural_key="행담도휴게소::서해안고속도로::목포방향",
            name="행담도휴게소",
            route_name="서해안고속도로",
            direction="목포방향",
            lon=126.8,
            lat=36.9,
            phone_number=None,
            has_gas_station=True,
            has_lpg_station=False,
            has_ev_charger=True,
            raw={},
        )
    )
    await store.swap(
        DATASET_REST_AREAS.name,
        [to_state_item(area)],
        guard=LENIENT,
        source_collected_at=None,
        loaded_at=datetime.now(UTC),
    )
    # 휴게소 유가 포인터가 없는 세대를 가리킨다(깨진 데이터셋).
    await store.client.set(
        state_key(DATASET_REST_AREA_FUEL_PRICES.name, "current"), "20260101T000000Z-dead"
    )
    areas = await api.get("/v1/service/transport/rest-areas")
    assert areas.status_code == 200, areas.text
    assert areas.json()["data"]["items"][0]["fuel_prices"] is None
    status_body = (await api.get("/v1/service/transport/status")).json()["data"]
    by_name = {d["dataset"]: d for d in status_body["datasets"]}
    assert by_name[DATASET_REST_AREAS.name]["loaded"] is True
    broken = by_name[DATASET_REST_AREA_FUEL_PRICES.name]
    assert broken["loaded"] is False
    assert broken["error"]


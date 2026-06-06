"""``test_client`` — ``AsyncKrtourMapClient`` 순수 경로 (DB 미접근, #122).

후보가 없을 때 ``sync_dedup_candidates``가 session을 열지 않고 빈 결과를
조기 반환하는지 검증 (순수 ``find_dedup_candidates`` 경로). DB가 필요한 경로는
``tests/integration/test_client_orchestration.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from krtour.map.client import AsyncKrtourMapClient, DedupSyncResult
from krtour.map.dto.coordinate import Coordinate
from krtour.map.infra.db import make_async_engine
from krtour.map.infra.dedup_repo import DedupQueueResult

pytestmark = pytest.mark.unit

_TEMPLE_CAT = "01070100"


@dataclass(frozen=True)
class _Stub:
    """``DedupInput`` Protocol 만족."""

    feature_id: str
    name: str
    coord: Coordinate | None
    category: str


def _c(lon: str, lat: str) -> Coordinate:
    return Coordinate(lon=Decimal(lon), lat=Decimal(lat))


async def test_sync_dedup_no_candidates_skips_db() -> None:
    # 연결되지 않는 DSN — 후보가 없으면 session을 안 열어야 통과 (DB 미접근).
    engine = make_async_engine("postgresql+asyncpg://u:p@localhost:5432/nodb")
    client = AsyncKrtourMapClient(engine)
    try:
        knps = [_Stub("a", "불국사", _c("129.3320", "35.7900"), _TEMPLE_CAT)]
        krh = [_Stub("b", "해인사", _c("128.0980", "35.8010"), _TEMPLE_CAT)]
        # 이름·좌표 모두 멀어 KEEP_SEPARATE → 후보 없음 → 큐/세션 미사용.
        result = await client.sync_dedup_candidates(knps, krh)
        assert result == DedupSyncResult(candidates=[], queue=DedupQueueResult())
    finally:
        await engine.dispose()


async def test_client_constructs_with_engine() -> None:
    engine = make_async_engine("postgresql+asyncpg://u:p@localhost:5432/nodb")
    try:
        client = AsyncKrtourMapClient(engine)
        assert isinstance(client, AsyncKrtourMapClient)
        async with client as c:
            assert c is client
    finally:
        await engine.dispose()


# ── T-213d: client read parity 위임 (DB 미접근 — repo/session monkeypatch) ──


class _FakeSessionCM:
    """``self._session_factory()`` 대체 — 실제 DB 세션 없이 sentinel 반환."""

    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _fake_session_factory() -> _FakeSessionCM:
    return _FakeSessionCM()


def _read_client(monkeypatch: pytest.MonkeyPatch) -> AsyncKrtourMapClient:
    engine = make_async_engine("postgresql+asyncpg://u:p@localhost:5432/nodb")
    client = AsyncKrtourMapClient(engine)
    # DB 미접근: 세션 팩토리를 sentinel CM으로 교체 (engine 미사용).
    monkeypatch.setattr(client, "_session_factory", _fake_session_factory)
    return client


async def test_get_features_delegates_to_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    import krtour.map.client as client_mod

    recorded: dict[str, object] = {}

    async def _fake(session: object, feature_ids: object) -> dict[str, dict[str, str]]:
        recorded["feature_ids"] = list(feature_ids)  # type: ignore[arg-type]
        return {"f1": {"feature_id": "f1"}}

    monkeypatch.setattr(client_mod, "get_feature_rows_by_ids", _fake)
    client = _read_client(monkeypatch)
    out = await client.get_features(["f1", "f2"])
    assert out == {"f1": {"feature_id": "f1"}}
    assert recorded["feature_ids"] == ["f1", "f2"]


async def test_search_features_delegates_to_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    import krtour.map.client as client_mod

    sentinel = object()
    recorded: dict[str, object] = {}

    async def _fake(session: object, **kwargs: object) -> object:
        recorded.update(kwargs)
        return sentinel

    monkeypatch.setattr(client_mod, "repo_search_features", _fake)
    client = _read_client(monkeypatch)
    out = await client.search_features(q="불국사", kinds=["place"], limit=10)
    assert out is sentinel
    assert recorded["q"] == "불국사"
    assert recorded["kinds"] == ["place"]
    assert recorded["limit"] == 10
    assert recorded["bbox"] is None
    assert recorded["cursor"] is None


async def test_features_nearby_target_delegates_to_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import krtour.map.client as client_mod

    sentinel = object()
    recorded: dict[str, object] = {}

    async def _fake(session: object, **kwargs: object) -> object:
        recorded.update(kwargs)
        return sentinel

    monkeypatch.setattr(client_mod, "repo_features_nearby_poi_cache_target", _fake)
    client = _read_client(monkeypatch)
    out = await client.features_nearby_poi_cache_target(
        target_id="t1", radius_km=2.0, sort="name", limit=20
    )
    assert out is sentinel
    assert recorded["target_id"] == "t1"
    assert recorded["radius_km"] == 2.0
    assert recorded["sort"] == "name"
    assert recorded["limit"] == 20
    assert recorded["statuses"] == ("active",)


async def test_features_nearby_coord_delegates_to_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import krtour.map.client as client_mod

    sentinel = object()
    recorded: dict[str, object] = {}

    async def _fake(session: object, **kwargs: object) -> object:
        recorded.update(kwargs)
        return sentinel

    monkeypatch.setattr(client_mod, "repo_features_nearby", _fake)
    client = _read_client(monkeypatch)
    out = await client.features_nearby(lon=127.0, lat=37.5, radius_m=1500.0)
    assert out is sentinel
    assert recorded["lon"] == 127.0
    assert recorded["lat"] == 37.5
    assert recorded["radius_m"] == 1500.0
    assert recorded["sort"] == "distance"
    assert recorded["statuses"] == ("active",)

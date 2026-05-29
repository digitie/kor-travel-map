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

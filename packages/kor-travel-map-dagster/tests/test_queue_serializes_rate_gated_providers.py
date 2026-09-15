"""큐가 run을 동시에 띄워도 gate를 선언한 provider는 **한 번에 하나만** 지난다.

`python-krex-api`는 초당 5건을 지킨다 — 그 보증은 **프로세스당**이다. 큐 센서는 틱당
RunRequest를 10개 내고 `docker/dagster.yaml`이 `tag_concurrency_limits`로 4를 동시에
돌리므로, run마다 `KrexClient`가 따로면 버킷도 따로여서 합계가 최대 **20 TPS**가
된다(2026-09-14 적대 리뷰 둘이 독립적으로 짚은 자리).

**한 프로세스 안에서만 재면 이 구멍이 보이지 않는다.** 그래서 여기서는 서로 다른
worker run을 흉내 낸다 — advisory lock 상태를 공유하는 **별개의 session 객체** 둘이
동시에 같은 scope를 돌린다. 진짜 Postgres에서 그 공유를 해 주는 것이 advisory lock이다.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

import pytest

from kortravelmap.dagster.feature_update_runner import (
    KREX_RATE_GATE,
    PROVIDER_RATE_GATES,
    provider_rate_gate,
)

_GATE_COOLDOWN: Final[float] = PROVIDER_RATE_GATES[KREX_RATE_GATE]


class _SharedLockTable:
    """여러 fake session이 공유하는 advisory lock 상태 — Postgres 자리를 대신한다."""

    def __init__(self) -> None:
        self._held: set[int] = set()
        self._changed = asyncio.Condition()

    async def acquire(self, lock_id: int) -> None:
        async with self._changed:
            while lock_id in self._held:
                await self._changed.wait()
            self._held.add(lock_id)

    async def release(self, lock_id: int) -> None:
        async with self._changed:
            self._held.discard(lock_id)
            self._changed.notify_all()

    def held(self) -> int:
        return len(self._held)


class _FakeSession:
    """`advisory_lock`이 쓰는 두 문장만 이해하는 session."""

    def __init__(self, table: _SharedLockTable) -> None:
        self._table = table

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> Any:
        sql = str(statement)
        lock_id = int((params or {})["lock_id"])
        if "pg_advisory_lock" in sql:
            await self._table.acquire(lock_id)
        elif "pg_advisory_unlock" in sql:
            await self._table.release(lock_id)
        else:  # pragma: no cover - 이 검사가 보는 문장은 둘뿐이다.
            raise AssertionError(f"예상하지 못한 문장: {sql}")
        return None


@pytest.mark.asyncio
async def test_gated_work_never_overlaps_across_sessions() -> None:
    """gate를 선언한 작업은 **동시에 둘이 들어가지 못한다.**"""

    table = _SharedLockTable()
    overlap = 0
    inside = 0

    async def worker() -> None:
        nonlocal overlap, inside
        async with provider_rate_gate(_FakeSession(table), KREX_RATE_GATE):
            inside += 1
            overlap = max(overlap, inside)
            await asyncio.sleep(0.02)
            inside -= 1

    await asyncio.gather(*(worker() for _ in range(4)))

    assert overlap == 1, (
        f"gate 안에 동시에 {overlap}개가 들어갔다. run마다 client가 따로라 "
        "겹치면 상한이 그만큼 곱해진다."
    )
    assert table.held() == 0, "lock이 반납되지 않았다 — 다음 run이 영영 기다린다"


@pytest.mark.asyncio
async def test_the_handover_leaves_a_gap_so_the_seam_does_not_burst() -> None:
    """넘겨줄 때 **간격을 남긴다** — 직렬화만으로는 이음매에서 상한을 넘는다.

    A가 마지막 요청을 보내고 즉시 lock을 놓으면 B의 첫 요청이 바로 뒤에 붙는다.
    상한은 "평균"이 아니라 "어느 1초 창에서도"이므로 이음매도 창 안이다.
    """

    table = _SharedLockTable()
    entered: list[float] = []

    async def worker() -> None:
        async with provider_rate_gate(_FakeSession(table), KREX_RATE_GATE):
            entered.append(asyncio.get_running_loop().time())

    await asyncio.gather(*(worker() for _ in range(3)))

    entered.sort()
    gaps = [b - a for a, b in zip(entered, entered[1:], strict=False)]
    assert gaps, "교대가 일어나지 않았다 — 이 검사가 아무것도 재지 않았다"
    assert min(gaps) >= _GATE_COOLDOWN * 0.9, (
        f"교대 간격이 {min(gaps):.4f}s다(기대 {_GATE_COOLDOWN}s). "
        "락을 놓기 전에 쉬지 않으면 이음매에서 상한을 넘는다."
    )


@pytest.mark.asyncio
async def test_ungated_work_is_not_serialized() -> None:
    """gate를 선언하지 않은 operation은 **막지 않는다.**

    이 검사가 없으면 "전부 직렬화한다"도 위 검사를 통과한다 — 큐 전체가 느려지는
    변경이 조용히 들어올 수 있다.
    """

    table = _SharedLockTable()
    inside = 0
    overlap = 0

    async def worker() -> None:
        nonlocal inside, overlap
        async with provider_rate_gate(_FakeSession(table), None):
            inside += 1
            overlap = max(overlap, inside)
            await asyncio.sleep(0.02)
            inside -= 1

    await asyncio.gather(*(worker() for _ in range(4)))
    assert overlap == 4, f"gate 없는 작업이 직렬화됐다(동시 {overlap}). 큐 전체가 느려진다."

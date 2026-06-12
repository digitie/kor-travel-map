"""``kortravelmap.infra.advisory_lock`` — PostgreSQL advisory lock helper (ADR-011).

다중 워커가 같은 작업(예: MOIS Step A bulk 적재)을 동시에 실행하지 못하도록
PostgreSQL **session-level advisory lock**으로 직렬화한다. ``import_jobs`` 큐의
``SELECT ... FOR UPDATE SKIP LOCKED`` 워커 직렬과, ADR-039 CLI mutex가 공통으로
쓰는 기초 헬퍼.

advisory lock은 ``bigint`` 키를 쓰므로, 문자열 lock key(예:
``"import:python-mois-api:mois_license_features_bulk"``)를 결정적으로 64-bit
정수로 해싱한다 (BLAKE2b 8바이트 → signed int64).

두 진입점:

- ``advisory_lock(session, key)`` — **blocking** lock. 다른 세션이 잡고 있으면
  획득할 때까지 대기 (``pg_advisory_lock``). exit 시 ``pg_advisory_unlock``.
- ``try_advisory_lock(session, key)`` — **non-blocking**. 즉시 획득 실패 시
  ``acquired=False``로 진입(대기 안 함, ``pg_try_advisory_lock``). 작업을 건너뛰는
  "이미 누가 돌고 있으면 skip" 패턴에 사용.

session-level lock은 transaction 경계와 무관하게 **명시적으로 unlock**해야 하므로
(``pg_advisory_xact_lock``과 달리 commit/rollback에 자동 해제 안 됨), 본 헬퍼는
``finally``에서 반드시 unlock한다. lock을 잡은 connection과 unlock 호출 connection이
같아야 하므로, 호출자는 **단일 connection에 고정된 session**(또는 같은 connection을
재사용하는 session)을 넘겨야 한다.

ADR 참조
--------
- ADR-002 — async-only
- ADR-004 — raw SQL ``text()``
- ADR-011 — 작업 큐 advisory lock + SKIP LOCKED 직렬화
- ADR-039 — CLI mutex (advisory lock 기반)
"""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "advisory_lock_key",
    "advisory_lock",
    "try_advisory_lock",
]

# signed int64 경계 — pg advisory lock은 bigint(-2^63 ~ 2^63-1).
_INT64_OFFSET = 2**63
_INT64_MODULO = 2**64


def advisory_lock_key(key: str) -> int:
    """문자열 lock key를 결정적 signed int64로 해싱 (pg advisory lock 인자).

    BLAKE2b 8바이트 digest → unsigned 64-bit → signed int64로 시프트. 같은
    문자열은 항상 같은 정수 (프로세스/플랫폼 무관 — hash() 랜덤화 회피).
    """
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    unsigned = int.from_bytes(digest, "big")
    return (unsigned % _INT64_MODULO) - _INT64_OFFSET


@asynccontextmanager
async def advisory_lock(
    session: AsyncSession, key: str | int
) -> AsyncIterator[None]:
    """**Blocking** session-level advisory lock (``pg_advisory_lock``).

    다른 세션이 같은 키를 잡고 있으면 획득할 때까지 대기한다. exit 시 반드시
    ``pg_advisory_unlock`` (commit/rollback에 자동 해제 안 됨 — session-level).

    Parameters
    ----------
    session
        lock/unlock을 같은 connection에서 실행할 ``AsyncSession``.
    key
        lock 키 (문자열이면 ``advisory_lock_key``로 해싱, int면 그대로 사용).

    Examples
    --------
    >>> async with advisory_lock(session, "import:python-mois-api:bulk"):  # doctest: +SKIP
    ...     await sync_mois_license_features_bulk(session, records, ...)
    """
    lock_id = key if isinstance(key, int) else advisory_lock_key(key)
    await session.execute(
        text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id}
    )
    try:
        yield
    finally:
        await session.execute(
            text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id}
        )


@asynccontextmanager
async def try_advisory_lock(
    session: AsyncSession, key: str | int
) -> AsyncIterator[bool]:
    """**Non-blocking** session-level advisory lock (``pg_try_advisory_lock``).

    즉시 획득 가능하면 ``True``, 다른 세션이 이미 잡고 있으면 대기하지 않고
    ``False``로 진입한다. ``True``로 진입한 경우에만 exit 시 unlock한다.

    "이미 누가 돌고 있으면 skip" 패턴:

    >>> async with try_advisory_lock(session, "import:mois:bulk") as acquired:  # doctest: +SKIP
    ...     if not acquired:
    ...         return  # 다른 워커가 적재 중 — skip
    ...     await sync_mois_license_features_bulk(session, records, ...)

    Returns
    -------
    bool
        lock 획득 여부 (context 변수).
    """
    lock_id = key if isinstance(key, int) else advisory_lock_key(key)
    result = await session.execute(
        text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": lock_id}
    )
    acquired = bool(result.scalar_one())
    try:
        yield acquired
    finally:
        if acquired:
            await session.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id}
            )

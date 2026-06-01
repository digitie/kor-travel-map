"""``krtour.map.cli.mutex`` — CLI 명령 mutex (ADR-039).

같은 CLI 명령(같은 provider+dataset, 같은 feature merge 등)이 다중 워커/세션에서
중복 실행되지 않도록 PostgreSQL advisory lock으로 직렬화한다. ``infra.advisory_lock``
위의 얇은 래퍼 + CLI 명령용 lock key 컨벤션(SPRINT-4 §2.8).

lock key 컨벤션
---------------
- ``import:{provider}:{dataset_key}`` — ``krtour-map import`` 중복 실행 차단.
- ``dedup-merge:{id}`` — manual merge 중복 실행 차단. CLI ``dedup-merge``는
  ``id`` = ``review_key``(병합 대상 후보쌍 식별자)를 쓴다.
- ``alembic-upgrade`` — Alembic 다중 워커 중복 차단.

read-only 명령(``status``/``--dry-run``)은 mutex 없이 (호출 측 책임).

두 진입점
---------
- ``mutex_lock(session, key)`` — **blocking**. 다른 실행이 끝날 때까지 대기.
- ``try_mutex_lock(session, key)`` — **non-blocking**. 이미 실행 중이면 대기하지
  않고 ``acquired=False``로 진입(CLI에서 "이미 실행 중" 메시지 후 종료).

ADR 참조
--------
- ADR-002 — async-only
- ADR-039 — CLI mutex (advisory lock 기반); lock 잔존 fallback은 호출 측
  ``lifespan``/``atexit`` + ``pg_stat_activity`` (후속).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from krtour.map.infra.advisory_lock import advisory_lock, try_advisory_lock

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "mutex_lock",
    "try_mutex_lock",
    "import_lock_key",
    "dedup_merge_lock_key",
    "alembic_upgrade_lock_key",
]


def import_lock_key(provider: str, dataset_key: str) -> str:
    """``krtour-map import <provider> <dataset>`` mutex 키."""
    return f"import:{provider}:{dataset_key}"


def dedup_merge_lock_key(target_id: str) -> str:
    """``krtour-map dedup-merge`` mutex 키. ``target_id`` = ``review_key``(병합
    대상 후보쌍 식별자). 값은 lock에 불투명 — 같은 후보 병합 중복 실행만 차단."""
    return f"dedup-merge:{target_id}"


def alembic_upgrade_lock_key() -> str:
    """``alembic upgrade head`` 다중 워커 중복 차단 mutex 키."""
    return "alembic-upgrade"


def mutex_lock(
    session: AsyncSession, key: str
) -> AbstractAsyncContextManager[None]:
    """CLI 명령 mutex (**blocking**). ``infra.advisory_lock`` 래퍼.

    다른 실행이 같은 키 lock을 잡고 있으면 해제될 때까지 대기한다. exit 시 unlock.

    >>> key = import_lock_key("python-mois-api", "bulk")
    >>> async with mutex_lock(session, key):  # doctest: +SKIP
    ...     await run_import(...)
    """
    return advisory_lock(session, key)


def try_mutex_lock(
    session: AsyncSession, key: str
) -> AbstractAsyncContextManager[bool]:
    """CLI 명령 mutex (**non-blocking**). ``infra.advisory_lock`` 래퍼.

    이미 같은 키로 실행 중이면 대기하지 않고 ``acquired=False``로 진입한다.

    >>> async with try_mutex_lock(session, alembic_upgrade_lock_key()) as ok:  # doctest: +SKIP
    ...     if not ok:
    ...         print("이미 실행 중 — 종료")
    ...         return
    ...     await upgrade(...)
    """
    return try_advisory_lock(session, key)

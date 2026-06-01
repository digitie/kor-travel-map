"""``krtour.map.cli`` — CLI 명령 + advisory lock 기반 mutex (ADR-039).

Sprint 4 진입과 함께 신설된 CLI layer. 의존 계층 최상위
(``category → dto → core → infra → providers → geocoding → client → cli``)로,
하위 layer(특히 ``infra.advisory_lock``)를 사용하지만 어떤 layer도 cli를
import하지 않는다 (import-linter layered).

본 PR(SPRINT-4 §2.8)은 mutex 기초만 제공한다:

- ``mutex.py`` — ``mutex_lock`` / ``try_mutex_lock`` async context manager +
  CLI 명령용 lock key 헬퍼(``import_lock_key`` 등). PostgreSQL advisory lock
  (``infra.advisory_lock``) 위 얇은 래퍼.

실제 CLI 명령(``krtour-map import`` 등)의 argparse/entry-point는 후속 PR.

ADR 참조
--------
- ADR-002 — async-only
- ADR-011 — 작업 큐 advisory lock + SKIP LOCKED
- ADR-039 — CLI mutex (advisory lock 기반)
"""

from __future__ import annotations

from krtour.map.cli.main import build_parser, main
from krtour.map.cli.mutex import (
    alembic_upgrade_lock_key,
    dedup_merge_lock_key,
    import_lock_key,
    mutex_lock,
    try_mutex_lock,
)

__all__ = [
    "main",
    "build_parser",
    "mutex_lock",
    "try_mutex_lock",
    "import_lock_key",
    "dedup_merge_lock_key",
    "alembic_upgrade_lock_key",
]

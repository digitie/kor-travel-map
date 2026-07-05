"""Dagster 측 파일 registry hook (H8/H9) — MOIS 소스 DB 생산/소비 기록.

dagster 코드는 sync 경로(op, ``asyncio.to_thread`` worker)에서 실행되므로 PG
write는 전용 스레드에서 one-shot async engine으로 수행한다(이벤트 루프 위에서
호출돼도 안전). hook은 본작업을 절대 실패시키지 않는다 — 실패는 WARN 로그만.
"""

from __future__ import annotations

import asyncio
import logging
import pathlib
import threading
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from kortravelmap.core.managed_file_states import MANAGED_FILE_LOCATION_MOIS_SOURCE
from kortravelmap.infra import file_registry
from kortravelmap.infra.db import make_async_engine
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from kortravelmap.settings import KorTravelMapSettings

__all__ = [
    "record_mois_source_download",
    "record_mois_source_loaded",
]

logger = logging.getLogger(__name__)

_HOOK_TIMEOUT_SECONDS = 15.0


def _run_blocking(coro_factory: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """전용 스레드에서 ``asyncio.run`` — 호출 스레드의 루프 유무와 무관하게 안전."""

    failure: list[BaseException | None] = [None]

    def _runner() -> None:
        try:
            asyncio.run(coro_factory())
        except BaseException as exc:  # noqa: BLE001 — 호출부 guard로 전달
            failure[0] = exc

    thread = threading.Thread(
        target=_runner, name="file-registry-hook", daemon=True
    )
    thread.start()
    thread.join(timeout=_HOOK_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise TimeoutError("file registry hook timed out")
    if failure[0] is not None:
        raise failure[0]


def _mois_sidecars(db_path: str) -> list[str]:
    base = pathlib.Path(db_path)
    candidates = [
        base.with_name(base.name + suffix) for suffix in ("-wal", "-shm", ".synced", ".lock")
    ]
    return [candidate.name for candidate in candidates if candidate.exists()]


def record_mois_source_download(
    settings: KorTravelMapSettings,
    *,
    summary_meta: dict[str, Any] | None = None,
    dagster_run_id: str | None = None,
) -> None:
    """MOIS 소스 DB sync 성공 기록 (H8) — 실패해도 sync를 죽이지 않는다."""

    try:
        db_path = settings.mois_source_db_path
        if db_path is None:
            return
        path = pathlib.Path(db_path)
        byte_size = path.stat().st_size if path.is_file() else None
        meta: dict[str, Any] = {
            "physical": {"path": db_path},
            "sidecars": _mois_sidecars(db_path),
        }
        if summary_meta:
            meta["sync"] = summary_meta

        async def _write() -> None:
            engine = make_async_engine(settings.pg_dsn)
            try:
                async with AsyncSession(engine) as session, session.begin():
                    await file_registry.register_file(
                        session,
                        storage_backend="filesystem",
                        location=MANAGED_FILE_LOCATION_MOIS_SOURCE,
                        path=path.name,
                        kind="provider_download",
                        provider="mois",
                        byte_size=byte_size,
                        origin_dagster_run_id=dagster_run_id,
                        downloaded_at=datetime.now(UTC),
                        actor="dagster",
                        event_kind="downloaded",
                        meta=meta,
                    )
            finally:
                await engine.dispose()

        _run_blocking(_write)
    except Exception:  # noqa: BLE001 — hook 무해화(설계 §0.3)
        logger.warning(
            "managed-file registry hook 실패(무시): mois-source download", exc_info=True
        )


def record_mois_source_loaded(
    settings: KorTravelMapSettings,
    *,
    dagster_run_id: str | None = None,
) -> None:
    """MOIS 소스 DB 소비(Phase B read) 기록 (H9) — 실패 무해."""

    try:
        db_path = settings.mois_source_db_path
        if db_path is None:
            return
        name = pathlib.Path(db_path).name

        async def _write() -> None:
            engine = make_async_engine(settings.pg_dsn)
            try:
                async with AsyncSession(engine) as session, session.begin():
                    await file_registry.touch_loaded(
                        session,
                        storage_backend="filesystem",
                        location=MANAGED_FILE_LOCATION_MOIS_SOURCE,
                        path=name,
                        event_kind="loaded",
                        actor="dagster",
                        dagster_run_id=dagster_run_id,
                    )
            finally:
                await engine.dispose()

        _run_blocking(_write)
    except Exception:  # noqa: BLE001 — hook 무해화(설계 §0.3)
        logger.warning(
            "managed-file registry hook 실패(무시): mois-source loaded", exc_info=True
        )

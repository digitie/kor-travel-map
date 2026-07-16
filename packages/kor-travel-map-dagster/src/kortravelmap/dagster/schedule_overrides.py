"""Dagster schedule cron override helper.

Dagster schedule의 ``cron_schedule``은 code location 로드 시점에 고정된다.
운영 UI는 ``ops.dagster_schedule_overrides``에 override를 저장하고 repository
location reload를 호출한다. 이 모듈은 reload 시 DB override를 읽되, DB 또는
마이그레이션을 읽을 수 없으면 code location 로드를 실패시켜 저장된 override를
조용히 무시한 채 기본 cron으로 실행하는 상태를 만들지 않는다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Final

import psycopg
from kortravelmap.settings import KorTravelMapSettings

__all__ = [
    "cron_for_schedule",
    "load_schedule_cron_overrides",
]

_ASYNC_DSN_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("postgresql+asyncpg://", "postgresql://"),
    ("postgresql+psycopg://", "postgresql://"),
)


def _psycopg_dsn() -> str:
    dsn = KorTravelMapSettings().pg_dsn.get_secret_value()
    for prefix, replacement in _ASYNC_DSN_PREFIXES:
        if dsn.startswith(prefix):
            return f"{replacement}{dsn[len(prefix):]}"
    return dsn


@lru_cache(maxsize=1)
def load_schedule_cron_overrides() -> dict[str, str]:
    """Return schedule_name → cron override mapping.

    DB 조회 실패는 호출자에게 그대로 전파한다. 저장된 override가 존재할 수 있는
    상황에서 기본값 fallback은 UI의 저장 상태와 실제 실행 cron을 갈라놓기 때문이다.
    """

    with (
        psycopg.connect(_psycopg_dsn(), connect_timeout=2) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            SELECT schedule_name, cron_schedule
            FROM ops.dagster_schedule_overrides
            WHERE btrim(schedule_name) <> ''
              AND btrim(cron_schedule) <> ''
            """
        )
        return {
            str(schedule_name): str(cron_schedule)
            for schedule_name, cron_schedule in cur.fetchall()
        }


def cron_for_schedule(schedule_name: str, default_cron: str) -> str:
    """Return DB override cron if present, otherwise the code default."""

    return load_schedule_cron_overrides().get(schedule_name, default_cron)

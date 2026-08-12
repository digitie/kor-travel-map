"""Dagster schedule cron override helper.

Dagster schedule의 ``cron_schedule``은 code location 로드 시점에 고정된다.
운영 UI는 ``ops.dagster_schedule_overrides``에 override를 저장하고 repository
location reload를 호출한다. 이 모듈은 reload 시 DB override를 읽되, DB 또는
마이그레이션을 읽을 수 없으면 standalone 개발 환경에서는 코드 기본 cron을 쓰고,
Docker 운영 code location에서는 로드를 실패시킨다. 운영 모드는 compose가
``KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED=true``로 명시한다.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Final

import psycopg
from kortravelmap.settings import KorTravelMapSettings

__all__ = [
    "cron_for_schedule",
    "ScheduleOverrideStorageUnavailable",
    "load_schedule_cron_overrides",
]

_ASYNC_DSN_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("postgresql+asyncpg://", "postgresql://"),
    ("postgresql+psycopg://", "postgresql://"),
)
_REQUIRED_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_SCHEDULE_OVERRIDES_REQUIRED"
_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES: Final = frozenset({"0", "false", "no", "off", ""})
_LOGGER = logging.getLogger(__name__)


def _overrides_required() -> bool:
    value = os.environ.get(_REQUIRED_ENV, "").strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(f"{_REQUIRED_ENV} must be a boolean value")


class ScheduleOverrideStorageUnavailable(RuntimeError):
    """override 저장소에 닿을 수 없다(설정 부재 포함).

    ``load_schedule_cron_overrides``의 계약은 "DB 없이도 정의를 import할 수 있다"이다.
    DSN 미설정은 그 계약에서 **연결 실패와 같은 부류**이지 프로그래밍 오류가 아니므로,
    ``OSError``/``psycopg.Error``와 같은 자리에서 잡히도록 전용 타입으로 올린다.
    (앞 판은 ``pg_dsn``이 ``None``일 때 ``AttributeError``가 나서 이 fallback을
    통째로 건너뛰었다 — ADR-090이 기본 DSN을 없앤 뒤의 회귀다.)
    """


def _psycopg_dsn() -> str:
    secret = KorTravelMapSettings().pg_dsn
    if secret is None:
        raise ScheduleOverrideStorageUnavailable(
            "KOR_TRAVEL_MAP_PG_DSN runtime DSN is required; "
            "no application DSN fallback exists"
        )
    dsn = secret.get_secret_value()
    for prefix, replacement in _ASYNC_DSN_PREFIXES:
        if dsn.startswith(prefix):
            return f"{replacement}{dsn[len(prefix):]}"
    return dsn


@lru_cache(maxsize=1)
def load_schedule_cron_overrides() -> dict[str, str]:
    """Return schedule_name → cron override mapping.

    standalone 개발·단위 테스트는 DB 없이도 정의를 import할 수 있어야 하므로
    기본 모드는 코드 cron으로 fallback한다. Docker 운영 code location은 compose가
    required 모드를 강제해 저장된 override를 조용히 무시하지 않는다.
    """

    required = _overrides_required()
    try:
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
    except (OSError, psycopg.Error, ScheduleOverrideStorageUnavailable):
        if required:
            raise
        _LOGGER.warning(
            "schedule override storage is unavailable; using code defaults"
        )
        return {}


def cron_for_schedule(schedule_name: str, default_cron: str) -> str:
    """Return DB override cron if present, otherwise the code default."""

    return load_schedule_cron_overrides().get(schedule_name, default_cron)

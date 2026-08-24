#!/usr/local/bin/python
"""Manager/local fresh-init 전용 application ``300`` migration executable.

이 command는 daemon entrypoint의 "기동 중 Alembic" 경로가 아니다. 역할 bootstrap이
끝난 virgin DB에 대해 restricted migrator로 exact ``300`` root를 한 번 적용하고 closed
runtime ACL을 조정한 뒤 종료한다. bootstrap-superuser credential과 API/UI credential은
받지 않으며, raw version table이 이미 있으면 어떤 repair/stamp도 하지 않고 거부한다.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text

from alembic import command
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.runtime_privileges import reconcile_runtime_privileges

_DESTINATION_HEAD: Final = "300"
_MIGRATOR_DSN_ENV: Final = "KOR_TRAVEL_MAP_MIGRATOR_PG_DSN"
_SCHEMA_OWNER_ROLE_ENV: Final = "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"
_BOOTSTRAP_DSN_ENV: Final = "KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN"
_MIGRATOR_ROLE: Final = "ktm_feature_migrator"
_APPLICATION_ROOT_CANDIDATES: Final = (Path("/app"), Path(__file__).resolve().parents[1])


class FreshMigrationError(RuntimeError):
    """fresh root migration의 fail-closed 오류."""


def _parse_args(arguments: Sequence[str] | None) -> None:
    values = list(sys.argv[1:] if arguments is None else arguments)
    if values != ["migrate"]:
        raise FreshMigrationError("only the fixed `migrate` operation is accepted")


def _application_root() -> Path:
    for candidate in _APPLICATION_ROOT_CANDIDATES:
        if (candidate / "alembic.ini").is_file() and (candidate / "alembic").is_dir():
            return candidate
    raise FreshMigrationError("installed application Alembic root is unavailable")


def _config(dsn: str) -> Config:
    root = _application_root()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    return config


async def _assert_virgin_version_table(dsn: str) -> None:
    """blank row도 acceptance하지 않아 fresh action의 재실행을 차단한다."""

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            version_table = await connection.scalar(
                text("SELECT to_regclass('public.alembic_version') IS NOT NULL")
            )
    finally:
        await engine.dispose()
    if bool(version_table):
        raise FreshMigrationError(
            "fresh 300 migration requires no existing public.alembic_version table"
        )


async def _assert_restricted_migrator_session(dsn: str) -> None:
    """DSN 이름이 아니라 실제 LOGIN principal을 migration 전에 고정한다.

    image가 non-root여도 ``MIGRATOR_PG_DSN``에 bootstrap superuser URL을 넣을 수
    있다. handoff와 마찬가지로 connection의 ``session_user``와 ``current_user``를
    모두 exact migrator로 닫아, superuser가 ``SET ROLE``만 흉내 내는 우회를
    metadata/version-table mutation 전에 거절한다.
    """

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT session_user::text, current_user::text, role.rolsuper "
                        "FROM pg_catalog.pg_roles AS role "
                        "WHERE role.rolname = session_user"
                    )
                )
            ).one_or_none()
    except Exception as exc:  # DSN authority/host details는 로그에 내보내지 않는다.
        raise FreshMigrationError("fresh 300 migration cannot verify migrator session") from exc
    finally:
        await engine.dispose()
    if (
        row is None
        or str(row[0]) != _MIGRATOR_ROLE
        or str(row[1]) != _MIGRATOR_ROLE
        or bool(row[2])
    ):
        raise FreshMigrationError("fresh 300 migration must connect as restricted migrator")


async def _assert_exact_destination_version(dsn: str) -> None:
    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
            )
            versions = tuple(str(value) for value in rows.scalars().all())
    finally:
        await engine.dispose()
    if versions != (_DESTINATION_HEAD,):
        raise FreshMigrationError("fresh 300 migration did not produce exact raw revision 300")


async def _migrate() -> None:
    if os.environ.get(_BOOTSTRAP_DSN_ENV):
        raise FreshMigrationError("bootstrap-superuser DSN must not enter fresh migration")
    dsn = os.environ.get(_MIGRATOR_DSN_ENV)
    if not dsn:
        raise FreshMigrationError(f"{_MIGRATOR_DSN_ENV} is required")
    config = _config(dsn)
    if tuple(ScriptDirectory.from_config(config).get_heads()) != (_DESTINATION_HEAD,):
        raise FreshMigrationError("installed active Alembic graph head is not exactly 300")

    await _assert_restricted_migrator_session(dsn)
    await _assert_virgin_version_table(dsn)
    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = dsn
    os.environ[_SCHEMA_OWNER_ROLE_ENV] = "true"
    await asyncio.to_thread(command.upgrade, config, "head")
    await reconcile_runtime_privileges()
    await _assert_exact_destination_version(dsn)


async def async_main(arguments: Sequence[str] | None = None) -> int:
    try:
        _parse_args(arguments)
        await _migrate()
    except FreshMigrationError as exc:
        print(f"fresh application 300 migration refused: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "schema": "kor-travel-map.application-fresh-300-migration.v1",
                "outcome": "migrated",
                "destination_head": _DESTINATION_HEAD,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def main(arguments: Sequence[str] | None = None) -> int:
    return asyncio.run(async_main(arguments))


if __name__ == "__main__":
    raise SystemExit(main())

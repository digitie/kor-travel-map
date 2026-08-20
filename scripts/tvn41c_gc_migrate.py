"""T-VN-41C GC 검증용 격리 DB를 배포 경로와 같은 방식으로 head까지 올린다.

통합 테스트 conftest가 fresh DB에 쓰는 순서를 그대로 따른다 — superuser로 role
graph를 만든 뒤 **migrator role**로, ``KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE=true``
아래에서 upgrade한다. 이 선행이 없으면 0095 계열이 ``42501``로 막는다. 마지막에
API entrypoint가 하는 ``reconcile_runtime_privileges``까지 돌려 배포 상태와 맞춘다.

usage: tvn41c_gc_migrate.py <repo_root> <dbname>
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from tests.integration._tvn34_migration_bootstrap import bootstrap_tvn34_migration_roles


async def main() -> int:
    repo_root = Path(sys.argv[1])
    dsn = normalize_async_dsn(os.environ["KOR_TRAVEL_MAP_PG_DSN"])

    engine = make_async_engine(dsn, pool_size=1)
    try:
        migrator_password = await bootstrap_tvn34_migration_roles(engine)
    finally:
        await engine.dispose()
    print("  role bootstrap OK")

    migrator_dsn = make_url(dsn).set(
        username="ktm_feature_migrator", password=migrator_password
    )
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    config.set_main_option("sqlalchemy.url", migrator_dsn.render_as_string(hide_password=False))
    os.environ["KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE"] = "true"
    await asyncio.to_thread(command.upgrade, config, "head")
    print("  alembic upgrade head OK")

    from kortravelmap.infra.runtime_privileges import (  # noqa: PLC0415 — upgrade 뒤에 import
        reconcile_runtime_privileges,
    )

    os.environ["KOR_TRAVEL_MAP_PG_DSN"] = migrator_dsn.render_as_string(hide_password=False)
    await reconcile_runtime_privileges()
    print("  reconcile_runtime_privileges OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

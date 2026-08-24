"""fresh ``300`` one-shot의 restricted migrator 경계."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.integration._application_300_bootstrap import bootstrap_application_300_roles
from tests.integration.test_alembic_metadata_consistency import _admin_execute, _with_database

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "docker" / "application-schema-fresh-300.py"


def _fresh_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("application_300_fresh", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_fresh_one_shot_rejects_superuser_dsn_before_version_table_mutation(
    pg_container: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``MIGRATOR_PG_DSN`` 이름에 superuser URL을 넣어도 root migration은 시작하지 않는다."""

    from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"application_300_fresh_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}"')
    admin_dsn = normalize_async_dsn(_with_database(raw_dsn, database))
    engine = make_async_engine(admin_dsn, pool_size=1)
    try:
        await bootstrap_application_300_roles(engine)
        module = _fresh_module()
        monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
        monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", admin_dsn)

        assert await module.async_main(["migrate"]) == 1
        assert "must connect as restricted migrator" in capsys.readouterr().err
        async with engine.connect() as connection:
            assert (
                await connection.scalar(
                    text("SELECT to_regclass('public.alembic_version') IS NULL")
                )
            ) is True
    finally:
        await engine.dispose()
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')

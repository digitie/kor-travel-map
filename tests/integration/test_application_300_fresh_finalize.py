"""fresh ``300``의 late runtime-ACL failure completion 경계."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text

from tests.integration._application_300_bootstrap import (
    upgrade_head_with_application_300_bootstrap,
)
from tests.integration.test_alembic_metadata_consistency import (
    _admin_execute,
    _raw_version,
    _with_database,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "docker" / "application-schema-fresh-finalize.py"


def _finalize_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("application_300_fresh_finalize", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def fresh_300_database(pg_container: object) -> AsyncIterator[tuple[str, str]]:
    """실제 fresh root를 만든 disposable DB와 restricted migrator DSN."""

    from kortravelmap.infra.db import normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"application_300_finalize_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}"')
    admin_dsn = normalize_async_dsn(_with_database(raw_dsn, database))
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", admin_dsn)
    try:
        await upgrade_head_with_application_300_bootstrap(config, admin_dsn)
        migrator_dsn = config.get_main_option("sqlalchemy.url")
        assert migrator_dsn is not None
        yield admin_dsn, migrator_dsn
    finally:
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')


async def _write_fence(
    module: ModuleType,
    admin_dsn: str,
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manager가 finalizer에 mount할 minimal fixed fence를 disposable test로 만든다."""

    from kortravelmap.infra.db import make_async_engine

    expected = module._static_contract()
    engine = make_async_engine(admin_dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT current_database(), "
                        "(SELECT oid FROM pg_catalog.pg_database "
                        "WHERE datname = current_database()), "
                        "(SELECT datdba::regrole::text FROM pg_catalog.pg_database "
                        "WHERE datname = current_database()), "
                        "(SELECT system_identifier::text "
                        "FROM pg_catalog.pg_control_system())"
                    )
                )
            ).one()
    finally:
        await engine.dispose()
    payload = {
        "schema": "kor-travel-docker-manager.map-fresh-300-finalize-fence.v1",
        "transaction_id": str(uuid4()),
        "journal_sha256": "c" * 64,
        "operation": "map-fresh-300-finalize",
        "map_candidate_commit": "a" * 40,
        "map_candidate_image_id": "sha256:" + "b" * 64,
        "postgres_image_id": expected["postgres_image_id"],
        "destination_head": "300",
        "reference_manifest_sha256": expected["reference_manifest_sha256"],
        "catalog_sha256": expected["catalog_sha256"],
        "seed_sha256": expected["seed_sha256"],
        "privileged_residue_sha256": expected["privileged_residue_sha256"],
        "pre_privileged_residue_sha256": expected["privileged_residue_sha256"],
        "runtime_invariants_sql_sha256": expected["runtime_invariants_sql_sha256"],
        "database_name": str(row[0]),
        "database_oid": int(row[1]),
        "database_owner": str(row[2]),
        "postgres_system_identifier": str(row[3]),
        "writer_fence_expires_at": "2999-01-01T00:00:00+00:00",
    }
    await asyncio.to_thread(
        path.write_text, json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    await asyncio.to_thread(path.chmod, 0o600)
    monkeypatch.setattr(module, "_FENCE_PATH", path)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_APPLICATION_FRESH_FINALIZE_IMAGE_ID", "sha256:" + "b" * 64
    )


@pytest.mark.asyncio
async def test_fresh_finalize_retries_only_fixed_raw_300_completion_after_late_acl_failure(
    fresh_300_database: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """ACL transaction late failure 뒤에도 raw 300을 generic migration 없이 completion한다."""

    admin_dsn, migrator_dsn = fresh_300_database
    module = _finalize_module()
    fence = tmp_path / "fresh-finalize-fence.json"
    await _write_fence(module, admin_dsn, fence, monkeypatch)
    monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)
    original_reconcile = module.reconcile_runtime_privileges

    async def _late_acl_failure() -> None:
        raise RuntimeError("controlled runtime ACL late failure")

    monkeypatch.setattr(module, "reconcile_runtime_privileges", _late_acl_failure)
    command = ["finalize", "--writer-fence-receipt", str(fence)]
    assert await module.async_main(command) == 1
    assert await _raw_version(admin_dsn) == ("300",)
    assert "runtime ACL reconciliation failed" in capsys.readouterr().err

    monkeypatch.setattr(module, "reconcile_runtime_privileges", original_reconcile)
    assert await module.async_main(command) == 0
    assert await _raw_version(admin_dsn) == ("300",)

"""fresh ``300`` one-shot의 restricted migrator 경계."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration._application_300_bootstrap import (
    bootstrap_application_300_roles,
    bootstrapped_application_300_migrator_dsn,
)
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


@pytest.fixture
def safe_fence_directory() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="ktm-fresh-root-", dir="/tmp"))
    try:
        yield path
    finally:
        shutil.rmtree(path)


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
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}" TEMPLATE template0')
    admin_dsn = normalize_async_dsn(_with_database(raw_dsn, database))
    engine = make_async_engine(admin_dsn, pool_size=1)
    try:
        await bootstrap_application_300_roles(engine)
        module = _fresh_module()
        monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
        monkeypatch.setenv("KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE", "local-dev")
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


@pytest.mark.asyncio
async def test_fresh_root_commits_and_recovers_same_immutable_operation_receipt(
    pg_container: object,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    safe_fence_directory: Path,
) -> None:
    """DB commit 뒤 stdout 유실은 exact operation ID의 read-only recovery로 닫는다."""

    from kortravelmap.infra.db import make_async_engine, normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"application_300_root_receipt_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}" TEMPLATE template0')
    admin_dsn = normalize_async_dsn(_with_database(raw_dsn, database))
    try:
        migrator_dsn = await bootstrapped_application_300_migrator_dsn(admin_dsn)
        module = _fresh_module()
        expected = module._static_contract()
        engine = make_async_engine(admin_dsn, pool_size=1)
        try:
            async with engine.connect() as connection:
                identity = (
                    await connection.execute(
                        text(
                            "SELECT current_database(), database.oid, "
                            "pg_catalog.pg_get_userbyid(database.datdba), "
                            "(SELECT system_identifier::text "
                            "FROM pg_catalog.pg_control_system()) "
                            "FROM pg_catalog.pg_database AS database "
                            "WHERE database.datname = current_database()"
                        )
                    )
                ).one()
        finally:
            await engine.dispose()
        operation_id = uuid4()
        fence = safe_fence_directory / "fence.json"
        payload = {
            "schema": "kor-travel-docker-manager.map-fresh-300-migrate-fence.v2",
            "transaction_id": str(uuid4()),
            "operation_id": str(operation_id),
            "journal_sha256": "c" * 64,
            "journal_generation": 1,
            "operation": "map-fresh-300",
            "map_candidate_commit": "a" * 40,
            "map_candidate_image_id": "sha256:" + "b" * 64,
            "postgres_image_id": expected["postgres_image_id"],
            "destination_head": "300",
            "reference_manifest_sha256": expected["reference_manifest_sha256"],
            "source_catalog_sha256": expected["source_catalog_sha256"],
            "destination_catalog_sha256": expected["destination_catalog_sha256"],
            "seed_sha256": expected["seed_sha256"],
            "privileged_residue_sha256": expected["privileged_residue_sha256"],
            "source_alembic_version_sha256": expected[
                "source_alembic_version_sha256"
            ],
            "destination_alembic_version_sha256": expected[
                "destination_alembic_version_sha256"
            ],
            "runtime_invariants_sql_sha256": expected["runtime_invariants_sql_sha256"],
            "database_name": str(identity[0]),
            "database_oid": int(identity[1]),
            "database_owner": str(identity[2]),
            "postgres_system_identifier": str(identity[3]),
            "writer_fence_expires_at": "2999-01-01T00:00:00+00:00",
        }
        await asyncio.to_thread(
            fence.write_text,
            json.dumps(payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        await asyncio.to_thread(fence.chmod, 0o600)
        monkeypatch.setattr(module, "_FENCE_PATH", fence)
        monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
        monkeypatch.setenv("KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE", "production")
        monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)
        monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
        monkeypatch.setenv(
            "KOR_TRAVEL_MAP_APPLICATION_FRESH_MIGRATE_IMAGE_ID",
            "sha256:" + "b" * 64,
        )

        probe_command = ["probe-missing", "--operation-id", str(operation_id)]
        assert await module.async_main(probe_command) == 0
        missing = json.loads(capsys.readouterr().out)
        assert missing["schema"].endswith("root-missing-receipt.v1")
        assert missing["outcome"] == "receipt-missing-exact-prestate"
        assert missing["operation_id"] == str(operation_id)
        assert missing["database_identity"] == {
            "database_name": str(identity[0]),
            "database_oid": int(identity[1]),
            "database_owner": str(identity[2]),
            "postgres_system_identifier": str(identity[3]),
        }
        assert missing["expected_post_source_catalog_sha256"] == expected[
            "source_catalog_sha256"
        ]
        assert missing["expected_post_seed_sha256"] == expected["seed_sha256"]
        assert missing["expected_post_destination_alembic_version_sha256"] == expected[
            "destination_alembic_version_sha256"
        ]

        engine = make_async_engine(admin_dsn, pool_size=1)
        try:
            # Large objects are database-wide and do not appear in the application
            # schema relation/procedure/type inventory.  A PUBLIC ACL must still make
            # the exact fresh-root probe fail closed.
            async with engine.begin() as connection:
                await connection.execute(text("SELECT lo_create(424242)"))
                await connection.execute(
                    text("GRANT SELECT ON LARGE OBJECT 424242 TO PUBLIC")
                )
            assert await module.async_main(probe_command) == 1
            assert "pre-root state is not exact" in capsys.readouterr().err
            async with engine.begin() as connection:
                await connection.execute(text("SELECT lo_unlink(424242)"))

            async with engine.begin() as connection:
                await connection.execute(text("CREATE TABLE ops.foreign_pre_root_drift(id bigint)"))
            assert await module.async_main(probe_command) == 1
            assert "pre-root state is not exact" in capsys.readouterr().err
            async with engine.begin() as connection:
                await connection.execute(text("DROP TABLE ops.foreign_pre_root_drift"))
        finally:
            await engine.dispose()
        assert await module.async_main(probe_command) == 0
        assert json.loads(capsys.readouterr().out)["outcome"] == (
            "receipt-missing-exact-prestate"
        )

        migrate_command = ["migrate", "--writer-fence-receipt", str(fence)]
        assert await module.async_main(migrate_command) == 0
        migrated = json.loads(capsys.readouterr().out)
        assert migrated["operation_id"] == str(operation_id)

        assert await module.async_main(
            ["recover", "--operation-id", str(operation_id)]
        ) == 0
        recovered = json.loads(capsys.readouterr().out)
        assert recovered == migrated
        assert await module.async_main(probe_command) == 1
        assert "existing operation receipt" in capsys.readouterr().err

        engine = make_async_engine(admin_dsn, pool_size=1)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                with pytest.raises(DBAPIError, match="append-only"):
                    await connection.execute(
                        text(
                            "UPDATE ops.application_schema_operation_receipts "
                            "SET journal_generation = journal_generation + 1 "
                            "WHERE operation_id = :operation_id"
                        ),
                        {"operation_id": operation_id},
                    )
                await transaction.rollback()
        finally:
            await engine.dispose()
    finally:
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')

"""fresh ``300``의 late runtime-ACL failure completion 경계."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text

from kortravelmap.infra.application_schema_head import application_schema_head
from tests.integration._application_300_bootstrap import (
    upgrade_head_with_application_300_bootstrap,
)
from tests.integration.test_alembic_metadata_consistency import (
    _admin_execute,
    _raw_version,
    _with_database,
)

pytestmark = pytest.mark.integration

#: fresh 설치는 `upgrade(head)`로 끝나므로 기대값은 파생 head다.
_EXPECTED_HEAD = application_schema_head()

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "docker" / "application-schema-fresh-finalize.py"


@pytest.fixture
def safe_fence_directory() -> Iterator[Path]:
    """NTFS pytest 임시 경로와 분리된 private Linux fence 디렉터리."""

    path = Path(tempfile.mkdtemp(prefix="ktm-fresh-finalize-", dir="/tmp"))
    try:
        yield path
    finally:
        shutil.rmtree(path)


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
) -> dict[str, object]:
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
        "schema": "kor-travel-docker-manager.map-fresh-300-finalize-fence.v3",
        "transaction_id": str(uuid4()),
        "operation_id": str(uuid4()),
        "journal_sha256": "c" * 64,
        "journal_generation": 2,
        "operation": "map-fresh-300-finalize",
        "prior_fresh_migration_result_sha256": "d" * 64,
        "prior_fresh_migration_fence_sha256": "e" * 64,
        "prior_fresh_migration_transaction_id": str(uuid4()),
        "prior_fresh_migration_operation_id": str(uuid4()),
        "prior_fresh_migration_journal_sha256": "f" * 64,
        "prior_fresh_migration_generation": 1,
        "map_candidate_commit": "a" * 40,
        "map_candidate_image_id": "sha256:" + "b" * 64,
        "postgres_image_id": expected["postgres_image_id"],
        "destination_head": _EXPECTED_HEAD,
        "reference_manifest_sha256": expected["reference_manifest_sha256"],
        "source_catalog_sha256": expected["source_catalog_sha256"],
        "destination_catalog_sha256": expected["destination_catalog_sha256"],
        "seed_sha256": expected["seed_sha256"],
        "privileged_residue_sha256": expected["privileged_residue_sha256"],
        "pre_privileged_residue_sha256": expected["privileged_residue_sha256"],
        "destination_alembic_version_sha256": expected[
            "destination_alembic_version_sha256"
        ],
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
    return payload


async def _insert_prior_root_receipt(
    module: ModuleType,
    admin_dsn: str,
    fence: dict[str, object],
) -> None:
    """production root one-shot이 남기는 append-only row를 fixture에도 결박한다."""

    from kortravelmap.infra.db import make_async_engine

    database_identity = {
        "database_name": fence["database_name"],
        "database_oid": fence["database_oid"],
        "database_owner": fence["database_owner"],
        "postgres_system_identifier": fence["postgres_system_identifier"],
    }
    payload = {
        "schema": "kor-travel-map.application-fresh-300-root.v2",
        "outcome": "root-committed",
        "authorization": "manager-fence",
        "operation_id": fence["prior_fresh_migration_operation_id"],
        "destination_head": _EXPECTED_HEAD,
        "map_candidate_commit": fence["map_candidate_commit"],
        "map_candidate_image_id": fence["map_candidate_image_id"],
        "postgres_image_id": fence["postgres_image_id"],
        "reference_manifest_sha256": fence["reference_manifest_sha256"],
        "writer_fence_receipt_sha256": fence[
            "prior_fresh_migration_fence_sha256"
        ],
        "writer_fence_transaction_id": fence[
            "prior_fresh_migration_transaction_id"
        ],
        "journal_sha256": fence["prior_fresh_migration_journal_sha256"],
        "journal_generation": fence["prior_fresh_migration_generation"],
        "database_identity": database_identity,
        "post_source_catalog_sha256": fence["source_catalog_sha256"],
        "post_seed_sha256": fence["seed_sha256"],
        "expected_privileged_residue_sha256": fence[
            "privileged_residue_sha256"
        ],
        "expected_destination_alembic_version_sha256": fence[
            "destination_alembic_version_sha256"
        ],
        "post_destination_alembic_version_sha256": fence[
            "destination_alembic_version_sha256"
        ],
    }
    canonical = module._canonical_result_bytes(payload)
    result_sha256 = module.hashlib.sha256(canonical).hexdigest()
    fence["prior_fresh_migration_result_sha256"] = result_sha256
    await asyncio.to_thread(
        module._FENCE_PATH.write_text,
        json.dumps(fence, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    await asyncio.to_thread(module._FENCE_PATH.chmod, 0o600)
    engine = make_async_engine(admin_dsn, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO ops.application_schema_operation_receipts ("
                    "operation_id, operation, result_schema, result_sha256, "
                    "map_candidate_commit, map_candidate_image_id, postgres_image_id, "
                    "writer_fence_receipt_sha256, journal_sha256, journal_generation, "
                    "destination_head, database_name, database_oid, database_owner, "
                    "postgres_system_identifier, result_payload) VALUES ("
                    "CAST(:operation_id AS uuid), 'application-root-300', "
                    "'kor-travel-map.application-fresh-300-root.v2', :result_sha256, "
                    ":map_commit, :map_image, :postgres_image, :fence_sha256, "
                    ":journal_sha256, :journal_generation, '300', :database_name, "
                    ":database_oid, :database_owner, :system_identifier, "
                    "CAST(:result_payload AS jsonb))"
                ),
                {
                    "operation_id": fence["prior_fresh_migration_operation_id"],
                    "result_sha256": result_sha256,
                    "map_commit": fence["map_candidate_commit"],
                    "map_image": fence["map_candidate_image_id"],
                    "postgres_image": fence["postgres_image_id"],
                    "fence_sha256": fence["prior_fresh_migration_fence_sha256"],
                    "journal_sha256": fence[
                        "prior_fresh_migration_journal_sha256"
                    ],
                    "journal_generation": fence[
                        "prior_fresh_migration_generation"
                    ],
                    **database_identity,
                    "system_identifier": fence["postgres_system_identifier"],
                    "result_payload": canonical.decode().rstrip("\n"),
                },
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_fresh_finalize_retries_only_fixed_raw_300_completion_after_late_acl_failure(
    fresh_300_database: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    safe_fence_directory: Path,
) -> None:
    """ACL transaction late failure 뒤에도 raw 300을 generic migration 없이 completion한다."""

    admin_dsn, migrator_dsn = fresh_300_database
    module = _finalize_module()
    fence = safe_fence_directory / "fence.json"
    fence_payload = await _write_fence(module, admin_dsn, fence, monkeypatch)
    await _insert_prior_root_receipt(module, admin_dsn, fence_payload)
    monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)
    assert await module.async_main(
        ["probe-missing", "--operation-id", str(fence_payload["operation_id"])]
    ) == 0
    missing = json.loads(capsys.readouterr().out)
    assert missing["schema"].endswith("finalize-missing-receipt.v1")
    assert missing["outcome"] == "receipt-missing-exact-prestate"
    assert missing["prior_fresh_migration_result_sha256"] == fence_payload[
        "prior_fresh_migration_result_sha256"
    ]
    original_reconcile = module.reconcile_runtime_privileges_in_transaction

    async def _late_acl_failure(_: object) -> None:
        raise RuntimeError("controlled runtime ACL late failure")

    monkeypatch.setattr(
        module,
        "reconcile_runtime_privileges_in_transaction",
        _late_acl_failure,
    )
    command = ["finalize", "--writer-fence-receipt", str(fence)]
    assert await module.async_main(command) == 1
    assert await _raw_version(admin_dsn) == (_EXPECTED_HEAD,)
    assert "runtime ACL reconciliation failed" in capsys.readouterr().err

    monkeypatch.setattr(
        module,
        "reconcile_runtime_privileges_in_transaction",
        original_reconcile,
    )
    original_receipts = module._assert_raw_300_and_receipts
    receipt_calls = 0

    async def _destination_postflight_failure(
        connection: object,
        expected: object,
        *,
        expected_catalog_sha256: str,
    ) -> tuple[str, str, str]:
        nonlocal receipt_calls
        receipt_calls += 1
        if receipt_calls == 2:
            raise module.FreshFinalizeError(
                "controlled destination catalog postflight failure"
            )
        return await original_receipts(
            connection,
            expected,
            expected_catalog_sha256=expected_catalog_sha256,
        )

    monkeypatch.setattr(
        module,
        "_assert_raw_300_and_receipts",
        _destination_postflight_failure,
    )
    assert await module.async_main(command) == 1
    assert await _raw_version(admin_dsn) == (_EXPECTED_HEAD,)
    assert "controlled destination catalog postflight failure" in capsys.readouterr().err

    # ACL reconcile가 성공한 뒤 postflight가 실패해도 같은 outer transaction이
    # source catalog로 rollback한다. 따라서 fixed finalizer를 그대로 재시도할 수 있다.
    monkeypatch.setattr(module, "_assert_raw_300_and_receipts", original_receipts)
    assert await module.async_main(command) == 0
    assert await _raw_version(admin_dsn) == (_EXPECTED_HEAD,)
    finalized = json.loads(capsys.readouterr().out)
    assert await module.async_main(
        ["recover", "--operation-id", finalized["operation_id"]]
    ) == 0
    assert json.loads(capsys.readouterr().out) == finalized
    assert await module.async_main(
        ["probe-missing", "--operation-id", finalized["operation_id"]]
    ) == 1
    assert "existing operation receipt" in capsys.readouterr().err

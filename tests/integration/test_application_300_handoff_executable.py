"""Docker Manager가 호출할 `0236 → 300` executable의 same-transaction gate."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
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
    _HANDOFF_SOURCE,
    _admin_execute,
    _prepare_logical_0236,
    _raw_version,
    _with_database,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "docker" / "transition-application-schema-0236-to-300.py"


def _handoff_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("application_300_handoff", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _writer_fence_receipt(
    module: ModuleType,
    admin_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Docker Manager-owned receipt shape를 integration DB identity에 strict bind한다."""

    from kortravelmap.infra.db import make_async_engine

    engine = make_async_engine(admin_dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        """
                        SELECT current_database(),
                               (SELECT oid FROM pg_catalog.pg_database
                                 WHERE datname = current_database()),
                               (SELECT datdba::regrole::text FROM pg_catalog.pg_database
                                 WHERE datname = current_database()),
                               (SELECT system_identifier::text
                                  FROM pg_catalog.pg_control_system())
                        """
                    )
                )
            ).one()
    finally:
        await engine.dispose()

    candidate_commit = "a" * 40
    candidate_image_id = "sha256:" + "b" * 64
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", candidate_commit)
    monkeypatch.setenv("KOR_TRAVEL_MAP_APPLICATION_HANDOFF_IMAGE_ID", candidate_image_id)
    expected = module._verify_reference_artifacts()
    payload = {
        "schema": "kor-travel-docker-manager.map-application-schema-handoff-fence.v1",
        "transaction_id": str(uuid4()),
        "journal_sha256": "c" * 64,
        "operation": "map-application-schema-0236-to-300",
        "map_candidate_commit": candidate_commit,
        "map_candidate_image_id": candidate_image_id,
        "source_head": _HANDOFF_SOURCE,
        "destination_head": "300",
        "reference_manifest_sha256": module._reference_manifest_sha256(),
        "catalog_sha256": expected["catalog_sha256"],
        "seed_sha256": expected["seed_sha256"],
        "database_name": str(row[0]),
        "database_oid": int(row[1]),
        "database_owner": str(row[2]),
        "postgres_system_identifier": str(row[3]),
        "writer_fence_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    path = tmp_path / "manager-fence-receipt.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


async def _contract_receipts(module: ModuleType, dsn: str) -> tuple[str, str]:
    """handoff와 같은 role/search_path에서 synthetic fixture의 contract를 관측한다."""

    from kortravelmap.infra.db import make_async_engine

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SET ROLE ktm_feature_schema_owner"))
            await connection.execute(text("SET search_path = public, x_extension"))
            return (
                await module._catalog_sha256(connection),
                await module._seed_sha256(connection),
            )
    finally:
        await engine.dispose()


@pytest.fixture
async def application_300_config(
    pg_container: object,
) -> AsyncIterator[tuple[Config, str]]:
    """executable 전용 fresh `300` DB를 만들고 teardown한다."""

    from kortravelmap.infra.db import normalize_async_dsn

    raw_dsn = pg_container.get_connection_url()  # type: ignore[attr-defined]
    database = f"application_300_executable_{uuid4().hex}"
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{database}"')
    admin_dsn = normalize_async_dsn(_with_database(raw_dsn, database))
    config = Config(str(_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", admin_dsn)
    try:
        await upgrade_head_with_application_300_bootstrap(config, admin_dsn)
        yield config, admin_dsn
    finally:
        await _admin_execute(raw_dsn, f'DROP DATABASE "{database}" WITH (FORCE)')


@pytest.mark.asyncio
async def test_handoff_executable_rejects_synthetic_0236_label_before_stamp(
    application_300_config: tuple[Config, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    config, admin_dsn = application_300_config
    await _prepare_logical_0236(config, admin_dsn)
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)

    module = _handoff_module()
    observed_catalog_sha256, observed_seed_sha256 = await _contract_receipts(
        module, migrator_dsn
    )

    expected_catalog_sha256 = module._expected_catalog_sha256()
    expected_seed_sha256 = module._expected_seed_sha256()
    # The fixture is a fresh `300` DB with only its raw version label changed.
    # It is not a runnable historical `0236` source, so CI must never use it as
    # a false positive transition proof. The independent source→fresh-oracle
    # protocol is the only positive handoff evidence.
    assert observed_catalog_sha256 != expected_catalog_sha256
    assert observed_seed_sha256 == expected_seed_sha256
    fence_receipt = await _writer_fence_receipt(
        module, admin_dsn, tmp_path, monkeypatch
    )

    assert await module.async_main(
        [
            "--confirm-0236-to-300",
            "--writer-fence-receipt",
            str(fence_receipt),
        ]
    ) == 1
    assert await _raw_version(admin_dsn) == (_HANDOFF_SOURCE,)
    assert "immutable 300 reference" in capsys.readouterr().err


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "contract_axis"),
    (
        ("GRANT SELECT (name) ON TABLE feature.features TO PUBLIC", "column ACL"),
        (
            "CREATE POLICY application_300_handoff_drift "
            "ON feature.features FOR SELECT TO PUBLIC USING (true)",
            "RLS policy",
        ),
        (
            "UPDATE ops.feature_override_field_paths "
            "SET provider_writable = false "
            "WHERE field_path = 'core.name'",
            "immutable seed",
        ),
    ),
)
async def test_handoff_executable_rejects_source_contract_drift_without_stamping(
    application_300_config: tuple[Config, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    mutation: str,
    contract_axis: str,
) -> None:
    """raw `0236` label만 맞춘 full catalog/seed drift는 metadata 변경 전 거부한다."""

    config, admin_dsn = application_300_config
    await _prepare_logical_0236(config, admin_dsn)
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)

    module = _handoff_module()
    before_catalog, before_seed = await _contract_receipts(module, migrator_dsn)
    await _admin_execute(admin_dsn, mutation)
    after_catalog, after_seed = await _contract_receipts(module, migrator_dsn)
    if contract_axis == "immutable seed":
        assert after_seed != before_seed
    else:
        assert after_catalog != before_catalog
    fence_receipt = await _writer_fence_receipt(
        module, admin_dsn, tmp_path, monkeypatch
    )
    assert await module.async_main(
        [
            "--confirm-0236-to-300",
            "--writer-fence-receipt",
            str(fence_receipt),
        ]
    ) == 1

    assert await _raw_version(admin_dsn) == (_HANDOFF_SOURCE,)
    error = capsys.readouterr().err
    assert "immutable 300 reference" in error, contract_axis


@pytest.mark.asyncio
async def test_mutable_provider_catalog_data_does_not_change_handoff_contract(
    application_300_config: tuple[Config, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """provider/curated 운영 데이터는 fresh seed이지 immutable handoff receipt가 아니다.

    Synthetic raw-0236 labels are intentionally rejected below. Actual positive
    handoff acceptance is proven only from the isolated historical source.
    """

    config, admin_dsn = application_300_config
    await _prepare_logical_0236(config, admin_dsn)
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)
    module = _handoff_module()
    before_catalog, before_seed = await _contract_receipts(module, migrator_dsn)
    await _admin_execute(
        admin_dsn,
        """
        UPDATE provider_sync.provider_datasets
        SET display_name = display_name || ' (operator-updated)'
        WHERE provider_dataset_id = (
            SELECT min(provider_dataset_id)
            FROM provider_sync.provider_datasets
        )
        """,
    )
    after_catalog, after_seed = await _contract_receipts(module, migrator_dsn)
    assert after_catalog == before_catalog
    assert after_seed == before_seed
    fence_receipt = await _writer_fence_receipt(
        module, admin_dsn, tmp_path, monkeypatch
    )

    assert await module.async_main(
        [
            "--confirm-0236-to-300",
            "--writer-fence-receipt",
            str(fence_receipt),
        ]
    ) == 1
    assert await _raw_version(admin_dsn) == (_HANDOFF_SOURCE,)
    assert "immutable 300 reference" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_handoff_rejects_superuser_even_with_a_valid_manager_receipt(
    application_300_config: tuple[Config, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """`SET ROLE` 이전 session_user gate가 superuser direct execution을 막는다."""

    config, admin_dsn = application_300_config
    await _prepare_logical_0236(config, admin_dsn)
    module = _handoff_module()
    fence_receipt = await _writer_fence_receipt(
        module, admin_dsn, tmp_path, monkeypatch
    )
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", admin_dsn)

    assert await module.async_main(
        [
            "--confirm-0236-to-300",
            "--writer-fence-receipt",
            str(fence_receipt),
        ]
    ) == 1
    assert await _raw_version(admin_dsn) == (_HANDOFF_SOURCE,)
    assert "must connect as ktm_feature_migrator" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_handoff_rejects_expired_or_wrong_database_manager_receipt(
    application_300_config: tuple[Config, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """expiry와 DB identity는 metadata transaction 전에 fail-close여야 한다."""

    config, admin_dsn = application_300_config
    await _prepare_logical_0236(config, admin_dsn)
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)
    module = _handoff_module()
    fence_receipt = await _writer_fence_receipt(
        module, admin_dsn, tmp_path, monkeypatch
    )
    payload = json.loads(fence_receipt.read_text(encoding="utf-8"))
    payload["writer_fence_expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    fence_receipt.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    fence_receipt.chmod(0o600)

    assert await module.async_main(
        [
            "--confirm-0236-to-300",
            "--writer-fence-receipt",
            str(fence_receipt),
        ]
    ) == 1
    assert await _raw_version(admin_dsn) == (_HANDOFF_SOURCE,)
    assert "has expired" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_catalog_receipt_distinguishes_permissive_and_restrictive_rls_policy(
    application_300_config: tuple[Config, str],
) -> None:
    """같은 policy 이름·role·식이어도 RLS 결합 의미를 receipt가 구별한다."""

    config, admin_dsn = application_300_config
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    module = _handoff_module()
    from kortravelmap.infra.db import make_async_engine

    async def catalog_receipt() -> str:
        engine = make_async_engine(migrator_dsn, pool_size=1)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("SET ROLE ktm_feature_schema_owner"))
                await connection.execute(text("SET search_path = public, x_extension"))
                return await module._catalog_sha256(connection)
        finally:
            await engine.dispose()

    baseline = await catalog_receipt()
    await _admin_execute(
        admin_dsn,
        "CREATE POLICY application_300_policy_mode "
        "ON feature.features AS PERMISSIVE FOR SELECT TO PUBLIC USING (true)",
    )
    permissive = await catalog_receipt()
    await _admin_execute(
        admin_dsn,
        "DROP POLICY application_300_policy_mode ON feature.features; "
        "CREATE POLICY application_300_policy_mode "
        "ON feature.features AS RESTRICTIVE FOR SELECT TO PUBLIC USING (true)",
    )
    restrictive = await catalog_receipt()

    assert baseline != permissive
    assert permissive != restrictive


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "reset", "failure"),
    (
        (
            "ALTER ROLE ktm_feature_api_runtime CONNECTION LIMIT 1",
            "ALTER ROLE ktm_feature_api_runtime CONNECTION LIMIT -1",
            "role attributes",
        ),
        (
            "ALTER ROLE ktm_feature_api_runtime VALID UNTIL '2030-01-01 00:00:00+00'",
            "ALTER ROLE ktm_feature_api_runtime VALID UNTIL 'infinity'",
            "role attributes",
        ),
        (
            "ALTER ROLE ktm_feature_api_runtime SET statement_timeout TO '1s'",
            "ALTER ROLE ktm_feature_api_runtime RESET statement_timeout",
            "role settings",
        ),
    ),
)
async def test_handoff_final_role_contract_rejects_nondefault_role_policy(
    application_300_config: tuple[Config, str],
    mutation: str,
    reset: str,
    failure: str,
) -> None:
    """source stamp 전에 connection/expiry/global role setting drift를 막는다."""

    _config, admin_dsn = application_300_config
    module = _handoff_module()
    from kortravelmap.infra.db import make_async_engine

    engine = make_async_engine(admin_dsn, pool_size=1)
    try:
        async with engine.begin() as connection:
            await module._verify_final_role_contract(connection)
            await connection.execute(text(mutation))
            with pytest.raises(module.HandoffError, match=failure):
                await module._verify_final_role_contract(connection)
            await connection.execute(text(reset))
            await module._verify_final_role_contract(connection)
    finally:
        await engine.dispose()

"""Docker Manager가 호출할 `0236 → 300` executable의 same-transaction gate."""

from __future__ import annotations

import importlib.util
import json
import os
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


def _write_private_fence(payload: dict[str, object]) -> Path:
    """NTFS pytest tmp 대신 실제 Linux mode를 보존하는 private fence를 쓴다."""

    fence_dir = Path("/tmp/kor-travel-map-handoff-tests")
    fence_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fence_dir.chmod(0o700)
    path = fence_dir / f"manager-fence-receipt-{uuid4().hex}.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


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
    # Production one-shot의 root-owned capability + Alembic guard는 container rehearsal이
    # 실제로 검증한다. 일반 개발 사용자로 도는 integration process에서는 같은 outer
    # transaction의 version-row mutation만 test double로 대체해 catalog/ACL rollback을
    # 계속 검증한다.
    if os.geteuid() != 0:
        def _stamp_version_row(sync_connection: object, config: object) -> None:
            del config
            sync_connection.execute(text("DELETE FROM public.alembic_version"))  # type: ignore[attr-defined]
            sync_connection.execute(  # type: ignore[attr-defined]
                text("INSERT INTO public.alembic_version (version_num) VALUES ('300')")
            )

        monkeypatch.setattr(module, "_stamp_on_existing_connection", _stamp_version_row)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", candidate_commit)
    monkeypatch.setenv("KOR_TRAVEL_MAP_APPLICATION_HANDOFF_IMAGE_ID", candidate_image_id)
    expected = module._verify_reference_artifacts()
    observed_privileged_residue = await _privileged_residue_receipt(module, admin_dsn)
    payload = {
        "schema": "kor-travel-docker-manager.map-application-schema-handoff-fence.v6",
        "transaction_id": str(uuid4()),
        "journal_sha256": "c" * 64,
        "journal_generation": 1,
        "operation": "map-application-schema-0236-to-300",
        "map_candidate_commit": candidate_commit,
        "map_candidate_image_id": candidate_image_id,
        "postgres_image_id": module._reference_manifest()["source"]["container_image_id"],
        "source_head": _HANDOFF_SOURCE,
        "destination_head": "300",
        "reference_manifest_sha256": module._reference_manifest_sha256(),
        "source_catalog_sha256": expected["source_catalog_sha256"],
        "destination_catalog_sha256": expected["destination_catalog_sha256"],
        "seed_sha256": expected["seed_sha256"],
        "privileged_residue_sha256": expected["privileged_residue_sha256"],
        "pre_privileged_residue_sha256": observed_privileged_residue,
        "source_alembic_version_sha256": expected[
            "source_alembic_version_sha256"
        ],
        "destination_alembic_version_sha256": expected[
            "destination_alembic_version_sha256"
        ],
        "runtime_invariants_sql_sha256": expected["runtime_invariants_sql_sha256"],
        "database_name": str(row[0]),
        "database_oid": int(row[1]),
        "database_owner": str(row[2]),
        "postgres_system_identifier": str(row[3]),
        "writer_fence_expires_at": (datetime.now(UTC) + timedelta(minutes=5)).isoformat(),
    }
    # Codex/Windows pytest tmp_path는 NTFS metadata translation 때문에 chmod(0600)가
    # 실제 Linux mode로 반영되지 않는다. production helper의 strict mode gate를
    # 약화하지 않고 검증하려면 fence만 private Linux tmpfs에 둔다.
    return _write_private_fence(payload)


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


async def _privileged_residue_receipt(module: ModuleType, dsn: str) -> str:
    """Manager/database-superuser 축만 읽는 secret-free residue receipt를 관측한다."""

    from kortravelmap.infra.db import make_async_engine

    engine = make_async_engine(dsn, pool_size=1)
    try:
        async with engine.connect() as connection:
            return await module._contract_sha256(
                connection, module._PRIVILEGED_RESIDUE_CONTRACT_SQL
            )
    finally:
        await engine.dispose()


async def _database_identity(dsn: str) -> tuple[str, int, str, str]:
    """post-stamp rollback가 raw revision뿐 아니라 database binding도 보존하는지 읽는다."""

    from kortravelmap.infra.db import make_async_engine

    engine = make_async_engine(dsn, pool_size=1)
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
    return str(row[0]), int(row[1]), str(row[2]), str(row[3])


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
async def test_handoff_executable_accepts_exact_source_contract(
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

    expected_catalog_sha256 = module._expected_source_catalog_sha256()
    expected_seed_sha256 = module._expected_seed_sha256()
    # Source 정본은 migration lineage가 아니라 exact physical catalog/seed facet이다.
    # fresh root에서 destination ACL을 적용하기 전 상태는 실제 0236 source와 물리적으로
    # 같아야 하며, 이 동등성은 별도 source→fresh oracle이 독립적으로 증명한다.
    assert observed_catalog_sha256 == expected_catalog_sha256
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
    ) == 0
    assert await _raw_version(admin_dsn) == ("300",)
    result = json.loads(capsys.readouterr().out)
    assert result["pre_catalog_sha256"] == expected_catalog_sha256
    assert result["post_catalog_sha256"] == module._expected_destination_catalog_sha256()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "contract_axis"),
    [
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
        (
            "CREATE TEXT SEARCH CONFIGURATION public.application_300_handoff_drift "
            "(PARSER = pg_catalog.default)",
            "public text search configuration",
        ),
        (
            "CREATE INDEX application_300_handoff_version_drift "
            "ON public.alembic_version (version_num)",
            "public Alembic extra index",
        ),
        (
            "GRANT SELECT (version_num) ON TABLE public.alembic_version TO PUBLIC",
            "public Alembic column ACL",
        ),
        (
            "GRANT USAGE ON TYPE public.alembic_version TO PUBLIC",
            "public Alembic row type ACL",
        ),
        (
            "GRANT USAGE ON TYPE public.alembic_version TO PUBLIC; "
            "REVOKE USAGE ON TYPE public.alembic_version FROM PUBLIC",
            "public Alembic row type explicit default ACL residue",
        ),
        (
            "ALTER TABLE public.alembic_version "
            "ADD COLUMN application_300_handoff_dropped integer; "
            "ALTER TABLE public.alembic_version "
            "DROP COLUMN application_300_handoff_dropped",
            "public Alembic dropped attribute slot",
        ),
        (
            "ALTER TABLE feature.features "
            "ADD COLUMN application_300_handoff_dropped integer; "
            "ALTER TABLE feature.features "
            "DROP COLUMN application_300_handoff_dropped",
            "application relation dropped attribute slot",
        ),
        (
            "GRANT USAGE ON LANGUAGE sql TO PUBLIC",
            "base procedural language ACL",
        ),
    ],
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
    """provider/curated 운영 데이터는 immutable handoff receipt가 아니다."""

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
    ) == 0
    assert await _raw_version(admin_dsn) == ("300",)
    assert json.loads(capsys.readouterr().out)["outcome"] == "stamped"


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
async def test_handoff_rolls_back_real_post_stamp_failure_to_exact_0236_state(
    application_300_config: tuple[Config, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """stamp 뒤 postflight가 실패해도 outer transaction은 source receipt를 보존한다.

    synthetic fixture는 source oracle의 full immutable catalog를 갖지 않으므로 첫
    preflight만 test-only expected receipt로 통과시킨다. 두 번째 call에서는 stamp가
    실제 raw ``300`` row를 쓴 것을 확인한 뒤 의도적으로 실패시켜, generic preflight
    failure가 아닌 **post-stamp** rollback 경계를 실행한다.
    """

    config, admin_dsn = application_300_config
    await _prepare_logical_0236(config, admin_dsn)
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)
    module = _handoff_module()
    fence_receipt = await _writer_fence_receipt(
        module, admin_dsn, tmp_path, monkeypatch
    )
    before_catalog, before_seed = await _contract_receipts(module, migrator_dsn)
    before_privileged = await _privileged_residue_receipt(module, admin_dsn)
    before_identity = await _database_identity(admin_dsn)
    expected = module._verify_reference_artifacts()
    first_preflight = True

    async def _controlled_post_stamp_failure(
        connection: object, *, expected_head: str
    ) -> dict[str, str]:
        nonlocal first_preflight
        if first_preflight:
            first_preflight = False
            assert expected_head == _HANDOFF_SOURCE
            return {
                "catalog_sha256": expected["source_catalog_sha256"],
                "seed_sha256": expected["seed_sha256"],
                "alembic_version_sha256": expected[
                    "source_alembic_version_sha256"
                ],
            }
        assert expected_head == "300"
        assert await module._raw_version(connection) == ("300",)
        raise module.HandoffError("controlled post-stamp rollback probe")

    monkeypatch.setattr(module, "_preflight", _controlled_post_stamp_failure)
    assert await module.async_main(
        [
            "--confirm-0236-to-300",
            "--writer-fence-receipt",
            str(fence_receipt),
        ]
    ) == 1

    assert first_preflight is False
    assert await _raw_version(admin_dsn) == (_HANDOFF_SOURCE,)
    assert await _contract_receipts(module, migrator_dsn) == (before_catalog, before_seed)
    assert await _privileged_residue_receipt(module, admin_dsn) == before_privileged
    assert await _database_identity(admin_dsn) == before_identity
    assert "controlled post-stamp rollback probe" in capsys.readouterr().err


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
async def test_catalog_receipt_is_stable_under_nondefault_deparse_session_gucs(
    application_300_config: tuple[Config, str],
) -> None:
    """caller DSN의 formatting GUC가 동일 catalog receipt를 바꾸면 안 된다."""

    config, _admin_dsn = application_300_config
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    module = _handoff_module()
    from kortravelmap.infra.db import make_async_engine

    engine = make_async_engine(migrator_dsn, pool_size=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("SET ROLE ktm_feature_schema_owner"))
            await connection.execute(text("SET search_path = public, x_extension"))
            baseline = await module._catalog_sha256(connection)
            for statement in (
                "SET LOCAL quote_all_identifiers TO on",
                "SET LOCAL DateStyle TO 'SQL, DMY'",
                "SET LOCAL IntervalStyle TO 'sql_standard'",
                "SET LOCAL TimeZone TO 'Asia/Seoul'",
                "SET LOCAL extra_float_digits TO 0",
                "SET LOCAL bytea_output TO 'escape'",
                "SET LOCAL standard_conforming_strings TO off",
                "SET LOCAL xmlbinary TO 'hex'",
            ):
                await connection.execute(text(statement))
            assert await module._catalog_sha256(connection) == baseline
            assert await connection.scalar(text("SHOW quote_all_identifiers")) == "off"
            assert await connection.scalar(text("SHOW TimeZone")) == "UTC"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_catalog_receipt_handles_text_search_parser_template_and_mapping(
    application_300_config: tuple[Config, str],
) -> None:
    """text-search parser/template OID는 regproc가 아니라 their catalog namespace/name이다."""

    config, admin_dsn = application_300_config
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    module = _handoff_module()
    baseline, _ = await _contract_receipts(module, migrator_dsn)
    configuration = "application_300_catalog_configuration"
    dictionary = "application_300_catalog_dictionary"
    try:
        await _admin_execute(
            admin_dsn,
            f"CREATE TEXT SEARCH DICTIONARY feature.{dictionary} "
            "(TEMPLATE = pg_catalog.simple, STOPWORDS = english); "
            f"CREATE TEXT SEARCH CONFIGURATION feature.{configuration} "
            "(PARSER = pg_catalog.default); "
            f"ALTER TEXT SEARCH CONFIGURATION feature.{configuration} "
            f"ADD MAPPING FOR asciiword WITH feature.{dictionary};",
        )
        changed, _ = await _contract_receipts(module, migrator_dsn)
        assert changed != baseline
    finally:
        await _admin_execute(
            admin_dsn,
            f"DROP TEXT SEARCH CONFIGURATION IF EXISTS feature.{configuration}; "
            f"DROP TEXT SEARCH DICTIONARY IF EXISTS feature.{dictionary};",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mutation", "reset", "failure"),
    [
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
    ],
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


@pytest.mark.asyncio
async def test_catalog_receipt_tracks_row_type_acl_and_composite_attribute_definition(
    application_300_config: tuple[Config, str],
) -> None:
    """grantable table row type와 composite layout은 relation receipt의 독립 축이다."""

    config, admin_dsn = application_300_config
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    module = _handoff_module()
    baseline, _ = await _contract_receipts(module, migrator_dsn)
    composite = "application_300_receipt_composite"
    try:
        await _admin_execute(admin_dsn, "GRANT USAGE ON TYPE feature.features TO PUBLIC")
        row_type_acl, _ = await _contract_receipts(module, migrator_dsn)
        assert row_type_acl != baseline

        await _admin_execute(admin_dsn, "REVOKE USAGE ON TYPE feature.features FROM PUBLIC")
        explicit_default_acl_residue, _ = await _contract_receipts(module, migrator_dsn)
        assert explicit_default_acl_residue != baseline

        await _admin_execute(
            admin_dsn,
            f"CREATE TYPE feature.{composite} AS (label text, ordinal integer)",
        )
        composite_created, _ = await _contract_receipts(module, migrator_dsn)
        assert composite_created != explicit_default_acl_residue

        await _admin_execute(
            admin_dsn,
            f"ALTER TYPE feature.{composite} ADD ATTRIBUTE category text",
        )
        composite_attribute_changed, _ = await _contract_receipts(module, migrator_dsn)
        assert composite_attribute_changed != composite_created
    finally:
        await _admin_execute(admin_dsn, f"DROP TYPE IF EXISTS feature.{composite}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role_attributes", ["NOLOGIN", "LOGIN", "SUPERUSER NOLOGIN"]
)
async def test_handoff_rejects_any_application_prefixed_role_before_stamp(
    application_300_config: tuple[Config, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    role_attributes: str,
) -> None:
    """열거되지 않은 ``ktm_*`` principal은 LOGIN 여부와 무관하게 source stamp 전 거절한다.

    reserved role inventory는 known 21개로 exact해야 한다. 이를 3가지 attribute class로
    확인해 unlisted NOLOGIN/LOGIN/superuser가 catalog/ownership guard 밖으로 빠지는 것을
    막는다. 이 경우 outer transaction은 raw ``0236`` row를 그대로 보존해야 한다.
    """

    config, admin_dsn = application_300_config
    await _prepare_logical_0236(config, admin_dsn)
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)

    module = _handoff_module()
    fence_receipt = await _writer_fence_receipt(
        module, admin_dsn, tmp_path, monkeypatch
    )
    role_name = "ktm_application_role_bypass"
    await _admin_execute(admin_dsn, f"CREATE ROLE {role_name} {role_attributes}")
    try:
        assert await module.async_main(
            [
                "--confirm-0236-to-300",
                "--writer-fence-receipt",
                str(fence_receipt),
            ]
        ) == 1
        assert await _raw_version(admin_dsn) == (_HANDOFF_SOURCE,)
        assert "reserved application role inventory" in capsys.readouterr().err
    finally:
        await _admin_execute(admin_dsn, f"DROP ROLE {role_name}")


@pytest.mark.asyncio
async def test_handoff_rejects_manager_observed_hidden_user_mapping_before_stamp(
    application_300_config: tuple[Config, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """migrator 권한을 넓히지 않고 특권 mapping residue를 fence에서 거부한다.

    `pg_user_mapping`은 schema-owner session의 catalog receipt에서 완전하게 보이지
    않는다. Manager가 superuser session으로 관측한 secret-free count digest가 immutable
    zero baseline과 다르면 controlled stamp보다 먼저 raw ``0236``을 보존하며 거부해야 한다.
    """

    config, admin_dsn = application_300_config
    await _prepare_logical_0236(config, admin_dsn)
    migrator_dsn = config.get_main_option("sqlalchemy.url")
    assert migrator_dsn is not None
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", migrator_dsn)

    module = _handoff_module()
    wrapper = "handoff_privileged_residue_fdw"
    server = "handoff_privileged_residue_server"
    await _admin_execute(
        admin_dsn,
        f"CREATE FOREIGN DATA WRAPPER {wrapper} NO HANDLER NO VALIDATOR; "
        f"CREATE SERVER {server} FOREIGN DATA WRAPPER {wrapper}; "
        "CREATE USER MAPPING FOR ktm_feature_api_runtime "
        f"SERVER {server} OPTIONS (user 'opaque');",
    )
    try:
        observed_privileged_residue = await _privileged_residue_receipt(module, admin_dsn)
        assert observed_privileged_residue != module._verify_reference_artifacts()[
            "privileged_residue_sha256"
        ]
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
        assert "baseline contract" in capsys.readouterr().err
    finally:
        await _admin_execute(
            admin_dsn,
            f"DROP USER MAPPING FOR ktm_feature_api_runtime SERVER {server}; "
            f"DROP SERVER {server}; DROP FOREIGN DATA WRAPPER {wrapper};",
        )

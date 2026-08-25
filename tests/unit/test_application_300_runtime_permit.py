"""`300` production final permit과 fresh migration executable의 정적 경계."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str, relative: str):
    path = _ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _valid_permit(module: object) -> dict[str, object]:
    reference_sha256, reference = module._read_reference()
    artifacts = reference["artifacts"]
    system_identifier = "1234567890"
    database_name = "kor_travel_map"
    database_oid = 16384
    database_owner = "ktm_feature_schema_owner"
    return {
        "schema": "kor-travel-docker-manager.map-application-final-permit.v4",
        "transition_kind": "map-fresh-300-finalize",
        "state": "finalized",
        "transaction_id": "b93bb7cf-7901-4790-88a8-2a7bbc07f3b7",
        "candidate": {
            "map_source_commit": "a" * 40,
            "api_image_id": "sha256:" + "b" * 64,
            "dagster_image_id": "sha256:" + "c" * 64,
            "postgres_image_id": reference["source"]["container_image_id"],
            "application_head": "300",
            "reference_manifest_sha256": reference_sha256,
            "source_alembic_version_sha256": artifacts[
                "source_alembic_version_contract_sha256"
            ],
            "destination_alembic_version_sha256": artifacts[
                "destination_alembic_version_contract_sha256"
            ],
            "runtime_invariants_sql_sha256": artifacts["runtime_invariants_sql_sha256"],
        },
        "database": {
            "name": database_name,
            "oid": database_oid,
            "owner": database_owner,
            "system_identifier": system_identifier,
            "identity_sha256": module._database_identity_sha256(
                system_identifier=system_identifier,
                name=database_name,
                oid=database_oid,
                owner=database_owner,
            ),
        },
        "receipts": {
            "expected_catalog_sha256": artifacts[
                "destination_catalog_contract_sha256"
            ],
            "observed_catalog_sha256": artifacts[
                "destination_catalog_contract_sha256"
            ],
            "expected_seed_sha256": artifacts["seed_contract_sha256"],
            "observed_seed_sha256": artifacts["seed_contract_sha256"],
            "expected_privileged_residue_sha256": artifacts[
                "privileged_residue_contract_sha256"
            ],
            "pre_privileged_residue_sha256": artifacts[
                "privileged_residue_contract_sha256"
            ],
            "post_privileged_residue_sha256": artifacts[
                "privileged_residue_contract_sha256"
            ],
            "expected_destination_alembic_version_sha256": artifacts[
                "destination_alembic_version_contract_sha256"
            ],
            "observed_destination_alembic_version_sha256": artifacts[
                "destination_alembic_version_contract_sha256"
            ],
            "runtime_invariant_violation_count": 0,
        },
        "operation_evidence": {
            "schema": (
                "kor-travel-docker-manager."
                "map-final-permit-fresh-finalize-evidence.v2"
            ),
            "journal_sha256": "d" * 64,
            "journal_generation": 2,
            "finalize_result_sha256": "e" * 64,
            "finalize_fence_receipt_sha256": "f" * 64,
            "finalize_fence_transaction_id": (
                "b93bb7cf-7901-4790-88a8-2a7bbc07f3b7"
            ),
            "prior_fresh_migration_result_sha256": "1" * 64,
            "prior_fresh_migration_fence_sha256": "2" * 64,
            "prior_fresh_migration_transaction_id": (
                "b93bb7cf-7901-4790-88a8-2a7bbc07f3b8"
            ),
            "prior_fresh_migration_journal_sha256": "3" * 64,
            "prior_fresh_migration_generation": 1,
            "pre_source_catalog_sha256": artifacts[
                "source_catalog_contract_sha256"
            ],
            "post_destination_catalog_sha256": artifacts[
                "destination_catalog_contract_sha256"
            ],
            "post_destination_alembic_version_sha256": artifacts[
                "destination_alembic_version_contract_sha256"
            ],
        },
    }


def test_final_permit_binds_candidate_baseline_and_full_database_preimage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """name/OID만 같은 다른 cluster가 final permit을 재사용할 수 없어야 한다."""

    module = _load_script(
        "application_schema_final_permit",
        "docker/application-schema-final-permit.py",
    )
    payload = _valid_permit(module)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_API_IMAGE_ID", "sha256:" + "b" * 64
    )

    assert module._validate_permit(json.dumps(payload).encode("utf-8"), consumer="api")[
        "state"
    ] == "finalized"

    payload["database"]["system_identifier"] = "9999999999"
    with pytest.raises(module.FinalPermitError, match="candidate|database"):
        module._validate_permit(json.dumps(payload).encode("utf-8"), consumer="api")


def test_final_permit_rejects_post_privileged_receipt_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """post-superuser receipt은 final permit에서 expected value와 같아야 한다."""

    module = _load_script(
        "application_schema_final_permit_post",
        "docker/application-schema-final-permit.py",
    )
    payload = _valid_permit(module)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_API_IMAGE_ID", "sha256:" + "b" * 64
    )
    payload["receipts"]["post_privileged_residue_sha256"] = "c" * 64

    with pytest.raises(module.FinalPermitError, match="receipt"):
        module._validate_permit(json.dumps(payload).encode("utf-8"), consumer="api")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("database", "oid"), False),
        (("receipts", "runtime_invariant_violation_count"), False),
        (("receipts", "runtime_invariant_violation_count"), True),
    ],
)
def test_final_permit_rejects_boolean_json_scalars(
    monkeypatch: pytest.MonkeyPatch,
    path: tuple[str, str],
    value: bool,
) -> None:
    """JSON bool은 Python int subclass여도 fixed permit의 numeric field가 아니다."""

    module = _load_script(
        "application_schema_final_permit_scalar_types",
        "docker/application-schema-final-permit.py",
    )
    payload = _valid_permit(module)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_API_IMAGE_ID", "sha256:" + "b" * 64
    )
    payload[path[0]][path[1]] = value

    with pytest.raises(module.FinalPermitError, match="database identity|runtime invariant"):
        module._validate_permit(json.dumps(payload).encode("utf-8"), consumer="api")


def test_final_permit_binds_each_runtime_consumer_to_its_own_immutable_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API receipt를 Dagster image에, 또는 반대로 재사용할 수 없어야 한다."""

    module = _load_script(
        "application_schema_final_permit_dagster",
        "docker/application-schema-final-permit.py",
    )
    payload = _valid_permit(module)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_DAGSTER_IMAGE_ID", "sha256:" + "c" * 64
    )

    assert module._validate_permit(json.dumps(payload).encode("utf-8"), consumer="dagster")[
        "state"
    ] == "finalized"

    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_DAGSTER_IMAGE_ID", "sha256:" + "b" * 64
    )
    with pytest.raises(module.FinalPermitError, match="candidate"):
        module._validate_permit(json.dumps(payload).encode("utf-8"), consumer="dagster")


def test_final_permit_requires_fresh_finalize_operation_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fresh root만으로 permit을 내지 않고 mandatory finalize lineage를 요구한다."""

    module = _load_script(
        "application_schema_final_permit_fresh_finalize",
        "docker/application-schema-final-permit.py",
    )
    payload = _valid_permit(module)
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    monkeypatch.setenv(
        "KOR_TRAVEL_MAP_APPLICATION_FINAL_PERMIT_API_IMAGE_ID", "sha256:" + "b" * 64
    )
    assert module._validate_permit(
        json.dumps(payload).encode("utf-8"), consumer="api"
    )["transition_kind"] == "map-fresh-300-finalize"

    payload["transition_kind"] = "map-application-schema-0236-to-300"
    with pytest.raises(module.FinalPermitError, match="transition"):
        module._validate_permit(json.dumps(payload).encode("utf-8"), consumer="api")

    payload = _valid_permit(module)
    payload["transition_kind"] = "map-fresh-300"
    with pytest.raises(module.FinalPermitError, match="transition"):
        module._validate_permit(json.dumps(payload).encode("utf-8"), consumer="api")


def test_final_permit_reader_rejects_inode_replacement_between_lstat_and_open(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """read-only mount라도 path replacement race가 capability를 바꾸지 못한다."""

    module = _load_script(
        "application_schema_final_permit_toctou",
        "docker/application-schema-final-permit.py",
    )
    permit_directory = tmp_path / "permit"
    permit_directory.mkdir(mode=0o700)
    permit_path = permit_directory / "permit.json"
    permit_path.write_text("{\"first\":true}", encoding="utf-8")
    permit_path.chmod(0o444)
    replacement_path = permit_directory / "replacement.json"
    replacement_path.write_text("{\"second\":true}", encoding="utf-8")
    replacement_path.chmod(0o444)
    monkeypatch.setattr(module, "_PERMIT_PATH", permit_path)

    original_lstat = Path.lstat
    original_open = os.open
    original_fstat = os.fstat

    def _root_owned(metadata: os.stat_result) -> os.stat_result:
        mode = stat.S_IFMT(metadata.st_mode) | (0o755 if stat.S_ISDIR(metadata.st_mode) else 0o444)
        return os.stat_result(
            (
                mode,
                metadata.st_ino,
                metadata.st_dev,
                metadata.st_nlink,
                0,
                metadata.st_gid,
                metadata.st_size,
                metadata.st_atime,
                metadata.st_mtime,
                metadata.st_ctime,
            )
        )

    def _lstat_as_root(path: Path) -> os.stat_result:
        return _root_owned(original_lstat(path))

    def _replace_before_open(path: str | bytes | os.PathLike[str], flags: int, *args: int) -> int:
        if os.fspath(path) == os.fspath(permit_path):
            os.replace(replacement_path, permit_path)
        return original_open(path, flags, *args)

    def _fstat_as_root(descriptor: int) -> os.stat_result:
        return _root_owned(original_fstat(descriptor))

    monkeypatch.setattr(Path, "lstat", _lstat_as_root)
    monkeypatch.setattr(module.os, "open", _replace_before_open)
    monkeypatch.setattr(module.os, "fstat", _fstat_as_root)

    with pytest.raises(module.FinalPermitError, match="changed while opening"):
        module._require_fixed_file()
    assert stat.S_IMODE(permit_path.lstat().st_mode) == 0o444


def test_fresh_migration_accepts_only_fixed_one_shot_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fresh helper에는 daemon/repair/downgrade 분기가 없다."""

    module = _load_script(
        "application_schema_fresh_300",
        "docker/application-schema-fresh-300.py",
    )

    monkeypatch.setenv("KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE", "local-dev")
    module._parse_args(["migrate"])
    with pytest.raises(module.FreshMigrationError, match="profile-fixed migrate/recover"):
        module._parse_args(["repair"])
    monkeypatch.setenv("KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE", "production")
    module._parse_args(
        [
            "migrate",
            "--writer-fence-receipt",
            "/run/kor-travel-map-application-fresh-migrate/fence.json",
        ]
    )
    operation_id = "00000000-0000-4000-8000-000000000001"
    assert module._parse_args(["probe-missing", "--operation-id", operation_id]) == (
        "probe-missing",
        module.UUID(operation_id),
    )
    with pytest.raises(module.FreshMigrationError, match="profile-fixed migrate/recover"):
        module._parse_args(["migrate"])

    source = (_ROOT / "docker/application-schema-fresh-300.py").read_text(encoding="utf-8")
    assert "_assert_restricted_migrator_session" in source
    assert "must connect as restricted migrator" in source
    assert "_assert_virgin_version_table" in source
    assert "bootstrap-superuser DSN must not enter fresh migration" in source
    assert "downgrade" not in source


def test_fresh_migration_rejects_mutable_installed_contract_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """installed fresh executable은 mutable helper를 import하지 않는다."""

    module = _load_script(
        "application_schema_fresh_300_unsafe_contract",
        "docker/application-schema-fresh-300.py",
    )
    installed_bin = tmp_path / "bin"
    installed_bin.mkdir()
    helper = installed_bin / "ktm-application-schema-contract"
    helper.write_text("def application_contract():\n    return {}\n", encoding="utf-8")
    helper.chmod(0o777)
    monkeypatch.setattr(module, "_INSTALLED_BIN_DIR", installed_bin)
    monkeypatch.setattr(module, "__file__", str(installed_bin / "fresh"))

    with pytest.raises(module.FreshMigrationError, match="helper is unsafe"):
        module._static_contract_helper_path()


def test_fresh_migration_rechecks_manager_fence_before_root_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """긴 preflight 중 만료한 generation은 Alembic root를 실행하지 않는다."""

    module = _load_script(
        "application_schema_fresh_300_fence_expiry",
        "docker/application-schema-fresh-300.py",
    )
    contract = {
        "schema": "kor-travel-map.application-baseline-contract.v1",
        "application_head": "300",
        "reference_manifest_sha256": "1" * 64,
        "postgres_image_id": "sha256:" + "2" * 64,
        "source_catalog_sha256": "3" * 64,
        "destination_catalog_sha256": "9" * 64,
        "seed_sha256": "4" * 64,
        "privileged_residue_sha256": "5" * 64,
        "source_alembic_version_sha256": "6" * 64,
        "destination_alembic_version_sha256": "7" * 64,
        "runtime_invariants_sql_sha256": "8" * 64,
    }
    fence = {
        "transaction_id": "b93bb7cf-7901-4790-88a8-2a7bbc07f3b7",
        "journal_sha256": "9" * 64,
        "journal_generation": 1,
        "map_candidate_commit": "a" * 40,
        "map_candidate_image_id": "sha256:" + "b" * 64,
    }
    identity = {
        "database_name": "kor_travel_map",
        "database_oid": 16384,
        "database_owner": "ktm_feature_schema_owner",
        "postgres_system_identifier": "1234567890",
    }
    calls = 0
    upgraded = False

    class _Script:
        @staticmethod
        def get_heads() -> tuple[str, ...]:
            return ("300",)

    def _fence_once_then_expired() -> tuple[dict[str, object], str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return fence, "c" * 64
        raise module.FreshMigrationError("fresh 300 migrate fence has expired")

    async def _restricted(_: str, __: object) -> dict[str, object]:
        return identity

    async def _virgin(_: str) -> None:
        return None

    async def _noop_lock(_: object) -> None:
        return None

    def _unexpected_upgrade(*_: object) -> None:
        nonlocal upgraded
        upgraded = True

    class _Transaction:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    class _Engine:
        def begin(self) -> _Transaction:
            return _Transaction()

        async def dispose(self) -> None:
            return None

    monkeypatch.setenv("KOR_TRAVEL_MAP_APPLICATION_SCHEMA_PROFILE", "production")
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", "postgresql+asyncpg://unused")
    monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
    monkeypatch.setattr(module, "_config", lambda _: object())
    monkeypatch.setattr(module.ScriptDirectory, "from_config", lambda _: _Script())
    monkeypatch.setattr(module, "_static_contract", lambda: contract)
    monkeypatch.setattr(module, "_require_fixed_fence", _fence_once_then_expired)
    monkeypatch.setattr(module, "_verify_fence_candidate", lambda *_: None)
    monkeypatch.setattr(module, "make_async_engine", lambda *_args, **_kwargs: _Engine())
    monkeypatch.setattr(module, "_assert_restricted_migrator_session", _restricted)
    monkeypatch.setattr(module, "_acquire_operation_lock", _noop_lock)
    monkeypatch.setattr(module, "_assert_virgin_version_table", _virgin)
    monkeypatch.setattr(module.command, "upgrade", _unexpected_upgrade)

    with pytest.raises(module.FreshMigrationError, match="has expired"):
        asyncio.run(module._migrate())
    assert calls == 2
    assert not upgraded
    assert "KOR_TRAVEL_MAP_PG_DSN" not in os.environ
    assert "KOR_TRAVEL_MAP_ALEMBIC_USE_SCHEMA_OWNER_ROLE" not in os.environ


def test_fresh_root_missing_receipt_probe_returns_strict_candidate_bound_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script(
        "application_schema_fresh_300_missing_receipt",
        "docker/application-schema-fresh-300.py",
    )
    operation_id = module.UUID("00000000-0000-4000-8000-000000000001")
    fence = {
        "operation_id": str(operation_id),
        "transaction_id": "00000000-0000-4000-8000-000000000002",
        "journal_sha256": "1" * 64,
        "journal_generation": 3,
        "map_candidate_commit": "a" * 40,
        "map_candidate_image_id": "sha256:" + "b" * 64,
    }
    contract = {
        "postgres_image_id": "sha256:" + "c" * 64,
        "reference_manifest_sha256": "2" * 64,
        "source_catalog_sha256": "3" * 64,
        "seed_sha256": "4" * 64,
        "destination_alembic_version_sha256": "5" * 64,
    }
    identity = {
        "database_name": "kor_travel_map",
        "database_oid": 16384,
        "database_owner": "ktm_feature_schema_owner",
        "postgres_system_identifier": "1234567890",
    }
    calls: list[str] = []

    class _Connection:
        async def execute(self, statement: object) -> None:
            calls.append(str(statement))

    class _ConnectionContext:
        async def __aenter__(self) -> _Connection:
            return _Connection()

        async def __aexit__(self, *_: object) -> None:
            return None

    class _Engine:
        def connect(self) -> _ConnectionContext:
            return _ConnectionContext()

        async def dispose(self) -> None:
            calls.append("disposed")

    fence_reads: list[bool] = []

    def _fence(*, allow_expired_for_read_only_probe: bool = False):
        fence_reads.append(allow_expired_for_read_only_probe)
        return fence, "6" * 64

    async def _restricted(*_: object) -> dict[str, object]:
        return identity

    async def _locked(_: object) -> None:
        calls.append("locked")

    async def _missing(*_: object) -> None:
        return None

    async def _exact(_: object) -> str:
        return "kor-travel-map.application-fresh-300-pre-root.v1"

    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", "postgresql+asyncpg://unused")
    monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
    monkeypatch.setattr(module, "_require_fixed_fence", _fence)
    monkeypatch.setattr(module, "_static_contract", lambda: contract)
    monkeypatch.setattr(module, "_verify_fence_candidate", lambda *_: None)
    monkeypatch.setattr(module, "make_async_engine", lambda *_args, **_kwargs: _Engine())
    monkeypatch.setattr(module, "_assert_restricted_migrator_session", _restricted)
    monkeypatch.setattr(module, "_acquire_operation_lock", _locked)
    monkeypatch.setattr(module, "_find_operation_receipt_if_present", _missing)
    monkeypatch.setattr(module, "_assert_exact_pre_root_state", _exact)

    result = asyncio.run(module._probe_missing(operation_id))

    assert set(result) == {
        "schema",
        "outcome",
        "operation_id",
        "destination_head",
        "map_candidate_commit",
        "map_candidate_image_id",
        "postgres_image_id",
        "reference_manifest_sha256",
        "writer_fence_receipt_sha256",
        "writer_fence_transaction_id",
        "journal_sha256",
        "journal_generation",
        "database_identity",
        "pre_root_state_schema",
        "expected_post_source_catalog_sha256",
        "expected_post_seed_sha256",
        "expected_post_destination_alembic_version_sha256",
    }
    assert result["schema"].endswith("root-missing-receipt.v1")
    assert result["outcome"] == "receipt-missing-exact-prestate"
    assert result["operation_id"] == str(operation_id)
    assert result["database_identity"] == identity
    assert result["expected_post_source_catalog_sha256"] == "3" * 64
    assert result["expected_post_seed_sha256"] == "4" * 64
    assert result["expected_post_destination_alembic_version_sha256"] == "5" * 64
    assert fence_reads == [True, True]
    assert calls[0] == "SET TRANSACTION READ ONLY"
    assert "locked" in calls
    assert calls[-1] == "disposed"


@pytest.mark.parametrize("failure", ["existing-receipt", "pre-root-drift"])
def test_fresh_root_missing_receipt_probe_fails_closed(
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script(
        f"application_schema_fresh_300_probe_{failure}",
        "docker/application-schema-fresh-300.py",
    )
    operation_id = module.UUID("00000000-0000-4000-8000-000000000001")
    fence = {"operation_id": str(operation_id)}

    class _Connection:
        async def execute(self, _: object) -> None:
            return None

    class _ConnectionContext:
        async def __aenter__(self) -> _Connection:
            return _Connection()

        async def __aexit__(self, *_: object) -> None:
            return None

    class _Engine:
        def connect(self) -> _ConnectionContext:
            return _ConnectionContext()

        async def dispose(self) -> None:
            return None

    async def _restricted(*_: object) -> dict[str, object]:
        return {}

    async def _noop(_: object) -> None:
        return None

    async def _receipt(*_: object) -> dict[str, object] | None:
        return {"operation_id": str(operation_id)} if failure == "existing-receipt" else None

    async def _prestate(_: object) -> str:
        if failure == "pre-root-drift":
            raise module.FreshMigrationError("fresh 300 pre-root state is not exact")
        raise AssertionError("pre-root attestation must not run after an existing receipt")

    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", "postgresql+asyncpg://unused")
    monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
    monkeypatch.setattr(
        module,
        "_require_fixed_fence",
        lambda **_: (fence, "6" * 64),
    )
    monkeypatch.setattr(module, "_static_contract", dict)
    monkeypatch.setattr(module, "_verify_fence_candidate", lambda *_: None)
    monkeypatch.setattr(module, "make_async_engine", lambda *_args, **_kwargs: _Engine())
    monkeypatch.setattr(module, "_assert_restricted_migrator_session", _restricted)
    monkeypatch.setattr(module, "_acquire_operation_lock", _noop)
    monkeypatch.setattr(module, "_find_operation_receipt_if_present", _receipt)
    monkeypatch.setattr(module, "_assert_exact_pre_root_state", _prestate)

    expected = "existing operation receipt" if failure == "existing-receipt" else "not exact"
    with pytest.raises(module.FreshMigrationError, match=expected):
        asyncio.run(module._probe_missing(operation_id))


def test_fresh_root_prestate_attestation_is_exact_and_read_only() -> None:
    module = _load_script(
        "application_schema_fresh_300_prestate_sql",
        "docker/application-schema-fresh-300.py",
    )

    sql = module._pre_root_attestation_sql()

    for required in (
        "transaction_read_only",
        "application_schema_operation_receipts",
        "public.alembic_version",
        "membership.admin_option",
        "membership.inherit_option",
        "membership.set_option",
        "pg_catalog.aclexplode",
        "extension.extversion",
        "available.default_version",
        "search_path=public, x_extension",
        "pg_catalog.pg_default_acl",
    ):
        assert required in sql
    assert not any(token in sql for token in ("INSERT ", "UPDATE ", "DELETE ", "ALTER "))


def test_fresh_finalize_accepts_only_manager_fixed_completion_operation() -> None:
    """late ACL failure는 generic retry가 아니라 fixed Manager fence completion만 받는다."""

    module = _load_script(
        "application_schema_fresh_finalize",
        "docker/application-schema-fresh-finalize.py",
    )

    with pytest.raises(module.FreshFinalizeError, match="fixed fresh-300 finalize"):
        module._parse_args(["finalize"])
    with pytest.raises(module.FreshFinalizeError, match="fixed fresh-300 finalize"):
        module._parse_args(["migrate"])
    operation_id = "00000000-0000-4000-8000-000000000001"
    assert module._parse_args(["recover", "--operation-id", operation_id]) == (
        "recover",
        module.UUID(operation_id),
    )
    assert module._parse_args(["probe-missing", "--operation-id", operation_id]) == (
        "probe-missing",
        module.UUID(operation_id),
    )

    source = (_ROOT / "docker/application-schema-fresh-finalize.py").read_text(
        encoding="utf-8"
    )
    assert "reconcile_runtime_privileges" in source
    assert "requires exact raw revision 300" in source
    assert "application-schema-contract.py" in source


def test_fresh_finalize_rechecks_live_fence_immediately_before_acl_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """긴 receipt preflight 뒤 만료한 writer fence에서는 ACL을 바꾸지 않는다."""

    module = _load_script(
        "application_schema_fresh_finalize_expiry",
        "docker/application-schema-fresh-finalize.py",
    )
    contract = {
        "schema": "kor-travel-map.application-baseline-contract.v1",
        "application_head": "300",
        "reference_manifest_sha256": "c" * 64,
        "postgres_image_id": "sha256:" + "d" * 64,
        "source_catalog_sha256": "e" * 64,
        "destination_catalog_sha256": "0" * 64,
        "seed_sha256": "f" * 64,
        "privileged_residue_sha256": "1" * 64,
        "source_alembic_version_sha256": "3" * 64,
        "destination_alembic_version_sha256": "4" * 64,
        "runtime_invariants_sql_sha256": "2" * 64,
    }
    fence = {
        "transaction_id": "b93bb7cf-7901-4790-88a8-2a7bbc07f3b7",
        "journal_sha256": "5" * 64,
        "journal_generation": 2,
        "prior_fresh_migration_result_sha256": "6" * 64,
        "prior_fresh_migration_fence_sha256": "7" * 64,
        "prior_fresh_migration_transaction_id": "b93bb7cf-7901-4790-88a8-2a7bbc07f3b8",
        "prior_fresh_migration_journal_sha256": "8" * 64,
        "prior_fresh_migration_generation": 1,
        "map_candidate_commit": "a" * 40,
        "map_candidate_image_id": "sha256:" + "b" * 64,
        "postgres_image_id": contract["postgres_image_id"],
        "destination_head": "300",
        "reference_manifest_sha256": contract["reference_manifest_sha256"],
        "source_catalog_sha256": contract["source_catalog_sha256"],
        "destination_catalog_sha256": contract["destination_catalog_sha256"],
        "seed_sha256": contract["seed_sha256"],
        "privileged_residue_sha256": contract["privileged_residue_sha256"],
        "pre_privileged_residue_sha256": contract["privileged_residue_sha256"],
        "destination_alembic_version_sha256": contract[
            "destination_alembic_version_sha256"
        ],
        "runtime_invariants_sql_sha256": contract["runtime_invariants_sql_sha256"],
    }
    calls = 0
    reconciled = False

    def _fence_once_then_expired() -> tuple[dict[str, object], str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return fence, "9" * 64
        raise module.FreshFinalizeError("fresh finalize writer fence has expired")

    async def _noop_restricted(_: str, __: object) -> None:
        return None

    async def _noop_receipts(
        _: object,
        __: object,
        *,
        expected_catalog_sha256: str,
    ) -> tuple[str, str, str]:
        return expected_catalog_sha256, "f" * 64, "4" * 64

    async def _noop_lock(_: object) -> None:
        return None

    async def _unexpected_reconcile(_: object) -> None:
        nonlocal reconciled
        reconciled = True

    class _Transaction:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *_: object) -> None:
            return None

    class _Engine:
        def begin(self) -> _Transaction:
            return _Transaction()

        async def dispose(self) -> None:
            return None

    monkeypatch.setattr(module, "_require_fixed_fence", _fence_once_then_expired)
    monkeypatch.setattr(module, "_static_contract", lambda: contract)
    monkeypatch.setattr(module, "make_async_engine", lambda *_args, **_kwargs: _Engine())
    monkeypatch.setattr(module, "_assert_restricted_migrator_and_database", _noop_restricted)
    monkeypatch.setattr(module, "_acquire_operation_lock", _noop_lock)
    monkeypatch.setattr(module, "_assert_raw_300_and_receipts", _noop_receipts)
    monkeypatch.setattr(
        module,
        "reconcile_runtime_privileges_in_transaction",
        _unexpected_reconcile,
    )
    monkeypatch.delenv("KOR_TRAVEL_MAP_BOOTSTRAP_PG_DSN", raising=False)
    monkeypatch.setenv("KOR_TRAVEL_MAP_MIGRATOR_PG_DSN", "postgresql+asyncpg://unused")
    monkeypatch.setenv("KOR_TRAVEL_MAP_IMAGE_REVISION", "a" * 40)
    monkeypatch.setenv("KOR_TRAVEL_MAP_APPLICATION_FRESH_FINALIZE_IMAGE_ID", "sha256:" + "b" * 64)

    with pytest.raises(module.FreshFinalizeError, match="has expired"):
        asyncio.run(module._finalize())
    assert calls == 2
    assert not reconciled


def test_static_baseline_contract_attests_all_manager_consumed_receipts() -> None:
    """Manager candidate attestation은 image 안의 immutable receipts만 읽는다."""

    module = _load_script(
        "application_schema_contract",
        "docker/application-schema-contract.py",
    )

    contract = module.application_contract()
    reference = json.loads(
        (_ROOT / "alembic/baseline/application-reference.json").read_text(encoding="utf-8")
    )
    artifacts = reference["artifacts"]
    assert contract == {
        "schema": "kor-travel-map.application-baseline-contract.v1",
        "application_head": "300",
        "reference_manifest_sha256": module._sha256_bytes(
            (_ROOT / "alembic/baseline/application-reference.json").read_bytes()
        ),
        "postgres_image_id": reference["source"]["container_image_id"],
        "source_catalog_sha256": artifacts["source_catalog_contract_sha256"],
        "destination_catalog_sha256": artifacts[
            "destination_catalog_contract_sha256"
        ],
        "seed_sha256": artifacts["seed_contract_sha256"],
        "privileged_residue_sha256": artifacts[
            "privileged_residue_contract_sha256"
        ],
        "source_alembic_version_sha256": artifacts[
            "source_alembic_version_contract_sha256"
        ],
        "destination_alembic_version_sha256": artifacts[
            "destination_alembic_version_contract_sha256"
        ],
        "runtime_invariants_sql_sha256": artifacts["runtime_invariants_sql_sha256"],
    }

    assert module.main(["unexpected"]) == 1


def test_fresh_database_contract_module_has_no_handoff_or_cli_surface() -> None:
    """fresh receipt helper는 읽기 전용 module이며 직접 실행·stamp할 수 없다."""

    contract = (
        _ROOT / "docker/application-schema-db-contract.py"
    ).read_text(encoding="utf-8")
    root = (_ROOT / "docker/application-schema-fresh-300.py").read_text(
        encoding="utf-8"
    )
    finalize = (_ROOT / "docker/application-schema-fresh-finalize.py").read_text(
        encoding="utf-8"
    )
    assert "def main(" not in contract
    assert "if __name__" not in contract
    assert "from alembic" not in contract
    assert "import alembic" not in contract
    assert "make_async_engine" not in contract
    assert "INSERT " not in contract
    assert "UPDATE " not in contract
    assert "DELETE " not in contract
    assert "application-schema-db-contract.py" in root
    assert "application-schema-db-contract.py" in finalize
    assert "transition-application-schema-0236-to-300.py" not in root
    assert "transition-application-schema-0236-to-300.py" not in finalize


def test_static_baseline_contract_rejects_mutable_installed_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """installed contract reader는 root-owned 0444가 아닌 artifact를 거부한다."""

    module = _load_script(
        "application_schema_contract_unsafe_artifact",
        "docker/application-schema-contract.py",
    )
    installed_bin = tmp_path / "bin"
    installed_bin.mkdir()
    artifact = tmp_path / "mutable.sql"
    artifact.write_text("SELECT 1;\n", encoding="utf-8")
    artifact.chmod(0o666)
    monkeypatch.setattr(module, "_INSTALLED_BIN_DIR", installed_bin)
    monkeypatch.setattr(module, "__file__", str(installed_bin / "contract"))

    with pytest.raises(
        module.ApplicationSchemaContractError,
        match="installed_application_baseline_unsafe",
    ):
        module._read_immutable_bytes(artifact)


def test_final_permit_binds_all_static_contract_facets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """permit은 manifest 문자열뿐 아니라 검증된 sidecar contract에 결박된다."""

    module = _load_script(
        "application_schema_final_permit_static_contract",
        "docker/application-schema-final-permit.py",
    )
    contract = dict(module._static_contract())
    contract["seed_sha256"] = "0" * 64
    monkeypatch.setattr(module, "_static_contract", lambda: contract)

    with pytest.raises(module.FinalPermitError, match="contract is inconsistent"):
        module._read_reference()

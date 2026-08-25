"""후보 이미지 Dagster metadata storage migration command 회귀."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_COMMAND_PATH = _REPOSITORY_ROOT / "docker" / "dagster-storage-migrate.py"
_SENTINEL_DSN = "postgresql://user:do-not-reflect@storage.internal/dagster"
_OPERATION_ID = "12345678-1234-5678-9234-567812345678"


class _FakeTransaction:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def __enter__(self) -> _FakeConnection:
        return self._connection

    def __exit__(self, *_args: object) -> None:
        return None


class _FakeConnection:
    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    def close(self) -> None:
        return None


class _FakeEngine:
    def __init__(self) -> None:
        self.connection = _FakeConnection()

    def connect(self) -> _FakeConnection:
        return self.connection

    def dispose(self) -> None:
        return None


def _mock_session_lock(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
    monkeypatch.setattr(module, "create_engine", lambda _dsn: _FakeEngine())
    monkeypatch.setattr(module, "_acquire_session_operation_lock", lambda _connection: None)
    monkeypatch.setattr(module, "_release_session_operation_lock", lambda _connection: None)


def _command_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_dagster_storage_migrate_command",
        _COMMAND_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _migration_environment(tmp_path: Path) -> dict[str, str]:
    dagster_home = tmp_path / "dagster-home"
    dagster_home.mkdir()
    (dagster_home / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    return {
        "PATH": os.environ["PATH"],
        "DAGSTER_HOME": str(dagster_home),
        "KOR_TRAVEL_MAP_DAGSTER_PG_URL": _SENTINEL_DSN,
    }


def test_head_attests_installed_dagster_package_graph_without_instance_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    expected_head = module._dagster_storage_head()
    monkeypatch.setattr(module.os, "environ", {"PATH": os.environ["PATH"]})

    assert module.main(["head"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "head": expected_head,
        "schema": "kor-travel-map.dagster-storage-head.v1",
    }


def test_storage_writer_runs_schema_migrate_then_required_reindex(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _command_module()
    environment = {"PATH": os.environ["PATH"]}
    calls: list[list[str]] = []

    def _run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "env": environment,
        }
        calls.append(arguments)
        return subprocess.CompletedProcess(arguments, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", _run)

    module._run_dagster_instance_migrate(environment)

    assert calls == [
        [
            module._ISOLATED_PYTHON,
            "-I",
            module._DAGSTER_EXECUTABLE,
            "instance",
            "migrate",
        ],
        [
            module._ISOLATED_PYTHON,
            "-I",
            module._DAGSTER_EXECUTABLE,
            "instance",
            "reindex",
        ],
    ]


def test_migrate_runs_dagster_cli_then_requires_exact_single_version_row(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    environment = _migration_environment(tmp_path)
    invoked_with: list[Mapping[str, str]] = []
    verified_with: list[Mapping[str, str]] = []
    identity = {"name": "metadata", "oid": 42}
    binding = {
        "operation_id": _OPERATION_ID,
        "permit_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "candidate_sha256": "c" * 64,
    }
    expected = {
        "head": "candidate-head",
        "schema": "kor-travel-map.dagster-storage-migration.v3",
        "status": "migrated",
        "operation_id": _OPERATION_ID,
        "permit_sha256": "a" * 64,
        "version_num": "candidate-head",
        "database_name": "metadata",
        "database_oid": "42",
    }
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
    _mock_session_lock(monkeypatch, module)

    def _verify_identity(
        current_environment: Mapping[str, str],
    ) -> tuple[str, dict[str, object]]:
        verified_with.append(current_environment)
        return _SENTINEL_DSN, identity

    monkeypatch.setattr(module, "_verify_database_identity", _verify_identity)
    monkeypatch.setattr(
        module,
        "_read_operation_binding",
        lambda _environment: (_SENTINEL_DSN, identity, binding),
    )
    monkeypatch.setattr(
        module,
        "_prepare_operation",
        lambda *_args, **_kwargs: ("execute", None),
    )
    monkeypatch.setattr(
        module,
        "_run_dagster_instance_migrate",
        lambda current_environment: invoked_with.append(current_environment),
    )
    monkeypatch.setattr(
        module,
        "_complete_operation",
        lambda *_args, **_kwargs: expected,
    )
    monkeypatch.setattr(module.os, "environ", environment)

    assert module.main(["migrate"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == expected
    assert invoked_with == [environment]
    assert verified_with == [environment, environment, environment]


def test_migrate_reexecutes_when_receipt_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    environment = _migration_environment(tmp_path)
    identity = {"name": "metadata", "oid": 42}
    binding = {
        "operation_id": _OPERATION_ID,
        "permit_sha256": "a" * 64,
        "candidate_sha256": "b" * 64,
    }
    calls: list[str] = []
    expected = {
        "schema": "kor-travel-map.dagster-storage-migration.v3",
        "status": "migrated",
        "operation_id": _OPERATION_ID,
        "head": "candidate-head",
        "version_num": "candidate-head",
    }
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
    _mock_session_lock(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "_verify_database_identity",
        lambda _environment: (_SENTINEL_DSN, identity),
    )
    monkeypatch.setattr(
        module,
        "_read_operation_binding",
        lambda _environment: (_SENTINEL_DSN, identity, binding),
    )
    monkeypatch.setattr(
        module,
        "_prepare_operation",
        lambda *_args, **_kwargs: ("execute", None),
    )
    monkeypatch.setattr(
        module,
        "_run_dagster_instance_migrate",
        lambda _environment: calls.append("migrate"),
    )
    monkeypatch.setattr(
        module,
        "_complete_operation",
        lambda *_args, **_kwargs: expected,
    )
    monkeypatch.setattr(module.os, "environ", environment)

    assert module.main(["migrate"]) == 0

    assert json.loads(capsys.readouterr().out) == expected
    assert calls == ["migrate"]


def test_prepare_final_head_without_receipt_reexecutes_same_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _command_module()
    connection = object()
    identity = {
        "name": "metadata",
        "oid": 42,
        "owner": "metadata_owner",
        "system_identifier": "1234",
    }
    binding = {
        "operation_id": _OPERATION_ID,
        "permit_sha256": "a" * 64,
        "candidate_sha256": "b" * 64,
    }
    intent = {
        **binding,
        "target_head": "candidate-head",
        "pre_state": "missing",
        "pre_version_rows": [],
        "database_name": "metadata",
        "database_oid": 42,
        "database_owner": "metadata_owner",
        "postgres_system_identifier": "1234",
    }
    bootstrapped: list[str] = []
    monkeypatch.setattr(module, "_ensure_operation_outbox", lambda _connection: None)
    monkeypatch.setattr(module, "_read_receipt", lambda *_args: None)
    monkeypatch.setattr(
        module,
        "_read_version_state",
        lambda *_args: ("final", ("candidate-head",)),
    )
    monkeypatch.setattr(module, "_read_intent", lambda *_args: intent)
    monkeypatch.setattr(
        module,
        "_bootstrap_fresh_dagster_catalog",
        lambda _connection, *, version_state: bootstrapped.append(version_state),
    )

    assert module._prepare_operation(
        connection,
        binding=binding,
        identity=identity,
        head="candidate-head",
    ) == ("execute", None)
    assert bootstrapped == ["final"]


def test_migrate_recovers_committed_receipt_without_any_writer_call(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    environment = _migration_environment(tmp_path)
    identity = {"name": "metadata", "oid": 42}
    binding = {"operation_id": _OPERATION_ID}
    recovered = {
        "schema": "kor-travel-map.dagster-storage-migration.v3",
        "operation_id": _OPERATION_ID,
        "status": "migrated",
        "head": "candidate-head",
        "version_num": "candidate-head",
    }
    calls: list[str] = []
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
    _mock_session_lock(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "_verify_database_identity",
        lambda _environment: (_SENTINEL_DSN, identity),
    )
    monkeypatch.setattr(
        module,
        "_read_operation_binding",
        lambda _environment: (_SENTINEL_DSN, identity, binding),
    )
    monkeypatch.setattr(
        module,
        "_prepare_operation",
        lambda *_args, **_kwargs: ("done", recovered),
    )
    monkeypatch.setattr(
        module,
        "_run_dagster_instance_migrate",
        lambda _environment: calls.append("migrate"),
    )
    monkeypatch.setattr(module.os, "environ", environment)

    assert module.main(["migrate"]) == 0
    assert json.loads(capsys.readouterr().out) == recovered
    assert calls == []


def test_explicit_recover_binds_operation_id_and_emits_canonical_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    environment = _migration_environment(tmp_path)
    recovered = {
        "schema": "kor-travel-map.dagster-storage-migration.v3",
        "operation_id": _OPERATION_ID,
        "status": "migrated",
        "head": "candidate-head",
        "version_num": "candidate-head",
    }
    observed: list[str] = []

    def _recover(_environment: Mapping[str, str], operation_id: object) -> dict[str, str]:
        observed.append(str(operation_id))
        return recovered

    monkeypatch.setattr(module, "_recover", _recover)
    monkeypatch.setattr(module.os, "environ", environment)

    assert module.main(["recover", "--operation-id", _OPERATION_ID]) == 0
    assert json.loads(capsys.readouterr().out) == recovered
    assert observed == [_OPERATION_ID]


def test_migrate_failure_never_reflects_metadata_dsn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    environment = _migration_environment(tmp_path)
    identity = {"name": "metadata", "oid": 42}
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
    _mock_session_lock(monkeypatch, module)
    monkeypatch.setattr(
        module,
        "_verify_database_identity",
        lambda _environment: (_SENTINEL_DSN, identity),
    )
    monkeypatch.setattr(
        module,
        "_read_operation_binding",
        lambda _environment: (
            _SENTINEL_DSN,
            identity,
            {"operation_id": _OPERATION_ID},
        ),
    )
    monkeypatch.setattr(
        module,
        "_prepare_operation",
        lambda *_args, **_kwargs: ("execute", None),
    )

    def _fail(_environment: Mapping[str, str]) -> None:
        raise module.DagsterStorageMigrationError("dagster_instance_migrate_failed")

    monkeypatch.setattr(module, "_run_dagster_instance_migrate", _fail)
    monkeypatch.setattr(module.os, "environ", environment)

    assert module.main(["migrate"]) == 1

    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "code": "dagster_instance_migrate_failed",
        "schema": "kor-travel-map.dagster-storage-migration-error.v1",
    }
    assert _SENTINEL_DSN not in captured.out
    assert _SENTINEL_DSN not in captured.err


def test_migrate_requires_explicit_instance_home_and_metadata_dsn(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
    monkeypatch.setattr(module.os, "environ", {"PATH": os.environ["PATH"]})

    assert module.main(["migrate"]) == 1

    assert json.loads(capsys.readouterr().err) == {
        "code": "missing_dagster_home",
        "schema": "kor-travel-map.dagster-storage-migration-error.v1",
    }

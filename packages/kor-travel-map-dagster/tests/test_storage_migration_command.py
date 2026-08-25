"""후보 이미지 Dagster metadata storage migration command 회귀."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_COMMAND_PATH = _REPOSITORY_ROOT / "docker" / "dagster-storage-migrate.py"
_SENTINEL_DSN = "postgresql://user:do-not-reflect@storage.internal/dagster"
_OPERATION_ID = "12345678-1234-5678-9234-567812345678"


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
        "schema": "kor-travel-map.dagster-storage-migration.v2",
        "status": "migrated",
        "operation_id": _OPERATION_ID,
        "permit_sha256": "a" * 64,
        "version_num": "candidate-head",
        "database_name": "metadata",
        "database_oid": "42",
    }
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")

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
    assert verified_with == [environment, environment]


@pytest.mark.parametrize(("action", "expected_cli_calls"), [("execute", 1), ("complete", 0)])
def test_migrate_distinguishes_pre_execution_and_post_commit_resume(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    action: str,
    expected_cli_calls: int,
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
        "schema": "kor-travel-map.dagster-storage-migration.v2",
        "status": "migrated",
        "operation_id": _OPERATION_ID,
        "head": "candidate-head",
        "version_num": "candidate-head",
    }
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
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
        lambda *_args, **_kwargs: (action, None),
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
    assert calls == ["migrate"] * expected_cli_calls


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
        "schema": "kor-travel-map.dagster-storage-migration.v2",
        "operation_id": _OPERATION_ID,
        "status": "migrated",
        "head": "candidate-head",
        "version_num": "candidate-head",
    }
    calls: list[str] = []
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
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
        "schema": "kor-travel-map.dagster-storage-migration.v2",
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

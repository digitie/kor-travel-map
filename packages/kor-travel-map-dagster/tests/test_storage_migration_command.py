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
_ERROR_SCHEMA = "kor-travel-map.dagster-storage-migration-error.v1"


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


def _mock_session_lock(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, calls: list[str]
) -> None:
    monkeypatch.setattr(module, "create_engine", lambda _dsn: _FakeEngine())
    monkeypatch.setattr(
        module,
        "_acquire_session_operation_lock",
        lambda _connection: calls.append("lock"),
    )
    monkeypatch.setattr(
        module,
        "_release_session_operation_lock",
        lambda _connection: calls.append("unlock"),
    )


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


def _accept_environment(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
    """이미지 안 `dagster.yaml` 봉인(`/opt/dagster`)은 이 호스트에 없다 — 그 경계만 넘긴다."""

    monkeypatch.setattr(
        module,
        "_require_migration_environment",
        lambda environment: (
            environment["KOR_TRAVEL_MAP_DAGSTER_PG_URL"],
            "production",
            "a" * 64,
        ),
    )


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


def test_migrate_prepares_then_runs_dagster_cli_then_checks_postcondition_under_lock(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    environment = _migration_environment(tmp_path)
    calls: list[str] = []
    invoked_with: list[Mapping[str, str]] = []
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
    _accept_environment(monkeypatch, module)
    _mock_session_lock(monkeypatch, module, calls)
    monkeypatch.setattr(
        module, "_prepare_storage", lambda _connection: calls.append("prepare")
    )

    def _instance_migrate(current_environment: Mapping[str, str]) -> None:
        calls.append("instance-migrate")
        invoked_with.append(current_environment)

    monkeypatch.setattr(module, "_run_dagster_instance_migrate", _instance_migrate)
    monkeypatch.setattr(
        module,
        "_verify_storage",
        lambda _connection, *, head: calls.append(f"verify:{head}"),
    )
    monkeypatch.setattr(module.os, "environ", environment)

    assert module.main(["migrate"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "head": "candidate-head",
        "schema": "kor-travel-map.dagster-storage-migration.v4",
        "status": "migrated",
    }
    assert calls == [
        "lock",
        "prepare",
        "instance-migrate",
        "verify:candidate-head",
        "unlock",
    ]
    assert invoked_with == [environment]


@pytest.mark.parametrize(
    "arguments",
    [
        ["verify-identity"],
        ["recover", "--operation-id", _OPERATION_ID],
        ["migrate", "--operation-id", _OPERATION_ID],
        [],
    ],
)
def test_removed_and_unknown_subcommands_are_invalid_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
) -> None:
    """ADR-102: `verify-identity`·`recover`는 permit/outbox와 함께 사라졌다."""

    module = _command_module()
    monkeypatch.setattr(module.os, "environ", _migration_environment(tmp_path))

    assert module.main(arguments) == 1

    assert json.loads(capsys.readouterr().err) == {
        "code": "invalid_arguments",
        "schema": _ERROR_SCHEMA,
    }


def test_migrate_failure_never_reflects_metadata_dsn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _command_module()
    environment = _migration_environment(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
    _accept_environment(monkeypatch, module)
    _mock_session_lock(monkeypatch, module, calls)
    monkeypatch.setattr(module, "_prepare_storage", lambda _connection: None)

    def _fail(_environment: Mapping[str, str]) -> None:
        raise module.DagsterStorageMigrationError("dagster_instance_migrate_failed")

    monkeypatch.setattr(module, "_run_dagster_instance_migrate", _fail)
    monkeypatch.setattr(module.os, "environ", environment)

    assert module.main(["migrate"]) == 1

    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "code": "dagster_instance_migrate_failed",
        "schema": _ERROR_SCHEMA,
    }
    assert _SENTINEL_DSN not in captured.out
    assert _SENTINEL_DSN not in captured.err
    # 실패해도 session lock은 풀린다.
    assert calls == ["lock", "unlock"]


def test_unreachable_metadata_database_never_reflects_metadata_dsn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """연결 단계의 드라이버 예외는 DSN 원문을 담는다 — 코드로만 낸다."""

    module = _command_module()
    environment = _migration_environment(tmp_path)
    monkeypatch.setattr(module, "_dagster_storage_head", lambda: "candidate-head")
    _accept_environment(monkeypatch, module)

    def _unreachable(dsn: str) -> object:
        raise RuntimeError(f"could not connect to {dsn}")

    monkeypatch.setattr(module, "create_engine", _unreachable)
    monkeypatch.setattr(module.os, "environ", environment)

    assert module.main(["migrate"]) == 1

    captured = capsys.readouterr()
    assert json.loads(captured.err) == {
        "code": "dagster_storage_database_unavailable",
        "schema": _ERROR_SCHEMA,
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
        "schema": _ERROR_SCHEMA,
    }

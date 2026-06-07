"""PostgreSQL advisory-lock command wrapper tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "with_pg_advisory_lock",
        ROOT / "scripts" / "with-pg-advisory-lock.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_sqlalchemy_postgres_dsn_is_normalized_for_psycopg() -> None:
    module = _load_script()

    assert (
        module._psycopg_dsn("postgresql+asyncpg://user:pass@localhost/db")
        == "postgresql://user:pass@localhost/db"
    )
    assert (
        module._psycopg_dsn("postgresql+psycopg://user:pass@localhost/db")
        == "postgresql://user:pass@localhost/db"
    )
    assert (
        module._psycopg_dsn("postgresql://user:pass@localhost/db")
        == "postgresql://user:pass@localhost/db"
    )


@pytest.mark.unit
def test_command_separator_is_removed_from_parsed_args() -> None:
    module = _load_script()

    args = module._parse_args(
        [
            "--key",
            "maintenance:backup-restore",
            "--dsn",
            "postgresql://user:pass@localhost/db",
            "--",
            "bash",
            "scripts/docker-backup.sh",
        ]
    )

    assert args.key == "maintenance:backup-restore"
    assert args.command == ["bash", "scripts/docker-backup.sh"]

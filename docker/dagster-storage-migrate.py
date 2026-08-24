#!/usr/local/bin/python -I
"""후보 이미지 안에서 Dagster metadata storage를 attest·migrate한다.

이 파일은 의도적으로 ``kortravelmap`` package를 import하지 않는다. migration-only
경로가 Map code location, application settings 또는 application Alembic chain을 읽으면
candidate storage head의 정본이 다시 흐려진다. 여기서 읽는 migration graph는 이미지에
설치된 Dagster package 자체뿐이다.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, TextIO

from alembic.config import Config
from alembic.script import ScriptDirectory
from dagster._core.storage.sql import ALEMBIC_SCRIPTS_LOCATION
from sqlalchemy import create_engine, text

_DAGSTER_HOME_ENV: Final = "DAGSTER_HOME"
_DAGSTER_PG_URL_ENV: Final = "KOR_TRAVEL_MAP_DAGSTER_PG_URL"
_HEAD_SCHEMA: Final = "kor-travel-map.dagster-storage-head.v1"
_MIGRATE_SCHEMA: Final = "kor-travel-map.dagster-storage-migration.v1"
_ERROR_SCHEMA: Final = "kor-travel-map.dagster-storage-migration-error.v1"
_ISOLATED_PYTHON: Final = "/usr/local/bin/python"
_DAGSTER_EXECUTABLE: Final = "/usr/local/bin/dagster"


class DagsterStorageMigrationError(RuntimeError):
    """외부 입력을 반사하지 않는 migration-only 계약 오류."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _dagster_storage_head() -> str:
    """실행 중인 이미지가 설치한 Dagster storage graph의 단일 head를 읽는다."""
    try:
        config = Config()
        config.set_main_option("script_location", ALEMBIC_SCRIPTS_LOCATION)
        heads = ScriptDirectory.from_config(config).get_heads()
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_storage_head_unavailable") from exc

    if len(heads) != 1:
        raise DagsterStorageMigrationError("dagster_storage_head_ambiguous")
    return heads[0]


def _require_migration_environment(environment: Mapping[str, str]) -> str:
    """같은 image의 Dagster instance config와 metadata DSN을 명시적으로 요구한다."""
    dagster_home_raw = environment.get(_DAGSTER_HOME_ENV)
    if not dagster_home_raw:
        raise DagsterStorageMigrationError("missing_dagster_home")

    dagster_home = Path(dagster_home_raw)
    if not dagster_home.is_absolute() or not dagster_home.is_dir():
        raise DagsterStorageMigrationError("invalid_dagster_home")

    dagster_yaml = dagster_home / "dagster.yaml"
    try:
        dagster_yaml_mode = dagster_yaml.stat().st_mode
    except OSError as exc:
        raise DagsterStorageMigrationError("missing_dagster_yaml") from exc
    if not stat.S_ISREG(dagster_yaml_mode):
        raise DagsterStorageMigrationError("invalid_dagster_yaml")

    dagster_pg_url = environment.get(_DAGSTER_PG_URL_ENV)
    if not dagster_pg_url or not dagster_pg_url.strip():
        raise DagsterStorageMigrationError("missing_dagster_pg_url")
    return dagster_pg_url


def _run_dagster_instance_migrate(environment: Mapping[str, str]) -> None:
    """Dagster가 제공하는 migration entrypoint를 실행하되 민감 출력은 전달하지 않는다."""
    try:
        completed = subprocess.run(
            [
                _ISOLATED_PYTHON,
                "-I",
                _DAGSTER_EXECUTABLE,
                "instance",
                "migrate",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=dict(environment),
        )
    except OSError as exc:
        raise DagsterStorageMigrationError("dagster_instance_migrate_unavailable") from exc
    if completed.returncode != 0:
        # Dagster의 info 출력이나 DB driver 예외에는 DSN이 포함될 수 있다. 이 명령은
        # container log로도 원문을 넘기지 않고, 호출자가 stable error code만 받게 한다.
        raise DagsterStorageMigrationError("dagster_instance_migrate_failed")


def _read_version_rows(dagster_pg_url: str) -> tuple[str, ...]:
    """동일 DSN의 Dagster storage version table을 읽는다."""
    engine = None
    try:
        engine = create_engine(dagster_pg_url)
        with engine.connect() as connection:
            rows = connection.execute(
                text("SELECT version_num FROM public.alembic_version ORDER BY version_num")
            ).all()
    except Exception as exc:
        raise DagsterStorageMigrationError("dagster_version_table_unavailable") from exc
    finally:
        if engine is not None:
            engine.dispose()
    return tuple(str(row[0]) for row in rows)


def _migrate(environment: Mapping[str, str]) -> dict[str, str]:
    head = _dagster_storage_head()
    dagster_pg_url = _require_migration_environment(environment)
    _run_dagster_instance_migrate(environment)
    version_rows = _read_version_rows(dagster_pg_url)
    if len(version_rows) != 1:
        raise DagsterStorageMigrationError("dagster_version_row_count_invalid")
    version_num = version_rows[0]
    if version_num != head:
        raise DagsterStorageMigrationError("dagster_version_mismatch")
    return {
        "schema": _MIGRATE_SCHEMA,
        "status": "migrated",
        "head": head,
        "version_num": version_num,
    }


def _emit(payload: Mapping[str, str], *, stream: TextIO = sys.stdout) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    """`head` 또는 `migrate`를 실행하고 안정된 JSON 결과를 출력한다."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments == ["head"]:
            _emit({"schema": _HEAD_SCHEMA, "head": _dagster_storage_head()})
            return 0
        if arguments == ["migrate"]:
            _emit(_migrate(os.environ))
            return 0
        raise DagsterStorageMigrationError("invalid_arguments")
    except DagsterStorageMigrationError as exc:
        _emit({"schema": _ERROR_SCHEMA, "code": exc.code}, stream=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

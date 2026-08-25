"""Fresh application ``300``이 공유하는 읽기 전용 DB contract 함수.

이 모듈은 CLI entrypoint나 schema mutation capability를 갖지 않는다. root/finalize
one-shot은 root-owned baseline SQL을 읽어 canonical receipt와 runtime invariant만
검증한다.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_APPLICATION_ROOT_CANDIDATES: Final = (Path("/app"), Path(__file__).resolve().parents[1])
_INSTALLED_MODULE_PATH: Final = Path("/app/docker/application-schema-db-contract.py")
_MAX_SQL_BYTES: Final = 4 * 1024 * 1024
_ALLOWED_CONTRACTS: Final = frozenset(
    {
        "application-catalog.sql",
        "application-seed.sql",
        "application-destination-alembic-version.sql",
        "application-runtime-invariants.sql",
    }
)
_RUNTIME_INVARIANTS_SQL: Final = "application-runtime-invariants.sql"
_CANONICAL_CONTRACT_GUC_STATEMENTS: Final = (
    "SET LOCAL quote_all_identifiers TO off",
    "SET LOCAL DateStyle TO 'ISO, YMD'",
    "SET LOCAL IntervalStyle TO 'postgres'",
    "SET LOCAL TimeZone TO 'UTC'",
    "SET LOCAL extra_float_digits TO 3",
    "SET LOCAL lc_numeric TO 'C'",
    "SET LOCAL bytea_output TO 'hex'",
    "SET LOCAL standard_conforming_strings TO on",
    "SET LOCAL xmlbinary TO 'base64'",
)


class ApplicationSchemaDatabaseContractError(RuntimeError):
    """읽기 전용 application DB contract를 안전하게 증명할 수 없을 때의 오류."""


def _installed_mode() -> bool:
    return Path(__file__).resolve() == _INSTALLED_MODULE_PATH


def _application_root() -> Path:
    for candidate in _APPLICATION_ROOT_CANDIDATES:
        baseline = candidate / "alembic" / "baseline"
        if baseline.is_dir():
            return candidate
    raise ApplicationSchemaDatabaseContractError(
        "installed application baseline is unavailable"
    )


def _read_contract_sql(name: str) -> str:
    if name not in _ALLOWED_CONTRACTS:
        raise ApplicationSchemaDatabaseContractError(
            "application DB contract name is invalid"
        )
    path = _application_root() / "alembic" / "baseline" / name
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_size > _MAX_SQL_BYTES
            or (_installed_mode() and metadata.st_uid != 0)
            or (_installed_mode() and stat.S_IMODE(metadata.st_mode) != 0o444)
            or (_installed_mode() and metadata.st_nlink != 1)
        ):
            raise ApplicationSchemaDatabaseContractError(
                "application DB contract file is unsafe"
            )
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino, opened.st_size)
                != (metadata.st_dev, metadata.st_ino, metadata.st_size)
            ):
                raise ApplicationSchemaDatabaseContractError(
                    "application DB contract changed while opening"
                )
            raw = os.read(descriptor, _MAX_SQL_BYTES + 1)
            if len(raw) > _MAX_SQL_BYTES:
                raise ApplicationSchemaDatabaseContractError(
                    "application DB contract file is too large"
                )
        finally:
            os.close(descriptor)
        value = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ApplicationSchemaDatabaseContractError(
            "application DB contract is unavailable"
        ) from exc
    if not value.strip():
        raise ApplicationSchemaDatabaseContractError(
            "application DB contract is empty"
        )
    return value


async def contract_sha256(connection: AsyncConnection, contract_name: str) -> str:
    """ordered scalar rows를 canonical UTF-8/LF receipt로 만든다."""

    for statement in _CANONICAL_CONTRACT_GUC_STATEMENTS:
        await connection.execute(text(statement))
    rows = await connection.execute(text(_read_contract_sql(contract_name)))
    digest = hashlib.sha256()
    for item in rows.scalars():
        digest.update(str(item).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


async def verify_runtime_projection_invariants(connection: AsyncConnection) -> None:
    """변하는 live revision 값을 freeze하지 않고 `300` 필요 조건만 확인한다."""

    rows = await connection.execute(text(_read_contract_sql(_RUNTIME_INVARIANTS_SQL)))
    violations = tuple(str(value) for value in rows.scalars())
    if violations:
        raise ApplicationSchemaDatabaseContractError(
            "application runtime revision projection invariant failed: "
            + ", ".join(violations)
        )

"""H35 helper의 process 경계와 비밀 비반사 black-box 테스트."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kortravelmap.cli._h35_contract import CONTRACT_VERSION

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "h35" / "h35_cutover.py"
_SECRET = "h35-do-not-reflect-secret"
_SOURCE_REVISION = "1" * 40


def _run(
    *arguments: str,
    stdin: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(environment or {})
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *arguments],
        cwd=_ROOT,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )


def _assert_narrow_error(
    result: subprocess.CompletedProcess[str],
    *,
    returncode: int,
    error_code: str,
) -> None:
    assert result.returncode == returncode
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert _SECRET not in result.stdout
    assert json.loads(result.stdout) == {
        "contract_version": CONTRACT_VERSION,
        "status": "failed",
        "error_code": error_code,
    }


@pytest.mark.parametrize(
    "arguments",
    [(), ("unknown",), ("preflight", _SECRET), ("--help", _SECRET)],
)
def test_invalid_argv_is_not_reflected(arguments: tuple[str, ...]) -> None:
    result = _run(*arguments, stdin=_SECRET)

    _assert_narrow_error(result, returncode=2, error_code="invalid_arguments")


@pytest.mark.parametrize(
    "stdin",
    [
        _SECRET,
        '{"secret":"' + _SECRET + '"}',
        "{} {}",
    ],
)
def test_invalid_stdin_is_not_reflected(stdin: str) -> None:
    result = _run("preflight", stdin=stdin)

    _assert_narrow_error(result, returncode=2, error_code="invalid_request")


def test_connection_exception_does_not_reflect_dsn_or_exception() -> None:
    request = {
        "contract_version": CONTRACT_VERSION,
        "operation": "preflight",
        "transaction_id": "00000000-0000-0000-0000-000000000001",
        "source_revision": _SOURCE_REVISION,
        "database_identity": "2" * 64,
        "prior_receipt": None,
        "prior_receipt_digest": None,
    }
    dsn = f"postgresql+asyncpg://{_SECRET}:{_SECRET}@127.0.0.1:1/secret_database"

    result = _run(
        "preflight",
        stdin=json.dumps(request),
        environment={
            "KOR_TRAVEL_MAP_PG_DSN": dsn,
            "KOR_TRAVEL_MAP_IMAGE_REVISION": _SOURCE_REVISION,
        },
    )

    _assert_narrow_error(result, returncode=1, error_code="internal_error")
    assert dsn not in result.stdout


def test_script_contains_no_host_path_or_network_argument_surface() -> None:
    result = _run("preflight", "--dsn", _SECRET, stdin="{}")

    _assert_narrow_error(result, returncode=2, error_code="invalid_arguments")

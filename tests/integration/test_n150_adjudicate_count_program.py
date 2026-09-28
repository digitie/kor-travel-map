"""`scripts/n150/adjudicate.sh`가 Map API 컨테이너 안에서 돌리는 잔여물 측정 프로그램 (ADR-103).

그 프로그램은 prod에서만 돈다 — n150 호스트 스크립트는 여기 말고는 실행되지 않는다. 그래서
스크립트에서 **그대로 떼어** 배포 경로와 같은 모양으로 실행한다: 이 컨테이너의
`KOR_TRAVEL_MAP_PG_DSN`(`postgresql+asyncpg://ktm_feature_service…`)만 env로 주고, `python -I -B -`
stdin으로 프로그램을, argv로 `run_id`를 준다. `+asyncpg` 제거, READ ONLY transaction 안의
`SET LOCAL ROLE ktm_feature_schema_owner`, bind parameter 타입 추론이 실제 스키마에서 되는지 본다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import normalize_async_dsn
from tests.integration._application_300_bootstrap import _TEST_RUNTIME_PASSWORD

pytestmark = pytest.mark.integration

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "n150" / "adjudicate.sh"


def _count_program() -> str:
    source = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"COUNT_PROGRAM = r'''\n(.*?)'''\n", source, re.DOTALL)
    assert match is not None, "adjudicate.sh에서 COUNT_PROGRAM을 찾지 못했다"
    return match.group(1)


def _run(dsn: str, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-B", "-", run_id],
        input=_count_program(),
        env={"PATH": os.environ.get("PATH", ""), "KOR_TRAVEL_MAP_PG_DSN": dsn},
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def service_dsn(pg_container: Any, migrated_engine: AsyncEngine) -> str:
    """배포의 API 런타임과 같은 LOGIN(`ktm_feature_service`)의 asyncpg DSN."""

    del migrated_engine  # role·schema가 만들어져 있어야 한다.
    url = make_url(normalize_async_dsn(pg_container.get_connection_url()))
    return url.set(
        username="ktm_feature_service", password=_TEST_RUNTIME_PASSWORD
    ).render_as_string(hide_password=False)


def test_count_program_reads_four_residue_rows_as_the_service_login(service_dsn: str) -> None:
    assert service_dsn.startswith("postgresql+asyncpg://")
    # run_id에 SQL 따옴표를 섞는다 — 문자열 결합이었다면 여기서 문법 오류가 난다.
    proc = _run(service_dsn, "e2e-run-'quoted'-probe")
    assert proc.returncode == 0, proc.stderr[-800:]
    residue = json.loads(proc.stdout)
    assert set(residue) == {
        "owned_features",
        "any_acceptance_prefix",
        "acceptance_aliases",
        "feature_requests",
    }
    assert all(isinstance(value, int) and value >= 0 for value in residue.values())
    assert residue["owned_features"] == 0
    assert residue["feature_requests"] == 0


def test_count_program_fails_loudly_without_the_dsn() -> None:
    """DSN이 없으면 0을 지어내지 않고 실패한다(판정이 "잔여물 0"으로 통과하면 안 된다)."""

    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-", "run"],
        input=_count_program(),
        env={"PATH": os.environ.get("PATH", "")},
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode != 0
    assert proc.stdout == ""

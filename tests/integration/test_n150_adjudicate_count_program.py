"""`scripts/n150/adjudicate.sh`가 Map API 컨테이너 안에서 돌리는 잔여물 측정 프로그램 (ADR-103).

그 프로그램은 prod에서만 돈다 — n150 호스트 스크립트는 여기 말고는 실행되지 않는다. 그래서
스크립트에서 **그대로 떼어** 배포 경로와 같은 모양으로 실행한다: 이 컨테이너의
`KOR_TRAVEL_MAP_PG_DSN`(`postgresql+asyncpg://ktm_feature_service…`)만 env로 주고, `python -I -B -`
stdin으로 프로그램을, argv로 `run_id`를 준다. `+asyncpg` 제거, READ ONLY transaction 안의
`SET LOCAL ROLE ktm_feature_schema_owner`, bind parameter 타입 추론이 실제 스키마에서 되는지 본다.

0은 이 판정에서 **위험한 방향**이다 — 늘 0을 내는 프로그램이면 `adjudicate.sh`가 잔여물이
남은 lane을 `clear-blocked`로 지운다. 그래서 세어야 할 행을 실제로 심은 양성 대조가 있다.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.db import normalize_async_dsn
from tests.integration._application_300_bootstrap import _TEST_RUNTIME_PASSWORD

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "n150" / "adjudicate.sh"
_FIXTURE_MODULE = _ROOT / "scripts" / "admin_feature_live_fixture.py"

#: SQL 따옴표를 섞은 run_id — 문자열 결합이었다면 문법 오류가 난다.
_RUN_ID = "e2e-run-'quoted'-probe"

#: 판정 프로그램이 읽는 표와 열. 양성 대조 DB는 이 열만 **실제 스키마의 타입 그대로** 만든다.
_READ_COLUMNS: dict[str, tuple[str, ...]] = {
    "feature.features": ("feature_id", "name"),
    "feature.feature_aliases": ("alias",),
    "ops.feature_requests": ("resolved_feature_id",),
}


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


def _fixture_name(run_id: str) -> str:
    """D2 fixture가 API-owned row에 붙이는 이름. 잔여물 소유권 키의 정본이다."""

    spec = importlib.util.spec_from_file_location("admin_feature_live_fixture", _FIXTURE_MODULE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module._admin_fixture_name(run_id))


def _read_column_types(admin_dsn: str) -> dict[str, list[tuple[str, str]]]:
    """판정 프로그램이 읽는 열의 실제 타입(migrated DB의 catalog에서)."""

    found: dict[str, list[tuple[str, str]]] = {}
    with psycopg.connect(admin_dsn) as connection:
        for relation, columns in _READ_COLUMNS.items():
            rows = connection.execute(
                "SELECT attname, pg_catalog.format_type(atttypid, atttypmod) "
                "FROM pg_catalog.pg_attribute "
                "WHERE attrelid = CAST(%s AS regclass) AND attname = ANY(%s) "
                "AND NOT attisdropped ORDER BY attnum",
                (relation, list(columns)),
            ).fetchall()
            assert {str(row[0]) for row in rows} == set(columns), relation
            found[relation] = [(str(row[0]), str(row[1])) for row in rows]
    return found


@pytest.fixture
def residue_probe_dsn(pg_container: Any, service_dsn: str) -> Iterator[str]:
    """세어야 할 잔여물을 **커밋해 둔** 버리는 DB의 service DSN.

    양성 대조는 migrated DB에 둘 수 없다. session이 나눠 쓰는 DB이고, `ops.feature_requests`는
    삭제가 막힌 증거 표이며(`trg_feature_requests_no_delete`), `feature.feature_aliases`의 CHECK는
    `e2e_live_acceptance::` alias를 받지 않는다. 프로그램은 별도 프로세스·별도 연결이라 커밋되지
    않은 seed를 보지 못한다. 그래서 같은 cluster에 DB를 하나 만들고, 프로그램이 읽는 열만 실제
    타입으로 만들어 `ktm_feature_schema_owner`로 심는다. role과 membership은 cluster 전역이라
    배포와 같은 `SET LOCAL ROLE` 경로가 그대로 돈다(service login에는 이 표의 권한이 없다).
    """

    admin_url = make_url(pg_container.get_connection_url()).set(drivername="postgresql")
    admin_dsn = admin_url.render_as_string(hide_password=False)
    columns = _read_column_types(admin_dsn)
    probe_database = f"ktm_adjudicate_probe_{uuid4().hex}"
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                sql.Identifier(probe_database)
            )
        )
    try:
        owned, other = uuid4(), uuid4()
        with psycopg.connect(
            admin_url.set(database=probe_database).render_as_string(hide_password=False)
        ) as connection:
            for schema in sorted({relation.split(".")[0] for relation in columns}):
                connection.execute(
                    sql.SQL("CREATE SCHEMA {} AUTHORIZATION ktm_feature_schema_owner").format(
                        sql.Identifier(schema)
                    )
                )
            connection.execute("SET LOCAL ROLE ktm_feature_schema_owner")
            for relation, typed in columns.items():
                connection.execute(
                    sql.SQL("CREATE TABLE {} ({})").format(
                        sql.Identifier(*relation.split(".")),
                        sql.SQL(", ").join(
                            sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(type_name))
                            for name, type_name in typed
                        ),
                    )
                )
            # 세어야 할 행 하나씩과, 세면 안 되는 이웃 행. 이웃이 있어야 "전부 센다"도 빨갛다.
            connection.execute(
                "INSERT INTO feature.features (feature_id, name) VALUES (%s, %s), (%s, %s)",
                (owned, _fixture_name(_RUN_ID), other, "남산서울타워"),
            )
            connection.execute(
                "INSERT INTO feature.feature_aliases (alias) VALUES (%s), (%s)",
                (f"e2e_live_acceptance::{_RUN_ID}::weather", "f_place_seoul_a_0123456789abcdef"),
            )
            connection.execute(
                "INSERT INTO ops.feature_requests (resolved_feature_id) "
                "VALUES (%s), (%s), (NULL)",
                (owned, other),
            )
        yield make_url(service_dsn).set(database=probe_database).render_as_string(
            hide_password=False
        )
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(probe_database)
                )
            )


def test_count_program_counts_seeded_residue_for_its_run_id_only(
    residue_probe_dsn: str,
) -> None:
    """양성 대조: 심은 행을 센다. 늘 0을 내거나 LIKE·bind가 어긋난 프로그램은 여기서 빨갛다."""

    proc = _run(residue_probe_dsn, _RUN_ID)
    assert proc.returncode == 0, proc.stderr[-800:]
    assert json.loads(proc.stdout) == {
        "owned_features": 1,
        "any_acceptance_prefix": 1,
        "acceptance_aliases": 1,
        "feature_requests": 1,
    }
    # 다른 run의 소유분은 0이다 — run_id와 무관하게 세는 프로그램도 빨갛다. 접두 두 줄은
    # run과 무관하게 넓게 센다.
    other = _run(residue_probe_dsn, "e2e-run-another-probe")
    assert other.returncode == 0, other.stderr[-800:]
    assert json.loads(other.stdout) == {
        "owned_features": 0,
        "any_acceptance_prefix": 1,
        "acceptance_aliases": 1,
        "feature_requests": 0,
    }


def test_count_program_reads_four_residue_rows_as_the_service_login(service_dsn: str) -> None:
    assert service_dsn.startswith("postgresql+asyncpg://")
    # 실제 migrated 스키마에서 bind parameter 타입 추론과 권한 경로가 도는지 본다.
    proc = _run(service_dsn, _RUN_ID)
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

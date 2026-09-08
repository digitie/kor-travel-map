"""head 스키마 오라클(``alembic/head-schema.sql``)의 산출·정규화 정본.

왜 이 파일이 있는가
-------------------

``alembic/baseline/schema.sql``은 **rev 300 시점의 덤프**다. 그 뒤 migration
(301~)이 만든 것은 담기지 않는다 — 실측하면 306의 ``purge_manual_feature``도,
307의 ``trg_features_manual_feature_truncate_fence``도 baseline에 0건이다.

그런데 저장소의 유도형 검사기 다섯이 그 파일에서 **현행 계약을 유도**했다. 즉
검사기가 보는 세계가 head보다 뒤처져 있고, 그 뒤처짐은 조용하다 —
``tests/lint/test_admin_state_constraint_mapping.py``의 docstring이 스스로 그
한계를 적으면서 "지금은 그런 migration이 없다"고 했는데, T-VN-39가 정확히 그
migration이다.

그래서 **빈 DB를 head까지 올린 결과**를 덤프해 오라클로 커밋한다. 정본은 언제나
"빈 DB에서 head까지 올린 결과"이고(``docs/architecture/postgres-schema.md``),
이 파일은 그 결과의 기계 사본이다.

``baseline/schema.sql``과 무엇이 다른가
--------------------------------------

baseline은 **실행되는 migration 입력**이라 ``scripts/build-baseline.sh``가
ACL 블록 재배치·``CREATE SCHEMA IF NOT EXISTS`` 치환 등 무거운 정규화를 한다.
이 파일은 **읽히기만 하는 오라클**이므로 결정성만 확보하면 된다 — 매 덤프마다
바뀌는 토큰과 버전 주석만 걷어낸다. 실행 가능하지 않고, 실행하려 해서도 안 된다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from typing import Any

ROOT = Path(__file__).resolve().parents[2]

#: head 오라클의 위치. `alembic/baseline/` **밖**에 둔다 — 그 디렉터리는 migration
#: 입력의 자리이고, 이 파일을 거기 두면 언젠가 누가 실행하려 든다.
HEAD_SCHEMA_PATH = ROOT / "alembic" / "head-schema.sql"

#: 이 환경변수가 1이면 비교 대신 **기록**한다. 산출은 head DB가 필요하므로
#: (n150 통합 게이트) 로컬에서 되살릴 수 없고, 그래서 아티팩트로 커밋한다.
REGENERATE_ENV = "KTM_WRITE_HEAD_SCHEMA"

_DUMP_SCHEMAS = ("feature", "provider_sync", "ops")

#: PostgreSQL 16의 pg_dump가 내는 psql client-side fence. 토큰이 매번 달라
#: 그대로 두면 결정론적 아티팩트가 되지 않는다. `build-baseline.sh`와 같은 판정이다.
_PSQL_RESTRICT = re.compile(r"\\(?:un)?restrict [A-Za-z0-9]+")

#: 판올림마다 바뀌는 두 줄.
_VERSION_COMMENT = ("-- Dumped from database version", "-- Dumped by pg_dump version")

_HEADER = """\
-- AUTO-GENERATED — 손으로 고치지 마라.
--
-- 빈 DB를 `alembic upgrade head`로 올린 결과의 `pg_dump --schema-only`다.
-- 산출·정규화 정본은 `tests/integration/_head_schema_artifact.py`이고,
-- 최신성은 `tests/integration/test_alembic_metadata_consistency.py`의
-- `test_head_schema_artifact_matches_head`가 CI에서 강제한다.
--
-- 이 파일은 **오라클이지 migration 입력이 아니다.** 실행하지 마라.
-- 유도형 검사기는 `alembic/baseline/schema.sql`(rev 300 덤프) 대신 이 파일을 읽는다.
"""


def normalize_dump(raw: str) -> str:
    """덤프에서 **매 실행마다 바뀌는 것만** 걷어낸다.

    스키마 내용은 한 글자도 건드리지 않는다 — 걷어내는 것을 늘리면 오라클이
    그만큼 눈을 감는다.
    """

    kept: list[str] = []
    for line in raw.split("\n"):
        if _PSQL_RESTRICT.fullmatch(line):
            continue
        if line.startswith(_VERSION_COMMENT):
            continue
        kept.append(line)
    body = "\n".join(kept).strip("\n")
    return _HEADER + body + "\n"


def dump_head_schema(container: Any, database: str) -> str:
    """head까지 올라간 ``database``의 스키마를 정규화해 돌려준다.

    컨테이너 안에서 ``pg_dump``를 돌린다 — 호스트에 client가 있다고 가정하지
    않는다(n150 게이트는 컨테이너만 보장한다).
    """

    wrapped = container.get_wrapped_container()
    user = container.username
    command = [
        "pg_dump",
        "-U",
        user,
        "-d",
        database,
        "--schema-only",
        "--exclude-table=public.alembic_version",
    ]
    for schema in _DUMP_SCHEMAS:
        command.extend(("-n", schema))
    exit_code, output = wrapped.exec_run(command)
    if exit_code != 0:
        raise RuntimeError(
            f"pg_dump가 {exit_code}로 실패했다: {output.decode('utf-8', 'replace')[-2000:]}"
        )
    return normalize_dump(output.decode("utf-8"))

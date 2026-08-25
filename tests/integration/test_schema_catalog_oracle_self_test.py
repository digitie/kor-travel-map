"""`scripts/compare-schema-catalogs.sh --self-test` — 오라클 자체를 CI에서 재증명한다.

squash 동등성 증명의 오라클은 이 스크립트다(`alembic/versions/300_schema_baseline.py`
docstring "동등성 증명"). 그런데 오라클은 CI 어디에도 걸려 있지 않았다 —
`.github/workflows/` 다섯 파일 어느 것도 이 스크립트를 부르지 않는다. 누가 카탈로그
축을 지우거나 namespace 필터를 좁히면, 다음 baseline 갱신은 **아무것도 보지 않는
비교기**로 "동등하다"고 선언하게 된다. 검사기가 검사 대상을 안 보면서 green인 것이
이 저장소의 지배적 실패 양식이다(`compare-schema-catalogs.sh:19-22`).

`--self-test`는 기준 DB를 두 벌 복제해 한쪽에만 알려진 변조를 주입하고 비교기가
그것을 잡는지 본다. 대조는 **항상 자기 복제본끼리**이므로(스크립트 :170-183, :212-213)
기준 DB가 어느 경로로 만들어졌는지는 정확성에 영향이 없다 — 아카이브가 된 체인이
아니라 `alembic upgrade head`(=`300`)로 세워도 된다.

**다만 커버리지에는 영향이 있다.** 변조 SQL이 대상 DB에 적용되지 않으면 스크립트는
`SKIP`만 찍고 `놓침`으로 세지 않는다(:214-217). 빈 DB를 기준으로 주면 13종 전부
SKIP → "잡음 0 / 놓침 0" → **exit 0**이다. 그래서 이 테스트는 exit code만 보지 않고
(a) SKIP이 하나도 없고 (b) 스크립트가 **선언한** 변조 수만큼 실제로 잡혔는지를 센다.

기대값을 스크립트에서 읽는 (b)가 잡는 것은 **비대칭 편집**이다 — 축만 지우거나 변조를
no-op으로 만들면 `놓침 > 0`으로 선다. **변조를 통째로 지우는 것은 못 잡는다**: 선언도
실측도 같이 줄어 `21 == 21`로 초록이 된다(적대 리뷰가 `MUTATIONS`에서 한 줄 지워
실증했다). 그 편집은 축을 남긴 채 그 축을 증명하던 변조만 없앤다. 그래서 내려가지 않는
하한 `_MINIMUM_MUTATIONS`를 따로 둔다.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit, urlunsplit

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "compare-schema-catalogs.sh"
_BASE_DB = "ktm_oracle_base"

#: 스크립트가 만드는 스크래치 DB. 중간에 죽으면 남으므로 teardown이 쓸어낸다
#: (`compare-schema-catalogs.sh:164-165`).
_SCRATCH_LIKE = ("ktm_oracle_control_%", "ktm_oracle_mutant_%")


def _with_database(url: str, database: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{database}"))


async def _admin_connect(default_url: str) -> Any:
    """컨테이너 기본 DB로의 asyncpg autocommit 연결.

    `test_alembic_metadata_consistency.py:_admin_execute`와 같은 경로다. `CREATE`/
    `DROP DATABASE`는 트랜잭션에서도 함수(`DO` 블록)에서도 실행할 수 없으므로
    SQLAlchemy 엔진이 아니라 raw asyncpg를 쓴다.
    """
    import asyncpg

    parts = urlsplit(default_url)
    return await asyncpg.connect(
        user=parts.username,
        password=parts.password,
        host=parts.hostname,
        port=parts.port,
        database=(parts.path or "/postgres").lstrip("/"),
    )


async def _admin_execute(default_url: str, statement: str) -> None:
    conn = await _admin_connect(default_url)
    try:
        await conn.execute(statement)
    finally:
        await conn.close()


async def _admin_fetch_names(default_url: str, query: str) -> list[str]:
    conn = await _admin_connect(default_url)
    try:
        return [str(row[0]) for row in await conn.fetch(query)]
    finally:
        await conn.close()


#: 자체검증 변조의 **하한**. 기대값을 스크립트에서 읽는 단언은 "변조를 지우면 red"를
#: 만들지 못한다(선언과 실측이 같이 줄어든다). 이 상수는 그 비대칭을 메운다.
_MINIMUM_MUTATIONS = 22


def _declared_mutation_count() -> int:
    """스크립트가 **선언한** 변조 수. 정본은 스크립트 자신이다.

    여기 숫자를 박으면 변조를 추가할 때 이 테스트가 뒤처지고, 변조를 지워도 침묵한다.
    `test_alembic_upgrade.py:_archived_revisions()`가 파일명 대신 선언을 읽는 것과
    같은 이유다.
    """
    source = _SCRIPT.read_text(encoding="utf-8")
    block = re.search(r"^  MUTATIONS=\(\n(.*?)^  \)\n", source, re.S | re.M)
    assert block is not None, "MUTATIONS 배열을 찾지 못했다 — 스크립트 구조가 바뀌었다"
    entries = [
        line for line in block.group(1).splitlines() if line.lstrip().startswith('"')
    ]
    assert entries, "MUTATIONS 배열이 비어 있다 — 오라클이 아무것도 검증하지 않는다"
    return len(entries)


async def _build_base_database(raw_dsn: str) -> None:
    """배포와 같은 경로(migrator LOGIN → SET ROLE schema owner, ADR-090)로 head까지."""
    from alembic.config import Config

    from kortravelmap.infra.db import normalize_async_dsn
    from tests.integration._application_300_bootstrap import (
        upgrade_head_with_application_300_bootstrap,
    )

    base_dsn = normalize_async_dsn(_with_database(raw_dsn, _BASE_DB))
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    await upgrade_head_with_application_300_bootstrap(cfg, base_dsn)


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """blocking 실행을 worker thread로 분리한다(ASYNC221).

    `encoding`을 명시하는 이유: 스크립트 출력이 한국어라 locale이 UTF-8이 아닌
    호스트에서 아래 집계 정규식이 조용히 어긋난다.
    """
    return subprocess.run(  # noqa: S603 - 저장소 스크립트를 그대로 실행하는 것이 목적이다
        command, check=False, capture_output=True, text=True, encoding="utf-8"
    )


@pytest.fixture(scope="module")
def oracle_container() -> Iterator[Any]:
    """**전용** PostGIS 컨테이너. 세션 공유 컨테이너를 쓰지 않는다.

    자체검증은 기준 DB를 23번 `CREATE DATABASE … TEMPLATE` / `DROP` 한다. 그것을 세션
    공유 인스턴스에서 하면 같은 인스턴스를 재는 planner 테스트를 교란할 수 있다.
    `25128842`(self-test 도입)의 CI integration에서
    `test_t212d_perf_explain::…_index_compatible`이 깨졌고, 직전 `5d5f27c6`은 green,
    같은 커밋의 로컬도 0 FAILED였다. 파일 정렬상 그 테스트는 이 파일 **뒤**에 돈다.

    ⚠️ **인과는 단일 관측이고 기전도 얇다.** 적대 리뷰가 그것을 짚었다: 그 테스트는
    EXPLAIN 직전에 전체 `ANALYZE`를 돌리므로 "낡은 통계"로 설명되지 않고, PG16의
    `CREATE DATABASE` 기본 전략은 `WAL_LOG`라 `FILE_COPY`가 강제하는 checkpoint도
    없다. 남는 경로는 autovacuum worker 경합과 page cache 축출 정도다. 그리고
    `test_gist_brin_index_audit`의 red는 **이 격리로 설명되지 않는다** — 알파벳 순서상
    이 파일보다 먼저 돌고, 그 테스트 자신의 docstring이 "부하가 높으면 red, 낮으면
    green, 실측 ratio 1.02x로 임계에 붙어 있다"고 적어 둔 선행 부채다.

    그래도 격리한다: 공유 인스턴스에 대한 DDL을 0회로 만드는 것은 확실한 개선이고
    되돌릴 이유가 없다. 다만 **호스트 page cache는 여전히 공유**하므로 진짜 기전이
    그쪽이면 이것으로 해결되지 않는다는 점을 함께 적어 둔다.
    """

    from tests.integration.conftest import _POSTGIS_IMAGE

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover — dev extras 미설치
        pytest.skip("testcontainers not installed")
    try:
        # 이미지 태그는 conftest가 정본이다. 여기 박으면 conftest가 올라갈 때 이
        # 게이트만 **조용히 옛 PG에서** 돈다 — 같은 커밋이 grantee 목록에서 없앤 것과
        # 똑같은 손 복제였다(적대 리뷰 지적).
        container = PostgresContainer(_POSTGIS_IMAGE)
    except Exception as exc:  # pragma: no cover — Docker 없음
        pytest.skip(f"PostgresContainer init failed (Docker?): {exc}")
    with container:
        yield container


@pytest.fixture
async def oracle_base_database(oracle_container: Any) -> AsyncIterator[str]:
    """`CREATE DATABASE ... TEMPLATE`의 원본이 될 전용 DB. raw DSN을 돌려준다.

    전용이어야 하는 이유는 둘이다.

    1. `TEMPLATE`은 원본에 **다른 연결이 없어야** 성립한다. 컨테이너 기본 DB는
       session-scope `pg_engine`(conftest.py:79)과 `migrated_engine`(:167)이 풀을
       물고 있고, `migrated_engine`은 CLI 계열 테스트 때문에 기본 DB를 **의도적으로**
       공유한다(conftest.py:192-195). 그래서 기본 DB로는 이 게이트를 돌릴 수 없다.
    2. 스크립트가 만드는 스크래치 DB가 다른 테스트와 섞이지 않는다.
    """
    raw_dsn = oracle_container.get_connection_url()
    await _admin_execute(raw_dsn, f'DROP DATABASE IF EXISTS "{_BASE_DB}" WITH (FORCE)')
    await _admin_execute(raw_dsn, f'CREATE DATABASE "{_BASE_DB}"')
    try:
        await _build_base_database(raw_dsn)
        # alembic env.py와 bootstrap 엔진은 dispose한다(alembic/env.py:285). 그 사실에
        # 기대지 않고 확인 사살한다 — 연결이 하나라도 남으면 TEMPLATE 복제가
        # `source database is being accessed by other users`로 죽는다.
        await _admin_execute(
            raw_dsn,
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{_BASE_DB}' AND pid <> pg_backend_pid()",
        )
        yield raw_dsn
    finally:
        leftovers = await _admin_fetch_names(
            raw_dsn,
            f"SELECT datname FROM pg_database WHERE datname = '{_BASE_DB}'"
            f" OR datname LIKE '{_SCRATCH_LIKE[0]}' OR datname LIKE '{_SCRATCH_LIKE[1]}'",
        )
        for name in leftovers:
            await _admin_execute(
                raw_dsn, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'
            )


async def test_catalog_oracle_detects_every_declared_mutation(
    oracle_container: Any, oracle_base_database: str
) -> None:
    """오라클이 선언한 변조를 **전부** 잡는다. 하나라도 놓치거나 건너뛰면 red다."""
    from sqlalchemy.engine import make_url

    container_id = oracle_container.get_wrapped_container().id
    admin_user = make_url(oracle_base_database).username
    assert admin_user is not None, "컨테이너 DSN에서 관리자 이름을 읽지 못했다"

    result = await asyncio.to_thread(
        _run,
        [
            "bash",
            str(_SCRIPT),
            "--self-test",
            container_id,
            _BASE_DB,
            "--admin-user",
            admin_user,
        ],
    )
    report = (
        f"exit={result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert result.returncode == 0, report

    # exit 0만으로는 부족하다. 변조가 대상 DB에 **적용되지 않으면** SKIP으로 넘어가고
    # 그것은 `놓침`으로 세지 않는다(compare-schema-catalogs.sh:214-217). 기준 DB가
    # 비어 있으면 13종 전부 SKIP → "잡음 0 / 놓침 0" → exit 0이다. 그 vacuous green이
    # 정확히 이 게이트가 막으려는 상태이므로 집계를 직접 센다.
    assert "SKIP" not in result.stdout, f"변조가 기준 DB에 적용되지 않았다\n{report}"
    tally = re.search(r"잡음 (\d+) / 놓침 (\d+)", result.stdout)
    assert tally is not None, f"자체검증 집계 줄을 찾지 못했다\n{report}"
    caught, missed = int(tally.group(1)), int(tally.group(2))
    assert missed == 0, report
    assert caught == _declared_mutation_count(), (
        f"선언 {_declared_mutation_count()}종 중 {caught}종만 검증됐다\n{report}"
    )
    # 위 단언만으로는 **변조를 지우는 것**을 못 잡는다 — 기대값을 검사 대상과 같은
    # 파일에서 읽으므로 한 줄을 지우면 선언도 실측도 같이 줄어 21 == 21로 초록이다
    # (적대 리뷰가 `MUTATIONS`에서 한 줄 지워 실증했다). 그 편집은 축을 남긴 채 그
    # 축을 증명하던 변조만 없앤다. 그래서 **내려가지 않는 하한**을 따로 둔다.
    # 변조를 늘리면 이 값도 함께 올려라 — 줄이는 방향은 리뷰 대상이다.
    assert caught >= _MINIMUM_MUTATIONS, (
        f"자체검증 변조가 {_MINIMUM_MUTATIONS}종 아래로 줄었다({caught}종) —"
        f" 축을 남긴 채 그 축을 증명하던 변조만 지운 편집이다\n{report}"
    )

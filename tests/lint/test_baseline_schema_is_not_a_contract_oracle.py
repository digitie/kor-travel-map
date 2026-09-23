"""`alembic/baseline/schema.sql`을 현행 계약의 유도원으로 쓰지 못하게 막는다.

## 왜

그 파일은 **baseline root 시점의 덤프**이고 head의 사본이 아니다. 2026-09-08까지
유도형 검사기 다섯이 거기서 현행 계약을 유도하고 있었고, 그 뒤처짐은 조용했다.

당시 실측 차이(rev 300 baseline 대 head): `feature.purge_manual_feature`는 baseline
0건 head 6건, `trg_features_manual_feature_truncate_fence`는 0건 대 3건, 루틴 본문은
155개 대 163개였다. 그리고 `uq_manual_feature_identity_claims_exact`를 baseline은
UNIQUE **제약**으로, head는 부분 유니크 **인덱스**로 봤다 — 낡음은 "덜 본다"에
그치지 않고 **모양을 틀리게 본다.**

`300`~`313`을 `400` 하나로 접은 지금 두 파일은 같은 순간의 head를 서술한다. 그래서
차이가 0이고, 그것이 이 규칙을 없앨 이유는 못 된다 — `401`이 붙는 순간 baseline은
다시 뒤처지고 그 뒤처짐은 여전히 조용하기 때문이다. 아래
`test_baseline_and_head_agree_while_the_root_is_the_head`가 지금의 0을 **확인**해서,
둘 중 하나만 다시 뜨는 일을 잡는다.

## 무엇을 허용하나

baseline을 읽는 정당한 이유는 셋뿐이다 — 그것을 **실행하는** migration, 그것을
**만들어 내는** 빌더, 그리고 그것을 목적 상태로 삼는 0236 handoff. 나머지는 head
오라클(`alembic/head-schema.sql`)을 읽어야 한다. 그 오라클의 최신성은
`tests/integration/test_alembic_metadata_consistency.py`의
`test_head_schema_artifact_matches_head`가 CI에서 강제한다.

## 산문은 대상이 아니다

"왜 baseline을 쓰지 않는가"를 적은 주석·docstring은 오히려 권장된다. 그래서 이
검사는 파이썬을 **AST로** 읽어 경로를 구성하는 문자열 리터럴만 본다. 줄 단위
문자열 검색으로 하면 자기 설명이 자기를 잡는다(첫 구현에서 실제로 그랬다).

## 이 검사가 공허해지는 경우

허용 목록에 새 경로를 추가하는 것으로 언제든 우회할 수 있다. 그래서 목록을 짧게
유지하고, 추가할 때 **왜 head 오라클로는 안 되는지**를 같은 줄에 적게 한다.
"""

from __future__ import annotations

import ast
import difflib
import json
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: baseline을 **실행**하거나 **만들거나** 그 계보를 다루는 자리. 여기 없는 파일이
#: baseline으로 경로를 구성하면 그것은 오라클로 쓰는 것이고, head와 어긋난다.
_ALLOWED = {
    # baseline을 실제로 적용하는 migration.
    "alembic/versions/400_schema_baseline.py",
    # baseline과 head 오라클을 **대조**하는 이 파일.
    "tests/lint/test_baseline_schema_is_not_a_contract_oracle.py",
    # `runtime_privileges.py`의 ACL 인벤토리는 head와 **rev 300 두 시점**에서 돈다
    # (0236 → 300 handoff가 stamp 직후 부른다). "이 루틴은 `300`에 아직 없어도 된다"는
    # 선언이 실제 `300` 상태와 맞는지는 head 오라클로는 잴 수 없다 — 재는 대상이 head가
    # 아니라 baseline root 그 자체다. 이 파일은 head 대조도 **함께** 한다.
    "tests/lint/test_db_procedure_signatures_exist_in_head.py",
}

#: 검색 대상. 생성물·아카이브는 뺀다.
_SEARCH_ROOTS = (
    "src",
    "packages",
    "tests",
    "scripts",
    "docker",
    "alembic/versions",
)


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(_ROOT)).replace("\\", "/")


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            ids.add(id(first.value))
    return ids


def _python_offenders(text: str) -> list[int]:
    """경로를 **구성하는** 문자열 리터럴만 잡는다. 주석·docstring은 통과한다."""

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    docstrings = _docstring_ids(tree)
    hits: set[int] = set()
    segments: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings:
            continue
        value = node.value
        if "baseline/schema.sql" in value:
            hits.add(node.lineno)
        # `_ROOT / "alembic" / "baseline" / "schema.sql"` 형태는 조각으로 나뉜다.
        # 같은 줄에 두 조각이 함께 있으면 경로 구성으로 본다.
        if value in {"baseline", "schema.sql"}:
            segments.setdefault(node.lineno, set()).add(value)
    hits.update(
        line for line, parts in segments.items() if parts == {"baseline", "schema.sql"}
    )
    return sorted(hits)


def _shell_offenders(text: str) -> list[int]:
    """셸은 파싱하지 않는다 — 주석(`#`)만 걷어내고 본다."""

    return [
        number
        for number, line in enumerate(text.split("\n"), start=1)
        if "baseline/schema.sql" in line and not line.lstrip().startswith("#")
    ]


def _offenders() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for root_name in _SEARCH_ROOTS:
        root = _ROOT / root_name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".sh"}:
                continue
            rel = _relative(path)
            if rel in _ALLOWED:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            hits = _python_offenders(text) if path.suffix == ".py" else _shell_offenders(text)
            if hits:
                found[rel] = hits
    return found


def test_the_search_roots_are_live() -> None:
    """탐색 루트가 옮겨지면 이 검사는 조용히 0건이 된다.

    루트별로 잰다 — 합쳐서 세면 하나가 죽어도 나머지가 채운다.
    """

    dead = sorted(name for name in _SEARCH_ROOTS if not any((_ROOT / name).rglob("*.py")))
    assert not dead, f"탐색 루트에 파이썬 모듈이 없다 — 경로가 옮겨졌다: {dead}"


def test_the_allowlist_entries_still_exist() -> None:
    """허용 목록이 죽은 경로를 들고 있으면 그만큼 검사가 느슨해진 채 굳는다."""

    missing = sorted(rel for rel in _ALLOWED if not (_ROOT / rel).is_file())
    assert not missing, f"허용 목록의 파일이 사라졌다: {missing}"


def test_the_detector_sees_a_planted_path_construction() -> None:
    """탐지기가 실제로 경로 구성을 잡는지 **심어서** 확인한다.

    AST로 좁힌 뒤에는 "아무것도 안 잡는데 초록"이 가장 그럴듯한 실패다.
    """

    planted = (
        '"""문서에 baseline/schema.sql 이라 적는 것은 잡히면 안 된다."""\n'
        "import pathlib\n"
        "# 주석에 적는 것도 잡히면 안 된다: baseline/schema.sql\n"
        'GOOD = pathlib.Path("alembic") / "head-schema.sql"\n'
        'BAD_ONE = pathlib.Path("alembic/baseline/schema.sql")\n'
        'BAD_TWO = pathlib.Path("alembic") / "baseline" / "schema.sql"\n'
    )
    assert _python_offenders(planted) == [5, 6]


#: 실행 가능한 baseline이 오라클과 달라지는 **정확한 네 가지**. 둘 다 같은 덤프에서
#: 나오고, baseline 쪽만 (a) 자기 설명 헤더가 없고 (b) schema 생성이 멱등하며
#: (c) ACL 블록마다 소유자로 role을 바꾸는 줄이 끼워져 있고 (d) pg_dump의
#: `search_path` 고정을 뺐다 — alembic/env.py가 트랜잭션 안에서 세운 것을 덮으면
#: 안 되기 때문이다. 그 넷만 지우면 두 파일은 한 글자까지 같아야 한다.
_ROLE_SWITCH = re.compile(
    r"^(?:SELECT set_config\('(?:role|ktm\.baseline_prior_role)'.*|"
    r"DO \$ktm_txn\$|BEGIN|END|\$ktm_txn\$;|"
    r"\s+IF coalesce\(current_setting\('ktm\.baseline_prior_role'.*|"
    r"\s+RAISE EXCEPTION|\s+'baseline은 하나의 트랜잭션.*|"
    r"\s+USING ERRCODE = '25P01';|\s+END IF;|-- .*ACL 구간.*|"
    r"-- GRANT/REVOKE는 소유자만.*|-- 아니라 경고 후 무시된다.*|"
    r"-- 트랜잭션 밖에서 돌리면.*|-- 소유자 아닌 세션으로 나간다\..*|"
    r"-- 문자열\*\*로 돌아오므로.*|"
    r"SELECT pg_catalog\.set_config\('search_path'.*)$"
)


def _comparable(text: str) -> list[str]:
    """두 덤프를 비교 가능한 형태로 만든다 — 지우는 것은 위 셋뿐이다."""

    body = text.split("SET statement_timeout = 0;", 1)[-1]
    kept: list[str] = []
    for line in body.split("\n"):
        if _ROLE_SWITCH.match(line):
            continue
        kept.append(line.replace("CREATE SCHEMA IF NOT EXISTS ", "CREATE SCHEMA "))
    return [line for line in kept if line.strip()]


def test_baseline_and_head_agree_while_the_root_is_the_head() -> None:
    """graph에 revision이 하나뿐인 동안 두 덤프는 같은 카탈로그를 서술해야 한다.

    스쿼시 직후에는 둘이 같은 순간의 head에서 나오므로 같다. 그 등식을 **확인해
    두면** 한쪽만 다시 뜨는 사고가 여기서 잡힌다. `401`이 붙으면 head가 root보다
    앞서므로 이 검사는 스스로 비켜난다 — 그때부터는 등식이 참이 아니고, 참이길
    요구하면 revision을 더할 때마다 재스쿼시를 강요하게 된다.
    """

    head = _ROOT / "alembic" / "head-schema.sql"
    baseline = _ROOT / "alembic" / "baseline" / "schema.sql"
    assert head.is_file(), f"head 오라클이 없다: {head}"

    graph = json.loads(
        (_ROOT / "src" / "kortravelmap" / "_application_migration_graph.json").read_text(
            encoding="utf-8"
        )
    )
    if len(graph["revisions"]) != 1:
        pytest.skip("head가 baseline root보다 앞선다 — 두 덤프가 갈리는 것이 정상이다")

    head_lines = _comparable(head.read_text(encoding="utf-8"))
    baseline_lines = _comparable(baseline.read_text(encoding="utf-8"))
    if head_lines == baseline_lines:
        return

    diff = list(
        difflib.unified_diff(baseline_lines, head_lines, "baseline", "head", n=1, lineterm="")
    )
    raise AssertionError(
        "baseline과 head 오라클이 같은 head를 서술하지 않는다 — 한쪽만 다시 뜬 것이다:\n"
        + "\n".join(diff[:40])
    )


def test_no_module_derives_current_contract_from_the_baseline_dump() -> None:
    offenders = _offenders()
    assert offenders == {}, (
        "이 파일들이 `alembic/baseline/schema.sql`로 경로를 구성한다. 그 파일은 baseline "
        "root 시점 덤프라 그 뒤 revision을 담지 않는다 — 현행 계약의 유도원으로 쓰면 "
        "검사기가 낡은 세계를 보고, 그 뒤처짐은 조용하다. `alembic/head-schema.sql`을 "
        "읽어라. "
        f"{offenders}"
    )

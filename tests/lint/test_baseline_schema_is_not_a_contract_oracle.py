"""`alembic/baseline/schema.sql`을 현행 계약의 유도원으로 쓰지 못하게 막는다.

## 왜

그 파일은 **rev 300 시점의 덤프**다. migration 입력이지 head의 사본이 아니다.
그런데 2026-09-08(T-VN-39 착수)까지 유도형 검사기 다섯이 거기서 현행 계약을
유도하고 있었고, 그 뒤처짐은 조용했다.

실측 차이:

- `feature.purge_manual_feature` — baseline 0건, head 6건 (306)
- `trg_features_manual_feature_truncate_fence` — baseline 0건, head 3건 (307)
- `feature.manual_feature_purge_records` — baseline 0건, head 29건 (306)
- 루틴 본문 수 — baseline 155개, head 163개
- `uq_manual_feature_identity_claims_exact` — baseline은 UNIQUE **제약**으로 보고
  head는 부분 유니크 **인덱스**로 본다(306이 바꿨다). 즉 낡음은 "덜 본다"에
  그치지 않고 **모양을 틀리게 본다.**

`tests/lint/test_admin_state_constraint_mapping.py`의 docstring이 이 한계를 스스로
적으면서 "지금은 그런 migration이 없다"고 했는데, T-VN-39가 정확히 그 migration이다.

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
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: baseline을 **실행**하거나 **만들거나** 그 계보를 다루는 자리. 여기 없는 파일이
#: baseline으로 경로를 구성하면 그것은 오라클로 쓰는 것이고, head와 어긋난다.
_ALLOWED = {
    # baseline을 실제로 적용하는 migration.
    "alembic/versions/300_schema_baseline.py",
    # 0236 → 300 handoff. baseline이 곧 그 handoff의 목적 상태다.
    "docker/transition-application-schema-0236-to-300.py",
    # baseline을 산출하는 빌더 자신.
    "scripts/build-baseline.sh",
    # head 오라클이 baseline보다 새롭다는 것을 **대조로 증명**하는 이 파일.
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


def test_the_head_oracle_exists_and_is_newer_than_baseline() -> None:
    """head 오라클이 실재하고 baseline보다 **더 많이** 담는지 확인한다.

    오라클을 옮겨 놓고 그 파일이 실은 baseline의 사본이면 아무것도 고쳐지지 않는다.
    301~ 이후 산물의 존재로 그 사실을 못 박는다.
    """

    head = _ROOT / "alembic" / "head-schema.sql"
    baseline = _ROOT / "alembic" / "baseline" / "schema.sql"
    assert head.is_file(), f"head 오라클이 없다: {head}"
    head_text = head.read_text(encoding="utf-8")
    baseline_text = baseline.read_text(encoding="utf-8")

    for marker in (
        "purge_manual_feature",
        "manual_feature_purge_records",
        "trg_features_manual_feature_truncate_fence",
    ):
        assert marker not in baseline_text, (
            f"{marker!r}가 baseline에 있다 — baseline이 다시 덤프됐다면 이 검사의 "
            "전제(baseline은 rev 300 시점)가 바뀐 것이므로 여기를 갱신하라."
        )
        assert marker in head_text, (
            f"{marker!r}가 head 오라클에 없다 — 오라클이 head가 아니거나 낡았다."
        )


def test_no_module_derives_current_contract_from_the_baseline_dump() -> None:
    offenders = _offenders()
    assert offenders == {}, (
        "이 파일들이 `alembic/baseline/schema.sql`로 경로를 구성한다. 그 파일은 rev 300 "
        "시점 덤프라 301~ 이후를 담지 않는다 — 현행 계약의 유도원으로 쓰면 검사기가 "
        "낡은 세계를 보고, 그 뒤처짐은 조용하다. `alembic/head-schema.sql`을 읽어라. "
        f"{offenders}"
    )

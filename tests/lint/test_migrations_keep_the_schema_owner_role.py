"""마이그레이션은 **롤을 되돌린 채로 끝나면 안 된다.**

2026-09-19 CI: `310_seoul_source_move`가 본문 끝에 `RESET ROLE`을 넣었다. 본문은
전부 성공했는데 그 직후 alembic이 내는 `UPDATE alembic_version`이
`permission denied for table alembic_version`으로 죽었고, 통합 검사 **1,080건**이
같은 원인으로 무너졌다.

이 저장소의 마이그레이션은 전부 `SET ROLE ktm_feature_schema_owner`를 **켠 채로
끝난다.** 그것이 우연이 아니라 계약이다 — 접속 로그인 롤에는 `alembic_version`의
UPDATE 권한이 없고, 버전 기록은 마이그레이션 본문이 끝난 **뒤** 같은 트랜잭션에서
나간다. 그런데 그 계약이 **어디에도 적혀 있지 않았다.** 300~309가 모두 우연히
지키고 있었을 뿐이라, 다음 사람이 "깔끔하게 정리한다"며 되돌리면 그때 깨진다.

그래서 여기서 센다. 검사가 보는 것은 **효과**다 — 파일에 `RESET ROLE`이 있는가가
아니라, `upgrade`/`downgrade`가 실행하는 문장열의 **마지막 롤 상태**가 로그인 롤로
돌아가 있는가다. 그래야 `SET ROLE`을 여러 번 오가는 마이그레이션(307이 그렇다)도
정상으로 통과한다.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
from typing import Final

import pytest

REPO_ROOT: Final = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS: Final = REPO_ROOT / "alembic" / "versions"

#: 마이그레이션이 남겨도 되는 롤. 비우면(=로그인 롤로 되돌리면) 버전 기록이 죽는다.
#:
#: 하나만 두는 이유: 지금 모든 마이그레이션이 이 롤로 끝나고, 다른 롤이 필요해지면
#: 그때 **그 롤이 `alembic_version`을 쓸 수 있는지 확인하고** 여기 추가하는 것이
#: 맞다. 목록을 미리 넓혀 두면 확인 없이 들어온다.
_ALLOWED_TRAILING_ROLES: Final = frozenset({"ktm_feature_schema_owner"})

_RESET_ROLE: Final = "reset role"
_SET_ROLE: Final = "set role "


def _migration_paths() -> list[pathlib.Path]:
    return sorted(_VERSIONS.glob("[0-9]*.py"))


def _migration_modules() -> list[tuple[str, ast.Module]]:
    modules: list[tuple[str, ast.Module]] = []
    for path in _migration_paths():
        modules.append((path.name, ast.parse(path.read_text(encoding="utf-8"))))
    return modules


def _imported_statements(path: pathlib.Path, function_name: str) -> list[str] | None:
    """마이그레이션을 **실제로 import해서** 그 문장 튜플을 그대로 읽는다.

    AST만으로는 `*_sidecar("...sql")`처럼 **호출이 만드는** 문장을 볼 수 없다.
    309부터 이 저장소의 마이그레이션은 본문을 별도 `.sql` 사이드카에 두고
    파일별 달러 인용 인식 분할기로 잘라 넣는다 — 즉 AST가 보는 리터럴은
    전체의 일부일 뿐이다.

    312의 경우 AST는 세 문장만 보고 초록을 줬다(2026-09-20 적대 리뷰). 실제로는
    42문장이고 그중 여덟이 `SET ROLE`이다. 검사가 보지 못한 자리에서 롤이
    되돌아가면 이 검사는 아무 말도 하지 않는다.

    import가 실패하면(alembic 컨텍스트가 필요한 드문 형태) ``None``을 돌려
    호출자가 AST로 떨어지게 한다 — 검사를 잃는 대신 덜 보는 쪽이 낫다.
    """

    attribute = f"_{function_name.upper()}_STATEMENTS"
    spec = importlib.util.spec_from_file_location(f"_migration_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:  # noqa: BLE001 - import 불가는 판정이 아니라 관측의 한계다
        return None
    statements = getattr(module, attribute, None)
    if not isinstance(statements, tuple | list):
        return None
    if not all(isinstance(statement, str) for statement in statements):
        return None
    return list(statements)


def _string_constants(module: ast.Module) -> dict[str, list[str]]:
    """모듈 최상위의 문자열/문자열 튜플 상수를 이름으로 모은다.

    `_UPGRADE_STATEMENTS`처럼 튜플에 담아 두고 루프로 실행하는 형태가 이 저장소의
    관례다. AST로 읽는 이유는 마이그레이션을 import하면 alembic 컨텍스트가 필요하기
    때문이다.
    """

    found: dict[str, list[str]] = {}
    for node in module.body:
        if not isinstance(node, ast.AnnAssign | ast.Assign):
            continue
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else list(node.targets)
        )
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        if not names or node.value is None:
            continue
        literals: list[str] = []
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            literals = [value.value]
        elif isinstance(value, ast.Tuple | ast.List):
            for element in value.elts:
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    literals.append(element.value)
                elif isinstance(element, ast.Name):
                    literals.extend(found.get(element.id, []))
                elif isinstance(element, ast.Starred) and isinstance(
                    element.value, ast.Name
                ):
                    literals.extend(found.get(element.value.id, []))
        elif isinstance(value, ast.JoinedStr | ast.BinOp):
            continue
        for name in names:
            found[name] = literals
    return found


def _executed_statements(module: ast.Module, function_name: str) -> list[str]:
    """``upgrade``/``downgrade``가 실제로 실행하는 문장을 **순서대로** 모은다."""

    constants = _string_constants(module)
    target = next(
        (
            node
            for node in module.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ),
        None,
    )
    if target is None:
        return []

    statements: list[str] = []
    for node in ast.walk(target):
        if isinstance(node, ast.Call):
            func = ast.unparse(node.func)
            if not func.endswith("op.execute") and func != "execute":
                continue
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    statements.append(argument.value)
                elif isinstance(argument, ast.Name):
                    statements.extend(constants.get(argument.id, []))
        elif isinstance(node, ast.For) and isinstance(node.iter, ast.Name):
            # `for statement in _UPGRADE_STATEMENTS: op.execute(statement)`
            statements.extend(constants.get(node.iter.id, []))
    return statements


def _statements_for(path: pathlib.Path, function_name: str) -> list[str]:
    """import로 읽은 실제 문장열. 안 되면 AST 추출로 떨어진다."""

    imported = _imported_statements(path, function_name)
    if imported is not None:
        return imported
    return _executed_statements(
        ast.parse(path.read_text(encoding="utf-8")), function_name
    )


def _trailing_role(statements: list[str]) -> str | None:
    """마지막에 남는 세션 롤. ``None``이면 로그인 롤로 되돌아간 것이다."""

    role: str | None = None
    for statement in statements:
        lowered = statement.strip().lower()
        if lowered.startswith(_RESET_ROLE):
            role = None
        elif lowered.startswith(_SET_ROLE):
            role = statement.strip()[len(_SET_ROLE) :].strip().strip(";").strip()
    return role


@pytest.mark.unit
def test_the_scan_actually_sees_role_switching_migrations() -> None:
    """항진명제 방지 — 롤을 바꾸는 마이그레이션을 실제로 찾아야 한다."""

    switching = [
        path.name
        for path in _migration_paths()
        if _trailing_role(_statements_for(path, "upgrade")) is not None
    ]
    assert len(switching) >= 5, (
        f"`SET ROLE`로 끝나는 마이그레이션을 {len(switching)}개만 찾았다 — "
        "추출이 낡았다(상수 형태가 바뀌었을 수 있다)."
    )


@pytest.mark.unit
def test_sidecar_migrations_are_not_read_through_the_ast_alone() -> None:
    """**하한을 '본 것'에 건다.**

    사이드카를 쓰는 마이그레이션에서 AST만으로 세면 문장 대부분이 빠진다. 그
    상태로도 이 모듈의 단언은 조용히 통과하므로, "import 경로가 실제로 더 많이
    본다"는 것을 여기서 명시적으로 센다. import 해석이 깨지면 이 검사가 먼저
    빨갛게 된다 — 롤 검사가 조용히 항진명제가 되는 대신.
    """

    improved: list[str] = []
    for path in _migration_paths():
        if "_sidecar(" not in path.read_text(encoding="utf-8"):
            continue
        ast_only = _executed_statements(
            ast.parse(path.read_text(encoding="utf-8")), "upgrade"
        )
        resolved = _statements_for(path, "upgrade")
        if len(resolved) > len(ast_only):
            improved.append(f"{path.name}: {len(ast_only)} -> {len(resolved)}")

    assert improved, (
        "사이드카를 쓰는 마이그레이션이 없거나, import 해석이 AST보다 더 보지 "
        "못한다 — 이 모듈의 롤 검사가 사이드카 문장을 못 보고 있다는 뜻이다."
    )


@pytest.mark.unit
def test_no_migration_hands_the_version_bump_back_to_the_login_role() -> None:
    """롤을 켠 마이그레이션은 **켠 채로 끝나야 한다.**

    alembic의 `UPDATE alembic_version`은 본문이 끝난 **뒤** 같은 트랜잭션에서
    나간다. 로그인 롤에는 그 표의 UPDATE 권한이 없으므로, 되돌리면 본문이 다
    성공하고도 버전 기록에서 죽는다.
    """

    offenders: list[str] = []
    for path in _migration_paths():
        name = path.name
        for function_name in ("upgrade", "downgrade"):
            statements = _statements_for(path, function_name)
            if not any(s.strip().lower().startswith(_SET_ROLE) for s in statements):
                continue
            role = _trailing_role(statements)
            if role is None:
                offenders.append(f"{name}:{function_name} (롤을 되돌린 채 끝난다)")
            elif role not in _ALLOWED_TRAILING_ROLES:
                offenders.append(f"{name}:{function_name} (마지막 롤={role})")

    assert not offenders, (
        "마이그레이션이 롤을 되돌린 채 끝난다 — alembic의 "
        "`UPDATE alembic_version`이 `permission denied`로 죽는다. "
        f"`RESET ROLE`을 빼거나 마지막에 `SET ROLE ktm_feature_schema_owner`로 "
        f"돌려 둘 것: {offenders}"
    )

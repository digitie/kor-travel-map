"""feature 참조 정규화 함수가 **바인드 타입에 맞는 자리**에만 쓰이는지 검사한다.

## 왜 이 검사가 있는가

`legacy_id_for_filter`는 한동안 두 가지 다른 일을 겸했다. 자유 검색어(`q`)를
정규화하는 일과, feature 필터 값을 정규화하는 일이다. 두 자리는 겉보기에 같지만
**바인드 타입이 다르다**:

    AND (CAST(:q_like AS text) IS NULL OR issue.message ILIKE CAST(:q_like AS text))
    AND (CAST(:feature_id AS uuid) IS NULL OR issue.feature_id = CAST(:feature_id AS uuid))

`q`는 자유 문자열이므로 이 함수가 원문을 그대로 돌려주는 것이 옳다. 그런데 재키
뒤 `feature_id`는 uuid 자리가 됐고, 같은 함수가 돌려준 `f_1156010100_p_...`가
그리로 들어가면 22P02다 — 운영자는 빈 목록이 아니라 **500**을 받는다.

T-VN-39는 그래서 표면을 둘로 갈랐다.

- `legacy_id_for_filter` — text 비교 전용. 임의 원문을 돌려줄 수 있다.
- `canonical_feature_id_for_filter` — uuid 바인드 전용. 언제나 uuid 표기이거나
  `None`이고, 어떤 Feature도 가리키지 않는 값은 `FeatureIdentityRefError`다.

이름만 갈라 두면 다음 사람이 다시 섞는다. 이 검사가 그 경계를 고정한다.

## 무엇을 재는가

`legacy_id_for_filter` 호출이 **`q=` 키워드 인자 자리에만** 나타나는지 본다. 그
자리가 이 저장소에서 text 검색어의 이름이고, 다른 이름으로 새는 순간이 곧
타입이 어긋나는 순간이다.

검사가 **비지 않았는지도 함께 잰다.** 호출부가 0이면 이 파일은 아무것도 재지
않으면서 초록으로 남는다 — 적대 리뷰가 이 저장소의 다른 검사에서 실제로 집어낸
부류라, 두 함수 모두에 하한을 둔다.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SELF = pathlib.Path(__file__).resolve()

_TEXT_ONLY = "legacy_id_for_filter"
_UUID_ONLY = "canonical_feature_id_for_filter"

# 이 이름의 키워드 인자만 text 비교로 흘러간다.
_TEXT_BIND_ARGUMENTS = frozenset({"q"})

# 하한 — 검사가 재는 대상이 사라지면 초록이 아니라 빨강이어야 한다.
_MINIMUM_TEXT_CALLS = 3
_MINIMUM_UUID_CALLS = 7

# uuid 필터를 노출하는 표면의 하한. 개수 세기와 달리 아래 검사는 표면을 **열거해서**
# 하나하나 확인하므로, 이 수는 "열거가 비지 않았다"만 보증한다.
_MINIMUM_UUID_FILTER_SURFACES = 3


def _sources() -> list[pathlib.Path]:
    roots = [_ROOT / "src", *(_ROOT / "packages").glob("*/src")]
    files: list[pathlib.Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        files.extend(
            path
            for path in root.rglob("*.py")
            if path.resolve() != _SELF and "build" not in path.parts
        )
    return sorted(files)


def _called_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _calls_in(tree: ast.AST, name: str) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _called_name(node) == name
    ]


def _keyword_bound_calls(tree: ast.AST, name: str) -> set[int]:
    """`<arg>=...legacy_id_for_filter(...)` 형태로 묶인 호출의 id 집합."""
    bound: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg not in _TEXT_BIND_ARGUMENTS:
            continue
        for inner in ast.walk(node.value):
            if isinstance(inner, ast.Call) and _called_name(inner) == name:
                bound.add(id(inner))
    return bound


def test_text_only_filter_helper_is_bound_only_to_text_arguments() -> None:
    offenders: list[str] = []
    total = 0
    for path in _sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = _calls_in(tree, _TEXT_ONLY)
        if not calls:
            continue
        total += len(calls)
        allowed = _keyword_bound_calls(tree, _TEXT_ONLY)
        for call in calls:
            if id(call) not in allowed:
                offenders.append(
                    f"{path.relative_to(_ROOT).as_posix()}:{call.lineno}"
                )
    assert not offenders, (
        f"`{_TEXT_ONLY}`는 text 비교 자리(현재 "
        f"{sorted(_TEXT_BIND_ARGUMENTS)})에만 쓸 수 있습니다. uuid 컬럼을 거르는 "
        f"자리에는 `{_UUID_ONLY}`를 쓰세요 — 아니면 legacy 참조가 22P02(500)가 "
        f"됩니다: {offenders}"
    )
    assert total >= _MINIMUM_TEXT_CALLS, (
        f"`{_TEXT_ONLY}` 호출부가 {total}개뿐입니다 — 검사가 비었습니다. "
        f"표면이 사라졌다면 이 검사도 함께 지우세요."
    )


def test_uuid_filter_helper_covers_the_uuid_bound_surfaces() -> None:
    total = sum(
        len(_calls_in(ast.parse(path.read_text(encoding="utf-8")), _UUID_ONLY))
        for path in _sources()
    )
    assert total >= _MINIMUM_UUID_CALLS, (
        f"`{_UUID_ONLY}` 호출부가 {total}개뿐입니다 — uuid 바인드 자리가 "
        f"`{_TEXT_ONLY}`로 되돌아갔는지 확인하세요."
    )


def _router_modules() -> list[pathlib.Path]:
    return sorted((_ROOT / "packages").glob("*/src/kortravelmap/api/routers/*.py"))


def _uuid_filter_parameters() -> list[tuple[pathlib.Path, Any, str]]:
    """`Annotated[str | None, Query()]`로 선언된 `*feature_id` 질의 파라미터 전부.

    **왜 이 모양만 고르나.** 형제 필터(`rule_id`·`theme_id`·`source_id`)는 `UUID`
    타입이라 FastAPI가 경계에서 이미 거른다. `str`로 선언된 것만 자유 문자열이
    그대로 통과하고, 그 값이 `CAST(:x AS uuid)`에 닿으면 22P02다. 경로 파라미터는
    제외한다 — 그 자리는 필터가 아니라 상세 조회이고 해석 규율이 다르다.
    """
    found: list[tuple[pathlib.Path, Any, str]] = []
    for path in _router_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for argument in [*node.args.args, *node.args.kwonlyargs]:
                if not argument.arg.endswith("feature_id") or argument.annotation is None:
                    continue
                annotation = ast.unparse(argument.annotation)
                if "Query" not in annotation or "str" not in annotation:
                    continue
                found.append((path, node, argument.arg))
    return found


def test_every_uuid_bound_feature_filter_is_normalized() -> None:
    """uuid 필터를 노출하는 **표면을 열거해서** 하나씩 확인한다.

    호출부 **개수**만 세면 "변환되지 않은 표면이 남아 있다"를 볼 수 없다. 실제로
    그랬다 — 이 검사의 첫 판이 초록인 채로 `/admin/theme-feature-candidates`의
    `feature_id`가 정규화 없이 `CAST(:feature_id AS uuid)`에 닿고 있었고, 그
    라우터의 `except ValueError`는 22P02가 오는 `sqlalchemy.exc.DataError`를 잡지
    못해 운영자에게 500이 나갔다. 적대 리뷰가 집었다.

    개수 하한은 "검사가 비지 않았다"만 말한다. 명제는 **전칭**이어야 한다 —
    이런 파라미터를 가진 handler는 전부 `canonical_feature_id_for_filter`를 지난다.
    """
    surfaces = _uuid_filter_parameters()
    assert len(surfaces) >= _MINIMUM_UUID_FILTER_SURFACES, (
        f"uuid 필터 표면을 {len(surfaces)}개만 찾았습니다 "
        f"(하한 {_MINIMUM_UUID_FILTER_SURFACES}) — 열거가 깨졌는지 확인하세요."
    )
    unnormalized: list[str] = []
    for path, node, name in surfaces:
        body = ast.unparse(node)
        if _UUID_ONLY not in body:
            unnormalized.append(
                f"{path.relative_to(_ROOT).as_posix()}:{node.lineno} "
                f"{node.name}({name})"
            )
    assert not unnormalized, (
        f"uuid로 바인드되는 feature 필터가 `{_UUID_ONLY}`를 지나지 않습니다: "
        + ", ".join(unnormalized)
        + " — 원문을 그대로 넘기면 legacy `f_*`도 오타 섞인 uuid도 22P02가 되고, "
        "그 오류는 `ValueError`가 아니라 `sqlalchemy.exc.DataError`라 라우터의 "
        "422 handler를 통과해 **500**으로 나갑니다."
    )

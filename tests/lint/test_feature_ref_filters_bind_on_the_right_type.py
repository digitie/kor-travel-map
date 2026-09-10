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

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SELF = pathlib.Path(__file__).resolve()

_TEXT_ONLY = "legacy_id_for_filter"
_UUID_ONLY = "canonical_feature_id_for_filter"

# 이 이름의 키워드 인자만 text 비교로 흘러간다.
_TEXT_BIND_ARGUMENTS = frozenset({"q"})

# 하한 — 검사가 재는 대상이 사라지면 초록이 아니라 빨강이어야 한다.
_MINIMUM_TEXT_CALLS = 3
_MINIMUM_UUID_CALLS = 5


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

"""provider가 만드는 모든 ``Feature``가 자기 자연키를 싣고 있는지 검사한다.

## 왜

T-VN-39 재키 후 Feature identity를 결정하는 축은
``(provider_dataset_id, feature_kind, natural_key)``다(ADR-068 결정 2). 그 세 번째
성분은 **provider만 알고 있다** — ``FeatureBundle.source_record.source_entity_id``로
대신할 수 없다. ``providers/opinet.py``에서 entity id는 제품별
(``f"{uni_id}:{prodcd}"``)이고 자연키는 주유소별(``uni_id``)이며, 그 가격들이 같은
price anchor Feature에 누적되기 때문이다.

그래서 ``Feature.provider_natural_key``를 실어야 하는데, 그것은 **28곳에 흩어진
손 작업**이다. 새 provider를 추가하는 사람이 한 줄 빠뜨리면 그 원천의 Feature는
identity claim을 얻지 못하고, 재키 후 **적재할 때마다 새 Feature가 생긴다.**
DDL 오류도 타입 오류도 나지 않는다.

## 무엇을 재는가

1. provider 모듈에서 ``make_feature_id(...)``를 부르는 함수는 반드시 같은 함수 안에서
   ``Feature(...)``를 만들고, 그 생성에 ``provider_natural_key=``가 있어야 한다.
2. 그 값이 같은 호출의 ``source_natural_key=``와 **글자 그대로 같아야 한다**.
   다르면 claim 축과 alias 축이 갈라지고, 그 어긋남은 조용하다.

## 이 검사가 공허해지는 경우

``make_feature_id``를 감싼 헬퍼를 통해 부르면 (1)이 그 함수를 못 본다 —
``providers/kma.py``의 ``kma_alert_notice_feature_id``가 실제로 그 모양이다. 그래서
**파일 단위 수 대조**를 함께 둔다: 한 모듈의 ``source_natural_key=`` 등장 수와
``provider_natural_key=`` 등장 수가 같아야 한다. 헬퍼로 감싸도 그 수는 맞아야 한다.
"""

from __future__ import annotations

import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: provider 변환기가 사는 자리. `offline_upload`도 같은 규약을 따른다.
_PROVIDER_ROOTS = (
    _ROOT / "src" / "kortravelmap" / "providers",
    _ROOT / "src" / "kortravelmap" / "offline_upload.py",
)

#: manual 경로는 이 규약의 대상이 아니다 — `manual_feature_identity_claims`가
#: identity를 소유하므로 `provider_natural_key`가 `None`이다.
_MANUAL_PATHS = frozenset(
    {
        "src/kortravelmap/infra/admin_feature_repo.py",
        "src/kortravelmap/infra/curation_repo.py",
        "src/kortravelmap/infra/feature_request_repo.py",
    }
)


def _provider_modules() -> tuple[pathlib.Path, ...]:
    found: list[pathlib.Path] = []
    for root in _PROVIDER_ROOTS:
        if root.is_file():
            found.append(root)
        elif root.is_dir():
            found.extend(sorted(p for p in root.rglob("*.py") if p.name != "__init__.py"))
    return tuple(found)


_MODULES = _provider_modules()


def _relative(path: pathlib.Path) -> str:
    return str(path.relative_to(_ROOT)).replace("\\", "/")


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _calls_in(node: ast.AST, func_name: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == func_name
    ]


def test_the_provider_modules_are_found() -> None:
    """탐색 경로가 죽으면 이 검사는 조용히 0건이 된다."""

    assert len(_MODULES) >= 15, [_relative(p) for p in _MODULES]
    names = {p.name for p in _MODULES}
    for expected in ("opinet.py", "kma.py", "krex.py", "offline_upload.py"):
        assert expected in names, f"{expected}를 찾지 못했다 — 탐색 경로가 옮겨졌다"


def test_every_module_carries_as_many_natural_keys_as_it_computes() -> None:
    """모듈 단위 수 대조 — 헬퍼로 감싼 호출도 이 검사는 통과하지 못한다."""

    mismatches: dict[str, tuple[int, int]] = {}
    for path in _MODULES:
        text = path.read_text(encoding="utf-8")
        computed = text.count("source_natural_key=")
        carried = text.count("provider_natural_key=")
        if computed != carried:
            mismatches[_relative(path)] = (computed, carried)
    detail = {
        name: {"source_natural_key": computed, "provider_natural_key": carried}
        for name, (computed, carried) in mismatches.items()
    }
    assert mismatches == {}, (
        "provider 모듈이 계산한 자연키 수와 Feature에 실은 수가 다르다. 빠진 쪽은 "
        "재키 후 identity claim을 얻지 못하고 **적재할 때마다 새 Feature가 생긴다** — "
        "DDL 오류도 타입 오류도 나지 않는다.\n"
        f"{detail}"
    )


def test_each_feature_built_beside_make_feature_id_carries_the_same_key() -> None:
    """같은 함수 안에서 계산한 자연키와 실은 자연키가 **글자 그대로** 같아야 한다."""

    problems: list[str] = []
    checked = 0
    for path in _MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            id_calls = _calls_in(node, "make_feature_id")
            feature_calls = _calls_in(node, "Feature")
            if not id_calls or not feature_calls:
                continue
            for id_call in id_calls:
                natural = _keyword(id_call, "source_natural_key")
                if natural is None:
                    problems.append(
                        f"{_relative(path)}:{id_call.lineno} make_feature_id에 "
                        "source_natural_key가 없다"
                    )
                    continue
                wanted = ast.unparse(natural)
                carried = [
                    ast.unparse(value)
                    for call in feature_calls
                    if (value := _keyword(call, "provider_natural_key")) is not None
                ]
                checked += 1
                if not carried:
                    problems.append(
                        f"{_relative(path)}:{node.lineno} {node.name}(): "
                        f"make_feature_id(source_natural_key={wanted})를 부르면서 "
                        "Feature에 provider_natural_key를 싣지 않았다"
                    )
                elif wanted not in carried:
                    problems.append(
                        f"{_relative(path)}:{node.lineno} {node.name}(): "
                        f"자연키가 다르다 — 계산={wanted} 실음={carried}"
                    )
    assert checked >= 20, f"검사한 쌍이 {checked}개뿐이다 — 탐지기가 대상을 못 보고 있다"
    assert problems == [], "\n".join(problems)


def test_the_detector_sees_a_planted_omission() -> None:
    """탐지기가 실제로 잡는지 심어서 확인한다.

    AST로 좁힌 뒤에는 "아무것도 안 잡는데 초록"이 가장 그럴듯한 실패다.
    """

    planted = (
        "def convert(item):\n"
        "    feature_id = make_feature_id(\n"
        "        bjd_code=None, kind='place', category='0', \n"
        "        source_type='p:d', source_natural_key=item.uid,\n"
        "    )\n"
        "    return Feature(feature_id=feature_id, kind='place')\n"
    )
    tree = ast.parse(planted)
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    id_call = _calls_in(function, "make_feature_id")[0]
    feature_call = _calls_in(function, "Feature")[0]
    assert _keyword(id_call, "source_natural_key") is not None
    assert _keyword(feature_call, "provider_natural_key") is None, (
        "심은 누락이 탐지되지 않는다 — 이 검사는 공허하다"
    )

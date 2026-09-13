"""선언한 쿼터 예외가 **실물 provider lib에 실재하는지** 결박한다.

``quota_exhaustion``은 provider 패키지를 import하지 않고 ``(모듈, 클래스 이름)``
쌍으로 판정한다. 그 선택에는 이유가 있다 — 이 판정은 **실패 경로에서만** 돌고,
거기서 provider 패키지를 import하면 실패 원인 규명이 import 오류로 바뀐다.

대가는 **오타가 조용하다**는 것이다. 이름을 하나 잘못 적으면 판정이 영원히
발화하지 않는데 테스트는 초록이다. 합성 대역으로 쓴 단언은 그 오타를 잡지 못한다 —
대역이 선언과 같은 이름을 쓰기 때문이다(적대 리뷰 지적).

그래서 여기서 **형제 체크아웃의 소스를 읽어** 각 이름이 실재하는 예외 클래스인지
확인한다(ADR-044: provider 로컬 우선 조회). 선언도 소스에서 AST로 읽는다 — 이
파일이 dagster를 import하지 않아야 provider 핀을 바꾸는 환경 어디서든 돈다.

체크아웃이 없으면 skip한다. `test_provider_protocol_conformance.py`와 같은 계약이다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_GUARD = (
    _ROOT
    / "packages"
    / "kor-travel-map-dagster"
    / "src"
    / "kortravelmap"
    / "dagster"
    / "quota_exhaustion.py"
)

#: 형제 체크아웃 루트 후보.
_SIBLING_ROOTS = (Path("F:/dev"), Path("/f/dev"), Path.home() / "dev")


def _declared_pairs() -> list[tuple[str, str]]:
    """``QUOTA_EXCEPTION_TYPES``의 ``(모듈, 클래스)`` 쌍을 소스에서 읽는다."""

    tree = ast.parse(_GUARD.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "QUOTA_EXCEPTION_TYPES":
            continue
        pairs: list[tuple[str, str]] = []
        for element in ast.walk(node):
            if not isinstance(element, ast.Tuple) or len(element.elts) != 2:
                continue
            first, second = element.elts
            if (
                isinstance(first, ast.Constant)
                and isinstance(first.value, str)
                and isinstance(second, ast.Constant)
                and isinstance(second.value, str)
            ):
                pairs.append((first.value, second.value))
        return sorted(set(pairs))
    return []


def _sibling_source(module: str) -> Path | None:
    for root in _SIBLING_ROOTS:
        candidate = root / f"python-{module}-api" / "src" / module / "exceptions.py"
        if candidate.is_file():
            return candidate
    return None


def test_the_declaration_is_not_empty() -> None:
    """항진명제 방지 — 선언이 비면 아래 파라미터가 0개가 되어 아무것도 재지 않는다."""

    pairs = _declared_pairs()
    assert len(pairs) >= 3, (
        f"선언된 쿼터 예외가 {len(pairs)}개뿐이다(유도 실패이거나 실제로 줄었다). "
        "줄이려면 왜 그 provider가 더 이상 쿼터를 알리지 않는지 먼저 적어라."
    )


@pytest.mark.parametrize(
    ("module", "class_name"),
    _declared_pairs(),
    ids=[f"{module}.{name}" for module, name in _declared_pairs()],
)
def test_each_declared_quota_exception_exists_in_the_real_library(
    module: str, class_name: str
) -> None:
    """선언한 이름이 실물 lib의 예외 클래스여야 한다."""

    source = _sibling_source(module)
    if source is None:
        pytest.skip(
            f"형제 체크아웃이 없어 `{module}`을 확인하지 못했다(ADR-044). "
            "provider 핀을 바꾸는 환경에서는 반드시 초록이어야 한다."
        )

    classes = {
        node.name
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, ast.ClassDef)
    }
    assert classes, f"{source}에서 클래스를 하나도 찾지 못했다 — 파서가 낡았다"
    assert class_name in classes, (
        f"`{module}.{class_name}`이 실물 lib에 없다. 이름이 바뀌었거나 오타다 — "
        f"어느 쪽이든 쿼터 판정이 그 provider에서 **영원히 발화하지 않는다**. "
        f"{source.name}에 있는 것: {sorted(classes)}"
    )

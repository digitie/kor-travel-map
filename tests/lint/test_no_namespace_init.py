"""``src/krtour/__init__.py``가 생성되지 않았는지 검증 (ADR-022).

PEP 420 implicit namespace ``krtour`` 위에 `krtour.map` (메인) /
`krtour.map_debug_ui` (별도 패키지) 가 공존한다. 누군가 ``src/krtour/__init__.py``
를 만들면 자매 distribution과 namespace 충돌 — CI에서 즉시 차단.

참조:
- ADR-022 §결과/부정 + SKILL.md ``DO NOT #21`` + AGENTS.md ``DO NOT #19``
"""

from __future__ import annotations

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_krtour_namespace_has_no_init() -> None:
    """``src/krtour/__init__.py``가 존재하면 PEP 420 namespace가 깨진다."""
    namespace_init = PROJECT_ROOT / "src" / "krtour" / "__init__.py"
    assert not namespace_init.exists(), (
        f"ADR-022 위반: {namespace_init} 가 존재합니다. "
        "PEP 420 implicit namespace `krtour`는 `__init__.py`를 가지면 안 됩니다. "
        "자매 distribution(`krtour-map-debug-ui` 등)과 namespace 충돌합니다. "
        "SKILL.md DO NOT #21 / AGENTS.md DO NOT #19 / ADR-022 §결과/부정 참조."
    )


@pytest.mark.unit
def test_krtour_map_package_init_exists() -> None:
    """반면 ``src/krtour/map/__init__.py``는 반드시 존재해야 한다."""
    pkg_init = PROJECT_ROOT / "src" / "krtour" / "map" / "__init__.py"
    assert pkg_init.exists(), (
        f"메인 패키지 init 파일 {pkg_init} 가 없습니다. "
        "PR#17 scaffolding 후 본 파일이 박혀 있어야 합니다."
    )


@pytest.mark.unit
def test_krtour_map_py_typed_exists() -> None:
    """PEP 561 marker (``py.typed``) 존재 확인."""
    py_typed = PROJECT_ROOT / "src" / "krtour" / "map" / "py.typed"
    assert py_typed.exists(), (
        f"PEP 561 marker {py_typed} 가 없습니다. "
        "타입 정보 노출을 위해 빈 파일이라도 박혀 있어야 합니다."
    )

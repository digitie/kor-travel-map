"""T-226 package layout lint."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.unit
def test_old_krtour_namespace_is_absent() -> None:
    """구 `src/krtour` namespace가 되살아나면 clean cut 위반이다."""
    old_namespace = PROJECT_ROOT / "src" / "krtour"
    assert not old_namespace.exists(), f"T-226 위반: 구 namespace {old_namespace} 가 존재합니다."


@pytest.mark.unit
def test_kortravelmap_package_init_exists() -> None:
    """`import kortravelmap as ktm` 진입점은 반드시 존재한다."""
    pkg_init = PROJECT_ROOT / "src" / "kortravelmap" / "__init__.py"
    assert pkg_init.exists(), f"메인 패키지 init 파일 {pkg_init} 가 없습니다."


@pytest.mark.unit
def test_kortravelmap_py_typed_exists() -> None:
    """PEP 561 marker (`py.typed`) 존재 확인."""
    py_typed = PROJECT_ROOT / "src" / "kortravelmap" / "py.typed"
    assert py_typed.exists(), f"PEP 561 marker {py_typed} 가 없습니다."

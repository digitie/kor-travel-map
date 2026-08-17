"""``providers/__init__.py`` docstring 인벤토리가 실제 모듈과 일치하는지.

이 docstring은 2026-05 Sprint 계획표가 그대로 굳어, 존재하지 않는 모듈 3개
(``krforest_weather``·``krforest_trails``·``khoa_weather``)를 나열하고 실재하는 6개를
빠뜨린 채 오래 남아 있었다. 순수 문서라 런타임은 멀쩡했고, 그래서 아무도 몰랐다.

고쳐 적는 것만으로는 같은 일이 또 생긴다 — provider가 하나 늘 때 docstring을 같이
고쳐야 한다고 **기억**에 의존하기 때문이다. 그래서 그 불변식을 여기서 강제한다.

**이 검사의 한계**: 모듈 *이름*이 표에 있는지만 본다. 비고 열의 설명이나 provider
라이브러리 이름이 맞는지는 보지 않는다. 그 축이 틀려도 이 테스트는 통과한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import kortravelmap.providers as providers_pkg

_PROVIDERS_DIR = Path(providers_pkg.__file__).parent

# 변환 모듈이 아니라서 표에 넣지 않는 것. 빼려면 docstring의 「표에 없는 모듈」도
# 같이 고쳐야 한다 — 그래서 여기에 이유를 적어 둔다.
_NOT_IN_TABLE = {
    "feature_operation_registry",  # operation key -> Dagster handler registry (T-VN-33)
    "knps_name_translations",  # knps가 쓰는 이름 대역표
}


def _module_names() -> set[str]:
    return {
        p.stem
        for p in _PROVIDERS_DIR.glob("*.py")
        if p.stem != "__init__"
    }


def _docstring_table_modules() -> set[str]:
    """docstring 표의 첫 열에서 ``module`` 이름을 뽑는다."""
    doc = providers_pkg.__doc__ or ""
    # `| ``name`` | ... |` 형태의 행에서 첫 칸만 취한다
    return {
        m.group(1)
        for m in re.finditer(r"^\|\s*``([a-z0-9_]+)``\s*\|", doc, re.MULTILINE)
    }


def _docstring_exception_modules() -> set[str]:
    """「표에 없는 모듈」 목록에서 이름을 뽑는다."""
    doc = providers_pkg.__doc__ or ""
    tail = doc.split("**표에 없는 모듈**", 1)
    if len(tail) != 2:
        return set()
    return {
        m.group(1)
        for m in re.finditer(r"^-\s+``([a-z0-9_]+)``", tail[1], re.MULTILINE)
    }


def test_docstring_table_covers_every_transform_module() -> None:
    """표 + 예외 목록이 실제 모듈 전부를 덮는다."""
    actual = _module_names()
    documented = _docstring_table_modules() | _docstring_exception_modules()

    missing = actual - documented
    assert not missing, (
        f"providers/ 에 있는데 docstring에 없는 모듈: {sorted(missing)}. "
        "provider를 추가했으면 __init__.py docstring 표에도 넣어라."
    )

    phantom = documented - actual
    assert not phantom, (
        f"docstring에 있는데 providers/ 에 없는 모듈: {sorted(phantom)}. "
        "모듈을 지웠거나 계획을 실제인 것처럼 적었다 — 계획은 "
        "docs/architecture/provider-contract.md가 정본이다."
    )


def test_exception_list_matches_the_declared_set() -> None:
    """예외 목록이 이 테스트가 아는 집합과 같은지.

    docstring에서 예외를 조용히 늘리면 표 검사가 그만큼 헐거워진다. 늘릴 때는
    여기 ``_NOT_IN_TABLE``도 같이 고치게 해서 이유를 남기도록 강제한다.
    """
    assert _docstring_exception_modules() == _NOT_IN_TABLE


def test_docstring_does_not_reference_nonexistent_planned_modules() -> None:
    """미구현 dataset 이름이 **모듈**인 것처럼 docstring에 다시 들어오지 않게.

    ``krforest_trails`` 등은 dataset이지 모듈이 아니다. 계획 정본은
    provider-contract.md이고, 그 이름들이 여기 표에 들어오면 phantom 검사가
    잡지만 산문에 섞이면 안 잡힌다 — 그래서 표 밖도 본다.
    """
    doc = providers_pkg.__doc__ or ""
    # 표/예외 목록 형태(`| ``x`` |`, `- ``x``')로 나타나면 안 되는 이름들
    for name in ("krforest_weather", "krforest_trails", "khoa_weather"):
        assert not re.search(rf"^\|\s*``{name}``", doc, re.MULTILINE), (
            f"``{name}``은 모듈이 아니다(표에 넣지 마라)"
        )
        assert not re.search(rf"^-\s+``{name}``", doc, re.MULTILINE), (
            f"``{name}``은 모듈이 아니다(예외 목록에 넣지 마라)"
        )

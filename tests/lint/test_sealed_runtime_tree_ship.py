"""sealed application 300 build의 runtime tree 선적(ship) 계약 lint.

## 왜 필요한가

Manager pinned rebuild는 ``scripts/build-application-300-candidate.sh``로 candidate
이미지를 봉인 검증한다. 그 게이트의 기대 manifest는 sealed Git archive의 runtime
소스 트리(``src/kortravelmap``, ``packages/kor-travel-map-api/src/kortravelmap/api``)
**전 파일**이고, 관측 manifest는 이미지 site-packages에서 ``.py``/``.json``/
``py.typed``만 본다. 따라서 다음 두 클래스는 PR CI 전부 green인 채 **Manager
rebuild 단계에서만** "installed runtime tree가 sealed Git archive와 다르다"로 터진다.

1. runtime 트리에 새 비-``.py`` 파일이 들어왔는데 해당 패키지의
   ``[tool.setuptools.package-data]``에 등록되지 않아 wheel에 실리지 않는 경우.
2. runtime 트리에 ``.py``/``.json``/``py.typed`` 밖의 확장자가 들어와 이미지 쪽
   manifest 필터에 아예 잡히지 않는 경우.

2026-08-31 실측: ``providers/_provider_surface.json``이 package-data에 없어 M05
activation pinned rebuild가 ``application_builder`` 단계에서 실패했다(수정 전까지
어떤 로컬/CI 게이트도 이를 보지 못했다). 이 lint는 그 클래스 전체를 PR 시점으로
끌어온다.

## 무엇을 보는가

- runtime 트리의 모든 파일 확장자가 sealed 이미지 manifest 허용 집합
  (``.py``/``.json``/``py.typed``)에 속하는지.
- 모든 디렉터리가 정규 패키지(``__init__.py`` 보유)인지 — 데이터 전용 디렉터리는
  ``packages.find``가 수집하지 않아 wheel에서 통째로 빠진다.
- 모든 비-``.py`` 파일이 **자기가 속한 가장 깊은 패키지**의 package-data에 fnmatch로
  덮이는지. setuptools는 하위 패키지 데이터를 상위 패키지 패턴으로 배포하지 않으므로
  소유 패키지 기준이 실제 wheel 내용과 일치한다.

## 무엇을 보지 못하는가 (과신 금지)

wheel을 실제로 빌드하지 않으므로 setuptools 동작 자체의 회귀(예: build backend
버전별 package-data 처리 변화)는 잡지 못한다. 그 최종 판정은 여전히 sealed builder가
갖는다 — 이 lint의 역할은 같은 판정을 몇 초짜리 정적 검사로 앞당기는 것뿐이다.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# sealed 이미지 manifest가 관측하는 파일 집합 —
# scripts/build-application-300-candidate.sh 의 image-side 필터와 동일해야 한다.
_SEALED_MANIFEST_SUFFIXES = frozenset({".py", ".json"})
_SEALED_MANIFEST_NAMES = frozenset({"py.typed"})

# (pyproject.toml, runtime 트리 root, root 패키지 이름) —
# scripts/build-application-300-candidate.sh 의 source-side 트리 목록과 동일해야 한다.
_RUNTIME_TREES: tuple[tuple[Path, Path, str], ...] = (
    (
        PROJECT_ROOT / "pyproject.toml",
        PROJECT_ROOT / "src" / "kortravelmap",
        "kortravelmap",
    ),
    (
        PROJECT_ROOT / "packages" / "kor-travel-map-api" / "pyproject.toml",
        PROJECT_ROOT
        / "packages"
        / "kor-travel-map-api"
        / "src"
        / "kortravelmap"
        / "api",
        "kortravelmap.api",
    ),
)


def _runtime_files(base: Path) -> list[Path]:
    return sorted(
        path
        for path in base.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.relative_to(base).parts
        and path.suffix != ".pyc"
    )


def _package_data(pyproject: Path) -> dict[str, list[str]]:
    with pyproject.open("rb") as handle:
        document = tomllib.load(handle)
    raw = document.get("tool", {}).get("setuptools", {}).get("package-data", {})
    return {name: list(patterns) for name, patterns in raw.items()}


@pytest.mark.unit
def test_runtime_tree_files_are_sealed_manifest_visible() -> None:
    """runtime 트리의 모든 파일은 sealed 이미지 manifest 필터에 보여야 한다."""
    invisible: list[str] = []
    for _, base, _ in _RUNTIME_TREES:
        for path in _runtime_files(base):
            if path.name in _SEALED_MANIFEST_NAMES:
                continue
            if path.suffix in _SEALED_MANIFEST_SUFFIXES:
                continue
            invisible.append(str(path.relative_to(PROJECT_ROOT)))
    assert not invisible, (
        "sealed 이미지 manifest는 .py/.json/py.typed만 관측한다. 다음 파일은 "
        "이미지 쪽에서 보이지 않아 pinned rebuild가 'installed runtime tree가 "
        "sealed Git archive와 다르다'로 실패한다 — runtime 트리 밖으로 옮기거나 "
        "scripts/build-application-300-candidate.sh 필터와 함께 바꿔야 한다: "
        f"{invisible}"
    )


@pytest.mark.unit
def test_runtime_tree_directories_are_regular_packages() -> None:
    """데이터 전용 디렉터리는 packages.find가 수집하지 않아 wheel에서 빠진다."""
    missing_init: list[str] = []
    for _, base, _ in _RUNTIME_TREES:
        directories = {
            parent
            for path in _runtime_files(base)
            for parent in [path.parent]
            if parent != base
        }
        for directory in sorted(directories):
            current = directory
            while current != base:
                if not (current / "__init__.py").is_file():
                    missing_init.append(str(current.relative_to(PROJECT_ROOT)))
                current = current.parent
    assert not missing_init, (
        "runtime 트리의 모든 디렉터리는 __init__.py를 가진 정규 패키지여야 한다. "
        f"다음 디렉터리는 wheel에 실리지 않는다: {sorted(set(missing_init))}"
    )


@pytest.mark.unit
def test_non_python_runtime_files_are_declared_package_data() -> None:
    """비-.py 파일은 소유 패키지의 package-data로 선언돼야 wheel에 실린다."""
    undeclared: list[str] = []
    for pyproject, base, root_package in _RUNTIME_TREES:
        package_data = _package_data(pyproject)
        for path in _runtime_files(base):
            if path.suffix == ".py":
                continue
            relative = path.relative_to(base)
            owning_package = ".".join((root_package, *relative.parent.parts))
            patterns = package_data.get(owning_package, [])
            if not any(fnmatch.fnmatch(path.name, pattern) for pattern in patterns):
                undeclared.append(
                    f"{path.relative_to(PROJECT_ROOT)} (필요한 선언: "
                    f'"{owning_package}" 의 [tool.setuptools.package-data], '
                    f"{pyproject.relative_to(PROJECT_ROOT)})"
                )
    assert not undeclared, (
        "다음 비-.py runtime 파일이 package-data에 선언되지 않아 wheel에서 빠지고, "
        "pinned rebuild가 'installed runtime tree가 sealed Git archive와 다르다'로 "
        f"실패한다: {undeclared}"
    )

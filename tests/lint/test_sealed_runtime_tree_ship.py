"""sealed application 300 build의 runtime tree 선적(ship) 계약 lint.

## 왜 필요한가

Manager pinned rebuild는 ``scripts/build-application-300-candidate.sh``로 candidate
이미지를 봉인 검증한다. 그 게이트의 기대 manifest는 sealed Git archive의 runtime
소스 트리(``src/kortravelmap``, ``packages/kor-travel-map-api/src/kortravelmap/api``)
**전 파일**이고, 관측 manifest는 이미지 site-packages에서 ``.py``/``.json``/
``py.typed``만 본다. 따라서 다음 두 클래스는 PR CI 전부 green인 채 **Manager
rebuild 단계에서만** "installed runtime tree가 sealed Git archive와 다르다"로 터진다.

1. runtime 트리에 새 비-``.py`` 파일이 들어왔는데 package-data로 선언되지 않아
   wheel에 실리지 않는 경우.
2. runtime 트리에 ``.py``/``.json``/``py.typed`` 밖의 확장자가 들어와 이미지 쪽
   manifest 필터에 아예 잡히지 않는 경우.

2026-08-31 실측: ``providers/_provider_surface.json``이 package-data에 없어 M05
activation pinned rebuild가 ``application_builder`` 단계에서 실패했다(수정 전까지
어떤 로컬/CI 게이트도 이를 보지 못했다). 이 lint는 그 클래스 전체를 PR 시점으로
끌어온다.

## 어떻게 미러하는가

- 파일 목록은 ``git ls-files``로 뽑는다 — sealed 게이트의 기준이 working tree가
  아니라 ``git archive``(추적 파일만)이기 때문이다. 로컬 잔재(untracked)는 sealed
  판정을 흔들지 못하므로 여기서도 보지 않는다.
- 트리 root가 없거나 symlink면 sealed 스크립트처럼 **즉시 실패**한다. 조용히 빈
  목록을 돌면 트리 이동 한 번에 게이트 전체가 무음으로 해제된다(적대 리뷰 실측).
- symlink 파일은 양쪽 manifest 모두 건너뛰므로 여기서도 제외한다.
- package-data 판정은 setuptools 실동작을 따른다: 각 패턴은 **선언한 패키지 디렉터리
  기준 상대경로**에 recursive glob으로 매칭되므로, 하위 패키지 데이터를 상위 패키지의
  경로 패턴(예: ``"kortravelmap" = ["providers/*.json"]``)으로 싣는 것도 유효하다.
  따라서 소유 패키지와 **모든 조상 패키지**의 선언을 함께 대조한다. ``namespaces =
  true``라 ``__init__.py`` 없는 디렉터리도 PEP 420 패키지로 수집·배포되므로 데이터
  전용 디렉터리를 따로 막지 않는다.

## 무엇을 보지 못하는가 (과신 금지)

wheel을 실제로 빌드하지 않는다. ``[tool.setuptools.exclude-package-data]``나
``packages.find``의 ``include``/``exclude``가 파일을 도로 빼는 경우, setuptools
자체의 동작 회귀, 그리고 이미지 쪽 '초과' 파일(다른 distribution이 같은 namespace에
설치하는 경우) 방향은 여기서 잡지 못한다. 그 최종 판정은 여전히 sealed builder가
갖는다 — 이 lint의 역할은 같은 판정을 몇 초짜리 정적 검사로 앞당기는 것뿐이다.
"""

from __future__ import annotations

import fnmatch
import subprocess
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# sealed 이미지 manifest가 관측하는 파일 집합 —
# scripts/build-application-300-candidate.sh 의 image-side 필터와 동일해야 한다.
_SEALED_MANIFEST_SUFFIXES = frozenset({".py", ".json"})

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


def _tracked_runtime_files(base: Path) -> list[Path]:
    """sealed Git archive가 보게 될 파일만 — 추적·비-symlink·실존."""
    moved_hint = (
        f"runtime 트리 root가 없거나 symlink다: {base} — 트리를 옮겼다면 "
        "scripts/build-application-300-candidate.sh와 이 lint의 _RUNTIME_TREES를 "
        "함께 바꿔야 한다."
    )
    assert base.is_dir(), moved_hint
    assert not base.is_symlink(), moved_hint
    listing = subprocess.run(
        [
            "git",
            "-C",
            str(PROJECT_ROOT),
            "ls-files",
            "-z",
            "--",
            base.relative_to(PROJECT_ROOT).as_posix(),
        ],
        check=True,
        capture_output=True,
    )
    files = sorted(
        path
        for entry in listing.stdout.decode("utf-8").split("\0")
        if entry
        for path in [PROJECT_ROOT / entry]
        if path.is_file() and not path.is_symlink()
    )
    assert files, f"runtime 트리에 추적 파일이 하나도 없다: {base}"
    return files


def _package_data(pyproject: Path) -> dict[str, list[str]]:
    with pyproject.open("rb") as handle:
        document = tomllib.load(handle)
    raw = document.get("tool", {}).get("setuptools", {}).get("package-data", {})
    return {name: list(patterns) for name, patterns in raw.items()}


def _glob_segments_match(
    parts: tuple[str, ...], pattern_parts: tuple[str, ...]
) -> bool:
    """setuptools의 recursive glob처럼 ``*``는 ``/``를 넘지 못하고 ``**``만 넘는다.

    ``fnmatch``를 경로 전체에 쓰면 ``*``가 ``/``를 넘어 매칭돼, setuptools가 싣지
    않는 선언(예: ``"kortravelmap" = ["*.json"]``)을 유효로 오판한다 — 그게 바로
    이 lint가 잡아야 할 클래스다. 세그먼트 단위 ``fnmatchcase``(플랫폼 무관
    대소문자 고정)로 미러한다.
    """
    if not pattern_parts:
        return not parts
    head = pattern_parts[0]
    rest = pattern_parts[1:]
    if head == "**":
        return any(
            _glob_segments_match(parts[skip:], rest)
            for skip in range(len(parts) + 1)
        )
    if not parts:
        return False
    return fnmatch.fnmatchcase(parts[0], head) and _glob_segments_match(
        parts[1:], rest
    )


def _is_declared(
    package_data: dict[str, list[str]],
    root_package: str,
    relative: Path,
) -> bool:
    """setuptools 의미론: 소유 패키지 또는 임의 조상 패키지의 패턴이 그 패키지
    디렉터리 기준 상대경로에 매칭되면 wheel에 실린다."""
    directory_parts = relative.parent.parts if relative.parent != Path(".") else ()
    for depth in range(len(directory_parts) + 1):
        package = ".".join((root_package, *directory_parts[:depth]))
        rest = (*directory_parts[depth:], relative.name)
        if any(
            _glob_segments_match(rest, tuple(pattern.split("/")))
            for pattern in package_data.get(package, [])
        ):
            return True
    return False


@pytest.mark.unit
def test_runtime_tree_files_are_sealed_manifest_visible() -> None:
    """runtime 트리의 모든 파일은 sealed 이미지 manifest 필터에 보여야 한다."""
    invisible: list[str] = []
    for _, base, _ in _RUNTIME_TREES:
        for path in _tracked_runtime_files(base):
            # image-side 필터의 endswith("py.typed")를 그대로 미러한다.
            if path.name.endswith("py.typed"):
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
def test_non_python_runtime_files_are_declared_package_data() -> None:
    """비-.py 파일은 package-data로 선언돼야 wheel에 실린다."""
    undeclared: list[str] = []
    for pyproject, base, root_package in _RUNTIME_TREES:
        package_data = _package_data(pyproject)
        for path in _tracked_runtime_files(base):
            if path.suffix == ".py":
                continue
            relative = path.relative_to(base)
            if _is_declared(package_data, root_package, relative):
                continue
            owning_package = ".".join((root_package, *relative.parent.parts))
            undeclared.append(
                f"{path.relative_to(PROJECT_ROOT)} — "
                f"{pyproject.relative_to(PROJECT_ROOT)}의 "
                f'[tool.setuptools.package-data]에 "{owning_package}" = '
                f'["{relative.name}"] 을 추가하거나, 조상 패키지에 경로 패턴'
                f'(예: "{root_package}" = ["{relative.as_posix()}"])으로 선언하라'
            )
    assert not undeclared, (
        "다음 비-.py runtime 파일이 package-data에 선언되지 않아 wheel에서 빠지고, "
        "pinned rebuild가 'installed runtime tree가 sealed Git archive와 다르다'로 "
        f"실패한다: {undeclared}"
    )

"""T-VN-H21: live geo 경계마다 ``preflight()``가 결선되어 있는지 구조적으로 고정한다.

``KorTravelGeoRestClient.preflight()``는 **한 군데만** 붙이면 장식이 된다. 실제로 최초 구현은
CLI 한 곳에만 붙어 있었고 API/Dagster의 live 경로 6곳은 여전히 키 누락 시 원인이 지워진
``400 Bad Request``만 받았다. 새 live 생성 지점이 preflight 없이 추가되는 회귀를 막는다.

정규식이 아니라 AST로 본다 — 주석/문서 문자열/변수명 변화에 흔들리지 않게 한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_CLIENT = "KorTravelGeoRestClient"
_REPO_ROOT = Path(__file__).resolve().parents[2]

# live 생성 지점을 찾을 소스 트리 (테스트/문서 제외 — 테스트는 mock transport라 키가 없어도 된다).
_SOURCE_ROOTS = (
    _REPO_ROOT / "src" / "kortravelmap",
    _REPO_ROOT / "packages" / "kor-travel-map-api" / "src",
    _REPO_ROOT / "packages" / "kor-travel-map-dagster" / "src",
)

# 클라이언트 자체 정의 모듈은 생성 지점이 아니라 정의부라 제외한다.
_EXEMPT = {_REPO_ROOT / "src" / "kortravelmap" / "geocoding.py"}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in _SOURCE_ROOTS:
        if root.exists():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _is_client_construction(node: ast.AST) -> bool:
    """``KorTravelGeoRestClient(...)`` 호출인가 (``mod.KorTravelGeoRestClient(...)`` 포함)."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == _CLIENT
    if isinstance(func, ast.Attribute):
        return func.attr == _CLIENT
    return False


def _preflighted_names(tree: ast.AST) -> set[str]:
    """``<name>.preflight()``가 호출된 모든 ``<name>``."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "preflight"
            and isinstance(node.func.value, ast.Name)
        ):
            names.add(node.func.value.id)
    return names


def _live_constructions() -> list[tuple[Path, int, str | None]]:
    """(파일, 줄번호, 대입된 변수명 또는 None) 목록."""
    found: list[tuple[Path, int, str | None]] = []
    for path in _python_files():
        if path in _EXEMPT:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            if not _is_client_construction(node.value):
                continue
            target = node.targets[0]
            name = target.id if isinstance(target, ast.Name) else None
            found.append((path, node.lineno, name))
        # 대입 없이 곧바로 인자로 넘기는 형태는 preflight를 붙일 수 없으므로 따로 잡는다.
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                continue
            for child in ast.iter_child_nodes(node):
                if _is_client_construction(child):
                    found.append((path, getattr(child, "lineno", 0), None))
    return found


def test_live_geo_client_constructions_exist() -> None:
    """스캐너가 실제로 무언가를 찾는다 — 0건이면 이 테스트 전체가 공허해진다."""
    constructions = _live_constructions()
    assert len(constructions) >= 6, (
        f"live geo client 생성 지점을 {len(constructions)}건만 찾았다. "
        "스캐너가 깨졌거나 소스 트리 경로가 바뀌었다."
    )


def test_every_live_geo_client_is_preflighted() -> None:
    """live 생성 지점은 모두 같은 모듈 안에서 ``preflight()``로 보호된다."""
    unguarded: list[str] = []
    for path, lineno, name in _live_constructions():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        guarded = _preflighted_names(tree)
        if name is None or name not in guarded:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            unguarded.append(f"{rel}:{lineno} (변수={name})")
    assert not unguarded, (
        "preflight()가 없는 live geo client 생성 지점:\n  "
        + "\n  ".join(unguarded)
        + "\n키가 없으면 이 경로들은 원인이 지워진 400 Bad Request만 받는다 (T-VN-H21)."
    )


def test_scanner_detects_an_unguarded_construction() -> None:
    """스캐너 자체가 tautology가 아님을 보인다 — 보호 없는 코드를 실제로 잡아낸다."""
    src = "def f(http):\n    c = KorTravelGeoRestClient(http, api_key=None)\n    return c\n"
    tree = ast.parse(src)
    constructions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and _is_client_construction(node.value)
    ]
    assert len(constructions) == 1
    assert _preflighted_names(tree) == set()  # 보호 없음이 정확히 감지된다.

    guarded_tree = ast.parse(src.replace("    return c", "    c.preflight()\n    return c"))
    assert _preflighted_names(guarded_tree) == {"c"}


@pytest.mark.parametrize(
    "expected",
    [
        "src/kortravelmap/cli/main.py",
        "packages/kor-travel-map-api/src/kortravelmap/api/feature_update_service.py",
        "packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_issues.py",
        "packages/kor-travel-map-api/src/kortravelmap/api/routers/offline_uploads.py",
        "packages/kor-travel-map-dagster/src/kortravelmap/dagster/offline_uploads.py",
        "packages/kor-travel-map-dagster/src/kortravelmap/dagster/resources.py",
    ],
)
def test_known_live_geo_modules_are_covered(expected: str) -> None:
    """알려진 live 경로가 스캔 범위에서 빠지지 않는다 (경로 이동 시 조용히 통과 방지)."""
    scanned = {path.relative_to(_REPO_ROOT).as_posix() for path, _, _ in _live_constructions()}
    assert expected in scanned, f"{expected}가 live geo 스캔 대상에서 사라졌다."

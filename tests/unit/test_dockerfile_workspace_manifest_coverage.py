"""`npm ci --workspaces`를 도는 Dockerfile이 워크스페이스 매니페스트를 다 복사하는지 본다.

루트 `package.json`의 `workspaces`가 정본이고, Dockerfile의 `COPY .../package.json`
줄은 그 정본의 **파생물**이어야 한다. 그런데 종전에는 두 Dockerfile이 같은 목록을
각자 손으로 적었고, 이미 어긋나 있었다 — `c7-playwright.Dockerfile`은 셋을 모두
복사하는데 `frontend.Dockerfile`은 `packages/kor-travel-map-user-client`를 빼먹었다.

`npm ci --workspaces`는 "선언된 워크스페이스를 전부 설치하라"는 뜻이다. 매니페스트가
없으면 npm은 그 워크스페이스를 파일시스템에서 못 찾고 조용히 뺀 트리를 만든다.
lockfile이 규정한 트리와 이미지 안의 트리가 달라지는데, 빌드는 성공하므로 아무도
모른다. 이 게이트는 목록이 다시 갈라지는 것을 선언 시점에 막는다.

워크스페이스가 늘어날 때 Dockerfile을 고치는 것을 잊으면 여기서 깨진다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_JSON = _ROOT / "package.json"
_DOCKER_DIR = _ROOT / "docker"


def _declared_workspace_manifests() -> set[str]:
    """루트 선언에서 워크스페이스 매니페스트의 저장소 상대 경로를 파생시킨다."""
    document = json.loads(_PACKAGE_JSON.read_text(encoding="utf-8"))
    patterns = document.get("workspaces") or []
    assert patterns, "루트 package.json에 workspaces 선언이 없다"
    manifests: set[str] = set()
    for pattern in patterns:
        for directory in sorted(_ROOT.glob(pattern)):
            manifest = directory / "package.json"
            if manifest.is_file():
                manifests.add(manifest.relative_to(_ROOT).as_posix())
    assert manifests, f"workspaces 선언 {patterns}가 아무 매니페스트도 가리키지 않는다"
    return manifests


def _dockerfiles_installing_workspaces() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(_DOCKER_DIR.glob("*.Dockerfile")):
        source = path.read_text(encoding="utf-8")
        if re.search(r"npm@[\d.]+ ci .*--workspaces|npm ci .*--workspaces", source):
            found[path.name] = source
    return found


def test_at_least_two_dockerfiles_install_workspaces() -> None:
    """게이트가 대상 없이 공허하게 통과하지 않도록 하한을 둔다."""
    assert len(_dockerfiles_installing_workspaces()) >= 2


def test_workspace_manifests_are_declared_once_in_the_root_package_json() -> None:
    assert _declared_workspace_manifests() == {
        "packages/map-marker-react/package.json",
        "packages/kor-travel-map-admin/frontend/package.json",
        "packages/kor-travel-map-user-client/package.json",
    }


@pytest.mark.parametrize("name", sorted(_dockerfiles_installing_workspaces()))
def test_dockerfile_copies_every_declared_workspace_manifest(name: str) -> None:
    source = _dockerfiles_installing_workspaces()[name]
    copied = {
        match.group(1)
        for match in re.finditer(
            r"^COPY\s+(?:--\S+\s+)*(\S*packages/\S*/package\.json)\b",
            source,
            re.MULTILINE,
        )
    }
    missing = sorted(
        manifest
        for manifest in _declared_workspace_manifests()
        if manifest not in copied
    )
    assert missing == [], f"{name}이 복사하지 않는 워크스페이스 매니페스트: {missing}"

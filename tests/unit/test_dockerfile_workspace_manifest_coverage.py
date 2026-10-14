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


# --- `file:` 의존성 -------------------------------------------------------------
#
# 매니페스트만이 아니다. `file:vendor/....tgz` 같은 로컬 경로 의존성도 `npm ci`
# **이전에** 이미지 안에 있어야 한다. 없으면 `npm ci`가 ENOENT로 죽는다 — 이번에는
# 시끄럽게 죽지만, C7 executor 빌드는 출력을 가리므로("values redacted") 원인이
# 보이지 않는다. 실제로 `frontend.Dockerfile`은 72242b1a0에서 vendor를 복사했는데
# `c7-playwright.Dockerfile`은 1a3c46737에서야 따라왔다 — 그 사이를 막는 게이트가
# 없었다. 정본은 매니페스트의 `file:` 값이고, Dockerfile COPY와 `.dockerignore`는
# 그 파생물이어야 한다.

_DEPENDENCY_SECTIONS = (
    "dependencies",
    "devDependencies",
    "optionalDependencies",
    "peerDependencies",
)


def _declared_file_dependencies() -> set[str]:
    """루트·워크스페이스 매니페스트의 `file:` 값을 저장소 상대 경로로 푼다."""
    manifests = {"package.json", *_declared_workspace_manifests()}
    paths: set[str] = set()
    for manifest in sorted(manifests):
        document = json.loads((_ROOT / manifest).read_text(encoding="utf-8"))
        base = (_ROOT / manifest).parent
        for section in _DEPENDENCY_SECTIONS:
            for spec in (document.get(section) or {}).values():
                if isinstance(spec, str) and spec.startswith("file:"):
                    target = (base / spec.removeprefix("file:")).resolve()
                    paths.add(target.relative_to(_ROOT).as_posix())
    return paths


def _covered_by(path: str, source: str) -> bool:
    source = source.removeprefix("./").rstrip("/")
    return source in {"", "."} or path == source or path.startswith(source + "/")


def _sources_copied_before_npm_ci(source: str) -> list[str]:
    """`npm ci`를 도는 stage에서 그 RUN보다 앞선 build-context COPY의 원본들."""
    lines = re.sub(r"\\\r?\n", " ", source).splitlines()
    stage_sources: list[str] = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"FROM\s", stripped, re.IGNORECASE):
            stage_sources = []
        elif re.match(r"(COPY|ADD)\s", stripped, re.IGNORECASE):
            tokens = stripped.split()[1:]
            if any(token.startswith("--from=") for token in tokens):
                continue
            operands = [token for token in tokens if not token.startswith("--")]
            stage_sources.extend(operands[:-1])
        elif re.match(r"RUN\s", stripped, re.IGNORECASE) and re.search(
            r"npm(@[\d.]+)? ci\b", stripped
        ):
            return stage_sources
    raise AssertionError("npm ci를 도는 RUN을 찾지 못했다")


def _dockerignore_excludes(path: str) -> bool:
    """`.dockerignore` 규칙(마지막 일치가 이김, 디렉터리 제외는 하위까지)."""
    candidates = [path]
    parts = path.split("/")
    candidates += ["/".join(parts[:index]) for index in range(1, len(parts))]
    excluded = False
    text = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for raw in text.splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        negated = rule.startswith("!")
        pattern = rule.removeprefix("!").strip("/")
        regex = ""
        index = 0
        while index < len(pattern):
            if pattern.startswith("**/", index):
                regex, index = regex + "(?:.*/)?", index + 3
            elif pattern.startswith("**", index):
                regex, index = regex + ".*", index + 2
            elif pattern[index] == "*":
                regex, index = regex + "[^/]*", index + 1
            elif pattern[index] == "?":
                regex, index = regex + "[^/]", index + 1
            else:
                regex, index = regex + re.escape(pattern[index]), index + 1
        if any(re.fullmatch(regex, candidate) for candidate in candidates):
            excluded = not negated
    return excluded


def test_file_dependencies_are_declared_and_exist() -> None:
    """하한: 게이트가 대상 없이 공허하게 통과하지 않는다."""
    declared = _declared_file_dependencies()
    assert declared, "매니페스트에 file: 의존성이 하나도 없다 — 게이트를 재검토하라"
    missing = sorted(path for path in declared if not (_ROOT / path).exists())
    assert missing == [], f"file: 의존성이 가리키는 경로가 없다: {missing}"


def test_dockerignore_matcher_sees_known_exclusions() -> None:
    """matcher가 실제로 제외를 본다는 것을 이미 아는 규칙으로 확인한다."""
    assert _dockerignore_excludes("packages/kor-travel-map-admin/frontend/node_modules/x")
    assert _dockerignore_excludes(".env.production")
    assert not _dockerignore_excludes(".env.example")
    assert not _dockerignore_excludes("package.json")


@pytest.mark.parametrize("name", sorted(_dockerfiles_installing_workspaces()))
def test_dockerfile_provides_every_file_dependency_before_npm_ci(name: str) -> None:
    sources = _sources_copied_before_npm_ci(_dockerfiles_installing_workspaces()[name])
    declared = sorted(_declared_file_dependencies())
    not_copied = [path for path in declared if not any(_covered_by(path, s) for s in sources)]
    ignored = [path for path in declared if _dockerignore_excludes(path)]
    assert not_copied == [], f"{name}이 npm ci 전에 복사하지 않는 file: 의존성: {not_copied}"
    assert ignored == [], f".dockerignore가 build context에서 빼는 file: 의존성: {ignored}"

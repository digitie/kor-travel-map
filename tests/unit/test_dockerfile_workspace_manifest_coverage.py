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
import posixpath
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
# **이전에** 이미지 안의 같은 자리에 있어야 한다. 없으면 `npm ci`가 죽는데, C7
# executor 빌드는 출력을 가리므로("values redacted") 원인이 보이지 않는다. 실제로
# `frontend.Dockerfile`은 72242b1a0에서 vendor를 복사했는데 `c7-playwright.Dockerfile`은
# 1a3c46737에서야 따라왔다 — 그 사이를 막는 게이트가 없었다.
#
# 정본은 `npm ci`가 실제로 읽는 `package-lock.json`이다: `packages[*].resolved`가
# `file:`로 시작하는 항목(워크스페이스 `link: true`는 제외). lock의 경로는 lock 위치
# (저장소 루트) 기준이라 해석이 필요 없고, override·전이 의존성도 덮는다. Dockerfile
# COPY와 `.dockerignore`는 그 파생물이어야 한다.

_PACKAGE_LOCK = _ROOT / "package-lock.json"
_WORKSPACE_INSTALL = re.compile(r"npm(?:@[\d.]+)?\s+ci\b[^\n]*--workspaces")


def _locked_file_dependencies() -> set[str]:
    """lock의 `file:` resolved 경로(저장소 루트 기준 POSIX)."""
    document = json.loads(_PACKAGE_LOCK.read_text(encoding="utf-8"))
    paths: set[str] = set()
    for entry in (document.get("packages") or {}).values():
        resolved = entry.get("resolved")
        if entry.get("link") or not isinstance(resolved, str):
            continue
        if resolved.startswith("file:"):
            paths.add(_normalize(resolved.removeprefix("file:")))
    return paths


def _normalize(path: str) -> str:
    normalized = posixpath.normpath(path).lstrip("/")
    return "" if normalized == "." else normalized


def _resolve(workdir: str, path: str) -> str:
    return _normalize(path if path.startswith("/") else posixpath.join(workdir, path))


def _copies_before_workspace_install(source: str) -> tuple[str, list[tuple[str, str]]]:
    """`npm ci --workspaces`를 도는 stage에서 그 RUN의 WORKDIR와, 그보다 앞선
    build-context COPY들의 (context 원본, 이미지 안 목적지) 쌍을 돌려준다.

    목적지는 루트 기준 정규화 경로다. Docker는 파일 원본을 `/`로 끝나는 목적지(또는
    원본이 여럿일 때) 아래에 제 이름으로 두고, 디렉터리 원본은 이름 없이 내용만 둔다.
    """
    lines = re.sub(r"\\\r?\n", " ", source).splitlines()
    workdir = "/"
    copies: list[tuple[str, str]] = []
    for line in lines:
        stripped = line.strip()
        keyword = stripped.split(maxsplit=1)[0].upper() if stripped else ""
        if keyword == "FROM":
            workdir, copies = "/", []
        elif keyword == "WORKDIR":
            workdir = "/" + _resolve(workdir, stripped.split(maxsplit=1)[1])
        elif keyword in {"COPY", "ADD"}:
            tokens = stripped.split()[1:]
            if any(token.startswith("--from=") for token in tokens):
                continue
            *sources, destination = [token for token in tokens if not token.startswith("--")]
            target = _resolve(workdir, destination)
            for item in sources:
                if len(sources) > 1 or (destination.endswith("/") and _is_file_like(item)):
                    name = posixpath.basename(_normalize(item))
                    copies.append((_normalize(item), posixpath.join(target, name)))
                else:
                    copies.append((_normalize(item), target))
        elif keyword == "RUN" and _WORKSPACE_INSTALL.search(stripped):
            return workdir, copies
    raise AssertionError("`npm ci --workspaces`를 도는 RUN을 찾지 못했다")


def _is_file_like(source: str) -> bool:
    """단일 원본이 파일인지(디렉터리 COPY는 내용만 옮긴다). 확장자로 가늠한다."""
    return "." in posixpath.basename(_normalize(source))


def _placed_at(path: str, workdir: str, copies: list[tuple[str, str]]) -> bool:
    """context 경로 `path`가 이미지 안 WORKDIR/<path>에 놓이는가."""
    want = _resolve(workdir, path)
    for source, destination in copies:
        if source and path != source and not path.startswith(source + "/"):
            continue
        rest = path[len(source) :].lstrip("/")
        if _normalize(posixpath.join("/" + destination, rest)) == want:
            return True
    return False


def _dockerignore_excludes(path: str, rules: str) -> bool:
    """`.dockerignore` 규칙(마지막 일치가 이김, 디렉터리 제외는 하위까지)."""
    parts = path.split("/")
    candidates = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
    excluded = False
    for raw in rules.splitlines():
        rule = raw.strip()
        if not rule or rule.startswith("#"):
            continue
        negated = rule.startswith("!")
        pattern = _normalize(rule.removeprefix("!"))
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


def test_locked_file_dependencies_exist() -> None:
    """하한: 게이트가 대상 없이 공허하게 통과하지 않는다."""
    locked = _locked_file_dependencies()
    assert locked, "package-lock.json에 file: 의존성이 하나도 없다 — 게이트를 재검토하라"
    missing = sorted(path for path in locked if not (_ROOT / path).is_file())
    assert missing == [], f"lock의 file: 의존성이 가리키는 파일이 없다: {missing}"


@pytest.mark.parametrize(
    ("path", "rules", "expected"),
    [
        ("vendor/a.tgz", "vendor/\n", True),  # 상위 디렉터리 제외
        ("pkg/vendor/a.tgz", "**/vendor\n", True),  # `**`
        ("pkg/vendor/a.tgz", "vendor\n", False),  # 패턴은 context 루트에 고정
        ("vendor/a.tgz", "/vendor\n", True),  # 선행 `/`
        ("vendor/a.tgz", "*.tgz\n!vendor/a.tgz\n", False),  # 부정, 마지막 일치가 이김
        ("vendor/a.tgz", "!vendor/a.tgz\nvendor\n", True),  # 순서가 바뀌면 제외
        ("vendor/a.tgz", "*.tgz\n", False),  # `*`는 `/`를 넘지 않는다
        ("vendor/a.tgz", "**/*.tgz\n", True),
        ("vendor/a.tgz", "# vendor\n\n", False),
    ],
)
def test_dockerignore_matcher(path: str, rules: str, expected: bool) -> None:
    assert _dockerignore_excludes(path, rules) is expected


@pytest.mark.parametrize(
    ("dockerfile", "expected"),
    [
        ("FROM x\nWORKDIR /w\nCOPY vendor ./vendor\nRUN npm ci --workspaces\n", True),
        ("FROM x\nWORKDIR /w\nCOPY vendor/a.tgz ./vendor/\nRUN npm ci --workspaces\n", True),
        ("FROM x\nWORKDIR /w\nCOPY . .\nRUN npm ci --workspaces\n", True),
        ("FROM x\nWORKDIR /w\nCOPY vendor /w/vendor\nRUN npm ci --workspaces\n", True),
        # 목적지가 다르면 npm ci가 찾는 자리가 아니다.
        ("FROM x\nWORKDIR /w\nCOPY vendor ./\nRUN npm ci --workspaces\n", False),
        ("FROM x\nWORKDIR /w\nCOPY vendor /vendor\nRUN npm ci --workspaces\n", False),
        ("FROM x\nCOPY vendor ./vendor\nWORKDIR /w\nRUN npm ci --workspaces\n", False),
        # 다른 stage의 COPY는 세지 않는다.
        (
            "FROM x\nWORKDIR /w\nCOPY vendor ./vendor\nRUN npm ci\n"
            "FROM y\nWORKDIR /w\nRUN npm ci --workspaces\n",
            False,
        ),
        # `--workspaces` 없는 앞선 npm ci가 아니라 `--workspaces` RUN까지 센다.
        (
            "FROM x\nWORKDIR /w\nRUN npm ci\nCOPY vendor vendor\nRUN npm ci --workspaces\n",
            True,
        ),
        (
            "FROM x\nWORKDIR /w\nRUN npm ci --workspaces\nCOPY vendor vendor\n",
            False,
        ),
    ],
)
def test_copy_placement_matcher(dockerfile: str, expected: bool) -> None:
    workdir, copies = _copies_before_workspace_install(dockerfile)
    assert _placed_at("vendor/a.tgz", workdir, copies) is expected


@pytest.mark.parametrize("name", sorted(_dockerfiles_installing_workspaces()))
def test_dockerfile_provides_every_file_dependency_before_npm_ci(name: str) -> None:
    workdir, copies = _copies_before_workspace_install(_dockerfiles_installing_workspaces()[name])
    assert _placed_at("package.json", workdir, copies), (
        f"{name}이 루트 package.json을 WORKDIR({workdir})에 두지 않는다"
    )
    locked = sorted(_locked_file_dependencies())
    not_placed = [path for path in locked if not _placed_at(path, workdir, copies)]
    assert not_placed == [], (
        f"{name}이 npm ci --workspaces 전에 {workdir}/<path>에 두지 않는 file: 의존성: {not_placed}"
    )
    rules = (_ROOT / ".dockerignore").read_text(encoding="utf-8")
    ignored = [path for path in locked if _dockerignore_excludes(path, rules)]
    assert ignored == [], f".dockerignore가 build context에서 빼는 file: 의존성: {ignored}"

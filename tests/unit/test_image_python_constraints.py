"""이미지가 설치하는 Python 버전이 재빌드로 흘러가지 못하는지 본다.

공유 Dagster plane(stage 0)의 전제는 "host(webserver/daemon) 버전 >= code-server
버전"이다(Dagster 호환 정책). 2026-09-29까지 Map 이미지는 lockfile 없이
`pip install ".[providers]"`로 설치했다 — `dagster>=1.9,<2`는 하한일 뿐이라 실제
버전은 빌드한 날 PyPI가 준 것이었다. 한 번의 무심한 재빌드가 code-server를 공유
host보다 높은 dagster로 올릴 수 있었다.

이 게이트가 지키는 것:

1. `docker/constraints-dagster.txt`의 핀은 전부 `==`이고, 공유 plane이 정한 패키지를
   빠짐없이 담는다.
2. dagster family는 한 버전이다(`dagster-postgres`는 0.(minor+16).patch 짝).
3. 각 핀이 저장소 pyproject 선언 범위 **안에** 든다 — 범위 밖 핀은 설치 시점의 해소
   실패로만 드러난다.
4. API·Dagster 두 Dockerfile의 프로젝트 설치가 **전부** 그 파일을 `-c`로 읽고, 읽기
   전에 builder에 COPY한다.
5. CI workflow가 저장소 패키지를 설치하는 `pip install`도 **전부** 같은 파일을 `-c`로
   읽는다 — 테스트가 이미지와 다른 dagster·pydantic·SQLAlchemy로 초록이 되지 않게.

이 파일은 **나열한 패키지만** 고정한다. 나머지 전이 의존성은 pyproject 범위 안에서 설치
시점에 해소된다(전체 freeze를 고정하지 않는다).
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_CONSTRAINTS_RELATIVE = "docker/constraints-dagster.txt"
_CONSTRAINTS = _ROOT / _CONSTRAINTS_RELATIVE
_DOCKERFILES = ("docker/api.Dockerfile", "docker/dagster.Dockerfile")
_WORKFLOWS = _ROOT / ".github" / "workflows"
_PYPROJECTS = (
    "pyproject.toml",
    "packages/kor-travel-map-api/pyproject.toml",
    "packages/kor-travel-map-dagster/pyproject.toml",
)

#: 공유 plane이 버전을 정하는 패키지(Manager `dagster-shared-plan` §3). 여기 빠진
#: 이름은 재빌드마다 움직인다.
_DAGSTER_FAMILY = frozenset(
    {"dagster", "dagster-webserver", "dagster-graphql", "dagster-pipes", "dagster-shared"}
)
_REQUIRED = _DAGSTER_FAMILY | {
    "dagster-postgres",
    "grpcio",
    "grpcio-health-checking",
    "protobuf",
    "pydantic",
    "pydantic-core",
    "pydantic-settings",
    "sqlalchemy",
    "psycopg",
    "psycopg-binary",
    "psycopg-pool",
    "psycopg2-binary",
    "asyncpg",
}
#: 한 줄 안의 셸 명령 경계. 줄바꿈은 ``splitlines``가 나눈다.
_COMMAND_SEPARATOR = re.compile(r"&&|\|\||;")
_CONSTRAINT_FLAGS = frozenset({"-c", "--constraint"})


def _shell_commands(text: str) -> list[str]:
    """continuation을 풀고 줄·``&&``·``||``·``;``로 나눈 셸 명령들."""

    joined = re.sub(r"\\\n\s*", " ", text)
    return [
        command.strip()
        for line in joined.splitlines()
        for command in _COMMAND_SEPARATOR.split(line)
        if command.strip()
    ]


def _command_tokens(command: str) -> list[str]:
    """셸 토큰. ``#`` 뒤는 주석이라 버린다 — 주석 속 ``-c``는 설치를 묶지 않는다."""

    return shlex.split(command, comments=True)


def _reads_constraints(tokens: list[str]) -> bool:
    pairs = zip(tokens, tokens[1:], strict=False)
    return f"--constraint={_CONSTRAINTS_RELATIVE}" in tokens or any(
        flag in _CONSTRAINT_FLAGS and value == _CONSTRAINTS_RELATIVE for flag, value in pairs
    )


_PIN_LINE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[0-9][0-9A-Za-z.+-]*)$")


def _pins() -> dict[str, Version]:
    pins: dict[str, Version] = {}
    for raw in _CONSTRAINTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _PIN_LINE.match(line)
        assert match is not None, f"정확한 `name==version` 핀이 아니다: {line!r}"
        name = canonicalize_name(match["name"])
        assert name not in pins, f"중복 핀: {name}"
        pins[name] = Version(match["version"])
    return pins


def test_constraints_pin_every_shared_plane_package_exactly() -> None:
    pins = _pins()
    missing = sorted(_REQUIRED - pins.keys())
    assert not missing, f"공유 plane 버전 집합에서 빠진 핀: {missing}"


def test_dagster_family_is_one_version() -> None:
    pins = _pins()
    family = {name: pins[name] for name in _DAGSTER_FAMILY}
    assert len(set(family.values())) == 1, family
    core = pins["dagster"]
    # dagster 1.N.P ↔ dagster-postgres 0.(N+16).P — 라이브러리는 core와 같은 날 나간다.
    assert pins["dagster-postgres"] == Version(f"0.{core.minor + 16}.{core.micro}"), (
        pins["dagster-postgres"],
        core,
    )


def _declared_requirements() -> list[tuple[str, Requirement]]:
    declared: list[tuple[str, Requirement]] = []
    for relative in _PYPROJECTS:
        document = tomllib.loads((_ROOT / relative).read_text(encoding="utf-8"))
        project = document["project"]
        groups = [project.get("dependencies", [])]
        groups.extend(project.get("optional-dependencies", {}).values())
        for group in groups:
            for raw in group:
                try:
                    requirement = Requirement(raw)
                except InvalidRequirement as exc:  # pragma: no cover - pyproject 자체가 깨짐
                    raise AssertionError(f"{relative}: {raw!r}") from exc
                declared.append((relative, requirement))
    return declared


def test_every_pin_satisfies_the_declared_ranges() -> None:
    pins = _pins()
    checked = 0
    for relative, requirement in _declared_requirements():
        name = canonicalize_name(requirement.name)
        if name not in pins or requirement.url is not None:
            continue
        checked += 1
        assert requirement.specifier.contains(pins[name], prereleases=True), (
            f"{relative}: {requirement} 이(가) 핀 {name}=={pins[name]}을 허용하지 않는다"
        )
    # 하한: dagster·SQLAlchemy·pydantic처럼 선언과 핀이 겹치는 이름을 실제로 봤다.
    assert checked >= 8, checked


def _builder_install_violations(text: str) -> list[str]:
    """Dockerfile builder stage의 프로젝트 설치가 constraints를 읽는지 본다.

    ``#`` 줄은 Dockerfile 주석이라 먼저 버린다 — 주석 속 ``COPY``·``-c``는 세지 않는다.
    """

    uncommented = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    stages = re.split(r"^FROM\s", uncommented, flags=re.MULTILINE)
    builders = [
        stage
        for stage in stages
        if re.match(r"\S+\s+AS\s+builder\s*$", stage.split("\n", 1)[0])
    ]
    if len(builders) != 1:
        return ["builder stage를 하나로 찾지 못했다"]
    builder = builders[0]
    # continuation을 풀고 `&&`·`||`·`;`로 나눠 명령 하나씩 본다.
    installs = [command for command in _shell_commands(builder) if "--prefix=/install" in command]
    if not installs:
        return ["프로젝트 설치를 찾지 못했다 — 게이트가 공허하다"]
    violations = [
        f"constraints를 읽지 않는다: {command}"
        for command in installs
        if not _reads_constraints(_command_tokens(command))
    ]
    copy_line = f"COPY {_CONSTRAINTS_RELATIVE} ./{_CONSTRAINTS_RELATIVE}"
    if copy_line not in builder:
        violations.append("builder가 constraints를 COPY하지 않는다")
    elif builder.index(copy_line) > builder.index("--prefix=/install"):
        violations.append("constraints COPY가 설치보다 뒤다")
    return violations


@pytest.mark.parametrize("relative", _DOCKERFILES)
def test_dockerfile_project_installs_read_the_constraints(relative: str) -> None:
    text = (_ROOT / relative).read_text(encoding="utf-8")
    assert _builder_install_violations(text) == [], relative


_BUILDER = """\
FROM python AS builder
COPY docker/constraints-dagster.txt ./docker/constraints-dagster.txt
RUN python -m pip install --upgrade pip \\
    && python -m pip install --prefix=/install \\
        -c docker/constraints-dagster.txt .
FROM python AS runtime
"""
_BUILDER_TAIL = "-c docker/constraints-dagster.txt .\n"


@pytest.mark.parametrize(
    ("dockerfile", "violations"),
    [
        (_BUILDER, 0),
        # `;`로 이은 두 번째 설치는 constraints 없이 돈다.
        (
            _BUILDER.replace(
                _BUILDER_TAIL, _BUILDER_TAIL[:-1] + " ; pip install --prefix=/install ./x\n"
            ),
            1,
        ),
        # 주석 속 `-c`는 설치를 묶지 않는다.
        (_BUILDER.replace(_BUILDER_TAIL, ". # -c docker/constraints-dagster.txt\n"), 1),
        # 주석 처리된 COPY는 COPY가 아니다.
        (_BUILDER.replace("COPY docker/", "# COPY docker/"), 1),
    ],
)
def test_builder_install_detector_rejects_unconstrained_installs(
    dockerfile: str, violations: int
) -> None:
    assert len(_builder_install_violations(dockerfile)) == violations


def _repository_installs(text: str) -> tuple[list[str], list[str]]:
    """workflow 본문에서 저장소 패키지를 까는 ``pip install`` 명령을 모두 찾는다.

    ``pip install --upgrade pip``처럼 저장소 밖 도구만 까는 명령은 제외한다. 저장소
    설치의 표지는 인자 ``.``·``.[extra]``·``./…``·``packages/…``다.
    돌려주는 것은 (저장소 설치 전부, 그중 constraints를 읽지 않는 것).
    """

    installs: list[str] = []
    unconstrained: list[str] = []
    for raw_command in _shell_commands(text):
        command = re.sub(r"^(?:-\s+)?(?:run:\s*)?", "", raw_command)
        if "pip install" not in command:
            continue
        # 주석을 뺀 토큰에서 `pip install` 뒤의 인자를 본다.
        tokens = _command_tokens(command)
        starts = [
            index + 2
            for index in range(len(tokens) - 1)
            if tokens[index] in {"pip", "pip3"} and tokens[index + 1] == "install"
        ]
        if not starts:
            continue
        targets = [
            argument
            for argument in tokens[starts[0] :]
            if argument == "." or argument.startswith((".[", "./", "packages/"))
        ]
        if not targets:
            continue
        installs.append(command)
        if not _reads_constraints(tokens):
            unconstrained.append(command)
    return installs, unconstrained


def test_workflow_repository_installs_read_the_constraints() -> None:
    per_workflow: dict[str, int] = {}
    for path in sorted(_WORKFLOWS.glob("*.y*ml")):
        installs, unconstrained = _repository_installs(path.read_text(encoding="utf-8"))
        assert unconstrained == [], (path.name, unconstrained)
        if installs:
            per_workflow[path.name] = len(installs)
    # 하한: 저장소를 까는 workflow를 **본** 것 — 넷 모두, 설치 명령 17개.
    assert set(per_workflow) >= {"ci.yml", "lint.yml", "openapi.yml", "postgis-only.yml"}, (
        per_workflow
    )
    assert sum(per_workflow.values()) >= 17, per_workflow


@pytest.mark.parametrize(
    ("workflow", "unconstrained"),
    [
        ('run: |\n  pip install -e ".[dev]"\n', 1),
        ("run: python -m pip install -e packages/kor-travel-map-api\n", 1),
        ("- run: pip install -e packages/kor-travel-map-dagster && pip install ruff\n", 1),
        ("run: pip install . \\\n  ./packages/kor-travel-map-api\n", 1),
        ("run: python -m pip install --upgrade pip\n", 0),
        ('run: pip install -c docker/constraints-dagster.txt -e ".[dev]"\n', 0),
        # 주석 속 `-c`는 설치를 묶지 않는다.
        ('run: pip install -e ".[dev]"  # -c docker/constraints-dagster.txt\n', 1),
        # `;`·`||`·줄바꿈으로 이은 두 번째 설치도 각자 본다.
        (
            "run: pip install -c docker/constraints-dagster.txt -e packages/kor-travel-map-api;"
            " pip install -e packages/kor-travel-map-dagster\n",
            1,
        ),
        ("run: pip install ruff || pip install -e packages/kor-travel-map-api\n", 1),
        ("run: |\n  pip install ruff\n  pip install -e .\n", 1),
        # 주석 줄의 설치는 설치가 아니다.
        ("run: |\n  # pip install -e .\n  pip install ruff\n", 0),
    ],
)
def test_workflow_install_detector_rejects_unconstrained_installs(
    workflow: str, unconstrained: int
) -> None:
    assert len(_repository_installs(workflow)[1]) == unconstrained

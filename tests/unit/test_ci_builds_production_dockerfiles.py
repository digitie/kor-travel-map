"""CI가 프로덕션 Dockerfile을 실제로 빌드하는지 본다.

2026-09-03까지 `.github/workflows/`에 `docker build`가 **0건**이었다. 그래서
Dockerfile 결함은 n150 격리 e2e나 pinned rebuild에서야 드러났고 그 피드백 루프는
한 시간이다 — `frontend.Dockerfile`이 선언된 워크스페이스 셋 중 둘만 복사하던
결함(#1137)이 정확히 그렇게 숨어 있었다. `frontend.yml`은 전체 체크아웃에서 같은
npm 명령을 돌리므로 영원히 통과했다.

이 게이트가 지키는 것 셋:

1. CI에 실제 이미지 빌드가 **있다**.
2. 빌드는 `scripts/docker-buildx.sh`를 **경유한다** — 그 스크립트를 호출하는 곳이
   저장소에 하나도 없어 스크립트 자체가 검증되지 않고 있었다.
3. `docker/`의 프로덕션 Dockerfile이 그 스크립트에 **빠짐없이** 실려 있다. 새
   Dockerfile을 추가하고 스크립트에 얹지 않으면 여기서 깨진다.

arm64는 굽지 않는다 — 배포 대상은 amd64뿐이고 기본값
`linux/amd64,linux/arm64`는 CI 시간을 두 배로 쓰면서 아무것도 더 막지 못한다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "docker-images.yml"
_BUILDX = _ROOT / "scripts" / "docker-buildx.sh"
_DOCKER_DIR = _ROOT / "docker"

#: 이 스크립트가 굽지 않는 Dockerfile과 그 이유. 프로덕션 런타임이 아닌 것만 들어온다.
_NOT_A_RUNTIME_IMAGE = {
    # C7 Playwright 러너는 테스트 하네스 이미지다. 별도 스크립트
    # (`scripts/build-c7-playwright-image.sh`)가 굽고, 필수 build arg
    # `C7_REPOSITORY_COMMIT`을 호출자가 정한다.
    "c7-playwright.Dockerfile",
}


def _workflow() -> dict[str, Any]:
    document = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _build_step() -> dict[str, Any]:
    steps = _workflow()["jobs"]["build"]["steps"]
    for step in steps:
        if "docker-buildx.sh" in str(step.get("run", "")):
            return step
    raise AssertionError("docker-buildx.sh를 실행하는 step이 없다")


def test_ci_actually_builds_images() -> None:
    """워크플로가 존재하고 PR에서 돈다."""
    document = _workflow()
    triggers = document.get(True) or document.get("on")
    assert "pull_request" in triggers, triggers
    assert "push" in triggers


def test_the_build_goes_through_the_repository_script() -> None:
    """스크립트를 우회해 인라인 `docker build`를 쓰면 스크립트가 다시 죽은 코드가 된다."""
    step = _build_step()
    assert "scripts/docker-buildx.sh" in step["run"]


def test_ci_does_not_build_arm64() -> None:
    """배포 대상은 amd64뿐이다 — 기본값은 arm64까지 굽는다."""
    environment = _build_step()["env"]
    assert environment["KOR_TRAVEL_MAP_DOCKER_PLATFORMS"] == "linux/amd64"


def test_ci_needs_no_registry() -> None:
    """`oci` 출력이라야 registry 자격증명 없이 돌 수 있다."""
    environment = _build_step()["env"]
    assert environment["KOR_TRAVEL_MAP_BUILDX_OUTPUT"] == "oci"


def test_the_workflow_has_no_path_filter() -> None:
    """path 필터는 Dockerfile의 `COPY` 대상을 두 번째로 선언하는 것이다.

    한쪽만 늘어나면 조용히 빠진다 — 이 저장소가 결함으로 규정한 이중 선언이다
    (AGENTS.md DO NOT 15). 필터가 없으면 파생할 것도 뒤처질 것도 없다.
    """
    triggers = _workflow().get(True) or _workflow().get("on")
    for event in ("push", "pull_request"):
        assert "paths" not in triggers[event], event
        assert "paths-ignore" not in triggers[event], event


def test_every_production_dockerfile_is_built() -> None:
    """`docker/`의 런타임 Dockerfile이 빌드 스크립트에 빠짐없이 실려 있다."""
    script = _BUILDX.read_text(encoding="utf-8")
    # 첫 인자는 이미지 **목록**이라 따옴표 안에 공백이 올 수 있다
    # (`build_one "$DAGSTER_IMAGE $DAGSTER_DAEMON_IMAGE" docker/dagster.Dockerfile`).
    built = set(
        re.findall(
            r"""^build_one\s+(?:"[^"]*"|'[^']*'|\S+)\s+(docker/\S+\.Dockerfile)""",
            script,
            re.M,
        )
    )
    present = {
        f"docker/{path.name}"
        for path in sorted(_DOCKER_DIR.glob("*.Dockerfile"))
        if path.name not in _NOT_A_RUNTIME_IMAGE
    }
    assert present, "docker/에 Dockerfile이 없다 — 게이트가 공허하다"
    assert built == present, {"스크립트에만": built - present, "빌드되지 않음": present - built}

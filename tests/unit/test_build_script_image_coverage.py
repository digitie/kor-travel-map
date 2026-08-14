"""두 빌드 스크립트가 **같은 이미지 집합**을 만드는지 검사한다.

2026-08-13 prod 재빌드에서 `kor-travel-map-dagster-daemon` 태그가 빠졌다. daemon은
`dagster-daemon run -m kortravelmap.dagster.definitions`로 **자기 이미지 안의 패키지를
in-process 로드**하므로, 옆의 code server가 최신이어도 소용이 없다. TVN33 커토버가
`ops.feature_update_requests.providers`를 지운 뒤 `feature_update_request_queue_sensor`가
30초마다 죽었다 — dagster metadata DB 실측 `consecutive_failure_count=2020`. 큐가 비어
있어 운영자에겐 무반응으로만 보였다.

그 사고의 직접 원인은 승인되지 않은 raw `docker build`였지만, **저장소도 같은 누락을
성문화하고 있었다**: `scripts/docker-build.sh`는 네 서비스를 나열하는데
`scripts/docker-buildx.sh`는 셋만 구웠다. 두 파일이 서로 모순인 채로 오래 있었다.

여기서 세는 것은 **Dockerfile의 다중집합**이다. `dagster`와 `dagster-daemon`은 같은
Dockerfile을 쓰고 command만 다르므로, "Dockerfile 종류가 같다"로는 누락을 못 잡는다 —
`dagster.Dockerfile`이 **두 번** 나와야 한다.

다중집합의 단위는 **이미지(태그)**이지 build 호출이 아니다. `docker-buildx.sh`는 그
둘을 한 번의 build에 태그 두 개로 굽는다 — 두 번 굽는 형태는 두 이미지가 같다는 보장이
없는데, daemon이 code server와 **같은 코드**여야 한다는 것이 바로 이 사고의 요구사항이다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = _ROOT / "docker-compose.yml"
_BUILD_SH = _ROOT / "scripts" / "docker-build.sh"
_BUILDX_SH = _ROOT / "scripts" / "docker-buildx.sh"


def _compose_build_dockerfiles() -> dict[str, str]:
    document: Any = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    found: dict[str, str] = {}
    for name, service in (document.get("services") or {}).items():
        build = service.get("build") if isinstance(service, dict) else None
        if isinstance(build, dict) and build.get("dockerfile"):
            found[name] = str(build["dockerfile"])
    assert found, "compose에 build 블록을 가진 서비스가 없다 — 이 가드의 전제가 깨졌다"
    return found


def _compose_build_services() -> list[str]:
    """`docker-build.sh`가 `docker compose build`에 넘기는 서비스 목록."""

    text = _BUILD_SH.read_text(encoding="utf-8")
    match = re.search(r'"\$\{compose\[@\]\}"\s+build\s+([^\n]+)', text)
    assert match is not None, "docker-build.sh에서 `compose build <services>` 줄을 찾지 못했다"
    services = match.group(1).split()
    assert services, "docker-build.sh가 빌드할 서비스를 하나도 나열하지 않는다"
    return services


def _buildx_dockerfiles() -> list[str]:
    """`docker-buildx.sh`가 굽는 **이미지마다** 그 Dockerfile을 하나씩.

    `build_one`의 첫 인자는 이미지 하나 이상의 목록이므로(같은 Dockerfile을 한 번만
    빌드하고 태그를 여럿 다는 형태) 호출 횟수가 아니라 **이미지 개수**를 센다. 호출을
    세면 dagster/dagster-daemon처럼 한 번에 두 태그를 다는 형태를 누락으로 오판한다.
    """

    found: list[str] = []
    for names, dockerfile in _buildx_calls():
        found.extend([dockerfile] * len(names))
    return found


def _buildx_calls() -> list[tuple[list[str], str]]:
    """`docker-buildx.sh`의 `build_one "<이미지들>" <dockerfile>` 호출 (이미지 목록, Dockerfile)."""

    text = _BUILDX_SH.read_text(encoding="utf-8")
    calls = re.findall(r'^build_one\s+"([^"]+)"\s+(\S+)', text, re.MULTILINE)
    assert calls, "docker-buildx.sh에서 build_one 호출을 찾지 못했다"
    parsed: list[tuple[list[str], str]] = []
    for images, dockerfile in calls:
        names = re.findall(r"\$\{?([A-Z_]+)\}?", images)
        assert names, f"build_one 첫 인자에서 이미지 변수를 찾지 못했다: {images!r}"
        parsed.append((names, dockerfile))
    return parsed


def test_both_build_scripts_produce_the_same_image_set() -> None:
    dockerfiles = _compose_build_dockerfiles()
    services = _compose_build_services()

    unknown = [name for name in services if name not in dockerfiles]
    assert not unknown, (
        f"docker-build.sh가 compose에 build 블록이 없는 서비스를 빌드하려 한다: {unknown}"
    )

    expected = sorted(dockerfiles[name] for name in services)
    actual = sorted(_buildx_dockerfiles())
    assert actual == expected, (
        "두 빌드 스크립트가 만드는 이미지 집합이 다르다 — 한쪽만 도는 배포에서 일부"
        " 컨테이너가 낡은 코드로 남는다(2026-08-13 daemon 사고).\n"
        f"  docker-build.sh({', '.join(services)}) -> {expected}\n"
        f"  docker-buildx.sh                      -> {actual}"
    )


def test_the_dagster_daemon_image_is_built() -> None:
    """daemon 누락은 **조용하다** — 큐가 비어 있으면 운영자에게 무반응으로만 보인다.

    다중집합 비교가 이미 잡지만, 회귀했을 때 실패 메시지가 사고 이름을 부르게 한다.
    """

    services = _compose_build_services()
    assert "dagster-daemon" in services, (
        "docker-build.sh가 dagster-daemon을 빌드하지 않는다 — 그 이미지는 자기 안의"
        " 패키지를 in-process 로드하므로 code server가 최신이어도 낡은 코드로 돈다"
    )
    daemon_dockerfile = _compose_build_dockerfiles()["dagster-daemon"]
    assert _buildx_dockerfiles().count(daemon_dockerfile) >= 2, (
        f"docker-buildx.sh가 {daemon_dockerfile}에 태그를 하나만 단다 — dagster와"
        " dagster-daemon은 같은 Dockerfile을 쓰는 **별개 태그**다"
    )


def test_the_dagster_pair_is_one_build_with_two_tags() -> None:
    """두 태그가 **같은 build**에서 나와야 한다.

    개수만 세면 `build_one`을 두 번 부르는 형태도 통과한다. 그러면 두 이미지가 같은
    코드라는 보장이 없는데(캐시 미스·비결정적 레이어), daemon은 자기 이미지의 패키지를
    in-process 로드하므로 code server와 어긋나는 순간 그게 곧 2026-08-13 사고다.
    """

    pair = [
        names
        for names, dockerfile in _buildx_calls()
        if dockerfile == _compose_build_dockerfiles()["dagster-daemon"]
    ]
    assert len(pair) == 1, (
        f"dagster Dockerfile을 {len(pair)}번 빌드한다 — 한 번 빌드하고 태그를 여럿"
        " 달아야 두 이미지가 같음을 보장한다"
    )
    assert len(pair[0]) >= 2, f"그 한 번의 build가 태그를 하나만 단다: {pair[0]}"

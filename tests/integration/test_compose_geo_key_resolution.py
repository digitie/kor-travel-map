"""`docker compose config`가 **해석한 값**으로 geo 소비자 키를 확인한다.

`tests/unit/test_geo_key_provenance.py`는 정적 검사다 — YAML을 스스로 읽고 쉘을 스스로
토큰화한다. 그 방식은 세 번 뚫렸다(리스트형 `environment`, 이름을 인용한 대입, override
파일). 여기서는 **Docker Compose 자신에게 묻는다**: 앵커·머지 키·리스트형·`env_file`·
override 파일·보간 순서를 전부 해석한 최종 값이 무엇인가.

방법은 sentinel이다. VWorld 계열 변수에만 알아볼 수 있는 값을 넣고 geo 소비자 변수는
비운 채 `docker compose config`를 돌린다. 어떤 서비스의 geo 소비자 키에서든 그 sentinel이
나오면 **그 경로로 VWorld 키가 실제로 흘러간다**는 뜻이다.

2026-08-13 prod 장애가 정확히 그 형상이었다 — `dagster`/`dagster-daemon`만 VWorld 키를
들고 있었고, geo는 그것을 `401 E0401`로 거절한다.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[2]
_SENTINEL = "VWORLD-SENTINEL-MUST-NOT-REACH-GEO"
_GEO_CONSUMER_VARS = frozenset(
    {
        "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY",
        "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",
        "KOR_TRAVEL_GEO_API_KEY",
    }
)
_VWORLD_VARS = (
    "NEXT_PUBLIC_VWORLD_API_KEY",
    "KOR_TRAVEL_GEO_VWORLD_API_KEY",
    "VWORLD_API_KEY",
)
#: `${NAME:?…}` — 값이 없으면 compose가 보간 단계에서 죽는다. 이름을 파일에서 **읽어**
#: 더미로 채운다. 손으로 적으면 compose가 늘 때마다 이 테스트만 조용히 안 돌게 된다.
_REQUIRED_RE = re.compile(r"\$\{([A-Z0-9_]+):\?")


def _compose_files() -> list[list[str]]:
    """검사할 파일 조합. base 단독 + base+override 각각."""

    base = _ROOT / "docker-compose.yml"
    assert base.exists(), "docker-compose.yml이 없다"
    overrides = sorted(
        path
        for path in _ROOT.glob("docker-compose.*.yml")
        if path.name != "docker-compose.yml"
    )
    combos = [[str(base)]]
    combos.extend([str(base), str(override)] for override in overrides)
    return combos


def _environment(files: list[str]) -> dict[str, str]:
    text = "\n".join(Path(name).read_text(encoding="utf-8") for name in files)
    env = dict(os.environ)
    for name in sorted(set(_REQUIRED_RE.findall(text))):
        env.setdefault(name, f"dummy-{name.lower()}-0123456789abcdef0123456789abcdef")
        env[name] = env[name] or f"dummy-{name.lower()}-0123456789abcdef0123456789abcdef"
    for name in _VWORLD_VARS:
        env[name] = _SENTINEL
    for name in _GEO_CONSUMER_VARS:
        env.pop(name, None)
    return env


#: `env_file:`은 `- path: x/.env` 형태와 `- x/.env` 형태를 모두 쓴다. 주석에 적힌 같은
#: 경로까지 잡히지만, 없으면 빈 파일을 만들고 끝나면 지우므로 무해하다.
_ENV_FILE_RE = re.compile(r"(?:path:\s*)?([\w./-]*\.env)\b")


@pytest.fixture
def _present_env_files() -> Any:
    """`env_file:`이 가리키는 파일이 없으면 **빈 파일로** 만들어 둔다.

    그 파일들은 gitignore 대상이라 체크아웃에는 없다. 없으면 compose가 보간 전에
    죽어서 이 검사가 통째로 안 돈다. 빈 파일로 채우면 compose 사슬만 재는 것이 되고,
    운영자 `.env`가 값을 주입하는 축은 이 가드의 범위 밖이라는 사실과도 맞다.
    """

    created: list[Path] = []
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in _ROOT.glob("docker-compose*.yml")
    )
    for name in sorted(set(_ENV_FILE_RE.findall(text))):
        candidate = (_ROOT / name).resolve()
        if _ROOT in candidate.parents and not candidate.exists():
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text("", encoding="utf-8")
            created.append(candidate)
    yield
    for path in created:
        path.unlink(missing_ok=True)


def _resolved(files: list[str], env: dict[str, str]) -> Any:
    command = ["docker", "compose"]
    for name in files:
        command += ["-f", name]
    command.append("config")
    result = subprocess.run(  # noqa: S603
        command, cwd=_ROOT, env=env, capture_output=True, text=True, check=False, timeout=180
    )
    assert result.returncode == 0, (
        f"docker compose config 실패 ({' '.join(files)}):\n{result.stderr[-2000:]}"
    )
    return yaml.safe_load(result.stdout)


@pytest.mark.parametrize("files", _compose_files(), ids=lambda files: Path(files[-1]).name)
@pytest.mark.usefixtures("_present_env_files")
def test_no_compose_path_resolves_a_geo_consumer_key_to_the_vworld_key(files: list[str]) -> None:
    if shutil.which("docker") is None:
        pytest.skip("docker CLI 없음 — 해석 검사를 돌릴 수 없다")
    document = _resolved(files, _environment(files))
    leaks: list[str] = []
    for name, service in (document.get("services") or {}).items():
        blocks: list[Any] = [service.get("environment")]
        build = service.get("build")
        if isinstance(build, dict):
            blocks.append(build.get("args"))
        for block in blocks:
            if not isinstance(block, dict):
                continue
            for key, value in block.items():
                if key in _GEO_CONSUMER_VARS and _SENTINEL in str(value or ""):
                    leaks.append(f"{name}.{key}")
    assert not leaks, (
        "geo 소비자 키가 VWorld 값으로 해석된다 — geo가 401(E0401)로 거절하는 값이다:\n"
        + "\n".join(f"  {entry}" for entry in leaks)
    )

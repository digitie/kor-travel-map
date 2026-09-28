"""`scripts/n150/repin.sh` 3단계 — D2 fixture DSN을 Map API 컨테이너의 DSN에서 유도한다 (ADR-103).

스크립트의 python helper를 **그대로 떼어** 가짜 `docker`(PATH 앞)와 임시 env 파일로 실행한다.
값은 비밀이므로 어떤 경로에서도 출력되면 안 되고, 확인이 하나라도 어긋나면 파일을 건드리지 않는다.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "n150" / "repin.sh"
_KEY = "E2E_ADMIN_FEATURE_FIXTURE_PG_DSN"
_SECRET = "s3cr3t-Pw_value.~x"
_GOOD_DSN = f"postgresql+asyncpg://ktm_feature_service:{_SECRET}@127.0.0.1:11000/kor_travel_map"
_OLD_LINE = f"{_KEY}=postgresql+asyncpg://ktm_feature_service:old@127.0.0.1:12700/kor_travel_map\n"


def _helper() -> str:
    source = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r'^python3 -I - "\$ENV_FILE" "\$\{APIS\[0\]\}" <<\'PY\'.*?\n(.*?)^PY$',
        source,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "repin.sh에서 fixture DSN helper를 찾지 못했다"
    return match.group(1)


def _run(tmp_path: Path, env_text: str, container_env: list[str]) -> tuple[
    subprocess.CompletedProcess[str], Path
]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    inspect = tmp_path / "inspect.json"
    inspect.write_text(json.dumps([{"Config": {"Env": container_env}}]), encoding="utf-8")
    docker = bin_dir / "docker"
    docker.write_text(
        '#!/bin/sh\n[ "$1" = inspect ] && [ "$2" = -- ] && [ "$3" = api123 ] || exit 9\n'
        f'cat "{inspect}"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)
    env_file = tmp_path / ".d2-live.env"
    env_file.write_text(env_text, encoding="utf-8")
    env_file.chmod(0o600)
    proc = subprocess.run(
        [sys.executable, "-I", "-", str(env_file), "api123"],
        input=_helper(),
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_LOGIN_ROLE": "ktm_feature_service",
            "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE": "kor_travel_map",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, env_file


def _no_secret(proc: subprocess.CompletedProcess[str]) -> None:
    assert _SECRET not in proc.stdout
    assert _SECRET not in proc.stderr


def test_replaces_exactly_the_fixture_line_with_the_api_dsn(tmp_path: Path) -> None:
    before = f"A=1\n{_OLD_LINE}E2E_C7_MAP_API_SERVICE=api\n"
    proc, env_file = _run(tmp_path, before, ["X=1", f"KOR_TRAVEL_MAP_PG_DSN={_GOOD_DSN}"])
    assert proc.returncode == 0, proc.stderr
    _no_secret(proc)
    assert env_file.read_text(encoding="utf-8") == (
        f"A=1\n{_KEY}={_GOOD_DSN}\nE2E_C7_MAP_API_SERVICE=api\n"
    )
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    # 임시 파일을 남기지 않는다.
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        ".d2-live.env",
        "bin",
        "inspect.json",
    ]


def test_plain_postgresql_scheme_is_accepted(tmp_path: Path) -> None:
    dsn = _GOOD_DSN.replace("postgresql+asyncpg://", "postgresql://")
    proc, env_file = _run(tmp_path, _OLD_LINE, [f"KOR_TRAVEL_MAP_PG_DSN={dsn}"])
    assert proc.returncode == 0, proc.stderr
    assert env_file.read_text(encoding="utf-8") == f"{_KEY}={dsn}\n"


@pytest.mark.parametrize(
    ("env_text", "container_dsn"),
    [
        # 사용자·DB·scheme이 대상 확인 키와 다르다.
        (_OLD_LINE, _GOOD_DSN.replace("ktm_feature_service", "kor_travel_map", 1)),
        (_OLD_LINE, _GOOD_DSN.replace("/kor_travel_map", "/kor_travel_map_dagster")),
        (_OLD_LINE, _GOOD_DSN.replace("postgresql+asyncpg://", "postgres://")),
        # 따옴표 없이 source할 수 없는 문자.
        (_OLD_LINE, _GOOD_DSN + "?sslmode=disable&x=1"),
        (_OLD_LINE, _GOOD_DSN.replace(_SECRET, _SECRET + "$HOME")),
        # 바꿀 줄이 정확히 하나가 아니다.
        ("A=1\n", _GOOD_DSN),
        (_OLD_LINE + _OLD_LINE, _GOOD_DSN),
        # 컨테이너에 DSN이 없다.
        (_OLD_LINE, None),
    ],
)
def test_refuses_and_leaves_the_file_untouched(
    tmp_path: Path, env_text: str, container_dsn: str | None
) -> None:
    container_env = ["X=1"] if container_dsn is None else [
        f"KOR_TRAVEL_MAP_PG_DSN={container_dsn}"
    ]
    proc, env_file = _run(tmp_path, env_text, container_env)
    assert proc.returncode != 0
    _no_secret(proc)
    assert env_file.read_text(encoding="utf-8") == env_text

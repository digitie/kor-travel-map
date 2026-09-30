"""`scripts/n150/repin.sh` 3단계 — D2 Dagster service 키를 Manager 토폴로지에서 유도한다.

PinVi가 공유 Dagster plane으로 옮겨 가며 `pinvi-dagster` service가 사라졌고(자리는 같은
image의 `pinvi-dagster-code-server`), 손으로 적은 `.d2-live.env`의 키 때문에 C7·D2 preflight가
없는 service에서 멈췄다. 스크립트의 python helper를 **그대로 떼어** 가짜 토폴로지 JSON과 임시
env 파일로 실행한다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "n150" / "repin.sh"

_ENV = (
    "A=1\n"
    "E2E_C7_MAP_API_SERVICE=kor-travel-map-api\n"
    "E2E_C7_DAGSTER_WEB_SERVICE=kor-travel-map-dagster\n"
    "E2E_C7_DAGSTER_DAEMON_SERVICE=kor-travel-map-dagster-daemon\n"
    "E2E_C7_PINVI_API_SERVICE=pinvi-api\n"
    "E2E_C7_PINVI_DAGSTER_SERVICE=pinvi-dagster\n"
    "Z=2\n"
)

_MAP_OWN = {
    "id": "map",
    "dagster": {"control_plane": "own"},
    "runtime_services": [
        "kor-travel-map-api",
        "kor-travel-map-ui",
        "kor-travel-map-dagster",
        "kor-travel-map-dagster-code-server",
        "kor-travel-map-dagster-daemon",
    ],
}
_MAP_SHARED = {
    "id": "map",
    "dagster": {"control_plane": "shared"},
    "runtime_services": [
        "kor-travel-map-api",
        "kor-travel-map-ui",
        "kor-travel-map-dagster-code-server",
    ],
}
_PINVI_SHARED = {
    "id": "pinvi",
    "dagster": {"control_plane": "shared"},
    "runtime_services": ["pinvi-api", "pinvi-web", "pinvi-dagster-code-server"],
}
_PLANE = {
    "id": "dagster",
    "dagster": None,
    "runtime_services": [
        "kor-travel-dagster-daemon",
        "kor-travel-dagster-webserver",
        "kor-travel-dagster-gateway",
    ],
}


def _helper() -> str:
    source = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r'^DAGSTER_KEYS_PROGRAM="\$\(cat <<\'PY\'\n(.*?)^PY\n\)"$',
        source,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "repin.sh에서 Dagster service helper를 찾지 못했다"
    # 토폴로지는 argv가 아니라 stdin으로 간다.
    assert (
        'printf \'%s\' "$TOPOLOGY" | python3 -I -c "$DAGSTER_KEYS_PROGRAM" "$ENV_FILE"' in source
    )
    return match.group(1)


def _environ(env_text: str) -> dict[str, str]:
    values = dict(line.split("=", 1) for line in env_text.splitlines() if "=" in line)
    return {"PATH": os.environ.get("PATH", ""), **values}


def _run(
    tmp_path: Path, topology: list[dict[str, Any]], env_text: str = _ENV
) -> tuple[subprocess.CompletedProcess[str], Path]:
    env_file = tmp_path / ".d2-live.env"
    env_file.write_text(env_text, encoding="utf-8")
    env_file.chmod(0o600)
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _helper(), str(env_file)],
        input=json.dumps(topology),
        env=_environ(env_text),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, env_file


def _keys(env_file: Path) -> dict[str, str]:
    text = env_file.read_text(encoding="utf-8")
    return dict(line.split("=", 1) for line in text.splitlines() if line.startswith("E2E_C7_"))


def test_pinvi_on_the_shared_plane_rewrites_the_retired_service(tmp_path: Path) -> None:
    """오늘(2026-10-01) n150 모양: Map은 전용 plane, PinVi는 공유 plane."""

    proc, env_file = _run(tmp_path, [_MAP_OWN, _PINVI_SHARED, _PLANE])

    assert proc.returncode == 0, proc.stderr
    keys = _keys(env_file)
    assert keys["E2E_C7_PINVI_DAGSTER_SERVICE"] == "pinvi-dagster-code-server"
    # 새 plane 키는 없으면 덧붙인다 — preflight는 own이면 web ≠ daemon을 요구한다.
    assert keys["E2E_C7_MAP_DAGSTER_CONTROL_PLANE"] == "own"
    # 전용 plane의 Map 키는 확인만 하고 그대로 둔다.
    assert keys["E2E_C7_DAGSTER_WEB_SERVICE"] == "kor-travel-map-dagster"
    assert keys["E2E_C7_DAGSTER_DAEMON_SERVICE"] == "kor-travel-map-dagster-daemon"
    # 다른 줄은 순서까지 그대로다.
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "A=1"
    assert lines[-2:] == ["Z=2", "E2E_C7_MAP_DAGSTER_CONTROL_PLANE=own"]
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"


def test_map_flip_points_web_and_daemon_at_the_map_code_server(tmp_path: Path) -> None:
    """Manager가 Map을 공유 plane으로 옮기면 두 키가 Map code-server를 함께 가리킨다."""

    proc, env_file = _run(tmp_path, [_MAP_SHARED, _PINVI_SHARED, _PLANE])

    assert proc.returncode == 0, proc.stderr
    keys = _keys(env_file)
    assert keys["E2E_C7_DAGSTER_WEB_SERVICE"] == "kor-travel-map-dagster-code-server"
    assert keys["E2E_C7_DAGSTER_DAEMON_SERVICE"] == "kor-travel-map-dagster-code-server"
    assert keys["E2E_C7_PINVI_DAGSTER_SERVICE"] == "pinvi-dagster-code-server"
    assert keys["E2E_C7_MAP_DAGSTER_CONTROL_PLANE"] == "shared"


def test_existing_plane_line_is_replaced_in_place(tmp_path: Path) -> None:
    before = _ENV + "E2E_C7_MAP_DAGSTER_CONTROL_PLANE=own\nTAIL=1\n"
    proc, env_file = _run(tmp_path, [_MAP_SHARED, _PINVI_SHARED], before)

    assert proc.returncode == 0, proc.stderr
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines[-2:] == ["E2E_C7_MAP_DAGSTER_CONTROL_PLANE=shared", "TAIL=1"]


def test_is_idempotent(tmp_path: Path) -> None:
    proc, env_file = _run(tmp_path, [_MAP_SHARED, _PINVI_SHARED, _PLANE])
    assert proc.returncode == 0, proc.stderr
    first = env_file.read_text(encoding="utf-8")
    again, _ = _run(tmp_path, [_MAP_SHARED, _PINVI_SHARED], first)
    assert again.returncode == 0, again.stderr
    assert env_file.read_text(encoding="utf-8") == first


def _without(target: dict[str, Any], service: str) -> dict[str, Any]:
    return {**target, "runtime_services": [s for s in target["runtime_services"] if s != service]}


@pytest.mark.parametrize(
    ("topology", "env_text", "reason"),
    [
        # 전용 plane에서 적힌 값이 그 target의 Dagster runtime service가 아니다.
        (
            [_MAP_OWN, _PINVI_SHARED],
            _ENV.replace("=kor-travel-map-dagster-daemon", "=kor-travel-map-dagster-old"),
            "전용 plane target map",
        ),
        # 전용 plane인데 web·daemon이 같은 service를 가리킨다.
        (
            [_MAP_OWN, _PINVI_SHARED],
            _ENV.replace("=kor-travel-map-dagster-daemon", "=kor-travel-map-dagster"),
            "전용 plane target map",
        ),
        # 공유 plane인데 Dagster service가 둘이다(모호).
        (
            [
                _MAP_OWN,
                {
                    **_PINVI_SHARED,
                    "runtime_services": [*_PINVI_SHARED["runtime_services"], "pinvi-dagster"],
                },
            ],
            _ENV,
            "하나가 아니다",
        ),
        # 공유 plane인데 Dagster service가 없다.
        ([_MAP_OWN, _without(_PINVI_SHARED, "pinvi-dagster-code-server")], _ENV, "하나가 아니다"),
        # API service를 가진 target이 없다.
        ([_MAP_OWN], _ENV, "E2E_C7_PINVI_API_SERVICE"),
        # control_plane을 모른다.
        ([_MAP_OWN, {**_PINVI_SHARED, "dagster": {"control_plane": "hybrid"}}], _ENV, "모른다"),
        ([_MAP_OWN, {**_PINVI_SHARED, "dagster": None}], _ENV, "모른다"),
        # 유도 값이 compose service 이름 문법 밖이다(파일은 따옴표 없이 source된다).
        (
            [
                _MAP_OWN,
                {**_PINVI_SHARED, "runtime_services": ["pinvi-api", "pinvi-dagster;$(id)"]},
            ],
            _ENV,
            "compose service 이름이 아니다",
        ),
        (
            [_MAP_OWN, {**_PINVI_SHARED, "runtime_services": ["pinvi-api", "Pinvi-Dagster"]}],
            _ENV,
            "compose service 이름이 아니다",
        ),
        # plane 줄이 여러 개다.
        (
            [_MAP_OWN, _PINVI_SHARED],
            _ENV + "E2E_C7_MAP_DAGSTER_CONTROL_PLANE=own\n" * 2,
            "여러 개다",
        ),
        # 쓸 키 줄이 없다.
        (
            [_MAP_OWN, _PINVI_SHARED],
            _ENV.replace("E2E_C7_PINVI_DAGSTER_SERVICE=pinvi-dagster\n", ""),
            "E2E_C7_PINVI_DAGSTER_SERVICE 줄",
        ),
    ],
)
def test_refuses_and_leaves_the_file_untouched(
    tmp_path: Path, topology: list[dict[str, Any]], env_text: str, reason: str
) -> None:
    proc, env_file = _run(tmp_path, topology, env_text)

    assert proc.returncode != 0
    assert reason in proc.stderr, proc.stderr
    assert env_file.read_text(encoding="utf-8") == env_text
    assert sorted(path.name for path in tmp_path.iterdir()) == [".d2-live.env"]


def test_verification_does_not_let_inherited_values_mask_the_file() -> None:
    """source 대조 전에 물려받은 키를 지운다 — 파일이 키를 못 세워도 옛 값이 가리지 않는다."""

    helper = _helper()
    assert "unset {' '.join(derived)}; set -a;" in helper


def test_repin_reads_the_installed_topology_not_a_literal() -> None:
    source = _SCRIPT.read_text(encoding="utf-8")
    assert '"$KTDCTL" targets list --json 2>/dev/null' in source
    # 옛 service 이름을 스크립트에 적지 않는다.
    assert "pinvi-dagster-code-server" not in source
    assert "kor-travel-map-dagster" not in source

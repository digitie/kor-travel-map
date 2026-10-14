"""`scripts/n150/repin.sh` 5단계 — D2 fixture의 Alembic head 확인 키를 Map API 이미지에서 유도한다.

`E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_ALEMBIC_REVISION`은 종전에 `/root/.d2-live.env`에서 손으로
고치는 값이었다. #1319가 head를 `406_feature_write_gate`로 올렸는데 키는 `404_…`에 남아
2026-10-14 D2가 `fixture target Alembic revision confirmation mismatch`로 멈췄다. 이제 repin이
매 주기 실행 중인 API 이미지의 `ktm-application-schema head`로 그 줄을 다시 쓴다.

스크립트의 python 프로그램을 **그대로 떼어** 임시 env 파일에 실행하고, 입력은 생산자
(`docker/application-schema-head.py`)를 이 저장소의 migration graph 위에서 실제로 돌린 출력이다.
그래서 migration이 하나 늘면 기대값도 함께 움직인다 — 리터럴 head는 이 파일 어디에도 없다.
"""

from __future__ import annotations

import importlib.util
import json
import re
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from kortravelmap.infra.application_schema_head import application_schema_head

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "n150" / "repin.sh"
_PRODUCER = _ROOT / "docker" / "application-schema-head.py"
_DOCKERFILE = _ROOT / "docker" / "api.Dockerfile"
_KEY = "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_ALEMBIC_REVISION"
#: 2026-10-14 n150에 남아 있던 손으로 적은 값 — 드리프트의 모양을 그대로 재현한다.
_STALE_LINE = f"{_KEY}=404_transport_provider_identity\n"


def _program() -> str:
    source = _SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"^FIXTURE_HEAD_PROGRAM=\"\$\(cat <<'PY'\n(.*?)^PY$",
        source,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "repin.sh에서 fixture Alembic head 프로그램을 찾지 못했다"
    return match.group(1)


def _producer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("repin_test_application_schema_head", _PRODUCER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _image_output(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> str:
    """API 이미지의 `ktm-application-schema head`가 이 트리에서 낼 stdout."""

    producer = _producer()
    src = str(_ROOT / "src")
    monkeypatch.setattr(producer.sysconfig, "get_paths", lambda: {"purelib": src, "platlib": src})
    capsys.readouterr()
    assert producer.main(["head"]) == 0
    return capsys.readouterr().out


def _run(
    tmp_path: Path, env_text: str, stdin: str
) -> tuple[subprocess.CompletedProcess[str], Path]:
    env_file = tmp_path / ".d2-live.env"
    env_file.write_text(env_text, encoding="utf-8")
    env_file.chmod(0o600)
    proc = subprocess.run(
        [sys.executable, "-I", "-c", _program(), str(env_file)],
        input=stdin,
        # 셸이 `set -a; .`로 옛 값을 물려준 상황을 재현한다 — 대조가 그것에 가려지면 안 된다.
        env={"PATH": "/usr/bin:/bin", _KEY: "404_transport_provider_identity"},
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, env_file


def test_stale_hand_written_head_is_replaced_by_the_image_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    head = application_schema_head()
    assert f"{_KEY}={head}\n" != _STALE_LINE, "이 저장소 head가 옛 값과 같다 — 재현이 무의미하다"
    before = f"A=1\n{_STALE_LINE}E2E_C7_MAP_API_SERVICE=api\n"
    proc, env_file = _run(tmp_path, before, _image_output(monkeypatch, capsys))
    assert proc.returncode == 0, proc.stderr
    assert env_file.read_text(encoding="utf-8") == (
        f"A=1\n{_KEY}={head}\nE2E_C7_MAP_API_SERVICE=api\n"
    )
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert sorted(path.name for path in tmp_path.iterdir()) == [".d2-live.env"]


def test_rerun_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    line = f"{_KEY}={application_schema_head()}\n"
    proc, env_file = _run(tmp_path, line, _image_output(monkeypatch, capsys))
    assert proc.returncode == 0, proc.stderr
    assert env_file.read_text(encoding="utf-8") == line


@pytest.mark.parametrize(
    ("env_text", "stdin"),
    [
        (_STALE_LINE, "not json"),
        (_STALE_LINE, ""),
        (
            _STALE_LINE,
            json.dumps(
                {
                    "schema": "kor-travel-map.application-head-error.v1",
                    "code": "application_graph_invalid",
                }
            ),
        ),
        (_STALE_LINE, json.dumps({"schema": "other.v1", "head": "406_feature_write_gate"})),
        (_STALE_LINE, json.dumps(["kor-travel-map.application-head.v1"])),
        # source하면 값이 바뀌거나 명령이 되는 head.
        (
            _STALE_LINE,
            json.dumps({"schema": "kor-travel-map.application-head.v1", "head": "406 x"}),
        ),
        (
            _STALE_LINE,
            json.dumps({"schema": "kor-travel-map.application-head.v1", "head": "$(id)"}),
        ),
        (_STALE_LINE, json.dumps({"schema": "kor-travel-map.application-head.v1", "head": ""})),
        (_STALE_LINE, json.dumps({"schema": "kor-travel-map.application-head.v1", "head": None})),
        # 바꿀 줄이 정확히 하나가 아니다.
        (
            "A=1\n",
            json.dumps(
                {"schema": "kor-travel-map.application-head.v1", "head": "406_feature_write_gate"}
            ),
        ),
        (
            _STALE_LINE + _STALE_LINE,
            json.dumps(
                {"schema": "kor-travel-map.application-head.v1", "head": "406_feature_write_gate"}
            ),
        ),
    ],
)
def test_refuses_and_leaves_the_file_untouched(tmp_path: Path, env_text: str, stdin: str) -> None:
    proc, env_file = _run(tmp_path, env_text, stdin)
    assert proc.returncode != 0
    assert env_file.read_text(encoding="utf-8") == env_text
    assert sorted(path.name for path in tmp_path.iterdir()) == [".d2-live.env"]


def test_program_reads_the_producer_the_api_image_installs() -> None:
    """5단계가 부르는 경로·기대 schema가 생산자와 그 이미지 설치 자리와 같다."""

    source = _SCRIPT.read_text(encoding="utf-8")
    call = re.search(r'docker exec "\$API" (?P<path>\S+) head\)', source)
    assert call is not None, "5단계가 4단계의 $API에서 head를 읽지 않는다"
    installed = re.search(
        r"^COPY\b.*\bdocker/application-schema-head\.py\s+(?P<dst>\S+)$",
        _DOCKERFILE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert installed is not None
    assert call.group("path") == installed.group("dst")
    assert f'HEAD_SCHEMA = "{_producer()._HEAD_SCHEMA}"' in _program()
    # `$API`는 4단계가 compose 조회로 대입한 값이다 — 그보다 앞에서 읽으면 빈 target이다.
    assert source.index('API="$(docker compose') < call.start()

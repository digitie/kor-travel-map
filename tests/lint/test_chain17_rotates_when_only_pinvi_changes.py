"""`chain17.sh` B 단계는 핀 원장을 **pair**로 본다 — map이 같아도 pinvi가 다르면 회전한다.

2026-10-13 09:11Z chain t1013e: B 단계가 `원장 map == MAP`만 보고 "이미 회전됨 — 건너뛴다"를
택해, `PINVI_OVERRIDE`로 준 새 PinVi가 회전되지 않고 원장의 옛 PinVi로 재구축·C6c 스모크가
돌아 같은 실패가 1분 만에 재현됐다. registry는 같은 Map·다른 PinVi 회전을 허용하고, 같은
pair(둘 다 같음)만 거부한다 — 건너뛰어도 되는 조건은 정확히 그 하나다.

이름이 아니라 효과를 결박한다: 스크립트의 B 단계 본문을 잘라 가짜 `ktdctl`(원장 파일을 읽는다)·
가짜 `rotate-pinned-pair`(호출을 기록하고 원장을 바꾼다) 위에서 실제로 실행한다. 조건식을 어떻게
쓰든 "map 같고 pinvi 다르면 rotate 호출, 둘 다 같으면 skip"이 깨지면 빨갛다. 회전 뒤 검증도
pair다 — rotate가 pinvi를 바꾸지 못하면 멈춰야 한다. 원장을 못 읽은 빈 값은 "다른 pair"가
아니다 — 회전을 시도하지 않고 그 사유로 멈춘다.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_CHAIN17 = _ROOT / "scripts" / "n150" / "chain17.sh"

MAP = "c4d17343" + "0" * 32
PINVI = "2fa1c166" + "0" * 32
OLD_MAP = "a" * 40
OLD_PINVI = "97f2baf2" + "0" * 32
REASON = "pair rotation under test"

_KTDCTL_STUB = """#!/bin/bash
# `ktdctl pin show`만 흉내 낸다. 원장은 $LEDGER_FILE("map <sha>" / "pinvi <sha>" 한 줄씩).
[ "$1 $2" = "pin show" ] || { echo "unexpected: $*" >&2; exit 2; }
cat "$LEDGER_FILE"
"""

_ROTATE_STUB = """#!/bin/bash
# 호출 인자를 한 줄씩 기록하고, 성공한 회전처럼 원장을 새 pair로 바꾼다
# (ROTATE_STUB_UPDATES=0이면 원장을 건드리지 않는 "거짓 성공"이다).
printf '%s\\n' "$@" >> "$CALLS_FILE"
if [ "${ROTATE_STUB_UPDATES:-1}" = 1 ]; then
  printf 'map %s\\npinvi %s\\n' "$1" "$2" > "$LEDGER_FILE"
fi
echo "history 2 entries"
echo "  $1 $2"
"""


def _stage_b(source: str) -> str:
    start = source.index('say "B. 회전"')
    end = source.index('say "C. rebuild')
    return source[start:end]


def _helpers(source: str) -> str:
    """스크립트 자신의 `die`·`say`·`pin` 정의를 그대로 쓴다 — 테스트가 대체본을 들고 있으면
    helper가 바뀌어도 여기서는 초록이다."""

    lines = re.findall(r"^(?:die|say|pin)\(\) \{.*$", source, re.MULTILINE)
    assert len(lines) == 3, lines
    return "\n".join(lines)


def _run_stage_b(
    tmp_path: Path, ledger_map: str, ledger_pinvi: str, *, rotate_updates: bool = True
) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    source = _CHAIN17.read_text(encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ktdctl = bin_dir / "ktdctl"
    rotate = bin_dir / "rotate-pinned-pair"
    for stub, body in ((ktdctl, _KTDCTL_STUB), (rotate, _ROTATE_STUB)):
        stub.write_text(body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    ledger = tmp_path / "ledger"
    ledger.write_text(f"map {ledger_map}\npinvi {ledger_pinvi}\n", encoding="utf-8", newline="\n")
    calls = tmp_path / "calls"

    script = "\n".join(
        [
            "set -uo pipefail",
            f"MAP={MAP}",
            f"PINVI={PINVI}",
            f'REASON="{REASON}"',
            f"KTDCTL={ktdctl.as_posix()}",
            f"ROTATE={rotate.as_posix()}",
            _helpers(source),
            _stage_b(source),
            "echo STAGE-B-DONE",
            "",
        ]
    )
    env = {
        **os.environ,
        "LEDGER_FILE": ledger.as_posix(),
        "CALLS_FILE": calls.as_posix(),
        "ROTATE_STUB_UPDATES": "1" if rotate_updates else "0",
    }
    completed = subprocess.run(
        ["bash", "-c", script], env=env, capture_output=True, text=True, check=False
    )
    recorded: list[list[str]] = []
    if calls.exists():
        lines = calls.read_text(encoding="utf-8").splitlines()
        recorded = [lines[i : i + 3] for i in range(0, len(lines), 3)]
    return completed, recorded


def test_the_stage_is_found_and_calls_the_launcher_through_the_variable() -> None:
    """추출이 실제 본문을 집었는지부터 본다 — 비면 아래 실행 단언이 공허하다."""

    source = _CHAIN17.read_text(encoding="utf-8")
    stage = _stage_b(source)
    assert '"$ROTATE" "$MAP" "$PINVI" "$REASON"' in stage
    assert "/opt/" not in stage, "B 단계가 launcher 경로를 직접 들고 있으면 stub으로 바꿀 수 없다"


def test_same_pair_is_skipped(tmp_path: Path) -> None:
    completed, calls = _run_stage_b(tmp_path, MAP, PINVI)
    assert completed.returncode == 0, completed.stderr
    assert calls == []
    assert "건너뛴다" in completed.stdout
    assert "STAGE-B-DONE" in completed.stdout


@pytest.mark.parametrize(
    ("ledger_map", "ledger_pinvi"),
    [
        pytest.param(MAP, OLD_PINVI, id="same-map-new-pinvi"),
        pytest.param(OLD_MAP, PINVI, id="new-map-same-pinvi"),
        pytest.param(OLD_MAP, OLD_PINVI, id="new-pair"),
    ],
)
def test_any_difference_from_the_ledger_rotates(
    tmp_path: Path, ledger_map: str, ledger_pinvi: str
) -> None:
    completed, calls = _run_stage_b(tmp_path, ledger_map, ledger_pinvi)
    assert completed.returncode == 0, completed.stderr
    assert calls == [[MAP, PINVI, REASON]]
    assert "건너뛴다" not in completed.stdout
    assert "STAGE-B-DONE" in completed.stdout


@pytest.mark.parametrize(
    ("ledger_map", "ledger_pinvi"),
    [
        pytest.param("", "", id="ledger-empty"),
        pytest.param(MAP, "", id="ledger-pinvi-missing"),
    ],
)
def test_unreadable_ledger_stops_before_any_rotation(
    tmp_path: Path, ledger_map: str, ledger_pinvi: str
) -> None:
    """`ktdctl pin show`가 map·pinvi를 내지 못하면 빈 문자열이 "다른 pair"로 읽혀 회전이 시도되고
    실패 사유가 '회전 실패'로 가려진다 — 비교 전에 원장 읽기 실패로 멈춰야 한다."""

    completed, calls = _run_stage_b(tmp_path, ledger_map, ledger_pinvi)
    assert calls == []
    assert completed.returncode == 1
    assert "핀 원장" in completed.stderr
    assert "STAGE-B-DONE" not in completed.stdout


def test_rotation_that_leaves_the_old_pinvi_in_the_ledger_stops_the_chain(tmp_path: Path) -> None:
    """회전 뒤 검증도 pair다. launcher가 0으로 끝났는데 원장 pinvi가 그대로면 C로 가지 않는다 —
    map만 보면 여기서도 옛 PinVi로 재구축한다."""

    completed, calls = _run_stage_b(tmp_path, MAP, OLD_PINVI, rotate_updates=False)
    assert calls == [[MAP, PINVI, REASON]]
    assert completed.returncode == 1
    assert "원장 pinvi" in completed.stderr
    assert "STAGE-B-DONE" not in completed.stdout

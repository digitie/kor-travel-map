"""n150 재핀 사이클 스크립트(`scripts/n150/*.sh`)가 퇴역한 attestation 체인을 되살리지 않는다.

ADR-102 결정 6이 C7 attestation 체인 — Manager v6 manifest·v8 journal의 `/etc` 사본,
root 소유 러너 스냅샷(`/usr/local/lib/kor-travel-map/...`), `gen_attest.py`의 host
attestation — 을 걷어내고, `/root`에만 있던 스크립트를 저장소로 옮겼다. 호스트 사본은
저장소에서 복사되므로, 여기서 막으면 호스트로도 되돌아가지 않는다.

같은 파일이 두 가지를 더 고정한다. D2는 D1과 **같은 체크아웃**에서 돌고, 회전 전
pair 계약 preflight는 여전히 hard gate다.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_N150 = _ROOT / "scripts" / "n150"
_FORBIDDEN = (
    "pinned-runtime-rebuild-v8",
    "pinned-runtime-generation-v6",
    "gen_attest",
    "/usr/local/lib/kor-travel-map",
    "/etc/kor-travel-map",
    "c7-prod-live-e2e-attestation",
    "verify_trusted_runtime_attestation",
    "c7_prod_attestation",
    "source-manifest.json",
)


def _scripts() -> list[Path]:
    return sorted(_N150.glob("*.sh"))


def _read(name: str) -> str:
    return (_N150 / name).read_text(encoding="utf-8")


def test_the_gate_sees_the_host_scripts() -> None:
    """유도가 실제로 파일을 찾았는지부터 본다 — 비면 아래 단언이 공허하다."""

    names = {path.name for path in _scripts()}
    assert {"adjudicate.sh", "chain16.sh", "chain17.sh", "repin.sh", "run-d2.sh"} <= names, names


@pytest.mark.parametrize("script", _scripts(), ids=lambda path: path.name)
def test_host_script_never_references_the_retired_chain(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    found = [marker for marker in _FORBIDDEN if marker in source]
    assert found == [], (
        f"{script.name}이 ADR-102 결정 6이 걷어낸 체인을 다시 참조한다: {found}. "
        "D1·D2는 핀된 SHA의 평범한 체크아웃에서 돈다."
    )


@pytest.mark.parametrize("script", _scripts(), ids=lambda path: path.name)
def test_host_script_is_valid_bash(script: Path) -> None:
    completed = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_chain17_keeps_pair_preflight_as_a_hard_gate_before_rotation() -> None:
    source = _read("chain17.sh")
    preflight = source.index('--rotation-preflight "$MAP" "$PINVI"')
    refusal = source.index('|| die "rotation preflight 거부"', preflight)
    rotation = source.index("/opt/kor-travel-docker-manager/scripts/rotate-pinned-pair")
    rebuild = source.index("/opt/kor-travel-docker-manager/scripts/run-pinned-rebuild-once")
    assert preflight < refusal < rotation < rebuild
    assert '/root/chain16.sh "$MAP" "$PINVI"' in source


def _assignment(source: str, name: str) -> str:
    match = re.search(rf'^{name}="?([^"\n]+)"?$', source, re.MULTILINE)
    assert match is not None, name
    return match.group(1)


def test_d2_runs_from_the_same_plain_checkout_as_d1() -> None:
    chain16 = _read("chain16.sh")
    run_d2 = _read("run-d2.sh")

    # D1이 푸는 체크아웃과 D2가 돌리는 체크아웃이 같은 경로다.
    assert _assignment(chain16, "NEW") == _assignment(run_d2, "SRC") == (
        "/home/digitie/ktm-c7-$MAP"
    )
    assert 'archive --format=tar "$MAP" | tar -xf - -C "$NEW"' in chain16
    assert '/root/run-d2.sh "$MAP"' in chain16
    assert 'RUNNER="$SRC/scripts/run-admin-feature-live-acceptance.sh"' in run_d2
    # run-d2.sh 본문을 sed로 고쳐 쓰던 스냅샷 경로 치환은 사라졌다.
    assert re.search(r"sed -i[^\n]*run-d2", chain16) is None


def test_repin_updates_only_the_two_non_secret_env_keys() -> None:
    source = _read("repin.sh")
    replaced = set(re.findall(r'-e "s\|\^(E2E_[A-Z0-9_]+)=', source))
    assert replaced == {"E2E_C7_EXPECTED_GIT_COMMIT", "E2E_C7_PLAYWRIGHT_IMAGE"}
    # 퇴역한 두 키는 지운다 — 러너가 더 읽지 않으므로 남겨 두면 거짓 입력이 된다.
    assert "'/^E2E_C7_(PINNED_RUNTIME_MANIFEST|REBUILD_JOURNAL)=/d'" in source
    assert "ktdctl" in source
    assert "pinned-runtime-generation" not in source


def test_adjudicate_clears_with_the_helper_of_the_plain_checkout() -> None:
    """BLOCKED 판정도 D1·D2와 같은 체크아웃의 helper를 쓴다 — 종전 호스트 사본은 root 소유
    스냅샷 경로와 attestation·manifest·journal digest를 읽어 M2 뒤에는 늘 실패했다."""

    source = _read("adjudicate.sh")
    checkout = (
        'SRC="/home/digitie/ktm-c7-${E2E_C7_EXPECTED_GIT_COMMIT:?E2E_C7_EXPECTED_GIT_COMMIT}"'
    )
    assert checkout in source
    for retired in ("E2E_C7_PINNED_RUNTIME_MANIFEST", "E2E_C7_REBUILD_JOURNAL", "host_attestation"):
        assert retired not in source


def test_adjudicate_only_clears_a_lane_that_is_really_stopped() -> None:
    """순서가 곧 안전이다: lock → ACTIVE 없음 → run 컨테이너 없음 → 잔여물 실측 → 증거 →
    clear-blocked. 러너와 같은 lock을 잡지 않으면 도는 run의 BLOCKED를 지울 수 있고,
    ACTIVE를 보지 않으면 종결되지 않은 작업의 앵커를 지운다."""

    source = _read("adjudicate.sh")
    order = [
        'flock -n 9 ||',
        'if [[ -e "$R/ACTIVE.json" || -L "$R/ACTIVE.json" ]]; then',
        "docker ps -aq --filter label=io.kortravelmap.admin-feature-acceptance.run-key",
        "python3 - \"$RECORD\"",
        'install -d -o root -g root -m 0700 "$ARCH"',
        'python3 -I -B "$HELPER" clear-blocked --path "$B"',
    ]
    positions = [source.index(marker) for marker in order]
    assert positions == sorted(positions), positions
    assert 'exec 9>"$R/orchestrator.lock"' in source
    assert "if len(residue) != 4:" in source
    assert "if any(residue.values()):" in source


def test_chain16_stops_before_d2_when_the_lane_is_not_clean() -> None:
    source = _read("chain16.sh")
    step = source[source.index('say "G. lane 정리"') : source.index('say "H. D2')]
    adjudicate = step.index("/root/adjudicate.sh")
    survives = step.index('[ -e "$R/BLOCKED.json" ] && die')
    active = step.index('[ -e "$R/ACTIVE.json" ] && die')
    # 판정 **뒤에** 남은 BLOCKED를 본다(앞에 두면 BLOCKED가 있는 모든 사이클이 죽는다).
    assert adjudicate < survives < active

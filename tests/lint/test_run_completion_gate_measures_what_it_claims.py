"""run 완주 게이트가 **재겠다고 말한 것을 실제로 들고 있는지** 결박한다.

이 게이트는 prod metadata DB와 GraphQL endpoint가 있어야 돌므로 CI에서 실행할 수
없다. 그렇다고 검사 밖에 두면, 술어가 하나씩 빠져도 아무도 모른 채 "배포 사후점검이
run 완주를 본다"는 주장만 남는다 — 이 저장소가 반복한 실패 모양이다.

그래서 **재는 대상의 이름**을 정적으로 확인한다. 약한 검사인 것을 안다: 이름이
있어도 술어가 틀릴 수 있다. 그 약점은 실측이 메운다 — 게이트 자체를 prod에서 돌려
2026-09-11 사고 config로 되돌렸을 때 red가 되는 것을 확인했고(`live-config` 두 축),
그 기록은 acceptance §T-VN-DAGSTER-STORAGE에 있다. 여기서 잡는 것은 **그 술어가
조용히 사라지는 것**이다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_GATE = _ROOT / "scripts" / "dagster_run_completion_gate.py"

#: 게이트가 반드시 재야 하는 축. 각각이 2026-09-11 사고의 한 겹이거나, 형제
#: 저장소가 18시간 멈춘 기제의 한 겹이다.
_REQUIRED_CHECKS = {
    # 사고 당시 config — 로컬 쓰기 두 축이 봉인된 DAGSTER_HOME으로 갔다.
    "live-config/local_artifact_storage",
    "live-config/compute_logs",
    # weather의 두 번째 겹 — storage가 SQLite로 떨어지면 종결 이벤트를 잃는다.
    "live-config/storage-is-postgres",
    "live-config/no-autocreate",
    # 회수 기제가 켜져 있고 이유를 묻지 않는 상한을 갖는다.
    "live-config/run-monitoring",
    "live-config/run-timeout-bounded",
    # 큐 상한이 버전 기본값이 아니라 이 파일에서 온다.
    "live-config/queue-cap-declared",
    # 능동 탐침 — 쌓인 성공 이력이 통과를 사 주지 못한다.
    "probe/reaches-success",
    # 멈춘 run이 슬롯을 붙잡고 있지 않다.
    "stuck/in-progress-past-bound",
    # 회수 기제를 담은 프로세스가 살아 있다.
    "daemon/heartbeats-fresh",
    # 빈 세계에서 초록이 되지 않는다.
    "floor/runs-observed",
    "floor/heartbeat-types",
}


def _string_literals() -> set[str]:
    tree = ast.parse(_GATE.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_the_gate_source_parses() -> None:
    """유도의 전제. 파싱되지 않으면 아래 단언이 무엇도 재지 못한다."""
    assert _GATE.is_file(), f"{_GATE}가 없다"
    literals = _string_literals()
    assert literals, "게이트에서 문자열 리터럴을 하나도 찾지 못했다 — 파서가 낡았다"


@pytest.mark.parametrize("check_name", sorted(_REQUIRED_CHECKS))
def test_the_gate_still_measures(check_name: str) -> None:
    """각 축이 게이트에 남아 있다."""
    assert check_name in _string_literals(), (
        f"게이트가 `{check_name}`을 더 이상 재지 않는다. 이 축은 2026-09-11 사고나 "
        "형제 저장소의 18시간 정지 중 한 겹이다 — 지우려면 그 겹이 왜 사라졌는지 "
        "acceptance에 먼저 적어라."
    )


def test_the_gate_reads_the_live_config_not_the_repo_copy() -> None:
    """배포된 것을 봐야 한다 — 저장소의 파일은 배포된 것이 아니다.

    2026-09-13에 같은 착각으로 `docker-compose.yml`을 Map 저장소에서 고치고
    "prod의 공백을 메웠다"고 적었다가 적대 리뷰에 잡혔다. prod가 읽는 것은 다른
    파일이었다. 이 게이트는 그 실수를 구조적으로 못 하게 한다 — 컨테이너 안의
    `$DAGSTER_HOME/dagster.yaml`을 읽는다.
    """
    source = _GATE.read_text(encoding="utf-8")
    assert "DAGSTER_HOME" in source
    assert 'posixpath.join(dagster_home, "dagster.yaml")' in source, (
        "게이트가 live config 경로를 `$DAGSTER_HOME`에서 유도하지 않는다 — "
        "저장소 사본을 읽으면 배포된 것이 아니라 적어 둔 것을 재게 된다."
    )


def test_the_probe_job_has_no_upstream_side_effects() -> None:
    """탐침은 부작용이 없어야 한다 — 게이트가 관측을 바꾸면 안 된다.

    기본 탐침은 DB projection 전용 job이다. provider 적재 job을 탐침으로 쓰면
    게이트를 돌릴 때마다 upstream 쿼터를 쓰고 Feature를 만든다.
    """
    source = _GATE.read_text(encoding="utf-8")
    assert '_DEFAULT_PROBE_JOB = "current_weather_summary_refresh"' in source, (
        "기본 탐침 job이 바뀌었다 — 부작용이 없는지 확인하고 이 검사를 갱신해라."
    )

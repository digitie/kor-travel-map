"""n150 호스트 스크립트는 Map DB instance를 이름·port·superuser로 적지 않는다 (ADR-103).

prod의 Map DB는 전용 instance(`kor-travel-map-postgres`, port 12700)에서 Manager 공용
instance로 옮긴다. 스크립트가 그 셋을 적어 두면 이전 뒤에는 옛 instance를 향하거나(아직
떠 있을 때) 조용히 실패한다. DB 접근은 실행 중인 Map API 컨테이너에서 유도한다 —
`adjudicate.sh`는 그 컨테이너 안에서 세고, `repin.sh`는 그 DSN에서 D2 fixture DSN을 만든다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "n150"

#: 저장소가 정본인 다섯 스크립트(`scripts/n150/README.md`). 목록은 glob으로 찾고, 이 집합은
#: 검사가 **무엇을 봤는지**의 하한이다 — glob이 비면 검사는 아무것도 증명하지 못한다.
_EXPECTED = {"adjudicate.sh", "chain16.sh", "chain17.sh", "repin.sh", "run-d2.sh"}

_FORBIDDEN = {
    "port 12700": re.compile(r"(?<![0-9])12700(?![0-9])"),
    "container kor-travel-map-postgres": re.compile(r"kor-travel-map-postgres"),
    # `-U kor_travel_map`과 argv 목록 모양(`"-U", "kor_travel_map"`)을 함께 잡는다.
    "superuser -U kor_travel_map": re.compile(r"-U[\"',\s]+kor_travel_map(?![A-Za-z0-9_])"),
}


def _scripts() -> list[Path]:
    return sorted(_SCRIPTS.glob("*.sh"))


def test_the_scan_sees_every_canonical_script() -> None:
    assert {path.name for path in _scripts()} >= _EXPECTED


@pytest.mark.parametrize("path", _scripts(), ids=lambda path: path.name)
def test_script_has_no_map_instance_literal(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    hits = [
        f"{label} (line {source.count(chr(10), 0, match.start()) + 1})"
        for label, pattern in _FORBIDDEN.items()
        for match in pattern.finditer(source)
    ]
    assert hits == [], f"{path.name}: {hits}"


@pytest.mark.parametrize(
    "line",
    [
        "docker exec -i kor-travel-map-postgres psql",
        "psql -h 127.0.0.1 -p 12700",
        "psql -U kor_travel_map -d x",
        '["psql", "-U", "kor_travel_map", "-p"]',
    ],
)
def test_the_detector_catches_each_forbidden_shape(line: str) -> None:
    """검사기가 빨갛게 될 수 있음을 스스로 보인다(항진명제 방지)."""

    assert any(pattern.search(line) for pattern in _FORBIDDEN.values())


@pytest.mark.parametrize(
    "line",
    [
        "psql -U kor_travel_map_dagster",
        "lat 127000000",
        "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE=kor_travel_map",
    ],
)
def test_the_detector_does_not_flag_neighbouring_names(line: str) -> None:
    assert not any(pattern.search(line) for pattern in _FORBIDDEN.values())

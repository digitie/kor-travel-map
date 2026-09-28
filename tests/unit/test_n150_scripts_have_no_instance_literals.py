"""n150 호스트 스크립트는 Map DB instance에 직접 닿지 않는다 (ADR-103).

prod의 Map DB는 전용 instance(`kor-travel-map-postgres`, port 12700)에서 Manager 공용
instance로 옮긴다. 스크립트가 instance의 이름·port·superuser를 적어 두면 이전 뒤에는 옛
instance를 향하거나(아직 떠 있을 때) 조용히 실패한다. 새 instance의 이름을 적으면 같은
결박이 되살아나고, 이번에는 모든 tenant의 cluster superuser다. DB 접근은 실행 중인 Map API
컨테이너에서 유도한다 — `adjudicate.sh`는 그 컨테이너 안에서 세고, `repin.sh`는 그 DSN에서
D2 fixture DSN을 만든다.

그래서 이름이 아니라 **효과**를 본다: PostgreSQL client를 부르지 않고, DSN authority나 port
flag를 적지 않고, `docker exec`는 유도한 API 컨테이너에만 한다. 옛 instance의 이름 셋은
그 위에 그대로 막아 둔다.
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

#: `docker exec`가 들어가도 되는 대상 — 스크립트가 Map API service에서 유도한 컨테이너 변수.
_DERIVED_API_TARGETS = {"api", "$api", "${api}", "$API", "${API}"}

_DOCKER_EXEC = re.compile(
    # 셸(`docker exec -i "$api"`)과 argv 목록(`"docker", "exec", "-i", api`) 두 모양.
    r"docker[\"',\s]+exec(?![\w-])(?P<flags>(?:[\"',\s]+-{1,2}[A-Za-z][\w-]*)*)"
    r"[\"',\s]+(?P<target>[^\s\"',]+)"
)

_FORBIDDEN = {
    # 효과: 스크립트가 PostgreSQL에 직접 붙는다.
    "PostgreSQL client": re.compile(
        r"(?<![\w-])(psql|pg_dump|pg_dumpall|pg_restore|pg_isready|createdb|dropdb)(?![\w-])"
    ),
    "DSN authority host:port/": re.compile(r"[A-Za-z0-9._\]-]+:[0-9]{2,5}/"),
    "port flag": re.compile(r"(?<![\w-])(-p|--port)[\s\"',=]*[0-9]"),
    # 옛 instance의 이름 셋(ADR-103 이전 값).
    "port 12700": re.compile(r"(?<![0-9])12700(?![0-9])"),
    "container kor-travel-map-postgres": re.compile(r"kor-travel-map-postgres"),
    # `-U kor_travel_map`과 argv 목록 모양(`"-U", "kor_travel_map"`)을 함께 잡는다.
    "superuser -U kor_travel_map": re.compile(r"-U[\"',\s]+kor_travel_map(?![A-Za-z0-9_])"),
}


def _hits(source: str) -> list[tuple[str, int]]:
    found = [
        (label, match.start())
        for label, pattern in _FORBIDDEN.items()
        for match in pattern.finditer(source)
    ]
    found.extend(
        ("docker exec into a non-derived target", match.start())
        for match in _DOCKER_EXEC.finditer(source)
        if match.group("target") not in _DERIVED_API_TARGETS
    )
    return found


def _scripts() -> list[Path]:
    return sorted(_SCRIPTS.glob("*.sh"))


def test_the_scan_sees_every_canonical_script() -> None:
    assert {path.name for path in _scripts()} >= _EXPECTED


@pytest.mark.parametrize("path", _scripts(), ids=lambda path: path.name)
def test_script_does_not_reach_an_instance_directly(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    hits = [
        f"{label} (line {source.count(chr(10), 0, start) + 1})"
        for label, start in _hits(source)
    ]
    assert hits == [], f"{path.name}: {hits}"


_API_LOOKUP = re.compile(
    r"docker[\"',\s]+compose[\"',\s]+--project-directory[\"',\s]+(?P<dir>[^\s\"',]+)"
    r"[\"',\s]+ps[\"',\s]+--no-trunc[\"',\s]+-q(?![\w-])"
)


def test_the_api_container_is_found_in_the_d2_runner_compose_project() -> None:
    """DB 접근의 출발점(Map API 컨테이너)을 D2 러너와 같은 compose project에서 찾는다.

    service 라벨만으로 찾으면 같은 라벨을 단 다른 stack(격리 live 등)의 컨테이너를 집는다 —
    prod API가 내려가 있으면 repin이 그 stack의 DSN을 fixture DSN으로 쓴다. `head -1`은
    둘 중 아무거나 고른다. project 디렉터리는 `run-d2.sh`가 러너를 돌리는 곳에서 읽는다.
    """

    runner = re.search(
        r"^cd (/\S+) \|\|", (_SCRIPTS / "run-d2.sh").read_text(encoding="utf-8"), re.M
    )
    assert runner is not None
    for name in ("adjudicate.sh", "chain16.sh", "repin.sh"):
        source = (_SCRIPTS / name).read_text(encoding="utf-8")
        assignment = re.search(r"^COMPOSE_DIR=(\S+)$", source, re.M)
        directories = [
            assignment.group(1)
            if match.group("dir") == "$COMPOSE_DIR" and assignment is not None
            else match.group("dir")
            for match in _API_LOOKUP.finditer(source)
        ]
        assert directories == [runner.group(1)], name
        assert "label=com.docker.compose.service" not in source, name


def test_the_scan_sees_the_derived_exec_it_allows() -> None:
    """허용한 `docker exec`를 실제로 본다 — 모양이 바뀌어 검사가 아무것도 안 보면 빨갛다."""

    source = (_SCRIPTS / "adjudicate.sh").read_text(encoding="utf-8")
    assert [match.group("target") for match in _DOCKER_EXEC.finditer(source)] == ["api"]


@pytest.mark.parametrize(
    "line",
    [
        # 옛 전용 instance.
        "docker exec -i kor-travel-map-postgres psql",
        "psql -h 127.0.0.1 -p 12700",
        "psql -U kor_travel_map -d x",
        '["psql", "-U", "kor_travel_map", "-p"]',
        # 새 공용 instance — 이름이 달라도 같은 결박이다.
        "docker exec kor-travel-shared-postgresql psql -U shared_admin -p 11000 -d x",
        "docker exec --user postgres kor-travel-shared-postgresql true",
        '["docker", "exec", "-i", "kor-travel-shared-postgresql", "sh"]',
        "E2E_ADMIN_FEATURE_FIXTURE_PG_DSN=postgresql://u:p@127.0.0.1:11000/kor_travel_map",
        '"postgresql+asyncpg://ktm_feature_service@[::1]:11000/kor_travel_map"',
        "pg_isready --port=11000",
        "pg_dump -h 127.0.0.1 kor_travel_map",
        'subprocess.run(["pg_restore", dump])',
    ],
)
def test_the_detector_catches_each_forbidden_shape(line: str) -> None:
    """검사기가 빨갛게 될 수 있음을 스스로 보인다(항진명제 방지)."""

    assert _hits(line)


@pytest.mark.parametrize(
    "line",
    [
        'docker exec -i "$api" python -I -B -',
        '["docker", "exec", "-i", api, "python", "-I", "-B", "-", run_id],',
        'docker exec "${API}" true',
        "-U kor_travel_map_dagster",
        "lat 127000000",
        "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE=kor_travel_map",
        'mkdir -p "$NEW"',
        'git -C /home/digitie/ktm-c7-src show "$MAP:scripts/m01_activation_preflight.py"',
        "import asyncpg",
        'echo "  시작 $(date -u +%FT%TZ)"',
    ],
)
def test_the_detector_does_not_flag_neighbouring_names(line: str) -> None:
    assert _hits(line) == []

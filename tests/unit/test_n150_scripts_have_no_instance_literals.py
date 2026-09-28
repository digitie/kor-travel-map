"""n150 호스트 스크립트는 Map DB instance에 직접 닿지 않는다 (ADR-103).

prod의 Map DB는 전용 instance(`kor-travel-map-postgres`, port 12700)에서 Manager 공용
instance로 옮긴다. 스크립트가 instance의 이름·port·superuser를 적어 두면 이전 뒤에는 옛
instance를 향하거나(아직 떠 있을 때) 조용히 실패한다. 새 instance의 이름을 적으면 같은
결박이 되살아나고, 이번에는 모든 tenant의 cluster superuser다. DB 접근은 실행 중인 Map API
컨테이너에서 유도한다 — `adjudicate.sh`는 그 컨테이너 안에서 세고, `repin.sh`는 그 DSN에서
D2 fixture DSN을 만든다.

그래서 이름이 아니라 **효과**를 본다: PostgreSQL client를 부르지 않고, PostgreSQL 서버 이미지를
띄우지 않고, DSN이나 libpq 연결 키워드(`host=`·`port=`·`PGHOST`…)를 적지 않고, `docker exec`
(`docker container exec`, `docker compose … exec` 포함)는 같은 스크립트가 Map API 조회로 **유도한**
변수에만 한다. 옛 instance의 이름 셋은 그 위에 그대로 막아 둔다.

검사는 어휘 검사다. 규칙은 넓히기보다 좁힌다 — 오탐(API health poll의 URL, `ssh -p`)은 작성자를
문자열 쪼개기 같은 우회로 민다. 미탐은 아래 두 자기 검사 목록에 실측한 모양을 더해 막는다.
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

#: 셸 단어와 argv 목록 원소 사이의 구분(공백·따옴표·쉼표).
_SEP = r"[\"',\s]+"

#: 값을 받는 `docker exec`·`docker compose exec` flag. 값(`-e X=1`)을 target으로 읽지
#: 않도록 먼저 먹는다.
_VALUE_FLAG = r"(?:--env-file|--env|--user|--workdir|--index|--detach-keys|-e|-u|-w)"

_DOCKER_EXEC = re.compile(
    # 셸(`docker exec -i "$api"`)과 argv 목록(`"docker", "exec", "-i", api`) 두 모양.
    # `docker container exec`와 `docker compose … exec`(target은 service)도 같은 효과다.
    rf"docker(?:{_SEP}container|{_SEP}compose(?![\w-])[^\n]*?)?{_SEP}exec(?![\w-])"
    rf"(?:{_SEP}(?:{_VALUE_FLAG}(?:=|{_SEP})[^\s\"',]+|-{{1,2}}[A-Za-z][\w-]*))*"
    rf"{_SEP}(?P<target>[^\s\"',]+)"
)

_FORBIDDEN = {
    # 효과: 스크립트가 PostgreSQL에 직접 붙거나 서버를 띄운다.
    "PostgreSQL client": re.compile(
        r"(?<![\w-])(psql|pg_dump|pg_dumpall|pg_restore|pg_isready|createdb|dropdb)(?![\w-])"
    ),
    "PostgreSQL server image": re.compile(
        r"(?<![\w.-])(?:[\w.-]+/)*(?:postgres|postgis)(?::[0-9]|@sha256:)"
    ),
    "DSN literal": re.compile(r"(?<![\w+.-])postgres(?:ql)?(?:\+\w+)?://"),
    "libpq connection keyword": re.compile(r"(?<![\w.-])(?:host|hostaddr|port)[ \t]*=(?!=)"),
    "libpq connection env": re.compile(r"(?<![\w-])PG(?:HOST|HOSTADDR|PORT|SERVICE)(?![\w-])"),
    # 옛 instance의 이름 셋(ADR-103 이전 값).
    "port 12700": re.compile(r"(?<![0-9])12700(?![0-9])"),
    "container kor-travel-map-postgres": re.compile(r"kor-travel-map-postgres"),
    # `-U kor_travel_map`과 argv 목록 모양(`"-U", "kor_travel_map"`)을 함께 잡는다.
    "superuser -U kor_travel_map": re.compile(r"-U[\"',\s]+kor_travel_map(?![A-Za-z0-9_])"),
}

#: Map API 컨테이너 조회 — D2 러너와 같은 compose project의 그 service.
_API_LOOKUP = re.compile(
    r"docker[\"',\s]+compose[\"',\s]+--project-directory[\"',\s]+(?P<dir>[^\s\"',]+)"
    r"[\"',\s]+ps[\"',\s]+--no-trunc[\"',\s]+-q(?![\w-])"
)

#: 셸(`API="$(…)"`, `local x=…`)과 python(`api = …`)의 대입 한 줄(논리 줄).
_ASSIGNMENT = re.compile(
    r"^[ \t]*(?:(?:local|export|readonly|declare)[ \t]+)?"
    r"(?P<name>[A-Za-z_]\w*)[ \t]*=(?!=)(?P<value>.*)$",
    re.MULTILINE,
)
_FIRST_OF = re.compile(r"[ \t]*(?P<source>[A-Za-z_]\w*)\[0\][ \t]*")
_VARIABLE = re.compile(r"\$?\{?(?P<name>[A-Za-z_]\w*)\}?")


def _logical(source: str) -> str:
    """셸 줄 잇기(`\\` + 줄바꿈)와 argv 목록·호출 안의 줄바꿈을 같은 길이의 공백으로 편다.

    길이가 같아 offset이 그대로다 — 줄 번호는 원문 기준으로 센다.
    """

    source = source.replace("\\\n", "  ")
    return re.sub(r"(?<=[,(\[])([ \t]*)\n", lambda match: match.group(1) + " ", source)


def _code(source: str) -> str:
    """주석 줄(셸·python 모두 `#`)을 같은 길이의 공백으로 지운 원문."""

    return re.sub(r"(?m)^[ \t]*#.*$", lambda match: " " * len(match.group(0)), source)


def _derived_api_variables(source: str) -> set[str]:
    """Map API 조회(`_API_LOOKUP`)의 결과로만 대입되는 변수 — `docker exec`를 허용하는 target.

    이름 목록이 아니라 유도를 본다. 조회를 직접 받거나(셸 `API="$(docker compose … ps …)"`,
    python `apis = subprocess.run([… "ps" …])`) 그 첫 원소(`api = apis[0]`)인 변수이고, 같은
    스크립트에 다른 대입이 하나라도 있으면 빠진다(`api=kor-travel-shared-postgresql`).
    """

    values: dict[str, list[str]] = {}
    for match in _ASSIGNMENT.finditer(_logical(_code(source))):
        values.setdefault(match.group("name"), []).append(match.group("value"))
    direct = {
        name
        for name, assigned in values.items()
        if all(_API_LOOKUP.search(value) for value in assigned)
    }
    first_of: set[str] = set()
    for name, assigned in values.items():
        sources = [_FIRST_OF.fullmatch(value) for value in assigned]
        if all(match is not None and match.group("source") in direct for match in sources):
            first_of.add(name)
    return direct | first_of


def _hits(source: str) -> list[tuple[str, int]]:
    logical = _logical(source)
    found = [
        (label, match.start())
        for label, pattern in _FORBIDDEN.items()
        for match in pattern.finditer(logical)
    ]
    derived = _derived_api_variables(source)
    for match in _DOCKER_EXEC.finditer(logical):
        variable = _VARIABLE.fullmatch(match.group("target"))
        if variable is None or variable.group("name") not in derived:
            found.append(("docker exec into a target not derived from the API", match.start()))
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
            for match in _API_LOOKUP.finditer(_logical(source))
        ]
        assert directories == [runner.group(1)], name
        assert "label=com.docker.compose.service" not in source, name


#: compose 호출 하나 — 셸 `$(…)`의 닫는 괄호, 또는 argv 목록을 넘긴 `subprocess.run(…)`의 닫는
#: 괄호까지.
_COMPOSE_CALL = re.compile(r"docker[\"',\s]+compose(?![\w-])[^)]*\)")
_STDERR_KEPT_OUT = re.compile(
    r"2>\s*/dev/null|&>\s*/dev/null|capture_output=True|stderr=subprocess\.(?:DEVNULL|PIPE)"
)


def test_compose_calls_keep_compose_warnings_out_of_the_output() -> None:
    """compose 호출은 stderr를 버리거나 잡는다 — 그 경고에 비밀에서 나온 조각이 섞인다.

    compose는 `ps`처럼 읽기만 하는 호출에서도 project의 `.env`를 해석한다. 따옴표 없는 값에 든
    `$`의 꼬리를 변수 이름으로 읽어 `The "<꼬리>" variable is not set` 경고를 stderr로 찍고,
    n150에서 그 꼬리는 비밀(관리자 비밀번호 hash)의 조각이었다(2026-09-29 실측). chain16은 repin
    출력을 `2>&1 | tail`로 운영 로그에 옮긴다. D2 러너(`validate_runtime`)처럼 버리거나 python에서
    잡는다. 셋 중 하나의 redirect를 지우면 빨갛다.
    """

    seen: set[str] = set()
    for path in _scripts():
        code = _code(path.read_text(encoding="utf-8"))
        for match in _COMPOSE_CALL.finditer(code):
            seen.add(path.name)
            line = code.count("\n", 0, match.start()) + 1
            assert _STDERR_KEPT_OUT.search(match.group(0)), f"{path.name}:{line}"
    assert seen >= {"adjudicate.sh", "chain16.sh", "repin.sh"}


def test_the_scan_sees_the_derived_exec_it_allows() -> None:
    """허용한 `docker exec`를 실제로 본다 — 모양이 바뀌어 검사가 아무것도 안 보면 빨갛다."""

    source = (_SCRIPTS / "adjudicate.sh").read_text(encoding="utf-8")
    assert [match.group("target") for match in _DOCKER_EXEC.finditer(_logical(source))] == ["api"]
    assert "api" in _derived_api_variables(source)
    for name in ("chain16.sh", "repin.sh"):
        assert "API" in _derived_api_variables((_SCRIPTS / name).read_text(encoding="utf-8"))


#: 자기 검사에서 쓰는 유도 한 줄(셸).
_SHELL_LOOKUP = (
    'API="$(docker compose --project-directory /opt/x ps --no-trunc -q svc 2>/dev/null)"\n'
)
_PYTHON_LOOKUP = (
    "apis = subprocess.run(\n"
    '    ["docker", "compose", "--project-directory", "/opt/x",\n'
    '     "ps", "--no-trunc", "-q", service],\n'
    "    check=True, capture_output=True, text=True,\n"
    ").stdout.split()\n"
    "api = apis[0]\n"
)


@pytest.mark.parametrize(
    "text",
    [
        # 옛 전용 instance.
        "docker exec -i kor-travel-map-postgres psql",
        "psql -h 127.0.0.1 -p 12700",
        "psql -U kor_travel_map -d x",
        '["psql", "-U", "kor_travel_map", "-p"]',
        # 새 공용 instance — 이름이 달라도 같은 결박이다.
        "docker exec kor-travel-shared-postgresql psql -U shared_admin -p 11000 -d x",
        "docker exec --user postgres kor-travel-shared-postgresql true",
        "docker exec -e X=1 kor-travel-shared-postgresql true",
        '["docker", "exec", "-i", "kor-travel-shared-postgresql", "sh"]',
        "docker container exec kor-travel-shared-postgresql true",
        "docker compose --project-directory /opt/kor-travel-docker-manager exec -T "
        "kor-travel-shared-postgres sh -c true",
        "docker compose -p kor-travel-docker-manager exec -T kor-travel-shared-postgres sh -c x",
        '["docker", "compose", "--project-directory", "/opt/x",\n'
        ' "exec", "-T", "kor-travel-shared-postgres", "sh"]',
        # 허용 이름이라도 유도가 아니면 빨갛다.
        'api=kor-travel-shared-postgresql; docker exec "$api" python -I -B -',
        _SHELL_LOOKUP + 'API=kor-travel-shared-postgresql\ndocker exec "$API" true',
        'docker exec -i "$api" python -I -B -',
        # DSN·libpq 연결 모양.
        "E2E_ADMIN_FEATURE_FIXTURE_PG_DSN=postgresql://u:p@127.0.0.1:11000/kor_travel_map",
        '"postgresql+asyncpg://ktm_feature_service@[::1]:11000/kor_travel_map"',
        "postgresql://u:p@127.0.0.1:11000?dbname=kor_travel_map",
        'asyncpg.connect(host="127.0.0.1", port=11000, user="shared_admin")',
        "host=127.0.0.1 port=11000 dbname=kor_travel_map",
        "PGPORT=11000 PGHOST=127.0.0.1 python -c 'import asyncpg'",
        "pg_isready --port=11000",
        "pg_dump -h 127.0.0.1 kor_travel_map",
        'subprocess.run(["pg_restore", dump])',
        # 서버 이미지를 host network로 띄운다.
        "docker run --rm --network host postgres:16-alpine sh",
        "docker run --rm postgis/postgis@sha256:" + "0" * 64,
    ],
)
def test_the_detector_catches_each_forbidden_shape(text: str) -> None:
    """검사기가 빨갛게 될 수 있음을 스스로 보인다(항진명제 방지)."""

    assert _hits(text)


@pytest.mark.parametrize(
    "text",
    [
        _SHELL_LOOKUP + 'docker exec -i "$API" python -I -B -',
        _SHELL_LOOKUP + 'docker exec -e X=1 --user app "${API}" true',
        _PYTHON_LOOKUP + '["docker", "exec", "-i", api, "python", "-I", "-B", "-", run_id],',
        "-U kor_travel_map_dagster",
        "lat 127000000",
        "E2E_ADMIN_FEATURE_FIXTURE_CONFIRM_DATABASE=kor_travel_map",
        'mkdir -p "$NEW"',
        'git -C /home/digitie/ktm-c7-src show "$MAP:scripts/m01_activation_preflight.py"',
        "import asyncpg",
        'echo "  시작 $(date -u +%FT%TZ)"',
        # 넓던 옛 규칙의 오탐(2026-09-29 n150 실측).
        "curl -fsS http://127.0.0.1:12701/healthz",
        "ssh -p 22 n150 true",
        # 이웃 이름.
        'if parts.scheme not in {"postgresql", "postgresql+asyncpg"}:',
        'scheme, sep, rest = dsn.partition("://")',
        'host_networked = network_mode == "host"',
        '"--network", "host"',
        "docker run --network=host image",
        "if parts.port != 5432:",
        "export PATH=/usr/bin",
        "exec 9>\"$R/orchestrator.lock\"",
    ],
)
def test_the_detector_does_not_flag_neighbouring_names(text: str) -> None:
    assert _hits(text) == []

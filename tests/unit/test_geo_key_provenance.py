"""geo **소비자** 키가 VWorld 키로 떨어지는 통로를 정적으로 막는다.

`kor-travel-geo`에는 성격이 다른 자격증명 둘이 있다. **VWorld 키**는 geo가 상류
VWorld로 나갈 때 쓰고, **geo public API key**는 소비자가 geo에 인증할 때 쓴다. geo는
VWorld 키를 `401 E0401`로 거절한다. 이름이 비슷해서 설정 사슬이 반복적으로 둘을 이어
왔고, 그때마다 **조용히** 실패했다 — `preflight()`는 존재·길이만 보므로 리소스 초기화는
통과하고, 실패는 첫 요청 시점에야 나타난다. 2026-08-13 prod에서 실제로 났다.

## 두 번 다시 쓴 이유

첫 판은 이름 하나만 앵커로 잡고 개수를 못박아, 같은 파일의 다른 줄이 VWorld로
떨어지는데도 초록이었다. 두 번째 판은 **손으로 고른 파일 목록**과 정규식 우변 잘라내기를
썼는데, 적대 리뷰가 우회 5종을 실증했다 — compose 리스트형 `environment`, 이름을 인용한
쉘 대입(`"NAME"="$VWORLD"`), TS의 괄호 감싸기, 목록 밖 파일(`docker-compose.host.yml`,
`verify-all-gates.sh`), 그리고 `.env.example` 과탐.

**정규식을 기우는 방식이 세 번 실패했으므로 축을 바꿨다:**

1. **목록이 아니라 발견.** 소비자 변수를 언급하는 파일을 저장소에서 **찾아** 확장자로
   분류한다. 새 파일이 생기면 자동으로 들어온다 — 목록 관리가 사라진다.
2. **쉘/Dockerfile은 단어 단위.** 이어쓰기를 합친 뒤 **인용을 보존한 채** 토큰으로 쪼개
   소비자 변수에 값을 넣는 토큰만 본다. `"NAME"="$VWORLD"`는 한 토큰이라 잘리지 않고,
   `--build-arg "A=…" --build-arg "B=…"`는 서로 다른 토큰이라 섞이지 않는다.
3. **TS는 문장 단위.** 괄호 그룹만 보면 같은 문장 안의 직접 참조를 놓친다.
4. **compose는 dict와 list를 모두 읽는다.** 그리고 override·`env_file`까지 포함한
   **해석된 값**은 `tests/integration/test_compose_geo_key_resolution.py`가
   `docker compose config`로 확인한다 — 여기 정적 검사는 그 앞단이다.

## 그래도 못 하는 것 — 과장하지 않고 적는다

세 판 연속으로 문제가 된 것이 정확히 **가드가 자기 능력을 과장한 것**이었다. 적대
리뷰가 실증한 잔여 우회를 전부 적는다.

- **중간 변수 우회.** 값 흐름 분석이 아니다. 함수로 빼서 소비자 이름 없이 VWorld를
  돌려주는 형태(`function resolveGeoKey() { … return process.env.NEXT_PUBLIC_VWORLD_API_KEY }`)도
  같은 부류다.
- **동적으로 조립한 환경변수 이름.** `` process.env[`NEXT_PUBLIC_${"VWORLD"}_API_KEY`] ``는
  템플릿 리터럴 본문이 이름 모양이 아니라 산문으로 판정돼 지워진다. 문자열 결합
  (`"NEXT_PUBLIC_" + "VWORLD_API_KEY"`)은 잡히지만 보간은 못 잡는다.
- **JS 객체에서 이름과 값을 형제 속성으로 쪼개는 것.** `{ name: "…GEO_API_KEY",
  fallback: vworldKey }` — 이웃 속성 오탐을 막으려 속성 단위로 좁힌 대가다.
- **운영자의 `.env` 파일 자체.** **2026-08-13 사고의 실제 원인이 그 축이었다** — 이
  가드는 그 사고를 막지 못했을 것이다. 저장소가 그 값을 **권하지** 않게 하는 것이
  여기서 할 수 있는 전부이고, `.env.example`을 주석까지 훑는 이유가 그것이다.
- **kor-travel-docker-manager의 compose.** prod가 실제로 쓰는 정의는 그 저장소에 있다.
- **profile로 가려진 compose 서비스.** `docker compose config`가 출력에서 제외하므로
  통합 층이 보지 못한다(정적 층은 본다).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]

#: geo가 인증에 받아들이는 소비자 키 이름들. VWorld 키와는 다른 자격증명이다.
_GEO_CONSUMER_VARS = (
    "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY",
    "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",
    "KOR_TRAVEL_GEO_API_KEY",
)
#: 앞에 `_`나 영숫자가 붙은 더 긴 이름(`E2E_KOR_TRAVEL_GEO_API_KEY`)은 다른 변수다.
_CONSUMER_RE = re.compile(
    "(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(name) for name in _GEO_CONSUMER_VARS) + ")"
)
_VWORLD = re.compile("VWORLD", re.IGNORECASE)
_ASSIGN_NAMES = "|".join(_GEO_CONSUMER_VARS)
_EXPORT_FIRST_RE = re.compile(rf"export_first\s+(?:{_ASSIGN_NAMES})\b[^\n]*")
#: 토큰 안에서 "소비자 변수에 값을 넣는" 형태. 이름 양쪽 인용은 선택이다.
_TOKEN_ASSIGN_RE = re.compile(rf"[\"']?(?:{_ASSIGN_NAMES})[\"']?\s*[:=]")

#: `.env.example`이 반드시 담아야 하는 경고. 금지가 아니라 **요구**라서 문구를 바꿔
#: 우회할 수 없고, 인라인 주석에 경고를 적었다고 빨간불이 뜨지도 않는다.
_ADVISORY_MARKER = "VWorld 키로는 인증되지 않는다"

#: 문서·마크다운은 대상이 아니다(서술이 목적이다). 이 가드 파일 자신도 뺀다 —
#: 금지 이름과 VWorld를 동시에 담을 수밖에 없어 자기 자신을 위반으로 잡는다
#: (`test_no_control_characters_in_source`가 금지 문자를 `chr()`로 적는 것과 같은 이유).
_SKIP_SUFFIXES = (".md",)
_SKIP_PATHS = ("tests/unit/test_geo_key_provenance.py",)

_OPENERS = "([{"
_CLOSERS = ")]}"


#: `git ls-files`를 못 쓸 때만 쓰는 배제 목록. 이 목록이 바로 적대 리뷰가 지적한
#: "사람이 다음에 무엇이 생길지 계속 맞혀야 하는" 표면이라 **fallback으로만** 둔다.
_FALLBACK_SKIP_DIRS = (
    "node_modules",
    ".next",
    "docs",
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
)
_FALLBACK_SKIP_DIR_SUFFIXES = (".egg-info",)


def _tracked_files() -> list[str] | None:
    """`git ls-files` 결과. git 저장소가 아니면 ``None``."""

    try:
        listed = subprocess.run(  # noqa: S603 - 저장소 자신의 파일 목록을 얻는 것이 목적이다
            ["git", "ls-files", "-z"],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted(entry for entry in listed.split("\0") if entry)


def _discover() -> list[str]:
    """소비자 변수를 언급하는 **추적 파일**을 찾는다(손으로 고르지 않는다).

    `git ls-files`로 뽑는다. `rglob` + 배제 목록을 쓰다가 `pip install -e`가 만드는
    `*.egg-info/PKG-INFO`(README 사본)가 CI에서만 걸려 red가 났다 — 배제 목록은
    "다음에 무엇이 생길지"를 사람이 계속 맞혀야 하는 목록이고, 그 실패 양식이 실제로
    한 번 터졌다. 추적 파일만 보면 빌드 산출물·캐시가 통째로 사라진다(적대 리뷰 권고).
    """

    candidates = _tracked_files()
    if candidates is None:
        # CI 미러 하네스는 워크트리를 tar로 복사해 `.git`이 없다. 그때만 파일 순회로
        # 되돌아가고 생성물을 이름으로 뺀다 — git이 있을 때는 이 목록이 쓰이지 않는다.
        candidates = [
            path.relative_to(_ROOT).as_posix()
            for path in sorted(_ROOT.rglob("*"))
            if not any(
                part in _FALLBACK_SKIP_DIRS or part.endswith(_FALLBACK_SKIP_DIR_SUFFIXES)
                for part in path.relative_to(_ROOT).parts
            )
        ]
    found: list[str] = []
    for relative in candidates:
        if relative in _SKIP_PATHS or relative.endswith(_SKIP_SUFFIXES):
            continue
        path = _ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _CONSUMER_RE.search(text):
            found.append(relative)
    return found


def _read(relative: str) -> str:
    return (_ROOT / relative).read_text(encoding="utf-8")


def _strip_line_comment(line: str) -> str:
    """인용부호 **밖**의 `#`부터 잘라 낸다."""

    single = double = False
    for index, char in enumerate(line):
        if char == "'" and not double:
            single = not single
        elif char == '"' and not single:
            double = not double
        elif (
            char == "#"
            and not single
            and not double
            and (index == 0 or line[index - 1].isspace())
        ):
            return line[:index]
    return line


def _shell_words(line: str) -> list[str]:
    """공백으로 단어를 나누되 **인용과 명령 치환 안의 공백은 나누지 않는다**.

    `shlex(posix=False)`를 썼다가 `"NAME=$(printf %s "$X")"` 에서 중첩 따옴표를 만나
    단어가 끊겼다 — 가드는 초록인데 셸은 정상 동작했다(적대 리뷰 실증). 그래서 `$( )`
    안에서 인용 문맥이 새로 열린다는 점까지 반영해 직접 센다.
    """

    words: list[str] = []
    current: list[str] = []
    single = double = backtick = False
    depth = 0
    index = 0
    while index < len(line):
        char = line[index]
        pair = line[index : index + 2]
        # 백슬래시 이스케이프는 다음 문자를 그대로 삼킨다 — `x\ $VW`는 셸이 한 단어로 둔다.
        if char == "\\" and not single and index + 1 < len(line):
            current.append(line[index : index + 2])
            index += 2
            continue
        if not single and pair == "$(":
            depth += 1
            current.append(pair)
            index += 2
            continue
        # 백틱 명령치환. `$( )`만 세다가 `` `printf %s "$VW"` ``에서 단어가 끊겼다
        # (적대 리뷰 실증). 백틱은 유효 POSIX이고 shellcheck도 style 경고일 뿐이다.
        if char == "`" and not single:
            backtick = not backtick
            current.append(char)
            index += 1
            continue
        if not single and depth > 0 and char == ")":
            depth -= 1
        elif char == "'" and not double:
            single = not single
        elif char == '"' and not single:
            double = not double
        elif char.isspace() and not single and not double and not backtick and depth == 0:
            if current:
                words.append("".join(current))
                current = []
            index += 1
            continue
        current.append(char)
        index += 1
    if current:
        words.append("".join(current))
    return words


def _shell_passages(relative: str) -> list[str]:
    """이어쓰기를 합친 뒤 **인용을 보존한 채** 토큰으로 쪼갠다.

    정규식으로 우변을 잘라내던 앞 판은 `"NAME"="$VWORLD"`에서 값의 여는 따옴표를
    닫는 따옴표로 오인해 우변을 통째로 버렸다 — 가드는 초록인데 실제 `docker build`가
    VWorld 값을 번들에 넣었다(적대 리뷰 실증). 셸 토큰 경계는 그런 절단이 없다.
    """

    stripped = "\n".join(_strip_line_comment(line) for line in _read(relative).splitlines())
    joined = stripped.replace("\\\n", " ")
    found: list[str] = []
    for line in joined.splitlines():
        found.extend(match.group(0) for match in _EXPORT_FIRST_RE.finditer(line))
        found.extend(word for word in _shell_words(line) if _TOKEN_ASSIGN_RE.search(word))
    # 이어쓰기 없이 여러 줄에 걸친 대입은 토큰으로도 안 보인다 — `${…}`/`$(…)`만 본다
    # (셸의 `{ }`는 함수 본문이라 그냥 훑으면 함수 전체가 한 구절이 된다).
    found.extend(
        group
        for match in _CONSUMER_RE.finditer(stripped)
        if (group := _enclosing_group(stripped, match.start(), require_dollar=True)) is not None
    )
    return found


def _enclosing_span(
    text: str, index: int, *, require_dollar: bool = False
) -> tuple[int, int] | None:
    depth = 0
    start = None
    for cursor in range(index - 1, -1, -1):
        char = text[cursor]
        if char in _CLOSERS:
            depth += 1
        elif char in _OPENERS:
            if depth == 0:
                start = cursor
                break
            depth -= 1
    if start is None:
        return None
    if require_dollar and not (start > 0 and text[start - 1] == "$"):
        return None
    depth = 0
    for cursor in range(start + 1, len(text)):
        char = text[cursor]
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            if depth == 0:
                return start, cursor + 1
            depth -= 1
    return start, len(text)


def _enclosing_group(text: str, index: int, *, require_dollar: bool = False) -> str | None:
    span = _enclosing_span(text, index, require_dollar=require_dollar)
    return None if span is None else text[span[0] : span[1]]


#: 환경변수 이름처럼 생긴 문자열만 남긴다. 산문 문자열은 지운다 — 이 저장소의 오류
#: 메시지는 "VWorld 키는 이 자리에 쓸 수 없다"처럼 **경고 자체**를 담으므로, 그대로
#: 훑으면 올바른 코드가 자기 설명 때문에 걸린다(실측 오탐 1건). `process.env["NAME"]`
#: 형태는 이름 모양이라 남는다.
_NAME_LIKE = re.compile(r"^[A-Za-z0-9_./:-]+$")


def _blank_prose_strings(text: str) -> str:
    def _blank(match: re.Match[str]) -> str:
        body = match.group(2)
        return match.group(0) if _NAME_LIKE.match(body) else f"{match.group(1)}{match.group(1)}"

    return re.sub(r"([\"'`])((?:[^\\\n]|\\.)*?)\1", _blank, text)


def _strip_js_comments(text: str) -> str:
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    without_line = "\n".join(re.sub(r"//.*$", "", line) for line in without_block.splitlines())
    return _blank_prose_strings(without_line)


def _element_of(group: str, offset: int) -> str:
    """객체 리터럴이면 **속성** 하나로 좁힌다.

    `{ A: "", B: vworldKey }` 전체를 한 구절로 보면 이웃 속성 때문에 정상 코드가
    걸린다(실측 오탐 1건). 배열 `[...]`은 그 자체가 원소(튜플)이므로 좁히지 않는다.
    """

    if not group.startswith("{"):
        return group
    depth = 0
    start = 1
    for cursor in range(1, offset):
        char = group[cursor]
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth -= 1
        elif char == "," and depth == 0:
            start = cursor + 1
    depth = 0
    for cursor in range(offset, len(group)):
        char = group[cursor]
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            if depth == 0:
                return group[start:cursor]
            depth -= 1
        elif char == "," and depth == 0:
            return group[start:cursor]
    return group[start:]


def _ts_passages(relative: str) -> list[str]:
    """TS는 **문장** 단위로 본다.

    괄호 그룹만 보면 같은 문장 안의 직접 참조를 놓친다 — 소비자 이름을 `(...)`로 감싸면
    같은 `const` 초기화식의 VWorld 폴백이 보이지 않았다(적대 리뷰 실증).
    """

    text = _strip_js_comments(_read(relative))
    seen: dict[str, None] = {}
    for match in _CONSUMER_RE.finditer(text):
        head = text.rfind(";", 0, match.start()) + 1
        tail = text.find(";", match.start())
        seen[text[head : tail if tail != -1 else len(text)]] = None
    return list(seen)


def _js_passages(relative: str) -> list[str]:
    """`.mjs`는 배열 원소 단위(감싸는 괄호 그룹)로 본다.

    여기서 문장 단위를 쓰면 `return [ … ]` 전체가 한 구절이 되어, 이웃한 VWorld 항목
    때문에 정상 코드가 걸린다.
    """

    text = _strip_js_comments(_read(relative))
    seen: dict[str, None] = {}
    for match in _CONSUMER_RE.finditer(text):
        span = _enclosing_span(text, match.start())
        if span is None:
            head = text.rfind(";", 0, match.start()) + 1
            tail = text.find(";", match.start())
            seen[text[head : tail if tail != -1 else len(text)]] = None
            continue
        seen[_element_of(text[span[0] : span[1]], match.start() - span[0])] = None
    return list(seen)


def _compose_passages(relative: str) -> list[str]:
    """YAML로 읽어 앵커/별칭·인용 키·머지 키를 **해석한 뒤** 값을 모은다.

    `environment` / `build.args`는 매핑과 **리스트**(`- KEY=value`) 둘 다 유효하다.
    앞 판은 매핑만 봐서 리스트형이 통째로 새어 나갔다(적대 리뷰가 실제
    `docker compose config`로 실증). 두 형태를 모두 읽는다.
    """

    document: Any = yaml.safe_load(_read(relative))
    if not isinstance(document, dict):
        return []
    found: list[str] = []
    for name, service in (document.get("services") or {}).items():
        if not isinstance(service, dict):
            continue
        blocks = [service.get("environment")]
        build = service.get("build")
        if isinstance(build, dict):
            blocks.append(build.get("args"))
        for block in blocks:
            if isinstance(block, dict):
                pairs = [(key, value) for key, value in block.items()]
            elif isinstance(block, list):
                pairs = [
                    tuple(str(entry).split("=", 1)) if "=" in str(entry) else (str(entry), "")
                    for entry in block
                ]
            else:
                continue
            for key, value in pairs:
                if str(key) in _GEO_CONSUMER_VARS:
                    found.append(f"{name}.{key}={value}")
    return found


def _advisory_passages(relative: str) -> list[str]:
    """`.env.example`은 **주석까지** 본다 — 막으려는 것이 값이 아니라 **권유**다.

    한때 주석을 걷어냈더니 "현재는 `NEXT_PUBLIC_VWORLD_API_KEY`와 동일"이라는, 2026-08-13
    사고를 손으로 재현시키던 바로 그 문안이 다시 초록이 됐다(적대 리뷰 실증). 인라인
    주석에 **경고**를 적었다고 빨간불이 뜨는 과탐도 피해야 하므로, marker 문장을 담은
    줄만 면제한다.
    """

    return [
        line
        for line in _read(relative).splitlines()
        if _CONSUMER_RE.search(line) and _ADVISORY_MARKER not in line
    ]


def _is_compose(relative: str) -> bool:
    """파일명이 아니라 **내용**으로 판정한다.

    `docker-compose` 접두어를 요구했더니 `compose.override.yaml`이 줄 단위 처리기로
    떨어져 앵커 별칭을 못 봤다 — 그리고 Docker Compose는 그 이름을 `-f` 없이도
    **자동으로 얹는다**(적대 리뷰가 `docker compose config`로 누출 실증).
    최상위에 `services:` 매핑이 있으면 compose다.
    """

    if not relative.endswith((".yml", ".yaml")):
        return False
    try:
        document = yaml.safe_load(_read(relative))
    except yaml.YAMLError:
        return False
    return isinstance(document, dict) and isinstance(document.get("services"), dict)


def _passages(relative: str) -> list[str]:
    name = Path(relative).name
    if name.endswith(".env.example"):
        return _advisory_passages(relative)
    if _is_compose(relative):
        return _compose_passages(relative)
    if name.endswith((".Dockerfile", ".sh")):
        return _shell_passages(relative)
    if name.endswith((".ts", ".tsx")):
        return _ts_passages(relative)
    if name.endswith((".mjs", ".js", ".jsx")):
        return _js_passages(relative)
    # 나머지(파이썬 등)는 줄 단위. 주석과 **산문 문자열**을 지운다 — 이 저장소의 오류
    # 메시지는 "VWorld 키는 이 자리에 쓸 수 없다" 같은 경고 자체를 담으므로, 그대로
    # 훑으면 올바른 코드가 자기 설명 때문에 걸리고 메시지까지 거짓이 된다(적대 리뷰
    # 지적). 환경변수 이름 모양의 문자열은 남으므로 `os.environ["…VWORLD…"]`는 보인다.
    return [
        _blank_prose_strings(_strip_line_comment(line))
        for line in _read(relative).splitlines()
        if _CONSUMER_RE.search(_blank_prose_strings(_strip_line_comment(line)))
    ]


_DISCOVERED = _discover()


def test_the_scan_actually_finds_the_known_carriers() -> None:
    """발견이 비어 있거나 알려진 통로를 놓치면 이 가드는 아무것도 지키지 않는다."""

    assert len(_DISCOVERED) >= 8, _DISCOVERED
    for expected in (
        "docker-compose.yml",
        "scripts/load-env.sh",
        "scripts/docker-buildx.sh",
        "docker/frontend.Dockerfile",
        "scripts/frontend-build-inputs.mjs",
        "packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts",
    ):
        assert expected in _DISCOVERED, f"{expected}을 발견하지 못했다: {_DISCOVERED}"


@pytest.mark.parametrize("relative", _DISCOVERED)
def test_geo_consumer_key_never_falls_back_to_vworld(relative: str) -> None:
    passages = _passages(relative)
    tainted = [chunk for chunk in passages if _VWORLD.search(chunk)]
    assert not tainted, (
        f"{relative}: geo 소비자 키가 VWorld 키로 떨어진다 — geo가 401(E0401)로"
        " 거절하는 값이다.\n"
        + "\n".join(f"  {' '.join(chunk.split())[:180]}" for chunk in tainted)
    )


@pytest.mark.parametrize(
    "relative", [name for name in _DISCOVERED if Path(name).name.endswith(".env.example")]
)
def test_env_examples_warn_that_the_vworld_key_is_not_valid(relative: str) -> None:
    """`.env.example`은 그 값을 **권하지 않는다**고 적어야 한다.

    운영자의 `.env`는 이 가드가 볼 수 없고, 2026-08-13 사고의 실제 원인이 그 축이었다.
    저장소가 할 수 있는 것은 예시가 그 값을 권하지 않게 하는 것뿐이다. 금지가 아니라
    **요구**로 적는다 — 문구를 바꿔 우회할 수 없고, 인라인 주석에 경고를 적었다는
    이유로 빨간불이 뜨지도 않는다.
    """

    assert _ADVISORY_MARKER in _read(relative), (
        f"{relative}에 geo 소비자 키 경고가 없다 — {_ADVISORY_MARKER!r} 문구를 넣어라"
    )


def test_load_env_maps_the_public_alias_forward() -> None:
    """`.env.example`이 시키는 이름만 설정해도 admin UI가 키를 받는다."""

    joined = _read("scripts/load-env.sh").replace("\\\n", " ")
    assert re.search(
        r"export_first\s+NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY\s+"
        r"KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY\b",
        joined,
    ), "load-env.sh가 geo 소비자 키의 public 별칭을 정본 이름에서 채우지 않는다"


def test_load_env_never_exits_on_alias_mismatch() -> None:
    """별칭 불일치로 **호출자를 죽이지 않는다**.

    `load-env.sh`는 항상 `source`된다(`docker-up.sh`·`docker-buildx.sh`·
    `docker-restore-swap.sh` …). `exit 1`은 호출 스크립트를 끝내고, 대화형 셸에서는
    터미널을 닫는다 — 복구 절차(`docker-restore-swap.sh`가 운영자에게 `source
    scripts/load-env.sh`를 지시한다) 도중에 그러면 안 된다(적대 리뷰 지적).
    """

    text = _read("scripts/load-env.sh")
    assert "geo_alias_split_brain" in text, "별칭 불일치 진단이 없다"
    block = text[text.index("geo_alias_split_brain") :]
    assert "exit 1" not in block.split("\nfi\n", 1)[0], (
        "별칭 불일치에서 exit 한다 — sourced 스크립트라 호출자를 죽인다"
    )


def test_compose_gives_the_frontend_a_runtime_geo_key() -> None:
    """프론트 컨테이너가 **재빌드 없이** 키를 받을 수 있어야 한다."""

    document: Any = yaml.safe_load(_read("docker-compose.yml"))
    environment = document["services"]["frontend"].get("environment") or {}
    assert "KOR_TRAVEL_GEO_API_KEY" in environment, (
        "frontend 서비스에 런타임 geo 키 env가 없다 — 이미지를 다시 굽지 않고는"
        " admin UI 지오코딩을 켤 수 없다"
    )


def test_frontend_geo_proxy_fails_closed_with_an_explicit_reason() -> None:
    """키가 없을 때 upstream의 400을 그대로 흘리지 않는다."""

    text = _read("packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts")
    assert 'GEO_API_KEY === ""' in text, "빈 키 단락 경로가 없다"
    assert "GEO_API_KEY_NOT_CONFIGURED" in text, "빈 키 응답에 명시적 사유 코드가 없다"

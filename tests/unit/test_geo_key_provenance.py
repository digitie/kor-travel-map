"""geo **소비자** 키가 VWorld 키로 떨어지는 통로를 정적으로 막는다.

`kor-travel-geo`에는 성격이 다른 자격증명 두 개가 있다:

- **VWorld 키** — geo가 *상류 VWorld로 나갈 때* 쓴다.
- **geo public API key** — map 같은 소비자가 *geo에 인증할 때* 쓴다.

geo는 VWorld 키를 `401 E0401`("VWorld 호환 인증키가 유효하지 않습니다")로 거절한다.
그런데 이름이 비슷해서 설정 사슬이 반복적으로 둘을 이어 왔고, 그때마다 **조용히**
실패했다 — `preflight()`는 존재·길이만 보므로 리소스 초기화는 통과하고, 실패는 첫
요청 시점에야 나타난다. 2026-08-13 prod에서 실제로 났다(T-VN-H46B).

## 이 가드가 하는 일과 못 하는 일

**한다**: 아래 파일들에서 geo 소비자 변수를 해석하는 **모든** 구절을 뽑아 VWorld
이름이 섞이는지 본다.

**못 한다** — 정직하게 적어 둔다:

- **중간 변수 우회.** 텍스트만 보므로 `const legacy = process.env.NEXT_PUBLIC_VWORLD_API_KEY`
  를 거쳐 넣으면 통과한다. 값 흐름 분석이 아니다.
- **`.env` 파일 자체.** 운영자의 `.env`에 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY=$VWORLD_API_KEY`
  가 있으면 보이지 않는다. **2026-08-13 사고의 실제 원인이 바로 그 축이었다** — 이
  가드는 그 사고를 막지 못했을 것이다. 저장소가 기본값으로 그 값을 **권하지** 않게
  하는 것이 여기서 할 수 있는 전부다.
- **kor-travel-docker-manager의 compose.** prod가 실제로 쓰는 정의는 그 저장소에 있다.

## 왜 개수를 고정하지 않나

이전 판은 `KOR_TRAVEL_MAP_…` 이름 하나만 앵커로 잡고 `expected=3`으로 못박았다.
그 결과 같은 파일의 `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY` 두 줄이 VWorld로 떨어지는데도
**5/5 초록**이었고, 고정된 개수가 "다 찾았다"는 착시까지 만들었다(2026-08-14 적대
리뷰 실증). 개수를 고정하는 대신 **대상 이름 전부**를 훑고, 0개면 선다 — 앵커가
빗나가 조용히 통과하는 것은 그대로 막으면서 정당한 추가에는 걸리지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]

#: geo가 인증에 받아들이는 소비자 키 이름들. VWorld 키와는 다른 자격증명이다.
_GEO_CONSUMER_VARS = (
    "KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY",
    "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",
    "KOR_TRAVEL_GEO_API_KEY",
)
_CONSUMER_RE = re.compile("|".join(re.escape(name) for name in _GEO_CONSUMER_VARS))
_VWORLD = re.compile("VWORLD", re.IGNORECASE)
#: 쉘·YAML에서 소비자 변수에 **값을 넣는 식**만 뽑는다. 줄 전체를 보면 두 가지로 샌다:
#:  - `unset A B`처럼 두 이름이 같은 줄에 있되 대입이 아닌 경우(오탐)
#:  - `--build-arg` 목록이 이어쓰기로 한 논리행이 되어 VWorld 인자와 geo 인자가
#:    같은 줄에 놓이는 경우(오탐)
#: 그래서 대입 지점부터 **그 값의 끝까지만** 자른다. 인용부호 안에서 시작했으면 닫는
#: 인용부호까지, 아니면 줄 끝까지.
_ASSIGN_NAMES = "|".join(_GEO_CONSUMER_VARS)
_EXPORT_FIRST_RE = re.compile(rf"export_first\s+(?:{_ASSIGN_NAMES})\b[^\n]*")
_ASSIGN_RE = re.compile(rf"(?P<quote>[\"']?)(?:{_ASSIGN_NAMES})\s*[:=]")

#: 줄 단위로 훑어도 완전한 파일(쉘·YAML). 이어쓰기만 합치면 한 줄이 한 구절이다.
_LINE_ORIENTED = (
    "docker-compose.yml",
    "scripts/load-env.sh",
    "scripts/docker-buildx.sh",
    "scripts/run-admin-feature-clone-live-acceptance.sh",
)
#: 구절이 여러 줄에 걸치는 파일(JS/TS). 괄호 균형으로 감싸는 그룹을 잘라 낸다.
_BRACKET_ORIENTED = (
    "scripts/frontend-build-inputs.mjs",
    "packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts",
)

_OPENERS = "([{"
_CLOSERS = ")]}"


def _read(relative: str) -> str:
    path = _ROOT / relative
    assert path.exists(), f"{relative}이 없다 — 대상이 옮겨졌다면 이 목록도 함께 옮겨라"
    return path.read_text(encoding="utf-8")


def _enclosing_slice(text: str, index: int) -> str:
    """``index``를 감싸는 가장 안쪽 괄호 그룹. 없으면 문장(세미콜론 사이)."""

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
        head = text.rfind(";", 0, index) + 1
        tail = text.find(";", index)
        return text[head : tail if tail != -1 else len(text)]
    depth = 0
    for cursor in range(start + 1, len(text)):
        char = text[cursor]
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            if depth == 0:
                return text[start : cursor + 1]
            depth -= 1
    return text[start:]


def _strip_comments(relative: str, text: str) -> str:
    """주석을 지운다.

    이 가드가 지키는 대상은 **코드**다. 주석에는 "VWorld 키로 떨어지지 않는다" 같은
    설명이 당연히 들어가고(이 저장소의 문체상 반드시 들어간다), 그것을 그대로 훑으면
    올바른 코드가 자기 설명 때문에 걸린다 — 실제로 첫 판이 그렇게 3건 오탐했다.
    """

    if relative in _LINE_ORIENTED:
        return "\n".join(re.sub(r"(?:^|(?<=\s))#.*$", "", line) for line in text.splitlines())
    without_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(re.sub(r"//.*$", "", line) for line in without_block.splitlines())


def _passages(relative: str) -> list[str]:
    """``relative``에서 geo 소비자 변수를 해석하는 구절 전부."""

    text = _strip_comments(relative, _read(relative))
    if relative in _LINE_ORIENTED:
        joined = text.replace("\\\n", " ")
        found: list[str] = []
        for line in joined.splitlines():
            found.extend(match.group(0) for match in _EXPORT_FIRST_RE.finditer(line))
            for match in _ASSIGN_RE.finditer(line):
                quote = match.group("quote")
                end = line.find(quote, match.end()) if quote else -1
                found.append(line[match.start() : end if end != -1 else len(line)])
        return found
    seen: dict[tuple[int, int], str] = {}
    for match in _CONSUMER_RE.finditer(text):
        chunk = _enclosing_slice(text, match.start())
        seen[(text.find(chunk), len(chunk))] = chunk
    return list(seen.values())


@pytest.mark.parametrize("relative", _LINE_ORIENTED + _BRACKET_ORIENTED)
def test_geo_consumer_key_never_falls_back_to_vworld(relative: str) -> None:
    passages = _passages(relative)
    assert passages, (
        f"{relative}: geo 소비자 키를 해석하는 구절을 하나도 찾지 못했다 —"
        " 대상이 사라졌다면 목록에서 빼고, 아니면 추출기를 고쳐라"
    )
    tainted = [chunk for chunk in passages if _VWORLD.search(chunk)]
    assert not tainted, (
        f"{relative}: geo 소비자 키가 VWorld 키로 떨어진다 — geo가 401(E0401)로"
        " 거절하는 값이다.\n"
        + "\n".join(f"  {' '.join(chunk.split())[:180]}" for chunk in tainted)
    )


def test_load_env_maps_the_public_alias_forward() -> None:
    """`.env.example`이 시키는 이름만 설정해도 admin UI가 키를 받는다.

    폴백 사슬을 끊는 것만으로는 부족하다. `NEXT_PUBLIC_…`를 채우던 (잘못된) 경로가
    사라졌으므로, **올바른** 경로를 대신 두지 않으면 `.env.example` 대로 설정한
    개발자의 admin UI 지오코딩이 영구히 죽는다.
    """

    joined = _read("scripts/load-env.sh").replace("\\\n", " ")
    assert re.search(
        r"export_first\s+NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY\s+"
        r"KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY\b",
        joined,
    ), "load-env.sh가 geo 소비자 키의 public 별칭을 정본 이름에서 채우지 않는다"


def test_frontend_geo_proxy_fails_closed_with_an_explicit_reason() -> None:
    """키가 없을 때 upstream의 400을 그대로 흘리지 않는다.

    geo는 키가 없으면 `400 E0100 field=key`를 돌려주는데, 그대로 통과시키면 화면에는
    "invalid request data"로 보여 **자격증명 누락이 아니라 요청 형식 오류처럼 읽힌다.**
    """

    text = _read("packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts")
    assert 'GEO_API_KEY === ""' in text, "빈 키 단락 경로가 없다"
    assert "GEO_API_KEY_NOT_CONFIGURED" in text, "빈 키 응답에 명시적 사유 코드가 없다"

"""geo **소비자** 키가 VWorld 키로 떨어지는 통로를 정적으로 막는다.

`kor-travel-geo`에는 성격이 다른 자격증명 두 개가 있다:

- **VWorld 키** — geo가 *상류 VWorld로 나갈 때* 쓴다.
- **geo public API key** — map 같은 소비자가 *geo에 인증할 때* 쓴다.

geo는 VWorld 키를 `401 E0401`("VWorld 호환 인증키가 유효하지 않습니다")로 거절한다.
그런데 이름이 비슷해서 설정 사슬이 반복적으로 둘을 이어 왔고, 그때마다 **조용히**
실패했다 — `preflight()`는 존재·길이만 보므로 리소스 초기화는 통과하고, 실패는 첫
요청 시점에야 나타난다. 2026-08-13 prod에서 실제로 났다(T-VN-H46B).

## 파일마다 보는 방식이 다르다

- **`docker-compose.yml`은 텍스트가 아니라 YAML로 읽는다.** 앵커/별칭(`&x` / `*x`)과
  인용된 매핑 키(`"NAME": …`)를 텍스트 매칭으로 쫓으면 반드시 샌다 — 적대 리뷰가
  두 형태 모두로 가드를 통과시키면서 compose가 VWorld 값으로 해석되는 것을 실증했다.
  파서가 그 둘을 해결해 주므로 **해석된 값**을 본다.
- **쉘·Dockerfile**은 줄 단위로 보되, 대입식의 **우변만** 잘라 낸다(`unset A B`나
  이어쓰기로 합쳐진 `--build-arg` 목록에서 오탐하지 않도록). 여기에 더해 소비자
  이름을 감싸는 괄호 그룹도 함께 본다 — `: "${NAME:=$( … )}"` 처럼 이어쓰기 없이
  여러 줄에 걸친 대입을 줄 단위로는 못 보기 때문이다.
- **JS/TS**는 소비자 이름을 감싸는 가장 안쪽 괄호 그룹을 본다.
- **`.env.example`류는 주석까지 본다.** 여기서 막으려는 것은 값이 아니라 **권유**다.
  2026-08-13 사고를 손으로 재현시키던 문안("현재는 VWorld 키와 동일")이 정확히
  주석이었다.

## 못 하는 것 — 정직하게 적어 둔다

- **중간 변수 우회.** 텍스트/YAML 값만 보므로 VWorld 이름을 지역 변수에 한 번 담았다가
  거쳐 넣으면 통과한다. 값 흐름 분석이 아니다.
- **운영자의 `.env` 파일 자체.** `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY=$VWORLD_API_KEY`
  가 있으면 보이지 않는다. **2026-08-13 사고의 실제 원인이 그 축이었다** — 이 가드는
  그 사고를 막지 못했을 것이다. 저장소가 그 값을 기본값으로 **권하지** 않게 하는 것이
  여기서 할 수 있는 전부이고, `.env.example`을 주석까지 훑는 이유가 그것이다.
- **kor-travel-docker-manager의 compose.** prod가 실제로 쓰는 정의는 그 저장소에 있다.

## 왜 개수를 고정하지 않나

이전 판은 이름 하나만 앵커로 잡고 `expected=3`으로 못박았다. 그 결과 같은 파일의
다른 두 줄이 VWorld로 떨어지는데도 초록이었고, 고정된 개수가 "다 찾았다"는 착시까지
만들었다. 개수 대신 **대상 파일 목록**을 고정하고 파일마다 0개면 서게 한다.
"""

from __future__ import annotations

import re
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
#: 이름 앞의 인용부호는 우변 끝을 찾는 데 쓰고, 이름과 `:`/`=` 사이의 닫는 인용부호는
#: 허용한다(`"NAME": value` 형태 — 적대 리뷰가 이 틈으로 통과시켰다).
_ASSIGN_RE = re.compile(rf"(?P<quote>[\"']?)(?:{_ASSIGN_NAMES})[\"']?\s*[:=]")

_COMPOSE = "docker-compose.yml"
_LINE_ORIENTED = (
    "scripts/load-env.sh",
    "scripts/docker-buildx.sh",
    "scripts/run-admin-feature-clone-live-acceptance.sh",
    "docker/frontend.Dockerfile",
)
_BRACKET_ORIENTED = (
    "scripts/frontend-build-inputs.mjs",
    "packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts",
)
#: 주석까지 훑는다 — 여기서 막는 것은 값이 아니라 권유다.
_ADVISORY = (
    ".env.example",
    "packages/kor-travel-map-admin/frontend/.env.example",
    "packages/kor-travel-map-api/.env.example",
)

_OPENERS = "([{"
_CLOSERS = ")]}"


def _read(relative: str) -> str:
    path = _ROOT / relative
    assert path.exists(), f"{relative}이 없다 — 대상이 옮겨졌다면 이 목록도 함께 옮겨라"
    return path.read_text(encoding="utf-8")


def _strip_line_comment(line: str) -> str:
    """인용부호 **밖**의 `#`부터 잘라 낸다.

    단순히 ` #` 이후를 버리면 따옴표 안의 `#`까지 잘려 값이 조용히 짧아진다 —
    적대 리뷰가 그 방식으로 VWorld 참조를 검사 전에 사라지게 만들었다.
    """

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


def _enclosing_group(text: str, index: int, *, require_dollar: bool = False) -> str | None:
    """``index``를 감싸는 가장 안쪽 괄호 그룹. 감싸는 것이 없으면 ``None``.

    ``require_dollar``는 쉘용이다. 쉘에서 `{ }`는 **함수 본문**이라 그냥 훑으면 함수
    전체가 한 구절이 되고, 같은 함수 안의 무관한 VWorld 대입까지 끌려 들어온다(실측
    오탐 1건). `${…}` / `$(…)` 치환만 본다 — 이어쓰기 없이 여러 줄에 걸친 대입이
    실제로 사는 곳이 거기다.
    """

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
                return text[start : cursor + 1]
            depth -= 1
    return text[start:]


def _statement_or_group(text: str, index: int) -> str:
    group = _enclosing_group(text, index)
    if group is not None:
        return group
    head = text.rfind(";", 0, index) + 1
    tail = text.find(";", index)
    return text[head : tail if tail != -1 else len(text)]


def _line_passages(relative: str) -> list[str]:
    stripped = "\n".join(_strip_line_comment(line) for line in _read(relative).splitlines())
    found: list[str] = []
    for line in stripped.replace("\\\n", " ").splitlines():
        found.extend(match.group(0) for match in _EXPORT_FIRST_RE.finditer(line))
        for match in _ASSIGN_RE.finditer(line):
            quote = match.group("quote")
            end = line.find(quote, match.end()) if quote else -1
            found.append(line[match.start() : end if end != -1 else len(line)])
    # 이어쓰기 없이 여러 줄에 걸친 대입은 줄 단위로 안 보인다 — 감싸는 괄호 그룹으로 본다.
    found.extend(
        group
        for match in _CONSUMER_RE.finditer(stripped)
        if (group := _enclosing_group(stripped, match.start(), require_dollar=True)) is not None
    )
    return found


def _bracket_passages(relative: str) -> list[str]:
    text = re.sub(r"/\*.*?\*/", "", _read(relative), flags=re.DOTALL)
    text = "\n".join(re.sub(r"//.*$", "", line) for line in text.splitlines())
    seen: dict[str, None] = {}
    for match in _CONSUMER_RE.finditer(text):
        seen[_statement_or_group(text, match.start())] = None
    return list(seen)


def _compose_passages() -> list[str]:
    """YAML로 읽어 앵커/별칭·인용 키를 **해석한 뒤** 소비자 키 값을 모은다."""

    document: Any = yaml.safe_load(_read(_COMPOSE))
    services = document.get("services", {}) if isinstance(document, dict) else {}
    found: list[str] = []
    for name, service in services.items():
        if not isinstance(service, dict):
            continue
        mappings = [service.get("environment")]
        build = service.get("build")
        if isinstance(build, dict):
            mappings.append(build.get("args"))
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            for key, value in mapping.items():
                if key in _GEO_CONSUMER_VARS:
                    found.append(f"{name}.{key}={value}")
    return found


def _passages(relative: str) -> list[str]:
    if relative == _COMPOSE:
        return _compose_passages()
    if relative in _ADVISORY:
        return [line for line in _read(relative).splitlines() if _CONSUMER_RE.search(line)]
    if relative in _LINE_ORIENTED:
        return _line_passages(relative)
    return _bracket_passages(relative)


_GUARDED = [_COMPOSE, *_LINE_ORIENTED, *_BRACKET_ORIENTED, *_ADVISORY]


@pytest.mark.parametrize("relative", _GUARDED)
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


def test_load_env_refuses_a_split_brain_between_the_two_aliases() -> None:
    """두 별칭이 **서로 다른 값**으로 설정되면 선다.

    별칭이라고 적어 두기만 하면 강제되지 않는다. 키 회전에서 운영자가 한쪽만 고치면
    backend ETL은 초록인데 admin UI만 401이 되고, 아무도 모른다 — 2026-08-13 사고와
    같은 모양이 한 겹 위에서 재현된다.
    """

    text = _read("scripts/load-env.sh")
    assert "geo_alias_split_brain" in text, (
        "load-env.sh가 두 별칭의 값 불일치를 검사하지 않는다"
    )


def test_compose_gives_the_frontend_a_runtime_geo_key() -> None:
    """프론트 컨테이너가 **재빌드 없이** 키를 받을 수 있어야 한다.

    `NEXT_PUBLIC_*`은 빌드 시점에 번들에 박히므로, 이미 만들어진 이미지에 키를 넣는
    유일한 경로는 런타임 env `KOR_TRAVEL_GEO_API_KEY`다(`route.ts`가 그것을 **먼저**
    읽는다). 이 배선이 없으면 admin UI 지오코딩은 이미지를 다시 굽기 전까지 죽어 있다.
    """

    document: Any = yaml.safe_load(_read(_COMPOSE))
    frontend = document["services"]["frontend"]
    environment = frontend.get("environment") or {}
    assert "KOR_TRAVEL_GEO_API_KEY" in environment, (
        "frontend 서비스에 런타임 geo 키 env가 없다 — 이미지를 다시 굽지 않고는"
        " admin UI 지오코딩을 켤 수 없다"
    )


def test_frontend_geo_proxy_fails_closed_with_an_explicit_reason() -> None:
    """키가 없을 때 upstream의 400을 그대로 흘리지 않는다.

    geo는 키가 없으면 `400 E0100 field=key`를 돌려주는데, 그대로 통과시키면 화면에는
    "invalid request data"로 보여 **자격증명 누락이 아니라 요청 형식 오류처럼 읽힌다.**
    """

    text = _read("packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts")
    assert 'GEO_API_KEY === ""' in text, "빈 키 단락 경로가 없다"
    assert "GEO_API_KEY_NOT_CONFIGURED" in text, "빈 키 응답에 명시적 사유 코드가 없다"

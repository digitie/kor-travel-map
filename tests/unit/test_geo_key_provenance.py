"""geo **소비자** 키가 VWorld 키로 떨어지는 통로를 정적으로 막는다.

`kor-travel-geo`에는 성격이 다른 자격증명 두 개가 있다:

- **VWorld 키** — geo가 *상류 VWorld로 나갈 때* 쓴다.
- **geo public API key** — map 같은 소비자가 *geo에 인증할 때* 쓴다.

geo는 VWorld 키를 `401 E0401`("VWorld 호환 인증키가 유효하지 않습니다")로 거절한다.
그런데 이름이 비슷해서 설정 사슬이 반복적으로 둘을 이어 왔고, 그때마다 **조용히**
실패했다. `preflight()`는 존재·길이만 보므로 리소스 초기화는 통과하고, 실패는 첫
요청 시점에 `GeoAuthNotConfiguredError`로 나타난다.

2026-08-13 prod에서 정확히 그 일이 났다(T-VN-H46B): `.env`를 올바른 값으로 고치고
api만 재생성해, dagster/daemon 두 컨테이너가 VWorld 키를 든 채로 남았다. ETL이
2026-08-07 이후 안 돌았기 때문에 **터지지 않았을 뿐**이었다.

그래서 값이 아니라 **통로**를 막는다. 아래 다섯 곳이 사고 당시 실제로 열려 있던
경로이고, 하나라도 다시 이어지면 여기서 선다.

추출기는 "찾지 못하면 통과"가 되지 않게 각각 **몇 개를 찾아야 하는지** 함께 단언한다.
파일이 재구성돼 앵커가 빗나가면 조용히 green이 되는 대신 그 사실이 실패로 나온다 —
이 저장소가 반복해서 당한 부류가 정확히 그것이다.
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
_VWORLD = re.compile("VWORLD", re.IGNORECASE)


def _read(relative: str) -> str:
    path = _ROOT / relative
    assert path.exists(), f"{relative}이 없다 — 이 가드의 대상이 사라졌다면 가드도 함께 옮겨라"
    return path.read_text(encoding="utf-8")


def _slices(text: str, anchor: re.Pattern[str], terminator: str) -> list[str]:
    """``anchor`` 매치마다 ``terminator``까지의 원문 조각을 돌려준다."""

    found: list[str] = []
    for match in anchor.finditer(text):
        end = text.find(terminator, match.end())
        assert end != -1, f"종결자 {terminator!r}를 찾지 못했다: {text[match.start():][:80]!r}"
        found.append(text[match.start() : end])
    return found


def _assert_clean(
    label: str, expressions: list[str], *, expected: int | None = None, at_least: int = 1
) -> None:
    """``expressions`` 어디에도 VWorld 이름이 없어야 한다.

    ``expected``를 주면 개수까지 고정한다 — 앵커가 빗나가 **찾지 못한 채 통과**하는
    일을 막는 장치다. 다만 같은 파일에 geo 소비자 변수를 해석하는 줄이 여럿 생기는
    것 자체는 정상인 경우가 있어(`load-env.sh`), 그럴 때는 하한만 건다. 어느 쪽이든
    0개면 선다.
    """

    if expected is not None:
        assert len(expressions) == expected, (
            f"{label}: 해석식을 {expected}개 기대했는데 {len(expressions)}개를 찾았다 —"
            " 파일이 재구성됐다면 이 추출기를 고쳐라(찾지 못한 채 통과시키지 마라)"
        )
    assert len(expressions) >= at_least, (
        f"{label}: geo 소비자 키 해석식을 하나도 찾지 못했다 — 추출기가 대상을 놓쳤다"
    )
    for expression in expressions:
        assert not _VWORLD.search(expression), (
            f"{label}: geo 소비자 키가 VWorld 키로 떨어진다 — geo가 401로 거절하는 값이다.\n"
            f"  {' '.join(expression.split())[:160]}"
        )


def test_compose_geo_key_does_not_fall_back_to_vworld() -> None:
    text = _read("docker-compose.yml")
    anchor = re.compile(r"^\s*KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY:", re.MULTILINE)
    _assert_clean("docker-compose.yml", _slices(text, anchor, "\n"), expected=3)


def test_load_env_geo_key_does_not_fall_back_to_vworld() -> None:
    # `export_first`는 역슬래시 이어쓰기를 쓴다 — 논리행으로 합쳐야 사슬 전체가 보인다.
    text = _read("scripts/load-env.sh").replace("\\\n", " ")
    lines = [line for line in text.splitlines() if line.strip().startswith("export_first")]
    resolving = [
        line
        for line in lines
        if any(re.search(rf"export_first\s+{var}\b", line) for var in _GEO_CONSUMER_VARS)
    ]
    # 개수는 고정하지 않는다 — geo 소비자 변수가 셋이라 `export_first` 줄이 여럿인 것은
    # 정상이다. 여기서 일하는 것은 VWorld 검사이고, 0개면 하한에서 선다.
    _assert_clean("scripts/load-env.sh", resolving)


def test_buildx_geo_build_arg_does_not_fall_back_to_vworld() -> None:
    text = _read("scripts/docker-buildx.sh")
    anchor = re.compile(r'--build-arg "NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY=')
    _assert_clean("scripts/docker-buildx.sh", _slices(text, anchor, "\n"), expected=1)


def test_frontend_build_inputs_geo_key_does_not_fall_back_to_vworld() -> None:
    text = _read("scripts/frontend-build-inputs.mjs")
    anchor = re.compile(r'"NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY",\n\s*envOrDefault\(')
    _assert_clean("scripts/frontend-build-inputs.mjs", _slices(text, anchor, "],"), expected=1)


def test_frontend_geo_proxy_does_not_fall_back_to_vworld() -> None:
    text = _read("packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts")
    anchor = re.compile(r"^const GEO_API_KEY =", re.MULTILINE)
    _assert_clean("frontend geo proxy route.ts", _slices(text, anchor, ";"), expected=1)

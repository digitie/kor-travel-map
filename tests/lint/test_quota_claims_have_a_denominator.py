"""쿼터에 대한 **수량 주장**이 근거 없이 돌아오지 못하게 한다.

2026-09-13까지 이 저장소는 upstream 쿼터에 대해 세 가지 틀린 말을 하고 있었다.

1. 관리자 UI가 모든 schedule에 "provider rate limit의 약 90% 이하를 목표로 한
   기본값"이라고 답했다. **그 90%는 계산된 적이 없다.** 분모(오퍼레이션당 일일
   트래픽)를 저장소가 갖고 있지 않았고 분자(주기당 요청 수)도 지표로 나오지
   않았다. 32개 중 31개가 같은 문자열을 받았으니 그것은 schedule에 대한 진술이
   아니라 상수였다.
2. ``kma_weather_max_grids_per_run``의 설명이 "초과분은 다음 run으로"라고 적었다.
   코드는 이월하지 않는다 — ``KmaWeatherGridLimitExceeded``로 **run 전체를
   거부한다**. 운영자가 대상을 늘리면 "나눠서 처리"가 아니라 "수집 정지"다.
3. ``settings.log_api_calls``가 "provider 호출 횟수를 ``ops.api_call_log``에 기록"
   한다고 적었다. 읽는 코드가 **없었고**, 그 표는 Map API로 들어오는 요청을 담는다.

셋 다 **읽는 사람이 검증할 수 없는 형태**로 틀렸다는 공통점이 있다. 그래서 여기서
잡는 것은 문구가 아니라 그 형태다.

**문자열 슬라이싱으로 판정하지 않는다.** 첫 판에서 그렇게 했다가 적대 리뷰에
잡혔다 — 마지막 삼중따옴표 뒤만 남기는 방식이라, 함수 안에 삼중따옴표가 하나 더 생기는 순간
검사 구간이 본문 밖으로 밀려나 아무것도 보지 못했고, 그 상태로 초록이었다. 지금은
AST로 **반환되는 문자열**과 **Field의 description**을 직접 읽는다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_GRAPHQL = (
    _ROOT
    / "packages"
    / "kor-travel-map-api"
    / "src"
    / "kortravelmap"
    / "api"
    / "dagster_graphql.py"
)
_SETTINGS = _ROOT / "src" / "kortravelmap" / "settings.py"
_KMA = (
    _ROOT
    / "packages"
    / "kor-travel-map-dagster"
    / "src"
    / "kortravelmap"
    / "dagster"
    / "kma_weather.py"
)
_QUOTA_DOC = _ROOT / "docs" / "etl" / "upstream-quota.md"

#: 운영자에게 돌려주는 문자열에서 "N%" 모양을 찾는다.
_PERCENT_CLAIM = re.compile(r"\d+\s*%")


def _function(path: Path, name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
            and node.name == name
        ):
            return node
    raise AssertionError(f"{path.name}에서 `{name}`을 찾지 못했다 — 유도가 낡았다")


def _returned_text(node: ast.AST) -> list[str]:
    """이 함수가 **반환하는** 문자열 조각을 전부 모은다.

    docstring은 제외된다(``Return``의 하위가 아니므로). f-string 조각과 이어붙인
    리터럴도 각각 잡히므로 ``"약 " + "90% 이하"`` 같은 회피가 통하지 않는다.
    """

    pieces: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Return) or child.value is None:
            continue
        for part in ast.walk(child.value):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                pieces.append(part.value)
    return pieces


def test_the_derivation_actually_found_the_returned_text() -> None:
    """유도의 전제. 비면 아래 단언이 공허하다."""

    pieces = _returned_text(_function(_GRAPHQL, "_schedule_note"))
    assert pieces, "`_schedule_note`가 반환하는 문자열을 하나도 찾지 못했다"
    assert sum(len(piece) for piece in pieces) > 40, (
        f"반환 문자열이 너무 짧다({pieces!r}) — 유도를 의심하라"
    )


def test_the_schedule_note_makes_no_ratio_claim() -> None:
    """분자도 분모도 없이 비율을 말하지 않는다."""

    offenders = [
        piece
        for piece in _returned_text(_function(_GRAPHQL, "_schedule_note"))
        if _PERCENT_CLAIM.search(piece)
    ]
    assert offenders == [], (
        f"schedule note가 분모 없는 비율을 말한다: {offenders}. "
        "비율을 말하려면 분자(주기당 요청 수)와 분모(오퍼레이션당 일일 한도)를 "
        "둘 다 갖고 계산해라."
    )


def test_the_schedule_note_points_at_the_measured_denominators() -> None:
    """비율 대신 실측 표를 가리킨다 — 그 표가 실재해야 한다."""

    relative = _QUOTA_DOC.relative_to(_ROOT).as_posix()
    pieces = _returned_text(_function(_GRAPHQL, "_schedule_note"))
    assert any(relative in piece for piece in pieces), (
        f"schedule note가 `{relative}`를 가리키지 않는다 — 운영자가 "
        "한도를 확인할 자리가 없어진다."
    )
    assert _QUOTA_DOC.is_file(), f"{relative}가 실재하지 않는다"


def _field_description(path: Path, field_name: str) -> str:
    """``<field>: T = Field(..., description=...)``의 description을 AST로 읽는다.

    문자열 슬라이스로 블록을 자르면 description 안에 ``\\n    name: `` 모양이
    생기는 순간 경계가 어긋난다(적대 리뷰 지적).
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != field_name:
            continue
        call = node.value
        assert isinstance(call, ast.Call), f"`{field_name}`이 Field(...) 호출이 아니다"
        for keyword in call.keywords:
            if keyword.arg == "description":
                return "".join(
                    part.value
                    for part in ast.walk(keyword.value)
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                )
        raise AssertionError(f"`{field_name}`에 description이 없다")
    raise AssertionError(f"`{field_name}` 필드를 찾지 못했다 — 유도가 낡았다")


def test_the_grid_cap_description_matches_the_code_that_enforces_it() -> None:
    """설정 설명과 그것을 강제하는 코드가 같은 말을 해야 한다.

    ``map_grid_targets``가 상한 초과분을 잘라내지만, asset은 잘린 것이 하나라도
    있으면 ``KmaWeatherGridLimitExceeded``로 run 전체를 거부한다. 즉 이 설정은
    "나눠서 처리"가 아니라 "넘으면 정지"다.
    """

    kma = _KMA.read_text(encoding="utf-8")
    assert "KmaWeatherGridLimitExceeded(" in kma, (
        "이 검사가 전제한 코드가 사라졌다 — 상한 초과가 더 이상 실패가 아니라면 "
        "설정 설명과 이 검사를 함께 고쳐라."
    )

    description = _field_description(_SETTINGS, "kma_weather_max_grids_per_run")
    assert "KmaWeatherGridLimitExceeded" in description, (
        "`kma_weather_max_grids_per_run` **설명**이 초과 시 run이 실패한다는 것을 "
        "말하지 않는다. 운영자는 '나눠서 처리된다'로 읽고 대상을 늘렸다가 "
        "수집 정지를 만난다."
    )
    assert "다음 run으로 넘어가지 않는다" in description, (
        "이월하지 않는다는 것을 명시해야 한다 — 지우려던 문구가 '초과분은 다음 "
        "run으로'였다."
    )
    stale = re.search(r"초과분은 다음 run으로(?!\s*넘어가지 않는다)", description)
    assert stale is None, (
        f"이월을 약속하는 문구가 설명에 돌아왔다: {description!r}"
    )


def test_the_api_call_log_is_not_advertised_as_an_upstream_counter() -> None:
    """`ops.api_call_log`는 upstream 요청 수를 세지 않는다 — 그렇게 적지 마라.

    쿼터 산수의 분자를 찾는 사람이 이 이름을 보고 멈춘다. 실제로 그 표를 채우는
    미들웨어는 **Map API로 들어오는 요청**의 method/path/status를 넣는다.
    """

    settings = _SETTINGS.read_text(encoding="utf-8")
    assert "log_api_calls: bool" not in settings, (
        "아무도 읽지 않는 `log_api_calls`가 돌아왔다. 되살리려면 실제로 읽는 코드와 "
        "함께 되살려라."
    )

    external = (_ROOT / "docs" / "external-apis.md").read_text(encoding="utf-8")
    offenders = [
        line
        for line in external.splitlines()
        if "api_call_log" in line and "provider" in line and "아니라" not in line
    ]
    assert offenders == [], (
        f"문서가 `ops.api_call_log`를 provider 호출 계수기로 소개한다: {offenders}"
    )

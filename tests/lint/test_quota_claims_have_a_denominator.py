"""쿼터에 대한 **수량 주장**이 근거 없이 돌아오지 못하게 한다.

2026-09-13까지 이 저장소는 upstream 쿼터에 대해 두 가지 틀린 말을 하고 있었다.

1. 관리자 UI가 모든 schedule에 "provider rate limit의 약 90% 이하를 목표로 한
   기본값"이라고 답했다. **그 90%는 계산된 적이 없다.** 분모(오퍼레이션당 일일
   트래픽)를 저장소가 갖고 있지 않았고 분자(주기당 요청 수)도 지표로 나오지
   않는다. 32개 중 31개가 같은 문자열을 받았으니 그것은 schedule에 대한 진술이
   아니라 상수였다.
2. ``kma_weather_max_grids_per_run``의 설명이 "초과분은 다음 run으로"라고 적었다.
   코드는 이월하지 않는다 — ``KmaWeatherGridLimitExceeded``로 **run 전체를
   거부한다**("partial execution is forbidden"). 운영자가 대상을 늘리면 "나눠서
   처리"가 아니라 "수집 정지"가 일어난다.

둘 다 **읽는 사람이 검증할 수 없는 형태**로 틀렸다는 공통점이 있다. 그래서 여기서
잡는 것은 문구가 아니라 그 형태다 — 비율 주장에는 분모가 따라와야 하고, 설정
설명은 그 설정을 강제하는 코드와 같은 말을 해야 한다.
"""

from __future__ import annotations

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


def _schedule_note_source() -> str:
    """``_schedule_note`` 함수 본문만 잘라 온다 — 파일 전체를 보면 주석에 걸린다."""

    source = _GRAPHQL.read_text(encoding="utf-8")
    start = source.index("def _schedule_note(")
    end = source.index("\ndef ", start + 1)
    return source[start:end]


def test_the_slice_actually_found_the_function() -> None:
    """유도의 전제. 비면 아래 단언이 공허하다."""

    body = _schedule_note_source()
    assert "return" in body
    assert len(body) > 200, "함수 본문이 너무 짧다 — 자르는 위치를 의심하라"


def test_the_schedule_note_makes_no_ratio_claim() -> None:
    """분자도 분모도 없이 비율을 말하지 않는다."""

    body = _schedule_note_source()
    # docstring은 그 주장이 왜 틀렸는지를 설명하므로 숫자가 남아 있어도 된다.
    # 검사는 **운영자에게 가는 문자열**만 본다.
    returned = re.findall(r'"([^"]*)"', body.split('"""')[-1])
    offenders = [text for text in returned if _PERCENT_CLAIM.search(text)]
    assert offenders == [], (
        f"schedule note가 분모 없는 비율을 말한다: {offenders}. "
        "비율을 말하려면 분자(주기당 요청 수)와 분모(오퍼레이션당 일일 한도)를 "
        "둘 다 갖고 계산해라 — 지금은 분모만 실측돼 있다."
    )


def test_the_schedule_note_points_at_the_measured_denominators() -> None:
    """비율 대신 실측 표를 가리킨다 — 그 표가 실재해야 한다."""

    body = _schedule_note_source()
    relative = _QUOTA_DOC.relative_to(_ROOT).as_posix()
    assert relative in body, (
        f"schedule note가 `{relative}`를 가리키지 않는다 — 운영자가 "
        "한도를 확인할 자리가 없어진다."
    )
    assert _QUOTA_DOC.is_file(), f"{relative}가 실재하지 않는다"


def test_the_grid_cap_description_matches_the_code_that_enforces_it() -> None:
    """설정 설명과 그것을 강제하는 코드가 같은 말을 해야 한다.

    ``map_grid_targets``가 상한 초과분을 잘라내지만, asset은 잘린 것이 하나라도
    있으면 ``KmaWeatherGridLimitExceeded``로 run 전체를 거부한다. 즉 이 설정은
    "나눠서 처리"가 아니라 "넘으면 정지"다.
    """

    kma = _KMA.read_text(encoding="utf-8")
    raises_on_overflow = "KmaWeatherGridLimitExceeded(" in kma
    assert raises_on_overflow, (
        "이 검사가 전제한 코드가 사라졌다 — 상한 초과가 더 이상 실패가 아니라면 "
        "설정 설명과 이 검사를 함께 고쳐라."
    )

    settings = _SETTINGS.read_text(encoding="utf-8")
    start = settings.index("kma_weather_max_grids_per_run: int = Field(")
    # 다음 필드 선언까지가 이 필드의 블록이다.
    following = re.search(r"\n    \w+: ", settings[start + 1 :])
    assert following is not None, "다음 필드를 찾지 못했다 — 자르는 규칙을 의심하라"
    field_block = settings[start : start + 1 + following.start()]
    assert "KmaWeatherGridLimitExceeded" in field_block, (
        "`kma_weather_max_grids_per_run` 설명이 초과 시 run이 실패한다는 것을 "
        "말하지 않는다. 운영자는 '나눠서 처리된다'로 읽고 대상을 늘렸다가 "
        "수집 정지를 만난다."
    )

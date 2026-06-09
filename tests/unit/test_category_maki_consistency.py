"""T-017 drift gate — Python category↔TS maki 매핑 1:1 검증 (ADR-029/043).

`packages/map-marker-react/`는 모노레포 내부 share 모듈(npm 게시 보류, ADR-043)로,
provider 변환기가 emit하는 `marker_icon`(= Python category catalog의 mapbox maki
아이콘 이름)을 글리프로 렌더링한다. Python 쪽이 새 카테고리/아이콘을 추가했는데 TS
``MAKI_GLYPH``에 글리프가 없으면 마커가 첫 글자 fallback으로 떨어진다 — 이 drift를
컴파일이 아니라 테스트로 잡는다.

계약: **Python category catalog가 쓰는 모든 maki 아이콘 이름은 TS ``MAKI_GLYPH``의
키로 존재해야 한다**(TS는 provider 직접 emit/특보 아이콘까지 커버하는 상위집합 허용).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from krtour.map.category import PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES

pytestmark = pytest.mark.unit

_MAKI_TS = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "map-marker-react"
    / "src"
    / "maki.ts"
)


def _ts_maki_glyph_keys() -> set[str]:
    """TS ``maki.ts``의 ``MAKI_GLYPH`` 객체 키(maki 이름)를 파싱한다."""
    text = _MAKI_TS.read_text(encoding="utf-8")
    marker = "MAKI_GLYPH"
    assert marker in text, f"{_MAKI_TS}에 MAKI_GLYPH 없음"
    block = text.split(marker, 1)[1]
    # `"name": "..."` 형태의 키만. (maki 이름은 소문자/숫자/하이픈.)
    return set(re.findall(r'"([a-z0-9-]+)"\s*:', block))


def test_maki_ts_source_exists() -> None:
    assert _MAKI_TS.is_file(), f"map-marker-react maki.ts 누락: {_MAKI_TS}"


def test_python_category_maki_icons_are_renderable_by_ts() -> None:
    """Python category가 쓰는 maki 아이콘 이름은 전부 TS MAKI_GLYPH에 있어야 한다."""
    ts_keys = _ts_maki_glyph_keys()
    assert ts_keys, "TS MAKI_GLYPH 키 파싱 실패(0개)"
    missing = sorted(
        name for name in PLACE_CATEGORY_MAPBOX_MAKI_ICON_VALUES if name not in ts_keys
    )
    assert not missing, (
        "Python category가 쓰는 maki 아이콘이 TS MAKI_GLYPH에 없음(drift) — "
        f"packages/map-marker-react/src/maki.ts에 추가 필요: {missing}"
    )

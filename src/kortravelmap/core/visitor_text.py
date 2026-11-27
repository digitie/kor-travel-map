"""방문 안내(``PlaceVisitorInfo``) 원문 정리 — provider 공용 순수 함수(ADR-126).

원문은 **가공하지 않는다**. ``<br>``은 줄바꿈으로, 나머지 태그는 걷고, HTML entity를 풀고,
줄마다 공백을 하나로 접는다. 그 밖의 재작성·요약은 하지 않는다. 모델 상한을 넘는 극단 값만
상한에서 자른다(한 행 때문에 run 전체가 검증 실패로 멈추지 않게).
"""

from __future__ import annotations

import re
from html import unescape
from typing import Final

__all__ = ["DESCRIPTION_MAX", "SHORT_TEXT_MAX", "clean_text", "http_url"]

DESCRIPTION_MAX: Final = 8000
SHORT_TEXT_MAX: Final = 2000

_TAG_RE: Final = re.compile(r"<[^>]+>")
_BR_RE: Final = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTTP_URL_RE: Final = re.compile(r"^https?://\S+$")
_PLACEHOLDERS: Final = frozenset({"-", "--", "null", "none", "n/a"})
"""값이 아닌 자리표시. "없음"은 넣지 않는다 — 휴무 "없음"(연중무휴)·주차 "없음"처럼 뜻이 있다."""


def clean_text(value: object, *, limit: int = SHORT_TEXT_MAX) -> str | None:
    """원문 → 정리한 원문(없거나 자리표시만 있으면 ``None``)."""
    if value is None:
        return None
    text = str(value)
    if not text.strip():
        return None
    text = _TAG_RE.sub("", _BR_RE.sub("\n", text))
    lines = [" ".join(unescape(line).split()) for line in text.splitlines()]
    joined = "\n".join(line for line in lines if line)
    if not joined or joined.casefold() in _PLACEHOLDERS:
        return None
    return joined[:limit]


def http_url(value: object) -> str | None:
    """공백 없는 http(s) URL만 통과시킨다(그 밖은 ``None``)."""
    text = str(value or "").strip()
    if len(text) < 8 or len(text) > 2048 or not _HTTP_URL_RE.match(text):
        return None
    return text

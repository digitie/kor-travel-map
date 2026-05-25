"""``krtour.map.core.types`` — KST aware datetime helper + 기본 타입.

ADR-019에 따라 모든 datetime은 KST aware (Asia/Seoul). naive datetime은
DTO/DB layer 어디에도 들어가면 안 된다.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

__all__ = ["KST", "kst_now"]


KST: ZoneInfo = ZoneInfo("Asia/Seoul")
"""Korea Standard Time (Asia/Seoul) — ADR-019."""


def kst_now() -> datetime:
    """현재 시각을 KST aware ``datetime``으로 반환한다.

    ADR-019 — 모든 datetime은 timezone aware. 본 라이브러리에서 ``datetime.
    utcnow()`` / ``datetime.now()`` 등 naive 호출은 금지. Pydantic
    ``default_factory=kst_now``로 일관 사용.
    """
    return datetime.now(KST)

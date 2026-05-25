"""``krtour.map.dto._time`` — KST aware datetime helpers.

ADR-019에 따라 모든 datetime은 KST aware (Asia/Seoul). 본 모듈은 dto 레이어
내부에 위치한다 — dto 모델의 ``default_factory=kst_now``로 자기 자신 안에서
참조하기 위함. core/infra/providers/client는 ``krtour.map.core``에서 re-export된
``kst_now``를 사용한다 (의존 방향 보존: ``dto → core → infra → ...``).

ADR 참조
--------
- ADR-002 — 의존 방향 ``dto → core → infra → providers → client → cli``
  (dto는 core를 import하지 않는다).
- ADR-019 — 모든 datetime은 KST aware. ``naive datetime`` 입력은
  ``ValidationError``.

설계 노트
---------
- 본 PR(#22)에서 import-linter 활성화 시 ``dto/feature.py``가 ``core``의
  ``kst_now``를 import하던 부분이 layered 계약 위반으로 감지됨. 정의를 dto
  레이어로 이전해 위반 해소.
- 공개 API (``from krtour.map.core import kst_now``)는 ``core/types.py``의
  re-export로 보존됨 — 호출 측 코드 변경 0.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

__all__ = ["KST", "kst_now"]


KST: ZoneInfo = ZoneInfo("Asia/Seoul")
"""한국 표준시 ``ZoneInfo`` 인스턴스. ``ADR-019``에 따라 본 라이브러리의 모든
``datetime``은 본 tzinfo로 aware해야 한다."""


def kst_now() -> datetime:
    """현재 시각을 KST aware ``datetime``으로 반환한다.

    ``datetime.now(KST)``와 동치이나 명시적 함수로 두어:
    1. ``default_factory=kst_now`` Pydantic 필드에서 일관 사용.
    2. 테스트에서 ``monkeypatch.setattr``로 mock 가능.
    """
    return datetime.now(KST)

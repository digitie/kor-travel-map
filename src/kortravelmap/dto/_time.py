"""``kortravelmap.dto._time`` — KST aware datetime helpers + 공용 validator.

ADR-019에 따라 모든 datetime은 KST aware (Asia/Seoul). 본 모듈은 dto 레이어
내부에 위치한다 — dto 모델의 ``default_factory=kst_now``로 자기 자신 안에서
참조하기 위함. core/infra/providers/client는 ``kortravelmap.core``에서 re-export된
``kst_now``를 사용한다 (의존 방향 보존: ``dto → core → infra → ...``).

ADR 참조
--------
- ADR-002 — 의존 방향 ``dto → core → infra → providers → client → cli``
  (dto는 core를 import하지 않는다).
- ADR-019 — 모든 datetime은 timezone aware. ``naive datetime`` 입력은
  ``ValidationError``. 본 라이브러리는 KST 기본이나, aware datetime (UTC 등 다른
  tz 포함)은 그대로 받고 직렬화/저장 직전 KST 변환은 호출자(provider 변환 함수)의
  책임 (ADR-019 §결과/부정).

설계 노트
---------
- 본 PR(#22)에서 import-linter 활성화 시 ``dto/feature.py``가 ``core``의
  ``kst_now``를 import하던 부분이 layered 계약 위반으로 감지됨. 정의를 dto
  레이어로 이전해 위반 해소.
- 공개 API (``from kortravelmap.core import kst_now``)는 ``core/types.py``의
  re-export로 보존됨 — 호출 측 코드 변경 0.
- PR#24 review report P0-2: 모든 DTO datetime 필드에 동일 validator 적용.
  ``check_aware_datetime``을 공용 함수로 박아 매 모델마다 재구현 회피.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

__all__ = ["KST", "kst_now", "check_aware_datetime"]


KST: ZoneInfo = ZoneInfo("Asia/Seoul")
"""한국 표준시 ``ZoneInfo`` 인스턴스. ``ADR-019``에 따라 본 라이브러리의 모든
``datetime``은 본 tzinfo로 aware해야 한다 (또는 다른 aware tz — 변환 책임은
호출자)."""


def kst_now() -> datetime:
    """현재 시각을 KST aware ``datetime``으로 반환한다.

    ``datetime.now(KST)``와 동치이나 명시적 함수로 두어:
    1. ``default_factory=kst_now`` Pydantic 필드에서 일관 사용.
    2. 테스트에서 ``monkeypatch.setattr``로 mock 가능.
    """
    return datetime.now(KST)


def check_aware_datetime(value: datetime | None) -> datetime | None:
    """ADR-019 강제: ``naive datetime`` 입력은 ``ValueError``.

    Pydantic ``field_validator``의 helper로 사용한다. ``None``은 그대로 통과 —
    선택적 필드에서 자유롭게 사용 가능.

    Parameters
    ----------
    value
        검증 대상 datetime 또는 ``None``.

    Returns
    -------
    datetime | None
        입력 그대로 (변환 안 함 — provider 변환 함수가 KST로 변환 책임).

    Raises
    ------
    ValueError
        ``value.tzinfo is None`` (naive datetime).

    Examples
    --------
    >>> from datetime import datetime, UTC
    >>> from zoneinfo import ZoneInfo
    >>> check_aware_datetime(datetime.now(ZoneInfo("Asia/Seoul")))  # OK
    >>> check_aware_datetime(datetime.now(UTC))  # OK (다른 aware tz)
    >>> check_aware_datetime(None)  # OK
    >>> check_aware_datetime(datetime(2026, 1, 1))  # raises ValueError
    Traceback (most recent call last):
        ...
    ValueError: datetime must be timezone-aware ...
    """
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError(
            "datetime must be timezone-aware (KST 또는 다른 aware tz). "
            "naive datetime은 금지 (ADR-019)."
        )
    return value

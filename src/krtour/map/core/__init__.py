"""``krtour.map.core`` — 순수 함수 + 도메인 룰 + 예외 계층.

``core/``는 비즈니스 로직만 (Protocol 의존). DB/HTTP/외부 client 의존 없음.
``infra/``/``providers/``는 core를 import하지만 그 반대는 금지 (ADR-002 의존
방향).

ADR 참조
--------
- ADR-002 — async-only API (sync 인터페이스 추가 금지)
- ADR-009 — ``feature_id`` 결정적 생성 (``make_feature_id``)
- ADR-016 — Record Linkage 가중치 0.45·name + 0.35·spatial + 0.20·category,
  임계값 0.85/0.65
- ADR-019 — KST aware datetime (``kst_now``)
- ADR-030 — ``functools.cache`` narrow 예외
- ADR-033 — ``feature_consistency_reports`` Phase 1 (F1~F3, Sprint 3)
"""

from __future__ import annotations

from .types import KST, kst_now

__all__ = ["KST", "kst_now"]
# Sprint 1+~에서 추가 예정:
#   exceptions: ValidationError, FeatureNotFoundError, ...
#   make_feature_id (ADR-009 결정적 생성, PR#20)
#   scoring stub (ADR-016, 실 검증은 Sprint 2 휴게소 sibling)
#   transformer_4326_to_5179 (ADR-030 narrow cache, infra/crs.py로 이동 가능)

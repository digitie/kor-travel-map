"""``krtour.map.core`` — 순수 함수 + 도메인 룰 + 예외 계층.

``core/``는 비즈니스 로직만 (Protocol 의존). DB/HTTP/외부 client 의존 없음.
``infra/``/``providers/``는 core를 import하지만 그 반대는 금지 (ADR-002 의존
방향).

**Sprint 1 PR#20에서 실제 코드 작성 예정** — 본 PR#17은 placeholder.

ADR 참조
--------
- ADR-002 — async-only API (sync 인터페이스 추가 금지)
- ADR-009 — ``feature_id`` 결정적 생성 (``make_feature_id``)
- ADR-016 — Record Linkage 가중치 0.45·name + 0.35·spatial + 0.20·category,
  임계값 0.85/0.65
- ADR-030 — ``functools.cache`` narrow 예외 (``pyproj.Transformer`` singleton
  은 ``core/`` 또는 ``infra/crs.py``에)
- ADR-033 — ``feature_consistency_reports`` Phase 1 (F1~F3, Sprint 3)
"""

from __future__ import annotations

__all__: list[str] = []
# Sprint 1 PR#20에서 채워질 예정:
#   exceptions: ValidationError, FeatureNotFoundError,
#     SourceRecordNotFoundError, DuplicateFeatureError, ImportJobConflictError,
#     ProviderError, FileStoreError
#   make_feature_id (ADR-009 결정적 생성)
#   scoring stub (ADR-016, 실 검증은 Sprint 2 휴게소 sibling)
#   kst_now (ADR-019)
#   transformer_4326_to_5179 (ADR-030 narrow cache, pyproj.Transformer
#     singleton)
#
# Sprint 3 PR (T-201a)에서 추가:
#   integrity.py — F1~F3 (orphan source / detail 누락 / CRS drift)

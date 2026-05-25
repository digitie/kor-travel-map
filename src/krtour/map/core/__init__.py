"""``krtour.map.core`` — 순수 함수 + 도메인 룰 + 예외 계층.

``core/``는 비즈니스 로직만 (Protocol 의존). DB/HTTP/외부 client 의존 없음.
``infra/``/``providers/``는 core를 import하지만 그 반대는 금지 (ADR-002 의존
방향).

**Sprint 1 PR#19**: ``types.py`` — ``KST``/``kst_now`` (ADR-019).
**Sprint 1 PR#20 (본 PR)**: ``exceptions`` 7종 (ADR backend-package §5) +
``ids.py`` ``make_feature_id`` (ADR-009 결정적 SHA1).
**Sprint 1 PR#21+**: ``ids.py``의 나머지 helper (``make_source_record_key`` /
``make_payload_hash``), ``scoring`` (ADR-016 Coordinate 의존), ``protocols``,
``providers`` (provider 이름 정규화), ``weather`` (build_weather_card),
``infra/crs.py`` (pyproj.Transformer ADR-030 narrow cache).
**Sprint 3 PR (T-201a)**: ``integrity.py`` — F1~F3 (orphan source / detail
누락 / CRS drift).

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

from krtour.map.core.exceptions import (
    DuplicateFeatureError,
    FeatureNotFoundError,
    FileStoreError,
    ImportJobConflictError,
    KrtourMapError,
    ProviderError,
    SourceRecordNotFoundError,
    ValidationError,
)
from krtour.map.core.ids import FEATURE_ID_HASH_LENGTH, make_feature_id
from krtour.map.core.types import KST, kst_now

__all__ = [
    # types (PR#19, ADR-019)
    "KST",
    "kst_now",
    # exceptions (PR#20, docs/backend-package.md §5)
    "KrtourMapError",
    "ValidationError",
    "FeatureNotFoundError",
    "SourceRecordNotFoundError",
    "DuplicateFeatureError",
    "ImportJobConflictError",
    "ProviderError",
    "FileStoreError",
    # ids (PR#20, ADR-009)
    "make_feature_id",
    "FEATURE_ID_HASH_LENGTH",
]

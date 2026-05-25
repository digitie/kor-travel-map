"""``krtour.map.dto`` — Pydantic v2 입력/출력 DTO.

본 모듈은 ``Feature`` + 7개 detail kind (place/event/notice/price/weather/
route/area) + ``WeatherValue``/``PriceValue``/``FeatureFile``/``SourceRecord``
/``OpeningTime``/``ProviderSyncState`` 등 모든 공개 DTO를 노출한다.

DB/FastAPI 의존 없음 (ADR-001 의존 방향 — dto는 최하단). ``feature.detail``은
자유 dict 금지 (ADR-018, ``DETAIL_MODELS`` 분기 강제). 모든 datetime은
KST aware (ADR-019).

**Sprint 1 PR#19에서 실제 코드 작성 예정** — 본 PR#17은 placeholder.

ADR 참조
--------
- ADR-001 — 의존 방향 ``category → dto → core → infra → providers → client → cli``
- ADR-018 — ``Feature.detail`` 자유 dict 금지
- ADR-019 — KST aware datetime만 허용
- ADR-027 — ``NOTICE_TYPES`` 14건 (``access_restriction``/``fire_alert`` 추가),
  ``AreaDetail.area_kind`` Literal에 ``hazard_zone`` 추가

자세히는 ``docs/feature-model.md`` + ``docs/notice-feature-etl.md``.
"""

from __future__ import annotations

__all__: list[str] = []
# Sprint 1 PR#19에서 채워질 예정:
#   Feature, FeatureKind, FeatureBundle,
#   PlaceDetail, EventDetail, NoticeDetail, RouteDetail, AreaDetail,
#   WeatherValue, PriceValue, FeatureFile, SourceRecord,
#   OpeningTime, OpeningPeriod, SpecialOpeningDay,
#   ProviderSyncState, ImportJob, AddressMatchReport, Coordinate,
#   NOTICE_TYPES (14건), normalize_notice_type, ...

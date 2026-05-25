"""``python-krtour-map`` — TripMate 지도 데이터 정규화·저장 함수 라이브러리.

본 패키지는 한국 공공 API(``python-*-api``) 결과를 단일 ``Feature`` 계약으로
정규화하고 PostgreSQL + PostGIS에 저장한다. TripMate는 본 패키지를 직접
import하여 함수로 호출한다 (ADR-003, REST 없음).

import 경로
-----------
- 메인 라이브러리: ``from krtour.map import ...`` (PEP 420 implicit namespace
  ``krtour``, ADR-022).
- 디버그 UI: ``from krtour.map_debug_ui import ...`` (별도 distribution,
  같은 ``krtour`` namespace, ADR-020).

핵심 진입점 (Sprint 2~5에서 구현):
    >>> from krtour.map import AsyncKrtourMapClient
    >>> async with AsyncKrtourMapClient(engine=..., providers=...) as client:
    ...     features = await client.features_in_bounds(bbox, kinds=["place"])

ADR 참조
--------
- ADR-002 — async-only API (sync 인터페이스 추가 금지)
- ADR-003 — TripMate 연계는 함수 직접 호출 (REST 없음)
- ADR-020 — 디버그 REST/UI는 별도 패키지 ``krtour-map-debug-ui``
- ADR-022 — PEP 420 implicit namespace ``krtour``
- ADR-030 — in-memory 캐시 금지 (``functools.cache`` 한정 narrow 예외)
- ADR-034 — Provider 9단계 구현 순서

자세히는 ``docs/architecture.md``, ``docs/decisions.md``.
"""

from __future__ import annotations

__all__ = [
    "__version__",
]

# PyPI distribution version. pyproject.toml의 ``[project] version``과 동기.
# 코드 작성 단계 진입 직후 (Sprint 1)이므로 0.2.0-dev 유지. Sprint 5 운영
# 진입 시점에 0.2.0으로 finalize.
__version__: str = "0.2.0-dev"

# 공개 API는 Sprint 2~5에서 점진 추가:
#   from krtour.map.client import AsyncKrtourMapClient  # Sprint 2
#   from krtour.map.dto import (
#       Feature, FeatureKind, FeatureBundle,
#       PlaceDetail, EventDetail, NoticeDetail, RouteDetail, AreaDetail,
#       WeatherValue, PriceValue, FeatureFile,
#   )  # Sprint 1 (PR#19)
#   from krtour.map.category import (
#       PlaceCategory, PlaceCategoryCode, PlaceCategoryTier1Code,
#       PLACE_CATEGORY_DEFINITIONS, get_category, ...,
#   )  # Sprint 1 (PR#18)
#   from krtour.map.settings import KrtourMapSettings  # Sprint 1 (본 PR#17)

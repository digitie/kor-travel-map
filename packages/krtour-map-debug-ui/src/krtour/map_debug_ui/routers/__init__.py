"""``krtour.map_debug_ui.routers`` — FastAPI 라우터 namespace.

prefix 분리 (ADR-035):
- ``/debug/...`` — 개발자용
- ``/admin/...`` — 운영자용 (Sprint 4+)
- ``/ops/...`` — 옵저버빌리티 (Sprint 3+)
- ``/features/...`` — feature 조회 (Sprint 2 적재 후)

본 PR(#35)에서는 ``health`` + ``version``만. 나머지는 후속 PR.
"""

from __future__ import annotations

from krtour.map_debug_ui.routers.etl import router as etl_router
from krtour.map_debug_ui.routers.features import router as features_router
from krtour.map_debug_ui.routers.geocoding import router as geocoding_router
from krtour.map_debug_ui.routers.health import router as health_router
from krtour.map_debug_ui.routers.mois_detail import router as mois_detail_router
from krtour.map_debug_ui.routers.version import router as version_router

__all__ = [
    "health_router",
    "version_router",
    "etl_router",
    "features_router",
    "geocoding_router",
    "mois_detail_router",
]

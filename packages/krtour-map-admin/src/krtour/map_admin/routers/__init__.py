"""``krtour.map_admin.routers`` — FastAPI 라우터 namespace.

prefix 분리 (ADR-035):
- ``/debug/...`` — 개발자용
- ``/admin/...`` — 운영자용 (Sprint 4+)
- ``/ops/...`` — 옵저버빌리티 (Sprint 3+)
- ``/features/...`` — feature 조회 (Sprint 2 적재 후)

본 PR(#35)에서는 ``health`` + ``version``만. 나머지는 후속 PR.
"""

from __future__ import annotations

from krtour.map_admin.routers.admin_features import router as admin_features_router
from krtour.map_admin.routers.dagster import router as dagster_router
from krtour.map_admin.routers.dedup_review import router as dedup_review_router
from krtour.map_admin.routers.etl import router as etl_router
from krtour.map_admin.routers.feature_update_requests import (
    router as feature_update_requests_router,
)
from krtour.map_admin.routers.features import (
    router as features_router,
)
from krtour.map_admin.routers.features import (
    tripmate_router,
)
from krtour.map_admin.routers.health import router as health_router
from krtour.map_admin.routers.mois_detail import router as mois_detail_router
from krtour.map_admin.routers.offline_uploads import router as offline_uploads_router
from krtour.map_admin.routers.ops import router as ops_router
from krtour.map_admin.routers.poi_cache_targets import (
    router as poi_cache_targets_router,
)
from krtour.map_admin.routers.version import router as version_router

__all__ = [
    "health_router",
    "version_router",
    "etl_router",
    "admin_features_router",
    "dedup_review_router",
    "feature_update_requests_router",
    "poi_cache_targets_router",
    "features_router",
    "tripmate_router",
    "mois_detail_router",
    "offline_uploads_router",
    "ops_router",
    "dagster_router",
]

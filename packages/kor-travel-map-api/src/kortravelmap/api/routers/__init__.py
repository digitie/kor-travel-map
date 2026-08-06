"""``kortravelmap.api.routers`` — FastAPI 라우터 namespace.

prefix 분리 (ADR-035):
- ``/debug/...`` — 개발자용
- ``/admin/...`` — 운영자용 (Sprint 4+)
- ``/ops/...`` — 옵저버빌리티 (Sprint 3+)
- ``/features/...`` — feature 조회 (Sprint 2 적재 후)

본 PR(#35)에서는 ``health`` + ``version``만. 나머지는 후속 PR.
"""

from __future__ import annotations

from kortravelmap.api.routers.admin_auth import router as admin_auth_router
from kortravelmap.api.routers.admin_backups import (
    restore_router as admin_restore_router,
)
from kortravelmap.api.routers.admin_backups import router as admin_backups_router
from kortravelmap.api.routers.admin_features import router as admin_features_router
from kortravelmap.api.routers.admin_files import router as admin_files_router
from kortravelmap.api.routers.admin_issues import router as admin_issues_router
from kortravelmap.api.routers.cache_target_streams import (
    admin_router as admin_cache_target_streams_router,
)
from kortravelmap.api.routers.cache_target_streams import (
    ops_router as ops_cache_target_streams_router,
)
from kortravelmap.api.routers.cache_target_streams import (
    service_router as service_cache_target_streams_router,
)
from kortravelmap.api.routers.categories import router as categories_router
from kortravelmap.api.routers.curated import admin_router as admin_curated_router
from kortravelmap.api.routers.curated import router as curated_router
from kortravelmap.api.routers.curations import admin_router as admin_curations_router
from kortravelmap.api.routers.curations import router as curations_router
from kortravelmap.api.routers.dedup_review import (
    feature_router as feature_dedup_review_router,
)
from kortravelmap.api.routers.dedup_review import router as dedup_review_router
from kortravelmap.api.routers.enrichment_review import (
    feature_router as feature_enrichment_review_router,
)
from kortravelmap.api.routers.enrichment_review import (
    router as enrichment_review_router,
)
from kortravelmap.api.routers.feature_alias_maps import (
    service_router as service_feature_alias_maps_router,
)
from kortravelmap.api.routers.features import (
    router as features_router,
)
from kortravelmap.api.routers.mois_detail import router as mois_detail_router
from kortravelmap.api.routers.offline_uploads import router as offline_uploads_router
from kortravelmap.api.routers.ops import router as ops_router
from kortravelmap.api.routers.ops_contract_fixtures import (
    router as ops_contract_fixtures_router,
)
from kortravelmap.api.routers.ops_datasets import router as ops_datasets_router
from kortravelmap.api.routers.ops_live import router as ops_live_router
from kortravelmap.api.routers.ops_logs import router as ops_logs_router
from kortravelmap.api.routers.ops_pipeline import router as ops_pipeline_router
from kortravelmap.api.routers.poi_cache_targets import (
    router as poi_cache_targets_router,
)
from kortravelmap.api.routers.public_providers import router as public_providers_router
from kortravelmap.api.routers.public_status import router as public_status_router
from kortravelmap.api.routers.public_views import router as public_views_router
from kortravelmap.api.routers.weather import admin_router as admin_weather_router
from kortravelmap.api.routers.weather import router as weather_router

__all__ = [
    "admin_backups_router",
    "admin_auth_router",
    "admin_cache_target_streams_router",
    "admin_restore_router",
    "admin_weather_router",
    "admin_features_router",
    "admin_files_router",
    "admin_curated_router",
    "admin_curations_router",
    "admin_issues_router",
    "dedup_review_router",
    "feature_dedup_review_router",
    "enrichment_review_router",
    "feature_enrichment_review_router",
    "poi_cache_targets_router",
    "features_router",
    "categories_router",
    "mois_detail_router",
    "offline_uploads_router",
    "ops_router",
    "ops_contract_fixtures_router",
    "ops_cache_target_streams_router",
    "ops_datasets_router",
    "ops_live_router",
    "ops_logs_router",
    "ops_pipeline_router",
    "public_status_router",
    "public_providers_router",
    "public_views_router",
    "service_cache_target_streams_router",
    "service_feature_alias_maps_router",
    "weather_router",
    "curated_router",
    "curations_router",
]

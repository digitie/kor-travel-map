"""``kortravelmap.infra`` — DB 어댑터 + 객체 저장소 + sync state.

``infra/``는 SQLAlchemy 2 async + GeoAlchemy2 + asyncpg + raw SQL (`sqlalchemy.
text()`)을 사용한다. ORM 모델은 매핑만 — 모든 쿼리는 `infra/*_repo.py`의
raw SQL (ADR-004).

**Sprint 1 PR#21 (본 PR)**:
- ``crs.py`` — ``pyproj.Transformer`` singleton (ADR-030 narrow cache,
  ``transformer_4326_to_5179`` / ``transformer_5179_to_4326``).
- ``db.py`` — async engine + session factory (``make_async_engine`` /
  ``make_async_session_factory`` / ``normalize_async_dsn``).
- ``tests/integration/conftest.py`` — testcontainers PostGIS fixture base
  (``pg_container`` / ``pg_engine`` / ``pg_session`` / ``feature_schema``).

**Sprint 2 첫 provider 적재 직전 PR**:
- ``models.py`` — SQLAlchemy 2 매핑 (``Feature``/``PlaceDetail``/...)
- ``feature_repo.py`` — raw SQL repository (``_SQL`` 상수 + ``text()``)
- ``source_repo.py``/``sync_repo.py``/``jobs_repo.py``
- ``scope_repo.py``/``feature_update_repo.py`` — ADR-045 feature update request 해석/큐
- ``file_store.py`` — S3 호환 객체 저장소 (RustFS)

ADR 참조
--------
- ADR-002 — async-only (SQLAlchemy 2 async + asyncpg)
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL (EXPLAIN 친화 + 인덱스 hint 자유)
- ADR-007 — PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- ADR-008 — extension은 ``x_extension`` schema에 격리
- ADR-011 — 작업 큐 ``ops.import_jobs`` 영속화 + advisory lock + SKIP LOCKED
- ADR-012 — 공간 쿼리 입력 좌표 1회 변환, 반경은 ``coord_5179`` (meter)
- ADR-013 — bulk insert ``psycopg.copy_*`` 우선, 30k 안전 마진
- ADR-015 — 객체 저장소 S3 호환 (RustFS 1차, MinIO/Ceph/R2 swap)
- ADR-030 — ``functools.cache`` narrow 예외 (``pyproj.Transformer`` singleton)
"""

from __future__ import annotations

from kortravelmap.infra.admin_feature_repo import (
    AdminFeaturePage,
    AdminFeatureRow,
    DedupReviewPage,
    DedupReviewRow,
    FeatureDeactivateResult,
    FeatureOverride,
    deactivate_feature,
    list_admin_features,
    list_dedup_reviews,
    merge_dedup_review,
    set_dedup_review_decision,
)
from kortravelmap.infra.advisory_lock import (
    advisory_lock,
    advisory_lock_key,
    try_advisory_lock,
)
from kortravelmap.infra.crs import (
    EPSG_UTM_K,
    EPSG_WGS84,
    project_to_4326,
    project_to_5179,
    transformer_4326_to_5179,
    transformer_5179_to_4326,
)
from kortravelmap.infra.db import (
    make_async_engine,
    make_async_session_factory,
    normalize_async_dsn,
)
from kortravelmap.infra.dedup_refresh_repo import (
    DEDUP_REFRESH_DEFAULT_LIMIT,
    DedupRefreshFeature,
    DedupRefreshScope,
    list_dedup_refresh_features,
)
from kortravelmap.infra.dedup_repo import (
    DedupQueueResult,
    enqueue_dedup_candidate,
    enqueue_dedup_candidates,
    pending_dedup_reviews,
)
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    FeatureSearchPage,
    FeatureSearchRow,
    NearbyFeaturePage,
    NearbyFeatureRow,
    features_in_bbox,
    features_nearby_poi_cache_target,
    get_feature_row,
    get_feature_rows_by_ids,
    list_active_place_coords,
    load_bundle,
    load_bundles,
    search_features,
    soft_delete_features_not_in_snapshot,
    upsert_feature,
    upsert_source_link,
    upsert_source_record,
)
from kortravelmap.infra.feature_update_executor import (
    FeatureUpdateExecutionPlan,
    FeatureUpdateExecutionResult,
    ProviderDatasetRefreshResult,
    ProviderDatasetRefreshRunner,
    ProviderDatasetRefreshScope,
    SkippedProviderDatasetRefresh,
    build_feature_update_execution_plan,
    execute_feature_update_request,
    execute_next_feature_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    FEATURE_UPDATE_JOB_KIND,
    FEATURE_UPDATE_LOCK_RETRY_AFTER_SECONDS,
    FEATURE_UPDATE_QUEUE_ADVISORY_KEY,
    FeatureUpdateLockBusy,
    FeatureUpdateQueueLockBusy,
    FeatureUpdateRequest,
    FeatureUpdateRequestPage,
    FeatureUpdateRequestPreview,
    cancel_update_request,
    claim_next_update_request,
    enqueue_feature_update_request,
    feature_update_scope_advisory_key,
    finish_update_request,
    get_update_request,
    list_update_requests,
    peek_next_update_request,
    start_update_request,
)
from kortravelmap.infra.file_store import S3ObjectStore, StoredObject
from kortravelmap.infra.integrity_violation_repo import (
    DataIntegrityViolation,
    create_data_integrity_violation,
    get_data_integrity_violation,
    list_data_integrity_violations,
    set_data_integrity_violation_status,
)
from kortravelmap.infra.jobs_repo import (
    ImportJob,
    ImportJobEvent,
    cancel_import_job,
    claim_next_import_job,
    enqueue_import_job,
    finish_import_job,
    get_import_job,
    heartbeat_import_job,
    record_import_job_event,
    recover_stale_running_jobs,
    start_import_job,
    update_import_job_payload,
)
from kortravelmap.infra.models import (
    Base,
    CuratedFeatureDetailSnapshotRow,
    CuratedFeatureRow,
    CuratedSourceRow,
    CuratedSourceRuleRow,
    CuratedThemeRow,
    DataIntegrityViolationRow,
    DedupReviewQueueRow,
    FeatureConsistencyReportRow,
    FeatureOverrideRow,
    FeatureRow,
    FeatureUpdateRequestRow,
    ImportJobEventRow,
    ImportJobRow,
    OfflineUploadRow,
    PoiCacheTargetFeatureLinkRow,
    PoiCacheTargetRow,
    ProviderRefreshPolicyRow,
    ProviderSyncStateRow,
    SourceLinkRow,
    SourceRecordRow,
    metadata,
)
from kortravelmap.infra.offline_upload_repo import (
    OfflineUpload,
    OfflineUploadPage,
    attach_offline_upload_load_job,
    create_offline_upload,
    finish_offline_upload_load,
    finish_offline_upload_validation,
    get_offline_upload,
    get_offline_upload_by_checksum,
    list_offline_uploads,
    mark_offline_upload_loading,
    mark_offline_upload_validating,
    reserve_offline_upload_load,
)
from kortravelmap.infra.poi_cache_target_repo import (
    PoiCacheTarget,
    PoiCacheTargetConflict,
    PoiCacheTargetFeatureLink,
    PoiCacheTargetPage,
    deactivate_poi_cache_target_feature_links,
    delete_poi_cache_target,
    get_poi_cache_target,
    get_poi_cache_target_by_key,
    list_active_target_coords,
    list_poi_cache_target_feature_links,
    list_poi_cache_targets,
    mark_poi_cache_targets_refresh_failed,
    mark_poi_cache_targets_refresh_requested,
    mark_poi_cache_targets_refreshed,
    upsert_poi_cache_target,
    upsert_poi_cache_target_feature_link,
)
from kortravelmap.infra.provider_refresh_policy_repo import (
    ProviderRefreshPolicy,
    get_provider_refresh_policy,
    list_provider_refresh_policies,
    upsert_provider_refresh_policy,
)
from kortravelmap.infra.scope_repo import (
    CacheTargetFeatureMatch,
    CacheTargetScopeTarget,
    FeatureScopeRow,
    ProviderDatasetScope,
    ScopeResolution,
    SigunguByRadiusResolver,
    count_features_matching_scope,
    resolve_bbox,
    resolve_cache_target_keys,
    resolve_center_radius,
    resolve_feature_ids,
    resolve_provider_dataset,
    resolve_sigungu_by_radius,
)
from kortravelmap.infra.status_repo import StatusCounts, gather_status_counts

__all__ = [
    # advisory_lock (ADR-011 / ADR-039)
    "advisory_lock",
    "advisory_lock_key",
    "try_advisory_lock",
    # crs (ADR-012 + ADR-030)
    "EPSG_WGS84",
    "EPSG_UTM_K",
    "transformer_4326_to_5179",
    "transformer_5179_to_4326",
    "project_to_5179",
    "project_to_4326",
    # db (ADR-007)
    "make_async_engine",
    "make_async_session_factory",
    "normalize_async_dsn",
    # models (PR#28, ADR-004 / ADR-007 / ADR-018)
    "Base",
    "metadata",
    "CuratedFeatureRow",
    "CuratedSourceRow",
    "CuratedSourceRuleRow",
    "CuratedThemeRow",
    "CuratedFeatureDetailSnapshotRow",
    "FeatureRow",
    "SourceRecordRow",
    "SourceLinkRow",
    "ProviderSyncStateRow",
    "FeatureConsistencyReportRow",
    "DedupReviewQueueRow",
    "ImportJobRow",
    "ImportJobEventRow",
    "FeatureOverrideRow",
    "FeatureUpdateRequestRow",
    "DataIntegrityViolationRow",
    "PoiCacheTargetRow",
    "PoiCacheTargetFeatureLinkRow",
    "ProviderRefreshPolicyRow",
    "OfflineUploadRow",
    # file_store (ADR-015 S3 호환 객체 저장소)
    "S3ObjectStore",
    "StoredObject",
    # feature_repo (ADR-004 raw SQL load 경로)
    "FeatureLoadResult",
    "FeatureSearchPage",
    "FeatureSearchRow",
    "NearbyFeaturePage",
    "NearbyFeatureRow",
    "upsert_feature",
    "upsert_source_record",
    "upsert_source_link",
    "load_bundle",
    "load_bundles",
    "soft_delete_features_not_in_snapshot",
    "get_feature_row",
    "get_feature_rows_by_ids",
    "list_active_place_coords",
    "features_in_bbox",
    "search_features",
    "features_nearby_poi_cache_target",
    # admin_feature_repo (ADR-045 T-207c)
    "AdminFeaturePage",
    "AdminFeatureRow",
    "FeatureDeactivateResult",
    "FeatureOverride",
    "DedupReviewPage",
    "DedupReviewRow",
    "list_admin_features",
    "deactivate_feature",
    "list_dedup_reviews",
    "merge_dedup_review",
    "set_dedup_review_decision",
    # dedup_repo (ADR-016 dedup 후보 큐)
    "DedupQueueResult",
    "enqueue_dedup_candidate",
    "enqueue_dedup_candidates",
    "pending_dedup_reviews",
    # dedup_refresh_repo (ADR-045 T-208f)
    "DEDUP_REFRESH_DEFAULT_LIMIT",
    "DedupRefreshFeature",
    "DedupRefreshScope",
    "list_dedup_refresh_features",
    # jobs_repo (ADR-011 작업 큐)
    "ImportJob",
    "ImportJobEvent",
    "enqueue_import_job",
    "start_import_job",
    "get_import_job",
    "record_import_job_event",
    "update_import_job_payload",
    "claim_next_import_job",
    "heartbeat_import_job",
    "cancel_import_job",
    "finish_import_job",
    "recover_stale_running_jobs",
    # offline_upload_repo (ADR-045 D-14 / T-208h)
    "OfflineUpload",
    "OfflineUploadPage",
    "attach_offline_upload_load_job",
    "create_offline_upload",
    "get_offline_upload",
    "get_offline_upload_by_checksum",
    "list_offline_uploads",
    "mark_offline_upload_loading",
    "mark_offline_upload_validating",
    "reserve_offline_upload_load",
    "finish_offline_upload_validation",
    "finish_offline_upload_load",
    # feature_update_repo (ADR-045 feature update request queue)
    "FEATURE_UPDATE_JOB_KIND",
    "FEATURE_UPDATE_QUEUE_ADVISORY_KEY",
    "FEATURE_UPDATE_LOCK_RETRY_AFTER_SECONDS",
    "FeatureUpdateLockBusy",
    "FeatureUpdateQueueLockBusy",
    "FeatureUpdateRequest",
    "FeatureUpdateRequestPreview",
    "FeatureUpdateRequestPage",
    "enqueue_feature_update_request",
    "peek_next_update_request",
    "claim_next_update_request",
    "feature_update_scope_advisory_key",
    "start_update_request",
    "finish_update_request",
    "cancel_update_request",
    "get_update_request",
    "list_update_requests",
    # feature_update_executor (ADR-045 T-206d)
    "FeatureUpdateExecutionPlan",
    "FeatureUpdateExecutionResult",
    "ProviderDatasetRefreshResult",
    "ProviderDatasetRefreshRunner",
    "ProviderDatasetRefreshScope",
    "SkippedProviderDatasetRefresh",
    "build_feature_update_execution_plan",
    "execute_feature_update_request",
    "execute_next_feature_update_request",
    # Phase 2 ops repos (ADR-045 T-205c)
    "DataIntegrityViolation",
    "create_data_integrity_violation",
    "get_data_integrity_violation",
    "list_data_integrity_violations",
    "set_data_integrity_violation_status",
    "PoiCacheTarget",
    "PoiCacheTargetConflict",
    "PoiCacheTargetFeatureLink",
    "PoiCacheTargetPage",
    "upsert_poi_cache_target",
    "get_poi_cache_target",
    "get_poi_cache_target_by_key",
    "list_poi_cache_targets",
    "list_active_target_coords",
    "delete_poi_cache_target",
    "deactivate_poi_cache_target_feature_links",
    "upsert_poi_cache_target_feature_link",
    "list_poi_cache_target_feature_links",
    "mark_poi_cache_targets_refresh_requested",
    "mark_poi_cache_targets_refreshed",
    "mark_poi_cache_targets_refresh_failed",
    "ProviderRefreshPolicy",
    "upsert_provider_refresh_policy",
    "get_provider_refresh_policy",
    "list_provider_refresh_policies",
    # scope_repo (ADR-045 feature update request dry-run/scope resolver)
    "FeatureScopeRow",
    "CacheTargetScopeTarget",
    "CacheTargetFeatureMatch",
    "ProviderDatasetScope",
    "ScopeResolution",
    "SigunguByRadiusResolver",
    "resolve_feature_ids",
    "resolve_center_radius",
    "resolve_bbox",
    "resolve_sigungu_by_radius",
    "resolve_provider_dataset",
    "resolve_cache_target_keys",
    "count_features_matching_scope",
    # status_repo (read-only 운영 현황)
    "StatusCounts",
    "gather_status_counts",
]

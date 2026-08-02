"""``kortravelmap.client`` — ``AsyncKorTravelMapClient`` (라이브러리 진입점).

kor-travel-map API/Dagster 내부 구현과 테스트가 사용하는 Python 진입점이다. consumer
운영 연동은 ADR-045 이후 OpenAPI HTTP 계약만 사용하고, 이 client를 직접 import하지
않는다. 본 client는 SQLAlchemy 2 async ``AsyncEngine``을 주입받으며
**transaction 경계의 소유자**다 — ``infra/*_repo.py``는 "commit은 호출자 책임"으로
``session.execute``만 하므로, write 메서드가 ``session.begin()``으로
commit/rollback을 잡는다 (단위 of work).

오케스트레이션 범위 (#122 실 DB 적재):
- ``load_feature_bundles`` — provider 변환 출력(``FeatureBundle``)을 한
  transaction으로 적재 (``infra.load_bundles``).
- ``sync_dedup_candidates`` — cross-provider 중복 후보 탐지(``core.dedup.
  find_dedup_candidates``, 순수) → ``ops.dedup_review_queue`` 적재
  (``infra.enqueue_dedup_candidates``). 두 feature가 먼저 적재돼 있어야 함(FK).
- ``enqueue_feature_update_request`` — admin/OpenAPI feature update request를
  ``ops.feature_update_requests``와 연결 ``ops.import_jobs``에 한 transaction으로
  적재한다.
- ``preview_feature_update_request`` — DB write 없이 scope 해석 결과를 반환한다.
- 읽기: ``features_in_bounds`` / ``get_feature`` / ``pending_dedup_reviews``.

engine 수명은 호출자 소유 (ADR-004 ``infra/db.py`` — ``await engine.dispose()``는
호출자 책임). 따라서 ``__aexit__``는 engine을 닫지 않는다.

후속(별도 PR): ``upload_feature_files`` / ``upsert_sync_state`` /
``build_weather_card`` 등.

ADR 참조
--------
- ADR-002 — async-only (sync 인터페이스 추가 금지)
- ADR-045 — consumer 연계는 OpenAPI, client는 kor-travel-map 내부 API/Dagster용
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL (``infra/*_repo.py``); client가 commit
- ADR-016 — dedup 후보 ``ops.dedup_review_queue`` 적재
- ADR-020 — 본 모듈에 FastAPI/Uvicorn import 금지 (디버그 REST는 별도 패키지)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from time import monotonic
from types import TracebackType
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.dedup import find_dedup_candidates, find_sibling_candidates
from kortravelmap.core.exceptions import IntegrityFindingPersistenceError
from kortravelmap.core.feature_operation import (
    DagsterFeatureOperationCursor,
    DagsterFeatureOperationMutation,
    DagsterFeatureOperationPage,
    FeatureOperationInvariantConflict,
    ProviderDatasetOperationKey,
)
from kortravelmap.enrichment import (
    PhoneEnrichmentCandidate,
    PhoneEnrichmentResult,
    apply_place_phone_enrichment,
    find_place_phone_candidates,
)
from kortravelmap.infra import feature_update_repo as fur_repo
from kortravelmap.infra.advisory_lock import advisory_lock, try_advisory_lock
from kortravelmap.infra.batch_dag import (
    BatchDagCancellationWon,
    BatchDagMvPrepared,
    BatchDagPrepared,
    BatchDagRunResult,
    batch_dag_mutex_key,
    fail_batch_dag_phase,
    finish_batch_mv_phase,
    make_batch_dag_request,
    plan_batch_dag,
    prepare_batch_dag,
    reload_batch_phase_loss_result,
    run_batch_consistency_phase,
    start_batch_mv_phase,
)
from kortravelmap.infra.cache_target_reconciliation_repo import (
    observe_expired_cache_target_snapshot_backlog as repo_observe_cache_target_snapshot_backlog,
)
from kortravelmap.infra.cache_target_reconciliation_repo import (
    prune_expired_cache_target_snapshots_batch as repo_prune_cache_target_snapshots_batch,
)
from kortravelmap.infra.cache_target_snapshot_gc_observation_repo import (
    record_cache_target_snapshot_gc_observation as repo_record_cache_target_snapshot_gc_observation,
)
from kortravelmap.infra.consistency import (
    DEDUP_PENDING_WARN_THRESHOLD,
    DEDUP_SCORE_REGRESSION_WARN_POINTS,
    PROVIDER_LAST_SUCCESS_WARN_SECONDS,
    ConsistencyReport,
    FileObjectRef,
)
from kortravelmap.infra.consistency import (
    run_consistency_checks as repo_run_consistency_checks,
)
from kortravelmap.infra.curated_repo import (
    ConciergeThemeSyncResult,
    CuratedFeatureCandidatesResult,
    CuratedFeatureDetailSnapshotMaterializeResult,
    CuratedFeatureStatusSweepResult,
    CuratedSourceMetadataRefreshResult,
)
from kortravelmap.infra.curated_repo import (
    apply_enabled_curated_source_rules as repo_apply_enabled_curated_source_rules,
)
from kortravelmap.infra.curated_repo import (
    materialize_curated_feature_detail_snapshots as repo_materialize_curated_snapshots,
)
from kortravelmap.infra.curated_repo import (
    refresh_curated_source_metadata as repo_refresh_curated_source_metadata,
)
from kortravelmap.infra.curated_repo import (
    sweep_curated_feature_status as repo_sweep_curated_feature_status,
)
from kortravelmap.infra.curated_repo import (
    sync_concierge_themes as repo_sync_concierge_themes,
)
from kortravelmap.infra.db import make_async_session_factory
from kortravelmap.infra.dedup_refresh_repo import (
    DedupRefreshScope,
    list_dedup_refresh_features,
)
from kortravelmap.infra.dedup_repo import (
    DedupQueueResult,
    enqueue_dedup_candidates,
    pending_dedup_reviews,
)
from kortravelmap.infra.enrichment_review_repo import (
    EnrichmentDecisionResult,
    EnrichmentQueueResult,
    EnrichmentReviewInput,
    enqueue_review_candidates,
)
from kortravelmap.infra.enrichment_review_repo import (
    decide_enrichment_review as repo_decide_enrichment_review,
)
from kortravelmap.infra.enrichment_review_repo import (
    pending_enrichment_reviews as repo_pending_enrichment_reviews,
)
from kortravelmap.infra.feature_operation_repo import (
    append_dagster_feature_attempt_event as repo_append_dagster_feature_attempt_event,
)
from kortravelmap.infra.feature_operation_repo import (
    ensure_dagster_feature_operation as repo_ensure_dagster_feature_operation,
)
from kortravelmap.infra.feature_operation_repo import (
    finish_dagster_feature_pair as repo_finish_dagster_feature_pair,
)
from kortravelmap.infra.feature_operation_repo import (
    list_reconcilable_dagster_feature_runs as repo_list_reconcilable_feature_runs,
)
from kortravelmap.infra.feature_operation_repo import (
    reconcile_dagster_feature_run as repo_reconcile_dagster_feature_run,
)
from kortravelmap.infra.feature_operation_repo import (
    record_feature_operation_invariant_conflict,
)
from kortravelmap.infra.feature_repo import (
    AirQualityLoadResult,
    EnrichmentLoadResult,
    FeatureLoadResult,
    FeatureSearchPage,
    NearbyFeaturePage,
    NoticeFeatureLoadResult,
    NoticeReconcileResult,
    close_notice_features,
    features_in_bbox,
    get_feature_row,
    get_feature_rows_by_ids,
    inactivate_features_by_source_entity_ids,
    inactivate_geometryless_area_features_by_source,
    load_bundles,
    load_source_record_links,
    supersede_stale_notice_features,
)
from kortravelmap.infra.feature_repo import (
    features_nearby as repo_features_nearby,
)
from kortravelmap.infra.feature_repo import (
    features_nearby_poi_cache_target as repo_features_nearby_poi_cache_target,
)
from kortravelmap.infra.feature_repo import (
    get_notice_snapshot_watermark as repo_get_notice_snapshot_watermark,
)
from kortravelmap.infra.feature_repo import (
    list_active_place_coords as repo_list_active_place_coords,
)
from kortravelmap.infra.feature_repo import (
    list_primary_place_locator as repo_list_primary_place_locator,
)
from kortravelmap.infra.feature_repo import (
    load_authoritative_notice_snapshot as repo_load_authoritative_notice_snapshot,
)
from kortravelmap.infra.feature_repo import (
    load_notice_event_bundles as repo_load_notice_event_bundles,
)
from kortravelmap.infra.feature_repo import (
    purge_expired_notices as repo_purge_expired_notices,
)
from kortravelmap.infra.feature_repo import (
    search_features as repo_search_features,
)
from kortravelmap.infra.feature_update_executor import (
    FeatureUpdateExecutionResult,
    ProviderDatasetRefreshRunner,
)
from kortravelmap.infra.feature_update_executor import (
    execute_feature_update_request as repo_execute_feature_update_request,
)
from kortravelmap.infra.feature_update_executor import (
    execute_next_feature_update_request as repo_execute_next_feature_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    FeatureUpdateRequestPage,
    FeatureUpdateRequestPreview,
)
from kortravelmap.infra.feature_update_repo import (
    enqueue_feature_update_request as repo_enqueue_feature_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    finish_update_request as repo_finish_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    get_update_request as repo_get_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    list_update_requests as repo_list_update_requests,
)
from kortravelmap.infra.feature_update_repo import (
    peek_next_update_request as repo_peek_next_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    peek_update_requests as repo_peek_update_requests,
)
from kortravelmap.infra.feature_update_repo import (
    preview_feature_update_request as repo_preview_feature_update_request,
)
from kortravelmap.infra.feature_update_repo import (
    start_update_request as repo_start_update_request,
)
from kortravelmap.infra.integrity_violation_repo import (
    IntegrityObservationReceipt,
    close_stale_integrity_findings,
    purge_resolved_integrity_findings,
    sync_integrity_findings,
)
from kortravelmap.infra.jobs_repo import ImportJobEvent
from kortravelmap.infra.merge_repo import MergeOutcome, merge_from_review
from kortravelmap.infra.poi_cache_target_repo import (
    has_active_poi_cache_targets_for_external_system as _repo_has_active_target_system,
)
from kortravelmap.infra.poi_cache_target_repo import (
    list_active_poi_cache_target_external_systems as _repo_list_active_target_systems,
)
from kortravelmap.infra.poi_cache_target_repo import (
    list_active_target_coords as repo_list_active_target_coords,
)
from kortravelmap.infra.price_repo import PriceFeatureLoadResult
from kortravelmap.infra.price_repo import (
    load_price_values as repo_load_price_values,
)
from kortravelmap.infra.status_repo import StatusCounts, gather_status_counts
from kortravelmap.infra.sync_state_repo import (
    SyncState,
)
from kortravelmap.infra.sync_state_repo import (
    get_sync_state as repo_get_sync_state,
)
from kortravelmap.infra.sync_state_repo import (
    list_sync_states as repo_list_sync_states,
)
from kortravelmap.infra.sync_state_repo import (
    record_sync_failure as repo_record_sync_failure,
)
from kortravelmap.infra.sync_state_repo import (
    record_sync_success as repo_record_sync_success,
)
from kortravelmap.infra.weather_repo import (
    WeatherCard,
)
from kortravelmap.infra.weather_repo import (
    build_weather_card as repo_build_weather_card,
)
from kortravelmap.infra.weather_repo import (
    load_weather_values as repo_load_weather_values,
)
from kortravelmap.mois import DEFAULT_BATCH_SIZE as MOIS_DEFAULT_BATCH_SIZE
from kortravelmap.mois import (
    MoisBulkJobResult,
    MoisBulkSyncResult,
    MoisClosedJobResult,
    MoisIncrementalJobResult,
    load_mois_license_features_bulk,
    run_mois_license_bulk_job,
    run_mois_license_closed_job,
    run_mois_license_incremental_job,
    sync_mois_license_features_bulk,
)
from kortravelmap.offline_upload import (
    OfflineUploadColumnMapping,
    OfflineUploadLoadResult,
    OfflineUploadObjectStore,
    OfflineUploadValidationResult,
)
from kortravelmap.offline_upload import (
    run_offline_upload_load_job as repo_run_offline_upload_load_job,
)
from kortravelmap.offline_upload import (
    run_offline_upload_validation_job as repo_run_offline_upload_validation_job,
)
from kortravelmap.providers.mois import DATASET_KEY_BULK as MOIS_DATASET_KEY_BULK
from kortravelmap.providers.mois import DATASET_KEY_HISTORY as MOIS_DATASET_KEY_HISTORY
from kortravelmap.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME
from kortravelmap.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    STANDARD_DATA_PROVIDER_NAME,
)
from kortravelmap.providers.visitkorea import (
    DEFAULT_ACCEPT_THRESHOLD,
    DEFAULT_REVIEW_FLOOR,
    FestivalCandidate,
    FestivalEnrichment,
    ScoringFestivalMatcher,
    festival_to_enrichment_links,
    festival_to_review_candidates,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Collection, Iterable, Mapping, Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncEngine

    from kortravelmap.core.dedup import DedupCandidate, DedupInput
    from kortravelmap.dto import FeatureBundle
    from kortravelmap.dto.price import PriceValue
    from kortravelmap.dto.weather import WeatherValue
    from kortravelmap.geocoding import AddressResolver, ReverseGeocoder
    from kortravelmap.infra.scope_repo import SigunguByRadiusResolver
    from kortravelmap.providers.mois import MoisLicensePlaceRecord
    from kortravelmap.providers.visitkorea import VisitKoreaFestivalItem
    from kortravelmap.settings import KorTravelMapSettings

__all__ = [
    "AirQualityLoadResult",
    "AsyncKorTravelMapClient",
    "BatchDagRunResult",
    "CacheTargetSnapshotGcDrainResult",
    "ConciergeThemeSyncResult",
    "CuratedFeatureCandidatesResult",
    "CuratedFeatureStatusSweepResult",
    "CuratedSourceMetadataRefreshResult",
    "CuratedFeatureDetailSnapshotMaterializeResult",
    "DedupRefreshResult",
    "DedupSyncResult",
    "DagsterFeatureOperationCursor",
    "DagsterFeatureOperationMutation",
    "DagsterFeatureOperationPage",
    "FeatureOperationInvariantConflict",
    "FestivalEnrichmentReviewRefreshResult",
    "IntegrityFindingSyncResult",
    "OfflineUploadColumnMapping",
    "OfflineUploadLoadResult",
    "OfflineUploadValidationResult",
    "PriceFeatureLoadResult",
    "ProviderDatasetOperationKey",
]


@dataclass(frozen=True)
class DedupSyncResult:
    """``sync_dedup_candidates`` 결과 — 탐지된 후보 + 큐 적재 카운트.

    - ``candidates`` — ``find_dedup_candidates`` 출력 (score 내림차순).
    - ``queue`` — ``ops.dedup_review_queue`` upsert 결과
      (inserted/updated/skipped).
    """

    candidates: list[DedupCandidate]
    queue: DedupQueueResult


@dataclass(frozen=True)
class DedupRefreshResult:
    """DB 기준 dedup 후보 refresh 결과."""

    mode: str
    left_scope: DedupRefreshScope
    right_scope: DedupRefreshScope | None
    left_count: int
    right_count: int
    candidates: list[DedupCandidate]
    queue: DedupQueueResult

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 바로 기록할 수 있는 summary."""
        metadata: dict[str, object] = {
            "mode": self.mode,
            "left_scope": self.left_scope.as_metadata(),
            "right_scope": (
                self.right_scope.as_metadata() if self.right_scope is not None else None
            ),
            "left_count": self.left_count,
            "right_count": self.right_count,
            "candidates_total": len(self.candidates),
            "queue_inserted": self.queue.inserted,
            "queue_updated": self.queue.updated,
            "queue_skipped": self.queue.skipped,
        }
        return metadata


@dataclass(frozen=True)
class FestivalEnrichmentReviewRefreshResult:
    """``refresh_festival_enrichment_reviews`` 결과 — 자동 적재 + 검토 큐 적재.

    - ``auto`` — ≥ accept_threshold라 즉시 적재된 enrichment 카운트.
    - ``review_queue`` — review-band를 ``ops.enrichment_review_queue``에 upsert한
      카운트(inserted/updated/skipped).
    """

    auto: EnrichmentLoadResult
    review_queue: EnrichmentQueueResult

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata로 바로 기록할 수 있는 summary."""
        return {
            "auto_enrichments_total": self.auto.enrichments_total,
            "auto_source_records_inserted": self.auto.source_records_inserted,
            "auto_source_links_inserted": self.auto.source_links_inserted,
            "auto_source_links_updated": self.auto.source_links_updated,
            "review_candidates_total": self.review_queue.candidates_total,
            "review_inserted": self.review_queue.inserted,
            "review_updated": self.review_queue.updated,
            "review_skipped": self.review_queue.skipped,
        }


@dataclass(frozen=True, slots=True)
class AddressValidationFinding:
    """durable하게 남길 주소/좌표 검증 finding 1건 (T-VN-H30A).

    ``linked``가 핵심이다. ``ops.data_integrity_violations``의 ``feature_id``/
    ``source_record_key``는 **FK**인데 주소 검증은 적재 **전**에 돌아서, drop된 행은 두 대상이
    아직(또는 영원히) DB에 없다. 그대로 넘기면 FK 위반으로 기록 자체가 실패한다.
    적재된 대상만 ``linked=True``로 표시하고, 나머지는 id를 ``payload``로만 나른다.
    """

    dedupe_key: str
    violation_type: str
    severity: str
    message: str
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    feature_id: str | None = None
    linked: bool = False
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IntegrityFindingSyncResult:
    """주소 검증 finding 관측·중복 제거·durable upsert 카운트."""

    observed_count: int
    unique_count: int
    upserted_count: int

    @property
    def unrecorded_count(self) -> int:
        """고유 finding 중 durable하게 기록되지 않은 건수."""
        return max(0, self.unique_count - self.upserted_count)


@dataclass(frozen=True, slots=True)
class CacheTargetSnapshotGcDrainResult:
    """만료 cache-target snapshot background drain 실행 결과."""

    acquired: bool
    skipped: bool
    batches: int
    deleted_items: int
    deleted_headers: int
    remaining_items: int | None
    remaining_headers: int | None
    total_items: int | None = None
    total_headers: int | None = None
    unexpired_unreferenced_items: int | None = None
    unexpired_unreferenced_headers: int | None = None
    referenced_items: int | None = None
    referenced_headers: int | None = None
    observation_run_id: str | None = None
    observed_at: datetime | None = None
    observation_referenced_items: int | None = None
    observation_referenced_headers: int | None = None
    previous_observation_run_id: str | None = None
    previous_observed_at: datetime | None = None
    previous_referenced_items: int | None = None
    previous_referenced_headers: int | None = None
    growth_baseline_observation_run_id: str | None = None
    growth_baseline_observed_at: datetime | None = None
    growth_baseline_referenced_items: int | None = None
    growth_baseline_referenced_headers: int | None = None
    observation_growth_baseline_eligible: bool | None = None
    observation_growth_min_interval_seconds: int | None = None


class AsyncKorTravelMapClient:
    """라이브러리 진입점 — DB 적재/조회 + dedup 후보 동기화 오케스트레이션.

    Parameters
    ----------
    engine
        ``infra.make_async_engine`` 등으로 만든 ``AsyncEngine`` (호출자 소유).
    settings
        ``KorTravelMapSettings`` (선택). 현재 적재/dedup 경로는 사용하지 않으나,
        후속 weather card / file upload 경로가 참조.

    Examples
    --------
    >>> async with AsyncKorTravelMapClient(engine) as client:  # doctest: +SKIP
    ...     result = await client.load_feature_bundles(bundles)
    ...     sync = await client.sync_dedup_candidates(knps_temples, krh_temples)
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        settings: KorTravelMapSettings | None = None,
    ) -> None:
        self._engine = engine
        self._session_factory = make_async_session_factory(engine)
        self._settings = settings

    async def __aenter__(self) -> AsyncKorTravelMapClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # engine 수명은 호출자 소유 (ADR-004 infra/db.py) — 여기서 dispose 안 함.
        return None

    @asynccontextmanager
    async def provider_run_lock(self, key: str) -> AsyncIterator[None]:
        """provider fetch→load 전체 실행을 DB instance 전역에서 직렬화한다.

        Dagster asset pool은 scheduled/manual asset run의 불필요한 동시 시작을
        줄이지만, feature update worker가 같은 실행 함수를 직접 부르는 경로까지
        포괄하지 못한다. 별도 DB session에 session-level advisory lock을 유지해
        어느 process/실행 경로에서 호출하든 같은 ``key``의 provider 작업이 겹치지
        않게 한다. process가 종료되면 PostgreSQL connection과 함께 lock도 해제된다.
        """
        async with (
            self._session_factory() as session,
            advisory_lock(session, key),
        ):
            yield

    async def drain_expired_cache_target_snapshots(
        self,
        *,
        max_batches: int = 2_000,
        max_seconds: float = 3_300,
        item_limit: int = 1_000,
        header_limit: int = 100,
        batch_statement_timeout_ms: int = 30_000,
        observation_run_id: str | None = None,
        observation_retention_days: int = 90,
        observation_growth_min_interval_seconds: int = 300,
    ) -> CacheTargetSnapshotGcDrainResult:
        """만료·미참조 cache-target snapshot backlog를 제한 내에서 비운다.

        별도 lock session의 session-level try-lock으로 process 전역 중복 drain을
        즉시 skip한다. 획득한 실행은 batch마다 새 session/transaction을 열어 commit해
        장시간 transaction과 대량 rollback을 피한다. repo가 반환한 system을 keyset
        cursor로 넘겨 exact 정렬 round-robin을 유지한다. 각 transaction에는 local
        ``statement_timeout``을 적용하고, 한 바퀴 동안 삭제 진척이 없으면 reader lock
        backlog를 남긴 채 종료한다. batch에서는 ``EXISTS``만 확인하고 정확한 전역
        remaining count는 종료 시 별도 observation transaction에서 한 번만 센다. 취소
        예외는 잡지 않아 transaction rollback과 lock 해제 뒤 호출자에게 그대로 전파한다.
        """
        if max_batches <= 0:
            raise ValueError("max_batches는 1 이상이어야 합니다.")
        if max_seconds <= 0:
            raise ValueError("max_seconds는 0보다 커야 합니다.")
        if not 0 < item_limit <= 10_000:
            raise ValueError("item_limit은 1 이상 10000 이하여야 합니다.")
        if not 0 < header_limit <= 1_000:
            raise ValueError("header_limit은 1 이상 1000 이하여야 합니다.")
        if not 0 < batch_statement_timeout_ms <= 300_000:
            raise ValueError(
                "batch_statement_timeout_ms는 1 이상 300000 이하여야 합니다."
            )
        if observation_run_id is not None:
            if (
                observation_run_id != observation_run_id.strip()
                or not observation_run_id
                or len(observation_run_id) > 255
            ):
                raise ValueError(
                    "observation_run_id는 trim된 1~255자 문자열이어야 합니다."
                )
            if not 1 <= observation_retention_days <= 3_650:
                raise ValueError(
                    "observation_retention_days는 1 이상 3650 이하여야 합니다."
                )
            if not 1 <= observation_growth_min_interval_seconds <= 86_400:
                raise ValueError(
                    "observation_growth_min_interval_seconds는 1 이상 86400 "
                    "이하여야 합니다."
                )

        # AsyncConnection context가 physical connection을 끝까지 pin한다. lock 획득
        # transaction은 즉시 commit하되 session-level advisory lock은 같은 backend에
        # 남고, finally의 unlock도 동일 connection에서 실행된다.
        async with self._engine.connect() as lock_connection, try_advisory_lock(
            lock_connection,
            "cache-target-snapshot-gc",
        ) as acquired:
            await lock_connection.commit()
            if not acquired:
                return CacheTargetSnapshotGcDrainResult(
                    acquired=False,
                    skipped=True,
                    batches=0,
                    deleted_items=0,
                    deleted_headers=0,
                    remaining_items=None,
                    remaining_headers=None,
                )
            batches = 0
            deleted_items = 0
            deleted_headers = 0
            deadline = monotonic() + max_seconds
            after_external_system: str | None = None
            systems_seen_in_round: set[str] = set()
            round_deleted = 0

            while batches < max_batches:
                remaining_seconds = deadline - monotonic()
                if remaining_seconds <= 0:
                    break
                statement_timeout_ms = min(
                    batch_statement_timeout_ms,
                    max(1, int(remaining_seconds * 1_000)),
                )
                async with (
                    self._session_factory() as batch_session,
                    batch_session.begin(),
                ):
                    await batch_session.execute(
                        text(
                            "SELECT set_config("
                            "'statement_timeout', :timeout, true)"
                        ),
                        {"timeout": f"{statement_timeout_ms}ms"},
                    )
                    batch = await repo_prune_cache_target_snapshots_batch(
                        batch_session,
                        after_external_system=after_external_system,
                        item_limit=item_limit,
                        header_limit=header_limit,
                    )
                batches += 1
                batch_deleted = batch.deleted_items + batch.deleted_headers
                deleted_items += batch.deleted_items
                deleted_headers += batch.deleted_headers
                after_external_system = batch.external_system

                no_progress_round = False
                if batch.external_system is None:
                    no_progress_round = batch.has_more and batch_deleted == 0
                elif batch.external_system in systems_seen_in_round:
                    no_progress_round = round_deleted == 0 and batch_deleted == 0
                    systems_seen_in_round = {batch.external_system}
                    round_deleted = batch_deleted
                else:
                    systems_seen_in_round.add(batch.external_system)
                    round_deleted += batch_deleted
                # acquisition transaction을 오래 유지하지 않으면서 pinned backend의
                # 생존과 lock 소유를 batch 사이에 확인한다.
                await lock_connection.execute(text("SELECT 1"))
                await lock_connection.commit()
                if not batch.has_more or no_progress_round:
                    break

            async with (
                self._session_factory() as observation_session,
                observation_session.begin(),
            ):
                await observation_session.execute(
                    text(
                        "SELECT set_config("
                        "'statement_timeout', :timeout, true)"
                    ),
                    {"timeout": f"{batch_statement_timeout_ms}ms"},
                )
                backlog = await repo_observe_cache_target_snapshot_backlog(
                    observation_session
                )
                observation = None
                if observation_run_id is not None:
                    observation = (
                        await repo_record_cache_target_snapshot_gc_observation(
                            observation_session,
                            dagster_run_id=observation_run_id,
                            referenced_items=backlog.referenced_items,
                            referenced_headers=backlog.referenced_headers,
                            retention_days=observation_retention_days,
                            growth_min_interval_seconds=(
                                observation_growth_min_interval_seconds
                            ),
                        )
                    )

            return CacheTargetSnapshotGcDrainResult(
                acquired=True,
                skipped=False,
                batches=batches,
                deleted_items=deleted_items,
                deleted_headers=deleted_headers,
                remaining_items=backlog.remaining_items,
                remaining_headers=backlog.remaining_headers,
                total_items=backlog.total_items,
                total_headers=backlog.total_headers,
                unexpired_unreferenced_items=(
                    backlog.unexpired_unreferenced_items
                ),
                unexpired_unreferenced_headers=(
                    backlog.unexpired_unreferenced_headers
                ),
                referenced_items=backlog.referenced_items,
                referenced_headers=backlog.referenced_headers,
                observation_run_id=(
                    observation.dagster_run_id if observation is not None else None
                ),
                observed_at=(observation.observed_at if observation is not None else None),
                observation_referenced_items=(
                    observation.referenced_items if observation is not None else None
                ),
                observation_referenced_headers=(
                    observation.referenced_headers if observation is not None else None
                ),
                previous_observation_run_id=(
                    observation.previous_observation_run_id
                    if observation is not None
                    else None
                ),
                previous_observed_at=(
                    observation.previous_observed_at
                    if observation is not None
                    else None
                ),
                previous_referenced_items=(
                    observation.previous_referenced_items
                    if observation is not None
                    else None
                ),
                previous_referenced_headers=(
                    observation.previous_referenced_headers
                    if observation is not None
                    else None
                ),
                growth_baseline_observation_run_id=(
                    observation.growth_baseline_run_id
                    if observation is not None
                    else None
                ),
                growth_baseline_observed_at=(
                    observation.growth_baseline_observed_at
                    if observation is not None
                    else None
                ),
                growth_baseline_referenced_items=(
                    observation.growth_baseline_referenced_items
                    if observation is not None
                    else None
                ),
                growth_baseline_referenced_headers=(
                    observation.growth_baseline_referenced_headers
                    if observation is not None
                    else None
                ),
                observation_growth_baseline_eligible=(
                    observation.growth_baseline_eligible
                    if observation is not None
                    else None
                ),
                observation_growth_min_interval_seconds=(
                    observation.growth_min_interval_seconds
                    if observation is not None
                    else None
                ),
            )

    # ─── write (transaction 소유) ──────────────────────────────────────────

    async def _record_feature_operation_conflict(
        self, conflict: FeatureOperationInvariantConflict
    ) -> None:
        async with self._session_factory() as session, session.begin():
            await record_feature_operation_invariant_conflict(session, conflict)

    async def ensure_dagster_feature_operation(
        self,
        *,
        dagster_run_id: str,
        trigger_kind: str,
        selected_pairs: Sequence[ProviderDatasetOperationKey],
        registry_version: str,
        engine_created_at: datetime,
        engine_started_at: datetime | None,
        observed_status: str,
    ) -> DagsterFeatureOperationMutation:
        """Dagster run root와 exact pair child 전체를 짧은 transaction에 ensure한다."""
        try:
            async with self._session_factory() as session, session.begin():
                return await repo_ensure_dagster_feature_operation(
                    session,
                    dagster_run_id=dagster_run_id,
                    trigger_kind=trigger_kind,
                    selected_pairs=selected_pairs,
                    registry_version=registry_version,
                    engine_created_at=engine_created_at,
                    engine_started_at=engine_started_at,
                    observed_status=observed_status,
                )
        except FeatureOperationInvariantConflict as exc:
            await self._record_feature_operation_conflict(exc)
            raise

    async def finish_dagster_feature_pair(
        self,
        *,
        dagster_run_id: str,
        pair: ProviderDatasetOperationKey,
    ) -> DagsterFeatureOperationMutation:
        """wrapper가 성공한 exact pair child 하나를 완료한다."""
        try:
            async with self._session_factory() as session, session.begin():
                return await repo_finish_dagster_feature_pair(
                    session, dagster_run_id=dagster_run_id, pair=pair
                )
        except FeatureOperationInvariantConflict as exc:
            await self._record_feature_operation_conflict(exc)
            raise

    async def append_dagster_feature_attempt_event(
        self,
        *,
        dagster_run_id: str,
        pair: ProviderDatasetOperationKey,
        attempt_number: int,
        outcome: str,
        error: Mapping[str, Any] | None,
    ) -> ImportJobEvent:
        """step retry attempt를 lifecycle 변경 없이 append-only event로 남긴다."""
        try:
            async with self._session_factory() as session, session.begin():
                return await repo_append_dagster_feature_attempt_event(
                    session,
                    dagster_run_id=dagster_run_id,
                    pair=pair,
                    attempt_number=attempt_number,
                    outcome=outcome,
                    error=error,
                )
        except FeatureOperationInvariantConflict as exc:
            await self._record_feature_operation_conflict(exc)
            raise

    async def reconcile_dagster_feature_run(
        self,
        *,
        dagster_run_id: str,
        trigger_kind: str,
        terminal_status: str,
        selected_pairs: Sequence[ProviderDatasetOperationKey],
        registry_version: str,
        engine_created_at: datetime,
        engine_started_at: datetime | None,
        engine_finished_at: datetime,
        error: Mapping[str, Any] | None,
    ) -> DagsterFeatureOperationMutation:
        """권위 있는 Dagster terminal을 root와 남은 active child에 반영한다."""
        try:
            async with self._session_factory() as session, session.begin():
                return await repo_reconcile_dagster_feature_run(
                    session,
                    dagster_run_id=dagster_run_id,
                    trigger_kind=trigger_kind,
                    terminal_status=terminal_status,
                    selected_pairs=selected_pairs,
                    registry_version=registry_version,
                    engine_created_at=engine_created_at,
                    engine_started_at=engine_started_at,
                    engine_finished_at=engine_finished_at,
                    error=error,
                )
        except FeatureOperationInvariantConflict as exc:
            await self._record_feature_operation_conflict(exc)
            raise

    async def list_reconcilable_dagster_feature_runs(
        self,
        *,
        cursor: DagsterFeatureOperationCursor | None,
        page_size: int = 200,
    ) -> DagsterFeatureOperationPage:
        """DB→Dagster sweep용 active unmarked root page를 반환한다."""
        async with self._session_factory() as session, session.begin():
            return await repo_list_reconcilable_feature_runs(
                session, cursor=cursor, page_size=page_size
            )

    async def load_feature_bundles(self, bundles: Iterable[FeatureBundle]) -> FeatureLoadResult:
        """``FeatureBundle`` 다수를 한 transaction으로 적재 (commit/rollback).

        feature → source_record → source_link 순 idempotent upsert
        (``infra.load_bundles``). 하나라도 실패하면 전체 rollback.
        """
        async with self._session_factory() as session, session.begin():
            return await load_bundles(session, bundles)

    async def load_authoritative_notice_snapshot(
        self,
        *,
        bundles: Sequence[FeatureBundle],
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        active_lineage_keys: Collection[str],
        observed_at: datetime,
    ) -> NoticeFeatureLoadResult:
        """full notice snapshot 적재와 lifecycle 반영을 한 transaction으로 수행."""
        async with self._session_factory() as session, session.begin():
            return await repo_load_authoritative_notice_snapshot(
                session,
                bundles=bundles,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
                active_lineage_keys=active_lineage_keys,
                observed_at=observed_at,
            )

    async def load_notice_event_bundles(
        self,
        *,
        bundles: Sequence[FeatureBundle],
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        lineage_events: Mapping[str, tuple[bool, datetime, datetime | None]],
        observed_at: datetime,
    ) -> NoticeFeatureLoadResult:
        """event notice 적재와 member lifecycle 반영을 한 transaction으로 수행."""
        async with self._session_factory() as session, session.begin():
            return await repo_load_notice_event_bundles(
                session,
                bundles=bundles,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
                lineage_events=lineage_events,
                observed_at=observed_at,
            )

    async def inactivate_features_by_source(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        source_entity_ids: set[str],
    ) -> int:
        """명시 철회/폐기된 source entity의 대응 feature를 inactive로 전환.

        provider가 ``reject``/``tombstone``/폐업으로 통지한 ``source_entity_id``
        집합에 속하는 primary-source feature를 ``status='inactive'``로 전환한다
        (``infra.inactivate_features_by_source_entity_ids``, ADR-017 — place 무기한
        유지·status만 전환, ADR-050 #4). 빈 집합이면 no-op(0). 한 transaction.
        D-12: 전환된 feature는 batch/단건 read의 ``found``에 status와 함께 남는다.
        """
        async with self._session_factory() as session, session.begin():
            return await inactivate_features_by_source_entity_ids(
                session,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
                source_entity_ids=source_entity_ids,
            )

    async def inactivate_geometryless_area_features_by_source(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
    ) -> int:
        """경계 geometry 없이 적재된 provider ``area`` feature를 inactive로 전환.

        기존 변환 정책 보정용 메서드다. ``provider``/``dataset_key``/
        ``source_entity_type``으로 primary source를 한정하고, 실제 feature 조건은
        ``kind='area' AND geom IS NULL``로 제한한다. 한 transaction.
        """
        async with self._session_factory() as session, session.begin():
            return await inactivate_geometryless_area_features_by_source(
                session,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
            )

    async def close_notice_features(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        closures: Mapping[str, datetime],
        announcements: Mapping[str, datetime] | None = None,
    ) -> int:
        """notice 발표/해제 계보 상태를 반영하고 닫힌 Feature 수를 반환한다.

        KMA 특보 등 event feed 경계 — mapping key는 사건 ``lineage_key``다.
        ``infra.feature_repo.close_notice_features`` 위임. 한 transaction.
        """
        async with self._session_factory() as session, session.begin():
            return await close_notice_features(
                session,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
                closures=closures,
                announcements=announcements,
            )

    async def reconcile_notice_features(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        active_lineage_keys: Collection[str] | None = None,
        closed_at: datetime | None = None,
    ) -> NoticeReconcileResult:
        """notice 중복/소멸 정리 — 적재 직후 호출(#632).

        같은 계보의 중복 feature를 soft-delete하고(latest 1개 유지), 현재 feed에
        없는 계보의 latest에 ``valid_end_time``을 채운다.
        ``infra.feature_repo.supersede_stale_notice_features`` 위임. 한 transaction.
        """
        async with self._session_factory() as session, session.begin():
            return await supersede_stale_notice_features(
                session,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
                active_lineage_keys=active_lineage_keys,
                closed_at=closed_at,
            )

    async def get_notice_snapshot_watermark(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
    ) -> datetime | None:
        """authoritative notice scope에 실제 반영된 최근 watermark를 조회한다."""
        async with self._session_factory() as session:
            return await repo_get_notice_snapshot_watermark(
                session,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
            )

    async def purge_expired_notices(self, *, retention: str = "1 year") -> int:
        """보존 기간이 지난 notice를 soft-delete (§9 보관 정책, #632).

        ``infra.feature_repo.purge_expired_notices`` 위임. 한 transaction.
        """
        async with self._session_factory() as session, session.begin():
            return await repo_purge_expired_notices(session, retention=retention)

    async def close_stale_address_validation_findings(
        self,
        *,
        provider: str,
        dataset_key: str,
        run_id: str,
        receipt: IntegrityObservationReceipt,
    ) -> int:
        """불변 observation generation을 authoritative finalize한다. 한 transaction."""

        async with self._session_factory() as session, session.begin():
            return await close_stale_integrity_findings(
                session,
                provider=provider,
                dataset_key=dataset_key,
                run_id=run_id,
                receipt=receipt,
            )

    async def purge_resolved_integrity_findings(self, *, retention: str = "90 days") -> int:
        """보존 기간이 지난 ``resolved`` finding을 삭제한다 (T-VN-H32). 한 transaction.

        ``acknowledged``는 지우지 않는다. ``purge_expired_notices``와 같은 retention 패턴이다.
        """
        async with self._session_factory() as session, session.begin():
            return await purge_resolved_integrity_findings(session, retention=retention)

    async def load_enrichment_links(
        self, enrichments: Iterable[FestivalEnrichment]
    ) -> EnrichmentLoadResult:
        """visitkorea 등 2차 enrichment(``FestivalEnrichment``)를 한 transaction으로 적재.

        각 enrichment의 ``source_record`` → ``source_link``(enrichment role) 순
        idempotent upsert (``infra.load_source_record_links``). **새 Feature는 만들지
        않으며**, ``source_link.feature_id``가 가리키는 1차 feature(datagokr 축제)가
        이미 적재돼 있어야 한다(FK). 하나라도 실패하면 전체 rollback.
        """
        pairs = [(e.source_record, e.source_link) for e in enrichments]
        async with self._session_factory() as session, session.begin():
            return await load_source_record_links(session, pairs)

    async def load_festival_enrichment(
        self,
        items: Iterable[VisitKoreaFestivalItem],
        *,
        fetched_at: datetime,
        name_threshold: float = 0.90,
    ) -> EnrichmentLoadResult:
        """visitkorea 축제 items를 적재된 datagokr 축제(1차)에 매칭해 enrichment 적재.

        한 transaction에서 (1) 적재된 datagokr 축제(``data.go.kr-standard`` /
        ``datagokr_cultural_festivals`` / kind ``event``)를 candidate로 읽고
        (2) ``ScoringFestivalMatcher``(이름 Jaro-Winkler 유사도, ADR-016)로 각
        visitkorea item을 매칭, (3) ``festival_to_enrichment_links``로 enrichment
        link를 만들고 (4) ``load_source_record_links``로 적재한다(ADR-042). 매칭
        실패 item은 제외. 1차 festival이 아직 없으면 candidate가 비어 enrichment도 0.
        """
        items_list = list(items)
        async with self._session_factory() as session, session.begin():
            candidate_rows = await list_dedup_refresh_features(
                session,
                DedupRefreshScope(
                    provider=STANDARD_DATA_PROVIDER_NAME,
                    dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
                    kinds=("event",),
                    limit=50_000,
                ),
            )
            matcher = ScoringFestivalMatcher(
                [
                    FestivalCandidate(feature_id=row.feature_id, name=row.name)
                    for row in candidate_rows
                ],
                name_threshold=name_threshold,
            )
            links = festival_to_enrichment_links(items_list, matcher=matcher, fetched_at=fetched_at)
            pairs = [(link.source_record, link.source_link) for link in links]
            return await load_source_record_links(session, pairs)

    async def refresh_festival_enrichment_reviews(
        self,
        items: Iterable[VisitKoreaFestivalItem],
        *,
        fetched_at: datetime,
        accept_threshold: float = DEFAULT_ACCEPT_THRESHOLD,
        review_floor: float = DEFAULT_REVIEW_FLOOR,
    ) -> FestivalEnrichmentReviewRefreshResult:
        """visitkorea 축제 items를 점수 밴드로 자동 적재 + 수동 검토 큐로 분류한다(T-RV-52c).

        한 transaction에서 (1) 적재된 datagokr 축제(1차)를 candidate로 읽고 (2)
        ``festival_to_review_candidates``로 ``accept_threshold`` 이상은 즉시 enrichment
        적재, ``[review_floor, accept_threshold)`` 모호 밴드는 ``ops.enrichment_review_queue``
        로 upsert한다. ``review_floor`` 미만은 버린다. 자동 적재 동작은 기존
        ``load_festival_enrichment``과 동치(임계값만 명시적). commit/rollback 소유.
        """
        items_list = list(items)
        async with self._session_factory() as session, session.begin():
            candidate_rows = await list_dedup_refresh_features(
                session,
                DedupRefreshScope(
                    provider=STANDARD_DATA_PROVIDER_NAME,
                    dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
                    kinds=("event",),
                    limit=50_000,
                ),
            )
            matcher = ScoringFestivalMatcher(
                [
                    FestivalCandidate(feature_id=row.feature_id, name=row.name)
                    for row in candidate_rows
                ],
            )
            plan = festival_to_review_candidates(
                items_list,
                matcher=matcher,
                fetched_at=fetched_at,
                accept_threshold=accept_threshold,
                review_floor=review_floor,
            )
            auto = await load_source_record_links(
                session,
                [(e.source_record, e.source_link) for e in plan.auto],
            )
            review_inputs = [
                EnrichmentReviewInput(
                    target_feature_id=candidate.target_feature_id,
                    target_name=candidate.target_name,
                    source_name=candidate.source_name,
                    name_score=candidate.name_score,
                    source_record=candidate.enrichment.source_record,
                )
                for candidate in plan.review
            ]
            review_queue = await enqueue_review_candidates(session, review_inputs)
            return FestivalEnrichmentReviewRefreshResult(auto=auto, review_queue=review_queue)

    async def list_pending_enrichment_reviews(self, *, limit: int = 100) -> list[dict[str, object]]:
        """검토 대기(``status='pending'``) 축제 enrichment 후보 list (name_score 내림차순).

        admin UI/디버깅용 raw row(점수 float 변환). DTO 매핑은 상위 책임.
        """
        async with self._session_factory() as session:
            return await repo_pending_enrichment_reviews(session, limit=limit)

    async def resolve_enrichment_review(
        self,
        review_id: str,
        decision: str,
        *,
        reviewed_by: str | None = None,
        reason: str | None = None,
    ) -> EnrichmentDecisionResult:
        """축제 enrichment 검토 행에 운영자 결정을 한 transaction으로 반영한다(T-RV-52c).

        ``decision='accepted'``이면 보관된 ``SourceRecord``를 복원해 ENRICHMENT link과
        함께 적재한다. reject/ignore는 상태만 갱신. 이미 검토된 행은 ``changed=False``.
        """
        async with self._session_factory() as session, session.begin():
            return await repo_decide_enrichment_review(
                session,
                review_id,
                decision,
                reviewed_by=reviewed_by,
                reason=reason,
            )

    async def load_mois_license_features_bulk(
        self,
        records: Iterable[MoisLicensePlaceRecord],
        *,
        fetched_at: datetime,
        dataset_key: str = MOIS_DATASET_KEY_BULK,
        reverse_geocoder: ReverseGeocoder | None = None,
        address_resolver: AddressResolver | None = None,
    ) -> FeatureLoadResult:
        """MOIS 인허가 ``PlaceRecord`` 묶음을 변환 → 적재 (한 transaction).

        PROMOTED 슬러그 / 영업중 record만 ``providers.mois``로 bundle화한 뒤
        idempotent upsert (``kortravelmap.mois.load_mois_license_features_bulk``).
        EXCLUDED/미매핑/비영업 record는 변환 단계에서 skip. 하나라도 실패하면
        전체 rollback. snapshot delete는 ``sync_mois_license_features_bulk``,
        advisory lock은 후속 PR (Sprint 4a §9).
        """
        async with self._session_factory() as session, session.begin():
            return await load_mois_license_features_bulk(
                session,
                records,
                fetched_at=fetched_at,
                dataset_key=dataset_key,
                reverse_geocoder=reverse_geocoder,
                address_resolver=address_resolver,
            )

    async def sync_mois_license_features_bulk(
        self,
        records: Iterable[MoisLicensePlaceRecord],
        *,
        fetched_at: datetime,
        dataset_key: str = MOIS_DATASET_KEY_BULK,
        reverse_geocoder: ReverseGeocoder | None = None,
        address_resolver: AddressResolver | None = None,
        batch_size: int = MOIS_DEFAULT_BATCH_SIZE,
    ) -> MoisBulkSyncResult:
        """MOIS 인허가 전체 snapshot 적재 + 부재 feature soft-delete (한 transaction).

        ``records``는 **이번 전체 snapshot**(영업중 PROMOTED record)이어야 한다 —
        ``batch_size``개씩 streaming 변환·upsert(메모리 바운드) → snapshot에 없는
        기존 feature를 ``status='inactive'``로 비활성화(ADR-017)까지 한 단위 of
        work로 수행한다. 하나라도 실패하면 전체 rollback. ``records``로 mois source
        DB의 ``iter_open_place_records(...)``를 그대로 넘기면 Step A가 완성된다.
        """
        async with self._session_factory() as session, session.begin():
            return await sync_mois_license_features_bulk(
                session,
                records,
                fetched_at=fetched_at,
                dataset_key=dataset_key,
                reverse_geocoder=reverse_geocoder,
                address_resolver=address_resolver,
                batch_size=batch_size,
            )

    async def run_mois_license_bulk_job(
        self,
        records: Iterable[MoisLicensePlaceRecord],
        *,
        fetched_at: datetime,
        dataset_key: str = MOIS_DATASET_KEY_BULK,
        reverse_geocoder: ReverseGeocoder | None = None,
        address_resolver: AddressResolver | None = None,
        source_checksum: str | None = None,
        batch_size: int = MOIS_DEFAULT_BATCH_SIZE,
    ) -> MoisBulkJobResult:
        """MOIS Step A bulk 적재를 advisory lock + import_jobs 추적으로 실행.

        단일 워커 직렬화(``try_advisory_lock``)로 다른 워커가 적재 중이면
        ``acquired=False``로 skip한다. 획득 시 ``import_jobs`` 작업을 running으로
        시작 → ``batch_size`` streaming 변환·upsert·snapshot prune → done/failed
        종료. 한 transaction — 실패 시 데이터와 작업 기록이 함께 rollback된다
        (원자성 우선; 영속 failed 기록이 필요하면 후속 lifespan 복구가 stale
        running을 정리, ADR-011). ``records``로 mois source DB의
        ``iter_open_place_records(...)``를 그대로 넘기면 Step A가 완성된다.
        """
        async with self._session_factory() as session, session.begin():
            return await run_mois_license_bulk_job(
                session,
                records,
                fetched_at=fetched_at,
                dataset_key=dataset_key,
                reverse_geocoder=reverse_geocoder,
                address_resolver=address_resolver,
                source_checksum=source_checksum,
                batch_size=batch_size,
            )

    async def run_mois_license_incremental_job(
        self,
        records: Iterable[MoisLicensePlaceRecord],
        *,
        fetched_at: datetime,
        new_cursor: dict[str, Any],
        dataset_key: str = MOIS_DATASET_KEY_HISTORY,
        sync_scope: str = "default",
        reverse_geocoder: ReverseGeocoder | None = None,
        address_resolver: AddressResolver | None = None,
        source_checksum: str | None = None,
        batch_size: int = MOIS_DEFAULT_BATCH_SIZE,
    ) -> MoisIncrementalJobResult:
        """MOIS Step B 증분 적재를 advisory lock + import_jobs + cursor 전진으로 실행.

        ``records``는 "지난 cursor 이후 변경된" record만(호출자/provider가 필터링).
        전체 snapshot이 아니므로 soft-delete(prune)하지 않는다. 성공 시
        ``provider_sync_state``의 cursor를 ``new_cursor``로 전진시킨다. 단일 워커
        직렬화(``acquired=False``면 skip). 한 transaction — 실패 시 데이터·cursor·
        작업 기록이 함께 rollback된다.
        """
        async with self._session_factory() as session, session.begin():
            return await run_mois_license_incremental_job(
                session,
                records,
                fetched_at=fetched_at,
                new_cursor=new_cursor,
                dataset_key=dataset_key,
                sync_scope=sync_scope,
                reverse_geocoder=reverse_geocoder,
                address_resolver=address_resolver,
                source_checksum=source_checksum,
                batch_size=batch_size,
            )

    async def run_mois_license_closed_job(
        self,
        records: Iterable[MoisLicensePlaceRecord],
        *,
        new_cursor: dict[str, Any],
        target_dataset_key: str = MOIS_DATASET_KEY_BULK,
        sync_scope: str = "default",
        source_checksum: str | None = None,
    ) -> MoisClosedJobResult:
        """MOIS Step C 폐업/취소 — 대응 feature를 inactive로 전환(ADR-017).

        ``records``는 provider가 closed/cancelled로 통지한 인허가. 각 record의
        ``source_entity_id``로 ``target_dataset_key``(보통 bulk)의 feature를
        ``status='inactive'``로 전환하고, closed dataset cursor를 ``new_cursor``로
        전진시킨다. advisory lock 단일 워커 직렬화(``acquired=False``면 skip). 한
        transaction.
        """
        async with self._session_factory() as session, session.begin():
            return await run_mois_license_closed_job(
                session,
                records,
                new_cursor=new_cursor,
                target_dataset_key=target_dataset_key,
                sync_scope=sync_scope,
                source_checksum=source_checksum,
            )

    async def run_offline_upload_load_job(
        self,
        upload_id: str,
        *,
        store: OfflineUploadObjectStore,
        dagster_run_id: str | None = None,
        address_resolver: AddressResolver | None = None,
        reverse_geocoder: ReverseGeocoder | None = None,
    ) -> OfflineUploadLoadResult:
        """오프라인 업로드 파일을 ``FeatureBundle``로 파싱해 적재한다.

        ``ops.offline_uploads`` 메타데이터의 ``storage_key``를 store에서 읽고,
        checksum/size 검증 후 JSON/JSONL ``FeatureBundle``을 적재한다. 진행 상태는
        ``ops.import_jobs``와 ``ops.offline_uploads``에 기록된다.
        """
        async with self._session_factory() as session, session.begin():
            return await repo_run_offline_upload_load_job(
                session,
                upload_id,
                store=store,
                dagster_run_id=dagster_run_id,
                address_resolver=address_resolver,
                reverse_geocoder=reverse_geocoder,
            )

    async def run_offline_upload_validation_job(
        self,
        upload_id: str,
        *,
        store: OfflineUploadObjectStore,
        column_mapping: OfflineUploadColumnMapping | Mapping[str, object],
        sample_size: int = 1000,
        operator: str | None = None,
        address_resolver: AddressResolver | None = None,
        reverse_geocoder: ReverseGeocoder | None = None,
    ) -> OfflineUploadValidationResult:
        """CSV/TSV 오프라인 업로드를 load 전에 검증하고 mapping payload를 저장한다."""
        async with self._session_factory() as session, session.begin():
            return await repo_run_offline_upload_validation_job(
                session,
                upload_id,
                store=store,
                column_mapping=column_mapping,
                sample_size=sample_size,
                operator=operator,
                address_resolver=address_resolver,
                reverse_geocoder=reverse_geocoder,
            )

    async def find_place_phone_candidates(
        self,
        *,
        provider: str = MOIS_PROVIDER_NAME,
        dataset_key: str = MOIS_DATASET_KEY_BULK,
        limit: int = 100,
    ) -> list[PhoneEnrichmentCandidate]:
        """전화번호 없는 place feature 후보 (phone enrichment 대상, 읽기 전용).

        외부 phone lookup(kakao/naver/google)은 호출자(백그라운드 워커) 책임(ADR-006).
        """
        async with self._session_factory() as session:
            return await find_place_phone_candidates(
                session, provider=provider, dataset_key=dataset_key, limit=limit
            )

    async def enrich_place_phone(
        self,
        *,
        feature_id: str,
        phone: str,
        enrichment_provider: str,
        source_entity_id: str,
        fetched_at: datetime,
    ) -> PhoneEnrichmentResult:
        """외부 lookup 전화번호를 feature에 보강 (detail.phones + enrichment 이력).

        정규화·dedup·max3 적용 후 ``detail.phones`` 갱신 + ``source_links(role=
        'enrichment')`` 적재. 무효/중복/초과 시 ``applied=False``. 한 transaction.
        """
        async with self._session_factory() as session, session.begin():
            return await apply_place_phone_enrichment(
                session,
                feature_id=feature_id,
                phone=phone,
                enrichment_provider=enrichment_provider,
                source_entity_id=source_entity_id,
                fetched_at=fetched_at,
            )

    async def enqueue_feature_update_request(
        self,
        *,
        scope: Mapping[str, Any],
        providers: Sequence[str] | None = None,
        dataset_keys: Sequence[str] | None = None,
        update_policy: Mapping[str, Any] | None = None,
        run_mode: str = "queued",
        priority: int = 50,
        operator: str | None = None,
        reason: str | None = None,
        sigungu_resolver: SigunguByRadiusResolver | None = None,
    ) -> FeatureUpdateRequest:
        """Feature update request와 연결 import job을 한 transaction에 생성한다."""
        async with self._session_factory() as session, session.begin():
            return await repo_enqueue_feature_update_request(
                session,
                scope=scope,
                providers=providers,
                dataset_keys=dataset_keys,
                update_policy=update_policy,
                run_mode=run_mode,
                priority=priority,
                operator=operator,
                reason=reason,
                sigungu_resolver=sigungu_resolver,
            )

    async def preview_feature_update_request(
        self,
        *,
        scope: Mapping[str, Any],
        providers: Sequence[str] | None = None,
        dataset_keys: Sequence[str] | None = None,
        update_policy: Mapping[str, Any] | None = None,
        run_mode: str = "queued",
        priority: int = 50,
        sigungu_resolver: SigunguByRadiusResolver | None = None,
    ) -> FeatureUpdateRequestPreview:
        """scope 해석 결과를 반환하되 아무 행도 저장하지 않는다."""
        async with self._session_factory() as session:
            return await repo_preview_feature_update_request(
                session,
                scope=scope,
                providers=providers,
                dataset_keys=dataset_keys,
                update_policy=update_policy,
                run_mode=run_mode,
                priority=priority,
                sigungu_resolver=sigungu_resolver,
            )

    async def fail_update_request(
        self,
        request_id: str,
        *,
        owner_dagster_run_id: str,
        expected_request_generation: int,
        error_message: str | None = None,
    ) -> FeatureUpdateRequest | None:
        """Dagster failure를 pre-start retry 또는 started owner 실패로 반영한다.

        request가 sensor가 본 queued generation 그대로면 generation을 +1해
        다음 run key를 연다. 이미 start한 동일 run이면 기존 run id CAS로 request와
        import job을 ``failed``로 닫는다.
        """
        async with self._session_factory() as session, session.begin():
            retry = await fur_repo.advance_update_request_generation_after_pre_start_failure(
                session,
                request_id,
                expected_generation=expected_request_generation,
            )
            if retry is not None:
                return retry
            return await repo_finish_update_request(
                session,
                request_id,
                status="failed",
                owner_dagster_run_id=owner_dagster_run_id,
                expected_generation=expected_request_generation,
                error_message=error_message,
            )

    async def peek_next_update_request(self) -> FeatureUpdateRequest | None:
        """Dagster sensor가 다음 queued request를 상태 변경 없이 확인한다."""
        async with self._session_factory() as session:
            return await repo_peek_next_update_request(session)

    async def peek_update_requests(self, *, limit: int = 10) -> tuple[FeatureUpdateRequest, ...]:
        """Dagster sensor가 queued request batch를 상태 변경 없이 확인한다."""
        async with self._session_factory() as session:
            return await repo_peek_update_requests(session, limit=limit)

    async def mark_update_request_started(
        self,
        request_id: str,
        *,
        dagster_run_id: str,
        expected_generation: int,
    ) -> FeatureUpdateRequest | None:
        """queued generation을 특정 Dagster run owner로 fail-closed claim한다."""
        async with self._session_factory() as session, session.begin():
            return await repo_start_update_request(
                session,
                request_id,
                dagster_run_id=dagster_run_id,
                expected_generation=expected_generation,
            )

    async def execute_next_feature_update_request(
        self,
        *,
        runner: ProviderDatasetRefreshRunner,
        dagster_run_id: str,
        sigungu_resolver: SigunguByRadiusResolver | None = None,
    ) -> FeatureUpdateExecutionResult | None:
        """queued feature update request 1건을 peek하고 lock 아래 claim해 실행한다.

        provider API 호출/Dagster orchestration은 runner가 담당한다. 본 client는
        전용 physical connection의 session-level scope lock을 유지하면서 prepare,
        provider scope, finalize를 각각 commit한다.
        """
        async with self._engine.connect() as connection:
            return await repo_execute_next_feature_update_request(
                connection,
                runner=runner,
                dagster_run_id=dagster_run_id,
                sigungu_resolver=sigungu_resolver,
            )

    async def execute_feature_update_request(
        self,
        request_id: str,
        *,
        runner: ProviderDatasetRefreshRunner,
        dagster_run_id: str,
        expected_request_generation: int | None = None,
        sigungu_resolver: SigunguByRadiusResolver | None = None,
    ) -> FeatureUpdateExecutionResult | None:
        """특정 feature update request를 즉시 실행한다. 없으면 ``None``."""
        async with self._engine.connect() as connection:
            async with (
                AsyncSession(
                    bind=connection,
                    expire_on_commit=False,
                ) as session,
                session.begin(),
            ):
                request = await repo_get_update_request(session, request_id)
            if request is None:
                return None
            return await repo_execute_feature_update_request(
                connection,
                request,
                runner=runner,
                dagster_run_id=dagster_run_id,
                expected_request_generation=expected_request_generation,
                sigungu_resolver=sigungu_resolver,
            )

    async def sync_dedup_candidates(
        self,
        left: Iterable[DedupInput],
        right: Iterable[DedupInput],
        *,
        include_auto_merge: bool = True,
    ) -> DedupSyncResult:
        """cross-provider 중복 후보 탐지 + ``ops.dedup_review_queue`` 적재.

        ``find_dedup_candidates``(순수, ADR-016)로 ``left × right``를 cross-score한
        뒤 후보를 큐에 upsert한다. ``left``/``right``의 feature(``feature_id``)는
        이미 ``feature.features``에 적재돼 있어야 한다 (큐 FK CASCADE). 후보가
        없으면 빈 큐 결과.

        Parameters
        ----------
        left, right
            ``DedupInput`` (보통 두 provider feature 집합; ``Feature``가 그대로 만족).
        include_auto_merge
            ``auto_merge`` 후보 포함 여부 (기본 True). False면 ``manual_review``만.
        """
        candidates = find_dedup_candidates(left, right, include_auto_merge=include_auto_merge)
        if not candidates:
            return DedupSyncResult(candidates=[], queue=DedupQueueResult())
        async with self._session_factory() as session, session.begin():
            queue = await enqueue_dedup_candidates(session, candidates)
        return DedupSyncResult(candidates=candidates, queue=queue)

    async def sync_sibling_candidates(
        self,
        features: Iterable[DedupInput],
        *,
        include_auto_merge: bool = True,
    ) -> DedupSyncResult:
        """**같은 dataset 내** 중복 후보 탐지 + ``ops.dedup_review_queue`` 적재.

        ``find_sibling_candidates``(순수, within-set pairwise)로 한 provider/dataset
        안의 self-sibling(예: MOIS 같은 사업장이 2슬러그로 중복 등록)을 탐지해 큐에
        upsert한다. ``features``의 feature는 이미 ``feature.features``에 적재돼 있어야
        한다 (큐 FK). 후보가 없으면 빈 큐 결과.

        Parameters
        ----------
        features
            같은 dataset의 ``DedupInput`` 집합 (``Feature``가 그대로 만족).
        include_auto_merge
            ``auto_merge`` 후보 포함 여부 (기본 True). False면 ``manual_review``만.
        """
        candidates = find_sibling_candidates(features, include_auto_merge=include_auto_merge)
        if not candidates:
            return DedupSyncResult(candidates=[], queue=DedupQueueResult())
        async with self._session_factory() as session, session.begin():
            queue = await enqueue_dedup_candidates(session, candidates)
        return DedupSyncResult(candidates=candidates, queue=queue)

    async def refresh_dedup_candidates_for_scope_pair(
        self,
        left_scope: DedupRefreshScope,
        right_scope: DedupRefreshScope,
        *,
        include_auto_merge: bool = True,
    ) -> DedupRefreshResult:
        """DB에 적재된 두 provider/dataset scope를 다시 score해 큐를 갱신한다."""
        async with self._session_factory() as session, session.begin():
            left = await list_dedup_refresh_features(session, left_scope)
            right = await list_dedup_refresh_features(session, right_scope)
            candidates = find_dedup_candidates(left, right, include_auto_merge=include_auto_merge)
            queue = (
                await enqueue_dedup_candidates(session, candidates)
                if candidates
                else DedupQueueResult()
            )
        return DedupRefreshResult(
            mode="pair",
            left_scope=left_scope,
            right_scope=right_scope,
            left_count=len(left),
            right_count=len(right),
            candidates=candidates,
            queue=queue,
        )

    async def refresh_sibling_dedup_candidates(
        self,
        scope: DedupRefreshScope,
        *,
        include_auto_merge: bool = True,
    ) -> DedupRefreshResult:
        """DB에 적재된 단일 provider/dataset scope 내부 중복 후보를 재계산한다."""
        async with self._session_factory() as session, session.begin():
            features = await list_dedup_refresh_features(session, scope)
            candidates = find_sibling_candidates(features, include_auto_merge=include_auto_merge)
            queue = (
                await enqueue_dedup_candidates(session, candidates)
                if candidates
                else DedupQueueResult()
            )
        return DedupRefreshResult(
            mode="sibling",
            left_scope=scope,
            right_scope=None,
            left_count=len(features),
            right_count=0,
            candidates=candidates,
            queue=queue,
        )

    async def run_consistency_report(
        self,
        *,
        batch_id: str | None = None,
        persist: bool = True,
        sample_limit: int = 20,
        dedup_pending_threshold: int = DEDUP_PENDING_WARN_THRESHOLD,
        provider_last_success_sla_seconds: int = PROVIDER_LAST_SUCCESS_WARN_SECONDS,
        dedup_score_regression_warn_points: float = DEDUP_SCORE_REGRESSION_WARN_POINTS,
        known_file_objects: Iterable[FileObjectRef] | None = None,
    ) -> ConsistencyReport:
        """F1~F8 consistency report를 실행하고 필요 시 DB에 저장한다."""
        async with self._session_factory() as session, session.begin():
            return await repo_run_consistency_checks(
                session,
                batch_id=batch_id,
                persist=persist,
                sample_limit=sample_limit,
                dedup_pending_threshold=dedup_pending_threshold,
                provider_last_success_sla_seconds=provider_last_success_sla_seconds,
                dedup_score_regression_warn_points=dedup_score_regression_warn_points,
                known_file_objects=known_file_objects,
            )

    async def refresh_curated_source_metadata(
        self,
        *,
        provider: str | None = None,
        dataset_key: str | None = None,
    ) -> CuratedSourceMetadataRefreshResult:
        """curated source metadata를 source_records 기준으로 갱신한다(T-223c-2)."""
        async with self._session_factory() as session, session.begin():
            return await repo_refresh_curated_source_metadata(
                session,
                provider=provider,
                dataset_key=dataset_key,
            )

    async def apply_curated_source_rules(
        self,
        *,
        limit: int = 500,
    ) -> CuratedFeatureCandidatesResult:
        """enabled source rule을 적용해 curated 후보/선정 row를 갱신한다(T-223c-2)."""
        async with self._session_factory() as session, session.begin():
            return await repo_apply_enabled_curated_source_rules(
                session,
                limit=limit,
            )

    async def sync_concierge_themes(
        self,
        *,
        min_features: int = 1,
    ) -> ConciergeThemeSyncResult:
        """concierge youtube channel/playlist 그룹핑을 curated 테마+rule로 동기화한다.

        이미 적재된 concierge 후보 feature의 그룹핑 값에서 유도해 그룹핑당 public
        테마 1개 + detail_selector rule 1개를 upsert하고 즉시 후보를 채운다(#15).
        """
        async with self._session_factory() as session, session.begin():
            return await repo_sync_concierge_themes(
                session,
                min_features=min_features,
            )

    async def sweep_curated_feature_status(
        self,
    ) -> CuratedFeatureStatusSweepResult:
        """inactive/deleted feature가 가리키는 curated overlay를 archive한다(T-223c-2)."""
        async with self._session_factory() as session, session.begin():
            return await repo_sweep_curated_feature_status(session)

    async def materialize_curated_feature_detail_snapshots(
        self,
        *,
        theme_slug: str | None = None,
        limit: int = 500,
    ) -> CuratedFeatureDetailSnapshotMaterializeResult:
        """curated feature detail snapshot cache를 materialize한다(T-223c-2)."""
        async with self._session_factory() as session, session.begin():
            return await repo_materialize_curated_snapshots(
                session,
                theme_slug=theme_slug,
                limit=limit,
            )

    async def run_batch_dag_consistency_gate(
        self,
        *,
        child_job_ids: Sequence[str] = (),
        load_batch_id: str | None = None,
        root_kind: str = "full_load_batch",
        root_payload: Mapping[str, Any] | None = None,
        dagster_run_id: str | None = None,
        plan_only: bool = False,
        consistency_persist: bool = True,
        sample_limit: int = 20,
        dedup_pending_threshold: int = DEDUP_PENDING_WARN_THRESHOLD,
        materialized_views: Sequence[str] = (),
        mv_refresh_strategy: str = "swap",
    ) -> BatchDagRunResult:
        """같은 connection/mutex에서 batch gate를 네 transaction phase로 실행한다."""
        request = make_batch_dag_request(
            child_job_ids=child_job_ids,
            load_batch_id=load_batch_id,
            root_kind=root_kind,
            root_payload=root_payload,
            dagster_run_id=dagster_run_id,
            consistency_persist=consistency_persist,
            sample_limit=sample_limit,
            dedup_pending_threshold=dedup_pending_threshold,
            materialized_views=materialized_views,
            mv_refresh_strategy=mv_refresh_strategy,
        )
        if plan_only:
            async with self._session_factory() as session:
                return await plan_batch_dag(session, request)

        result: BatchDagRunResult | None = None
        prepared: BatchDagPrepared | None = None
        async with (
            self._engine.connect() as connection,
            AsyncSession(bind=connection, expire_on_commit=False) as session,
        ):
            try:
                async with advisory_lock(session, batch_dag_mutex_key(request.load_batch_id)):
                    # session-level lock SELECT의 autobegin을 먼저 닫는다. lock은
                    # 같은 connection에서 아래 phase commit 사이에도 유지된다.
                    await session.commit()
                    async with session.begin():
                        prepared_or_result = await prepare_batch_dag(session, request)
                    if isinstance(prepared_or_result, BatchDagRunResult):
                        result = prepared_or_result
                    else:
                        prepared = prepared_or_result

                    report: ConsistencyReport | None = None
                    if result is None and prepared is not None:
                        try:
                            async with session.begin():
                                consistency_or_result = await run_batch_consistency_phase(
                                    session, prepared
                                )
                            if isinstance(consistency_or_result, BatchDagRunResult):
                                result = consistency_or_result
                            else:
                                report = consistency_or_result
                        except BatchDagCancellationWon:
                            async with session.begin():
                                result = await reload_batch_phase_loss_result(session, prepared)
                        except Exception as exc:  # noqa: BLE001
                            message = f"{exc.__class__.__name__}: {exc}"
                            try:
                                async with session.begin():
                                    result = await fail_batch_dag_phase(
                                        session, prepared, message=message
                                    )
                            except BatchDagCancellationWon:
                                async with session.begin():
                                    result = await reload_batch_phase_loss_result(
                                        session,
                                        prepared,
                                        error_message=message,
                                    )

                    mv_phase: BatchDagMvPrepared | None = None
                    if result is None and prepared is not None and report is not None:
                        try:
                            async with session.begin():
                                mv_or_result = await start_batch_mv_phase(session, prepared, report)
                            if isinstance(mv_or_result, BatchDagRunResult):
                                result = mv_or_result
                            else:
                                mv_phase = mv_or_result
                        except BatchDagCancellationWon:
                            async with session.begin():
                                result = await reload_batch_phase_loss_result(
                                    session, prepared, report=report
                                )
                        except Exception as exc:  # noqa: BLE001
                            message = f"{exc.__class__.__name__}: {exc}"
                            try:
                                async with session.begin():
                                    result = await fail_batch_dag_phase(
                                        session,
                                        prepared,
                                        message=message,
                                        report=report,
                                    )
                            except BatchDagCancellationWon:
                                async with session.begin():
                                    result = await reload_batch_phase_loss_result(
                                        session,
                                        prepared,
                                        report=report,
                                        error_message=message,
                                    )

                    if result is None and prepared is not None and mv_phase is not None:
                        try:
                            async with session.begin():
                                result = await finish_batch_mv_phase(session, mv_phase)
                        except BatchDagCancellationWon:
                            async with session.begin():
                                result = await reload_batch_phase_loss_result(
                                    session,
                                    prepared,
                                    report=mv_phase.consistency_report,
                                    mv_job=mv_phase.mv_refresh_job,
                                )
                        except Exception as exc:  # noqa: BLE001
                            message = f"{exc.__class__.__name__}: {exc}"
                            try:
                                async with session.begin():
                                    result = await fail_batch_dag_phase(
                                        session,
                                        prepared,
                                        message=message,
                                        report=mv_phase.consistency_report,
                                        mv_job=mv_phase.mv_refresh_job,
                                    )
                            except BatchDagCancellationWon:
                                async with session.begin():
                                    result = await reload_batch_phase_loss_result(
                                        session,
                                        prepared,
                                        report=mv_phase.consistency_report,
                                        mv_job=mv_phase.mv_refresh_job,
                                        error_message=message,
                                    )
            finally:
                # advisory_lock의 unlock SELECT도 autobegin하므로 connection을
                # 반환하기 전에 명시적으로 commit한다.
                if session.in_transaction():
                    await session.commit()
        if result is None:
            raise RuntimeError("batch DAG phase orchestration produced no result")
        return result

    async def merge_dedup_review(
        self,
        review_id: str,
        *,
        merged_by: str | None = None,
        reason: str | None = None,
    ) -> MergeOutcome:
        """검토 큐 후보(``review_id``) 1쌍을 master 자동 선정 후 병합한다 (ADR-016).

        ``infra.merge_repo.merge_from_review``를 한 transaction에서 실행: loser의
        source_link를 master로 재지정, loser feature soft-delete, ``feature_merge_history``
        기록, 큐 행 ``merged`` 전이. master는 ``select_master``(좌표 → updated_at →
        source 우선순위)로 결정. 큐 행이 없거나 이미 검토됐으면 ``MergeError``.

        **중복 실행 직렬화(ADR-039)는 호출 측 책임** — CLI ``dedup-merge``가
        ``dedup-merge:{review_id}`` advisory lock으로 감싼다(본 메서드는 lock 미적용).
        """
        async with self._session_factory() as session, session.begin():
            return await merge_from_review(session, review_id, merged_by=merged_by, reason=reason)

    # ─── read ──────────────────────────────────────────────────────────────

    async def get_feature(self, feature_id: str) -> dict[str, Any] | None:
        """``feature.features`` 단건 조회 (raw row dict). 없으면 ``None``."""
        async with self._session_factory() as session:
            return await get_feature_row(session, feature_id)

    async def features_in_bounds(
        self,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        kinds: list[str] | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """bbox(4326) 안의 feature 경량 표현 list (지도/목록용)."""
        async with self._session_factory() as session:
            return await features_in_bbox(
                session,
                min_lon=min_lon,
                min_lat=min_lat,
                max_lon=max_lon,
                max_lat=max_lat,
                kinds=kinds,
                limit=limit,
            )

    async def get_features(self, feature_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """여러 feature 상세 row를 한 번에 조회 (``feature_id`` → row dict).

        ``infra.feature_repo.get_feature_rows_by_ids`` 위임. soft-deleted feature는
        제외되므로 입력 순서/누락은 호출자가 key 존재로 판단한다(consumer batch 계약).
        API/Dagster 내부 read path가 admin batch 라우터와 같은 repo를 재사용하도록
        client 표면으로 노출한다(T-213d).
        """
        async with self._session_factory() as session:
            return await get_feature_rows_by_ids(session, feature_ids)

    async def search_features(
        self,
        *,
        q: str | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        kinds: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        page_size: int = 50,
        cursor: str | None = None,
        include_total: bool = False,
        cursor_signing_key: bytes,
    ) -> FeatureSearchPage:
        """사용자 feature 검색(pg_trgm ``q`` 또는 ``bbox``) — keyset cursor.

        ``infra.feature_repo.search_features`` 위임. ``q``/``bbox`` 중 하나는 필수
        (둘 다 없으면 ``ValueError``). ``cursor_signing_key``는 인증 credential과
        분리한 32-byte 이상 HMAC key다. ``include_total=False``면 COUNT를 실행하지
        않고 ``total_count=None``을 반환한다. ``q``는 ``SET LOCAL`` threshold로만
        적용한다(ADR-004).
        """
        async with self._session_factory() as session:
            return await repo_search_features(
                session,
                q=q,
                bbox=bbox,
                kinds=kinds,
                categories=categories,
                page_size=page_size,
                cursor=cursor,
                include_total=include_total,
                cursor_signing_key=cursor_signing_key,
            )

    async def features_nearby(
        self,
        *,
        lon: float,
        lat: float,
        radius_m: float,
        kinds: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        statuses: Sequence[str] | None = ("active",),
        providers: Sequence[str] | None = None,
        sort: str = "distance",
        limit: int = 100,
        cursor: str | None = None,
    ) -> NearbyFeaturePage:
        """일반 좌표(``lon``/``lat``) 중심 반경 ``radius_m`` 안 feature summary (T-213b).

        ``infra.feature_repo.features_nearby`` 위임. 입력 좌표는 CTE에서 1회만 5179로
        변환하고 술어는 STORED ``coord_5179``에 직접 적용한다(ADR-012). 응답/커서는
        by-target nearby와 동일(``NearbyFeaturePage``). ``sort`` ∈
        {distance, name, last_updated_at}.
        """
        async with self._session_factory() as session:
            return await repo_features_nearby(
                session,
                lon=lon,
                lat=lat,
                radius_m=radius_m,
                kinds=kinds,
                categories=categories,
                statuses=statuses,
                providers=providers,
                sort=sort,
                limit=limit,
                cursor=cursor,
            )

    async def features_nearby_poi_cache_target(
        self,
        *,
        target_id: str,
        radius_km: float | None = None,
        kinds: Sequence[str] | None = None,
        categories: Sequence[str] | None = None,
        statuses: Sequence[str] | None = ("active",),
        providers: Sequence[str] | None = None,
        sort: str = "distance",
        limit: int = 100,
        cursor: str | None = None,
    ) -> NearbyFeaturePage:
        """POI/cache target(``target_id``) 주변 feature summary — keyset cursor.

        ``infra.feature_repo.features_nearby_poi_cache_target`` 위임. 반경 술어는
        STORED ``coord_5179``에 직접 적용한다(ADR-012). ``sort`` ∈
        {distance, name, last_updated_at}. T-213d로 by-target nearby read path를
        client 표면으로 노출한다(좌표 기준 ``/features/nearby``는 T-213b).
        """
        async with self._session_factory() as session:
            return await repo_features_nearby_poi_cache_target(
                session,
                target_id=target_id,
                radius_km=radius_km,
                kinds=kinds,
                categories=categories,
                statuses=statuses,
                providers=providers,
                sort=sort,
                limit=limit,
                cursor=cursor,
            )

    async def pending_dedup_reviews(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """검토 대기(``status='pending'``) dedup 후보 list — total_score 내림차순."""
        async with self._session_factory() as session:
            return await pending_dedup_reviews(session, limit=limit)

    # ─── provider sync state (T-213g) ───────────────────────────────────────

    async def get_sync_state(
        self, *, provider: str, dataset_key: str, sync_scope: str = "default"
    ) -> SyncState | None:
        """provider/dataset/scope 1건 sync state. 없으면 ``None`` (read)."""
        async with self._session_factory() as session:
            return await repo_get_sync_state(
                session,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=sync_scope,
            )

    async def list_sync_states(
        self,
        *,
        provider: str,
        dataset_key: str | None = None,
        sync_scope: str | None = None,
    ) -> list[SyncState]:
        """provider sync state 목록(데이터 신선도). filter optional (read, T-213g)."""
        async with self._session_factory() as session:
            return await repo_list_sync_states(
                session,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=sync_scope,
            )

    async def record_sync_success(
        self,
        *,
        provider: str,
        dataset_key: str,
        sync_scope: str = "default",
        cursor: dict[str, Any],
        next_run_after: datetime | None = None,
    ) -> SyncState:
        """적재 성공 기록 — cursor 전진 + last_success_at (write, 1 transaction)."""
        async with self._session_factory() as session, session.begin():
            return await repo_record_sync_success(
                session,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=sync_scope,
                cursor=cursor,
                next_run_after=next_run_after,
            )

    async def record_sync_failure(
        self,
        *,
        provider: str,
        dataset_key: str,
        sync_scope: str = "default",
        next_run_after: datetime | None = None,
    ) -> SyncState:
        """적재 실패 기록 — cursor 미전진 + last_failure_at + 연속 실패 +1 (write)."""
        async with self._session_factory() as session, session.begin():
            return await repo_record_sync_failure(
                session,
                provider=provider,
                dataset_key=dataset_key,
                sync_scope=sync_scope,
                next_run_after=next_run_after,
            )

    # ─── KMA weather 대상 조회 (T-219b) ─────────────────────────────────────

    async def list_poi_cache_target_coords(
        self,
        *,
        external_system: str | None = None,
    ) -> list[tuple[float, float]]:
        """활성(미삭제 + update_enabled) POI cache target ``(lon, lat)`` 목록 (read).

        KMA weather 적재 대상 격자 산출용 — 외부 시스템이 등록한 관심 지점이
        1차 weather 대상이다(`docs/etl/kma-weather-etl.md` §3 옵션 B). exact
        ``external_system``을 주면 그 시스템의 target만 반환한다.
        """
        async with self._session_factory() as session:
            return await repo_list_active_target_coords(
                session,
                external_system=external_system,
            )

    async def list_active_poi_cache_target_external_systems(self) -> list[str]:
        """활성 POI cache target을 가진 canonical external system 목록 (read)."""
        async with self._session_factory() as session:
            return await _repo_list_active_target_systems(session)

    async def has_active_poi_cache_targets_for_external_system(
        self,
        external_system: str,
    ) -> bool:
        """exact external system에 활성 POI cache target이 있는지 확인한다 (read)."""
        async with self._session_factory() as session:
            return await _repo_has_active_target_system(
                session,
                external_system,
            )

    async def list_active_place_coords(self) -> list[tuple[str, float, float]]:
        """미삭제 place feature의 ``(feature_id, lon, lat)`` 전량 (read).

        ``deleted_at IS NULL`` 기준 — ``status='inactive'``여도 미삭제면 날씨를
        붙일 수 있다(D-12 read 정합). 호출자(Dagster asset)가 좌표를 KMA 격자로
        변환해 대상 격자와 일치하는 feature에 ``WeatherValue``를 적재한다.
        """
        async with self._session_factory() as session:
            return await repo_list_active_place_coords(session)

    async def list_primary_place_locator(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
    ) -> list[tuple[str, str, float, float]]:
        """primary place feature의 ``(source_entity_id, feature_id, lon, lat)`` 전량 (read, #547).

        ``(provider, dataset_key, source_entity_type)`` primary source이고 좌표가 있는
        place feature를 provider 파생 자연키(``source_entity_id``)와 함께 반환한다.
        호출자(Dagster 휴게소 유가 asset)가 이 목록으로 휴게소명·노선·방향 자연키 →
        (feature_id, 좌표) locator를 구성해 lon/lat 없는 유가 record가 place 좌표·
        ``parent_feature_id``를 상속하게 한다(geocoding 미경유 — 좌표 출처는 place).
        """
        async with self._session_factory() as session:
            return await repo_list_primary_place_locator(
                session,
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
            )

    # ─── weather card (T-213e) ───────────────────────────────────────────────

    async def load_weather_values(self, values: Iterable[WeatherValue]) -> int:
        """``WeatherValue`` 들을 ``feature_weather_values``에 멱등 upsert (write)."""
        async with self._session_factory() as session, session.begin():
            return await repo_load_weather_values(session, values)

    # ─── price values (T-price) ───────────────────────────────────────────────

    async def load_price_values(self, values: Iterable[PriceValue]) -> int:
        """``PriceValue`` 들을 ``feature_price_values``에 멱등 upsert (write)."""
        async with self._session_factory() as session, session.begin():
            return await repo_load_price_values(session, values)

    async def load_price_features(
        self,
        price_bundles: Iterable[FeatureBundle],
        price_values: Iterable[PriceValue],
    ) -> PriceFeatureLoadResult:
        """price-kind anchor feature + 가격값을 한 transaction으로 적재한다."""
        bundles = list(price_bundles)
        values = list(price_values)
        async with self._session_factory() as session, session.begin():
            features = await load_bundles(session, bundles)
            value_count = await repo_load_price_values(session, values)
        return PriceFeatureLoadResult(features=features, price_values=value_count)

    async def load_air_quality(
        self,
        station_bundles: Iterable[FeatureBundle],
        weather_values: Iterable[WeatherValue],
    ) -> AirQualityLoadResult:
        """대기질 측정소 weather feature + 측정값을 **한 transaction**으로 적재(T-RV-55d).

        ① 측정소 weather-kind ``FeatureBundle``을 ``load_bundles``로 적재(FK 선결),
        ② 같은 transaction에서 air_quality ``WeatherValue``를 ``load_weather_values``로
        upsert한다. weather value의 ``feature_id``는 같은 transaction에서 막 적재된
        측정소 feature를 참조하므로 FK가 충족된다. 하나라도 실패하면 전체 rollback.

        변환(측정소→bundle, 측정값→value)은 호출자(dagster asset) 책임 —
        ``air_quality_stations_to_bundles`` / ``air_quality_to_weather_values``.
        """
        bundles = list(station_bundles)
        values = list(weather_values)
        async with self._session_factory() as session, session.begin():
            stations = await load_bundles(session, bundles)
            value_count = await repo_load_weather_values(session, values)
        return AirQualityLoadResult(stations=stations, weather_values=value_count)

    async def build_weather_card(
        self,
        *,
        feature_id: str,
        asof: datetime | None = None,
        freshness_seconds: int | None = None,
    ) -> WeatherCard:
        """feature weather card — forecast_style×metric_key 최신값 + freshness (read).

        ``infra.weather_repo.build_weather_card`` 위임(T-213e).
        """
        from kortravelmap.infra.weather_repo import DEFAULT_WEATHER_FRESHNESS_SECONDS

        fresh = (
            freshness_seconds
            if freshness_seconds is not None
            else DEFAULT_WEATHER_FRESHNESS_SECONDS
        )
        async with self._session_factory() as session:
            return await repo_build_weather_card(
                session, feature_id=feature_id, asof=asof, freshness_seconds=fresh
            )

    async def get_update_request(self, request_id: str) -> FeatureUpdateRequest | None:
        """Feature update request 단건 조회. 없으면 ``None``."""
        async with self._session_factory() as session:
            return await repo_get_update_request(session, request_id)

    async def list_update_requests(
        self,
        *,
        status: str | None = None,
        scope_type: str | None = None,
        provider: str | None = None,
        dataset_key: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> FeatureUpdateRequestPage:
        """Feature update request 목록을 keyset cursor로 조회한다."""
        async with self._session_factory() as session:
            return await repo_list_update_requests(
                session,
                status=status,
                scope_type=scope_type,
                provider=provider,
                dataset_key=dataset_key,
                created_from=created_from,
                created_to=created_to,
                limit=limit,
                cursor=cursor,
            )

    async def status_counts(self) -> StatusCounts:
        """운영 현황 카운트 스냅샷 (read-only) — ``ktmctl status``용.

        features(활성/비활성/kind별) + source_records(provider별) + import_jobs
        (status별) + dedup_review_queue(status별)를 한 번에 집계. mutex 불필요.
        """
        async with self._session_factory() as session:
            return await gather_status_counts(session)

    async def record_address_validation_findings(
        self,
        findings: Sequence[AddressValidationFinding],
        *,
        provider: str,
        dataset_key: str,
        run_id: str | None = None,
    ) -> IntegrityFindingSyncResult:
        """주소/좌표 검증 결과를 ``ops.data_integrity_violations``에 durable하게 남긴다.

        T-VN-H30A: 지금까지 검증 결과는 Dagster run metadata에만 있어 **run이 사라지면 증거도
        사라졌다**. ``/admin/issues``에서도 보이지 않았다. 같은 export를 매 run 전량 재생해도
        큐가 부풀지 않도록 ``dedupe_key``로 열린 이슈 1건에 접는다.

        ``feature_id``/``source_record_key``는 FK이므로 **적재된 대상에만** 넘긴다. 적재 전
        단계에서 drop된 행은 두 대상이 DB에 없으므로 id를 payload에만 담아야 한다 — 호출자가
        ``AddressValidationFinding.linked``로 구분해 준다.

        DB 예외는 raw SQLAlchemy/asyncpg 객체를 노출하지 않고
        ``IntegrityFindingPersistenceError``로 정규화한다. 호출자는 strict 정책에서 이를
        fail-closed로 처리하고, 다른 정책에서는 명시적 unrecorded metadata로 남길 수 있다.
        """
        if not provider or not dataset_key:
            raise ValueError("provider/dataset_key는 finding 정체성에 필수다.")

        # batch 안 중복 제거 — 같은 dedupe_key가 한 statement에 두 번 오면 Postgres가
        # "ON CONFLICT DO UPDATE command cannot affect row a second time"로 실패한다.
        # (payload가 byte-동일한 중복 레코드가 실제로 export에 존재한다.)
        deduped: dict[str, dict[str, Any]] = {}
        for finding in findings:
            if finding.provider not in {None, provider}:
                raise ValueError("finding provider가 기록 범위와 다르다.")
            if finding.dataset_key not in {None, dataset_key}:
                raise ValueError("finding dataset_key가 기록 범위와 다르다.")
            deduped[finding.dedupe_key] = {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_record_key": (
                    finding.source_record_key if finding.linked else None
                ),
                "feature_id": finding.feature_id if finding.linked else None,
                "violation_type": finding.violation_type,
                "severity": finding.severity,
                "message": finding.message,
                "payload": {
                    **dict(finding.payload),
                    "dedupe_key": finding.dedupe_key,
                    "occurrence_count": 1,
                },
            }
        rows = [deduped[key] for key in sorted(deduped)]
        try:
            async with self._session_factory() as session, session.begin():
                upserted = await sync_integrity_findings(
                    session,
                    provider=provider,
                    dataset_key=dataset_key,
                    findings=rows,
                    external_run_id=run_id,
                )
        except Exception as exc:  # noqa: BLE001
            raise IntegrityFindingPersistenceError(
                provider=provider,
                dataset_key=dataset_key,
                observed_count=len(findings),
                unique_count=len(rows),
                error_type=type(exc).__name__,
            ) from None
        return IntegrityFindingSyncResult(
            observed_count=len(findings),
            unique_count=len(rows),
            upserted_count=upserted,
        )

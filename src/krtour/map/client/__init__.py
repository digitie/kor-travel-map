"""``krtour.map.client`` — ``AsyncKrtourMapClient`` (라이브러리 진입점).

krtour-map API/Dagster 내부 구현과 테스트가 사용하는 Python 진입점이다. TripMate
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
  적재한다. ``dry_run=True``는 DB write 없이 scope 해석 preview만 반환한다.
- 읽기: ``features_in_bounds`` / ``get_feature`` / ``pending_dedup_reviews``.

engine 수명은 호출자 소유 (ADR-004 ``infra/db.py`` — ``await engine.dispose()``는
호출자 책임). 따라서 ``__aexit__``는 engine을 닫지 않는다.

후속(별도 PR): ``upload_feature_files`` / ``upsert_sync_state`` /
``build_weather_card`` 등.

ADR 참조
--------
- ADR-002 — async-only (sync 인터페이스 추가 금지)
- ADR-045 — TripMate 연계는 OpenAPI, client는 krtour-map 내부 API/Dagster용
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL (``infra/*_repo.py``); client가 commit
- ADR-016 — dedup 후보 ``ops.dedup_review_queue`` 적재
- ADR-020 — 본 모듈에 FastAPI/Uvicorn import 금지 (디버그 REST는 별도 패키지)
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any

from krtour.map.core.dedup import find_dedup_candidates, find_sibling_candidates
from krtour.map.enrichment import (
    PhoneEnrichmentCandidate,
    PhoneEnrichmentResult,
    apply_place_phone_enrichment,
    find_place_phone_candidates,
)
from krtour.map.infra.consistency import (
    DEDUP_PENDING_WARN_THRESHOLD,
    ConsistencyReport,
)
from krtour.map.infra.consistency import (
    run_consistency_checks as repo_run_consistency_checks,
)
from krtour.map.infra.db import make_async_session_factory
from krtour.map.infra.dedup_refresh_repo import (
    DedupRefreshScope,
    list_dedup_refresh_features,
)
from krtour.map.infra.dedup_repo import (
    DedupQueueResult,
    enqueue_dedup_candidates,
    pending_dedup_reviews,
)
from krtour.map.infra.feature_repo import (
    FeatureLoadResult,
    features_in_bbox,
    get_feature_row,
    load_bundles,
)
from krtour.map.infra.feature_update_executor import (
    FeatureUpdateExecutionResult,
    ProviderDatasetRefreshRunner,
)
from krtour.map.infra.feature_update_executor import (
    execute_feature_update_request as repo_execute_feature_update_request,
)
from krtour.map.infra.feature_update_executor import (
    execute_next_feature_update_request as repo_execute_next_feature_update_request,
)
from krtour.map.infra.feature_update_repo import (
    FeatureUpdateRequest,
    FeatureUpdateRequestPage,
    FeatureUpdateRequestPreview,
)
from krtour.map.infra.feature_update_repo import (
    cancel_update_request as repo_cancel_update_request,
)
from krtour.map.infra.feature_update_repo import (
    enqueue_feature_update_request as repo_enqueue_feature_update_request,
)
from krtour.map.infra.feature_update_repo import (
    finish_update_request as repo_finish_update_request,
)
from krtour.map.infra.feature_update_repo import (
    get_update_request as repo_get_update_request,
)
from krtour.map.infra.feature_update_repo import (
    list_update_requests as repo_list_update_requests,
)
from krtour.map.infra.feature_update_repo import (
    peek_next_update_request as repo_peek_next_update_request,
)
from krtour.map.infra.merge_repo import MergeOutcome, merge_from_review
from krtour.map.infra.status_repo import StatusCounts, gather_status_counts
from krtour.map.mois import DEFAULT_BATCH_SIZE as MOIS_DEFAULT_BATCH_SIZE
from krtour.map.mois import (
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
from krtour.map.offline_upload import (
    OfflineUploadColumnMapping,
    OfflineUploadLoadResult,
    OfflineUploadObjectStore,
    OfflineUploadValidationResult,
)
from krtour.map.offline_upload import (
    run_offline_upload_load_job as repo_run_offline_upload_load_job,
)
from krtour.map.offline_upload import (
    run_offline_upload_validation_job as repo_run_offline_upload_validation_job,
)
from krtour.map.providers.mois import DATASET_KEY_BULK as MOIS_DATASET_KEY_BULK
from krtour.map.providers.mois import DATASET_KEY_HISTORY as MOIS_DATASET_KEY_HISTORY
from krtour.map.providers.mois import PROVIDER_NAME as MOIS_PROVIDER_NAME

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncEngine

    from krtour.map.core.dedup import DedupCandidate, DedupInput
    from krtour.map.dto import FeatureBundle
    from krtour.map.geocoding import AddressResolver, ReverseGeocoder
    from krtour.map.infra.scope_repo import SigunguByRadiusResolver
    from krtour.map.providers.mois import MoisLicensePlaceRecord
    from krtour.map.settings import KrtourMapSettings

__all__ = [
    "AsyncKrtourMapClient",
    "DedupRefreshResult",
    "DedupSyncResult",
    "OfflineUploadColumnMapping",
    "OfflineUploadLoadResult",
    "OfflineUploadValidationResult",
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


class AsyncKrtourMapClient:
    """라이브러리 진입점 — DB 적재/조회 + dedup 후보 동기화 오케스트레이션.

    Parameters
    ----------
    engine
        ``infra.make_async_engine`` 등으로 만든 ``AsyncEngine`` (호출자 소유).
    settings
        ``KrtourMapSettings`` (선택). 현재 적재/dedup 경로는 사용하지 않으나,
        후속 weather card / file upload 경로가 참조.

    Examples
    --------
    >>> async with AsyncKrtourMapClient(engine) as client:  # doctest: +SKIP
    ...     result = await client.load_feature_bundles(bundles)
    ...     sync = await client.sync_dedup_candidates(knps_temples, krh_temples)
    """

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        settings: KrtourMapSettings | None = None,
    ) -> None:
        self._engine = engine
        self._session_factory = make_async_session_factory(engine)
        self._settings = settings

    async def __aenter__(self) -> AsyncKrtourMapClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # engine 수명은 호출자 소유 (ADR-004 infra/db.py) — 여기서 dispose 안 함.
        return None

    # ─── write (transaction 소유) ──────────────────────────────────────────

    async def load_feature_bundles(
        self, bundles: Iterable[FeatureBundle]
    ) -> FeatureLoadResult:
        """``FeatureBundle`` 다수를 한 transaction으로 적재 (commit/rollback).

        feature → source_record → source_link 순 idempotent upsert
        (``infra.load_bundles``). 하나라도 실패하면 전체 rollback.
        """
        async with self._session_factory() as session, session.begin():
            return await load_bundles(session, bundles)

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
        idempotent upsert (``krtour.map.mois.load_mois_license_features_bulk``).
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
        dry_run: bool = False,
        operator: str | None = None,
        reason: str | None = None,
        sigungu_resolver: SigunguByRadiusResolver | None = None,
    ) -> FeatureUpdateRequest | FeatureUpdateRequestPreview:
        """Feature update request를 생성하거나 dry-run preview를 반환한다.

        ``dry_run=True``이면 DB row/import job을 만들지 않고 scope 해석 결과만
        반환한다. 실제 요청은 ``ops.feature_update_requests``와 연결
        ``ops.import_jobs``를 한 transaction에 생성한다.
        """
        if dry_run:
            async with self._session_factory() as session:
                return await repo_enqueue_feature_update_request(
                    session,
                    scope=scope,
                    providers=providers,
                    dataset_keys=dataset_keys,
                    update_policy=update_policy,
                    run_mode=run_mode,
                    priority=priority,
                    dry_run=True,
                    operator=operator,
                    reason=reason,
                    sigungu_resolver=sigungu_resolver,
                )
        async with self._session_factory() as session, session.begin():
            return await repo_enqueue_feature_update_request(
                session,
                scope=scope,
                providers=providers,
                dataset_keys=dataset_keys,
                update_policy=update_policy,
                run_mode=run_mode,
                priority=priority,
                dry_run=False,
                operator=operator,
                reason=reason,
                sigungu_resolver=sigungu_resolver,
            )

    async def cancel_update_request(
        self,
        request_id: str,
        *,
        error_message: str | None = None,
    ) -> FeatureUpdateRequest | None:
        """queued/running feature update request를 ``cancelled``로 닫는다."""
        async with self._session_factory() as session, session.begin():
            return await repo_cancel_update_request(
                session, request_id, error_message=error_message
            )

    async def fail_update_request(
        self,
        request_id: str,
        *,
        dagster_run_id: str | None = None,
        error_message: str | None = None,
    ) -> FeatureUpdateRequest | None:
        """queued/running feature update request를 ``failed``로 닫는다."""
        async with self._session_factory() as session, session.begin():
            return await repo_finish_update_request(
                session,
                request_id,
                state="failed",
                dagster_run_id=dagster_run_id,
                error_message=error_message,
            )

    async def peek_next_update_request(self) -> FeatureUpdateRequest | None:
        """Dagster sensor가 다음 queued request를 상태 변경 없이 확인한다."""
        async with self._session_factory() as session:
            return await repo_peek_next_update_request(session)

    async def execute_next_feature_update_request(
        self,
        *,
        runner: ProviderDatasetRefreshRunner,
        dagster_run_id: str | None = None,
        sigungu_resolver: SigunguByRadiusResolver | None = None,
    ) -> FeatureUpdateExecutionResult | None:
        """queued feature update request 1건을 claim하고 runner로 실행한다.

        provider API 호출/Dagster orchestration은 runner가 담당한다. 본 client는
        request/import job 상태, scope 재해석, target link 갱신, 성공/실패 전이를
        한 transaction으로 묶는다.
        """
        async with self._session_factory() as session, session.begin():
            return await repo_execute_next_feature_update_request(
                session,
                runner=runner,
                dagster_run_id=dagster_run_id,
                sigungu_resolver=sigungu_resolver,
            )

    async def execute_feature_update_request(
        self,
        request_id: str,
        *,
        runner: ProviderDatasetRefreshRunner,
        dagster_run_id: str | None = None,
        sigungu_resolver: SigunguByRadiusResolver | None = None,
    ) -> FeatureUpdateExecutionResult | None:
        """특정 feature update request를 즉시 실행한다. 없으면 ``None``."""
        async with self._session_factory() as session, session.begin():
            request = await repo_get_update_request(session, request_id)
            if request is None:
                return None
            return await repo_execute_feature_update_request(
                session,
                request,
                runner=runner,
                dagster_run_id=dagster_run_id,
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
        candidates = find_dedup_candidates(
            left, right, include_auto_merge=include_auto_merge
        )
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
        candidates = find_sibling_candidates(
            features, include_auto_merge=include_auto_merge
        )
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
            candidates = find_dedup_candidates(
                left, right, include_auto_merge=include_auto_merge
            )
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
            candidates = find_sibling_candidates(
                features, include_auto_merge=include_auto_merge
            )
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
    ) -> ConsistencyReport:
        """F1~F4 consistency report를 실행하고 필요 시 DB에 저장한다."""
        async with self._session_factory() as session, session.begin():
            return await repo_run_consistency_checks(
                session,
                batch_id=batch_id,
                persist=persist,
                sample_limit=sample_limit,
                dedup_pending_threshold=dedup_pending_threshold,
            )

    async def merge_dedup_review(
        self,
        review_key: str,
        *,
        merged_by: str | None = None,
        reason: str | None = None,
    ) -> MergeOutcome:
        """검토 큐 후보(``review_key``) 1쌍을 master 자동 선정 후 병합한다 (ADR-016).

        ``infra.merge_repo.merge_from_review``를 한 transaction에서 실행: loser의
        source_link를 master로 재지정, loser feature soft-delete, ``feature_merge_history``
        기록, 큐 행 ``merged`` 전이. master는 ``select_master``(좌표 → updated_at →
        source 우선순위)로 결정. 큐 행이 없거나 이미 검토됐으면 ``MergeError``.

        **중복 실행 직렬화(ADR-039)는 호출 측 책임** — CLI ``dedup-merge``가
        ``dedup-merge:{review_key}`` advisory lock으로 감싼다(본 메서드는 lock 미적용).
        """
        async with self._session_factory() as session, session.begin():
            return await merge_from_review(
                session, review_key, merged_by=merged_by, reason=reason
            )

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

    async def pending_dedup_reviews(
        self, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """검토 대기(``status='pending'``) dedup 후보 list — total_score 내림차순."""
        async with self._session_factory() as session:
            return await pending_dedup_reviews(session, limit=limit)

    async def get_update_request(
        self, request_id: str
    ) -> FeatureUpdateRequest | None:
        """Feature update request 단건 조회. 없으면 ``None``."""
        async with self._session_factory() as session:
            return await repo_get_update_request(session, request_id)

    async def list_update_requests(
        self,
        *,
        state: str | None = None,
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
                state=state,
                scope_type=scope_type,
                provider=provider,
                dataset_key=dataset_key,
                created_from=created_from,
                created_to=created_to,
                limit=limit,
                cursor=cursor,
            )

    async def status_counts(self) -> StatusCounts:
        """운영 현황 카운트 스냅샷 (read-only) — ``krtour-map status``용.

        features(활성/비활성/kind별) + source_records(provider별) + import_jobs
        (state별) + dedup_review_queue(status별)를 한 번에 집계. mutex 불필요.
        """
        async with self._session_factory() as session:
            return await gather_status_counts(session)

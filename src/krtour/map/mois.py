"""``krtour.map.mois`` — MOIS 인허가 feature 적재 loader (Sprint 4a).

``providers.mois``의 변환 출력(``FeatureBundle``)을 PostGIS에 적재하는 얇은
오케스트레이션. 변환(provider) → 적재(infra) 사이를 잇는 단위 of work이며,
``AsyncKrtourMapClient.load_feature_bundles``와 동일하게 **transaction은 호출자
또는 본 함수가 잡는다**.

범위 (Sprint 4a loader)
-----------------------
- ``load_mois_license_features_bulk`` — 소량 batch UPSERT (단위 테스트 / admin
  trigger 용). ``license_records_to_bundles``(async) → ``infra.load_bundles``.
- snapshot ``delete_not_in`` / advisory lock(ADR-011) / mois source DB iterator
  (``collect_and_load_*``)는 **후속 PR** (docs/mois-feature-etl.md §9). 본 모듈은
  in-memory record iterable만 받는다 (mois 라이브러리 런타임 import 안 함).

ADR 참조
--------
- ADR-002 — async-only, infra는 commit 안 함(단위 of work는 호출자/본 함수)
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL(infra); 본 모듈이 session.begin() 소유
- ADR-006 — provider/mois 라이브러리 직접 사용 (wrapper 금지)
- ADR-013 — bulk COPY 최적화는 infra 후속 (현재 순차 upsert)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from krtour.map.infra.advisory_lock import try_advisory_lock
from krtour.map.infra.feature_repo import (
    FeatureLoadResult,
    load_bundles,
    soft_delete_features_not_in_snapshot,
)
from krtour.map.infra.jobs_repo import (
    ImportJob,
    finish_import_job,
    start_import_job,
)
from krtour.map.providers.mois import (
    DATASET_KEY_BULK,
    PROVIDER_NAME,
    license_records_to_bundles,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from krtour.map.geocoding import ReverseGeocoder
    from krtour.map.providers.mois import MoisLicensePlaceRecord

# providers.mois의 source_entity_type (license_place). 변환 모듈 내부 상수와 동일.
_LICENSE_ENTITY_TYPE = "license_place"

# import_jobs kind (data-model.md §9.1 예시).
_BULK_JOB_KIND = "mois_license_full_update"

# streaming 배치 적재 기본 크기 (대용량 source DB snapshot 메모리 바운드).
DEFAULT_BATCH_SIZE: Final[int] = 500


def _batched(
    records: Iterable[MoisLicensePlaceRecord], size: int
) -> Iterator[list[MoisLicensePlaceRecord]]:
    """iterable을 ``size``개씩 list 배치로 끊어 내보낸다 (메모리 바운드)."""
    batch: list[MoisLicensePlaceRecord] = []
    for record in records:
        batch.append(record)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _bulk_advisory_key(dataset_key: str) -> str:
    """Step A 단일 워커 직렬화용 advisory lock 키 (ADR-011/039 import:* 패턴)."""
    return f"import:{PROVIDER_NAME}:{dataset_key}"


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "MoisBulkSyncResult",
    "MoisBulkJobResult",
    "load_mois_license_features_bulk",
    "delete_mois_license_features_not_in",
    "sync_mois_license_features_bulk",
    "run_mois_license_bulk_job",
]


@dataclass(frozen=True)
class MoisBulkSyncResult:
    """``sync_mois_license_features_bulk`` 결과 — 적재 카운트 + 비활성화 수.

    - ``load`` — upsert 카운트 (``FeatureLoadResult``).
    - ``deactivated`` — snapshot에 없어 soft-delete된 기존 feature 수.
    """

    load: FeatureLoadResult
    deactivated: int


@dataclass(frozen=True)
class MoisBulkJobResult:
    """``run_mois_license_bulk_job`` 결과 — 작업 추적 + 동기화 카운트.

    - ``acquired`` — advisory lock 획득 여부. ``False``면 다른 워커가 이미 적재
      중이라 건너뜀(``job``/``sync`` 모두 ``None``).
    - ``job`` — 종료 상태의 ``ImportJob``(done/failed). lock 미획득 시 ``None``.
    - ``sync`` — ``MoisBulkSyncResult``. 실패 또는 lock 미획득 시 ``None``.
    """

    acquired: bool
    job: ImportJob | None = None
    sync: MoisBulkSyncResult | None = None


async def load_mois_license_features_bulk(
    session: AsyncSession,
    records: Iterable[MoisLicensePlaceRecord],
    *,
    fetched_at: datetime,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> FeatureLoadResult:
    """MOIS 인허가 ``PlaceRecord`` 묶음을 변환 → 적재 (소량 batch UPSERT).

    PROMOTED 슬러그 / 영업중 record만 ``providers.mois.license_records_to_bundles``로
    bundle화한 뒤 ``infra.load_bundles``로 idempotent upsert한다. **commit은
    호출자 책임** — `session.begin()` 안에서 호출하거나, 본 함수 반환 후 호출자가
    commit한다 (단위 of work, ADR-002/004). EXCLUDED/미매핑/비영업 record는 변환
    단계에서 skip되어 적재 대상이 아니다.

    Parameters
    ----------
    session
        적재 대상 ``AsyncSession`` (commit은 호출자/감싼 transaction 소유).
    records
        ``MoisLicensePlaceRecord`` Protocol 만족 iterable (mois source DB
        영업중 row 등). 본 모듈은 mois 라이브러리를 import하지 않는다.
    fetched_at
        provider 호출 시각 (KST aware, ADR-019).
    dataset_key
        ``mois_license_features_bulk`` (기본) / ``_history``.
    reverse_geocoder
        좌표 → ``Address`` async 역지오코더. ``legal_dong_code`` 부재 시에만
        호출되어 bjd_code를 보강한다 (ADR-009). 중복 좌표는 변환 함수 내부에서
        ``cached_reverse_geocoder``로 1회만 호출.

    Returns
    -------
    FeatureLoadResult
        feature/source_record/source_link upsert 카운트. 변환 대상이 없으면
        모두 0.
    """
    bundles = await license_records_to_bundles(
        records,
        fetched_at=fetched_at,
        dataset_key=dataset_key,
        reverse_geocoder=reverse_geocoder,
    )
    return await load_bundles(session, bundles)


async def delete_mois_license_features_not_in(
    session: AsyncSession,
    snapshot_source_entity_ids: set[str],
    *,
    dataset_key: str = DATASET_KEY_BULK,
) -> int:
    """snapshot에 없는 mois license feature를 soft-delete (status='inactive').

    Step A bulk snapshot 적재 후, 이번 snapshot에서 사라진(폐업/제외) feature를
    비활성화한다 (ADR-017 — place는 무기한 유지, status만 inactive + deleted_at).
    이미 비활성인 feature는 건드리지 않는다. commit은 호출자 책임.

    Parameters
    ----------
    snapshot_source_entity_ids
        이번 snapshot에 적재된 ``source_entity_id``(= ``f"{slug}::{mng_no}"``) 집합.
        비어 있으면 해당 dataset의 모든 활성 mois license feature가 비활성화된다.
    dataset_key
        대상 dataset (기본 ``mois_license_features_bulk``).

    Returns
    -------
    int
        soft-delete된 feature 수.
    """
    return await soft_delete_features_not_in_snapshot(
        session,
        provider=PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=_LICENSE_ENTITY_TYPE,
        snapshot_source_entity_ids=snapshot_source_entity_ids,
    )


async def sync_mois_license_features_bulk(
    session: AsyncSession,
    records: Iterable[MoisLicensePlaceRecord],
    *,
    fetched_at: datetime,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> MoisBulkSyncResult:
    """전체 영업중 snapshot 적재 + snapshot 부재 feature soft-delete (Step A bulk).

    ``records``는 **이번 전체 snapshot**(영업중 PROMOTED record)이어야 한다 —
    부분 batch에 쓰면 누락분이 전부 비활성화된다. mois source DB의 대용량 스트림을
    메모리 바운드로 처리하기 위해 ``batch_size``개씩 끊어 변환·upsert하며 snapshot
    key만 누적한다. 전체 적재 후 snapshot에 없는 기존 feature를 soft-delete한다.
    commit은 호출자/감싼 transaction 소유 (한 단위 of work — 하나라도 실패하면
    전체 rollback).

    ``records``로 ``mois.db.iter_open_place_records(...)``(source DB 영업중 스트림)을
    그대로 넘기면 Step A가 완성된다 (본 모듈은 ADR-006상 mois를 import하지 않으므로
    iterator를 호출자가 주입).
    """
    load_result = FeatureLoadResult()
    snapshot_keys: set[str] = set()
    for batch in _batched(records, batch_size):
        bundles = await license_records_to_bundles(
            batch,
            fetched_at=fetched_at,
            dataset_key=dataset_key,
            reverse_geocoder=reverse_geocoder,
        )
        load_result = load_result.merge(await load_bundles(session, bundles))
        snapshot_keys.update(b.source_record.source_entity_id for b in bundles)
    deactivated = await soft_delete_features_not_in_snapshot(
        session,
        provider=PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=_LICENSE_ENTITY_TYPE,
        snapshot_source_entity_ids=snapshot_keys,
    )
    return MoisBulkSyncResult(load=load_result, deactivated=deactivated)


async def run_mois_license_bulk_job(
    session: AsyncSession,
    records: Iterable[MoisLicensePlaceRecord],
    *,
    fetched_at: datetime,
    dataset_key: str = DATASET_KEY_BULK,
    reverse_geocoder: ReverseGeocoder | None = None,
    source_checksum: str | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> MoisBulkJobResult:
    """Step A bulk 적재를 **advisory lock + import_jobs 추적**으로 감싼 오케스트레이션.

    1. ``try_advisory_lock("import:python-mois-api:<dataset_key>")`` — 단일 워커
       직렬화. 다른 워커가 이미 적재 중이면 대기하지 않고
       ``MoisBulkJobResult(acquired=False)``로 즉시 반환(skip).
    2. ``start_import_job`` — ``state='running'`` 작업 row 생성(추적).
    3. ``sync_mois_license_features_bulk`` — 변환 → upsert → snapshot prune.
    4. ``finish_import_job`` — 성공 시 ``done``(progress 100), 예외 시 ``failed``
       (error_message 기록) 후 re-raise.

    **transaction 주의**: 본 함수는 한 ``session``에서 job row와 데이터 작업을
    함께 수행한다. 호출자가 outer transaction을 rollback하면 ``failed`` 작업
    기록도 함께 사라진다. 작업 기록을 데이터 실패와 독립적으로 영속화하려면
    ``AsyncKrtourMapClient.run_mois_license_bulk_job``(분리 transaction)을 쓴다.
    """
    async with try_advisory_lock(session, _bulk_advisory_key(dataset_key)) as acquired:
        if not acquired:
            return MoisBulkJobResult(acquired=False)
        job = await start_import_job(
            session,
            kind=_BULK_JOB_KIND,
            payload={"dataset_key": dataset_key},
            source_checksum=source_checksum,
        )
        try:
            sync = await sync_mois_license_features_bulk(
                session,
                records,
                fetched_at=fetched_at,
                dataset_key=dataset_key,
                reverse_geocoder=reverse_geocoder,
                batch_size=batch_size,
            )
        except Exception as exc:
            # 작업을 failed로 표시 후 원래 예외를 re-raise. 같은 transaction을
            # 호출자가 rollback하면 이 기록도 사라진다(docstring 참조).
            await finish_import_job(
                session, job.job_id, state="failed", error_message=str(exc)
            )
            raise
        finished = await finish_import_job(session, job.job_id, state="done")
        return MoisBulkJobResult(acquired=True, job=finished or job, sync=sync)

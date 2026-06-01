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
from typing import TYPE_CHECKING

from krtour.map.infra.feature_repo import (
    FeatureLoadResult,
    load_bundles,
    soft_delete_features_not_in_snapshot,
)
from krtour.map.providers.mois import (
    DATASET_KEY_BULK,
    PROVIDER_NAME,
    license_records_to_bundles,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from krtour.map.geocoding import ReverseGeocoder
    from krtour.map.providers.mois import MoisLicensePlaceRecord

# providers.mois의 source_entity_type (license_place). 변환 모듈 내부 상수와 동일.
_LICENSE_ENTITY_TYPE = "license_place"

__all__ = [
    "MoisBulkSyncResult",
    "load_mois_license_features_bulk",
    "delete_mois_license_features_not_in",
    "sync_mois_license_features_bulk",
]


@dataclass(frozen=True)
class MoisBulkSyncResult:
    """``sync_mois_license_features_bulk`` 결과 — 적재 카운트 + 비활성화 수.

    - ``load`` — upsert 카운트 (``FeatureLoadResult``).
    - ``deactivated`` — snapshot에 없어 soft-delete된 기존 feature 수.
    """

    load: FeatureLoadResult
    deactivated: int


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
) -> MoisBulkSyncResult:
    """전체 영업중 snapshot 적재 + snapshot 부재 feature soft-delete (Step A bulk).

    ``records``는 **이번 전체 snapshot**(영업중 PROMOTED record)이어야 한다 —
    부분 batch에 쓰면 누락분이 전부 비활성화된다. 변환 → upsert → snapshot에 없는
    기존 feature soft-delete를 한 단위 of work로 수행한다 (commit은 호출자/감싼
    transaction 소유). mois source DB cursor iterator(``collect_and_load_*``)는
    후속 PR — 본 함수는 in-memory snapshot iterable을 받는다.
    """
    bundles = await license_records_to_bundles(
        records,
        fetched_at=fetched_at,
        dataset_key=dataset_key,
        reverse_geocoder=reverse_geocoder,
    )
    load_result = await load_bundles(session, bundles)
    snapshot_keys = {b.source_record.source_entity_id for b in bundles}
    deactivated = await soft_delete_features_not_in_snapshot(
        session,
        provider=PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=_LICENSE_ENTITY_TYPE,
        snapshot_source_entity_ids=snapshot_keys,
    )
    return MoisBulkSyncResult(load=load_result, deactivated=deactivated)

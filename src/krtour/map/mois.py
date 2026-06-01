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

from typing import TYPE_CHECKING

from krtour.map.infra.feature_repo import FeatureLoadResult, load_bundles
from krtour.map.providers.mois import (
    DATASET_KEY_BULK,
    license_records_to_bundles,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

    from krtour.map.geocoding import ReverseGeocoder
    from krtour.map.providers.mois import MoisLicensePlaceRecord

__all__ = ["load_mois_license_features_bulk"]


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

"""``krtour.map.client`` — ``AsyncKrtourMapClient`` (라이브러리 진입점).

TripMate가 ``pip install`` 후 import하는 단일 진입점. SQLAlchemy 2 async
``AsyncEngine``을 주입받아 메서드 호출로 사용한다 (ADR-003 함수 직접 호출, HTTP
없음). 본 client는 **transaction 경계의 소유자**다 — ``infra/*_repo.py``는
"commit은 호출자 책임"으로 ``session.execute``만 하므로, write 메서드가
``session.begin()``으로 commit/rollback을 잡는다 (단위 of work).

오케스트레이션 범위 (#122 실 DB 적재):
- ``load_feature_bundles`` — provider 변환 출력(``FeatureBundle``)을 한
  transaction으로 적재 (``infra.load_bundles``).
- ``sync_dedup_candidates`` — cross-provider 중복 후보 탐지(``core.dedup.
  find_dedup_candidates``, 순수) → ``ops.dedup_review_queue`` 적재
  (``infra.enqueue_dedup_candidates``). 두 feature가 먼저 적재돼 있어야 함(FK).
- 읽기: ``features_in_bounds`` / ``get_feature`` / ``pending_dedup_reviews``.

engine 수명은 호출자 소유 (ADR-004 ``infra/db.py`` — ``await engine.dispose()``는
호출자 책임). 따라서 ``__aexit__``는 engine을 닫지 않는다.

후속(별도 PR): ``upload_feature_files`` / ``upsert_sync_state`` /
``build_weather_card`` 등.

ADR 참조
--------
- ADR-002 — async-only (sync 인터페이스 추가 금지)
- ADR-003 — TripMate 연계는 함수 직접 호출 (REST 없음)
- ADR-004 — ORM 매핑만, 쿼리는 raw SQL (``infra/*_repo.py``); client가 commit
- ADR-016 — dedup 후보 ``ops.dedup_review_queue`` 적재
- ADR-020 — 본 모듈에 FastAPI/Uvicorn import 금지 (디버그 REST는 별도 패키지)
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import TYPE_CHECKING, Any

from krtour.map.core.dedup import find_dedup_candidates
from krtour.map.infra.db import make_async_session_factory
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
from krtour.map.mois import load_mois_license_features_bulk
from krtour.map.providers.mois import DATASET_KEY_BULK as MOIS_DATASET_KEY_BULK

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncEngine

    from krtour.map.core.dedup import DedupCandidate, DedupInput
    from krtour.map.dto import FeatureBundle
    from krtour.map.geocoding import ReverseGeocoder
    from krtour.map.providers.mois import MoisLicensePlaceRecord
    from krtour.map.settings import KrtourMapSettings

__all__ = ["AsyncKrtourMapClient", "DedupSyncResult"]


@dataclass(frozen=True)
class DedupSyncResult:
    """``sync_dedup_candidates`` 결과 — 탐지된 후보 + 큐 적재 카운트.

    - ``candidates`` — ``find_dedup_candidates`` 출력 (score 내림차순).
    - ``queue`` — ``ops.dedup_review_queue`` upsert 결과
      (inserted/updated/skipped).
    """

    candidates: list[DedupCandidate]
    queue: DedupQueueResult


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
    ) -> FeatureLoadResult:
        """MOIS 인허가 ``PlaceRecord`` 묶음을 변환 → 적재 (한 transaction).

        PROMOTED 슬러그 / 영업중 record만 ``providers.mois``로 bundle화한 뒤
        idempotent upsert (``krtour.map.mois.load_mois_license_features_bulk``).
        EXCLUDED/미매핑/비영업 record는 변환 단계에서 skip. 하나라도 실패하면
        전체 rollback. snapshot delete / advisory lock은 후속 PR (Sprint 4a §9).
        """
        async with self._session_factory() as session, session.begin():
            return await load_mois_license_features_bulk(
                session,
                records,
                fetched_at=fetched_at,
                dataset_key=dataset_key,
                reverse_geocoder=reverse_geocoder,
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

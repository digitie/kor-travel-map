"""``test_client_orchestration`` — ``AsyncKrtourMapClient`` 적재/dedup (#122).

client가 transaction을 소유해 commit하는 경로를 실 PostGIS(migrated_engine,
alembic head)에서 검증한다:

- ``load_feature_bundles`` — FeatureBundle 적재 후 **별도 세션** ``get_feature``로
  commit 확인 + ``features_in_bounds`` bbox 조회.
- ``sync_dedup_candidates`` — 사전 적재된 temple 두 건을 cross-score → 후보 적재 →
  ``pending_dedup_reviews``로 큐 확인. ``include_auto_merge=False`` 패스스루.

client는 migrated_session(rollback 격리)과 달리 **commit**하므로, 각 테스트는
``map_client`` fixture teardown에서 관련 테이블을 TRUNCATE해 격리한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from krtour.map.client import AsyncKrtourMapClient
from krtour.map.dto.coordinate import Coordinate
from krtour.map.infra.feature_update_repo import (
    FeatureUpdateRequest,
    FeatureUpdateRequestPreview,
)
from krtour.map.infra.models import FeatureRow
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_TEMPLE_CAT = "01070100"

_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue, "
    "ops.feature_update_requests, ops.import_jobs RESTART IDENTITY CASCADE"
)


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 (좌표 있는 케이스)."""

    management_no: str
    festival_name: str
    venue_name: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    road_address: str | None
    jibun_address: str | None
    organizer_name: str | None
    organizer_tel: str | None
    data_reference_date: date | None
    provider_org_name: str | None
    bjd_code: str | None = None
    sigungu_code: str | None = None
    sido_code: str | None = None
    admin_address: str | None = None


_FEST = _Festival(
    management_no="FEST-CLIENT-001",
    festival_name="서울 봄꽃 축제",
    venue_name="여의도공원",
    start_date=date(2026, 4, 5),
    end_date=date(2026, 4, 12),
    description="봄꽃 축제 상세.",
    latitude=Decimal("37.5263"),
    longitude=Decimal("126.9239"),
    road_address="서울특별시 영등포구 여의공원로 120",
    jibun_address="서울특별시 영등포구 여의도동 8",
    organizer_name="영등포구청",
    organizer_tel="02-2670-3114",
    data_reference_date=date(2026, 3, 1),
    provider_org_name="서울특별시 영등포구",
)


@dataclass(frozen=True)
class _Stub:
    """``DedupInput`` Protocol 만족."""

    feature_id: str
    name: str
    coord: Coordinate | None
    category: str


def _temple(feature_id: str, name: str = "불국사") -> FeatureRow:
    from geoalchemy2 import WKTElement

    return FeatureRow(
        feature_id=feature_id,
        kind="place",
        name=name,
        category=_TEMPLE_CAT,
        coord=WKTElement("POINT(129.3320 35.7900)", srid=4326),
        detail={"summary": "temple"},
    )


def _stub(feature_id: str, name: str = "불국사") -> _Stub:
    return _Stub(
        feature_id=feature_id,
        name=name,
        coord=Coordinate(lon=Decimal("129.3320"), lat=Decimal("35.7900")),
        category=_TEMPLE_CAT,
    )


@pytest.fixture
async def map_client(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncKrtourMapClient]:
    """client + teardown TRUNCATE (client는 commit하므로 명시 격리)."""
    client = AsyncKrtourMapClient(migrated_engine)
    try:
        yield client
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text(_TRUNCATE_SQL))


async def _seed_temples(engine: AsyncEngine, *feature_ids: str) -> None:
    """temple feature를 committed로 적재 (dedup FK 대상)."""
    async with AsyncSession(engine) as session, session.begin():
        for fid in feature_ids:
            session.add(_temple(fid))


async def test_load_feature_bundles_commits_and_reads(
    map_client: AsyncKrtourMapClient,
) -> None:
    bundles = await cultural_festivals_to_bundles(
        [_FEST],  # type: ignore[list-item]
        fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
    )
    result = await map_client.load_feature_bundles(bundles)
    assert result.bundles_total == 1
    assert result.features_inserted == 1
    assert result.source_records_inserted == 1
    assert result.source_links_inserted == 1

    fid = bundles[0].feature.feature_id
    # 별도 세션 조회 → client가 commit했음을 확인.
    row = await map_client.get_feature(fid)
    assert row is not None
    assert row["name"] == bundles[0].feature.name
    assert row["coord_5179_srid"] == 5179  # ADR-012 generated column

    feats = await map_client.features_in_bounds(
        min_lon=126.0, min_lat=37.0, max_lon=127.5, max_lat=38.0, kinds=["event"]
    )
    assert any(f["feature_id"] == fid for f in feats)


async def test_sync_dedup_candidates_persists(
    map_client: AsyncKrtourMapClient, migrated_engine: AsyncEngine
) -> None:
    await _seed_temples(migrated_engine, "cli-knps-1", "cli-krh-1")

    sync = await map_client.sync_dedup_candidates(
        [_stub("cli-knps-1")], [_stub("cli-krh-1")]
    )
    assert len(sync.candidates) == 1
    assert sync.candidates[0].decision == "auto_merge"  # 완전 동일 → auto_merge
    assert sync.queue.inserted == 1
    assert sync.queue.updated == 0

    reviews = await map_client.pending_dedup_reviews()
    assert len(reviews) == 1
    assert reviews[0]["feature_id_a"] == "cli-knps-1"
    assert reviews[0]["feature_id_b"] == "cli-krh-1"
    assert reviews[0]["total_score"] >= 85.0
    assert reviews[0]["decision_reason"] == "auto_merge"


async def test_sync_dedup_excludes_auto_merge_when_disabled(
    map_client: AsyncKrtourMapClient, migrated_engine: AsyncEngine
) -> None:
    await _seed_temples(migrated_engine, "cli-a", "cli-b")

    # 완전 동일 쌍은 auto_merge — include_auto_merge=False면 후보 0 → DB 미적재.
    sync = await map_client.sync_dedup_candidates(
        [_stub("cli-a")], [_stub("cli-b")], include_auto_merge=False
    )
    assert sync.candidates == []
    assert sync.queue.inserted == 0
    assert await map_client.pending_dedup_reviews() == []


async def test_feature_update_request_client_lifecycle(
    map_client: AsyncKrtourMapClient,
) -> None:
    preview = await map_client.enqueue_feature_update_request(
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-mois-api"],
        dry_run=True,
    )
    assert isinstance(preview, FeatureUpdateRequestPreview)
    assert preview.matched_scope == {"feature_count": 0, "sigungu_codes": []}

    request = await map_client.enqueue_feature_update_request(
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-mois-api"],
        dataset_keys=["mois_license_features_bulk"],
        update_policy={"mode": "refresh_existing"},
        priority=70,
        operator="integration-test",
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.state == "queued"
    assert request.job_id is not None

    loaded = await map_client.get_update_request(request.request_id)
    assert loaded is not None
    assert loaded.request_id == request.request_id
    assert loaded.providers == ("python-mois-api",)

    page1 = await map_client.list_update_requests(limit=1)
    assert page1.items == (loaded,)
    assert page1.next_cursor is None

    cancelled = await map_client.cancel_update_request(
        request.request_id, error_message="client test cancel"
    )
    assert cancelled is not None
    assert cancelled.state == "cancelled"
    assert cancelled.error_message == "client test cancel"

    cancelled_page = await map_client.list_update_requests(
        state="cancelled", limit=10
    )
    assert tuple(item.request_id for item in cancelled_page.items) == (
        request.request_id,
    )

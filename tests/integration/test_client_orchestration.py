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
from krtour.map.providers.airkorea import (
    air_quality_stations_to_bundles,
    air_quality_to_weather_values,
)
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_TEMPLE_CAT = "01070100"

_TRUNCATE_SQL = (
    "TRUNCATE feature.features, feature.feature_weather_values, "
    "provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue, "
    "ops.enrichment_review_queue, "
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
    assert request.status == "queued"
    assert request.job_id is not None

    loaded = await map_client.get_update_request(request.request_id)
    assert loaded is not None
    assert loaded.request_id == request.request_id
    assert loaded.providers == ("python-mois-api",)

    peeked = await map_client.peek_next_update_request()
    assert peeked is not None
    assert peeked.request_id == request.request_id
    assert peeked.status == "queued"

    peeked_batch = await map_client.peek_update_requests(limit=5)
    assert [item.request_id for item in peeked_batch] == [request.request_id]
    assert peeked_batch[0].status == "queued"

    page1 = await map_client.list_update_requests(limit=1)
    assert page1.items == (loaded,)
    assert page1.next_cursor is None

    to_fail = await map_client.enqueue_feature_update_request(
        scope={"type": "feature_ids", "feature_ids": []},
        providers=["python-mois-api"],
        priority=80,
    )
    assert isinstance(to_fail, FeatureUpdateRequest)
    failed = await map_client.fail_update_request(
        to_fail.request_id,
        dagster_run_id="dagster-run-client-test",
        error_message="client test failure",
    )
    assert failed is not None
    assert failed.status == "failed"
    assert failed.dagster_run_id == "dagster-run-client-test"
    assert failed.error_message == "client test failure"

    cancelled = await map_client.cancel_update_request(
        request.request_id, error_message="client test cancel"
    )
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.error_message == "client test cancel"

    cancelled_page = await map_client.list_update_requests(
        status="cancelled", limit=10
    )
    assert tuple(item.request_id for item in cancelled_page.items) == (
        request.request_id,
    )


# -- T-RV-52c: festival enrichment review --------------------------------------


@dataclass(frozen=True)
class _VkItem:
    """``VisitKoreaFestivalItem`` Protocol 만족 (enrichment 입력)."""

    content_id: str
    title: str | None
    overview: str | None = None
    first_image: str | None = None
    first_image2: str | None = None
    addr1: str | None = "서울특별시 영등포구"
    area_code: str | None = "1"
    sigungu_code: str | None = "19"
    event_start_date: str | None = "20260405"
    event_end_date: str | None = "20260412"
    tel: str | None = None
    homepage: str | None = None
    modified_time: str | None = "20260301120000"


async def _seed_primary_festival(map_client: AsyncKrtourMapClient) -> None:
    """datagokr 1차 축제(event) feature를 commit 적재 (matcher 후보 대상)."""
    bundles = await cultural_festivals_to_bundles(
        [_FEST], fetched_at=datetime(2026, 3, 1, 9, 0, tzinfo=_KST)
    )
    await map_client.load_feature_bundles(bundles)


async def test_refresh_festival_enrichment_reviews_classifies(
    map_client: AsyncKrtourMapClient,
) -> None:
    await _seed_primary_festival(map_client)
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=_KST)

    # 부분 일치 → review-band, 완전 일치 → auto. 밴드를 넓혀 분류를 강제.
    items = [
        _VkItem(content_id="vk-review", title="서울 봄꽃"),
        _VkItem(content_id="vk-auto", title="서울 봄꽃 축제"),
    ]
    result = await map_client.refresh_festival_enrichment_reviews(
        items, fetched_at=fetched, accept_threshold=0.99, review_floor=0.5
    )
    assert result.auto.source_links_inserted == 1
    assert result.review_queue.inserted == 1

    pending = await map_client.list_pending_enrichment_reviews()
    assert len(pending) == 1
    assert pending[0]["source_name"] == "서울 봄꽃"
    review_id = pending[0]["review_id"]

    decision = await map_client.resolve_enrichment_review(
        review_id, "accepted", reviewed_by="tester"
    )
    assert decision.changed is True
    assert decision.applied is True

    # accept 후 더 이상 pending 없음.
    assert await map_client.list_pending_enrichment_reviews() == []


async def test_resolve_enrichment_review_reject_keeps_no_link(
    map_client: AsyncKrtourMapClient, migrated_engine: AsyncEngine
) -> None:
    await _seed_primary_festival(map_client)
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=_KST)
    await map_client.refresh_festival_enrichment_reviews(
        [_VkItem(content_id="vk-review", title="서울 봄꽃")],
        fetched_at=fetched,
        accept_threshold=0.99,
        review_floor=0.5,
    )
    pending = await map_client.list_pending_enrichment_reviews()
    review_id = pending[0]["review_id"]

    decision = await map_client.resolve_enrichment_review(review_id, "rejected")
    assert decision.changed is True
    assert decision.applied is False

    # reject는 enrichment link을 만들지 않는다.
    async with AsyncSession(migrated_engine) as session:
        enrichment_links = (
            await session.execute(
                text(
                    "SELECT count(*) FROM provider_sync.source_links "
                    "WHERE source_role = 'enrichment'"
                )
            )
        ).scalar_one()
    assert enrichment_links == 0


# -- T-RV-55d: air quality (station weather feature + weather values) ----------


@dataclass(frozen=True)
class _AirStation:
    """``AirQualityStationItem`` Protocol 만족."""

    station_name: str
    addr: str | None
    lat: float | None
    lon: float | None


@dataclass(frozen=True)
class _AirMeasurement:
    """``AirQualityMeasurementItem`` Protocol 만족."""

    station_name: str
    data_time: datetime
    sido_name: str | None = "서울"
    khai_value: int | None = None
    khai_grade: int | None = None
    pm10_value: float | None = None
    pm10_grade: int | None = None
    pm25_value: float | None = None
    pm25_grade: int | None = None
    o3_value: float | None = None
    o3_grade: int | None = None
    no2_value: float | None = None
    no2_grade: int | None = None
    so2_value: float | None = None
    so2_grade: int | None = None
    co_value: float | None = None
    co_grade: int | None = None


async def test_load_air_quality_commits_station_and_values(
    map_client: AsyncKrtourMapClient, migrated_engine: AsyncEngine
) -> None:
    fetched = datetime(2026, 6, 8, 9, 0, tzinfo=_KST)
    station = _AirStation(
        station_name="중구", addr="서울 중구", lat=37.5640, lon=126.9750
    )
    bundles = await air_quality_stations_to_bundles([station], fetched_at=fetched)
    station_feature_ids = {
        b.source_record.source_entity_id: b.feature.feature_id for b in bundles
    }
    measurement = _AirMeasurement(
        station_name="중구",
        data_time=datetime(2026, 6, 8, 8, 0, tzinfo=_KST),
        pm10_value=45.0,
        pm10_grade=2,
        pm25_value=18.0,
        pm25_grade=1,
    )
    values = air_quality_to_weather_values(
        [measurement], station_feature_ids=station_feature_ids
    )

    result = await map_client.load_air_quality(bundles, values)
    assert result.stations.features_inserted == 1
    assert result.weather_values == 2  # PM10 + PM2_5

    # 측정소는 weather feature로, 측정값은 feature_weather_values로 commit됐는지.
    async with AsyncSession(migrated_engine) as session:
        kind = (
            await session.execute(
                text(
                    "SELECT kind FROM feature.features WHERE feature_id = :f"
                ),
                {"f": bundles[0].feature.feature_id},
            )
        ).scalar_one()
        assert kind == "weather"
        value_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM feature.feature_weather_values "
                    "WHERE feature_id = :f"
                ),
                {"f": bundles[0].feature.feature_id},
            )
        ).scalar_one()
        assert value_count == 2

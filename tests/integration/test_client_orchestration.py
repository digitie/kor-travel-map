"""``test_client_orchestration`` — ``AsyncKorTravelMapClient`` 적재/dedup (#122).

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

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import SourceRecord
from kortravelmap.dto.coordinate import Coordinate
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    FeatureUpdateRequestPreview,
)
from kortravelmap.infra.jobs_repo import ImportJobDatasetTarget
from kortravelmap.infra.models import FeatureRow
from kortravelmap.providers.airkorea import (
    air_quality_stations_to_bundles,
    air_quality_to_weather_values,
)
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles
from tests.integration._db_cleanup import truncate_committed_test_rows
from tests.integration._feature_ids import feature_uuid

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_TEMPLE_CAT = "01070100"

_TRUNCATE_SQL = (
    # ``source_entities``를 빼면 record만 지워지고 entity가 링크 없이 남아
    # 정합성 검사 F1(orphan source_entity)이 **다른 테스트에서** 켜진다.
    # T-VN-33이 head를 끼우면서 record CASCADE가 더 이상 entity를 지우지 않는다.
    "TRUNCATE feature.features, feature.feature_weather_values, "
    "provider_sync.source_entities, provider_sync.source_entity_heads, "
    "provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue, "
    "ops.enrichment_review_queue, "
    "ops.feature_update_requests, ops.import_jobs RESTART IDENTITY CASCADE"
)


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 (좌표 있는 케이스).

    provider 실모델 ``PublicCulturalFestival`` 필드명 (ADR-044 재정렬, #374).
    """

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


_FEST = _Festival(
    fstvl_nm="서울 봄꽃 축제",
    opar="여의도공원",
    fstvl_start_date=date(2026, 4, 5),
    fstvl_end_date=date(2026, 4, 12),
    fstvl_co="봄꽃 축제 상세.",
    mnnst_nm="영등포구청",
    phone_number="02-2670-3114",
    rdnmadr="서울특별시 영등포구 여의공원로 120",
    lnmadr="서울특별시 영등포구 여의도동 8",
    latitude=37.5263,
    longitude=126.9239,
    reference_date=date(2026, 3, 1),
    instt_nm="서울특별시 영등포구",
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
    )


def _stub(feature_id: str, name: str = "불국사") -> _Stub:
    return _Stub(
        feature_id=feature_id,
        name=name,
        coord=Coordinate(lon=Decimal("129.3320"), lat=Decimal("35.7900")),
        category=_TEMPLE_CAT,
    )


async def _canonical_uuid_for_alias(
    engine: AsyncEngine, legacy_feature_id: str
) -> str | None:
    """provider 적재 경로가 legacy ``f_*``에 발급한 정본 키(uuid text). 없으면 ``None``.

    T-VN-39 재키(alembic 309) 뒤 ``feature.features.feature_id``는 서버가 발급한
    UUIDv7이고, provider 변환기가 유도한 ``bundle.feature.feature_id``는 정본 키가
    **아니라** ``feature_aliases``에 등록된 주소다(ADR-098 결정 6). 이 client가
    commit한 Feature를 다시 조회하려면 그 주소를 여기서 한 번 정본 키로 바꾼다.

    ``None``은 "그 주소가 등록되지 않았다" — 즉 적재가 commit되지 않았다는 뜻이고,
    rollback을 증명하는 쪽에서 그대로 쓴다.
    """
    async with AsyncSession(engine) as session:
        bound = (
            await session.execute(
                text(
                    "SELECT CAST(a.feature_id AS text) "
                    "FROM feature.feature_aliases AS a "
                    "WHERE a.alias = :alias AND a.alias_kind = 'legacy_feature_id'"
                ),
                {"alias": legacy_feature_id},
            )
        ).scalar_one_or_none()
    return None if bound is None else str(bound)


#: dedup 큐가 저장하는 쌍은 ``ck_dedup_pair_order``가 ``a < b``를 요구하고
#: ``_canonical_pair``가 그 순서로 정규화한다. 아래 테스트는 **어느 쪽이 a인지**를
#: 단언하므로 유도 uuid(라벨 사전순과 무관)를 쓸 수 없다 — 순서를 눈으로 확인할 수
#: 있는 리터럴을 든다(선례: ``test_cli_dedup_merge._F_LOSER``/``_F_MASTER``).
_F_DEDUP_KNPS = "00000000-0000-7000-8000-000000110001"
_F_DEDUP_KRH = "00000000-0000-7000-8000-000000110002"


@pytest.fixture
async def map_client(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncKorTravelMapClient]:
    """client + teardown TRUNCATE (client는 commit하므로 명시 격리)."""
    client = AsyncKorTravelMapClient(migrated_engine)
    try:
        yield client
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await truncate_committed_test_rows(session, _TRUNCATE_SQL)


async def _seed_temples(engine: AsyncEngine, *feature_ids: str) -> None:
    """temple feature를 committed로 적재 (dedup FK 대상)."""
    async with AsyncSession(engine) as session, session.begin():
        for fid in feature_ids:
            session.add(_temple(fid))


async def _free_memberships(
    engine: AsyncEngine, count: int
) -> list[ImportJobDatasetTarget]:
    """활성 request가 점유하지 않은 canonical triple을 catalog에서 고른다.

    T-VN-33 이후 feature update request는 ``providers``/``dataset_keys`` 배열이
    아니라 **정확한** ``provider_dataset_id + sync_scope + operation_key``
    membership을 받는다(ADR-088). 0089가 catalog를 seed하므로 실제 행을 읽어
    쓰고, 같은 triple을 두 활성 request가 점유하면 membership mutex에 걸리므로
    서로 다른 triple을 고른다.
    """

    async with AsyncSession(engine) as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT scope.provider_dataset_id, scope.sync_scope,
                           scope.operation_key
                    FROM provider_sync.provider_dataset_operation_scopes AS scope
                    JOIN provider_sync.provider_datasets AS dataset
                      ON dataset.provider_dataset_id = scope.provider_dataset_id
                    JOIN provider_sync.provider_dataset_operations AS operation
                      ON operation.provider_dataset_id = scope.provider_dataset_id
                     AND operation.operation_key = scope.operation_key
                    WHERE dataset.is_active AND operation.is_enabled
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ops.feature_update_request_datasets AS member
                          JOIN ops.feature_update_requests AS request
                            ON request.request_id = member.request_id
                          JOIN ops.import_jobs AS job ON job.job_id = request.job_id
                          WHERE member.provider_dataset_id = scope.provider_dataset_id
                            AND member.sync_scope = scope.sync_scope
                            AND member.operation_key = scope.operation_key
                            AND job.status IN ('queued', 'running')
                      )
                    ORDER BY scope.provider_dataset_id, scope.sync_scope,
                             scope.operation_key
                    LIMIT :count
                    """
                ),
                {"count": count},
            )
        ).all()
    assert len(rows) == count
    return [
        ImportJobDatasetTarget(
            provider_dataset_id=int(row.provider_dataset_id),
            sync_scope=str(row.sync_scope),
            operation_key=str(row.operation_key),
        )
        for row in rows
    ]


async def test_load_feature_bundles_commits_and_reads(
    map_client: AsyncKorTravelMapClient, migrated_engine: AsyncEngine
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

    # 조회 키는 적재가 발급한 정본 키다 — DTO의 ``f_*``는 그 주소일 뿐이다.
    fid = await _canonical_uuid_for_alias(
        migrated_engine, bundles[0].feature.feature_id
    )
    assert fid is not None
    # 별도 세션 조회 → client가 commit했음을 확인.
    row = await map_client.get_feature(fid)
    assert row is not None
    assert row["name"] == bundles[0].feature.name
    assert row["coord_5179_srid"] == 5179  # ADR-012 generated column

    feats = await map_client.features_in_bounds(
        min_lon=126.0, min_lat=37.0, max_lon=127.5, max_lat=38.0, kinds=["event"]
    )
    # uuid 컬럼을 읽으면 driver가 ``uuid.UUID``를 준다 — 비교 전에 text로 낮춘다.
    assert any(str(f["feature_id"]) == fid for f in feats)


async def test_load_feature_bundle_batches_rolls_back_prior_batches(
    map_client: AsyncKorTravelMapClient, migrated_engine: AsyncEngine
) -> None:
    bundles = await cultural_festivals_to_bundles(
        [_FEST],  # type: ignore[list-item]
        fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
    )

    async def _failing_batches() -> AsyncIterator[list[object]]:
        yield list(bundles)
        raise RuntimeError("second batch conversion failed")

    with pytest.raises(RuntimeError, match="second batch"):
        await map_client.load_feature_bundle_batches(  # type: ignore[arg-type]
            _failing_batches()
        )

    # 첫 batch가 rollback됐다는 증거를 "그 Feature가 없다"로 잡는다. 재키 뒤 정본
    # 키는 적재가 발급하므로 미리 알 수 없고, legacy 주소가 등록부에 없다는 것이
    # 곧 그 Feature가 commit되지 않았다는 뜻이다 — 생성 procedure가 core 행과
    # alias를 같은 transaction에서 남기기 때문이다.
    assert (
        await _canonical_uuid_for_alias(
            migrated_engine, bundles[0].feature.feature_id
        )
        is None
    )


async def test_sync_dedup_candidates_persists(
    map_client: AsyncKorTravelMapClient, migrated_engine: AsyncEngine
) -> None:
    await _seed_temples(migrated_engine, _F_DEDUP_KNPS, _F_DEDUP_KRH)

    sync = await map_client.sync_dedup_candidates(
        [_stub(_F_DEDUP_KNPS)], [_stub(_F_DEDUP_KRH)]
    )
    assert len(sync.candidates) == 1
    assert sync.candidates[0].decision == "auto_merge"  # 완전 동일 → auto_merge
    assert sync.queue.inserted == 1
    assert sync.queue.updated == 0

    reviews = await map_client.pending_dedup_reviews()
    assert len(reviews) == 1
    # 큐 컬럼은 uuid지만 이 표면은 dict를 그대로 돌려주고 상위가 JSON으로
    # 직렬화한다. 그래서 SQL이 경계에서 text로 편다 — 여기서 `str(...)`로 표기를
    # 맞추면 그 계약이 깨져도 초록이 된다(적대 리뷰가 짝인 전화번호 테스트에서
    # 집은 부류다). 표기를 맞추지 말고 **표기를 잰다.**
    assert isinstance(reviews[0]["feature_id_a"], str)
    assert isinstance(reviews[0]["feature_id_b"], str)
    assert reviews[0]["feature_id_a"] == _F_DEDUP_KNPS
    assert reviews[0]["feature_id_b"] == _F_DEDUP_KRH
    assert reviews[0]["total_score"] >= 85.0
    assert reviews[0]["decision_reason"] == "auto_merge"


async def test_sync_dedup_excludes_auto_merge_when_disabled(
    map_client: AsyncKorTravelMapClient, migrated_engine: AsyncEngine
) -> None:
    # 이 쌍은 큐에 들어가지 않으므로 저장 순서가 의미를 갖지 않는다 — 라벨에서
    # 결정적으로 유도한 정본 uuid를 그대로 쓴다(``feature.features`` 직접 INSERT).
    cli_a = feature_uuid("cli-a")
    cli_b = feature_uuid("cli-b")
    await _seed_temples(migrated_engine, cli_a, cli_b)

    # 완전 동일 쌍은 auto_merge — include_auto_merge=False면 후보 0 → DB 미적재.
    sync = await map_client.sync_dedup_candidates(
        [_stub(cli_a)], [_stub(cli_b)], include_auto_merge=False
    )
    assert sync.candidates == []
    assert sync.queue.inserted == 0
    assert await map_client.pending_dedup_reviews() == []


async def test_feature_update_request_client_lifecycle(
    map_client: AsyncKorTravelMapClient,
    migrated_engine: AsyncEngine,
) -> None:
    first, second, third = await _free_memberships(migrated_engine, 3)

    preview = await map_client.preview_feature_update_request(
        scope={"type": "feature_ids", "feature_ids": []},
        dataset_memberships=[first],
    )
    assert isinstance(preview, FeatureUpdateRequestPreview)
    assert preview.matched_scope["feature_count"] == 0
    assert preview.matched_scope["sigungu_codes"] == []
    # matched_scope는 이제 해석된 canonical membership도 함께 싣는다.
    assert [
        member["provider_dataset_id"]
        for member in preview.matched_scope["dataset_memberships"]
    ] == [first.provider_dataset_id]
    assert [m.provider_dataset_id for m in preview.dataset_memberships] == [
        first.provider_dataset_id
    ]

    request = await map_client.enqueue_feature_update_request(
        scope={"type": "feature_ids", "feature_ids": []},
        dataset_memberships=[first],
        update_policy={"mode": "refresh_existing"},
        priority=70,
        operator="integration-test",
    )
    assert isinstance(request, FeatureUpdateRequest)
    assert request.status == "queued"
    assert request.job_id is not None
    assert request.generation == 1

    loaded = await map_client.get_update_request(request.request_id)
    assert loaded is not None
    assert loaded.request_id == request.request_id
    # providers/dataset_keys 배열 사본은 T-VN-33에서 사라졌다 — 정본은 membership,
    # provider/dataset_key는 catalog projection일 뿐이다.
    assert [
        (m.provider_dataset_id, m.sync_scope, m.operation_key)
        for m in loaded.dataset_memberships
    ] == [(first.provider_dataset_id, first.sync_scope, first.operation_key)]
    assert loaded.dataset_memberships[0].provider
    assert loaded.dataset_memberships[0].dataset_key

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

    pre_start_failure = await map_client.enqueue_feature_update_request(
        scope={"type": "feature_ids", "feature_ids": []},
        dataset_memberships=[second],
        priority=75,
    )
    assert isinstance(pre_start_failure, FeatureUpdateRequest)
    retried = await map_client.fail_update_request(
        pre_start_failure.request_id,
        owner_dagster_run_id="dagster-run-before-start",
        expected_request_generation=pre_start_failure.generation,
        error_message="resource initialization failed",
    )
    assert retried is not None
    assert retried.status == "queued"
    assert retried.dagster_run_id is None
    assert retried.generation == pre_start_failure.generation + 1

    to_fail = await map_client.enqueue_feature_update_request(
        scope={"type": "feature_ids", "feature_ids": []},
        dataset_memberships=[third],
        priority=80,
    )
    assert isinstance(to_fail, FeatureUpdateRequest)
    with pytest.raises(ValueError, match="trimmed non-empty"):
        await map_client.mark_update_request_started(
            to_fail.request_id,
            dagster_run_id=None,  # type: ignore[arg-type]
            expected_generation=to_fail.generation,
        )
    still_queued = await map_client.get_update_request(to_fail.request_id)
    assert still_queued == to_fail

    started_to_fail = await map_client.mark_update_request_started(
        to_fail.request_id,
        dagster_run_id="dagster-run-client-test",
        expected_generation=to_fail.generation,
    )
    assert started_to_fail is not None
    wrong_owner = await map_client.mark_update_request_started(
        to_fail.request_id,
        dagster_run_id="dagster-run-other",
        expected_generation=started_to_fail.generation,
    )
    assert wrong_owner is None
    failed = await map_client.fail_update_request(
        to_fail.request_id,
        owner_dagster_run_id="dagster-run-client-test",
        expected_request_generation=started_to_fail.generation,
        error_message="client test failure",
    )
    assert failed is not None
    assert failed.status == "failed"
    assert failed.dagster_run_id == "dagster-run-client-test"
    assert failed.error_message == "client test failure"

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
    map_x: float | None = 126.9245
    map_y: float | None = 37.526
    event_start_date: str | None = "20260405"
    event_end_date: str | None = "20260412"
    tel: str | None = None
    homepage: str | None = None
    modified_time: str | None = "20260301120000"


async def _seed_primary_festival(map_client: AsyncKorTravelMapClient) -> None:
    """datagokr 1차 축제(event) feature를 commit 적재 (matcher 후보 대상)."""
    bundles = await cultural_festivals_to_bundles(
        [_FEST], fetched_at=datetime(2026, 3, 1, 9, 0, tzinfo=_KST)
    )
    await map_client.load_feature_bundles(bundles)


async def test_refresh_festival_enrichment_reviews_classifies(
    map_client: AsyncKorTravelMapClient,
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
    map_client: AsyncKorTravelMapClient, migrated_engine: AsyncEngine
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
    map_client: AsyncKorTravelMapClient, migrated_engine: AsyncEngine
) -> None:
    fetched = datetime(2026, 6, 8, 9, 0, tzinfo=_KST)
    station = _AirStation(station_name="중구", addr="서울 중구", lat=37.5640, lon=126.9750)
    bundles = await air_quality_stations_to_bundles([station], fetched_at=fetched)
    # ``load_air_quality``는 측정소 bundle과 측정값을 **한 transaction**에 넣는다.
    # 그래서 호출자가 값에 붙일 수 있는 측정소 식별자는 적재 전에 손에 있는 것,
    # 즉 provider 변환기가 유도한 legacy ``f_*``뿐이다 — dagster asset
    # (``run_feature_weather_airkorea_air_quality``)도 정확히 이 매핑을 만든다.
    # 이 호출 shape을 유지하는 것이 이 테스트가 지키는 계약이다.
    station_feature_ids = {b.source_record.source_entity_id: b.feature.feature_id for b in bundles}
    measurement = _AirMeasurement(
        station_name="중구",
        data_time=datetime(2026, 6, 8, 8, 0, tzinfo=_KST),
        pm10_value=45.0,
        pm10_grade=2,
        pm25_value=18.0,
        pm25_grade=1,
    )
    values = air_quality_to_weather_values([measurement], station_feature_ids=station_feature_ids)
    raw_data = {
        "records": [
            {"station_name": measurement.station_name, "data_time": measurement.data_time}
        ]
    }
    payload_hash = make_payload_hash(raw_data)
    source_record = SourceRecord(
        provider="python-airkorea-api",
        dataset_key="airkorea_air_quality",
        source_entity_type="weather_response",
        source_entity_id="test-run:20260608T090000+0900",
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched,
        source_record_key=make_source_record_key(
            provider="python-airkorea-api",
            dataset_key="airkorea_air_quality",
            source_entity_type="weather_response",
            source_entity_id="test-run:20260608T090000+0900",
            raw_payload_hash=payload_hash,
        ),
    )
    async with AsyncSession(migrated_engine) as session:
        provider_dataset_id = await session.scalar(
            text(
                """
                SELECT provider_dataset_id
                FROM provider_sync.provider_datasets
                WHERE provider = 'python-airkorea-api'
                  AND dataset_key = 'airkorea_air_quality'
                """
            )
        )
    assert provider_dataset_id is not None

    result = await map_client.load_air_quality(
        bundles,
        values,
        provider_dataset_id=int(provider_dataset_id),
        source_record=source_record,
    )
    assert result.stations.features_inserted == 1
    assert result.weather_values == 2  # PM10 + PM2_5

    # 측정소는 weather feature로, 측정값은 feature_weather_values로 commit됐는지.
    # 두 표의 ``feature_id``는 재키 뒤 uuid다 — 조회 키는 적재가 발급한 정본 키이고,
    # 맨몸 바인드를 두면 PostgreSQL이 그 자리를 text로 유도하므로 명시 캐스트로
    # uuid에 고정한다(재키 후 이 저장소의 관행).
    station_uuid = await _canonical_uuid_for_alias(
        migrated_engine, bundles[0].feature.feature_id
    )
    assert station_uuid is not None
    async with AsyncSession(migrated_engine) as session:
        kind = (
            await session.execute(
                text(
                    "SELECT kind FROM feature.features "
                    "WHERE feature_id = CAST(:f AS uuid)"
                ),
                {"f": station_uuid},
            )
        ).scalar_one()
        assert kind == "weather"
        value_count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM feature.feature_weather_values "
                    "WHERE feature_id = CAST(:f AS uuid)"
                ),
                {"f": station_uuid},
            )
        ).scalar_one()
        assert value_count == 2

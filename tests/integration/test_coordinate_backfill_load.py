"""같은 원본의 기존 행 보정 — 좌표 결측 backfill·concierge 해수욕장 재투영(#1459 §4·§6).

원본(payload)이 같으면 ``became_current``가 거짓이라 적재가 Feature 본문을 다시 쓰지 않는다. 그래서
정지오코딩 fallback 이전에 좌표 없이 적재된 주차장·국가유산 행, 그리고 근거 없는 해수욕장
제안으로 적재된 concierge 행은 원천이 바뀌기 전까지 고쳐지지 않았다. 이 파일은 재적재 한 번이 그것을
고치고, 두 번째 재적재는 아무것도 바꾸지 않는다는 것을 실제 PostGIS에서 본다.

(종전 대표 행은 표준데이터 축제였다 — 2026-11-10 축제 원천이 TourAPI로 바뀌며 그 dataset은
퇴역했고, TourAPI 축제는 원천 좌표를 늘 준다. 같은 backfill scope의 주차장으로 옮겼다.)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from kortravelmap.dto import Address, Coordinate
from kortravelmap.infra import feature_identity, feature_repo
from kortravelmap.providers.kor_travel_concierge import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
    KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK,
    kor_travel_concierge_items_to_bundles,
)
from kortravelmap.providers.standard_data import parking_lots_to_bundles

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto import FeatureBundle

pytestmark = pytest.mark.integration

_FETCHED = datetime(2026, 11, 9, tzinfo=UTC)
_POINT = Coordinate(lon=Decimal("128.7170"), lat=Decimal("37.6770"))


async def _geocode(_address: Address) -> Coordinate | None:
    return _POINT


async def _reverse(_coord: Coordinate) -> Address | None:
    return Address(
        legal="강원특별자치도 평창군 대관령면 횡계리",
        bjd_code="5176025021",
        sigungu_code="51760",
        sido_code="51",
        sido_name="강원특별자치도",
        sigungu_name="평창군",
    )


@dataclass(frozen=True)
class _ParkingLot:
    """``PublicParkingLotItem`` Protocol 만족(provider ``PublicParkingLot`` 필드 이름)."""

    prkplce_no: str | None
    prkplce_nm: str | None
    prkplce_se: str | None = "공영"
    rdnmadr: str | None = None
    lnmadr: str | None = None
    prkcmprt: int | None = 30
    parkingchrge_info: str | None = "무료"
    latitude: float | None = None
    longitude: float | None = None
    phone_number: str | None = None
    instt_code: str | None = None
    raw: Any = None


def _parking_lot() -> _ParkingLot:
    return _ParkingLot(
        prkplce_no="BACKFILL-PARKING-1459",
        prkplce_nm="백필 횡계 공영주차장 1459",
        rdnmadr="강원특별자치도 평창군 대관령면 대관령로 135-9",
        lnmadr="강원특별자치도 평창군 대관령면 횡계리 661",
    )


async def _stored(session: AsyncSession, bundle: FeatureBundle) -> dict[str, Any]:
    identity = await feature_identity.resolve_feature_identity(session, bundle.feature.feature_id)
    assert identity is not None
    row = (
        await session.execute(
            text(
                "SELECT x_extension.ST_X(coord) AS lon, x_extension.ST_Y(coord) AS lat,"
                " sigungu_code, category, row_revision"
                " FROM feature.features WHERE feature_id = CAST(:id AS uuid)"
            ),
            {"id": identity.feature_id},
        )
    ).mappings().one()
    return dict(row)


async def test_same_payload_reload_backfills_a_geocoded_coordinate_once(
    migrated_session: AsyncSession,
) -> None:
    [unplaced] = await parking_lots_to_bundles([_parking_lot()], fetched_at=_FETCHED)
    assert unplaced.feature.coord is None
    first = await feature_repo.load_bundles(migrated_session, [unplaced])
    assert first.features_inserted == 1
    before = await _stored(migrated_session, unplaced)
    assert before["lon"] is None

    [placed] = await parking_lots_to_bundles(
        [_parking_lot()],
        fetched_at=_FETCHED,
        reverse_geocoder=_reverse,
        address_geocoder=_geocode,
    )
    # 원본은 그대로다 — 같은 source record(payload hash)다.
    assert placed.source_record.raw_payload_hash == unplaced.source_record.raw_payload_hash
    second = await feature_repo.load_bundles(migrated_session, [placed])
    assert second.features_updated == 1
    after = await _stored(migrated_session, placed)
    assert (after["lon"], after["lat"]) == pytest.approx((128.7170, 37.6770))
    assert after["sigungu_code"] == "51760"

    third = await feature_repo.load_bundles(migrated_session, [placed])
    assert third.features_updated == 0
    assert (await _stored(migrated_session, placed))["row_revision"] == after["row_revision"]


def _concierge_item(name: str, category: str) -> dict[str, Any]:
    return {
        "export_id": "ytpc_914590",
        "candidate_id": 914590,
        "operation": "upsert",
        "schema_version": 1,
        "place": {
            "name": name,
            "description": None,
            "gemini_enriched_description": None,
            "category_label": "관광 > 자연명소 > 해수욕장",
            "category_code_suggestion": category,
            "longitude": 127.1260,
            "latitude": 36.4640,
            "address": {
                "official_address": "충청남도 공주시 금성동 53-51",
                "road_address": None,
                "legal_dong_code": None,
                "sido_code": None,
                "sigungu_code": None,
            },
        },
        "youtube": {
            "video_id": "video-1459",
            "video_url": "https://www.youtube.com/watch?v=video-1459",
            "video_title": "공주 여행",
            "source_type": "keyword",
            "source_value": "공주 여행",
            "source_title": "공주 여행",
            "source_search_query": "공주 여행",
            "corrected_search_query": "공주 여행",
            "channel_id": "channel-1459",
            "channel_title": "여행 채널",
            "channel_summary": None,
            "playlist_id": None,
            "playlist_title": None,
            "video_summary": None,
        },
        "evidence": {
            "timestamp_start": "00:01:00",
            "timestamp_end": "00:02:00",
            "transcript_excerpt": "공산성에 왔습니다.",
            "gemini_url_evidence": None,
            "confidence_score": 0.9,
            "providers": {"kakao": {}},
        },
        "source_record": {
            "provider": KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
            "source_entity_type": "extracted_place_candidate",
            "source_entity_id": "914590",
        },
        "updated_at": "2026-11-08T00:00:00Z",
    }


async def test_same_payload_reload_reprojects_an_unsupported_beach_category(
    migrated_session: AsyncSession,
) -> None:
    item = _concierge_item("공산성", "01050100")
    [bundle] = await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED)
    # 종전 변환(제안을 그대로 받던 때)의 결과를 같은 원본으로 심는다.
    legacy = bundle.model_copy(
        update={"feature": bundle.feature.model_copy(update={"category": "01050100"})}
    )
    await feature_repo.load_bundles(migrated_session, [legacy])
    assert (await _stored(migrated_session, legacy))["category"] == "01050100"

    reload = await feature_repo.load_bundles(migrated_session, [bundle])
    assert reload.features_updated == 1
    assert (
        await _stored(migrated_session, bundle)
    )["category"] == KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK

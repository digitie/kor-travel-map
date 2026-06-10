"""``test_providers_tripmate_agent`` — TripMate-agent YouTube 후보 provider 변환."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from krtour.map.dto import Address, Coordinate, FeatureKind, SourceRole
from krtour.map.providers.tripmate_agent import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    TRIPMATE_AGENT_MARKER_COLOR,
    TRIPMATE_AGENT_PROVIDER_NAME,
    TRIPMATE_AGENT_YOUTUBE_CATEGORY_FALLBACK,
    tripmate_agent_inactive_entity_ids,
    tripmate_agent_items_to_bundles,
)

_KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 6, 10, 12, 0, tzinfo=_KST)


def _item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "export_id": "ytpc_123",
        "candidate_id": 123,
        "operation": "upsert",
        "place": {
            "name": "월정리 해변",
            "description": "제주 동쪽 해변",
            "gemini_enriched_description": "에메랄드빛 바다와 카페가 가까운 해변",
            "category_label": "해변",
            "category_code_suggestion": "01020300",
            "longitude": 126.7958,
            "latitude": 33.5563,
            "address": {
                "official_address": "제주특별자치도 제주시 구좌읍 월정리",
                "road_address": "제주특별자치도 제주시 구좌읍 해맞이해안로",
                "legal_dong_code": "5011025624",
                "sido_code": "50",
                "sigungu_code": "50110",
            },
        },
        "youtube": {
            "video_id": "video-1",
            "video_url": "https://www.youtube.com/watch?v=video-1",
            "video_title": "제주 동쪽 여행",
            "channel_id": "channel-1",
            "channel_title": "여행 채널",
            "playlist_id": "playlist-1",
            "playlist_title": "제주 플레이리스트",
        },
        "evidence": {
            "timestamp_start": "00:03:12",
            "timestamp_end": "00:04:10",
            "transcript_excerpt": "월정리 해변에 도착했습니다.",
            "gemini_url_evidence": "video-url",
            "confidence_score": 0.86,
            "providers": {"vworld": {}, "kakao": {}, "naver": {}, "google": {}},
        },
        "source_record": {
            "provider": TRIPMATE_AGENT_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
            "source_entity_type": "extracted_place_candidate",
            "source_entity_id": "123",
            "raw_payload_hash": "sha256:tripmate-hash",
        },
        "updated_at": "2026-06-10T00:00:00Z",
    }
    item.update(overrides)
    return item


async def test_tripmate_agent_youtube_item_to_feature_bundle() -> None:
    [bundle] = await tripmate_agent_items_to_bundles([_item()], fetched_at=_FETCHED)

    feature = bundle.feature
    assert feature.kind is FeatureKind.PLACE
    assert feature.name == "월정리 해변"
    assert feature.category == "01020300"
    assert feature.marker_color == TRIPMATE_AGENT_MARKER_COLOR
    assert feature.feature_id.startswith("f_5011025624_p_")
    assert feature.address.road == "제주특별자치도 제주시 구좌읍 해맞이해안로"
    assert feature.coord == Coordinate(lon="126.7958", lat="33.5563")
    assert feature.detail is not None
    assert feature.detail.place_kind == "youtube_place_candidate"  # type: ignore[union-attr]
    assert feature.detail.facility_info["youtube_video_id"] == "video-1"  # type: ignore[union-attr]
    assert feature.detail.facility_info["timestamp_start"] == "00:03:12"  # type: ignore[union-attr]
    # T-217f — TripMate 출처 배지 UX가 detail.facility_info만으로 confidence를 얻는다.
    assert feature.detail.facility_info["confidence_score"] == 86  # type: ignore[union-attr]

    source_record = bundle.source_record
    assert source_record.provider == TRIPMATE_AGENT_PROVIDER_NAME
    assert source_record.dataset_key == DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    assert source_record.source_entity_type == "extracted_place_candidate"
    assert source_record.source_entity_id == "123"
    assert source_record.raw_payload_hash == "sha256:tripmate-hash"
    assert source_record.raw_data["youtube"]["video_title"] == "제주 동쪽 여행"

    assert bundle.source_link.source_role is SourceRole.PRIMARY
    assert bundle.source_link.match_method == "tripmate_agent_export"
    assert bundle.source_link.confidence == 86
    assert feature.raw_refs[0].source_entity_id == "123"


async def test_tripmate_agent_skips_reject_and_tombstone() -> None:
    bundles = await tripmate_agent_items_to_bundles(
        [_item(operation="reject"), _item(operation="tombstone")],
        fetched_at=_FETCHED,
    )

    assert bundles == []


def test_tripmate_agent_inactive_entity_ids_collects_reject_and_tombstone() -> None:
    """T-217b — reject/tombstone item만 entity id로 수집한다(ADR-050 #4)."""
    items = [
        _item(operation="upsert"),
        _item(
            operation="reject",
            source_record={**_item()["source_record"], "source_entity_id": "201"},
        ),
        _item(
            operation="tombstone",
            source_record={**_item()["source_record"], "source_entity_id": "202"},
        ),
        # source_record가 비면 candidate_id → export_id 순 fallback.
        _item(operation="tombstone", source_record={}, candidate_id=303),
    ]

    assert tripmate_agent_inactive_entity_ids(items) == {"201", "202", "303"}


def test_tripmate_agent_inactive_entity_ids_ignores_unidentifiable() -> None:
    items = [
        _item(
            operation="reject",
            source_record={},
            candidate_id=None,
            export_id=None,
        ),
    ]

    assert tripmate_agent_inactive_entity_ids(items) == set()


async def test_tripmate_agent_defaults_source_and_category() -> None:
    item = _item(source_record={}, place={**_item()["place"], "category_code_suggestion": None})

    [bundle] = await tripmate_agent_items_to_bundles([item], fetched_at=_FETCHED)

    assert bundle.source_record.provider == TRIPMATE_AGENT_PROVIDER_NAME
    assert bundle.source_record.dataset_key == DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    assert bundle.source_record.source_entity_id == "123"
    assert bundle.feature.category == TRIPMATE_AGENT_YOUTUBE_CATEGORY_FALLBACK


async def test_tripmate_agent_reverse_geocoder_fills_missing_bjd() -> None:
    item = _item(
        place={
            **_item()["place"],
            "address": {
                "official_address": "제주특별자치도 제주시 구좌읍 월정리",
                "road_address": "제주특별자치도 제주시 구좌읍 해맞이해안로",
            },
        }
    )

    async def _reverse(_coord: Coordinate) -> Address:
        return Address(bjd_code="5011025624", sigungu_code="50110", sido_code="50")

    [bundle] = await tripmate_agent_items_to_bundles(
        [item],
        fetched_at=_FETCHED,
        reverse_geocoder=_reverse,
    )

    assert bundle.feature.address.bjd_code == "5011025624"
    assert bundle.feature.feature_id.startswith("f_5011025624_p_")


async def test_tripmate_agent_missing_name_is_skipped() -> None:
    item = _item(place={**_item()["place"], "name": ""})

    assert await tripmate_agent_items_to_bundles([item], fetched_at=_FETCHED) == []


async def test_tripmate_agent_sparse_payload_uses_export_id_and_json_fallbacks() -> None:
    item = _item(
        candidate_id=" ",
        source_record={},
        youtube=None,
        evidence={"confidence_score": "bad"},
        extra_decimal=Decimal("12.34"),
        extra_date=date(2026, 6, 10),
        extra_list=[Decimal("1.5"), object()],
        place={
            **_item()["place"],
            "longitude": "",
            "latitude": "not-a-coordinate",
            "category_code_suggestion": "bad",
            "address": {
                "official_address": "  제주특별자치도 제주시 구좌읍 월정리  ",
                "road_address": "",
                "legal_dong_code": "bad",
                "sido_code": "bad",
                "sigungu_code": "bad",
            },
        },
    )

    [bundle] = await tripmate_agent_items_to_bundles([item], fetched_at=_FETCHED)

    assert bundle.feature.coord is None
    assert bundle.feature.category == TRIPMATE_AGENT_YOUTUBE_CATEGORY_FALLBACK
    assert bundle.feature.address.legal == "제주특별자치도 제주시 구좌읍 월정리"
    assert bundle.feature.address.road is None
    assert bundle.source_record.source_entity_id == "ytpc_123"
    assert bundle.source_link.confidence == 80
    assert bundle.source_record.raw_data["extra_decimal"] == "12.34"
    assert bundle.source_record.raw_data["extra_date"] == "2026-06-10"
    assert bundle.source_record.raw_data["extra_list"][0] == "1.5"
    assert isinstance(bundle.source_record.raw_data["extra_list"][1], str)


async def test_tripmate_agent_skips_non_mapping_place_and_missing_source_id() -> None:
    no_place = _item(place=None)
    no_source_id = _item(candidate_id="", export_id="", source_record={})

    assert await tripmate_agent_items_to_bundles(
        [no_place, no_source_id], fetched_at=_FETCHED
    ) == []

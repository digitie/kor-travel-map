"""``test_providers_kor_travel_concierge`` — kor-travel-concierge YouTube 후보 provider 변환."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.dto import Address, Coordinate, FeatureKind, SourceRole
from kortravelmap.providers.kor_travel_concierge import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    KOR_TRAVEL_CONCIERGE_MARKER_COLOR,
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
    KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK,
    kor_travel_concierge_inactive_entity_ids,
    kor_travel_concierge_items_to_bundles,
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
            # ADR-057/C-03 — producer(feature_export_service)는 admin 코드를 항상 None으로
            # 보낸다(feature_id/bjd는 소비자 책임). 픽스처도 동일하게 맞춘다.
            "address": {
                "official_address": "제주특별자치도 제주시 구좌읍 월정리",
                "road_address": "제주특별자치도 제주시 구좌읍 해맞이해안로",
                "legal_dong_code": None,
                "sido_code": None,
                "sigungu_code": None,
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
            "provider": KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
            "dataset_key": DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
            "source_entity_type": "extracted_place_candidate",
            "source_entity_id": "123",
            "raw_payload_hash": "sha256:krtour-ai-hash",
        },
        "updated_at": "2026-06-10T00:00:00Z",
    }
    item.update(overrides)
    return item


async def test_kor_travel_concierge_youtube_item_to_feature_bundle() -> None:
    [bundle] = await kor_travel_concierge_items_to_bundles([_item()], fetched_at=_FETCHED)

    feature = bundle.feature
    assert feature.kind is FeatureKind.PLACE
    assert feature.name == "월정리 해변"
    assert feature.category == "01020300"
    assert feature.marker_color == KOR_TRAVEL_CONCIERGE_MARKER_COLOR
    # ADR-057 — feature_id는 안정 candidate.id에만 고정(bjd/category 미포함) → f_global_.
    assert feature.feature_id.startswith("f_global_p_")
    assert feature.address.road == "제주특별자치도 제주시 구좌읍 해맞이해안로"
    assert feature.coord == Coordinate(lon="126.7958", lat="33.5563")
    assert feature.detail is not None
    assert feature.detail.place_kind == "youtube_place_candidate"  # type: ignore[union-attr]
    assert feature.detail.facility_info["youtube_video_id"] == "video-1"  # type: ignore[union-attr]
    assert feature.detail.facility_info["timestamp_start"] == "00:03:12"  # type: ignore[union-attr]
    # T-217f/ADR-053 — 출처 배지 UX가 detail.facility_info만으로 confidence를 얻는다.
    assert feature.detail.facility_info["confidence_score"] == 86  # type: ignore[union-attr]
    assert feature.detail.payload["kor_travel_concierge"]["youtube"]["video_id"] == "video-1"  # type: ignore[union-attr]

    source_record = bundle.source_record
    assert source_record.provider == KOR_TRAVEL_CONCIERGE_PROVIDER_NAME
    assert source_record.dataset_key == DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    assert source_record.source_entity_type == "extracted_place_candidate"
    assert source_record.source_entity_id == "123"
    assert source_record.raw_payload_hash == "sha256:krtour-ai-hash"
    assert source_record.raw_data["youtube"]["video_title"] == "제주 동쪽 여행"

    assert bundle.source_link.source_role is SourceRole.PRIMARY
    assert bundle.source_link.match_method == "kor_travel_concierge_export"
    assert bundle.source_link.confidence == 86
    assert feature.raw_refs[0].source_entity_id == "123"


async def test_kor_travel_concierge_skips_reject_and_tombstone() -> None:
    bundles = await kor_travel_concierge_items_to_bundles(
        [_item(operation="reject"), _item(operation="tombstone")],
        fetched_at=_FETCHED,
    )

    assert bundles == []


def test_kor_travel_concierge_inactive_entity_ids_collects_reject_and_tombstone() -> None:
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

    assert kor_travel_concierge_inactive_entity_ids(items) == {"201", "202", "303"}


def test_kor_travel_concierge_inactive_entity_ids_ignores_unidentifiable() -> None:
    items = [
        _item(
            operation="reject",
            source_record={},
            candidate_id=None,
            export_id=None,
        ),
    ]

    assert kor_travel_concierge_inactive_entity_ids(items) == set()


async def test_kor_travel_concierge_source_entity_id_immutable_across_operations() -> None:
    """#452/#443 — 같은 candidate는 upsert/reject/tombstone에서 동일 source_entity_id를
    내야 inactivate 조인(upsert 저장 키 == inactivate 매칭 키)이 성립한다(ADR-050 #4).

    concierge #85가 upsert<->reject만 회귀로 고정했고 tombstone 경로는 코드 추론
    (공유 ``_source_entity_id`` helper)에만 의존했다 — 본 테스트가 tombstone까지 명시
    고정한다."""
    [bundle] = await kor_travel_concierge_items_to_bundles(
        [_item(operation="upsert")], fetched_at=_FETCHED
    )
    upsert_id = bundle.source_record.source_entity_id

    assert kor_travel_concierge_inactive_entity_ids([_item(operation="tombstone")]) == {
        upsert_id
    }
    assert kor_travel_concierge_inactive_entity_ids([_item(operation="reject")]) == {
        upsert_id
    }


async def test_kor_travel_concierge_defaults_source_and_category() -> None:
    item = _item(source_record={}, place={**_item()["place"], "category_code_suggestion": None})

    [bundle] = await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED)

    assert bundle.source_record.provider == KOR_TRAVEL_CONCIERGE_PROVIDER_NAME
    assert bundle.source_record.dataset_key == DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    assert bundle.source_record.source_entity_id == "123"
    assert bundle.feature.category == KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK


async def test_kor_travel_concierge_reverse_geocoder_fills_address_not_feature_id() -> None:
    """reverse geocoder는 Address.bjd_code(표시·공간 쿼리용)만 채우고 feature_id는
    바꾸지 않는다 — ADR-057(식별자는 안정 candidate.id에 고정, C-01 회귀 방지)."""
    item = _item()

    async def _reverse(_coord: Coordinate) -> Address:
        return Address(bjd_code="5011025624", sigungu_code="50110", sido_code="50")

    [no_geo] = await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED)
    [with_geo] = await kor_travel_concierge_items_to_bundles(
        [item], fetched_at=_FETCHED, reverse_geocoder=_reverse
    )

    # geocoder가 Address.bjd_code를 채운다 (표시·공간 쿼리용).
    assert with_geo.feature.address.bjd_code == "5011025624"
    assert no_geo.feature.address.bjd_code is None
    # 그러나 feature_id는 geocoder 유무와 무관하게 동일하다 (ADR-057, C-01 회귀 방지).
    assert with_geo.feature.feature_id == no_geo.feature.feature_id
    assert with_geo.feature.feature_id.startswith("f_global_p_")


async def test_kor_travel_concierge_feature_id_stable_when_category_fills_in() -> None:
    """같은 후보(candidate.id)의 category_code_suggestion이 enrich 전 None →
    후 8자리로 바뀌어도 feature_id는 동일하다 — ADR-057(C-02 회귀 방지)."""
    before = _item(place={**_item()["place"], "category_code_suggestion": None})
    after = _item(place={**_item()["place"], "category_code_suggestion": "01020300"})

    [b_before] = await kor_travel_concierge_items_to_bundles([before], fetched_at=_FETCHED)
    [b_after] = await kor_travel_concierge_items_to_bundles([after], fetched_at=_FETCHED)

    # 표시 category는 바뀌지만 feature_id(identity)는 불변.
    assert b_before.feature.category == KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK
    assert b_after.feature.category == "01020300"
    assert b_before.feature.feature_id == b_after.feature.feature_id


async def test_kor_travel_concierge_missing_name_is_skipped() -> None:
    item = _item(place={**_item()["place"], "name": ""})

    assert await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED) == []


async def test_kor_travel_concierge_sparse_payload_uses_export_id_and_json_fallbacks() -> None:
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

    [bundle] = await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED)

    assert bundle.feature.coord is None
    assert bundle.feature.category == KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK
    assert bundle.feature.address.legal == "제주특별자치도 제주시 구좌읍 월정리"
    assert bundle.feature.address.road is None
    assert bundle.source_record.source_entity_id == "ytpc_123"
    assert bundle.source_link.confidence == 80
    assert bundle.source_record.raw_data["extra_decimal"] == "12.34"
    assert bundle.source_record.raw_data["extra_date"] == "2026-06-10"
    assert bundle.source_record.raw_data["extra_list"][0] == "1.5"
    assert isinstance(bundle.source_record.raw_data["extra_list"][1], str)


async def test_kor_travel_concierge_skips_non_mapping_place_and_missing_source_id() -> None:
    no_place = _item(place=None)
    no_source_id = _item(candidate_id="", export_id="", source_record={})

    assert await kor_travel_concierge_items_to_bundles(
        [no_place, no_source_id], fetched_at=_FETCHED
    ) == []


async def test_kor_travel_concierge_unknown_operation_is_not_loaded_or_inactivated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C-05 — 알 수 없는 operation은 적재(upsert)도 비활성화(reject/tombstone)도 안 된다.
    제외 시 WARNING 1건을 남기는 관측 계약도 고정한다(#452/#441)."""
    item = _item(
        operation="noop",
        source_record={**_item()["source_record"], "source_entity_id": "999"},
    )

    assert await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED) == []
    with caplog.at_level(
        logging.WARNING, logger="kortravelmap.providers.kor_travel_concierge"
    ):
        assert kor_travel_concierge_inactive_entity_ids([item]) == set()
    assert any(
        "unknown operation" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    )


async def test_kor_travel_concierge_identity_triple_is_forced_to_constants(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """C-04 — payload가 다른 provider/dataset/entity_type을 보내도 고정 상수로 강제해
    upsert 저장 키 == inactivate 매칭 키를 보장한다(raw 값은 raw_data에 보존). 강제 시
    identity drift WARNING을 남기는 관측 계약도 고정한다(#452/#441)."""
    item = _item(
        source_record={
            "provider": "some-alias",
            "dataset_key": "other_dataset",
            "source_entity_type": "other_type",
            "source_entity_id": "123",
            "raw_payload_hash": "sha256:x",
        }
    )

    with caplog.at_level(
        logging.WARNING, logger="kortravelmap.providers.kor_travel_concierge"
    ):
        [bundle] = await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED)

    assert any(
        "identity drift" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    )

    sr = bundle.source_record
    assert sr.provider == KOR_TRAVEL_CONCIERGE_PROVIDER_NAME
    assert sr.dataset_key == DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    assert sr.source_entity_type == "extracted_place_candidate"
    # raw payload(concierge가 실제 보낸 값)는 그대로 보존된다.
    assert sr.raw_data["source_record"]["provider"] == "some-alias"


async def test_kor_travel_concierge_preserves_producer_only_extras() -> None:
    """C-08 — producer가 보내는 loader 미사용 필드(video_summary/rejection_reason 등)는
    drop되지 않고 raw_data에 보존된다."""
    item = _item(
        rejection_reason="검수 제외",
        youtube={**_item()["youtube"], "video_summary": "요약", "channel_summary": "채널 요약"},
        evidence={**_item()["evidence"], "providers": {"vworld": {}}},
    )

    [bundle] = await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED)

    assert bundle.feature.name == "월정리 해변"
    raw = bundle.source_record.raw_data
    assert raw["rejection_reason"] == "검수 제외"
    assert raw["youtube"]["video_summary"] == "요약"
    assert raw["evidence"]["providers"]["vworld"] == {}

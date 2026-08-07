"""``test_providers_kor_travel_concierge`` — kor-travel-concierge YouTube 후보 provider 변환."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from kortravelmap.core.exceptions import ValidationError as DomainValidationError
from kortravelmap.dto import Address, Coordinate, FeatureKind, SourceRole
from kortravelmap.geocoding import ReverseGeocodeObservation
from kortravelmap.providers.kor_travel_concierge import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    KOR_TRAVEL_CONCIERGE_MARKER_COLOR,
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
    KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK,
    kor_travel_concierge_inactive_entity_ids,
    kor_travel_concierge_items_to_bundles,
    kor_travel_concierge_latest_items,
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
            # producer T-189(2026-07-14)부터 장소 매칭 시 실 행정코드를 보낸다. 미매칭·
            # 미보강 후보는 여전히 None — 본 픽스처는 None 케이스를 유지하고 실코드
            # 케이스는 test_..._producer_admin_codes_flow_to_address가 고정한다.
            # feature_id는 어느 쪽이든 candidate.id에만 고정된다(ADR-057).
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
            # producer 8720dda(2026-06-25) — 수집 대상 provenance. keyword 수집이면
            # source_search_query/corrected_search_query가 채워지고, source_title은
            # 접두사 없는 검색어 원문이다(producer _source_title).
            "source_type": "keyword",
            "source_value": "제주 동쪽 여행",
            "source_title": "제주 동쪽 여행 브이로그",
            "source_search_query": "제주 동쪽 여행 브이로그",
            "corrected_search_query": "제주 동쪽 여행 브이로그",
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
    # producer provenance(8720dda) — 출처 UX가 읽는 평면 미러(§4).
    assert feature.detail.facility_info["youtube_source_type"] == "keyword"  # type: ignore[union-attr]
    assert feature.detail.facility_info["youtube_source_title"] == "제주 동쪽 여행 브이로그"  # type: ignore[union-attr]
    assert feature.detail.facility_info["youtube_source_search_query"] == "제주 동쪽 여행 브이로그"  # type: ignore[union-attr]
    assert feature.detail.payload["kor_travel_concierge"]["youtube"]["video_id"] == "video-1"  # type: ignore[union-attr]
    # nested pass-through — curated source rule이 읽는 경로
    # (detail #>> '{payload,kor_travel_concierge,youtube,source_title}').
    nested_youtube = feature.detail.payload["kor_travel_concierge"]["youtube"]  # type: ignore[union-attr]
    assert nested_youtube["source_title"] == "제주 동쪽 여행 브이로그"

    source_record = bundle.source_record
    assert source_record.provider == KOR_TRAVEL_CONCIERGE_PROVIDER_NAME
    assert source_record.dataset_key == DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    assert source_record.source_entity_type == "extracted_place_candidate"
    assert source_record.source_entity_id == "123"
    # concierge는 ``sha256:<hex>``로 보내지만 저장 정본은 접두 없는 lowercase
    # hex다 (T-VN-33 ``ck_source_records_payload_hash_canonical``). 안 벗기면
    # 제약 validate가 막히므로 **받는 자리에서** 정규화한다.
    assert source_record.raw_payload_hash == "krtour-ai-hash"
    assert source_record.raw_data["youtube"]["video_title"] == "제주 동쪽 여행"

    assert bundle.source_link.source_role is SourceRole.PRIMARY
    assert bundle.source_link.match_method == "kor_travel_concierge_export"
    assert bundle.source_link.confidence == 86
    assert feature.raw_refs[0].source_entity_id == "123"


async def test_kor_travel_concierge_latest_items_keeps_last_observation_per_candidate() -> None:
    """mid-run 검수 전이 수렴 — 같은 후보가 한 스트림에 두 번 관측되면 마지막이 이긴다.

    changes 페이지네이션 도중 producer가 ledger 행을 새 sequence로 전진시키면(되돌리기
    등) 같은 후보가 구/신 operation으로 두 번 관측될 수 있다. 압축 없이 '적재 후
    일괄 inactivate' 순서로 처리하면 구 reject가 신 upsert를 덮는다.
    """
    revert_flow = [
        _item(operation="reject"),  # 구 sequence 관측
        _item(operation="upsert"),  # 신 sequence 관측(되돌리기 재확정)
    ]
    latest = kor_travel_concierge_latest_items(revert_flow)
    assert [item["operation"] for item in latest] == ["upsert"]
    assert len(await kor_travel_concierge_items_to_bundles(latest, fetched_at=_FETCHED)) == 1
    assert kor_travel_concierge_inactive_entity_ids(latest) == set()

    removal_flow = [
        _item(operation="upsert"),
        _item(operation="tombstone"),  # 제거 목록 이동이 나중 관측
    ]
    latest = kor_travel_concierge_latest_items(removal_flow)
    assert [item["operation"] for item in latest] == ["tombstone"]
    assert await kor_travel_concierge_items_to_bundles(latest, fetched_at=_FETCHED) == []
    assert kor_travel_concierge_inactive_entity_ids(latest) == {"123"}


def test_kor_travel_concierge_latest_items_passes_through_unidentifiable() -> None:
    """entity id가 없는 item은 압축 대상이 아니라 그대로 통과한다(후속 단계가 skip)."""
    unidentifiable = _item(candidate_id=None, export_id=None, source_record={})
    other = _item(
        source_record={**_item()["source_record"], "source_entity_id": "777"},
    )

    latest = kor_travel_concierge_latest_items([unidentifiable, other, other])

    assert latest == [unidentifiable, other]


async def test_kor_travel_concierge_producer_admin_codes_flow_to_address() -> None:
    """producer T-189 — 실 행정코드가 오면 Address로 싣되 feature_id는 불변(ADR-057)."""
    coded = _item(
        place={
            **_item()["place"],
            "address": {
                **_item()["place"]["address"],
                "legal_dong_code": "5011025624",
                "sido_code": "50",
                "sigungu_code": "50110",
            },
        },
        schema_version=1,
    )

    [with_codes] = await kor_travel_concierge_items_to_bundles([coded], fetched_at=_FETCHED)
    [without_codes] = await kor_travel_concierge_items_to_bundles(
        [_item()], fetched_at=_FETCHED
    )

    assert with_codes.feature.address.bjd_code == "5011025624"
    assert with_codes.feature.address.sido_code == "50"
    assert with_codes.feature.address.sigungu_code == "50110"
    # 상위 additive 필드(schema_version)는 raw_data에 보존된다.
    assert with_codes.source_record.raw_data["schema_version"] == 1
    # 행정코드 유무와 무관하게 feature_id는 candidate.id에만 고정(ADR-057).
    assert with_codes.feature.feature_id == without_codes.feature.feature_id


async def test_kor_travel_concierge_provenance_absent_keys_are_omitted() -> None:
    """provenance 미포함(구 payload 또는 channel/playlist 수집) item은 facility_info에
    해당 평면 key를 만들지 않는다 — None 필터 계약(§4)."""
    youtube = {
        key: value
        for key, value in _item()["youtube"].items()
        if not key.startswith("source_") and key != "corrected_search_query"
    }

    [bundle] = await kor_travel_concierge_items_to_bundles(
        [_item(youtube=youtube)], fetched_at=_FETCHED
    )

    facility_info = bundle.feature.detail.facility_info  # type: ignore[union-attr]
    assert "youtube_source_type" not in facility_info
    assert "youtube_source_search_query" not in facility_info
    assert "youtube_corrected_search_query" not in facility_info
    assert facility_info["youtube_video_id"] == "video-1"


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


async def test_kor_travel_concierge_missing_name_is_quarantined() -> None:
    item = _item(place={**_item()["place"], "name": ""})
    quarantined = []

    assert await kor_travel_concierge_items_to_bundles(
        [item],
        fetched_at=_FETCHED,
        quarantine=quarantined,
    ) == []
    assert [(entry.item_key, entry.reason_code) for entry in quarantined] == [
        ("ytpc_123", "missing_place_name")
    ]


async def test_kor_travel_concierge_invalid_upsert_raises_without_quarantine() -> None:
    item = _item(place={**_item()["place"], "name": ""})

    with pytest.raises(DomainValidationError, match="place.name"):
        await kor_travel_concierge_items_to_bundles([item], fetched_at=_FETCHED)


async def test_kor_travel_concierge_preserves_reverse_candidate_names() -> None:
    class _Observed:
        async def observe(self, coord: Coordinate) -> ReverseGeocodeObservation:
            assert coord == Coordinate(lon="126.7958", lat="33.5563")
            return ReverseGeocodeObservation(
                Address(
                    bjd_code="1111017700",
                    sigungu_code="11110",
                    sido_code="11",
                    sigungu_name="종로구",
                ),
                ("종로구", "서대문구"),
            )

        async def __call__(self, coord: Coordinate) -> Address | None:
            return (await self.observe(coord)).address

    [bundle] = await kor_travel_concierge_items_to_bundles(
        [_item()],
        fetched_at=_FETCHED,
        reverse_geocoder=_Observed(),
    )

    assert bundle.admin_evidence is not None
    assert bundle.admin_evidence.obs_sigungu_names == ("종로구", "서대문구")


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


async def test_kor_travel_concierge_nonfinite_confidence_preserves_batch() -> None:
    valid = _item()
    nonfinite = _item(
        candidate_id="candidate-nan",
        export_id="export-nan",
        evidence={"confidence_score": "NaN"},
        source_record={
            **_item()["source_record"],
            "source_entity_id": "source-nan",
        },
    )
    quarantined = []

    bundles = await kor_travel_concierge_items_to_bundles(
        [valid, nonfinite],
        fetched_at=_FETCHED,
        quarantine=quarantined,
    )

    assert len(bundles) == 2
    assert quarantined == []
    assert bundles[1].source_link.confidence == 80


async def test_kor_travel_concierge_quarantines_missing_required_upsert_fields() -> None:
    no_place = _item(place=None)
    no_source_id = _item(candidate_id="", export_id="", source_record={})
    quarantined = []

    assert await kor_travel_concierge_items_to_bundles(
        [no_place, no_source_id],
        fetched_at=_FETCHED,
        quarantine=quarantined,
    ) == []
    assert [(entry.item_key, entry.reason_code) for entry in quarantined] == [
        ("ytpc_123", "missing_place_name"),
        (
            "payload:2fdb8d542cac7e8e",
            "missing_source_entity_id",
        ),
    ]


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

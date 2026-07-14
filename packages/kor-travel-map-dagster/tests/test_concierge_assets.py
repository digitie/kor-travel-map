"""``test_concierge_assets`` — concierge asset의 mid-run 검수 전이 압축 배선.

``run_feature_place_kor_travel_concierge_youtube``가 record 스트림을
``kor_travel_concierge_latest_items``로 **적재(upsert)·inactivate 양쪽 모두보다
앞에서** 압축하는 배선을 고정한다. 압축 함수 자체의 회귀는
``tests/unit/test_providers_kor_travel_concierge.py``가 담당하고, 여기서는 배선이
빠지거나 한쪽에만 적용되도록 리팩터될 때 빨간불이 되는 asset-level 테스트를 둔다.
"""

from __future__ import annotations

from typing import Any

from dagster import build_asset_context
from kortravelmap.infra.feature_repo import FeatureLoadResult

from kortravelmap.dagster.assets import run_feature_place_kor_travel_concierge_youtube


class _FakeConciergeClient:
    def __init__(self) -> None:
        self.loaded_bundles: list[Any] = []
        self.inactivate_calls: list[dict[str, Any]] = []

    async def load_feature_bundles(self, bundles: Any) -> FeatureLoadResult:
        materialized = list(bundles)
        self.loaded_bundles.extend(materialized)
        return FeatureLoadResult(
            bundles_total=len(materialized),
            features_inserted=len(materialized),
        )

    async def inactivate_features_by_source(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        source_entity_ids: set[str],
    ) -> int:
        self.inactivate_calls.append(
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
                "source_entity_ids": set(source_entity_ids),
            }
        )
        return len(source_entity_ids)


def _export_item(operation: str, *, candidate_id: int = 9201) -> dict[str, Any]:
    return {
        "export_id": f"ytpc_{candidate_id}",
        "candidate_id": candidate_id,
        "operation": operation,
        "schema_version": 1,
        "place": {
            "name": "협재 해수욕장",
            "description": "제주 서쪽 해변",
            "category_label": "해변",
            "category_code_suggestion": "01020300",
            "longitude": 126.2396,
            "latitude": 33.3941,
            "address": {
                "official_address": "제주특별자치도 제주시 한림읍 협재리",
                "road_address": None,
                "legal_dong_code": None,
                "sido_code": None,
                "sigungu_code": None,
            },
        },
        "youtube": {
            "video_id": "video-asset-1",
            "video_url": "https://www.youtube.com/watch?v=video-asset-1",
            "video_title": "제주 서쪽 여행",
            "source_type": "keyword",
            "source_value": "제주 서쪽 여행",
            "source_title": "제주 서쪽 여행",
            "source_search_query": "제주 서쪽 여행",
            "corrected_search_query": "제주 서쪽 여행",
            "channel_id": "channel-asset-1",
            "channel_title": "여행 채널",
            "playlist_id": None,
            "playlist_title": None,
        },
        "evidence": {
            "timestamp_start": "00:01:00",
            "timestamp_end": "00:02:00",
            "transcript_excerpt": "협재 해수욕장에 도착했습니다.",
            "gemini_url_evidence": None,
            "confidence_score": 0.9,
            "providers": {"kakao": {}},
        },
        "source_record": {
            "provider": "kor-travel-concierge-youtube",
            "dataset_key": "youtube_place_candidates",
            "source_entity_type": "extracted_place_candidate",
            "source_entity_id": str(candidate_id),
        },
        "updated_at": "2026-07-14T00:00:00Z",
    }


def _context(client: _FakeConciergeClient, records: list[dict[str, Any]]) -> Any:
    return build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": None,
            "fetched_at": None,
            "strict_address": True,
            "kor_travel_concierge_youtube_features": records,
        }
    )


async def test_concierge_asset_revert_mid_run_keeps_latest_upsert() -> None:
    """구 reject + 신 upsert 스트림 — 최신 upsert만 적재되고 inactivate는 없다.

    changes 페이지네이션 도중 producer가 후보를 re-sequence하면(재확정) 같은
    후보가 구 reject·신 upsert로 한 스트림에 공존한다. 압축 배선이 빠지면 구
    reject가 inactivate로 되살아나 신 상태를 덮는다(원 버그 재발).
    """
    client = _FakeConciergeClient()
    context = _context(
        client,
        [_export_item("reject"), _export_item("upsert")],
    )

    result = await run_feature_place_kor_travel_concierge_youtube(context)

    assert result.load.bundles_total == 1
    [bundle] = client.loaded_bundles
    assert bundle.source_record.source_entity_id == "9201"
    assert client.inactivate_calls == []


async def test_concierge_asset_removal_mid_run_inactivates_latest_tombstone() -> None:
    """구 upsert + 신 tombstone 스트림 — 적재 없이 inactivate만 수행한다."""
    client = _FakeConciergeClient()
    context = _context(
        client,
        [_export_item("upsert"), _export_item("tombstone")],
    )

    result = await run_feature_place_kor_travel_concierge_youtube(context)

    assert result.load.bundles_total == 0
    assert client.loaded_bundles == []
    [call] = client.inactivate_calls
    assert call["provider"] == "kor-travel-concierge-youtube"
    assert call["dataset_key"] == "youtube_place_candidates"
    assert call["source_entity_type"] == "extracted_place_candidate"
    assert call["source_entity_ids"] == {"9201"}

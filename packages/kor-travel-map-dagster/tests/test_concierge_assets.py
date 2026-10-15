"""``test_concierge_assets`` — concierge asset의 mid-run 검수 전이 압축 배선.

``run_feature_place_kor_travel_concierge_youtube``가 record 스트림을
``kor_travel_concierge_latest_items``로 **적재(upsert)·inactivate 양쪽 모두보다
앞에서** 압축하는 배선을 고정한다. 압축 함수 자체의 회귀는
``tests/unit/test_providers_kor_travel_concierge.py``가 담당하고, 여기서는 배선이
빠지거나 한쪽에만 적용되도록 리팩터될 때 빨간불이 되는 asset-level 테스트를 둔다.
"""

from __future__ import annotations

from typing import Any

import pytest
from dagster import Failure, build_asset_context
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.infra.feature_repo import FeatureLoadResult

from kortravelmap.dagster.assets import run_feature_place_kor_travel_concierge_youtube


class _FakeConciergeClient:
    def __init__(self) -> None:
        self.loaded_bundles: list[Any] = []
        self.retire_calls: list[dict[str, Any]] = []

    async def load_feature_bundles(self, bundles: Any, geo: Any = None) -> FeatureLoadResult:
        materialized = list(bundles)
        self.loaded_bundles.extend(materialized)
        return FeatureLoadResult(
            bundles_total=len(materialized),
            features_inserted=len(materialized),
        )

    async def load_authoritative_feature_snapshot(
        self,
        bundles: Any,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        retired_source_entity_ids: set[str] | None = None,
        retire_geometryless_areas: bool = False,
        geo: Any = None,
    ) -> tuple[FeatureLoadResult, int]:
        assert not retire_geometryless_areas
        result = await self.load_feature_bundles(bundles)
        retired = 0
        if retired_source_entity_ids:
            retired = await self.retire_features_by_source(
                provider=provider,
                dataset_key=dataset_key,
                source_entity_type=source_entity_type,
                source_entity_ids=retired_source_entity_ids,
            )
        return result, retired

    async def retire_features_by_source(
        self,
        *,
        provider: str,
        dataset_key: str,
        source_entity_type: str,
        source_entity_ids: set[str],
    ) -> int:
        self.retire_calls.append(
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_entity_type": source_entity_type,
                "source_entity_ids": set(source_entity_ids),
            }
        )
        return len(source_entity_ids)

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        count = len(self.recorded_findings)
        return IntegrityFindingSyncResult(count, count, count)


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
            # T-189 — 장소 매칭 후보는 실 행정코드가 실린다(strict 주소 검증 통과).
            "address": {
                "official_address": "제주특별자치도 제주시 한림읍 협재리",
                "road_address": None,
                "legal_dong_code": "5011031025",
                "sido_code": "50",
                "sigungu_code": "50110",
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
    assert client.retire_calls == []


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
    [call] = client.retire_calls
    assert call["provider"] == "kor-travel-concierge-youtube"
    assert call["dataset_key"] == "youtube_place_candidates"
    assert call["source_entity_type"] == "extracted_place_candidate"
    assert call["source_entity_ids"] == {"9201"}


async def test_concierge_asset_rejects_unaccounted_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _silently_drop(*args: Any, **kwargs: Any) -> list[Any]:
        return []

    monkeypatch.setattr(
        "kortravelmap.dagster.assets.kor_travel_concierge_items_to_bundles",
        _silently_drop,
    )
    client = _FakeConciergeClient()
    context = _context(client, [_export_item("upsert")])

    with pytest.raises(Failure, match="upsert 보존 불변식 위반"):
        await run_feature_place_kor_travel_concierge_youtube(context)

    assert client.loaded_bundles == []


# -- ADR-109 결정 6(a): resource 토큰이 변환기까지 간다(kwarg 전달 경로 결박, T-GR-03) ----------

_PAYLOAD_BJD = "5011025900"
_GEO_BJD = "5011025000"
_TOKEN_A = "dd1-" + "1" * 32
_TOKEN_B = "dd1-" + "2" * 32


class _Handle:
    def __init__(self, token: str) -> None:
        self.token = token

    async def current(self) -> Any:
        from kortravelmap.dto.geo_dataset import DatasetRef

        return DatasetRef(version_token="dv1-" + "a" * 32, data_token=self.token)


class _ObservedGeo:
    async def observe(self, coord: Any) -> Any:
        from kortravelmap.dto import Address
        from kortravelmap.geocoding import ReverseGeocodeObservation

        return ReverseGeocodeObservation(
            Address(bjd_code=_GEO_BJD, sigungu_code="50110", sido_code="50"), ()
        )

    async def __call__(self, coord: Any) -> Any:
        return (await self.observe(coord)).address


@pytest.mark.parametrize(
    ("resource_token", "expected_bjd"),
    [(_TOKEN_B, _GEO_BJD), (_TOKEN_A, _PAYLOAD_BJD)],
    ids=["payload-token-stale", "payload-token-current"],
)
async def test_concierge_asset_passes_the_run_token_to_the_converter(
    resource_token: str, expected_bjd: str
) -> None:
    item = _export_item("upsert")
    item["place"]["address"]["legal_dong_code"] = _PAYLOAD_BJD
    item["place"]["address"]["geo_data_token"] = _TOKEN_A
    client = _FakeConciergeClient()
    context = build_asset_context(
        resources={
            "kor_travel_map_client": client,
            "reverse_geocoder": _ObservedGeo(),
            "kor_travel_geo_dataset": _Handle(resource_token),
            "fetched_at": None,
            "strict_address": "off",
            "kor_travel_concierge_youtube_features": [item],
        }
    )

    await run_feature_place_kor_travel_concierge_youtube(context)

    [bundle] = client.loaded_bundles
    assert bundle.feature.address.bjd_code == expected_bjd

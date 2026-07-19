"""curated REST 라우터 app mount 단위 테스트."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.routers import curated
from kortravelmap.api.settings import ApiSettings
from kortravelmap.infra.curated_repo import CuratedFeature, CuratedFeaturePage
from pydantic import SecretStr

from kortravelmap.settings import KorTravelMapSettings

pytestmark = pytest.mark.unit


def _raw_curated_feature() -> CuratedFeature:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    return CuratedFeature(
        curated_feature_id="11111111-1111-4111-8111-111111111111",
        theme_id="22222222-2222-4222-8222-222222222222",
        theme_slug="public-raw-boundary",
        theme_name="공개 raw 경계",
        theme_group="test",
        feature_id="feature:public-curated",
        feature_name="공개 큐레이션 장소",
        feature_category="01070100",
        feature_kind="place",
        lon=126.978,
        lat=37.566,
        sido_code="11",
        sigungu_code="11110",
        legal_dong_code="1111010100",
        address={"road": "서울특별시 공개로 1"},
        detail={
            "feature_id": "feature:public-curated",
            "place_kind": "museum",
            "phones": ["02-0000-0000"],
            "facility_info": {"wheelchair": True},
            "payload": {
                "sentinel": "RAW_DETAIL_PAYLOAD",
                "source_record_key": "RAW_NESTED_SOURCE_RECORD_KEY",
                "raw_payload_hash": "RAW_NESTED_HASH",
            },
            "raw_data": {"sentinel": "RAW_DETAIL_ROOT"},
        },
        source_id="33333333-3333-4333-8333-333333333333",
        provider="raw-provider-internal",
        dataset_key="raw-dataset-internal",
        source_name="공개 출처명",
        source_url="https://example.test/source",
        source_record_key="RAW_TOP_LEVEL_SOURCE_RECORD_KEY",
        curation_status="curated",
        selection_origin="source_rule",
        selected_by="RAW_ADMIN_ACTOR",
        selected_at=now,
        rejected_by=None,
        rejected_at=None,
        rejection_reason=None,
        rank_score=99.0,
        display_title="공개 제목",
        display_summary="공개 요약",
        curation_relation="nearby_option",
        reuse_policy="allowed",
        content_version=3,
        metadata={"raw_external_id": "RAW_METADATA_ID"},
        created_at=now,
        updated_at=now,
        archived_at=None,
    )


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested_key
            for nested_value in value.values()
            for nested_key in _nested_keys(nested_value)
        }
    if isinstance(value, list):
        return {
            nested_key
            for nested_value in value
            for nested_key in _nested_keys(nested_value)
        }
    return set()


def test_curated_routes_are_in_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "/v1/curated-themes" in paths
    assert "/v1/curated-sources" in paths
    assert "/v1/curated-features" in paths
    assert "/v1/curated-features/{curated_feature_id}" in paths
    assert "/v1/curated-features/{curated_feature_id}/detail-snapshot" not in paths
    assert "/v1/admin/features/curated/{curated_feature_id}/detail-snapshot" in paths
    assert "/v1/admin/features/curated/{curated_feature_id}/select" in paths
    assert "/v1/admin/curated-features" not in paths
    assert "/v1/admin/curated-features/{curated_feature_id}/select" not in paths
    assert "/v1/admin/curated-source-rules/{rule_id}/apply" in paths


def test_curated_source_rule_view_accepts_detail_selector() -> None:
    from kortravelmap.infra.curated_repo import CuratedSourceRule

    now = datetime(2026, 7, 12, tzinfo=UTC)
    row = CuratedSourceRule(
        rule_id="11111111-1111-1111-1111-111111111111",
        theme_id="22222222-2222-2222-2222-222222222222",
        theme_slug="youtube-food",
        source_id="33333333-3333-3333-3333-333333333333",
        provider="kor-travel-concierge-youtube",
        dataset_key="youtube_place_candidates",
        place_kind="youtube_place_candidate",
        category=None,
        region_scope={},
        detail_selector={"path": ["payload", "channel_id"], "value": "channel-A"},
        default_action="curated",
        priority=10,
        enabled=True,
        metadata={},
        created_at=now,
        updated_at=now,
    )

    view = curated._rule_view(row)

    assert view.detail_selector == {
        "path": ["payload", "channel_id"],
        "value": "channel-A",
    }


def test_public_curated_list_and_detail_strip_raw_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#765: 공개 list/detail은 같은 fail-closed allowlist를 사용한다."""

    row = _raw_curated_feature()

    async def _list(_session: object, **kwargs: Any) -> CuratedFeaturePage:
        assert kwargs["public_only"] is True
        return CuratedFeaturePage(items=(row,), next_cursor=None)

    async def _get(_session: object, **kwargs: Any) -> CuratedFeature:
        assert kwargs["public_only"] is True
        return row

    monkeypatch.setattr(curated.curated_repo, "list_curated_features", _list)
    monkeypatch.setattr(curated.curated_repo, "get_curated_feature", _get)

    app = create_app(
        ApiSettings(public_api_key_required=False, vworld_api_key=None)
    )

    async def _session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)

    listed = client.get("/v1/curated-features")
    detailed = client.get(f"/v1/curated-features/{row.curated_feature_id}")

    assert listed.status_code == 200
    assert detailed.status_code == 200
    list_item = listed.json()["data"]["items"][0]
    detail_item = detailed.json()["data"]
    assert list_item == detail_item
    assert set(detail_item) == set(curated.PublicCuratedFeatureView.model_fields)
    assert detail_item["detail"] == {
        "feature_id": "feature:public-curated",
        "place_kind": "museum",
        "phones": ["02-0000-0000"],
        "facility_info": {"wheelchair": True},
    }
    assert {
        "payload",
        "raw_data",
        "raw_payload_hash",
        "source_record_key",
        "source_id",
        "metadata",
        "selected_by",
    }.isdisjoint(_nested_keys(detail_item))

    # 같은 repository row의 admin/operator projection은 감사 원문을 그대로 유지한다.
    admin_item = curated._feature_view(row).model_dump(mode="json")
    assert admin_item["source_record_key"] == "RAW_TOP_LEVEL_SOURCE_RECORD_KEY"
    assert admin_item["detail"]["payload"]["sentinel"] == "RAW_DETAIL_PAYLOAD"
    assert admin_item["metadata"]["raw_external_id"] == "RAW_METADATA_ID"


class _FakePlaceSearchClient:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakePlaceSearchClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(("GET", url, kwargs))
        request = httpx.Request("GET", url)
        if url == curated.KAKAO_LOCAL_KEYWORD_URL:
            return httpx.Response(
                200,
                json={
                    "documents": [
                        {
                            "place_name": "카카오 장소",
                            "address_name": "서울 종로구 세종로",
                            "road_address_name": "서울 종로구 사직로 161",
                            "x": "126.976896",
                            "y": "37.579553",
                            "category_name": "여행 > 관광명소",
                        }
                    ]
                },
                request=request,
            )
        if url == curated.NAVER_LOCAL_SEARCH_URL:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "title": "<b>네이버 장소</b>",
                            "address": "서울 종로구 세종로",
                            "roadAddress": "서울 종로구 사직로 161",
                            "mapx": "1269768960",
                            "mapy": "375795530",
                            "category": "여행>관광명소",
                        }
                    ]
                },
                request=request,
            )
        raise AssertionError(f"unexpected GET {url}")

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(("POST", url, kwargs))
        request = httpx.Request("POST", url)
        if url == curated.GOOGLE_PLACES_TEXT_SEARCH_URL:
            return httpx.Response(
                200,
                json={
                    "places": [
                        {
                            "displayName": {"text": "구글 장소"},
                            "formattedAddress": "서울 종로구 사직로 161",
                            "location": {
                                "latitude": 37.579553,
                                "longitude": 126.976896,
                            },
                            "primaryTypeDisplayName": {"text": "관광명소"},
                        }
                    ]
                },
                request=request,
            )
        raise AssertionError(f"unexpected POST {url}")


@pytest.mark.asyncio
async def test_curated_place_search_calls_external_providers_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakePlaceSearchClient.calls = []
    monkeypatch.setattr(curated.httpx, "AsyncClient", _FakePlaceSearchClient)
    monkeypatch.setattr(
        curated,
        "KorTravelMapSettings",
        lambda: KorTravelMapSettings(
            _env_file=None,
            kakao_local_rest_api_key=SecretStr("kakao-key"),
            naver_search_client_id=SecretStr("naver-id"),
            naver_search_client_secret=SecretStr("naver-secret"),
            google_places_api_key=SecretStr("google-key"),
        ),
    )

    data = await curated._direct_place_search("경복궁")

    assert data.errors == {}
    assert data.kakao[0].name == "카카오 장소"
    assert data.naver[0].name == "네이버 장소"
    assert data.naver[0].longitude == pytest.approx(126.976896)
    assert data.naver[0].latitude == pytest.approx(37.579553)
    assert data.google[0].name == "구글 장소"
    assert data.google[0].category == "관광명소"

    call_urls = {url for _, url, _ in _FakePlaceSearchClient.calls}
    assert call_urls == {
        curated.KAKAO_LOCAL_KEYWORD_URL,
        curated.NAVER_LOCAL_SEARCH_URL,
        curated.GOOGLE_PLACES_TEXT_SEARCH_URL,
    }
    assert any(
        call_kwargs.get("headers", {}).get("Authorization") == "KakaoAK kakao-key"
        for _, _, call_kwargs in _FakePlaceSearchClient.calls
    )
    assert any(
        call_kwargs.get("headers", {}).get("X-Goog-Api-Key") == "google-key"
        for _, _, call_kwargs in _FakePlaceSearchClient.calls
    )


@pytest.mark.asyncio
async def test_curated_place_search_reports_missing_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        curated,
        "KorTravelMapSettings",
        lambda: KorTravelMapSettings(_env_file=None),
    )

    data = await curated._direct_place_search("경복궁")

    assert data.google == []
    assert data.kakao == []
    assert data.naver == []
    assert set(data.errors) == {"google", "kakao", "naver"}

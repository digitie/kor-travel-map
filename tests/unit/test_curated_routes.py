"""curated REST 라우터 app mount 단위 테스트."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from kortravelmap.api.app import create_app
from kortravelmap.api.routers import curated
from pydantic import SecretStr

from kortravelmap.settings import KorTravelMapSettings

pytestmark = pytest.mark.unit


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

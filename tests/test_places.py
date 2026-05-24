from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from krtour_map.enums import FeatureKind, SourceRole
from krtour_map.models import Address, Coordinate, Feature, PlaceDetail
from krtour_map.places import (
    GOOGLE_PLACES_PROVIDER,
    KAKAO_LOCAL_PROVIDER,
    NAVER_SEARCH_PROVIDER,
    GooglePlacesTextSearcher,
    KakaoLocalPlaceSearcher,
    NaverLocalPlaceSearcher,
    PlaceHttpRequest,
    PlaceSearchCandidate,
    enrich_place_phone,
    place_phone_searchers_from_env,
    place_search_query,
)


class FakeTransport:
    def __init__(self, *payloads: Mapping[str, Any]) -> None:
        self.payloads = list(payloads)
        self.requests: list[PlaceHttpRequest] = []

    def __call__(self, request: PlaceHttpRequest) -> Mapping[str, Any]:
        self.requests.append(request)
        return self.payloads.pop(0)


def _place_feature() -> Feature:
    return Feature(
        feature_id="f_place_phone_1",
        kind=FeatureKind.PLACE,
        name="카카오프렌즈 코엑스점",
        coord=Coordinate(lat="37.51207412593136", lon="127.05902969025047"),
        address=Address(address="서울 강남구 영동대로 513"),
        category="tourist_attraction",
        marker_icon="marker",
        marker_color="P-01",
    )


def test_kakao_keyword_searcher_parses_phone_and_uses_rest_api_key_header() -> None:
    feature = _place_feature()
    transport = FakeTransport(
        {
            "documents": [
                {
                    "id": "26338954",
                    "place_name": "카카오프렌즈 코엑스점",
                    "phone": "02-6002-1880",
                    "address_name": "서울 강남구 삼성동 159",
                    "road_address_name": "서울 강남구 영동대로 513",
                    "x": "127.05902969025047",
                    "y": "37.51207412593136",
                    "place_url": "http://place.map.kakao.com/26338954",
                    "category_name": "가정,생활 > 디자인문구",
                }
            ]
        }
    )

    candidates = KakaoLocalPlaceSearcher("test-key", transport=transport)(feature)

    assert len(candidates) == 1
    assert candidates[0].provider == KAKAO_LOCAL_PROVIDER
    assert candidates[0].phone == "02-6002-1880"
    assert candidates[0].confidence >= 80
    request = transport.requests[0]
    assert request.headers["Authorization"] == "KakaoAK test-key"
    assert request.params is not None
    assert request.params["query"] == place_search_query(feature)
    assert request.params["x"] == feature.coord.longitude


def test_naver_local_searcher_requires_secret_and_treats_empty_telephone_as_missing() -> None:
    assert place_phone_searchers_from_env({"NAVER_CLIENT_ID": "client-id"}) == ()

    feature = _place_feature()
    transport = FakeTransport(
        {
            "items": [
                {
                    "title": "<b>카카오프렌즈 코엑스점</b>",
                    "link": "https://example.com/naver-place",
                    "category": "쇼핑",
                    "telephone": "",
                    "address": "서울특별시 강남구 삼성동 159",
                    "roadAddress": "서울특별시 강남구 영동대로 513",
                    "mapx": "1270590296",
                    "mapy": "375120741",
                }
            ]
        }
    )

    searcher = NaverLocalPlaceSearcher("client-id", "client-secret", transport=transport)
    candidates = searcher(feature)

    assert len(candidates) == 1
    assert candidates[0].provider == NAVER_SEARCH_PROVIDER
    assert candidates[0].name == "카카오프렌즈 코엑스점"
    assert candidates[0].phone is None
    request = transport.requests[0]
    assert request.headers["X-Naver-Client-Id"] == "client-id"
    assert request.headers["X-Naver-Client-Secret"] == "client-secret"


def test_google_places_text_searcher_requests_phone_fields() -> None:
    feature = _place_feature()
    transport = FakeTransport(
        {
            "places": [
                {
                    "id": "google-place-id",
                    "displayName": {"text": "카카오프렌즈 코엑스점"},
                    "formattedAddress": "서울 강남구 영동대로 513",
                    "location": {
                        "latitude": 37.51207412593136,
                        "longitude": 127.05902969025047,
                    },
                    "googleMapsUri": "https://maps.google.com/?cid=1",
                    "nationalPhoneNumber": "02-6002-1880",
                }
            ]
        }
    )

    candidates = GooglePlacesTextSearcher("google-key", transport=transport)(feature)

    assert len(candidates) == 1
    assert candidates[0].provider == GOOGLE_PLACES_PROVIDER
    assert candidates[0].phone == "02-6002-1880"
    request = transport.requests[0]
    assert request.method == "POST"
    assert "places.nationalPhoneNumber" in request.headers["X-Goog-FieldMask"]
    assert request.json_body is not None
    assert request.json_body["regionCode"] == "KR"
    assert request.json_body["locationBias"]["circle"]["center"]["latitude"] == (
        feature.coord.latitude
    )


def test_enrich_place_phone_adds_phone_and_source_trace() -> None:
    feature = _place_feature()

    def fake_searcher(_: Feature) -> tuple[PlaceSearchCandidate, ...]:
        return (
            PlaceSearchCandidate(
                provider=KAKAO_LOCAL_PROVIDER,
                provider_place_id="26338954",
                name=feature.name,
                phone="02-6002-1880",
                road_address_name="서울 강남구 영동대로 513",
                coord=feature.coord,
                place_url="http://place.map.kakao.com/26338954",
                raw={"id": "26338954", "phone": "02-6002-1880"},
                confidence=95,
                match_method="kakao_keyword_phone",
            ),
        )

    result = enrich_place_phone(
        feature,
        PlaceDetail(feature_id=feature.feature_id, phones=["02-111-2222"]),
        searchers=[fake_searcher],
    )

    assert result.added_phones == ("02-6002-1880",)
    assert result.place_detail.phones == ["02-111-2222", "02-6002-1880"]
    assert result.place_detail.payload["place_phone_enrichment"]["version"]
    assert result.source_records[0].provider == KAKAO_LOCAL_PROVIDER
    assert result.source_links[0].source_role == SourceRole.ENRICHMENT
    assert result.source_links[0].confidence == 95

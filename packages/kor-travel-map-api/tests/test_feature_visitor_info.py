"""공개 feature 상세의 typed 방문 안내(ADR-126).

``visitor_info``는 ``detail.facility_info``에서 떼어 typed 필드 하나로만 나간다(정본 하나).
"""

from __future__ import annotations

from typing import Any

import pytest

from kortravelmap.api.routers import features

pytestmark = pytest.mark.unit

_INFO: dict[str, Any] = {
    "source": "tourapi",
    "attribution": "한국관광공사",
    "usage_hours": "09:00~18:00",
    "images": [
        {
            "url": "http://tong.visitkorea.or.kr/a.jpg",
            "license": {
                "attribution": "한국관광공사",
                "kogl_type": 3,
                "label": "공공누리 제3유형(출처표시·변경금지)",
                "derivatives_allowed": False,
                "commercial_allowed": True,
            },
        }
    ],
}


def test_place_visitor_info_moves_to_typed_field() -> None:
    detail = {"place_kind": "tourapi_attraction", "facility_info": {"x": 1, "visitor_info": _INFO}}
    rest, info = features._split_visitor_info("place", detail)
    assert rest["facility_info"] == {"x": 1}
    assert info is not None
    assert info.usage_hours == "09:00~18:00"
    assert info.images[0].license.derivatives_allowed is False
    assert detail["facility_info"]["visitor_info"] == _INFO  # 입력은 건드리지 않는다


def test_non_place_or_missing_visitor_info_passes_through() -> None:
    detail = {"facility_info": {"visitor_info": _INFO}}
    assert features._split_visitor_info("event", detail) == (detail, None)
    plain = {"facility_info": {"x": 1}}
    assert features._split_visitor_info("place", plain) == (plain, None)


def test_malformed_stored_visitor_info_is_dropped_not_500() -> None:
    detail = {"facility_info": {"visitor_info": {"source": "unknown"}}}
    rest, info = features._split_visitor_info("place", detail)
    assert info is None
    assert rest["facility_info"] == {}


def test_openapi_exposes_typed_visitor_info() -> None:
    schema = features.FeatureDetailResponse.model_json_schema()
    prop = schema["properties"]["visitor_info"]
    assert any(option.get("$ref", "").endswith("PlaceVisitorInfo") for option in prop["anyOf"])

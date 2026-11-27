"""``test_place_visitor_info`` — place 방문 안내 typed 모델(ADR-126).

- ``PlaceVisitorInfo``는 ``PlaceDetail.facility_info["visitor_info"]``에서 검증된다(자유 dict 금지).
- 이미지는 공공누리 유형을 아는 것만 담는다(fail-closed). 3·4유형은 변경 금지다.
- 국가유산은 설명문만 담는다(이미지 ``imageNuri`` 코드표 미확인).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from kortravelmap.dto import (
    ContentLicense,
    PlaceDetail,
    PlaceImage,
    PlaceVisitorInfo,
    kogl_license,
)
from kortravelmap.providers.krheritage import heritage_items_to_bundles

pytestmark = pytest.mark.unit

KST = timezone(timedelta(hours=9))
_FETCHED = datetime(2026, 11, 27, 4, 0, tzinfo=KST)


# -- DTO ------------------------------------------------------------------


def test_kogl_license_derives_permissions() -> None:
    type1 = kogl_license(1, attribution="한국관광공사")
    type3 = kogl_license(3, attribution="한국관광공사")
    assert (type1.derivatives_allowed, type1.commercial_allowed) == (True, True)
    assert (type3.derivatives_allowed, type3.commercial_allowed) == (False, True)
    assert type3.label == "공공누리 제3유형(출처표시·변경금지)"


def test_license_flags_must_match_kogl_type() -> None:
    with pytest.raises(ValidationError, match="derivatives_allowed"):
        ContentLicense(
            attribution="한국관광공사",
            kogl_type=3,
            derivatives_allowed=True,
            commercial_allowed=True,
        )


def test_image_without_kogl_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="kogl_type"):
        PlaceImage.model_validate(
            {
                "url": "https://example.org/a.jpg",
                "license": {
                    "attribution": "국가유산청",
                    "derivatives_allowed": False,
                    "commercial_allowed": False,
                },
            }
        )


def test_image_url_must_be_http() -> None:
    with pytest.raises(ValidationError):
        PlaceImage(url="javascript:alert(1)", license=kogl_license(1, attribution="x"))


def test_explicit_none_visitor_info_is_removed() -> None:
    detail = PlaceDetail(feature_id="f", facility_info={"visitor_info": None, "x": 1})
    assert detail.facility_info == {"x": 1}


def test_place_detail_validates_and_normalizes_visitor_info() -> None:
    info = PlaceVisitorInfo(source="tourapi", attribution="한국관광공사", usage_hours="09:00~18:00")
    detail = PlaceDetail(feature_id="f", facility_info={"visitor_info": info, "x": 1})
    assert detail.facility_info == {
        "x": 1,
        "visitor_info": {
            "source": "tourapi",
            "attribution": "한국관광공사",
            "usage_hours": "09:00~18:00",
        },
    }
    # 저장값(dict)을 다시 읽어도 같은 모양이다.
    again = PlaceDetail.model_validate(detail.model_dump(mode="json"))
    assert again.facility_info == detail.facility_info


def test_place_detail_rejects_free_dict_visitor_info() -> None:
    with pytest.raises(ValidationError):
        PlaceDetail(
            feature_id="f",
            facility_info={"visitor_info": {"source": "tourapi", "hours": "x"}},
        )


def test_place_detail_drops_empty_visitor_info() -> None:
    info = PlaceVisitorInfo(source="krheritage", attribution="국가유산청, www.khs.go.kr")
    detail = PlaceDetail(feature_id="f", facility_info={"visitor_info": info})
    assert detail.facility_info == {}


# -- 국가유산 설명문 ----------------------------------------------------------


@dataclass(frozen=True)
class _HeritageKey:
    ccba_kdcd: str = "11"
    ccba_asno: str = "0000010000000"
    ccba_ctcd: str = "11"

    @property
    def natural_key(self) -> str:
        return f"{self.ccba_kdcd}-{self.ccba_asno}-{self.ccba_ctcd}"


@dataclass(frozen=True)
class _Heritage:
    key: _HeritageKey
    name_ko: str = "서울 숭례문"
    category: str | None = "국보"
    region: str | None = "서울"
    sigungu: str | None = "중구"
    longitude: float | None = 126.975312652739
    latitude: float | None = 37.559975221378
    location_text: str | None = "서울 중구 세종대로 40 (남대문로4가)"
    designated_at: str | None = "19621220"
    owner: str | None = "국가유산청 덕수궁관리소"
    image_url: str | None = None
    content: str | None = None


def test_heritage_content_becomes_description_with_khs_attribution() -> None:
    item = _Heritage(_HeritageKey(), content="조선시대 한양도성의 정문으로 남쪽에 있다.")
    bundle = asyncio.run(heritage_items_to_bundles([item], fetched_at=_FETCHED))[0]
    info = bundle.feature.detail.facility_info["visitor_info"]  # type: ignore[union-attr]
    assert info == {
        "source": "krheritage",
        "attribution": "국가유산청, www.khs.go.kr",
        "description": "조선시대 한양도성의 정문으로 남쪽에 있다.",
    }
    assert bundle.source_record.raw_data["content"] == item.content


def test_heritage_description_keeps_literal_angle_brackets_and_paragraphs() -> None:
    # provider가 이미 태그를 걷고 entity를 푼 본문 — 다시 정리하면 책 제목 꺾쇠가 지워진다.
    text = "<삼국유사>에 전한다.\n\n둘째 문단."
    item = _Heritage(_HeritageKey(), content=f"  {text}  ")
    bundle = asyncio.run(heritage_items_to_bundles([item], fetched_at=_FETCHED))[0]
    info = bundle.feature.detail.facility_info["visitor_info"]  # type: ignore[union-attr]
    assert info["description"] == text
    assert "images" not in info  # imageNuri 코드표 미확인 — 이미지는 담지 않는다


def test_heritage_without_content_has_no_visitor_info() -> None:
    bundle = asyncio.run(
        heritage_items_to_bundles([_Heritage(_HeritageKey())], fetched_at=_FETCHED)
    )[0]
    assert "visitor_info" not in bundle.feature.detail.facility_info  # type: ignore[union-attr]
    assert "content" not in bundle.source_record.raw_data  # 옛 payload hash 유지

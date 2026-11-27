"""``PlaceVisitorInfo`` — place 방문 안내(이용시간·휴무·주차·요금·이미지·무장애·반려동물).

원천마다 이름이 다른 방문 안내 필드를 **한 typed 모델**로 모은다(ADR-018 — 자유 dict 금지).
저장 위치는 ``PlaceDetail.facility_info["visitor_info"]``이고, ``PlaceDetail``이 그 키를 이 모델로
검증·정규화한다. 그래서 DB 컬럼·DB 쪽 protocol 함수는 바뀌지 않는다(``facility_info``는 통째
jsonb다) — ADR-126.

원칙
----
- 원천 문장은 **가공하지 않는다**. 태그·공백만 걷은 원문 그대로 둔다(요약·번역·재작성 없음).
- 이미지는 원본 URL만 참조하고 라이선스를 이미지마다 남긴다. 이용 조건을 확인할 수 없는
  이미지는 **담지 않는다**(fail-closed). 공공누리 제3·4유형은 변경 금지라
  ``derivatives_allowed=False``다 — 표시하는 쪽은 크롭·필터·썸네일 재생성을 하지 않는다.
- 출처(``attribution``)는 원천 기관명이다. 화면은 이것을 그대로 표시한다.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "VISITOR_INFO_KEY",
    "AccessibilityGroup",
    "AccessibilityNote",
    "ContentLicense",
    "FeeAudience",
    "PetPolicy",
    "PlaceFee",
    "PlaceImage",
    "PlaceVisitorInfo",
    "VisitorInfoSource",
    "kogl_license",
]

VISITOR_INFO_KEY = "visitor_info"
"""``PlaceDetail.facility_info`` 안에서 이 모델이 사는 키."""

_Text = Annotated[str, Field(min_length=1, max_length=8000)]
_ShortText = Annotated[str, Field(min_length=1, max_length=2000)]
_Url = Annotated[str, Field(min_length=8, max_length=2048, pattern=r"^https?://\S+$")]

VisitorInfoSource = Literal[
    "tourapi",
    "krheritage",
    "datagokr_museum",
    "krforest_recreation_forest",
]
"""방문 안내를 만든 원천(한 place에 한 원천 — primary provider)."""

_KOGL_LABEL: dict[int, str] = {
    0: "공공누리 제0유형(조건 없음)",
    1: "공공누리 제1유형(출처표시)",
    2: "공공누리 제2유형(출처표시·상업적 이용금지)",
    3: "공공누리 제3유형(출처표시·변경금지)",
    4: "공공누리 제4유형(출처표시·상업적 이용금지·변경금지)",
}


class ContentLicense(BaseModel):
    """한 이미지의 이용 조건 — 공공누리 유형이 확인된 것만 있다(없으면 이미지를 담지 않는다).

    텍스트 안내는 원천 데이터의 이용허락을 따르므로 license 없이
    ``PlaceVisitorInfo.attribution``만 남긴다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    attribution: _ShortText = Field(description="출처 표시 문구(원천 기관명).")
    kogl_type: Annotated[int, Field(ge=0, le=4)] = Field(description="공공누리 유형 0~4.")
    label: _ShortText | None = Field(default=None, description="사람이 읽는 이용 조건.")
    derivatives_allowed: bool = Field(
        description="변경(크롭·필터·리사이즈 재생성) 허용 여부. 공공누리 3·4유형은 False."
    )
    commercial_allowed: bool = Field(description="상업적 이용 허용 여부. 공공누리 2·4유형은 False.")

    @model_validator(mode="after")
    def _consistent_with_kogl(self) -> Self:
        if self.derivatives_allowed != (self.kogl_type in (0, 1, 2)):
            raise ValueError("derivatives_allowed가 공공누리 유형과 맞지 않는다")
        if self.commercial_allowed != (self.kogl_type in (0, 1, 3)):
            raise ValueError("commercial_allowed가 공공누리 유형과 맞지 않는다")
        return self


def kogl_license(kogl_type: int, *, attribution: str) -> ContentLicense:
    """공공누리 유형 → :class:`ContentLicense` (허용 여부는 유형에서 결정된다)."""
    return ContentLicense(
        attribution=attribution,
        kogl_type=kogl_type,
        label=_KOGL_LABEL[kogl_type],
        derivatives_allowed=kogl_type in (0, 1, 2),
        commercial_allowed=kogl_type in (0, 1, 3),
    )


class PlaceImage(BaseModel):
    """원본 참조 이미지 1장(가공 없음)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: _Url = Field(description="원본 이미지 URL(원천이 준 그대로).")
    thumbnail_url: _Url | None = Field(
        default=None, description="원천이 준 작은 이미지 URL. Map이 만든 썸네일이 아니다."
    )
    caption: _ShortText | None = Field(
        default=None, description="원천 이미지 이름(없으면 null — 화면이 장소명으로 대체한다)."
    )
    license: ContentLicense


FeeAudience = Literal["adult", "youth", "child"]


class PlaceFee(BaseModel):
    """구조화된 요금 1건(원천이 숫자로 줄 때만 — 박물관 표준데이터)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    audience: FeeAudience
    amount_krw: Annotated[int, Field(ge=0, le=10_000_000)]


AccessibilityGroup = Literal["physical", "visual", "hearing", "infant_family"]
"""무장애 분류 — 지체(physical)·시각(visual)·청각(hearing)·영유아 가족(infant_family)."""


class AccessibilityNote(BaseModel):
    """무장애 안내 1항목(TourAPI ``detailWithTour2`` 한 필드)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group: AccessibilityGroup
    facility: Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z_]+$")]
    label: _ShortText
    text: _ShortText


class PetPolicy(BaseModel):
    """반려동물 동반 안내(TourAPI ``detailPetTour2``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    companion_type: _ShortText | None = Field(default=None, description="동반 구분.")
    allowed_pets: _ShortText | None = Field(default=None, description="동반 가능 동물.")
    requirements: _ShortText | None = Field(default=None, description="동반 시 필요 사항.")
    notes: _ShortText | None = Field(default=None, description="기타 동반 정보.")

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not any((self.companion_type, self.allowed_pets, self.requirements, self.notes)):
            raise ValueError("빈 반려동물 안내는 None으로 둔다")
        return self


class PlaceVisitorInfo(BaseModel):
    """place 방문 안내 — 원천 문장 그대로의 typed 묶음.

    소비자 규칙: 모르는 ``source``·``group``·``audience`` 값과 모르는 필드는 무시한다(원천이 늘면
    값이 더해진다). 목록 필드는 비어 있으면 생략될 수 있다. 배지는 원문을 해석하지 말고
    ``accessibility``가 비어 있지 않음 / ``pet_policy``가 있음으로 판단한다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: VisitorInfoSource
    attribution: _ShortText = Field(description="출처 표시 문구(원천 기관명).")
    reference_date: date | None = Field(default=None, description="원천 기준일(있을 때).")
    description: _Text | None = Field(
        default=None, description="원천 소개문(국가유산 설명문·박물관 소개 등)."
    )
    usage_hours: _ShortText | None = Field(default=None, description="이용·관람 시간 원문.")
    rest_days: _ShortText | None = Field(default=None, description="휴무·휴관일 원문.")
    parking: _ShortText | None = Field(default=None, description="주차 안내 원문.")
    parking_fee: _ShortText | None = Field(default=None, description="주차 요금 원문.")
    fee_text: _ShortText | None = Field(default=None, description="이용 요금 원문.")
    fees: list[PlaceFee] = Field(default_factory=list, max_length=3)
    discount: _ShortText | None = Field(default=None, description="할인 안내 원문.")
    reservation: _ShortText | None = Field(default=None, description="예약 안내 원문.")
    inquiry: _ShortText | None = Field(default=None, description="문의·안내 원문.")
    transport: _ShortText | None = Field(default=None, description="교통 안내 원문.")
    facilities: _ShortText | None = Field(default=None, description="주요·편의 시설 원문.")
    capacity: _ShortText | None = Field(default=None, description="수용 인원 원문.")
    accommodation_available: bool | None = Field(default=None, description="숙박 가능 여부.")
    pet_note: _ShortText | None = Field(
        default=None, description="반려동물 동반 여부 원문(소개정보 한 줄, 해석하지 않는다)."
    )
    images: list[PlaceImage] = Field(default_factory=list, max_length=30)
    accessibility: list[AccessibilityNote] = Field(default_factory=list, max_length=40)
    pet_policy: PetPolicy | None = None

    def is_empty(self) -> bool:
        """출처 말고는 아무 안내도 없는가(저장하지 않을 대상)."""
        return all(
            value is None or value == []
            for name, value in self
            if name not in {"source", "attribution", "reference_date"}
        )

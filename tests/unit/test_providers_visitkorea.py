"""``test_providers_visitkorea`` — VisitKorea TourAPI enrichment (PR#51, ADR-042).

본 PR 테스트 범위:
- ``festival_to_enrichment_links`` happy path (매칭된 item만 enrichment).
- ``FestivalMatcher.match() -> None``인 item은 결과에서 제외.
- ``SourceLink``는 enrichment role + is_primary_source=False + 1차 feature_id 매핑.
- ``SourceRecord``는 새 Feature 없이 visitkorea raw 보존 (provider/dataset_key).
- 결정성 — 같은 입력은 항상 같은 ``source_record_key``.
- ``FestivalEnrichment`` consistency validator (role/key/primary).
- naive ``fetched_at``은 ADR-019 reject.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from krtour.map.dto import SourceRole
from krtour.map.providers.visitkorea import (
    DATASET_KEY_FESTIVAL_EVENTS,
    VISITKOREA_PROVIDER_NAME,
    FestivalEnrichment,
    festival_to_enrichment_links,
)

KST = timezone(timedelta(hours=9))


# -- fixtures (Protocol 만족 frozen dataclass) ----------------------------


@dataclass(frozen=True)
class _Item:
    """``VisitKoreaFestivalItem`` Protocol 만족 테스트 dataclass."""

    content_id: str
    title: str | None
    overview: str | None
    first_image: str | None
    first_image2: str | None
    addr1: str | None
    area_code: str | None
    sigungu_code: str | None
    event_start_date: str | None
    event_end_date: str | None
    tel: str | None
    homepage: str | None
    modified_time: datetime | str | None


@dataclass(frozen=True)
class _Match:
    """``FestivalMatch`` Protocol 만족."""

    feature_id: str
    confidence: int
    match_method: str


class _DictMatcher:
    """``FestivalMatcher`` — content_id → (feature_id, confidence) dict 기반.

    매핑에 없는 content_id는 ``None`` 반환 (enrichment 생략 검증용).
    """

    def __init__(self, mapping: dict[str, _Match]) -> None:
        self._mapping = mapping

    def match(self, item: object) -> _Match | None:
        return self._mapping.get(item.content_id)  # type: ignore[attr-defined]


_ITEM1 = _Item(
    content_id="2747929",
    title="서울 봄꽃 축제",
    overview="여의도 일대 봄꽃 축제 상세 설명.",
    first_image="http://tong.visitkorea.or.kr/img1.jpg",
    first_image2="http://tong.visitkorea.or.kr/img1_thumb.jpg",
    addr1="서울특별시 영등포구 여의공원로 120",
    area_code="1",
    sigungu_code="19",
    event_start_date="20260405",
    event_end_date="20260412",
    tel="02-2670-3114",
    homepage='<a href="http://spring.example.kr">바로가기</a>',
    # provider 실모델(TourItem.modified_time)은 datetime으로 파싱해 보존한다
    # (ADR-044 재정렬 — T-212e live 실측). 변환이 원시 TourAPI 표기로
    # 문자열화하는지 본 fake로 검증한다.
    modified_time=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=9))),
)
_ITEM2 = _Item(
    content_id="2747930",
    title="부산 바다 축제",
    overview=None,
    first_image=None,
    first_image2=None,
    addr1="부산광역시 해운대구 해운대해변로 264",
    area_code="6",
    sigungu_code="16",
    event_start_date="20260801",
    event_end_date="20260805",
    tel=None,
    homepage=None,
    modified_time="20260601090000",
)

# ITEM1은 매칭, ITEM2는 매칭 실패(미등록) → 결과에서 제외.
_FEATURE_ID_1 = "f_1156000000_e_abcdef0123456789abcd"
_MATCHER = _DictMatcher(
    {
        "2747929": _Match(
            feature_id=_FEATURE_ID_1,
            confidence=88,
            match_method="name_region_match",
        ),
    }
)


# -- happy path -----------------------------------------------------------


@pytest.mark.unit
def test_enrichment_only_matched_items() -> None:
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=KST)
    links = festival_to_enrichment_links(
        [_ITEM1, _ITEM2], matcher=_MATCHER, fetched_at=fetched
    )
    # ITEM2는 매칭 실패 → 1건만.
    assert len(links) == 1
    assert isinstance(links[0], FestivalEnrichment)


@pytest.mark.unit
def test_enrichment_source_link_shape() -> None:
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=KST)
    [link] = festival_to_enrichment_links(
        [_ITEM1], matcher=_MATCHER, fetched_at=fetched
    )
    sl = link.source_link
    assert sl.feature_id == _FEATURE_ID_1
    assert sl.source_role is SourceRole.ENRICHMENT
    assert sl.is_primary_source is False
    assert sl.match_method == "name_region_match"
    assert sl.confidence == 88
    # link가 record를 가리킴.
    assert sl.source_record_key == link.source_record.source_record_key


@pytest.mark.unit
def test_enrichment_source_record_no_feature() -> None:
    """enrichment는 Feature를 만들지 않고 visitkorea raw만 보존."""
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=KST)
    [link] = festival_to_enrichment_links(
        [_ITEM1], matcher=_MATCHER, fetched_at=fetched
    )
    sr = link.source_record
    assert sr.provider == VISITKOREA_PROVIDER_NAME
    assert sr.dataset_key == DATASET_KEY_FESTIVAL_EVENTS
    assert sr.source_entity_id == "2747929"
    # 이미지/overview는 raw_data에 보존 (FeatureFileSource는 후속 PR).
    assert sr.raw_data["first_image"] == "http://tong.visitkorea.or.kr/img1.jpg"
    assert sr.raw_data["overview"] == "여의도 일대 봄꽃 축제 상세 설명."
    assert sr.raw_data["content_id"] == "2747929"
    # datetime modified_time은 원시 TourAPI 표기(YYYYMMDDHHMMSS) 문자열로
    # 정규화돼 source_version/raw_data 모두에 들어간다 (JSON 직렬화 안전).
    assert sr.source_version == "20260301120000"
    assert sr.raw_data["modified_time"] == "20260301120000"


@pytest.mark.unit
def test_enrichment_deterministic_key() -> None:
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=KST)
    [a] = festival_to_enrichment_links([_ITEM1], matcher=_MATCHER, fetched_at=fetched)
    [b] = festival_to_enrichment_links([_ITEM1], matcher=_MATCHER, fetched_at=fetched)
    assert a.source_record.source_record_key == b.source_record.source_record_key


@pytest.mark.unit
def test_enrichment_empty_when_no_match() -> None:
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=KST)
    empty = _DictMatcher({})
    links = festival_to_enrichment_links(
        [_ITEM1, _ITEM2], matcher=empty, fetched_at=fetched
    )
    assert links == []


@pytest.mark.unit
def test_enrichment_naive_fetched_at_rejected() -> None:
    """ADR-019 — naive datetime은 SourceRecord validator에서 reject."""
    naive = datetime(2026, 5, 28, 10, 0)  # tzinfo 없음
    with pytest.raises(ValidationError):
        festival_to_enrichment_links([_ITEM1], matcher=_MATCHER, fetched_at=naive)


# -- FestivalEnrichment consistency validator -----------------------------


@pytest.mark.unit
def test_festival_enrichment_rejects_primary_role() -> None:
    """직접 구성 시 role이 enrichment가 아니면 reject."""
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=KST)
    [link] = festival_to_enrichment_links(
        [_ITEM1], matcher=_MATCHER, fetched_at=fetched
    )
    sr = link.source_record
    bad_link = link.source_link.model_copy(
        update={"source_role": SourceRole.PRIMARY}
    )
    with pytest.raises(ValidationError):
        FestivalEnrichment(source_record=sr, source_link=bad_link)


@pytest.mark.unit
def test_festival_enrichment_rejects_key_mismatch() -> None:
    fetched = datetime(2026, 5, 28, 10, 0, tzinfo=KST)
    [link] = festival_to_enrichment_links(
        [_ITEM1], matcher=_MATCHER, fetched_at=fetched
    )
    bad_link = link.source_link.model_copy(
        update={"source_record_key": "sr_does_not_match"}
    )
    with pytest.raises(ValidationError):
        FestivalEnrichment(source_record=link.source_record, source_link=bad_link)

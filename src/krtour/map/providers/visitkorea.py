"""``krtour.map.providers.visitkorea`` — VisitKorea TourAPI → enrichment links.

datagokr 전국문화축제표준데이터(``standard_data.cultural_festivals_to_bundles``)
가 **1차 source**로 Feature를 만든다 (ADR-042). 본 모듈은 VisitKorea TourAPI를
**2차 enrichment**로 쓴다 — 이미지 / 상세설명(overview) / contentId 매핑을
``source_links(source_role='enrichment')``로 **이미 적재된 festival
feature_id**에 잇는다.

즉 본 모듈은 **새 Feature를 만들지 않는다**. 1차로 적재된 festival의
``feature_id``에 visitkorea ``SourceRecord`` + ``SourceLink``(enrichment)만
추가한다. 어떤 datagokr festival이 어떤 visitkorea festival인지 매칭하는 일은
이름/지역 fuzzy match (ADR-016 Record Linkage scoring)라 본 모듈 밖에서
결정한다 — ``FestivalMatcher`` plug-in으로 주입 (``standard_data``의
``ReverseGeocoder`` 패턴과 동일).

지원 dataset:

| dataset_key | 역할 | 함수 |
|-------------|------|------|
| ``visitkorea_festival_events`` | enrichment | ``festival_to_enrichment_links`` |

ADR 참조
--------
- ADR-006 — provider wrapper 금지 (public client 직접 사용, 본 모듈은 변환만)
- ADR-009 — ``make_source_record_key`` / ``make_payload_hash``
- ADR-016 — Record Linkage (festival ↔ visitkorea 매칭은 ``FestivalMatcher``
  주입; scoring 자체는 ``core/scoring.py``)
- ADR-019 — datetime aware (KST)
- ADR-024 — canonical provider name ``python-visitkorea-api``
- ADR-042 — datagokr 1차 + visitkorea enrichment 2차

설계 메모
--------
``python-visitkorea-api``의 typed model(``SearchFestivalItem`` 등)은 본
라이브러리가 import하지 않는다 (ADR-006). 입력 shape는
``VisitKoreaFestivalItem`` ``Protocol``로만 정의. ``FeatureFileSource`` DTO는
아직 없으므로(Sprint 2-3 예정) 이미지 URL은 ``SourceRecord.raw_data``에
보존만 한다 — RustFS 업로드/파일 row는 후속 PR.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from krtour.map.core.address import normalize_korean_text, normalize_phone_number
from krtour.map.core.ids import make_payload_hash, make_source_record_key
from krtour.map.core.providers import normalize_provider_name
from krtour.map.core.scoring import name_similarity
from krtour.map.dto import SourceLink, SourceRecord, SourceRole

__all__ = [
    "VisitKoreaFestivalItem",
    "FestivalMatch",
    "FestivalMatcher",
    "FestivalCandidate",
    "ScoringFestivalMatcher",
    "FestivalEnrichment",
    "FestivalReviewCandidate",
    "FestivalMatchPlan",
    "festival_to_enrichment_links",
    "festival_to_review_candidates",
    "VISITKOREA_PROVIDER_NAME",
    "DATASET_KEY_FESTIVAL_EVENTS",
    "DEFAULT_ACCEPT_THRESHOLD",
    "DEFAULT_REVIEW_FLOOR",
]


# -- 상수 -----------------------------------------------------------------

VISITKOREA_PROVIDER_NAME: Final[str] = "python-visitkorea-api"
"""canonical provider name (ADR-024). ``normalize_provider_name``으로 정규화."""

DATASET_KEY_FESTIVAL_EVENTS: Final[str] = "visitkorea_festival_events"
"""``provider_sync.source_records.dataset_key`` 값 — VisitKorea 축제 enrichment."""

_SOURCE_ENTITY_TYPE: Final[str] = "festival_enrichment"
"""provider 내 entity 종류 — ``source_records.source_entity_type``."""


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class VisitKoreaFestivalItem(Protocol):
    """VisitKorea TourAPI ``searchFestival`` 한 item의 입력 shape.

    ``python-visitkorea-api``의 typed model(``SearchFestivalItem``)이 본
    Protocol을 만족해야 한다. 필드 이름이 다르면 호출자가 가벼운 dataclass
    adapter를 자기 영역에서 만들어 전달.
    """

    content_id: str
    """TourAPI contentId — provider 내 자연키 (``source_entity_id``로 매핑)."""

    title: str | None
    """축제명 (raw_data 보존 — 1차 datagokr이 이미 ``Feature.name``을 가짐)."""

    overview: str | None
    """상세설명 (enrichment 핵심 — raw_data에 보존)."""

    first_image: str | None
    """대표 이미지 URL. ``FeatureFileSource``는 후속 — 지금은 raw_data만."""

    first_image2: str | None
    """썸네일 이미지 URL."""

    addr1: str | None
    """주소 (raw_address 검증용)."""

    area_code: str | None
    """TourAPI 지역코드 (법정동코드 아님 — raw_data만)."""

    sigungu_code: str | None
    """TourAPI 시군구코드 (법정동코드 아님 — raw_data만)."""

    event_start_date: str | None
    """축제 시작일 (YYYYMMDD 문자열, raw_data 보존)."""

    event_end_date: str | None
    """축제 종료일 (YYYYMMDD 문자열, raw_data 보존)."""

    tel: str | None
    """문의 전화 (raw_data 보존)."""

    homepage: str | None
    """홈페이지 (HTML anchor 포함 가능 — raw_data 보존)."""

    modified_time: str | None
    """TourAPI 최종 수정시각 (``source_version`` 대용)."""


# -- 매칭 Protocol (festival ↔ visitkorea) --------------------------------


class FestivalMatch(Protocol):
    """``FestivalMatcher.match(item)`` 결과 — 1차 festival과의 매칭 정보.

    매칭 자체(이름/지역 fuzzy)는 본 모듈 밖 책임 (ADR-016 ``core/scoring.py``).
    본 모듈은 결과만 받아 ``SourceLink``로 옮긴다.
    """

    feature_id: str
    """매칭된 datagokr festival의 ``make_feature_id(...)`` 결과."""

    confidence: int
    """매칭 신뢰도 0~100 (ADR-016 scoring × 100). ``SourceLink.confidence``로."""

    match_method: str
    """매칭 방법 (예: ``'name_region_match'`` / ``'manual'``)."""


class FestivalMatcher(Protocol):
    """visitkorea item → 1차 festival ``FestivalMatch`` resolver (plug-in).

    ``standard_data.ReverseGeocoder``와 동일한 plug-in 패턴. 구현체는 호출자
    (TripMate Dagster asset)가 ``core/scoring.py``로 적재된 festival과 비교해
    제공. 매칭 실패 시 ``None`` → 해당 visitkorea item은 enrichment 생략.
    """

    def match(self, item: VisitKoreaFestivalItem) -> FestivalMatch | None: ...


# -- 기본 매칭 구현 (이름 유사도, ADR-016) --------------------------------


@dataclass(frozen=True, slots=True)
class FestivalCandidate:
    """``ScoringFestivalMatcher`` 후보 — 이미 적재된 datagokr 축제 1건.

    ``feature_id``는 ``make_feature_id(...)`` 결과(1차 datagokr festival),
    ``name``은 ``Feature.name``. 호출자(Dagster asset)가 DB에서 적재된 festival을
    읽어 candidate list를 만든다.
    """

    feature_id: str
    name: str


@dataclass(slots=True)
class _FestivalMatch:
    """``FestivalMatch`` Protocol 구현.

    ``FestivalMatch`` Protocol이 mutable 속성을 선언하므로 frozen이 아니다(frozen이면
    read-only라 mypy structural 매칭 실패). 내부 사용은 read-only로만 한다.
    """

    feature_id: str
    confidence: int
    match_method: str


class ScoringFestivalMatcher:
    """``FestivalMatcher`` 기본 구현 — 이름 Jaro-Winkler 유사도(ADR-016)로 매칭.

    ``VisitKoreaFestivalItem`` Protocol은 좌표/법정동코드를 노출하지 않으므로(area_code/
    sigungu_code는 TourAPI 자체 코드라 datagokr bjd와 직접 비교 불가) **이름 유사도만**
    쓴다. ``name_threshold`` 이상이면서 최고점인 후보를 매칭한다(동점이면 먼저 등장한
    후보). 매칭 실패 시 ``None``.

    축제명은 보통 변별력이 높아 이름-only 매칭으로도 정밀도가 충분하다. 기본 임계값은
    보수적으로 0.90(false positive 회피). 좌표 기반 보강은 Protocol 확장 후속.
    """

    def __init__(
        self,
        candidates: Iterable[FestivalCandidate],
        *,
        name_threshold: float = 0.90,
        match_method: str = "name_match",
    ) -> None:
        if not 0.0 <= name_threshold <= 1.0:
            raise ValueError("name_threshold must be in [0, 1]")
        self._candidates = [c for c in candidates if c.name and c.name.strip()]
        self._threshold = name_threshold
        self._match_method = match_method

    def best_match(
        self, item: VisitKoreaFestivalItem
    ) -> tuple[FestivalCandidate, float] | None:
        """임계값과 무관하게 최고 이름 유사도 후보 + 점수(0.0~1.0)를 반환.

        ``match()``(임계 적용)와 review-band 분류(``festival_to_review_candidates``)가
        공유하는 raw 매칭. title이 비었거나 후보가 없으면 ``None``.
        """
        title = item.title or ""
        if not title.strip():
            return None
        best: FestivalCandidate | None = None
        best_score = 0.0
        for candidate in self._candidates:
            score = name_similarity(title, candidate.name)
            if score > best_score:
                best_score = score
                best = candidate
        if best is None:
            return None
        return best, best_score

    def match(self, item: VisitKoreaFestivalItem) -> FestivalMatch | None:
        found = self.best_match(item)
        if found is None:
            return None
        best, best_score = found
        if best_score < self._threshold:
            return None
        return _FestivalMatch(
            feature_id=best.feature_id,
            confidence=round(best_score * 100),
            match_method=self._match_method,
        )


# -- 결과 DTO -------------------------------------------------------------


class FestivalEnrichment(BaseModel):
    """visitkorea enrichment 한 건 — ``SourceRecord`` + ``SourceLink``(enrichment).

    ``FeatureBundle``과 달리 ``Feature``를 포함하지 않는다 (enrichment는 기존
    feature에 source만 추가). 적재 시 호출자는 ``source_record`` → ``source_link``
    순으로 insert (feature는 1차에서 이미 존재).
    """

    model_config = ConfigDict(extra="forbid")

    source_record: SourceRecord
    source_link: SourceLink

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        """source_link가 source_record를 가리키고, enrichment 규약을 지키는지."""
        if self.source_link.source_record_key != self.source_record.source_record_key:
            raise ValueError(
                "source_link.source_record_key가 source_record와 불일치"
            )
        if self.source_link.source_role is not SourceRole.ENRICHMENT:
            raise ValueError("enrichment link의 source_role은 ENRICHMENT여야 함")
        if self.source_link.is_primary_source:
            raise ValueError("enrichment link는 is_primary_source=False여야 함")
        return self


# -- 단일 변환 ------------------------------------------------------------


def _item_to_enrichment(
    item: VisitKoreaFestivalItem,
    match: FestivalMatch,
    *,
    fetched_at: datetime,
) -> FestivalEnrichment:
    """한 visitkorea item + 매칭 결과 → 한 ``FestivalEnrichment``. 모듈 private."""

    # 1) Raw payload (canonical JSON 직렬화 가능한 dict). 이미지/overview 등
    #    enrichment 콘텐츠는 여기에 보존 — FeatureFileSource DTO는 후속 PR.
    raw_data: dict[str, Any] = {
        "content_id": item.content_id,
        "title": item.title,
        "overview": item.overview,
        "first_image": item.first_image,
        "first_image2": item.first_image2,
        "addr1": item.addr1,
        "area_code": item.area_code,
        "sigungu_code": item.sigungu_code,
        "event_start_date": item.event_start_date,
        "event_end_date": item.event_end_date,
        "tel": normalize_phone_number(item.tel),
        "homepage": item.homepage,
        "modified_time": item.modified_time,
    }
    payload_hash = make_payload_hash(raw_data)

    # 2) source_record_key (ADR-009) — contentId 자연키.
    source_record_key = make_source_record_key(
        provider=VISITKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FESTIVAL_EVENTS,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=item.content_id,
        raw_payload_hash=payload_hash,
    )

    # 3) SourceRecord (visitkorea raw 보존). Feature/feature_id는 만들지 않음.
    source_record = SourceRecord(
        provider=normalize_provider_name(VISITKOREA_PROVIDER_NAME),
        dataset_key=DATASET_KEY_FESTIVAL_EVENTS,
        source_entity_type=_SOURCE_ENTITY_TYPE,
        source_entity_id=item.content_id,
        raw_payload_hash=payload_hash,
        source_version=item.modified_time,
        raw_name=normalize_korean_text(item.title),
        raw_address=normalize_korean_text(item.addr1),
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )

    # 4) SourceLink — enrichment (ADR-042). 1차 festival feature_id에 매핑.
    source_link = SourceLink(
        feature_id=match.feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.ENRICHMENT,
        match_method=match.match_method,
        confidence=match.confidence,
        is_primary_source=False,
    )

    return FestivalEnrichment(source_record=source_record, source_link=source_link)


# -- 공개 API -----------------------------------------------------------


def festival_to_enrichment_links(
    items: Iterable[VisitKoreaFestivalItem],
    *,
    matcher: FestivalMatcher,
    fetched_at: datetime,
) -> list[FestivalEnrichment]:
    """VisitKorea 축제 items → ``list[FestivalEnrichment]`` (ADR-042 2차 enrichment).

    1차(datagokr)로 이미 적재된 festival ``feature_id``에 visitkorea
    ``SourceRecord`` + ``SourceLink``(``source_role='enrichment'``)만 잇는다.
    **새 Feature를 만들지 않는다.**

    Parameters
    ----------
    items
        ``python-visitkorea-api`` searchFestival typed model iterable. 본 모듈의
        ``VisitKoreaFestivalItem`` Protocol을 만족해야 한다.
    matcher
        visitkorea item → 1차 festival 매칭 resolver (``FestivalMatcher``).
        ``match()``가 ``None``을 반환하는 item은 enrichment 생략 (출력 제외).
        매칭 로직(이름/지역 fuzzy, ADR-016)은 호출자 책임.
    fetched_at
        provider 호출 시각 (KST aware, ADR-019). 모든 record가 동일 값 사용.

    Returns
    -------
    list[FestivalEnrichment]
        매칭된 item 순서 유지. 각 원소는 ``SourceRecord`` + ``SourceLink``
        (enrichment). 매칭 실패 item은 제외되므로 ``len(result) <= len(items)``.

    Raises
    ------
    ValueError
        ``fetched_at``이 naive datetime (ADR-019, ``SourceRecord`` validator).

    Examples
    --------
    >>> # client = AsyncVisitKoreaClient(...)        # python-visitkorea-api
    >>> # items = [i async for i in client.aiter_festivals(...)]
    >>> # matcher = ScoringFestivalMatcher(loaded_festivals)   # core/scoring 활용
    >>> # links = festival_to_enrichment_links(
    >>> #     items, matcher=matcher, fetched_at=datetime.now(KST),
    >>> # )
    >>> # await krtour_client.load_enrichment_links(links)

    Notes
    -----
    - ``FeatureFileSource`` DTO 도입(Sprint 2-3) 전까지 이미지 URL은
      ``SourceRecord.raw_data['first_image' / 'first_image2']``에만 보존.
    - ``area_code`` / ``sigungu_code``는 TourAPI 자체 코드라 법정동코드로 저장
      하지 않는다 (raw_data만) — ADR-042.
    """
    results: list[FestivalEnrichment] = []
    for item in items:
        match = matcher.match(item)
        if match is None:
            continue
        results.append(
            _item_to_enrichment(item, match, fetched_at=fetched_at)
        )
    return results


# -- review-band 분류 (T-RV-52c 수동 검토 큐) ------------------------------

DEFAULT_ACCEPT_THRESHOLD: Final[float] = 0.90
"""이름 유사도 ≥ 이 값이면 자동 enrichment(현행 동작 유지, ADR-042)."""

DEFAULT_REVIEW_FLOOR: Final[float] = 0.70
"""``[REVIEW_FLOOR, ACCEPT_THRESHOLD)`` 밴드는 자동 확정이 모호 → 수동 검토 큐로.

이 값 미만은 매칭 후보로 보지 않고 버린다(false positive 회피).
"""


@dataclass(frozen=True, slots=True)
class FestivalReviewCandidate:
    """수동 검토가 필요한 visitkorea↔datagokr 축제 매칭 후보 1건.

    ``[REVIEW_FLOOR, ACCEPT_THRESHOLD)`` 밴드(자동 확정하기엔 모호)에 든 매칭을
    운영자가 accept/reject 하도록 큐에 넣기 위한 DTO. ``enrichment``는 accept 시
    그대로 적재할 ``SourceRecord`` + ``SourceLink``(ENRICHMENT, 제안 1차 feature_id)다.
    """

    target_feature_id: str
    """제안된 1차(datagokr) festival ``feature_id``."""

    target_name: str
    """1차 festival 이름 (검토 표시용)."""

    source_name: str
    """visitkorea 축제명 (검토 표시용)."""

    name_score: float
    """이름 Jaro-Winkler 유사도(0.0~1.0)."""

    enrichment: FestivalEnrichment
    """accept 시 적재할 enrichment(SourceRecord+SourceLink)."""


@dataclass(frozen=True, slots=True)
class FestivalMatchPlan:
    """``festival_to_review_candidates`` 결과 — 자동/검토 분류.

    - ``auto`` — ≥ accept_threshold, 현행대로 즉시 적재 대상.
    - ``review`` — review-band, 운영자 수동 검토 큐 대상.
    """

    auto: list[FestivalEnrichment]
    review: list[FestivalReviewCandidate]


def festival_to_review_candidates(
    items: Iterable[VisitKoreaFestivalItem],
    *,
    matcher: ScoringFestivalMatcher,
    fetched_at: datetime,
    accept_threshold: float = DEFAULT_ACCEPT_THRESHOLD,
    review_floor: float = DEFAULT_REVIEW_FLOOR,
    match_method: str = "name_match",
) -> FestivalMatchPlan:
    """visitkorea 축제 items를 이름 유사도 점수 밴드로 자동/검토 분류한다.

    각 item의 최고 유사도 후보(``matcher.best_match``)를 찾아:

    - ``score >= accept_threshold`` → ``auto`` (즉시 적재, 현행 동작 유지)
    - ``review_floor <= score < accept_threshold`` → ``review`` (수동 검토 큐)
    - ``score < review_floor`` → 제외 (매칭 없음)

    Parameters
    ----------
    items
        ``VisitKoreaFestivalItem`` Protocol iterable.
    matcher
        ``ScoringFestivalMatcher`` (1차 festival 후보로 구성). ``best_match``로 임계와
        무관한 최고점 후보를 얻는다.
    fetched_at
        provider 호출 시각(KST aware, ADR-019).
    accept_threshold, review_floor
        밴드 경계(0.0~1.0). ``review_floor <= accept_threshold`` 이어야 한다.

    Returns
    -------
    FestivalMatchPlan
        ``auto`` + ``review`` 분류 결과. item 순서 유지.

    Raises
    ------
    ValueError
        밴드 경계가 부적절(범위 밖 또는 ``review_floor > accept_threshold``)할 때.
    """
    if not 0.0 <= review_floor <= accept_threshold <= 1.0:
        raise ValueError(
            "0 <= review_floor <= accept_threshold <= 1 이어야 함"
        )
    auto: list[FestivalEnrichment] = []
    review: list[FestivalReviewCandidate] = []
    for item in items:
        found = matcher.best_match(item)
        if found is None:
            continue
        candidate, score = found
        if score < review_floor:
            continue
        match = _FestivalMatch(
            feature_id=candidate.feature_id,
            confidence=round(score * 100),
            match_method=match_method,
        )
        enrichment = _item_to_enrichment(item, match, fetched_at=fetched_at)
        if score >= accept_threshold:
            auto.append(enrichment)
        else:
            review.append(
                FestivalReviewCandidate(
                    target_feature_id=candidate.feature_id,
                    target_name=candidate.name,
                    source_name=normalize_korean_text(item.title) or item.title or "",
                    name_score=score,
                    enrichment=enrichment,
                )
            )
    return FestivalMatchPlan(auto=auto, review=review)

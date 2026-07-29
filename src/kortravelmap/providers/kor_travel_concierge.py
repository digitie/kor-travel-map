"""``kortravelmap.providers.kor_travel_concierge``.

kor-travel-concierge YouTube 후보 → FeatureBundle.

``kor-travel-concierge``는 YouTube 여행 콘텐츠에서 장소 후보와 근거를 추출하고,
``kor-travel-map``은 문서화된 ``/api/v1/features/*`` JSON을 pull해(ADR-053,
ADR-050 #1
경로 중립화) 최종 ``Feature``/``SourceRecord``/``SourceLink``로 소유한다. 이 모듈은
REST client wrapper가 아니라, 이미 받은 export item dict를 DTO로 바꾸는 순수 변환
함수다. ``operation=upsert``는 ``FeatureBundle`` 적재로, ``reject``/``tombstone``은
``kor_travel_concierge_inactive_entity_ids``로 분리해 대응 feature inactive 전환에 쓴다
(ADR-050 #4, T-217b — MOIS Step C 동형).

ADR 참조: ADR-006 / ADR-009 / ADR-019 / ADR-024 / ADR-045 / ADR-050 / ADR-053 / ADR-057
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from pydantic import ValidationError as PydanticValidationError

from kortravelmap.category import PlaceCategoryCode, mapbox_maki_icon_or_none
from kortravelmap.core.address import (
    extract_sido_code,
    extract_sigungu_code,
    normalize_korean_text,
)
from kortravelmap.core.exceptions import ValidationError as DomainValidationError
from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    AdminClaimKind,
    AdminEvidence,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    RawDataRef,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.geocoding import (
    ObservedReverseGeocoder,
    ReverseGeocoder,
    cached_reverse_geocoder,
)

__all__ = [
    "DATASET_KEY_YOUTUBE_PLACE_CANDIDATES",
    "KOR_TRAVEL_CONCIERGE_MARKER_COLOR",
    "KOR_TRAVEL_CONCIERGE_PROVIDER_NAME",
    "KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE",
    "KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK",
    "KorTravelConciergeFeatureItem",
    "KorTravelConciergeQuarantine",
    "kor_travel_concierge_inactive_entity_ids",
    "kor_travel_concierge_items_to_bundles",
    "kor_travel_concierge_latest_items",
    "kor_travel_concierge_upsert_count",
]


KorTravelConciergeFeatureItem = Mapping[str, Any]
"""kor-travel-concierge ``/api/v1/features/*`` item JSON shape."""


class KorTravelConciergeItemValidationError(DomainValidationError):
    """upsert item 하나가 Map의 필수 적재 계약을 충족하지 못했다."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class KorTravelConciergeQuarantine:
    """적재하지 못한 upsert item의 안정 식별자와 sanitized 사유."""

    item_key: str
    reason_code: str
    message: str

KOR_TRAVEL_CONCIERGE_PROVIDER_NAME: Final[str] = "kor-travel-concierge-youtube"
"""YouTube 장소 후보 provider canonical name."""

DATASET_KEY_YOUTUBE_PLACE_CANDIDATES: Final[str] = "youtube_place_candidates"
"""kor-travel-concierge export dataset key."""

KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE: Final[str] = "extracted_place_candidate"
"""export 계약의 source_entity_type 기본값 — inactive 전환 매칭에도 사용."""

_SOURCE_ENTITY_TYPE: Final[str] = KOR_TRAVEL_CONCIERGE_SOURCE_ENTITY_TYPE
_PLACE_KIND: Final[str] = "youtube_place_candidate"
KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK: Final[str] = PlaceCategoryCode.TOURISM.value
"""kor-travel-concierge category suggestion이 없거나 잘못된 경우의 안전한 fallback."""

_FEATURE_ID_IDENTITY_CATEGORY: Final[str] = KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK
"""ADR-057 — feature_id 파생 전용 **고정** category. 실제 표시 category(place의
``category_code_suggestion``)는 enrich 전 None→후 8자리로 바뀌므로, 식별자에 넣으면
같은 후보가 재export마다 새 feature로 갈린다. 식별자에는 이 불변값만 쓰고 표시
category는 ``Feature.category``(가변)에 싣는다."""

KOR_TRAVEL_CONCIERGE_MARKER_COLOR: Final[str] = "P-13"
_DEFAULT_MARKER_ICON: Final[str] = "marker"

_OPERATION_UPSERT: Final[str] = "upsert"
_INACTIVATE_OPERATIONS: Final[frozenset[str]] = frozenset({"reject", "tombstone"})
"""ADR-050 #4 — feature를 inactive로 전환하는 operation. 이 둘만 비활성화하고 그 외
unknown operation은 적재도 비활성화도 하지 않는다(C-05 — live feature 파괴적 오분류 방지)."""

logger = logging.getLogger(__name__)


async def kor_travel_concierge_items_to_bundles(
    items: Iterable[KorTravelConciergeFeatureItem],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    quarantine: list[KorTravelConciergeQuarantine] | None = None,
) -> list[FeatureBundle]:
    """kor-travel-concierge feature export items → ``list[FeatureBundle]``.

    ``quarantine``을 주면 구성에 실패한 item을 예외와 함께 담고 나머지를 계속 변환한다
    (T-VN-H28B 건별 격리). 주지 않으면 종전대로 예외를 그대로 올린다 — 호출자가 명시적으로
    격리를 선택해야 손실을 감춘 채 진행하지 않는다.

    ``operation``이 ``upsert``가 아닌 ``reject``/``tombstone`` item은 적재형
    ``FeatureBundle``로 표현하지 않는다 — 같은 items에서
    ``kor_travel_concierge_inactive_entity_ids``로 추출해 대응 feature를 inactive로
    전환한다(ADR-050 #4, T-217b).
    """
    geocoder = (
        cached_reverse_geocoder(reverse_geocoder)
        if reverse_geocoder is not None
        else None
    )
    bundles: list[FeatureBundle] = []
    for item in items:
        if _operation(item) != _OPERATION_UPSERT:
            continue
        try:
            bundle = await _item_to_bundle(
                item,
                fetched_at=fetched_at,
                reverse_geocoder=geocoder,
            )
        except (PydanticValidationError, DomainValidationError) as exc:
            # T-VN-H28B: 건별 격리. 이전에는 item 1건의 구성 실패가 batch 전체를 죽였다
            # (concierge export는 1회 1,477건 전량 재생이라 손실이 전부였다).
            if quarantine is not None:
                quarantine.append(_quarantine_entry(item, exc))
                continue
            raise
        bundles.append(bundle)
    return bundles


def _quarantine_item_key(item: KorTravelConciergeFeatureItem) -> str:
    source_record = _mapping(item.get("source_record"))
    for value in (
        item.get("export_id"),
        item.get("candidate_id"),
        source_record.get("source_entity_id"),
    ):
        text = str(value).strip() if value is not None else ""
        if text:
            return text[:160]
    digest = make_payload_hash(_plain_json_dict(item)).removeprefix("sha256:")
    return f"payload:{digest[:16]}"


def _quarantine_entry(
    item: KorTravelConciergeFeatureItem,
    exc: PydanticValidationError | DomainValidationError,
) -> KorTravelConciergeQuarantine:
    if isinstance(exc, KorTravelConciergeItemValidationError):
        reason_code = exc.reason_code
        message = str(exc)
    elif isinstance(exc, PydanticValidationError):
        reason_code = "dto_validation"
        fields = [
            ".".join(str(part) for part in error.get("loc", ()))
            for error in exc.errors(include_url=False, include_input=False)[:5]
        ]
        message = "DTO validation failed"
        if fields:
            message = f"{message}: {', '.join(fields)}"
    else:
        reason_code = "domain_validation"
        message = f"{type(exc).__name__}: domain validation failed"
    return KorTravelConciergeQuarantine(
        item_key=_quarantine_item_key(item),
        reason_code=reason_code,
        message=message[:300],
    )


async def _item_to_bundle(
    item: KorTravelConciergeFeatureItem,
    *,
    fetched_at: datetime,
    reverse_geocoder: ObservedReverseGeocoder | None,
) -> FeatureBundle:
    place = _mapping(item.get("place"))
    source_record_payload = _mapping(item.get("source_record"))
    name = normalize_korean_text(_text(place, "name"))
    source_entity_id = _source_entity_id(item, source_record_payload)
    if not name:
        raise KorTravelConciergeItemValidationError(
            "missing_place_name",
            "upsert item의 place.name이 비어 있습니다.",
        )
    if not source_entity_id:
        raise KorTravelConciergeItemValidationError(
            "missing_source_entity_id",
            "upsert item의 source entity 식별자가 비어 있습니다.",
        )

    # ADR-053/057 (C-04) — identity triple(provider/dataset_key/source_entity_type)은 이
    # provider에서 **고정**이다(inactive 전환도 같은 고정값으로 매칭). payload 값을 그대로
    # 쓰면 upsert 저장 키와 inactivate 매칭 키가 갈릴 수 있으므로(silent miss), 상수로
    # 강제해 upsert 저장 == inactivate 매칭 == feature_id source_type을 보장한다. payload가
    # 다르면 계약 drift이므로 경고만 남긴다(raw 값은 raw_data에 보존된다).
    _warn_on_identity_drift(source_record_payload)
    provider = normalize_provider_name(KOR_TRAVEL_CONCIERGE_PROVIDER_NAME)
    dataset_key = DATASET_KEY_YOUTUBE_PLACE_CANDIDATES
    source_entity_type = _SOURCE_ENTITY_TYPE
    category = _category(place)
    coord = _coordinate(place)

    address_payload = _mapping(place.get("address"))
    geo: Address | None = None
    obs_sigungu_names: tuple[str, ...] = ()
    if coord is not None and reverse_geocoder is not None:
        observation = await reverse_geocoder.observe(coord)
        geo = observation.address
        obs_sigungu_names = observation.sigungu_names
    address = _address(address_payload, geo=geo)

    raw_data = _plain_json_dict(item)
    payload_hash = (
        _text(source_record_payload, "raw_payload_hash") or make_payload_hash(raw_data)
    )
    source_record_key = make_source_record_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    # ADR-057 — feature_id는 **안정 식별자(candidate.id=source_entity_id)**에만 고정한다.
    # producer는 admin 코드를 항상 None으로 보내고(bjd는 optional reverse geocoder에만
    # 의존) category_code_suggestion도 enrich 전 None이라, bjd/category를 식별자에 넣으면
    # 같은 후보가 재export마다 새 feature로 갈린다(중복·dedup 단절). 따라서 파생에는
    # bjd_code=None + 고정 ``_FEATURE_ID_IDENTITY_CATEGORY`` + provider/dataset **상수**
    # source_type을 쓰고, 실제 bjd/category는 Address/Feature 가변 속성으로 실어 재import
    # 시 in-place 갱신한다.
    feature_id = make_feature_id(
        bjd_code=None,
        kind=FeatureKind.PLACE.value,
        category=_FEATURE_ID_IDENTITY_CATEGORY,
        source_type=f"{KOR_TRAVEL_CONCIERGE_PROVIDER_NAME}:{DATASET_KEY_YOUTUBE_PLACE_CANDIDATES}",
        source_natural_key=source_entity_id,
    )

    youtube = _mapping(item.get("youtube"))
    evidence = _mapping(item.get("evidence"))
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coord,
        address=address,
        category=category,
        marker_icon=mapbox_maki_icon_or_none(category) or _DEFAULT_MARKER_ICON,
        marker_color=KOR_TRAVEL_CONCIERGE_MARKER_COLOR,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=_PLACE_KIND,
            facility_info=_facility_info(place, youtube, evidence),
            payload={
                "kor_travel_concierge": {
                    "export_id": item.get("export_id"),
                    "operation": _operation(item),
                    "youtube": _plain_json_value(youtube),
                    "evidence": _plain_json_value(evidence),
                    "updated_at": item.get("updated_at"),
                }
            },
        ),
        raw_refs=[
            RawDataRef(
                provider=provider,
                dataset_key=dataset_key,
                source_entity_id=source_entity_id,
                source_role=SourceRole.PRIMARY,
                fetched_at=fetched_at,
                payload_hash=payload_hash,
                extra={"export_id": item.get("export_id")},
            )
        ],
    )
    source_record = SourceRecord(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        source_version=None,
        raw_name=name,
        raw_address=address.display() or None,
        raw_longitude=coord.lon if coord is not None else None,
        raw_latitude=coord.lat if coord is not None else None,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="kor_travel_concierge_export",
        confidence=_confidence(evidence.get("confidence_score")),
        is_primary_source=True,
    )
    return FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
        admin_evidence=_admin_evidence(
            address_payload,
            geo=geo,
            obs_sigungu_names=obs_sigungu_names,
            reverse_attempted=coord is not None and reverse_geocoder is not None,
        ),
    )


def kor_travel_concierge_latest_items(
    items: Iterable[KorTravelConciergeFeatureItem],
) -> list[KorTravelConciergeFeatureItem]:
    """후보(``source_entity_id``)별 **마지막 관측 item**만 남긴다 — ledger 압축 미러.

    producer export ledger는 후보당 1행이지만, ``changes`` 페이지네이션 **도중**
    검수 전이(되돌리기 등)가 일어나면 producer가 그 행을 새 sequence로 전진시켜
    같은 후보가 한 스트림에 구 operation(예: reject)과 신 operation(예: upsert)
    으로 두 번 관측될 수 있다. 스트림 순서 = sequence 순서이므로 **마지막 관측이
    ledger 최신 상태**다. asset은 적재(upsert)와 inactive 전환을 operation 종류
    순서로 나눠 처리하므로, 압축 없이는 같은 run의 구 reject가 신 upsert를 덮어
    다음 run까지 잘못 inactive로 남는다. entity id를 뽑을 수 없는 item은 그대로
    통과시킨다(후속 단계가 각자 skip).
    """
    latest: dict[str, KorTravelConciergeFeatureItem] = {}
    passthrough: list[KorTravelConciergeFeatureItem] = []
    for item in items:
        entity_id = _source_entity_id(item, _mapping(item.get("source_record")))
        if entity_id is None:
            passthrough.append(item)
            continue
        # 재관측 시 뒤로 이동시켜 최종 관측 순서를 유지한다.
        latest.pop(entity_id, None)
        latest[entity_id] = item
    return [*passthrough, *latest.values()]


def kor_travel_concierge_upsert_count(
    items: Iterable[KorTravelConciergeFeatureItem],
) -> int:
    """현재 stream에서 적재 대상으로 분류되는 upsert item 수."""
    return sum(1 for item in items if _operation(item) == _OPERATION_UPSERT)


def kor_travel_concierge_inactive_entity_ids(
    items: Iterable[KorTravelConciergeFeatureItem],
) -> set[str]:
    """``reject``/``tombstone`` item의 ``source_entity_id`` 집합 (T-217b, ADR-050 #4).

    kor-travel-concierge 검수에서 철회(reject)되거나 폐기(tombstone)된 후보에 대응하는
    기적재 feature를 ``infra.inactivate_features_by_source_entity_ids``로
    ``status='inactive'`` 전환할 때 쓴다(MOIS Step C 동형, ADR-017 — place 무기한
    유지·status만 전환). export 계약(kor-travel-concierge plan §7)상 provider/dataset/
    source_entity_type은 단일 고정값이므로 entity id 집합만 모은다. id를 뽑을 수
    없는 item은 무시한다(빈 집합이면 호출측 no-op).

    D-12(2026-06-10): inactive 전환된 feature는 batch/단건 read의 ``found``에
    status와 함께 남는다 — ``missing``(미존재)과 "철회/폐업됨"을 구분한다.
    """
    entity_ids: set[str] = set()
    for item in items:
        operation = _operation(item)
        if operation == _OPERATION_UPSERT:
            continue
        if operation not in _INACTIVATE_OPERATIONS:
            # C-05 — 알 수 없는 operation은 적재도 비활성화도 하지 않는다(live feature
            # 파괴적 오분류 방지). 계약상 reject/tombstone만 inactivate 대상이다.
            logger.warning(
                "kor-travel-concierge unknown operation %r — inactivate 대상에서 제외",
                operation,
            )
            continue
        source_record_payload = _mapping(item.get("source_record"))
        entity_id = _source_entity_id(item, source_record_payload)
        if entity_id is not None:
            entity_ids.add(entity_id)
    return entity_ids


def _operation(item: Mapping[str, Any]) -> str:
    return str(item.get("operation") or _OPERATION_UPSERT).strip().lower()


def _warn_on_identity_drift(source_record_payload: Mapping[str, Any]) -> None:
    """payload의 identity triple이 고정 상수와 다르면 계약 drift로 경고한다(C-04).

    값 자체는 상수를 써서 키 일관성을 보장하되, concierge가 provider/dataset_key/
    source_entity_type을 바꾸면 조용히 넘어가지 않도록 관측 가능하게 만든다.
    """
    for key, expected in (
        ("provider", KOR_TRAVEL_CONCIERGE_PROVIDER_NAME),
        ("dataset_key", DATASET_KEY_YOUTUBE_PLACE_CANDIDATES),
        ("source_entity_type", _SOURCE_ENTITY_TYPE),
    ):
        actual = _text(source_record_payload, key)
        if actual is not None and actual != expected:
            logger.warning(
                "kor-travel-concierge identity drift: source_record.%s=%r != 고정 상수 %r",
                key,
                actual,
                expected,
            )


def _mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_entity_id(
    item: Mapping[str, Any], source_record_payload: Mapping[str, Any]
) -> str | None:
    for value in (
        source_record_payload.get("source_entity_id"),
        item.get("candidate_id"),
        item.get("export_id"),
    ):
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _category(place: Mapping[str, Any]) -> str:
    value = _text(place, "category_code_suggestion")
    if value is not None and len(value) == 8 and value.isdigit():
        return value
    return KOR_TRAVEL_CONCIERGE_YOUTUBE_CATEGORY_FALLBACK


def _coordinate(place: Mapping[str, Any]) -> Coordinate | None:
    lon = _decimal_or_none(place.get("longitude"))
    lat = _decimal_or_none(place.get("latitude"))
    if lon is None or lat is None:
        return None
    return Coordinate(lon=lon, lat=lat)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _address(payload: Mapping[str, Any], *, geo: Address | None) -> Address:
    """payload/geo를 하나의 ``Address``로 병합한다.

    T-VN-H28B: ``bjd_code``가 있으면 시군구·시도를 **bjd에서만 유도**한다. 이전에는
    payload ``sigungu_code``를 우선했는데, payload에 ``sigungu_code``만 있고
    ``legal_dong_code``가 없으면 ``bjd_code``는 geo에서 오고 ``sigungu_code``는 payload에서
    와서 서로 다른 지역을 가리킬 수 있었다. 그때 ``Address._check_code_consistency``가
    ``ValidationError``를 던지는데 batch 변환에 건별 격리가 없어 **1건이 batch 전체를
    죽였다**. bjd에서만 유도하면 불일치가 구조적으로 불가능하다.

    payload가 주장한 코드는 버리지 않는다 — ``_admin_evidence``가 교차검증용으로 보존한다.
    """
    bjd_code = _ten_digit_code(_text(payload, "legal_dong_code"))
    if bjd_code is None and geo is not None:
        bjd_code = geo.bjd_code
    if bjd_code is not None:
        sigungu_code = extract_sigungu_code(bjd_code)
        sido_code = extract_sido_code(bjd_code)
    else:
        sigungu_code = _five_digit_code(_text(payload, "sigungu_code")) or (
            geo.sigungu_code if geo is not None else None
        )
        sido_code = _two_digit_code(_text(payload, "sido_code")) or (
            geo.sido_code if geo is not None else None
        )
    return Address(
        road=normalize_korean_text(_text(payload, "road_address")),
        legal=normalize_korean_text(_text(payload, "official_address")),
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=sigungu_code,
        sido_code=sido_code,
        road_name_code=geo.road_name_code if geo is not None else None,
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )


def _admin_evidence(
    payload: Mapping[str, Any],
    *,
    geo: Address | None,
    obs_sigungu_names: tuple[str, ...],
    reverse_attempted: bool,
) -> AdminEvidence:
    """행정구역 판정의 두 축을 병합 전에 보존한다 (T-VN-H28B).

    ``obs_code``는 좌표 reverse 결과의 법정동코드만, ``claim_code``는 payload가 스스로
    선언한 법정동 계열 코드만 담는다. 둘 다 있을 때만 코드 대 코드 교차검증이 성립한다.
    """
    claim_code = _ten_digit_code(_text(payload, "legal_dong_code"))
    claim_kind: AdminClaimKind | None = "bjd" if claim_code else None
    if claim_code is None:
        claim_code = _five_digit_code(_text(payload, "sigungu_code"))
        claim_kind = "sigungu" if claim_code else None
    if claim_code is None:
        claim_code = _two_digit_code(_text(payload, "sido_code"))
        claim_kind = "sido" if claim_code else None
    return AdminEvidence(
        obs_code=geo.bjd_code if geo is not None else None,
        obs_sigungu_names=obs_sigungu_names,
        reverse_attempted=reverse_attempted,
        claim_code=claim_code,
        claim_kind=claim_kind,
        # 독립 축 — provider **원천** 문자열만. geo 유래 값을 넣으면 자기 자신과 비교하게 된다.
        claim_text=normalize_korean_text(_text(payload, "road_address"))
        or normalize_korean_text(_text(payload, "official_address")),
    )


def _ten_digit_code(value: str | None) -> str | None:
    return value if value is not None and len(value) == 10 and value.isdigit() else None


def _five_digit_code(value: str | None) -> str | None:
    return value if value is not None and len(value) == 5 and value.isdigit() else None


def _two_digit_code(value: str | None) -> str | None:
    return value if value is not None and len(value) == 2 and value.isdigit() else None


def _facility_info(
    place: Mapping[str, Any],
    youtube: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    values = {
        "description": _text(place, "description"),
        "gemini_enriched_description": _text(place, "gemini_enriched_description"),
        "category_label": _text(place, "category_label"),
        "youtube_video_id": _text(youtube, "video_id"),
        "youtube_video_url": _text(youtube, "video_url"),
        "youtube_video_title": _text(youtube, "video_title"),
        "youtube_channel_id": _text(youtube, "channel_id"),
        "youtube_channel_title": _text(youtube, "channel_title"),
        "youtube_playlist_id": _text(youtube, "playlist_id"),
        "youtube_playlist_title": _text(youtube, "playlist_title"),
        # 2026-06-25 producer provenance 확장(concierge 8720dda) — 이 영상이 어떤 수집
        # 대상(keyword 검색어/channel/playlist)에서 나왔는지의 평면 미러. nested
        # ``detail.payload.kor_travel_concierge.youtube``에도 그대로 실리지만, 출처 UX는
        # facility_info 평면 key를 우선 읽는다(§4).
        "youtube_source_type": _text(youtube, "source_type"),
        "youtube_source_value": _text(youtube, "source_value"),
        "youtube_source_title": _text(youtube, "source_title"),
        "youtube_source_search_query": _text(youtube, "source_search_query"),
        "youtube_corrected_search_query": _text(youtube, "corrected_search_query"),
        "timestamp_start": _text(evidence, "timestamp_start"),
        "timestamp_end": _text(evidence, "timestamp_end"),
        "transcript_excerpt": _text(evidence, "transcript_excerpt"),
        "gemini_url_evidence": _text(evidence, "gemini_url_evidence"),
        # kor-travel-concierge feature export 소비자가 detail.facility_info만 읽고도
        # confidence까지 얻도록 0~100 정규화 점수를 함께 노출한다.
        "confidence_score": _confidence(evidence.get("confidence_score")),
    }
    return {key: value for key, value in values.items() if value is not None}


def _confidence(value: Any) -> int:
    if value is None:
        return 80
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 80
    if 0 <= score <= 1:
        score *= 100
    return max(0, min(100, round(score)))


def _plain_json_dict(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): _plain_json_value(item)
        for key, item in value.items()
        if isinstance(key, str)
    }


def _plain_json_value(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return _plain_json_dict(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_plain_json_value(item) for item in value]
    return str(value)

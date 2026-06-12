"""``kortravelmap.enrichment`` — Place 전화번호 보강 (Sprint 4b 백그라운드 시작).

MOIS PROMOTED place 중 **전화번호 없는** feature를 후보로 발굴하고(`find_place_phone_
candidates`), 외부 lookup(kakao-local / naver-search / google-places) 결과 전화번호를
feature에 보강한다(`apply_place_phone_enrichment` — `detail.phones` 갱신 +
``source_links(role='enrichment')`` 이력). SPRINT-4 §2.7.

**외부 API 호출은 본 lib가 하지 않는다**(ADR-006) — 호출자(백그라운드 워커)가
kakao/naver/google를 호출하고 그 결과 전화번호를 본 함수에 주입한다. 본 모듈은
후보 발굴 + 정규화·dedup·이력 적재만 담당한다.

ADR 참조
--------
- ADR-002 — async-only, commit은 호출자/감싼 transaction
- ADR-006 — provider/외부 API 미import (결과 주입)
- ADR-009 — source_record_key/payload_hash 결정적 생성
- ADR-016 — source_role='enrichment'(보조 source, is_primary_source=False)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from kortravelmap.core.address import normalize_phone_number
from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import SourceLink, SourceRecord, SourceRole
from kortravelmap.infra.feature_repo import (
    find_place_features_without_phone as _find_no_phone,
)
from kortravelmap.infra.feature_repo import (
    get_feature_row,
    set_feature_phones,
    upsert_source_link,
    upsert_source_record,
)
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK as MOIS_DATASET_KEY_BULK,
)
from kortravelmap.providers.mois import (
    PROVIDER_NAME as MOIS_PROVIDER_NAME,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ENRICHMENT_DATASET_KEY",
    "ENRICHMENT_ENTITY_TYPE",
    "MAX_PHONES",
    "PhoneEnrichmentCandidate",
    "PhoneEnrichmentResult",
    "find_place_phone_candidates",
    "apply_place_phone_enrichment",
]

ENRICHMENT_DATASET_KEY: Final[str] = "place_phone_enrichment"
ENRICHMENT_ENTITY_TYPE: Final[str] = "place_phone"
MAX_PHONES: Final[int] = 3  # PlaceDetail.phones max_length
_DEFAULT_CONFIDENCE: Final[int] = 80
# MOIS license place entity type (providers.mois._LICENSE_ENTITY_TYPE).
_MOIS_LICENSE_ENTITY_TYPE: Final[str] = "license_place"


@dataclass(frozen=True)
class PhoneEnrichmentCandidate:
    """전화번호 없는 place 후보 — 외부 lookup 입력."""

    feature_id: str
    name: str
    source_entity_id: str
    address: dict[str, Any]


@dataclass(frozen=True)
class PhoneEnrichmentResult:
    """보강 결과. ``applied=False``면 ``reason``에 사유."""

    feature_id: str
    applied: bool
    phone: str | None = None
    reason: str | None = None


async def find_place_phone_candidates(
    session: AsyncSession,
    *,
    provider: str = MOIS_PROVIDER_NAME,
    dataset_key: str = MOIS_DATASET_KEY_BULK,
    source_entity_type: str = _MOIS_LICENSE_ENTITY_TYPE,
    limit: int = 100,
) -> list[PhoneEnrichmentCandidate]:
    """전화번호 없는 place feature 후보 list (기본 MOIS bulk).

    외부 phone lookup은 호출자가 후보별로 수행(ADR-006). 반환 후보의
    ``feature_id``/``source_entity_id``를 `apply_place_phone_enrichment`에 그대로 전달.
    """
    rows = await _find_no_phone(
        session,
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        limit=limit,
    )
    return [
        PhoneEnrichmentCandidate(
            feature_id=r["feature_id"],
            name=r["name"],
            source_entity_id=r["source_entity_id"],
            address=r["address"] if isinstance(r.get("address"), dict) else {},
        )
        for r in rows
    ]


async def apply_place_phone_enrichment(
    session: AsyncSession,
    *,
    feature_id: str,
    phone: str,
    enrichment_provider: str,
    source_entity_id: str,
    fetched_at: datetime,
    confidence: int = _DEFAULT_CONFIDENCE,
) -> PhoneEnrichmentResult:
    """외부 lookup 전화번호를 feature에 보강 (정규화 + dedup + enrichment 이력).

    1. 전화번호 정규화 — 무효면 ``applied=False reason='invalid_phone'``.
    2. feature 조회 — 없으면 ``feature_not_found``. 이미 같은 번호면 ``duplicate``.
       ``phones``가 이미 ``MAX_PHONES``개면 ``max_phones``.
    3. ``detail.phones``에 append + ``source_records``(enrichment) +
       ``source_links(role='enrichment', is_primary_source=False)`` upsert.

    ``enrichment_provider``는 외부 source 이름(예: ``kakao-local-api``). commit은
    호출자 책임.
    """
    normalized = normalize_phone_number(phone)
    # normalize_phone_number는 숫자 부족 시 원본을 그대로 돌려준다(provenance 보존).
    # enrichment는 품질을 위해 한국 전화번호 최소 자릿수(9)를 강제한다.
    if normalized is None or sum(c.isdigit() for c in normalized) < 9:
        return PhoneEnrichmentResult(
            feature_id=feature_id, applied=False, reason="invalid_phone"
        )

    row = await get_feature_row(session, feature_id)
    if row is None:
        return PhoneEnrichmentResult(
            feature_id=feature_id, applied=False, reason="feature_not_found"
        )
    detail = row.get("detail") or {}
    phones: list[str] = list(detail.get("phones") or [])
    if normalized in phones:
        return PhoneEnrichmentResult(
            feature_id=feature_id, applied=False, phone=normalized, reason="duplicate"
        )
    if len(phones) >= MAX_PHONES:
        return PhoneEnrichmentResult(
            feature_id=feature_id, applied=False, phone=normalized, reason="max_phones"
        )

    phones.append(normalized)
    await set_feature_phones(session, feature_id, phones)

    provider_norm = normalize_provider_name(enrichment_provider)
    raw_data: dict[str, Any] = {"phone": normalized, "source": enrichment_provider}
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=provider_norm,
        dataset_key=ENRICHMENT_DATASET_KEY,
        source_entity_type=ENRICHMENT_ENTITY_TYPE,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    await upsert_source_record(
        session,
        SourceRecord(
            provider=provider_norm,
            dataset_key=ENRICHMENT_DATASET_KEY,
            source_entity_type=ENRICHMENT_ENTITY_TYPE,
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
            raw_data=raw_data,
            fetched_at=fetched_at,
            source_record_key=source_record_key,
        ),
    )
    await upsert_source_link(
        session,
        SourceLink(
            feature_id=feature_id,
            source_record_key=source_record_key,
            source_role=SourceRole.ENRICHMENT,
            match_method="phone_enrichment",
            confidence=confidence,
            is_primary_source=False,
        ),
    )
    return PhoneEnrichmentResult(
        feature_id=feature_id, applied=True, phone=normalized
    )

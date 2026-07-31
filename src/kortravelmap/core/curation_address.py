"""큐레이션 Feature 후보용 구조화 한국 주소 matcher.

자유 문자열을 JSON 직렬화나 SQL ``LIKE``에 넘기지 않는다. 사람이 읽는 주소 field만
NFKC 정규화한 뒤 literal token과 행정 hierarchy로 비교한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from kortravelmap.core.address import normalize_korean_text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Any

__all__ = [
    "CURATION_ADDRESS_RESOLVER_VERSION",
    "AddressHint",
    "address_hint_matches",
    "parse_address_hint",
]

CURATION_ADDRESS_RESOLVER_VERSION: Final = "structured-address-v1-2026-07-31"

_SIDO_ALIASES: Final[dict[str, str]] = {
    "서울": "서울특별시",
    "서울시": "서울특별시",
    "서울특별시": "서울특별시",
    "부산": "부산광역시",
    "부산시": "부산광역시",
    "부산광역시": "부산광역시",
    "대구": "대구광역시",
    "대구시": "대구광역시",
    "대구광역시": "대구광역시",
    "인천": "인천광역시",
    "인천시": "인천광역시",
    "인천광역시": "인천광역시",
    "광주": "광주광역시",
    "광주시": "광주광역시",
    "광주광역시": "광주광역시",
    "대전": "대전광역시",
    "대전시": "대전광역시",
    "대전광역시": "대전광역시",
    "울산": "울산광역시",
    "울산시": "울산광역시",
    "울산광역시": "울산광역시",
    "세종": "세종특별자치시",
    "세종시": "세종특별자치시",
    "세종특별자치시": "세종특별자치시",
    "경기": "경기도",
    "경기도": "경기도",
    "강원": "강원특별자치도",
    "강원도": "강원특별자치도",
    "강원특별자치도": "강원특별자치도",
    "충북": "충청북도",
    "충청북도": "충청북도",
    "충남": "충청남도",
    "충청남도": "충청남도",
    "전북": "전북특별자치도",
    "전라북도": "전북특별자치도",
    "전북특별자치도": "전북특별자치도",
    "전남": "전라남도",
    "전라남도": "전라남도",
    # 2026 VWorld 선반영 명칭을 현재 Feature 정본 명칭으로 canonicalize한다.
    "전남광주통합특별시": "전라남도",
    "경북": "경상북도",
    "경상북도": "경상북도",
    "경남": "경상남도",
    "경상남도": "경상남도",
    "제주": "제주특별자치도",
    "제주도": "제주특별자치도",
    "제주특별자치도": "제주특별자치도",
}

_SIGUNGU_ALIASES: Final[dict[tuple[str, str], str]] = {
    ("인천광역시", "영종구"): "중구",
    ("인천광역시", "제물포구"): "중구",
    ("경기도", "화성시 만세구"): "화성시",
}

_LOCALITY_SUFFIXES: Final = ("읍", "면", "동", "가", "리")
_SIGUNGU_SUFFIXES: Final = ("시", "군", "구")
_AUTHORITATIVE_TEXT_FIELDS: Final = ("road", "legal", "admin")


@dataclass(frozen=True)
class AddressHint:
    """정규화한 행정주소 hierarchy와 나머지 literal token."""

    normalized: str
    sido: str | None
    sigungu: str | None
    locality: tuple[str, ...]
    detail: tuple[str, ...]


def _tokens(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    normalized = normalize_korean_text(value)
    if normalized is None:
        return ()
    return tuple(token.casefold() for token in normalized.split(" "))


def _canonical_sido(token: str) -> str | None:
    return _SIDO_ALIASES.get(token)


def _canonical_sigungu(sido: str | None, value: str) -> str:
    return _SIGUNGU_ALIASES.get((sido or "", value), value)


def _consume_sigungu(
    tokens: Sequence[str],
    offset: int,
    *,
    sido: str | None,
) -> tuple[str | None, int]:
    if offset >= len(tokens) or not tokens[offset].endswith(_SIGUNGU_SUFFIXES):
        return None, offset
    parts = [tokens[offset]]
    offset += 1
    if parts[0].endswith("시") and offset < len(tokens) and tokens[offset].endswith("구"):
        parts.append(tokens[offset])
        offset += 1
    return _canonical_sigungu(sido, " ".join(parts)), offset


def parse_address_hint(value: str | None) -> AddressHint | None:
    """자유 문자열을 안전한 literal hierarchy로 파싱한다."""

    normalized = normalize_korean_text(value)
    if normalized is None:
        return None
    tokens = tuple(token.casefold() for token in normalized.split(" "))
    offset = 0
    sido = _canonical_sido(tokens[0]) if tokens else None
    if sido is not None:
        offset += 1
    sigungu, offset = _consume_sigungu(tokens, offset, sido=sido)
    locality: list[str] = []
    while offset < len(tokens) and tokens[offset].endswith(_LOCALITY_SUFFIXES):
        locality.append(tokens[offset])
        offset += 1
    return AddressHint(
        normalized=normalized,
        sido=sido,
        sigungu=sigungu,
        locality=tuple(locality),
        detail=tokens[offset:],
    )


def _field_hint(tokens: Sequence[str]) -> AddressHint | None:
    if not tokens:
        return None
    return parse_address_hint(" ".join(tokens))


def _ordered_contains(haystack: Sequence[str], needles: Sequence[str]) -> bool:
    if not needles:
        return True
    offset = 0
    for token in haystack:
        if token == needles[offset]:
            offset += 1
            if offset == len(needles):
                return True
    return False


def address_hint_matches(address: Mapping[str, Any] | None, hint: str | None) -> bool:
    """구조화 주소 field가 hint의 literal hierarchy를 충족하는지 반환한다.

    서로 다른 field의 token을 이어 붙이지 않는다. 같은 hierarchy level의 field가
    서로 충돌하면 어떤 한 field가 우연히 맞더라도 fail-close한다.
    """

    expected = parse_address_hint(hint)
    if expected is None or not address:
        return False

    field_tokens = tuple(
        tokens
        for field in _AUTHORITATIVE_TEXT_FIELDS
        if (tokens := _tokens(address.get(field)))
    )
    field_hints = tuple(
        parsed for tokens in field_tokens if (parsed := _field_hint(tokens)) is not None
    )

    sido_values = {
        value
        for value in (
            _canonical_sido(token)
            for token in (
                *_tokens(address.get("sido_name")),
                *(parsed.sido or "" for parsed in field_hints),
            )
        )
        if value is not None
    }
    if expected.sido is not None and sido_values != {expected.sido}:
        return False

    sigungu_values = {
        value
        for value in (
            _canonical_sigungu(expected.sido, " ".join(_tokens(address.get("sigungu_name")))),
            *(parsed.sigungu or "" for parsed in field_hints),
        )
        if value
    }
    if expected.sigungu is not None and sigungu_values != {expected.sigungu}:
        return False

    literal_tail = (*expected.locality, *expected.detail)
    if not literal_tail:
        return expected.sido is not None or expected.sigungu is not None

    return any(_ordered_contains(tokens, literal_tail) for tokens in field_tokens)

"""큐레이션 주소 후보 matcher의 literal hierarchy 계약."""

from __future__ import annotations

import unicodedata

import pytest

from kortravelmap.core.curation_address import (
    CURATION_ADDRESS_RESOLVER_VERSION,
    address_hint_matches,
    parse_address_hint,
)

pytestmark = pytest.mark.unit


def test_normalizes_unicode_and_preserves_literal_token_boundary() -> None:
    address = {
        "sido_name": "울산광역시",
        "sigungu_name": "울주군",
        "admin": "울산광역시 울주군 서생면",
    }
    assert address_hint_matches(
        address,
        unicodedata.normalize("NFD", "울산광역시 울주군 서생면"),
    )
    assert not address_hint_matches(
        {**address, "admin": "울산광역시 울주군 온산읍", "road": "서생면로 1"},
        "울산광역시 울주군 서생면",
    )
    assert not address_hint_matches(address, "%")
    assert not address_hint_matches(address, "_")


def test_requires_one_authoritative_field_to_hold_the_literal_tail() -> None:
    assert not address_hint_matches(
        {
            "sido_name": "울산광역시",
            "sigungu_name": "울주군",
            "legal": "울산광역시 울주군 서생면",
            "admin": "대송리",
        },
        "울산광역시 울주군 서생면 대송리",
    )
    assert address_hint_matches(
        {
            "sido_name": "울산광역시",
            "sigungu_name": "울주군",
            "legal": "울산광역시 울주군 서생면 대송리 28-6",
        },
        "울산광역시 울주군 서생면 대송리",
    )


def test_fails_closed_when_authoritative_hierarchy_conflicts() -> None:
    assert not address_hint_matches(
        {
            "sido_name": "울산광역시",
            "sigungu_name": "울주군",
            "legal": "울산광역시 울주군 서생면 대송리",
            "admin": "부산광역시 기장군 기장읍 대변리",
        },
        "울산광역시 울주군 서생면",
    )


@pytest.mark.parametrize(
    ("old_name", "new_name"),
    [
        ("전라남도 신안군 흑산면 가거도리", "전남광주통합특별시 신안군 흑산면 가거도리"),
        ("인천광역시 중구 운서동", "인천광역시 영종구 운서동"),
        ("경기도 화성시 서신면", "경기도 화성시 만세구 서신면"),
    ],
)
def test_versioned_administrative_aliases_match(
    old_name: str,
    new_name: str,
) -> None:
    assert address_hint_matches({"legal": old_name}, new_name)
    assert CURATION_ADDRESS_RESOLVER_VERSION.startswith("structured-address-v1-")


def test_parses_compound_sigungu_hierarchy() -> None:
    parsed = parse_address_hint("경상북도 포항시 남구 호미곶면 대보리")
    assert parsed is not None
    assert parsed.sido == "경상북도"
    assert parsed.sigungu == "포항시 남구"
    assert parsed.locality == ("호미곶면", "대보리")

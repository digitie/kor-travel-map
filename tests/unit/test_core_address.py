"""``test_core_address`` — kraddr-base 흡수 utility (PR#37, ADR-041)."""

from __future__ import annotations

import pytest

from kortravelmap.core.address import (
    BjdParts,
    extract_sido_code,
    extract_sigungu_code,
    is_valid_bjd_code,
    normalize_bjd_code,
    normalize_korean_text,
    normalize_phone_number,
    parse_bjd_code,
)

# -- normalize_bjd_code ----------------------------------------------------


@pytest.mark.unit
class TestNormalizeBjdCode:
    def test_none_returns_none(self) -> None:
        assert normalize_bjd_code(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_bjd_code("") is None
        assert normalize_bjd_code("   ") is None

    def test_already_10_digits(self) -> None:
        assert normalize_bjd_code("1156010100") == "1156010100"

    def test_int_input_padded(self) -> None:
        assert normalize_bjd_code(1156010100) == "1156010100"

    def test_int_input_short(self) -> None:
        # 9자리 int → 0 padding.
        assert normalize_bjd_code(156010100) == "0156010100"

    def test_negative_int_rejected(self) -> None:
        with pytest.raises(ValueError, match="음수"):
            normalize_bjd_code(-1)

    def test_dash_separator_absorbed(self) -> None:
        assert normalize_bjd_code("11-560-101-00") == "1156010100"

    def test_dot_separator_absorbed(self) -> None:
        assert normalize_bjd_code("11.560.101.00") == "1156010100"

    def test_whitespace_absorbed(self) -> None:
        assert normalize_bjd_code(" 11 560 101 00 ") == "1156010100"

    def test_9digit_padded(self) -> None:
        assert normalize_bjd_code("156010100") == "0156010100"

    def test_too_short_rejected(self) -> None:
        with pytest.raises(ValueError, match="10자리"):
            normalize_bjd_code("12345")

    def test_too_long_rejected(self) -> None:
        with pytest.raises(ValueError, match="10자리"):
            normalize_bjd_code("12345678901234")

    def test_non_numeric_only_returns_none(self) -> None:
        # "abc" → re.sub removes everything → "" → None.
        assert normalize_bjd_code("abc") is None


# -- is_valid_bjd_code -----------------------------------------------------


@pytest.mark.unit
class TestIsValidBjdCode:
    def test_valid_10_digit(self) -> None:
        assert is_valid_bjd_code("1156010100") is True

    def test_valid_after_normalize(self) -> None:
        # dash 흡수 후 10자리 → valid.
        assert is_valid_bjd_code("11-560-101-00") is True

    def test_none_invalid(self) -> None:
        assert is_valid_bjd_code(None) is False

    def test_empty_invalid(self) -> None:
        assert is_valid_bjd_code("") is False

    def test_too_short_invalid(self) -> None:
        assert is_valid_bjd_code("1234") is False

    def test_too_long_invalid(self) -> None:
        assert is_valid_bjd_code("12345678901234") is False


# -- parse_bjd_code --------------------------------------------------------


@pytest.mark.unit
class TestParseBjdCode:
    def test_seoul_yeongdeungpo(self) -> None:
        parts = parse_bjd_code("1156010100")
        assert parts == BjdParts(
            sido="11", sigungu="560", eupmyeondong="101", ri="00"
        )

    def test_compose_methods(self) -> None:
        parts = parse_bjd_code("1156010100")
        assert parts.sido_code() == "11"
        assert parts.sigungu_code() == "11560"
        assert parts.eupmyeondong_code() == "11560101"
        assert parts.to_bjd_code() == "1156010100"

    def test_int_input(self) -> None:
        parts = parse_bjd_code(1156010100)
        assert parts.sido == "11"

    def test_dash_absorbed(self) -> None:
        parts = parse_bjd_code("11-560-101-00")
        assert parts.sido == "11"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="parse 불가"):
            parse_bjd_code("")


# -- extract_sigungu_code / extract_sido_code ------------------------------


@pytest.mark.unit
def test_extract_sigungu_code() -> None:
    assert extract_sigungu_code("1156010100") == "11560"
    assert extract_sigungu_code(1156010100) == "11560"
    assert extract_sigungu_code("11-560-101-00") == "11560"
    assert extract_sigungu_code(None) is None
    assert extract_sigungu_code("") is None


@pytest.mark.unit
def test_extract_sido_code() -> None:
    assert extract_sido_code("1156010100") == "11"
    assert extract_sido_code(1156010100) == "11"
    assert extract_sido_code(None) is None
    assert extract_sido_code("") is None


# -- normalize_phone_number ------------------------------------------------


@pytest.mark.unit
class TestNormalizePhoneNumber:
    def test_none_returns_none(self) -> None:
        assert normalize_phone_number(None) is None

    def test_empty_returns_none(self) -> None:
        assert normalize_phone_number("") is None
        assert normalize_phone_number("   ") is None

    def test_seoul_9_digit(self) -> None:
        assert normalize_phone_number("027531234") == "02-753-1234"

    def test_seoul_10_digit(self) -> None:
        assert normalize_phone_number("0226703114") == "02-2670-3114"

    def test_seoul_already_dashed(self) -> None:
        # 이미 dash 있어도 normalize 동일.
        assert normalize_phone_number("02-2670-3114") == "02-2670-3114"

    def test_mobile_11_digit(self) -> None:
        assert normalize_phone_number("01012345678") == "010-1234-5678"

    def test_regional_10_digit(self) -> None:
        assert normalize_phone_number("0317531234") == "031-753-1234"

    def test_regional_11_digit(self) -> None:
        # 11자리 일반 — 3-4-4 표기 (010-XXXX-XXXX와 동일 규칙).
        assert normalize_phone_number("03112345678") == "031-1234-5678"

    def test_no_digits_returns_original_trimmed(self) -> None:
        assert normalize_phone_number("internal-ext-203") == "internal-ext-203"

    def test_unrecognized_format_returns_trimmed(self) -> None:
        # 8자리는 매핑 안 됨 — 원본 trim 반환.
        assert normalize_phone_number(" 1234567 ") == "1234567"


# -- normalize_korean_text -------------------------------------------------


@pytest.mark.unit
class TestNormalizeKoreanText:
    def test_none_returns_none(self) -> None:
        assert normalize_korean_text(None) is None

    def test_empty_returns_none(self) -> None:
        assert normalize_korean_text("") is None
        assert normalize_korean_text("   ") is None

    def test_strip_outer(self) -> None:
        assert normalize_korean_text("  서울특별시  ") == "서울특별시"

    def test_collapse_multiple_spaces(self) -> None:
        assert normalize_korean_text("서울   특별시") == "서울 특별시"

    def test_fullwidth_space_normalized(self) -> None:
        # 전각 공백(U+3000)이 NFKC로 일반 공백으로.
        assert normalize_korean_text("서울　특별시") == "서울 특별시"

    def test_already_clean_unchanged(self) -> None:
        assert normalize_korean_text("서울특별시") == "서울특별시"

"""``test_dto_address`` — 보강된 Address DTO (PR#37, ADR-041)."""

from __future__ import annotations

import pytest

from krtour.map.dto import Address


@pytest.mark.unit
def test_empty_address_all_none() -> None:
    """모든 필드 default None — Feature.address 기본값으로 사용."""
    address = Address()
    assert address.road is None
    assert address.legal is None
    assert address.bjd_code is None
    assert address.zipcode is None
    assert address.sido_name is None
    assert address.is_complete() is False
    assert address.display() == ""


@pytest.mark.unit
def test_full_address_valid() -> None:
    """모든 필드 채워진 영등포 여의도 example — validator + helper 동작."""
    address = Address(
        road="서울특별시 영등포구 여의공원로 120",
        legal="서울특별시 영등포구 여의도동 8",
        admin="서울특별시 영등포구 여의동",
        bjd_code="1156010100",
        admin_dong_code="1156051000",
        sigungu_code="11560",
        sido_code="11",
        road_name_code="115603166015",
        road_address_management_no="1156010100100080000000001",
        zipcode="07258",
        sido_name="서울특별시",
        sigungu_name="영등포구",
    )
    assert address.bjd_code == "1156010100"
    assert address.is_complete() is True
    assert address.display() == "서울특별시 영등포구 여의공원로 120"


@pytest.mark.unit
def test_display_falls_through_road_legal_admin() -> None:
    assert Address(road="A", legal="B", admin="C").display() == "A"
    assert Address(legal="B", admin="C").display() == "B"
    assert Address(admin="C").display() == "C"
    assert Address().display() == ""


@pytest.mark.unit
def test_is_complete_requires_bjd_and_address_string() -> None:
    # bjd_code 만으론 부족.
    assert Address(bjd_code="1156010100").is_complete() is False
    # road or legal 둘 중 하나 필요.
    assert (
        Address(bjd_code="1156010100", road="서울 영등포 여의공원로 120").is_complete()
        is True
    )
    assert (
        Address(bjd_code="1156010100", legal="서울 영등포 여의도동 8").is_complete()
        is True
    )
    # bjd_code 없으면 false.
    assert Address(road="서울 영등포 여의공원로 120").is_complete() is False


# -- field validators ---


@pytest.mark.unit
class TestBjdCodeValidator:
    def test_valid_10_digit_accepted(self) -> None:
        assert Address(bjd_code="1156010100").bjd_code == "1156010100"

    def test_short_rejected(self) -> None:
        with pytest.raises(ValueError, match="10자리"):
            Address(bjd_code="123")

    def test_long_rejected(self) -> None:
        with pytest.raises(ValueError, match="10자리"):
            Address(bjd_code="12345678901234")

    def test_non_numeric_rejected(self) -> None:
        with pytest.raises(ValueError, match="10자리"):
            Address(bjd_code="1156abc100")

    def test_none_ok(self) -> None:
        assert Address(bjd_code=None).bjd_code is None


@pytest.mark.unit
class TestSigunguCodeValidator:
    def test_valid_5_digit_accepted(self) -> None:
        assert Address(sigungu_code="11560").sigungu_code == "11560"

    def test_short_rejected(self) -> None:
        with pytest.raises(ValueError, match="5자리"):
            Address(sigungu_code="123")


@pytest.mark.unit
class TestSidoCodeValidator:
    def test_valid_2_digit_accepted(self) -> None:
        assert Address(sido_code="11").sido_code == "11"

    def test_long_rejected(self) -> None:
        with pytest.raises(ValueError, match="2자리"):
            Address(sido_code="111")


@pytest.mark.unit
class TestZipcodeValidator:
    def test_valid_5_digit_accepted(self) -> None:
        assert Address(zipcode="07258").zipcode == "07258"

    def test_old_6_digit_rejected(self) -> None:
        # 구 우편번호 6자리는 폐기됨.
        with pytest.raises(ValueError, match="5자리"):
            Address(zipcode="121-768")


# -- model-level consistency validator ---


@pytest.mark.unit
class TestCodeConsistencyValidator:
    def test_consistent_codes_accepted(self) -> None:
        a = Address(bjd_code="1156010100", sigungu_code="11560", sido_code="11")
        assert a.bjd_code == "1156010100"

    def test_partial_codes_ok(self) -> None:
        # bjd만 있고 sigungu/sido 없어도 OK (consistency check skip).
        Address(bjd_code="1156010100")
        # sigungu만 있고 bjd 없어도 OK.
        Address(sigungu_code="11560")

    def test_sido_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="sido_code"):
            # bjd 앞 2자리 '11' ≠ sido_code '22'.
            Address(bjd_code="1156010100", sido_code="22")

    def test_sigungu_mismatch_rejected(self) -> None:
        with pytest.raises(ValueError, match="sigungu_code"):
            # bjd 앞 5자리 '11560' ≠ sigungu '22999'.
            Address(bjd_code="1156010100", sigungu_code="22999")


# -- extra=forbid ---


@pytest.mark.unit
def test_extra_field_rejected() -> None:
    """ADR-018 — extra='forbid'."""
    with pytest.raises(ValueError, match="unknown_field"):
        Address(unknown_field="x")  # type: ignore[call-arg]

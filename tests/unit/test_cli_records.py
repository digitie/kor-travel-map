"""``test_cli_records`` — CLI ``import``용 NDJSON MOIS 레코드 리더 (순수).

``MoisLicenseJsonRecord`` 래퍼의 attribute/날짜 파싱과 ``iter_mois_license_records``의
streaming/에러 처리를 DB 없이 검증한다.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from krtour.map.cli.records import (
    MoisLicenseJsonRecord,
    iter_mois_license_records,
)

if TYPE_CHECKING:
    from pathlib import Path

# ``MoisLicensePlaceRecord`` Protocol 필드 대표 집합 — ``@property`` 멤버(앞쪽)와
# 일반 method 멤버(facility_info)를 모두 포함해 ``__getattr__`` 계약을 검증한다.
# (Protocol 전체 열거는 ``__protocol_attrs__``가 3.12+ 전용이라 버전 비의존적으로
# 명시 집합을 쓴다.)
_REPRESENTATIVE_FIELDS = (
    "service_slug",
    "mng_no",
    "place_name",
    "telno",
    "lon",
    "lat",
    "legal_dong_code",
    "road_name_code",
    "license_date",
    "designation_date",
    "business_type_name",
    "medical_subject_names",
    "ground_floor_count",
    "facility_area",
)


def test_record_exposes_dict_fields() -> None:
    rec = MoisLicenseJsonRecord(
        {"service_slug": "general_restaurants", "mng_no": "A1", "place_name": "민어집"}
    )
    assert rec.service_slug == "general_restaurants"
    assert rec.mng_no == "A1"
    assert rec.place_name == "민어집"


def test_record_missing_key_is_none() -> None:
    rec = MoisLicenseJsonRecord({"service_slug": "x"})
    # Protocol 필드인데 dict에 없으면 None (누락 허용 계약).
    assert rec.telno is None
    assert rec.lon is None
    assert rec.legal_dong_code is None


def test_record_parses_iso_date_fields() -> None:
    rec = MoisLicenseJsonRecord(
        {"license_date": "2020-05-01", "designation_date": "2019-01-02T00:00:00"}
    )
    assert rec.license_date == date(2020, 5, 1)
    # datetime 형태도 앞 10자만 잘라 date로.
    assert rec.designation_date == date(2019, 1, 2)


def test_record_bad_date_is_none() -> None:
    rec = MoisLicenseJsonRecord({"license_date": "not-a-date", "designation_date": ""})
    assert rec.license_date is None
    assert rec.designation_date is None


def test_record_passes_through_numbers_and_bool() -> None:
    rec = MoisLicenseJsonRecord(
        {"lon": 127.1, "lat": 37.5, "is_open": True, "ground_floor_count": 3}
    )
    assert rec.lon == 127.1
    assert rec.lat == 37.5
    assert rec.is_open is True
    assert rec.ground_floor_count == 3


def test_record_exposes_all_protocol_fields() -> None:
    """변환 코드는 duck-typed attribute 접근만 하므로, Protocol 전 필드가 빈
    dict에서도 ``AttributeError`` 없이 읽혀야 한다(누락 → None 계약).

    (``isinstance`` runtime_checkable은 Protocol이 ``@property``와 일반 method를
    섞어 선언해 ``__getattr__`` 인스턴스에 대해 신뢰할 수 없으므로 쓰지 않는다.)
    """
    rec = MoisLicenseJsonRecord({})
    for attr in _REPRESENTATIVE_FIELDS:
        # 접근 자체가 예외 없이 되고 빈 dict에선 None — 누락 허용 계약.
        assert getattr(rec, attr) is None


def test_record_dunder_access_raises() -> None:
    rec = MoisLicenseJsonRecord({"service_slug": "x"})
    # 내부/dunder 이름은 None이 아니라 AttributeError (재귀/오작동 방지).
    with pytest.raises(AttributeError):
        _ = rec.__missing_internal__


def test_iter_reads_ndjson_lazily(tmp_path: Path) -> None:
    path = tmp_path / "mois.ndjson"
    path.write_text(
        '{"service_slug": "a", "mng_no": "1"}\n'
        "\n"  # 빈 줄은 skip
        '{"service_slug": "b", "mng_no": "2"}\n',
        encoding="utf-8",
    )
    records = list(iter_mois_license_records(path))
    assert [r.mng_no for r in records] == ["1", "2"]


def test_iter_accepts_utf8_bom(tmp_path: Path) -> None:
    path = tmp_path / "bom.ndjson"
    path.write_text('{"service_slug": "a", "mng_no": "1"}\n', encoding="utf-8-sig")
    records = list(iter_mois_license_records(path))
    assert records[0].service_slug == "a"


def test_iter_raises_on_bad_json_with_line_no(tmp_path: Path) -> None:
    path = tmp_path / "bad.ndjson"
    path.write_text(
        '{"service_slug": "a"}\n{not json}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match=r":2:"):
        list(iter_mois_license_records(path))


def test_iter_raises_on_non_object_line(tmp_path: Path) -> None:
    path = tmp_path / "arr.ndjson"
    path.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        list(iter_mois_license_records(path))

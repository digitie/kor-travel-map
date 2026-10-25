"""휴게소 reader의 고정 Geo 증거 계약. SQL/수집 배선 전의 내부 전제다.

지문은 전달된 사실의 비교값이며 DB 출처나 현재 토큰의 권한을 자체 증명하지 않는다.
후속 SD가 같은 snapshot의 실제 base/stamp를 반환하고 엄격 decoder가 결박해야 한다.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo

REST_AREA_READER_REVISION: Final = "431_transport_rest_reader"
REST_AREA_GEO_DIGEST_DOMAIN: Final = b"kor-travel-map:transport-rest-area-geo-evidence:v1\0"
REST_AREA_ADDRESS_FIELDS: Final = (
    "road",
    "legal",
    "admin",
    "bjd_code",
    "admin_dong_code",
    "sigungu_code",
    "sido_code",
    "road_name_code",
    "road_address_management_no",
    "zipcode",
    "sido_name",
    "sigungu_name",
)
_PAYLOAD_HASH: Final = re.compile(r"[0-9a-f]{32}")
_ENTITY_KEY: Final = re.compile(r"se_[0-9a-f]{64}")
_RECORD_KEY: Final = re.compile(r"sr_[0-9a-f]{20}")
_POINT_NDR_4326: Final = "0101000020e6100000"
_MAX_GEO_BYTES: Final = 131_072


def _text(value: object, *, cap: int, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if type(value) is not str or len(value) > cap or "\0" in value:
        raise ValueError("invalid rest-area Geo text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("invalid rest-area Geo Unicode") from exc
    if size > cap:
        raise ValueError("invalid rest-area Geo text budget")
    return value


def _time(value: object) -> str:
    if type(value) is not datetime or (
        type(value.tzinfo) is not timezone
        and not (type(value.tzinfo) is ZoneInfo and value.tzinfo.key == "Asia/Seoul")
    ):
        raise ValueError("invalid rest-area Geo observation time")
    if value.utcoffset() is None:
        raise ValueError("invalid rest-area Geo observation time")
    try:
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    except OverflowError as exc:
        raise ValueError("invalid rest-area Geo observation range") from exc


def _frame(value: str | None) -> bytes:
    # NULL과 빈 문자열을 구분하며 구분자/Unicode가 경계를 바꾸지 못한다.
    if value is None:
        return b"\0"
    encoded = value.encode("utf-8")
    return b"\1" + len(encoded).to_bytes(8, "big") + encoded


@dataclass(frozen=True)
class RestAreaGeoFacts:
    """SD의 실제 base/stamp 결박에 사용할 고정 필드. 외부 입력은 권한 증거가 아니다.

    address는 REST_AREA_ADDRESS_FIELDS 순서다. coord는 NDR/2D/POINT/SRID4326 EWKB만 받는다.
    이 단계는 reverse 재사용의 called만 지원한다. 다른 outcome의 확대는 별도 계약이다.
    """

    dataset_id: int
    source_entity_key: str
    source_record_key: str
    raw_payload_hash: str
    feature_id: UUID
    coordinate_ewkb: str
    address: tuple[str | None, ...]
    geo_version_token: str
    geo_data_token: str
    reverse_outcome: str
    stamped_at: datetime

    def __post_init__(self) -> None:
        if type(self.dataset_id) is not int or not 1 <= self.dataset_id < 2**63:
            raise ValueError("invalid rest-area Geo dataset")
        for value, pattern, length in (
            (self.source_entity_key, _ENTITY_KEY, 67),
            (self.source_record_key, _RECORD_KEY, 23),
            (self.raw_payload_hash, _PAYLOAD_HASH, 32),
        ):
            if type(value) is not str or len(value) != length or pattern.fullmatch(value) is None:
                raise ValueError("invalid rest-area Geo source binding")
        if type(self.feature_id) is not UUID:
            raise ValueError("invalid rest-area Geo Feature binding")
        coord = self.coordinate_ewkb
        if (
            type(coord) is not str
            or len(coord) != 50
            or not coord.startswith(_POINT_NDR_4326)
            or re.fullmatch(r"[0-9a-f]{50}", coord) is None
        ):
            raise ValueError("invalid rest-area Geo coordinate encoding")
        lon, lat = struct.unpack("<dd", bytes.fromhex(coord)[9:])
        if not math.isfinite(lon) or not math.isfinite(lat) or abs(lon) > 180 or abs(lat) > 90:
            raise ValueError("invalid rest-area Geo coordinate range")
        if type(self.address) is not tuple or len(self.address) != len(REST_AREA_ADDRESS_FIELDS):
            raise ValueError("invalid rest-area Geo address schema")
        for address_value in self.address:
            _text(address_value, cap=8192, nullable=True)
        for value in (self.geo_version_token, self.geo_data_token):
            _text(value, cap=256)
            if not value or value != value.strip():
                raise ValueError("invalid rest-area Geo token")
        if type(self.reverse_outcome) is not str or self.reverse_outcome != "called":
            raise ValueError("unsupported rest-area Geo outcome")
        _time(self.stamped_at)
        if sum(len(_frame(value)) for value in self._parts()) > _MAX_GEO_BYTES:
            raise ValueError("invalid rest-area Geo whole budget")

    def _parts(self) -> tuple[str | None, ...]:
        return (
            str(self.dataset_id),
            self.source_entity_key,
            self.source_record_key,
            self.raw_payload_hash,
            str(self.feature_id),
            self.coordinate_ewkb,
            *self.address,
            self.geo_version_token,
            self.geo_data_token,
            self.reverse_outcome,
            _time(self.stamped_at),
        )

    def digest(self) -> str:
        """정확 versioned length-frame SHA256. JSON 키 순서/공백/float text와 무관하다."""
        digest = hashlib.sha256(REST_AREA_GEO_DIGEST_DOMAIN)
        for value in self._parts():
            digest.update(_frame(value))
        return digest.hexdigest()

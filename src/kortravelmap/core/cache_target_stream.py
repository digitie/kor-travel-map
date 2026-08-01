"""Cache target source fingerprint와 snapshot Merkle v1 순수 계약.

외부 producer가 보내는 좌표/반경을 JSON 부동소수점 표기에 의존하지 않는 정수
projection으로 바꾼다. 이 모듈은 DB/API 의존 없이 Map과 consumer의 golden vector를
공유하기 위한 정본 구현이다.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, InvalidOperation
from typing import Final, Literal, TypeAlias

from kortravelmap.core.sync_scope import MAX_EXTERNAL_SYSTEM_NAME_LENGTH

__all__ = [
    "CACHE_TARGET_SOURCE_VERSION",
    "ActiveCacheTargetSourceV1",
    "CacheTargetSourceV1",
    "DeletedCacheTargetSourceV1",
    "SnapshotMerkleRowV1",
    "canonical_cache_target_source_bytes",
    "cache_target_source_fingerprint",
    "make_active_cache_target_source",
    "make_deleted_cache_target_source",
    "snapshot_leaf_digest",
    "snapshot_merkle_root",
    "validate_cache_target_external_system",
    "validate_cache_target_key",
]

CACHE_TARGET_SOURCE_VERSION: Final[Literal["cache-target-source-v1"]] = (
    "cache-target-source-v1"
)

_COORD_QUANTUM: Final[Decimal] = Decimal("0.000001")
_RADIUS_QUANTUM_KM: Final[Decimal] = Decimal("0.001")
_COORD_SCALE: Final[int] = 1_000_000
_RADIUS_KM_TO_METRES: Final[int] = 1_000
_MAX_RADIUS_KM: Final[Decimal] = Decimal("100")
_MAX_U32: Final[int] = 2**32 - 1
_MAX_U64: Final[int] = 2**64 - 1
_LOWERCASE_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")

_LEAF_DOMAIN: Final[bytes] = b"KTMCTLEAF\x00"
_NODE_DOMAIN: Final[bytes] = b"KTMCTNODE\x00"
_EMPTY_DOMAIN: Final[bytes] = b"KTMCTEMPTY\x00"


def validate_cache_target_external_system(value: str) -> str:
    """외부 system identity의 단일 Unicode 정규형을 강제한다."""
    if not value or value != value.strip():
        raise ValueError("external_system은 trim된 비어 있지 않은 문자열이어야 합니다.")
    if len(value) > MAX_EXTERNAL_SYSTEM_NAME_LENGTH:
        raise ValueError(f"external_system은 {MAX_EXTERNAL_SYSTEM_NAME_LENGTH}자 이하여야 합니다.")
    if value != unicodedata.normalize("NFC", value):
        raise ValueError("external_system은 NFC 정규형이어야 합니다.")
    return value


def validate_cache_target_key(value: str) -> str:
    """cache target 자연키의 단일 Unicode 정규형을 강제한다."""
    if not value or value != value.strip() or len(value) > 512:
        raise ValueError("target_key는 trim된 1~512자 문자열이어야 합니다.")
    if value != unicodedata.normalize("NFC", value):
        raise ValueError("target_key는 NFC 정규형이어야 합니다.")
    return value


@dataclass(frozen=True, slots=True)
class ActiveCacheTargetSourceV1:
    """정수 단위로 정규화한 active desired state."""

    lon_e6: int
    lat_e6: int
    radius_m: int
    update_enabled: bool
    version: Literal["cache-target-source-v1"] = CACHE_TARGET_SOURCE_VERSION
    state: Literal["active"] = "active"

    def __post_init__(self) -> None:
        if not -180 * _COORD_SCALE <= self.lon_e6 <= 180 * _COORD_SCALE:
            raise ValueError("lon_e6는 유효한 경도 범위여야 합니다.")
        if not -90 * _COORD_SCALE <= self.lat_e6 <= 90 * _COORD_SCALE:
            raise ValueError("lat_e6는 유효한 위도 범위여야 합니다.")
        if not 0 < self.radius_m <= int(_MAX_RADIUS_KM) * _RADIUS_KM_TO_METRES:
            raise ValueError("radius_m은 1 이상 100000 이하여야 합니다.")
        if not isinstance(self.update_enabled, bool):
            raise TypeError("update_enabled는 bool이어야 합니다.")
        if self.version != CACHE_TARGET_SOURCE_VERSION or self.state != "active":
            raise ValueError("active source의 version/state가 canonical 값이 아닙니다.")


@dataclass(frozen=True, slots=True)
class DeletedCacheTargetSourceV1:
    """payload가 없는 durable tombstone desired state."""

    version: Literal["cache-target-source-v1"] = CACHE_TARGET_SOURCE_VERSION
    state: Literal["deleted"] = "deleted"

    def __post_init__(self) -> None:
        if self.version != CACHE_TARGET_SOURCE_VERSION or self.state != "deleted":
            raise ValueError("deleted source의 version/state가 canonical 값이 아닙니다.")


CacheTargetSourceV1: TypeAlias = ActiveCacheTargetSourceV1 | DeletedCacheTargetSourceV1


@dataclass(frozen=True, slots=True)
class SnapshotMerkleRowV1:
    """ADR-081 snapshot leaf의 유일한 다섯 필드."""

    external_system: str
    target_key: str
    state: Literal["active", "deleted"]
    source_generation: int
    source_payload_fingerprint: str


def _finite_decimal(value: Decimal | int | str, *, field: str) -> Decimal:
    if isinstance(value, (bool, float)):
        raise TypeError(f"{field}는 Decimal, int 또는 10진 문자열이어야 합니다.")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field}는 유효한 10진수여야 합니다.") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field}는 유한한 10진수여야 합니다.")
    return parsed


def _quantized_int(
    value: Decimal,
    *,
    quantum: Decimal,
    scale: int,
) -> int:
    try:
        return int(value.quantize(quantum, rounding=ROUND_HALF_EVEN) * scale)
    except DecimalException as exc:
        raise ValueError("numeric 값이 canonical 정규화 범위를 벗어났습니다.") from exc


def make_active_cache_target_source(
    *,
    lon: Decimal | int | str,
    lat: Decimal | int | str,
    radius_km: Decimal | int | str,
    update_enabled: bool,
) -> ActiveCacheTargetSourceV1:
    """외부 numeric 값을 v1 정수 projection으로 정규화한다."""
    longitude = _finite_decimal(lon, field="lon")
    latitude = _finite_decimal(lat, field="lat")
    radius = _finite_decimal(radius_km, field="radius_km")
    if not Decimal("-180") <= longitude <= Decimal("180"):
        raise ValueError("lon은 -180 이상 180 이하여야 합니다.")
    if not Decimal("-90") <= latitude <= Decimal("90"):
        raise ValueError("lat은 -90 이상 90 이하여야 합니다.")
    if not Decimal("0") < radius <= _MAX_RADIUS_KM:
        raise ValueError("radius_km는 0 초과 100 이하여야 합니다.")
    if not isinstance(update_enabled, bool):
        raise TypeError("update_enabled는 bool이어야 합니다.")

    radius_m = _quantized_int(
        radius,
        quantum=_RADIUS_QUANTUM_KM,
        scale=_RADIUS_KM_TO_METRES,
    )
    if radius_m <= 0:
        raise ValueError("radius_km는 metre 정규화 뒤에도 양수여야 합니다.")
    return ActiveCacheTargetSourceV1(
        lon_e6=_quantized_int(
            longitude,
            quantum=_COORD_QUANTUM,
            scale=_COORD_SCALE,
        ),
        lat_e6=_quantized_int(
            latitude,
            quantum=_COORD_QUANTUM,
            scale=_COORD_SCALE,
        ),
        radius_m=radius_m,
        update_enabled=update_enabled,
    )


def make_deleted_cache_target_source() -> DeletedCacheTargetSourceV1:
    """v1 tombstone source를 만든다."""
    return DeletedCacheTargetSourceV1()


def canonical_cache_target_source_bytes(source: CacheTargetSourceV1) -> bytes:
    """typed source를 compact sorted UTF-8 JSON bytes로 직렬화한다."""
    if isinstance(source, ActiveCacheTargetSourceV1):
        payload: dict[str, object] = {
            "coord": {"lat_e6": source.lat_e6, "lon_e6": source.lon_e6},
            "radius_m": source.radius_m,
            "state": source.state,
            "update_enabled": source.update_enabled,
            "version": source.version,
        }
    elif isinstance(source, DeletedCacheTargetSourceV1):
        payload = {"state": source.state, "version": source.version}
    else:
        raise TypeError("지원하지 않는 cache target source 타입입니다.")
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def cache_target_source_fingerprint(source: CacheTargetSourceV1) -> str:
    """canonical source bytes의 lowercase SHA-256 hex를 반환한다."""
    return hashlib.sha256(canonical_cache_target_source_bytes(source)).hexdigest()


def _nfc_bytes(value: str, *, field: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field}는 비어 있지 않은 문자열이어야 합니다.")
    encoded = unicodedata.normalize("NFC", value).encode("utf-8")
    if len(encoded) > _MAX_U32:
        raise ValueError(f"{field} UTF-8 길이는 u32 범위여야 합니다.")
    return encoded


def _raw_fingerprint(value: str) -> bytes:
    if len(value) != 64 or any(character not in _LOWERCASE_HEX for character in value):
        raise ValueError("source_payload_fingerprint는 lowercase SHA-256 hex여야 합니다.")
    return bytes.fromhex(value)


def _leaf_material(row: SnapshotMerkleRowV1) -> tuple[bytes, bytes, bytes]:
    system = _nfc_bytes(row.external_system, field="external_system")
    key = _nfc_bytes(row.target_key, field="target_key")
    if row.state == "active":
        state = b"\x01"
    elif row.state == "deleted":
        state = b"\x02"
    else:
        raise ValueError("state는 active 또는 deleted여야 합니다.")
    if not 0 < row.source_generation <= _MAX_U64:
        raise ValueError("source_generation은 양의 u64 범위여야 합니다.")
    material = b"".join(
        (
            _LEAF_DOMAIN,
            len(system).to_bytes(4, "big"),
            system,
            len(key).to_bytes(4, "big"),
            key,
            state,
            row.source_generation.to_bytes(8, "big"),
            _raw_fingerprint(row.source_payload_fingerprint),
        )
    )
    return system, key, material


def snapshot_leaf_digest(row: SnapshotMerkleRowV1) -> bytes:
    """ADR-081 domain-separated leaf digest를 반환한다."""
    return hashlib.sha256(_leaf_material(row)[2]).digest()


def snapshot_merkle_root(rows: list[SnapshotMerkleRowV1]) -> str:
    """NFC UTF-8 byte-order와 odd promotion을 적용한 Merkle root hex."""
    ordered: list[tuple[bytes, bytes, bytes]] = []
    identities: set[tuple[bytes, bytes]] = set()
    for row in rows:
        system, key, material = _leaf_material(row)
        identity = (system, key)
        if identity in identities:
            raise ValueError("NFC 정규화 뒤 snapshot target identity가 중복됩니다.")
        identities.add(identity)
        ordered.append((system, key, hashlib.sha256(material).digest()))
    if not ordered:
        return hashlib.sha256(_EMPTY_DOMAIN).hexdigest()

    level = [digest for _, _, digest in sorted(ordered, key=lambda item: item[:2])]
    while len(level) > 1:
        next_level: list[bytes] = []
        for offset in range(0, len(level), 2):
            left = level[offset]
            if offset + 1 == len(level):
                next_level.append(left)
            else:
                next_level.append(
                    hashlib.sha256(_NODE_DOMAIN + left + level[offset + 1]).digest()
                )
        level = next_level
    return level[0].hex()

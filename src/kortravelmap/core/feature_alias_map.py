"""Feature alias-map v1 canonical bytes·checksum 순수 계약 (T-VN-32C, ADR-068).

PinVi alias-map DB-to-DB 이관(consumer-rollout-v1 T-VN-32 "32C: 검증된 alias
map DB-to-DB 이관 → 양 저장소 checksum 일치")의 양 저장소 공용 golden vector
정본 구현이다. DB/API 의존 없이 Map과 PinVi가 **독립 구현으로 같은 값**을
재계산해 `contracts/feature-alias-map-v1-golden.json`으로 대조한다
(`cache-target-source-v1` golden과 같은 패턴).

canonical 계약 (feature-alias-map-v1)
-------------------------------------

- **row** = ``(alias, feature_uuid, alias_kind)``.
  - ``alias``: trim된 비어 있지 않은 NFC 정규형 문자열, ≤256자
    (``infra.feature_identity.MAX_FEATURE_REF_LENGTH``와 정합). 비-NFC 입력은
    정규화하지 않고 **거부**한다(fail-close — 저장소 간 보이지 않는 정규화
    차이를 남기지 않는다).
  - ``feature_uuid``: canonical lowercase hyphenated 36자 형태만 수용.
    digest material에는 RFC 4122 big-endian **raw 16 bytes**로 들어간다.
  - ``alias_kind``: 닫힌 집합(0079 CHECK와 동일 domain). 현재
    ``'legacy_feature_id'`` 1종.
- **leaf material** (domain separation + length prefix — 구분자 충돌 원천
  차단)::

      "KTMFAMLEAF\\x00" || u32be(len(alias_utf8)) || alias_utf8
                        || u32be(len(kind_utf8))  || kind_utf8
                        || uuid_raw_16bytes

  ``leaf = sha256(material)``.
- **순서**: alias NFC UTF-8 byte 오름차순 전순서(alias는 PK라 유일).
  NFC 정규화 뒤 중복 alias는 거부한다.
- **merkle root**: 정렬된 leaf를 이진 결합(``sha256("KTMFAMNODE\\x00"+L+R)``),
  홀수 leaf는 상위 레벨로 승격. 빈 map은 ``sha256("KTMFAMEMPTY\\x00")``.
- **파생 검증**: ``alias_kind='legacy_feature_id'`` 행은
  ``feature_uuid == uuid5(FEATURE_UUID_NAMESPACE, alias)``
  (``core.ids.feature_uuid_from_legacy``)여야 한다. checksum은 저장된 값
  위에서 계산하고, 파생 검증은 별도 함수로 분리한다 — 이관 소비자(PinVi)는
  두 검증을 모두 통과한 map만 "검증된 alias map"으로 적용한다.
"""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from dataclasses import dataclass
from typing import Final, Literal

from kortravelmap.core.ids import feature_uuid_from_legacy

__all__ = [
    "FEATURE_ALIAS_MAP_VERSION",
    "FEATURE_ALIAS_KINDS",
    "MAX_FEATURE_ALIAS_LENGTH",
    "FeatureAliasMapRowV1",
    "feature_alias_leaf_digest",
    "feature_alias_map_merkle_root",
    "validate_feature_alias",
    "validate_feature_alias_kind",
    "validate_canonical_feature_uuid",
    "verify_legacy_alias_derivation",
]

FEATURE_ALIAS_MAP_VERSION: Final[Literal["feature-alias-map-v1"]] = "feature-alias-map-v1"

FEATURE_ALIAS_KINDS: Final[frozenset[str]] = frozenset({"legacy_feature_id"})
"""0079 ``ck_feature_aliases_alias_kind``와 동일한 닫힌 kind domain."""

MAX_FEATURE_ALIAS_LENGTH: Final[int] = 256
"""경계 참조 상한(``MAX_FEATURE_REF_LENGTH``)과 정합 — legacy id 실측 최대
수십 자."""

_CANONICAL_UUID_LENGTH: Final[int] = 36
_UUID_HYPHEN_POSITIONS: Final[tuple[int, ...]] = (8, 13, 18, 23)
_LOWERCASE_UUID: Final[frozenset[str]] = frozenset("0123456789abcdef-")

_LEAF_DOMAIN: Final[bytes] = b"KTMFAMLEAF\x00"
_NODE_DOMAIN: Final[bytes] = b"KTMFAMNODE\x00"
_EMPTY_DOMAIN: Final[bytes] = b"KTMFAMEMPTY\x00"
_MAX_U32: Final[int] = 2**32 - 1


def validate_feature_alias(value: str) -> str:
    """alias 문자열의 canonical 계약 검증 — 통과 시 그대로 반환.

    비-NFC 입력은 정규화하지 않고 거부한다: 이관·checksum 표면에서 저장소마다
    다른 정규화가 조용히 끼어들면 byte 계약이 갈라진다 (fail-close).
    """
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("alias는 trim된 비어 있지 않은 문자열이어야 합니다.")
    if len(value) > MAX_FEATURE_ALIAS_LENGTH:
        raise ValueError(f"alias는 {MAX_FEATURE_ALIAS_LENGTH}자 이하여야 합니다.")
    if value != unicodedata.normalize("NFC", value):
        raise ValueError("alias는 NFC 정규형이어야 합니다.")
    return value


def validate_feature_alias_kind(value: str) -> str:
    """``alias_kind`` 닫힌 집합 검증 — 임의 kind 발명 fail-close."""
    if value not in FEATURE_ALIAS_KINDS:
        raise ValueError(
            f"alias_kind는 {sorted(FEATURE_ALIAS_KINDS)} 중 하나여야 합니다 (got {value!r})."
        )
    return value


def validate_canonical_feature_uuid(value: str) -> str:
    """canonical lowercase hyphenated UUID 형태만 수용한다.

    ``uuid.UUID``가 수용하는 hex-only/braced/URN/대문자 변형은 전부 거부 —
    checksum 입력의 표기 자유도를 0으로 만든다.
    """
    if (
        not isinstance(value, str)
        or len(value) != _CANONICAL_UUID_LENGTH
        or any(value[position] != "-" for position in _UUID_HYPHEN_POSITIONS)
        or any(character not in _LOWERCASE_UUID for character in value)
    ):
        raise ValueError(
            "feature_uuid는 canonical lowercase hyphenated 36자 형태여야 합니다."
        )
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError(
            "feature_uuid는 canonical lowercase hyphenated 36자 형태여야 합니다."
        ) from exc
    if str(parsed) != value:
        raise ValueError(
            "feature_uuid는 canonical lowercase hyphenated 36자 형태여야 합니다."
        )
    return value


@dataclass(frozen=True, slots=True)
class FeatureAliasMapRowV1:
    """alias-map leaf를 구성하는 exact 3-field row (생성 시 canonical 검증)."""

    alias: str
    feature_uuid: str
    alias_kind: str

    def __post_init__(self) -> None:
        validate_feature_alias(self.alias)
        validate_canonical_feature_uuid(self.feature_uuid)
        validate_feature_alias_kind(self.alias_kind)


def _leaf_material(row: FeatureAliasMapRowV1) -> tuple[bytes, bytes]:
    """(정렬키 alias bytes, domain-separated leaf material)."""
    alias_bytes = row.alias.encode("utf-8")
    kind_bytes = row.alias_kind.encode("utf-8")
    if len(alias_bytes) > _MAX_U32 or len(kind_bytes) > _MAX_U32:
        raise ValueError("alias/alias_kind UTF-8 길이는 u32 범위여야 합니다.")
    material = b"".join(
        (
            _LEAF_DOMAIN,
            len(alias_bytes).to_bytes(4, "big"),
            alias_bytes,
            len(kind_bytes).to_bytes(4, "big"),
            kind_bytes,
            uuid.UUID(row.feature_uuid).bytes,
        )
    )
    return alias_bytes, material


def feature_alias_leaf_digest(row: FeatureAliasMapRowV1) -> bytes:
    """domain-separated leaf sha256 digest (raw 32 bytes)."""
    return hashlib.sha256(_leaf_material(row)[1]).digest()


def feature_alias_map_merkle_root(rows: list[FeatureAliasMapRowV1]) -> str:
    """alias NFC UTF-8 byte-order·odd promotion을 적용한 merkle root hex."""
    keyed: list[tuple[bytes, bytes]] = []
    seen: set[bytes] = set()
    for row in rows:
        alias_bytes, material = _leaf_material(row)
        if alias_bytes in seen:
            raise ValueError("alias-map에 중복 alias가 있습니다 (NFC 정규형 기준).")
        seen.add(alias_bytes)
        keyed.append((alias_bytes, hashlib.sha256(material).digest()))
    if not keyed:
        return hashlib.sha256(_EMPTY_DOMAIN).hexdigest()

    level = [digest for _, digest in sorted(keyed, key=lambda item: item[0])]
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


def verify_legacy_alias_derivation(row: FeatureAliasMapRowV1) -> None:
    """``legacy_feature_id`` 행의 uuid5 파생 규칙 검증 (ADR-068·0080 CHECK 대응).

    checksum은 저장된 값 위에서 계산하므로, "검증된 alias map"이 되려면 이
    파생 검증을 **함께** 통과해야 한다. dual 기간 alias는 전부
    ``uuid5(FEATURE_UUID_NAMESPACE, alias)`` 파생 산출이다.
    """
    expected = str(feature_uuid_from_legacy(row.alias))
    if row.feature_uuid != expected:
        raise ValueError(
            "legacy alias 파생 불일치 — "
            f"alias={row.alias!r}, feature_uuid={row.feature_uuid!r}, "
            f"expected={expected!r} (ADR-068 uuid5 파생)."
        )

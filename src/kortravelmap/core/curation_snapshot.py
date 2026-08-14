"""PinVi canonical curation snapshot 직렬화 계약.

snapshot ETag와 collection item-set digest는 같은 canonical JSON v1을 쓴다.
문자열은 NFC, object key는 사전순, 정수 identity는 호출자가 decimal string으로
준비하며 ``etag`` 자기 자신은 payload 조립 단계에서 제외한다.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence

__all__ = [
    "canonical_curation_snapshot_bytes",
    "canonical_curation_snapshot_value",
    "curation_snapshot_sha256",
]


def _canonical_value(value: object) -> object:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise TypeError("curation snapshot object keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            if key in normalized:
                raise ValueError("curation snapshot object keys collide after NFC normalization")
            normalized[key] = _canonical_value(raw_value)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_canonical_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TypeError(f"unsupported curation snapshot value: {type(value).__name__}")


def canonical_curation_snapshot_bytes(value: object) -> bytes:
    """canonicalization v1 UTF-8 JSON bytes를 반환한다."""

    return json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_curation_snapshot_value(value: object) -> object:
    """응답과 hash가 공유할 재귀 NFC-normalized JSON value를 반환한다."""

    return _canonical_value(value)


def curation_snapshot_sha256(value: object) -> str:
    """canonicalization v1 payload의 lowercase SHA-256 hex."""

    return hashlib.sha256(canonical_curation_snapshot_bytes(value)).hexdigest()

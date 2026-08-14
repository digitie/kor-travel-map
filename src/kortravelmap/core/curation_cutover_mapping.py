"""T-VN-40C legacy identity mapping export canonicalization.

The Map-maintained ``ops.curation_cutover_identity_mappings`` relation is the
only cross-database backfill input for PinVi.  The service endpoint pages its
rows, but every page carries this deterministic root so a consumer can reject
an incomplete or mixed export.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

__all__ = [
    "CurationCutoverIdentityMappingDigestInput",
    "curation_cutover_identity_mapping_root",
]

_LEAF_PREFIX = b"KTMCURMAPLEAF\x00"
_NODE_PREFIX = b"KTMCURNODE\x00"
_EMPTY_PREFIX = b"KTMCUREMPTY\x00"


@dataclass(frozen=True, slots=True)
class CurationCutoverIdentityMappingDigestInput:
    """Immutable Map mapping row used in the T-VN-40C Merkle receipt."""

    legacy_curated_feature_id: UUID
    collection_id: UUID
    curation_item_id: UUID
    mapping_kind: str
    source_row_hash: str


def _frame(value: bytes) -> bytes:
    return len(value).to_bytes(4, byteorder="big", signed=False) + value


def _nfc_utf8(value: str) -> bytes:
    return unicodedata.normalize("NFC", value).encode("utf-8")


def _leaf(mapping: CurationCutoverIdentityMappingDigestInput) -> bytes:
    try:
        source_row_hash = bytes.fromhex(mapping.source_row_hash)
    except ValueError as exc:
        raise ValueError("source_row_hash must be lowercase SHA-256 hex") from exc
    if len(source_row_hash) != 32 or mapping.source_row_hash != mapping.source_row_hash.lower():
        raise ValueError("source_row_hash must be lowercase SHA-256 hex")
    return hashlib.sha256(
        _LEAF_PREFIX
        + _frame(mapping.legacy_curated_feature_id.bytes)
        + _frame(mapping.collection_id.bytes)
        + _frame(mapping.curation_item_id.bytes)
        + _frame(_nfc_utf8(mapping.mapping_kind))
        + _frame(source_row_hash)
    ).digest()


def curation_cutover_identity_mapping_root(
    mappings: Iterable[CurationCutoverIdentityMappingDigestInput],
) -> str:
    """Return the recovery-preflight ``KTMCUR*`` Merkle root.

    UUID raw bytes are the stable ordering key.  Duplicate legacy identities
    are rejected here even though the database primary key already forbids
    them, keeping fixture and consumer implementations fail-closed.
    """

    ordered = sorted(mappings, key=lambda mapping: mapping.legacy_curated_feature_id.bytes)
    if any(
        left.legacy_curated_feature_id == right.legacy_curated_feature_id
        for left, right in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("legacy_curated_feature_id values must be unique")

    level = [_leaf(mapping) for mapping in ordered]
    if not level:
        return hashlib.sha256(_EMPTY_PREFIX).hexdigest()
    while len(level) > 1:
        next_level: list[bytes] = []
        for index in range(0, len(level), 2):
            left = level[index]
            if index + 1 == len(level):
                next_level.append(left)
            else:
                next_level.append(hashlib.sha256(_NODE_PREFIX + left + level[index + 1]).digest())
        level = next_level
    return level[0].hex()

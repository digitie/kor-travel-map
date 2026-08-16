"""T-VN-40C Map→PinVi identity mapping receipt canonicalization tests."""

from __future__ import annotations

from uuid import UUID

import pytest

from kortravelmap.core.curation_cutover_mapping import (
    CurationCutoverIdentityMappingDigestInput,
    curation_cutover_identity_mapping_root,
)


def _mapping(
    legacy_id: str,
    *,
    kind: str = "legacy_projection",
    source_row_hash: str = "a" * 64,
) -> CurationCutoverIdentityMappingDigestInput:
    return CurationCutoverIdentityMappingDigestInput(
        legacy_curated_feature_id=UUID(legacy_id),
        collection_id=UUID("22222222-2222-2222-2222-222222222222"),
        curation_item_id=UUID("33333333-3333-3333-3333-333333333333"),
        mapping_kind=kind,
        source_row_hash=source_row_hash,
    )


def test_cutover_mapping_root_is_order_independent_and_nfc_framed() -> None:
    """Wire root stays stable for a reordered export and NFC-equivalent kind."""

    first = _mapping("00000000-0000-0000-0000-000000000001", kind="cafe\u0301")
    second = _mapping(
        "00000000-0000-0000-0000-000000000002",
        source_row_hash="b" * 64,
    )

    assert curation_cutover_identity_mapping_root((second, first)) == (
        "16cfcd93951f61514a9d39bbc1e535ecb437f49637fed8bdcfcb95b498801db2"
    )
    assert curation_cutover_identity_mapping_root((
        _mapping("00000000-0000-0000-0000-000000000001", kind="café"),
        second,
    )) == curation_cutover_identity_mapping_root((second, first))


def test_cutover_mapping_root_rejects_duplicate_identity_and_noncanonical_hash() -> None:
    mapping = _mapping("00000000-0000-0000-0000-000000000001")

    with pytest.raises(ValueError, match="must be unique"):
        curation_cutover_identity_mapping_root((mapping, mapping))
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        curation_cutover_identity_mapping_root((
            _mapping(
                "00000000-0000-0000-0000-000000000002",
                source_row_hash="A" * 64,
            ),
        ))

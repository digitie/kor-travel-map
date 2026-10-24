"""413은 검토한 7개 루틴의 첫 BEGIN만 바꾸며 shape 변화는 거부한다."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "alembic/versions/413_legacy_sql_protocol_entry.py"
_SPEC = spec_from_file_location("_test_413_protocol_entry", _PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
_MIGRATION = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MIGRATION)
_FENCE = _MIGRATION._GLOBAL_FENCE
_PROTOCOL = _MIGRATION._PROTOCOL
_EXPECTED = {
    "archive_curation_item_command": "ktm_curation_command_owner",
    "create_curation_item_command": "ktm_curation_command_owner",
    "create_manual_curation_item_with_feature_command": "ktm_curation_command_owner",
    "finalize_provider_curation_root": "ktm_curation_command_owner",
    "patch_curation_item_command": "ktm_curation_command_owner",
    "reclassify_curation_quarantine_command": "ktm_curation_command_owner",
    "register_provider_field_shadow_policy": "ktm_feature_schema_owner",
}


def test_only_reviewed_seven_entrypoints_and_original_owners_are_selected():
    assert _MIGRATION._LEGACY_OWNERS == _EXPECTED
    assert "activate_provider_field_policy" not in _MIGRATION._LEGACY_OWNERS
    assert "_record_provider_field_candidates" not in _MIGRATION._LEGACY_OWNERS


@pytest.mark.parametrize("declaration", ["", "DECLARE\n  value integer;\n"])
def test_first_begin_gets_protocol_before_existing_validation(declaration):
    body = "\n" + declaration + "BEGIN\n  IF true THEN NULL; END IF;\n  " + _FENCE + "\nEND;\n"
    changed = _MIGRATION._with_protocol_entry(body)
    assert changed.partition("\nBEGIN\n")[2].lstrip().startswith(_PROTOCOL)
    assert changed.count(_PROTOCOL) == 1
    assert changed.replace("  " + _PROTOCOL + "\n", "", 1) == body


@pytest.mark.parametrize(
    "invalid",
    [
        "missing-fence",
        "duplicate-fence",
        "already-protocol",
        "missing-begin",
        "fence-in-declare",
    ],
)
def test_changed_definition_shape_fails_closed(invalid):
    body = "\nBEGIN\n  " + _FENCE + "\nEND;\n"
    if invalid == "missing-fence":
        body = body.replace(_FENCE, "NULL;")
    elif invalid == "duplicate-fence":
        body = body.replace(_FENCE, _FENCE + "\n" + _FENCE)
    elif invalid == "already-protocol":
        body = body.replace(_FENCE, _PROTOCOL + "\n" + _FENCE)
    elif invalid == "missing-begin":
        body = body.replace("\nBEGIN\n", "\nBEGIN ")
    else:
        body = "DECLARE\n  -- " + _FENCE + "\nBEGIN\n NULL;\nEND;"
    with pytest.raises(RuntimeError, match="legacy SQL"):
        _MIGRATION._with_protocol_entry(body)

"""검토한 field author/revoke 본문은 한 줄 외 보존하고 반복/다른 진입 형태를 거절한다."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_spec = spec_from_file_location(
    "_test_416",
    Path(__file__).resolve().parents[2] / "alembic/versions/416_field_override_protocol.py",
)
assert _spec is not None
assert _spec.loader is not None
_migration = module_from_spec(_spec)
_spec.loader.exec_module(_migration)


@pytest.mark.parametrize("declaration", ["", "DECLARE\n    field integer;\n"])
def test_only_first_entry_is_inserted_and_original_body_preserved(declaration):
    body = "\n" + declaration + "BEGIN\n    IF true THEN NULL; END IF;\nEND;\n"
    changed = _migration._with_protocol_entry(body)
    assert changed.partition("\nBEGIN\n")[2].lstrip().startswith(_migration._PROTOCOL)
    assert changed.replace("  " + _migration._PROTOCOL + "\n", "", 1) == body


@pytest.mark.parametrize(
    "body",
    ["BEGIN NULL; END;", "\nBEGIN\nPERFORM ops.lock_scoped_feature_write_protocol(true);\nEND;"],
)
def test_unknown_or_repeated_protocol_shape_is_rejected(body):
    with pytest.raises(RuntimeError, match="legacy SQL"):
        _migration._with_protocol_entry(body)


def test_both_field_entries_share_existing_protocol_owner_without_new_grants():
    assert set(_migration._LEGACY_OWNERS) == {
        "author_feature_field_overrides",
        "revoke_feature_field_overrides",
    }
    assert set(_migration._LEGACY_OWNERS.values()) == {"ktm_feature_state_procedure_owner"}
    assert set(_migration._EXPECTED_DEFINITIONS) == set(_migration._LEGACY_OWNERS)

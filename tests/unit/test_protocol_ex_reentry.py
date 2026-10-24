"""재진입 패치는 원문을 보존하고 알려지지 않은 모양을 거절한다."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_spec = spec_from_file_location(
    "_test_417", Path(__file__).resolve().parents[2] / "alembic/versions/417_protocol_ex_reentry.py"
)
assert _spec is not None
assert _spec.loader is not None
_migration = module_from_spec(_spec)
_spec.loader.exec_module(_migration)


def test_reentry_insertion_preserves_all_original_bytes_and_session_safety():
    body = "NULL validation\n" + _migration._ENTRY_MARKER + " original rest\n"
    changed = _migration._with_fast_reentry(body)
    assert changed.replace(_migration._FAST_REENTRY, "", 1) == body
    assert changed.index("NULL validation") < changed.index(_migration._FAST_REENTRY)
    assert "PERFORM pg_advisory_xact_lock(1369104691,115);\n        RETURN;" in changed


@pytest.mark.parametrize("body", ["unknown", _migration._ENTRY_MARKER * 2])
def test_unknown_entry_shape_is_rejected(body):
    with pytest.raises(RuntimeError, match="protocol SQL shape"):
        _migration._with_fast_reentry(body)


def test_already_changed_definition_is_rejected():
    body = _migration._FAST_REENTRY + _migration._ENTRY_MARKER
    with pytest.raises(RuntimeError, match="protocol SQL shape"):
        _migration._with_fast_reentry(body)

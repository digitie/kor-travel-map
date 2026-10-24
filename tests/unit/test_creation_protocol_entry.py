"""418 first-BEGIN 변환은 알려진 원문만 보존하며 이중 gate를 거부한다."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

_spec = spec_from_file_location(
    "_test418", Path(__file__).resolve().parents[2] / "alembic/versions/418_creation_protocol.py"
)
assert _spec is not None
assert _spec.loader is not None
_m = module_from_spec(_spec)
_spec.loader.exec_module(_m)


def test_inserted_first_gate_preserves_declared_and_nested_blocks():
    body = "\nDECLARE value text;\nBEGIN\n  value:=NULL;\n  BEGIN\n    NULL;\n  END;\nEND\n"
    result = _m._with_protocol_entry(body)
    assert result.replace("  " + _m._PROTOCOL + "\n", "", 1) == body
    assert result.partition("\nBEGIN\n")[2].startswith("  " + _m._PROTOCOL + "\n")


@pytest.mark.parametrize("body", ["unknown", "BEGIN\nNULL;", "\nBEGIN\n" + _m._PROTOCOL])
def test_unknown_or_already_gated_shape_fails_closed(body):
    with pytest.raises(RuntimeError):
        _m._with_protocol_entry(body)


def test_four_exact_whitelist_and_internal_owner_grants_only():
    assert len(_m._LEGACY_OWNERS) == len(_m._EXPECTED_DEFINITIONS) == 4
    assert set(_m._LEGACY_OWNERS.values()) == {
        "ktm_feature_state_procedure_owner",
        "ktm_manual_feature_procedure_owner",
        "ktm_feature_request_procedure_owner",
    }

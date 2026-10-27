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


# 418의 상수를 다시 적던 owner/grant 검사는 지웠다(434 WI-3). 그 GRANT는 schema owner로 돌아
# 실제로는 아무것도 주지 않았는데 상수 검사는 초록이었다. 실제 ACL은 migration만으로 만든
# head 오라클에서 유도해 본다 — tests/lint/test_protocol_entry_acl_oracle.py.

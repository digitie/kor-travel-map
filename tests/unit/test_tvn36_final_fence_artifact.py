"""T-VN-36D destructive-fence artifact의 bytes/parser freeze."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[2]
_CONTRACT: Final = _ROOT / "contracts" / "vnext" / "tvn36-post-cutover-invariants-v1.sql"
#: T-VN-39 재키가 override 프로시저의 첫 인자를 uuid로 옮겼다. INV-36-04는 그
#: 시그니처가 head에 **있어야 한다**고 선언하므로 계약이 따라와야 한다 —
#: `to_regprocedure`는 IN 인자로 매칭하고, 옛 text 시그니처는 이제 NULL이다.
#: 이 핀은 "계약이 조용히 바뀌지 않는다"를 지키는 것이지 특정 내용을
#: 영구 고정하는 것이 아니다 — 내용이 바뀌면 여기도 같은 커밋에서 바뀐다.
_EXPECTED_SHA256: Final = "19a450cc2363c7286acb45fe583f954430727e23e378d678d06e455458a727ec"
_EXPECTED_ASSERTION_COUNT: Final = 6


def test_tvn36_final_fence_contract_bytes_and_parser_are_frozen() -> None:
    """모든 destructive assertion은 phase trailer가 있는 frozen artifact여야 한다."""

    content = _CONTRACT.read_text(encoding="utf-8")
    parsed = re.findall(
        r"(?ms)^(SELECT .*?); -- expect: 0 -- phase: post-tvn36$",
        content,
    )
    markers = re.findall(r"(?m); -- expect: 0 -- phase: post-tvn36$", content)
    assert len(parsed) == _EXPECTED_ASSERTION_COUNT
    assert len(markers) == _EXPECTED_ASSERTION_COUNT
    assert hashlib.sha256(_CONTRACT.read_bytes()).hexdigest() == _EXPECTED_SHA256


def test_tvn36_final_fence_contract_names_only_final_provenance_relations() -> None:
    """bridge 제거와 typed registry/base/override 정본을 함께 고정한다."""

    content = _CONTRACT.read_text(encoding="utf-8")
    assert "'feature', 'feature_base_field_values'" in content
    assert "'ops', 'feature_overrides'" in content
    assert "'ops', 'feature_override_field_paths'" in content
    assert "'feature.feature_versions'" in content
    assert "'ops.feature_change_requests'" in content

"""T-VN-36D destructive-fence artifact의 bytes/parser freeze."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[2]
_CONTRACT: Final = _ROOT / "contracts" / "vnext" / "tvn36-post-cutover-invariants-v1.sql"
_EXPECTED_SHA256: Final = "0153a71af68eea65e9641b4c9d0634a69ea2d68b39c4b9ade1769cfb2fe01d37"
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

"""T-VN-34C post-cutover DB contract artifact freeze."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[2]
_CONTRACT: Final = _ROOT / "contracts" / "vnext" / "tvn34c-post-cutover-invariants-v1.sql"
_EXPECTED_SHA256: Final = "5a401b3fe35f16d56ec188966a6221570ee8baef09dafbd4cbf4ec369611323e"
_EXPECTED_ASSERTION_COUNT: Final = 11


def test_tvn34c_post_cutover_contract_bytes_and_parser_are_frozen() -> None:
    """모든 assertion은 phase marker와 함께 고정된 바이트 artifact에서 읽힌다."""

    content = _CONTRACT.read_text(encoding="utf-8")
    parsed = re.findall(
        r"(?ms)^(SELECT .*?); -- expect: 0 -- phase: post-cutover$",
        content,
    )
    markers = re.findall(r"(?m); -- expect: 0 -- phase: post-cutover$", content)
    assert len(markers) == _EXPECTED_ASSERTION_COUNT
    assert len(parsed) == _EXPECTED_ASSERTION_COUNT
    assert hashlib.sha256(_CONTRACT.read_bytes()).hexdigest() == _EXPECTED_SHA256


def test_tvn34c_contract_freezes_the_direct_typed_assembly_boundary() -> None:
    """C contract는 public 26-column allowlist와 direct subtype 의존을 함께 명시한다."""

    content = _CONTRACT.read_text(encoding="utf-8")
    assert "feature.features_detailed" in content
    assert "feature.feature_places" in content
    assert "feature.feature_events" in content
    assert "feature.feature_notices" in content
    assert "feature.feature_routes" in content
    assert "feature.feature_areas" in content
    assert "uq_feature_versions_user_request_receipt" in content

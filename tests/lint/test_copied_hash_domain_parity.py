"""사본 CHECK가 원본 CHECK 도메인을 승계하는지의 lint.

``ops.manual_provider_dedup_cases.source_record_raw_payload_hash``는
``feature.source_records.raw_payload_hash``의 사본인데, 사본 제약만 64-hex를
강제해 기본 ``make_payload_hash``(32-hex prefix) 규약으로 적재된 모든
provider 레코드가 M05 case 기록에서 깨졌다(2026-09-01 e2e16 실측, 303이
수리). 두 도메인이 다시 갈라지는 회귀를 ORM 정의 층에서 잡는다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MODELS = PROJECT_ROOT / "src" / "kortravelmap" / "infra" / "models.py"

_SOURCE_PATTERN = re.compile(
    r"raw_payload_hash\s*~\s*'(\^\[0-9a-f\]\{1,64\}\$)'"
)


@pytest.mark.unit
def test_dedup_case_payload_hash_domain_matches_source_records() -> None:
    models = _MODELS.read_text(encoding="utf-8")
    source_domains = set(_SOURCE_PATTERN.findall(models))
    assert source_domains == {"^[0-9a-f]{1,64}$"}, (
        "raw_payload_hash 계열 CHECK 도메인이 갈라졌다 — 사본"
        "(manual_provider_dedup_cases.source_record_raw_payload_hash)은 원본"
        "(source_records.raw_payload_hash)의 도메인 ^[0-9a-f]{1,64}$ 를 그대로"
        f" 승계해야 한다: {sorted(source_domains)}"
    )
    # 사본 필드가 다른(더 좁은) 도메인으로 별도 선언되지 않았는지 — 64-hex
    # 강제가 되살아나면 이 단언이 잡는다.
    assert "source_record_raw_payload_hash ~ '^[0-9a-f]{64}$'" not in models

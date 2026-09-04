"""`feature.features`를 가리키는 단일 컬럼 FK의 **대상 identity 열**을 결박한다.

D2 fixture helper(`scripts/admin_feature_live_fixture.py`)는 cleanup 뒤 남은 참조를 세려고
`feature.features`로 들어오는 단일 컬럼 FK를 훑는다. 그때 대상 열이 무엇인지에 따라 소유
행을 `feature_id`(varchar)로 찾을지 `feature_uuid`(uuid)로 찾을지가 갈린다.

종전 helper는 "대상은 언제나 `feature_id`"라고 **단언만 했다.** 그 사실은 스키마에 결박돼
있지 않았고, `T-VN-M04`의 `0233`이 `ops.feature_requests.resolved_feature_id(uuid) →
feature.features.feature_uuid`를 넣으면서 조용히 무효화됐다. D2가 그 뒤로 돌지 않아
2026-09-05 실행에서야 드러났고, 그때는 이미 배포 스택 실행 13분을 태운 뒤였다.

이 게이트는 그 사실을 **탐지 가능**하게 만든다. 허용 집합을 helper 소스에서 **유도**하므로
한쪽만 바뀌면 여기서 깨진다 — 다음 migration이 세 번째 identity 열을 도입하면 CI가 잡고,
D2 실행 도중이 아니라 PR에서 드러난다(AGENTS.md DO NOT 15: 유도 → 결박 → 탐지).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = _ROOT / "alembic" / "baseline" / "schema.sql"
_HELPER = _ROOT / "scripts" / "admin_feature_live_fixture.py"

#: `ADD CONSTRAINT <name> FOREIGN KEY (<cols>) REFERENCES feature.features(<targets>)`
_FOREIGN_KEY = re.compile(
    r"ADD CONSTRAINT\s+(?P<name>\S+)\s+FOREIGN KEY\s*\((?P<columns>[^)]*)\)\s*"
    r"REFERENCES\s+feature\.features\s*\((?P<targets>[^)]*)\)",
    re.IGNORECASE,
)


def _single_column_targets() -> dict[str, str]:
    """단일 컬럼 FK만 골라 constraint 이름 → 대상 열 이름."""

    schema = _SCHEMA.read_text(encoding="utf-8")
    targets: dict[str, str] = {}
    for match in _FOREIGN_KEY.finditer(schema):
        columns = [value.strip() for value in match.group("columns").split(",")]
        references = [value.strip() for value in match.group("targets").split(",")]
        # composite FK는 helper가 이미 제외한다(`cardinality(conkey) = 1`).
        if len(columns) != 1 or len(references) != 1:
            continue
        targets[match.group("name")] = references[0]
    return targets


def _helper_identity_columns() -> set[str]:
    """helper가 실제로 처리하는 대상 열 집합을 **소스에서 유도**한다."""

    source = _HELPER.read_text(encoding="utf-8")
    match = re.search(
        r'target_column_name\s+not\s+in\s+\{(?P<members>[^}]*)\}', source
    )
    assert match is not None, (
        "helper의 identity 대상 집합을 찾지 못했다 — 이 게이트가 공허해졌다. "
        "`_foreign_key_reference_counts`의 검사 형태가 바뀌었으면 여기도 함께 고쳐라."
    )
    return set(re.findall(r'"([a-z_]+)"', match.group("members")))


def test_the_gate_reads_a_real_schema() -> None:
    """게이트가 실제 FK를 읽고 있는지부터 본다 — 0건이면 아래 단언이 공허하다."""

    targets = _single_column_targets()
    assert len(targets) >= 10, f"단일 컬럼 FK를 {len(targets)}건만 읽었다 — 파서를 의심하라"


def test_every_single_column_feature_fk_targets_a_handled_identity() -> None:
    """모든 단일 컬럼 FK의 대상이 helper가 다루는 identity 열이어야 한다."""

    handled = _helper_identity_columns()
    assert handled, "helper가 다루는 identity 집합이 비었다"
    unhandled = {
        name: target
        for name, target in _single_column_targets().items()
        if target not in handled
    }
    assert unhandled == {}, (
        "helper가 다루지 않는 identity 열을 가리키는 단일 컬럼 FK가 있다. "
        f"helper 처리 집합={sorted(handled)}, 위반={unhandled}. "
        "`scripts/admin_feature_live_fixture.py`의 `_foreign_key_reference_counts`가 "
        "그 열로도 소유 행을 찾도록 넓혀라 — **건너뛰지 마라.** 건너뛰면 cleanup 잔여물 "
        "탐지에 사각이 생긴다."
    )


def test_the_uuid_target_that_broke_this_is_still_covered() -> None:
    """이 게이트를 만들게 한 실제 사례가 계속 덮이는지 본다.

    `T-VN-M04`의 `0233`이 넣은 FK다. 회귀하면 D2가 다시 배포 스택 실행 도중에 죽는다.
    """

    targets = _single_column_targets()
    assert targets.get("feature_requests_resolved_feature_id_fkey") == "feature_uuid"
    assert "feature_uuid" in _helper_identity_columns()

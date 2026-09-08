"""purge 프로시저가 raise하는 제약이 전부 도메인 오류로 분류돼 있는지 본다.

admin state 경로에서 같은 부류의 누락이 **두 번** catch-all 500을 냈다 — 2026-08-12의
`ck_features_state_tuple`, 그리고 2026-09-08에 찾은 넷. 그때마다 원인은 같았다:
**분류를 잊는 것이 기본값**이었다.

여기서는 그 기본값을 처음부터 막는다. 이름을 두 벌 적지 않고 migration 원문에서
유도한다(AGENTS.md DO NOT 15) — 프로시저 본문이 정본이고 매핑이 그것을 따라간다.
"""

from __future__ import annotations

import pathlib
import re
from typing import Final

from kortravelmap.infra.manual_feature_purge_repo import (
    _PURGE_ERROR_BY_CONSTRAINT,
    PURGE_OPERATION,
)

_MIGRATION: Final[pathlib.Path] = (
    pathlib.Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "306_m02_manual_feature_purge.py"
)

_RAISED = re.compile(r"CONSTRAINT = '([a-z0-9_]+)'")


def _migration_text() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def test_the_migration_actually_raises_named_constraints() -> None:
    """유도가 비면 아래 분류 검사가 통째로 공허해진다."""

    raised = set(_RAISED.findall(_migration_text()))
    assert len(raised) >= 4, sorted(raised)
    assert "ck_manual_feature_purge_unauthorised" in raised


def test_every_constraint_the_purge_path_raises_is_classified() -> None:
    """분류를 잊으면 raw로 새고, 호출자는 그것을 500으로 본다."""

    text_body = _migration_text()
    # append-only 가드는 purge 경로의 오류가 아니다 — 그것은 "누가 증거를 고치려 했다"이고
    # 프로시저가 아니라 트리거가 낸다. purge 프로시저 본문에서 나오는 것만 본다.
    purge_body_start = text_body.index("_PURGE_PROCEDURE: Final[str]")
    purge_body_end = text_body.index("_COUNT_HELPER: Final[str]")
    from_procedure = set(_RAISED.findall(text_body[purge_body_start:purge_body_end]))

    fence_start = text_body.index("_PURGE_FENCE_UPGRADED: Final[str]")
    fence_end = text_body.index("_PURGE_FENCE_ORIGINAL: Final[str]")
    from_fence = set(_RAISED.findall(text_body[fence_start:fence_end]))

    reachable = from_procedure | from_fence
    assert reachable, "purge 경로에서 raise되는 제약을 하나도 찾지 못했다"
    unclassified = sorted(reachable - set(_PURGE_ERROR_BY_CONSTRAINT))
    assert not unclassified, (
        "purge 경로가 raise하는데 분류되지 않은 제약이 있다 — 호출자가 500으로 본다:"
        f" {unclassified}"
    )


def test_no_classified_name_is_absent_from_the_migration() -> None:
    """반대 방향 — 없는 제약을 분류해 두면 그 응답 계약은 영원히 발화하지 않는다."""

    raised = set(_RAISED.findall(_migration_text()))
    phantom = sorted(set(_PURGE_ERROR_BY_CONSTRAINT) - raised)
    assert not phantom, f"분류돼 있으나 migration에 없는 제약: {phantom}"


def test_the_operation_name_matches_the_procedure_contract() -> None:
    """operation 문자열이 갈리면 프로시저가 모든 호출을 거부한다 — 조용히, 항상."""

    assert f"'{PURGE_OPERATION}'" in _migration_text()

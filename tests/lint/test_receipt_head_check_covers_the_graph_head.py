"""receipt의 head CHECK가 현재 graph head를 **반드시** 포함하는지.

## 왜 필요한가

`ops.application_schema_operation_receipts.destination_head`에는 값 열거 CHECK가 있다.
baseline은 `'300'`만 허용했고, `301`이 자기 head를 더한다.

같은 표의 다른 CHECK 열 개는 전부 **형식** 검사다(`~ '^[0-9a-f]{64}$'` 등). head만
값 열거인 이유는 그 자리가 정확한 동등성을 요구하기 때문이고, 그 엄격함 자체는 옳다 —
DB 층 fail-close 하나를 형식 검사로 낮추면, executable·finalize·permit 셋이 모두
뚫렸을 때 마지막으로 남는 방어가 사라진다.

**문제는 열거가 아니라, 열거를 갱신할 의무를 아무것도 강제하지 않는다는 것이었다.**
migration을 하나 더하면서 이 CHECK를 잊으면 코드는 전부 통과하고, 프로덕션에서
fresh 설치가 `new row violates check constraint`로 죽는다. CI가 integration DB를
띄우지 않는 조합에서는 머지까지 아무도 못 본다.

여기서 그 의무를 정적으로 강제한다. 열거는 그대로 두고, 잊는 것만 막는다.

## 무엇을 보지 못하는가

- CHECK가 실제 DB에 적용됐는지 (integration이 본다)
- 열거에 **존재하지 않는 revision**이 섞이는 것 — 과잉은 해가 적어 막지 않는다
- baseline `schema.sql`의 원본 CHECK (재봉인 대상이라 여기서 다루지 않는다)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kortravelmap.infra.application_schema_head import (
    BASELINE_ROOT_REVISION,
    application_schema_head,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "alembic" / "versions"

_CONSTRAINT = "ck_application_schema_operation_receipts_head"
_ALLOWED = re.compile(
    r"ADD\s+CONSTRAINT\s+" + _CONSTRAINT + r"\s+CHECK\s*\(\s*destination_head\s+(.*?)\)",
    re.IGNORECASE | re.DOTALL,
)
_LITERAL = re.compile(r"'([^']+)'")


def _allowed_heads() -> tuple[str, ...]:
    """migration이 **마지막으로** 선언한 허용 head 집합.

    `_UPGRADE_STATEMENTS`와 `_DOWNGRADE_STATEMENTS`가 같은 파일에 있으므로 파일 안의
    마지막 선언을 그대로 믿으면 downgrade 쪽을 읽는다. upgrade 경로만 본다.
    """
    latest: tuple[str, ...] | None = None
    for path in sorted(VERSIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        upgrade_only = source.split("_DOWNGRADE_STATEMENTS", 1)[0]
        for match in _ALLOWED.finditer(upgrade_only):
            latest = tuple(_LITERAL.findall(match.group(1)))
    return latest or (BASELINE_ROOT_REVISION,)


def test_receipt_head_check_admits_the_current_graph_head() -> None:
    """**이 게이트의 본체.**

    현재 head가 허용 집합에 없으면 fresh 설치가 receipt를 쓰는 순간 죽는다.
    """
    head = application_schema_head()
    allowed = _allowed_heads()

    assert head in allowed, (
        f"현재 graph head `{head}`가 receipt head CHECK 허용 집합 {allowed}에 없다 — "
        f"새 migration의 `_UPGRADE_STATEMENTS`에 "
        f"`ADD CONSTRAINT {_CONSTRAINT} CHECK (destination_head IN (…, '{head}'))`을 "
        "더할 것. 잊으면 프로덕션 fresh 설치가 CHECK 위반으로 죽는다."
    )


def test_receipt_head_check_keeps_the_baseline_root() -> None:
    """baseline root도 남아 있어야 한다.

    `300`에서 멈춘 기존 설치의 receipt 행이 이미 존재한다. 열거에서 빼면 그 표가
    CHECK를 거짓으로 만든 채 남거나, `ALTER TABLE`이 실패한다.
    """
    assert BASELINE_ROOT_REVISION in _allowed_heads()


def test_the_check_is_a_value_enumeration_not_a_pattern() -> None:
    """열거를 형식 검사로 **낮추지** 못하게 한다.

    이 게이트가 생긴 뒤 "매번 갱신하기 번거로우니 `~ '^[0-9a-z]…'`로 바꾸자"는 유혹이
    생긴다. 그것은 갱신 의무를 없애는 대신 DB 층 fail-close를 없애는 거래다. 의무는
    이미 여기서 강제되므로 거래할 이유가 없다.
    """
    for path in sorted(VERSIONS.glob("*.py")):
        source = path.read_text(encoding="utf-8").split("_DOWNGRADE_STATEMENTS", 1)[0]
        for match in _ALLOWED.finditer(source):
            body = match.group(1)
            assert "~" not in body, (
                f"{path.name}: receipt head CHECK를 형식 검사로 낮췄다 — 정확한 head "
                "동등성은 DB 층에 남겨 둘 것"
            )
            assert _LITERAL.findall(body), f"{path.name}: 허용 head 리터럴이 없다"


@pytest.mark.parametrize("head", ["302_future", "0999"])
def test_the_gate_bites_when_a_new_head_is_not_admitted(head: str) -> None:
    """게이트가 실제로 무는지 — 허용되지 않은 head를 넣어 확인한다."""
    allowed = _allowed_heads()
    assert head not in allowed

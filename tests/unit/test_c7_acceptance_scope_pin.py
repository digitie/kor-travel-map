"""C7 인수 scope 상수가 migration과 live 스펙에서 같은 값인지 잠근다.

이 값은 두 언어에 나뉘어 있다 — migration이 카탈로그에 **선언**하고
(`alembic/versions/0224_c7_external_system_scope.py`), live 스펙이 그 선언을
**제출**한다(`e2e/live/_ops-c7-admin-api.ts`). 주석으로만 묶여 있으면 드리프트했을 때
증상이 "prod C7이 preview 422로 죽고 CI는 green"이다 — 이 저장소가 실제로 겪은,
피드백이 가장 늦은 실패 계급 그대로다(`docs/journal.md` 2026-08-19).

ADR-088 이후 제출 가능한 ``sync_scope``의 정본은 ``provider_dataset_operation_scopes``
선언이므로, 선언되지 않은 이름은 ``infra/feature_update_repo``의 exact join에서 0행이
되고 exact FK 4종도 그 행을 요구한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

_ROOT: Final = Path(__file__).resolve().parents[2]
_MIGRATION: Final = _ROOT / "alembic" / "versions" / "0224_c7_external_system_scope.py"
_TS_HELPER: Final = (
    _ROOT
    / "packages"
    / "kor-travel-map-admin"
    / "frontend"
    / "e2e"
    / "live"
    / "_ops-c7-admin-api.ts"
)


def _python_constant(name: str) -> str:
    """migration 모듈을 import하지 않고 리터럴만 읽는다(alembic 컨텍스트 불필요)."""
    tree = ast.parse(_MIGRATION.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if isinstance(target, ast.Name) and target.id == name:
                value = node.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
    raise AssertionError(f"{_MIGRATION.name}: {name} 문자열 리터럴이 없다")


def _typescript_constant(name: str) -> str:
    source = _TS_HELPER.read_text(encoding="utf-8")
    matched = re.search(rf'^export const {name} = "([^"]+)" as const;$', source, re.MULTILINE)
    assert matched is not None, f"{_TS_HELPER.name}: {name} 리터럴이 없다"
    return matched.group(1)


def test_external_system_constant_matches_between_migration_and_live_spec() -> None:
    assert _python_constant("C7_EXTERNAL_SYSTEM") == _typescript_constant("C7_EXTERNAL_SYSTEM")


def test_declared_sync_scope_is_the_canonical_external_system_form() -> None:
    external_system = _python_constant("C7_EXTERNAL_SYSTEM")
    from kortravelmap.core.sync_scope import parse_canonical_sync_scope

    scope = parse_canonical_sync_scope(f"external_system:{external_system}")
    assert scope.kind == "external_system"
    assert scope.external_system == external_system


def test_live_spec_derives_its_scope_from_the_same_prefix() -> None:
    """TS 쪽 scope 문자열이 상수 조합이라 손으로 갈릴 수 없다."""
    source = _TS_HELPER.read_text(encoding="utf-8")
    assert (
        "export const C7_KMA_SYNC_SCOPE =\n"
        "  `${EXTERNAL_SYSTEM_SYNC_SCOPE_PREFIX}${C7_EXTERNAL_SYSTEM}` as const;" in source
    ), "C7_KMA_SYNC_SCOPE가 상수 조합이 아니다 — 리터럴로 굳으면 드리프트를 잡을 수 없다"

"""쿼터성 실패가 step 재시도를 사지 못하게 하는 것을 **행동과 구조 양쪽에서** 결박한다.

두 종류의 단언이 있다.

- **행동** — 가짜 provider가 ``failure_kind="quota"``로 실패하면 asset 경계를
  빠져나가는 예외가 ``allow_retries=False``인 :class:`dagster.Failure`여야 하고,
  재시도 가능한 분류(``network``)는 **원 예외 그대로** 나가야 한다. 뒤쪽이 없으면
  이 변경은 "모든 실패의 재시도를 껐다"가 되어 H45가 해결한 것을 되돌린다.
- **구조** — ``FEATURE_LOAD_RETRY_POLICY``를 단 asset을 소스에서 **유도**해, 그
  전부가 쿼터 판정을 거치는 경계를 지나는지 본다. 36번째 asset이 그 경계를
  우회하면 여기서 빨개진다(AGENTS.md DO NOT 15: 유도 → 결박 → 탐지).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.dagster.quota_exhaustion import (
    quota_exhaustion_cause,
    raise_terminal_if_quota_exhausted,
)

from dagster import Failure

pytestmark = pytest.mark.unit

_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "kortravelmap" / "dagster"

#: 쿼터 판정을 실제로 부르는 함수 이름 — 이 심볼이 결박의 앵커다.
_GUARD_CALL = "raise_terminal_if_quota_exhausted"


class _QuotaExhausted(RuntimeError):
    """``python-kma-api``의 resultCode 22 예외 모양 — 분류를 속성으로 갖는다."""

    failure_kind = "quota"
    retryable = False


class _NetworkBlip(RuntimeError):
    """간헐 장애 — 재시도가 실제로 도움이 되는 쪽."""

    failure_kind = "network"
    retryable = True


class _Wrapped(RuntimeError):
    """asset 경계가 분류를 메시지로 녹여 다시 던지는 모양."""


# ---------------------------------------------------------------- 행동


def test_direct_quota_failure_becomes_a_terminal_dagster_failure() -> None:
    with pytest.raises(Failure) as caught:
        raise_terminal_if_quota_exhausted(_QuotaExhausted("resultCode 22"))
    assert caught.value.allow_retries is False


def test_quota_classification_survives_being_melted_into_a_message() -> None:
    """``ProviderDatasetRefreshFailure``가 문자열로 녹여도 ``__cause__``가 남는다.

    이것이 이 모듈이 문자열을 파싱하지 않는 이유다 — 연쇄를 걷는다.
    """

    cause = _QuotaExhausted("resultCode 22")
    try:
        raise _Wrapped(f"KMA provider refresh failed: {cause}") from cause
    except _Wrapped as wrapped:
        found = quota_exhaustion_cause(wrapped)
        assert found is cause
        with pytest.raises(Failure) as caught:
            raise_terminal_if_quota_exhausted(wrapped)
    assert caught.value.allow_retries is False


def test_retryable_failures_keep_their_retries() -> None:
    """과분류 방지. 여기가 빨개지면 H45가 고친 것을 되돌린 것이다."""

    blip = _NetworkBlip("gateway timeout")
    assert quota_exhaustion_cause(blip) is None
    raise_terminal_if_quota_exhausted(blip)  # 아무 일도 일어나지 않아야 한다


def test_unclassified_failures_keep_their_retries() -> None:
    """``failure_kind``가 없는 예외(파싱·계약 위반)는 건드리지 않는다."""

    assert quota_exhaustion_cause(ValueError("parse error")) is None


def test_a_cyclic_cause_chain_terminates() -> None:
    """실패 경로에서 무한 루프를 내면 원인 규명 자체가 불가능해진다."""

    first = RuntimeError("a")
    second = RuntimeError("b")
    first.__cause__ = second
    second.__cause__ = first
    assert quota_exhaustion_cause(first) is None


# ---------------------------------------------------------------- 구조


def _module_trees() -> dict[str, ast.Module]:
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(_PACKAGE.glob("*.py"))
    }


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _quota_guarded_functions() -> set[str]:
    """쿼터 판정을 직접 부르는 함수를 유도한다 — 목록을 손으로 적지 않는다."""

    guarded: set[str] = set()
    for tree in _module_trees().values():
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and (
                _GUARD_CALL in _called_names(node)
            ):
                guarded.add(node.name)
    return guarded


def _feature_load_assets() -> list[tuple[str, ast.AsyncFunctionDef | ast.FunctionDef]]:
    """``FEATURE_LOAD_RETRY_POLICY``를 단 asset을 소스에서 유도한다."""

    found: list[tuple[str, ast.AsyncFunctionDef | ast.FunctionDef]] = []
    for name, tree in _module_trees().items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                for keyword in decorator.keywords:
                    if keyword.arg == "retry_policy" and ast.unparse(
                        keyword.value
                    ).endswith("FEATURE_LOAD_RETRY_POLICY"):
                        found.append((name, node))
    return found


def test_the_derivation_actually_found_something() -> None:
    """항진명제 방지 — 유도가 비면 아래 단언이 무엇도 재지 못한다."""

    assets = _feature_load_assets()
    assert len(assets) >= 35, (
        f"재시도 정책을 단 asset을 {len(assets)}개만 찾았다 — 유도가 낡았다."
    )
    guarded = _quota_guarded_functions()
    assert guarded, (
        f"`{_GUARD_CALL}`를 부르는 함수를 하나도 찾지 못했다 — 결박이 사라졌다."
    )


@pytest.mark.parametrize(
    ("module", "asset_name", "calls"),
    [
        (module, node.name, _called_names(node))
        for module, node in _feature_load_assets()
    ],
    ids=[f"{module}:{node.name}" for module, node in _feature_load_assets()],
)
def test_every_retrying_asset_passes_through_the_quota_guard(
    module: str, asset_name: str, calls: set[str]
) -> None:
    """재시도 정책을 단 asset은 전부 쿼터 판정을 지나야 한다.

    ``max_retries=3``은 실패한 순회를 **세 번 더** 돌린다. 쿼터 소진에서는 그
    네 번이 전부 실패하도록 정해져 있다(한도는 다음 창에서 리셋된다) — 요청만
    네 배로 나간다. 2026-09-13 실측 분모로 그 크기가 보인다: KMA 격자 300 ×
    매시 = 7,200/일인데 오퍼레이션당 한도가 10,000이다. 한 번의 재시도 순환이
    그날 한도를 넘긴다.
    """

    guarded = _quota_guarded_functions()
    assert calls & guarded, (
        f"{module}의 `{asset_name}`이 쿼터 판정을 지나지 않는다. "
        f"이 asset은 `FEATURE_LOAD_RETRY_POLICY`(max_retries=3)를 달고 있어 "
        "쿼터성 실패 하나가 upstream 요청을 네 배로 만든다. "
        f"`{_GUARD_CALL}`를 부르는 경계를 지나게 하거나, 지나지 않아도 되는 "
        "이유를 acceptance에 먼저 적어라."
    )


def test_the_guard_is_not_bypassed_by_an_unimported_symbol() -> None:
    """부르는 이름이 실제로 이 모듈에서 온 것인지 본다.

    이름만 같고 다른 것을 부르면 위 단언은 초록인데 아무 일도 일어나지 않는다.
    """

    importers = {
        name
        for name, tree in _module_trees().items()
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and any(alias.name == _GUARD_CALL for alias in node.names)
    }
    assert importers, f"`{_GUARD_CALL}`를 import하는 모듈이 없다"
    assert "feature_operation_tracking.py" in importers, (
        "single-member asset 34개가 지나는 경계가 쿼터 판정을 import하지 않는다"
    )
    assert "mcst_features.py" in importers, (
        "multi-member asset(mcst)이 쿼터 판정을 import하지 않는다"
    )


def test_the_guard_module_reuses_the_declared_nonretryable_set() -> None:
    """분류 집합의 정본은 하나여야 한다 — 층마다 다른 집합을 두면 둘이 된다."""

    source = (_PACKAGE / "quota_exhaustion.py").read_text(encoding="utf-8")
    assert "from .upstream_retry import NONRETRYABLE_FAILURE_KINDS" in source, (
        "쿼터 분류 집합을 이 모듈이 따로 정의하면 `upstream_retry`와 갈라진다."
    )


def test_the_terminal_failure_names_what_it_suppressed() -> None:
    """사후 판독이 이벤트 로그만으로 가능해야 한다."""

    with pytest.raises(Failure) as caught:
        raise_terminal_if_quota_exhausted(_QuotaExhausted("resultCode 22"))
    metadata: dict[str, Any] = dict(caught.value.metadata)
    assert "failure_kind" in metadata
    assert "step_retries_suppressed" in metadata

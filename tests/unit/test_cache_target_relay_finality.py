"""#975 적대 재리뷰 P2 — relay 종결성 규칙 회귀.

이 규칙의 핵심은 "예외 클래스 하나로 분기하지 않는다"이다. 클래스만 보고 억제하면
generation 전진·fingerprint 변경·head 소멸까지 relay 종결 event가 사라져 PinVi가 요청의
끝을 못 본다. 억제 근거를 가진 것은 restore fence 이동뿐이다(runbook §5-5).

여기서는 DB 없이 고정 가능한 두 가지를 본다 — reason 어휘와, executor/취소 서비스가
그 reason으로 분기한다는 사실.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from kortravelmap.infra.cache_target_event_repo import (
    CacheTargetRefreshProtocolViolation,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_violation_carries_typed_reason() -> None:
    """reason 없이 만들 수 없다 — 클래스만 보고 분기하던 시절로 돌아가지 못하게."""
    violation = CacheTargetRefreshProtocolViolation(
        "테스트",
        reason=CacheTargetRefreshProtocolViolation.GENERATION_ADVANCED,
    )
    assert violation.reason == "generation_advanced"
    with pytest.raises(TypeError):
        CacheTargetRefreshProtocolViolation("reason 없이")  # type: ignore[call-arg]


def test_reason_vocabulary_is_exact() -> None:
    """네 원인이 각각 이름을 갖는다. 빈 어휘면 아래 검사가 자명하게 통과한다."""
    reasons = {
        CacheTargetRefreshProtocolViolation.EPOCH_MOVED,
        CacheTargetRefreshProtocolViolation.GENERATION_ADVANCED,
        CacheTargetRefreshProtocolViolation.FINGERPRINT_CHANGED,
        CacheTargetRefreshProtocolViolation.HEAD_MISSING,
    }
    assert reasons == {
        "epoch_moved",
        "generation_advanced",
        "fingerprint_changed",
        "head_missing",
    }


def _raise_reasons(path: Path) -> list[str]:
    """모듈 안 `CacheTargetRefreshProtocolViolation(...)` raise의 reason 인자를 모은다."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Raise) or node.exc is None:
            continue
        call = node.exc
        if not isinstance(call, ast.Call):
            continue
        name = call.func
        if not (
            isinstance(name, ast.Name)
            and name.id == "CacheTargetRefreshProtocolViolation"
        ):
            continue
        kw = {k.arg: k.value for k in call.keywords}
        reason = kw.get("reason")
        if isinstance(reason, ast.Attribute):
            found.append(reason.attr)
        else:
            found.append("<no-reason>")
    return found


def test_every_raise_site_supplies_a_reason() -> None:
    """raise 지점이 하나라도 reason을 빼면 호출자 분기가 조용히 무너진다."""
    path = _ROOT / "src/kortravelmap/infra/cache_target_event_repo.py"
    reasons = _raise_reasons(path)
    assert len(reasons) >= 4, f"raise 지점이 너무 적다: {reasons}"
    assert "<no-reason>" not in reasons, f"reason 없는 raise: {reasons}"
    # 네 원인이 모두 실제로 쓰인다
    assert {"EPOCH_MOVED", "GENERATION_ADVANCED", "FINGERPRINT_CHANGED", "HEAD_MISSING"} <= set(
        reasons
    ), reasons


def test_executor_suppresses_only_epoch_moved() -> None:
    """억제 판단이 `reason == EPOCH_MOVED`에 걸려 있는지 — 클래스 isinstance면 회귀다."""
    from kortravelmap.infra import feature_update_executor

    source = inspect.getsource(feature_update_executor)
    assert "EPOCH_MOVED" in source, "억제 판단이 reason을 보지 않는다"
    assert "not isinstance(\n                exc, CacheTargetRefreshProtocolViolation\n            )" not in source, (
        "예외 클래스 전체를 억제하던 옛 규칙이 되살아났다"
    )


def test_cancellation_service_uses_the_shared_helper_on_both_paths() -> None:
    """queued/running 두 경로가 같은 헬퍼를 부르는지 — 한쪽만 있으면 종결 event가 샌다."""
    path = (
        _ROOT
        / "packages/kor-travel-map-api/src/kortravelmap/api/pipeline_cancellation_service.py"
    )
    source = path.read_text(encoding="utf-8")
    calls = source.count("await _append_cache_target_terminal_relay_event(")
    assert calls == 2, f"헬퍼 호출이 2곳이어야 한다(queued/running): {calls}"
    assert "EPOCH_MOVED" in source, "삼킴이 reason으로 gate되지 않는다"

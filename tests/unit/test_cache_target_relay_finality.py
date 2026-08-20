"""#975 적대 재리뷰 P2 — relay 종결성 규칙 회귀.

이 규칙의 핵심은 "예외 클래스 하나로 분기하지 않는다"이다. 클래스만 보고 억제하면
generation 전진·fingerprint 변경·head 소멸까지 relay 종결 event가 사라져 PinVi가 요청의
끝을 못 본다. 억제 근거를 가진 것은 restore fence 이동뿐이다(runbook §5-5).

**이 파일의 첫 판은 공허했다.** 판정을 소스 문자열로 확인해서, 규칙을 완전히 되돌려도
초록이었다(적대 리뷰 P2, 리뷰어가 실측). 그래서 판정을 순수 함수
``suppresses_relay_finalization``으로 뽑고 여기서는 **값으로** 검사한다 — 규칙을 되돌리면
반드시 red다.
"""

from __future__ import annotations

import copy
import pickle

import pytest

from kortravelmap.infra.cache_target_event_repo import (
    CacheTargetRefreshProtocolViolation,
)
from kortravelmap.infra.feature_update_executor import (
    suppresses_relay_finalization,
)

pytestmark = pytest.mark.unit

_NON_EPOCH_REASONS = (
    CacheTargetRefreshProtocolViolation.GENERATION_ADVANCED,
    CacheTargetRefreshProtocolViolation.FINGERPRINT_CHANGED,
    CacheTargetRefreshProtocolViolation.HEAD_MISSING,
)


def test_reason_vocabulary_is_exact() -> None:
    """네 원인이 각각 이름을 갖는다. 빈 어휘면 아래 검사가 자명하게 통과한다."""
    assert {
        CacheTargetRefreshProtocolViolation.EPOCH_MOVED,
        *_NON_EPOCH_REASONS,
    } == {
        "epoch_moved",
        "generation_advanced",
        "fingerprint_changed",
        "head_missing",
    }


def test_only_epoch_moved_suppresses_relay_finalization() -> None:
    """규칙 자체를 값으로 고정한다 — 되돌리면 여기서 red다."""
    epoch = CacheTargetRefreshProtocolViolation(
        "fence moved", CacheTargetRefreshProtocolViolation.EPOCH_MOVED
    )
    assert suppresses_relay_finalization(epoch) is True

    for reason in _NON_EPOCH_REASONS:
        violation = CacheTargetRefreshProtocolViolation("stale", reason)
        assert suppresses_relay_finalization(violation) is False, reason


def test_unrelated_exception_with_a_reason_attribute_does_not_suppress() -> None:
    """duck typing이던 시절 `.reason`을 가진 남의 예외가 판정에 끼어들 수 있었다.

    표준 라이브러리만 해도 `ssl.SSLError`·`UnicodeDecodeError`·`URLError`가 `.reason`을
    갖는다. `isinstance` 좁히기가 사라지면 이 검사가 red가 된다.
    """

    class _Impostor(RuntimeError):
        reason = CacheTargetRefreshProtocolViolation.EPOCH_MOVED

    assert suppresses_relay_finalization(_Impostor("남의 예외")) is False
    assert suppresses_relay_finalization(ValueError("무관")) is False


def test_violation_round_trips_through_pickle_and_copy() -> None:
    """예외는 프로세스 경계를 넘을 수 있어야 한다 — keyword-only 필수 인자면 깨진다."""
    original = CacheTargetRefreshProtocolViolation(
        "generation advanced",
        CacheTargetRefreshProtocolViolation.GENERATION_ADVANCED,
    )
    revived = pickle.loads(pickle.dumps(original))
    assert revived.reason == CacheTargetRefreshProtocolViolation.GENERATION_ADVANCED
    assert str(revived) == str(original)
    assert copy.copy(original).reason == original.reason


def test_running_cancel_relay_status_is_not_folded() -> None:
    """`done`을 `failed`로 접던 매핑이 되살아나면 red.

    `_terminal_mapping`이 주는 `target_status`는 {cancelled, done, failed} 셋이고 셋 다
    `CacheTargetRefreshStatus`에 있다. 처음 구현이 `done`을 `failed`로 접어, ledger가
    `done`으로 커밋한 같은 transaction에서 PinVi에 `failed`를 보냈다(적대 리뷰 P1, 검증됨).
    """
    from typing import get_args

    from kortravelmap.api.pipeline_cancellation_service import _terminal_mapping

    from kortravelmap.infra.cache_target_event_repo import CacheTargetRefreshStatus

    allowed = set(get_args(CacheTargetRefreshStatus))
    seen: set[str] = set()
    for terminal in ("CANCELED", "SUCCESS", "FAILURE"):
        _run_result, _stored, target_status, _error = _terminal_mapping(terminal)
        seen.add(target_status)
        assert target_status in allowed, (terminal, target_status)
    # 셋이 서로 다른 값이어야 접기(fold)가 없다는 뜻이다.
    assert len(seen) == 3, seen

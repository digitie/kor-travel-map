"""쿼터 소진은 재시도로 낫지 않는다 — asset 경계에서 step 재시도를 끈다.

``FEATURE_LOAD_RETRY_POLICY``는 ``max_retries=3``이다. 즉 step 하나가 실패하면
Dagster가 60·120·240초 간격으로 **같은 순회를 세 번 더** 돌린다. 그 정책은 간헐
5xx·게이트웨이 timeout을 겨냥한 것이고 그 자리에서는 옳다.

쿼터 소진에서는 옳지 않다. ``python-kma-api``가 그 성질을 자기 소스에 적어 두었다 —
``resultCode 22``는 일일 요청 한도 초과이고 **한도는 자정에 리셋**되므로 같은 날
재시도는 몇 번을 해도 같은 코드를 받는다(``kma/_http.py``). 그래서 네 번째 순회까지
가는 동안 성공 확률은 0인데 요청과 벽시계는 **네 배**로 나간다.

``upstream_retry``가 이미 같은 판단을 **호출 한 건** 수준에서 내리고 있다
(:data:`~.upstream_retry.NONRETRYABLE_FAILURE_KINDS`). 빠져 있던 것은 그 위층 —
**step 재시도**다. 안쪽에서 "이건 재시도해도 소용없다"고 판정한 실패가 바깥에서
세 번 더 순회를 사는 모순이 있었다.

**이 기제가 실재한다는 근거.** Dagster 1.13.18
``_core/execution/plan/utils.py``의 ``user_code_error_boundary``가 그 자리다::

    if retry_policy:
        # if Failure with allow_retries set to false, disregard retry policy and raise
        if isinstance(e, Failure) and not e.allow_retries:
            raise e
        raise RetryRequestedFromPolicy(...)

즉 ``allow_retries=False``가 ``RetryPolicy``를 **이긴다**. 그리고 그 위의
``except DagsterError as de: raise de``가 먼저 잡지 않는다 — ``Failure``의 MRO는
``(Failure, Exception, BaseException, object)``라 ``DagsterError``가 아니다(실측).

그 경계가 asset 본문을 실제로 감싼다: ``plan/compute.py``가 사용자 generator를
``iterate_with_context(lambda: op_execution_error_boundary(...), user_event_generator)``
로 돌린다. async asset은 ``gen_from_async_gen``을 한 겹 지나지만 같은 경계 안이다.

따라서 **그냥 ``Failure``를 던지는 것으로는 부족하다.** ``allow_retries``의 기본값은
``True``이고(``events.py``: ``check.opt_bool_param(allow_retries, ..., True)``) 그때는
정책이 그대로 세 번 더 돌린다. 이 모듈이 그 인자를 명시하는 이유다.

run 수준 재시도는 별개 축인데 이 배포에는 없다 — ``docker/dagster.yaml``에
``run_retries`` 블록이 없고 ``run_monitoring.max_resume_run_attempts``는 0이다.

**분류를 문자열에서 되찾지 않는다.** asset 경계는 provider 예외를
``ProviderDatasetRefreshFailure``로 감싸면서 ``failure_kind``를 메시지 문자열로
녹인다(``message=f"KMA provider refresh failed: {exc}"``). 그러나 그 자리는
``raise failure from cause``이므로 원 예외가 ``__cause__``에 남는다. 여기서는 그
연쇄를 걷는다 — 메시지를 파싱하면 provider가 문구를 바꾸는 날 조용히 빗나간다.

**``rate_limit``도 같이 끈다 — 그리고 그 교환을 적어 둔다.** 분 단위 429는 60초
뒤에 풀릴 수도 있으니 step 재시도가 도움이 되는 경우가 있다. 그래도 같은 집합을
쓰는 이유는 둘이다. (1) ``NONRETRYABLE_FAILURE_KINDS``가 이 저장소의 선언된 쿼터
보호 정본이고, 층마다 다른 집합을 두면 정본이 둘이 된다. (2) 손실이 묶여 있다 —
정기 schedule이 다음 주기에 다시 오므로 재시도를 잃어 늦어지는 최대치는 schedule
간격 하나다. 반대로 일일 쿼터에 재시도를 켜 두면 **매번** 네 배를 낸다.
"""

from __future__ import annotations

from dagster import Failure

from .upstream_retry import NONRETRYABLE_FAILURE_KINDS

__all__ = [
    "quota_exhaustion_cause",
    "raise_terminal_if_quota_exhausted",
]


def quota_exhaustion_cause(exc: BaseException) -> BaseException | None:
    """예외 연쇄에서 쿼터성 분류를 가진 원 예외를 찾는다.

    ``__cause__``(명시적 ``raise ... from``)를 먼저 보고 없으면
    ``__context__``(암묵 연쇄)를 따라간다. 순환 연쇄에서 멈추도록 방문한 예외를
    기억한다 — 실제로 순환을 만든 코드는 없지만, 이 함수는 실패 경로에서만
    도므로 여기서 무한 루프를 내면 원인 규명 자체가 불가능해진다.
    """

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "failure_kind", None) in NONRETRYABLE_FAILURE_KINDS:
            return current
        current = current.__cause__ or current.__context__
    return None


def raise_terminal_if_quota_exhausted(exc: BaseException) -> None:
    """쿼터성 실패면 step 재시도를 끈 :class:`dagster.Failure`로 바꿔 던진다.

    쿼터성이 아니면 **아무것도 하지 않는다** — 호출자가 원 예외를 그대로
    재던져 기존 실패 분류 경로를 탄다. 간헐 장애의 재시도는 그대로 남는다.
    """

    cause = quota_exhaustion_cause(exc)
    if cause is None:
        return
    failure_kind = str(getattr(cause, "failure_kind", ""))
    raise Failure(
        description=(
            f"upstream 쿼터 소진({failure_kind}) — step 재시도를 끈다. "
            "한도는 다음 창(data.go.kr은 자정 KST)에서 리셋되므로 같은 run 안의 "
            "재시도는 성공할 수 없고 요청만 늘린다. 다음 schedule이 다시 온다. "
            f"원 예외: {type(cause).__name__}: {cause}"
        ),
        metadata={
            "failure_kind": failure_kind,
            "provider_error": type(cause).__name__,
            "step_retries_suppressed": "true",
        },
        allow_retries=False,
    ) from exc

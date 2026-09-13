"""일일 쿼터 소진은 재시도로 낫지 않는다 — asset 경계에서 step 재시도를 끈다.

``FEATURE_LOAD_RETRY_POLICY``는 ``max_retries=3``이다. 즉 step 하나가 실패하면
Dagster가 60·120·240초 간격으로 같은 순회를 세 번 더 돌린다. 그 정책은 간헐
5xx·게이트웨이 timeout을 겨냥한 것이고 그 자리에서는 옳다.

**일일 쿼터 소진에서는 옳지 않다.** ``python-kma-api``가 그 성질을 자기 소스에 적어
두었다 — ``resultCode 22``는 일일 요청 한도 초과이고 **한도는 자정에 리셋**되므로
같은 날 재시도는 몇 번을 해도 같은 코드를 받는다(``kma/_http.py``).

**무엇을 아끼는가 — 정확히.** 처음에 이 자리에 "요청이 네 배로 나간다"고 적었다.
**그것이 틀렸다**(적대 리뷰 지적). 쿼터가 소진된 뒤의 재시도는 **첫 격자에서
즉사한다** — ``kma_weather``의 격자 루프는 항상 ``grids[0]``부터 다시 시작하고
(성공 cursor는 루프 완주 뒤에만 전진한다) 그 첫 호출이 곧바로 code 22를 받는다.
그래서 재시도 3회가 사는 것은 순회 3벌이 아니라 **요청 3건**이다. 실제로 아끼는
것은 이것이다:

- 성공할 수 없는 upstream 요청 **3건** (그날 이미 넘긴 한도를 더 넘긴다)
- step backoff **420초**(60+120+240)와 그동안의 **큐 슬롯 점유 3회**
- 실패 attempt 기록 3건 — 사후 판독에서 원인 하나가 넷으로 보이던 것

요청 수가 네 배가 되는 것은 순회 **도중** 나는 *재시도 가능한* 실패(H45가 겨냥한
쪽)이고, 이 모듈은 그쪽을 건드리지 않는다.

**HTTP 429는 여기서 제외한다.** 초·분 단위 throttle은 60초 뒤 재시도가 거의 확실히
성공하는데, 이 저장소 schedule 다수가 **월 1회**다 — 429 한 번에 재시도를 끄면 그
asset은 **한 달** 갱신되지 않는다. provider lib들이 429와 resultCode 22에 같은
``failure_kind="rate_limit"``를 붙이므로(visitkorea·mcst·krforest 실측) 분류
문자열만으로는 둘을 가를 수 없고, 대신 예외가 들고 있는 HTTP 상태를 본다.

**``failure_kind``가 없는 provider가 절반이다.** 그 속성을 예외에 붙이는 lib은
kma·krforest·visitkorea·kasi·khoa·mcst·enckc·krbluelink·knps이고
airkorea·datagokr·krairport·krex·opinet·krheritage·mois·vworld는 붙이지 않는다
(knps는 붙이지만 쿼터 분류는 쓰지 않는다 — network/auth 등만 단다).
그래서 속성 하나에만 걸면 **가장 좁은 분모에서 한 번도 발화하지 않는다** —
에어코리아가 오퍼레이션당 500/일이다(``docs/etl/upstream-quota.md``). 그 구멍을
:data:`QUOTA_EXCEPTION_TYPES`가 메운다.

**이 기제가 실재한다는 근거.** Dagster 1.13.18 ``_core/execution/plan/utils.py``의
``op_execution_error_boundary``가 그 자리다::

    if retry_policy:
        # if Failure with allow_retries set to false, disregard retry policy and raise
        if isinstance(e, Failure) and not e.allow_retries:
            raise e
        raise RetryRequestedFromPolicy(...)

즉 ``allow_retries=False``가 ``RetryPolicy``를 **이긴다**. 그 위의
``except DagsterError as de: raise de``가 먼저 잡지도 않는다 — ``Failure``의 MRO는
``(Failure, Exception, BaseException, object)``라 ``DagsterError``가 아니다(실측).
그리고 그 경계가 asset 본문을 감싼다: ``plan/compute.py``가 사용자 generator를
``iterate_with_context(lambda: op_execution_error_boundary(...), ...)``로 돌린다.
async asset은 ``gen_from_async_gen``을 한 겹 지나지만 같은 경계 안이다.

따라서 **그냥 ``Failure``를 던지는 것으로는 부족하다.** ``allow_retries``의 기본값은
``True``이므로 그때는 정책이 그대로 세 번 더 돌린다.

run 수준 재시도는 별개 축인데 이 배포에는 없다 — ``docker/dagster.yaml``에
``run_retries`` 블록이 없고 ``run_monitoring.max_resume_run_attempts``는 0이다.

**분류를 문자열에서 되찾지 않는다.** asset 경계는 provider 예외를
``ProviderDatasetRefreshFailure``로 감싸면서 ``failure_kind``를 메시지 문자열로
녹인다. 그러나 그 자리는 ``raise failure from cause``이므로 원 예외가
``__cause__``에 남는다. 여기서는 그 연쇄를 걷는다.
"""

from __future__ import annotations

from typing import Final

from dagster import Failure

from .upstream_retry import NONRETRYABLE_FAILURE_KINDS

__all__ = [
    "QUOTA_EXCEPTION_TYPES",
    "quota_exhaustion_cause",
    "raise_terminal_if_quota_exhausted",
]

#: HTTP 상태를 실어 나르는 속성 이름 — provider lib마다 다르다(실측: visitkorea·kma·
#: opinet은 ``status_code``, krex는 ``http_status``).
_HTTP_STATUS_ATTRIBUTES: Final[tuple[str, ...]] = ("status_code", "http_status")

#: ``failure_kind``를 붙이지 않는 lib의 쿼터 예외 — ``(top-level 모듈, 클래스 이름)``.
#:
#: 모듈까지 함께 보는 이유는 이름이 겹치기 때문이다(krheritage의 ``RateLimitError``는
#: 한 단어짜리 이름이다). 클래스를 직접 import하지 않는 이유는 이 판정이 **실패
#: 경로에서만** 돌기 때문이다 — 여기서 provider 패키지를 import하면 실패 원인 규명이
#: import 오류로 바뀔 수 있다. 실물 lib과의 계약은 contract 테스트가 고정한다.
#:
#: **여기 없는 것과 그 이유:**
#:
#: - ``krheritage.RateLimitError`` — upstream 신호가 아니다. docstring이
#:   "local rate limiting cannot schedule a request"이고 lib 안에서 raise되는 자리가
#:   없다. krheritage는 쿼터 소진을 **알려 주지 않는다** — acceptance가 든
#:   "4 × ~3,950 = 15,800요청"은 이 기제로 닫히지 않는다.
#: - ``krairport.KrairportRateLimitError`` — 429와 resultCode를 같은 타입으로 던지며
#:   **어느 쪽인지 알려 주는 속성이 없다**(``_http.py:208``/``:225``). 가를 수단이
#:   없어 넣지 않는다.
#: - ``datagokr`` · ``mois`` · ``krmois`` — 쿼터 전용 예외 자체가 없다.
QUOTA_EXCEPTION_TYPES: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        # 429와 본문 LIMIT 마커를 같은 타입으로 던지고 속성이 없다. 그런데 airkorea
        # schedule은 매시라 429를 쿼터로 오인해도 손실이 **한 시간**으로 묶인다.
        # 이 저장소는 이미 이 예외가 "코드 22 — 일일 쿼터 소진"임을 알고 재시도에서
        # 제외해 두었다(``provider_fetchers.AIRKOREA_RETRYABLE_EXCEPTION_NAMES``).
        ("airkorea", "AirKoreaRateLimitError"),
        # 429에는 ``http_status``가 붙고 EXCEEDED_LIMIT/code 22에는 붙지 않는다 —
        # 아래 429 판정이 둘을 가른다.
        ("krex", "KrexQuotaExceededError"),
        # HTTP 경로에 ``status_code``가 붙는다. 같은 이유로 429는 걸러진다.
        ("opinet", "OpinetRateLimitError"),
    }
)


def _http_status(exc: BaseException) -> int | None:
    """예외가 들고 있는 HTTP 상태. 없으면 ``None``."""

    for name in _HTTP_STATUS_ATTRIBUTES:
        value = getattr(exc, name, None)
        if isinstance(value, int):
            return value
    return None


def _declares_quota_identity(exc: BaseException) -> bool:
    """``(모듈, 클래스)`` 선언 집합에 걸리는가 — MRO 전체를 본다."""

    for klass in type(exc).__mro__:
        module = getattr(klass, "__module__", "").split(".", 1)[0]
        if (module, klass.__name__) in QUOTA_EXCEPTION_TYPES:
            return True
    return False


def _is_daily_quota_exhaustion(exc: BaseException) -> bool:
    """이 예외가 **다음 창까지 회복되지 않는** 한도 초과인가.

    HTTP 429는 아니다 — 초·분 단위로 풀리고, 이 저장소 schedule의 다수가 월 1회라
    거기서 재시도를 끄면 한 달을 잃는다.
    """

    if _http_status(exc) == 429:
        return False
    if getattr(exc, "failure_kind", None) in NONRETRYABLE_FAILURE_KINDS:
        return True
    return _declares_quota_identity(exc)


def quota_exhaustion_cause(exc: BaseException) -> BaseException | None:
    """예외 연쇄에서 일일 쿼터 소진을 뜻하는 원 예외를 찾는다.

    ``__cause__``(명시적 ``raise ... from``)를 먼저 보고 없으면
    ``__context__``(암묵 연쇄)를 따라간다. 순환 연쇄에서 멈추도록 방문한 예외를
    기억한다 — 이 함수는 실패 경로에서만 도므로 여기서 무한 루프를 내면 원인 규명
    자체가 불가능해진다.
    """

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if _is_daily_quota_exhaustion(current):
            return current
        current = current.__cause__ or current.__context__
    return None


def raise_terminal_if_quota_exhausted(exc: BaseException) -> None:
    """일일 쿼터 소진이면 step 재시도를 끈 :class:`dagster.Failure`로 바꿔 던진다.

    아니면 **아무것도 하지 않는다** — 호출자가 원 예외를 그대로 재던져 기존 실패
    분류 경로를 탄다. 간헐 장애와 HTTP 429의 재시도는 그대로 남는다.
    """

    cause = quota_exhaustion_cause(exc)
    if cause is None:
        return
    failure_kind = str(getattr(cause, "failure_kind", "") or "unclassified")
    raise Failure(
        description=(
            f"upstream 일일 쿼터 소진({failure_kind}) — step 재시도를 끈다. "
            "한도는 다음 창(data.go.kr은 자정 KST)에서 리셋되므로 같은 run 안의 "
            "재시도는 성공할 수 없고 요청만 더 쓴다. 다음 schedule이 다시 온다. "
            f"원 예외: {type(cause).__name__}: {cause}"
        ),
        metadata={
            "failure_kind": failure_kind,
            "provider_error": type(cause).__name__,
            "provider_module": type(cause).__module__.split(".", 1)[0],
            "step_retries_suppressed": "true",
        },
        allow_retries=False,
    ) from exc

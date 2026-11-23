"""upstream provider 단건 호출의 유한 재시도 (T-VN-H45).

data.go.kr 계열 upstream은 간헐 지연·5xx·게이트웨이 timeout이 일상이라, N건을
순차 호출하는 asset이 "예외 즉시 step 실패 → step 전량 재시도"만 가지면 시도당
생존 확률이 p^N으로 붕괴한다(H45 실측: KMA 격자 187+건 run이 단건 프로브 정상
상태에서도 매 주기 실패 — prod run 스택은 ``raise_for_kma_network_error``
= ``retryable=True`` network 분류였다).

**재시도 레이어 정산(적대 리뷰 1·2 H 반영)**: provider lib은 이미 transport
재시도를 소유한다(kma ``get_with_retries``·airkorea ``HttpClient`` — 기본
retries=3 → 4 HTTP 시도). 본 모듈은 그 위의 **두 번째** 레이어이므로 곱셈을
통제한다:

- 기본 attempts는 **2**(추가 1회) — 호출 지점은 client에 ``retries=1``을 함께
  주입해 총 HTTP 시도 상한을 경계당 2×2=4로 유지한다(레이어 도입 전 lib 단독
  4와 동일).

**attempts는 시도 횟수의 상한이지 시간의 상한이 아니다.** 종전 이 자리에 "timeout
20s 기준 경계당 최악 wall ≈ 84s, 187격자 병적 상한 ≈ 4.4h < dagster run 한도 6h"를
적어 두었는데 그 부등식은 **양변이 틀렸다**(2026-09-12 정정).

- 좌변: 호출측이 넘기는 timeout은 httpx 스칼라이고, httpx는 그것을
  connect/read/write/pool **각각에** 복사한다. 그중 read timeout은 소켓 read마다
  **재무장되는 간격 상한**이다(``httpcore``의 ``while True: read(..., timeout=...)``) —
  호출 전체의 deadline이 아니다. 19초마다 1바이트를 흘리는 연결은 어떤 시도도
  끝내지 못하므로 재시도 예산이 소진되지 않는다. 이 모듈에는 코루틴 수준 상한
  (``asyncio.timeout``/``wait_for``)이 없다. 형제 저장소 ``kor-travel-weather``가
  같은 것을 값을 치르고 배웠다 — "``client_timeout``은 HTTP 클라이언트 설정이고
  이 코루틴에 대한 deadline이 아니다".
- 우변: 당시 KMA job이 받는 상한은 6h가 아니라 job tag ``dagster/max_runtime`` = 7200초였다.
  그리고 격자 기본값은 187이 아니라 300(최대 500)이었다. (KMA 경로는 2026-10-01
  ADR-104로 Map Dagster에서 제거됐다 — 이 단락은 계산 방식의 기록으로 남긴다.)

**그리고 요청당 시간은 상수가 아니다.** 형제 저장소가 2026-09-12에 그것을 값을
치르고 측정했다 — 무료 티어 쿼터를 초과해 throttle되자 요청이 ~0.3초에서 12~17초로
**40~50배** 늘어났고, 그래서 *성공한* 순회도 4~13시간이 걸렸다. 매시 도착하는 일이
여섯 시간 걸리면 큐는 반드시 찬다. 그쪽 결론이 이것이다 — "**It was arithmetic, not
a hang.**" ``run_monitoring``은 프로세스가 죽은 run을 실패시키는데 throttle된 run은
살아서 일하고 있다.

즉 어떤 벽시계 추정도 **어느 구간을 가정했는지** 함께 적어야 한다. 쿼터 안에서 도는
것과 초과해 throttle된 것은 같은 코드의 두 다른 세계다. 그리고 그 세계를 바꾸는 것은
timeout이 아니라 **덜 걷거나 덜 자주 걷는 것**뿐이다.

**실제로 강제되는 시간 상한은 run 층뿐이다** — job의 ``dagster/max_runtime`` tag,
없으면 ``docker/dagster.yaml``의 ``run_monitoring.max_runtime_seconds``. 그 회수는
프로세스 생존과 무관하다: ``check_run_timeout``이 ``terminate`` 성공 여부를 보지 않고
try 밖에서 ``_force_mark_as_failed``를 호출하므로, 소켓에 붙어 있는 run도 FAILURE가
되고 큐 슬롯이 풀린다. 그래서 여기서 여유를 계산하지 않는다 — 여유가 있다고 믿고
격자 수나 backoff를 올리면 7200초 tag에 먼저 걸리고, 그때 cursor는 전진하지 않아
같은 작업을 매 주기 반복한다.
- **쿼터/레이트리밋은 재시도하지 않는다**: 일일 쿼터 소진(kma resultCode 22 —
  ``failure_kind="quota"``/``"rate_limit"``)은 transient가 아니고, 재시도는
  쿼터 구멍만 키운다(provider별 run당 호출 상한의 일일 한도 보호 취지).
  lib이 ``retryable=True``로 분류해도 여기서 걸러낸다.
- **run 예산**(:class:`RetryBudget`): 상관 장애(전 격자 동시 열화)에서는 건별
  재시도가 무력하므로, run당 재시도 총량을 소진하면 이후 retryable 실패도
  즉시 전파해 run을 빨리 실패시킨다(early abort). 예산은 호출 경계 수에
  비례하되 설정 가능한 하한과 안전 상한으로 묶는다.
- 분류: kma 계열은 예외의 ``retryable`` 속성, 타 provider는 호출측
  ``is_retryable``로 타입 명시. 미분류(파싱·인증·계약 위반)는 즉시 전파 —
  fail-close 유지.
- 부분 실행 금지 불변식은 그대로다: attempts 소진 시 **원 예외를 원형
  그대로** 재던져 기존 실패 분류 경로를 탄다.
- backoff는 지수(2^n)·상한 capped다(sleep은 호출 시점 late-binding —
  ``time.sleep``/``asyncio.sleep`` module-global 조회라 테스트에서 module
  단위 대체 가능). 동기 :func:`retry_upstream`의 backoff는 이벤트 루프
  위에서 소비되는 sync generator 안이라면 루프를 블록한다 — 예산·attempts
  2가 그 상한을 묶는다(비동기 경계는 :func:`retry_upstream_async`).
- ``jitter=True``면 대기를 ``[delay/2, delay]`` 구간에서 고른다(equal jitter). 같은
  상류를 여러 worker가 동시에 두드릴 때 재시도가 같은 순간에 몰리지 않게 한다.
  기본값은 결정적(``False``)이다 — 상태 job의 시험이 정확한 대기를 잰다.
- ``retry_after``를 주면 예외가 실어 온 ``Retry-After``(초)를 존중한다 — 대기는
  backoff와 그 값 중 큰 쪽이고, 그 값이 ``max_retry_after``를 넘으면 **재시도하지 않고
  원 예외를 그대로 올린다**(몇 분 뒤에 오라는 상류를 이 run 안에서 기다리지 않는다).

**호출 단위 재시도의 적용처(2026-11-24, 감사 §4 #15).** 이 모듈은 처음에 KHOA 한 곳에만
걸려 있었고, 나머지 다건 호출 fetcher(국가유산·산림청·TourAPI·서울 열린데이터·표준데이터
공개 파일·concierge export·MCST·MOIS LOCALDATA)는 5xx 한 번에 asset 전체를 처음부터 다시
돌았다. 지금은 그 fetcher들이 ``provider_fetchers.provider_call_with_retry``(호출 지점 정책 — 분류는
:mod:`.upstream_transient`)로 페이지·지역·slug마다 이 경계를 지난다. ADR-006은 그대로다 —
provider client를 감싸는 adapter가 아니라 public client 호출 하나를 재시도로 두르는 것이다.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import time
from collections.abc import Awaitable, Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Final, TypeVar

__all__ = [
    "DEFAULT_MAX_RETRY_AFTER_SECONDS",
    "DEFAULT_UPSTREAM_ATTEMPTS",
    "DEFAULT_UPSTREAM_BASE_DELAY_SECONDS",
    "DEFAULT_UPSTREAM_MAX_DELAY_SECONDS",
    "DEFAULT_UPSTREAM_RETRY_BUDGET_PERCENT",
    "DEFAULT_UPSTREAM_RUN_RETRY_BUDGET",
    "MAX_UPSTREAM_RUN_RETRY_BUDGET",
    "NONRETRYABLE_FAILURE_KINDS",
    "PROVIDER_CLIENT_INNER_RETRIES",
    "RetryBudget",
    "active_run_retry_budget",
    "default_upstream_retryable",
    "retry_upstream",
    "retry_upstream_async",
    "retry_upstream_awaitable",
    "sharing_run_retry_budget",
]

T = TypeVar("T")

DEFAULT_UPSTREAM_ATTEMPTS: Final[int] = 2
DEFAULT_UPSTREAM_BASE_DELAY_SECONDS: Final[float] = 2.0
DEFAULT_UPSTREAM_MAX_DELAY_SECONDS: Final[float] = 20.0
DEFAULT_UPSTREAM_RUN_RETRY_BUDGET: Final[int] = 8
DEFAULT_UPSTREAM_RETRY_BUDGET_PERCENT: Final[int] = 5
MAX_UPSTREAM_RUN_RETRY_BUDGET: Final[int] = 32
PROVIDER_CLIENT_INNER_RETRIES: Final[int] = 1
"""client 주입용 내부 재시도 — 외부 attempts 2와 곱해 경계당 HTTP 4 시도 유지."""

PROVIDER_BOUNDARY_BASE_DELAY_SECONDS: Final[float] = 15.0
"""provider 호출 경계용 backoff(재리뷰 2 N-2) — lib 내부 재시도가 ~2s 안에
소진되므로, 외부 재시도가 "같은 4회를 0.2s 넓게"가 아니라 **수 초~수 분
장애에 대한 독립 시행**이 되도록 간격을 벌린다. 비용은 비례 예산의 hard cap이
묶는다(32 × 15s = 480s/run backoff 상한)."""

NONRETRYABLE_FAILURE_KINDS: Final[frozenset[str]] = frozenset({"quota", "rate_limit"})
"""``retryable=True``여도 재시도하지 않는 failure_kind — 일일 쿼터 보호."""

DEFAULT_MAX_RETRY_AFTER_SECONDS: Final[float] = 120.0
"""상류가 ``Retry-After``로 이보다 오래 기다리라고 하면 이 run 안에서 기다리지 않는다.

provider 경계 backoff 상한(:data:`DEFAULT_UPSTREAM_MAX_DELAY_SECONDS`·15초 기준 지수)보다
넉넉하되, 몇 분짜리 대기를 페이지마다 쌓아 run 상한에 먼저 닿지 않게 둔 값이다."""


def default_upstream_retryable(exc: BaseException) -> bool:
    """kma 계열 규약 — ``retryable=True``이면서 쿼터성 분류가 아닐 때만 재시도.

    ``retryable=False``(인증·파라미터 오류)와 속성 부재(미분류 — 파싱 등)는
    즉시 전파 대상이다.
    """

    if getattr(exc, "retryable", None) is not True:
        return False
    failure_kind = getattr(exc, "failure_kind", None)
    return failure_kind not in NONRETRYABLE_FAILURE_KINDS


@dataclass
class RetryBudget:
    """run 단위 재시도 총량 — 소진 후에는 retryable 실패도 즉시 전파(early abort).

    상관 장애(모든 호출이 동시에 열화)에서 N×backoff 전액을 지불하지 않기 위한
    상한이다. 하나의 asset run / fetch generator당 하나를 만들어 전 경계에
    공유한다.
    """

    limit: int = DEFAULT_UPSTREAM_RUN_RETRY_BUDGET
    used: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if self.limit < 0:
            raise ValueError(f"retry budget limit must be >= 0: {self.limit}")

    @classmethod
    def proportional(
        cls,
        expected_calls: int,
        *,
        percent: int = DEFAULT_UPSTREAM_RETRY_BUDGET_PERCENT,
        minimum: int = DEFAULT_UPSTREAM_RUN_RETRY_BUDGET,
        maximum: int = MAX_UPSTREAM_RUN_RETRY_BUDGET,
    ) -> RetryBudget:
        """예상 호출 경계 수의 ``percent``만큼 재시도 예산을 만든다.

        작은 순회는 기존 하한(8)을 유지하고, 대규모 격자는 호출 수에 비례해
        간헐 실패 허용량을 늘린다. ``maximum``은 상관 장애에서 run wall time이
        무제한으로 늘어나는 것을 막는 hard cap이다.
        """

        if expected_calls < 0:
            raise ValueError(f"expected_calls must be >= 0: {expected_calls}")
        if percent < 0:
            raise ValueError(f"percent must be >= 0: {percent}")
        if minimum < 0 or maximum < 0 or minimum > maximum:
            raise ValueError(
                f"retry budget bounds must satisfy 0 <= minimum <= maximum: {minimum}, {maximum}"
            )
        scaled = (expected_calls * percent + 99) // 100
        return cls(limit=min(maximum, max(minimum, scaled)))

    def try_consume(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    def widen_to(self, limit: int) -> RetryBudget:
        """예산 상한을 ``limit``까지 넓힌다 — 좁히지는 않고 :data:`MAX_UPSTREAM_RUN_RETRY_BUDGET`을
        넘지 않는다.

        run 경계(:func:`sharing_run_retry_budget`)는 무엇을 부를지 모른 채 기본 예산을 연다.
        그 안의 fetcher가 호출 수를 알게 되면 비례 예산까지 넓힌다. 새 예산을 따로 만들지 않는
        이유는 큐 run 하나가 scope 여러 개를 돌 때 scope 수만큼 예산이 곱해지기 때문이다 — 넓혀도
        run 전체의 재시도는 여전히 hard cap 하나로 묶인다.
        """

        if limit < 0:
            raise ValueError(f"retry budget limit must be >= 0: {limit}")
        self.limit = max(self.limit, min(limit, MAX_UPSTREAM_RUN_RETRY_BUDGET))
        return self


_RUN_RETRY_BUDGET: Final[ContextVar[RetryBudget | None]] = ContextVar(
    "kortravelmap_run_retry_budget", default=None
)


@contextlib.contextmanager
def sharing_run_retry_budget(budget: RetryBudget | None = None) -> Iterator[RetryBudget]:
    """이 블록(= run 하나) 안의 fetcher가 나눠 쓸 재시도 예산을 연다.

    여는 자리는 run 경계다 — asset step
    (:func:`~.feature_operation_tracking.run_tracked_feature_asset`)과 큐 run
    (:func:`~.sensors.execute_feature_update_request_op`, 그 안의 scope별 runner). 큐 run 하나는
    scope 여러 개를 차례로 돌므로 fetcher마다 예산을 새로 만들면 run 하나가 scope 수 × 예산만큼
    재시도한다. **이미 열려 있으면 바깥 예산을 그대로 쓴다** — 안쪽 경계가 예산을 되살리지 않는다.
    """

    outer = _RUN_RETRY_BUDGET.get()
    if outer is not None:
        if budget is not None and budget is not outer:
            # 넘긴 예산은 쓰이지 않는다 — 조용히 무시하면 호출자가 상한을 잘못 믿는다.
            raise ValueError(
                "run 재시도 예산이 이미 열려 있다 — 안쪽에서 다른 예산을 넘길 수 없다."
            )
        yield outer
        return
    shared = budget if budget is not None else RetryBudget()
    token = _RUN_RETRY_BUDGET.set(shared)
    try:
        yield shared
    finally:
        _RUN_RETRY_BUDGET.reset(token)


def active_run_retry_budget() -> RetryBudget | None:
    """지금 run 경계가 연 공유 예산. 경계 밖(단독 호출·테스트)이면 ``None``."""

    return _RUN_RETRY_BUDGET.get()


def _backoff_delay(attempt: int, *, base_delay: float, max_delay: float) -> float:
    return min(max_delay, base_delay * (2.0 ** (attempt - 1)))


def _retry_delay(
    exc: Exception,
    attempt: int,
    *,
    base_delay: float,
    max_delay: float,
    jitter: bool,
    retry_after: Callable[[BaseException], float | None] | None,
) -> float:
    """이번 재시도 앞의 대기. jitter는 backoff 몫에만 걸고 ``Retry-After``는 하한으로 둔다."""

    delay = _backoff_delay(attempt, base_delay=base_delay, max_delay=max_delay)
    if jitter:
        # `random.uniform`은 호출 시점 조회다 — 시험이 module 단위로 바꿔 끼운다.
        delay = random.uniform(delay / 2.0, delay)
    hinted = _retry_after_hint(exc, retry_after)
    return delay if hinted is None else max(delay, hinted)


def _retry_after_hint(
    exc: BaseException, retry_after: Callable[[BaseException], float | None] | None
) -> float | None:
    if retry_after is None:
        return None
    # 진단 부수 경로 — 힌트 해석이 실패해도 원 예외의 분류를 바꾸지 않는다.
    with contextlib.suppress(Exception):
        value = retry_after(exc)
        if value is not None and value >= 0:
            return float(value)
    return None


def _should_retry(
    exc: Exception,
    *,
    attempt: int,
    attempts: int,
    is_retryable: Callable[[BaseException], bool],
    budget: RetryBudget | None,
    label: str,
    on_retry: Callable[[str], None] | None,
    retry_after: Callable[[BaseException], float | None] | None = None,
    max_retry_after: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
) -> bool:
    """재시도 여부 판정 + 텔레메트리. 분류 통과 후에만 예산을 소모한다."""

    safe_label = label.replace("\r", r"\r").replace("\n", r"\n")
    if attempt >= attempts or not is_retryable(exc):
        return False
    hinted = _retry_after_hint(exc, retry_after)
    if hinted is not None and hinted > max_retry_after:
        # 상류가 이 run이 기다릴 수 있는 것보다 길게 기다리라고 했다 — 예산을 쓰지 않고
        # 원 예외로 끝낸다. 다음 주기(또는 step 재시도)가 다시 온다.
        _notify(
            on_retry,
            f"upstream retry {safe_label}: Retry-After {hinted:.0f}s > "
            f"{max_retry_after:.0f}s — {type(exc).__name__} 즉시 전파",
        )
        return False
    if budget is not None and not budget.try_consume():
        _notify(
            on_retry,
            f"upstream retry budget exhausted ({budget.limit}) — "
            f"{safe_label}: {type(exc).__name__} 즉시 전파",
        )
        return False
    _notify(
        on_retry,
        f"upstream retry {safe_label}: attempt {attempt}/{attempts} 실패 "
        f"({type(exc).__name__}) — 재시도",
    )
    return True


def _notify(on_retry: Callable[[str], None] | None, message: str) -> None:
    """텔레메트리는 fallible — logger 실패가 upstream 원 예외를 덮으면 실패
    분류가 오진된다(리뷰 1 N-3). 삼키고 진행한다."""

    if on_retry is None:
        return
    # 진단 부수 경로 — logger 실패가 원 예외를 덮으면 실패 분류가 오진된다.
    with contextlib.suppress(Exception):
        on_retry(message)


def retry_upstream(
    call: Callable[[], T],
    *,
    label: str,
    is_retryable: Callable[[BaseException], bool] = default_upstream_retryable,
    attempts: int = DEFAULT_UPSTREAM_ATTEMPTS,
    base_delay: float = DEFAULT_UPSTREAM_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_UPSTREAM_MAX_DELAY_SECONDS,
    budget: RetryBudget | None = None,
    on_retry: Callable[[str], None] | None = None,
    jitter: bool = False,
    retry_after: Callable[[BaseException], float | None] | None = None,
    max_retry_after: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> T:
    """동기 upstream 단건 호출을 유한 재시도한다. ``label``은 진단용.

    ``sleep`` 기본은 호출 시점의 ``time.sleep``(late-binding — 테스트에서
    monkeypatch 가능).
    """

    if attempts < 1:
        raise ValueError(f"attempts must be >= 1: {attempts} ({label})")
    do_sleep = time.sleep if sleep is None else sleep
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not _should_retry(
                exc,
                attempt=attempt,
                attempts=attempts,
                is_retryable=is_retryable,
                budget=budget,
                label=label,
                on_retry=on_retry,
                retry_after=retry_after,
                max_retry_after=max_retry_after,
            ):
                raise
            do_sleep(
                _retry_delay(
                    exc,
                    attempt,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    jitter=jitter,
                    retry_after=retry_after,
                )
            )
    raise AssertionError(f"unreachable: {label}")  # pragma: no cover


async def retry_upstream_awaitable(
    call: Callable[[], Awaitable[T]],
    *,
    label: str,
    is_retryable: Callable[[BaseException], bool] = default_upstream_retryable,
    attempts: int = DEFAULT_UPSTREAM_ATTEMPTS,
    base_delay: float = DEFAULT_UPSTREAM_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_UPSTREAM_MAX_DELAY_SECONDS,
    budget: RetryBudget | None = None,
    on_retry: Callable[[str], None] | None = None,
    jitter: bool = False,
    retry_after: Callable[[BaseException], float | None] | None = None,
    max_retry_after: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    """**async client 호출**을 재시도 경계 안에서 await한다.

    :func:`retry_upstream_async`와 헷갈리기 쉬우므로 차이를 못 박는다 — 그쪽은
    호출을 ``call()``로 **동기 실행**하고 backoff 대기만 event loop에 양보한다
    (동기 client를 async asset 안에서 쓸 때). 코루틴을 돌려주는 호출을 거기 넘기면
    ``call()``이 코루틴 **객체**를 만들어 그대로 반환하므로, 그 안에서 나는 예외를
    재시도가 **한 번도 보지 못한다.** 재시도가 조용히 없어지는 셈이다.

    async 전용 provider client(khoa 6.x 등)는 이 함수를 쓴다. 계약·backoff·예산은
    동일하고 다른 것은 await 경계 하나다.
    """
    if attempts < 1:
        raise ValueError(f"attempts must be >= 1: {attempts} ({label})")
    do_sleep = asyncio.sleep if sleep is None else sleep
    for attempt in range(1, attempts + 1):
        try:
            return await call()
        except Exception as exc:
            if not _should_retry(
                exc,
                attempt=attempt,
                attempts=attempts,
                is_retryable=is_retryable,
                budget=budget,
                label=label,
                on_retry=on_retry,
                retry_after=retry_after,
                max_retry_after=max_retry_after,
            ):
                raise
            await do_sleep(
                _retry_delay(
                    exc,
                    attempt,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    jitter=jitter,
                    retry_after=retry_after,
                )
            )
    raise AssertionError(f"unreachable: {label}")  # pragma: no cover


async def retry_upstream_async(
    call: Callable[[], T],
    *,
    label: str,
    is_retryable: Callable[[BaseException], bool] = default_upstream_retryable,
    attempts: int = DEFAULT_UPSTREAM_ATTEMPTS,
    base_delay: float = DEFAULT_UPSTREAM_BASE_DELAY_SECONDS,
    max_delay: float = DEFAULT_UPSTREAM_MAX_DELAY_SECONDS,
    budget: RetryBudget | None = None,
    on_retry: Callable[[str], None] | None = None,
    jitter: bool = False,
    retry_after: Callable[[BaseException], float | None] | None = None,
    max_retry_after: float = DEFAULT_MAX_RETRY_AFTER_SECONDS,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> T:
    """async 문맥용 — 호출 자체는 호출측 규약대로(동기 client도 그대로) 실행하고
    backoff 대기만 event loop에 양보한다. cancellation(``BaseException``)은
    재시도로 삼키지 않는다. ``sleep`` 기본은 호출 시점의 ``asyncio.sleep``."""

    if attempts < 1:
        raise ValueError(f"attempts must be >= 1: {attempts} ({label})")
    do_sleep = asyncio.sleep if sleep is None else sleep
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:
            if not _should_retry(
                exc,
                attempt=attempt,
                attempts=attempts,
                is_retryable=is_retryable,
                budget=budget,
                label=label,
                on_retry=on_retry,
                retry_after=retry_after,
                max_retry_after=max_retry_after,
            ):
                raise
            await do_sleep(
                _retry_delay(
                    exc,
                    attempt,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    jitter=jitter,
                    retry_after=retry_after,
                )
            )
    raise AssertionError(f"unreachable: {label}")  # pragma: no cover

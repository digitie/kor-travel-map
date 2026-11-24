"""상류(transport·weather) 상태 신호 — Valkey 상태 적재 job이 같은 말로 남긴다.

2026-11-23 수집 실패 감사(``docs/reports/2026-11-23-collection-failure-audit.md`` §1.3·§3·§4 #9)가
본 것: 같은 "상류가 오래됐다"가 weather에서는 초록(200 + ``source_status=stale``이면 교체하고
SUCCESS), transport에서는 빨강(503·stale이면 step을 30·60초 뒤 두 번 더 돌린 뒤 FAILURE)이었다.
몇 시간짜리 상류 장애를 30·60초 뒤 다시 물어, Map에서 재시도가 붙은 run 344건 중 성공으로 끝난
것은 54건(16%)뿐이었다. 그리고 그 step 재시도 정책(``RetryPolicy``) 때문에 run 상한으로 죽은
step에도 Dagster가 재시도를 요청했다(14일 100회, 전부 weather 상태 job — Dagster는 interrupt를
retry policy에 넘긴다).

이제 규칙은 하나다(ADR-114 "2026-11-24 개정" 절이 정본, 소유자 결정 "나이 기준 혼합"). 기준은
**지금 서비스하는 세대의 원천 나이**(``source_collected_at``, 없으면 적재·304 재확인 시각)와 job
spec의 경고 임계 ``stale_alert_after``다. 임계는 읽기 쪽 계약 ``dataset.max_age``(REST
``freshness.stale``)보다 낮다 — 소비자가 stale을 받기 전에 운영자가 빨간 run을 먼저 본다.

- **상류 미준비**(503 — transport code 503 전부 포함 — ·``collection`` stale/실패 플래그·무응답·HTTP
  층 재시도를 다 쓴 5xx·429·snapshot 만료 반복·weather export 읽기 자리를 못 잡음·run 상한 안에
  순회를 끝낼 수 없음)는 이번 tick을 건너뛴다(step 재시도 없음, 세대 유지).
- **상류 stale이지만 값이 왔다**(weather 200 + ``stale``)는 그대로 교체한다 — 지금 세대보다 나쁘지
  않다.
- **비정상 집합 거부**(0건·급감, ADR-114 D4)와 transport 0건 export는 데이터 보호라 계속 거부한다.
- 어느 경우든 결과 metadata에 상류 상태와 서비스 세대 나이를 싣고, run tag
  :data:`UPSTREAM_STATE_TAG`·:data:`STALE_ALERT_TAG`를 언제나 쓴다(재실행이 낡은 tag를 물려받지
  않게).
- **run 결과는 나이가 정한다**: 서비스 세대가 경고 임계 안이면 성공이다 — 한두 tick의 상류 이상은
  빨갛게 만들지 않는다(종전 transport 503 80건·거부 64건은 대부분 다음 tick에 풀렸다). 임계를 넘으면
  (세대가 아예 없으면 포함) **실패, 재시도 없음**이다(:func:`raise_if_stale`) — Map에는 상류 장애
  경보가 따로 없으므로 빨간 run이 유일한 신호다. 다음 tick이 다시 본다.
  설정 오류(주소·DNS)도 이 길로 늦어도 기준 나이 안에 빨갛게 된다.
- Map 쪽 저장소(Valkey) 연결 실패만 step 재시도한다 — ``RetryPolicy`` 대신 op가
  :class:`dagster.RetryRequested`를 직접 올린다(:func:`retry_state_store_outage`). 그래야 run
  상한으로 죽은 step에 재시도를 요청하지 않는다.
"""

# ``from __future__ import annotations``를 쓰지 않는다 — 다른 Dagster 모듈과 같다.
import contextlib
import math
import random
import time
from datetime import datetime, timedelta
from typing import Any, Final, NoReturn

import httpx
from kortravelmap.infra.valkey_state import GenerationMeta, StateStoreError
from kortravelmap.providers.kor_travel_transport import (
    TransportExportBusy,
    TransportSourceNotCurrent,
)

from dagster import MAX_RUNTIME_SECONDS_TAG, Failure, OpExecutionContext, RetryRequested

__all__ = [
    "STALE_ALERT_TAG",
    "STATE_STORE_MAX_RETRIES",
    "STATE_STORE_RETRY_DELAY_SECONDS",
    "UPSTREAM_NOT_READY",
    "UPSTREAM_OK",
    "UPSTREAM_REFUSED",
    "UPSTREAM_STALE",
    "UPSTREAM_STATE_TAG",
    "jittered",
    "raise_if_stale",
    "refused",
    "report_upstream_signal",
    "retry_state_store_outage",
    "run_deadline",
    "served_age_seconds",
    "upstream_not_ready_kind",
    "upstream_signal",
]

UPSTREAM_STATE_TAG: Final[str] = "kor_travel_map.upstream_state"
"""run tag — 상류 상태(``ok``·``stale``·``not_ready``·``refused``)."""

STALE_ALERT_TAG: Final[str] = "kor_travel_map.upstream_stale_alert"
"""run tag — 서비스 세대의 원천 나이가 stale 기준을 넘었으면 ``true``, 아니면 ``false``."""

UPSTREAM_OK: Final[str] = "ok"
UPSTREAM_STALE: Final[str] = "stale"
"""값은 왔고 교체했다. 원천이 스스로 stale이라고 알렸다(weather 200 + ``source_status=stale``)."""
UPSTREAM_NOT_READY: Final[str] = "not_ready"
"""이번 tick을 건너뛰었다. 세대는 그대로다."""
UPSTREAM_REFUSED: Final[str] = "refused"
"""원천 집합이 비정상(0건·급감)이라 교체를 거부했다. 세대는 그대로다."""

STATE_STORE_MAX_RETRIES: Final[int] = 2
STATE_STORE_RETRY_DELAY_SECONDS: Final[float] = 30.0
"""Valkey 연결 실패 step 재시도 — 30·60초(±20%) 뒤 두 번. 종전 ``RetryPolicy``와 같은 간격이다."""

_JITTER_RATIO: Final[float] = 0.2


def jittered(seconds: float, *, ratio: float = _JITTER_RATIO) -> float:
    """``seconds``를 ±``ratio`` 안에서 흔든다(같은 순간 실패한 run들이 같은 순간 다시 묻지 않게)."""
    if seconds <= 0:
        return 0.0
    return seconds * random.uniform(1.0 - ratio, 1.0 + ratio)  # noqa: S311 — 보안 난수 아님


_UNREACHABLE: Final = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
"""상류 무응답으로 보는 전송 오류. ``UnsupportedProtocol``(scheme 없는 주소)·``LocalProtocolError``·
``ProxyError``는 Map 설정·코드 문제라 넣지 않는다(그대로 실패)."""


def upstream_not_ready_kind(exc: BaseException) -> str | None:
    """상류 미준비로 볼 실패면 그 ``failure_kind``, 아니면 ``None``.

    원인 사슬(``__cause__``)을 따라 처음 만나는 **분류를 가진** 예외가 판정한다 — provider 예외와
    계약 위반(``ValueError`` 계열)은 ``retryable``이 있고, 그 값이 결론이다(``retryable=False``인
    계약 위반 뒤의 재시도 가능한 원인을 따라 들어가지 않는다). ``__context__``는 따르지 않는다 —
    처리 중에 난 **다른** 실패라 그 원인이 아니다(``quota_exhaustion``과 같은 규칙). 무응답 전송
    오류와 HTTP 429·5xx 응답(transport의 ``raise_for_status``)도 미준비다. Valkey
    실패(:class:`StateStoreError`)는 Map 쪽 문제라 아니다.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, StateStoreError):
            return None
        if isinstance(current, TransportSourceNotCurrent | TransportExportBusy):
            # transport가 503 code로 "근거 수집이 현재가 아니다"(4종)·"경합"(대기 상한 초과
            # 포함)이라고 알렸다. step 재시도로는 풀리지 않으므로 ``retryable``과 상관없이 미준비다
            # (transport #277·ADR-106 개정, 소유자 결정 2026-11-24 "나이 기준 혼합").
            return current.failure_kind
        retryable = getattr(current, "retryable", None)
        if isinstance(retryable, bool):
            if not retryable:
                return None
            kind = getattr(current, "failure_kind", None)
            return kind if isinstance(kind, str) and kind else type(current).__name__
        if isinstance(current, _UNREACHABLE):
            return f"upstream_unreachable:{type(current).__name__}"
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            return f"upstream_http_{status}" if status == 429 or status >= 500 else None
        current = current.__cause__
    return None


def served_age_seconds(meta: GenerationMeta | None, *, now: datetime) -> float | None:
    """서비스 세대의 원천 나이(초). 원천 수집 시각이 없으면 적재 시각으로 잰다.

    원천 수집 시각이 없는 세대(공항·weather 위치 roster)는 원천이 304로 "그대로다"라고 다시 확인한
    시각(``checked_at``)이 적재 시각보다 늦으면 그것으로 잰다. 세대가 없으면(첫 적재 전) ``None``.
    """
    if meta is None:
        return None
    basis = meta.source_collected_at
    if basis is None:
        basis = max(meta.loaded_at, meta.checked_at or meta.loaded_at)
    return max(0.0, (now - basis).total_seconds())


def upstream_signal(
    state: str,
    *,
    served: GenerationMeta | None,
    alert_after: timedelta,
    now: datetime,
    reason: str = "",
) -> dict[str, Any]:
    """op metadata에 싣는 상류 신호. 세대가 없으면(첫 적재 전) 나이를 모르므로 경고다."""
    age = served_age_seconds(served, now=now)
    alert = age is None or age > alert_after.total_seconds()
    collected = served.source_collected_at if served is not None else None
    return {
        "upstream_state": state,
        "upstream_reason": reason,
        "served_generation": served.generation if served is not None else "",
        "served_source_collected_at": collected.isoformat() if collected is not None else "",
        "served_age_seconds": int(age) if age is not None else -1,
        "stale_alert_after_seconds": int(alert_after.total_seconds()),
        "stale_alert": alert,
    }


def report_upstream_signal(context: OpExecutionContext, metadata: dict[str, Any]) -> None:
    """상류 상태를 run tag로 쓰고, ``ok``가 아니거나 경고면 WARNING을 남긴다.

    tag는 언제나 둘 다 쓴다 — 부모 run tag를 물려받는 재실행이 낡은 경고를 들고 다니지 않게.
    tag 쓰기 실패는 적재를 막지 않는다.
    """
    state = metadata.get("upstream_state")
    if state is None:
        return  # 잠금 건너뜀 — 상류를 보지 않았다
    alert = bool(metadata.get("stale_alert"))
    tags = {UPSTREAM_STATE_TAG: str(state), STALE_ALERT_TAG: "true" if alert else "false"}
    with contextlib.suppress(Exception):
        context.instance.add_run_tags(context.run_id, tags)
    if state == UPSTREAM_OK and not alert:
        return
    context.log.warning(
        "%s: 상류 상태 %s(%s) — 서비스 세대 %s, 원천 나이 %s초(경고 기준 %s초)%s",
        metadata.get("dataset", ""),
        state,
        metadata.get("upstream_reason") or "-",
        metadata.get("served_generation") or "없음",
        metadata.get("served_age_seconds"),
        metadata.get("stale_alert_after_seconds"),
        " — stale 기준 초과" if alert else "",
    )


def refused(
    *,
    dataset: str,
    failure_kind: str,
    description: str,
    served: GenerationMeta | None,
    alert_after: timedelta,
    now: datetime,
    details: dict[str, Any],
) -> dict[str, Any]:
    """비정상 집합 거부 metadata(세대 유지). run 결과는 :func:`raise_if_stale`이 나이로 정한다."""
    return {
        "dataset": dataset,
        "skipped": "refused",
        "failure_kind": failure_kind,
        "refusal": description[:500],
        "override": "run config ops.<op>.config.allow_shrink: true",
        **details,
        **upstream_signal(
            UPSTREAM_REFUSED, served=served, alert_after=alert_after, now=now, reason=failure_kind
        ),
    }


def raise_if_stale(metadata: dict[str, Any]) -> None:
    """서비스 세대가 stale 기준을 넘었으면(세대가 없으면 포함) 재시도 없는 실패로 끝낸다."""
    if not metadata.get("stale_alert"):
        return
    state = metadata.get("upstream_state", "")
    age = metadata.get("served_age_seconds")
    limit = metadata.get("stale_alert_after_seconds")
    served = (
        f"서비스 세대 {metadata.get('served_generation')}의 원천 나이 {age}초가 stale 기준 "
        f"{limit}초를 넘었다"
        if metadata.get("served_generation")
        else "서비스할 세대가 없다(첫 적재 전)"
    )
    hint = {
        UPSTREAM_NOT_READY: "상류가 준비되지 않았다 — 상류(transport·weather) 수집·export를 본다.",
        UPSTREAM_REFUSED: (
            "원천 집합을 거부했다 — 원천이 정말 줄었다면 allow_shrink로 한 번 받아들이고, 아니면 "
            "상류를 고친다."
        ),
        UPSTREAM_STALE: "값은 받아 교체했으나 원천 자체가 오래됐다 — 상류 수집을 본다.",
        UPSTREAM_OK: "값은 받아 교체했으나 원천 수집 시각이 오래됐다 — 상류 수집을 본다.",
    }.get(str(state), "")
    raise Failure(
        description=(
            f"{metadata.get('dataset', '')}: {served}. 상류 {state}"
            f"({metadata.get('upstream_reason') or metadata.get('failure_kind') or '-'}). {hint}"
        ),
        metadata={**metadata, "step_retries_suppressed": "true"},
        allow_retries=False,
    )


def run_deadline(context: OpExecutionContext, default_cap_seconds: int, tail_seconds: int) -> float:
    """run 상한(``dagster/max_runtime``)에서 꼬리를 뺀 monotonic 시각.

    run monitor는 step이 아니라 **run** 시작부터 센다 — step 재시도가 이미 쓴 시간도 뺀다
    (``mois_chunked_load._run_clock_start``와 같은 규칙). 상한은 run의 실제 tag(없으면 기본값)다.
    run 시작을 모르면(조회 실패 포함) 지금부터 센다.
    """
    now = time.time()
    cap = default_cap_seconds
    with contextlib.suppress(AttributeError, TypeError, ValueError):
        cap = int(context.run.tags.get(MAX_RUNTIME_SECONDS_TAG, cap))
    try:
        record = context.instance.get_run_record_by_id(context.run_id)
    except Exception:  # noqa: BLE001 — 시작 시각을 모르면 지금부터 센다(적재를 막지 않는다)
        record = None
    start_time = getattr(record, "start_time", None)
    elapsed = 0.0
    if (
        isinstance(start_time, int | float)
        and not isinstance(start_time, bool)
        and math.isfinite(start_time)
        and 0 < start_time <= now
    ):
        elapsed = now - float(start_time)
    return time.monotonic() + cap - tail_seconds - elapsed


def retry_state_store_outage(
    context: OpExecutionContext, exc: StateStoreError, *, deadline: float
) -> NoReturn:
    """Valkey 연결 실패를 step 재시도로 넘긴다 — 대기가 run 상한(꼬리 제외) 안에 들 때만.

    ``RetryPolicy``를 쓰지 않는 이유: Dagster는 retry policy가 있는 step이 interrupt(run 상한 초과
    취소 포함)로 끝나도 재시도를 요청한다. 재시도가 필요한 실패만 여기서 직접 요청한다.
    """
    try:
        attempt = int(context.retry_number)
    except Exception:  # noqa: BLE001 — retry_number가 없는 context(테스트 대역)
        attempt = 0
    wait = jittered(STATE_STORE_RETRY_DELAY_SECONDS * (2**attempt))
    if attempt >= STATE_STORE_MAX_RETRIES or time.monotonic() + wait >= deadline:
        raise exc
    raise RetryRequested(max_retries=STATE_STORE_MAX_RETRIES, seconds_to_wait=wait) from exc

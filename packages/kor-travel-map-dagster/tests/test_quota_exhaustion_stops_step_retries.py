"""쿼터성 실패가 step 재시도를 사지 못하게 하는 것을 **경계를 실제로 돌려** 결박한다.

세 종류의 단언이 있다.

- **경계 실행** — `run_tracked_feature_asset`와 `feature_place_mcst_culture`를
  진짜로 호출해, 빠져나오는 예외가 `allow_retries=False`인 `dagster.Failure`인지
  본다. 처음에는 이것이 **하나도 없었다**(적대 리뷰 지적) — 행동 단언이 전부
  판정 함수를 직접 불러서, 결박 지점을 지워도 초록이었다.
- **분류** — 일일 쿼터만 끄고 HTTP 429와 간헐 장애는 재시도를 남긴다.
- **구조** — `FEATURE_LOAD_RETRY_POLICY`를 단 asset을 소스에서 유도해, 그 전부가
  쿼터 판정을 지나는지 본다. 결박의 단위는 함수 이름이 아니라 **`except` 핸들러**다
  (AGENTS.md DO NOT 15: 유도 → 결박 → 탐지).
"""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from dagster import Failure
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership

from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
    run_tracked_feature_asset,
)
from kortravelmap.dagster.quota_exhaustion import (
    QUOTA_EXCEPTION_TYPES,
    quota_exhaustion_cause,
    raise_terminal_if_quota_exhausted,
)

_PACKAGE = Path(__file__).resolve().parents[1] / "src" / "kortravelmap" / "dagster"

#: 쿼터 판정을 실제로 부르는 함수 이름 — 이 심볼이 결박의 앵커다.
_GUARD_CALL = "raise_terminal_if_quota_exhausted"


class _QuotaExhausted(RuntimeError):
    """``python-kma-api``의 resultCode 22 예외 모양 — 분류를 속성으로 갖는다."""

    failure_kind = "quota"
    retryable = False


class _HttpThrottled(RuntimeError):
    """HTTP 429 — 같은 ``rate_limit`` 분류지만 초·분 단위로 풀린다."""

    failure_kind = "rate_limit"
    status_code = 429
    retryable = True


class _NetworkBlip(RuntimeError):
    """간헐 장애 — 재시도가 실제로 도움이 되는 쪽."""

    failure_kind = "network"
    retryable = True


class _Wrapped(RuntimeError):
    """asset 경계가 분류를 메시지로 녹여 다시 던지는 모양."""


# ---------------------------------------------------------------- 경계 실행


class _Client:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.memberships = (
            ProviderDatasetOperationMembership(
                provider_dataset_id=41,
                sync_scope="dataset_wide",
                operation_key="feature_place_mcst_culture_job",
            ),
        )

    async def ensure_dagster_feature_operation(self, **_kwargs: Any) -> Any:
        self.calls.append("ensure")
        return SimpleNamespace(outcome="applied", block_reason=None)

    async def finish_dagster_feature_membership(self, **_kwargs: Any) -> Any:
        self.calls.append("finish")
        return SimpleNamespace(outcome="applied", block_reason=None)

    async def append_dagster_feature_attempt_event(self, **_kwargs: Any) -> None:
        self.calls.append("attempt")

    async def resolve_feature_operation_memberships(self, **_kwargs: Any) -> Any:
        self.calls.append("memberships")
        return self.memberships


class _Instance:
    def __init__(self, run: Any) -> None:
        self.run = run

    def get_run_record_by_id(self, run_id: str) -> Any:
        assert run_id == self.run.run_id
        return SimpleNamespace(
            dagster_run=self.run,
            create_timestamp=datetime(2026, 9, 13, tzinfo=UTC),
            start_time=datetime(2026, 9, 13, 1, tzinfo=UTC).timestamp(),
        )


def _dagster_run(*, tagged: bool) -> Any:
    tags = (
        {
            "kor_travel_map.operation_key": "feature_place_mcst_culture_job",
            "kor_travel_map.trigger_kind": "schedule",
        }
        if tagged
        else {}
    )
    return SimpleNamespace(
        run_id="run-quota",
        job_name="feature_place_mcst_culture_job",
        tags=tags,
        status=SimpleNamespace(value="STARTED"),
    )


def _context(*, tracked: bool) -> Any:
    """`run_tracked_feature_asset`의 두 갈래를 각각 만든다.

    ``tracked=False``는 run tag에 operation_key가 없는 run — UI 수동 실행이나
    태그 없는 backfill이 그 경로를 탄다. 이 갈래에 판정을 걸지 않으면 그 run들이
    조용히 재시도를 산다.
    """

    client = _Client()
    run = _dagster_run(tagged=tracked)
    guard = FeatureOperationExecutionGuard(
        client=client,  # type: ignore[arg-type]
        instance=_Instance(run),
        operation_key="feature_place_mcst_culture_job" if tracked else None,
        memberships=client.memberships if tracked else (),
        dagster_run_id=run.run_id,
        trigger_kind="schedule" if tracked else None,
    )
    return SimpleNamespace(
        resources=SimpleNamespace(feature_operation_guard=guard, kor_travel_map_client=client),
        instance=guard.instance,
        run=run,
        retry_number=0,
    )


@pytest.mark.parametrize("tracked", [True, False], ids=["guarded", "untracked"])
def test_the_asset_boundary_turns_quota_into_a_terminal_failure(tracked: bool) -> None:
    """**경계를 실제로 돌린다.** 두 갈래 모두 재시도를 끈 실패로 나와야 한다."""

    async def _raise(_context: Any) -> None:
        raise _QuotaExhausted("resultCode 22")

    with pytest.raises(Failure) as caught:
        asyncio.run(run_tracked_feature_asset(_context(tracked=tracked), _raise))
    assert caught.value.allow_retries is False


@pytest.mark.parametrize("tracked", [True, False], ids=["guarded", "untracked"])
def test_the_asset_boundary_leaves_retryable_failures_alone(tracked: bool) -> None:
    """과분류 방지 — 원 예외가 그대로 나와야 재시도 정책이 산다."""

    async def _raise(_context: Any) -> None:
        raise _NetworkBlip("gateway timeout")

    with pytest.raises(_NetworkBlip):
        asyncio.run(run_tracked_feature_asset(_context(tracked=tracked), _raise))


@pytest.mark.parametrize("tracked", [True, False], ids=["guarded", "untracked"])
def test_the_asset_boundary_leaves_http_429_alone(tracked: bool) -> None:
    """429는 60초 뒤에 풀린다 — 월 1회 schedule을 한 달 잃을 수는 없다."""

    async def _raise(_context: Any) -> None:
        raise _HttpThrottled("HTTP 429")

    with pytest.raises(_HttpThrottled):
        asyncio.run(run_tracked_feature_asset(_context(tracked=tracked), _raise))


def test_the_guarded_branch_still_records_the_failed_attempt() -> None:
    """실패 기록이 먼저다 — 판정이 그 순서를 바꾸면 사후 판독이 비어 버린다."""

    context = _context(tracked=True)

    async def _raise(_context: Any) -> None:
        raise _QuotaExhausted("resultCode 22")

    with pytest.raises(Failure):
        asyncio.run(run_tracked_feature_asset(context, _raise))
    assert "attempt" in context.resources.kor_travel_map_client.calls


# ---------------------------------------------------------------- 분류


def test_direct_quota_failure_becomes_a_terminal_dagster_failure() -> None:
    with pytest.raises(Failure) as caught:
        raise_terminal_if_quota_exhausted(_QuotaExhausted("resultCode 22"))
    assert caught.value.allow_retries is False


def test_quota_classification_survives_being_melted_into_a_message() -> None:
    """``ProviderDatasetRefreshFailure``가 문자열로 녹여도 ``__cause__``가 남는다."""

    cause = _QuotaExhausted("resultCode 22")
    wrapped: _Wrapped | None = None
    try:
        raise _Wrapped(f"KMA provider refresh failed: {cause}") from cause
    except _Wrapped as caught_wrapped:
        wrapped = caught_wrapped
    assert wrapped is not None
    assert quota_exhaustion_cause(wrapped) is cause

    with pytest.raises(Failure) as caught:
        raise_terminal_if_quota_exhausted(wrapped)
    assert caught.value.allow_retries is False


def test_http_429_keeps_its_retries_even_though_it_is_rate_limit() -> None:
    """분류 문자열이 같아도 회복 창이 다르다.

    provider lib들이 429와 resultCode 22에 같은 ``failure_kind="rate_limit"``를
    붙인다(visitkorea·mcst·krforest 실측). 둘을 가르는 것은 HTTP 상태뿐이다.
    """

    assert quota_exhaustion_cause(_HttpThrottled("HTTP 429")) is None


def test_retryable_failures_keep_their_retries() -> None:
    """여기가 빨개지면 H45가 고친 것을 되돌린 것이다."""

    blip = _NetworkBlip("gateway timeout")
    assert quota_exhaustion_cause(blip) is None
    raise_terminal_if_quota_exhausted(blip)


def test_unclassified_failures_keep_their_retries() -> None:
    assert quota_exhaustion_cause(ValueError("parse error")) is None


def test_a_cyclic_cause_chain_terminates() -> None:
    """실패 경로에서 무한 루프를 내면 원인 규명 자체가 불가능해진다."""

    first = RuntimeError("a")
    second = RuntimeError("b")
    first.__cause__ = second
    second.__cause__ = first
    assert quota_exhaustion_cause(first) is None


def test_a_provider_without_failure_kind_is_caught_by_identity() -> None:
    """``failure_kind``를 붙이지 않는 lib이 절반이다 — 이름/모듈로 메운다.

    에어코리아가 그 대표이고 **가장 좁은 분모**다(오퍼레이션당 500/일).
    """

    module, class_name = next(
        pair for pair in sorted(QUOTA_EXCEPTION_TYPES) if pair[0] == "airkorea"
    )
    fake = type(class_name, (RuntimeError,), {"__module__": module})
    assert quota_exhaustion_cause(fake("daily limit exceeded")) is not None


def test_identity_match_still_honours_the_429_exclusion() -> None:
    """선언 집합에 걸려도 429면 재시도를 남긴다."""

    module, class_name = next(
        pair for pair in sorted(QUOTA_EXCEPTION_TYPES) if pair[0] == "krex"
    )
    fake = type(class_name, (RuntimeError,), {"__module__": module, "http_status": 429})
    assert quota_exhaustion_cause(fake("HTTP 429")) is None


def test_identity_match_is_module_qualified() -> None:
    """이름만 같은 남의 예외에 걸리면 안 된다."""

    impostor = type(
        "AirKoreaRateLimitError", (RuntimeError,), {"__module__": "somewhere_else"}
    )
    assert quota_exhaustion_cause(impostor("x")) is None


def test_a_plain_failure_would_still_be_retried() -> None:
    """``Failure``만으로는 부족하다 — ``allow_retries``의 기본값은 ``True``다."""

    assert Failure(description="x").allow_retries is True


def test_the_terminal_failure_names_what_it_suppressed() -> None:
    """사후 판독이 이벤트 로그만으로 가능해야 한다."""

    with pytest.raises(Failure) as caught:
        raise_terminal_if_quota_exhausted(_QuotaExhausted("resultCode 22"))
    metadata: dict[str, Any] = dict(caught.value.metadata)
    assert "failure_kind" in metadata
    assert "step_retries_suppressed" in metadata
    assert "provider_module" in metadata


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


def _functions() -> list[tuple[str, ast.AsyncFunctionDef | ast.FunctionDef]]:
    return [
        (name, node)
        for name, tree in _module_trees().items()
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    ]


def _unguarded_handlers(node: ast.AST) -> list[int]:
    """``except`` 핸들러 중 쿼터 판정을 거치지 않고 **재던지는** 것의 줄 번호.

    결박의 단위가 '함수 이름'이면 같은 함수 안의 두 실패 분기 중 하나를 지워도
    초록이다 — 적대 리뷰가 정확히 그 구멍을 지적했다. 그래서 핸들러마다 센다.

    ``raise``로 예외를 밖으로 내보내는 핸들러만 본다. 삼키거나(로그 후 pass)
    다른 것으로 바꾸는 핸들러는 재시도 정책과 무관하다.
    """

    unguarded: list[int] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.ExceptHandler):
            continue
        handler = ast.Module(body=child.body, type_ignores=[])
        reraises = any(isinstance(stmt, ast.Raise) for stmt in ast.walk(handler))
        if not reraises:
            continue
        if _GUARD_CALL not in _called_names(handler):
            unguarded.append(child.lineno)
    return unguarded


def _quota_guarded_functions() -> set[str]:
    """쿼터 판정을 부르되 **재던지는 핸들러를 하나도 빠뜨리지 않은** 함수."""

    guarded: set[str] = set()
    for _name, node in _functions():
        if _GUARD_CALL not in _called_names(node):
            continue
        if _unguarded_handlers(node):
            continue
        guarded.add(node.name)
    return guarded


def _feature_load_assets() -> list[tuple[str, ast.AsyncFunctionDef | ast.FunctionDef]]:
    """**재시도 정책을 단** asset을 소스에서 유도한다.

    종전에는 ``FEATURE_LOAD_RETRY_POLICY``라는 **이름**으로 골랐다. 그러면 정당한
    이유로 다른 정책을 쓰는 asset이 생기는 순간 그것이 유도에서 빠지고, 이 파일의
    쿼터 결박 검사도 그 asset을 보지 못한다 — 하필 그런 asset이 쿼터가 가장 아픈
    자리다(2026-09-19: OpiNet이 run 예산 때문에 `max_retries=0`으로 갈렸다).

    그래서 이름이 아니라 **`retry_policy`를 선언했다는 사실**로 고른다.
    """

    found: list[tuple[str, ast.AsyncFunctionDef | ast.FunctionDef]] = []
    for name, node in _functions():
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if any(keyword.arg == "retry_policy" for keyword in decorator.keywords):
                found.append((name, node))
    return found


def test_the_derivation_actually_found_something() -> None:
    """항진명제 방지 — 유도가 비면 아래 단언이 무엇도 재지 못한다."""

    assets = _feature_load_assets()
    assert len(assets) >= 35, (
        f"재시도 정책을 단 asset을 {len(assets)}개만 찾았다 — 유도가 낡았다."
    )
    assert _quota_guarded_functions(), (
        f"`{_GUARD_CALL}`를 부르는 함수를 하나도 찾지 못했다 — 결박이 사라졌다."
    )


def test_no_reraising_handler_in_a_guarded_function_skips_the_guard() -> None:
    """같은 함수 안의 실패 분기를 **하나라도** 빠뜨리면 빨갛다.

    `run_tracked_feature_asset`에는 재던지는 핸들러가 둘 있다(guard 유무). 종전
    탐지기는 함수 이름만 봐서 한쪽을 지워도 초록이었다.
    """

    offenders: list[str] = []
    for module, node in _functions():
        if _GUARD_CALL not in _called_names(node):
            continue
        for lineno in _unguarded_handlers(node):
            offenders.append(f"{module}:{lineno} ({node.name})")
    assert offenders == [], (
        "쿼터 판정을 부르는 함수 안에 그 판정을 거치지 않고 재던지는 `except`가 "
        f"있다: {offenders}. 실패 분기가 둘인데 한쪽만 걸면 그쪽 run은 조용히 "
        "재시도를 산다."
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
    """재시도 정책을 단 asset은 전부 쿼터 판정을 지나야 한다."""

    guarded = _quota_guarded_functions()
    assert asset_name in guarded or calls & guarded, (
        f"{module}의 `{asset_name}`이 쿼터 판정을 지나지 않는다. "
        f"이 asset은 `FEATURE_LOAD_RETRY_POLICY`(max_retries=3)를 달고 있어 "
        "쿼터성 실패 하나가 성공할 수 없는 요청 3건과 backoff 420초를 더 쓴다. "
        f"`{_GUARD_CALL}`를 부르는 경계를 지나게 하거나, 지나지 않아도 되는 "
        "이유를 acceptance에 먼저 적어라."
    )


def test_the_guard_is_not_bypassed_by_an_unimported_symbol() -> None:
    """부르는 이름이 실제로 이 모듈에서 온 것인지 본다."""

    importers = {
        name
        for name, tree in _module_trees().items()
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "quota_exhaustion"
        and any(alias.name == _GUARD_CALL for alias in node.names)
    }
    assert "feature_operation_tracking.py" in importers, (
        "single-member asset 34개가 지나는 경계가 쿼터 판정을 `quota_exhaustion`에서 "
        "import하지 않는다"
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


def test_the_kma_result_does_not_carry_a_second_numerator() -> None:
    """분자의 정본은 하나여야 한다.

    종전에는 `KmaWeatherLoadResult.as_metadata()`가 `grids_fetched`를
    `upstream_requests_min`으로도 실었다. 그 둘은 **다른 수**다 — `grids_fetched`는
    호출에 **성공한** 격자 수이고, 실패해 중단된 격자도 요청은 나갔다. 같은 이름을
    두 곳이 들고 있으면 갈라지므로, 분자는 격자 루프가
    `note_upstream_request`로 세고 `_add_output_metadata`가 싣는다.
    """

    from kortravelmap.dagster.kma_weather import KmaWeatherLoadResult

    result = KmaWeatherLoadResult(
        provider="kma",
        dataset_key="kma_short_forecast",
        base_datetime="202609130200",
        skipped=False,
        grids_total=59,
        grids_fetched=59,
        grids_dropped=0,
        features_total=59,
        values_loaded=600,
        membership_fingerprint="abc",
    )
    metadata = result.as_metadata()
    assert metadata["grids_fetched"] == 59
    assert "upstream_requests_min" not in metadata, (
        "분자 정본이 둘이 됐다 — 격자 루프의 계수기가 정본이다."
    )


# ---------------------------------------------------------------- 분자 배선


_COUNTER_SCOPE = "counting_upstream_requests"


def test_the_counting_scope_is_opened_at_the_same_boundaries_as_the_guard() -> None:
    """분자 계수기와 쿼터 판정은 **같은 두 경계**에서 열려야 한다.

    계수기를 여는 자리를 놓치면 `test_upstream_request_numerator.py`는 전부
    초록인 채로 prod에서 아무것도 세지 않는다 — 그 파일은 계수기가 열린 뒤를
    재고, 여기서는 **그것이 열리는지**를 잰다.
    """

    openers = {
        node.name
        for _module, node in _functions()
        if _COUNTER_SCOPE in _called_names(node)
    }
    guarded = _quota_guarded_functions()
    missing = sorted(guarded - openers)
    assert missing == [], (
        f"쿼터 판정을 거는 경계가 분자 계수기를 열지 않는다: {missing}. "
        "판정과 계수는 같은 실행 범위의 두 얼굴이다 — 한쪽만 걸면 그 asset의 "
        "요청 수가 metadata에 실리지 않는다."
    )
    assert openers, "계수기를 여는 함수를 하나도 찾지 못했다 — 결박이 사라졌다"


def _parent_map(module: ast.Module) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(module):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _enclosing_with_calls(
    parents: dict[ast.AST, ast.AST], target: ast.AST
) -> set[str]:
    """``target``을 감싸는 ``with``의 context manager 이름 — **같은 함수 안에서만**.

    함수 경계에서 멈추는 이유는, 멈추지 않으면 ``with`` 안에 ``def``만 두고 그
    함수를 밖에서 불러도 초록이 되기 때문이다(3차 리뷰). 계수기는 **호출 시점**에
    열려 있어야 하므로 정의를 감싼 ``with``는 아무 의미가 없다.
    """

    names: set[str] = set()
    node: ast.AST | None = target
    while node is not None:
        if isinstance(node, ast.With | ast.AsyncWith):
            for item in node.items:
                expr = item.context_expr
                if isinstance(expr, ast.Call):
                    func = expr.func
                    if isinstance(func, ast.Name):
                        names.add(func.id)
                    elif isinstance(func, ast.Attribute):
                        names.add(func.attr)
        parent = parents.get(node)
        if isinstance(parent, ast.AsyncFunctionDef | ast.FunctionDef | ast.Lambda):
            # 여기서 끊는다 — 그 위의 with는 정의를 감쌀 뿐 호출을 감싸지 않는다.
            return names
        node = parent
    return names


def test_the_queue_runner_opens_the_counter_around_the_raw_run_function() -> None:
    """feature-update queue 경계도 계수기를 연다.

    이 경로는 asset wrapper가 아니라 **원본 run 함수**를 직접 부른다. 그래서
    wrapper가 여는 계수기가 여기엔 없다 — 열지 않으면 계측된 fetcher가 큐로 돌
    때 모든 `note_upstream_request()`가 no-op이 되고, 값이 조용히 사라진다
    (2026-09-13 2차 적대 리뷰 blocker).

    종전 구조 검사는 "쿼터 판정을 거는 함수가 계수기를 여는가"만 물었는데, 그
    두 집합이 정확히 같은 두 함수라 **동어반복**이었고 이 경계를 볼 수 없었다.
    여기서는 호출 자리를 AST로 찾아 **그 자리가 계수 범위 안에 있는지**를 본다.
    """

    module = ast.parse((_PACKAGE / "feature_update_runner.py").read_text(encoding="utf-8"))
    parents = _parent_map(module)
    # `spec.run(...)`은 호출이지만 `spec.resources`는 `asyncio.to_thread`에
    # **참조로** 넘어간다. 그래서 Call이 아니라 Attribute 노드를 찾는다 — 호출
    # 형태에 의존하면 참조 전달 한 줄로 검사를 빠져나갈 수 있다.
    dispatches = [
        node
        for node in ast.walk(module)
        if isinstance(node, ast.Attribute)
        and node.attr in {"run", "resources"}
        and isinstance(node.value, ast.Name)
        and node.value.id == "spec"
    ]
    found = sorted({node.attr for node in dispatches})
    assert found == ["resources", "run"], (
        f"runner가 raw run 함수와 resources 팩토리를 쓰는 자리를 찾지 못했다 — "
        f"{found}만 보인다. 이 검사가 아무것도 보지 않고 있다."
    )
    uncounted = [
        f"{node.attr}@{node.lineno}"
        for node in dispatches
        if _COUNTER_SCOPE not in _enclosing_with_calls(parents, node)
    ]
    assert uncounted == [], (
        f"계수 범위 **밖**에서 부른다({uncounted}). 그 경로의 "
        "`note_upstream_request()`는 전부 no-op이 되고, 계측된 진입점이 큐로 돌면 "
        "`upstream_requests_min` 없이 조용히 나간다. **`spec.resources`도 같은 "
        "범위여야 한다** — MOIS Phase A는 거기서 전국 파일을 받는다(3차 리뷰 blocker)."
    )


def test_the_asset_boundaries_open_the_counter_around_the_run_callable() -> None:
    """asset 경계 둘도 **호출을 감싸는지** 본다 — 이름이 나오는지가 아니라.

    종전 검사(`test_the_counting_scope_is_opened_at_the_same_boundaries_as_the_guard`)는
    "그 함수가 `counting_upstream_requests`를 부르는가"만 물었다. `with`를 실제
    호출 **밖**으로 빼도 전부 초록이었다(3차 리뷰). 여기서는 호출 노드를 찾아
    그것을 감싸는 `with`를 본다.
    """

    targets = [
        ("feature_operation_tracking.py", "run"),
        ("mcst_features.py", "run_feature_place_mcst_culture"),
    ]
    problems: list[str] = []
    for filename, callee in targets:
        module = ast.parse((_PACKAGE / filename).read_text(encoding="utf-8"))
        parents = _parent_map(module)
        calls = [
            node
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == callee
        ]
        assert calls, f"{filename}에서 `{callee}(...)` 호출을 찾지 못했다 — 유도가 낡았다."
        problems.extend(
            f"{filename}:{node.lineno}"
            for node in calls
            if _COUNTER_SCOPE not in _enclosing_with_calls(parents, node)
        )
    assert problems == [], (
        f"asset 경계가 run 호출을 계수 범위 밖에서 부른다: {problems}. "
        "`with counting_upstream_requests():`가 그 호출을 감싸야 한다 — "
        "이름이 같은 함수 안에 있기만 한 것으로는 부족하다."
    )


# `test_every_retrying_asset_counts_its_upstream_requests`는 여기 있었다(2026-09-13
# 제거). 이름과 달리 **항진명제였다** — 계수기를 여는 wrapper를 모든 asset이 지나므로
# `asset_name in openers or calls & openers`가 언제나 참이었고, 세지 않는 fetcher를
# 절대 볼 수 없었다. 적대 리뷰가 그것을 잡았다.
#
# 요청을 보내는 것은 asset이 아니라 **fetcher**다. 그래서 커버리지 검사는
# `tests/lint/test_every_fetcher_counts_or_declares_why_not.py`로 옮겼다 — 거기서는
# fetcher마다 계수 호출을 (전이 포함) 요구하고, 못 세는 것은 이유와 함께 선언한다.

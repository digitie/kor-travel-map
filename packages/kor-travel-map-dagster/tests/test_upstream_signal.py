"""상류 상태 신호(``upstream_signal``) — 미준비 판정·서비스 세대 나이·run tag·Valkey 재시도."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from dagster import Failure, RetryRequested
from kortravelmap.infra.valkey_state import GenerationMeta, StateStoreUnavailable
from kortravelmap.providers.kor_travel_transport import (
    TransportExportContractError,
    TransportExportEmpty,
    TransportExportHidden,
    TransportExportNotCurrent,
    TransportSnapshotExpired,
)
from kortravelmap.providers.kor_travel_weather import (
    WeatherExportMissing,
    WeatherExportNotReady,
)

from kortravelmap.dagster import upstream_signal
from kortravelmap.dagster.upstream_signal import (
    STALE_ALERT_TAG,
    UPSTREAM_STATE_TAG,
    jittered,
    raise_if_stale,
    refused,
    report_upstream_signal,
    retry_state_store_outage,
    served_age_seconds,
    upstream_not_ready_kind,
)

signal = upstream_signal.upstream_signal

NOW = datetime(2026, 11, 24, 0, 0, tzinfo=UTC)


def _meta(collected: datetime | None, loaded: datetime) -> GenerationMeta:
    return GenerationMeta(
        dataset="transport.highway_incidents",
        generation="g-1",
        count=30,
        geo_count=30,
        lookup_count=0,
        duplicates=0,
        source_collected_at=collected,
        loaded_at=loaded,
        run_id=None,
        guard_override=False,
    )


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (TransportExportNotCurrent("503"), "transport_not_current"),
        (TransportSnapshotExpired("410"), "transport_snapshot_expired"),
        (WeatherExportNotReady("503"), "weather_not_ready"),
        (httpx.ConnectTimeout("connect"), "upstream_unreachable:ConnectTimeout"),
        (httpx.RemoteProtocolError("끊김"), "upstream_unreachable:RemoteProtocolError"),
        (
            httpx.HTTPStatusError(
                "503",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(502, request=httpx.Request("GET", "http://x")),
            ),
            "upstream_http_502",
        ),
    ],
)
def test_waitable_upstream_failures_are_not_ready(error: Exception, kind: str) -> None:
    assert upstream_not_ready_kind(error) == kind


@pytest.mark.parametrize(
    "error",
    [
        TransportExportHidden("404"),
        TransportExportEmpty("0건"),  # 데이터 보호 — 거부 규칙이 따로 본다
        TransportExportContractError("모양"),
        WeatherExportMissing("404"),
        StateStoreUnavailable("Valkey"),  # Map 쪽 실패다
        RuntimeError("버그"),
        httpx.UnsupportedProtocol("scheme 없는 주소"),  # Map 설정 오류
        httpx.HTTPStatusError(
            "404",
            request=httpx.Request("GET", "http://x"),
            response=httpx.Response(404, request=httpx.Request("GET", "http://x")),
        ),
    ],
)
def test_terminal_or_map_side_failures_are_not_upstream_not_ready(error: Exception) -> None:
    assert upstream_not_ready_kind(error) is None


def _contract_over_a_retryable_cause() -> None:
    # weather ``_read_all_pages``가 순회 도중 422를 두 번 보면 이렇게 올린다.
    raise TransportExportContractError("두 번째도 422") from TransportExportNotCurrent("503")


def test_a_contract_error_decides_even_over_a_retryable_cause() -> None:
    with pytest.raises(TransportExportContractError) as excinfo:
        _contract_over_a_retryable_cause()
    assert upstream_not_ready_kind(excinfo.value) is None


def _wrapped() -> None:
    raise RuntimeError("감싼 예외") from WeatherExportNotReady("503")


def _failed_while_handling() -> None:
    try:
        raise httpx.ReadTimeout("느림")
    except httpx.ReadTimeout:
        raise RuntimeError("처리 중 난 다른 실패")  # noqa: B904 — 암묵 __context__가 요점이다


def test_the_cause_chain_decides_but_unrelated_context_does_not() -> None:
    with pytest.raises(RuntimeError) as wrapped:
        _wrapped()
    assert upstream_not_ready_kind(wrapped.value) == "weather_not_ready"
    with pytest.raises(RuntimeError) as unrelated:
        _failed_while_handling()
    assert unrelated.value.__context__ is not None
    assert upstream_not_ready_kind(unrelated.value) is None


def test_served_age_prefers_the_source_collection_and_falls_back_to_the_load() -> None:
    assert served_age_seconds(None, now=NOW) is None
    collected = _meta(NOW - timedelta(minutes=40), NOW - timedelta(minutes=5))
    assert served_age_seconds(collected, now=NOW) == 2_400
    no_source = _meta(None, NOW - timedelta(minutes=5))
    assert served_age_seconds(no_source, now=NOW) == 300
    rechecked = replace(no_source, checked_at=NOW - timedelta(minutes=1))
    assert served_age_seconds(rechecked, now=NOW) == 60  # 304 재확인이 적재보다 늦다
    future = _meta(NOW + timedelta(minutes=5), NOW)
    assert served_age_seconds(future, now=NOW) == 0  # 시계가 어긋나도 음수 나이는 없다


def test_signal_alerts_past_the_age_or_without_a_served_generation() -> None:
    fresh = _meta(NOW - timedelta(minutes=40), NOW)
    ok = signal("not_ready", served=fresh, alert_after=timedelta(hours=1), now=NOW, reason="r")
    assert ok == {
        "upstream_state": "not_ready",
        "upstream_reason": "r",
        "served_generation": "g-1",
        "served_source_collected_at": (NOW - timedelta(minutes=40)).isoformat(),
        "served_age_seconds": 2_400,
        "stale_alert_after_seconds": 3_600,
        "stale_alert": False,
    }
    old = signal("ok", served=fresh, alert_after=timedelta(minutes=30), now=NOW)
    assert old["stale_alert"] is True
    none = signal("not_ready", served=None, alert_after=timedelta(hours=1), now=NOW)
    assert none["served_age_seconds"] == -1
    assert none["stale_alert"] is True


def test_refusal_keeps_the_generation_and_the_age_decides_the_run() -> None:
    kwargs: dict[str, Any] = {
        "dataset": "transport.highway_incidents",
        "failure_kind": "state_swap_refused",
        "description": "0건",
        "alert_after": timedelta(hours=1),
        "now": NOW,
        "details": {"baseline": 30, "new_count": 0},
    }
    fresh = refused(served=_meta(NOW - timedelta(minutes=10), NOW), **kwargs)
    assert fresh["skipped"] == "refused"
    assert fresh["upstream_state"] == "refused"
    assert fresh["baseline"] == 30
    raise_if_stale(fresh)  # 기준 안 — 성공
    old = refused(served=_meta(NOW - timedelta(hours=2), NOW), **kwargs)
    with pytest.raises(Failure) as excinfo:
        raise_if_stale(old)
    assert excinfo.value.allow_retries is False
    assert "allow_shrink" in str(excinfo.value.description)
    assert str(excinfo.value.metadata["step_retries_suppressed"].value) == "true"


@pytest.mark.parametrize("state", ["not_ready", "ok", "stale"])
def test_every_state_past_the_age_fails_and_says_why(state: str) -> None:
    metadata = signal(
        state,
        served=_meta(NOW - timedelta(hours=5), NOW),
        alert_after=timedelta(hours=3),
        now=NOW,
        reason="transport_not_current",
    )
    with pytest.raises(Failure) as excinfo:
        raise_if_stale({"dataset": "weather.current", **metadata})
    description = str(excinfo.value.description)
    assert "18000초" in description
    assert "10800초" in description
    assert state in description


def test_no_served_generation_fails_once_the_upstream_is_not_ready() -> None:
    metadata = signal("not_ready", served=None, alert_after=timedelta(hours=3), now=NOW)
    with pytest.raises(Failure) as excinfo:
        raise_if_stale(metadata)
    assert "첫 적재 전" in str(excinfo.value.description)
    raise_if_stale({"dataset": "x", "skipped": "locked"})  # 잠금 건너뜀은 상류를 보지 않았다


class _Log:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str, *args: Any) -> None:
        self.warnings.append(message % args)


def _context(*, fail_tags: bool = False, retry_number: int = 0) -> Any:
    tagged: list[tuple[str, dict[str, str]]] = []

    def add_run_tags(run_id: str, tags: dict[str, str]) -> None:
        if fail_tags:
            raise RuntimeError("storage 일시 장애")
        tagged.append((run_id, tags))

    return SimpleNamespace(
        run_id="run-1",
        instance=SimpleNamespace(add_run_tags=add_run_tags),
        log=_Log(),
        tagged=tagged,
        retry_number=retry_number,
    )


def test_report_always_writes_both_tags_and_warns_only_when_not_plain_ok() -> None:
    quiet = _context()
    report_upstream_signal(quiet, {"upstream_state": "ok", "stale_alert": False})
    report_upstream_signal(quiet, {"dataset": "x", "skipped": "locked"})
    # 부모 tag를 물려받는 재실행이 낡은 경고를 들고 다니지 않게 ok도 쓴다.
    assert quiet.tagged == [("run-1", {UPSTREAM_STATE_TAG: "ok", STALE_ALERT_TAG: "false"})]
    assert quiet.log.warnings == []

    stale = _context()
    report_upstream_signal(
        stale,
        {
            "dataset": "transport.fuel_stations",
            "upstream_state": "not_ready",
            "upstream_reason": "transport_not_current",
            "served_generation": "g-1",
            "served_age_seconds": 180_000,
            "stale_alert_after_seconds": 172_800,
            "stale_alert": True,
        },
    )
    assert stale.tagged == [("run-1", {UPSTREAM_STATE_TAG: "not_ready", STALE_ALERT_TAG: "true"})]
    (warning,) = stale.log.warnings
    assert "transport_not_current" in warning
    assert "stale 기준 초과" in warning


def test_report_survives_a_tag_write_failure() -> None:
    context = _context(fail_tags=True)
    report_upstream_signal(context, {"upstream_state": "refused", "stale_alert": False})
    assert len(context.log.warnings) == 1


def test_valkey_outage_requests_a_jittered_step_retry_within_the_run() -> None:
    error = StateStoreUnavailable("연결 실패")
    with pytest.raises(RetryRequested) as excinfo:
        retry_state_store_outage(
            cast(Any, _context(retry_number=1)), error, deadline=time.monotonic() + 600
        )
    assert excinfo.value.max_retries == 2
    assert 48 <= excinfo.value.seconds_to_wait <= 72  # 60초 ± 20%
    assert excinfo.value.__cause__ is error


@pytest.mark.parametrize(("retry_number", "remaining"), [(2, 600.0), (0, 20.0)])
def test_valkey_outage_fails_when_retries_or_run_time_are_used_up(
    retry_number: int, remaining: float
) -> None:
    error = StateStoreUnavailable("연결 실패")
    with pytest.raises(StateStoreUnavailable):
        retry_state_store_outage(
            cast(Any, _context(retry_number=retry_number)),
            error,
            deadline=time.monotonic() + remaining,
        )


def test_jitter_stays_within_twenty_percent() -> None:
    values = [jittered(100.0) for _ in range(200)]
    assert all(80.0 <= value <= 120.0 for value in values)
    assert len(set(values)) > 1
    assert jittered(0.0) == 0.0


def test_run_deadline_counts_from_the_run_start() -> None:
    started = time.time() - 100
    context = SimpleNamespace(
        instance=SimpleNamespace(
            get_run_record_by_id=lambda _id: SimpleNamespace(start_time=started)
        ),
        run_id="run-x",
        run=SimpleNamespace(tags={"dagster/max_runtime": "1000"}),
    )
    remaining = upstream_signal.run_deadline(cast(Any, context), 480, 60) - time.monotonic()
    assert 1000 - 165 < remaining < 1000 - 159.99

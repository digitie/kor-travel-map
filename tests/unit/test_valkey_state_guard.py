"""ADR-114 D4 비정상 집합 거부 판정과 상태 키 규칙 — 순수 함수만(Valkey 없이)."""

from __future__ import annotations

import pytest

from kortravelmap.infra.valkey_state import (
    STATE_KEY_PREFIX,
    ShrinkGuard,
    StateStoreNotConfigured,
    evaluate_shrink_guard,
    make_valkey_client,
    state_key,
)
from kortravelmap.providers.kor_travel_transport_state import (
    DATASET_FUEL_STATIONS,
    DATASET_HIGHWAY_INCIDENTS,
    TRANSPORT_STATE_DATASETS,
)
from kortravelmap.settings import KorTravelMapSettings

pytestmark = pytest.mark.unit

INCIDENTS = DATASET_HIGHWAY_INCIDENTS.guard
FUEL = DATASET_FUEL_STATIONS.guard


def test_krex_empty_response_is_refused() -> None:
    """2026-10-23 사고: 활성 돌발 106건 뒤 빈 응답 — 교체하지 않는다."""
    reason = evaluate_shrink_guard([106], 0, INCIDENTS)
    assert reason is not None
    assert "0건" in reason


def test_gradual_decline_is_measured_against_the_recent_maximum() -> None:
    """106 → 27 → 7: 직전(27)과만 비교하면 7은 통과한다. 최근 최대(106)와 비교해 거부한다."""
    assert evaluate_shrink_guard([106], 27, INCIDENTS) is None
    assert evaluate_shrink_guard([27, 106], 7, INCIDENTS) is not None
    # 대조: 직전 하나만 보면 받아들였을 값이다(7 ≥ ceil(27×0.25)=7).
    assert evaluate_shrink_guard([27], 7, INCIDENTS) is None


def test_ratio_boundary_is_the_ceiling() -> None:
    guard = ShrinkGuard(min_ratio=0.25, baseline_min=20)
    # ceil(106 × 0.25) = 27 — 27은 통과, 26은 거부.
    assert evaluate_shrink_guard([106], 27, guard) is None
    assert evaluate_shrink_guard([106], 26, guard) is not None


def test_small_baseline_skips_the_ratio_and_allows_empty_only_when_declared() -> None:
    assert evaluate_shrink_guard([19], 1, INCIDENTS) is None
    assert evaluate_shrink_guard([19], 0, INCIDENTS) is None
    assert evaluate_shrink_guard([20], 0, INCIDENTS) is not None
    no_empty = ShrinkGuard(min_ratio=0.5, baseline_min=20)
    assert evaluate_shrink_guard([3], 0, no_empty) is not None


def test_first_load_obeys_the_absolute_floor() -> None:
    assert evaluate_shrink_guard([], 9_999, FUEL) is not None
    assert evaluate_shrink_guard([], 10_000, FUEL) is None
    assert evaluate_shrink_guard([], 0, INCIDENTS) is None


def test_absolute_floor_applies_even_when_ratio_would_pass() -> None:
    assert evaluate_shrink_guard([10_100], 9_500, FUEL) is not None


def test_allow_shrink_overrides_every_refusal() -> None:
    assert evaluate_shrink_guard([106], 0, INCIDENTS, allow_shrink=True) is None
    assert evaluate_shrink_guard([], 0, FUEL, allow_shrink=True) is None


def test_growth_is_always_accepted() -> None:
    assert evaluate_shrink_guard([11_000], 12_000, FUEL) is None


def test_guard_rejects_nonsense_configuration() -> None:
    with pytest.raises(ValueError, match="min_ratio"):
        ShrinkGuard(min_ratio=0.0, baseline_min=1)
    with pytest.raises(ValueError, match="baseline_min"):
        ShrinkGuard(min_ratio=0.5, baseline_min=0)
    with pytest.raises(ValueError, match="음수"):
        evaluate_shrink_guard([], -1, FUEL)


def test_every_dataset_refuses_the_empty_response_after_a_large_set() -> None:
    """데이터셋 정의가 바뀌어도 '큰 집합 뒤 0건'은 모두 거부해야 한다."""
    for dataset in TRANSPORT_STATE_DATASETS:
        big = max(dataset.guard.baseline_min, dataset.guard.min_count) * 2
        assert evaluate_shrink_guard([big], 0, dataset.guard) is not None, dataset.name


def test_state_keys_are_namespaced_and_reject_separator_injection() -> None:
    assert state_key("transport.fuel_stations", "current") == (
        f"{STATE_KEY_PREFIX}:transport.fuel_stations:current"
    )
    for bad in ("", "a:b"):
        with pytest.raises(ValueError, match="성분"):
            state_key(bad, "current")
        with pytest.raises(ValueError, match="성분"):
            state_key("transport.airports", bad)


def test_missing_url_is_not_configured_and_hides_nothing() -> None:
    settings = KorTravelMapSettings.model_construct(valkey_url=None)
    with pytest.raises(StateStoreNotConfigured) as excinfo:
        make_valkey_client(settings)
    assert excinfo.value.retryable is False
    assert excinfo.value.failure_kind == "state_store_not_configured"


def test_client_does_not_retry_and_uses_the_configured_timeouts() -> None:
    from pydantic import SecretStr

    settings = KorTravelMapSettings.model_construct(
        valkey_url=SecretStr("redis://:pw@127.0.0.1:1/0"),
        valkey_connect_timeout_seconds=0.7,
        valkey_socket_timeout_seconds=1.3,
    )
    client = make_valkey_client(settings)
    kwargs = client.connection_pool.connection_kwargs
    assert kwargs["socket_connect_timeout"] == 0.7
    assert kwargs["socket_timeout"] == 1.3
    assert kwargs["password"] == "pw"
    # 연결 층과 client 층 둘 다 재시도가 꺼져 있어야 "곧바로 503"이 된다.
    for retry in (kwargs.get("retry"), client.get_retry()):
        assert retry is not None
        assert retry.get_retries() == 0


def test_malformed_url_is_not_configured_and_does_not_echo_the_password() -> None:
    from pydantic import SecretStr

    settings = KorTravelMapSettings.model_construct(
        valkey_url=SecretStr("redis://:se/cret@127.0.0.1:6379/0"),
        valkey_connect_timeout_seconds=1.0,
        valkey_socket_timeout_seconds=1.0,
    )
    with pytest.raises(StateStoreNotConfigured) as excinfo:
        make_valkey_client(settings)
    assert "cret" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


"""``test_ids_weather`` — make_weather_value_key (PR#38, ADR-010)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kortravelmap.core.ids import (
    WEATHER_VALUE_KEY_HASH_LENGTH,
    make_weather_value_key,
)

KST = timezone(timedelta(hours=9))


_BASE_ARGS = dict(
    feature_id="f_global_w_seoul",
    provider="python-kma-api",
    weather_domain="kma_short_forecast",
    forecast_style="short",
    metric_key="TMP",
)


@pytest.mark.unit
def test_returns_wv_prefix_and_correct_length() -> None:
    key = make_weather_value_key(**_BASE_ARGS)
    assert key.startswith("wv_")
    assert len(key) == 3 + WEATHER_VALUE_KEY_HASH_LENGTH


@pytest.mark.unit
def test_deterministic_same_input() -> None:
    a = make_weather_value_key(**_BASE_ARGS)
    b = make_weather_value_key(**_BASE_ARGS)
    assert a == b


@pytest.mark.unit
def test_differs_when_metric_key_changes() -> None:
    a = make_weather_value_key(**_BASE_ARGS)
    b = make_weather_value_key(**{**_BASE_ARGS, "metric_key": "REH"})
    assert a != b


@pytest.mark.unit
def test_differs_when_provider_changes() -> None:
    a = make_weather_value_key(**_BASE_ARGS)
    b = make_weather_value_key(**{**_BASE_ARGS, "provider": "python-krforest-api"})
    assert a != b


@pytest.mark.unit
def test_differs_when_valid_at_changes() -> None:
    a = make_weather_value_key(
        **_BASE_ARGS,
        valid_at=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
    )
    b = make_weather_value_key(
        **_BASE_ARGS,
        valid_at=datetime(2026, 5, 28, 12, 0, tzinfo=KST),
    )
    assert a != b


@pytest.mark.unit
def test_same_when_only_timeline_bucket_would_change() -> None:
    """make_weather_value_key는 timeline_bucket을 인자로 받지 않음 — ADR-010."""
    # 같은 input은 같은 key. timeline_bucket이 다르더라도 key 계산에 영향 X.
    a = make_weather_value_key(
        **_BASE_ARGS,
        issued_at=datetime(2026, 5, 27, 23, 0, tzinfo=KST),
        valid_at=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
    )
    b = make_weather_value_key(
        **_BASE_ARGS,
        issued_at=datetime(2026, 5, 27, 23, 0, tzinfo=KST),
        valid_at=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
    )
    assert a == b


@pytest.mark.unit
def test_empty_feature_id_rejected() -> None:
    with pytest.raises(ValueError, match="비어"):
        make_weather_value_key(
            **{**_BASE_ARGS, "feature_id": ""},
        )


@pytest.mark.unit
def test_pipe_separator_in_component_rejected() -> None:
    """| 구분자 충돌 차단 (ADR-009)."""
    with pytest.raises(ValueError, match=r"'\|'"):
        make_weather_value_key(
            **{**_BASE_ARGS, "metric_key": "BAD|KEY"},
        )


@pytest.mark.unit
def test_all_time_fields_none_ok() -> None:
    """시간 필드 미상이어도 key 생성 가능 (advisory 등)."""
    key = make_weather_value_key(**_BASE_ARGS)
    assert key.startswith("wv_")

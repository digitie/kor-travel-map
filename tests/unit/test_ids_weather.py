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
    provider_dataset_id=42,
    weather_domain="kma_short_forecast",
    forecast_style="short",
    metric_key="TMP",
    target_at=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
    source_record_key="sr_weather_response_a",
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
def test_differs_when_dataset_changes() -> None:
    a = make_weather_value_key(**_BASE_ARGS)
    b = make_weather_value_key(**{**_BASE_ARGS, "provider_dataset_id": 43})
    assert a != b


@pytest.mark.unit
def test_differs_when_target_or_response_revision_changes() -> None:
    a = make_weather_value_key(**_BASE_ARGS)
    b = make_weather_value_key(
        **{**_BASE_ARGS, "target_at": datetime(2026, 5, 28, 12, 0, tzinfo=KST)}
    )
    assert a != b
    assert a != make_weather_value_key(**{**_BASE_ARGS, "source_record_key": "sr_b"})


@pytest.mark.unit
def test_same_when_only_timeline_bucket_would_change() -> None:
    """timeline_bucket은 immutable fact identity에 참여하지 않는다."""
    # 같은 input은 같은 key. timeline_bucket이 다르더라도 key 계산에 영향 X.
    a = make_weather_value_key(**_BASE_ARGS)
    b = make_weather_value_key(**_BASE_ARGS)
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
def test_nonpositive_dataset_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        make_weather_value_key(**{**_BASE_ARGS, "provider_dataset_id": 0})

"""``test_ids_price`` — make_price_value_key (PR#42)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from kortravelmap.core.ids import (
    PRICE_VALUE_KEY_HASH_LENGTH,
    make_price_value_key,
)

KST = timezone(timedelta(hours=9))

_BASE = dict(
    feature_id="f_1156010100_p_abc",
    provider_dataset_id=17,
    price_domain="opinet_gas_station",
    product_key="gasoline",
    observed_at=datetime(2026, 5, 28, 3, 0, tzinfo=KST),
    source_record_key="sr_price_response_a",
)


@pytest.mark.unit
def test_returns_pv_prefix_correct_length() -> None:
    key = make_price_value_key(**_BASE)
    assert key.startswith("pv_")
    assert len(key) == 3 + PRICE_VALUE_KEY_HASH_LENGTH


@pytest.mark.unit
def test_deterministic_same_input() -> None:
    assert make_price_value_key(**_BASE) == make_price_value_key(**_BASE)


@pytest.mark.unit
def test_differs_when_product_changes() -> None:
    a = make_price_value_key(**_BASE)
    b = make_price_value_key(**{**_BASE, "product_key": "diesel"})
    assert a != b


@pytest.mark.unit
def test_differs_when_observed_at_changes() -> None:
    a = make_price_value_key(**_BASE)
    b = make_price_value_key(
        **{**_BASE, "observed_at": datetime(2026, 5, 28, 4, 0, tzinfo=KST)}
    )
    assert a != b


@pytest.mark.unit
def test_differs_when_provider_dataset_changes() -> None:
    a = make_price_value_key(**_BASE)
    b = make_price_value_key(**{**_BASE, "provider_dataset_id": 18})
    assert a != b


@pytest.mark.unit
def test_differs_when_source_response_revision_changes() -> None:
    a = make_price_value_key(**_BASE)
    b = make_price_value_key(**{**_BASE, "source_record_key": "sr_price_response_b"})
    assert a != b


@pytest.mark.unit
def test_empty_component_rejected() -> None:
    with pytest.raises(ValueError, match="비어"):
        make_price_value_key(**{**_BASE, "product_key": ""})


@pytest.mark.unit
def test_pipe_separator_rejected() -> None:
    with pytest.raises(ValueError, match=r"'\|'"):
        make_price_value_key(**{**_BASE, "product_key": "bad|key"})

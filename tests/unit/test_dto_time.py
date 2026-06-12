"""``test_dto_time`` — KST aware datetime helpers + 공용 validator (ADR-019).

PR#24 review report P0-2: 모든 DTO datetime 필드에 동일 정책 적용. 본 테스트는
helper 자체와 ``RawDataRef.fetched_at``에 적용된 validator 검증.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from kortravelmap.dto import RawDataRef, check_aware_datetime, kst_now
from kortravelmap.dto._time import KST


@pytest.mark.unit
def test_kst_is_asia_seoul() -> None:
    """``KST`` 상수는 정확히 ``Asia/Seoul``."""
    assert ZoneInfo("Asia/Seoul") == KST


@pytest.mark.unit
def test_kst_now_is_aware() -> None:
    """``kst_now()``는 항상 KST aware datetime."""
    dt = kst_now()
    assert dt.tzinfo is not None
    assert dt.utcoffset() is not None
    # KST = UTC+9
    assert dt.utcoffset().total_seconds() == 9 * 3600


# ── check_aware_datetime helper ────────────────────────────────────────


@pytest.mark.unit
def test_check_aware_datetime_accepts_kst() -> None:
    """KST aware datetime은 통과 (그대로 반환)."""
    dt = datetime(2026, 1, 1, 12, 0, tzinfo=KST)
    assert check_aware_datetime(dt) is dt


@pytest.mark.unit
def test_check_aware_datetime_accepts_utc() -> None:
    """UTC aware datetime도 통과 (다른 tz 허용 — 변환은 호출자 책임)."""
    dt = datetime(2026, 1, 1, 3, 0, tzinfo=UTC)
    assert check_aware_datetime(dt) is dt


@pytest.mark.unit
def test_check_aware_datetime_accepts_none() -> None:
    """``None``은 그대로 통과 (선택 필드 호환)."""
    assert check_aware_datetime(None) is None


@pytest.mark.unit
def test_check_aware_datetime_rejects_naive() -> None:
    """``tzinfo=None``인 naive datetime은 ValueError."""
    with pytest.raises(ValueError, match="timezone-aware"):
        check_aware_datetime(datetime(2026, 1, 1, 12, 0))


# ── RawDataRef.fetched_at (review report P0-2) ─────────────────────────


@pytest.mark.unit
def test_raw_data_ref_naive_fetched_at_rejected() -> None:
    """``RawDataRef.fetched_at``에 naive datetime은 ValidationError."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        RawDataRef(
            provider="visitkorea",
            dataset_key="festival",
            source_entity_id="E001",
            fetched_at=datetime(2026, 1, 1, 12, 0),  # naive
        )


@pytest.mark.unit
def test_raw_data_ref_aware_fetched_at_accepted() -> None:
    """KST/UTC aware datetime 모두 허용."""
    ref_kst = RawDataRef(
        provider="visitkorea",
        dataset_key="festival",
        source_entity_id="E001",
        fetched_at=datetime(2026, 1, 1, 12, 0, tzinfo=KST),
    )
    assert ref_kst.fetched_at is not None

    ref_utc = RawDataRef(
        provider="visitkorea",
        dataset_key="festival",
        source_entity_id="E002",
        fetched_at=datetime(2026, 1, 1, 3, 0, tzinfo=UTC),
    )
    assert ref_utc.fetched_at is not None


@pytest.mark.unit
def test_raw_data_ref_none_fetched_at_accepted() -> None:
    """``fetched_at=None`` (default) 허용."""
    ref = RawDataRef(
        provider="visitkorea",
        dataset_key="festival",
        source_entity_id="E001",
    )
    assert ref.fetched_at is None

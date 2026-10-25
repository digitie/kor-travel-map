"""복구 TX 상한은 기존 서버 설정을 덮어 늘리지 않고 deadline도 지킨다."""

import time
from unittest.mock import AsyncMock

import pytest

from kortravelmap.infra.transaction_limits import (
    apply_bounded_transaction_limits,
    connection_check_interval,
    transaction_deadline,
)


async def test_bounded_caps_without_deadline_and_existing_settings_minimum():
    session = AsyncMock()
    await apply_bounded_transaction_limits(session)
    query, params = session.execute.await_args.args
    assert params == {"statement": 30000, "lock": 1000}
    assert "LEAST(COALESCE(NULLIF(setting::bigint,0),cap),cap)" in str(query)
    assert "set_config(name" in str(query)


async def test_short_outer_deadline_and_connection_check_are_preserved():
    session = AsyncMock()
    with transaction_deadline(time.monotonic() + 1), connection_check_interval(2):
        await apply_bounded_transaction_limits(session)
    assert session.execute.await_args_list[0].args[1] == {"statement": 1000, "lock": 500}
    query, params = session.execute.await_args_list[1].args
    assert params == {"interval": 2000}
    assert "LEAST" in str(query)


@pytest.mark.parametrize("cap", [0, -1, True, 1.5])
async def test_invalid_cap_is_rejected_before_sql(cap):
    session = AsyncMock()
    with pytest.raises(ValueError, match="positive"):
        await apply_bounded_transaction_limits(session, lock_timeout_ms=cap)
    session.execute.assert_not_awaited()

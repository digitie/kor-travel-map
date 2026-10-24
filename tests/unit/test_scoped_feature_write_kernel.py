"""공식 Python 경계의 무제한 입력·암묵 TX를 거부한다."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.infra.scoped_feature_writes import (
    ScopedWriteDependency,
    ScopedWriteRegion,
    append_scoped_feature_write_manifest,
    claim_scoped_feature_write,
    lock_scoped_feature_write_protocol,
)


@pytest.mark.parametrize(
    ("version", "key"), [(True, "a"), (0, "a"), (2147483648, "a"), (1, ""), (1, "a/b"), (1, "가")]
)
def test_region_shape(version, key):
    with pytest.raises(ValueError, match="invalid|unsupported"):
        ScopedWriteRegion(version, key)


@pytest.mark.parametrize(
    ("ordinal", "kind", "key", "value"),
    [
        (True, "feature", str(uuid4()), "1"),
        (8192, "feature", str(uuid4()), "1"),
        (0, "other", "a", "1"),
        (0, "feature", "bad", "1"),
        (0, "feature", str(uuid4()), "0"),
        (0, "source_head", "x" * 129, "1"),
    ],
)
def test_member_shape(ordinal, kind, key, value):
    with pytest.raises(ValueError, match="invalid|unsupported"):
        ScopedWriteDependency(ordinal, kind, key, value)


async def test_transaction_is_explicit():
    async with AsyncSession() as session:
        with pytest.raises(ValueError, match="transaction"):
            await lock_scoped_feature_write_protocol(session, exclusive=False)


async def test_region_input_consumption_is_bounded():
    seen = 0

    def regions():
        nonlocal seen
        while True:
            seen += 1
            yield ScopedWriteRegion(1, str(seen))

    async with AsyncSession() as session, session.begin():
        with pytest.raises(ValueError, match="bounded"):
            await claim_scoped_feature_write(
                session,
                attempt_id=uuid4(),
                owner=uuid4(),
                dataset_id=1,
                idempotency_key="fixture",
                regions=regions(),
                input_digest="a" * 64,
                expected_members=0,
            )
    assert seen == 257


async def test_manifest_input_consumption_is_bounded():
    seen = 0

    def members():
        nonlocal seen
        while True:
            seen += 1
            yield ScopedWriteDependency(seen - 1, "source_head", str(seen), "record")

    async with AsyncSession() as session, session.begin():
        with pytest.raises(ValueError, match="bounded"):
            await append_scoped_feature_write_manifest(
                session, attempt_id=uuid4(), owner=uuid4(), members=members()
            )
    assert seen == 257

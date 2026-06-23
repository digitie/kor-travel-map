"""``ops.public_api_keys`` helper 단위 테스트."""

from __future__ import annotations

from typing import Any, cast

import pytest

from kortravelmap.infra.public_api_keys import (
    generate_public_api_key,
    hash_public_api_key,
    public_api_key_matches,
    revoke_public_api_key,
)


@pytest.mark.unit
def test_generate_public_api_key_uses_vworld_wire_shape() -> None:
    api_key = generate_public_api_key()

    assert len(api_key) == 32
    assert api_key.isalnum()


@pytest.mark.unit
def test_public_api_key_matches_hash_constant_time_surface() -> None:
    key_hashes = frozenset({hash_public_api_key("abc123")})

    assert public_api_key_matches("abc123", key_hashes)
    assert not public_api_key_matches("wrong", key_hashes)


@pytest.mark.unit
async def test_revoke_public_api_key_invalid_uuid_returns_none_without_db_call() -> None:
    class NoDbSession:
        async def execute(self, *_args: object, **_kwargs: object) -> object:
            raise AssertionError("invalid UUID must not reach the database")

    assert (
        await revoke_public_api_key(
            cast(Any, NoDbSession()),
            "not-a-uuid",
            revoked_by="admin",
        )
        is None
    )

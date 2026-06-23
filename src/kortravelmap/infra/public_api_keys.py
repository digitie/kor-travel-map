"""``ops.public_api_keys`` — VWorld 호환 public API key 저장/검증."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import string
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import TYPE_CHECKING, Any, Final, Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "PUBLIC_API_KEY_QUERY_PARAM",
    "PublicApiKeyCreateResult",
    "PublicApiKeyRow",
    "PublicApiKeyState",
    "active_public_api_key_hashes",
    "cached_active_public_api_key_hashes",
    "create_public_api_key",
    "generate_public_api_key",
    "hash_public_api_key",
    "invalidate_public_api_key_cache",
    "list_public_api_keys",
    "public_api_key_matches",
    "revoke_public_api_key",
]

PUBLIC_API_KEY_QUERY_PARAM: Final[str] = "key"
PUBLIC_API_KEY_LENGTH: Final[int] = 32
PUBLIC_API_KEY_ALPHABET: Final[str] = string.ascii_letters + string.digits
PublicApiKeyState = Literal["active", "revoked"]


@dataclass(frozen=True, slots=True)
class PublicApiKeyRow:
    """``ops.public_api_keys`` 조회 행."""

    public_api_key_id: str
    key_hint: str
    state: PublicApiKeyState
    created_at: datetime
    label: str | None = None
    created_by: str | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None


@dataclass(frozen=True, slots=True)
class PublicApiKeyCreateResult:
    """생성된 public API key. ``key`` 원문은 이 응답에서만 노출한다."""

    key: str
    item: PublicApiKeyRow


@dataclass(frozen=True, slots=True)
class _ActiveKeyCacheEntry:
    hashes: frozenset[str]
    expires_at: float


_active_key_cache: _ActiveKeyCacheEntry | None = None
_active_key_cache_lock = asyncio.Lock()


_PUBLIC_API_KEY_SELECT: Final[str] = """
SELECT public_api_key_id::text AS public_api_key_id,
       label,
       key_hint,
       state,
       created_at,
       created_by,
       revoked_at,
       revoked_by
  FROM ops.public_api_keys
"""


def generate_public_api_key() -> str:
    """VWorld wire shape과 같은 32자 영숫자 key를 생성한다."""

    return "".join(
        secrets.choice(PUBLIC_API_KEY_ALPHABET)
        for _ in range(PUBLIC_API_KEY_LENGTH)
    )


def hash_public_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.strip().encode("utf-8")).hexdigest()


def public_api_key_matches(api_key: str, key_hashes: frozenset[str]) -> bool:
    key_hash = hash_public_api_key(api_key)
    return any(hmac.compare_digest(key_hash, stored_hash) for stored_hash in key_hashes)


async def cached_active_public_api_key_hashes(
    session: AsyncSession,
    *,
    ttl_seconds: int,
) -> frozenset[str]:
    """public 요청 hot path용 active key hash 캐시."""

    global _active_key_cache
    now = monotonic()
    cached = _active_key_cache
    if cached is not None and cached.expires_at > now:
        return cached.hashes
    async with _active_key_cache_lock:
        cached = _active_key_cache
        now = monotonic()
        if cached is not None and cached.expires_at > now:
            return cached.hashes
        hashes = await active_public_api_key_hashes(session)
        _active_key_cache = _ActiveKeyCacheEntry(
            hashes=hashes,
            expires_at=now + max(ttl_seconds, 0),
        )
        return hashes


def invalidate_public_api_key_cache() -> None:
    global _active_key_cache
    _active_key_cache = None


async def active_public_api_key_hashes(session: AsyncSession) -> frozenset[str]:
    rows = (
        await session.execute(
            text(
                """
SELECT key_hash
  FROM ops.public_api_keys
 WHERE state = 'active'
"""
            )
        )
    ).scalars().all()
    return frozenset(str(row) for row in rows)


async def list_public_api_keys(
    session: AsyncSession,
    *,
    limit: int = 100,
) -> tuple[PublicApiKeyRow, ...]:
    rows = (
        await session.execute(
            text(_PUBLIC_API_KEY_SELECT + " ORDER BY created_at DESC LIMIT :limit"),
            {"limit": limit},
        )
    ).mappings().all()
    return tuple(_map_public_api_key(row) for row in rows)


async def create_public_api_key(
    session: AsyncSession,
    *,
    label: str | None,
    created_by: str | None,
) -> PublicApiKeyCreateResult:
    normalized_label = label.strip() if label is not None else None
    if normalized_label == "":
        normalized_label = None
    api_key = generate_public_api_key()
    row = (
        await session.execute(
            text(
                """
INSERT INTO ops.public_api_keys
  (public_api_key_id, key_hash, key_hint, label, created_by)
VALUES
  (:public_api_key_id, :key_hash, :key_hint, :label, :created_by)
RETURNING public_api_key_id::text AS public_api_key_id,
          label,
          key_hint,
          state,
          created_at,
          created_by,
          revoked_at,
          revoked_by
"""
            ),
            {
                "public_api_key_id": str(uuid4()),
                "key_hash": hash_public_api_key(api_key),
                "key_hint": api_key[-6:],
                "label": normalized_label,
                "created_by": created_by,
            },
        )
    ).mappings().one()
    invalidate_public_api_key_cache()
    return PublicApiKeyCreateResult(key=api_key, item=_map_public_api_key(row))


async def revoke_public_api_key(
    session: AsyncSession,
    public_api_key_id: str,
    *,
    revoked_by: str | None,
) -> PublicApiKeyRow | None:
    try:
        normalized_public_api_key_id = str(UUID(public_api_key_id))
    except ValueError:
        return None
    row = (
        await session.execute(
            text(
                """
UPDATE ops.public_api_keys
   SET state = 'revoked',
       revoked_at = now(),
       revoked_by = :revoked_by
 WHERE public_api_key_id = :public_api_key_id
   AND state = 'active'
RETURNING public_api_key_id::text AS public_api_key_id,
          label,
          key_hint,
          state,
          created_at,
          created_by,
          revoked_at,
          revoked_by
"""
            ),
            {
                "public_api_key_id": normalized_public_api_key_id,
                "revoked_by": revoked_by,
            },
        )
    ).mappings().first()
    if row is None:
        return None
    invalidate_public_api_key_cache()
    return _map_public_api_key(row)


def _map_public_api_key(row: Any) -> PublicApiKeyRow:
    data = dict(row)
    state = str(data["state"])
    if state not in {"active", "revoked"}:
        raise ValueError(f"invalid public API key state: {state}")
    return PublicApiKeyRow(
        public_api_key_id=str(data["public_api_key_id"]),
        label=str(data["label"]) if data.get("label") is not None else None,
        key_hint=str(data["key_hint"]),
        state=cast(PublicApiKeyState, state),
        created_at=data["created_at"],
        created_by=(
            str(data["created_by"]) if data.get("created_by") is not None else None
        ),
        revoked_at=data.get("revoked_at"),
        revoked_by=(
            str(data["revoked_by"]) if data.get("revoked_by") is not None else None
        ),
    )

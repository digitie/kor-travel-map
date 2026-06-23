"""``ops.admin_auth_events`` — admin UI 로그인/로그아웃 감사 기록."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "AdminAuthEventOutcome",
    "AdminAuthEventRow",
    "AdminAuthEventType",
    "list_admin_auth_events",
    "record_admin_auth_event",
]

AdminAuthEventType = Literal["login", "logout"]
AdminAuthEventOutcome = Literal["succeeded", "failed", "denied"]


@dataclass(frozen=True, slots=True)
class AdminAuthEventRow:
    """``ops.admin_auth_events`` 조회 행."""

    auth_event_id: str
    event_type: AdminAuthEventType
    outcome: AdminAuthEventOutcome
    attempted_username: str | None
    actor: str | None
    reason: str | None
    next_path: str | None
    client_ip: str | None
    user_agent: str | None
    request_id: str | None
    created_at: datetime


_AUTH_EVENT_COLUMNS: Final[str] = """
auth_event_id::text AS auth_event_id,
event_type,
outcome,
attempted_username,
actor,
reason,
next_path,
client_ip,
user_agent,
request_id,
created_at
"""


async def record_admin_auth_event(
    session: AsyncSession,
    *,
    event_type: AdminAuthEventType,
    outcome: AdminAuthEventOutcome,
    attempted_username: str | None,
    actor: str | None,
    reason: str | None,
    next_path: str | None,
    client_ip: str | None,
    user_agent: str | None,
    request_id: str | None,
) -> AdminAuthEventRow:
    row = (
        await session.execute(
            text(
                f"""
INSERT INTO ops.admin_auth_events (
    event_type,
    outcome,
    attempted_username,
    actor,
    reason,
    next_path,
    client_ip,
    user_agent,
    request_id
) VALUES (
    :event_type,
    :outcome,
    :attempted_username,
    :actor,
    :reason,
    :next_path,
    :client_ip,
    :user_agent,
    :request_id
)
RETURNING {_AUTH_EVENT_COLUMNS}
"""
            ),
            {
                "event_type": event_type,
                "outcome": outcome,
                "attempted_username": attempted_username,
                "actor": actor,
                "reason": reason,
                "next_path": next_path,
                "client_ip": client_ip,
                "user_agent": user_agent,
                "request_id": request_id,
            },
        )
    ).mappings().one()
    return _map_auth_event(row)


async def list_admin_auth_events(
    session: AsyncSession,
    *,
    limit: int = 100,
    event_type: AdminAuthEventType | None = None,
    outcome: AdminAuthEventOutcome | None = None,
) -> tuple[AdminAuthEventRow, ...]:
    rows = (
        await session.execute(
            text(
                f"""
SELECT {_AUTH_EVENT_COLUMNS}
  FROM ops.admin_auth_events
 WHERE (CAST(:event_type AS text) IS NULL OR event_type = CAST(:event_type AS text))
   AND (CAST(:outcome AS text) IS NULL OR outcome = CAST(:outcome AS text))
 ORDER BY created_at DESC, auth_event_id DESC
 LIMIT :limit
"""
            ),
            {"limit": limit, "event_type": event_type, "outcome": outcome},
        )
    ).mappings().all()
    return tuple(_map_auth_event(row) for row in rows)


def _map_auth_event(row: Any) -> AdminAuthEventRow:
    data = dict(row)
    event_type = str(data["event_type"])
    outcome = str(data["outcome"])
    if event_type not in {"login", "logout"}:
        raise ValueError(f"invalid auth event type: {event_type}")
    if outcome not in {"succeeded", "failed", "denied"}:
        raise ValueError(f"invalid auth event outcome: {outcome}")
    return AdminAuthEventRow(
        auth_event_id=str(data["auth_event_id"]),
        event_type=cast(AdminAuthEventType, event_type),
        outcome=cast(AdminAuthEventOutcome, outcome),
        attempted_username=(
            str(data["attempted_username"])
            if data.get("attempted_username") is not None
            else None
        ),
        actor=str(data["actor"]) if data.get("actor") is not None else None,
        reason=str(data["reason"]) if data.get("reason") is not None else None,
        next_path=str(data["next_path"]) if data.get("next_path") is not None else None,
        client_ip=str(data["client_ip"]) if data.get("client_ip") is not None else None,
        user_agent=str(data["user_agent"]) if data.get("user_agent") is not None else None,
        request_id=str(data["request_id"]) if data.get("request_id") is not None else None,
        created_at=data["created_at"],
    )

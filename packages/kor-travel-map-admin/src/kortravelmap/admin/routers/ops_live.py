"""``WS /v1/ops/live`` — admin 운영 화면 실시간 signal 채널.

DB trigger/NOTIFY 없이 시작하는 1차 구현이다. WebSocket 연결 안에서 topic별
snapshot을 주기적으로 읽고, revision이 바뀐 topic만 client에 전송한다. Admin UI는
payload 자체를 source of truth로 쓰지 않고 TanStack Query invalidate signal로 쓴다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from kortravelmap.infra.ops_repo import get_ops_import_job
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.admin.db import get_session

__all__ = [
    "LiveTopicSnapshot",
    "router",
    "collect_live_topic_snapshots",
]

_LOG = logging.getLogger(__name__)

router = APIRouter(tags=["ops-live"])

_DEFAULT_TOPICS: Final[tuple[str, ...]] = (
    "import_jobs",
    "feature_update_requests",
    "offline_uploads",
    "dagster_runs",
)
_BASE_TOPICS: Final[frozenset[str]] = frozenset(_DEFAULT_TOPICS)
_TOPIC_PREFIXES: Final[tuple[str, ...]] = (
    "import_job:",
    "import_job_events:",
    "feature_update_request:",
    "offline_upload:",
    "dagster_run:",
)
_MAX_TOPICS: Final[int] = 32
_MIN_POLL_INTERVAL_MS: Final[int] = 1_000
_MAX_POLL_INTERVAL_MS: Final[int] = 30_000
_HEARTBEAT_INTERVAL_SECONDS: Final[float] = 30.0
_ALLOWED_TOPIC_CHARS: Final[frozenset[str]] = frozenset(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    ":_-."
)


@dataclass(frozen=True)
class LiveTopicSnapshot:
    """topic별 WebSocket 전송 단위."""

    topic: str
    revision: str
    data: dict[str, Any]


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _revision(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=_json_default)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _json_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = json.loads(value)
    if not value:
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _json_scalar_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = json.loads(value)
    if not value:
        return []
    return [str(item) for item in value if item is not None]


def _normalize_topic(raw: str) -> str:
    topic = raw.strip()
    if topic in _BASE_TOPICS:
        return topic
    if len(topic) > 256 or any(ch not in _ALLOWED_TOPIC_CHARS for ch in topic):
        raise ValueError(f"unsupported live topic: {raw!r}")
    if any(topic.startswith(prefix) and len(topic) > len(prefix) for prefix in _TOPIC_PREFIXES):
        return topic
    raise ValueError(f"unsupported live topic: {raw!r}")


def _topics_from_value(value: object) -> set[str]:
    if value is None:
        return set(_DEFAULT_TOPICS)
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, list | tuple | set):
        raw_items = [str(item) for item in value]
    else:
        raise ValueError("topics must be a comma-separated string or string list")
    topics = {_normalize_topic(item) for item in raw_items if str(item).strip()}
    if not topics:
        return set(_DEFAULT_TOPICS)
    if len(topics) > _MAX_TOPICS:
        raise ValueError(f"too many live topics: max {_MAX_TOPICS}")
    return topics


def _poll_interval_ms(raw: str | None) -> int:
    if raw is None:
        return 2_000
    try:
        value = int(raw)
    except ValueError:
        return 2_000
    return max(_MIN_POLL_INTERVAL_MS, min(value, _MAX_POLL_INTERVAL_MS))


def _message_base(message_type: str, *, sequence: int) -> dict[str, Any]:
    return {
        "type": message_type,
        "version": 1,
        "sequence": sequence,
        "sent_at": _utcnow().isoformat(),
    }


async def _rollback_safe(session: AsyncSession) -> None:
    rollback = getattr(session, "rollback", None)
    if callable(rollback):
        await rollback()


_IMPORT_JOBS_LIVE_SQL: Final[str] = """
WITH status_counts AS (
  SELECT COALESCE(jsonb_object_agg(status, count), '{}'::jsonb) AS counts_by_status
  FROM (
    SELECT status, COUNT(*)::int AS count
    FROM ops.import_jobs
    GROUP BY status
  ) s
),
active_jobs AS (
  SELECT COALESCE(jsonb_agg(to_jsonb(j) ORDER BY j.created_at DESC), '[]'::jsonb)
    AS active_jobs
  FROM (
    SELECT
      job_id::text AS job_id,
      kind,
      status,
      progress,
      current_stage,
      load_batch_id::text AS load_batch_id,
      parent_job_id::text AS parent_job_id,
      created_at,
      heartbeat_at,
      finished_at
    FROM ops.import_jobs
    WHERE status IN ('queued', 'running')
    ORDER BY created_at DESC, job_id DESC
    LIMIT 20
  ) j
),
event_stats AS (
  SELECT COUNT(*)::int AS events_total, MAX(occurred_at) AS latest_event_at
  FROM ops.import_job_events
)
SELECT
  status_counts.counts_by_status,
  active_jobs.active_jobs,
  event_stats.events_total,
  event_stats.latest_event_at,
  MAX(ops.import_jobs.created_at) AS latest_job_created_at,
  MAX(ops.import_jobs.heartbeat_at) AS latest_job_heartbeat_at,
  MAX(ops.import_jobs.finished_at) AS latest_job_finished_at
FROM ops.import_jobs
CROSS JOIN status_counts
CROSS JOIN active_jobs
CROSS JOIN event_stats
GROUP BY
  status_counts.counts_by_status,
  active_jobs.active_jobs,
  event_stats.events_total,
  event_stats.latest_event_at
"""

_IMPORT_JOB_EVENTS_LIVE_SQL: Final[str] = """
WITH recent AS (
  SELECT
    event_id::text AS event_id,
    level,
    code,
    message,
    stage,
    occurred_at
  FROM ops.import_job_events
  WHERE job_id = CAST(:job_id AS uuid)
  ORDER BY occurred_at DESC, event_id DESC
  LIMIT 5
)
SELECT
  COUNT(e.event_id)::int AS events_total,
  MAX(e.occurred_at) AS latest_event_at,
  COALESCE(jsonb_agg(to_jsonb(recent) ORDER BY recent.occurred_at DESC)
    FILTER (WHERE recent.event_id IS NOT NULL), '[]'::jsonb) AS recent_events
FROM ops.import_job_events e
LEFT JOIN recent ON recent.event_id = e.event_id::text
WHERE e.job_id = CAST(:job_id AS uuid)
"""

_FEATURE_UPDATE_REQUESTS_LIVE_SQL: Final[str] = """
WITH status_counts AS (
  SELECT COALESCE(jsonb_object_agg(status, count), '{}'::jsonb) AS counts_by_status
  FROM (
    SELECT status, COUNT(*)::int AS count
    FROM ops.feature_update_requests
    GROUP BY status
  ) s
),
active_requests AS (
  SELECT COALESCE(jsonb_agg(to_jsonb(r) ORDER BY r.priority DESC, r.created_at ASC),
    '[]'::jsonb) AS active_requests
  FROM (
    SELECT
      request_id::text AS request_id,
      status,
      scope_type,
      priority,
      job_id::text AS job_id,
      dagster_run_id,
      created_at,
      updated_at
    FROM ops.feature_update_requests
    WHERE status IN ('queued', 'running')
    ORDER BY priority DESC, created_at ASC
    LIMIT 20
  ) r
)
SELECT
  status_counts.counts_by_status,
  active_requests.active_requests,
  MAX(ops.feature_update_requests.updated_at) AS latest_updated_at
FROM ops.feature_update_requests
CROSS JOIN status_counts
CROSS JOIN active_requests
GROUP BY status_counts.counts_by_status, active_requests.active_requests
"""

_FEATURE_UPDATE_REQUEST_LIVE_SQL: Final[str] = """
SELECT
  request_id::text AS request_id,
  status,
  scope_type,
  priority,
  job_id::text AS job_id,
  dagster_run_id,
  error_message,
  created_at,
  started_at,
  finished_at,
  updated_at
FROM ops.feature_update_requests
WHERE request_id = CAST(:request_id AS uuid)
"""

_OFFLINE_UPLOADS_LIVE_SQL: Final[str] = """
WITH status_counts AS (
  SELECT COALESCE(jsonb_object_agg(status, count), '{}'::jsonb) AS counts_by_status
  FROM (
    SELECT status, COUNT(*)::int AS count
    FROM ops.offline_uploads
    GROUP BY status
  ) s
),
active_uploads AS (
  SELECT COALESCE(jsonb_agg(to_jsonb(u) ORDER BY u.updated_at DESC), '[]'::jsonb)
    AS active_uploads
  FROM (
    SELECT
      upload_id::text AS upload_id,
      provider,
      dataset_key,
      status,
      validation_job_id::text AS validation_job_id,
      load_job_id::text AS load_job_id,
      created_at,
      updated_at
    FROM ops.offline_uploads
    WHERE status IN ('validating', 'loading')
    ORDER BY updated_at DESC, upload_id DESC
    LIMIT 20
  ) u
)
SELECT
  status_counts.counts_by_status,
  active_uploads.active_uploads,
  MAX(ops.offline_uploads.updated_at) AS latest_updated_at
FROM ops.offline_uploads
CROSS JOIN status_counts
CROSS JOIN active_uploads
GROUP BY status_counts.counts_by_status, active_uploads.active_uploads
"""

_OFFLINE_UPLOAD_LIVE_SQL: Final[str] = """
SELECT
  upload_id::text AS upload_id,
  provider,
  dataset_key,
  sync_scope,
  status,
  validation_job_id::text AS validation_job_id,
  load_job_id::text AS load_job_id,
  created_at,
  updated_at
FROM ops.offline_uploads
WHERE upload_id = CAST(:upload_id AS uuid)
"""

_DAGSTER_RUNS_LIVE_SQL: Final[str] = """
SELECT
  COALESCE(jsonb_agg(DISTINCT COALESCE(payload->>'dagster_run_id', payload->>'run_id'))
    FILTER (WHERE COALESCE(payload->>'dagster_run_id', payload->>'run_id') IS NOT NULL),
    '[]'::jsonb) AS run_ids,
  COUNT(*) FILTER (
    WHERE COALESCE(payload->>'dagster_run_id', payload->>'run_id') IS NOT NULL
  )::int AS linked_job_count,
  MAX(heartbeat_at) AS latest_job_heartbeat_at,
  MAX(finished_at) AS latest_job_finished_at
FROM ops.import_jobs
WHERE payload ? 'dagster_run_id' OR payload ? 'run_id'
"""

_DAGSTER_RUN_LIVE_SQL: Final[str] = """
SELECT COALESCE(jsonb_agg(to_jsonb(j) ORDER BY j.created_at DESC), '[]'::jsonb)
  AS linked_jobs
FROM (
  SELECT
    job_id::text AS job_id,
    kind,
    status,
    progress,
    current_stage,
    created_at,
    heartbeat_at,
    finished_at
  FROM ops.import_jobs
  WHERE payload->>'dagster_run_id' = :run_id OR payload->>'run_id' = :run_id
  ORDER BY created_at DESC, job_id DESC
  LIMIT 20
) j
"""


async def _row_mapping(
    session: AsyncSession,
    sql: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = await session.execute(text(sql), params or {})
    row = result.mappings().first()
    return dict(row) if row is not None else {}


async def _import_jobs_snapshot(session: AsyncSession) -> dict[str, Any]:
    row = await _row_mapping(session, _IMPORT_JOBS_LIVE_SQL)
    return {
        "counts_by_status": _json_dict(row.get("counts_by_status")),
        "active_jobs": _json_list(row.get("active_jobs")),
        "events_total": int(row.get("events_total") or 0),
        "latest_event_at": _iso(row.get("latest_event_at")),
        "latest_job_created_at": _iso(row.get("latest_job_created_at")),
        "latest_job_heartbeat_at": _iso(row.get("latest_job_heartbeat_at")),
        "latest_job_finished_at": _iso(row.get("latest_job_finished_at")),
    }


async def _import_job_snapshot(session: AsyncSession, job_id: str) -> dict[str, Any]:
    job = await get_ops_import_job(session, job_id)
    if job is None:
        return {"job_id": job_id, "exists": False}
    return {
        "job_id": job.job_id,
        "exists": True,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "current_stage": job.current_stage,
        "load_batch_id": job.load_batch_id,
        "parent_job_id": job.parent_job_id,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "heartbeat_at": _iso(job.heartbeat_at),
        "finished_at": _iso(job.finished_at),
        "error_message": job.error_message,
    }


async def _import_job_events_snapshot(session: AsyncSession, job_id: str) -> dict[str, Any]:
    row = await _row_mapping(session, _IMPORT_JOB_EVENTS_LIVE_SQL, {"job_id": job_id})
    return {
        "job_id": job_id,
        "events_total": int(row.get("events_total") or 0),
        "latest_event_at": _iso(row.get("latest_event_at")),
        "recent_events": _json_list(row.get("recent_events")),
    }


async def _feature_update_requests_snapshot(session: AsyncSession) -> dict[str, Any]:
    row = await _row_mapping(session, _FEATURE_UPDATE_REQUESTS_LIVE_SQL)
    return {
        "counts_by_status": _json_dict(row.get("counts_by_status")),
        "active_requests": _json_list(row.get("active_requests")),
        "latest_updated_at": _iso(row.get("latest_updated_at")),
    }


async def _feature_update_request_snapshot(
    session: AsyncSession,
    request_id: str,
) -> dict[str, Any]:
    row = await _row_mapping(
        session,
        _FEATURE_UPDATE_REQUEST_LIVE_SQL,
        {"request_id": request_id},
    )
    if not row:
        return {"request_id": request_id, "exists": False}
    return {
        "request_id": row.get("request_id"),
        "exists": True,
        "status": row.get("status"),
        "scope_type": row.get("scope_type"),
        "priority": row.get("priority"),
        "job_id": row.get("job_id"),
        "dagster_run_id": row.get("dagster_run_id"),
        "error_message": row.get("error_message"),
        "created_at": _iso(row.get("created_at")),
        "started_at": _iso(row.get("started_at")),
        "finished_at": _iso(row.get("finished_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


async def _offline_uploads_snapshot(session: AsyncSession) -> dict[str, Any]:
    row = await _row_mapping(session, _OFFLINE_UPLOADS_LIVE_SQL)
    return {
        "counts_by_status": _json_dict(row.get("counts_by_status")),
        "active_uploads": _json_list(row.get("active_uploads")),
        "latest_updated_at": _iso(row.get("latest_updated_at")),
    }


async def _offline_upload_snapshot(session: AsyncSession, upload_id: str) -> dict[str, Any]:
    row = await _row_mapping(session, _OFFLINE_UPLOAD_LIVE_SQL, {"upload_id": upload_id})
    if not row:
        return {"upload_id": upload_id, "exists": False}
    return {
        "upload_id": row.get("upload_id"),
        "exists": True,
        "provider": row.get("provider"),
        "dataset_key": row.get("dataset_key"),
        "sync_scope": row.get("sync_scope"),
        "status": row.get("status"),
        "validation_job_id": row.get("validation_job_id"),
        "load_job_id": row.get("load_job_id"),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


async def _dagster_runs_snapshot(session: AsyncSession) -> dict[str, Any]:
    row = await _row_mapping(session, _DAGSTER_RUNS_LIVE_SQL)
    return {
        "run_ids": _json_scalar_list(row.get("run_ids")),
        "linked_job_count": int(row.get("linked_job_count") or 0),
        "latest_job_heartbeat_at": _iso(row.get("latest_job_heartbeat_at")),
        "latest_job_finished_at": _iso(row.get("latest_job_finished_at")),
    }


async def _dagster_run_snapshot(session: AsyncSession, run_id: str) -> dict[str, Any]:
    row = await _row_mapping(session, _DAGSTER_RUN_LIVE_SQL, {"run_id": run_id})
    return {"run_id": run_id, "linked_jobs": _json_list(row.get("linked_jobs"))}


async def collect_live_topic_snapshots(
    session: AsyncSession,
    topics: set[str],
) -> dict[str, LiveTopicSnapshot]:
    """요청 topic들의 현재 snapshot을 조회한다."""

    snapshots: dict[str, LiveTopicSnapshot] = {}
    for topic in sorted(topics):
        if topic == "import_jobs":
            data = await _import_jobs_snapshot(session)
        elif topic.startswith("import_job_events:"):
            data = await _import_job_events_snapshot(session, topic.split(":", 1)[1])
        elif topic.startswith("import_job:"):
            data = await _import_job_snapshot(session, topic.split(":", 1)[1])
        elif topic == "feature_update_requests":
            data = await _feature_update_requests_snapshot(session)
        elif topic.startswith("feature_update_request:"):
            data = await _feature_update_request_snapshot(session, topic.split(":", 1)[1])
        elif topic == "offline_uploads":
            data = await _offline_uploads_snapshot(session)
        elif topic.startswith("offline_upload:"):
            data = await _offline_upload_snapshot(session, topic.split(":", 1)[1])
        elif topic == "dagster_runs":
            data = await _dagster_runs_snapshot(session)
        elif topic.startswith("dagster_run:"):
            data = await _dagster_run_snapshot(session, topic.split(":", 1)[1])
        else:  # pragma: no cover — _normalize_topic에서 걸러진다.
            continue
        snapshots[topic] = LiveTopicSnapshot(
            topic=topic,
            revision=_revision(data),
            data=data,
        )
    await _rollback_safe(session)
    return snapshots


async def _send_error(websocket: WebSocket, *, sequence: int, message: str) -> int:
    await websocket.send_json(
        {
            **_message_base("error", sequence=sequence),
            "message": message,
        }
    )
    return sequence + 1


async def _send_snapshots(
    websocket: WebSocket,
    session: AsyncSession,
    topics: set[str],
    revisions: dict[str, str],
    *,
    sequence: int,
    force: bool,
) -> int:
    try:
        snapshots = await collect_live_topic_snapshots(session, topics)
    except Exception:  # noqa: BLE001 — live signal 실패는 연결을 끊지 않고 error frame.
        _LOG.exception("ops live snapshot 조회 실패")
        return await _send_error(
            websocket,
            sequence=sequence,
            message="ops live snapshot 조회에 실패했습니다.",
        )
    for topic, snapshot in snapshots.items():
        if not force and revisions.get(topic) == snapshot.revision:
            continue
        revisions[topic] = snapshot.revision
        await websocket.send_json(
            {
                **_message_base(
                    "snapshot" if force else "update",
                    sequence=sequence,
                ),
                "topic": topic,
                "revision": snapshot.revision,
                "data": snapshot.data,
            }
        )
        sequence += 1
    for removed in set(revisions) - topics:
        revisions.pop(removed, None)
    return sequence


async def _receive_command(websocket: WebSocket, timeout_seconds: float) -> object | None:
    try:
        return await asyncio.wait_for(websocket.receive_json(), timeout=timeout_seconds)
    except TimeoutError:
        return None


def _apply_command(topics: set[str], command: object) -> tuple[set[str], str]:
    if not isinstance(command, dict):
        raise ValueError("command must be an object")
    command_type = str(command.get("type") or "")
    command_topics = _topics_from_value(command.get("topics"))
    if command_type == "subscribe":
        updated = set(topics)
        updated.update(command_topics)
    elif command_type == "unsubscribe":
        updated = set(topics)
        updated.difference_update(command_topics)
    elif command_type == "replace":
        updated = command_topics
    elif command_type == "ping":
        return topics, "pong"
    else:
        raise ValueError("unsupported live command type")
    if len(updated) > _MAX_TOPICS:
        raise ValueError(f"too many live topics: max {_MAX_TOPICS}")
    return updated, "subscribed"


@router.websocket("/ops/live")
async def ops_live(
    websocket: WebSocket,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """admin UI 실시간 signal WebSocket."""

    await websocket.accept()
    sequence = 1
    try:
        topics = _topics_from_value(websocket.query_params.get("topics"))
    except ValueError as exc:
        await websocket.send_json(
            {
                **_message_base("error", sequence=sequence),
                "message": str(exc),
            }
        )
        await websocket.close(code=1008)
        return
    poll_interval_ms = _poll_interval_ms(websocket.query_params.get("poll_interval_ms"))
    poll_interval_seconds = poll_interval_ms / 1_000
    await websocket.send_json(
        {
            **_message_base("hello", sequence=sequence),
            "topics": sorted(topics),
            "poll_interval_ms": poll_interval_ms,
        }
    )
    sequence += 1
    revisions: dict[str, str] = {}
    sequence = await _send_snapshots(
        websocket,
        session,
        topics,
        revisions,
        sequence=sequence,
        force=True,
    )
    last_heartbeat = _utcnow()
    try:
        while True:
            try:
                command = await _receive_command(websocket, poll_interval_seconds)
            except WebSocketDisconnect:
                return
            if command is not None:
                try:
                    topics, ack_type = _apply_command(topics, command)
                except ValueError as exc:
                    sequence = await _send_error(
                        websocket,
                        sequence=sequence,
                        message=str(exc),
                    )
                    continue
                await websocket.send_json(
                    {
                        **_message_base(ack_type, sequence=sequence),
                        "topics": sorted(topics),
                    }
                )
                sequence += 1
                sequence = await _send_snapshots(
                    websocket,
                    session,
                    topics,
                    revisions,
                    sequence=sequence,
                    force=True,
                )
                last_heartbeat = _utcnow()
                continue
            sequence = await _send_snapshots(
                websocket,
                session,
                topics,
                revisions,
                sequence=sequence,
                force=False,
            )
            now = _utcnow()
            if (now - last_heartbeat).total_seconds() >= _HEARTBEAT_INTERVAL_SECONDS:
                await websocket.send_json(
                    {
                        **_message_base("heartbeat", sequence=sequence),
                        "topics": sorted(topics),
                    }
                )
                sequence += 1
                last_heartbeat = now
    except WebSocketDisconnect:
        return

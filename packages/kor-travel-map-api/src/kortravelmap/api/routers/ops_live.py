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
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from kortravelmap.infra.ops_repo import get_ops_import_job
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.db import get_session
from kortravelmap.api.ops_live_auth import (
    OPS_LIVE_AUTH_CLOSE_CODE,
    OPS_LIVE_EXPIRED_CLOSE_CODE,
    OpsLiveTicketContext,
    authenticate_ops_live_websocket,
    claim_ops_live_ticket,
    select_ops_live_subprotocol,
)

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
_BASE_TOPICS: Final[frozenset[str]] = frozenset(
    (
        *_DEFAULT_TOPICS,
        "provider_sync",
        "dataset_projection",
        "dagster_schedules",
    )
)
_UUID_TOPIC_PREFIXES: Final[tuple[str, ...]] = (
    "import_job:",
    "import_job_events:",
    "feature_update_request:",
    "offline_upload:",
)
_DAGSTER_RUN_TOPIC_PREFIX: Final[str] = "dagster_run:"
_MAX_TOPICS: Final[int] = 32
_MAX_DAGSTER_RUN_ID_LENGTH: Final[int] = 255
_CLOSE_TIMEOUT_SECONDS: Final[float] = 1.0
_ROLLBACK_TIMEOUT_SECONDS: Final[float] = 1.0
_RETRY_LATER_CLOSE_CODE: Final[int] = 1013
_MIN_POLL_INTERVAL_MS: Final[int] = 1_000
_MAX_POLL_INTERVAL_MS: Final[int] = 30_000
_HEARTBEAT_INTERVAL_SECONDS: Final[float] = 30.0


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
    for prefix in _UUID_TOPIC_PREFIXES:
        if topic.startswith(prefix) and len(topic) > len(prefix):
            identifier = topic.removeprefix(prefix)
            try:
                parsed_identifier = UUID(identifier)
            except ValueError as exc:
                raise ValueError(f"live topic id must be a UUID: {raw!r}") from exc
            if identifier != str(parsed_identifier):
                raise ValueError(f"live topic id must be a canonical UUID: {raw!r}")
            return topic
    if topic.startswith(_DAGSTER_RUN_TOPIC_PREFIX):
        identifier = topic.removeprefix(_DAGSTER_RUN_TOPIC_PREFIX).strip()
        if (
            not identifier
            or len(identifier) > _MAX_DAGSTER_RUN_ID_LENGTH
            or any(ord(ch) < 0x20 for ch in identifier)
        ):
            raise ValueError(f"invalid Dagster run id live topic: {raw!r}")
        return f"{_DAGSTER_RUN_TOPIC_PREFIX}{identifier}"
    raise ValueError(f"unsupported live topic: {raw!r}")


def _topics_from_value(value: object) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list):
        raise ValueError("topics must be a JSON string array")
    raw_items = [str(item) for item in value]
    topics = {_normalize_topic(item) for item in raw_items if str(item).strip()}
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


async def _rollback_bounded(session: AsyncSession) -> None:
    try:
        await asyncio.wait_for(
            _rollback_safe(session),
            timeout=_ROLLBACK_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        _LOG.warning("ops live session rollback timeout")
    except Exception:  # noqa: BLE001 — transaction 정리 실패를 격리한다.
        _LOG.exception("ops live session rollback 실패")


_IMPORT_JOBS_LIVE_SQL: Final[str] = """
WITH status_counts AS (
  SELECT COALESCE(jsonb_object_agg(status, count), '{}'::jsonb) AS counts_by_status
  FROM (
    SELECT status, COUNT(*)::int AS count
    FROM ops.import_jobs
    WHERE quarantined_at IS NULL
    GROUP BY status
  ) s
),
active_jobs AS (
  SELECT COALESCE(
    jsonb_agg(to_jsonb(j) ORDER BY j.created_at DESC, j.job_id DESC),
    '[]'::jsonb
  ) AS active_jobs
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
      AND quarantined_at IS NULL
    ORDER BY created_at DESC, job_id DESC
    LIMIT 20
  ) j
),
event_clock AS (
  SELECT COALESCE(MAX(revision), 0)::bigint AS event_clock_revision
  FROM ops.import_job_event_clock
  WHERE clock_id
),
event_stats AS (
  SELECT
    MAX(latest.event_id::text) AS latest_event_id,
    MAX(latest.occurred_at) AS latest_event_at
  FROM (
    SELECT event_id, occurred_at
    FROM ops.import_job_events AS event
    WHERE event.quarantined_at IS NULL
    ORDER BY occurred_at DESC, event_id DESC
    LIMIT 1
  ) AS latest
),
job_stats AS (
  SELECT
    MAX(created_at) AS latest_job_created_at,
    MAX(heartbeat_at) AS latest_job_heartbeat_at,
    MAX(finished_at) AS latest_job_finished_at
  FROM ops.import_jobs
  WHERE quarantined_at IS NULL
)
SELECT
  status_counts.counts_by_status,
  active_jobs.active_jobs,
  event_clock.event_clock_revision,
  event_stats.latest_event_id,
  event_stats.latest_event_at,
  job_stats.latest_job_created_at,
  job_stats.latest_job_heartbeat_at,
  job_stats.latest_job_finished_at
FROM status_counts
CROSS JOIN active_jobs
CROSS JOIN event_clock
CROSS JOIN event_stats
CROSS JOIN job_stats
"""

_IMPORT_JOB_EVENTS_LIVE_SQL: Final[str] = """
WITH event_clock AS (
  SELECT COALESCE(MAX(revision), 0)::bigint AS event_clock_revision
  FROM ops.import_job_event_clock
  WHERE clock_id
),
recent AS (
  SELECT
    event_id::text AS event_id,
    level,
    code,
    message,
    stage,
    occurred_at
  FROM ops.import_job_events AS event
  WHERE event.job_id = CAST(:job_id AS uuid)
    AND event.quarantined_at IS NULL
  ORDER BY event.occurred_at DESC, event.event_id DESC
  LIMIT 5
)
SELECT
  event_clock.event_clock_revision,
  MAX(recent.occurred_at) AS latest_event_at,
  COALESCE(jsonb_agg(
    to_jsonb(recent) ORDER BY recent.occurred_at DESC, recent.event_id DESC
  )
    FILTER (WHERE recent.event_id IS NOT NULL), '[]'::jsonb) AS recent_events
FROM event_clock
LEFT JOIN recent ON TRUE
GROUP BY event_clock.event_clock_revision
"""

_FEATURE_UPDATE_REQUESTS_LIVE_SQL: Final[str] = """
WITH status_counts AS (
  SELECT COALESCE(jsonb_object_agg(status, count), '{}'::jsonb) AS counts_by_status
  FROM (
    SELECT job.status, COUNT(*)::int AS count
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job
      ON job.job_id = request.job_id
     AND job.quarantined_at IS NULL
    GROUP BY job.status
  ) s
),
active_requests AS (
  SELECT COALESCE(
    jsonb_agg(
      to_jsonb(r)
      ORDER BY r.priority DESC, r.created_at ASC, r.request_id ASC
    ),
    '[]'::jsonb
  ) AS active_requests
  FROM (
    SELECT
      request.request_id::text AS request_id,
      job.status,
      request.scope_type,
      request.priority,
      request.job_id::text AS job_id,
      job.dagster_run_id,
      request.created_at,
      request.generation,
      request.matched_scope,
      job.dispatch_requested_at,
      COALESCE(
        job.heartbeat_at,
        job.started_at,
        job.dispatch_requested_at,
        job.created_at
      ) AS updated_at
    FROM ops.feature_update_requests AS request
    JOIN ops.import_jobs AS job
      ON job.job_id = request.job_id
     AND job.quarantined_at IS NULL
    WHERE job.status IN ('queued', 'running')
    ORDER BY
      request.priority DESC,
      request.created_at ASC,
      request.request_id ASC
    LIMIT 20
  ) r
)
SELECT
  status_counts.counts_by_status,
  active_requests.active_requests,
  MAX(COALESCE(
    job.finished_at,
    job.heartbeat_at,
    job.started_at,
    job.dispatch_requested_at,
    job.created_at
  ))
    AS latest_updated_at
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job
  ON job.job_id = request.job_id
 AND job.quarantined_at IS NULL
CROSS JOIN status_counts
CROSS JOIN active_requests
GROUP BY status_counts.counts_by_status, active_requests.active_requests
"""

_FEATURE_UPDATE_REQUEST_LIVE_SQL: Final[str] = """
SELECT
  request.request_id::text AS request_id,
  job.status,
  request.scope_type,
  request.priority,
  request.job_id::text AS job_id,
  job.dagster_run_id,
  job.error_message,
  request.created_at,
  job.started_at,
  job.finished_at,
  request.generation,
  request.matched_scope,
  job.dispatch_requested_at,
  COALESCE(
    job.finished_at,
    job.heartbeat_at,
    job.started_at,
    job.dispatch_requested_at,
    job.created_at
  ) AS updated_at
FROM ops.feature_update_requests AS request
JOIN ops.import_jobs AS job
  ON job.job_id = request.job_id
 AND job.quarantined_at IS NULL
WHERE request.request_id = CAST(:request_id AS uuid)
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
  SELECT COALESCE(
    jsonb_agg(to_jsonb(u) ORDER BY u.updated_at DESC, u.upload_id DESC),
    '[]'::jsonb
  ) AS active_uploads
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

# ADR-064/T-ADM-C3 — 실컬럼 ``dagster_run_id`` 우선 + payload 폴백 COALESCE.
# 0048 migration이 기존 payload(``dagster_run_id``/레거시 ``run_id``)를 백필하지만,
# migration runner는 api-entrypoint뿐이라 배포 창(mixed-version)에서 구 dagster
# 이미지가 백필 **이후** payload-only row를 더 쓸 수 있다 — 그 row도 놓치지 않도록
# 읽기 경로는 정확성 우선으로 폴백을 유지한다(부분 인덱스는 실컬럼 branch fast
# path용 존치). 폴백 제거(순수 실컬럼 전환)는 구 이미지 소진 + 0048 docstring의
# 백필 SQL 재실행 후 T-ADM-C6b 시점에 재검토한다.
_DAGSTER_RUNS_LIVE_SQL: Final[str] = """
SELECT
  COALESCE(
    jsonb_agg(DISTINCT j.run_id ORDER BY j.run_id)
      FILTER (WHERE j.run_id IS NOT NULL),
    '[]'::jsonb
  ) AS run_ids,
  COUNT(*) FILTER (WHERE j.run_id IS NOT NULL)::int AS linked_job_count,
  MAX(j.heartbeat_at) FILTER (WHERE j.run_id IS NOT NULL)
    AS latest_job_heartbeat_at,
  MAX(j.finished_at) FILTER (WHERE j.run_id IS NOT NULL)
    AS latest_job_finished_at
FROM (
  SELECT
    COALESCE(
      dagster_run_id,
      NULLIF(COALESCE(payload->>'dagster_run_id', payload->>'run_id'), '')
    ) AS run_id,
    heartbeat_at,
    finished_at
  FROM ops.import_jobs
  WHERE quarantined_at IS NULL
    AND (
      dagster_run_id IS NOT NULL
      OR payload ? 'dagster_run_id'
      OR payload ? 'run_id'
    )
) j
"""

_DAGSTER_RUN_LIVE_SQL: Final[str] = """
SELECT COALESCE(
  jsonb_agg(to_jsonb(j) ORDER BY j.created_at DESC, j.job_id DESC),
  '[]'::jsonb
) AS linked_jobs
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
  WHERE quarantined_at IS NULL
    AND COALESCE(
      dagster_run_id,
      NULLIF(COALESCE(payload->>'dagster_run_id', payload->>'run_id'), '')
    ) = :run_id
  ORDER BY created_at DESC, job_id DESC
  LIMIT 20
) j
"""

_PROVIDER_SYNC_LIVE_SQL: Final[str] = """
SELECT
  (SELECT COUNT(*) FROM provider_sync.provider_sync_state) AS state_count,
  (SELECT MAX(updated_at) FROM provider_sync.provider_sync_state) AS state_updated_at,
  (SELECT COUNT(*) FROM ops.provider_refresh_policies) AS policy_count,
  (SELECT MAX(updated_at) FROM ops.provider_refresh_policies) AS policy_updated_at,
  (
    SELECT revision
    FROM ops.ops_live_topic_revisions
    WHERE topic = 'provider_sync'
  ) AS live_revision
"""

_DATASET_PROJECTION_LIVE_SQL: Final[str] = """
SELECT revision AS live_revision
FROM ops.ops_live_topic_revisions
WHERE topic = 'dataset_projection'
"""

_DAGSTER_SCHEDULES_LIVE_SQL: Final[str] = """
SELECT
  (SELECT COUNT(*) FROM ops.dagster_schedule_overrides) AS override_count,
  (SELECT MAX(updated_at) FROM ops.dagster_schedule_overrides) AS override_updated_at,
  (
    SELECT COALESCE(MAX(event_id), 0)::bigint
    FROM ops.dagster_schedule_audit_events
  ) AS audit_revision,
  (
    SELECT COALESCE(MAX(resolution_id), 0)::bigint
    FROM ops.dagster_schedule_claim_resolutions
  ) AS claim_resolution_revision,
  (
    SELECT revision
    FROM ops.ops_live_topic_revisions
    WHERE topic = 'dagster_schedules'
  ) AS live_revision
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
        "event_clock_revision": int(row.get("event_clock_revision") or 0),
        "latest_event_id": row.get("latest_event_id"),
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
        "event_clock_revision": int(row.get("event_clock_revision") or 0),
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
        # append-only request의 REST mutable 필드는 matched_scope/generation,
        # canonical job의 mutable REST 필드는 lifecycle + dispatch intent다.
        "generation": int(row.get("generation") or 0),
        "matched_scope": _json_dict(row.get("matched_scope")),
        "dispatch_requested_at": _iso(row.get("dispatch_requested_at")),
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


async def _provider_sync_snapshot(session: AsyncSession) -> dict[str, Any]:
    row = await _row_mapping(session, _PROVIDER_SYNC_LIVE_SQL)
    return {
        "state_count": int(row.get("state_count") or 0),
        "state_updated_at": _iso(row.get("state_updated_at")),
        "policy_count": int(row.get("policy_count") or 0),
        "policy_updated_at": _iso(row.get("policy_updated_at")),
        "live_revision": int(row.get("live_revision") or 0),
    }


async def _dataset_projection_snapshot(session: AsyncSession) -> dict[str, Any]:
    row = await _row_mapping(session, _DATASET_PROJECTION_LIVE_SQL)
    return {"live_revision": int(row.get("live_revision") or 0)}


async def _dagster_schedules_snapshot(session: AsyncSession) -> dict[str, Any]:
    row = await _row_mapping(session, _DAGSTER_SCHEDULES_LIVE_SQL)
    return {
        "audit_revision": int(row.get("audit_revision") or 0),
        "claim_resolution_revision": int(
            row.get("claim_resolution_revision") or 0
        ),
        "override_count": int(row.get("override_count") or 0),
        "override_updated_at": _iso(row.get("override_updated_at")),
        "live_revision": int(row.get("live_revision") or 0),
    }


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
        elif topic == "provider_sync":
            data = await _provider_sync_snapshot(session)
        elif topic == "dataset_projection":
            data = await _dataset_projection_snapshot(session)
        elif topic == "dagster_schedules":
            data = await _dagster_schedules_snapshot(session)
        else:  # pragma: no cover — _normalize_topic에서 걸러진다.
            continue
        snapshots[topic] = LiveTopicSnapshot(
            topic=topic,
            revision=_revision(data),
            data=data,
        )
    await _rollback_safe(session)
    return snapshots


def _remaining_lease_seconds(expires_at: datetime) -> float:
    return (expires_at - _utcnow()).total_seconds()


async def _accept_best_effort(
    websocket: WebSocket,
    *,
    subprotocol: str | None,
) -> bool:
    try:
        await asyncio.wait_for(
            websocket.accept(subprotocol=subprotocol),
            timeout=_CLOSE_TIMEOUT_SECONDS,
        )
        return True
    except TimeoutError:
        _LOG.warning("ops live accept timeout")
    except Exception:  # noqa: BLE001 — close/rollback으로 이어지는 격리 경계다.
        _LOG.exception("ops live accept 실패")
    return False


async def _close_best_effort(
    websocket: WebSocket,
    *,
    code: int,
    reason: str,
) -> None:
    try:
        await asyncio.wait_for(
            websocket.close(code=code, reason=reason),
            timeout=_CLOSE_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        _LOG.warning("ops live close timeout: code=%s", code)
    except Exception:  # noqa: BLE001 — connection 정리는 best effort 경계다.
        _LOG.exception("ops live close 전달 실패: code=%s", code)


async def _accept_and_close_best_effort(
    websocket: WebSocket,
    *,
    code: int,
    reason: str,
    subprotocol: str | None,
) -> None:
    async def _accept_yield_then_close() -> None:
        accepted = await _accept_best_effort(websocket, subprotocol=subprotocol)
        if not accepted:
            return
        # ASGI에는 transport drain acknowledgement가 없다. close를 다음 loop turn에
        # 예약해 Uvicorn sansio의 101/close coalescing을 best effort로 줄이고, exact
        # proxy+Chromium live gate에서 최종 전달 계약을 검증한다.
        await asyncio.sleep(0)
        await _close_best_effort(websocket, code=code, reason=reason)

    operation = asyncio.create_task(_accept_yield_then_close())
    cancellation: asyncio.CancelledError | None = None
    while True:
        try:
            await asyncio.shield(operation)
            break
        except asyncio.CancelledError as exc:
            if operation.done():
                raise
            # accept의 내부 wait_for handoff와 close 대기를 모두 outer cancellation에서
            # 보호한다. 반복 취소도 operation의 bounded timeout을 취소하지 않는다.
            cancellation = exc
    if cancellation is not None:
        raise cancellation


async def _rollback_and_accept_close(
    websocket: WebSocket,
    session: AsyncSession,
    *,
    code: int,
    reason: str,
    subprotocol: str | None,
) -> None:
    await _rollback_bounded(session)
    await _accept_and_close_best_effort(
        websocket,
        code=code,
        reason=reason,
        subprotocol=subprotocol,
    )


async def _rollback_and_close(
    websocket: WebSocket,
    session: AsyncSession,
    *,
    code: int,
    reason: str,
) -> None:
    await _rollback_bounded(session)
    await _close_best_effort(websocket, code=code, reason=reason)


async def _close_expired_best_effort(websocket: WebSocket) -> None:
    await _close_best_effort(
        websocket,
        code=OPS_LIVE_EXPIRED_CLOSE_CODE,
        reason="ops live ticket expired",
    )


async def _send_json_before_expiry(
    websocket: WebSocket,
    session: AsyncSession,
    payload: dict[str, Any],
    *,
    expires_at: datetime,
) -> bool:
    remaining = _remaining_lease_seconds(expires_at)
    if remaining <= 0:
        await _close_expired_best_effort(websocket)
        return False
    send_timeout = asyncio.timeout(remaining)
    try:
        async with send_timeout:
            await websocket.send_json(payload)
    except TimeoutError:
        if send_timeout.expired() or _remaining_lease_seconds(expires_at) <= 0:
            await _close_expired_best_effort(websocket)
            return False
        _LOG.exception("ops live frame 전송 timeout")
        await _rollback_and_close(
            websocket,
            session,
            code=_RETRY_LATER_CLOSE_CODE,
            reason="ops live transport unavailable",
        )
        return False
    except WebSocketDisconnect:
        return False
    except Exception:  # noqa: BLE001 — transport 구현별 OSError/RuntimeError를 격리한다.
        _LOG.exception("ops live frame 전송 실패")
        await _rollback_and_close(
            websocket,
            session,
            code=_RETRY_LATER_CLOSE_CODE,
            reason="ops live transport unavailable",
        )
        return False
    return True


async def _send_error(
    websocket: WebSocket,
    session: AsyncSession,
    *,
    sequence: int,
    message: str,
    expires_at: datetime,
) -> int | None:
    sent = await _send_json_before_expiry(
        websocket,
        session,
        {
            **_message_base("error", sequence=sequence),
            "message": message,
        },
        expires_at=expires_at,
    )
    return sequence + 1 if sent else None


async def _send_snapshots(
    websocket: WebSocket,
    session: AsyncSession,
    topics: set[str],
    revisions: dict[str, str],
    *,
    sequence: int,
    force: bool,
    expires_at: datetime,
) -> int | None:
    remaining = _remaining_lease_seconds(expires_at)
    if remaining <= 0:
        try:
            await _close_expired_best_effort(websocket)
        finally:
            await _rollback_bounded(session)
        return None
    lease_timeout = asyncio.timeout(remaining)
    try:
        async with lease_timeout:
            snapshots = await collect_live_topic_snapshots(session, topics)
    except TimeoutError:
        if lease_timeout.expired() or _remaining_lease_seconds(expires_at) <= 0:
            try:
                await _close_expired_best_effort(websocket)
            finally:
                await _rollback_bounded(session)
            return None
        _LOG.exception("ops live snapshot 조회 timeout")
        await _rollback_and_close(
            websocket,
            session,
            code=_RETRY_LATER_CLOSE_CODE,
            reason="ops live snapshot unavailable",
        )
        return None
    except Exception:  # noqa: BLE001 — DB/session 오류는 data 없이 격리한다.
        _LOG.exception("ops live snapshot 조회 실패")
        await _rollback_and_close(
            websocket,
            session,
            code=_RETRY_LATER_CLOSE_CODE,
            reason="ops live snapshot unavailable",
        )
        return None
    for topic, snapshot in snapshots.items():
        if not force and revisions.get(topic) == snapshot.revision:
            continue
        revisions[topic] = snapshot.revision
        sent = await _send_json_before_expiry(
            websocket,
            session,
            {
                **_message_base(
                    "snapshot" if force else "update",
                    sequence=sequence,
                ),
                "topic": topic,
                "revision": snapshot.revision,
                "data": snapshot.data,
            },
            expires_at=expires_at,
        )
        if not sent:
            return None
        sequence += 1
    for removed in set(revisions) - topics:
        revisions.pop(removed, None)
    return sequence


async def _receive_command(websocket: WebSocket, timeout_seconds: float) -> object | None:
    poll_timeout = asyncio.timeout(timeout_seconds)
    try:
        async with poll_timeout:
            command: object = await websocket.receive_json()
            return command
    except TimeoutError:
        if poll_timeout.expired():
            return None
        raise


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
    else:
        raise ValueError("unsupported live command type")
    if len(updated) > _MAX_TOPICS:
        raise ValueError(f"too many live topics: max {_MAX_TOPICS}")
    return updated, "subscribed"


@router.websocket("/ops/live")
async def ops_live(
    websocket: WebSocket,
    auth_context: Annotated[
        OpsLiveTicketContext | None,
        Depends(authenticate_ops_live_websocket),
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """admin UI 실시간 signal WebSocket."""

    if auth_context is None:
        # HTTP upgrade 거절은 browser WebSocket API에서 1006으로 뭉개진다. snapshot을
        # 보내지 않는 최소 handshake 뒤 4401을 닫아 client가 재시도를 중단할 수 있게 한다.
        rejected_subprotocol = select_ops_live_subprotocol(
            websocket.headers.get("sec-websocket-protocol")
        )
        await _rollback_and_accept_close(
            websocket,
            session,
            code=OPS_LIVE_AUTH_CLOSE_CODE,
            reason="ops live authentication required",
            subprotocol=rejected_subprotocol,
        )
        return
    remaining_lease_seconds = _remaining_lease_seconds(auth_context.expires_at)
    if remaining_lease_seconds <= 0:
        await _rollback_and_accept_close(
            websocket,
            session,
            code=OPS_LIVE_EXPIRED_CLOSE_CODE,
            reason="ops live ticket expired",
            subprotocol=auth_context.subprotocol,
        )
        return
    claim_timeout = asyncio.timeout(remaining_lease_seconds)
    try:
        async with claim_timeout:
            claimed = await claim_ops_live_ticket(session, auth_context)
    except TimeoutError:
        if (
            claim_timeout.expired()
            or _remaining_lease_seconds(auth_context.expires_at) <= 0
        ):
            await _rollback_and_accept_close(
                websocket,
                session,
                code=OPS_LIVE_EXPIRED_CLOSE_CODE,
                reason="ops live ticket expired",
                subprotocol=auth_context.subprotocol,
            )
            return
        _LOG.exception("ops live ticket nonce claim timeout")
        await _rollback_and_accept_close(
            websocket,
            session,
            code=_RETRY_LATER_CLOSE_CODE,
            reason="ops live authentication unavailable",
            subprotocol=auth_context.subprotocol,
        )
        return
    except Exception:  # noqa: BLE001 — claim 저장소 장애는 data 전송 없이 재시도 가능 close.
        _LOG.exception("ops live ticket nonce claim 실패")
        await _rollback_and_accept_close(
            websocket,
            session,
            code=_RETRY_LATER_CLOSE_CODE,
            reason="ops live authentication unavailable",
            subprotocol=auth_context.subprotocol,
        )
        return
    if _remaining_lease_seconds(auth_context.expires_at) <= 0:
        await _rollback_and_accept_close(
            websocket,
            session,
            code=OPS_LIVE_EXPIRED_CLOSE_CODE,
            reason="ops live ticket expired",
            subprotocol=auth_context.subprotocol,
        )
        return
    if not claimed:
        await _rollback_and_accept_close(
            websocket,
            session,
            code=OPS_LIVE_AUTH_CLOSE_CODE,
            reason="ops live ticket already used",
            subprotocol=auth_context.subprotocol,
        )
        return
    accepted = await _accept_best_effort(
        websocket,
        subprotocol=auth_context.subprotocol,
    )
    if not accepted:
        await _rollback_and_close(
            websocket,
            session,
            code=_RETRY_LATER_CLOSE_CODE,
            reason="ops live handshake unavailable",
        )
        return
    sequence = 1
    topics: set[str] = set()
    poll_interval_ms = _poll_interval_ms(websocket.query_params.get("poll_interval_ms"))
    poll_interval_seconds = poll_interval_ms / 1_000
    hello_sent = await _send_json_before_expiry(
        websocket,
        session,
        {
            **_message_base("hello", sequence=sequence),
            "actor": auth_context.actor,
            "topics": sorted(topics),
            "poll_interval_ms": poll_interval_ms,
            "ticket_expires_at": auth_context.expires_at.isoformat(),
        },
        expires_at=auth_context.expires_at,
    )
    if not hello_sent:
        return
    sequence += 1
    revisions: dict[str, str] = {}
    next_sequence = await _send_snapshots(
        websocket,
        session,
        topics,
        revisions,
        sequence=sequence,
        force=True,
        expires_at=auth_context.expires_at,
    )
    if next_sequence is None:
        return
    sequence = next_sequence
    last_heartbeat = _utcnow()
    try:
        while True:
            now = _utcnow()
            if now >= auth_context.expires_at:
                await _rollback_and_close(
                    websocket,
                    session,
                    code=OPS_LIVE_EXPIRED_CLOSE_CODE,
                    reason="ops live ticket expired",
                )
                return
            remaining_lease_seconds = (
                auth_context.expires_at - now
            ).total_seconds()
            try:
                command = await _receive_command(
                    websocket,
                    min(poll_interval_seconds, remaining_lease_seconds),
                )
            except WebSocketDisconnect:
                return
            except Exception:  # noqa: BLE001 — transport별 receive 오류는 1013으로 수렴한다.
                _LOG.exception("ops live command 수신 실패")
                await _rollback_and_close(
                    websocket,
                    session,
                    code=_RETRY_LATER_CLOSE_CODE,
                    reason="ops live transport unavailable",
                )
                return
            if command is not None:
                try:
                    topics, ack_type = _apply_command(topics, command)
                except ValueError as exc:
                    next_sequence = await _send_error(
                        websocket,
                        session,
                        sequence=sequence,
                        message=str(exc),
                        expires_at=auth_context.expires_at,
                    )
                    if next_sequence is None:
                        return
                    sequence = next_sequence
                    continue
                ack_sent = await _send_json_before_expiry(
                    websocket,
                    session,
                    {
                        **_message_base(ack_type, sequence=sequence),
                        "topics": sorted(topics),
                    },
                    expires_at=auth_context.expires_at,
                )
                if not ack_sent:
                    return
                sequence += 1
                next_sequence = await _send_snapshots(
                    websocket,
                    session,
                    topics,
                    revisions,
                    sequence=sequence,
                    force=True,
                    expires_at=auth_context.expires_at,
                )
                if next_sequence is None:
                    return
                sequence = next_sequence
                last_heartbeat = _utcnow()
                continue
            next_sequence = await _send_snapshots(
                websocket,
                session,
                topics,
                revisions,
                sequence=sequence,
                force=False,
                expires_at=auth_context.expires_at,
            )
            if next_sequence is None:
                return
            sequence = next_sequence
            now = _utcnow()
            if (now - last_heartbeat).total_seconds() >= _HEARTBEAT_INTERVAL_SECONDS:
                heartbeat_sent = await _send_json_before_expiry(
                    websocket,
                    session,
                    {
                        **_message_base("heartbeat", sequence=sequence),
                        "topics": sorted(topics),
                    },
                    expires_at=auth_context.expires_at,
                )
                if not heartbeat_sent:
                    return
                sequence += 1
                last_heartbeat = now
    except WebSocketDisconnect:
        return

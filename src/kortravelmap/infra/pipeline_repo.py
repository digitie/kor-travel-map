"""``kortravelmap.infra.pipeline_repo`` — 파이프라인 root 실행 read model.

``/v1/ops/pipeline/executions``가 쓰는 DB-only projection이다. import job hierarchy를
recursive SQL로 component에 귀속하고, 각 job의 가장 가까운 update request anchor로
branch를 나눈다. request branch와 owner 없는 standalone partition만 root로 노출한다.
Dagster run은 목록 cursor에 섞지 않고 실컬럼 ``dagster_run_id``로만 연결한다.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, cast
from uuid import UUID

from sqlalchemy import text

from kortravelmap.core.pipeline_cancellation_states import PipelineCancellationStatus
from kortravelmap.infra.pipeline_cancellation_repo import PipelineCancellationSummary
from kortravelmap.infra.pipeline_lineage import PIPELINE_LINEAGE_CTES_SQL

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "PIPELINE_EXECUTION_KINDS",
    "PipelineExecution",
    "PipelineExecutionPage",
    "PipelineProviderDatasetIdentity",
    "PipelineProjectedJob",
    "PipelineStatusCounts",
    "get_pipeline_status_counts",
    "list_pipeline_executions",
]

PIPELINE_EXECUTION_KINDS: Final[frozenset[str]] = frozenset({"import_job", "update_request"})

_MAX_PAGE_SIZE: Final[int] = 200
_CURSOR_KIND: Final[str] = "pipeline_executions"


@dataclass(frozen=True)
class PipelineExecution:
    """실행 타임라인 root 1행."""

    kind: str
    id: str
    status: str
    created_at: datetime
    providers: tuple[str, ...]
    dataset_keys: tuple[str, ...]
    provider_dataset: PipelineProviderDatasetIdentity | None
    progress: int | None
    current_stage: str | None
    scope_type: str | None
    priority: int | None
    run_mode: str | None
    operator: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    requested_job_id: str | None
    lineage_owner: bool | None
    linked_job_count: int
    projected_job: PipelineProjectedJob | None
    cancellation: PipelineCancellationSummary | None = None


@dataclass(frozen=True)
class PipelineProviderDatasetIdentity:
    """``provider_dataset`` request의 pair identity."""

    provider: str
    dataset_key: str
    sync_scope: str | None


@dataclass(frozen=True)
class PipelineProjectedJob:
    """root branch 또는 standalone partition에서 대표로 노출할 import job."""

    id: str
    job_kind: str
    status: str
    progress: int
    current_stage: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    dagster_run_id: str | None
    load_batch_id: str | None
    parent_job_id: str | None
    depth: int


@dataclass(frozen=True)
class PipelineExecutionPage:
    """Keyset cursor 기반 실행 타임라인 목록."""

    items: tuple[PipelineExecution, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class PipelineStatusCounts:
    """파이프라인 overview 상태 스트립용 작업/요청 집계."""

    import_jobs_by_status: dict[str, int]
    update_requests_by_status: dict[str, int]
    failed_import_jobs_24h: int
    failed_update_requests_24h: int


def _limit(value: int) -> int:
    if value <= 0:
        raise ValueError("limit must be greater than 0")
    return min(int(value), _MAX_PAGE_SIZE)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _encode_cursor(*, at: datetime, key: str, item_kind: str) -> str:
    if item_kind not in PIPELINE_EXECUTION_KINDS:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor")
    try:
        cursor_id = str(UUID(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor") from exc
    raw = json.dumps(
        {
            "v": 2,
            "cursor": _CURSOR_KIND,
            "at": at.isoformat(),
            "id": cursor_id,
            "item_kind": item_kind,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None,
) -> tuple[datetime | None, str | None, str | None]:
    if cursor is None:
        return None, None, None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {_CURSOR_KIND} cursor")
    if payload.get("v") != 2 or payload.get("cursor") != _CURSOR_KIND:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor")
    try:
        at = datetime.fromisoformat(str(payload["at"]))
        if at.utcoffset() is None:
            raise ValueError("cursor datetime must include a timezone")
        # id는 SQL에서 uuid로 CAST된다 — 여기서 UUID 형식을 강제해 비정형 값이
        # DB 오류(500)로 새지 않고 ValueError(라우터 422)로 떨어지게 한다.
        key = str(UUID(str(payload["id"])))
        item_kind = str(payload["item_kind"])
        if item_kind not in PIPELINE_EXECUTION_KINDS:
            raise ValueError("invalid item kind")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor") from exc
    return at, key, item_kind


# hierarchy를 component로 완전히 접은 다음 root filter/keyset을 적용한다. event identity
# 집계는 page에 실제 포함된 standalone root에만 lateral로 수행한다.
_LIST_EXECUTIONS_SQL: Final[str] = "WITH RECURSIVE\n" + PIPELINE_LINEAGE_CTES_SQL + """,
ranked_request_jobs AS (
    SELECT
        owner.owner_request_id,
        owner.anchor_depth AS depth,
        job.*,
        COUNT(*) OVER (PARTITION BY owner.owner_request_id)::integer
            AS linked_job_count,
        ROW_NUMBER() OVER (
            PARTITION BY owner.owner_request_id
            ORDER BY owner.anchor_depth DESC, job.created_at DESC, job.job_id DESC
        ) AS projection_rank
    FROM job_owners AS owner
    JOIN ops.import_jobs AS job ON job.job_id = owner.job_id
),
request_summaries AS (
    SELECT
        ranked.owner_request_id,
        ranked.linked_job_count,
        ranked.job_id AS projected_job_id,
        ranked.kind AS projected_job_kind,
        ranked.status AS projected_status,
        ranked.progress AS projected_progress,
        ranked.current_stage AS projected_current_stage,
        ranked.error_message AS projected_error_message,
        ranked.created_at AS projected_created_at,
        ranked.started_at AS projected_started_at,
        ranked.finished_at AS projected_finished_at,
        ranked.dagster_run_id AS projected_dagster_run_id,
        ranked.load_batch_id AS projected_load_batch_id,
        ranked.parent_job_id AS projected_parent_job_id,
        ranked.depth AS projected_depth
    FROM ranked_request_jobs AS ranked
    WHERE ranked.projection_rank = 1
),
ranked_standalone_jobs AS (
    SELECT
        standalone.*,
        COUNT(*) OVER (PARTITION BY standalone.component_root_id)::integer
            AS linked_job_count,
        ROW_NUMBER() OVER (
            PARTITION BY standalone.component_root_id
            ORDER BY
                standalone.depth DESC,
                standalone.created_at DESC,
                standalone.job_id DESC
        ) AS projection_rank
    FROM standalone_jobs AS standalone
),
standalone_summaries AS (
    SELECT
        ranked.component_root_id,
        ranked.linked_job_count,
        ranked.job_id AS projected_job_id,
        ranked.kind AS projected_job_kind,
        ranked.status AS projected_status,
        ranked.progress AS projected_progress,
        ranked.current_stage AS projected_current_stage,
        ranked.error_message AS projected_error_message,
        ranked.created_at AS projected_created_at,
        ranked.started_at AS projected_started_at,
        ranked.finished_at AS projected_finished_at,
        ranked.dagster_run_id AS projected_dagster_run_id,
        ranked.load_batch_id AS projected_load_batch_id,
        ranked.parent_job_id AS projected_parent_job_id,
        ranked.depth AS projected_depth
    FROM ranked_standalone_jobs AS ranked
    WHERE ranked.projection_rank = 1
),
request_roots AS (
    SELECT
        'update_request'::text AS kind,
        request.request_id AS id,
        request.status,
        request.created_at,
        stored.providers
          || CASE
            WHEN request.scope_type = 'provider_dataset'
             AND NULLIF(request.scope->>'provider', '') IS NOT NULL
             AND NOT (request.scope->>'provider' = ANY(stored.providers))
            THEN ARRAY[request.scope->>'provider']
            ELSE '{}'::text[]
          END AS providers,
        stored.dataset_keys
          || CASE
            WHEN request.scope_type = 'provider_dataset'
             AND NULLIF(request.scope->>'dataset_key', '') IS NOT NULL
             AND NOT (request.scope->>'dataset_key' = ANY(stored.dataset_keys))
            THEN ARRAY[request.scope->>'dataset_key']
            ELSE '{}'::text[]
          END AS dataset_keys,
        NULL::integer AS progress,
        NULL::text AS current_stage,
        request.scope_type,
        request.priority,
        request.run_mode,
        request.operator,
        request.error_message,
        request.started_at,
        request.finished_at,
        request.dagster_run_id,
        request.job_id AS requested_job_id,
        (anchor.request_id IS NOT NULL) AS lineage_owner,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.linked_job_count ELSE 0 END AS linked_job_count,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_job_id END AS projected_job_id,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_job_kind END AS projected_job_kind,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_status END AS projected_status,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_progress END AS projected_progress,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_current_stage END AS projected_current_stage,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_error_message END AS projected_error_message,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_created_at END AS projected_created_at,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_started_at END AS projected_started_at,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_finished_at END AS projected_finished_at,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_dagster_run_id END AS projected_dagster_run_id,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_load_batch_id END AS projected_load_batch_id,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_parent_job_id END AS projected_parent_job_id,
        CASE WHEN anchor.request_id IS NOT NULL
            THEN summary.projected_depth END AS projected_depth,
        request.scope->>'provider' AS scope_provider,
        request.scope->>'dataset_key' AS scope_dataset,
        request.scope->>'sync_scope' AS scope_sync_scope,
        anchor.component_root_id
    FROM ops.feature_update_requests AS request
    CROSS JOIN LATERAL (
      SELECT
        ARRAY(SELECT jsonb_array_elements_text(request.providers)) AS providers,
        ARRAY(SELECT jsonb_array_elements_text(request.dataset_keys)) AS dataset_keys
    ) AS stored
    LEFT JOIN anchor_requests AS anchor ON anchor.request_id = request.request_id
    LEFT JOIN request_summaries AS summary
      ON summary.owner_request_id = anchor.request_id
),
standalone_roots AS (
    SELECT
        'import_job'::text AS kind,
        root.job_id AS id,
        root.status,
        root.created_at,
        '{}'::text[] AS providers,
        '{}'::text[] AS dataset_keys,
        root.progress,
        root.current_stage,
        NULL::text AS scope_type,
        NULL::integer AS priority,
        NULL::text AS run_mode,
        NULL::text AS operator,
        root.error_message,
        root.started_at,
        root.finished_at,
        root.dagster_run_id,
        NULL::uuid AS requested_job_id,
        NULL::boolean AS lineage_owner,
        summary.linked_job_count,
        summary.projected_job_id,
        summary.projected_job_kind,
        summary.projected_status,
        summary.projected_progress,
        summary.projected_current_stage,
        summary.projected_error_message,
        summary.projected_created_at,
        summary.projected_started_at,
        summary.projected_finished_at,
        summary.projected_dagster_run_id,
        summary.projected_load_batch_id,
        summary.projected_parent_job_id,
        summary.projected_depth,
        NULL::text AS scope_provider,
        NULL::text AS scope_dataset,
        NULL::text AS scope_sync_scope,
        summary.component_root_id
    FROM standalone_summaries AS summary
    JOIN ops.import_jobs AS root ON root.job_id = summary.component_root_id
),
all_roots AS (
    SELECT * FROM request_roots
    UNION ALL
    SELECT * FROM standalone_roots
),
filtered_roots AS (
    SELECT root.*
    FROM all_roots AS root
    WHERE (CAST(:kind AS text) IS NULL OR root.kind = CAST(:kind AS text))
      AND (CAST(:status AS text) IS NULL OR root.status = CAST(:status AS text))
      AND (
        CAST(:provider AS text) IS NULL
        OR (
          root.kind = 'update_request'
          AND (
            CAST(:provider AS text) = ANY(root.providers)
            OR (
              root.scope_type = 'provider_dataset'
              AND root.scope_provider = CAST(:provider AS text)
            )
          )
        )
        OR (
          root.kind = 'import_job'
          AND EXISTS (
            SELECT 1
            FROM standalone_jobs AS component
            CROSS JOIN LATERAL (
              SELECT 1
              FROM ops.import_job_events AS event
              WHERE event.job_id = component.job_id
                AND NULLIF(event.provider, '') = CAST(:provider AS text)
              LIMIT 1
            ) AS matched_provider
            WHERE component.component_root_id = root.component_root_id
          )
        )
      )
      AND (
        CAST(:dataset_key AS text) IS NULL
        OR (
          root.kind = 'update_request'
          AND (
            CAST(:dataset_key AS text) = ANY(root.dataset_keys)
            OR (
              root.scope_type = 'provider_dataset'
              AND root.scope_dataset = CAST(:dataset_key AS text)
            )
          )
        )
        OR (
          root.kind = 'import_job'
          AND EXISTS (
            SELECT 1
            FROM standalone_jobs AS component
            CROSS JOIN LATERAL (
              SELECT 1
              FROM ops.import_job_events AS event
              WHERE event.job_id = component.job_id
                AND NULLIF(event.dataset_key, '') = CAST(:dataset_key AS text)
              LIMIT 1
            ) AS matched_dataset
            WHERE component.component_root_id = root.component_root_id
          )
        )
      )
      AND (
        CAST(:created_from AS timestamptz) IS NULL
        OR root.created_at >= CAST(:created_from AS timestamptz)
      )
      AND (
        CAST(:created_to AS timestamptz) IS NULL
        OR root.created_at <= CAST(:created_to AS timestamptz)
      )
      AND (
        CAST(:cursor_created_at AS timestamptz) IS NULL
        OR (root.created_at, root.id, root.kind) < (
          CAST(:cursor_created_at AS timestamptz),
          CAST(:cursor_id AS uuid),
          CAST(:cursor_item_kind AS text)
        )
      )
),
page_roots AS (
    SELECT *
    FROM filtered_roots
    ORDER BY created_at DESC, id DESC, kind DESC
    LIMIT :page_limit
)
SELECT
    page.kind,
    page.id,
    page.status,
    page.created_at,
    CASE WHEN page.kind = 'import_job'
      THEN COALESCE(identity.providers, '{}'::text[])
      ELSE page.providers
    END AS providers,
    CASE WHEN page.kind = 'import_job'
      THEN COALESCE(identity.dataset_keys, '{}'::text[])
      ELSE page.dataset_keys
    END AS dataset_keys,
    page.scope_provider,
    page.scope_dataset,
    page.scope_sync_scope,
    page.progress,
    page.current_stage,
    page.scope_type,
    page.priority,
    page.run_mode,
    page.operator,
    page.error_message,
    page.started_at,
    page.finished_at,
    page.dagster_run_id,
    page.requested_job_id,
    page.lineage_owner,
    page.linked_job_count,
    page.projected_job_id,
    page.projected_job_kind,
    page.projected_status,
    page.projected_progress,
    page.projected_current_stage,
    page.projected_error_message,
    page.projected_created_at,
    page.projected_started_at,
    page.projected_finished_at,
    page.projected_dagster_run_id,
    page.projected_load_batch_id,
    page.projected_parent_job_id,
    page.projected_depth,
    cancellation.cancellation_id,
    cancellation.cancellation_status,
    cancellation.cancellation_requested_at,
    cancellation.cancellation_requested_by,
    cancellation.cancellation_reason,
    cancellation.cancellation_retryable,
    cancellation.cancellation_unresolved_member_count
FROM page_roots AS page
LEFT JOIN LATERAL (
    SELECT
        COALESCE(
          array_agg(DISTINCT NULLIF(event.provider, '')
                    ORDER BY NULLIF(event.provider, ''))
            FILTER (WHERE NULLIF(event.provider, '') IS NOT NULL),
          '{}'::text[]
        ) AS providers,
        COALESCE(
          array_agg(DISTINCT NULLIF(event.dataset_key, '')
                    ORDER BY NULLIF(event.dataset_key, ''))
            FILTER (WHERE NULLIF(event.dataset_key, '') IS NOT NULL),
          '{}'::text[]
        ) AS dataset_keys
    FROM standalone_jobs AS component
    JOIN ops.import_job_events AS event ON event.job_id = component.job_id
    WHERE page.kind = 'import_job'
      AND component.component_root_id = page.component_root_id
) AS identity ON page.kind = 'import_job'
LEFT JOIN LATERAL (
    SELECT
        attempt.cancellation_id,
        attempt.status AS cancellation_status,
        attempt.requested_at AS cancellation_requested_at,
        attempt.requested_by AS cancellation_requested_by,
        attempt.reason AS cancellation_reason,
        (attempt.status = 'retryable') AS cancellation_retryable,
        (
          SELECT COUNT(*)::integer
          FROM ops.pipeline_cancellation_members AS member
          WHERE member.cancellation_id = attempt.cancellation_id
            AND member.result IN ('pending', 'cancel_failed')
        ) AS cancellation_unresolved_member_count
    FROM ops.pipeline_cancellations AS attempt
    WHERE attempt.root_kind = page.kind
      AND attempt.root_id = page.id
    ORDER BY
        (attempt.status = 'in_progress') DESC,
        attempt.requested_at DESC,
        attempt.cancellation_id DESC
    LIMIT 1
) AS cancellation ON true
ORDER BY page.created_at DESC, page.id DESC, page.kind DESC
"""

_STATUS_COUNTS_SQL: Final[str] = """
SELECT
  (
    SELECT COALESCE(jsonb_object_agg(status, n), '{}'::jsonb)
    FROM (
      SELECT status, COUNT(*)::int AS n
      FROM ops.import_jobs
      GROUP BY status
    ) AS s
  ) AS import_jobs_by_status,
  (
    SELECT COALESCE(jsonb_object_agg(status, n), '{}'::jsonb)
    FROM (
      SELECT status, COUNT(*)::int AS n
      FROM ops.feature_update_requests
      GROUP BY status
    ) AS s
  ) AS update_requests_by_status,
  (
    SELECT COUNT(*)::int
    FROM ops.import_jobs
    WHERE status = 'failed'
      AND COALESCE(finished_at, created_at) >= now() - INTERVAL '24 hours'
  ) AS failed_import_jobs_24h,
  (
    SELECT COUNT(*)::int
    FROM ops.feature_update_requests
    WHERE status = 'failed'
      AND COALESCE(finished_at, created_at) >= now() - INTERVAL '24 hours'
  ) AS failed_update_requests_24h
"""


def _row_to_execution(row: Any) -> PipelineExecution:
    provider_dataset = None
    if (
        row.kind == "update_request"
        and row.scope_type == "provider_dataset"
        and row.scope_provider
        and row.scope_dataset
    ):
        provider_dataset = PipelineProviderDatasetIdentity(
            provider=str(row.scope_provider),
            dataset_key=str(row.scope_dataset),
            sync_scope=(str(row.scope_sync_scope) if row.scope_sync_scope is not None else None),
        )
    projected_job = None
    if row.projected_job_id is not None:
        projected_job = PipelineProjectedJob(
            id=str(row.projected_job_id),
            job_kind=str(row.projected_job_kind),
            status=str(row.projected_status),
            progress=int(row.projected_progress),
            current_stage=row.projected_current_stage,
            error_message=row.projected_error_message,
            created_at=row.projected_created_at,
            started_at=row.projected_started_at,
            finished_at=row.projected_finished_at,
            dagster_run_id=row.projected_dagster_run_id,
            load_batch_id=(
                str(row.projected_load_batch_id)
                if row.projected_load_batch_id is not None
                else None
            ),
            parent_job_id=(
                str(row.projected_parent_job_id)
                if row.projected_parent_job_id is not None
                else None
            ),
            depth=int(row.projected_depth),
        )
    cancellation = None
    if row.cancellation_id is not None:
        cancellation = PipelineCancellationSummary(
            cancellation_id=str(row.cancellation_id),
            status=cast(
                PipelineCancellationStatus,
                str(row.cancellation_status),
            ),
            requested_at=row.cancellation_requested_at,
            requested_by=str(row.cancellation_requested_by),
            reason=row.cancellation_reason,
            retryable=bool(row.cancellation_retryable),
            unresolved_member_count=int(
                row.cancellation_unresolved_member_count
            ),
        )
    return PipelineExecution(
        kind=str(row.kind),
        id=str(row.id),
        status=str(row.status),
        created_at=row.created_at,
        providers=tuple(str(value) for value in row.providers),
        dataset_keys=tuple(str(value) for value in row.dataset_keys),
        provider_dataset=provider_dataset,
        progress=int(row.progress) if row.progress is not None else None,
        current_stage=row.current_stage,
        scope_type=row.scope_type,
        priority=int(row.priority) if row.priority is not None else None,
        run_mode=row.run_mode,
        operator=row.operator,
        error_message=row.error_message,
        started_at=row.started_at,
        finished_at=row.finished_at,
        dagster_run_id=row.dagster_run_id,
        requested_job_id=(str(row.requested_job_id) if row.requested_job_id is not None else None),
        lineage_owner=(bool(row.lineage_owner) if row.lineage_owner is not None else None),
        linked_job_count=int(row.linked_job_count),
        projected_job=projected_job,
        cancellation=cancellation,
    )


async def list_pipeline_executions(
    session: AsyncSession,
    *,
    kind: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> PipelineExecutionPage:
    """root 실행 목록 — ``(created_at DESC, id DESC, kind DESC)`` cursor."""
    if kind is not None and kind not in PIPELINE_EXECUTION_KINDS:
        raise ValueError(f"kind must be one of {sorted(PIPELINE_EXECUTION_KINDS)}, got {kind!r}")
    page_size = _limit(limit)
    cursor_created_at, cursor_id, cursor_item_kind = _decode_cursor(cursor)
    rows = (
        await session.execute(
            text(_LIST_EXECUTIONS_SQL),
            {
                "kind": kind,
                "status": status,
                "provider": provider,
                "dataset_key": dataset_key,
                "created_from": created_from,
                "created_to": created_to,
                "cursor_created_at": cursor_created_at,
                "cursor_id": cursor_id,
                "cursor_item_kind": cursor_item_kind,
                "page_limit": page_size + 1,
            },
        )
    ).all()
    items = tuple(_row_to_execution(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor(
            at=items[-1].created_at,
            key=items[-1].id,
            item_kind=items[-1].kind,
        )
        if len(rows) > page_size and items
        else None
    )
    return PipelineExecutionPage(items=items, next_cursor=next_cursor)


async def get_pipeline_status_counts(session: AsyncSession) -> PipelineStatusCounts:
    """overview 상태 스트립용 작업/요청 상태 집계 + 최근 24h 실패 카운트."""
    row = (await session.execute(text(_STATUS_COUNTS_SQL))).one()
    return PipelineStatusCounts(
        import_jobs_by_status={
            str(k): int(v) for k, v in _json_dict(row.import_jobs_by_status).items()
        },
        update_requests_by_status={
            str(k): int(v) for k, v in _json_dict(row.update_requests_by_status).items()
        },
        failed_import_jobs_24h=int(row.failed_import_jobs_24h),
        failed_update_requests_24h=int(row.failed_update_requests_24h),
    )

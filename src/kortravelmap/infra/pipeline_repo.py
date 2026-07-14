"""``kortravelmap.infra.pipeline_repo`` — 파이프라인 실행 타임라인 UNION 조회 (ADR-064).

``/v1/ops/pipeline/executions``가 쓰는 **DB-only UNION** 조회다:
``ops.import_jobs`` ∪ ``ops.feature_update_requests``를 공유 keyset cursor
``(created_at DESC, id DESC)`` + ``kind`` discriminator(``import_job`` /
``update_request``)로 병합한다. Dagster run(GraphQL, 휘발·cursor 없음)은 이 목록에
**섞지 않는다** — 연결은 실컬럼 ``dagster_run_id`` 속성으로만 노출한다(ADR-064 §2).

성능: 두 branch 각각 자신의 ``(created_at DESC, id DESC)`` 인덱스로 사전
정렬·제한(limit+1)한 뒤 병합-재정렬한다. cursor 술어는 branch 안쪽에 두어
인덱스 range scan을 유지한다.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "PIPELINE_EXECUTION_KINDS",
    "PipelineExecution",
    "PipelineExecutionPage",
    "PipelineStatusCounts",
    "get_pipeline_status_counts",
    "list_pipeline_executions",
]

PIPELINE_EXECUTION_KINDS: Final[frozenset[str]] = frozenset(
    {"import_job", "update_request"}
)

_MAX_PAGE_SIZE: Final[int] = 200
_CURSOR_KIND: Final[str] = "pipeline_executions"


@dataclass(frozen=True)
class PipelineExecution:
    """실행 타임라인 1행 — import job 또는 feature update request."""

    kind: str
    id: str
    status: str
    created_at: datetime
    job_kind: str | None
    provider: str | None
    dataset_key: str | None
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
    job_id: str | None
    request_id: str | None
    load_batch_id: str | None
    parent_job_id: str | None


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


def _encode_cursor(*, at: datetime, key: str) -> str:
    raw = json.dumps(
        {"v": 1, "kind": _CURSOR_KIND, "at": at.isoformat(), "key": key},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, str | None]:
    if cursor is None:
        return None, None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"invalid {_CURSOR_KIND} cursor")
    if payload.get("v") != 1 or payload.get("kind") != _CURSOR_KIND:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor")
    try:
        at = datetime.fromisoformat(str(payload["at"]))
        # key는 SQL에서 uuid로 CAST된다 — 여기서 UUID 형식을 강제해 비정형 값이
        # DB 오류(500)로 새지 않고 ValueError(라우터 422)로 떨어지게 한다.
        key = str(UUID(str(payload["key"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor") from exc
    return at, key


# 두 branch 모두 동일 컬럼 시그니처를 갖는다. 각 branch에서 인덱스 정렬 + limit+1
# 사전 제한 후 바깥에서 병합-재정렬한다. cursor/필터 술어는 branch 안에 둔다.
_LIST_EXECUTIONS_SQL: Final[str] = """
WITH import_job_rows AS (
    SELECT
        'import_job'::text AS kind,
        job_id AS id,
        status,
        created_at,
        kind AS job_kind,
        payload->>'provider' AS provider,
        payload->>'dataset_key' AS dataset_key,
        progress,
        current_stage,
        NULL::text AS scope_type,
        NULL::integer AS priority,
        NULL::text AS run_mode,
        NULL::text AS operator,
        error_message,
        started_at,
        finished_at,
        dagster_run_id,
        NULL::uuid AS linked_job_id,
        payload->>'request_id' AS linked_request_id,
        load_batch_id,
        parent_job_id
    FROM ops.import_jobs
    WHERE CAST(:include_import_jobs AS boolean)
      AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
      AND (
        CAST(:provider AS text) IS NULL
        OR payload->>'provider' = CAST(:provider AS text)
      )
      AND (
        CAST(:created_from AS timestamptz) IS NULL
        OR created_at >= CAST(:created_from AS timestamptz)
      )
      AND (
        CAST(:created_to AS timestamptz) IS NULL
        OR created_at <= CAST(:created_to AS timestamptz)
      )
      AND (
        CAST(:cursor_created_at AS timestamptz) IS NULL
        OR (created_at, job_id) < (
            CAST(:cursor_created_at AS timestamptz),
            CAST(:cursor_id AS uuid)
        )
      )
    ORDER BY created_at DESC, job_id DESC
    LIMIT :branch_limit
),
update_request_rows AS (
    SELECT
        'update_request'::text AS kind,
        request_id AS id,
        status,
        created_at,
        NULL::text AS job_kind,
        COALESCE(scope->>'provider', providers->>0) AS provider,
        COALESCE(scope->>'dataset_key', dataset_keys->>0) AS dataset_key,
        NULL::integer AS progress,
        NULL::text AS current_stage,
        scope_type,
        priority,
        run_mode,
        operator,
        error_message,
        started_at,
        finished_at,
        dagster_run_id,
        job_id AS linked_job_id,
        NULL::text AS linked_request_id,
        NULL::uuid AS load_batch_id,
        NULL::uuid AS parent_job_id
    FROM ops.feature_update_requests
    WHERE CAST(:include_update_requests AS boolean)
      AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
      AND (
        CAST(:provider AS text) IS NULL
        OR providers @> CAST(:provider_filter AS jsonb)
        OR scope->>'provider' = CAST(:provider AS text)
      )
      AND (
        CAST(:created_from AS timestamptz) IS NULL
        OR created_at >= CAST(:created_from AS timestamptz)
      )
      AND (
        CAST(:created_to AS timestamptz) IS NULL
        OR created_at <= CAST(:created_to AS timestamptz)
      )
      AND (
        CAST(:cursor_created_at AS timestamptz) IS NULL
        OR (created_at, request_id) < (
            CAST(:cursor_created_at AS timestamptz),
            CAST(:cursor_id AS uuid)
        )
      )
    ORDER BY created_at DESC, request_id DESC
    LIMIT :branch_limit
)
SELECT *
FROM (
    SELECT * FROM import_job_rows
    UNION ALL
    SELECT * FROM update_request_rows
) AS united
ORDER BY created_at DESC, id DESC
LIMIT :branch_limit
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
    return PipelineExecution(
        kind=str(row.kind),
        id=str(row.id),
        status=str(row.status),
        created_at=row.created_at,
        job_kind=row.job_kind,
        provider=row.provider,
        dataset_key=row.dataset_key,
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
        job_id=str(row.linked_job_id) if row.linked_job_id is not None else None,
        request_id=row.linked_request_id,
        load_batch_id=str(row.load_batch_id) if row.load_batch_id is not None else None,
        parent_job_id=(
            str(row.parent_job_id) if row.parent_job_id is not None else None
        ),
    )


async def list_pipeline_executions(
    session: AsyncSession,
    *,
    kind: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> PipelineExecutionPage:
    """실행 타임라인 UNION 목록 — ``(created_at DESC, id DESC)`` keyset cursor.

    ``kind``가 ``None``이면 두 branch를 모두 병합하고, ``import_job`` /
    ``update_request``면 해당 branch만 조회한다. provider 필터는 import job의
    ``payload->>'provider'``와 update request의 ``providers`` 배열/
    ``provider_dataset`` scope를 함께 본다.
    """
    if kind is not None and kind not in PIPELINE_EXECUTION_KINDS:
        raise ValueError(
            f"kind must be one of {sorted(PIPELINE_EXECUTION_KINDS)}, got {kind!r}"
        )
    page_size = _limit(limit)
    cursor_created_at, cursor_id = _decode_cursor(cursor)
    rows = (
        await session.execute(
            text(_LIST_EXECUTIONS_SQL),
            {
                "include_import_jobs": kind in (None, "import_job"),
                "include_update_requests": kind in (None, "update_request"),
                "status": status,
                "provider": provider,
                "provider_filter": (
                    json.dumps([provider]) if provider is not None else None
                ),
                "created_from": created_from,
                "created_to": created_to,
                "cursor_created_at": cursor_created_at,
                "cursor_id": cursor_id,
                "branch_limit": page_size + 1,
            },
        )
    ).all()
    items = tuple(_row_to_execution(row) for row in rows[:page_size])
    next_cursor = (
        _encode_cursor(at=items[-1].created_at, key=items[-1].id)
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
            str(k): int(v)
            for k, v in _json_dict(row.update_requests_by_status).items()
        },
        failed_import_jobs_24h=int(row.failed_import_jobs_24h),
        failed_update_requests_24h=int(row.failed_update_requests_24h),
    )

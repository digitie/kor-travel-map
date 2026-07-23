"""``kortravelmap.infra.pipeline_repo`` — 파이프라인 root 실행 read model.

``/v1/ops/pipeline/executions``가 쓰는 DB-only projection이다. import job hierarchy를
recursive SQL로 component에 귀속하고, 각 job의 가장 가까운 update request anchor로
branch를 나눈다. request branch와 owner 없는 standalone partition만 root로 노출한다.
Dagster run은 목록 cursor에 섞지 않고 실컬럼 ``dagster_run_id``로만 연결한다.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, cast
from uuid import UUID

from sqlalchemy import text

from kortravelmap.core.pipeline_cancellation_states import PipelineCancellationStatus
from kortravelmap.core.sync_scope import parse_canonical_sync_scope
from kortravelmap.infra.pipeline_cancellation_repo import PipelineCancellationSummary
from kortravelmap.infra.pipeline_lineage import (
    PIPELINE_LINEAGE_BODY_SQL,
    PIPELINE_LINEAGE_CTES_SQL,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "PIPELINE_EXECUTION_KINDS",
    "PipelineExecution",
    "PipelineExecutionPage",
    "PipelineDatasetLatestExecution",
    "PipelineDatasetExecutionSnapshot",
    "PipelineCursorFilterMismatch",
    "PipelineProviderDatasetIdentity",
    "PipelineProjectedJob",
    "PipelineStatusCounts",
    "get_pipeline_status_counts",
    "get_pipeline_execution",
    "list_latest_dataset_pipeline_executions",
    "list_dataset_pipeline_execution_snapshots",
    "list_dataset_pipeline_execution_snapshots_scoped",
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
    provider_datasets: tuple[PipelineProviderDatasetIdentity, ...]
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
    dagster_run_status: str | None
    trigger_kind: str | None
    operation_registry_version: str | None
    requested_job_id: str | None
    linked_job_count: int
    projected_job: PipelineProjectedJob
    cancellation: PipelineCancellationSummary | None = None


@dataclass(frozen=True)
class PipelineProviderDatasetIdentity:
    """canonical root에 귀속된 정확한 provider/dataset pair."""

    provider: str
    dataset_key: str
    sync_scope: str | None
    operation_member_id: str
    status: str


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
    dagster_run_status: str | None
    trigger_kind: str | None
    operation_registry_version: str | None
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
    """canonical root 단위 파이프라인 overview 집계."""

    operations_by_status: dict[str, int]
    active_operations: int
    failed_operations_24h: int


@dataclass(frozen=True)
class PipelineDatasetLatestExecution:
    """provider/dataset/scope별 최신 canonical root와 해당 pair 상태."""

    provider: str
    dataset_key: str
    sync_scope: str | None
    execution: PipelineExecution
    operation_member_id: str
    pair_status: str


@dataclass(frozen=True)
class PipelineDatasetExecutionSnapshot:
    """동일 DB snapshot에서 읽은 exact scope의 종료/활성 실행."""

    provider: str
    dataset_key: str
    sync_scope: str | None
    latest_terminal: PipelineDatasetLatestExecution | None
    active: PipelineDatasetLatestExecution | None


class PipelineCursorFilterMismatch(ValueError):
    """다른 filter 집합에서 발급한 실행 cursor를 재사용했다."""


def _filter_fingerprint(
    *,
    kind: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    sync_scopes: tuple[str, ...] = (),
    include_unscoped_scope: bool = False,
    filter_sync_scopes: bool = False,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> str:
    payload = {
        "kind": kind,
        "status": status,
        "provider": provider,
        "dataset_key": dataset_key,
        "sync_scopes": sorted(sync_scopes),
        "include_unscoped_scope": include_unscoped_scope,
        "filter_sync_scopes": filter_sync_scopes,
        "load_batch_id": load_batch_id,
        "parent_job_id": parent_job_id,
        "created_from": created_from.isoformat() if created_from is not None else None,
        "created_to": created_to.isoformat() if created_to is not None else None,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_EMPTY_FILTER_FINGERPRINT: Final[str] = _filter_fingerprint()


def _limit(value: int) -> int:
    if value <= 0:
        raise ValueError("limit must be greater than 0")
    return min(int(value), _MAX_PAGE_SIZE)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return list(value) if value else []


def _encode_cursor(
    *,
    at: datetime,
    key: str,
    item_kind: str,
    filter_fingerprint: str = _EMPTY_FILTER_FINGERPRINT,
) -> str:
    if item_kind not in PIPELINE_EXECUTION_KINDS:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor")
    try:
        cursor_id = str(UUID(key))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor") from exc
    raw = json.dumps(
        {
            "v": 3,
            "cursor": _CURSOR_KIND,
            "filters": filter_fingerprint,
            "at": at.isoformat(),
            "id": cursor_id,
            "item_kind": item_kind,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(
    cursor: str | None,
    *,
    filter_fingerprint: str = _EMPTY_FILTER_FINGERPRINT,
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
    if payload.get("v") != 3 or payload.get("cursor") != _CURSOR_KIND:
        raise ValueError(f"invalid {_CURSOR_KIND} cursor")
    if payload.get("filters") != filter_fingerprint:
        raise PipelineCursorFilterMismatch(
            f"{_CURSOR_KIND} cursor does not match the current filters"
        )
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


# hierarchy/component/anchor 규칙과 exact pair projection은 executions, overview,
# datasets latest가 같은 CTE를 공유한다. provider와 dataset 배열은 표시·단일 필터용일
# 뿐 pair 복원에는 절대 사용하지 않는다. 실행 identity의 DB 정본은 import_jobs의
# typed column이며 import_job_events는 감사·타임라인 전용이라 projection에서 읽지 않는다.
# projection body는 source CTE 이름만 알며 overview/latest/무필터 목록은 전역 source,
# identity/detail 조회는 component source를 쓴다.
_PIPELINE_ROOT_BODY_SQL: Final[str] = """
ranked_request_jobs AS (
    SELECT
        owner.owner_request_id,
        owner.anchor_depth AS depth,
        job.*,
        COUNT(*) OVER (PARTITION BY owner.owner_request_id)::integer
            AS linked_job_count,
        ROW_NUMBER() OVER (
            PARTITION BY owner.owner_request_id
            ORDER BY
                CASE
                  WHEN job.kind = 'provider_feature_load_run'
                   AND job.job_id = owner.anchor_job_id THEN 0
                  ELSE 1
                END,
                owner.anchor_depth DESC,
                job.created_at DESC,
                job.job_id DESC
        ) AS projection_rank
    FROM job_owners AS owner
    JOIN pipeline_jobs AS job ON job.job_id = owner.job_id
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
        ranked.dagster_run_status AS projected_dagster_run_status,
        ranked.trigger_kind AS projected_trigger_kind,
        ranked.operation_registry_version AS projected_operation_registry_version,
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
                CASE
                  WHEN standalone.kind = 'provider_feature_load_run'
                   AND standalone.job_id = standalone.component_root_id THEN 0
                  ELSE 1
                END,
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
        ranked.dagster_run_status AS projected_dagster_run_status,
        ranked.trigger_kind AS projected_trigger_kind,
        ranked.operation_registry_version AS projected_operation_registry_version,
        ranked.load_batch_id AS projected_load_batch_id,
        ranked.parent_job_id AS projected_parent_job_id,
        ranked.depth AS projected_depth
    FROM ranked_standalone_jobs AS ranked
    WHERE ranked.projection_rank = 1
),
direct_request_pairs AS (
    SELECT
        'update_request'::text AS root_kind,
        request.request_id AS root_id,
        request.scope->>'provider' AS provider,
        request.scope->>'dataset_key' AS dataset_key,
        request.effective_sync_scope AS sync_scope
    FROM pipeline_requests AS request
    WHERE request.scope_type = 'provider_dataset'
      AND jsonb_typeof(request.scope->'provider') = 'string'
      AND jsonb_typeof(request.scope->'dataset_key') = 'string'
      AND btrim(request.scope->>'provider') = request.scope->>'provider'
      AND btrim(request.scope->>'dataset_key') = request.scope->>'dataset_key'
      AND btrim(request.scope->>'provider') <> ''
      AND btrim(request.scope->>'dataset_key') <> ''
),
request_roots AS (
    SELECT
        'update_request'::text AS kind,
        request.request_id AS id,
        request.status,
        request.created_at,
        request.providers,
        request.dataset_keys,
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
        NULL::text AS dagster_run_status,
        'update_request'::text AS trigger_kind,
        NULL::text AS operation_registry_version,
        request.job_id AS requested_job_id,
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
        summary.projected_dagster_run_status,
        summary.projected_trigger_kind,
        summary.projected_operation_registry_version,
        summary.projected_load_batch_id,
        summary.projected_parent_job_id,
        summary.projected_depth,
        anchor.component_root_id
    FROM pipeline_requests AS request
    JOIN anchor_requests AS anchor ON anchor.request_id = request.request_id
    JOIN request_summaries AS summary
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
        root.dagster_run_status,
        root.trigger_kind,
        root.operation_registry_version,
        NULL::uuid AS requested_job_id,
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
        summary.projected_dagster_run_status,
        summary.projected_trigger_kind,
        summary.projected_operation_registry_version,
        summary.projected_load_batch_id,
        summary.projected_parent_job_id,
        summary.projected_depth,
        summary.component_root_id
    FROM standalone_summaries AS summary
    JOIN pipeline_jobs AS root ON root.job_id = summary.component_root_id
),
all_roots AS (
    SELECT * FROM request_roots
    UNION ALL
    SELECT * FROM standalone_roots
),
root_job_members AS (
    SELECT
        'update_request'::text AS root_kind,
        owner.owner_request_id AS root_id,
        owner.job_id,
        owner.anchor_depth AS depth,
        job.load_batch_id,
        job.parent_job_id,
        job.provider,
        job.dataset_key,
        job.status,
        job.created_at
    FROM job_owners AS owner
    JOIN pipeline_jobs AS job ON job.job_id = owner.job_id

    UNION ALL

    SELECT
        'import_job'::text AS root_kind,
        standalone.component_root_id AS root_id,
        standalone.job_id,
        standalone.depth,
        standalone.load_batch_id,
        standalone.parent_job_id,
        standalone.provider,
        standalone.dataset_key,
        standalone.status,
        standalone.created_at
    FROM standalone_jobs AS standalone
),
ranked_member_pairs AS (
    SELECT
        member.*,
        ROW_NUMBER() OVER (
            PARTITION BY
                member.root_kind, member.root_id,
                member.provider, member.dataset_key
            ORDER BY member.depth DESC, member.created_at DESC, member.job_id DESC
        ) AS pair_rank
    FROM root_job_members AS member
    WHERE NULLIF(member.provider, '') IS NOT NULL
      AND NULLIF(member.dataset_key, '') IS NOT NULL
),
canonical_provider_datasets AS (
    SELECT
        member.root_kind,
        member.root_id,
        member.provider,
        member.dataset_key,
        direct.sync_scope,
        member.job_id AS operation_member_id,
        member.status
    FROM ranked_member_pairs AS member
    LEFT JOIN direct_request_pairs AS direct
      ON direct.root_kind = member.root_kind
     AND direct.root_id = member.root_id
     AND direct.provider = member.provider
     AND direct.dataset_key = member.dataset_key
    WHERE member.pair_rank = 1
),
roots_with_identity AS (
    SELECT
        root.*,
        ARRAY(
            SELECT DISTINCT identity.provider
            FROM (
                SELECT unnest(root.providers) AS provider
                UNION ALL
                SELECT pair.provider
                FROM canonical_provider_datasets AS pair
                WHERE pair.root_kind = root.kind AND pair.root_id = root.id
            ) AS identity
            WHERE NULLIF(identity.provider, '') IS NOT NULL
            ORDER BY identity.provider
        ) AS effective_providers,
        ARRAY(
            SELECT DISTINCT identity.dataset_key
            FROM (
                SELECT unnest(root.dataset_keys) AS dataset_key
                UNION ALL
                SELECT pair.dataset_key
                FROM canonical_provider_datasets AS pair
                WHERE pair.root_kind = root.kind AND pair.root_id = root.id
            ) AS identity
            WHERE NULLIF(identity.dataset_key, '') IS NOT NULL
            ORDER BY identity.dataset_key
        ) AS effective_dataset_keys,
        COALESCE(
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'provider', pair.provider,
                        'dataset_key', pair.dataset_key,
                        'sync_scope', pair.sync_scope,
                        'operation_member_id', pair.operation_member_id,
                        'status', pair.status
                    )
                    ORDER BY pair.provider, pair.dataset_key
                )
                FROM canonical_provider_datasets AS pair
                WHERE pair.root_kind = root.kind AND pair.root_id = root.id
            ),
            '[]'::jsonb
        ) AS provider_datasets
    FROM all_roots AS root
)
"""

_PIPELINE_ROOT_CTES_SQL: Final[str] = PIPELINE_LINEAGE_CTES_SQL + ",\n" + _PIPELINE_ROOT_BODY_SQL

# --- scoped 변형 (dataset detail 조회 전용) ---------------------------------
# ``load_dataset_detail``은 단일 (provider, dataset_key) snapshot만 필요하지만
# unscoped ``_LIST_DATASET_EXECUTION_SNAPSHOTS_SQL``은 roots_with_identity의
# per-root 상관 서브쿼리를 전체 파이프라인 히스토리에 대해 계산하므로 누적 실행
# 이력에 비례해 O(roots^2)로 악화하고(높은 plan cost가 JIT까지 유발) detail
# endpoint가 클라이언트 timeout을 넘긴다. 아래 변형은 roots_with_identity를 대상
# (provider, dataset_key)에 속한 root로만 좁혀 동일 결과를 훨씬 적은 비용으로
# 만든다. 공유 CTE 텍스트를 그대로 재사용하고 마지막 ``FROM all_roots`` 소스에만
# EXISTS 필터를 덧붙인다.
_ROOTS_WITH_IDENTITY_FROM_ANCHOR: Final[str] = "    FROM all_roots AS root\n)"
if _ROOTS_WITH_IDENTITY_FROM_ANCHOR not in _PIPELINE_ROOT_BODY_SQL:  # pragma: no cover
    raise RuntimeError(
        "pipeline_repo: scoped dataset snapshot anchor "
        "'FROM all_roots AS root' 를 찾지 못했습니다"
    )
_PIPELINE_ROOT_BODY_SCOPED_SQL: Final[str] = _PIPELINE_ROOT_BODY_SQL.replace(
    _ROOTS_WITH_IDENTITY_FROM_ANCHOR,
    "    FROM all_roots AS root\n"
    "    WHERE EXISTS (\n"
    "        SELECT 1\n"
    "        FROM canonical_provider_datasets AS scoped_pair\n"
    "        WHERE scoped_pair.root_kind = root.kind\n"
    "          AND scoped_pair.root_id = root.id\n"
    "          AND scoped_pair.provider = :snapshot_provider\n"
    "          AND scoped_pair.dataset_key = :snapshot_dataset_key\n"
    "    )\n)",
    1,
)
_PIPELINE_ROOT_CTES_SCOPED_SQL: Final[str] = (
    PIPELINE_LINEAGE_CTES_SQL + ",\n" + _PIPELINE_ROOT_BODY_SCOPED_SQL
)

_SCOPED_COMPONENT_SOURCE_BODY_SQL: Final[str] = """
scoped_jobs AS (
    SELECT job.*
    FROM scoped_job_seeds AS seed
    CROSS JOIN LATERAL (
        SELECT
            selected.job_id,
            selected.kind,
            selected.load_batch_id,
            selected.parent_job_id,
            selected.status,
            selected.progress,
            selected.current_stage,
            selected.error_message,
            selected.dagster_run_id,
            selected.provider,
            selected.dataset_key,
            selected.trigger_kind,
            selected.operation_registry_version,
            selected.dagster_run_status,
            selected.started_at,
            selected.finished_at,
            selected.created_at
        FROM ops.import_jobs AS selected
        WHERE selected.job_id = seed.job_id
          AND selected.quarantined_at IS NULL
        OFFSET 0
    ) AS job

    UNION

    SELECT related.*
    FROM scoped_jobs AS current_job
    CROSS JOIN LATERAL (
        (
            SELECT
                parent.job_id,
                parent.kind,
                parent.load_batch_id,
                parent.parent_job_id,
                parent.status,
                parent.progress,
                parent.current_stage,
                parent.error_message,
                parent.dagster_run_id,
                parent.provider,
                parent.dataset_key,
                parent.trigger_kind,
                parent.operation_registry_version,
                parent.dagster_run_status,
                parent.started_at,
                parent.finished_at,
                parent.created_at
            FROM ops.import_jobs AS parent
            WHERE parent.job_id = current_job.parent_job_id
              AND parent.quarantined_at IS NULL
            OFFSET 0
        )

        UNION ALL

        (
            SELECT
                child.job_id,
                child.kind,
                child.load_batch_id,
                child.parent_job_id,
                child.status,
                child.progress,
                child.current_stage,
                child.error_message,
                child.dagster_run_id,
                child.provider,
                child.dataset_key,
                child.trigger_kind,
                child.operation_registry_version,
                child.dagster_run_status,
                child.started_at,
                child.finished_at,
                child.created_at
            FROM ops.import_jobs AS child
            WHERE child.parent_job_id = current_job.job_id
              AND child.quarantined_at IS NULL
            OFFSET 0
        )
    ) AS related
),
pipeline_jobs AS MATERIALIZED (
    SELECT
        job.job_id,
        job.kind,
        job.load_batch_id,
        job.parent_job_id,
        job.status,
        job.progress,
        job.current_stage,
        job.error_message,
        job.dagster_run_id,
        job.provider,
        job.dataset_key,
        job.trigger_kind,
        job.operation_registry_version,
        job.dagster_run_status,
        job.started_at,
        job.finished_at,
        job.created_at
    FROM scoped_jobs AS job
),
pipeline_requests AS MATERIALIZED (
    SELECT
        request.request_id,
        request.scope_type,
        request.scope,
        request.providers,
        request.dataset_keys,
        request.run_mode,
        request.priority,
        identity_job.status,
        request.job_id,
        identity_job.sync_scope AS effective_sync_scope,
        identity_job.dagster_run_id,
        request.operator,
        identity_job.error_message,
        identity_job.started_at,
        identity_job.finished_at,
        request.created_at
    FROM scoped_request_seeds AS seed
    CROSS JOIN LATERAL (
        SELECT selected.*
        FROM ops.feature_update_requests AS selected
        WHERE selected.request_id = seed.request_id
        OFFSET 0
    ) AS request
    JOIN ops.import_jobs AS identity_job
      ON identity_job.job_id = request.job_id
     AND identity_job.quarantined_at IS NULL

    UNION

    SELECT
        request.request_id,
        request.scope_type,
        request.scope,
        request.providers,
        request.dataset_keys,
        request.run_mode,
        request.priority,
        identity_job.status,
        request.job_id,
        identity_job.sync_scope AS effective_sync_scope,
        identity_job.dagster_run_id,
        request.operator,
        identity_job.error_message,
        identity_job.started_at,
        identity_job.finished_at,
        request.created_at
    FROM scoped_jobs AS job
    CROSS JOIN LATERAL (
        SELECT selected.*
        FROM ops.feature_update_requests AS selected
        WHERE selected.job_id = job.job_id
        OFFSET 0
    ) AS request
    JOIN ops.import_jobs AS identity_job
      ON identity_job.job_id = request.job_id
     AND identity_job.quarantined_at IS NULL
)
"""

_IDENTITY_SCOPED_SOURCE_SQL: Final[str] = (
    """
scoped_request_seeds AS MATERIALIZED (
    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    WHERE CAST(:provider AS text) IS NOT NULL
      AND CAST(:dataset_key AS text) IS NULL
      AND request.providers @> ARRAY[CAST(:provider AS text)]

    UNION

    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    WHERE CAST(:provider AS text) IS NULL
      AND CAST(:dataset_key AS text) IS NOT NULL
      AND request.dataset_keys @> ARRAY[CAST(:dataset_key AS text)]
),
scoped_job_seeds AS MATERIALIZED (
    SELECT job.job_id
    FROM ops.import_jobs AS job
    WHERE CAST(:provider AS text) IS NOT NULL
      AND CAST(:dataset_key AS text) IS NOT NULL
      AND job.quarantined_at IS NULL
      AND job.provider = CAST(:provider AS text)
      AND job.dataset_key = CAST(:dataset_key AS text)

    UNION

    SELECT job.job_id
    FROM ops.import_jobs AS job
    WHERE CAST(:provider AS text) IS NOT NULL
      AND CAST(:dataset_key AS text) IS NULL
      AND job.quarantined_at IS NULL
      AND job.provider = CAST(:provider AS text)

    UNION

    SELECT job.job_id
    FROM ops.import_jobs AS job
    WHERE CAST(:provider AS text) IS NULL
      AND CAST(:dataset_key AS text) IS NOT NULL
      AND job.quarantined_at IS NULL
      AND job.dataset_key = CAST(:dataset_key AS text)

    UNION

    SELECT request.job_id
    FROM scoped_request_seeds AS request
    WHERE request.job_id IS NOT NULL
),
"""
    + _SCOPED_COMPONENT_SOURCE_BODY_SQL
)

_MEMBERSHIP_SCOPED_SOURCE_SQL: Final[str] = (
    """
scoped_request_seeds(request_id, job_id) AS MATERIALIZED (
    SELECT NULL::uuid, NULL::uuid
    WHERE FALSE
),
scoped_job_seeds AS MATERIALIZED (
    SELECT job.job_id
    FROM ops.import_jobs AS job
    WHERE CAST(:load_batch_id AS uuid) IS NOT NULL
      AND job.load_batch_id = CAST(:load_batch_id AS uuid)
      AND job.quarantined_at IS NULL

    UNION

    SELECT job.job_id
    FROM ops.import_jobs AS job
    WHERE CAST(:parent_job_id AS uuid) IS NOT NULL
      AND job.parent_job_id = CAST(:parent_job_id AS uuid)
      AND job.quarantined_at IS NULL
),
"""
    + _SCOPED_COMPONENT_SOURCE_BODY_SQL
)

_DETAIL_SCOPED_SOURCE_SQL: Final[str] = (
    """
scoped_request_seeds AS MATERIALIZED (
    SELECT request.request_id, request.job_id
    FROM ops.feature_update_requests AS request
    WHERE CAST(:root_kind AS text) = 'update_request'
      AND request.request_id = CAST(:root_id AS uuid)
),
scoped_job_seeds AS MATERIALIZED (
    SELECT job.job_id
    FROM ops.import_jobs AS job
    WHERE CAST(:root_kind AS text) = 'import_job'
      AND job.job_id = CAST(:root_id AS uuid)
      AND job.quarantined_at IS NULL

    UNION

    SELECT request.job_id
    FROM scoped_request_seeds AS request
    WHERE request.job_id IS NOT NULL
),
"""
    + _SCOPED_COMPONENT_SOURCE_BODY_SQL
)

_LIST_EXECUTIONS_BODY_SQL: Final[str] = """
filtered_roots AS (
    SELECT root.*
    FROM roots_with_identity AS root
    WHERE (CAST(:kind AS text) IS NULL OR root.kind = CAST(:kind AS text))
      AND (CAST(:status AS text) IS NULL OR root.status = CAST(:status AS text))
      AND (
        (CAST(:provider AS text) IS NULL AND CAST(:dataset_key AS text) IS NULL)
        OR (
          CAST(:provider AS text) IS NOT NULL
          AND CAST(:dataset_key AS text) IS NOT NULL
          AND EXISTS (
            SELECT 1
            FROM canonical_provider_datasets AS pair
            WHERE pair.root_kind = root.kind
              AND pair.root_id = root.id
              AND pair.provider = CAST(:provider AS text)
              AND pair.dataset_key = CAST(:dataset_key AS text)
              AND (
                NOT CAST(:filter_sync_scopes AS boolean)
                OR pair.sync_scope = ANY(CAST(:sync_scopes AS text[]))
                OR (
                  CAST(:include_unscoped_scope AS boolean)
                  AND pair.sync_scope IS NULL
                )
              )
          )
        )
        OR (
          CAST(:provider AS text) IS NOT NULL
          AND CAST(:dataset_key AS text) IS NULL
          AND (
            CAST(:provider AS text) = ANY(root.providers)
            OR EXISTS (
              SELECT 1
              FROM canonical_provider_datasets AS pair
              WHERE pair.root_kind = root.kind
                AND pair.root_id = root.id
                AND pair.provider = CAST(:provider AS text)
            )
          )
        )
        OR (
          CAST(:provider AS text) IS NULL
          AND CAST(:dataset_key AS text) IS NOT NULL
          AND (
            CAST(:dataset_key AS text) = ANY(root.dataset_keys)
            OR EXISTS (
              SELECT 1
              FROM canonical_provider_datasets AS pair
              WHERE pair.root_kind = root.kind
                AND pair.root_id = root.id
                AND pair.dataset_key = CAST(:dataset_key AS text)
            )
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
        CAST(:load_batch_id AS uuid) IS NULL
        OR EXISTS (
          SELECT 1
          FROM root_job_members AS member
          WHERE member.root_kind = root.kind
            AND member.root_id = root.id
            AND member.load_batch_id = CAST(:load_batch_id AS uuid)
        )
      )
      AND (
        CAST(:parent_job_id AS uuid) IS NULL
        OR EXISTS (
          SELECT 1
          FROM root_job_members AS member
          WHERE member.root_kind = root.kind
            AND member.root_id = root.id
            AND member.parent_job_id = CAST(:parent_job_id AS uuid)
        )
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
    page.effective_providers AS providers,
    page.effective_dataset_keys AS dataset_keys,
    page.provider_datasets,
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
    page.dagster_run_status,
    page.trigger_kind,
    page.operation_registry_version,
    page.requested_job_id,
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
    page.projected_dagster_run_status,
    page.projected_trigger_kind,
    page.projected_operation_registry_version,
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

_LIST_EXECUTIONS_SQL: Final[str] = (
    "WITH RECURSIVE\n"
    + _IDENTITY_SCOPED_SOURCE_SQL
    + ",\n"
    + PIPELINE_LINEAGE_BODY_SQL
    + ",\n"
    + _PIPELINE_ROOT_BODY_SQL
    + ",\n"
    + _LIST_EXECUTIONS_BODY_SQL
)

_LIST_MEMBERSHIP_EXECUTIONS_SQL: Final[str] = (
    "WITH RECURSIVE\n"
    + _MEMBERSHIP_SCOPED_SOURCE_SQL
    + ",\n"
    + PIPELINE_LINEAGE_BODY_SQL
    + ",\n"
    + _PIPELINE_ROOT_BODY_SQL
    + ",\n"
    + _LIST_EXECUTIONS_BODY_SQL
)

_LIST_ALL_EXECUTIONS_SQL: Final[str] = (
    "WITH RECURSIVE\n" + _PIPELINE_ROOT_CTES_SQL + ",\n" + _LIST_EXECUTIONS_BODY_SQL
)

_STATUS_COUNTS_SQL: Final[str] = (
    "WITH RECURSIVE\n"
    + _PIPELINE_ROOT_CTES_SQL
    + """,
status_counts AS (
    SELECT status, COUNT(*)::integer AS n
    FROM all_roots
    GROUP BY status
)
SELECT
    COALESCE(jsonb_object_agg(status, n), '{}'::jsonb) AS operations_by_status,
    COALESCE(SUM(n) FILTER (WHERE status IN ('queued', 'running')), 0)::integer
        AS active_operations,
    (
        SELECT COUNT(*)::integer
        FROM all_roots
        WHERE status = 'failed'
          AND COALESCE(finished_at, created_at) >= now() - INTERVAL '24 hours'
    ) AS failed_operations_24h
FROM status_counts
"""
)

_DATASET_EXECUTION_RESULT_SQL: Final[str] = """
SELECT
    page.kind, page.id, page.status, page.created_at,
    page.effective_providers AS providers,
    page.effective_dataset_keys AS dataset_keys,
    page.provider_datasets,
    page.progress, page.current_stage, page.scope_type, page.priority,
    page.run_mode, page.operator, page.error_message,
    page.started_at, page.finished_at,
    page.dagster_run_id, page.dagster_run_status, page.trigger_kind,
    page.operation_registry_version, page.requested_job_id,
    page.linked_job_count,
    page.projected_job_id, page.projected_job_kind, page.projected_status,
    page.projected_progress, page.projected_current_stage,
    page.projected_error_message, page.projected_created_at,
    page.projected_started_at, page.projected_finished_at,
    page.projected_dagster_run_id, page.projected_dagster_run_status,
    page.projected_trigger_kind, page.projected_operation_registry_version,
    page.projected_load_batch_id, page.projected_parent_job_id,
    page.projected_depth,
    page.selected_provider, page.selected_dataset_key, page.selected_sync_scope,
    page.selected_operation_member_id, page.selected_pair_status,
    page.selected_is_active,
    cancellation.cancellation_id,
    cancellation.cancellation_status,
    cancellation.cancellation_requested_at,
    cancellation.cancellation_requested_by,
    cancellation.cancellation_reason,
    cancellation.cancellation_retryable,
    cancellation.cancellation_unresolved_member_count
FROM ranked_dataset_roots AS page
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
    WHERE attempt.root_kind = page.kind AND attempt.root_id = page.id
    ORDER BY
        (attempt.status = 'in_progress') DESC,
        attempt.requested_at DESC,
        attempt.cancellation_id DESC
    LIMIT 1
) AS cancellation ON true
WHERE page.dataset_rank = 1
ORDER BY
    page.selected_provider,
    page.selected_dataset_key,
    page.selected_sync_scope NULLS FIRST,
    page.selected_is_active
"""

_LIST_LATEST_DATASET_EXECUTIONS_SQL: Final[str] = (
    "WITH RECURSIVE\n"
    + _PIPELINE_ROOT_CTES_SQL
    + """,
ranked_dataset_roots AS (
    SELECT
        root.*,
        pair.provider AS selected_provider,
        pair.dataset_key AS selected_dataset_key,
        pair.sync_scope AS selected_sync_scope,
        pair.operation_member_id AS selected_operation_member_id,
        pair.status AS selected_pair_status,
        pair.status IN ('queued', 'running') AS selected_is_active,
        ROW_NUMBER() OVER (
            PARTITION BY pair.provider, pair.dataset_key, pair.sync_scope
            ORDER BY root.created_at DESC, root.id DESC, root.kind DESC
        ) AS dataset_rank
    FROM roots_with_identity AS root
    JOIN canonical_provider_datasets AS pair
      ON pair.root_kind = root.kind AND pair.root_id = root.id
)
"""
    + _DATASET_EXECUTION_RESULT_SQL
)

_LIST_DATASET_EXECUTION_SNAPSHOTS_SQL: Final[str] = (
    "WITH RECURSIVE\n"
    + _PIPELINE_ROOT_CTES_SQL
    + """,
ranked_dataset_roots AS (
    SELECT
        root.*,
        pair.provider AS selected_provider,
        pair.dataset_key AS selected_dataset_key,
        pair.sync_scope AS selected_sync_scope,
        pair.operation_member_id AS selected_operation_member_id,
        pair.status AS selected_pair_status,
        pair.status IN ('queued', 'running') AS selected_is_active,
        ROW_NUMBER() OVER (
            PARTITION BY
                pair.provider,
                pair.dataset_key,
                pair.sync_scope,
                (pair.status IN ('queued', 'running'))
            ORDER BY root.created_at DESC, root.id DESC, root.kind DESC
        ) AS dataset_rank
    FROM roots_with_identity AS root
    JOIN canonical_provider_datasets AS pair
      ON pair.root_kind = root.kind AND pair.root_id = root.id
)
"""
    + _DATASET_EXECUTION_RESULT_SQL
)

# ``_LIST_DATASET_EXECUTION_SNAPSHOTS_SQL``의 scoped 변형. scoped root CTE와
# 대상 (provider, dataset_key)로 좁힌 ranked_dataset_roots를 사용해 동일한
# per-scope 최신 종료/활성 실행 결과를 만든다(단, 대상 dataset만).
_LIST_DATASET_EXECUTION_SNAPSHOTS_SCOPED_SQL: Final[str] = (
    "WITH RECURSIVE\n"
    + _PIPELINE_ROOT_CTES_SCOPED_SQL
    + """,
ranked_dataset_roots AS (
    SELECT
        root.*,
        pair.provider AS selected_provider,
        pair.dataset_key AS selected_dataset_key,
        pair.sync_scope AS selected_sync_scope,
        pair.operation_member_id AS selected_operation_member_id,
        pair.status AS selected_pair_status,
        pair.status IN ('queued', 'running') AS selected_is_active,
        ROW_NUMBER() OVER (
            PARTITION BY
                pair.provider,
                pair.dataset_key,
                pair.sync_scope,
                (pair.status IN ('queued', 'running'))
            ORDER BY root.created_at DESC, root.id DESC, root.kind DESC
        ) AS dataset_rank
    FROM roots_with_identity AS root
    JOIN canonical_provider_datasets AS pair
      ON pair.root_kind = root.kind AND pair.root_id = root.id
    WHERE pair.provider = :snapshot_provider
      AND pair.dataset_key = :snapshot_dataset_key
)
"""
    + _DATASET_EXECUTION_RESULT_SQL
)

_GET_EXECUTION_SQL: Final[str] = (
    "WITH RECURSIVE\n"
    + _DETAIL_SCOPED_SOURCE_SQL
    + ",\n"
    + PIPELINE_LINEAGE_BODY_SQL
    + ",\n"
    + _PIPELINE_ROOT_BODY_SQL
    + """,
matched_root AS (
    SELECT root.*
    FROM roots_with_identity AS root
    WHERE (
        CAST(:root_kind AS text) = 'update_request'
        AND root.kind = 'update_request'
        AND root.id = CAST(:root_id AS uuid)
      ) OR (
        CAST(:root_kind AS text) = 'import_job'
        AND (
          (root.kind = 'import_job' AND root.id = CAST(:root_id AS uuid))
          OR EXISTS (
            SELECT 1
            FROM root_job_members AS member
            WHERE member.root_kind = root.kind
              AND member.root_id = root.id
              AND member.job_id = CAST(:root_id AS uuid)
          )
        )
      )
    ORDER BY root.created_at DESC, root.id DESC, root.kind DESC
    LIMIT 1
)
SELECT
    root.kind, root.id, root.status, root.created_at,
    root.effective_providers AS providers,
    root.effective_dataset_keys AS dataset_keys,
    root.provider_datasets,
    root.progress, root.current_stage, root.scope_type, root.priority,
    root.run_mode, root.operator, root.error_message,
    root.started_at, root.finished_at,
    root.dagster_run_id, root.dagster_run_status, root.trigger_kind,
    root.operation_registry_version, root.requested_job_id,
    root.linked_job_count,
    root.projected_job_id, root.projected_job_kind, root.projected_status,
    root.projected_progress, root.projected_current_stage,
    root.projected_error_message, root.projected_created_at,
    root.projected_started_at, root.projected_finished_at,
    root.projected_dagster_run_id, root.projected_dagster_run_status,
    root.projected_trigger_kind, root.projected_operation_registry_version,
    root.projected_load_batch_id, root.projected_parent_job_id,
    root.projected_depth,
    cancellation.cancellation_id,
    cancellation.cancellation_status,
    cancellation.cancellation_requested_at,
    cancellation.cancellation_requested_by,
    cancellation.cancellation_reason,
    cancellation.cancellation_retryable,
    cancellation.cancellation_unresolved_member_count
FROM matched_root AS root
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
    WHERE attempt.root_kind = root.kind AND attempt.root_id = root.id
    ORDER BY
        (attempt.status = 'in_progress') DESC,
        attempt.requested_at DESC,
        attempt.cancellation_id DESC
    LIMIT 1
) AS cancellation ON true
"""
)


def _row_to_execution(row: Any) -> PipelineExecution:
    provider_datasets = tuple(
        PipelineProviderDatasetIdentity(
            provider=str(item["provider"]),
            dataset_key=str(item["dataset_key"]),
            sync_scope=(str(item["sync_scope"]) if item.get("sync_scope") is not None else None),
            operation_member_id=str(item["operation_member_id"]),
            status=str(item["status"]),
        )
        for item in _json_list(row.provider_datasets)
    )
    if row.projected_job_id is None:
        raise RuntimeError("canonical pipeline root must have a projected job")
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
        dagster_run_status=row.projected_dagster_run_status,
        trigger_kind=row.projected_trigger_kind,
        operation_registry_version=row.projected_operation_registry_version,
        load_batch_id=(
            str(row.projected_load_batch_id) if row.projected_load_batch_id is not None else None
        ),
        parent_job_id=(
            str(row.projected_parent_job_id) if row.projected_parent_job_id is not None else None
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
            unresolved_member_count=int(row.cancellation_unresolved_member_count),
        )
    return PipelineExecution(
        kind=str(row.kind),
        id=str(row.id),
        status=str(row.status),
        created_at=row.created_at,
        providers=tuple(str(value) for value in row.providers),
        dataset_keys=tuple(str(value) for value in row.dataset_keys),
        provider_datasets=provider_datasets,
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
        dagster_run_status=row.dagster_run_status,
        trigger_kind=row.trigger_kind,
        operation_registry_version=row.operation_registry_version,
        requested_job_id=(str(row.requested_job_id) if row.requested_job_id is not None else None),
        linked_job_count=int(row.linked_job_count),
        projected_job=projected_job,
        cancellation=cancellation,
    )


async def get_pipeline_execution(
    session: AsyncSession,
    *,
    kind: str,
    execution_id: str,
) -> PipelineExecution | None:
    """root id 또는 import member id에서 canonical root projection을 찾는다."""
    if kind not in PIPELINE_EXECUTION_KINDS:
        raise ValueError(f"kind must be one of {sorted(PIPELINE_EXECUTION_KINDS)}, got {kind!r}")
    try:
        root_id = str(UUID(execution_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("execution_id must be a UUID") from exc
    row = (
        await session.execute(
            text(_GET_EXECUTION_SQL),
            {"root_kind": kind, "root_id": root_id},
        )
    ).one_or_none()
    return _row_to_execution(row) if row is not None else None


async def list_pipeline_executions(
    session: AsyncSession,
    *,
    kind: str | None = None,
    status: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    dataset_sync_scopes: Collection[str | None] | None = None,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> PipelineExecutionPage:
    """root 실행 목록 — ``(created_at DESC, id DESC, kind DESC)`` cursor."""
    if kind is not None and kind not in PIPELINE_EXECUTION_KINDS:
        raise ValueError(f"kind must be one of {sorted(PIPELINE_EXECUTION_KINDS)}, got {kind!r}")
    if dataset_sync_scopes is not None and (provider is None or dataset_key is None):
        raise ValueError("dataset_sync_scopes requires both provider and dataset_key")
    try:
        normalized_load_batch_id = str(UUID(load_batch_id)) if load_batch_id is not None else None
    except (TypeError, ValueError) as exc:
        raise ValueError("load_batch_id must be a UUID") from exc
    try:
        normalized_parent_job_id = str(UUID(parent_job_id)) if parent_job_id is not None else None
    except (TypeError, ValueError) as exc:
        raise ValueError("parent_job_id must be a UUID") from exc
    sync_scopes = tuple(
        dict.fromkeys(
            parse_canonical_sync_scope(scope).value
            for scope in (dataset_sync_scopes or ())
            if scope is not None
        )
    )
    include_unscoped_scope = bool(
        dataset_sync_scopes is not None and None in dataset_sync_scopes
    )
    filter_sync_scopes = dataset_sync_scopes is not None
    page_size = _limit(limit)
    filter_fingerprint = _filter_fingerprint(
        kind=kind,
        status=status,
        provider=provider,
        dataset_key=dataset_key,
        sync_scopes=sync_scopes,
        include_unscoped_scope=include_unscoped_scope,
        filter_sync_scopes=filter_sync_scopes,
        load_batch_id=normalized_load_batch_id,
        parent_job_id=normalized_parent_job_id,
        created_from=created_from,
        created_to=created_to,
    )
    cursor_created_at, cursor_id, cursor_item_kind = _decode_cursor(
        cursor,
        filter_fingerprint=filter_fingerprint,
    )
    if normalized_load_batch_id is not None or normalized_parent_job_id is not None:
        query = _LIST_MEMBERSHIP_EXECUTIONS_SQL
    elif provider is None and dataset_key is None:
        query = _LIST_ALL_EXECUTIONS_SQL
    else:
        query = _LIST_EXECUTIONS_SQL
    rows = (
        await session.execute(
            text(query),
            {
                "kind": kind,
                "status": status,
                "provider": provider,
                "dataset_key": dataset_key,
                "filter_sync_scopes": filter_sync_scopes,
                "sync_scopes": list(sync_scopes),
                "include_unscoped_scope": include_unscoped_scope,
                "load_batch_id": normalized_load_batch_id,
                "parent_job_id": normalized_parent_job_id,
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
            filter_fingerprint=filter_fingerprint,
        )
        if len(rows) > page_size and items
        else None
    )
    return PipelineExecutionPage(items=items, next_cursor=next_cursor)


async def get_pipeline_status_counts(session: AsyncSession) -> PipelineStatusCounts:
    """overview 상태 스트립용 canonical root 집계."""
    row = (await session.execute(text(_STATUS_COUNTS_SQL))).one()
    return PipelineStatusCounts(
        operations_by_status={
            str(k): int(v) for k, v in _json_dict(row.operations_by_status).items()
        },
        active_operations=int(row.active_operations),
        failed_operations_24h=int(row.failed_operations_24h),
    )


async def list_latest_dataset_pipeline_executions(
    session: AsyncSession,
) -> tuple[PipelineDatasetLatestExecution, ...]:
    """모든 exact pair의 최신 canonical root를 단일 batch query로 반환한다."""
    rows = (await session.execute(text(_LIST_LATEST_DATASET_EXECUTIONS_SQL))).all()
    return tuple(_row_to_dataset_execution(row) for row in rows)


def _row_to_dataset_execution(row: Any) -> PipelineDatasetLatestExecution:
    return PipelineDatasetLatestExecution(
        provider=str(row.selected_provider),
        dataset_key=str(row.selected_dataset_key),
        sync_scope=(
            str(row.selected_sync_scope) if row.selected_sync_scope is not None else None
        ),
        execution=_row_to_execution(row),
        operation_member_id=str(row.selected_operation_member_id),
        pair_status=str(row.selected_pair_status),
    )


def _group_dataset_execution_snapshot_rows(
    rows: Collection[Any],
) -> tuple[PipelineDatasetExecutionSnapshot, ...]:
    """dataset execution snapshot row를 (provider, dataset_key, sync_scope)별
    최신 종료/활성 실행 쌍으로 묶는다. unscoped·scoped 쿼리가 공유한다."""
    grouped: dict[
        tuple[str, str, str | None],
        dict[bool, PipelineDatasetLatestExecution],
    ] = {}
    for row in rows:
        item = _row_to_dataset_execution(row)
        key = (item.provider, item.dataset_key, item.sync_scope)
        is_active = bool(row.selected_is_active)
        if is_active in grouped.setdefault(key, {}):
            raise RuntimeError("dataset execution snapshot returned duplicate status groups")
        grouped[key][is_active] = item
    return tuple(
        PipelineDatasetExecutionSnapshot(
            provider=provider,
            dataset_key=dataset_key,
            sync_scope=sync_scope,
            latest_terminal=items.get(False),
            active=items.get(True),
        )
        for (provider, dataset_key, sync_scope), items in grouped.items()
    )


async def list_dataset_pipeline_execution_snapshots(
    session: AsyncSession,
) -> tuple[PipelineDatasetExecutionSnapshot, ...]:
    """exact scope별 최신 종료 실행과 활성 실행을 동일 SQL snapshot으로 반환한다."""
    rows = (await session.execute(text(_LIST_DATASET_EXECUTION_SNAPSHOTS_SQL))).all()
    return _group_dataset_execution_snapshot_rows(rows)


async def list_dataset_pipeline_execution_snapshots_scoped(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
) -> tuple[PipelineDatasetExecutionSnapshot, ...]:
    """단일 (provider, dataset_key)로 좁힌 snapshot.

    ``load_dataset_detail`` 전용. unscoped 버전은 roots_with_identity per-root
    상관 서브쿼리를 전체 파이프라인 히스토리에 대해 계산해 누적 실행 이력에
    비례하는 O(roots^2) 비용(+높은 plan cost로 인한 JIT)을 낸다. 이 변형은 대상
    dataset의 root로만 범위를 좁혀 동일한 per-scope 결과를 만든다.

    또한 이 쿼리는 plan cost가 높아 PostgreSQL JIT가 트리거되는데, JIT 컴파일
    자체가 실제 실행(수백 ms)의 몇 배(수 초)에 달해 순손해다. 트랜잭션 범위로만
    (``SET LOCAL`` — 트랜잭션 종료 시 자동 복원) JIT를 꺼 순수 실행 비용만 남긴다.
    detail 트랜잭션의 후속 쿼리들은 모두 bounded여서 JIT-off가 무해하다.
    """
    await session.execute(text("SET LOCAL jit = off"))
    rows = (
        await session.execute(
            text(_LIST_DATASET_EXECUTION_SNAPSHOTS_SCOPED_SQL),
            {
                "snapshot_provider": provider,
                "snapshot_dataset_key": dataset_key,
            },
        )
    ).all()
    return _group_dataset_execution_snapshot_rows(rows)

"""T-200 load batch DAG + consistency gate orchestration.

본 모듈은 Dagster에 의존하지 않고 ``ops.import_jobs``만 사용해 full-load batch의
root/child/gate/mv-refresh 추적을 기록한다. 실제 provider/offline 적재는 기존 runner가
만든 import job을 ``child_job_ids``로 넘기고, 이 모듈은 child 완료 여부와 정합성 게이트를
검증한다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID, uuid4

from sqlalchemy import text

from krtour.map.infra.consistency import (
    DEDUP_PENDING_WARN_THRESHOLD,
    ConsistencyReport,
    run_consistency_checks,
)
from krtour.map.infra.jobs_repo import (
    ImportJob,
    attach_import_jobs_to_batch,
    finish_import_job,
    list_import_jobs_by_ids,
    start_import_job,
    update_import_job_payload,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "BatchDagRunResult",
    "MaterializedViewRefreshResult",
    "run_batch_dag_consistency_gate",
]

BATCH_ROOT_JOB_KIND: Final[str] = "full_load_batch"
CONSISTENCY_GATE_JOB_KIND: Final[str] = "consistency_check"
MV_REFRESH_JOB_KIND: Final[str] = "mv_refresh"
_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MV_REFRESH_STRATEGIES: Final[frozenset[str]] = frozenset(
    {"swap", "refresh_concurrently", "concurrently", "refresh", "blocking", "none"}
)


@dataclass(frozen=True)
class MaterializedViewRefreshResult:
    """T-200 ``mv_refresh`` 단계 결과."""

    view_name: str
    strategy: str
    state: str
    error_message: str | None = None

    def as_metadata(self) -> dict[str, object]:
        """Dagster/import job payload에 넣을 dict."""
        return {
            "view_name": self.view_name,
            "strategy": self.strategy,
            "state": self.state,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class BatchDagRunResult:
    """Batch DAG gate 실행 결과."""

    load_batch_id: str
    state: str
    root_job: ImportJob | None = None
    child_jobs: tuple[ImportJob, ...] = ()
    consistency_job: ImportJob | None = None
    mv_refresh_job: ImportJob | None = None
    consistency_report: ConsistencyReport | None = None
    mv_refreshes: tuple[MaterializedViewRefreshResult, ...] = ()
    blocked_by_gate: bool = False
    plan_only: bool = False
    missing_child_job_ids: tuple[str, ...] = ()
    error_message: str | None = None

    def as_metadata(self) -> dict[str, object]:
        """Dagster metadata와 ``import_jobs.payload``에 공통으로 쓰는 summary."""
        return {
            "load_batch_id": self.load_batch_id,
            "state": self.state,
            "plan_only": self.plan_only,
            "root_job_id": self.root_job.job_id if self.root_job is not None else None,
            "child_job_count": len(self.child_jobs),
            "child_jobs_done": sum(
                1 for job in self.child_jobs if job.status == "done"
            ),
            "missing_child_job_ids": list(self.missing_child_job_ids),
            "consistency_job_id": (
                self.consistency_job.job_id if self.consistency_job is not None else None
            ),
            "consistency_severity_max": (
                self.consistency_report.severity_max
                if self.consistency_report is not None
                else None
            ),
            "consistency_total_violations": (
                int(self.consistency_report.summary.get("total_violations", 0))
                if self.consistency_report is not None
                else None
            ),
            "mv_refresh_job_id": (
                self.mv_refresh_job.job_id if self.mv_refresh_job is not None else None
            ),
            "mv_refresh_count": len(self.mv_refreshes),
            "mv_refreshes": [item.as_metadata() for item in self.mv_refreshes],
            "blocked_by_gate": self.blocked_by_gate,
            "error_message": self.error_message,
        }


async def run_batch_dag_consistency_gate(
    session: AsyncSession,
    *,
    child_job_ids: Sequence[str] = (),
    load_batch_id: str | None = None,
    root_kind: str = BATCH_ROOT_JOB_KIND,
    root_payload: Mapping[str, Any] | None = None,
    dagster_run_id: str | None = None,
    plan_only: bool = False,
    consistency_persist: bool = True,
    sample_limit: int = 20,
    dedup_pending_threshold: int = DEDUP_PENDING_WARN_THRESHOLD,
    materialized_views: Sequence[str] = (),
    mv_refresh_strategy: str = "swap",
) -> BatchDagRunResult:
    """기존 child import job을 batch로 묶고 consistency gate를 실행한다.

    ``child_job_ids``의 모든 job이 ``done``이어야 gate가 진행된다. 정합성 리포트의
    ``severity_max``가 ``ERROR``이면 ``mv_refresh``를 실행하지 않고 root/gate job을
    ``failed``로 닫는다.
    """
    normalized_batch_id = _normalize_uuid(load_batch_id or str(uuid4()))
    normalized_child_ids = _normalize_uuid_list(child_job_ids)
    strategy = _normalize_mv_refresh_strategy(mv_refresh_strategy)
    views = tuple(str(view) for view in materialized_views if str(view))

    if plan_only:
        child_jobs = await list_import_jobs_by_ids(session, normalized_child_ids)
        return BatchDagRunResult(
            load_batch_id=normalized_batch_id,
            state="planned",
            child_jobs=_order_jobs(child_jobs, normalized_child_ids),
            plan_only=True,
            missing_child_job_ids=_missing_child_ids(child_jobs, normalized_child_ids),
        )

    payload = {
        **dict(root_payload or {}),
        "load_batch_id": normalized_batch_id,
        "child_job_ids": list(normalized_child_ids),
        "dagster_run_id": dagster_run_id,
        "materialized_views": list(views),
        "mv_refresh_strategy": strategy,
    }
    root = await start_import_job(
        session,
        kind=root_kind,
        payload=payload,
        load_batch_id=normalized_batch_id,
    )

    child_jobs = await attach_import_jobs_to_batch(
        session,
        normalized_child_ids,
        load_batch_id=normalized_batch_id,
        parent_job_id=root.job_id,
    )
    child_jobs = _order_jobs(child_jobs, normalized_child_ids)
    missing = _missing_child_ids(child_jobs, normalized_child_ids)
    child_error = _child_error_message(child_jobs, missing)
    if child_error is not None:
        result = BatchDagRunResult(
            load_batch_id=normalized_batch_id,
            state="failed",
            root_job=root,
            child_jobs=child_jobs,
            missing_child_job_ids=missing,
            error_message=child_error,
        )
        await update_import_job_payload(
            session, root.job_id, payload={**payload, **result.as_metadata()}
        )
        root = await finish_import_job(
            session, root.job_id, status="failed", error_message=child_error
        ) or root
        return BatchDagRunResult(
            load_batch_id=normalized_batch_id,
            state="failed",
            root_job=root,
            child_jobs=child_jobs,
            missing_child_job_ids=missing,
            error_message=child_error,
        )

    consistency_job = await start_import_job(
        session,
        kind=CONSISTENCY_GATE_JOB_KIND,
        payload={
            "load_batch_id": normalized_batch_id,
            "persist": consistency_persist,
            "sample_limit": sample_limit,
            "dedup_pending_threshold": dedup_pending_threshold,
        },
        load_batch_id=normalized_batch_id,
        parent_job_id=root.job_id,
    )
    try:
        report = await run_consistency_checks(
            session,
            batch_id=normalized_batch_id,
            persist=consistency_persist,
            sample_limit=sample_limit,
            dedup_pending_threshold=dedup_pending_threshold,
        )
    except Exception as exc:  # noqa: BLE001 - gate 실패를 import job에 남긴다.
        message = f"{exc.__class__.__name__}: {exc}"
        consistency_job = await finish_import_job(
            session, consistency_job.job_id, status="failed", error_message=message
        ) or consistency_job
        root = await finish_import_job(
            session, root.job_id, status="failed", error_message=message
        ) or root
        return BatchDagRunResult(
            load_batch_id=normalized_batch_id,
            state="failed",
            root_job=root,
            child_jobs=child_jobs,
            consistency_job=consistency_job,
            error_message=message,
        )

    await update_import_job_payload(
        session,
        consistency_job.job_id,
        payload=_consistency_payload(report),
    )
    if report.severity_max == "ERROR":
        message = "consistency gate blocked mv_refresh: severity_max=ERROR"
        consistency_job = await finish_import_job(
            session, consistency_job.job_id, status="failed", error_message=message
        ) or consistency_job
        root = await finish_import_job(
            session, root.job_id, status="failed", error_message=message
        ) or root
        return BatchDagRunResult(
            load_batch_id=normalized_batch_id,
            state="failed",
            root_job=root,
            child_jobs=child_jobs,
            consistency_job=consistency_job,
            consistency_report=report,
            blocked_by_gate=True,
            error_message=message,
        )

    consistency_job = await finish_import_job(
        session, consistency_job.job_id, status="done"
    ) or consistency_job
    mv_job = await start_import_job(
        session,
        kind=MV_REFRESH_JOB_KIND,
        payload={"materialized_views": list(views), "strategy": strategy},
        load_batch_id=normalized_batch_id,
        parent_job_id=root.job_id,
    )
    try:
        mv_refreshes = await refresh_materialized_views(
            session, views, strategy=strategy
        )
    except Exception as exc:  # noqa: BLE001 - refresh 실패를 batch 실패로 보존
        message = f"{exc.__class__.__name__}: {exc}"
        await update_import_job_payload(
            session,
            mv_job.job_id,
            payload={
                "materialized_views": list(views),
                "strategy": strategy,
                "error_message": message,
            },
        )
        mv_job = await finish_import_job(
            session, mv_job.job_id, status="failed", error_message=message
        ) or mv_job
        root = await finish_import_job(
            session, root.job_id, status="failed", error_message=message
        ) or root
        return BatchDagRunResult(
            load_batch_id=normalized_batch_id,
            state="failed",
            root_job=root,
            child_jobs=child_jobs,
            consistency_job=consistency_job,
            mv_refresh_job=mv_job,
            consistency_report=report,
            error_message=message,
        )

    await update_import_job_payload(
        session,
        mv_job.job_id,
        payload={
            "materialized_views": list(views),
            "strategy": strategy,
            "results": [item.as_metadata() for item in mv_refreshes],
        },
    )
    mv_job = await finish_import_job(session, mv_job.job_id, status="done") or mv_job
    result = BatchDagRunResult(
        load_batch_id=normalized_batch_id,
        state="done",
        root_job=root,
        child_jobs=child_jobs,
        consistency_job=consistency_job,
        mv_refresh_job=mv_job,
        consistency_report=report,
        mv_refreshes=mv_refreshes,
    )
    await update_import_job_payload(
        session, root.job_id, payload={**payload, **result.as_metadata()}
    )
    root = await finish_import_job(session, root.job_id, status="done") or root
    return BatchDagRunResult(
        load_batch_id=normalized_batch_id,
        state="done",
        root_job=root,
        child_jobs=child_jobs,
        consistency_job=consistency_job,
        mv_refresh_job=mv_job,
        consistency_report=report,
        mv_refreshes=mv_refreshes,
    )


async def refresh_materialized_views(
    session: AsyncSession,
    materialized_views: Sequence[str],
    *,
    strategy: str,
) -> tuple[MaterializedViewRefreshResult, ...]:
    """설정된 materialized view를 refresh한다.

    현재 schema에는 운영 MV가 없으므로 빈 목록은 명시적 ``skipped`` 결과로 남긴다.
    ``swap``은 현재 Postgres 구현에서 ``REFRESH MATERIALIZED VIEW CONCURRENTLY``로
    매핑한다. 실제 shadow-table swap이 필요하면 별도 MV 카탈로그 task에서 확장한다.
    """
    normalized_strategy = _normalize_mv_refresh_strategy(strategy)
    views = tuple(str(view) for view in materialized_views if str(view))
    if not views:
        return (
            MaterializedViewRefreshResult(
                view_name="",
                strategy=normalized_strategy,
                state="skipped:no_materialized_views",
            ),
        )
    if normalized_strategy == "none":
        return tuple(
            MaterializedViewRefreshResult(
                view_name=view,
                strategy=normalized_strategy,
                state="skipped:strategy_none",
            )
            for view in views
        )

    results: list[MaterializedViewRefreshResult] = []
    for view in views:
        sql = _refresh_materialized_view_sql(view, strategy=normalized_strategy)
        await session.execute(text(sql))
        results.append(
            MaterializedViewRefreshResult(
                view_name=view,
                strategy=normalized_strategy,
                state="done",
            )
        )
    return tuple(results)


def _normalize_uuid(value: str) -> str:
    return str(UUID(str(value)))


def _normalize_uuid_list(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(_normalize_uuid(value) for value in values)


def _normalize_mv_refresh_strategy(value: str) -> str:
    strategy = str(value)
    if strategy not in _MV_REFRESH_STRATEGIES:
        raise ValueError(
            "mv_refresh_strategy must be one of "
            f"{sorted(_MV_REFRESH_STRATEGIES)}, got {strategy!r}."
        )
    return strategy


def _order_jobs(
    jobs: Sequence[ImportJob],
    job_ids: Sequence[str],
) -> tuple[ImportJob, ...]:
    by_id = {job.job_id: job for job in jobs}
    return tuple(by_id[job_id] for job_id in job_ids if job_id in by_id)


def _missing_child_ids(
    child_jobs: Sequence[ImportJob],
    child_job_ids: Sequence[str],
) -> tuple[str, ...]:
    found = {job.job_id for job in child_jobs}
    return tuple(job_id for job_id in child_job_ids if job_id not in found)


def _child_error_message(
    child_jobs: Sequence[ImportJob],
    missing_child_job_ids: Sequence[str],
) -> str | None:
    if missing_child_job_ids:
        return "missing child import jobs: " + ",".join(missing_child_job_ids)
    not_done = [job for job in child_jobs if job.status != "done"]
    if not_done:
        summary = ",".join(f"{job.job_id}:{job.status}" for job in not_done)
        return "child import jobs are not done: " + summary
    return None


def _consistency_payload(report: ConsistencyReport) -> dict[str, object]:
    return {
        "batch_id": report.batch_id,
        "severity_max": report.severity_max,
        "summary": report.summary,
        "cases": [
            {
                "code": case.code,
                "severity": case.severity,
                "description": case.description,
                "count": case.count,
                "sample_ids": list(case.sample_ids),
            }
            for case in report.cases
        ],
    }


def _refresh_materialized_view_sql(view_name: str, *, strategy: str) -> str:
    quoted = _quote_relation_name(view_name)
    if strategy in {"swap", "refresh_concurrently", "concurrently"}:
        return f"REFRESH MATERIALIZED VIEW CONCURRENTLY {quoted}"
    if strategy in {"refresh", "blocking"}:
        return f"REFRESH MATERIALIZED VIEW {quoted}"
    raise ValueError(f"refresh SQL 없는 strategy: {strategy!r}")


def _quote_relation_name(view_name: str) -> str:
    parts = view_name.split(".")
    if len(parts) != 2 or any(not _IDENTIFIER_RE.fullmatch(part) for part in parts):
        raise ValueError(
            "materialized view name은 schema.view 형식의 SQL identifier여야 함: "
            f"{view_name!r}"
        )
    return ".".join(f'"{part}"' for part in parts)

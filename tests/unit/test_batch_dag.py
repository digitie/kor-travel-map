"""``infra.batch_dag`` 단위 테스트."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

import pytest

from krtour.map.infra import batch_dag
from krtour.map.infra.batch_dag import (
    MaterializedViewRefreshResult,
    refresh_materialized_views,
    run_batch_dag_consistency_gate,
)
from krtour.map.infra.consistency import ConsistencyReport
from krtour.map.infra.jobs_repo import ImportJob

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_BATCH_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_ROOT_ID = "00000000-0000-0000-0000-000000000001"
_CONSISTENCY_ID = "00000000-0000-0000-0000-000000000002"
_MV_ID = "00000000-0000-0000-0000-000000000003"
_CHILD_ID = "10000000-0000-0000-0000-000000000001"


async def test_batch_gate_success_records_mv_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fakes(monkeypatch, severity="WARN", child_state="done")

    result = await run_batch_dag_consistency_gate(
        _session(),
        child_job_ids=[_CHILD_ID],
        load_batch_id=_BATCH_ID,
        root_payload={"source": "unit"},
        materialized_views=["feature.search_mv"],
        mv_refresh_strategy="refresh",
    )

    assert result.state == "done"
    assert result.root_job is not None
    assert result.root_job.state == "done"
    assert result.consistency_report is not None
    assert result.consistency_report.severity_max == "WARN"
    assert result.mv_refresh_job is not None
    assert result.mv_refreshes[0].state == "done"
    assert calls["refresh"] == ["refresh"]
    assert calls["updates"][_ROOT_ID]["source"] == "unit"
    assert calls["updates"][_ROOT_ID]["mv_refresh_count"] == 1


async def test_batch_gate_blocks_mv_refresh_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fakes(monkeypatch, severity="ERROR", child_state="done")

    result = await run_batch_dag_consistency_gate(
        _session(),
        child_job_ids=[_CHILD_ID],
        load_batch_id=_BATCH_ID,
    )

    assert result.state == "failed"
    assert result.blocked_by_gate is True
    assert result.mv_refresh_job is None
    assert calls["refresh"] == []
    assert calls["jobs"][_ROOT_ID].state == "failed"
    assert calls["jobs"][_CONSISTENCY_ID].state == "failed"


async def test_batch_gate_fails_before_consistency_when_child_not_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install_fakes(monkeypatch, severity="OK", child_state="running")

    result = await run_batch_dag_consistency_gate(
        _session(),
        child_job_ids=[_CHILD_ID],
        load_batch_id=_BATCH_ID,
    )

    assert result.state == "failed"
    assert result.consistency_job is None
    assert result.error_message is not None
    assert "not done" in result.error_message
    assert calls["consistency"] == []


async def test_batch_gate_plan_only_reads_children_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_list(_session: object, job_ids: list[str]) -> tuple[ImportJob, ...]:
        return (_job(job_ids[0], "offline_upload_load", state="done"),)

    async def fail_start(*_args: object, **_kwargs: object) -> ImportJob:
        raise AssertionError("plan_only must not create import jobs")

    monkeypatch.setattr(batch_dag, "list_import_jobs_by_ids", fake_list)
    monkeypatch.setattr(batch_dag, "start_import_job", fail_start)

    result = await run_batch_dag_consistency_gate(
        _session(),
        child_job_ids=[_CHILD_ID],
        load_batch_id=_BATCH_ID,
        plan_only=True,
    )

    assert result.state == "planned"
    assert result.plan_only is True
    assert result.child_jobs[0].job_id == _CHILD_ID
    assert result.missing_child_job_ids == ()


async def test_refresh_materialized_views_executes_validated_sql() -> None:
    session = _SqlSession()

    result = await refresh_materialized_views(
        cast("AsyncSession", session),
        ["feature.search_mv"],
        strategy="refresh",
    )

    assert result == (
        MaterializedViewRefreshResult(
            view_name="feature.search_mv",
            strategy="refresh",
            state="done",
        ),
    )
    assert session.sql == ['REFRESH MATERIALIZED VIEW "feature"."search_mv"']


async def test_refresh_materialized_views_skips_empty_list() -> None:
    result = await refresh_materialized_views(_session(), [], strategy="swap")

    assert result[0].state == "skipped:no_materialized_views"


async def test_refresh_materialized_views_rejects_bad_view_name() -> None:
    with pytest.raises(ValueError, match="schema.view"):
        await refresh_materialized_views(
            _session(), ["feature.bad-name"], strategy="swap"
        )


async def test_batch_gate_rejects_bad_strategy() -> None:
    with pytest.raises(ValueError, match="mv_refresh_strategy"):
        await run_batch_dag_consistency_gate(
            _session(),
            load_batch_id=_BATCH_ID,
            mv_refresh_strategy="bad",
        )


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    severity: str,
    child_state: str,
) -> dict[str, Any]:
    calls: dict[str, Any] = {
        "jobs": {},
        "updates": {},
        "consistency": [],
        "refresh": [],
    }

    async def fake_start(
        _session: object,
        *,
        kind: str,
        payload: dict[str, Any] | None = None,
        source_checksum: str | None = None,
        load_batch_id: str | None = None,
        parent_job_id: str | None = None,
    ) -> ImportJob:
        job_id = {
            "full_load_batch": _ROOT_ID,
            "consistency_check": _CONSISTENCY_ID,
            "mv_refresh": _MV_ID,
        }[kind]
        job = _job(
            job_id,
            kind,
            payload=payload,
            state="running",
            source_checksum=source_checksum,
            load_batch_id=load_batch_id,
            parent_job_id=parent_job_id,
        )
        calls["jobs"][job_id] = job
        return job

    async def fake_attach(
        _session: object,
        job_ids: tuple[str, ...],
        *,
        load_batch_id: str,
        parent_job_id: str,
    ) -> tuple[ImportJob, ...]:
        return tuple(
            _job(
                job_id,
                "offline_upload_load",
                state=child_state,
                load_batch_id=load_batch_id,
                parent_job_id=parent_job_id,
            )
            for job_id in job_ids
        )

    async def fake_update(
        _session: object,
        job_id: str,
        *,
        payload: dict[str, Any],
    ) -> ImportJob:
        calls["updates"][job_id] = payload
        job = calls["jobs"][job_id]
        updated = replace(cast(ImportJob, job), payload=payload)
        calls["jobs"][job_id] = updated
        return updated

    async def fake_finish(
        _session: object,
        job_id: str,
        *,
        state: str = "done",
        error_message: str | None = None,
    ) -> ImportJob:
        job = cast(ImportJob, calls["jobs"][job_id])
        finished = replace(
            job,
            state=state,
            progress=100 if state == "done" else job.progress,
            error_message=error_message,
        )
        calls["jobs"][job_id] = finished
        return finished

    async def fake_consistency(_session: object, **kwargs: Any) -> ConsistencyReport:
        calls["consistency"].append(kwargs)
        return ConsistencyReport(
            batch_id=str(kwargs["batch_id"]),
            severity_max=severity,
            cases=[],
            summary={
                "total_violations": 1 if severity == "ERROR" else 0,
                "cases_evaluated": 4,
                "by_code": {},
            },
        )

    async def fake_refresh(
        _session: object,
        materialized_views: tuple[str, ...],
        *,
        strategy: str,
    ) -> tuple[MaterializedViewRefreshResult, ...]:
        calls["refresh"].append(strategy)
        return tuple(
            MaterializedViewRefreshResult(
                view_name=view,
                strategy=strategy,
                state="done",
            )
            for view in materialized_views
        )

    monkeypatch.setattr(batch_dag, "start_import_job", fake_start)
    monkeypatch.setattr(batch_dag, "attach_import_jobs_to_batch", fake_attach)
    monkeypatch.setattr(batch_dag, "update_import_job_payload", fake_update)
    monkeypatch.setattr(batch_dag, "finish_import_job", fake_finish)
    monkeypatch.setattr(batch_dag, "run_consistency_checks", fake_consistency)
    monkeypatch.setattr(batch_dag, "refresh_materialized_views", fake_refresh)
    return calls


def _job(
    job_id: str,
    kind: str,
    *,
    payload: dict[str, Any] | None = None,
    state: str = "running",
    source_checksum: str | None = None,
    load_batch_id: str | None = None,
    parent_job_id: str | None = None,
) -> ImportJob:
    return ImportJob(
        job_id=job_id,
        kind=kind,
        payload=dict(payload or {}),
        state=state,
        progress=100 if state == "done" else 0,
        current_stage=None,
        source_checksum=source_checksum,
        error_message=None,
        load_batch_id=load_batch_id,
        parent_job_id=parent_job_id,
    )


def _session() -> AsyncSession:
    return cast("AsyncSession", object())


class _SqlSession:
    def __init__(self) -> None:
        self.sql: list[str] = []

    async def execute(self, statement: object) -> None:
        self.sql.append(str(statement))

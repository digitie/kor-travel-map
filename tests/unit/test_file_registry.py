"""``file_registry`` 순수 헬퍼 단위 테스트 — DB 없는 매퍼/guard/검증 경로.

DB를 타는 register_file/scan/list 경로는 integration(testcontainers)에서 검증한다.
여기서는 row→dataclass 매핑, hook 무해화 guard, kind 검증만 좁게 커버한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from kortravelmap.infra.file_registry import (
    ManagedFilePage,
    ManagedFileSummary,
    _row_to_event,
    _row_to_file,
    register_file,
    registry_guard,
)

pytestmark = pytest.mark.unit


_NOW = datetime(2026, 7, 4, 12, 0, tzinfo=UTC)


def _file_row(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "file_id": 7,
        "storage_backend": "filesystem",
        "location": "backup_root",
        "path": "e2e-20260704.tar.zst",
        "is_directory": False,
        "kind": "backup",
        "provider": None,
        "dataset_key": None,
        "status": "active",
        "orphan_reason": None,
        "registered_by": "scan",
        "byte_size": 1024,
        "checksum_sha256": None,
        "upload_id": None,
        "origin_import_job_id": None,
        "origin_dagster_run_id": None,
        "downloaded_at": None,
        "last_loaded_at": None,
        "last_seen_at": _NOW,
        "deleted_at": None,
        "meta": {"bucket": "kor-travel-map-backups"},
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_row_to_file_maps_all_columns_and_copies_meta() -> None:
    meta = {"bucket": "b1"}
    managed = _row_to_file(_file_row(meta=meta))

    assert managed.file_id == 7
    assert managed.location == "backup_root"
    assert managed.kind == "backup"
    assert managed.byte_size == 1024
    # meta는 방어적으로 복사한다(원본 mutation이 dataclass에 새지 않게).
    assert managed.meta == {"bucket": "b1"}
    assert managed.meta is not meta


def test_row_to_file_stringifies_uuids_and_handles_none() -> None:
    # UUID 유사 객체는 str()로 정규화, None은 그대로 None.
    with_ids = _row_to_file(
        _file_row(
            upload_id=SimpleNamespace(__str__=lambda self: "uuid-up"),
            origin_import_job_id=None,
            meta=None,
        )
    )
    assert isinstance(with_ids.upload_id, str)
    assert with_ids.origin_import_job_id is None
    # meta=None → 빈 dict.
    assert with_ids.meta == {}


def test_row_to_event_maps_and_defaults_detail() -> None:
    row = SimpleNamespace(
        event_id=3,
        file_id=7,
        event_kind="registered",
        occurred_at=_NOW,
        import_job_id=None,
        dagster_run_id=None,
        actor="api:admin",
        detail=None,
    )
    event = _row_to_event(row)
    assert event.event_id == 3
    assert event.event_kind == "registered"
    assert event.actor == "api:admin"
    assert event.import_job_id is None
    assert event.detail == {}


def test_row_to_event_stringifies_import_job_id() -> None:
    row = SimpleNamespace(
        event_id=4,
        file_id=7,
        event_kind="loaded",
        occurred_at=_NOW,
        import_job_id=SimpleNamespace(__str__=lambda self: "job-uuid"),
        dagster_run_id="run-1",
        actor=None,
        detail={"k": "v"},
    )
    event = _row_to_event(row)
    assert isinstance(event.import_job_id, str)
    assert event.dagster_run_id == "run-1"
    assert event.detail == {"k": "v"}


async def test_registry_guard_passes_through_on_success() -> None:
    entered = False
    async with registry_guard("offline-upload:register"):
        entered = True
    assert entered


async def test_registry_guard_swallows_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # hook 실패는 본작업을 죽이면 안 된다 — 예외를 삼키고 warning만 남긴다.
    with caplog.at_level(logging.WARNING):
        async with registry_guard("backup:register"):
            raise RuntimeError("db exploded")
    assert any("registry hook" in rec.message for rec in caplog.records)


async def test_register_file_rejects_unknown_kind() -> None:
    # kind 검증은 session을 건드리기 전에 실패해야 한다(가짜 session이면 실패 즉시 드러남).
    with pytest.raises(ValueError, match="unknown managed file kind"):
        await register_file(
            object(),  # type: ignore[arg-type]
            storage_backend="filesystem",
            location="backup_root",
            path="x",
            kind="not-a-real-kind",
        )


def test_managed_file_summary_and_page_defaults() -> None:
    summary = ManagedFileSummary()
    assert summary.by_kind == []
    assert summary.by_status == []
    assert summary.by_location == []

    page = ManagedFilePage(items=[], total_count=0)
    assert page.items == []
    assert page.total_count == 0

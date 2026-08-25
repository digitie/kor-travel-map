"""파일 registry reconciliation scan — location 단위 3단계 pass (PR-D §2.2).

절차: ① enumerate(물리 목록) → ② upsert(+orphan rule) → ③ sweep(이번 pass에서
**실제 열거한 location에 한해** 미발견 행 missing 처리). location 밖 sweep 금지가
핵심 정합성 규칙 — 스캐너가 못 훑은 location의 행을 missing으로 만드는 사고
(예: api가 죽어 backup_root를 못 훑은 pass가 백업 전체를 missing 처리)를 막는다.

scanner 소유권(split-brain, docs/architecture/file-registry.md):
- ``backup_root``(+swap env 파일) — **api** 컨테이너만 보인다 → rescan API가 동기 실행.
- ``mois_source``/S3 버킷 — **dagster** 컨테이너가 소유 → dagster scan job.
데이터 backfill은 migration이 아니라 배포 후 첫 scan이 수행한다(§5.1).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from kortravelmap.core.managed_file_states import (
    MANAGED_FILE_LOCATION_BACKUP_ROOT,
    MANAGED_FILE_LOCATION_MOIS_SOURCE,
    MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
)
from kortravelmap.infra import file_registry
from kortravelmap.infra.backup import list_backup_artifacts

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.infra.backup import BackupArtifact
    from kortravelmap.infra.file_store import S3ObjectStore

__all__ = [
    "ScanLocationResult",
    "backfill_offline_upload_rows",
    "parse_extra_roots",
    "scan_backup_root",
    "scan_extra_root",
    "scan_mois_source",
    "scan_s3_location",
]

logger = logging.getLogger(__name__)

_E2E_BACKUP_MODE = "n150-live-e2e-backup-runner"
_E2E_BACKUP_PREFIX = "e2e-"


@dataclass(slots=True)
class ScanLocationResult:
    """location 1개 scan 요약 — rescan API 응답/Dagster run metadata용."""

    location: str
    scanned: int = 0
    registered: int = 0
    orphaned: int = 0
    missing: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "location": self.location,
            "scanned": self.scanned,
            "registered": self.registered,
            "orphaned": self.orphaned,
            "missing": self.missing,
            **({"details": self.details} if self.details else {}),
        }


def parse_extra_roots(raw: str | None) -> list[tuple[str, Path]]:
    """``logical=path[,logical=path]`` 설정 파서 (EXTRA_ROOTS 탈출구)."""

    if not raw:
        return []
    roots: list[tuple[str, Path]] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        logical, _, path_text = part.partition("=")
        logical = logical.strip()
        path_text = path_text.strip()
        if not logical or not path_text:
            logger.warning("file_registry_extra_roots 항목 무시(형식 오류): %r", part)
            continue
        roots.append((logical, Path(path_text)))
    return roots


def _is_e2e_backup(artifact: BackupArtifact) -> bool:
    if artifact.mode == _E2E_BACKUP_MODE:
        return True
    return artifact.backup_id.startswith(_E2E_BACKUP_PREFIX)


def _stat_mois_source(db_path: str) -> tuple[str, int, list[str]] | None:
    """MOIS 소스 DB 본체 stat + sidecar 열거 — blocking, to_thread용."""

    path = Path(db_path)
    if not path.is_file():
        return None
    stat = path.stat()
    sidecars = [
        candidate.name
        for candidate in (
            path.with_name(path.name + suffix)
            for suffix in ("-wal", "-shm", ".synced", ".lock")
        )
        if candidate.exists()
    ]
    return path.name, stat.st_size, sidecars


@dataclass(slots=True)
class _ExtraEntry:
    name: str
    is_dir: bool
    size: int | None
    physical: str


def _enumerate_extra_root(
    root: Path, max_entries: int
) -> tuple[list[_ExtraEntry], bool]:
    """extra root top-level 열거 — blocking, to_thread용."""

    if not root.is_dir():
        return [], False
    entries: list[_ExtraEntry] = []
    truncated = False
    for index, item in enumerate(sorted(root.iterdir())):
        if index >= max_entries:
            truncated = True
            break
        try:
            stat = item.stat()
        except OSError:
            continue
        is_dir = item.is_dir()
        entries.append(
            _ExtraEntry(item.name, is_dir, None if is_dir else stat.st_size, str(item))
        )
    return entries, truncated


async def scan_backup_root(
    session: AsyncSession,
    *,
    backup_root: Path,
    e2e_backup_ttl_days: int,
    actor: str = "scan:api",
    max_entries: int = 5000,
) -> ScanLocationResult:
    """backup_root walk — artifact 등록 + orphan rule + sweep (api 소유 location)."""

    scan_started_at = datetime.now(UTC)
    result = ScanLocationResult(location=MANAGED_FILE_LOCATION_BACKUP_ROOT)
    now = scan_started_at

    artifacts = list_backup_artifacts(backup_root)[:max_entries]
    for artifact in artifacts:
        result.scanned += 1
        managed = await file_registry.register_file(
            session,
            storage_backend="filesystem",
            location=MANAGED_FILE_LOCATION_BACKUP_ROOT,
            path=artifact.backup_id,
            kind="backup",
            is_directory=True,
            registered_by="scan",
            byte_size=artifact.byte_size,
            downloaded_at=artifact.created_at_utc,
            actor=actor,
            meta={
                "manifest_status": artifact.manifest_status,
                "mode": artifact.mode,
                "components": artifact.components,
                "databases": artifact.databases,
                "checksum_count": artifact.checksum_count,
                "physical": {"path": str(artifact.path)},
            },
        )
        result.registered += 1
        # Orphan rule 평가 (docs/architecture/file-registry.md):
        if artifact.manifest_status != "ok":
            # manifest 부재/파싱 실패 — 실패한 백업 시도 잔재.
            if await file_registry.mark_orphan(
                session,
                file_id=managed.file_id,
                reason="manifest_missing",
                actor=actor,
                detail={"manifest_status": artifact.manifest_status},
            ):
                result.orphaned += 1
        elif _is_e2e_backup(artifact):
            created = artifact.created_at_utc
            expired = created is not None and (
                now - created > timedelta(days=e2e_backup_ttl_days)
            )
            if expired and await file_registry.mark_orphan(
                session,
                file_id=managed.file_id,
                reason="e2e_backup_expired",
                actor=actor,
                detail={"ttl_days": e2e_backup_ttl_days, "mode": artifact.mode},
            ):
                result.orphaned += 1

    # 열거를 무사히 마쳤으므로 이 location만 sweep.
    result.missing = await file_registry.sweep_missing(
        session,
        location=MANAGED_FILE_LOCATION_BACKUP_ROOT,
        scan_started_at=scan_started_at,
        actor=actor,
    )
    return result


async def scan_mois_source(
    session: AsyncSession,
    *,
    db_path: str | None,
    actor: str = "scan:dagster",
) -> ScanLocationResult:
    """MOIS 소스 SQLite scan (dagster 소유 location) — 부재 감지가 곧 가치."""

    scan_started_at = datetime.now(UTC)
    result = ScanLocationResult(location=MANAGED_FILE_LOCATION_MOIS_SOURCE)
    probe = await asyncio.to_thread(_stat_mois_source, db_path) if db_path else None
    if db_path and probe is not None:
        name, size, sidecars = probe
        result.scanned += 1
        await file_registry.register_file(
            session,
            storage_backend="filesystem",
            location=MANAGED_FILE_LOCATION_MOIS_SOURCE,
            path=name,
            kind="provider_download",
            # dataset가 없는 filesystem audit owner는 명시적 provider-only 예외다.
            provider_name="mois",
            registered_by="scan",
            byte_size=size,
            actor=actor,
            meta={"physical": {"path": db_path}, "sidecars": sidecars},
        )
        result.registered += 1
    # db_path 미설정이어도 sweep은 수행 — "설정이 사라진" 배포에서 잔존 행을
    # missing으로 만드는 게 옳다(파일을 볼 수 있는 컨테이너는 dagster뿐).
    result.missing = await file_registry.sweep_missing(
        session,
        location=MANAGED_FILE_LOCATION_MOIS_SOURCE,
        scan_started_at=scan_started_at,
        actor=actor,
    )
    return result


_OWNER_UPLOAD_SQL = text(
    """
    SELECT upload_id, provider_dataset_id, byte_size, checksum_sha256
    FROM ops.offline_uploads
    WHERE storage_key = :storage_key
    """
)


async def scan_s3_location(
    session: AsyncSession,
    *,
    store: S3ObjectStore,
    location: str,
    prefix: str,
    actor: str = "scan:dagster",
    max_keys: int = 5000,
) -> ScanLocationResult:
    """S3 버킷 prefix scan — offline_uploads는 zombie(#397) rule을 적용한다."""

    scan_started_at = datetime.now(UTC)
    result = ScanLocationResult(location=location)
    objects = await store.list_objects(prefix=prefix, max_keys=max_keys)
    is_uploads = location == MANAGED_FILE_LOCATION_OFFLINE_UPLOADS
    for obj in objects:
        result.scanned += 1
        owner = None
        if is_uploads:
            owner = (
                await session.execute(
                    _OWNER_UPLOAD_SQL, {"storage_key": obj.object_key}
                )
            ).first()
        managed = await file_registry.register_file(
            session,
            storage_backend="s3",
            location=location,
            path=obj.object_key,
            kind="upload" if is_uploads else "feature_file",
            registered_by="scan",
            provider_dataset_id=(
                int(owner.provider_dataset_id) if owner is not None else None
            ),
            byte_size=obj.byte_size,
            checksum_sha256=(
                owner.checksum_sha256 if owner is not None else None
            ),
            upload_id=str(owner.upload_id) if owner is not None else None,
            actor=actor,
            meta={"physical": {"bucket": store.bucket}, "etag": obj.etag},
        )
        result.registered += 1
        # #397 — 소유 ops.offline_uploads row가 없는 객체 = zombie.
        if (
            is_uploads
            and owner is None
            and await file_registry.mark_orphan(
                session,
                file_id=managed.file_id,
                reason="zombie_object",
                actor=actor,
                detail={"bucket": store.bucket},
            )
        ):
            result.orphaned += 1
    result.missing = await file_registry.sweep_missing(
        session,
        location=location,
        scan_started_at=scan_started_at,
        actor=actor,
    )
    return result


async def scan_extra_root(
    session: AsyncSession,
    *,
    logical: str,
    root: Path,
    actor: str,
    max_entries: int = 5000,
) -> ScanLocationResult:
    """EXTRA_ROOTS 운영자 탈출구 — top-level 항목만 kind='other'로 등록."""

    scan_started_at = datetime.now(UTC)
    result = ScanLocationResult(location=logical)
    entries, truncated = await asyncio.to_thread(
        _enumerate_extra_root, root, max_entries
    )
    if truncated:
        logger.warning(
            "extra root %s 스캔 상한(%d) 도달 — 잔여 항목 생략", logical, max_entries
        )
    for entry in entries:
        result.scanned += 1
        managed = await file_registry.register_file(
            session,
            storage_backend="filesystem",
            location=logical,
            path=entry.name,
            kind="other",
            is_directory=entry.is_dir,
            registered_by="scan",
            byte_size=entry.size,
            actor=actor,
            meta={"physical": {"path": entry.physical}},
        )
        result.registered += 1
        # hook 계보가 없는 발견분 — 운영자 판단 대상으로 표시.
        if await file_registry.mark_orphan(
            session,
            file_id=managed.file_id,
            reason="scan_unregistered",
            actor=actor,
        ):
            result.orphaned += 1
    result.missing = await file_registry.sweep_missing(
        session,
        location=logical,
        scan_started_at=scan_started_at,
        actor=actor,
    )
    return result


async def backfill_offline_upload_rows(
    session: AsyncSession,
    *,
    actor: str,
) -> int:
    """DB-side sweep — registry에 없는 ``ops.offline_uploads`` row 회수(backfill).

    파일시스템/S3 접근이 필요 없어 어느 프로세스에서든 실행 가능하다. hook 도입
    이전에 생성된 업로드 메타데이터를 registry로 끌어온다.
    """

    rows = (
        await session.execute(
            text(
                """
                SELECT u.upload_id, u.provider_dataset_id, u.storage_key,
                       u.byte_size, u.checksum_sha256, u.created_at
                FROM ops.offline_uploads AS u
                WHERE NOT EXISTS (
                    SELECT 1 FROM ops.managed_files AS mf
                    WHERE mf.storage_backend = 's3'
                      AND mf.location = :location
                      AND mf.path = u.storage_key
                )
                """
            ),
            {"location": MANAGED_FILE_LOCATION_OFFLINE_UPLOADS},
        )
    ).all()
    for row in rows:
        await file_registry.register_file(
            session,
            storage_backend="s3",
            location=MANAGED_FILE_LOCATION_OFFLINE_UPLOADS,
            path=row.storage_key,
            kind="upload",
            registered_by="backfill",
            provider_dataset_id=int(row.provider_dataset_id),
            byte_size=row.byte_size,
            checksum_sha256=row.checksum_sha256,
            upload_id=str(row.upload_id),
            downloaded_at=row.created_at,
            actor=actor,
        )
    return len(rows)

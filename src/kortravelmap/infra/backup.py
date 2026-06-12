"""Standalone backup artifact helpers.

Docker backup/restore scripts produce filesystem artifacts under
``data/backups/<backup_id>``. This module only parses and summarizes those
artifacts; executing Docker commands stays in the admin package boundary.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

__all__ = [
    "BackupArtifact",
    "BackupArtifactError",
    "backup_artifact",
    "backup_artifact_path",
    "list_backup_artifacts",
    "validate_backup_id",
]

_BACKUP_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._-]+$")


class BackupArtifactError(ValueError):
    """Backup artifact path or manifest is invalid."""


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    """Filesystem summary for one backup artifact directory."""

    backup_id: str
    path: Path
    manifest_status: str
    created_at_utc: datetime | None
    mode: str | None
    components: dict[str, str]
    databases: dict[str, str]
    object_storage: dict[str, Any]
    byte_size: int
    checksum_count: int


def validate_backup_id(backup_id: str) -> str:
    """Validate and return a path-safe backup id."""
    if not _BACKUP_ID_RE.fullmatch(backup_id):
        raise BackupArtifactError(
            "backup_id는 영문/숫자/점/밑줄/하이픈만 사용할 수 있습니다."
        )
    return backup_id


def backup_artifact_path(root: Path, backup_id: str) -> Path:
    """Return the normalized artifact path below ``root``."""
    safe_id = validate_backup_id(backup_id)
    root_path = root.expanduser().resolve()
    path = (root_path / safe_id).resolve()
    if path.parent != root_path:
        raise BackupArtifactError("backup artifact 경로가 backup root 밖입니다.")
    return path


def _directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def _checksum_count(path: Path) -> int:
    checksums = path / "meta" / "SHA256SUMS"
    if not checksums.is_file():
        return 0
    return sum(1 for line in checksums.read_text(encoding="utf-8").splitlines() if line)


def _parse_created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _load_manifest(path: Path) -> tuple[str, dict[str, Any]]:
    manifest_path = path / "meta" / "manifest.json"
    if not manifest_path.is_file():
        return "missing", {}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "invalid", {}
    if not isinstance(raw, dict):
        return "invalid", {}
    return "ok", raw


def backup_artifact(root: Path, backup_id: str) -> BackupArtifact:
    """Return one backup artifact summary."""
    path = backup_artifact_path(root, backup_id)
    if not path.is_dir():
        raise BackupArtifactError(f"backup artifact가 없습니다: {backup_id}")
    manifest_status, manifest = _load_manifest(path)
    components = manifest.get("components")
    databases = manifest.get("databases")
    object_storage = manifest.get("object_storage")
    return BackupArtifact(
        backup_id=backup_id,
        path=path,
        manifest_status=manifest_status,
        created_at_utc=_parse_created_at(manifest.get("created_at_utc")),
        mode=manifest.get("mode") if isinstance(manifest.get("mode"), str) else None,
        components=dict(components) if isinstance(components, dict) else {},
        databases=dict(databases) if isinstance(databases, dict) else {},
        object_storage=(
            dict(object_storage) if isinstance(object_storage, dict) else {}
        ),
        byte_size=_directory_size(path),
        checksum_count=_checksum_count(path),
    )


def list_backup_artifacts(root: Path) -> tuple[BackupArtifact, ...]:
    """List backup artifact directories below ``root`` sorted newest first."""
    root_path = root.expanduser()
    if not root_path.is_dir():
        return ()
    artifacts: list[BackupArtifact] = []
    for item in root_path.iterdir():
        if not item.is_dir() or not _BACKUP_ID_RE.fullmatch(item.name):
            continue
        try:
            artifacts.append(backup_artifact(root_path, item.name))
        except BackupArtifactError:
            continue
    return tuple(
        sorted(
            artifacts,
            key=lambda artifact: (
                artifact.created_at_utc or datetime.min.replace(tzinfo=UTC),
                artifact.backup_id,
            ),
            reverse=True,
        )
    )

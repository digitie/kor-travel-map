"""Backup artifact helper tests."""

from __future__ import annotations

import json

import pytest

from kortravelmap.infra.backup import (
    BackupArtifactError,
    backup_artifact,
    backup_artifact_path,
    list_backup_artifacts,
    validate_backup_id,
)


def _write_artifact(root, backup_id: str, *, created_at: str) -> None:
    backup_dir = root / backup_id
    (backup_dir / "postgres").mkdir(parents=True)
    (backup_dir / "rustfs").mkdir()
    (backup_dir / "meta").mkdir()
    (backup_dir / "postgres" / "kor_travel_map.dump").write_bytes(b"app")
    (backup_dir / "postgres" / "kor_travel_map_dagster.dump").write_bytes(b"dagster")
    (backup_dir / "rustfs" / "rustfs-data.tar.gz").write_bytes(b"rustfs")
    (backup_dir / "meta" / "manifest.json").write_text(
        json.dumps(
            {
                "backup_id": backup_id,
                "created_at_utc": created_at,
                "mode": "docker-compose-cold-backup",
                "components": {
                    "postgres_app": "postgres/kor_travel_map.dump",
                    "postgres_dagster": "postgres/kor_travel_map_dagster.dump",
                    "rustfs": "rustfs/rustfs-data.tar.gz",
                },
                "databases": {"app": "kor_travel_map", "dagster": "kor_travel_map_dagster"},
                "object_storage": {"feature_bucket": "kor-travel-map"},
            }
        ),
        encoding="utf-8",
    )
    (backup_dir / "meta" / "SHA256SUMS").write_text(
        "a  postgres/kor_travel_map.dump\nb  postgres/kor_travel_map_dagster.dump\n",
        encoding="utf-8",
    )


def test_list_backup_artifacts_reads_manifest_and_sorts_newest_first(tmp_path) -> None:
    _write_artifact(tmp_path, "backup-old", created_at="2026-06-06T01:00:00Z")
    _write_artifact(tmp_path, "backup-new", created_at="2026-06-06T02:00:00Z")

    artifacts = list_backup_artifacts(tmp_path)

    assert [item.backup_id for item in artifacts] == ["backup-new", "backup-old"]
    assert artifacts[0].manifest_status == "ok"
    assert artifacts[0].components["postgres_app"] == "postgres/kor_travel_map.dump"
    assert artifacts[0].checksum_count == 2
    assert artifacts[0].byte_size > 0


def test_backup_artifact_missing_manifest_is_visible(tmp_path) -> None:
    (tmp_path / "manual").mkdir()

    artifact = backup_artifact(tmp_path, "manual")

    assert artifact.manifest_status == "missing"
    assert artifact.components == {}


def test_backup_id_validation_rejects_path_traversal(tmp_path) -> None:
    with pytest.raises(BackupArtifactError):
        validate_backup_id("../prod")
    with pytest.raises(BackupArtifactError):
        backup_artifact_path(tmp_path, "../prod")

"""Docker standalone backup runbook 회귀 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


@pytest.mark.unit
def test_root_package_exposes_docker_backup_script() -> None:
    package_json = json.loads(_read("package.json"))

    assert package_json["scripts"]["docker:backup"] == "bash scripts/docker-backup.sh"
    assert package_json["scripts"]["docker:restore"] == "bash scripts/docker-restore.sh"


@pytest.mark.unit
def test_docker_backup_script_captures_standalone_backup_bundle() -> None:
    script = _read("scripts/docker-backup.sh")

    assert 'source "$ROOT_DIR/scripts/load-env.sh"' in script
    assert "KRTOUR_MAP_POSTGRES_DB" in script
    assert "KRTOUR_MAP_DAGSTER_POSTGRES_DB" in script
    assert "KRTOUR_MAP_OBJECT_STORE_BUCKET" in script
    assert "KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET" in script
    assert "--format=custom" in script
    assert "pg_dump" in script
    assert "rustfs-perms" in script
    assert "rustfs-data.tar.gz" in script
    assert "manifest.json" in script
    assert "SHA256SUMS" in script


@pytest.mark.unit
def test_docker_backup_script_is_non_destructive() -> None:
    script = _read("scripts/docker-backup.sh")

    assert "KRTOUR_MAP_BACKUP_ALLOW_RUNNING" in script
    assert "docker compose stop" not in script
    assert "pg_restore" not in script
    assert "docker compose down" not in script


@pytest.mark.unit
def test_docker_restore_script_restores_backup_into_staging_targets() -> None:
    script = _read("scripts/docker-restore.sh")

    assert 'source "$ROOT_DIR/scripts/load-env.sh"' in script
    assert "KRTOUR_MAP_RESTORE_BACKUP_ID" in script
    assert "KRTOUR_MAP_RESTORE_BACKUP_DIR" in script
    assert (
        'KRTOUR_MAP_RESTORE_APP_DB="${KRTOUR_MAP_RESTORE_APP_DB:-'
        '${KRTOUR_MAP_POSTGRES_DB}_restore}"'
    ) in script
    assert (
        'KRTOUR_MAP_RESTORE_DAGSTER_DB="${KRTOUR_MAP_RESTORE_DAGSTER_DB:-'
        '${KRTOUR_MAP_DAGSTER_POSTGRES_DB}_restore}"'
    ) in script
    assert "KRTOUR_MAP_RESTORE_RUSTFS_VOLUME" in script
    assert "sha256sum -c meta/SHA256SUMS" in script
    assert "pg_restore" in script
    assert "--clean" in script
    assert "--if-exists" in script
    assert "--no-owner" in script
    assert "--no-privileges" in script
    assert "rustfs-data.tar.gz" in script
    assert "docker run --rm" in script


@pytest.mark.unit
def test_docker_restore_script_refuses_production_targets_by_default() -> None:
    script = _read("scripts/docker-restore.sh")

    assert "refusing to restore into production app DB" in script
    assert "refusing to restore into production Dagster DB" in script
    assert "KRTOUR_MAP_RESTORE_RECREATE" in script
    assert "set KRTOUR_MAP_RESTORE_RECREATE=1" in script
    assert "docker compose down" not in script
    assert "KRTOUR_MAP_RESTORE_ALLOW_PRODUCTION" not in script


@pytest.mark.unit
def test_backup_restore_runbook_documents_three_part_bundle_and_restore_boundary() -> None:
    runbook = _read("docs/backup-restore.md")

    assert "krtour_map" in runbook
    assert "krtour_map_dagster" in runbook
    assert "RustFS" in runbook
    assert "postgres/krtour_map.dump" in runbook
    assert "postgres/krtour_map_dagster.dump" in runbook
    assert "rustfs/rustfs-data.tar.gz" in runbook
    assert "meta/manifest.json" in runbook
    assert "meta/SHA256SUMS" in runbook
    assert "TripMate" in runbook
    assert "npm run docker:restore" in runbook
    assert "krtour_map_restore" in runbook
    assert "krtour_map_dagster_restore" in runbook
    assert "T-209e-c" in runbook

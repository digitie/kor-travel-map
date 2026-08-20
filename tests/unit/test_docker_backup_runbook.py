"""Docker standalone backup runbook 회귀 테스트."""

from __future__ import annotations

import json
import os
import subprocess
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
    assert "KOR_TRAVEL_MAP_POSTGRES_DB" in script
    assert "KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB" in script
    assert "KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET" in script
    assert "KOR_TRAVEL_MAP_OFFLINE_UPLOAD_BUCKET" in script
    assert "--format=custom" in script
    assert "pg_dump" in script
    assert "rustfs-perms" in script
    assert "rustfs-data.tar.gz" in script
    assert "manifest.json" in script
    assert "SHA256SUMS" in script
    assert "pg_export_snapshot" in script
    assert "--snapshot=$snapshot_id" in script
    assert "manual_feature_identity_claims.jsonl" in script
    assert "feature_creation_origins.jsonl" in script
    assert "domain_commands.jsonl" in script
    assert "domain_command_results.jsonl" in script
    assert "feature_requests.jsonl" in script
    assert "manual_provider_dedup_cases.jsonl" in script
    assert "manual_provider_dedup_resolutions.jsonl" in script
    assert "feature_reference_reconciliation_events.jsonl" in script
    assert "feature_reference_reconciliation_acks.jsonl" in script
    assert '"schema_version": 3' in script
    assert '"manual_feature_evidence"' in script
    assert "with-pg-advisory-lock.py" in script
    assert "maintenance:backup-restore" in script
    assert "write-domain-command-marker.py" in script


@pytest.mark.unit
def test_maintenance_lock_handoff_is_not_environment_spoofable() -> None:
    scripts = "\n".join(
        _read(path)
        for path in (
            "scripts/docker-backup.sh",
            "scripts/docker-restore.sh",
            "scripts/docker-restore-swap.sh",
            "scripts/with-pg-advisory-lock.py",
        )
    )

    assert "KOR_TRAVEL_MAP_MAINTENANCE_LOCK_HELD" not in scripts
    assert "KOR_TRAVEL_MAP_MAINTENANCE_LOCK_DISABLED" not in scripts
    assert "--maintenance-lock-child" in scripts


@pytest.mark.unit
def test_all_backup_effect_scripts_require_preacquired_durable_docker_fence() -> None:
    common = _read("scripts/domain-command-fence.sh")
    helper = _read("scripts/docker-domain-command-fence.py")
    assert "KOR_TRAVEL_MAP_COMMAND_FENCE_PREACQUIRED" in common
    assert 'KOR_TRAVEL_MAP_COMMAND_RECOVERY:-0}" != "0"' in common
    assert "domain_command_fence verify" in common
    assert "domain_command_fence release" in common
    assert "--pull=never" in helper
    assert '"none"' in helper
    assert '"--read-only"' in helper
    assert '"ALL"' in helper
    assert '"no-new-privileges"' in helper
    assert "fence-image-id" in helper
    assert "source-revision" in helper

    for path, first_mutation in (
        ("scripts/docker-backup.sh", "rm -rf --"),
        ("scripts/docker-restore.sh", 'prepare_database "$KOR_TRAVEL_MAP_RESTORE_APP_DB"'),
        (
            "scripts/docker-restore-swap.sh",
            '"$python_bin" "$ROOT_DIR/scripts/write-restore-swap-env.py"',
        ),
    ):
        script = _read(path)
        assert "source \"$ROOT_DIR/scripts/domain-command-fence.sh\"" in script
        assert script.index("acquire_domain_command_fence") < script.index(
            first_mutation
        )
        assert script.index("write-domain-command-marker.py") < script.index(
            "release_domain_command_fence"
        )


@pytest.mark.unit
def test_docker_backup_script_is_non_destructive() -> None:
    script = _read("scripts/docker-backup.sh")

    assert "KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING" in script
    assert "docker compose stop" not in script
    assert "pg_restore" not in script
    assert "docker compose down" not in script


@pytest.mark.unit
def test_docker_restore_script_restores_backup_into_staging_targets() -> None:
    script = _read("scripts/docker-restore.sh")

    assert 'source "$ROOT_DIR/scripts/load-env.sh"' in script
    assert "KOR_TRAVEL_MAP_RESTORE_BACKUP_ID" in script
    assert "KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR" in script
    assert (
        'KOR_TRAVEL_MAP_RESTORE_APP_DB="${KOR_TRAVEL_MAP_RESTORE_APP_DB:-'
        '${KOR_TRAVEL_MAP_POSTGRES_DB}_restore}"'
    ) in script
    assert (
        'KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB="${KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB:-'
        '${KOR_TRAVEL_MAP_DAGSTER_POSTGRES_DB}_restore}"'
    ) in script
    assert "KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME" in script
    assert "sha256sum -c meta/SHA256SUMS" in script
    assert "pg_restore" in script
    assert "--clean" in script
    assert "--if-exists" in script
    assert "--no-owner" in script
    assert "--no-privileges" in script
    assert "vacuumdb" in script
    assert "--analyze-in-stages" in script
    assert "rustfs-data.tar.gz" in script
    assert "docker run --rm" in script
    assert "KOR_TRAVEL_MAP_RESTORE_SKIP_VERIFY" in script
    assert "docker-restore-verify.sh" in script
    assert "with-pg-advisory-lock.py" in script
    assert "maintenance:backup-restore" in script
    assert "KOR_TRAVEL_MAP_COMMAND_RECOVERY" in script
    assert "recovering completed restore" not in script
    assert "recovery_complete" not in script
    assert "write-domain-command-marker.py" in script


@pytest.mark.unit
def test_docker_restore_script_refuses_production_targets_by_default() -> None:
    script = _read("scripts/docker-restore.sh")

    assert "refusing to restore into production app DB" in script
    assert "refusing to restore into production Dagster DB" in script
    assert "KOR_TRAVEL_MAP_RESTORE_RECREATE" in script
    assert "set KOR_TRAVEL_MAP_RESTORE_RECREATE=1" in script
    assert "docker compose down" not in script
    assert "KOR_TRAVEL_MAP_RESTORE_ALLOW_PRODUCTION" not in script


@pytest.mark.unit
def test_restore_recovery_does_not_adopt_healthy_stale_targets(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "backups" / "backup-1"
    for relative_path in (
        "postgres/kor_travel_map.dump",
        "postgres/kor_travel_map_dagster.dump",
        "rustfs/rustfs-data.tar.gz",
        "meta/manifest.json",
        "meta/SHA256SUMS",
    ):
        target = backup / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture")
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = binary_dir / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {docker_log}\n"
        "if [[ \"$*\" == *\"SELECT 1 FROM pg_database\"* ]]; then\n"
        "  printf '1\\n'\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{binary_dir}:{os.environ['PATH']}",
        "KOR_TRAVEL_MAP_BACKUP_ROOT": str(tmp_path / "backups"),
        "KOR_TRAVEL_MAP_RESTORE_BACKUP_ID": "backup-1",
        "KOR_TRAVEL_MAP_RESTORE_APP_DB": "stale_app",
        "KOR_TRAVEL_MAP_RESTORE_DAGSTER_DB": "stale_dagster",
        "KOR_TRAVEL_MAP_RESTORE_RUSTFS_VOLUME": "stale-volume",
        "KOR_TRAVEL_MAP_RESTORE_SKIP_CHECKSUM": "1",
        "KOR_TRAVEL_MAP_RESTORE_SKIP_RUSTFS": "1",
        "KOR_TRAVEL_MAP_RESTORE_RECREATE": "0",
        "KOR_TRAVEL_MAP_COMMAND_RECOVERY": "1",
        "KOR_TRAVEL_MAP_COMMAND_MARKER_KEY": "command-91",
        "KOR_TRAVEL_MAP_COMMAND_ID": "91",
        "KOR_TRAVEL_MAP_COMMAND_OPERATION": "admin.backup.restore",
        "KOR_TRAVEL_MAP_COMMAND_EFFECT_KIND": "restore",
        "KOR_TRAVEL_MAP_COMMAND_BACKUP_ID": "backup-1",
        "KOR_TRAVEL_MAP_COMMAND_INPUT_DIGEST": "a" * 64,
    }

    completed = subprocess.run(
        [
            "bash",
            str(ROOT / "scripts/docker-restore.sh"),
            "--maintenance-lock-child",
            "backup-1",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "restore target DB already exists: stale_app" in completed.stderr
    assert "pg_restore" not in docker_log.read_text(encoding="utf-8")
    assert not (tmp_path / "backups" / ".domain-command-markers").exists()


@pytest.mark.unit
def test_restore_verify_script_checks_staging_counts() -> None:
    script = _read("scripts/docker-restore-verify.sh")

    assert "feature.features" in script
    assert "last_analyze" in script
    assert "last_autoanalyze" in script
    assert "feature_stats=ready" in script
    assert "information_schema.tables" in script
    assert "docker volume inspect" in script
    assert "file_count" in script
    assert "verify_manual_feature_evidence" in script
    assert "manual_feature_evidence" in script
    assert "manual evidence root mismatch" in script
    assert 'schema_version not in {1, 2, 3}' in script
    assert "feature_requests" in script
    assert "manual_provider_dedup_cases" in script
    assert "manual_provider_dedup_resolutions" in script
    assert "feature_reference_reconciliation_events" in script
    assert "feature_reference_reconciliation_acks" in script
    assert "rebuild_feature_reference_reconciliation_leases" in script
    assert "M05 restore has a non-prefix reconciliation ACK" in script
    assert "M05 restore has an ACK/event hash mismatch" in script
    assert "lease_epoch = CASE" in script
    assert "KOR_TRAVEL_MAP_RESTORE_BACKUP_DIR" in script


@pytest.mark.unit
def test_n150_restore_runner_analyzes_restored_databases() -> None:
    script = _read("live-e2e-backup-runner/restore.sh")
    readme = _read("live-e2e-backup-runner/README.md")

    assert script.index("pg_restore") < script.index("vacuumdb")
    assert "--analyze-in-stages" in script
    assert "vacuumdb --analyze-in-stages" in readme


@pytest.mark.unit
def test_restore_swap_script_generates_env_switch_and_can_apply() -> None:
    script = _read("scripts/docker-restore-swap.sh")
    writer = _read("scripts/write-restore-swap-env.py")

    assert "docker-restore-verify.sh" in script
    assert "fence-cache-target-restored-db.py" in script
    assert "write-restore-swap-env.py" in script
    assert script.index("acquire_domain_command_fence") < script.index(
        "fence-cache-target-restored-db.py"
    )
    assert script.index("fence-cache-target-restored-db.py") < script.index(
        "write-restore-swap-env.py"
    )
    assert "KOR_TRAVEL_MAP_DOCKER_PG_DSN" in writer
    assert "KOR_TRAVEL_MAP_DOCKER_DAGSTER_PG_URL" in writer
    assert "KOR_TRAVEL_MAP_RUSTFS_VOLUME" in writer
    assert "KOR_TRAVEL_MAP_RESTORE_SWAP_APPLY" in script
    assert "docker compose" in script
    assert "with-pg-advisory-lock.py" in script
    assert "KOR_TRAVEL_MAP_RESTORE_SWAP_ENV_FILE" not in script
    assert 'marker_effect_state="swap_applied"' in script
    assert 'marker_effect_state="swap_planned"' in script
    assert "write-domain-command-marker.py" in script


@pytest.mark.unit
def test_docker_compose_supports_restore_rustfs_volume_swap() -> None:
    compose = _read("docker-compose.yml")

    assert "kor-travel-map-rustfs-data:/data" in compose
    assert "name: ${KOR_TRAVEL_MAP_RUSTFS_VOLUME:-kor-travel-map-rustfs}" in compose


@pytest.mark.unit
def test_backup_restore_runbook_documents_three_part_bundle_and_restore_boundary() -> None:
    runbook = _read("docs/backup-restore.md")

    assert "kor_travel_map" in runbook
    assert "kor_travel_map_dagster" in runbook
    assert "RustFS" in runbook
    assert "postgres/kor_travel_map.dump" in runbook
    assert "postgres/kor_travel_map_dagster.dump" in runbook
    assert "rustfs/rustfs-data.tar.gz" in runbook
    assert "meta/manifest.json" in runbook
    assert "meta/SHA256SUMS" in runbook
    assert "외부 서비스" in runbook
    assert "npm run docker:restore" in runbook
    assert "kor_travel_map_restore" in runbook
    assert "kor_travel_map_dagster_restore" in runbook
    assert "docker-restore-verify.sh" in runbook
    assert "docker-restore-swap.sh" in runbook
    assert "T-209e" in runbook

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
    assert "feature_reference_reconciliation_subscriptions.jsonl" in script
    assert '"schema_version": 4' in script
    assert '"recovery_status": "audit_only_no_restore"' in script
    assert '"manual_feature_evidence"' in script
    assert "with-pg-advisory-lock.py" in script
    assert "maintenance:backup-restore" in script
    assert "write-domain-command-marker.py" in script


@pytest.mark.unit
def test_backup_maintenance_lock_is_not_environment_spoofable() -> None:
    scripts = "\n".join(
        _read(path)
        for path in (
            "scripts/docker-backup.sh",
            "scripts/with-pg-advisory-lock.py",
        )
    )

    assert "KOR_TRAVEL_MAP_MAINTENANCE_LOCK_HELD" not in scripts
    assert "KOR_TRAVEL_MAP_MAINTENANCE_LOCK_DISABLED" not in scripts
    assert "--maintenance-lock-child" in scripts


@pytest.mark.unit
def test_backup_effect_requires_preacquired_durable_docker_fence() -> None:
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

    script = _read("scripts/docker-backup.sh")
    assert 'source "$ROOT_DIR/scripts/domain-command-fence.sh"' in script
    assert script.index("acquire_domain_command_fence") < script.index("rm -rf --")
    assert script.index("write-domain-command-marker.py") < script.index(
        "release_domain_command_fence"
    )

    for path in (
        "scripts/docker-restore.sh",
        "scripts/docker-restore-swap.sh",
        "scripts/docker-restore-verify.sh",
        "live-e2e-backup-runner/restore.sh",
        "live-e2e-backup-runner/swap.sh",
    ):
        disabled = _read(path)
        assert "is disabled" in disabled
        for mutation in (
            "acquire_domain_command_fence",
            "pg_restore",
            "write-restore-swap-env.py",
            "docker compose",
        ):
            if mutation in disabled:
                assert disabled.index("exit 2") < disabled.index(mutation)


@pytest.mark.unit
def test_docker_backup_script_is_non_destructive() -> None:
    script = _read("scripts/docker-backup.sh")

    assert "KOR_TRAVEL_MAP_BACKUP_ALLOW_RUNNING" in script
    assert "docker compose stop" not in script
    assert "pg_restore" not in script
    assert "docker compose down" not in script


@pytest.mark.unit
def test_restore_scripts_fail_closed_before_any_legacy_operation() -> None:
    for path in (
        "scripts/docker-restore.sh",
        "scripts/docker-restore-swap.sh",
        "scripts/docker-restore-verify.sh",
    ):
        script = _read(path)
        assert "is disabled" in script
        assert "backup artifacts are audit-only under the 300 baseline" in script
        assert "previous-revision restore" in script
        assert script.rstrip().endswith("exit 2")
        assert "KOR_TRAVEL_MAP_" not in script


@pytest.mark.unit
@pytest.mark.parametrize(
    "relative_path",
    [
        "scripts/docker-restore.sh",
        "scripts/docker-restore-swap.sh",
        "scripts/docker-restore-verify.sh",
        "live-e2e-backup-runner/restore.sh",
        "live-e2e-backup-runner/swap.sh",
    ],
)
def test_restore_entrypoints_do_not_touch_docker_even_with_escape_flags(
    tmp_path: Path,
    relative_path: str,
) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    docker_log = tmp_path / "docker.log"
    fake_docker = binary_dir / "docker"
    fake_docker.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {docker_log}\n"
        'if [[ "$*" == *"SELECT 1 FROM pg_database"* ]]; then\n'
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
            str(ROOT / relative_path),
            "--maintenance-lock-child",
            "backup-1",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "disabled" in completed.stderr
    assert not docker_log.exists()
    assert not (tmp_path / "backups" / ".domain-command-markers").exists()


@pytest.mark.unit
def test_live_restore_runners_are_disabled_with_the_root_restore_surface() -> None:
    for path in ("live-e2e-backup-runner/restore.sh", "live-e2e-backup-runner/swap.sh"):
        script = _read(path)
        assert "is disabled" in script
        assert "backup artifacts are audit-only under the 300 baseline" in script
        assert script.rstrip().endswith("exit 2")
        if "pg_restore" in script:
            assert script.index("exit 2") < script.index("pg_restore")


@pytest.mark.unit
def test_docker_compose_supports_restore_rustfs_volume_swap() -> None:
    compose = _read("docker-compose.yml")

    assert "kor-travel-map-rustfs-data:/data" in compose
    assert "name: ${KOR_TRAVEL_MAP_RUSTFS_VOLUME:-kor-travel-map-rustfs}" in compose


@pytest.mark.unit
def test_backup_restore_runbook_documents_audit_only_bundle_and_handoff_boundary() -> None:
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
    assert 'schema_version: 4' in runbook
    assert 'recovery_status: "audit_only_no_restore"' in runbook
    assert "scripts/docker-restore.sh" in runbook
    assert "RESTORE_UNSUPPORTED" in runbook
    assert "0236_tvn41s_compaction_drained → 300" in runbook
    assert "Docker Manager" in runbook
    assert "npm run docker:restore" not in runbook
    assert "kor_travel_map_restore" not in runbook
    assert "docker-restore-verify.sh" in runbook

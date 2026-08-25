"""API + Dagster application ``300`` paired candidate의 정적 봉인 계약."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_storage_helper(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    dagster = ModuleType("dagster")
    dagster_core = ModuleType("dagster._core")
    dagster_storage = ModuleType("dagster._core.storage")
    dagster_sql = ModuleType("dagster._core.storage.sql")
    dagster_sql.ALEMBIC_SCRIPTS_LOCATION = "/unused"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dagster", dagster)
    monkeypatch.setitem(sys.modules, "dagster._core", dagster_core)
    monkeypatch.setitem(sys.modules, "dagster._core.storage", dagster_storage)
    monkeypatch.setitem(sys.modules, "dagster._core.storage.sql", dagster_sql)
    path = ROOT / "docker" / "dagster-storage-migrate.py"
    spec = importlib.util.spec_from_file_location("dagster_storage_migrate", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_paired_builder_seals_both_images_and_one_dagster_launch_image() -> None:
    script = (ROOT / "scripts" / "build-application-300-paired-candidate.sh").read_text(
        encoding="utf-8"
    )

    assert "kor-travel-map.application-300-paired-candidate-build.v1" in script
    assert '"api_candidate": api_candidate' in script
    assert '"dagster_candidate": {' in script
    assert '"requires_same_image_id": True' in script
    assert '"application_final_permit_consumers": ["webserver", "daemon"]' in script
    assert '"webserver_image_id": dagster_image_id' in script
    assert '"daemon_image_id": dagster_image_id' in script
    assert '"storage_migration_image_id": dagster_image_id' in script
    assert '"webserver_argv_policy": {' in script
    assert '"port_decimal_minimum": 1' in script
    assert '"port_decimal_maximum": 65535' in script
    assert '"image_default_webserver_argv": [' in script
    assert '"scope": "dagster-metadata-only-excluded-from-application-final-permit"' in script
    assert '["/usr/local/bin/ktm-dagster-storage", "migrate"]' in script
    assert '"metadata_database_identity_permit": {' in script
    assert '"production_authority": "docker-manager"' in script
    assert '"forbidden_application_raw_revision": "300"' in script
    assert '"dagster_config_receipt_field": "candidate_dagster_yaml_sha256"' in script
    assert '"candidate_commit"' in script
    assert '"candidate_git_tree"' in script
    assert "candidate_full_rootfs_layers_sha256" in script
    assert "candidate_runtime_manifest_sha256" in script
    assert "candidate_dependency_sbom_sha256" in script
    assert "candidate_config_sha256" in script
    assert "candidate_dagster_yaml_sha256" in script
    assert "candidate_proof_manifest_sha256" in script
    assert "application_contract_sha256" in script
    assert "--network=none --read-only" in script
    assert "PYTHONPATH" in script
    assert "PYTHONHOME" in script
    for builder in (
        "scripts/build-application-300-candidate.sh",
        "scripts/build-application-300-paired-candidate.sh",
    ):
        source = (ROOT / builder).read_text(encoding="utf-8")
        assert 'chmod -R u+rwX -- "$SEALED_PARENT"' in source
        assert 'rm -rf -- "$SEALED_PARENT"' in source

    rehearsal = (ROOT / "scripts" / "rehearse-application-300-handoff.sh").read_text(
        encoding="utf-8"
    )
    assert "--paired-build-receipt" in rehearsal
    assert "build-application-300-paired-candidate.sh" in rehearsal
    assert "paired_candidate_build_receipt_sha256" in rehearsal
    assert "paired_dagster_image_id" in rehearsal
    assert "kor-travel-map.application-300-handoff-rehearsal.v6" in rehearsal
    assert 'launch["webserver_argv_policy"] != {' in rehearsal
    assert 'launch["image_default_webserver_argv"] != [' in rehearsal
    assert 'launch["daemon_argv"] != [' in rehearsal
    assert 'launch["metadata_database_identity_permit"] != {' in rehearsal


@pytest.mark.unit
def test_dagster_image_has_symmetric_provenance_and_immutable_contract_tool() -> None:
    dockerfile = (ROOT / "docker" / "dagster.Dockerfile").read_text(encoding="utf-8")

    for label in (
        "org.opencontainers.image.revision",
        "candidate-git-tree",
        "candidate-dockerfile-sha256",
        "candidate-base-image-reference",
        "candidate-base-image-id",
    ):
        assert label in dockerfile
    assert (
        "docker/application-schema-contract.py "
        "/usr/local/bin/ktm-application-schema-contract" in dockerfile
    )
    assert "test ! -w /usr/local/bin/ktm-application-schema-contract" in dockerfile
    assert "find /app/alembic -type d -exec chmod 0555" in dockerfile
    assert "find /app/alembic -type f -exec chmod 0444" in dockerfile
    assert "test ! -w /app/alembic" in dockerfile
    assert "! mv /app/alembic/baseline /app/alembic/replaced" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/dagster-entrypoint.sh"]' in dockerfile
    assert (
        'CMD ["/usr/local/bin/dagster-webserver", "-m", '
        '"kortravelmap.dagster.definitions", "-h", "0.0.0.0", "-p", "12702"]'
        in dockerfile
    )

    paired_builder = (
        ROOT / "scripts" / "build-application-300-paired-candidate.sh"
    ).read_text(encoding="utf-8")
    assert "--network=none --entrypoint /bin/sh" in paired_builder
    assert "! mv /app/alembic/baseline /app/alembic/replaced" in paired_builder


@pytest.mark.unit
def test_storage_helper_ignores_fake_path_for_dagster_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _load_storage_helper(monkeypatch)
    observed: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    environment = {"PATH": "/tmp/operator-controlled-bin"}
    helper._run_dagster_instance_migrate(environment)

    assert observed["command"] == [
        "/usr/local/bin/python",
        "-I",
        "/usr/local/bin/dagster",
        "instance",
        "migrate",
    ]
    assert observed["environment"] == environment
    source = (ROOT / "docker" / "dagster-storage-migrate.py").read_text(
        encoding="utf-8"
    )
    assert source.startswith("#!/usr/local/bin/python -I\n")
    assert '["dagster", "instance", "migrate"]' not in source

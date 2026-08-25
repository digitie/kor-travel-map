"""API + Dagster application ``300`` paired candidate의 정적 봉인 계약."""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _strict_receipt_snapshot_program() -> str:
    source = (
        ROOT / "scripts" / "build-application-300-paired-candidate.sh"
    ).read_text(encoding="utf-8")
    marker = (
        '  python3 - "$source_path" "$snapshot_path" "$(id -u)" '
        '"$description" <<\'PY\'\n'
    )
    _, found, remainder = source.partition(marker)
    assert found
    program, found, _ = remainder.partition("\nPY\n}")
    assert found
    return program


def _snapshot_receipt(source: Path, destination: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _strict_receipt_snapshot_program(),
            str(source),
            str(destination),
            str(os.getuid()),
            "API receipt",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _private_receipt_publish_program() -> str:
    source = (
        ROOT / "scripts" / "build-application-300-paired-candidate.sh"
    ).read_text(encoding="utf-8")
    marker = (
        '  python3 - "$source_path" "$destination_path" "$(id -u)" <<\'PY\'\n'
    )
    _, found, remainder = source.partition(marker)
    assert found
    program, found, _ = remainder.partition("\nPY\n}")
    assert found
    return program


def _publish_receipt(source: Path, destination: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _private_receipt_publish_program(),
            str(source),
            str(destination),
            str(os.getuid()),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


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
    assert '"schema": "kor-travel-map.dagster-storage-database-permit.v2"' in script
    assert '"operation_id_binding": {' in script
    assert '"format": "canonical-lowercase-uuid"' in script
    assert '"authority": "docker-manager-durable-journal"' in script
    assert '"forbidden_application_raw_revision": "300"' in script
    assert '"dagster_config_receipt_field": "candidate_dagster_yaml_sha256"' in script
    assert '"login_role_attributes"' in script
    assert '"required_login_role_attributes": {' in script
    assert '"can_login": True' in script
    assert '"inherit": False' in script
    assert '"requires_owner_login_and_effective_role_equality": True' in script
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
    api_builder = (ROOT / "scripts/build-application-300-candidate.sh").read_text(
        encoding="utf-8"
    )
    assert 'stat -c "%u:%a" /app/resources/curations' in api_builder
    assert "! touch /app/resources/curations/.candidate-mutation" in api_builder
    assert "! mv /app/resources/curations/manifest.json" in api_builder
    assert "--entrypoint sha256sum" in api_builder
    assert "image_sidecar_sha256=\"${image_sidecar_digest_line%% *}\"" in api_builder
    assert "awk '{print \\\\\\$1}'" not in api_builder
    assert 'filesystem_root = Path("/")' in api_builder
    assert "relative_to(filesystem_root)" in api_builder
    assert "relative_to('/')" not in api_builder

    paired_builder = (
        ROOT / "scripts" / "build-application-300-paired-candidate.sh"
    ).read_text(encoding="utf-8")
    assert 'filesystem_root = Path("/")' in paired_builder
    assert "relative_to(filesystem_root).as_posix()" in paired_builder
    assert "relative_to('/').as_posix()" not in paired_builder

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
def test_api_only_partial_receipt_resumes_only_through_exact_verifier() -> None:
    """API publish 뒤 중단은 삭제 없이 exact verify 뒤 Dagster로 재개한다."""
    script = (
        ROOT / "scripts" / "build-application-300-paired-candidate.sh"
    ).read_text(encoding="utf-8")

    detects_partial = 'API_RECEIPT_PREEXISTED=1'
    fresh_api_build = (
        'if [ "$MODE" = "build" ] && [ "$API_RECEIPT_PREEXISTED" -eq 0 ]; then'
    )
    stable_snapshot = (
        'snapshot_strict_receipt "$API_RECEIPT" "$API_RECEIPT_FOR_VERIFY" '
        '"API receipt"'
    )
    exact_verify = (
        'api_candidate_json="$("${api_builder[@]}" --verify)" || '
        'die "API candidate 검증에 실패했다"'
    )
    dagster_build = "docker build --pull=false"

    assert script.index(detects_partial) < script.index(fresh_api_build)
    assert script.index(fresh_api_build) < script.index(stable_snapshot)
    assert script.index(stable_snapshot) < script.index(exact_verify)
    assert script.index(exact_verify) < script.index(dagster_build)
    assert '--receipt "$API_RECEIPT_FOR_VERIFY"' in script
    assert 'rm -f -- "$API_RECEIPT"' not in script
    assert 'rm -- "$API_RECEIPT"' not in script


@pytest.mark.unit
def test_partial_receipt_snapshot_is_stable_private_and_does_not_mutate_source(
    tmp_path: Path,
) -> None:
    tmp_path.chmod(0o700)
    source = tmp_path / "api-candidate-build.json"
    source.write_bytes(b'{"candidate":"exact"}\n')
    source.chmod(0o600)
    source_inode = source.stat().st_ino
    destination = tmp_path / "verified.snapshot"

    result = _snapshot_receipt(source, destination)

    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == b'{"candidate":"exact"}\n'
    assert source.stat().st_ino == source_inode
    assert destination.read_bytes() == source.read_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600


@pytest.mark.unit
@pytest.mark.parametrize("hostile_kind", ["symlink", "hardlink", "malformed-mode"])
def test_partial_receipt_snapshot_rejects_unsafe_files(
    tmp_path: Path,
    hostile_kind: str,
) -> None:
    """final symlink·hardlink·mode drift는 exact API verifier 전에 fail-close한다."""
    tmp_path.chmod(0o700)
    source = tmp_path / "api-candidate-build.json"
    target = tmp_path / "foreign.json"
    target.write_bytes(b'{"candidate":"foreign-or-malformed"}\n')
    target.chmod(0o600)
    if hostile_kind == "symlink":
        source.symlink_to(target)
    elif hostile_kind == "hardlink":
        source.hardlink_to(target)
    else:
        source.write_bytes(target.read_bytes())
        source.chmod(0o640)

    destination = tmp_path / "must-not-exist.snapshot"
    result = _snapshot_receipt(source, destination)

    assert result.returncode != 0
    assert not destination.exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "malformed_payload",
    [
        b"not-json\n",
        b'{"duplicate":1, "duplicate":2}\n',
        b'{"valid":true}',
        b"[]\n",
    ],
)
def test_partial_receipt_snapshot_rejects_malformed_content(
    tmp_path: Path,
    malformed_payload: bytes,
) -> None:
    tmp_path.chmod(0o700)
    source = tmp_path / "api-candidate-build.json"
    source.write_bytes(malformed_payload)
    source.chmod(0o600)
    destination = tmp_path / "must-not-exist.snapshot"

    result = _snapshot_receipt(source, destination)

    assert result.returncode != 0
    assert not destination.exists()


@pytest.mark.unit
def test_paired_receipt_publish_is_no_replace_and_fsync_ready(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)
    source = tmp_path / ".paired.staged"
    source.write_bytes(b'{"candidate":"exact"}\n')
    source.chmod(0o600)
    destination = tmp_path / "paired-candidate-build.json"

    result = _publish_receipt(source, destination)

    assert result.returncode == 0, result.stderr
    assert not source.exists()
    assert destination.read_bytes() == b'{"candidate":"exact"}\n'
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert destination.stat().st_nlink == 1

    replacement = tmp_path / ".paired.replacement"
    replacement.write_bytes(b'{"candidate":"foreign"}\n')
    replacement.chmod(0o600)
    refused = _publish_receipt(replacement, destination)

    assert refused.returncode != 0
    assert replacement.exists()
    assert destination.read_bytes() == b'{"candidate":"exact"}\n'


@pytest.mark.unit
def test_receipt_helpers_reject_group_or_world_visible_parent(tmp_path: Path) -> None:
    tmp_path.chmod(0o750)
    source = tmp_path / "api-candidate-build.json"
    source.write_bytes(b'{"candidate":"exact"}\n')
    source.chmod(0o600)

    snapshot = _snapshot_receipt(source, tmp_path / "snapshot")
    publish = _publish_receipt(source, tmp_path / "paired-candidate-build.json")

    assert snapshot.returncode != 0
    assert publish.returncode != 0
    assert source.exists()
    assert not (tmp_path / "snapshot").exists()
    assert not (tmp_path / "paired-candidate-build.json").exists()


@pytest.mark.unit
@pytest.mark.parametrize(
    "script_name",
    [
        "build-application-300-candidate.sh",
        "build-application-300-paired-candidate.sh",
    ],
)
def test_embedded_python_does_not_break_its_shell_single_quote(
    script_name: str,
) -> None:
    source = (ROOT / "scripts" / script_name).read_text(encoding="utf-8")
    inside_python = False
    block_count = 0
    for line_number, line in enumerate(source.splitlines(), start=1):
        if not inside_python and line.endswith("-c '") and "entrypoint" in line:
            inside_python = True
            block_count += 1
            continue
        if not inside_python:
            continue
        if line.startswith("'"):
            inside_python = False
            continue
        assert "'" not in line, (
            f"{script_name}:{line_number}: shell single-quoted Python block contains "
            "an unescaped single quote"
        )
    assert not inside_python
    assert block_count > 0


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

    api_dockerfile = (ROOT / "docker" / "api.Dockerfile").read_text(encoding="utf-8")
    assert "COPY --chown=root:root resources/curations" in api_dockerfile
    assert "find /app/resources/curations -type d -exec chmod 0555" in api_dockerfile
    assert "find /app/resources/curations -type f -exec chmod 0444" in api_dockerfile
    assert "! mv /app/resources/curations/manifest.json" in api_dockerfile


@pytest.mark.unit
def test_storage_helper_ignores_fake_path_for_dagster_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = _load_storage_helper(monkeypatch)
    observed: dict[str, Any] = {"commands": []}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        observed["commands"].append(command)
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    environment = {"PATH": "/tmp/operator-controlled-bin"}
    helper._run_dagster_instance_migrate(environment)

    assert observed["commands"] == [
        [
            "/usr/local/bin/python",
            "-I",
            "/usr/local/bin/dagster",
            "instance",
            "migrate",
        ],
        [
            "/usr/local/bin/python",
            "-I",
            "/usr/local/bin/dagster",
            "instance",
            "reindex",
        ],
    ]
    assert observed["environment"] == environment
    source = (ROOT / "docker" / "dagster-storage-migrate.py").read_text(
        encoding="utf-8"
    )
    assert source.startswith("#!/usr/local/bin/python -I\n")
    assert '["dagster", "instance", "migrate"]' not in source

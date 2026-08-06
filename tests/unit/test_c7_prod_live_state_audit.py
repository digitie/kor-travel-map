"""C7 production live state 감사 도구의 fail-closed 회귀 테스트."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDITOR = ROOT / "scripts" / "audit-c7-prod-live-state.py"


def _load_auditor() -> ModuleType:
    spec = importlib.util.spec_from_file_location("c7_prod_state_audit", AUDITOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _portable_safe_entry(path: Path, *, directory: bool) -> bool:
    observed = path.lstat()
    return (
        (stat.S_ISDIR(observed.st_mode) if directory else stat.S_ISREG(observed.st_mode))
        and not path.is_symlink()
        and stat.S_IMODE(observed.st_mode) == (0o700 if directory else 0o600)
    )


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def test_missing_state_root_is_a_clean_absence(tmp_path: Path) -> None:
    auditor = _load_auditor()

    result = auditor.audit_state_root(tmp_path / "missing")

    assert result.state_root_exists is False
    assert result.blocked is False
    assert result.unsafe_entries == 0
    assert result.unexpected_entries == 0


def test_broken_state_root_symlink_is_unsafe(tmp_path: Path) -> None:
    auditor = _load_auditor()
    root = tmp_path / "state"
    root.symlink_to(tmp_path / "missing-target", target_is_directory=True)

    result = auditor.audit_state_root(root)

    assert result.state_root_exists is True
    assert result.state_root_safe is False
    assert result.unsafe_entries == 1


def test_partial_restore_is_reported_without_payload_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auditor = _load_auditor()
    monkeypatch.setattr(auditor, "_safe_entry", _portable_safe_entry)
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    _write_json(root / "BLOCKED.json", {"phase": "restore_failed", "secret": "hidden"})
    _write_json(root / "run-20260719T010101Z-10.json", {"phase": "restore_failed"})
    runtime = root / "runtime.A1b2C3"
    runtime.mkdir(mode=0o700)
    temporary = root / ".state.A1b2C3"
    temporary.touch(mode=0o600)

    result = auditor.audit_state_root(root)
    encoded = json.dumps(auditor.asdict(result), sort_keys=True)

    assert result.blocked is True
    assert result.journals == {"run": 1, "schedule": 0, "kma": 0, "poi": 0}
    assert result.journal_phases["run"] == {"restore_failed": 1}
    assert result.runtime_directories == 1
    assert result.temporary_files == 1
    assert result.requires_recovery is True
    assert "hidden" not in encoded


def test_evidence_tree_rejects_symlinks_and_unexpected_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auditor = _load_auditor()
    monkeypatch.setattr(auditor, "_safe_entry", _portable_safe_entry)
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    evidence = root / "evidence"
    evidence.mkdir(mode=0o700)
    run = evidence / "unexpected-name"
    run.mkdir(mode=0o700)
    _write_json(run / "manifest.json", {"version": 1})
    (run / "unsafe-link").symlink_to(run / "manifest.json")

    result = auditor.audit_state_root(root)

    assert result.evidence_directories == 1
    assert result.unsafe_entries >= 1
    assert result.unexpected_entries == 1


def test_nested_runtime_journals_and_running_cid_are_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auditor = _load_auditor()
    monkeypatch.setattr(auditor, "_safe_entry", _portable_safe_entry)
    monkeypatch.setattr(
        auditor,
        "_read_creator_reference",
        lambda _path, _roots: {
            "container_name": "kor-travel-map-c7-e2e-10",
            "creator_pgid": 10,
            "creator_pid": 10,
            "creator_sid": 10,
            "creator_start_ticks": 10,
            "phase": "creating",
            "runtime": str(tmp_path / "state" / "runtime.A1b2C3"),
            "version": 1,
        },
    )
    monkeypatch.setattr(auditor, "_creator_is_active", lambda _reference: False)
    monkeypatch.setattr(
        auditor, "_container_running_state", lambda _reference, _cid: True
    )
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    runtime = root / "runtime.A1b2C3"
    runtime.mkdir(mode=0o700)
    journals = runtime / "journals"
    journals.mkdir(mode=0o700)
    playwright = runtime / "playwright"
    playwright.mkdir(mode=0o700)
    _write_json(journals / "sensor.json", {"phase": "restoring"})
    _write_json(journals / "schedule.json", {"phase": "restored"})
    cid = root / "container-10.cid"
    cid.write_text("a" * 64, encoding="ascii")
    cid.chmod(0o600)
    _write_json(root / "container-10.json", {"redacted": True})

    result = auditor.audit_state_root(root)

    assert result.runtime_directories == 1
    assert result.journals == {"run": 1, "schedule": 1, "kma": 0, "poi": 0}
    assert result.journal_phases["run"] == {"restoring": 1}
    assert result.journal_phases["schedule"] == {"restored": 1}
    assert result.container_reference_files == 2
    assert result.running_containers == 1
    assert result.requires_recovery is True


def test_creator_reference_detects_cidfile_create_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auditor = _load_auditor()
    monkeypatch.setattr(auditor, "_safe_entry", _portable_safe_entry)
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    runtime = root / "runtime.A1b2C3"
    runtime.mkdir(mode=0o700)
    monkeypatch.setattr(
        auditor,
        "_read_creator_reference",
        lambda _path, _roots: {
            "container_name": "kor-travel-map-c7-e2e-11",
            "creator_pgid": 11,
            "creator_pid": 11,
            "creator_sid": 11,
            "creator_start_ticks": 11,
            "phase": "creating",
            "runtime": str(runtime),
            "version": 1,
        },
    )
    monkeypatch.setattr(auditor, "_creator_is_active", lambda _reference: True)
    monkeypatch.setattr(
        auditor, "_container_running_state", lambda _reference, _cid: True
    )
    _write_json(root / "container-11.json", {"redacted": True})
    cid = root / "container-11.cid"
    cid.touch(mode=0o600)

    result = auditor.audit_state_root(root)

    assert result.active_creator_processes == 1
    assert result.running_containers == 1
    assert result.container_reference_files == 2
    assert result.requires_recovery is True


def test_evidence_manifest_hashes_are_recomputed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auditor = _load_auditor()
    monkeypatch.setattr(auditor, "_safe_entry", _portable_safe_entry)
    run = tmp_path / "run-20260719T010101Z-10"
    run.mkdir(mode=0o700)
    result_file = run / "journals" / "sensor.json"
    result_file.parent.mkdir(mode=0o700)
    result_file.write_text("{}\n", encoding="utf-8")
    result_file.chmod(0o600)
    attestation_file = run / "runtime-attestation.json"
    attestation_file.write_text("{}\n", encoding="utf-8")
    attestation_file.chmod(0o600)
    pinned_runtime_manifest_file = run / "pinned-runtime-manifest.json"
    pinned_runtime_manifest_file.write_text("{}\n", encoding="utf-8")
    pinned_runtime_manifest_file.chmod(0o600)
    pinned_runtime_rebuild_journal_file = run / "pinned-runtime-rebuild-journal.json"
    pinned_runtime_rebuild_journal_file.write_text("{}\n", encoding="utf-8")
    pinned_runtime_rebuild_journal_file.chmod(0o600)
    final_schema_reload_receipt_file = run / "final-schema-reload-receipt.json"
    final_schema_reload_receipt_file.write_text("{}\n", encoding="utf-8")
    final_schema_reload_receipt_file.chmod(0o600)
    attestation_hash = hashlib.sha256(attestation_file.read_bytes()).hexdigest()
    pinned_runtime_manifest_hash = hashlib.sha256(
        pinned_runtime_manifest_file.read_bytes()
    ).hexdigest()
    pinned_runtime_rebuild_journal_hash = hashlib.sha256(
        pinned_runtime_rebuild_journal_file.read_bytes()
    ).hexdigest()
    final_schema_reload_receipt_hash = hashlib.sha256(
        final_schema_reload_receipt_file.read_bytes()
    ).hexdigest()
    manifest = {
        "map_application_head": "0058_example",
        "pinned_runtime_manifest_sha256": pinned_runtime_manifest_hash,
        "pinned_runtime_rebuild_journal_sha256": pinned_runtime_rebuild_journal_hash,
        "final_schema_reload_receipt_sha256": final_schema_reload_receipt_hash,
        "files": [
            {
                "path": "journals/sensor.json",
                "sha256": hashlib.sha256(result_file.read_bytes()).hexdigest(),
                "size": result_file.stat().st_size,
            },
            {
                "path": "runtime-attestation.json",
                "sha256": attestation_hash,
                "size": attestation_file.stat().st_size,
            },
            {
                "path": "pinned-runtime-manifest.json",
                "sha256": pinned_runtime_manifest_hash,
                "size": pinned_runtime_manifest_file.stat().st_size,
            },
            {
                "path": "pinned-runtime-rebuild-journal.json",
                "sha256": pinned_runtime_rebuild_journal_hash,
                "size": pinned_runtime_rebuild_journal_file.stat().st_size,
            },
            {
                "path": "final-schema-reload-receipt.json",
                "sha256": final_schema_reload_receipt_hash,
                "size": final_schema_reload_receipt_file.stat().st_size,
            },
        ],
        "finished_at": "2026-07-19T01:01:01+00:00",
        "host_attestation_sha256": attestation_hash,
        "orchestrator_verified": True,
        "playwright_image_id": f"sha256:{'c' * 64}",
        "repository_commit": "d" * 40,
        "status": 0,
        "version": 4,
    }
    _write_json(run / "manifest.json", manifest)

    assert auditor._valid_evidence_manifest(run) is True
    manifest["version"] = 2
    _write_json(run / "manifest.json", manifest)
    assert auditor._valid_evidence_manifest(run) is False
    manifest["version"] = 4
    _write_json(run / "manifest.json", manifest)
    result_file.write_text("tampered\n", encoding="utf-8")
    result_file.chmod(0o600)
    assert auditor._valid_evidence_manifest(run) is False


def test_active_lock_is_detected_across_process_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auditor = _load_auditor()
    monkeypatch.setattr(auditor, "_safe_entry", _portable_safe_entry)
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    lock = root / "orchestrator.lock"
    lock.touch(mode=0o600)
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import fcntl,os,sys; "
                "fd=os.open(sys.argv[1],os.O_RDWR); "
                "fcntl.flock(fd,fcntl.LOCK_EX); "
                "print('locked',flush=True); sys.stdin.read()"
            ),
            str(lock),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        assert auditor.audit_state_root(root).active_lock is True
    finally:
        holder.terminate()
        holder.wait(timeout=5)
        for stream in (holder.stdin, holder.stdout, holder.stderr):
            if stream is not None:
                stream.close()


def test_real_safe_entry_requires_root_owner_and_exact_mode(tmp_path: Path) -> None:
    auditor = _load_auditor()
    target = tmp_path / "entry"
    target.touch(mode=0o600)

    assert auditor._safe_entry(target, directory=False) is (os.geteuid() == 0)
    target.chmod(0o644)
    assert auditor._safe_entry(target, directory=False) is False

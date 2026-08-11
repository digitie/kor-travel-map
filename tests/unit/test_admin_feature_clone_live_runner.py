from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from contextlib import suppress
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATE_HELPER = _REPO_ROOT / "scripts" / "admin_feature_clone_live_state.py"
_RUNNER = _REPO_ROOT / "scripts" / "run-admin-feature-clone-live-acceptance.sh"
_COMMIT = "a" * 40
_RECOVERY_COMMIT = "2" * 40
_API_IMAGE_ID = f"sha256:{'b' * 64}"
_UI_IMAGE_ID = f"sha256:{'1' * 64}"
_PLAYWRIGHT_IMAGE_ID = f"sha256:{'f' * 64}"
_CONTAINER_SHA256 = "c" * 64
_SYSTEM_SHA256 = "d" * 64
_SCHEMA_SHA256 = "3" * 64
_CONTENT_SHA256 = "4" * 64
_DATABASE_SHA256 = "8" * 64
_EXTENSION_SHA256 = "9" * 64
_DUMP_SHA256 = "5" * 64
_DUMP_FILENAME = f"clone-checkpoint-{'6' * 64}.dump"
_CONTENT_CUTOFF = "2026-07-29T00:00:00.000000Z"
_RUN_KEY = "e" * 64
_NETWORK_NAME = f"ktm-afcla-{_RUN_KEY[:12]}-net"
_RUN_ID = "clone-20260729000000-abcdef123456"
_MIGRATION_HEAD = "0066_curation_component_identity"
_CLONE_IDENTITY_SHA256 = hashlib.sha256(
    (
        f"{_CONTAINER_SHA256}\n{_SYSTEM_SHA256}\n15475\n"
        f"{_MIGRATION_HEAD}\n{_DATABASE_SHA256}\n{_EXTENSION_SHA256}\n"
        f"{_SCHEMA_SHA256}\n{_CONTENT_SHA256}\n"
    ).encode()
).hexdigest()


def _run_helper(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_STATE_HELPER), *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def _run_reusable_dump_selector(
    state_root: Path,
    *,
    excluded_path: Path | None = None,
    excluded_sha256: str = "",
    excluded_size: int | None = None,
    normalize_metadata: bool = False,
) -> subprocess.CompletedProcess[str]:
    source = _RUNNER.read_text(encoding="utf-8")
    start = source.index("select_reusable_checkpoint_dump() {")
    end = source.index("\n}\n\nverify_checkpoint_dump() {", start) + 2
    function_source = source[start:end]
    stat_override = (
        "stat() {\n"
        "  case \"$*\" in\n"
        "    *%u:%g:%a*) printf '0:0:600\\n' ;;\n"
        "    *) command stat \"$@\" ;;\n"
        "  esac\n"
        "}\n"
        if normalize_metadata
        else ""
    )
    script = (
        "set -euo pipefail\n"
        'readonly STATE_ROOT="$1"\n'
        "die() { printf '%s\\n' \"$1\" >&2; exit 1; }\n"
        f"{stat_override}"
        f"{function_source}\n"
        'select_reusable_checkpoint_dump "$2" "$3" "$4"\n'
    )
    return subprocess.run(
        [
            "bash",
            "-c",
            script,
            "bash",
            str(state_root),
            str(excluded_path) if excluded_path is not None else "",
            excluded_sha256,
            str(excluded_size) if excluded_size is not None else "",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _write_snapshot(
    path: Path,
    *,
    total: int,
    non_deleted: int = 100,
    schema_sha256: str = _SCHEMA_SHA256,
    content_sha256: str = _CONTENT_SHA256,
) -> None:
    _run_helper(
        "write-snapshot",
        "--path",
        str(path),
        "--active-owned-features",
        "0",
        "--clone-container-sha256",
        _CONTAINER_SHA256,
        "--clone-system-identifier-sha256",
        _SYSTEM_SHA256,
        "--content-cutoff",
        _CONTENT_CUTOFF,
        "--content-sha256",
        content_sha256,
        "--database-sha256",
        _DATABASE_SHA256,
        "--extension-sha256",
        _EXTENSION_SHA256,
        "--feature-non-deleted",
        str(non_deleted),
        "--feature-total",
        str(total),
        "--host-port",
        "15475",
        "--migration-head",
        _MIGRATION_HEAD,
        "--nonterminal-owned-change-requests",
        "0",
        "--relation-count",
        "57",
        "--schema-sha256",
        schema_sha256,
    )


def _write_fixture(
    path: Path,
    *,
    features: int,
    weather: int,
    price: int,
    foreign_key_references: int = 0,
) -> None:
    action = path.stem.removeprefix("direct-")
    path.write_text(
        json.dumps(
            {
                "action": action,
                "counts": {
                    "features": features,
                    "price_values": price,
                    "weather_values": weather,
                },
                "foreign_key_constraints_checked": 12,
                "foreign_key_references": foreign_key_references,
                "version": 1,
            }
        ),
        encoding="utf-8",
    )


def _write_report(directory: Path) -> None:
    directory.mkdir()
    (directory / "c7-results.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<testsuite tests="2">'
        '<testcase classname="c7-redacted" name="auth.setup.ts#1" time="0.100">'
        "</testcase>"
        '<testcase classname="c7-redacted" '
        'name="admin-feature-acceptance-write.live.spec.ts#2" time="0.200">'
        "</testcase>"
        "</testsuite>",
        encoding="utf-8",
    )
    (directory / "c7-summary.html").write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        "<title>C7 redacted result</title><body><h1>C7 redacted result</h1>"
        "<p>result=passed planned=2 observed=2</p><table><thead><tr>"
        "<th>#</th><th>spec</th><th>status</th><th>duration_ms</th>"
        "</tr></thead><tbody>"
        "<tr><td>1</td><td>auth.setup.ts</td><td>passed</td><td>100</td></tr>"
        "<tr><td>2</td><td>admin-feature-acceptance-write.live.spec.ts</td>"
        "<td>passed</td><td>200</td></tr>"
        "</tbody></table></body></html>",
        encoding="utf-8",
    )
    (directory / "c7-summary.json").write_text(
        json.dumps(
            {
                "counts": {"passed": 2},
                "result": "passed",
                "testsObserved": 2,
                "testsPlanned": 2,
                "version": 1,
            }
        ),
        encoding="utf-8",
    )


def _write_failed_main_report(directory: Path) -> None:
    for path in directory.iterdir():
        path.unlink()
    directory.rmdir()
    _write_report(directory)
    (directory / "c7-results.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<testsuite tests="2">'
        '<testcase classname="c7-redacted" name="auth.setup.ts#1" time="0.100">'
        "</testcase>"
        '<testcase classname="c7-redacted" '
        'name="admin-feature-acceptance-write.live.spec.ts#2" time="0.200">'
        "<failure/></testcase>"
        "</testsuite>",
        encoding="utf-8",
    )
    (directory / "c7-summary.html").write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        "<title>C7 redacted result</title><body><h1>C7 redacted result</h1>"
        "<p>result=failed planned=2 observed=2</p><table><thead><tr>"
        "<th>#</th><th>spec</th><th>status</th><th>duration_ms</th>"
        "</tr></thead><tbody>"
        "<tr><td>1</td><td>auth.setup.ts</td><td>passed</td><td>100</td></tr>"
        "<tr><td>2</td><td>admin-feature-acceptance-write.live.spec.ts</td>"
        "<td>failed</td><td>200</td></tr>"
        "</tbody></table></body></html>",
        encoding="utf-8",
    )
    (directory / "c7-summary.json").write_text(
        json.dumps(
            {
                "counts": {"failed": 1, "passed": 1},
                "result": "failed",
                "testsObserved": 2,
                "testsPlanned": 2,
                "version": 1,
            }
        ),
        encoding="utf-8",
    )


def _prepare_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    blocked = tmp_path / "BLOCKED.json"
    startup = runtime / "clone-startup-before.json"
    _write_snapshot(startup, total=120)
    _write_snapshot(runtime / "clone-startup-after.json", total=120)
    _write_snapshot(runtime / "clone-final.json", total=126)
    checkpoint = runtime / "clone-checkpoint.json"
    _run_helper(
        "write-checkpoint",
        "--dump-filename",
        _DUMP_FILENAME,
        "--dump-sha256",
        _DUMP_SHA256,
        "--dump-size",
        "1024",
        "--final-snapshot",
        str(startup),
        "--path",
        str(checkpoint),
        "--restored-snapshot",
        str(startup),
        "--snapshot",
        str(startup),
    )
    checkpoint_sha256 = json.loads(checkpoint.read_text(encoding="utf-8"))[
        "checkpoint_sha256"
    ]
    _run_helper(
        "write-blocked",
        "--path",
        str(blocked),
        "--phase",
        "candidate-startup-pending",
        "--run-id",
        _RUN_ID,
        "--run-key",
        _RUN_KEY,
        "--api-image-id",
        _API_IMAGE_ID,
        "--clone-checkpoint-sha256",
        checkpoint_sha256,
        "--clone-identity-sha256",
        _CLONE_IDENTITY_SHA256,
        "--network-name",
        _NETWORK_NAME,
        "--playwright-image-id",
        _PLAYWRIGHT_IMAGE_ID,
        "--source-commit",
        _COMMIT,
        "--ui-image-id",
        _UI_IMAGE_ID,
    )
    _write_fixture(
        runtime / "direct-seed.json",
        features=2,
        weather=1,
        price=1,
        foreign_key_references=6,
    )
    _write_fixture(
        runtime / "direct-cleanup.json", features=0, weather=0, price=0
    )
    _write_fixture(runtime / "direct-audit.json", features=0, weather=0, price=0)
    (runtime / "api-owned-audit.json").write_text(
        json.dumps(
            {
                "action": "api-audit",
                "counts": {
                    "change_requests": 14,
                    "feature_versions": 13,
                    "features": 6,
                },
                "foreign_key_constraints_checked": 12,
                "foreign_key_references": 19,
                "version": 1,
            }
        ),
        encoding="utf-8",
    )
    (runtime / "auth-audit.json").write_text(
        json.dumps(
            {
                "action": "auth-verify",
                "counts": {"main": 1, "recovery": 1},
                "version": 1,
            }
        ),
        encoding="utf-8",
    )
    _write_report(runtime / "playwright-main")
    _write_report(runtime / "playwright-recovery")
    _run_helper(
        "write-image-evidence",
        "--api-image-id",
        _API_IMAGE_ID,
        "--path",
        str(runtime / "image-evidence.json"),
        "--playwright-image-id",
        _PLAYWRIGHT_IMAGE_ID,
        "--source-commit",
        _COMMIT,
        "--ui-image-id",
        _UI_IMAGE_ID,
    )
    _run_helper(
        "write-resource-state",
        "--no-clone-network-attached",
        "--owned-containers",
        "0",
        "--owned-images",
        "0",
        "--owned-networks",
        "0",
        "--path",
        str(runtime / "resource-final.json"),
    )
    return runtime, blocked


def _complete(
    runtime: Path,
    blocked: Path,
    *,
    phase: str = "passed",
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    arguments = [
        "complete",
        "--blocked-path",
        str(blocked),
        "--phase",
        phase,
        "--result-path",
        str(runtime / "result.json"),
        "--runtime",
        str(runtime),
    ]
    if phase == "recovered":
        current = runtime / "clone-recovery-current.json"
        _write_snapshot(current, total=126)
        arguments.extend(
            [
                "--current-snapshot",
                str(current),
                "--recovery-tool-source-commit",
                _RECOVERY_COMMIT,
            ]
        )
    topic_proof = runtime / "topic-revision-proof.json"
    if topic_proof.exists():
        arguments.extend(
            [
                "--observed-snapshot",
                str(runtime / "clone-final-observed.json"),
                "--topic-revision-proof",
                str(topic_proof),
            ]
        )
        topic_start = runtime / "topic-revision-start.json"
        if topic_start.exists():
            arguments.extend(["--topic-revision-start", str(topic_start)])
    return _run_helper(*arguments, check=check)


def _write_topic_revision_evidence(
    runtime: Path,
    *,
    observed_content_sha256: str,
    normalized_content_sha256: str = _CONTENT_SHA256,
    source: str = "checkpoint-dump",
    start_revision: int = 100,
    current_revision: int = 101,
) -> None:
    checkpoint_sha256 = json.loads(
        (runtime / "clone-checkpoint.json").read_text(encoding="utf-8")
    )["checkpoint_sha256"]
    _write_snapshot(
        runtime / "clone-final-observed.json",
        total=126,
        content_sha256=observed_content_sha256,
    )
    if source == "runtime-start":
        _run_helper(
            "write-topic-revision-start",
            "--checkpoint-sha256",
            checkpoint_sha256,
            "--path",
            str(runtime / "topic-revision-start.json"),
            "--revision",
            str(start_revision),
            "--run-id",
            _RUN_ID,
            "--updated-at",
            "2026-07-29T00:00:00.000000Z",
        )
    _run_helper(
        "write-topic-revision-proof",
        "--checkpoint-sha256",
        checkpoint_sha256,
        "--current-revision",
        str(current_revision),
        "--current-updated-at",
        "2026-07-29T00:00:01.000000Z",
        "--normalized-content-sha256",
        normalized_content_sha256,
        "--observed-content-sha256",
        observed_content_sha256,
        "--path",
        str(runtime / "topic-revision-proof.json"),
        "--run-id",
        _RUN_ID,
        "--source",
        source,
        "--start-revision",
        str(start_revision),
        "--start-updated-at",
        "2026-07-29T00:00:00.000000Z",
    )


def test_complete_validates_evidence_and_clears_blocked(tmp_path: Path) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)

    _complete(runtime, blocked)

    assert not blocked.exists()
    payload = json.loads((runtime / "result.json").read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["phase"] == "passed"
    assert payload["source_commit"] == _COMMIT
    assert payload["recovery_tool_source_commit"] is None
    assert payload["tests"] == {
        "main": {"passed": 2},
        "recovery": {"passed": 2},
    }
    assert payload["phase_history"] == ["candidate-startup-pending"]
    assert payload["cleanup"] == {
        "api_owned_active_features": 0,
        "api_owned_change_requests": 14,
        "api_owned_features": 6,
        "api_owned_feature_versions": 13,
        "api_owned_nonterminal_change_requests": 0,
        "auth_audit_main": 1,
        "auth_audit_recovery": 1,
        "foreign_key_references": 0,
        "owned_features": 0,
        "post_cleanup_audit_features": 0,
        "recovery_auth_reset_main": 0,
        "recovery_auth_reset_recovery": 0,
        "recovery_purged_change_requests": 0,
        "recovery_purged_feature_versions": 0,
        "recovery_purged_features": 0,
    }


def test_complete_recovers_without_rerunning_valid_evidence(tmp_path: Path) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)

    _complete(runtime, blocked, phase="recovered")

    payload = json.loads((runtime / "result.json").read_text(encoding="utf-8"))
    assert not blocked.exists()
    assert payload["phase"] == "recovered"
    assert payload["recovery_tool_source_commit"] == _RECOVERY_COMMIT


@pytest.mark.parametrize(
    ("final_total", "empty_api_audit", "empty_auth_audit", "historical_audit"),
    [
        (120, True, True, "api-checkpoint-restored-auth-checkpoint-restored"),
        (120, False, True, "api-recorded-auth-checkpoint-restored"),
        (126, False, False, "recorded"),
    ],
)
def test_abandon_failed_run_requires_cleaned_failure_evidence(
    tmp_path: Path,
    final_total: int,
    empty_api_audit: bool,
    empty_auth_audit: bool,
    historical_audit: str,
) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    _write_snapshot(
        runtime / "clone-final.json",
        total=final_total,
        content_sha256="7" * 64,
    )
    _write_failed_main_report(runtime / "playwright-main")
    if empty_api_audit:
        (runtime / "api-owned-audit.json").write_bytes(b"")
    if empty_auth_audit:
        (runtime / "auth-audit.json").write_bytes(b"")
    if empty_api_audit or empty_auth_audit:
        (runtime / "playwright-main" / "admin-feature-acceptance-safe-debug.json").write_text(
            json.dumps(
                {
                    "last_browser_fetch_status": 404,
                    "stage": "create-draft",
                }
            ),
            encoding="utf-8",
        )
    for phase in (
        "candidate-startup-running",
        "fixture-seed-running",
        "browser-main-running",
        "browser-recovery-running",
        "direct-cleanup-running",
        "test-failed-restored",
        "failed-resource-finalizing",
    ):
        _run_helper("update-blocked", "--path", str(blocked), "--phase", phase)

    not_restored = _run_helper(
        "abandon-failed-run",
        "--blocked-path",
        str(blocked),
        "--result-path",
        str(runtime / "failed-restored.json"),
        "--restored-snapshot",
        str(runtime / "clone-final.json"),
        "--runtime",
        str(runtime),
        check=False,
    )
    assert not_restored.returncode != 0
    assert "trusted checkpoint" in not_restored.stderr

    _run_helper(
        "abandon-failed-run",
        "--blocked-path",
        str(blocked),
        "--result-path",
        str(runtime / "failed-restored.json"),
        "--restored-snapshot",
        str(runtime / "clone-startup-before.json"),
        "--runtime",
        str(runtime),
    )

    payload = json.loads(
        (runtime / "failed-restored.json").read_text(encoding="utf-8")
    )
    assert not blocked.exists()
    assert payload["status"] == "failed-restored"
    assert payload["historical_audit"] == historical_audit
    assert payload["tests"] == {
        "main": {"failed": 1, "passed": 1},
        "recovery": {"passed": 2},
    }


def test_runner_bootstraps_requested_snapshot_before_validating_mode() -> None:
    source = _RUNNER.read_text(encoding="utf-8")
    bootstrap_gate = 'if [[ "$SCRIPT_DIR" != "$INSTALL_BASE/$SOURCE_COMMIT" ]]; then'
    mode_gate = '[[ "$MODE" == "baseline" || "$MODE" == "checkpoint" ||'

    assert source.index(bootstrap_gate) < source.index(mode_gate)
    assert '"$MODE" == "abort"' in source


def test_failed_run_abort_recreates_clone_identity_before_login_fence() -> None:
    source = _RUNNER.read_text(encoding="utf-8")
    abort_source = source.split('if [[ "$MODE" == "abort" ]]; then', maxsplit=1)[1]
    abort_source = abort_source.split('if [[ "$MODE" == "recover" ]]; then', maxsplit=1)[0]

    assert abort_source.index("BASE_CLONE_CONTAINER_SHA256") < abort_source.index(
        "start_acceptance_login_fence"
    )
    assert abort_source.index("BASE_CLONE_SYSTEM_SHA256") < abort_source.index(
        "start_acceptance_login_fence"
    )
    assert abort_source.index("restore_clone_checkpoint") < abort_source.index(
        "start_acceptance_login_fence"
    )
    assert abort_source.index("verify-checkpoint") < abort_source.index(
        "start_acceptance_login_fence"
    )
    assert abort_source.index("finalize_resources") < abort_source.index(
        "abandon-failed-run"
    )


def test_complete_accepts_bound_runtime_topic_revision_normalization(
    tmp_path: Path,
) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    _write_topic_revision_evidence(
        runtime,
        observed_content_sha256="7" * 64,
        source="runtime-start",
    )

    _complete(runtime, blocked)

    payload = json.loads((runtime / "result.json").read_text(encoding="utf-8"))
    assert not blocked.exists()
    assert payload["phase"] == "passed"
    assert payload["isolation"]["dataset_projection_revision_delta"] == 1
    assert payload["isolation"]["dataset_projection_start_source"] == "runtime-start"


def test_recovery_revalidates_only_legacy_content_digest_drift(
    tmp_path: Path,
) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    _write_snapshot(
        runtime / "clone-final.json",
        total=126,
        content_sha256="7" * 64,
    )
    _run_helper(
        "update-blocked",
        "--path",
        str(blocked),
        "--phase",
        "direct-cleanup-running",
    )
    _write_topic_revision_evidence(
        runtime,
        observed_content_sha256="7" * 64,
    )
    _run_helper(
        "update-blocked",
        "--path",
        str(blocked),
        "--phase",
        "recovery-resource-finalizing",
    )

    _complete(runtime, blocked, phase="recovered")

    payload = json.loads((runtime / "result.json").read_text(encoding="utf-8"))
    assert not blocked.exists()
    assert payload["phase"] == "recovered"
    assert payload["isolation"]["content_sha256"] == _CONTENT_SHA256
    assert payload["isolation"]["dataset_projection_revision_delta"] == 1
    assert (
        payload["isolation"]["dataset_projection_start_source"]
        == "checkpoint-dump"
    )


def test_topic_revision_proof_rejects_non_advancing_revision(tmp_path: Path) -> None:
    runtime, _blocked = _prepare_runtime(tmp_path)
    checkpoint_sha256 = json.loads(
        (runtime / "clone-checkpoint.json").read_text(encoding="utf-8")
    )["checkpoint_sha256"]

    completed = _run_helper(
        "write-topic-revision-proof",
        "--checkpoint-sha256",
        checkpoint_sha256,
        "--current-revision",
        "100",
        "--current-updated-at",
        "2026-07-29T00:00:01.000000Z",
        "--normalized-content-sha256",
        _CONTENT_SHA256,
        "--observed-content-sha256",
        "7" * 64,
        "--path",
        str(runtime / "topic-revision-proof.json"),
        "--run-id",
        _RUN_ID,
        "--source",
        "checkpoint-dump",
        "--start-revision",
        "100",
        "--start-updated-at",
        "2026-07-29T00:00:00.000000Z",
        check=False,
    )

    assert completed.returncode != 0
    assert "revision" in completed.stderr


def test_topic_revision_proof_accepts_multiple_fixture_changes(
    tmp_path: Path,
) -> None:
    runtime, _blocked = _prepare_runtime(tmp_path)

    _write_topic_revision_evidence(
        runtime,
        observed_content_sha256="7" * 64,
        current_revision=102,
    )

    assert (runtime / "topic-revision-proof.json").exists()


def test_checkpoint_dump_topic_proof_rejects_unrelated_final_phase(
    tmp_path: Path,
) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    _write_snapshot(
        runtime / "clone-final.json",
        total=126,
        content_sha256="7" * 64,
    )
    for phase in ("direct-cleanup-running", "browser-main-running"):
        _run_helper(
            "update-blocked",
            "--path",
            str(blocked),
            "--phase",
            phase,
        )
    _write_topic_revision_evidence(
        runtime,
        observed_content_sha256="7" * 64,
    )

    completed = _complete(runtime, blocked, phase="recovered", check=False)

    assert completed.returncode != 0
    assert "실패 당시 최종 snapshot" in completed.stderr
    assert blocked.exists()


def test_recovery_rejects_non_content_snapshot_drift(tmp_path: Path) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    _write_snapshot(
        runtime / "clone-final.json",
        total=126,
        content_sha256="7" * 64,
    )
    _run_helper(
        "update-blocked",
        "--path",
        str(blocked),
        "--phase",
        "direct-cleanup-running",
    )
    _write_topic_revision_evidence(
        runtime,
        observed_content_sha256="7" * 64,
    )
    current = runtime / "clone-recovery-current.json"
    _write_snapshot(
        current,
        total=126,
        content_sha256=_CONTENT_SHA256,
        schema_sha256="6" * 64,
    )

    completed = _run_helper(
        "complete",
        "--blocked-path",
        str(blocked),
        "--current-snapshot",
        str(current),
        "--observed-snapshot",
        str(runtime / "clone-final-observed.json"),
        "--phase",
        "recovered",
        "--recovery-tool-source-commit",
        _RECOVERY_COMMIT,
        "--result-path",
        str(runtime / "result.json"),
        "--runtime",
        str(runtime),
        "--topic-revision-proof",
        str(runtime / "topic-revision-proof.json"),
        check=False,
    )

    assert completed.returncode != 0
    assert "실패 당시 최종 snapshot" in completed.stderr
    assert blocked.exists()


def test_recovered_result_preserves_hard_purge_evidence(tmp_path: Path) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    _run_helper(
        "update-blocked",
        "--path",
        str(blocked),
        "--phase",
        "recovery-hard-purge-running",
    )
    (runtime / "direct-purge-interrupted.json").write_text(
        json.dumps(
            {
                "action": "purge",
                "counts": {
                    "features": 0,
                    "price_values": 0,
                    "weather_values": 0,
                },
                "foreign_key_constraints_checked": 12,
                "foreign_key_references": 0,
                "purged": {
                    "change_requests": 9,
                    "feature_versions": 8,
                    "features": 4,
                },
                "version": 1,
            }
        ),
        encoding="utf-8",
    )

    _complete(runtime, blocked, phase="recovered")

    payload = json.loads((runtime / "result.json").read_text(encoding="utf-8"))
    assert payload["phase_history"] == [
        "candidate-startup-pending",
        "recovery-hard-purge-running",
    ]
    assert payload["cleanup"]["recovery_purged_features"] == 4
    assert payload["cleanup"]["recovery_purged_change_requests"] == 9
    assert payload["cleanup"]["recovery_purged_feature_versions"] == 8


@pytest.mark.parametrize(
    ("mutation", "expected_message"),
    [
        ("startup-schema", "candidate startup"),
        ("checkpoint", "trusted checkpoint"),
        ("resource", "resource cleanup"),
        ("seed-fk", "fixture FK reference"),
        ("xml-identity", "XML test identity"),
        ("xml-tail", "XML test identity"),
        ("html-duration", "XML/HTML duration"),
    ],
)
def test_complete_rejects_false_green_evidence(
    tmp_path: Path,
    mutation: str,
    expected_message: str,
) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    if mutation == "startup-schema":
        _write_snapshot(
            runtime / "clone-startup-after.json",
            total=120,
            schema_sha256="6" * 64,
        )
    elif mutation == "checkpoint":
        checkpoint = json.loads(
            (runtime / "clone-checkpoint.json").read_text(encoding="utf-8")
        )
        checkpoint["baseline"]["content_sha256"] = "7" * 64
        (runtime / "clone-checkpoint.json").write_text(
            json.dumps(checkpoint), encoding="utf-8"
        )
        expected_message = "checkpoint digest"
    elif mutation == "resource":
        _run_helper(
            "write-resource-state",
            "--clone-network-attached",
            "--owned-containers",
            "1",
            "--owned-images",
            "0",
            "--owned-networks",
            "0",
            "--path",
            str(runtime / "resource-final.json"),
        )
    elif mutation == "seed-fk":
        _write_fixture(
            runtime / "direct-seed.json",
            features=2,
            weather=1,
            price=1,
            foreign_key_references=0,
        )
    elif mutation == "xml-identity":
        xml_path = runtime / "playwright-main" / "c7-results.xml"
        xml_path.write_text(
            xml_path.read_text(encoding="utf-8").replace(
                "auth.setup.ts#1", "other.spec.ts#1"
            ),
            encoding="utf-8",
        )
    elif mutation == "xml-tail":
        xml_path = runtime / "playwright-main" / "c7-results.xml"
        xml_path.write_text(
            xml_path.read_text(encoding="utf-8").replace(
                "</testcase><testcase", "</testcase>UNEXPECTED-TAIL<testcase", 1
            ),
            encoding="utf-8",
        )
    elif mutation == "html-duration":
        html_path = runtime / "playwright-main" / "c7-summary.html"
        html_path.write_text(
            html_path.read_text(encoding="utf-8").replace(
                "<td>100</td>", "<td>101</td>", 1
            ),
            encoding="utf-8",
        )

    completed = _complete(runtime, blocked, check=False)

    assert completed.returncode != 0
    assert expected_message in completed.stderr
    assert blocked.exists()
    assert not (runtime / "result.json").exists()


def test_update_blocked_preserves_phase_history(tmp_path: Path) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)

    _run_helper(
        "update-blocked",
        "--path",
        str(blocked),
        "--phase",
        "browser-main-running",
    )

    payload = json.loads(blocked.read_text(encoding="utf-8"))
    assert payload["phase"] == "browser-main-running"
    assert payload["phase_history"] == [
        "candidate-startup-pending",
        "browser-main-running",
    ]
    assert runtime.exists()


def test_checkpoint_allows_only_owned_count_drift_when_requested(
    tmp_path: Path,
) -> None:
    runtime, _blocked = _prepare_runtime(tmp_path)
    drifted = runtime / "drifted.json"
    _write_snapshot(drifted, total=123, non_deleted=97)

    strict = _run_helper(
        "verify-checkpoint",
        "--checkpoint",
        str(runtime / "clone-checkpoint.json"),
        "--snapshot",
        str(drifted),
        check=False,
    )
    owned_drift = _run_helper(
        "verify-checkpoint",
        "--allow-owned-drift",
        "--checkpoint",
        str(runtime / "clone-checkpoint.json"),
        "--snapshot",
        str(drifted),
    )

    assert strict.returncode != 0
    assert len(owned_drift.stdout.strip()) == 64


def test_checkpoint_rejects_dump_restore_snapshot_drift(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    restored = tmp_path / "restored.json"
    _write_snapshot(baseline, total=120)
    _write_snapshot(restored, total=121)

    completed = _run_helper(
        "write-checkpoint",
        "--dump-filename",
        _DUMP_FILENAME,
        "--dump-sha256",
        _DUMP_SHA256,
        "--dump-size",
        "1024",
        "--final-snapshot",
        str(baseline),
        "--path",
        str(tmp_path / "checkpoint.json"),
        "--restored-snapshot",
        str(restored),
        "--snapshot",
        str(baseline),
        check=False,
    )

    assert completed.returncode != 0
    assert "복원 검증 snapshot" in completed.stderr
    assert "fields=feature_total" in completed.stderr


def test_baseline_checkpoint_records_archive_without_claiming_full_restore(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot.json"
    checkpoint = tmp_path / "checkpoint.json"
    _write_snapshot(snapshot, total=120)

    _run_helper(
        "write-baseline-checkpoint",
        "--dump-filename",
        _DUMP_FILENAME,
        "--dump-sha256",
        _DUMP_SHA256,
        "--dump-size",
        "1024",
        "--path",
        str(checkpoint),
        "--snapshot",
        str(snapshot),
    )
    version = _run_helper(
        "read-checkpoint",
        "--checkpoint",
        str(checkpoint),
        "--field",
        "version",
    )
    verified = _run_helper(
        "verify-checkpoint",
        "--checkpoint",
        str(checkpoint),
        "--snapshot",
        str(snapshot),
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))

    assert version.stdout.strip() == "5"
    assert len(verified.stdout.strip()) == 64
    assert "restore_verification" not in payload
    assert payload["recovery_provenance"] == {
        "archive_format": "custom",
        "archive_verified": True,
        "full_restore_verified": False,
    }


def test_baseline_checkpoint_rejects_forged_full_restore_claim(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot.json"
    checkpoint = tmp_path / "checkpoint.json"
    _write_snapshot(snapshot, total=120)
    _run_helper(
        "write-baseline-checkpoint",
        "--dump-filename",
        _DUMP_FILENAME,
        "--dump-sha256",
        _DUMP_SHA256,
        "--dump-size",
        "1024",
        "--path",
        str(checkpoint),
        "--snapshot",
        str(snapshot),
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["recovery_provenance"]["full_restore_verified"] = True
    unsigned = {
        key: value for key, value in payload.items() if key != "checkpoint_sha256"
    }
    payload["checkpoint_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")

    rejected = _run_helper(
        "read-checkpoint",
        "--checkpoint",
        str(checkpoint),
        "--field",
        "version",
        check=False,
    )

    assert rejected.returncode != 0
    assert "archive provenance" in rejected.stderr


def test_reusable_dump_selector_rejects_symlink_and_ambiguous_candidates(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    outside = tmp_path / "outside.dump"
    outside.write_bytes(b"archive")
    symlink = state_root / f"clone-checkpoint-{'1' * 64}.dump"
    symlink.symlink_to(outside)

    unsafe = _run_reusable_dump_selector(
        state_root,
        normalize_metadata=True,
    )

    assert unsafe.returncode != 0
    assert "resume path is unsafe" in unsafe.stderr

    symlink.unlink()
    first = state_root / f"clone-checkpoint-{'2' * 64}.dump"
    second = state_root / f"clone-checkpoint-{'3' * 64}.dump"
    first.write_bytes(b"first")
    second.write_bytes(b"second")

    ambiguous = _run_reusable_dump_selector(
        state_root,
        normalize_metadata=True,
    )

    assert ambiguous.returncode != 0
    assert "resume is ambiguous" in ambiguous.stderr


def test_reusable_dump_selector_validates_metadata_and_excludes_old_dump(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    old_dump = state_root / f"clone-checkpoint-{'4' * 64}.dump"
    candidate = state_root / f"clone-checkpoint-{'5' * 64}.dump"
    old_dump.write_bytes(b"old")
    candidate.write_bytes(b"candidate")
    candidate.chmod(0o644)

    unsafe_metadata = _run_reusable_dump_selector(
        state_root,
        excluded_path=old_dump,
    )
    selected = _run_reusable_dump_selector(
        state_root,
        excluded_path=old_dump,
        normalize_metadata=True,
    )

    assert unsafe_metadata.returncode != 0
    assert "resume metadata is unsafe" in unsafe_metadata.stderr
    assert selected.returncode == 0
    assert selected.stdout == str(candidate)


def test_reusable_dump_selector_excludes_legacy_dump_by_signed_provenance(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    old_dump = state_root / f"clone-checkpoint-{'6' * 64}.dump"
    candidate = state_root / f"clone-checkpoint-{'7' * 64}.dump"
    old_dump.write_bytes(b"legacy-without-filename")
    candidate.write_bytes(b"durable-resume")
    old_digest = hashlib.sha256(old_dump.read_bytes()).hexdigest()

    selected = _run_reusable_dump_selector(
        state_root,
        excluded_sha256=old_digest,
        excluded_size=old_dump.stat().st_size,
        normalize_metadata=True,
    )

    assert selected.returncode == 0
    assert selected.stdout == str(candidate)


def test_checkpoint_rejects_source_drift_after_restore(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    restored = tmp_path / "restored.json"
    final = tmp_path / "final.json"
    _write_snapshot(baseline, total=120)
    _write_snapshot(restored, total=120)
    _write_snapshot(final, total=121)

    completed = _run_helper(
        "write-checkpoint",
        "--dump-filename",
        _DUMP_FILENAME,
        "--dump-sha256",
        _DUMP_SHA256,
        "--dump-size",
        "1024",
        "--final-snapshot",
        str(final),
        "--path",
        str(tmp_path / "checkpoint.json"),
        "--restored-snapshot",
        str(restored),
        "--snapshot",
        str(baseline),
        check=False,
    )

    assert completed.returncode != 0
    assert "원본 clone snapshot" in completed.stderr
    assert "fields=feature_total" in completed.stderr


def test_legacy_v2_checkpoint_is_validated_and_promoted_to_v4(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot.json"
    checkpoint = tmp_path / "checkpoint.json"
    _write_snapshot(snapshot, total=120)
    _run_helper(
        "write-checkpoint",
        "--dump-filename",
        _DUMP_FILENAME,
        "--dump-sha256",
        _DUMP_SHA256,
        "--dump-size",
        "1024",
        "--final-snapshot",
        str(snapshot),
        "--path",
        str(checkpoint),
        "--restored-snapshot",
        str(snapshot),
        "--snapshot",
        str(snapshot),
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload.pop("source_stability")
    payload.pop("write_quiescence")
    payload["version"] = 2
    unsigned = {
        key: value for key, value in payload.items() if key != "checkpoint_sha256"
    }
    payload["checkpoint_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")

    version_before = _run_helper(
        "read-checkpoint",
        "--checkpoint",
        str(checkpoint),
        "--field",
        "version",
    )
    _run_helper(
        "promote-checkpoint",
        "--checkpoint",
        str(checkpoint),
        "--final-snapshot",
        str(snapshot),
        "--path",
        str(checkpoint),
    )
    promoted = json.loads(checkpoint.read_text(encoding="utf-8"))

    assert version_before.stdout.strip() == "2"
    assert promoted["version"] == 4
    assert promoted["source_stability"]["verified"] is True
    assert promoted["write_quiescence"] == {
        "cluster_single_login_role_fenced": True,
        "relation_share_locks": True,
        "verified": True,
    }


def test_legacy_v3_checkpoint_is_validated_and_promoted_to_v4(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot.json"
    checkpoint = tmp_path / "checkpoint.json"
    _write_snapshot(snapshot, total=120)
    _run_helper(
        "write-checkpoint",
        "--dump-filename",
        _DUMP_FILENAME,
        "--dump-sha256",
        _DUMP_SHA256,
        "--dump-size",
        "1024",
        "--final-snapshot",
        str(snapshot),
        "--path",
        str(checkpoint),
        "--restored-snapshot",
        str(snapshot),
        "--snapshot",
        str(snapshot),
    )
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    payload["version"] = 3
    payload["write_quiescence"] = {
        "database_default_read_only": True,
        "relation_share_locks": True,
        "verified": True,
    }
    unsigned = {
        key: value for key, value in payload.items() if key != "checkpoint_sha256"
    }
    payload["checkpoint_sha256"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    checkpoint.write_text(json.dumps(payload), encoding="utf-8")

    version_before = _run_helper(
        "read-checkpoint",
        "--checkpoint",
        str(checkpoint),
        "--field",
        "version",
    )
    _run_helper(
        "promote-checkpoint",
        "--checkpoint",
        str(checkpoint),
        "--final-snapshot",
        str(snapshot),
        "--path",
        str(checkpoint),
    )
    promoted = json.loads(checkpoint.read_text(encoding="utf-8"))

    assert version_before.stdout.strip() == "3"
    assert promoted["version"] == 4
    assert promoted["write_quiescence"] == {
        "cluster_single_login_role_fenced": True,
        "relation_share_locks": True,
        "verified": True,
    }


def test_checkpoint_scratch_ownership_is_durable_and_identity_bound(
    tmp_path: Path,
) -> None:
    state = tmp_path / "scratch.json"
    identity_args = (
        "--clone-container-sha256",
        _CONTAINER_SHA256,
        "--clone-system-identifier-sha256",
        _SYSTEM_SHA256,
        "--path",
        str(state),
    )
    database = f"ktm_checkpoint_{'7' * 24}"
    owner_role = f"ktm_checkpoint_owner_{'9' * 24}"
    ownership_token = "8" * 64
    _run_helper(
        "write-scratch",
        *identity_args,
        "--database",
        database,
        "--ownership-token",
        ownership_token,
        "--owner-role",
        owner_role,
    )

    intent_version = _run_helper(
        "read-scratch", *identity_args, "--field", "version"
    )
    unclaimed_oid = _run_helper(
        "read-scratch",
        *identity_args,
        "--field",
        "database_oid",
        check=False,
    )
    _run_helper(
        "claim-scratch",
        *identity_args,
        "--database-oid",
        "16384",
        "--owner-role-oid",
        "16385",
    )
    observed_database = _run_helper(
        "read-scratch", *identity_args, "--field", "database"
    )
    observed_token = _run_helper(
        "read-scratch", *identity_args, "--field", "ownership_token"
    )
    observed_oid = _run_helper(
        "read-scratch", *identity_args, "--field", "database_oid"
    )
    observed_role = _run_helper(
        "read-scratch", *identity_args, "--field", "owner_role"
    )
    observed_role_oid = _run_helper(
        "read-scratch", *identity_args, "--field", "owner_role_oid"
    )
    claimed_version = _run_helper(
        "read-scratch", *identity_args, "--field", "version"
    )
    rejected = _run_helper(
        "read-scratch",
        "--clone-container-sha256",
        "0" * 64,
        "--clone-system-identifier-sha256",
        _SYSTEM_SHA256,
        "--path",
        str(state),
        "--field",
        "database",
        check=False,
    )
    _run_helper("clear-scratch", *identity_args)

    assert intent_version.stdout.strip() == "4"
    assert unclaimed_oid.returncode != 0
    assert observed_database.stdout.strip() == database
    assert observed_token.stdout.strip() == ownership_token
    assert observed_oid.stdout.strip() == "16384"
    assert observed_role.stdout.strip() == owner_role
    assert observed_role_oid.stdout.strip() == "16385"
    assert claimed_version.stdout.strip() == "5"
    assert rejected.returncode != 0
    assert not state.exists()


def test_checkpoint_quiescence_state_is_durable_and_identity_bound(
    tmp_path: Path,
) -> None:
    state = tmp_path / "quiescence.json"
    identity_args = (
        "--clone-container-sha256",
        _CONTAINER_SHA256,
        "--clone-system-identifier-sha256",
        _SYSTEM_SHA256,
        "--path",
        str(state),
    )
    _run_helper(
        "write-quiescence",
        *identity_args,
        "--application-name",
        f"ktm_checkpoint_{'a' * 16}",
        "--database",
        "kor_travel_map_clone",
    )
    database = _run_helper(
        "read-quiescence", *identity_args, "--field", "database"
    )
    setting = _run_helper(
        "read-quiescence", *identity_args, "--field", "fence"
    )
    application_name = _run_helper(
        "read-quiescence", *identity_args, "--field", "application_name"
    )
    rejected = _run_helper(
        "read-quiescence",
        "--clone-container-sha256",
        "0" * 64,
        "--clone-system-identifier-sha256",
        _SYSTEM_SHA256,
        "--path",
        str(state),
        "--field",
        "database",
        check=False,
    )
    _run_helper("clear-quiescence", *identity_args)

    assert database.stdout.strip() == "kor_travel_map_clone"
    assert setting.stdout.strip() == "cluster_single_login_role_password_rotation"
    assert application_name.stdout.strip() == f"ktm_checkpoint_{'a' * 16}"
    assert rejected.returncode != 0
    assert not state.exists()


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_checkpoint_quiescence_state_remains_recoverable(
    tmp_path: Path,
    version: int,
) -> None:
    state = tmp_path / "quiescence.json"
    payload: dict[str, object] = {
        "clone_container_sha256": _CONTAINER_SHA256,
        "clone_system_identifier_sha256": _SYSTEM_SHA256,
        "database": "kor_travel_map_clone",
        "version": version,
    }
    if version == 1:
        payload["setting"] = "default_transaction_read_only=on"
    else:
        payload["application_name"] = f"ktm_checkpoint_{'b' * 16}"
        payload["fence"] = "database_role_password_rotation"
    state.write_text(json.dumps(payload), encoding="utf-8")
    identity_args = (
        "--clone-container-sha256",
        _CONTAINER_SHA256,
        "--clone-system-identifier-sha256",
        _SYSTEM_SHA256,
        "--path",
        str(state),
    )

    observed = _run_helper(
        "read-quiescence", *identity_args, "--field", "version"
    )
    _run_helper("clear-quiescence", *identity_args)

    assert observed.stdout.strip() == str(version)
    assert not state.exists()


def test_runner_closes_reviewed_trust_boundaries() -> None:
    source = _RUNNER.read_text(encoding="utf-8")
    recovery_source = source.split(
        'if [[ "$MODE" == "recover" ]]; then', maxsplit=1
    )[1].split('[[ ! -e "$BLOCKED_FILE"', maxsplit=1)[0]

    assert "E2E_REPOSITORY_ROOT" not in source
    assert ".venv/bin/alembic" not in source
    assert "git_repo" not in source
    assert "git status" not in source
    assert "source.tar.gz" in source
    assert "github.com/digitie/kor-travel-map/archive" in source
    assert "--proto '=https' --proto-redir '=https'" in source
    assert 'readonly BOOTSTRAP_LOCK_FILE="$INSTALL_BASE/bootstrap.lock"' in source
    assert "coproc BOOTSTRAP_LOCK_GUARD" in source
    assert "mv -T --no-clobber" in source
    assert 'validate_snapshot "$SOURCE_COMMIT" "$expected_root"' in source
    assert "-name '.incoming-*'" in source
    assert (
        r"^\.incoming-[0-9a-f]{40}-[0-9]+(-[0-9a-f]{12})?$"
        in source
    )
    assert "DOCKER_HOST DOCKER_TLS_VERIFY" in source
    assert "coproc ORCHESTRATOR_LOCK_GUARD" in source
    assert 'flock --exclusive --nonblock "$LOCK_FILE"' in source
    assert 'exec 9<>"$LOCK_FILE"' not in source
    assert "9>&-" not in source
    assert "candidate-startup-pending" in source
    assert source.rindex("state_helper write-blocked") < source.rindex(
        "create_candidate_network"
    )
    assert 'docker network create --internal \\' in source
    assert "owned_network_identity" in source
    assert "candidate network ownership label mismatch" in source
    assert '--network "$NETWORK_NAME"' in source
    assert source.count("--network host") == 1
    assert "-e PGPASSWORD=" not in source
    assert '"$E2E_ADMIN_PASSWORD" "$RUN_ID"' not in source
    assert "--build-arg NEXT_PUBLIC_VWORLD_API_KEY" in source
    assert "schema_sha256" in source
    assert "content_sha256" in source
    assert "ops_live_topic_revisions" in source
    assert "dataset projection revision did not advance" in source
    assert "--table=ops_live_topic_revisions" in source
    assert "write-topic-revision-proof" in source
    assert "c7-loopback-ui-proxy.mjs" in source
    assert '"$ARCHIVE_PREFIX/scripts/c7-loopback-ui-proxy.mjs"' in source
    assert 'src=$LOOPBACK_PROXY_HELPER,dst=/opt/c7-loopback-ui-proxy.mjs,readonly' in source
    assert "node /opt/c7-loopback-ui-proxy.mjs" in source
    assert "legacy current snapshot lacks the loopback proxy source" in source
    assert "runtime loopback proxy differs from the immutable archive" in source
    assert "existing runtime loopback proxy is unsafe" in source
    assert "source commit 간 retry도 fail-closed로 수렴한다" in source
    assert "api_audit_status=0" in source
    assert (
        'run_helper api-audit "$RUNTIME_DIR/api-owned-audit.json" '
        "|| api_audit_status=$?" in source
    )
    assert "Playwright or fixture acceptance failed after cleanup" in source
    assert 'E2E_BASE_URL=http://127.0.0.1:$LOOPBACK_UI_PORT' in source
    assert 'KTM_C7_LOOPBACK_UI_PROXY_TARGET=http://candidate-ui:$UI_PORT' in source
    assert "hashtextextended(row_value::text" in source
    assert "attribute.attidentity" in source
    assert "attribute.attgenerated" in source
    assert "trigger_row.tgenabled" in source
    assert "relation.relowner::regrole::text" in source
    assert "pg_catalog.pg_default_acl" in source
    assert "database_sha256" in source
    assert "'<database-owner>'" in source
    assert "owner.rolname = '$db_user'" in source
    assert "extension_sha256" in source
    assert "unnest(extension.extconfig) WITH ORDINALITY" in source
    assert "config_namespace.nspname" in source
    assert "config_relation.relname" in source
    assert "extension.extconfig::text" not in source
    assert 'MODE" == "baseline"' in source
    assert "state_helper write-baseline-checkpoint" in source
    assert "pg_get_functiondef" in source
    assert "pg_get_viewdef" in source
    assert "pg_catalog.pg_policy" in source
    assert "pg_dump --format=custom" in source
    assert "pg_restore --exit-on-error --single-transaction" in source
    assert "--restored-snapshot" in source
    assert "--final-snapshot" in source
    assert "start_checkpoint_quiescence" in source
    assert "LOCK TABLE %I.%I IN SHARE MODE" in source
    assert "set_clone_database_password" in source
    assert "clone_host_tcp_password_works" in source
    assert '-p "$DB_HOST_PORT"' in source
    assert "checkpoint_login_role_invariant" in source
    assert "terminate_foreign_cluster_sessions" in source
    assert "CHECKPOINT_QUIESCENCE_BACKEND_PID" in source
    assert "CHECKPOINT_QUIESCENCE_BACKEND_START_EPOCH" in source
    assert "extract(epoch FROM backend_start)" in source
    assert "application_name <> '$CHECKPOINT_QUIESCENCE_APP'" not in source
    assert 'clone_host_tcp_password_works "$CHECKPOINT_FENCE_PASSWORD"' in source
    assert "terminate_checkpoint_backends" in source
    assert "state_helper write-quiescence" in source
    assert "state_helper promote-checkpoint" in source
    assert "state_helper write-scratch" in source
    assert "state_helper claim-scratch" in source
    assert 'CREATE ROLE \\"$VERIFICATION_OWNER_ROLE\\"' in source
    assert '--owner="$VERIFICATION_OWNER_ROLE"' in source
    assert "shobj_description" in source
    assert "recover_verification_database" in source
    assert "fsync_file_and_directory" in source
    assert "verify_checkpoint_dump" in source
    assert "checkpoint_references_dump" in source
    assert "select_reusable_checkpoint_dump" in source
    assert "checkpoint dump resume is ambiguous" in source
    assert source.count("remove_unreferenced_checkpoint_dumps") >= 5
    assert "docker network create --internal" in source
    assert "'{{.Internal}}'" in source
    assert "clone-recovery-current.json" in source
    assert "playwright-interruption-cleanup" in source
    assert "recovery-hard-purge-running" in source
    assert 'run_helper purge "$RUNTIME_DIR/direct-purge-interrupted.json"' in source
    assert 'run_helper auth-reset "$RUNTIME_DIR/auth-audit-reset.json"' in source
    assert recovery_source.index("BLOCKED_WRITTEN=1") < recovery_source.index(
        "load_blocked"
    )
    assert "if state_helper verify-checkpoint \\" in recovery_source
    assert "--allow-owned-drift" in recovery_source
    assert recovery_source.index("if state_helper verify-checkpoint") < recovery_source.index(
        "state_helper validate-evidence"
    ) < recovery_source.index('for image in "$API_IMAGE_ID"')
    assert recovery_source.index("remove_owned_containers") < recovery_source.index(
        "recover_checkpoint_quiescence"
    )
    assert 'docker image rm "$tag"' in source
    assert 'docker image rm --force "${images[@]}"' not in source
    assert source.rindex("finalize_resources") < source.rindex(
        "state_helper complete"
    )
    assert "refresh_blocked_written_from_durable_state" in source
    cleanup_source = source.split("cleanup_on_exit() {", maxsplit=1)[1].split(
        "trap cleanup_on_exit EXIT", maxsplit=1
    )[0]
    assert cleanup_source.index(
        "refresh_blocked_written_from_durable_state"
    ) < cleanup_source.index("remove_owned_containers")
    normal_source = source.rsplit(
        '[[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]]',
        maxsplit=1,
    )[1]
    assert normal_source.index("start_acceptance_login_fence") < normal_source.index(
        'write_snapshot "$RUNTIME_DIR/clone-startup-before.json"'
    )
    assert normal_source.index(
        "assert_acceptance_login_fence_after_resources"
    ) < normal_source.index("stop_checkpoint_quiescence")
    assert normal_source.index("stop_checkpoint_quiescence") < normal_source.index(
        "state_helper complete"
    )
    assert "alembic upgrade" not in source
    assert "E2E_LIVE_ALLOW_PROD" not in source
    assert "E2E_ISOLATED_LIVE_DOCKER_NETWORK=1" in source


def test_orchestrator_guardian_lock_is_not_inherited_by_external_child(
    tmp_path: Path,
) -> None:
    """runner SIGKILL 뒤에도 장시간 외부 자식이 guardian flock을 붙잡지 않는다."""
    harness = tmp_path / "lock-owner.sh"
    lock_path = tmp_path / "orchestrator.lock"
    harness.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
lock_path="$1"
coproc LOCK_GUARD {
  flock --exclusive --nonblock "$lock_path" \
    /bin/sh -c 'printf "locked\\n"; IFS= read -r _'
}
IFS= read -r lock_status <&"${LOCK_GUARD[0]}"
[[ "$lock_status" == "locked" ]]
sleep 30 &
printf '%s\\n' "$!"
wait
""",
        encoding="utf-8",
    )
    harness.chmod(0o755)
    process = subprocess.Popen(
        [str(harness), str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    grandchild_pid = int(process.stdout.readline())
    try:
        os.kill(process.pid, signal.SIGKILL)
        process.wait(timeout=5)
        reacquired = subprocess.run(
            ["flock", "--exclusive", "--nonblock", str(lock_path), "true"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert reacquired.returncode == 0
        os.kill(grandchild_pid, 0)
    finally:
        with suppress(ProcessLookupError):
            os.kill(grandchild_pid, signal.SIGTERM)
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


@pytest.mark.parametrize("unsafe_entry", ["trace.zip", "screenshot.png", "extra.json"])
def test_complete_rejects_extra_browser_evidence(
    tmp_path: Path,
    unsafe_entry: str,
) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    (runtime / "playwright-main" / unsafe_entry).write_text(
        "unsafe", encoding="utf-8"
    )

    completed = _complete(runtime, blocked, check=False)

    assert completed.returncode != 0
    assert blocked.exists()

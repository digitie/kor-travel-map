"""#741/#785/T-VN-15 targeted production live lane의 정적 복구 계약."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _ROOT / "scripts" / "run-admin-feature-live-acceptance.sh"
_STATE = _ROOT / "scripts" / "admin_feature_live_state.py"
_SUPERVISOR = _ROOT / "scripts" / "admin_feature_live_supervisor.py"
_ATTESTATION = _ROOT / "scripts" / "lib" / "c7_prod_attestation.py"
_LIVE_CONFIG = (
    _ROOT
    / "packages"
    / "kor-travel-map-admin"
    / "frontend"
    / "playwright.live.config.ts"
)
_SPEC = (
    _ROOT
    / "packages"
    / "kor-travel-map-admin"
    / "frontend"
    / "e2e"
    / "live"
    / "admin-feature-acceptance-write.live.spec.ts"
)
_C7_RUNNER = _ROOT / "scripts" / "run-c7-prod-live-e2e.sh"

_ORIGIN_EXECUTION = {
    "api_image_id": "sha256:" + "1" * 64,
    "final_schema_reload_receipt_sha256": "c" * 64,
    "host_attestation_sha256": "3" * 64,
    "pinned_runtime_manifest_sha256": "2" * 64,
    "pinned_runtime_rebuild_journal_sha256": "6" * 64,
    "playwright_image_id": "sha256:" + "4" * 64,
    "source_commit": "5" * 40,
}
_RECOVERY_EXECUTION = {
    "api_image_id": "sha256:" + "6" * 64,
    "final_schema_reload_receipt_sha256": "d" * 64,
    "host_attestation_sha256": "8" * 64,
    "pinned_runtime_manifest_sha256": "7" * 64,
    "pinned_runtime_rebuild_journal_sha256": "b" * 64,
    "playwright_image_id": "sha256:" + "9" * 64,
    "source_commit": "a" * 40,
}


def _load_script_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name,
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_STATE_MODULE = _load_script_module("admin_feature_live_state", _STATE)
_SUPERVISOR_MODULE = _load_script_module(
    "admin_feature_live_supervisor",
    _SUPERVISOR,
)

def _execution_args(path: Path, identity: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        api_image_id=identity["api_image_id"],
        final_schema_reload_receipt_sha256=identity["final_schema_reload_receipt_sha256"],
        host_attestation_sha256=identity["host_attestation_sha256"],
        path=path,
        pinned_runtime_manifest_sha256=identity["pinned_runtime_manifest_sha256"],
        pinned_runtime_rebuild_journal_sha256=identity[
            "pinned_runtime_rebuild_journal_sha256"
        ],
        playwright_image_id=identity["playwright_image_id"],
        source_commit=identity["source_commit"],
    )


def test_blocked_v4_records_execution_identity() -> None:
    payload = _STATE_MODULE._blocked_payload(  # noqa: SLF001
        "live-20260726010101-abcdef123456",
        0,
        "browser-running",
        "blocked",
        _ORIGIN_EXECUTION,
    )

    assert set(payload) == {
        "execution",
        "owned_feature_ids",
        "phase",
        "recorded_at",
        "recovery_attempt",
        "run_id",
        "status",
        "version",
    }
    assert payload["version"] == 5
    assert payload["execution"] == _ORIGIN_EXECUTION


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase", "invalid phase"),
        ("recorded_at", "not-a-timestamp"),
        ("status", "complete"),
    ],
)
def test_blocked_v4_rejects_malformed_control_fields(
    field: str,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _STATE_MODULE._blocked_payload(  # noqa: SLF001
        "live-20260726010101-abcdef123456",
        0,
        "browser-running",
        "blocked",
        _ORIGIN_EXECUTION,
    )
    payload[field] = value
    monkeypatch.setattr(_STATE_MODULE, "_read_root_json", lambda _path: payload)

    with pytest.raises(ValueError, match="invalid BLOCKED state"):
        _STATE_MODULE._validated_blocked(tmp_path / "BLOCKED.json")  # noqa: SLF001


def test_legacy_blocked_v3_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _STATE_MODULE._blocked_payload(  # noqa: SLF001
        "live-20260726010101-abcdef123456",
        0,
        "browser-running",
        "blocked",
        _ORIGIN_EXECUTION,
    )
    payload["version"] = 4
    payload.pop("execution")
    monkeypatch.setattr(_STATE_MODULE, "_read_root_json", lambda _path: payload)

    with pytest.raises(ValueError, match="invalid BLOCKED state"):
        _STATE_MODULE._validated_blocked(tmp_path / "BLOCKED.json")  # noqa: SLF001


def test_write_blocked_rejects_execution_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blocked_path = tmp_path / "BLOCKED.json"
    blocked_path.touch()
    blocked = _STATE_MODULE._blocked_payload(  # noqa: SLF001
        "live-20260726010101-abcdef123456",
        2,
        "recovery-running",
        "blocked",
        _ORIGIN_EXECUTION,
    )
    monkeypatch.setattr(_STATE_MODULE, "_validated_blocked", lambda _path: blocked)
    args = _execution_args(blocked_path, _RECOVERY_EXECUTION)
    args.phase = "recovery-failed"
    args.recovery_attempt = 2
    args.run_id = blocked["run_id"]
    args.status = "blocked"

    with pytest.raises(ValueError, match="blocked identity changed"):
        _STATE_MODULE._write_blocked(args)  # noqa: SLF001


def test_bash_pending_term_observes_disarmed_signal_guard() -> None:
    subprocess.run(
        [
            "bash",
            "-c",
            "set -euo pipefail; RUN_ID=owned; blocked=present; "
            "finish_signal() { [[ -z \"$RUN_ID\" ]] || blocked=recreated; }; "
            "trap finish_signal TERM; RUN_ID=\"\"; "
            "bash -c 'kill -TERM \"$PPID\"'; [[ \"$blocked\" == present ]]",
        ],
        check=True,
    )


def test_recovery_requires_and_preserves_exact_execution_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blocked = _STATE_MODULE._blocked_payload(  # noqa: SLF001
        "live-20260726010101-abcdef123456",
        2,
        "test-failed-restored",
        "blocked",
        _ORIGIN_EXECUTION,
    )
    written: dict[str, object] = {}
    monkeypatch.setattr(
        _STATE_MODULE,
        "_validated_blocked",
        lambda _path: blocked,
    )
    monkeypatch.setattr(
        _STATE_MODULE,
        "_atomic_write",
        lambda path, payload: written.update(path=path, payload=payload),
    )

    _STATE_MODULE._begin_recovery(  # noqa: SLF001
        _execution_args(tmp_path / "BLOCKED.json", _ORIGIN_EXECUTION)
    )

    assert written["path"] == tmp_path / "BLOCKED.json"
    recovered = written["payload"]
    assert isinstance(recovered, dict)
    assert recovered["execution"] == _ORIGIN_EXECUTION
    assert recovered["recovery_attempt"] == 3
    assert recovered["phase"] == "recovery_claimed"


def test_recovery_rejects_execution_identity_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    blocked = _STATE_MODULE._blocked_payload(  # noqa: SLF001
        "live-20260726010101-abcdef123456",
        2,
        "test-failed-restored",
        "blocked",
        _ORIGIN_EXECUTION,
    )
    monkeypatch.setattr(_STATE_MODULE, "_validated_blocked", lambda _path: blocked)

    with pytest.raises(ValueError, match="recovery execution identity changed"):
        _STATE_MODULE._begin_recovery(  # noqa: SLF001
            _execution_args(tmp_path / "BLOCKED.json", _RECOVERY_EXECUTION)
        )


def test_result_v4_durably_preserves_execution_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "live-20260726010101-abcdef123456"
    blocked_path = tmp_path / "BLOCKED.json"
    blocked = _STATE_MODULE._blocked_payload(  # noqa: SLF001
        run_id,
        3,
        "recovery-running",
        "blocked",
        _ORIGIN_EXECUTION,
    )
    written: dict[str, object] = {}
    monkeypatch.setattr(
        _STATE_MODULE,
        "_validated_blocked",
        lambda path: blocked if path == blocked_path else pytest.fail("wrong BLOCKED path"),
    )
    monkeypatch.setattr(
        _STATE_MODULE,
        "_atomic_write",
        lambda path, payload: written.update(path=path, payload=payload),
    )
    args = _execution_args(blocked_path, _ORIGIN_EXECUTION)
    args.blocked_path = blocked_path
    args.path = tmp_path / "result.json"
    args.phase = "recovered"
    args.recovery_attempt = 3
    args.run_id = run_id
    args.status = "complete"

    _STATE_MODULE._write_result(args)  # noqa: SLF001

    assert written["path"] == tmp_path / "result.json"
    result = written["payload"]
    assert isinstance(result, dict)
    assert set(result) == {
        "execution_identity_sha256",
        "final_schema_reload_receipt_sha256",
        "host_attestation_sha256",
        "owned_feature_id_sha256",
        "phase",
        "pinned_runtime_manifest_sha256",
        "pinned_runtime_rebuild_journal_sha256",
        "recorded_at",
        "recovery_attempt",
        "run_id_sha256",
        "status",
        "version",
    }
    assert result["version"] == 5
    assert result["execution_identity_sha256"] == (
        _STATE_MODULE._execution_identity_sha256(_ORIGIN_EXECUTION)  # noqa: SLF001
    )
    assert result["pinned_runtime_manifest_sha256"] == "2" * 64
    assert result["pinned_runtime_rebuild_journal_sha256"] == "6" * 64
    assert result["final_schema_reload_receipt_sha256"] == "c" * 64
    assert result["host_attestation_sha256"] == "3" * 64


def test_result_rejects_execution_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_id = "live-20260726010101-abcdef123456"
    blocked_path = tmp_path / "BLOCKED.json"
    blocked = _STATE_MODULE._blocked_payload(  # noqa: SLF001
        run_id,
        3,
        "recovery-running",
        "blocked",
        _ORIGIN_EXECUTION,
    )
    monkeypatch.setattr(_STATE_MODULE, "_validated_blocked", lambda _path: blocked)
    args = _execution_args(blocked_path, _RECOVERY_EXECUTION)
    args.blocked_path = blocked_path
    args.path = tmp_path / "result.json"
    args.phase = "recovered"
    args.recovery_attempt = 3
    args.run_id = run_id
    args.status = "complete"

    with pytest.raises(ValueError, match="result does not match BLOCKED state"):
        _STATE_MODULE._write_result(args)  # noqa: SLF001


def test_runner_disarms_signal_guard_before_blocked_clear() -> None:
    runner = _RUNNER.read_text()
    recover = runner[runner.index("recover_run() {") : runner.index("run_new() {")]
    run_new = runner[runner.index("run_new() {") :]
    for body in (recover, run_new):
        assert body.index("  RUN_ID=\"\"") < body.index(
            "  state_helper clear-blocked --path \"$BLOCKED_FILE\""
        )
    assert '    --blocked-path "$BLOCKED_FILE" \\' in runner
    assert runner.count('"${EXECUTION_IDENTITY_ARGS[@]}"') == 3
    assert _STATE.read_text().count("_add_execution_identity_arguments(") == 4


def test_targeted_lane_is_not_part_of_strict_c7_runner() -> None:
    assert "admin-feature-acceptance-write" not in _C7_RUNNER.read_text()


def test_runner_uses_trusted_c7_v4_v5_v7_runtime_attestation_before_state() -> None:
    runner = _RUNNER.read_text()
    state = _STATE.read_text()
    attestation = _ATTESTATION.read_text()
    validate = runner.index("  state_helper validate-c7-module")
    runtime = runner.index('    python3 -I -B "$c7_module" runtime')
    initialize = runner.rindex("\ninitialize_state\n")
    assert validate < runtime < initialize
    assert 'readonly HOST_ATTESTATION_FILE="/etc/kor-travel-map/' in runner
    assert 'readonly C7_INSTALL_BASE="/usr/local/lib/kor-travel-map/c7-runner"' in runner
    assert 'attestation.get("version") != 5' in state
    assert 'manifest["version"] != 5' in attestation
    assert 'value["version"] != 7' in attestation
    assert 'value["phase"] != "committed"' in attestation
    assert 'value["stage"] != "finalized"' in attestation
    assert 'active["map_source_revision"] != source_commits["map"]' in attestation
    assert 'compose_project_hashes != {attestation["compose_project_sha256"]}' in attestation
    assert 'environment_sha256 != expected["environment_sha256"]' in attestation
    assert 'command_sha256 != expected["command_sha256"]' in attestation
    assert 'observed_images[role] != active[field]' in attestation
    assert '_public_origin(environ["E2E_BASE_URL"])' in attestation
    assert 'E2E_C7_PINNED_RUNTIME_MANIFEST' in runner
    assert 'E2E_C7_PINNED_RUNTIME_REBUILD_JOURNAL' in runner
    assert 'E2E_C7_FINAL_SCHEMA_RELOAD_RECEIPT' in runner
    assert 'E2E_C7_COMPATIBLE_PAIR_MANIFEST' not in runner
    assert 'E2E_C7_EXPECTED_GIT_COMMIT' in runner


def test_cursor_secret_is_attested_and_fail_closed_on_exact_api_image() -> None:
    runner = _RUNNER.read_text()
    supervisor = _SUPERVISOR.read_text()
    attestation = _ATTESTATION.read_text()
    assert 'role != "map_api"' in attestation
    assert 'cursor secret escaped API runtime' in attestation
    assert 'environment.get("KOR_TRAVEL_MAP_API_PROFILE") != "production"' in attestation
    assert 'environment.get("KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED") != "true"' in attestation
    assert "len(cursor) < 32" in attestation
    assert "character.isspace()" in attestation
    assert "cursor in protected" in attestation
    assert 'API_IMAGE_ID="$(docker inspect' in runner
    assert 'run_supervisor probe probe-cursor-missing' in runner
    assert '"--network",\n            "none"' in supervisor
    assert '"--read-only"' in supervisor
    assert 'KOR_TRAVEL_MAP_API_PROFILE=production' in supervisor
    assert 'KOR_TRAVEL_MAP_API_FEATURES_ROUTES_ENABLED=true' in supervisor
    assert 'KOR_TRAVEL_MAP_API_OPS_ROUTES_ENABLED=false' in supervisor
    assert "KOR_TRAVEL_MAP_API_CURSOR_SIGNING_SECRET=" not in supervisor
    assert "API cursor fail-closed probe mismatch" in supervisor
    assert '"phase": "entrypoint-pre-migration"' in _STATE.read_text()


def test_sigkill_safe_supervisor_owns_docker_lifecycle_and_barrier() -> None:
    runner = _RUNNER.read_text()
    supervisor = _SUPERVISOR.read_text()
    state = _STATE.read_text()
    assert 'exec {BARRIER_FD}>"$BARRIER_FILE"' in runner
    assert 'flock "$BARRIER_FD"' in runner
    assert 'setsid python3 -I -B "$SUPERVISOR"' in runner
    assert 'fcntl.flock(self.args.barrier_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)' in supervisor
    assert supervisor.index('self.active("intent", "active")') < supervisor.index(
        "return self.executor()"
    )
    assert supervisor.index('self.active("create-pending", "active")') < supervisor.index(
        "completed = _run(command, capture=True)"
    )
    assert supervisor.index('self.active("created", "active")') < supervisor.index(
        '["docker", "start", "--", self.container_id]'
    )
    for field in (
        "supervisor_pid",
        "supervisor_pgid",
        "supervisor_sid",
        "supervisor_start_ticks",
    ):
        assert field in state
    assert "ACTIVE operation lacks a dead supervisor terminal outcome" in runner
    assert 'payload.get("phase") != "terminal"' in state
    assert "terminal supervisor is still alive" in state
    assert "non-terminal active operation cannot be cleared" in state
    assert "tombstone" not in (runner + supervisor + state).lower()


def test_runner_has_no_raw_database_helper_and_recovery_leaves_zero_container_residue() -> None:
    runner = _RUNNER.read_text()
    supervisor = _SUPERVISOR.read_text()
    assert "docker compose exec" not in (runner + supervisor)
    assert "--env-file" not in supervisor
    assert 'f".{self.args.operation}.env"' not in supervisor
    assert "admin_feature_live_fixture" not in (runner + supervisor)
    assert "--mode\", choices=(\"executor\", \"probe\")" in supervisor
    assert "io.kortravelmap.admin-feature-acceptance.run-key" in supervisor
    assert "io.kortravelmap.admin-feature-acceptance.operation" in supervisor
    assert "deterministic container name is occupied" in supervisor
    assert 'docker container rm --force -- "$container_id"' in runner
    assert "owned Docker container residue remains" in runner
    assert "deterministic Docker container name residue remains" in runner
    # cursor probe는 API runtime DB credential을 복제하지 않고 항상 networkless다.
    probe_body = supervisor[supervisor.index("def probe(") :]
    assert '"--network",\n            "none"' in probe_body


def test_runner_requires_exact_root_source_snapshot() -> None:
    runner = _RUNNER.read_text()
    state = _STATE.read_text()
    bootstrap = runner.index("verify_root_snapshot_bootstrap()")
    helper = runner.index("state_helper()")
    validate = runner.index("  state_helper validate-source")
    initialize = runner.rindex("\ninitialize_state\n")
    entrypoint = runner[runner.rindex('[[ "$MODE" == "run" || "$MODE" == "recover" ]]') :]
    assert bootstrap < helper
    assert entrypoint.index("verify_root_snapshot_bootstrap") < entrypoint.index("validate_runtime")
    assert validate < initialize
    assert "os.O_NOFOLLOW" in runner
    assert "unsafe bootstrap ancestor" in runner
    assert "snapshot exact file set mismatch" in runner
    assert "snapshot file hash mismatch" in runner
    assert (
        'expected_root = Path("/usr/local/lib/kor-travel-map/'
        'admin-feature-live-acceptance") / commit'
        in runner
    )
    assert validate < initialize
    assert "set(os.listdir(root)) != required | {args.manifest.name}" in state
    assert "snapshot exact file set mismatch" in state
    assert "snapshot file hash mismatch" in state
    assert "stat.S_IMODE(observed.st_mode) & 0o022" in state
    assert '--required-file "${SUPERVISOR##*/}"' in runner
    assert "admin_feature_live_fixture.py" not in runner
    assert 'name == "run-admin-feature-live-acceptance.sh"' in state


def test_final_live_lane_is_fixture_free_and_uses_only_browser_commands() -> None:
    runner = _RUNNER.read_text()
    state = _STATE.read_text()
    supervisor = _SUPERVISOR.read_text()
    for source in (runner, state, supervisor):
        # T-VN-48D의 별도 clone runner는 legacy fixture를 계속 소유한다. F1D의
        # browser-only live lane은 그 helper를 읽거나 실행하면 안 된다.
        assert "admin_feature_live_fixture" not in source
        assert "direct-seed" not in source
        assert "direct-cleanup" not in source
        assert "direct-audit" not in source
        assert "helper-" not in source
        assert "feature.features" not in source
    assert '"executor-main",' in state
    assert '"executor-recovery",' in state
    assert '"probe-cursor-missing",' in state
    assert len(_STATE_MODULE._owned_ids("live-20260726010101-abcdef123456")) == 6  # noqa: SLF001


def test_browser_lane_uses_direct_typed_state_commands_and_bff() -> None:
    spec = _SPEC.read_text()
    assert '"/v1/admin/features"' in spec
    assert '`${adminFeaturePath(featureId)}/state`' in spec
    assert 'action: "patch"' in spec
    assert 'action: "retire"' in spec
    assert 'reason_code:' in spec
    assert 'headers: { "If-Match": patchTag }' in spec
    assert 'headers: { "If-Match": retireTag }' in spec
    assert 'state/transitions?page_size=20' in spec
    assert "await cleanupOwnedFeatures(page)" in spec
    assert "response redacted" in spec
    assert "result.text" not in spec
    assert "annotations.push" not in spec


def test_browser_lane_is_a_browser_bff_contract() -> None:
    spec = _SPEC.read_text()
    assert 'createHash("sha256")' in spec
    assert 'fetch(`/api/proxy${path}`' in spec
    assert 'credentials: "same-origin"' in spec
    assert '"Idempotency-Key"' in spec
    assert '?key=' not in spec
    assert 'searchParams.set("key"' not in spec
    assert "X-API-Key" not in spec


def test_browser_lane_covers_public_to_suppressed_to_retired_state_flow() -> None:
    spec = _SPEC.read_text()
    assert 'publication_state: "published"' in spec
    assert 'publication_state: "suppressed"' in spec
    assert 'lifecycle_state: "retired"' in spec
    assert 'publicFeaturePath(featureId)' in spec
    assert 'getByTestId("feature-detail-view")' in spec


def test_evidence_validator_requires_exact_schema_phase_counts_and_fsync() -> None:
    runner = _RUNNER.read_text()
    state = _STATE.read_text()
    assert "evidence exact file set mismatch" in state
    assert "redacted report mismatch" in state
    assert "redacted report exact file set mismatch" in state
    assert "set(os.listdir(path)) != _REPORT_NAMES" in state
    assert '"c7-results.xml"' in state
    assert '"c7-summary.html"' in state
    assert "_validated_report_rows(" in state
    assert "redacted report test identity mismatch" in state
    assert "os.O_NONBLOCK" in state
    assert "direct evidence mismatch" not in state
    assert "helper-" not in state
    assert "lifecycle exact file set mismatch" in state
    assert "lifecycle event count mismatch" in state
    assert "lifecycle phase payload mismatch" in state
    assert "validation evidence mismatch" in state
    assert '"counts": {"passed": 2}' in state
    assert '"reports_passed": 2 if args.mode == "normal" else 1' in state
    assert "_validate_root_tree(runtime)" in state
    assert "_fsync_tree(runtime)" in state
    run_new = runner[runner.index("run_new() {") :]
    assert run_new.index("  validate_evidence normal") < run_new.index("  write_result passed")
    assert run_new.index("  write_result passed") < run_new.index(
        '  state_helper clear-blocked --path "$BLOCKED_FILE"'
    )


@pytest.mark.parametrize(
    "rows",
    [
        '<testcase classname="c7-redacted" name="unexpected.spec.ts#1" '
        'time="0.001"></testcase>',
        '<testcase classname="c7-redacted" name="auth.setup.ts#1" '
        'time="0.001"><failure/></testcase>',
    ],
)
def test_redacted_report_rows_reject_unknown_or_failure_content(rows: str) -> None:
    with pytest.raises(ValueError, match="redacted report"):
        _STATE_MODULE._validated_report_rows(  # noqa: SLF001
            f"<suite>{rows}</suite>\n",
            prefix="<suite>",
            sequence_group=2,
            spec_group=1,
            suffix="</suite>\n",
            row_pattern=_STATE_MODULE._XML_CASE_RE,  # noqa: SLF001
        )


def test_c7_raw_playwright_output_is_outside_evidence_bind() -> None:
    config = _LIVE_CONFIG.read_text()
    assert (
        'path.join(\n  "/tmp",\n  `kor-travel-map-c7-test-results-${process.pid}`'
        in config
    )
    assert "const redactedEvidence = shouldAssertC7OriginGuard() || isolatedEvidence" in config
    assert "outputDir: redactedEvidence" in config
    assert "? c7RawOutputDir" in config
    assert ': path.join(artifactRoot, "test-results")' in config

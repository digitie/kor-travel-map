"""#741/#785/T-VN-15 targeted production live lane의 정적 복구 계약."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _ROOT / "scripts" / "run-admin-feature-live-acceptance.sh"
_CLONE_RUNNER = _ROOT / "scripts" / "run-admin-feature-clone-live-acceptance.sh"
_FIXTURE = _ROOT / "scripts" / "admin_feature_live_fixture.py"
_STATE = _ROOT / "scripts" / "admin_feature_live_state.py"
_CLONE_STATE = _ROOT / "scripts" / "admin_feature_clone_live_state.py"
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
    "pinned_runtime_manifest_sha256": "2" * 64,
    "rebuild_journal_sha256": "b" * 64,
    "host_attestation_sha256": "3" * 64,
    "playwright_image_id": "sha256:" + "4" * 64,
    "source_commit": "5" * 40,
}
_RECOVERY_EXECUTION = {
    "api_image_id": "sha256:" + "6" * 64,
    "pinned_runtime_manifest_sha256": "7" * 64,
    "rebuild_journal_sha256": "c" * 64,
    "host_attestation_sha256": "8" * 64,
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
_CLONE_STATE_MODULE = _load_script_module(
    "admin_feature_clone_live_state", _CLONE_STATE
)
_FIXTURE_MODULE = _load_script_module("admin_feature_live_fixture", _FIXTURE)
_SUPERVISOR_MODULE = _load_script_module(
    "admin_feature_live_supervisor",
    _SUPERVISOR,
)


def test_clone_recovery_purge_uses_name_keyed_api_owned_identity() -> None:
    """T-VN-36 API-owned 소유권 키는 이름이고, id는 서버 규칙에서 파생한다."""

    run_id = "clone-20260729000000-abcdef123456"
    fixture_name = _FIXTURE_MODULE._admin_fixture_name(run_id)  # noqa: SLF001
    reason_prefix = _FIXTURE_MODULE._admin_reason_prefix(run_id)  # noqa: SLF001

    # live spec의 FIXTURE_NAME/REASON과 같은 문자열이어야 감사가 같은 행을 본다.
    spec = _SPEC.read_text()
    assert "const FIXTURE_NAME = `E2E TVN36 state fixture ${RUN_ID}`;" in spec
    assert "const REASON = `tvn36-live-${RUN_ID}`;" in spec
    assert fixture_name == f"E2E TVN36 state fixture {run_id}"
    assert reason_prefix == f"tvn36-live-{run_id}"

    # id는 서버가 발급한다(`_create_feature_id`). clone 러너의 content digest는
    # 같은 규칙을 shell 안에서 재현하므로 두 파생이 일치해야 한다.
    feature_id = _FIXTURE_MODULE._admin_fixture_feature_id(run_id)  # noqa: SLF001
    raw = f"global|place|01070300|user_request|{fixture_name}:127.500000,36.500000|"
    assert feature_id == f"f_global_p_{hashlib.sha1(raw.encode()).hexdigest()[:16]}"
    runner = _CLONE_RUNNER.read_text()
    assert 'f"E2E TVN36 state fixture {run_id}:127.500000,36.500000",' in runner
    assert "e2e_live_acceptance::{run_id}::{role}" not in runner

    assert _FIXTURE_MODULE._provider_fixture_feature_id(  # noqa: SLF001
        run_id, "weather"
    ).startswith("f_global_w_")
    assert _FIXTURE_MODULE._provider_fixture_feature_id(  # noqa: SLF001
        run_id, "price"
    ).startswith("f_global_p_")

    # 완료 감사가 요구하는 전이 사슬은 spec이 실제로 실행하는 3단계다.
    assert _FIXTURE_MODULE._expected_transition_chain(run_id) == (  # noqa: SLF001
        ("initial", "admin_feature_create"),
        ("admin", f"{reason_prefix}:suppress"),
        ("admin", f"{reason_prefix}:retire"),
    )


def test_clone_checkpoint_schema_digest_uses_restore_stable_catalog() -> None:
    """restore가 정규화하는 CHECK 표현·dropped-column ordinal을 오판하지 않는다."""
    source = (
        _ROOT / "scripts" / "run-admin-feature-clone-live-acceptance.sh"
    ).read_text(encoding="utf-8")

    assert "constraint_row.conkey::text" not in source
    assert "constraint_row.confkey::text" not in source
    assert "key_attribute.attname" in source
    assert "referenced_attribute.attname" in source
    assert "array_position(constraint_row.conkey, key_attribute.attnum)" in source
    assert "constraint_row.confrelid::regclass::text" in source
    assert "constraint_row.convalidated" in source
    assert "pg_get_constraintdef(constraint_row.oid, true)" not in source
    assert "row_number() OVER (" in source
    assert "PARTITION BY attribute.attrelid ORDER BY attribute.attnum" in source
    assert "attribute.attnum::text || attribute.attname" not in source
    assert "attnum gap은 pg_dump/pg_restore가 정규화한다" in source


def test_live_fixture_counts_only_direct_feature_id_references() -> None:
    """composite subtype/alias fence는 fixture feature_id만으로 억지로 계수하지 않는다."""
    source = _FIXTURE.read_text(encoding="utf-8")

    assert "AND cardinality(constraint_row.conkey) = 1" in source
    assert "AND cardinality(constraint_row.confkey) = 1" in source
    assert "composite FK는 이 fixture가 가진 feature_id만으로 reference를 셀 수" in source


def _execution_args(path: Path, identity: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(
        api_image_id=identity["api_image_id"],
        pinned_runtime_manifest_sha256=identity["pinned_runtime_manifest_sha256"],
        rebuild_journal_sha256=identity["rebuild_journal_sha256"],
        host_attestation_sha256=identity["host_attestation_sha256"],
        path=path,
        playwright_image_id=identity["playwright_image_id"],
        source_commit=identity["source_commit"],
    )


def test_blocked_v3_records_execution_identity() -> None:
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
    assert payload["version"] == 3
    assert payload["execution"] == _ORIGIN_EXECUTION


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("phase", "invalid phase"),
        ("recorded_at", "not-a-timestamp"),
        ("status", "complete"),
    ],
)
def test_blocked_v3_rejects_malformed_control_fields(
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


def test_legacy_blocked_v2_is_rejected(
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
    payload["version"] = 2
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


def test_result_v3_durably_preserves_execution_identity(
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
        "host_attestation_sha256",
        "owned_feature_id_sha256",
        "phase",
        "recorded_at",
        "recovery_attempt",
        "pinned_runtime_manifest_sha256",
        "rebuild_journal_sha256",
        "run_id_sha256",
        "status",
        "version",
    }
    assert result["version"] == 3
    assert result["execution_identity_sha256"] == (
        _STATE_MODULE._execution_identity_sha256(_ORIGIN_EXECUTION)  # noqa: SLF001
    )
    assert result["pinned_runtime_manifest_sha256"] == "2" * 64
    assert result["rebuild_journal_sha256"] == "b" * 64
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


_MODULE_DIGEST = "1" * 64


def _bootstrap_args(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: dict[str, object],
) -> SimpleNamespace:
    """`_validate_c7_module`의 version 분기까지 **실제로 도달하게** 만든다.

    이 함수는 root 소유 절대경로 전제(경로 고정·ancestor 검사·0600 읽기) 뒤에야
    version을 본다. 그 전제를 그대로 두면 테스트가 version 분기에 닿지 못하고
    다른 이유로 raise되어, 무엇을 검사했는지 알 수 없는 통과가 된다.
    """

    commit = "5" * 40
    monkeypatch.setattr(_STATE_MODULE, "_C7_BASE", tmp_path)
    monkeypatch.setattr(_STATE_MODULE, "_safe_ancestors", lambda _path: None)
    monkeypatch.setattr(
        _STATE_MODULE,
        "_read_regular",
        lambda *_args, **_kwargs: json.dumps(payload).encode("utf-8"),
    )
    monkeypatch.setattr(_STATE_MODULE, "_file_sha256", lambda *_args, **_kwargs: _MODULE_DIGEST)
    return SimpleNamespace(
        expected_commit=commit,
        module=tmp_path / commit / _STATE_MODULE._C7_MODULE_RELATIVE,  # noqa: SLF001
        attestation=tmp_path / "attestation.json",
    )


def _bootstrap_payload(version: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "repository_commit": "5" * 40,
        "orchestrator_files": {
            "scripts/audit-c7-prod-live-state.py": "0" * 64,
            "scripts/lib/c7-prod-runner-lifecycle.sh": "0" * 64,
            "scripts/lib/c7_prod_attestation.py": _MODULE_DIGEST,
            "scripts/run-c7-prod-live-e2e.sh": "0" * 64,
        },
    }
    if version is not None:
        payload["version"] = version
    return payload


def test_c7_module_bootstrap_accepts_v4_host_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """양성 경로가 없으면 아래 음성 테스트는 '항상 raise'와 구별되지 않는다."""

    args = _bootstrap_args(monkeypatch, tmp_path, _bootstrap_payload(4))

    _STATE_MODULE._validate_c7_module(args)  # noqa: SLF001


@pytest.mark.parametrize("version", [3, 5, "4", None])
def test_c7_module_bootstrap_rejects_non_v4_host_attestation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> None:
    """bootstrap 검증이 host attestation version을 **실제로** 판정하는지 본다.

    문자열 위치 단언만 있으면 상수가 어긋나도 통과한다. 실제로 이 브랜치에서
    검증 모듈은 v4를 요구하는데 bootstrap은 v3를 요구해 admin lane이 통째로
    fail-closed되는 상태가 CI green으로 남아 있었다(2026-08-20 적대 리뷰).
    """

    args = _bootstrap_args(monkeypatch, tmp_path, _bootstrap_payload(version))

    with pytest.raises(ValueError, match="C7 module bootstrap mismatch"):
        _STATE_MODULE._validate_c7_module(args)  # noqa: SLF001


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
    assert 'attestation.get("version") != 4' in state
    assert 'manifest["version"] != 5' in attestation
    assert 'value["version"] != 7' in attestation
    assert 'value["phase"] != _JOURNAL_COMMITTED_PHASE' in attestation
    assert 'value["candidate"] != generation' in attestation
    assert 'active["map_source_revision"] != source_commits["map"]' in attestation
    assert 'compose_project_hashes != {attestation["compose_project_sha256"]}' in attestation
    assert 'environment_sha256 != expected["environment_sha256"]' in attestation
    assert 'command_sha256 != expected["command_sha256"]' in attestation
    assert 'observed_images[role] != active[field]' in attestation
    assert '_public_origin(environ["E2E_BASE_URL"])' in attestation
    assert 'E2E_C7_PINNED_RUNTIME_MANIFEST' in runner
    assert 'E2E_C7_REBUILD_JOURNAL' in runner
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
        'return self.helper()'
    )
    assert supervisor.index('self.active("create-pending", "active")') < supervisor.index(
        "completed = _run(command, capture=True, env=process_environment)"
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


def test_helper_is_standalone_labeled_and_recovery_leaves_zero_container_residue() -> None:
    runner = _RUNNER.read_text()
    supervisor = _SUPERVISOR.read_text()
    assert "docker compose exec" not in (runner + supervisor)
    assert '"--volumes-from"' in supervisor
    assert 'f"{self.args.api_container}:ro"' in supervisor
    assert "--env-file" not in supervisor
    assert 'f".{self.args.operation}.env"' not in supervisor
    assert "runtime_environment = _unique_environment(environment)" in supervisor
    assert "process_environment.update(runtime_environment)" in supervisor
    assert 'for value in ("--env", name)' in supervisor
    assert "process_environment=process_environment" in supervisor
    assert '"host" if host_networked else ordered_networks[0]' in supervisor
    assert '"docker", "network", "connect"' in supervisor
    assert "io.kortravelmap.admin-feature-acceptance.run-key" in supervisor
    assert "io.kortravelmap.admin-feature-acceptance.operation" in supervisor
    assert "deterministic container name is occupied" in supervisor
    assert 'docker container rm --force -- "$container_id"' in runner
    assert "owned Docker container residue remains" in runner
    assert "deterministic Docker container name residue remains" in runner
    assert "recovery mode cannot seed fixtures" in runner


def test_helper_clones_host_network_mode_without_post_create_attachment() -> None:
    supervisor = _SUPERVISOR.read_text()
    # n150 production compose는 API runtime을 network_mode=host로 돌린다. docker는
    # `network connect host`를 거부하므로 helper는 host network로 직접 create해야
    # 하고(loopback DB 도달성이 API runtime과 일치), post-create attachment를
    # 시도해서는 안 된다. host mode에서 Networks가 {"host"} 외 조합이면 fail-closed.
    assert 'network_mode = record.get("HostConfig", {}).get("NetworkMode")' in supervisor
    assert 'host_networked = network_mode == "host"' in supervisor
    assert 'set(networks) != {"host"}' in supervisor
    # 비-host runtime은 첫 network로 직접 create한다: none+connect는 docker가
    # none(private) 모드 컨테이너에 network connect를 거부해 죽은 경로였다.
    assert 'ordered_networks = [] if host_networked else sorted(networks)' in supervisor
    assert '"host" if host_networked else ordered_networks[0]' in supervisor
    # connect 루프는 host 가드 아래 "나머지" network에만 — 인접 substring으로
    # nesting 자체를 고정한다(순서 비교만으로는 dedent mutation을 못 잡는다).
    assert (
        "if not host_networked:\n            for network in ordered_networks[1:]:"
        in supervisor
    )
    # cursor probe는 API network mode와 무관하게 항상 networkless로 남는다.
    probe_body = supervisor[supervisor.index("def probe(") :]
    assert '"--network",\n            "none"' in probe_body


def test_helper_environment_parser_preserves_values_without_disk_copy() -> None:
    assert _SUPERVISOR_MODULE._unique_environment(  # noqa: SLF001
        ["A=one", "B=two=three", "EMPTY="]
    ) == {"A": "one", "B": "two=three", "EMPTY": ""}


@pytest.mark.parametrize(
    "items",
    [
        object(),
        ["NO_SEPARATOR"],
        ["1INVALID=value"],
        ["DUPLICATE=first", "DUPLICATE=second"],
        ["NUL=value\0tail"],
    ],
)
def test_helper_environment_parser_rejects_ambiguous_shapes(items: object) -> None:
    with pytest.raises(RuntimeError, match="environment shape"):
        _SUPERVISOR_MODULE._unique_environment(items)  # noqa: SLF001


def test_runner_requires_exact_root_source_snapshot() -> None:
    runner = _RUNNER.read_text()
    state = _STATE.read_text()
    validate = runner.index("  state_helper validate-source")
    initialize = runner.rindex("\ninitialize_state\n")
    assert validate < initialize
    assert "set(os.listdir(root)) != required | {args.manifest.name}" in state
    assert "snapshot exact file set mismatch" in state
    assert "snapshot file hash mismatch" in state
    assert "stat.S_IMODE(observed.st_mode) & 0o022" in state
    assert 'safe_root_file "$SOURCE_MANIFEST" 444' in runner
    assert 'safe_root_file "$SUPERVISOR" 444' in runner
    assert '--required-file "${SUPERVISOR##*/}"' in runner
    assert 'name == "run-admin-feature-live-acceptance.sh"' in state


def test_direct_cleanup_locks_owned_parents_before_fk_audit_and_delete() -> None:
    fixture = _FIXTURE.read_text()
    cleanup = fixture[
        fixture.index("async def _cleanup(") : fixture.index(
            "class _ApiOwnedInspection("
        )
    ]
    inspection = fixture[
        fixture.index("async def _inspect_api_owned(") : fixture.index(
            "async def _purge_api_owned("
        )
    ]
    purge = fixture[
        fixture.index("async def _purge_api_owned(") : fixture.index(
            "def _expected_transition_chain("
        )
    ]
    owned_values = fixture[
        fixture.index("async def _assert_owned_values(") : fixture.index(
            "async def _assert_owned_state("
        )
    ]
    assert fixture.count('lock_clause = " FOR UPDATE" if lock else ""') == 2
    assert owned_values.count("+ lock_clause") == 2
    assert "_assert_owned_values(session, run_id, feature_ids, present, lock=lock)" in fixture
    lock = cleanup.index("lock=True")
    foreign_key_audit = cleanup.index("DELETE FROM feature.features")
    assert lock < foreign_key_audit
    assert "Parent FOR UPDATE" in cleanup
    assert "pg_catalog.pg_constraint" in fixture
    assert "foreign_key_constraints_checked" in fixture
    assert "foreign_key_references" in fixture
    assert "owned fixture ID의 소유권 fingerprint가 다릅니다" in fixture
    assert "owned weather value fingerprint가 다릅니다" in fixture
    assert "owned price value fingerprint가 다릅니다" in fixture
    assert '"feature.feature_aliases.feature_id"] = len(present)' in fixture
    assert '"feature.current_weather_summary.feature_id"] = 1' in fixture
    assert '"feature.current_price_summary.feature_id"] = 1' in fixture
    assert 'if rows:' in inspection
    assert '"feature.feature_aliases.feature_id"] = len(rows)' in inspection
    assert cleanup.count("DELETE FROM feature.features") == 1
    assert purge.count("DELETE FROM feature.features") == 1
    # 0104가 review/whole-row-freeze 모델을 지웠다. purge는 Feature 한 번 삭제로
    # CASCADE 자식(alias/subtype/field override)을 함께 지우고, append-only 전이
    # 감사는 남았음을 확인만 한다.
    assert "DELETE FROM ops.feature_change_requests" not in fixture
    assert "FROM feature.feature_versions" not in fixture
    assert "FROM feature.feature_state_transitions" in fixture
    assert "FROM ops.feature_overrides" in fixture
    assert "FROM ops.domain_commands AS command" in fixture
    assert "API-owned 전이 사슬이 예상과 다릅니다" in inspection
    assert "API-owned field override 소유권이 다릅니다" in inspection
    assert "API-owned domain command receipt 소유권이 다릅니다" in inspection
    assert "append-only 상태 전이 감사가 purge로 훼손되었습니다" in purge
    assert "inspection.field_overrides" in purge
    assert 'result["feature_uuids"] = list(api_owned_feature_uuids)' in fixture
    assert "async def _owned_summary_run_ids(" in fixture
    assert "owned weather/price current-summary receipt가 정확하지 않습니다" in fixture
    assert 'result["summary_run_ids"] = list(summary_run_ids)' in fixture


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


def test_clone_content_digest_excludes_only_exact_run_bound_receipts() -> None:
    """admin command와 immutable summary receipt는 exact 실행 소유권으로만 제외한다."""
    runner = _CLONE_RUNNER.read_text(encoding="utf-8")

    assert "'domain_commands', 'domain_command_results'" in runner
    assert "command.actor = ''ui-auth''" in runner
    assert "result.response_body #>> ''{data,item,request_id}''" in runner
    assert "result.response_body::text LIKE %L" in runner
    assert "'%e2e_live_acceptance::${run_id}::%'" in runner
    assert "owned_feature_ids_sql()" in runner
    assert "ARRAY[${owned_feature_ids}]::text[]" in runner
    assert "\\$fmt\\$ WHERE NOT (row_value.feature_id" in runner
    assert "owned_summary_run_ids_sql()" in runner
    assert '"summary_run_ids"' in runner
    assert "row_value.summary_run_id <> ALL (ARRAY[${owned_summary_run_ids}]::bigint[])" in runner
    assert "current_summary_runs_summary_run_id_seq" in runner
    assert "provider_datasets_provider_dataset_id_seq" in runner
    assert "legacy-v2 legacy-v1 legacy-v0" in runner


def test_clone_seed_receipt_evidence_requires_two_distinct_positive_ids(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "direct-seed.json"
    payload = {
        "action": "seed",
        "counts": {"features": 2, "price_values": 1, "weather_values": 1},
        "foreign_key_constraints_checked": 18,
        "foreign_key_references": 6,
        "summary_run_ids": [101, 102],
        "version": 1,
    }
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    assert _CLONE_STATE_MODULE._fixture_counts(  # noqa: SLF001
        evidence_path,
        "seed",
        {"features": 2, "price_values": 1, "weather_values": 1},
        expected_foreign_key_references=6,
    ) == payload

    payload["summary_run_ids"] = [101, 101]
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="current-summary receipt"):
        _CLONE_STATE_MODULE._fixture_counts(  # noqa: SLF001
            evidence_path,
            "seed",
            {"features": 2, "price_values": 1, "weather_values": 1},
            expected_foreign_key_references=6,
        )


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
    assert "direct evidence mismatch" in state
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

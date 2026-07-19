"""#741/#785/T-VN-15 targeted production live lane의 정적 복구 계약."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _ROOT / "scripts" / "run-admin-feature-live-acceptance.sh"
_FIXTURE = _ROOT / "scripts" / "admin_feature_live_fixture.py"
_STATE = _ROOT / "scripts" / "admin_feature_live_state.py"
_SUPERVISOR = _ROOT / "scripts" / "admin_feature_live_supervisor.py"
_ATTESTATION = _ROOT / "scripts" / "lib" / "c7_prod_attestation.py"
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


def test_targeted_lane_is_not_part_of_strict_c7_runner() -> None:
    assert "admin-feature-acceptance-write" not in _C7_RUNNER.read_text()


def test_runner_uses_trusted_c7_v3_v4_runtime_attestation_before_state() -> None:
    runner = _RUNNER.read_text()
    state = _STATE.read_text()
    attestation = _ATTESTATION.read_text()
    validate = runner.index("  state_helper validate-c7-module")
    runtime = runner.index('    python3 -I -B "$c7_module" runtime')
    initialize = runner.rindex("\ninitialize_state\n")
    assert validate < runtime < initialize
    assert 'readonly HOST_ATTESTATION_FILE="/etc/kor-travel-map/' in runner
    assert 'readonly C7_INSTALL_BASE="/usr/local/lib/kor-travel-map/c7-runner"' in runner
    assert 'attestation.get("version") != 3' in state
    assert 'manifest["version"] != 4' in attestation
    assert 'active["map_source_revision"] != source_commits["map"]' in attestation
    assert 'compose_project_hashes != {attestation["compose_project_sha256"]}' in attestation
    assert 'environment_sha256 != expected["environment_sha256"]' in attestation
    assert 'command_sha256 != expected["command_sha256"]' in attestation
    assert 'observed_images[role] != active[field]' in attestation
    assert '_public_origin(environ["E2E_BASE_URL"])' in attestation
    assert 'E2E_C7_COMPATIBLE_PAIR_MANIFEST' in runner
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


def test_helper_is_standalone_labeled_and_recovery_leaves_zero_container_residue() -> None:
    runner = _RUNNER.read_text()
    supervisor = _SUPERVISOR.read_text()
    assert "docker compose exec" not in (runner + supervisor)
    assert '"--volumes-from",\n                f"{self.args.api_container}:ro"' in supervisor
    assert '"--env-file",\n                str(env_file)' in supervisor
    assert '"--network",\n                "none"' in supervisor
    assert '"docker", "network", "connect"' in supervisor
    assert "io.kortravelmap.admin-feature-acceptance.run-key" in supervisor
    assert "io.kortravelmap.admin-feature-acceptance.operation" in supervisor
    assert "deterministic container name is occupied" in supervisor
    assert 'docker container rm --force -- "$container_id"' in runner
    assert "owned Docker container residue remains" in runner
    assert "deterministic Docker container name residue remains" in runner
    assert "recovery mode cannot seed fixtures" in runner


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
    cleanup = fixture[fixture.index("async def _cleanup(") : fixture.index("async def _run(")]
    assert 'lock_clause = " FOR UPDATE" if lock else ""' in fixture
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
    assert fixture.count("DELETE FROM feature.features") == 1


def test_browser_lane_covers_nonpublic_bbox_and_stale_raw_etag() -> None:
    spec = _SPEC.read_text()
    assert 'max_lat: String(lat + 0.00001)' in spec
    assert 'expect(result.data.mode).toBe("items")' in spec
    assert "expect(result.data.truncated).toBe(false)" in spec
    assert "result.data.coverage.returned).toBeLessThan" in spec
    assert 'expect(staleResponse.status()).toBe(412)' in spec
    assert 'headers()["if-match"]' in spec
    assert "revisionResponses).toHaveLength(revisionsBeforeSubmit" in spec
    assert "최신값으로 폼 다시 불러오기" in spec
    assert 'expect(secondResponse.request().headers()["if-match"]).toBe(competingTag)' in spec
    assert "await cleanupApiOwnedFeatures(page)" in spec
    assert "owned pending change request가 cleanup 뒤 남았습니다" in spec
    assert "response redacted" in spec
    assert "result.text" not in spec
    assert "annotations.push" not in spec


def test_browser_lane_covers_t_vn_15_search_contract_only_through_bff() -> None:
    spec = _SPEC.read_text()
    assert 'const SEARCH_FEATURES = ["alpha", "beta"]' in spec
    assert 'status: "active" as const' in spec
    assert 'createHash("sha256")' in spec
    assert '.update(fixture.featureId, "utf8")' in spec
    assert 'fetch(`/api/proxy${path}`' in spec
    assert '"/v1/features/search?' in spec
    assert "include_total: \"false\"" in spec
    assert "include_total: \"true\"" in spec
    assert "firstWithoutTotal.meta.page?.total).toBeNull()" in spec
    assert "firstWithTotal.meta.page?.total).toBe(2)" in spec
    assert "CURSOR_QUERY_MISMATCH" in spec
    assert "FEATURE_SEARCH_CURSOR_TAMPERED" in spec
    assert "tamperCursorPayload" in spec
    assert "expect(serialized).not.toContain(cursor)" in spec
    assert '?key=' not in spec
    assert 'searchParams.set("key"' not in spec
    assert "X-API-Key" not in spec


def test_browser_lane_covers_all_nonpublic_markers_and_cards() -> None:
    spec = _SPEC.read_text()
    for status in ("draft", "inactive", "hidden"):
        assert f'"{status}"' in spec
    assert '/v1/admin/features/in-bounds"' in spec
    assert 'page.getByLabel(`${fixture.name} (place)`' in spec
    assert 'page.getByTestId("feature-weather-panel")' in spec
    assert 'page.getByTestId("feature-price-panel")' in spec
    assert "weather.data.metrics).toHaveLength(1)" in spec
    assert "price.data.history).toHaveLength(1)" in spec
    assert "assertPublicInBoundsExcludes(" in spec


def test_evidence_validator_requires_exact_schema_phase_counts_and_fsync() -> None:
    runner = _RUNNER.read_text()
    state = _STATE.read_text()
    assert "evidence exact file set mismatch" in state
    assert "redacted report mismatch" in state
    assert "direct evidence mismatch" in state
    assert "lifecycle exact file set mismatch" in state
    assert "lifecycle event count mismatch" in state
    assert "lifecycle phase payload mismatch" in state
    assert "validation evidence mismatch" in state
    assert '"counts": {"passed": 2}' in state
    assert '"reports_passed": 2 if args.mode == "normal" else 1' in state
    assert "_validate_root_tree(runtime)" in state
    assert "_fsync_tree(runtime)" in state
    assert runner.index("  validate_evidence normal") < runner.index("  write_result passed")
    assert runner.index("  write_result passed") < runner.index(
        '  state_helper clear-blocked --path "$BLOCKED_FILE"'
    )

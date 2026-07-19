"""#741/#785 targeted production live lane의 정적 복구 계약."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _ROOT / "scripts" / "run-admin-feature-live-acceptance.sh"
_FIXTURE = _ROOT / "scripts" / "admin_feature_live_fixture.py"
_STATE = _ROOT / "scripts" / "admin_feature_live_state.py"
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


def test_runner_journals_before_direct_fixture_mutation_and_recovers() -> None:
    source = _RUNNER.read_text()
    state_source = _STATE.read_text()
    blocked = "write_blocked fixture_seed_pending"
    seed = 'fixture_helper seed "$RUNTIME_DIR/direct-seed.json"'
    assert source.index(blocked) < source.index(seed)
    assert "prior BLOCKED state requires recover mode" in source
    assert '"$RUNTIME_DIR/playwright-recovery"' in source
    assert 'fixture_helper cleanup "$RUNTIME_DIR/direct-cleanup.json"' in source
    assert 'fixture_helper audit "$RUNTIME_DIR/direct-audit.json"' in source
    assert "cleanup_failed" in source
    assert "test_failed_restored" in source
    assert '"owned_feature_ids"' in state_source
    assert '"owned_feature_id_sha256"' in state_source
    assert 'RUNTIME_DIR="$STATE_ROOT/run-$RUN_KEY"' in source
    assert 'payload.get("owned_feature_ids") != _owned_ids(payload["run_id"])' in state_source
    assert "os.fsync(directory)" in state_source


def test_runner_pins_healthy_api_ui_and_hardens_executor() -> None:
    source = _RUNNER.read_text()
    state_source = _STATE.read_text()
    assert "E2E_ADMIN_FEATURE_ACCEPTANCE_UI_SERVICE" in source
    assert '"org.opencontainers.image.revision"' in source
    assert '[[ "$running" == "true" && "$health" == "healthy" ]]' in source
    assert "docker create --pull=never" in source
    for phase in ("create_pending", "created", "running", "exited", "removed"):
        assert phase in source
    assert "container_id_sha256" in state_source
    assert "container_name_sha256" in state_source
    assert "E2E_C7_EXPECTED_UI_ORIGIN_SHA256" in source
    assert "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256" in source
    assert "--security-opt no-new-privileges" in source
    assert "--cap-drop ALL" in source
    assert '<"$FIXTURE_HELPER" >"$output" || return' in source


def test_runner_requires_exact_root_source_snapshot_before_state_mutation() -> None:
    source = _RUNNER.read_text()
    state_source = _STATE.read_text()
    validate = source.index("  state_helper validate-source")
    initialize = source.rindex("\ninitialize_state\n")
    assert validate < initialize
    assert "set(os.listdir(root)) != expected_names" in state_source
    assert "_file_sha256(root / name) != expected_hash" in state_source
    assert "stat.S_IMODE(observed.st_mode) & 0o022" in state_source
    assert 'safe_root_file "$SOURCE_MANIFEST" 444' in source
    assert '--required-file "${STATE_HELPER##*/}"' in source
    assert "args.manifest.parent.resolve(strict=True) != root" in state_source


def test_direct_fixture_helper_only_mutates_exact_owned_ids() -> None:
    source = _FIXTURE.read_text()
    assert 'f"{prefix}::weather"' in source
    assert 'f"{prefix}::price"' in source
    assert "coord, coord_precision_digits, status" in source
    assert "owned fixture ID의 소유권 fingerprint가 다릅니다" in source
    assert "owned weather value fingerprint가 다릅니다" in source
    assert "owned price value fingerprint가 다릅니다" in source
    assert "pg_catalog.pg_constraint" in source
    assert "foreign_key_constraints_checked" in source
    assert "foreign_key_references" in source
    assert "feature_id = :weather_id AND kind = 'weather'" in source
    assert "feature_id = :price_id AND kind = 'price'" in source
    assert source.count("DELETE FROM feature.features") == 1
    assert '"features": 0, "weather_values": 0, "price_values": 0' in source


def test_browser_lane_covers_stale_raw_etag_and_fail_loud_cleanup() -> None:
    source = _SPEC.read_text()
    assert 'expect(staleResponse.status()).toBe(412)' in source
    assert 'headers()["if-match"]' in source
    assert "revisionResponses).toHaveLength(revisionsBeforeSubmit" in source
    assert "최신값으로 폼 다시 불러오기" in source
    assert 'expect(secondResponse.request().headers()["if-match"]).toBe(competingTag)' in source
    assert "await cleanupApiOwnedFeatures(page)" in source
    assert "owned pending change request가 cleanup 뒤 남았습니다" in source
    assert "decodeURIComponent(revisionPath(CORRECTION_FEATURE.featureId))" in source
    assert "decodeURIComponent(adminFeaturePath(CORRECTION_FEATURE.featureId))" in source
    assert "response redacted" in source
    assert "result.text" not in source
    assert "annotations.push" not in source
    assert "recovery-only는 Feature를 생성할 수 없습니다" in source
    assert "recovery-only는 correction write를 실행할 수 없습니다" in source


def test_browser_lane_covers_all_nonpublic_markers_and_cards() -> None:
    source = _SPEC.read_text()
    for status in ("draft", "inactive", "hidden"):
        assert f'"{status}"' in source
    assert '/v1/admin/features/in-bounds"' in source
    assert 'page.getByLabel(`${fixture.name} (place)`' in source
    assert 'page.getByTestId("feature-weather-panel")' in source
    assert 'page.getByTestId("feature-price-panel")' in source
    assert "weather.data.metrics).toHaveLength(1)" in source
    assert "price.data.history).toHaveLength(1)" in source
    assert "assertAdminInBoundsIncludes(page, WEATHER_FEATURE" in source
    assert "assertAdminInBoundsIncludes(page, PRICE_FEATURE" in source
    assert "assertPublicInBoundsExcludes(" in source

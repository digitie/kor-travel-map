"""T-VN-34C n150 fresh-live 실행기 정적 안전 계약."""

from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _ROOT / "scripts" / "run-tvn34c-n150-fresh-live-e2e.sh"
_INSTALLER = _ROOT / "scripts" / "install-tvn34c-n150-fresh-live-e2e.sh"
_SEEDER = _ROOT / "scripts" / "tvn34c_fresh_live_etl_seed.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_fresh_live_shell_scripts_are_syntax_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_RUNNER), str(_INSTALLER)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_runner_uses_receipt_pinned_archives_not_its_checkout() -> None:
    runner = _text(_RUNNER)

    assert 'readonly RECEIPT="$INSTALL_DIR/consumer-rollout-v1.json"' in runner
    assert 'task = data.get("deployment_receipt_task")' in runner
    assert 'receipt.get("state") != "complete"' in runner
    assert '"map_service_openapi_sha256"' in runner
    assert '"pinvi_service_vendor_sha256"' in runner
    assert 'openapi.service.json' in runner
    assert 'kor-travel-map-openapi-service.json' in runner
    assert 'pinvi_admin_detail_vendor_sha256' not in runner
    assert (
        'python3 - "$RECEIPT" "$MAP_DIR" "$PINVI_DIR" "$MAP_COMMIT" "$PINVI_COMMIT"'
        in runner
    )
    assert 'safe_extract "$MAP_ARCHIVE" "$RUN_DIR"' in runner
    assert 'safe_extract "$PINVI_ARCHIVE" "$RUN_DIR"' in runner
    assert '"version"] != 4' in runner
    assert 'read_map_application_head' in runner
    assert '"$MAP_DIR/docker/application-schema-head.py"' in runner
    assert '"$MAP_DIR/src/kortravelmap/_application_migration_graph.json"' in runner
    assert 'namespace.get("_application_head")' in runner
    assert "known = {" not in runner
    assert 'KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=$EXPECTED_HEAD' in runner
    assert "feature.features_detailed') IS NULL" in runner
    assert "T-VN-36 final legacy Feature columns remain" in runner
    assert "T-VN-36 final request/version bridge remains" in runner
    assert 'local log="$evidence/playwright.log"' in runner
    assert '2>&1 | tee "$log"' in runner
    assert 'compose_map up --detach --wait postgres' in runner
    assert "- candidate-ui" in runner
    assert 'E2E_BASE_URL=http://localhost:12705' in runner
    assert "PINVI_KOR_TRAVEL_MAP_CACHE_TARGET_COMMAND_TOKEN=$cache_target_command_token" in runner
    assert "PINVI_KOR_TRAVEL_MAP_CACHE_TARGET_CONSUMER_TOKEN=$cache_target_consumer_token" in runner
    assert "PINVI_KOR_TRAVEL_MAP_CURATION_SNAPSHOT_TOKEN=$curation_snapshot_token" in runner
    assert (
        "PINVI_KOR_TRAVEL_MAP_CURATION_CUTOVER_MAPPING_TOKEN=$curation_cutover_mapping_token"
        in runner
    )
    assert "KOR_TRAVEL_MAP_API_PINVI_CURATION_SNAPSHOT_TOKEN_SHA256=$curation_snapshot_digest" in runner
    assert (
        "KOR_TRAVEL_MAP_API_PINVI_CURATION_CUTOVER_MAPPING_TOKEN_SHA256=$curation_cutover_mapping_digest"
        in runner
    )
    assert "PINVI_KOR_TRAVEL_MAP_CACHE_TARGET_EXPECTED_CONTRACT_GENERATION=7" in runner
    assert 'compose_ui_password_hash="${ui_password_hash//\\$/\\$\\$}"' in runner
    assert "KOR_TRAVEL_MAP_API_OPS_FIXTURE_TOKEN=$ops_fixture" in runner
    assert "docker image inspect --format '{{.Id}}' \"$dagster_image_reference\"" in runner
    assert "mcr.microsoft.com/playwright:v1.60.0-noble" in _text(
        _ROOT / "docker" / "c7-playwright.Dockerfile"
    )


def test_installer_archives_exact_pair_and_installs_immutable_inputs() -> None:
    installer = _text(_INSTALLER)

    assert (
        'git -C "$MAP_REPOSITORY" archive --format=tar.gz --prefix=map/ "$MAP_COMMIT"'
        in installer
    )
    assert (
        'git -C "$PINVI_REPOSITORY" archive --format=tar.gz --prefix=pinvi/ "$PINVI_COMMIT"'
        in installer
    )
    assert 'task = rollout.get("deployment_receipt_task")' in installer
    assert 'receipt.get("state") != "complete"' in installer
    assert '"map_service_openapi_sha256"' in installer
    assert '"pinvi_service_vendor_sha256"' in installer
    assert 'openapi.service.json' in installer
    assert 'kor-travel-map-openapi-service.json' in installer
    assert 'pinvi_admin_detail_vendor_sha256' not in installer
    assert '"version":4' in installer
    assert 'readonly snapshot_name="${MAP_COMMIT}-${PINVI_COMMIT}-${RUNNER_COMMIT}"' in installer
    assert 'install -o root -g root -m 0500' in installer
    assert (
        'install -o root -g root -m 0544 "$stage/scripts/tvn34c_fresh_live_etl_seed.py"'
        in installer
    )
    assert 'install -d -o root -g root -m 0700 "$temporary"' in installer
    assert 'install -o root -g root -m 0600' in installer
    assert 'sudo /bin/bash -s' in installer


def test_seed_helper_requires_dagster_runtime_preflight() -> None:
    seeder = _text(_SEEDER)

    assert 'expected_login="ktm_feature_dagster_runtime"' in seeder
    assert "AsyncKorTravelMapClient" in seeder
    assert "FeatureKind.PLACE" in seeder
    assert "FeatureKind.WEATHER" in seeder
    assert "FeatureKind.PRICE" in seeder
    assert "weather_values_inserted" in seeder
    assert "price_values_inserted" in seeder
    assert "upsert_provider_refresh_policy" in seeder
    assert "stale_after_minutes=24 * 60" in seeder
    assert '_PROVIDER: Final[str] = "python-khoa-api"' in seeder
    assert '_DATASET_KEY: Final[str] = "khoa_beaches"' in seeder

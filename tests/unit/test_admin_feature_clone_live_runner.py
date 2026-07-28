from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STATE_HELPER = _REPO_ROOT / "scripts" / "admin_feature_clone_live_state.py"
_RUNNER = _REPO_ROOT / "scripts" / "run-admin-feature-clone-live-acceptance.sh"
_COMMIT = "a" * 40
_IMAGE_ID = f"sha256:{'b' * 64}"
_SHA256 = "c" * 64


def _run_helper(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_STATE_HELPER), *arguments],
        check=check,
        capture_output=True,
        text=True,
    )


def _write_snapshot(path: Path, *, total: int, non_deleted: int = 100) -> None:
    _run_helper(
        "write-snapshot",
        "--path",
        str(path),
        "--active-owned-features",
        "0",
        "--clone-container-sha256",
        _SHA256,
        "--clone-system-identifier-sha256",
        "d" * 64,
        "--feature-non-deleted",
        str(non_deleted),
        "--feature-total",
        str(total),
        "--host-port",
        "15475",
        "--migration-head",
        "0066_curation_component_identity",
        "--nonterminal-owned-change-requests",
        "0",
        "--relation-count",
        "57",
    )


def _write_fixture(path: Path, *, features: int, weather: int, price: int) -> None:
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
                "foreign_key_references": 0,
                "version": 1,
            }
        ),
        encoding="utf-8",
    )


def _write_report(directory: Path) -> None:
    directory.mkdir()
    (directory / "c7-results.xml").write_text("<testsuites/>", encoding="utf-8")
    (directory / "c7-summary.html").write_text("<!doctype html>", encoding="utf-8")
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


def _prepare_runtime(tmp_path: Path) -> tuple[Path, Path]:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    blocked = tmp_path / "BLOCKED.json"
    _run_helper(
        "write-blocked",
        "--path",
        str(blocked),
        "--phase",
        "fixture-seed-pending",
        "--run-id",
        "clone-20260729000000-abcdef123456",
        "--run-key",
        "e" * 64,
        "--api-image-id",
        _IMAGE_ID,
        "--clone-identity-sha256",
        _SHA256,
        "--playwright-image-id",
        f"sha256:{'f' * 64}",
        "--source-commit",
        _COMMIT,
        "--ui-image-id",
        f"sha256:{'1' * 64}",
    )
    _write_snapshot(runtime / "clone-startup-before.json", total=120)
    _write_snapshot(runtime / "clone-startup-after.json", total=120)
    _write_snapshot(runtime / "clone-final.json", total=126)
    _write_fixture(
        runtime / "direct-seed.json", features=2, weather=1, price=1
    )
    _write_fixture(
        runtime / "direct-cleanup.json", features=0, weather=0, price=0
    )
    _write_fixture(
        runtime / "direct-audit.json", features=0, weather=0, price=0
    )
    _write_report(runtime / "playwright-main")
    _write_report(runtime / "playwright-recovery")
    return runtime, blocked


def test_complete_validates_evidence_and_clears_blocked(tmp_path: Path) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    result = runtime / "result.json"

    _run_helper(
        "complete",
        "--blocked-path",
        str(blocked),
        "--phase",
        "passed",
        "--result-path",
        str(result),
        "--runtime",
        str(runtime),
    )

    assert not blocked.exists()
    payload = json.loads(result.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["phase"] == "passed"
    assert payload["source_commit"] == _COMMIT
    assert payload["tests"] == {
        "main": {"passed": 2},
        "recovery": {"passed": 2},
    }
    assert payload["cleanup"] == {
        "api_owned_active_features": 0,
        "api_owned_nonterminal_change_requests": 0,
        "foreign_key_references": 0,
        "owned_features": 0,
        "post_cleanup_audit_features": 0,
    }


def test_complete_rejects_startup_db_mutation(tmp_path: Path) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    _write_snapshot(runtime / "clone-startup-after.json", total=121)

    completed = _run_helper(
        "complete",
        "--blocked-path",
        str(blocked),
        "--phase",
        "passed",
        "--result-path",
        str(runtime / "result.json"),
        "--runtime",
        str(runtime),
        check=False,
    )

    assert completed.returncode != 0
    assert blocked.exists()
    assert not (runtime / "result.json").exists()


def test_runner_fail_closes_prod_and_proves_exact_isolated_identity() -> None:
    source = _RUNNER.read_text(encoding="utf-8")

    assert (
        'INSTALL_BASE="/usr/local/lib/kor-travel-map/'
        'admin-feature-clone-live-acceptance"'
    ) in source
    assert 'STATE_ROOT="/var/lib/kor-travel-map/admin-feature-clone-live-acceptance"' in source
    assert "kor-travel-docker-manager" in source
    assert "DB_HOST_PORT != 5432" in source
    assert "port != 12701 && port != 12705" in source
    assert "clone-startup-before.json" in source
    assert "clone-startup-after.json" in source
    assert "clone-final.json" in source
    assert "git_repo archive" in source
    assert "org.opencontainers.image.revision" in source
    assert "io.kortravelmap.c7.repository-commit" in source
    assert "-m uvicorn kortravelmap.api.app:app" in source
    assert "alembic upgrade" not in source
    assert "E2E_LIVE_ALLOW_PROD" not in source
    assert "E2E_ISOLATED_LIVE_EVIDENCE=1" in source


@pytest.mark.parametrize(
    "unsafe_entry",
    ["trace.zip", "screenshot.png", "extra.json"],
)
def test_complete_rejects_extra_browser_evidence(
    tmp_path: Path, unsafe_entry: str
) -> None:
    runtime, blocked = _prepare_runtime(tmp_path)
    (runtime / "playwright-main" / unsafe_entry).write_text("unsafe", encoding="utf-8")

    completed = _run_helper(
        "complete",
        "--blocked-path",
        str(blocked),
        "--phase",
        "passed",
        "--result-path",
        str(runtime / "result.json"),
        "--runtime",
        str(runtime),
        check=False,
    )

    assert completed.returncode != 0
    assert blocked.exists()

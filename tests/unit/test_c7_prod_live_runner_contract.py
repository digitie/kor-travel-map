"""C7 prod live runner의 fail-closed 정적 계약 회귀 테스트."""

import re
import subprocess
from pathlib import Path

import pytest

from scripts.lib import c7_prod_runtime as _RUNTIME_MODULE

# 기대 목록은 **테스트가** 적는다. 모듈 상수에서 파생시키면 "모듈이 스스로를 만족한다"는
# 항등식이 되어 아무것도 보지 않는다(2026-08-20 적대 리뷰 지적).
_EXPECTED_ROLE_SERVICE_ENVS = (
    ("map_api", "E2E_C7_MAP_API_SERVICE"),
    ("map_ui", "E2E_C7_UI_SERVICE"),
    ("map_dagster_web", "E2E_C7_DAGSTER_WEB_SERVICE"),
    ("map_dagster_daemon", "E2E_C7_DAGSTER_DAEMON_SERVICE"),
    ("pinvi_api", "E2E_C7_PINVI_API_SERVICE"),
    ("pinvi_web", "E2E_C7_PINVI_WEB_SERVICE"),
    ("pinvi_dagster", "E2E_C7_PINVI_DAGSTER_SERVICE"),
)

#: ADR-102 결정 6이 걷어낸 attestation 체인의 흔적. 러너가 이것들을 다시 요구하면
#: Manager 내부 파일 모양이 바뀔 때마다 러너가 함께 깨지던 결합이 되살아난다.
_RETIRED_CHAIN_MARKERS = (
    "E2E_C7_PINNED_RUNTIME_MANIFEST",
    "E2E_C7_REBUILD_JOURNAL",
    "rebuild_journal_sha256",
    "pinned_runtime_manifest_sha256",
    "host_attestation_sha256",
    "c7_prod_attestation",
    "/etc/kor-travel-map",
    "/usr/local/lib/kor-travel-map",
    "orchestrator_files",
)

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-c7-prod-live-e2e.sh"
RUNTIME = ROOT / "scripts" / "lib" / "c7_prod_runtime.py"
LIVE_DIR = (
    ROOT / "packages" / "kor-travel-map-admin" / "frontend" / "e2e" / "live"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _bash_function(source: str, name: str) -> str:
    """러너 소스에서 함수 정의 하나를 **그대로** 떼어 낸다(본문은 열 0의 `}`로 끝난다)."""

    start = source.index(f"\n{name}() {{\n") + 1
    return source[start : source.index("\n}\n", start) + 3]


def _section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    return source[start_index : source.index(end, start_index)]


def _assert_in_order(source: str, *markers: str) -> None:
    cursor = 0
    for marker in markers:
        cursor = source.index(marker, cursor) + len(marker)


def test_final_runner_anchors_host_login_and_causal_poi_spec() -> None:
    script = _read(RUNNER)

    assert "require_command node" not in script
    assert "require_command npm" not in script
    assert "\nnpm run e2e:live" not in script
    assert "docker_run_playwright npm run e2e:live" in script
    assert "docker_run_playwright node -" in script
    assert "| python " not in script
    _assert_in_order(
        script,
        "require_command python3\n",
        "\nvalidate_environment\n",
        "verify_runtime_preflight 2>/dev/null ||",
        "verify_alembic_state",
        "verify_ui_auth_preflight ||",
        "initialize_state_paths\n",
        "verify_clean_state_audit\n",
        "start_orchestrator_lock_guard\n",
        '[[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]]',
        "has_residual_state &&",
        "create_blocked_sentinel\n",
        "trap finish EXIT\n",
        "trap 'exit_for_signal 130' INT\n",
        "trap 'exit_for_signal 143' TERM",
    )
    # preflight 모듈은 러너와 **같은 체크아웃**에서 읽는다(고정 설치 경로가 아니다).
    assert 'python3 -I -B "$SCRIPT_DIR/lib/c7_prod_runtime.py" runtime' in script
    assert 'python3 "$SCRIPT_DIR/audit-c7-prod-live-state.py"' in script
    assert 'REPOSITORY_COMMIT="$E2E_C7_EXPECTED_GIT_COMMIT"' in script
    assert "require_command git" not in script
    assert 'response.status != 200' in script
    assert 'response.headers.get("Set-Cookie")' in script
    assert 'poi-cache-targets-write.live.spec.ts' in script
    assert 'state_is_exact_restored poi "$POI_STATE_FILE"' in script
    # causal POI spec 선택은 한글 제목이 아니라 안정 tag grep으로 고정한다.
    assert '"@c7-causal"' in script
    assert "API PUT로 target을" not in script
    assert "--pass-with-no-tests" not in script


def test_final_restore_probe_parses_problem_json_and_requires_exact_404() -> None:
    script = _read(RUNNER)

    assert 'contentType.toLowerCase().includes("json")' in script
    assert 'startsWith("application/problem+json")' in script
    assert 'item.result.status === 404' in script
    assert 'item.result.body.code === "NOT_FOUND"' in script
    assert 'item.count === 0' in script


def test_poi_cleanup_is_journaled_and_conditional() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")
    poi_spec = _read(LIVE_DIR / "poi-cache-targets-write.live.spec.ts")

    assert '"target_put_intent"' in helper
    assert 'headers: { "If-Match": entityTag }' in helper
    assert 'result.status === 412' in helper
    assert '"delete_conflict"' in helper
    assert '"create_put_intent"' in poi_spec
    assert '"update_put_intent"' in poi_spec
    assert '"cleanup_delete_intent"' in poi_spec
    assert "@c7-causal" in poi_spec
    assert 'deleted.status === 412' in poi_spec
    assert 'sameSocketReceipts' in poi_spec


def test_kma_target_recreation_and_response_loss_are_durable() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")

    assert 'target_history: TargetJournalRef[]' in helper
    assert 'state.targetHistory.push({ ...target })' in helper
    assert 'state.targets[index] = target' in helper
    assert 'status: "put_response_lost"' in helper
    assert 'status: "put_replay_pending"' in helper
    assert '"target_put_replay_response_lost"' in helper
    assert 'recoverUnresolvedTargetIntents' in helper
    assert 'kind: "target_intent_recovery"' in helper
    assert 'exactTargetDiscoveryComplete' in helper
    assert 'preservedForManualCleanup' in helper
    assert "targetId === previousTarget.targetId" in helper
    assert "identity.entityTag === previousTarget.entityTag" in helper
    assert 'identity.lockVersion !== 1' in helper
    assert 'item.status === "deleted"' in helper


def test_previous_journal_is_validated_before_non_overwriting_merge() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")
    merge = _section(
        helper,
        "async function mergePreviousJournal(",
        "async function writeDurableJournal(",
    )

    residue = merge.index("if (!isOrchestratorPlaceholder && !isCurrentScenario)")
    merge_comment = merge.index("previous payload 자체가 완전한 restored 상태", residue)
    target_merge = merge.index(
        "if (existing === undefined) state.allTargetRefs.set(key, item);",
        merge_comment,
    )
    assert residue < merge_comment < target_merge
    assert "state.idempotencyEntries.has(value.idempotency_key)" in merge
    assert "state.requestTerminalStatuses.get(requestId)" in merge
    assert "state.allTargetRefs.set(key, item);" not in merge[:target_merge]


def test_every_kma_create_has_exact_server_target_preflight() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")
    create = _section(
        helper,
        "export async function createKmaRequest(",
        "export type TrackedUiKmaCreateResult",
    )

    _assert_in_order(
        create,
        "const expectedTargets = state.targets.filter(",
        "await assertExactOwnedTargetsAtServer(",
        "await journalPendingRequest(",
        "await submit()",
    )
    assert "const OWNED_TARGET_PAGE_SIZE = 500" in helper
    assert "const OWNED_TARGET_SET_LIMIT = 501" in helper
    assert "const OWNED_TARGET_PAGE_LIMIT = 2" in helper
    assert "page_size: String(OWNED_TARGET_PAGE_SIZE)" in helper
    assert 'include_deleted: "false"' in helper
    assert "const seenCursors = new Set<string>()" in helper
    assert "seenCursors.has(nextCursor)" in helper
    assert "target cursor page limit(2) 초과" in helper
    assert 'if (!exactJson(observed, expected))' in helper


def test_every_kma_run_now_has_exact_server_target_preflight() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")
    tracked = _section(
        helper,
        "export async function runTrackedRequestNowFromUi(",
        "export async function runRequestNow(",
    )
    direct = _section(
        helper,
        "export async function runRequestNow(",
        "export async function journalRunNowMutation(",
    )

    for source, journal_marker in (
        (tracked, 'journalRunNowMutation(state, requestId, "pending")'),
        (direct, 'writeDurableJournal(state, "run_now_pending")'),
    ):
        _assert_in_order(
            source,
            "const expectedTargets = state.targets.filter(",
            "await assertExactOwnedTargetsAtServer(",
            journal_marker,
        )
    _assert_in_order(
        tracked,
        "await assertExactOwnedTargetsAtServer(",
        'journalRunNowMutation(state, requestId, "pending")',
        "await route.continue()",
    )


def test_kma_preview_terminal_and_metadata_are_exact_kma_only() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")
    active = _read(LIVE_DIR / "ops-c7-kma-active-write.live.spec.ts")
    empty = _read(LIVE_DIR / "ops-c7-kma-empty-write.live.spec.ts")
    cap = _read(LIVE_DIR / "ops-c7-kma-cap-write.live.spec.ts")

    assert "assertExactKmaPreviewResponse" in helper
    assert "assertKmaOnlyTerminalProviderScopes" in helper
    assert '"eligible_provider_scopes"' in helper
    assert '"skipped_provider_scopes"' in helper
    assert '"executed_provider_scopes"' in helper
    assert "assertOnlyKmaCanonicalIdentity(matched" in helper
    assert "FORBIDDEN_PROVIDER_PATTERN" in helper
    assert "providerDatasets.length !== 1" in helper
    # identity는 triple이다(ADR-088). 자연키는 생산자가 strip하므로 여기서 단언하면
    # 항상 실패한다 — 아래 test_live_helper_does_not_assert_stripped_identity_keys 참조.
    assert "entry.provider_dataset_id !== identity.providerDatasetId" in helper
    assert "entry.operation_key !== identity.operationKey" in helper
    assert "entry.sync_scope !== expectedEffectiveSyncScope" in helper
    assert "entry.feature_count < 0" in helper
    for spec in (active, empty, cap):
        assert "assertExactKmaPreviewResponse(" in spec
        assert "assertKmaOnlyTerminalProviderScopes(" in spec
    assert "const LOWERCASE_SHA256_PATTERN = /^[0-9a-f]{64}$/" in active
    assert "isCanonicalKmaBaseDatetime" in active
    assert "KMA_BASE_DATETIME_PATTERN" in active


def test_live_helper_does_not_assert_stripped_identity_keys() -> None:
    """matched_scope 단언이 생산자가 strip하는 자연키를 건드리지 않는다.

    `api/feature_update_service._public_matched_scope`가
    `_NATURAL_IDENTITY_RESPONSE_KEYS`를 응답에서 지운다("실행 진단에서 legacy natural
    identity projection을 유출하지 않는다"). 그 자리에서 `provider`/`dataset_key`를
    단언하면 **항상** 실패한다.

    이 게이트가 필요한 이유는 앞 판이 정확히 반대로 했기 때문이다 — 소스 pin이
    `pair.provider !== KMA_PROVIDER` 같은 **소비자 쪽 문자열을 고정**해서, 드리프트를
    잡기는커녕 stale 단언을 얼려 두고 있었다. 그래서 계약이 바뀐 뒤에도 CI는 green이었고
    prod C7 실행에서만 드러났다. 이번에는 축을 **생산자 상수에서 읽어** 대조한다.
    """

    from kortravelmap.api.feature_update_service import (
        _NATURAL_IDENTITY_RESPONSE_KEYS,
    )

    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")
    preview = _section(
        helper,
        "function assertExactKmaPreviewBody(",
        "export async function assertExactKmaPreviewResponse(",
    )
    terminal = _section(
        helper,
        "export function assertKmaOnlyTerminalProviderScopes(",
        "export async function createKmaRequest(",
    )
    assert _NATURAL_IDENTITY_RESPONSE_KEYS, "생산자 상수가 비었다"
    for section, label in ((preview, "preview"), (terminal, "terminal")):
        for key in _NATURAL_IDENTITY_RESPONSE_KEYS:
            reason = (
                f"{label} 단언이 생산자가 strip하는 `{key}`를 본다 — "
                "triple(provider_dataset_id/sync_scope/operation_key)로 단언하라"
            )
            # 속성 접근 두 모양(`x.key !==`, `x.key!==`)을 각각 본다.
            assert f".{key} " not in section, reason
            assert f".{key}!" not in section, reason


def test_kma_dagster_job_and_terminal_run_identity_are_exact() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")
    specs = [
        _read(LIVE_DIR / name)
        for name in (
            "ops-c7-kma-active-write.live.spec.ts",
            "ops-c7-kma-empty-write.live.spec.ts",
            "ops-c7-kma-cap-write.live.spec.ts",
        )
    ]

    assert '"feature_update_request_worker" as const' in helper
    assert "pipelines { name isJob }" in helper
    assert "matches.length !== 1 || matches[0]?.isJob !== true" in helper
    terminal = _section(
        helper,
        "async function assertTerminalDagsterRunIdentity(",
        "function parseStrongEntityTag(",
    )
    for marker in (
        "run.runId !== runId",
        "run.jobName !== KMA_SAFE_DAGSTER_JOB",
        "FEATURE_UPDATE_REQUEST_ID_TAG",
        "FEATURE_UPDATE_REQUEST_GENERATION_TAG",
        'FEATURE_UPDATE_SCOPE_TYPE_TAG) !== "provider_dataset"',
        "sensorName !== QUEUE_SENSOR_NAME",
    ):
        assert marker in terminal
    wait = _section(
        helper,
        "export async function waitForTerminal(",
        "export async function rediscoverExactActiveRequest(",
    )
    _assert_in_order(
        wait,
        'await writeDurableJournal(state, "request_terminal")',
        "await assertTerminalDagsterRunIdentity(page, detail)",
        "return detail",
    )
    for spec, mutation_marker in zip(
        specs,
        (
            "await withC7Cleanup(",
            "await previewEmptyRequestFromUi(",
            "await withC7Cleanup(",
        ),
        strict=True,
    ):
        _assert_in_order(
            spec,
            'await bootstrapC7SameOriginPage(page, "/ops/pipeline")',
            "await assertKmaDagsterWorkerJobDefinition()",
            mutation_marker,
        )


def test_route_handlers_have_settlement_barriers() -> None:
    live_browser = _read(LIVE_DIR / "_ops-live-browser.ts")
    read_auth = _read(LIVE_DIR / "ops-c7-read-auth.live.spec.ts")
    schedule = _read(LIVE_DIR / "ops-c7-schedule-write.live.spec.ts")

    # 두 복구-leg 핸들러(expired-recovery·healthy-rotation)의 재연결 leg는 route.fetch()
    # passthrough(Playwright가 Sec-Fetch-Site 미전달 -> BFF 403) 대신 route.continue()로
    # 실제 브라우저 요청을 그대로 전달한다(#809). settlement barrier(waitForSettlement ->
    # unroute)는 그대로 유지되므로 각 핸들러가 unroute 전에 정착하는지 검증한다.
    cursor = 0
    for _ in range(2):
        route_action = live_browser.index("await route.continue()", cursor)
        settled = live_browser.index("await waitForSettlement()", route_action)
        unroute = live_browser.index("await page.unroute", settled)
        assert route_action < settled < unroute
        cursor = unroute + 1

    schedule_mutation = _section(
        schedule,
        "async function submitUiMutation(",
        "function safeFutureCron(",
    )
    _assert_in_order(
        schedule_mutation,
        "await route.fetch()",
        "waitForRouteHandlers()",
        ".unroute(routeMatcher, routeHandler)",
    )
    logout = read_auth[read_auth.index('test("LAST: 실제 로그아웃') :]
    _assert_in_order(
        logout,
        "await route.fetch()",
        "logoutRouteSettled",
        '.unroute("**/api/auth/logout", logoutRoute)',
    )
    assert "OPS_LIVE_UNAUTHORIZED_CLOSE_CODE" in read_auth
    assert "OPS_LIVE_EXPIRED_CLOSE_CODE" in read_auth


def test_all_c7_journals_fsync_before_and_after_atomic_rename() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")
    sensor = _read(LIVE_DIR / "_ops-c7-dagster-sensor.ts")
    schedule = _read(LIVE_DIR / "ops-c7-schedule-write.live.spec.ts")
    poi = _read(LIVE_DIR / "poi-cache-targets-write.live.spec.ts")

    helper_write = _section(
        helper,
        "async function writeDurableJournal(",
        "/**\n * 브라우저 인증 세션",
    )
    sensor_write = _section(
        sensor,
        "async #persist(",
        "export async function createQueueSensorController(",
    )
    schedule_write = _section(
        schedule,
        "async function persistRecoveryState(",
        "async function persistMutationState(",
    )
    poi_write = _section(
        poi,
        "async function writePoiJournal(",
        "function apiPath(",
    )
    for source in (helper_write, sensor_write, schedule_write, poi_write):
        _assert_in_order(
            source,
            "await writeFile(",
            "await temporaryHandle.sync()",
            "await rename(",
            "await stateHandle.sync()",
            "await directoryHandle.sync()",
        )


def test_runner_uses_fixed_root_owned_atomic_state() -> None:
    script = _read(RUNNER)
    atomic = _section(script, "atomic_replace_state()", "runtime_is_private_direct_child()")

    assert 'FIXED_STATE_ROOT="/var/lib/kor-travel-map/c7-prod-live-e2e"' in script
    assert 'XDG_STATE_HOME override is forbidden' in script
    assert '"$(stat -c \'%u:%g:%a\' -- "$STATE_ROOT")" == "0:0:700"' in script
    assert 'BLOCKED_FILE="$STATE_ROOT/BLOCKED.json"' in script
    assert 'LOCK_FILE="$STATE_ROOT/orchestrator.lock"' in script
    _assert_in_order(
        atomic,
        'temporary="$(mktemp "$STATE_ROOT/.state.XXXXXX")"',
        'fsync_file_and_parent "$temporary"',
        'mv -T -- "$temporary" "$destination"',
        'fsync_file_and_parent "$destination"',
    )
    assert 'atomic_replace_state "$BLOCKED_FILE"' in script
    lock_guard = _section(
        script,
        "start_orchestrator_lock_guard()",
        "runtime_is_private_direct_child()",
    )
    assert "os.O_NOFOLLOW" in lock_guard
    assert "os.O_CREAT" in lock_guard
    assert "stat.S_ISREG" in lock_guard
    assert "observed.st_uid != 0" in lock_guard
    assert "stat.S_IMODE(observed.st_mode) != 0o600" in lock_guard
    assert "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)" in lock_guard
    assert "O_TRUNC" not in lock_guard
    invocation = script[
        script.index("# 여기까지는 수집/파이프라인 domain state를 바꾸지 않는 preflight다.") :
    ]
    _assert_in_order(
        invocation,
        "verify_runtime_preflight",
        "verify_alembic_state",
        "verify_ui_auth_preflight",
        "initialize_state_paths",
        "verify_clean_state_audit",
        "start_orchestrator_lock_guard",
        '[[ ! -e "$BLOCKED_FILE" && ! -L "$BLOCKED_FILE" ]]',
        "has_residual_state",
        "create_blocked_sentinel",
    )


def test_runner_uses_attested_immutable_playwright_executor_and_redacted_evidence() -> None:
    script = _read(RUNNER)
    runtime = _read(RUNTIME)
    build_script = _read(ROOT / "scripts" / "build-c7-playwright-image.sh")
    lifecycle = _read(ROOT / "scripts" / "lib" / "c7-prod-runner-lifecycle.sh")
    dockerfile = _read(ROOT / "docker" / "c7-playwright.Dockerfile")
    dockerignore = _read(ROOT / ".dockerignore")
    compose = _read(ROOT / "docker-compose.yml")
    config = _read(
        ROOT
        / "packages"
        / "kor-travel-map-admin"
        / "frontend"
        / "playwright.live.config.ts"
    )
    reporter = _read(
        ROOT
        / "packages"
        / "kor-travel-map-admin"
        / "frontend"
        / "e2e"
        / "c7-redacted-reporter.ts"
    )
    admin_helper = _read(
        ROOT
        / "packages"
        / "kor-travel-map-admin"
        / "frontend"
        / "e2e"
        / "live"
        / "_ops-c7-admin-api.ts"
    )

    assert "mcr.microsoft.com/playwright:v1.60.0-noble@sha256:" in dockerfile
    assert 'git -C "$REPO_ROOT" archive --format=tar "$commit"' in build_script
    assert "--pull=false" in build_script
    assert "**/*.tsbuildinfo" in dockerignore
    assert "**/*.local.md" in dockerignore
    assert 'io.kortravelmap.c7.repository-commit' in dockerfile
    assert 'io.kortravelmap.c7.playwright-base' in dockerfile
    for image_dockerfile in ("api.Dockerfile", "dagster.Dockerfile", "frontend.Dockerfile"):
        source = _read(ROOT / "docker" / image_dockerfile)
        assert 'LABEL org.opencontainers.image.revision="$KOR_TRAVEL_MAP_GIT_COMMIT"' in source
    revision_arg = "KOR_TRAVEL_MAP_GIT_COMMIT: ${KOR_TRAVEL_MAP_GIT_COMMIT:-development}"
    assert compose.count(revision_arg) == 7
    frontend_build = _section(compose, "  frontend:\n", "    environment:\n")
    assert frontend_build.count("      args:\n") == 1
    assert "        KOR_TRAVEL_MAP_GIT_COMMIT:" in frontend_build
    assert "        NEXT_PUBLIC_KOR_TRAVEL_MAP_API:" in frontend_build
    assert '[[ "$E2E_C7_PLAYWRIGHT_IMAGE" =~ ^sha256:' in script
    assert 'executor.get("Id") != executor_image' in runtime
    assert 'executor_labels.get("io.kortravelmap.c7.repository-commit") != commit' in runtime
    assert 'image_labels.get("org.opencontainers.image.revision") != commit' in runtime
    # 모듈 상수가 기대 목록과 **정확히** 같아야 한다. 빠지면 그 runtime이 검사 밖에
    # 남고(그것이 v4의 결함이었다), 늘면 테스트가 모르는 runtime이 생긴 것이다.
    assert tuple(_RUNTIME_MODULE.ROLE_SERVICE_ENVS) == _EXPECTED_ROLE_SERVICE_ENVS
    assert "len(set(role_services.values())) != len(role_services)" in runtime
    assert "len(observed_containers) != len(role_services)" in runtime
    # cleanup journal 계약: 최종본은 v4이고 소유권 결박을 싣는다. v3는 첫 durable
    # write 전 bootstrap placeholder 전용이다. 이 단언이 없으면 browser lane과 shell이
    # 서로 다른 version을 요구하는 상태가 CI green으로 남는다(2026-08-20 실측).
    assert 'state.get("version") != 4' in script
    assert 'state.get("request_ownership"), list' in script
    assert (
        '"run_id":"__orchestrator_pending__","target_history":[],'
        '"target_refs":[],"version":3}' in script
    )
    assert 'docker create --pull=never' in script
    assert 'docker start --attach --interactive' in script
    assert "--network bridge --ipc private" in script
    assert "--network host" not in script
    assert "--ipc host" not in script
    assert "write_container_reference \\\n    creating" in script
    assert '"phase": phase' in script
    assert '\\"phase\\":\\"create\\"' in script
    assert "--read-only" in script
    assert "--security-opt no-new-privileges" in script
    assert "--cap-drop ALL" in script
    assert 'kill -0 "$LOCK_GUARD_PID"' in script
    assert 'ACTIVE_COMMAND_PID=$!' in script
    _assert_in_order(
        lifecycle,
        'kill -TERM -- "-$pgid"',
        'kill -KILL -- "-$pgid"',
    )
    assert '"c7-results.xml"' in script
    assert 'source.suffix.lower() == ".png"' not in script
    assert "testInfo.attach(" not in admin_helper
    assert "c7-cleanup-manifest.json" not in admin_helper
    assert 'trace: redactedEvidence ? "off"' in config
    assert 'screenshot: redactedEvidence ? "off"' in config
    assert '"./e2e/c7-redacted-reporter.ts"' in config
    assert (
        'path.join(\n  "/tmp",\n  `kor-travel-map-c7-test-results-${process.pid}`'
        in config
    )
    assert "outputDir: redactedEvidence" in config
    assert "? c7RawOutputDir" in config
    assert ': path.join(artifactRoot, "test-results")' in config
    assert "test.location.file" in reporter
    assert "result.errors" not in reporter
    assert "result.stdout" not in reporter
    assert "result.stderr" not in reporter


def test_runner_preserves_recovery_state_on_failure_and_runs_full_audit() -> None:
    script = _read(RUNNER)
    finish = _section(script, "finish()", "create_blocked_sentinel()")

    assert 'python3 "$SCRIPT_DIR/audit-c7-prod-live-state.py" >/dev/null' in script
    _assert_in_order(
        script,
        "initialize_state_paths\n",
        "verify_clean_state_audit\n",
        "start_orchestrator_lock_guard\n",
    )
    # `container_clean/evidence_preserved` 조합의 세 번째는 attested input 사본 삭제를
    # 지키던 블록이었다(ADR-102에서 사본과 함께 사라졌다). 남은 둘은 runtime 정리와 그
    # 거절 분기다.
    assert finish.count("status == 0 && ORCHESTRATOR_VERIFIED == 1") >= 3
    assert finish.count("container_clean == 1 && evidence_preserved == 1") >= 2
    assert finish.index('rm -f -- "$E2E_STORAGE_STATE"') < finish.index(
        'rm -rf -- "$RUNTIME_DIR"'
    )


def test_runner_requires_distinct_recreated_target_history() -> None:
    script = _read(RUNNER)

    assert "if not isinstance(target_history, list) or not target_history" in script
    assert "current_by_natural_key" in script
    assert 'item["targetId"] in current_target_ids' in script
    assert "raise SystemExit(36)" in script


def test_causal_poi_put_response_loss_is_exact_and_fail_closed() -> None:
    poi = _read(LIVE_DIR / "poi-cache-targets-write.live.spec.ts")
    recovery = _section(
        poi,
        "async function putWithCausalResponseRecovery(",
        "function causalRevision(",
    )

    _assert_in_order(
        recovery,
        '`${phase}_put_response_lost`',
        "const rediscovered = await fetchTarget(page)",
        "assertExactIntendedTarget(",
        '`${phase}_put_replay_intent`',
        "result = await put()",
        "const exactRead = await fetchTarget(page)",
    )
    assert "causal receipt가 유실되어 BLOCKED" in recovery
    cleanup = poi[poi.index("} finally {") :]
    assert "assertExactIntendedTarget(" in cleanup
    assert "deleteTargetByApi(" in cleanup


def test_causal_poi_create_injects_committed_response_loss_once() -> None:
    poi = _read(LIVE_DIR / "poi-cache-targets-write.live.spec.ts")
    injection = _section(
        poi,
        "async function putWithDeterministicCommittedResponseLoss(",
        "function causalRevision(",
    )
    create_step = _section(
        poi,
        'test.step("API PUT로 고유 target을 생성하고 GET으로 영속화를 확인한다"',
        'test.step("admin 목록을 다시 열면',
    )

    _assert_in_order(
        injection,
        "const upstream = await route.fetch()",
        "committed = evidence",
        'await route.abort("failed")',
        "putWithCausalResponseRecovery(",
        "() => committed",
        "waitForSettlement()",
        ".unroute(exactUrl, routeHandler)",
    )
    assert "putAttempts !== 1" in injection
    assert "committed response-loss primary/route cleanup 실패" in injection
    assert "putWithDeterministicCommittedResponseLoss(" in create_step
    assert "putWithCausalResponseRecovery(" not in create_step


def test_kma_cursor_requires_canonical_nonempty_base_datetime() -> None:
    active = _read(LIVE_DIR / "ops-c7-kma-active-write.live.spec.ts")
    cursor = _section(
        active,
        "function cursorMembershipFingerprint(",
        'test.describe("C7 KMA active',
    )

    assert 'expect(typeof baseDatetime).toBe("string")' in cursor
    assert "expect(isCanonicalKmaBaseDatetime(baseDatetime)).toBe(true)" in cursor
    assert "if (baseDatetime !== undefined)" not in cursor


# -- ADR-102 결정 6: attestation 체인 제거 ------------------------------------


def test_runner_no_longer_requires_the_retired_attestation_chain() -> None:
    """러너와 preflight 모듈은 Manager manifest/journal·host attestation·root 스냅샷을 모른다."""

    script = _read(RUNNER)
    runtime = _read(RUNTIME)
    runtime_code = runtime[runtime.index("from __future__") :]
    for marker in _RETIRED_CHAIN_MARKERS:
        assert marker not in script, f"C7 러너가 퇴역한 체인을 다시 요구한다: {marker}"
        assert marker not in runtime_code, f"preflight 모듈이 퇴역한 체인을 읽는다: {marker}"
    assert not (ROOT / "scripts" / "lib" / "c7_prod_attestation.py").exists()


def test_evidence_manifest_v3_carries_no_attested_document_digest() -> None:
    script = _read(RUNNER)
    evidence = _section(script, "preserve_evidence() {", "\nfinish() {")
    manifest = _section(evidence, "manifest = {", "}\n")

    assert '"version": 3,' in manifest
    assert set(re.findall(r'"([a-z_]+)":', manifest)) == {
        "alembic_head",
        "files",
        "finished_at",
        "orchestrator_verified",
        "playwright_image_id",
        "repository_commit",
        "status",
        "version",
    }
    # 사본을 archive에 넣던 경로도 함께 사라졌다.
    assert "runtime-attestation.json" not in evidence
    assert "pinned-runtime-rebuild.json" not in evidence


_C7_ENV = {
    "E2E_BASE_URL": "https://map.example.test",
    "NEXT_PUBLIC_KOR_TRAVEL_MAP_API": "https://api.example.test",
    "E2E_DAGSTER_URL": "https://dagster.example.test/graphql",
    "E2E_ADMIN_PASSWORD": "redacted",
    "E2E_DAGSTER_JOB": "feature_update_request_worker",
    "E2E_C7_SCHEDULE": "feature_weather_kma_short_forecast_hourly_schedule",
    "E2E_C7_EXPECTED_GIT_COMMIT": "a" * 40,
    "E2E_C7_PLAYWRIGHT_IMAGE": "sha256:" + "3" * 64,
    "E2E_C7_EXPECTED_UI_ORIGIN_SHA256": "1" * 64,
    "E2E_C7_EXPECTED_API_WS_ORIGIN_SHA256": "2" * 64,
    "E2E_C7_EXPECTED_DAGSTER_ORIGIN_SHA256": "4" * 64,
    "E2E_C7_DAGSTER_WEB_SERVICE": "map-web",
    "E2E_C7_DAGSTER_DAEMON_SERVICE": "map-daemon",
    "E2E_C7_UI_SERVICE": "map-ui",
    "E2E_C7_MAP_API_SERVICE": "map-api",
    "E2E_C7_PINVI_API_SERVICE": "pinvi-api",
    "E2E_C7_PINVI_WEB_SERVICE": "pinvi-web",
    "E2E_C7_PINVI_DAGSTER_SERVICE": "pinvi-dagster",
    "E2E_LIVE_ALLOW_PROD": "1",
    "E2E_ADMIN_WRITE": "1",
    "E2E_C7_READ_AUTH_WRITE": "1",
    "E2E_KMA_SCOPE_WRITE": "1",
    "E2E_DAGSTER_WRITE": "1",
    "E2E_DAGSTER_RUN": "1",
    "E2E_QUEUE_SENSOR_BARRIER": "1",
}


def _run_c7_environment_validation(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """러너의 env 계약 함수를 **소스 그대로** 떼어 실행한다(root·docker 없이)."""

    script = _read(RUNNER)
    readonly = "\n".join(re.findall(r"^readonly SAFE_\w+=.*$", script, re.MULTILINE))
    functions = "".join(
        _bash_function(script, name)
        for name in (
            "die",
            "require_env",
            "require_enabled",
            "validate_sha256_env",
            "validate_service_env",
            "validate_environment",
        )
    )
    program = f"set -euo pipefail\n{readonly}\n{functions}validate_environment\necho ENV_OK\n"
    return subprocess.run(
        ["/bin/bash", "-c", program],
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", **env},
        text=True,
        timeout=10,
        check=False,
    )


def test_runner_env_contract_accepts_env_without_manifest_or_journal() -> None:
    """`.d2-live.env`에서 두 키를 지워도 러너가 env 단계에서 죽지 않는다."""

    assert "E2E_C7_PINNED_RUNTIME_MANIFEST" not in _C7_ENV
    assert "E2E_C7_REBUILD_JOURNAL" not in _C7_ENV
    accepted = _run_c7_environment_validation(_C7_ENV)
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout == "ENV_OK\n"


@pytest.mark.parametrize(
    "name", ["E2E_C7_EXPECTED_GIT_COMMIT", "E2E_C7_PLAYWRIGHT_IMAGE", "E2E_C7_UI_SERVICE"]
)
def test_runner_env_contract_still_rejects_each_kept_identity(name: str) -> None:
    """위 양성 결과가 '무엇이든 통과'가 아님을 같은 하네스로 보인다."""

    env = {key: value for key, value in _C7_ENV.items() if key != name}
    rejected = _run_c7_environment_validation(env)
    assert rejected.returncode == 1
    assert f"required env is missing: {name}" in rejected.stderr
    assert "ENV_OK" not in rejected.stdout

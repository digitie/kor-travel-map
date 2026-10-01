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
DAGSTER_SRC = (
    ROOT / "packages" / "kor-travel-map-dagster" / "src" / "kortravelmap" / "dagster"
)

#: C7 blocking gate가 도는 spec 목록. **테스트가** 적는다(러너에서 파생하면 항등식이다).
#: KMA exact-scope 3-spec(active/empty/cap)은 2026-10-01 퇴역했다(ADR-104/105).
_EXPECTED_C7_SPECS = (
    "e2e/live/ops-c7-read-auth.live.spec.ts",
    "e2e/live/ops-c7-schedule-write.live.spec.ts",
)
#: schedule-write가 실제로 조작하는 schedule. 실수로 tick이 나가도 upstream 호출이 0이어야
#: 한다 — 공항 fetcher는 krairport 번들 정적 데이터만 읽는다.
_EXPECTED_SAFE_SCHEDULE = "feature_place_krairport_airports_monthly_schedule"


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


def test_target_recreation_and_response_loss_are_durable() -> None:
    helper = _read(LIVE_DIR / "_ops-c7-admin-api.ts")

    assert 'target_history: TargetJournalRef[]' in helper
    assert 'state.targetHistory.push({ ...target })' in helper
    assert 'state.targets[index] = target' in helper
    assert 'status: "put_response_lost"' in helper
    assert 'status: "put_replay_pending"' in helper
    assert '"target_put_replay_response_lost"' in helper
    assert 'recoverUnresolvedTargetIntents' in helper
    assert 'kind: "target_intent_recovery"' in helper
    # 응답 유실 intent 하나라도 정체를 증명하지 못하면 어떤 target도 지우지 않는다.
    assert "const canDeleteTargets = targetRecovery.complete;" in helper
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

    placeholder = merge.index("if (isOrchestratorPlaceholder(raw)) return;")
    residue = merge.index("if (!isCurrentScenario) {", placeholder)
    merge_comment = merge.index("previous payload 자체가 완전한 restored 상태", residue)
    target_merge = merge.index(
        "if (existing === undefined) state.allTargetRefs.set(key, item);",
        merge_comment,
    )
    assert placeholder < residue < merge_comment < target_merge
    assert "state.allTargetRefs.set(key, item);" not in merge[:target_merge]
    # placeholder는 러너가 깔아 두는 **정확한** 꼴만 받는다(exactJson).
    assert (
        'const ORCHESTRATOR_PLACEHOLDER = { phase: "orchestrator_pending", version: 1 };'
        in helper
    )
    assert "exactJson(record, ORCHESTRATOR_PLACEHOLDER)" in helper


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
    schedule = _read(LIVE_DIR / "ops-c7-schedule-write.live.spec.ts")
    poi = _read(LIVE_DIR / "poi-cache-targets-write.live.spec.ts")

    helper_write = _section(
        helper,
        "async function writeDurableJournal(",
        "/**\n * 브라우저 인증 세션",
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
    for source in (helper_write, schedule_write, poi_write):
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
    # service는 서로 달라야 한다 — 공유 Dagster plane에서 Map web·daemon 두 role만 Map
    # code-server 하나를 함께 가리킬 수 있다(``SHAREABLE_ROLES``).
    assert "len(roles) > 1 and not roles <= shareable" in runtime
    assert 'shareable = SHAREABLE_ROLES if map_plane == "shared" else frozenset()' in runtime
    assert "len(observed_containers) != len(roles_by_service)" in runtime
    assert {"map_dagster_web", "map_dagster_daemon"} == _RUNTIME_MODULE.SHAREABLE_ROLES
    # target journal 계약: 최종본은 helper의 v1(`version: 1` + exact key 집합)이고, 러너는
    # 첫 durable write 전 helper가 받는 그 placeholder를 깐다. 한쪽만 바뀌면 browser lane과
    # shell이 서로 다른 모양을 요구하는 상태가 CI green으로 남는다(2026-08-20 실측).
    assert "version: 1;" in admin_helper
    assert 'state.get("version") != 1' in script
    assert '"$TARGET_STATE_FILE" \\\n  \'{"phase":"orchestrator_pending","version":1}\'' in script
    assert 'process.env.E2E_C7_TARGET_STATE_FILE' in admin_helper
    assert 'export E2E_C7_TARGET_STATE_FILE="$TARGET_STATE_FILE"' in script
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

    # 남은 시나리오(invalidation)는 target을 재생성하지 않으므로 이력은 비어 있을 수 있다.
    # 있으면 삭제가 증명돼야 하고 현재 identity와 겹치면 안 된다.
    assert "if not isinstance(target_history, list):" in script
    assert "if not all(deleted_target(item) for item in target_history):" in script
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
    "E2E_C7_SCHEDULE": _EXPECTED_SAFE_SCHEDULE,
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
    "E2E_DAGSTER_WRITE": "1",
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


@pytest.mark.parametrize(
    "schedule",
    [
        # 2026-09-09에 사라진 옛 KMA schedule — 러너가 이것을 다시 받으면 안 된다.
        "feature_weather_kma_short_forecast_hourly_schedule",
        "feature_place_krairport_airports_monthly_schedule_typo",
    ],
)
def test_runner_env_contract_rejects_a_non_allowlisted_schedule(schedule: str) -> None:
    rejected = _run_c7_environment_validation({**_C7_ENV, "E2E_C7_SCHEDULE": schedule})
    assert rejected.returncode == 1
    assert "not the allowlisted zero-upstream schedule" in rejected.stderr
    assert "ENV_OK" not in rejected.stdout


def test_runner_runs_exactly_the_expected_c7_specs() -> None:
    script = _read(RUNNER)
    block = _section(script, "readonly SPECS=(\n", "\n)\n")
    specs = tuple(re.findall(r'^  "([^"]+)"$', block, re.MULTILINE))
    assert specs == _EXPECTED_C7_SPECS
    for spec in specs:
        assert (ROOT / "packages" / "kor-travel-map-admin" / "frontend" / spec).is_file()


def test_safe_schedule_is_one_live_zero_upstream_schedule_everywhere() -> None:
    """allowlist schedule이 실재하고 꺼져 있지 않으며, 세 사본이 같은 값이다.

    옛 KMA schedule은 2026-09-09에 사라졌는데 러너·spec은 그 이름을 계속 들고 있어서 C7이
    그날부터 돌 수 없었다. 이름을 소스에서 읽어 정의 쪽(``schedules.py``)과 대조한다.
    """

    script = _read(RUNNER)
    spec = _read(LIVE_DIR / "ops-c7-schedule-write.live.spec.ts")
    schedules = _read(DAGSTER_SRC / "schedules.py")
    fetchers = _read(DAGSTER_SRC / "provider_fetchers.py")

    runner_value = re.search(r'^readonly SAFE_SCHEDULE="([^"]+)"$', script, re.MULTILINE)
    remote_value = re.search(r'^const SAFE_SCHEDULE = "([^"]+)";$', script, re.MULTILINE)
    spec_value = re.search(r'const SAFE_SCHEDULE =\s*"([^"]+)" as const;', spec)
    assert runner_value is not None
    assert remote_value is not None
    assert spec_value is not None
    values = {runner_value.group(1), remote_value.group(1), spec_value.group(1)}
    assert values == {_EXPECTED_SAFE_SCHEDULE}

    # 정의가 정확히 하나 있고, 자동 적재를 끈 목록에 없다.
    assert schedules.count(f'schedule_name="{_EXPECTED_SAFE_SCHEDULE}"') == 1
    disabled = _section(
        schedules,
        "DISABLED_FEATURE_LOAD_SCHEDULES: Final[frozenset[str]] = frozenset(",
        "\n)\n",
    )
    assert _EXPECTED_SAFE_SCHEDULE not in disabled
    # 그 schedule의 fetcher는 번들 정적 데이터만 yield한다(network 호출 없음).
    fetcher = _section(
        fetchers,
        "async def fetch_krairport_airports(",
        "\nasync def ",
    )
    assert "client.airports(active=True)" in fetcher
    assert "httpx" not in fetcher


def test_c7_lane_has_no_direct_dagster_client() -> None:
    """남은 C7 spec은 Dagster GraphQL에 직접 POST하지 않는다 — 자격증명도 받지 않는다.

    KMA queue sensor barrier와 run identity 대조가 퇴역하며 그 client(+ Basic Auth bind)는
    죽은 배관이 됐다. 다시 들이면 러너 env·mount·검증을 함께 되살려야 한다.
    """

    script = _read(RUNNER)
    for path in sorted(LIVE_DIR.glob("*.ts")):
        source = _read(path)
        assert "E2E_DAGSTER_BASIC_AUTH_FILE" not in source, path.name
        assert "dagsterGraphqlEndpoint()" not in source, path.name
    assert "E2E_DAGSTER_BASIC_AUTH_FILE" not in script
    assert "sensorOrError" not in script
    assert not (LIVE_DIR / "_dagster-basic-auth.ts").exists()

"""C7 prod live runner의 fail-closed 정적 계약 회귀 테스트."""

import ast
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
#: 기준 5(queue sensor → worker run)는 같은 날 upstream 0 dataset으로 되살렸다
#: (`ops-c7-update-request-write`).
_EXPECTED_C7_SPECS = (
    "e2e/live/ops-c7-read-auth.live.spec.ts",
    "e2e/live/ops-c7-schedule-write.live.spec.ts",
    "e2e/live/ops-c7-update-request-write.live.spec.ts",
)
_UPDATE_REQUEST_SPEC = "ops-c7-update-request-write.live.spec.ts"
#: schedule-write가 실제로 조작하는 schedule. 실수로 tick이 나가도 **외부 provider** 호출이
#: 0이어야 한다 — 공항 fetcher는 kor-travel-transport의 공항 export 하나만 읽고, transport는
#: 그것을 krairport 번들 정적 목록에서 낸다(ADR-106, transport ADR-013).
_EXPECTED_SAFE_SCHEDULE = "feature_place_transport_airports_monthly_schedule"
#: update-request spec이 실제로 request를 만드는 operation. 이것도 upstream 호출이 0이어야
#: 한다 — 이름이 아니라 operation → fetcher 배선과 fetcher 본문의 효과로 본다.
_EXPECTED_SAFE_UPDATE_OPERATION = "feature_place_transport_airports_job"


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
    "E2E_C7_UPDATE_REQUEST_WRITE": "1",
    "E2E_C7_UPDATE_REQUEST_OPERATION": _EXPECTED_SAFE_UPDATE_OPERATION,
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
            "validate_dagster_basic_auth_file",
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
    "name",
    [
        "E2E_C7_EXPECTED_GIT_COMMIT",
        "E2E_C7_PLAYWRIGHT_IMAGE",
        "E2E_C7_UI_SERVICE",
        "E2E_C7_UPDATE_REQUEST_OPERATION",
    ],
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
        "feature_place_transport_airports_monthly_schedule_typo",
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
    # 그 schedule이 돌리는 job의 fetcher는 upstream 호출이 0이다 — 이름이 아니라
    # schedule → job → operation 배선을 따라가 fetcher 본문의 효과로 본다.
    job_name = _schedule_job_name(schedules, _EXPECTED_SAFE_SCHEDULE)
    fetcher_name = _operation_fetcher_name(
        _read(DAGSTER_SRC / "feature_update_runner.py"), job_name
    )
    assert _zero_upstream_violations(fetchers, fetcher_name) == []


# -- 기준 5: exact-scope request → queue sensor → worker run (upstream 0) -----------


def _schedule_job_name(schedules_source: str, schedule_name: str) -> str:
    """``schedules.py``에서 그 schedule이 돌리는 job 이름을 AST로 읽는다."""

    found = []
    for node in ast.walk(ast.parse(schedules_source)):
        if not isinstance(node, ast.Call):
            continue
        keywords = {item.arg: item.value for item in node.keywords if item.arg}
        name = keywords.get("schedule_name")
        job = keywords.get("job_name")
        if (
            isinstance(name, ast.Constant)
            and name.value == schedule_name
            and isinstance(job, ast.Constant)
            and isinstance(job.value, str)
        ):
            found.append(job.value)
    assert len(found) == 1, f"schedule→job 배선이 정확히 하나가 아니다: {found}"
    return found[0]


def _operation_resource(runner_source: str, operation_key: str) -> tuple[str, str]:
    """``feature_update_runner.py``의 operation 배선에서 (resource key, fetcher 이름)을 읽는다.

    ``_operation_specs(<op>, ..., resources=_records("<key>", <fetcher>))`` 꼴만 받는다. 다른
    resource factory(scope별 분기, budget 등)로 배선되면 fetcher 하나로 효과를 말할 수 없으니
    실패한다(fail-closed).
    """

    found: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(runner_source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_operation_specs"
        ):
            continue
        keys = [arg.value for arg in node.args if isinstance(arg, ast.Constant)]
        if operation_key not in keys:
            continue
        resources = next(
            (item.value for item in node.keywords if item.arg == "resources"), None
        )
        if not (
            isinstance(resources, ast.Call)
            and isinstance(resources.func, ast.Name)
            and resources.func.id == "_records"
            and len(resources.args) == 2
            and isinstance(resources.args[0], ast.Constant)
            and isinstance(resources.args[0].value, str)
            and isinstance(resources.args[1], ast.Name)
        ):
            raise AssertionError("operation이 단일 `_records(<key>, <fetcher>)`로 배선되지 않았다")
        found.append((resources.args[0].value, resources.args[1].id))
    assert len(found) == 1, f"operation 배선이 정확히 하나가 아니다: {found}"
    return found[0]


def _operation_fetcher_name(runner_source: str, operation_key: str) -> str:
    return _operation_resource(runner_source, operation_key)[1]


#: 외부 provider에 닿지 않는 호출만. 여기 없는 호출은 위반이다(헬퍼를 거친 우회도 막는다).
#: transport 헬퍼는 같은 플랫폼 내부 서비스로 가는 경로다 — 그중 요청을 보내는
#: ``_transport_get``은 아래에서 **공항 export 경로로만** 허용한다(ADR-106).
#: ``_transport_run_budget``은 run 공유 재시도 장부를 꺼낼 뿐이고, ``_transport_json``은 이미 받은
#: 응답 본문을 JSON으로 읽을 뿐이다 — 둘 다 요청을 보내지 않는다(2026-10-04).
_ZERO_UPSTREAM_NAME_CALLS = frozenset(
    {
        "cast",
        "dict",
        "_transport_connection",
        "_transport_get",
        "_transport_json",
        "_transport_run_budget",
        "parse_airports",
    }
)
#: ``RetryBudget``은 재시도 횟수 장부를 만들 뿐 요청을 보내지 않는다(요청은 ``_transport_get``).
_ZERO_UPSTREAM_ATTRIBUTE_CALLS = frozenset({"AsyncClient", "json", "aclose", "RetryBudget"})
#: ``_transport_get``이 부를 수 있는 유일한 경로 상수.
_ZERO_UPSTREAM_TRANSPORT_PATH = "EXPORT_PATH_AIRPORTS"


def _is_transport_get(call: ast.AST) -> bool:
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id == "_transport_get"
    )


def _is_transport_client(context: ast.withitem) -> bool:
    expr = context.context_expr
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Attribute)
        and expr.func.attr == "AsyncClient"
        and isinstance(expr.func.value, ast.Name)
        and expr.func.value.id == "httpx"
    )


def _zero_upstream_violations(fetchers_source: str, fetcher_name: str) -> list[str]:
    """fetcher 본문에서 upstream에 닿을 수 있는 자리를 모은다(빈 목록 = upstream 0).

    이름이 아니라 효과에 건다.

    - 요청을 세는 자리(``note_upstream_request``)를 직접 부르면 다른 요청이 있다는 뜻이다.
    - ``await``는 세션 정리(``aclose``)와 공항 export로 가는 ``_transport_get``만 허용한다.
      ``_transport_get``의 경로 인자가 공항 export 상수가 아니면 위반이다.
    - ``async with``는 transport용 ``httpx.AsyncClient`` 하나만, ``async for``는 없어야 한다.
    - 호출은 위 허용 목록만 — 새 헬퍼를 거쳐 우회하면 여기서 빨개진다.
    """

    functions = [
        node
        for node in ast.walk(ast.parse(fetchers_source))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fetcher_name
    ]
    assert len(functions) == 1, f"fetcher 정의가 정확히 하나가 아니다: {fetcher_name}"
    violations: list[str] = []
    for node in ast.walk(functions[0]):
        if isinstance(node, ast.AsyncFor):
            violations.append(f"async iteration at line {node.lineno}")
        elif isinstance(node, ast.AsyncWith):
            if not all(_is_transport_client(item) for item in node.items):
                violations.append(
                    f"async context other than the transport client at line {node.lineno}"
                )
        elif isinstance(node, ast.Await):
            awaited = node.value
            if _is_transport_get(awaited):
                assert isinstance(awaited, ast.Call)
                path = awaited.args[1] if len(awaited.args) > 1 else None
                if not (isinstance(path, ast.Name) and path.id == _ZERO_UPSTREAM_TRANSPORT_PATH):
                    violations.append(
                        f"transport request off the airport export at line {node.lineno}"
                    )
            elif not (
                isinstance(awaited, ast.Call)
                and isinstance(awaited.func, ast.Attribute)
                and awaited.func.attr == "aclose"
            ):
                violations.append(f"await other than aclose/airport export at line {node.lineno}")
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id not in _ZERO_UPSTREAM_NAME_CALLS:
                    violations.append(f"call {func.id} at line {node.lineno}")
            elif isinstance(func, ast.Attribute):
                if func.attr not in _ZERO_UPSTREAM_ATTRIBUTE_CALLS:
                    violations.append(f"call .{func.attr} at line {node.lineno}")
            else:
                violations.append(f"dynamic call at line {node.lineno}")
    return violations


def _with_statement_appended(fetchers_source: str, fetcher_name: str, statement: str) -> str:
    """실제 fetcher 본문 끝에 문장 하나를 덧붙인 소스(검사기를 빨갛게 만들어 보는 용도)."""

    tree = ast.parse(fetchers_source)
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == fetcher_name
    )
    injected = ast.parse(f"async def _probe():\n    {statement}\n").body[0]
    assert isinstance(injected, ast.AsyncFunctionDef)
    function.body.extend(injected.body)
    return ast.unparse(ast.fix_missing_locations(tree))


def test_update_request_operation_is_one_zero_upstream_operation_everywhere() -> None:
    """request를 만드는 operation이 러너·spec에서 같고, 그 fetcher는 upstream 호출이 0이다."""

    script = _read(RUNNER)
    spec = _read(LIVE_DIR / _UPDATE_REQUEST_SPEC)
    runner_value = re.search(
        r'^readonly SAFE_UPDATE_OPERATION="([^"]+)"$', script, re.MULTILINE
    )
    spec_value = re.search(r'const SAFE_UPDATE_OPERATION = "([^"]+)" as const;', spec)
    assert runner_value is not None
    assert spec_value is not None
    assert {runner_value.group(1), spec_value.group(1)} == {
        _EXPECTED_SAFE_UPDATE_OPERATION
    }

    resource_key, fetcher_name = _operation_resource(
        _read(DAGSTER_SRC / "feature_update_runner.py"),
        _EXPECTED_SAFE_UPDATE_OPERATION,
    )
    assert _zero_upstream_violations(
        _read(DAGSTER_SRC / "provider_fetchers.py"), fetcher_name
    ) == []

    # spec이 grid에서 고르는 provider·dataset이 그 resource의 provider·dataset과 같다.
    declared = []
    for node in ast.walk(ast.parse(_read(DAGSTER_SRC / "resources.py"))):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ProviderRecordResourceSpec"
        ):
            continue
        keywords = {
            item.arg: item.value.value
            for item in node.keywords
            if item.arg and isinstance(item.value, ast.Constant)
        }
        if keywords.get("resource_key") == resource_key:
            declared.append((keywords.get("provider_package"), keywords.get("dataset_key")))
    assert len(declared) == 1
    provider, dataset_key = declared[0]
    assert f'const SAFE_PROVIDER = "{provider}" as const;' in spec
    assert f'const SAFE_DATASET_KEY = "{dataset_key}" as const;' in spec


@pytest.mark.parametrize(
    "statement",
    [
        "await client.departures()",
        "note_upstream_request()",
        "async for page in client.iter_pages(client.departures):\n        pass",
        "_fetch_more(client)",
        "await _transport_get(client, EXPORT_PATH_FUEL_STATIONS, {}, budget=budget)",
        "async with httpx_mock.AsyncClient() as other:\n        pass",
    ],
)
def test_zero_upstream_check_turns_red_on_an_upstream_call(statement: str) -> None:
    """검사기가 항진명제가 아님을 실제 fetcher에 upstream 호출을 하나 심어 보인다."""

    _, fetcher_name = _operation_resource(
        _read(DAGSTER_SRC / "feature_update_runner.py"),
        _EXPECTED_SAFE_UPDATE_OPERATION,
    )
    mutated = _with_statement_appended(
        _read(DAGSTER_SRC / "provider_fetchers.py"), fetcher_name, statement
    )
    assert _zero_upstream_violations(mutated, fetcher_name) != []


def test_operation_resolution_rejects_an_unwired_operation() -> None:
    with pytest.raises(AssertionError):
        _operation_resource(
            _read(DAGSTER_SRC / "feature_update_runner.py"),
            _EXPECTED_SAFE_UPDATE_OPERATION + "_typo",
        )


@pytest.mark.parametrize(
    "operation",
    [
        # upstream이 있는 operation — allowlist 밖이다.
        "feature_place_khoa_beaches_job",
        _EXPECTED_SAFE_UPDATE_OPERATION + "_typo",
    ],
)
def test_runner_env_contract_rejects_a_non_allowlisted_update_operation(
    operation: str,
) -> None:
    rejected = _run_c7_environment_validation(
        {**_C7_ENV, "E2E_C7_UPDATE_REQUEST_OPERATION": operation}
    )
    assert rejected.returncode == 1
    assert "not the allowlisted zero-upstream operation" in rejected.stderr
    assert "ENV_OK" not in rejected.stdout


def test_runner_env_contract_requires_the_update_request_write_opt_in() -> None:
    env = {k: v for k, v in _C7_ENV.items() if k != "E2E_C7_UPDATE_REQUEST_WRITE"}
    rejected = _run_c7_environment_validation(env)
    assert rejected.returncode == 1
    assert "explicit opt-in is required: E2E_C7_UPDATE_REQUEST_WRITE=1" in rejected.stderr


def test_update_request_journal_is_shared_between_runner_and_spec() -> None:
    """`requests.json`: 러너가 placeholder를 깔고, spec이 같은 키 집합으로 쓰고, 러너가 검증한다."""

    script = _read(RUNNER)
    spec = _read(LIVE_DIR / _UPDATE_REQUEST_SPEC)

    assert 'REQUEST_STATE_FILE="$RUNTIME_DIR/journals/requests.json"' in script
    assert (
        '"$REQUEST_STATE_FILE" \\\n  \'{"phase":"orchestrator_pending","version":1}\''
        in script
    )
    assert 'export E2E_C7_REQUEST_STATE_FILE="$REQUEST_STATE_FILE"' in script
    assert 'state_is_exact_restored requests "$REQUEST_STATE_FILE"' in script
    assert "process.env.E2E_C7_REQUEST_STATE_FILE" in spec
    assert (
        'const ORCHESTRATOR_PLACEHOLDER = { phase: "orchestrator_pending", version: 1 };'
        in spec
    )
    # 키 집합: spec의 TS type과 러너의 exact_dict가 같아야 한다(한쪽만 바뀌면 빨갛다).
    type_block = _section(spec, "type RequestJournal = {", "\n};")
    spec_keys = set(re.findall(r"^  ([a-z_]+): ", type_block, re.MULTILINE))
    requests_branch = _section(script, 'elif kind == "requests":', "\nelse:")
    runner_keys = set(
        re.findall(
            r'^            "([a-z_]+)",$',
            _section(requests_branch, "if not exact_dict(", "or state.get"),
            re.MULTILINE,
        )
    )
    assert spec_keys == runner_keys
    assert len(spec_keys) == 14
    assert 'state.get("terminal_status") == "done"' in requests_branch
    assert 'state.get("dagster_run_status") == "SUCCESS"' in requests_branch
    assert 'state.get("sensor_name") == "feature_update_request_queue_sensor"' in (
        requests_branch
    )
    # journal은 다른 C7 journal과 같은 fsync·atomic rename 순서로 쓴다.
    _assert_in_order(
        _section(spec, "async function writeRequestJournal(", "\n}\n"),
        "await writeFile(",
        "await temporaryHandle.sync()",
        "await rename(",
        "await stateHandle.sync()",
        "await directoryHandle.sync()",
    )
    # 성공 증명 전에는 `restored`를 쓰지 않는다 — 실패 정리는 `restore_failed`다.
    _assert_in_order(
        spec,
        'expect(run.status).toBe("SUCCESS")',
        "expect(after.active_execution).toBeNull()",
        'journal.phase = "restored"',
    )
    settle = _section(spec, "async function settleOwnedRequestAfterFailure(", "\n}\n")
    assert 'journal.phase = "restore_failed"' in settle
    assert '"restored"' not in settle


def test_update_request_spec_observes_the_queue_sensor_run_read_only() -> None:
    """barrier는 run tag로 본다 — sensor·Map location·request·generation. Dagster는 읽기만 한다."""

    dagster = _read(LIVE_DIR / "_ops-c7-dagster.ts")
    spec = _read(LIVE_DIR / _UPDATE_REQUEST_SPEC)

    for source in (dagster, spec):
        assert re.search(r"\bmutation\s+\w+", source) is None
    assert "if (/^\\s*mutation\\b/.test(query))" in dagster
    for marker in (
        "run.jobName !== QUEUE_WORKER_JOB",
        "tags.get(DAGSTER_CODE_LOCATION_TAG) !== MAP_DAGSTER_LOCATION_NAME",
        "tags.get(FEATURE_UPDATE_REQUEST_ID_TAG) !== identity.requestId",
        "tags.get(FEATURE_UPDATE_REQUEST_GENERATION_TAG) !== String(identity.generation)",
        "sensorName !== QUEUE_SENSOR_NAME",
    ):
        assert marker in dagster
    # 이름은 Dagster 정의와 같아야 한다.
    sensors = _read(DAGSTER_SRC / "sensors.py")
    assert '@job(name="feature_update_request_worker")' in sensors
    assert 'name="feature_update_request_queue_sensor",' in sensors
    assert 'QUEUE_WORKER_JOB = "feature_update_request_worker" as const;' in dagster
    assert 'QUEUE_SENSOR_NAME = "feature_update_request_queue_sensor" as const;' in dagster
    location = re.search(r"location_name: (\S+)", _read(ROOT / "docker" / "workspace.yaml"))
    assert location is not None
    assert f'MAP_DAGSTER_LOCATION_NAME = "{location.group(1)}" as const;' in dagster
    # 생성 → dispatch barrier → API terminal → Dagster terminal 순서.
    _assert_in_order(
        spec,
        "await assertQueueWorkerOperational();",
        "before.active_execution !== null",
        "await createOwnedRequest(page, body, journal)",
        "expect(record.dagster_run_id).toBeNull()",
        "await waitForDispatch(page, record.request_id)",
        "await waitForTerminal(page, record.request_id, TERMINAL_TIMEOUT_MS)",
        "await waitForDagsterTerminal(page, identity)",
    )
    # 409(남의 활성 request)는 건드리지 않고 멈춘다.
    assert "result.status === 409" in spec
    assert '"create_rejected"' in spec


def _credential_file(tmp_path: Path, content: bytes, mode: int = 0o600) -> Path:
    path = tmp_path / "dagster-basic-auth"
    path.write_bytes(content)
    path.chmod(mode)
    return path


def test_runner_env_contract_accepts_a_private_basic_auth_file(tmp_path: Path) -> None:
    path = _credential_file(tmp_path, b"c7-runner:s3cr3t:with-colon\n")
    accepted = _run_c7_environment_validation(
        {**_C7_ENV, "E2E_DAGSTER_BASIC_AUTH_FILE": str(path)}
    )
    assert accepted.returncode == 0, accepted.stderr
    assert "s3cr3t" not in accepted.stdout + accepted.stderr


@pytest.mark.parametrize(
    ("content", "mode", "link"),
    [
        (b"c7-runner:s3cr3t\n", 0o640, False),
        (b"c7-runner:s3cr3t\n", 0o604, False),
        (b"c7-runner:s3cr3t\n", 0o600, True),
        (b"no-password-s3cr3t\n", 0o600, False),
        (b"c7 runner:s3cr3t\n", 0o600, False),
        (b"c7-runner:s3cr3t\nsecond:line\n", 0o600, False),
    ],
)
def test_runner_env_contract_rejects_an_unsafe_basic_auth_file(
    tmp_path: Path, content: bytes, mode: int, link: bool
) -> None:
    path = _credential_file(tmp_path, content, mode)
    if link:
        alias = tmp_path / "alias"
        alias.symlink_to(path)
        path = alias
    rejected = _run_c7_environment_validation(
        {**_C7_ENV, "E2E_DAGSTER_BASIC_AUTH_FILE": str(path)}
    )
    assert rejected.returncode == 1
    assert "Dagster Basic Auth file is unsafe" in rejected.stderr
    assert "s3cr3t" not in rejected.stdout + rejected.stderr
    assert "ENV_OK" not in rejected.stdout


def test_runner_env_contract_rejects_a_relative_basic_auth_path() -> None:
    rejected = _run_c7_environment_validation(
        {**_C7_ENV, "E2E_DAGSTER_BASIC_AUTH_FILE": "dagster-basic-auth"}
    )
    assert rejected.returncode == 1
    assert "must be absolute" in rejected.stderr


def test_basic_auth_reaches_the_dagster_post_only_by_read_only_mount() -> None:
    """C7이 Dagster에 POST하는 자리는 하나이고, 자격증명은 read-only bind로만 들어간다.

    `docker inspect`의 Env에는 컨테이너 안 경로만 있다.
    """

    script = _read(RUNNER)
    dagster = _read(LIVE_DIR / "_ops-c7-dagster.ts")
    assert "readFileSync(credentialPath" in dagster
    assert "process.env.E2E_DAGSTER_BASIC_AUTH_FILE" in dagster
    posts = sum(
        len(re.findall(r"await fetch\(dagsterGraphqlEndpoint\(\)", _read(path)))
        for path in sorted(LIVE_DIR.glob("*.ts"))
    )
    assert posts == 1
    assert dagster.count("...dagsterAuthorizationHeaders(),") == 1
    assert (
        '--mount "type=bind,src=$E2E_DAGSTER_BASIC_AUTH_FILE,'
        'dst=$DAGSTER_BASIC_AUTH_CONTAINER_PATH,readonly"' in script
    )
    assert '--env "E2E_DAGSTER_BASIC_AUTH_FILE=$DAGSTER_BASIC_AUTH_CONTAINER_PATH"' in script
    # 이름만 준 `--env NAME`은 호스트 값(호스트 경로)을 그대로 복사한다 — 쓰지 않는다.
    assert re.search(r"--env E2E_DAGSTER_BASIC_AUTH_FILE\s", script) is None
    assert re.search(r"\bE2E_DAGSTER_BASIC_AUTH_FILE E2E", script) is None



"""C7 prod live runner의 fail-closed 정적 계약 회귀 테스트."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "scripts" / "run-c7-prod-live-e2e.sh"
LIVE_DIR = (
    ROOT / "packages" / "kor-travel-map-admin" / "frontend" / "e2e" / "live"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    return source[start_index : source.index(end, start_index)]


def _assert_in_order(source: str, *markers: str) -> None:
    cursor = 0
    for marker in markers:
        cursor = source.index(marker, cursor) + len(marker)


def test_final_runner_anchors_host_login_and_causal_poi_spec() -> None:
    script = _read(RUNNER)

    host_python_invocations = (
        'python3 - "$target"',
        'python3 - "$STATE_ROOT"',
        'python3 - "$LOCK_FILE"',
        'python3 - "$HOST_ATTESTATION_FILE"',
        "| python3 -c '",
        'python3 - "$kind" "$state_file"',
    )
    for invocation in host_python_invocations:
        assert script.count(invocation) == 1
    assert [
        line.strip() for line in script.splitlines() if line.lstrip().startswith("python ")
    ] == ["python -c \\"]
    assert "| python " not in script
    _assert_in_order(
        script,
        "require_command python3\n",
        "initialize_state_paths\n",
        "start_orchestrator_lock_guard\n",
        '[[ ! -e "$BLOCKED_FILE" ]]',
        "create_blocked_sentinel\n",
    )
    assert '/etc/kor-travel-map/c7-prod-live-e2e-attestation.json' in script
    assert 'machine_id_sha256' in script
    assert 'hostname_sha256' in script
    assert 'KOR_TRAVEL_MAP_UI_ADMIN_PASSWORD_HASH=' in script
    assert 'response.status !== 200' in script
    assert 'response.headers.get("set-cookie")' in script
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
    assert "assertOnlyKmaProviderObjects(matched" in helper
    assert "FORBIDDEN_PROVIDER_PATTERN" in helper
    assert "providerDatasets.length !== 1" in helper
    assert "pair.provider !== KMA_PROVIDER" in helper
    assert "pair.dataset_key !== KMA_DATASET_KEY" in helper
    assert "pair.feature_count < 0" in helper
    assert "matchedScope.effective_sync_scope !== expectedEffectiveSyncScope" in helper
    for spec in (active, empty, cap):
        assert "assertExactKmaPreviewResponse(" in spec
        assert "assertKmaOnlyTerminalProviderScopes(" in spec
    assert "const LOWERCASE_SHA256_PATTERN = /^[0-9a-f]{64}$/" in active
    assert "isCanonicalKmaBaseDatetime" in active
    assert "KMA_BASE_DATETIME_PATTERN" in active


def test_route_fetch_handlers_have_settlement_barriers() -> None:
    live_browser = _read(LIVE_DIR / "_ops-live-browser.ts")
    read_auth = _read(LIVE_DIR / "ops-c7-read-auth.live.spec.ts")
    schedule = _read(LIVE_DIR / "ops-c7-schedule-write.live.spec.ts")

    cursor = 0
    for _ in range(2):
        fetch = live_browser.index("await route.fetch()", cursor)
        settled = live_browser.index("await waitForSettlement()", fetch)
        unroute = live_browser.index("await page.unroute", settled)
        assert fetch < settled < unroute
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
    invocation = script[script.index("initialize_state_paths\nreadonly") :]
    _assert_in_order(
        invocation,
        "initialize_state_paths",
        "start_orchestrator_lock_guard",
        '[[ ! -e "$BLOCKED_FILE" ]]',
        "create_blocked_sentinel",
        "has_residual_state",
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


def test_history_cursor_pages_match_exact_ordered_dom_identity() -> None:
    active = _read(LIVE_DIR / "ops-c7-kma-active-write.live.spec.ts")
    data_table = _read(
        ROOT
        / "packages"
        / "kor-travel-map-admin"
        / "frontend"
        / "src"
        / "components"
        / "ui"
        / "data-table.tsx"
    )
    execution_timeline = _read(
        ROOT
        / "packages"
        / "kor-travel-map-admin"
        / "frontend"
        / "src"
        / "app"
        / "ops"
        / "pipeline"
        / "execution-timeline.tsx"
    )
    events_panel = _read(
        ROOT
        / "packages"
        / "kor-travel-map-admin"
        / "frontend"
        / "src"
        / "app"
        / "ops"
        / "pipeline"
        / "events-panel.tsx"
    )
    continuation = _section(
        active,
        "async function assertHistoryContinuationFromUi(",
        "function isExactHistoryPageResponse(",
    )

    assert "data-row-identity={rowIdentity?.(row.original)}" in data_table
    assert (
        "JSON.stringify([row.created_at, row.id, row.kind])"
        in execution_timeline
    )
    assert "JSON.stringify([row.occurred_at, row.event_id])" in events_panel
    assert continuation.count("orderedHistoryIdentityTuples(") == 4
    assert continuation.count("assertDisjointOrderedContinuation(") == 2
    assert continuation.count(".map(identityKey)") == 4
    assert ".some(" not in continuation
    assert "innerText" not in continuation
    assert "new Set(keys).size !== keys.length" in active
    assert "compareOrderedIdentity(firstLast, secondFirst) !== -1" in active
    assert 'locator("tbody tr[data-row-identity]")' in active


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

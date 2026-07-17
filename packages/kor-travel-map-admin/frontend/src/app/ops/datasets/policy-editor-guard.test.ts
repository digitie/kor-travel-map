import { describe, expect, it, vi } from "vitest";

import type { ProviderRefreshPolicyRecord } from "@/api/datasets";

import {
  applyPolicyMutationConflict,
  applyPolicyMutationSuccess,
  initialPolicyEditorState,
  isPolicySaveBlocked,
  observePolicyProp,
  type PolicyEditorState,
  type PolicyRevisionConflict,
  type PolicySaveGuard,
  submitPolicyIfAllowed,
} from "./policy-editor-guard";

function makePolicy(
  revision: string,
  overrides: Partial<ProviderRefreshPolicyRecord> = {},
): ProviderRefreshPolicyRecord {
  return {
    burst_size: null,
    config_source: "db",
    created_at: "2026-07-17T00:00:00.000Z",
    dataset_key: "forecast",
    enabled: true,
    max_concurrent: 1,
    max_requests_per_day: null,
    max_requests_per_hour: null,
    max_requests_per_minute: 30,
    min_interval_seconds: null,
    optimal_interval_seconds: null,
    provider: "kma",
    rate_limit_source: {},
    revision,
    source_kind: "openapi",
    stale_after_minutes: 60,
    system_interval_seconds: 3600,
    targeted_policy: "follow_system",
    updated_at: "2026-07-17T00:00:01.000Z",
    ...overrides,
  };
}

function dirtyStateBefore(latestRevision: string): PolicyEditorState {
  const initial = initialPolicyEditorState(makePolicy("1"));
  const dirty: PolicyEditorState = {
    ...initial,
    dirty: true,
    draft: { ...initial.draft, targeted_policy: "allow_targeted" },
  };
  return observePolicyProp(
    dirty,
    makePolicy(latestRevision, { targeted_policy: "disabled" }),
  );
}

const OPEN: PolicySaveGuard = {
  acknowledgedPropRevision: "2",
  hasDeferredServerPolicy: false,
  hasRevisionConflict: false,
  incomingPropRevision: "2",
};
const BLOCKED_CASES: readonly [string, Partial<PolicySaveGuard>][] = [
  ["incoming prop 미반영", { incomingPropRevision: "3" }],
  ["deferred server policy", { hasDeferredServerPolicy: true }],
  ["revision conflict", { hasRevisionConflict: true }],
];

describe("policy editor save guard", () => {
  it.each(BLOCKED_CASES)(
    "%s이면 render와 submit을 함께 차단한다",
    (_label, override) => {
      const guard = { ...OPEN, ...override };
      const submit = vi.fn();

      expect(isPolicySaveBlocked(guard)).toBe(true);
      expect(submitPolicyIfAllowed(guard, submit)).toBe(false);
      expect(submit).not.toHaveBeenCalled();
    },
  );

  it("incoming prop을 acknowledge한 own mutation refetch는 submit을 허용한다", () => {
    const submit = vi.fn();

    expect(isPolicySaveBlocked(OPEN)).toBe(false);
    expect(submitPolicyIfAllowed(OPEN, submit)).toBe(true);
    expect(submit).toHaveBeenCalledTimes(1);
  });
});

describe("policy editor server state transition", () => {
  it("dirty prop mismatch는 draft/base를 보존하고 ack/latest/deferred를 원자 갱신한다", () => {
    const initial = initialPolicyEditorState(makePolicy("1"));
    const dirty: PolicyEditorState = {
      ...initial,
      dirty: true,
      draft: { ...initial.draft, targeted_policy: "allow_targeted" },
    };
    const latest = makePolicy("2", { targeted_policy: "disabled" });

    const observed = observePolicyProp(dirty, latest);

    expect(observed).toMatchObject({
      acknowledgedPropRevision: "2",
      dirty: true,
      draftBaseRevision: "1",
      hasDeferredServerPolicy: true,
      latestObservedPolicy: latest,
      latestObservedRevision: "2",
      serverSnapshotEpoch: 1,
    });
    expect(observed.draft).toBe(dirty.draft);
    expect(observed.draftBasePolicy).toBe(dirty.draftBasePolicy);
  });

  it("clean prop mismatch는 최신 서버 정책을 draft/base/latest에 함께 적용한다", () => {
    const initial = initialPolicyEditorState(makePolicy("1"));
    const latest = makePolicy("2", { targeted_policy: "disabled" });

    const observed = observePolicyProp(initial, latest);

    expect(observed).toMatchObject({
      acknowledgedPropRevision: "2",
      dirty: false,
      draft: { targeted_policy: "disabled" },
      draftBasePolicy: latest,
      draftBaseRevision: "2",
      hasDeferredServerPolicy: false,
      latestObservedPolicy: latest,
      latestObservedRevision: "2",
      serverSnapshotEpoch: 1,
    });
  });

  it("own-refetch는 ack만 따라잡고 다음 mutation은 적용 뒤 증가한 epoch를 쓴다", () => {
    const initial = initialPolicyEditorState(makePolicy("1"));
    const saved = makePolicy("2", { targeted_policy: "disabled" });
    const afterMutation = applyPolicyMutationSuccess(
      initial,
      saved,
      initial.serverSnapshotEpoch,
    );
    const caughtUp = observePolicyProp(afterMutation, saved);

    expect(caughtUp).toEqual({
      ...afterMutation,
      acknowledgedPropRevision: "2",
    });
    expect(caughtUp.serverSnapshotEpoch).toBe(1);

    const nextSaved = makePolicy("3");
    expect(
      applyPolicyMutationSuccess(
        caughtUp,
        nextSaved,
        caughtUp.serverSnapshotEpoch,
      ),
    ).toMatchObject({
      latestObservedRevision: "3",
      serverSnapshotEpoch: 2,
    });
  });

  it("null→numeric과 numeric→null prop snapshot은 각각 epoch를 올려 적용한다", () => {
    const absent = initialPolicyEditorState(null);
    const createdPolicy = makePolicy("1");
    const created = observePolicyProp(absent, createdPolicy);

    expect(created).toMatchObject({
      acknowledgedPropRevision: "1",
      draftBaseRevision: "1",
      latestObservedPolicy: createdPolicy,
      latestObservedRevision: "1",
      serverSnapshotEpoch: 1,
    });

    const deleted = observePolicyProp(created, null);
    expect(deleted).toMatchObject({
      acknowledgedPropRevision: null,
      draftBasePolicy: null,
      draftBaseRevision: null,
      latestObservedPolicy: null,
      latestObservedRevision: null,
      serverSnapshotEpoch: 2,
    });
  });

  it("삭제 후 rev1 재생성은 새 generation이며 old rev3 success/409를 모두 무시한다", () => {
    const originalPolicy = makePolicy("3");
    const original = initialPolicyEditorState(originalPolicy);
    const startEpoch = original.serverSnapshotEpoch;
    const deleted = observePolicyProp(original, null);
    const recreatedPolicy = makePolicy("1", { source_kind: "manual" });
    const recreated = observePolicyProp(deleted, recreatedPolicy);
    const oldConflict: PolicyRevisionConflict = {
      currentPolicy: originalPolicy,
      currentRevision: "3",
      terminal: false,
    };

    expect(recreated).toMatchObject({
      draft: { source_kind: "manual" },
      latestObservedRevision: "1",
      serverSnapshotEpoch: 2,
    });
    expect(
      applyPolicyMutationSuccess(recreated, originalPolicy, startEpoch),
    ).toBe(recreated);
    expect(
      applyPolicyMutationConflict(recreated, oldConflict, startEpoch),
    ).toBe(recreated);
  });

  it("삭제 generation에서 시작한 mutation은 재생성 뒤 rev1/null 응답도 무시한다", () => {
    const deleted = observePolicyProp(
      initialPolicyEditorState(makePolicy("3")),
      null,
    );
    const startEpoch = deleted.serverSnapshotEpoch;
    const recreated = observePolicyProp(deleted, makePolicy("1"));
    const absentConflict: PolicyRevisionConflict = {
      currentPolicy: null,
      currentRevision: null,
      terminal: false,
    };

    expect(
      applyPolicyMutationSuccess(recreated, makePolicy("1"), startEpoch),
    ).toBe(recreated);
    expect(
      applyPolicyMutationConflict(recreated, absentConflict, startEpoch),
    ).toBe(recreated);
  });

  it("prop epoch가 바뀐 뒤 늦은 rev2 success/409는 rev3 편집 상태를 보존한다", () => {
    const initial = initialPolicyEditorState(makePolicy("1"));
    const startEpoch = initial.serverSnapshotEpoch;
    const latestState = observePolicyProp(
      {
        ...initial,
        dirty: true,
        draft: { ...initial.draft, targeted_policy: "allow_targeted" },
      },
      makePolicy("3", { targeted_policy: "disabled" }),
    );
    const staleConflict: PolicyRevisionConflict = {
      currentPolicy: makePolicy("2"),
      currentRevision: "2",
      terminal: false,
    };

    expect(
      applyPolicyMutationSuccess(latestState, makePolicy("2"), startEpoch),
    ).toBe(latestState);
    expect(
      applyPolicyMutationConflict(latestState, staleConflict, startEpoch),
    ).toBe(latestState);
  });

  it.each([
    ["작은 revision", "2", "3"],
    ["자릿수 9→10", "9", "10"],
    ["자릿수 99→100", "99", "100"],
    ["2^53 초과 revision", "9007199254740993", "9007199254740994"],
  ])(
    "같은 epoch의 낮은 success/409(%s)도 보조 revision guard가 막는다",
    (_label, staleRevision, latestRevision) => {
      const latestState = initialPolicyEditorState(makePolicy(latestRevision));
      const staleConflict: PolicyRevisionConflict = {
        currentPolicy: makePolicy(staleRevision),
        currentRevision: staleRevision,
        terminal: false,
      };

      expect(
        applyPolicyMutationSuccess(
          latestState,
          makePolicy(staleRevision),
          latestState.serverSnapshotEpoch,
        ),
      ).toBe(latestState);
      expect(
        applyPolicyMutationConflict(
          latestState,
          staleConflict,
          latestState.serverSnapshotEpoch,
        ),
      ).toBe(latestState);
    },
  );

  it.each([
    ["같은 revision", "3"],
    ["더 새 revision", "4"],
  ])("success의 %s snapshot은 정상 적용한다", (_label, revision) => {
    const latestState = dirtyStateBefore("3");
    const saved = makePolicy(revision, { targeted_policy: "disabled" });

    expect(
      applyPolicyMutationSuccess(
        latestState,
        saved,
        latestState.serverSnapshotEpoch,
      ),
    ).toMatchObject({
      dirty: false,
      draft: { targeted_policy: "disabled" },
      draftBasePolicy: saved,
      draftBaseRevision: revision,
      hasDeferredServerPolicy: false,
      lastSavedAt: saved.updated_at,
      latestObservedPolicy: saved,
      latestObservedRevision: revision,
      revisionConflict: null,
      serverSnapshotEpoch: latestState.serverSnapshotEpoch + 1,
    });
  });

  it.each([
    ["같은 revision", "3"],
    ["더 새 revision", "4"],
  ])("409의 %s snapshot은 정상 적용한다", (_label, revision) => {
    const latestState = dirtyStateBefore("3");
    const currentPolicy = makePolicy(revision, { source_kind: "manual" });
    const conflict: PolicyRevisionConflict = {
      currentPolicy,
      currentRevision: revision,
      terminal: false,
    };

    expect(
      applyPolicyMutationConflict(
        latestState,
        conflict,
        latestState.serverSnapshotEpoch,
      ),
    ).toMatchObject({
      draft: {
        source_kind: "manual",
        targeted_policy: "allow_targeted",
      },
      hasDeferredServerPolicy: true,
      latestObservedPolicy: currentPolicy,
      latestObservedRevision: revision,
      revisionConflict: conflict,
      serverSnapshotEpoch: latestState.serverSnapshotEpoch + 1,
    });
  });
});

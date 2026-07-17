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

function dirtyStateBefore(
  latestRevision: string,
): PolicyEditorState {
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
    });
  });

  it("이미 mutation 본문으로 적용한 revision의 prop refetch는 ack만 따라잡는다", () => {
    const initial = initialPolicyEditorState(makePolicy("1"));
    const saved = makePolicy("2", { targeted_policy: "disabled" });
    const afterMutation = applyPolicyMutationSuccess(initial, saved);

    expect(observePolicyProp(afterMutation, saved)).toEqual({
      ...afterMutation,
      acknowledgedPropRevision: "2",
    });
  });

  it.each([
    ["작은 revision", "2", "3"],
    ["2^53 초과 revision", "9007199254740993", "9007199254740994"],
  ])(
    "늦은 success(%s)는 더 최신 snapshot을 되돌리지 않는다",
    (_label, staleRevision, latestRevision) => {
      const latestState = dirtyStateBefore(latestRevision);

      expect(
        applyPolicyMutationSuccess(latestState, makePolicy(staleRevision)),
      ).toBe(latestState);
    },
  );

  it.each([
    ["작은 revision", "2", "3"],
    ["2^53 초과 revision", "9007199254740993", "9007199254740994"],
  ])(
    "늦은 409(%s)는 최신 draft/deferred/conflict를 보존한다",
    (_label, staleRevision, latestRevision) => {
      const latestState = dirtyStateBefore(latestRevision);
      const staleConflict: PolicyRevisionConflict = {
        currentPolicy: makePolicy(staleRevision),
        currentRevision: staleRevision,
        terminal: false,
      };

      expect(
        applyPolicyMutationConflict(latestState, staleConflict),
      ).toBe(latestState);
    },
  );

  it.each([
    ["같은 revision", "3"],
    ["더 새 revision", "4"],
  ])("success의 %s snapshot은 정상 적용한다", (_label, revision) => {
    const latestState = dirtyStateBefore("3");
    const saved = makePolicy(revision, { targeted_policy: "disabled" });

    expect(applyPolicyMutationSuccess(latestState, saved)).toMatchObject({
      dirty: false,
      draft: { targeted_policy: "disabled" },
      draftBasePolicy: saved,
      draftBaseRevision: revision,
      hasDeferredServerPolicy: false,
      lastSavedAt: saved.updated_at,
      latestObservedPolicy: saved,
      latestObservedRevision: revision,
      revisionConflict: null,
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

    expect(applyPolicyMutationConflict(latestState, conflict)).toMatchObject({
      draft: {
        source_kind: "manual",
        targeted_policy: "allow_targeted",
      },
      hasDeferredServerPolicy: true,
      latestObservedPolicy: currentPolicy,
      latestObservedRevision: revision,
      revisionConflict: conflict,
    });
  });
});

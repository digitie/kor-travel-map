import { describe, expect, it, vi } from "vitest";

import {
  isPolicySaveBlocked,
  type PolicySaveGuard,
  submitPolicyIfAllowed,
} from "./policy-editor-guard";

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

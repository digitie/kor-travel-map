import type {
  ProviderRefreshPolicyRecord,
  ProviderRefreshPolicyUpsertRequest,
} from "@/api/datasets";

export const POLICY_SOURCE_KINDS = [
  "openapi",
  "filedata",
  "manual",
  "system",
] as const;
export const POLICY_TARGETED_POLICIES = [
  "follow_system",
  "allow_targeted",
  "disabled",
] as const;

export type PolicyDraft = {
  source_kind: ProviderRefreshPolicyUpsertRequest["source_kind"] | "";
  targeted_policy: ProviderRefreshPolicyUpsertRequest["targeted_policy"];
  system_interval_seconds: string;
  optimal_interval_seconds: string;
  min_interval_seconds: string;
  max_requests_per_minute: string;
  max_requests_per_hour: string;
  max_requests_per_day: string;
  max_concurrent: string;
  burst_size: string;
  stale_after_minutes: string;
  enabled: boolean;
};

export type PolicyRevisionConflict = {
  currentPolicy: ProviderRefreshPolicyRecord | null;
  currentRevision: string | null;
  terminal: boolean;
};

export type PolicyEditorState = {
  acknowledgedPropRevision: string | null;
  dirty: boolean;
  draft: PolicyDraft;
  draftBasePolicy: ProviderRefreshPolicyRecord | null;
  draftBaseRevision: string | null;
  error: string | null;
  fieldErrors: Partial<Record<string, string>>;
  hasDeferredServerPolicy: boolean;
  lastSavedAt: string | null;
  latestObservedPolicy: ProviderRefreshPolicyRecord | null;
  latestObservedRevision: string | null;
  reconcileMessage: string | null;
  revisionConflict: PolicyRevisionConflict | null;
};

export type PolicySaveGuard = {
  acknowledgedPropRevision: string | null;
  hasDeferredServerPolicy: boolean;
  hasRevisionConflict: boolean;
  incomingPropRevision: string | null;
};

function numberText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/** 서버 정본 source_kind만 신뢰한다 — 없으면 명시 선택을 요구한다. */
function sourceKindValue(
  value: string | null | undefined,
): ProviderRefreshPolicyUpsertRequest["source_kind"] | "" {
  return POLICY_SOURCE_KINDS.includes(
    value as ProviderRefreshPolicyUpsertRequest["source_kind"],
  )
    ? (value as ProviderRefreshPolicyUpsertRequest["source_kind"])
    : "";
}

function targetedPolicyValue(
  value: string | null | undefined,
): ProviderRefreshPolicyUpsertRequest["targeted_policy"] {
  return POLICY_TARGETED_POLICIES.includes(
    value as ProviderRefreshPolicyUpsertRequest["targeted_policy"],
  )
    ? (value as ProviderRefreshPolicyUpsertRequest["targeted_policy"])
    : "follow_system";
}

// full PUT의 nullable interval/quota는 빈 입력으로 보존한다(#684).
export function policyToDraft(
  policy: ProviderRefreshPolicyRecord | null | undefined,
): PolicyDraft {
  return {
    source_kind: sourceKindValue(policy?.source_kind),
    targeted_policy: targetedPolicyValue(policy?.targeted_policy),
    system_interval_seconds: numberText(policy?.system_interval_seconds),
    optimal_interval_seconds: numberText(policy?.optimal_interval_seconds),
    min_interval_seconds: numberText(policy?.min_interval_seconds),
    max_requests_per_minute: numberText(policy?.max_requests_per_minute),
    max_requests_per_hour: numberText(policy?.max_requests_per_hour),
    max_requests_per_day: numberText(policy?.max_requests_per_day),
    max_concurrent: numberText(policy?.max_concurrent ?? 1),
    burst_size: numberText(policy?.burst_size),
    stale_after_minutes: numberText(policy?.stale_after_minutes),
    enabled: policy?.enabled ?? true,
  };
}

export function initialPolicyEditorState(
  policy: ProviderRefreshPolicyRecord | null | undefined,
): PolicyEditorState {
  const canonicalPolicy = policy ?? null;
  const revision = policy?.revision ?? null;
  return {
    acknowledgedPropRevision: revision,
    dirty: false,
    draft: policyToDraft(policy),
    draftBasePolicy: canonicalPolicy,
    draftBaseRevision: revision,
    error: null,
    fieldErrors: {},
    hasDeferredServerPolicy: false,
    lastSavedAt: null,
    latestObservedPolicy: canonicalPolicy,
    latestObservedRevision: revision,
    reconcileMessage: null,
    revisionConflict: null,
  };
}

export function applyServerPolicyState(
  state: PolicyEditorState,
  policy: ProviderRefreshPolicyRecord | null | undefined,
): PolicyEditorState {
  const canonicalPolicy = policy ?? null;
  const revision = policy?.revision ?? null;
  return {
    ...state,
    dirty: false,
    draft: policyToDraft(policy),
    draftBasePolicy: canonicalPolicy,
    draftBaseRevision: revision,
    error: null,
    fieldErrors: {},
    hasDeferredServerPolicy: false,
    latestObservedPolicy: canonicalPolicy,
    latestObservedRevision: revision,
    reconcileMessage: null,
    revisionConflict: null,
  };
}

/**
 * 새 prop revision을 render commit 전에 원자 반영한다. dirty draft는 보존하고,
 * mutation/409 본문에서 이미 본 revision의 refetch는 acknowledge만 한다.
 */
export function observePolicyProp(
  state: PolicyEditorState,
  policy: ProviderRefreshPolicyRecord | null | undefined,
): PolicyEditorState {
  const incomingRevision = policy?.revision ?? null;
  if (incomingRevision === state.acknowledgedPropRevision) {
    return state;
  }

  const acknowledgedState = {
    ...state,
    acknowledgedPropRevision: incomingRevision,
  };
  if (incomingRevision === state.latestObservedRevision) {
    return acknowledgedState;
  }
  if (!state.dirty) {
    return applyServerPolicyState(acknowledgedState, policy);
  }
  return {
    ...acknowledgedState,
    hasDeferredServerPolicy: true,
    latestObservedPolicy: policy ?? null,
    latestObservedRevision: incomingRevision,
  };
}

const POSITIVE_DECIMAL_REVISION = /^[1-9]\d*$/;

/** candidate가 current보다 오래됐는지 정수 변환 없이 판정한다. */
function isOlderPolicyRevision(
  candidate: string | null,
  current: string | null,
): boolean {
  if (
    candidate === null ||
    current === null ||
    candidate === current ||
    !POSITIVE_DECIMAL_REVISION.test(candidate) ||
    !POSITIVE_DECIMAL_REVISION.test(current)
  ) {
    return false;
  }
  if (candidate.length !== current.length) {
    return candidate.length < current.length;
  }
  return candidate < current;
}

/** 늦게 도착한 mutation success는 더 최신인 prop/409 snapshot을 되돌리지 않는다. */
export function applyPolicyMutationSuccess(
  state: PolicyEditorState,
  policy: ProviderRefreshPolicyRecord,
): PolicyEditorState {
  if (isOlderPolicyRevision(policy.revision, state.latestObservedRevision)) {
    return state;
  }
  return {
    ...applyServerPolicyState(state, policy),
    lastSavedAt: policy.updated_at,
  };
}

/** 늦게 도착한 409도 최신 draft/deferred/conflict 상태를 그대로 보존한다. */
export function applyPolicyMutationConflict(
  state: PolicyEditorState,
  conflict: PolicyRevisionConflict,
): PolicyEditorState {
  if (
    isOlderPolicyRevision(
      conflict.currentRevision,
      state.latestObservedRevision,
    )
  ) {
    return state;
  }
  return {
    ...state,
    draft:
      conflict.currentPolicy === null
        ? state.draft
        : {
            ...state.draft,
            source_kind: sourceKindValue(conflict.currentPolicy.source_kind),
          },
    error: null,
    hasDeferredServerPolicy: true,
    latestObservedPolicy: conflict.currentPolicy,
    latestObservedRevision: conflict.currentRevision,
    revisionConflict: conflict,
  };
}

export function isPolicySaveBlocked(guard: PolicySaveGuard): boolean {
  return (
    guard.incomingPropRevision !== guard.acknowledgedPropRevision ||
    guard.hasDeferredServerPolicy ||
    guard.hasRevisionConflict
  );
}

export function submitPolicyIfAllowed(
  guard: PolicySaveGuard,
  submit: () => void,
): boolean {
  if (isPolicySaveBlocked(guard)) {
    return false;
  }
  submit();
  return true;
}

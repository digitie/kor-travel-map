export type PolicySaveGuard = {
  acknowledgedPropRevision: string | null;
  hasDeferredServerPolicy: boolean;
  hasRevisionConflict: boolean;
  incomingPropRevision: string | null;
};

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

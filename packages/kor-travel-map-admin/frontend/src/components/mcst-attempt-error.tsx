import { Button } from "@/components/ui/button";

const PHASE_LABELS = { fetch: "수집", load: "적재", finalize: "완료 기록", run: "실행" } as const;
const CODES = new Set([
  "MCST_DATASET_FETCH_FAILED",
  "MCST_DATASET_LOAD_FAILED",
  "MCST_DATASET_FINALIZE_FAILED",
  "MCST_DATASET_RUN_ABORTED",
]);

/** 승인된 진단 필드만 읽는다. 응답 본문·URL·임의 payload는 표시하지 않는다. */
export function McstAttemptError({
  error,
  onSelectJob,
}: {
  error: unknown;
  onSelectJob?: () => void;
}) {
  if (!error || typeof error !== "object" || Array.isArray(error)) return null;
  const value = error as Record<string, unknown>;
  if (
    typeof value.code !== "string" || !CODES.has(value.code) ||
    typeof value.phase !== "string" || !Object.hasOwn(PHASE_LABELS, value.phase) ||
    typeof value.reason !== "string" || !/^[A-Za-z0-9_]{1,80}$/.test(value.reason) ||
    typeof value.retryable !== "boolean"
  ) return null;
  return (
    <div aria-label="데이터셋 실패 원인" className="w-full space-y-2 text-xs">
      <p>
        실패 단계: {PHASE_LABELS[value.phase as keyof typeof PHASE_LABELS]} ·{" "}
        원인: <span className="font-mono">{value.reason}</span> ·{" "}
        재시도: {value.retryable ? "가능" : "불가"}
      </p>
      <p className="font-mono text-text-secondary">{value.code}</p>
      {onSelectJob ? (
        <Button size="sm" type="button" variant="outline" onClick={onSelectJob}>
          실패한 데이터셋 작업 보기
        </Button>
      ) : null}
    </div>
  );
}

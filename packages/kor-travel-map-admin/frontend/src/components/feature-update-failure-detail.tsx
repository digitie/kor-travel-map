import { formatDateTime } from "@/lib/format";

/**
 * 큐 요청(feature update request) 실패·재발행 event의 원인을 한 덩어리로 보여 준다.
 *
 * 감사 2026-11-23 §1.2·§4 #15 — 종전에는 큐 요청 실패가 Map DB에 원인 없이 한 줄로만 남았다.
 * 이제 backend가 event payload에 분류·실패 단계·Dagster run·재발행 일정을 싣는다(비밀값은 서버가
 * 걷어낸다). 여기서는 **승인된 필드만** 읽는다 — 임의 payload를 그대로 펼치지 않는다.
 */
const CODES = new Set([
  "FEATURE_UPDATE_EXECUTION_FAILED",
  "FEATURE_UPDATE_RETRY_SCHEDULED",
  "FEATURE_UPDATE_RETRIES_EXHAUSTED",
  "FEATURE_UPDATE_RUN_FAILED",
]);

const FAILURE_CLASS_LABELS: Record<string, string> = {
  transient_db: "일시 DB 오류",
  execution: "실행 오류",
  dispatch: "시작 전 실패",
};

const DB_FAILURE_LABELS: Record<string, string> = {
  lock_timeout: "lock 대기 초과",
  serialization: "직렬화 충돌",
  deadlock: "교착",
  connection: "연결 끊김",
};

function text(value: unknown, max = 200): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= max
    ? value
    : null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0
    ? value
    : null;
}

export function isFeatureUpdateFailureEvent(code: string | null | undefined): boolean {
  return typeof code === "string" && CODES.has(code);
}

export function FeatureUpdateFailureDetail({
  code,
  payload,
}: {
  code: string | null | undefined;
  payload: unknown;
}) {
  if (!isFeatureUpdateFailureEvent(code)) return null;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const value = payload as Record<string, unknown>;
  const failureClass = text(value.failure_class, 40);
  const dbFailure = text(value.db_failure, 40);
  const stage = text(value.stage);
  const failedStep = text(value.failed_step);
  const runId = text(value.dagster_run_id, 80);
  const retryCount = count(value.retry_count);
  const maxRetries = count(value.max_retries);
  const nextDispatchAt = text(value.next_dispatch_at, 60);
  const classLabel = failureClass
    ? (FAILURE_CLASS_LABELS[failureClass] ?? failureClass)
    : null;
  const dbLabel = dbFailure ? (DB_FAILURE_LABELS[dbFailure] ?? dbFailure) : null;
  const items: Array<{ label: string; value: string; mono?: boolean }> = [];
  if (classLabel) {
    items.push({
      label: "분류",
      value: dbLabel ? `${classLabel}(${dbLabel})` : classLabel,
    });
  }
  if (stage) items.push({ label: "실패 단계", value: stage, mono: true });
  if (failedStep) items.push({ label: "실패 step", value: failedStep, mono: true });
  if (retryCount !== null && maxRetries !== null) {
    items.push({ label: "재발행", value: `${retryCount}/${maxRetries}` });
  }
  if (nextDispatchAt) {
    items.push({ label: "다음 발행", value: formatDateTime(nextDispatchAt) });
  }
  if (runId) items.push({ label: "Dagster run", value: runId, mono: true });
  if (items.length === 0) return null;
  return (
    <dl
      aria-label="요청 실패 원인"
      className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs"
    >
      {items.map((item) => (
        <div className="flex gap-1" key={item.label}>
          <dt className="text-text-secondary">{item.label}</dt>
          <dd className={item.mono ? "font-mono break-all" : undefined}>
            {item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

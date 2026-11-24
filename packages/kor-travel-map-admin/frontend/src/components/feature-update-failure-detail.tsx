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

function isFeatureUpdateFailureEvent(code: string | null | undefined): boolean {
  return typeof code === "string" && CODES.has(code);
}

type FailureItem = { label: string; value: string; mono?: boolean };

function classItem(value: Record<string, unknown>): FailureItem | null {
  const failureClass = text(value.failure_class, 40);
  if (!failureClass) return null;
  const classLabel = FAILURE_CLASS_LABELS[failureClass] ?? failureClass;
  const dbFailure = text(value.db_failure, 40);
  const dbLabel = dbFailure ? (DB_FAILURE_LABELS[dbFailure] ?? dbFailure) : null;
  return { label: "분류", value: dbLabel ? `${classLabel}(${dbLabel})` : classLabel };
}

function retryItem(value: Record<string, unknown>): FailureItem | null {
  const retryCount = count(value.retry_count);
  const maxRetries = count(value.max_retries);
  if (retryCount === null || maxRetries === null) return null;
  return { label: "재발행", value: `${retryCount}/${maxRetries}` };
}

function monoItem(label: string, raw: string | null): FailureItem | null {
  return raw ? { label, value: raw, mono: true } : null;
}

/** 승인된 필드만 순서대로 — 값이 없는 항목은 뺀다. */
function failureItems(payload: unknown): FailureItem[] {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return [];
  const value = payload as Record<string, unknown>;
  const nextDispatchAt = text(value.next_dispatch_at, 60);
  const items = [
    classItem(value),
    monoItem("실패 단계", text(value.stage, 300)),
    monoItem("실패 step", text(value.failed_step, 300)),
    retryItem(value),
    nextDispatchAt ? { label: "다음 발행", value: formatDateTime(nextDispatchAt) } : null,
    monoItem("Dagster run", text(value.dagster_run_id, 80)),
  ];
  return items.filter((item): item is FailureItem => item !== null);
}

export function FeatureUpdateFailureDetail({
  code,
  payload,
}: {
  code: string | null | undefined;
  payload: unknown;
}) {
  const items = isFeatureUpdateFailureEvent(code) ? failureItems(payload) : [];
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

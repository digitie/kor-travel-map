import type {
  ExecutionKind,
  PipelineExecutionRootRecord,
} from "@/api/pipeline";

/**
 * root 행의 effective provider/dataset identity 표시 문자열. 독립 배열은 단일
 * provider/dataset 필터와 요약 표시용이고 exact pair는 호출부가
 * `provider_datasets[]`로 별도 표시한다.
 */
export function rootIdentityLabel(root: PipelineExecutionRootRecord): {
  primary: string;
  secondary: string;
} {
  const providers = root.providers.length > 0 ? root.providers.join(", ") : null;
  const datasets =
    root.dataset_keys.length > 0 ? root.dataset_keys.join(", ") : null;
  return {
    primary: providers ?? root.scope_type ?? root.kind,
    secondary: datasets ?? root.scope_type ?? "",
  };
}

/** root 진행 표시 — request root는 projected_job, standalone root는 자체 진행률(C3b c). */
export function rootProgressLabel(root: PipelineExecutionRootRecord): string {
  if (root.kind === "update_request") {
    if (!root.projected_job) {
      return "-";
    }
    const stage = root.projected_job.current_stage
      ? ` · ${root.projected_job.current_stage}`
      : "";
    return `${root.projected_job.progress}%${stage}`;
  }
  if (root.progress === null || root.progress === undefined) {
    return "-";
  }
  const stage = root.current_stage ? ` · ${root.current_stage}` : "";
  return `${root.progress}%${stage}`;
}

export const EXECUTION_KIND_LABELS: Record<ExecutionKind, string> = {
  import_job: "적재 작업",
  update_request: "갱신 요청",
};

export function executionKindLabel(kind: string): string {
  return kind in EXECUTION_KIND_LABELS
    ? EXECUTION_KIND_LABELS[kind as ExecutionKind]
    : kind;
}

/** `execution={kind}:{id}` 딥링크 파싱. 잘못된 값은 무시한다. */
export function parseExecutionParam(
  value: string | undefined,
): { kind: ExecutionKind; id: string } | null {
  if (!value) {
    return null;
  }
  const separator = value.indexOf(":");
  if (separator <= 0) {
    return null;
  }
  const kind = value.slice(0, separator);
  const id = value.slice(separator + 1);
  if ((kind !== "import_job" && kind !== "update_request") || !id) {
    return null;
  }
  return { kind, id };
}

const CRON_FIELD_NAMES = ["분", "시", "일", "월", "요일"] as const;

/** 5-field cron의 얕은 사람 친화 설명(검증은 서버 책임 — #613 가드). */
export function describeCron(cron: string | null | undefined): string | null {
  if (!cron) {
    return null;
  }
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) {
    return null;
  }
  const [minute, hour, day, month, weekday] = parts;
  if (minute.startsWith("*/")) {
    return `${minute.slice(2)}분 간격 실행`;
  }
  if (hour === "*" && day === "*" && month === "*" && weekday === "*") {
    return `매시 ${minute}분 실행`;
  }
  if (day === "*" && month === "*" && weekday === "*") {
    return `매일 ${hour}시 ${minute}분 실행`;
  }
  if (day === "*" && month === "*") {
    return `매주 요일(${weekday}) ${hour}시 ${minute}분 실행`;
  }
  if (month === "*" && weekday === "*") {
    return `매월 ${day}일 ${hour}시 ${minute}분 실행`;
  }
  return parts
    .map((part, index) => `${CRON_FIELD_NAMES[index]}=${part}`)
    .join(" ");
}

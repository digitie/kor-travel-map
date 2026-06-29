import { cn } from "@/lib/utils";

// 영어 enum 상태값 → 간결한 한글. 키는 toLowerCase 후 하이픈을 언더스코어로
// 정규화한 형태로 보관한다(예: "dry-run"/"dry_run" 모두 매칭).
const STATUS_LABELS: Record<string, string> = {
  // 정상/성공 계열
  ok: "정상",
  normal: "정상",
  success: "성공",
  succeeded: "성공",
  done: "완료",
  completed: "완료",
  active: "활성",
  accepted: "수락됨",
  merged: "병합됨",
  resolved: "해결됨",
  started: "시작됨",
  applied: "반영됨",
  curated: "큐레이션됨",
  validated: "검증됨",
  loaded: "적재됨",
  implemented: "구현됨",
  fresh: "최신",
  // 진행/대기 계열
  queued: "대기",
  pending: "대기",
  loading: "로딩중",
  running: "실행중",
  starting: "시작중",
  dry_run: "모의실행",
  validating: "검증중",
  in_progress: "진행중",
  materializing: "구체화중",
  scheduled: "예정됨",
  planned: "예정됨",
  ongoing: "진행중",
  managed: "관리됨",
  acknowledged: "확인됨",
  open: "열림",
  candidate: "후보",
  uploaded: "업로드됨",
  canceling: "취소중",
  paused: "일시정지",
  connecting: "연결중",
  reconnecting: "재연결중",
  // 실패/부정 계열
  error: "오류",
  failed: "실패",
  failure: "실패",
  cancelled: "취소됨",
  canceled: "취소됨",
  unavailable: "사용불가",
  critical: "심각",
  rejected: "거절됨",
  denied: "거부됨",
  inactive: "비활성",
  deleted: "삭제됨",
  disabled: "비활성화",
  expired: "만료됨",
  archived: "보관됨",
  deprecated: "지원중단",
  revoked: "폐기됨",
  skipped: "건너뜀",
  validation_failed: "검증실패",
  load_failed: "적재실패",
  not_found: "없음",
  degraded: "저하됨",
  manual_required: "수동 필요",
  provider_needed: "공급자 필요",
  manual_only: "수동 전용",
  ended: "종료됨",
  stopped: "중지됨",
  ignored: "무시됨",
  hidden: "숨김",
  not_started: "시작 전",
  stale: "오래됨",
  // 기타/중립
  draft: "초안",
  unknown: "알수없음",
  none: "없음",
  info: "정보",
  warning: "경고",
  debug: "디버그",
};

/**
 * 영어 enum 상태값을 간결한 한글로 변환한다. 알 수 없는 값은 원문을 그대로
 * 돌려준다(빈 문자열로 만들지 않음). null/undefined는 빈 문자열로 처리한다.
 */
export function statusLabel(status: string | null | undefined): string {
  if (status == null) return "";
  const normalized = status.toLowerCase().replace(/-/g, "_");
  return STATUS_LABELS[normalized] ?? status;
}

function statusTone(status: string | null | undefined) {
  const normalized = (status ?? "").toLowerCase();
  if (
    [
      "ok",
      "done",
      "success",
      "active",
      "accepted",
      "merged",
      "resolved",
      "started",
    ].includes(normalized)
  ) {
    return "success" as const;
  }
  if (
    [
      "error",
      "failed",
      "failure",
      "cancelled",
      "canceled",
      "unavailable",
      "critical",
      "rejected",
    ].includes(normalized)
  ) {
    return "destructive" as const;
  }
  if (["queued", "pending", "loading", "running", "dry-run"].includes(normalized)) {
    return "warning" as const;
  }
  return "muted" as const;
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const tone = statusTone(status);
  return (
    <span
      className={cn(
        "inline-flex h-6 w-fit shrink-0 items-center gap-1.5 rounded-md px-2 text-[11px] font-bold tracking-[0.05em] uppercase",
        tone === "success" && "bg-success/10 text-success",
        tone === "destructive" && "bg-destructive/10 text-destructive",
        tone === "warning" && "bg-warning/10 text-warning",
        tone === "muted" && "bg-surface-subtle text-text-secondary",
      )}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
      {status == null ? "-" : statusLabel(status)}
    </span>
  );
}

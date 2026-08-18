// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app
/**
 * 상태 어휘의 단일 정본 — enum → 한글 라벨 사전 + 상태 → tone 테이블(design.md §Status colour
 * semantics). 모든 badge·dot·option·column은 이 모듈을 읽고, enum 값을 raw로 렌더하지 않는다.
 *
 *  - `statusLabel(status)`  enum → 간결한 한글(알 수 없는 값은 원문 유지, null → "").
 *  - `toneFor(status)`      enum → StatusTone(알 수 없는 값은 "neutral").
 *  - `STATUS_TONE`          정규화 키(lowercase, `-`→`_`) → tone 테이블(읽기 전용).
 *  - `httpStatusTone(code)` HTTP status code → tone(2xx neutral · 3xx info · 4xx warning · 5xx destructive).
 *
 * select/filter option도 raw enum을 쓰지 않는다 — `{ value, label: statusLabel(value) }`로 만든다.
 *
 * tone 의미(design.md):
 *  success     = 활성/완료/ready
 *  warning     = 검토 필요/대기(사람의 결정을 기다림)/quarantine/저하
 *  destructive = 실패/blocked/dead-letter/거부
 *  info        = draft/candidate/valid(정보성) + 기계가 진행 중인 상태(queued/running/…)
 *  neutral     = archived/disabled/unknown/종료된 중립 상태
 *
 * 키는 toLowerCase 후 하이픈을 언더스코어로 정규화한 형태로 보관한다
 * (예: "dry-run"/"dry_run" 모두 매칭). 컴포넌트 파일은 이 모듈만 import한다.
 */

export type StatusTone = "success" | "warning" | "destructive" | "info" | "neutral";

/** 상태 문자열을 사전 키로 정규화한다: lowercase + `-` → `_` + trim. */
export function normalizeStatusKey(status: string): string {
  return status.trim().toLowerCase().replace(/-/g, "_");
}

// 영어 enum 상태값 → 간결한 한글. 기존 라벨 값은 유지(테스트/e2e 문자열 계약),
// 아직 raw로 렌더되던 enum(feature 3축 · curation · import row · stream · freshness ·
// verification · level 등)을 추가했다.
export const STATUS_LABELS: Readonly<Record<string, string>> = {
  // 정상/성공 계열
  ok: "정상",
  normal: "정상",
  success: "성공",
  succeeded: "성공",
  done: "완료",
  completed: "완료",
  active: "활성",
  ready: "준비됨",
  accepted: "수락됨",
  merged: "병합됨",
  resolved: "해결됨",
  started: "시작됨",
  uploading: "업로드중",
  applied: "반영됨",
  curated: "큐레이션됨",
  validated: "검증됨",
  loaded: "적재됨",
  implemented: "구현됨",
  fresh: "최신",
  published: "공개",
  included: "포함됨",
  imported: "반영됨",
  promoted: "승격됨",
  delivered: "전달됨",
  reconciled: "정합화됨",
  confirmed: "확인됨",
  confirmed_applied: "반영 확인",
  confirmed_not_applied: "미반영 확인",
  allowed: "허용",
  saved: "저장됨",
  recorded: "기록됨",
  finalized: "확정됨",
  found: "발견됨",
  managed: "관리됨",
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
  acknowledged: "확인됨",
  open: "열림",
  candidate: "후보",
  uploaded: "업로드됨",
  canceling: "취소중",
  deleting: "삭제중",
  paused: "일시정지",
  connecting: "연결중",
  reconnecting: "재연결중",
  live: "실시간",
  polling: "폴링 보완",
  leased: "처리중",
  preparing: "준비중",
  armed: "대기중",
  // 실패/부정 계열
  error: "오류",
  failed: "실패",
  failure: "실패",
  cancelled: "취소됨",
  canceled: "취소됨",
  unavailable: "사용불가",
  unauthorized: "로그인 필요",
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
  cancel_failed: "취소 실패",
  terminal_record_failed: "기록 실패",
  not_found: "없음",
  degraded: "저하됨",
  manual_required: "수동 필요",
  manual_review: "수동 검토",
  provider_needed: "공급자 필요",
  manual_only: "수동 전용",
  ended: "종료됨",
  stopped: "중지됨",
  ignored: "무시됨",
  hidden: "숨김",
  not_started: "시작 전",
  never_run: "미실행",
  stale: "오래됨",
  overdue: "오래됨",
  blocked: "차단됨",
  dead: "데드레터",
  dead_letter: "데드레터",
  quarantined: "격리",
  invalid: "형식 오류",
  unmatched: "미일치",
  review_required: "수동 검토",
  ambiguous: "후보 다수",
  mismatch: "불일치",
  pending_verification: "검증 대기",
  retry: "재시도",
  retryable: "재시도 가능",
  fenced: "펜스 차단",
  restore_fenced: "복원 펜스",
  orphan: "고아 항목",
  missing: "누락",
  transient: "일시적",
  permanent: "영구적",
  retired: "종료",
  suppressed: "비공개",
  superseded: "대체됨",
  // 기타/중립
  draft: "초안",
  valid: "유효",
  unknown: "알수없음",
  none: "없음",
  info: "정보",
  warning: "경고",
  debug: "디버그",
  standby: "대기 모드",
  canonical: "정본",
  no_data: "데이터 없음",
  unchanged: "변경 없음",
  not_applicable: "해당 없음",
  not_requested: "미요청",
  already_terminal: "이미 종료",
  cleared: "해제됨",
  consumed: "소비됨",
  uncertain: "불확실",
};

/** 상태 → tone. design.md §Status colour semantics의 유일한 발행처. */
export const STATUS_TONE: Readonly<Record<string, StatusTone>> = {
  // ── success: 활성/완료/ready ──
  ok: "success",
  normal: "success",
  success: "success",
  succeeded: "success",
  done: "success",
  completed: "success",
  active: "success",
  ready: "success",
  accepted: "success",
  merged: "success",
  resolved: "success",
  started: "success",
  applied: "success",
  curated: "success",
  validated: "success",
  loaded: "success",
  implemented: "success",
  fresh: "success",
  published: "success",
  included: "success",
  imported: "success",
  promoted: "success",
  delivered: "success",
  reconciled: "success",
  confirmed: "success",
  confirmed_applied: "success",
  confirmed_not_applied: "success",
  allowed: "success",
  saved: "success",
  recorded: "success",
  finalized: "success",
  found: "success",
  managed: "success",
  live: "success",
  ongoing: "success",
  // ── warning: 검토 필요 / 사람의 결정 대기 / quarantine / 저하 ──
  warning: "warning",
  pending: "warning",
  open: "warning",
  paused: "warning",
  degraded: "warning",
  reconnecting: "warning",
  quarantined: "warning",
  review_required: "warning",
  ambiguous: "warning",
  unmatched: "warning",
  manual_required: "warning",
  manual_review: "warning",
  manual_only: "warning",
  provider_needed: "warning",
  stale: "warning",
  overdue: "warning",
  mismatch: "warning",
  pending_verification: "warning",
  retry: "warning",
  retryable: "warning",
  fenced: "warning",
  restore_fenced: "warning",
  orphan: "warning",
  missing: "warning",
  transient: "warning",
  uncertain: "warning",
  // ── destructive: 실패 / blocked / dead-letter / 거부 ──
  error: "destructive",
  failed: "destructive",
  failure: "destructive",
  critical: "destructive",
  cancelled: "destructive",
  canceled: "destructive",
  unavailable: "destructive",
  unauthorized: "destructive",
  rejected: "destructive",
  denied: "destructive",
  blocked: "destructive",
  dead: "destructive",
  dead_letter: "destructive",
  invalid: "destructive",
  validation_failed: "destructive",
  load_failed: "destructive",
  cancel_failed: "destructive",
  terminal_record_failed: "destructive",
  permanent: "destructive",
  // ── info: draft / candidate / valid(정보성) + 기계 진행 중 ──
  info: "info",
  draft: "info",
  candidate: "info",
  valid: "info",
  queued: "info",
  loading: "info",
  running: "info",
  starting: "info",
  dry_run: "info",
  validating: "info",
  in_progress: "info",
  materializing: "info",
  scheduled: "info",
  planned: "info",
  acknowledged: "info",
  uploading: "info",
  uploaded: "info",
  canceling: "info",
  deleting: "info",
  connecting: "info",
  polling: "info",
  leased: "info",
  preparing: "info",
  armed: "info",
  // ── neutral: archived / disabled / unknown / 종료된 중립 상태 ──
  debug: "neutral",
  unknown: "neutral",
  none: "neutral",
  standby: "neutral",
  inactive: "neutral",
  deleted: "neutral",
  disabled: "neutral",
  expired: "neutral",
  archived: "neutral",
  deprecated: "neutral",
  revoked: "neutral",
  skipped: "neutral",
  not_found: "neutral",
  ended: "neutral",
  stopped: "neutral",
  ignored: "neutral",
  hidden: "neutral",
  not_started: "neutral",
  never_run: "neutral",
  retired: "neutral",
  suppressed: "neutral",
  superseded: "neutral",
  canonical: "neutral",
  no_data: "neutral",
  unchanged: "neutral",
  not_applicable: "neutral",
  not_requested: "neutral",
  already_terminal: "neutral",
  cleared: "neutral",
  consumed: "neutral",
};

/**
 * 영어 enum 상태값을 간결한 한글로 변환한다. 알 수 없는 값은 원문을 그대로
 * 돌려준다(빈 문자열로 만들지 않음). null/undefined는 빈 문자열로 처리한다.
 */
export function statusLabel(status: string | null | undefined): string {
  if (status == null) return "";
  return STATUS_LABELS[normalizeStatusKey(status)] ?? status;
}

/**
 * 상태 → tone. 알 수 없는 값(그리고 null/undefined)은 "neutral".
 * 하이픈/대소문자는 정규화한다("dry-run" → "dry_run").
 */
export function toneFor(status: string | null | undefined): StatusTone {
  if (status == null) return "neutral";
  return STATUS_TONE[normalizeStatusKey(status)] ?? "neutral";
}

/**
 * HTTP status code → tone(M20 HttpStatusBadge 규율): 2xx neutral(정상은 조용히) ·
 * 3xx info · 4xx warning · 5xx destructive · 그 외/파싱 불가 neutral.
 */
export function httpStatusTone(code: number | string | null | undefined): StatusTone {
  const numeric = typeof code === "number" ? code : Number.parseInt(String(code ?? ""), 10);
  if (!Number.isFinite(numeric)) return "neutral";
  if (numeric >= 500) return "destructive";
  if (numeric >= 400) return "warning";
  if (numeric >= 300) return "info";
  return "neutral";
}

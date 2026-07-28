import { Badge } from "@/components/ui/badge";
import { statusLabel } from "@/lib/status-label";
import { cn } from "@/lib/utils";


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
      "live",
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
      "unauthorized",
      "critical",
      "rejected",
    ].includes(normalized)
  ) {
    return "destructive" as const;
  }
  if (
    [
      "queued",
      "pending",
      "loading",
      "running",
      "dry-run",
      "reconnecting",
      "polling",
    ].includes(normalized)
  ) {
    return "warning" as const;
  }
  return "muted" as const;
}

// tone → ui/badge variant. muted는 ghost 배경과 동일 톤을 로컬 클래스로 유지한다.
const TONE_VARIANT = {
  success: "success",
  destructive: "destructive",
  warning: "warning",
  muted: "ghost",
} as const;

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const tone = statusTone(status);
  return (
    <Badge
      className={cn(
        "gap-1.5 text-[11px]",
        tone === "muted" && "bg-surface-subtle text-text-secondary",
      )}
      variant={TONE_VARIANT[tone]}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
      {status == null ? "-" : statusLabel(status)}
    </Badge>
  );
}

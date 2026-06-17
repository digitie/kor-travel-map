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
      {status ?? "-"}
    </span>
  );
}

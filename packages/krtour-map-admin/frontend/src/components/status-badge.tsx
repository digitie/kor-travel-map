import { Badge } from "@/components/ui/badge";

function statusVariant(status: string | null | undefined) {
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
    return "secondary" as const;
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
  return "outline" as const;
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  return <Badge variant={statusVariant(status)}>{status ?? "-"}</Badge>;
}

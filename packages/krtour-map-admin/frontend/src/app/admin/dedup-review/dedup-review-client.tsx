"use client";

import { CheckIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { useState } from "react";

import {
  type DedupDecision,
  type DedupStatus,
  useDedupDecisionMutation,
  useDedupReviews,
} from "@/api/dedup";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime, shortId } from "@/lib/format";

const statuses: Array<DedupStatus | "all"> = [
  "pending",
  "accepted",
  "rejected",
  "merged",
  "ignored",
  "all",
];

export function DedupReviewClient() {
  const [status, setStatus] = useState<DedupStatus | "all">("pending");
  const reviews = useDedupReviews({
    status: status === "all" ? undefined : [status],
    page_size: 100,
  });
  const decision = useDedupDecisionMutation();

  const decide = (reviewKey: string, value: DedupDecision) => {
    decision.mutate({
      reviewKey,
      body: {
        decision: value,
        decision_reason: `admin-ui ${value}`,
        reviewed_by: "local-admin",
      },
    });
  };

  return (
    <AdminShell
      actions={
        <Button
          disabled={reviews.isFetching}
          type="button"
          variant="outline"
          onClick={() => void reviews.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="중복 후보를 운영자가 검토합니다. merge는 master 선택 UI가 필요한 후속 조치입니다."
      section="Admin"
      title="Dedup review"
    >
      <div className="flex flex-col gap-4">
        {(reviews.isError || decision.isError) && (
          <Alert variant="destructive">
            <AlertTitle>dedup review 처리 실패</AlertTitle>
            <AlertDescription>
              {reviews.error?.message ?? decision.error?.message}
            </AlertDescription>
          </Alert>
        )}

        <NativeSelect
          aria-label="dedup status"
          value={status}
          onChange={(event) => setStatus(event.target.value as DedupStatus | "all")}
        >
          {statuses.map((item) => (
            <NativeSelectOption key={item} value={item}>
              {item}
            </NativeSelectOption>
          ))}
        </NativeSelect>

        {reviews.isLoading ? <Skeleton className="h-96" /> : null}
        <div className="overflow-auto rounded-lg border bg-background">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>review</TableHead>
                <TableHead>score</TableHead>
                <TableHead>feature A</TableHead>
                <TableHead>feature B</TableHead>
                <TableHead>distance</TableHead>
                <TableHead>status</TableHead>
                <TableHead>created</TableHead>
                <TableHead>actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(reviews.data?.data.items ?? []).map((item) => (
                <TableRow key={item.review_key}>
                  <TableCell className="font-mono text-xs">
                    {shortId(item.review_key)}
                  </TableCell>
                  <TableCell className="font-mono">
                    {item.total_score.toFixed(1)}
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{item.feature_a.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.feature_a.provider ?? "-"} · {item.feature_a.category}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{item.feature_b.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.feature_b.provider ?? "-"} · {item.feature_b.category}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono">
                    {item.distance_m === null ? "-" : `${item.distance_m.toFixed(1)}m`}
                  </TableCell>
                  <TableCell>
                    <StatusBadge status={item.status} />
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(item.created_at)}
                  </TableCell>
                  <TableCell>
                    {item.status === "pending" ? (
                      <div className="flex flex-wrap gap-1">
                        <Button
                          disabled={decision.isPending}
                          size="sm"
                          type="button"
                          variant="outline"
                          onClick={() => decide(item.review_key, "accepted")}
                        >
                          <CheckIcon data-icon="inline-start" />
                          accept
                        </Button>
                        <Button
                          disabled={decision.isPending}
                          size="sm"
                          type="button"
                          variant="outline"
                          onClick={() => decide(item.review_key, "rejected")}
                        >
                          <XIcon data-icon="inline-start" />
                          reject
                        </Button>
                        <Button
                          disabled={decision.isPending}
                          size="sm"
                          type="button"
                          variant="ghost"
                          onClick={() => decide(item.review_key, "ignored")}
                        >
                          ignore
                        </Button>
                      </div>
                    ) : (
                      <span className="text-sm text-muted-foreground">완료</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {!reviews.isLoading && (reviews.data?.data.items.length ?? 0) === 0 ? (
                <TableRow>
                  <TableCell
                    className="h-32 text-center text-muted-foreground"
                    colSpan={8}
                  >
                    dedup review가 없습니다.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      </div>
    </AdminShell>
  );
}

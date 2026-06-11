"use client";

import { CheckIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { useState } from "react";

import {
  type EnrichmentDecision,
  type EnrichmentStatus,
  useEnrichmentDecisionMutation,
  useEnrichmentReviews,
} from "@/api/enrichment";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
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

const statuses: Array<EnrichmentStatus | "all"> = [
  "pending",
  "accepted",
  "rejected",
  "ignored",
  "all",
];

const PAGE_SIZE = 50;

export function EnrichmentReviewClient() {
  const [status, setStatus] = useState<EnrichmentStatus | "all">("pending");
  // cursorStack: 2페이지부터의 cursor 누적(1페이지는 cursor 없음). 마지막이 현재 페이지.
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const currentCursor =
    cursorStack.length > 0 ? cursorStack[cursorStack.length - 1] : undefined;
  const reviews = useEnrichmentReviews({
    status: status === "all" ? undefined : [status],
    page_size: PAGE_SIZE,
    cursor: currentCursor,
  });
  const decision = useEnrichmentDecisionMutation();

  const nextCursor = reviews.data?.meta.page?.next_cursor ?? undefined;
  const pageIndex = cursorStack.length + 1;

  const changeStatus = (value: EnrichmentStatus | "all") => {
    setStatus(value);
    setCursorStack([]); // 필터 바뀌면 1페이지로.
  };
  const goNext = () => {
    if (nextCursor) setCursorStack((stack) => [...stack, nextCursor]);
  };
  const goPrev = () => setCursorStack((stack) => stack.slice(0, -1));

  const decide = (reviewId: string, value: EnrichmentDecision) => {
    decision.mutate({
      reviewKey: reviewId,
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
      description="축제 enrichment 매칭(visitkorea 2차 → datagokr 1차)을 운영자가 검토합니다. accept하면 1차 축제에 visitkorea source가 enrichment로 연결됩니다."
      section="Admin"
      title="Enrichment review"
    >
      <div className="flex flex-col gap-4">
        {(reviews.isError || decision.isError) && (
          <Alert variant="destructive">
            <AlertTitle>enrichment review 처리 실패</AlertTitle>
            <AlertDescription>
              {reviews.error?.message ?? decision.error?.message}
            </AlertDescription>
          </Alert>
        )}

        <NativeSelect
          aria-label="enrichment status"
          value={status}
          onChange={(event) =>
            changeStatus(event.target.value as EnrichmentStatus | "all")
          }
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
                <TableHead>1차 (datagokr)</TableHead>
                <TableHead>2차 (visitkorea)</TableHead>
                <TableHead>status</TableHead>
                <TableHead>created</TableHead>
                <TableHead>actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(reviews.data?.data.items ?? []).map((item) => (
                <TableRow key={item.review_id}>
                  <TableCell className="font-mono text-xs">
                    {shortId(item.review_id)}
                  </TableCell>
                  <TableCell className="font-mono">
                    {item.name_score.toFixed(1)}
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{item.target_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.target_category ?? "-"} ·{" "}
                      {shortId(item.target_feature_id)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium">{item.source_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {item.source_provider} · {item.source_entity_id}
                    </div>
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
                          onClick={() => decide(item.review_id, "accepted")}
                        >
                          <CheckIcon data-icon="inline-start" />
                          accept
                        </Button>
                        <Button
                          disabled={decision.isPending}
                          size="sm"
                          type="button"
                          variant="outline"
                          onClick={() => decide(item.review_id, "rejected")}
                        >
                          <XIcon data-icon="inline-start" />
                          reject
                        </Button>
                        <Button
                          disabled={decision.isPending}
                          size="sm"
                          type="button"
                          variant="ghost"
                          onClick={() => decide(item.review_id, "ignored")}
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
              {!reviews.isLoading &&
              (reviews.data?.data.items.length ?? 0) === 0 ? (
                <TableRow>
                  <TableCell
                    className="h-32 text-center text-muted-foreground"
                    colSpan={7}
                  >
                    enrichment review가 없습니다.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>

        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-muted-foreground">
            페이지 {pageIndex} · {reviews.data?.data.items.length ?? 0}건
            {nextCursor ? " (다음 페이지 있음)" : ""}
          </span>
          <div className="flex gap-1">
            <Button
              aria-label="이전 페이지"
              disabled={cursorStack.length === 0 || reviews.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={goPrev}
            >
              이전
            </Button>
            <Button
              aria-label="다음 페이지"
              disabled={!nextCursor || reviews.isFetching}
              size="sm"
              type="button"
              variant="outline"
              onClick={goNext}
            >
              다음
            </Button>
          </div>
        </div>
      </div>
    </AdminShell>
  );
}

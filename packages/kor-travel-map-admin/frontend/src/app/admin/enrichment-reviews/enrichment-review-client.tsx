"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { CheckIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { useMemo, useState } from "react";

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
import { DataTable } from "@/components/ui/data-table";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
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

  const items = reviews.data?.data.items ?? [];
  type ReviewRow = NonNullable<typeof reviews.data>["data"]["items"][number];
  const columns = useMemo<ColumnDef<ReviewRow, unknown>[]>(
    () => [
      {
        id: "review",
        header: "review",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.review_id)}
          </span>
        ),
      },
      {
        accessorKey: "name_score",
        header: "score",
        cell: ({ row }) => (
          <span className="font-mono">{row.original.name_score.toFixed(1)}</span>
        ),
      },
      {
        id: "target",
        header: "1차 (datagokr)",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.target_name}</div>
            <div className="text-xs text-muted-foreground">
              {row.original.target_category ?? "-"} ·{" "}
              {shortId(row.original.target_feature_id)}
            </div>
          </>
        ),
      },
      {
        id: "source",
        header: "2차 (visitkorea)",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.source_name}</div>
            <div className="text-xs text-muted-foreground">
              {row.original.source_provider} · {row.original.source_entity_id}
            </div>
          </>
        ),
      },
      {
        accessorKey: "status",
        header: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "created_at",
        header: "created",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "actions",
        enableSorting: false,
        cell: ({ row }) => {
          const item = row.original;
          return item.status === "pending" ? (
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
          );
        },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [decision.isPending],
  );

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

        <DataTable
          columns={columns}
          data={items}
          getRowId={(row) => row.review_id}
          isLoading={reviews.isLoading}
          emptyMessage="enrichment review가 없습니다."
          containerClassName="overflow-auto rounded-lg border bg-background"
        />

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

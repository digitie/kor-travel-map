"use client";

import {
  type ColumnDef,
  type Row,
  type RowSelectionState,
} from "@tanstack/react-table";
import { CheckIcon, MergeIcon, RefreshCwIcon, XIcon } from "lucide-react";
import { useMemo, useState } from "react";

import {
  type DedupDecision,
  type DedupFeatureRecord,
  type DedupReviewRecord,
  type DedupStatus,
  useDedupDecisionMutation,
  useDedupReviews,
} from "@/api/dedup";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatDateTime, shortId } from "@/lib/format";

const statuses: Array<DedupStatus | "all"> = [
  "pending",
  "accepted",
  "rejected",
  "merged",
  "ignored",
  "all",
];

/**
 * master 자동 선정 추천(`core.scoring.select_master` 1순위 = 좌표 보유)의 클라이언트
 * 힌트. backend가 좌표→updated_at→provider 우선순위로 최종 결정하므로 여기서는 운영자
 * 판단을 돕는 좌표 보유 여부만 노출한다.
 */
function hasCoord(feature: DedupFeatureRecord): boolean {
  return typeof feature.lon === "number" && typeof feature.lat === "number";
}

export function DedupReviewClient() {
  const [status, setStatus] = useState<DedupStatus | "all">("pending");
  const [mergeKey, setMergeKey] = useState<string | null>(null);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const reviews = useDedupReviews({
    status: status === "all" ? undefined : [status],
    page_size: 100,
  });
  const decision = useDedupDecisionMutation();

  const decide = (reviewId: string, value: DedupDecision) => {
    decision.mutate({
      reviewKey: reviewId,
      body: {
        decision: value,
        decision_reason: `admin-ui ${value}`,
        reviewed_by: "local-admin",
      },
    });
  };

  /**
   * merge 확정. ``masterFeatureId``가 없으면 backend가 ``select_master``로 자동 선정한다.
   * 성공/실패와 무관하게 inline master 선택 패널을 닫는다.
   */
  const merge = (reviewId: string, masterFeatureId?: string) => {
    decision.mutate(
      {
        reviewKey: reviewId,
        body: {
          decision: "merged",
          master_feature_id: masterFeatureId,
          decision_reason: masterFeatureId
            ? "admin-ui merge (master 수동 선택)"
            : "admin-ui merge (master 자동 선정)",
          reviewed_by: "local-admin",
        },
      },
      { onSettled: () => setMergeKey(null) },
    );
  };

  const items = reviews.data?.data.items ?? [];
  const columns = useMemo<ColumnDef<DedupReviewRecord, unknown>[]>(
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
        accessorKey: "total_score",
        header: "score",
        cell: ({ row }) => (
          <span className="font-mono">{row.original.total_score.toFixed(1)}</span>
        ),
      },
      {
        id: "feature_a",
        header: "feature A",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.feature_a.name}</div>
            <div className="text-xs text-muted-foreground">
              {row.original.feature_a.provider ?? "-"} ·{" "}
              {row.original.feature_a.category}
            </div>
          </>
        ),
      },
      {
        id: "feature_b",
        header: "feature B",
        enableSorting: false,
        cell: ({ row }) => (
          <>
            <div className="font-medium">{row.original.feature_b.name}</div>
            <div className="text-xs text-muted-foreground">
              {row.original.feature_b.provider ?? "-"} ·{" "}
              {row.original.feature_b.category}
            </div>
          </>
        ),
      },
      {
        accessorKey: "distance_m",
        header: "distance",
        cell: ({ row }) => (
          <span className="font-mono">
            {typeof row.original.distance_m === "number"
              ? `${row.original.distance_m.toFixed(1)}m`
              : "-"}
          </span>
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
            mergeKey === item.review_id ? (
              <div className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">
                  master 선택 (병합 시 나머지는 master로 흡수)
                </span>
                <div className="flex flex-wrap gap-1">
                  <Button
                    disabled={decision.isPending}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() =>
                      merge(item.review_id, item.feature_a.feature_id)
                    }
                  >
                    A: {item.feature_a.name}
                    {hasCoord(item.feature_a) ? " · 좌표✓" : ""}
                  </Button>
                  <Button
                    disabled={decision.isPending}
                    size="sm"
                    type="button"
                    variant="outline"
                    onClick={() =>
                      merge(item.review_id, item.feature_b.feature_id)
                    }
                  >
                    B: {item.feature_b.name}
                    {hasCoord(item.feature_b) ? " · 좌표✓" : ""}
                  </Button>
                  <Button
                    disabled={decision.isPending}
                    size="sm"
                    type="button"
                    variant="secondary"
                    onClick={() => merge(item.review_id)}
                  >
                    자동 선정
                  </Button>
                  <Button
                    disabled={decision.isPending}
                    size="sm"
                    type="button"
                    variant="ghost"
                    onClick={() => setMergeKey(null)}
                  >
                    취소
                  </Button>
                </div>
              </div>
            ) : (
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
                  variant="default"
                  onClick={() => setMergeKey(item.review_id)}
                >
                  <MergeIcon data-icon="inline-start" />
                  merge
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
            )
          ) : (
            <span className="text-sm text-muted-foreground">완료</span>
          );
        },
      },
    ],
    [decision.isPending, mergeKey],
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
      description="중복 후보를 운영자가 검토합니다. accept/reject/ignore 또는 merge(master 수동 선택 또는 자동 선정)로 처리합니다."
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

        <DataTable
          columns={columns}
          data={items}
          getRowId={(row) => row.review_id}
          isLoading={reviews.isLoading}
          emptyMessage="dedup review가 없습니다."
          manualSorting={false}
          containerClassName="overflow-auto rounded-lg border bg-background"
          enableRowSelection={(row) => row.original.status === "pending"}
          rowSelection={rowSelection}
          onRowSelectionChange={setRowSelection}
          renderBulkActions={(rows: Row<DedupReviewRecord>[]) => {
            // pending review만 일괄 결정한다(완료된 review 재결정 방지 — 선택 자체도
            // enableRowSelection predicate로 막지만 방어적으로 한 번 더 거른다).
            const decideBulk = (value: DedupDecision) => {
              rows
                .filter((row) => row.original.status === "pending")
                .forEach((row) => decide(row.original.review_id, value));
              setRowSelection({});
            };
            return (
              <div className="flex flex-wrap gap-1">
                <Button
                  disabled={decision.isPending}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => decideBulk("accepted")}
                >
                  <CheckIcon data-icon="inline-start" />
                  선택 accept
                </Button>
                <Button
                  disabled={decision.isPending}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => decideBulk("rejected")}
                >
                  <XIcon data-icon="inline-start" />
                  선택 reject
                </Button>
              </div>
            );
          }}
        />
      </div>
    </AdminShell>
  );
}

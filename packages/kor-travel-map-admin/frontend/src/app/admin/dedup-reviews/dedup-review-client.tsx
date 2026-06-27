"use client";

import {
  type ColumnDef,
  type Row,
  type RowSelectionState,
} from "@tanstack/react-table";
import { CheckIcon, MergeIcon, RefreshCwIcon, SearchIcon, XIcon } from "lucide-react";
import { useCallback, useDeferredValue, useMemo, useState } from "react";

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
import { Input } from "@/components/ui/input";
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
const DEDUP_KINDS = [
  "place",
  "event",
  "notice",
  "price",
  "weather",
  "route",
  "area",
] as const;
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const SCORE_FILTERS = [
  { value: "all", label: "score all" },
  { value: "high", label: "score >= 90", min: 90 },
  { value: "middle", label: "score 70-90", min: 70, max: 90 },
  { value: "low", label: "score < 70", max: 70 },
] as const;

type DedupKindFilter = (typeof DEDUP_KINDS)[number] | "all";
type ScoreFilter = (typeof SCORE_FILTERS)[number]["value"];

function scoreBounds(value: ScoreFilter): { min?: number; max?: number } {
  const found = SCORE_FILTERS.find((item) => item.value === value);
  return {
    min: found && "min" in found ? found.min : undefined,
    max: found && "max" in found ? found.max : undefined,
  };
}

function formatScore(value: number): string {
  return value.toFixed(1);
}

function formatDistance(value: number | null | undefined): string {
  if (typeof value !== "number") return "-";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}km`;
  return `${value.toFixed(1)}m`;
}

function formatCount(value: number | null | undefined): string {
  return typeof value === "number" ? value.toLocaleString("ko-KR") : "-";
}

/**
 * master 자동 선정 추천(`core.scoring.select_master` 1순위 = 좌표 보유)의 클라이언트
 * 힌트. backend가 좌표→updated_at→provider 우선순위로 최종 결정하므로 여기서는 운영자
 * 판단을 돕는 좌표 보유 여부만 노출한다.
 */
function hasCoord(feature: DedupFeatureRecord): boolean {
  return typeof feature.lon === "number" && typeof feature.lat === "number";
}

export function DedupReviewClient() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState<DedupStatus | "all">("pending");
  const [kind, setKind] = useState<DedupKindFilter>("all");
  const [provider, setProvider] = useState("");
  const [datasetKey, setDatasetKey] = useState("");
  const [category, setCategory] = useState("");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(100);
  const [mergeKey, setMergeKey] = useState<string | null>(null);
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});
  const [pageIndex, setPageIndex] = useState(1);
  const deferredQ = useDeferredValue(q.trim());
  const deferredProvider = useDeferredValue(provider.trim());
  const deferredDatasetKey = useDeferredValue(datasetKey.trim());
  const deferredCategory = useDeferredValue(category.trim());
  const bounds = scoreBounds(scoreFilter);
  const reviewParams = useMemo(
    () => ({
      status: status === "all" ? undefined : [status],
      kind: kind === "all" ? undefined : [kind],
      provider: deferredProvider.length > 0 ? [deferredProvider] : undefined,
      dataset_key:
        deferredDatasetKey.length > 0 ? [deferredDatasetKey] : undefined,
      category: deferredCategory.length > 0 ? [deferredCategory] : undefined,
      min_score: bounds.min,
      max_score: bounds.max,
      q: deferredQ.length > 0 ? deferredQ : undefined,
      page_size: pageSize,
      page: pageIndex,
    }),
    [
      bounds.max,
      bounds.min,
      deferredCategory,
      deferredDatasetKey,
      deferredProvider,
      deferredQ,
      kind,
      pageIndex,
      pageSize,
      status,
    ],
  );
  const reviews = useDedupReviews(reviewParams);
  const decision = useDedupDecisionMutation();
  const nextCursor = reviews.data?.meta.page?.next_cursor ?? undefined;
  const items = reviews.data?.data.items ?? [];
  const totalItems = reviews.data?.meta.page?.total ?? null;
  const totalPages =
    typeof totalItems === "number"
      ? Math.max(1, Math.ceil(totalItems / pageSize))
      : null;
  const hasNextPage =
    totalPages === null ? Boolean(nextCursor) : pageIndex < totalPages;
  const hasPreviousPage = pageIndex > 1;

  const resetPage = () => {
    setPageIndex(1);
    setMergeKey(null);
    setRowSelection({});
  };
  const goFirst = () => resetPage();
  const goLast = () => {
    if (totalPages !== null) {
      setPageIndex(totalPages);
      setMergeKey(null);
      setRowSelection({});
    }
  };
  const goNext = () => {
    if (!hasNextPage) return;
    setPageIndex((current) =>
      totalPages === null ? current + 1 : Math.min(totalPages, current + 1),
    );
    setMergeKey(null);
    setRowSelection({});
  };
  const goPrev = () => {
    setPageIndex((current) => Math.max(1, current - 1));
    setMergeKey(null);
    setRowSelection({});
  };

  const decide = useCallback((reviewId: string, value: DedupDecision) => {
    decision.mutate({
      reviewKey: reviewId,
      body: {
        decision: value,
        decision_reason: `admin-ui ${value}`,
        reviewed_by: "local-admin",
      },
    });
  }, [decision]);

  /**
   * merge 확정. ``masterFeatureId``가 없으면 backend가 ``select_master``로 자동 선정한다.
   * 성공/실패와 무관하게 inline master 선택 패널을 닫는다.
   */
  const merge = useCallback((reviewId: string, masterFeatureId?: string) => {
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
  }, [decision]);

  const renderPagination = (placement: "top" | "bottom") => (
    <nav
      aria-label={`dedup pagination ${placement}`}
      className="flex flex-col gap-2 rounded-lg border bg-background px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
    >
      <span className="text-sm text-muted-foreground">
        페이지 {pageIndex} / {totalPages ?? "-"} · 총 {formatCount(totalItems)}건
        · 현재 {formatCount(items.length)}건
      </span>
      <div className="flex flex-wrap gap-1">
        <Button
          aria-label="dedup 첫 페이지"
          disabled={!hasPreviousPage || reviews.isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={goFirst}
        >
          첫 페이지
        </Button>
        <Button
          aria-label="dedup 이전 페이지"
          disabled={!hasPreviousPage || reviews.isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={goPrev}
        >
          이전
        </Button>
        <Button
          aria-label="dedup 다음 페이지"
          disabled={!hasNextPage || reviews.isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={goNext}
        >
          다음
        </Button>
        <Button
          aria-label="dedup 마지막 페이지"
          disabled={totalPages === null || !hasNextPage || reviews.isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={goLast}
        >
          마지막 페이지
        </Button>
      </div>
    </nav>
  );
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
          <div className="space-y-1 font-mono text-xs">
            <div>total {formatScore(row.original.total_score)}</div>
            <div>name {formatScore(row.original.name_score)}</div>
            <div>distance {formatScore(row.original.spatial_score)}</div>
          </div>
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
          <span className="font-mono">{formatDistance(row.original.distance_m)}</span>
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
    [decide, decision.isPending, merge, mergeKey],
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

        <section className="rounded-lg border bg-background p-4">
          <div className="grid gap-3 lg:grid-cols-[minmax(12rem,1fr)_auto_auto_minmax(10rem,14rem)_minmax(10rem,14rem)_minmax(8rem,12rem)_auto_auto]">
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                aria-label="dedup search"
                className="pl-8"
                placeholder="feature id, name"
                value={q}
                onChange={(event) => {
                  setQ(event.target.value);
                  resetPage();
                }}
              />
            </div>
            <NativeSelect
              aria-label="dedup status"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value as DedupStatus | "all");
                resetPage();
              }}
            >
              {statuses.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="dedup kind"
              value={kind}
              onChange={(event) => {
                setKind(event.target.value as DedupKindFilter);
                resetPage();
              }}
            >
              <NativeSelectOption value="all">all kinds</NativeSelectOption>
              {DEDUP_KINDS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Input
              aria-label="dedup provider"
              placeholder="provider"
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value);
                resetPage();
              }}
            />
            <Input
              aria-label="dedup dataset"
              placeholder="dataset"
              value={datasetKey}
              onChange={(event) => {
                setDatasetKey(event.target.value);
                resetPage();
              }}
            />
            <Input
              aria-label="dedup category"
              placeholder="category"
              value={category}
              onChange={(event) => {
                setCategory(event.target.value);
                resetPage();
              }}
            />
            <NativeSelect
              aria-label="dedup score filter"
              value={scoreFilter}
              onChange={(event) => {
                setScoreFilter(event.target.value as ScoreFilter);
                resetPage();
              }}
            >
              {SCORE_FILTERS.map((item) => (
                <NativeSelectOption key={item.value} value={item.value}>
                  {item.label}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="dedup page size"
              value={String(pageSize)}
              onChange={(event) => {
                setPageSize(Number(event.target.value) as typeof pageSize);
                resetPage();
              }}
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
        </section>

        {renderPagination("top")}

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

        {renderPagination("bottom")}
      </div>
    </AdminShell>
  );
}

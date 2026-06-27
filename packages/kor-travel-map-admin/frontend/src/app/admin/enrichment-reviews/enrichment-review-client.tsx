"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { CheckIcon, MapIcon, RefreshCwIcon, SearchIcon, XIcon } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

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
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { formatDateTime, shortId } from "@/lib/format";

const statuses: Array<EnrichmentStatus | "all"> = [
  "pending",
  "accepted",
  "rejected",
  "ignored",
  "all",
];

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200] as const;
const SCORE_FILTERS = [
  { value: "all", label: "score all" },
  { value: "high", label: "score >= 90", min: 90 },
  { value: "middle", label: "score 70-90", min: 70, max: 90 },
  { value: "low", label: "score < 70", max: 70 },
] as const;
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

type ScoreFilter = (typeof SCORE_FILTERS)[number]["value"];

function scoreBounds(value: ScoreFilter): { min?: number; max?: number } {
  const found = SCORE_FILTERS.find((item) => item.value === value);
  return {
    min: found && "min" in found ? found.min : undefined,
    max: found && "max" in found ? found.max : undefined,
  };
}

function formatScore(value: number | null | undefined): string {
  return typeof value === "number" ? value.toFixed(1) : "-";
}

function formatDistance(value: number | null | undefined): string {
  if (typeof value !== "number") return "-";
  if (value >= 1000) return `${(value / 1000).toFixed(2)}km`;
  return `${value.toFixed(1)}m`;
}

function formatDateOnly(value: string | null | undefined): string {
  if (!value) return "-";
  if (/^\d{8}$/.test(value)) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return value;
}

function formatPeriod(
  start: string | null | undefined,
  end: string | null | undefined,
): string {
  const left = formatDateOnly(start);
  const right = formatDateOnly(end);
  if (left === "-" && right === "-") return "-";
  return `${left} ~ ${right}`;
}

function formatCount(value: number | null | undefined): string {
  return typeof value === "number" ? value.toLocaleString("ko-KR") : "-";
}

export function EnrichmentReviewClient() {
  const [q, setQ] = useState("");
  const [provider, setProvider] = useState("");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");
  const [status, setStatus] = useState<EnrichmentStatus | "all">("pending");
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);
  const [pageIndex, setPageIndex] = useState(1);
  const [mapReviewId, setMapReviewId] = useState<string | null>(null);
  const deferredQ = useDeferredValue(q.trim());
  const deferredProvider = useDeferredValue(provider.trim());
  const bounds = scoreBounds(scoreFilter);
  const reviewParams = useMemo(
    () => ({
      status: status === "all" ? undefined : [status],
      provider: deferredProvider.length > 0 ? [deferredProvider] : undefined,
      min_score: bounds.min,
      max_score: bounds.max,
      q: deferredQ.length > 0 ? deferredQ : undefined,
      page_size: pageSize,
      page: pageIndex,
    }),
    [
      bounds.max,
      bounds.min,
      deferredProvider,
      deferredQ,
      pageIndex,
      pageSize,
      status,
    ],
  );
  const reviews = useEnrichmentReviews(reviewParams);
  const decision = useEnrichmentDecisionMutation();

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
    setPageIndex(1); // 필터 바뀌면 1페이지로.
    setMapReviewId(null);
  };
  const changeStatus = (value: EnrichmentStatus | "all") => {
    setStatus(value);
    resetPage();
  };
  const goFirst = () => {
    resetPage();
  };
  const goLast = () => {
    if (totalPages !== null) {
      setPageIndex(totalPages);
      setMapReviewId(null);
    }
  };
  const goNext = () => {
    if (!hasNextPage) return;
    setPageIndex((current) =>
      totalPages === null ? current + 1 : Math.min(totalPages, current + 1),
    );
    setMapReviewId(null);
  };
  const goPrev = () => {
    setPageIndex((current) => Math.max(1, current - 1));
    setMapReviewId(null);
  };

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

  const mapReview = items.find((item) => item.review_id === mapReviewId) ?? null;
  const renderPagination = (placement: "top" | "bottom") => (
    <nav
      aria-label={`enrichment pagination ${placement}`}
      className="flex flex-col gap-2 rounded-lg border bg-background px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
    >
      <span className="text-sm text-muted-foreground">
        페이지 {pageIndex} / {totalPages ?? "-"} · 총 {formatCount(totalItems)}건
        · 현재 {formatCount(items.length)}건
      </span>
      <div className="flex flex-wrap gap-1">
        <Button
          aria-label="첫 페이지"
          disabled={!hasPreviousPage || reviews.isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={goFirst}
        >
          첫 페이지
        </Button>
        <Button
          aria-label="이전 페이지"
          disabled={!hasPreviousPage || reviews.isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={goPrev}
        >
          이전
        </Button>
        <Button
          aria-label="다음 페이지"
          disabled={!hasNextPage || reviews.isFetching}
          size="sm"
          type="button"
          variant="outline"
          onClick={goNext}
        >
          다음
        </Button>
        <Button
          aria-label="마지막 페이지"
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
        // keyset cursor 목록(next_cursor) — 서버 정렬 유지, client 정렬 끔(#502).
        enableSorting: false,
        cell: ({ row }) => (
          <div className="space-y-1 font-mono text-xs">
            <div>name {formatScore(row.original.name_score)}</div>
            <div>distance {formatScore(row.original.spatial_score)}</div>
          </div>
        ),
      },
      {
        accessorKey: "distance_m",
        header: "distance",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono">
            {formatDistance(row.original.distance_m)}
          </span>
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
            <div className="text-xs text-muted-foreground">
              {formatPeriod(
                row.original.target_start_date,
                row.original.target_end_date,
              )}
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
            <div className="text-xs text-muted-foreground">
              {formatPeriod(
                row.original.source_start_date,
                row.original.source_end_date,
              )}
            </div>
          </>
        ),
      },
      {
        accessorKey: "status",
        header: "status",
        enableSorting: false,
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "created_at",
        header: "created",
        enableSorting: false,
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
          const hasMapCoords =
            typeof item.target_lon === "number" &&
            typeof item.target_lat === "number" &&
            typeof item.source_lon === "number" &&
            typeof item.source_lat === "number";
          return item.status === "pending" ? (
            <div className="flex flex-wrap gap-1">
              <Button
                disabled={!hasMapCoords}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => setMapReviewId(item.review_id)}
              >
                <MapIcon data-icon="inline-start" />
                지도
              </Button>
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
            <div className="flex flex-wrap items-center gap-1">
              <Button
                disabled={!hasMapCoords}
                size="sm"
                type="button"
                variant="outline"
                onClick={() => setMapReviewId(item.review_id)}
              >
                <MapIcon data-icon="inline-start" />
                지도
              </Button>
              <span className="text-sm text-muted-foreground">완료</span>
            </div>
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

        <section className="rounded-lg border bg-background p-4">
          <div className="grid gap-3 md:grid-cols-[minmax(12rem,1fr)_auto_minmax(12rem,16rem)_auto_auto]">
            <div className="relative">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                aria-label="enrichment search"
                className="pl-8"
                placeholder="review, target, source"
                value={q}
                onChange={(event) => {
                  setQ(event.target.value);
                  resetPage();
                }}
              />
            </div>
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
            <Input
              aria-label="enrichment provider"
              placeholder="source provider"
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value);
                resetPage();
              }}
            />
            <NativeSelect
              aria-label="enrichment score filter"
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
              aria-label="enrichment page size"
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

        {mapReview &&
        typeof mapReview.target_lon === "number" &&
        typeof mapReview.target_lat === "number" &&
        typeof mapReview.source_lon === "number" &&
        typeof mapReview.source_lat === "number" ? (
          <section
            aria-label="enrichment coordinate map"
            className="rounded-lg border bg-background"
          >
            <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
              <div>
                <div className="font-medium">좌표 비교</div>
                <div className="text-sm text-muted-foreground">
                  {formatDistance(mapReview.distance_m)} · datagokr / visitkorea
                </div>
              </div>
              <Button
                size="sm"
                type="button"
                variant="ghost"
                onClick={() => setMapReviewId(null)}
              >
                닫기
              </Button>
            </div>
            <div className="grid gap-0 lg:grid-cols-[minmax(0,1fr)_18rem]">
              <div className="relative h-80 min-h-72 overflow-hidden">
                <VWorldMapView
                  apiKey={VWORLD_KEY}
                  center={[
                    (mapReview.target_lon + mapReview.source_lon) / 2,
                    (mapReview.target_lat + mapReview.source_lat) / 2,
                  ]}
                  className="absolute inset-0 h-full w-full"
                  key={mapReview.review_id}
                  navigation
                  scale
                  testId="enrichment-review-map"
                  zoom={14}
                >
                  <VWorldMarker
                    lngLat={[mapReview.target_lon, mapReview.target_lat]}
                    markerColor="#2563eb"
                    selected
                    title={`datagokr: ${mapReview.target_name}`}
                  />
                  <VWorldMarker
                    lngLat={[mapReview.source_lon, mapReview.source_lat]}
                    markerColor="#dc2626"
                    title={`visitkorea: ${mapReview.source_name}`}
                  />
                </VWorldMapView>
              </div>
              <div className="space-y-3 border-t p-4 text-sm lg:border-l lg:border-t-0">
                <div>
                  <div className="font-medium text-blue-700">datagokr</div>
                  <div>{mapReview.target_name}</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {mapReview.target_lon.toFixed(6)},{" "}
                    {mapReview.target_lat.toFixed(6)}
                  </div>
                </div>
                <div>
                  <div className="font-medium text-red-700">visitkorea</div>
                  <div>{mapReview.source_name}</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {mapReview.source_lon.toFixed(6)},{" "}
                    {mapReview.source_lat.toFixed(6)}
                  </div>
                </div>
              </div>
            </div>
          </section>
        ) : null}

        {renderPagination("top")}

        <DataTable
          columns={columns}
          data={items}
          getRowId={(row) => row.review_id}
          isLoading={reviews.isLoading}
          emptyMessage="enrichment review가 없습니다."
          containerClassName="overflow-auto rounded-lg border bg-background"
        />

        {renderPagination("bottom")}
      </div>
    </AdminShell>
  );
}

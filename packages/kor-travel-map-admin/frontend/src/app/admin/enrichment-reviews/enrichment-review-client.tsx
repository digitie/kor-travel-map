"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  CheckIcon,
  EyeIcon,
  RefreshCwIcon,
  SearchIcon,
  XIcon,
} from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import {
  type EnrichmentDecision,
  type EnrichmentReviewDetailResponse,
  type EnrichmentStatus,
  useEnrichmentDecisionMutation,
  useEnrichmentReviewDetail,
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

type EnrichmentReviewDetail = EnrichmentReviewDetailResponse["data"];
type EnrichmentDetailSource = EnrichmentReviewDetail["default_detail_source"];

function formatMaybe(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return JSON.stringify(value);
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-52 overflow-auto rounded-md bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  );
}

function DetailMetric({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="break-words text-sm">{formatMaybe(value)}</dd>
    </div>
  );
}

function EnrichmentDetailDialog({
  detail,
  error,
  isLoading,
  isPending,
  onAccept,
  onClose,
  onSelectDetailSource,
  selectedDetailSource,
}: {
  detail: EnrichmentReviewDetail | undefined;
  error: Error | null;
  isLoading: boolean;
  isPending: boolean;
  onAccept: () => void;
  onClose: () => void;
  onSelectDetailSource: (value: EnrichmentDetailSource) => void;
  selectedDetailSource: EnrichmentDetailSource | null;
}) {
  const target = detail?.target;
  const source = detail?.source;
  const hasMap =
    typeof target?.lon === "number" &&
    typeof target.lat === "number" &&
    typeof source?.raw_longitude === "number" &&
    typeof source.raw_latitude === "number";
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-auto bg-black/45 p-4">
      <div
        aria-label="enrichment review detail"
        aria-modal="true"
        className="w-full max-w-6xl rounded-lg border bg-background shadow-xl"
        role="dialog"
      >
        <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold">Enrichment 상세 비교</h2>
            <div className="text-sm text-muted-foreground">
              {detail ? `${shortId(detail.review_id)} · ${formatDistance(detail.distance_m)}` : "loading"}
            </div>
          </div>
          <Button size="sm" type="button" variant="ghost" onClick={onClose}>
            닫기
          </Button>
        </div>
        <div className="space-y-4 p-4">
          {isLoading ? (
            <div className="text-sm text-muted-foreground">불러오는 중</div>
          ) : error ? (
            <Alert variant="destructive">
              <AlertTitle>상세 조회 실패</AlertTitle>
              <AlertDescription>{error.message}</AlertDescription>
            </Alert>
          ) : detail && target && source ? (
            <>
              <div className="flex flex-col gap-3 rounded-lg border bg-muted/40 p-3 lg:flex-row lg:items-center lg:justify-between">
                <dl className="grid flex-1 gap-3 sm:grid-cols-4">
                  <DetailMetric label="name" value={formatScore(detail.name_score)} />
                  <DetailMetric label="distance score" value={formatScore(detail.spatial_score)} />
                  <DetailMetric label="distance" value={formatDistance(detail.distance_m)} />
                  <DetailMetric
                    label="audit default"
                    value={detail.default_detail_source}
                  />
                </dl>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="sr-only" id="enrichment-detail-source-note">
                    선택값은 accept 적용 데이터 변경 없이 decision reason에 기록됩니다.
                  </span>
                  <NativeSelect
                    aria-describedby="enrichment-detail-source-note"
                    aria-label="enrichment detail source audit note"
                    title="선택값은 적용 데이터 변경 없이 decision reason에 기록됩니다."
                    value={selectedDetailSource ?? detail.default_detail_source}
                    onChange={(event) =>
                      onSelectDetailSource(
                        event.target.value as EnrichmentDetailSource,
                      )
                    }
                  >
                    <NativeSelectOption
                      disabled={!detail.target_detail_available}
                      value="target"
                    >
                      기록: 정리된 datagokr
                    </NativeSelectOption>
                    <NativeSelectOption value="visitkorea">
                      기록: visitkorea
                    </NativeSelectOption>
                  </NativeSelect>
                  <Button
                    disabled={detail.status !== "pending" || isPending}
                    size="sm"
                    type="button"
                    variant="default"
                    onClick={onAccept}
                  >
                    <CheckIcon data-icon="inline-start" />
                    accept
                  </Button>
                </div>
              </div>
              {hasMap ? (
                <section className="overflow-hidden rounded-lg border">
                  <div className="border-b px-4 py-2 text-sm font-medium">
                    위치 비교
                  </div>
                  <div className="relative h-80 min-h-72">
                    <VWorldMapView
                      apiKey={VWORLD_KEY}
                      center={[
                        ((target.lon ?? 0) + (source.raw_longitude ?? 0)) / 2,
                        ((target.lat ?? 0) + (source.raw_latitude ?? 0)) / 2,
                      ]}
                      className="absolute inset-0 h-full w-full"
                      key={detail.review_id}
                      navigation
                      scale
                      testId="enrichment-detail-map"
                      zoom={14}
                    >
                      <VWorldMarker
                        lngLat={[target.lon ?? 0, target.lat ?? 0]}
                        markerColor="#2563eb"
                        selected
                        title={`datagokr: ${target.name}`}
                      />
                      <VWorldMarker
                        lngLat={[source.raw_longitude ?? 0, source.raw_latitude ?? 0]}
                        markerColor="#dc2626"
                        title={`visitkorea: ${source.raw_name ?? detail.source_name}`}
                      />
                    </VWorldMapView>
                  </div>
                </section>
              ) : null}
              <div className="grid gap-4 lg:grid-cols-2">
                <section className="min-w-0 rounded-lg border bg-background p-4">
                  <div className="mb-3">
                    <div className="text-xs font-medium text-blue-700">
                      1차 datagokr
                    </div>
                    <h3 className="break-words text-base font-semibold">
                      {target.name}
                    </h3>
                    <div className="break-all font-mono text-xs text-muted-foreground">
                      {target.feature_id}
                    </div>
                  </div>
                  <dl className="grid gap-3 sm:grid-cols-2">
                    <DetailMetric label="kind" value={target.kind} />
                    <DetailMetric label="category" value={target.category} />
                    <DetailMetric
                      label="period"
                      value={formatPeriod(
                        detail.target_start_date,
                        detail.target_end_date,
                      )}
                    />
                    <DetailMetric label="status" value={target.status} />
                    <DetailMetric label="lon" value={target.lon?.toFixed(6)} />
                    <DetailMetric label="lat" value={target.lat?.toFixed(6)} />
                  </dl>
                  <div className="mt-4 space-y-3">
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">
                        detail
                      </div>
                      <JsonBlock value={target.detail} />
                    </div>
                    <div>
                      <div className="mb-1 text-xs font-medium text-muted-foreground">
                        address
                      </div>
                      <JsonBlock value={target.address} />
                    </div>
                  </div>
                </section>
                <section className="min-w-0 rounded-lg border bg-background p-4">
                  <div className="mb-3">
                    <div className="text-xs font-medium text-red-700">
                      2차 visitkorea
                    </div>
                    <h3 className="break-words text-base font-semibold">
                      {source.raw_name ?? detail.source_name}
                    </h3>
                    <div className="break-all font-mono text-xs text-muted-foreground">
                      {source.provider} · {source.source_entity_id}
                    </div>
                  </div>
                  <dl className="grid gap-3 sm:grid-cols-2">
                    <DetailMetric label="dataset" value={source.dataset_key} />
                    <DetailMetric
                      label="period"
                      value={formatPeriod(
                        detail.source_start_date,
                        detail.source_end_date,
                      )}
                    />
                    <DetailMetric
                      label="lon"
                      value={source.raw_longitude?.toFixed(6)}
                    />
                    <DetailMetric
                      label="lat"
                      value={source.raw_latitude?.toFixed(6)}
                    />
                    <DetailMetric label="address" value={source.raw_address} />
                    <DetailMetric label="record" value={source.source_record_key} />
                  </dl>
                  <div className="mt-4">
                    <div className="mb-1 text-xs font-medium text-muted-foreground">
                      raw_data
                    </div>
                    <JsonBlock value={source.raw_data} />
                  </div>
                </section>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function EnrichmentReviewClient() {
  const [q, setQ] = useState("");
  const [provider, setProvider] = useState("");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");
  const [status, setStatus] = useState<EnrichmentStatus | "all">("pending");
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);
  const [pageIndex, setPageIndex] = useState(1);
  const [detailReviewId, setDetailReviewId] = useState<string | null>(null);
  const [selectedDetailSource, setSelectedDetailSource] =
    useState<EnrichmentDetailSource | null>(null);
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
  const detail = useEnrichmentReviewDetail(detailReviewId);
  const decision = useEnrichmentDecisionMutation();

  const items = reviews.data?.data.items ?? [];
  const totalItems = reviews.data?.meta.page?.total ?? null;
  const totalPages =
    typeof totalItems === "number"
      ? Math.max(1, Math.ceil(totalItems / pageSize))
      : null;
  const hasNextPage = totalPages !== null && pageIndex < totalPages;
  const hasPreviousPage = pageIndex > 1;

  const resetPage = () => {
    setPageIndex(1); // 필터 바뀌면 1페이지로.
    setDetailReviewId(null);
    setSelectedDetailSource(null);
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
      setDetailReviewId(null);
      setSelectedDetailSource(null);
    }
  };
  const goNext = () => {
    if (!hasNextPage) return;
    setPageIndex((current) =>
      totalPages === null ? current + 1 : Math.min(totalPages, current + 1),
    );
    setDetailReviewId(null);
    setSelectedDetailSource(null);
  };
  const goPrev = () => {
    setPageIndex((current) => Math.max(1, current - 1));
    setDetailReviewId(null);
    setSelectedDetailSource(null);
  };

  const decide = (
    reviewId: string,
    value: EnrichmentDecision,
    detailSource?: EnrichmentDetailSource | null,
  ) => {
    decision.mutate({
      reviewKey: reviewId,
      body: {
        decision: value,
        decision_reason: `admin-ui ${value}`,
        selected_detail_source: detailSource ?? undefined,
        reviewed_by: "local-admin",
      },
    });
  };

  const openDetail = (reviewId: string) => {
    setDetailReviewId(reviewId);
    setSelectedDetailSource(null);
  };

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
        // 서버 page 목록 — 서버 정렬 유지, client 정렬 끔(#502).
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
          return item.status === "pending" ? (
            <div
              className="flex flex-wrap gap-1"
              onClick={(event) => event.stopPropagation()}
            >
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={() => openDetail(item.review_id)}
              >
                <EyeIcon data-icon="inline-start" />
                detail
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
            <div
              className="flex flex-wrap items-center gap-1"
              onClick={(event) => event.stopPropagation()}
            >
              <Button
                size="sm"
                type="button"
                variant="outline"
                onClick={() => openDetail(item.review_id)}
              >
                <EyeIcon data-icon="inline-start" />
                detail
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
      description="축제 enrichment 매칭(visitkorea 2차 → datagokr 1차)을 운영자가 검토합니다. accept하면 1차 축제에 visitkorea source가 enrichment로 연결되고, 상세 source 선택값은 decision reason에 기록됩니다."
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

        {detailReviewId ? (
          <EnrichmentDetailDialog
            detail={detail.data?.data}
            error={detail.error ?? null}
            isLoading={detail.isLoading}
            isPending={decision.isPending}
            selectedDetailSource={selectedDetailSource}
            onAccept={() =>
              decide(
                detailReviewId,
                "accepted",
                selectedDetailSource ??
                  detail.data?.data.default_detail_source ??
                  "visitkorea",
              )
            }
            onClose={() => {
              setDetailReviewId(null);
              setSelectedDetailSource(null);
            }}
            onSelectDetailSource={setSelectedDetailSource}
          />
        ) : null}

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

        {renderPagination("top")}

        <DataTable
          columns={columns}
          data={items}
          getRowId={(row) => row.review_id}
          isLoading={reviews.isLoading}
          emptyMessage="enrichment review가 없습니다."
          containerClassName="overflow-auto rounded-lg border bg-background"
          onRowClick={(row) => openDetail(row.review_id)}
          isRowActive={(row) => row.review_id === detailReviewId}
        />

        {renderPagination("bottom")}
      </div>
    </AdminShell>
  );
}

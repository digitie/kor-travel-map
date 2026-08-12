"use client";

import {
  AlertTriangleIcon,
  EyeIcon,
  ExternalLinkIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  XCircleIcon,
} from "lucide-react";
import {
  type ColumnDef,
  type OnChangeFn,
  type SortingState,
} from "@tanstack/react-table";
import Link from "next/link";
import { useCallback, useDeferredValue, useMemo, useState } from "react";

import {
  FEATURE_KINDS,
  FEATURE_LIFECYCLE_STATES,
  FEATURE_PUBLICATION_STATES,
  FEATURE_QUALITY_STATES,
  fetchAdminFeatureCorrectionBasis,
  useAdminFeatures,
  useAdminFeatureDetail,
  usePatchAdminFeatureStateMutation,
  type AdminFeatureDetailData,
  type AdminFeatureRecord,
  type AdminFeatureSort,
  type FeatureKind,
  type FeatureLifecycleState,
  type FeaturePublicationState,
  type FeatureQualityState,
  type SortOrder,
} from "@/api/features";
import { AdminShell } from "@/components/admin-shell";
import { CursorPager } from "@/components/pagination-bar";
import { useConfirm } from "@/components/confirm-dialog";
import { EntityLink } from "@/components/entity-link";
import { FeatureAssociations } from "@/components/feature-associations";
import { FeatureKindDetailPanel } from "@/components/feature-kind-detail-panel";
import { FeatureStateBadges } from "@/components/feature-state-badges";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { VWorldMapView, VWorldMarker } from "@/components/vworld-map-view";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;
const SORT_OPTIONS: AdminFeatureSort[] = [
  "name",
  "updated_at",
  "created_at",
  "kind",
  "provider",
  "issue_count",
];
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY;

type HasIssueFilter = "all" | "yes" | "no";
type AxisFilter<T extends string> = T | "all";

function parseProviderDatasetId(value: string | undefined): number | null {
  if (!value || !/^\d+$/.test(value)) return null;
  const providerDatasetId = Number(value);
  return Number.isSafeInteger(providerDatasetId) && providerDatasetId > 0
    ? providerDatasetId
    : null;
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function coordLabel(feature: AdminFeatureRecord): string {
  if (typeof feature.lon === "number" && typeof feature.lat === "number") {
    return `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`;
  }
  return "없음";
}

function featureDetailHref(featureId: string): string {
  return `/features/${encodeURIComponent(featureId)}`;
}

function FeatureLocationMap({
  feature,
}: {
  feature: AdminFeatureDetailData["feature"] | null | undefined;
}) {
  const hasCoord =
    typeof feature?.lon === "number" && typeof feature?.lat === "number";
  if (!hasCoord) {
    return (
      <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        좌표가 없어 지도 marker를 표시할 수 없습니다.
      </div>
    );
  }

  return (
    <div className="relative h-52 overflow-hidden rounded-md border">
      <VWorldMapView
        apiKey={VWORLD_KEY}
        center={[feature.lon as number, feature.lat as number]}
        className="absolute inset-0 h-full w-full"
        key={feature.feature_id}
        navigation
        scale
        zoom={14}
      >
        <VWorldMarker
          lngLat={[feature.lon as number, feature.lat as number]}
          markerColor="#2563eb"
          selected
          title={feature.name}
        />
      </VWorldMapView>
    </div>
  );
}

function FeatureDetailInspector({ featureId }: { featureId: string | null }) {
  const detail = useAdminFeatureDetail(featureId);
  const data = detail.data?.data;
  const feature = data?.feature;

  if (!featureId) {
    return (
      <div className="rounded-lg border bg-background p-5 text-sm text-muted-foreground">
        table에서 feature를 선택하면 상세와 kind별 패널을 확인할 수 있습니다.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border bg-background">
        {detail.isLoading ? <Skeleton className="m-4 h-48" /> : null}
        {detail.isError ? (
          <Alert className="m-4" variant="destructive">
            <AlertTitle>feature 상세 조회 실패</AlertTitle>
            <AlertDescription>{detail.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {data && feature ? (
          <div className="flex flex-col gap-4 p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="text-lg font-semibold">{feature.name}</div>
                <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
                  {featureId}
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <FeatureStateBadges
                    lifecycleState={feature.lifecycle_state}
                    publicationState={feature.publication_state}
                    qualityState={feature.quality_state}
                  />
                  <Badge variant="outline">{feature.kind}</Badge>
                  <Badge variant="outline">{feature.category}</Badge>
                </div>
              </div>
              <Link
                className={cn(
                  buttonVariants({ variant: "outline", size: "sm" }),
                )}
                href={`/admin/features/change-requests?action=update&feature_id=${encodeURIComponent(featureId)}`}
              >
                <PencilIcon data-icon="inline-start" />
                편집
              </Link>
            </div>
            <FeatureLocationMap feature={feature} />
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted-foreground">coord</dt>
              <dd className="font-mono">
                {typeof feature.lon === "number" &&
                typeof feature.lat === "number"
                  ? `${feature.lon.toFixed(5)}, ${feature.lat.toFixed(5)}`
                  : "없음"}
              </dd>
              <dt className="text-muted-foreground">sigungu</dt>
              <dd>{feature.sigungu_code ?? "없음"}</dd>
            </dl>
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                address
              </summary>
              <JsonBlock value={feature.address} />
            </details>
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                detail
              </summary>
              <JsonBlock value={feature.detail} />
            </details>
            <FeatureAssociations
              compact
              curations={data.curations}
              observations={data.sources}
            />
          </div>
        ) : null}
      </div>
      <FeatureKindDetailPanel compact feature={feature} featureId={featureId} />
    </div>
  );
}

function useAdminFeaturesClientController({
  initialQ,
  initialKind,
  initialLifecycleState,
  initialPublicationState,
  initialQualityState,
  initialProviderDatasetId,
  initialHasIssue,
}: {
  initialQ?: string;
  initialKind?: string;
  initialLifecycleState?: string;
  initialPublicationState?: string;
  initialQualityState?: string;
  initialProviderDatasetId?: string;
  initialHasIssue?: string;
} = {}) {
  const [q, setQ] = useState(initialQ ?? "");
  const deferredQ = useDeferredValue(q.trim());
  const [kind, setKind] = useState<FeatureKind | "all">(() =>
    initialKind && (FEATURE_KINDS as readonly string[]).includes(initialKind)
      ? (initialKind as FeatureKind)
      : "all",
  );
  const [lifecycleState, setLifecycleState] = useState<
    AxisFilter<FeatureLifecycleState>
  >(() =>
    initialLifecycleState &&
    ([...FEATURE_LIFECYCLE_STATES, "all"] as string[]).includes(
      initialLifecycleState,
    )
      ? (initialLifecycleState as AxisFilter<FeatureLifecycleState>)
      : "all",
  );
  const [publicationState, setPublicationState] = useState<
    AxisFilter<FeaturePublicationState>
  >(() =>
    initialPublicationState &&
    ([...FEATURE_PUBLICATION_STATES, "all"] as string[]).includes(
      initialPublicationState,
    )
      ? (initialPublicationState as AxisFilter<FeaturePublicationState>)
      : "all",
  );
  const [qualityState, setQualityState] = useState<
    AxisFilter<FeatureQualityState>
  >(() =>
    initialQualityState &&
    ([...FEATURE_QUALITY_STATES, "all"] as string[]).includes(
      initialQualityState,
    )
      ? (initialQualityState as AxisFilter<FeatureQualityState>)
      : "all",
  );
  // retire의 **mutation 이전** 실패(correction basis fetch)를 담는다. mutation이
  // 시작되지 않으면 `stateMutation.isError`가 false로 남아 화면에 아무것도 뜨지 않는다.
  const [retireError, setRetireError] = useState<string | null>(null);
  const [hasIssue, setHasIssue] = useState<HasIssueFilter>(() =>
    initialHasIssue === "yes" || initialHasIssue === "no"
      ? initialHasIssue
      : "all",
  );
  const [providerDatasetId, setProviderDatasetId] = useState<number | null>(
    () => parseProviderDatasetId(initialProviderDatasetId),
  );
  const [sort, setSort] = useState<AdminFeatureSort>("name");
  const [order, setOrder] = useState<SortOrder>("asc");
  const [pageSize, setPageSize] =
    useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);
  const [cursor, setCursor] = useState<string | null>(null);
  const [pageIndex, setPageIndex] = useState(1);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(
    null,
  );

  const params = useMemo(
    () => ({
      q: deferredQ.length > 0 ? deferredQ : undefined,
      kind: kind === "all" ? undefined : [kind],
      lifecycle_state: lifecycleState === "all" ? undefined : [lifecycleState],
      publication_state:
        publicationState === "all" ? undefined : [publicationState],
      quality_state: qualityState === "all" ? undefined : [qualityState],
      has_issue: hasIssue === "all" ? undefined : hasIssue === "yes",
      provider_dataset_id: providerDatasetId ?? undefined,
      page_size: pageSize,
      cursor: cursor ?? undefined,
      sort,
      order,
    }),
    [
      cursor,
      deferredQ,
      hasIssue,
      kind,
      order,
      pageSize,
      providerDatasetId,
      sort,
      lifecycleState,
      publicationState,
      qualityState,
    ],
  );
  const features = useAdminFeatures(params);
  const stateMutation = usePatchAdminFeatureStateMutation();
  const confirm = useConfirm();
  const items = features.data?.data.items ?? [];
  const nextCursor = features.data?.meta.page?.next_cursor ?? null;
  const durationMs = features.data?.meta.duration_ms ?? 0;

  const resetCursor = () => {
    setCursor(null);
    setPageIndex(1);
  };
  const goFirstPage = () => {
    setCursor(null);
    setPageIndex(1);
  };
  const goNextPage = () => {
    if (!nextCursor) return;
    setCursor(nextCursor);
    setPageIndex((page) => page + 1);
  };
  const refresh = () => {
    void features.refetch();
  };

  const retireFeature = useCallback(
    async (feature: AdminFeatureRecord) => {
      if (feature.lifecycle_state === "retired") return;
      const ok = await confirm({
        title: `${feature.name} feature를 종료할까요?`,
        description: "provider 재적재로 다시 활성화되지 않도록 잠급니다.",
        confirmLabel: "종료",
        destructive: true,
      });
      if (!ok) return;
      setRetireError(null);
      // mutation **이전** 단계다. `fetchAdminFeatureCorrectionBasis`는 revision/detail
      // 3회 불일치나 4xx/5xx에서 reject하는데, 여기서 새어 나가면 mutation이 시작조차
      // 되지 않아 `stateMutation.isError`가 false로 남는다 — 운영자 입장에서는 버튼을
      // 눌렀는데 아무 일도, 아무 메시지도 없다. 실패를 화면의 같은 Alert로 올린다.
      let basis: Awaited<ReturnType<typeof fetchAdminFeatureCorrectionBasis>>;
      try {
        basis = await fetchAdminFeatureCorrectionBasis(feature.feature_id);
      } catch (error: unknown) {
        setRetireError(error instanceof Error ? error.message : String(error));
        return;
      }
      stateMutation.mutate({
        featureId: basis.featureId,
        entityTag: basis.entityTag,
        body: { action: "retire", reason_code: "admin_ui_retire" },
      });
    },
    [confirm, stateMutation],
  );

  // 서버 정렬(keyset cursor)이므로 sort/order state를 react-table SortingState로
  // 양방향 미러링한다. 기존 sort NativeSelect + asc/desc Button과 동일 state를 공유한다.
  const sorting = useMemo<SortingState>(
    () => [{ id: sort, desc: order === "desc" }],
    [sort, order],
  );
  const handleSortingChange: OnChangeFn<SortingState> = (updater) => {
    const next = typeof updater === "function" ? updater(sorting) : updater;
    const first = next[0];
    if (!first) return;
    setSort(first.id as AdminFeatureSort);
    setOrder(first.desc ? "desc" : "asc");
    resetCursor();
  };

  const columns = useMemo<ColumnDef<AdminFeatureRecord, unknown>[]>(
    () => [
      {
        id: "name",
        header: "feature",
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <>
              <div className="font-medium">{feature.name}</div>
              <div className="break-all font-mono text-xs text-muted-foreground">
                {shortId(feature.feature_id, 18)}
              </div>
            </>
          );
        },
      },
      {
        id: "kind_state",
        header: "종류/상태 축",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <>
              <div className="flex flex-wrap gap-1">
                <Badge variant="outline">{feature.kind}</Badge>
                <FeatureStateBadges
                  lifecycleState={feature.lifecycle_state}
                  publicationState={feature.publication_state}
                  qualityState={feature.quality_state}
                />
              </div>
              <div className="mt-1 font-mono text-xs text-muted-foreground">
                {feature.category}
              </div>
            </>
          );
        },
      },
      {
        id: "provider",
        header: "provider",
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <>
              <div>{feature.primary_provider ?? "-"}</div>
              <div className="text-xs text-muted-foreground">
                {feature.primary_dataset_key ?? "-"}
              </div>
            </>
          );
        },
      },
      {
        id: "issue_count",
        header: "이슈",
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <>
              {feature.issue_count > 0 ? (
                <EntityLink
                  id=""
                  kind="issue"
                  params={{ feature_id: feature.feature_id }}
                >
                  <Badge variant="destructive">{feature.issue_count}</Badge>
                </EntityLink>
              ) : (
                <Badge variant="outline">{feature.issue_count}</Badge>
              )}
              {feature.issues.slice(0, 2).map((issue) => (
                <div
                  className="mt-1 max-w-48 truncate text-xs text-muted-foreground"
                  key={issue.issue_id ?? issue.message}
                >
                  {issue.violation_type ?? "issue"} · {issue.message ?? "-"}
                </div>
              ))}
            </>
          );
        },
      },
      {
        id: "coord_address",
        header: "좌표/주소",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <>
              <div className="font-mono text-xs">{coordLabel(feature)}</div>
              <div className="mt-1 max-w-64 truncate text-xs text-muted-foreground">
                {feature.address_label || "-"}
              </div>
            </>
          );
        },
      },
      {
        id: "updated_at",
        header: "수정",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.updated_at)}
          </span>
        ),
      },
      {
        id: "actions",
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => {
          const feature = row.original;
          return (
            <div className="flex flex-wrap gap-1">
              <Link
                className={cn(
                  buttonVariants({ variant: "outline", size: "sm" }),
                )}
                href={featureDetailHref(feature.feature_id)}
                onClick={(event) => {
                  event.stopPropagation();
                }}
              >
                <ExternalLinkIcon data-icon="inline-start" />
                detail
              </Link>
              <Button
                size="sm"
                type="button"
                variant="ghost"
                onClick={(event) => {
                  event.stopPropagation();
                  setSelectedFeatureId(feature.feature_id);
                }}
              >
                <EyeIcon data-icon="inline-start" />
                preview
              </Button>
              <Button
                disabled={
                  stateMutation.isPending ||
                  feature.lifecycle_state === "retired"
                }
                size="sm"
                type="button"
                variant="ghost"
                onClick={(event) => {
                  event.stopPropagation();
                  void retireFeature(feature);
                }}
              >
                <XCircleIcon data-icon="inline-start" />
                retire
              </Button>
            </div>
          );
        },
      },
    ],
    [retireFeature, stateMutation.isPending],
  );

  return {
    columns,
    cursor,
    retireError,
    stateMutation,
    durationMs,
    features,
    goFirstPage,
    goNextPage,
    handleSortingChange,
    hasIssue,
    items,
    kind,
    nextCursor,
    order,
    pageIndex,
    pageSize,
    providerDatasetId,
    q,
    refresh,
    resetCursor,
    selectedFeatureId,
    setHasIssue,
    setKind,
    setOrder,
    setPageSize,
    setProviderDatasetId,
    setQ,
    setSelectedFeatureId,
    setSort,
    setLifecycleState,
    setPublicationState,
    setQualityState,
    sort,
    sorting,
    lifecycleState,
    publicationState,
    qualityState,
  };
}

function AdminFeaturesClientView({
  columns,
  cursor,
  retireError,
  stateMutation,
  durationMs,
  features,
  goFirstPage,
  goNextPage,
  handleSortingChange,
  hasIssue,
  items,
  kind,
  nextCursor,
  order,
  pageIndex,
  pageSize,
  providerDatasetId,
  q,
  refresh,
  resetCursor,
  selectedFeatureId,
  setHasIssue,
  setKind,
  setOrder,
  setPageSize,
  setProviderDatasetId,
  setQ,
  setSelectedFeatureId,
  setSort,
  setLifecycleState,
  setPublicationState,
  setQualityState,
  sort,
  sorting,
  lifecycleState,
  publicationState,
  qualityState,
}: ReturnType<typeof useAdminFeaturesClientController>) {
  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/new"
          >
            <PlusIcon data-icon="inline-start" />새 작성
          </Link>
          <Button
            disabled={features.isFetching}
            type="button"
            variant="outline"
            onClick={refresh}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
        </>
      }
      title="Feature 목록"
    >
      <div className="flex flex-col gap-4">
        {(features.isError || stateMutation.isError || retireError !== null) && (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>admin feature 처리 실패</AlertTitle>
            <AlertDescription>
              {features.error?.message ??
                stateMutation.error?.message ??
                retireError}
            </AlertDescription>
          </Alert>
        )}

        <section className="rounded-lg border bg-background p-3">
          <div className="flex gap-2 overflow-x-auto pb-1">
            <div className="relative w-72 shrink-0">
              <SearchIcon className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                aria-label="feature search"
                className="pl-8"
                placeholder="name, address, feature_id"
                value={q}
                onChange={(event) => {
                  setQ(event.target.value);
                  resetCursor();
                }}
              />
            </div>
            <NativeSelect
              aria-label="feature kind"
              className="w-36 shrink-0"
              value={kind}
              onChange={(event) => {
                setKind(event.target.value as FeatureKind | "all");
                resetCursor();
              }}
            >
              <NativeSelectOption value="all">all kinds</NativeSelectOption>
              {FEATURE_KINDS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="feature lifecycle state"
              className="w-36 shrink-0"
              value={lifecycleState}
              onChange={(event) => {
                setLifecycleState(
                  event.target.value as AxisFilter<FeatureLifecycleState>,
                );
                resetCursor();
              }}
            >
              <NativeSelectOption value="all">모든 수명</NativeSelectOption>
              {FEATURE_LIFECYCLE_STATES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="feature publication state"
              className="w-36 shrink-0"
              value={publicationState}
              onChange={(event) => {
                setPublicationState(
                  event.target.value as AxisFilter<FeaturePublicationState>,
                );
                resetCursor();
              }}
            >
              <NativeSelectOption value="all">모든 공개</NativeSelectOption>
              {FEATURE_PUBLICATION_STATES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="feature quality state"
              className="w-36 shrink-0"
              value={qualityState}
              onChange={(event) => {
                setQualityState(
                  event.target.value as AxisFilter<FeatureQualityState>,
                );
                resetCursor();
              }}
            >
              <NativeSelectOption value="all">모든 품질</NativeSelectOption>
              {FEATURE_QUALITY_STATES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="has issue"
              className="w-36 shrink-0"
              value={hasIssue}
              onChange={(event) => {
                setHasIssue(event.target.value as HasIssueFilter);
                resetCursor();
              }}
            >
              <NativeSelectOption value="all">issue all</NativeSelectOption>
              <NativeSelectOption value="yes">issue only</NativeSelectOption>
              <NativeSelectOption value="no">no issue</NativeSelectOption>
            </NativeSelect>
            <Input
              aria-label="feature provider dataset ID"
              className="w-52 shrink-0"
              inputMode="numeric"
              min={1}
              placeholder="provider dataset ID"
              type="number"
              value={providerDatasetId ?? ""}
              onChange={(event) => {
                setProviderDatasetId(
                  parseProviderDatasetId(event.target.value),
                );
                resetCursor();
              }}
            />
            <Link
              aria-label="데이터셋에서 선택"
              className={cn(
                buttonVariants({ variant: "outline", size: "sm" }),
                "shrink-0",
              )}
              href="/ops/datasets"
            >
              데이터셋에서 선택
            </Link>
            <NativeSelect
              aria-label="feature sort"
              className="w-48 shrink-0"
              value={sort}
              onChange={(event) => {
                setSort(event.target.value as AdminFeatureSort);
                resetCursor();
              }}
            >
              {SORT_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="feature page size"
              className="w-24 shrink-0"
              value={String(pageSize)}
              onChange={(event) => {
                setPageSize(Number(event.target.value) as typeof pageSize);
                resetCursor();
              }}
            >
              {PAGE_SIZE_OPTIONS.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Button
              className="shrink-0"
              size="sm"
              type="button"
              variant={order === "asc" ? "default" : "outline"}
              onClick={() => {
                setOrder("asc");
                resetCursor();
              }}
            >
              asc
            </Button>
            <Button
              className="shrink-0"
              size="sm"
              type="button"
              variant={order === "desc" ? "default" : "outline"}
              onClick={() => {
                setOrder("desc");
                resetCursor();
              }}
            >
              desc
            </Button>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_28rem]">
          <div className="min-w-0 rounded-lg border bg-background">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <div className="font-medium">Feature 목록</div>
                <Badge variant="outline">
                  {formatCount(items.length)} rows
                </Badge>
                <Badge variant="outline">page {formatCount(pageIndex)}</Badge>
                <Badge variant="outline">
                  page size {formatCount(pageSize)}
                </Badge>
                <Badge variant="outline">{durationMs}ms</Badge>
              </div>
              <CursorPager
                framed={false}
                hasNext={Boolean(nextCursor)}
                isFirst={cursor === null}
                isFetching={features.isFetching}
                onFirst={goFirstPage}
                onNext={goNextPage}
              />
            </div>
            <DataTable
              columns={columns}
              data={items}
              getRowId={(feature) => feature.feature_id}
              isLoading={features.isLoading}
              emptyMessage="feature가 없습니다."
              sorting={sorting}
              onSortingChange={handleSortingChange}
              manualSorting
              onRowClick={(feature) => setSelectedFeatureId(feature.feature_id)}
              isRowActive={(feature) =>
                selectedFeatureId === feature.feature_id
              }
              containerClassName="overflow-auto"
            />
          </div>

          <FeatureDetailInspector featureId={selectedFeatureId} />
        </section>
      </div>
    </AdminShell>
  );
}

export function AdminFeaturesClient({
  initialQ,
  initialKind,
  initialLifecycleState,
  initialPublicationState,
  initialQualityState,
  initialProviderDatasetId,
  initialHasIssue,
}: {
  initialQ?: string;
  initialKind?: string;
  initialLifecycleState?: string;
  initialPublicationState?: string;
  initialQualityState?: string;
  initialProviderDatasetId?: string;
  initialHasIssue?: string;
} = {}) {
  const controller = useAdminFeaturesClientController({
    initialQ,
    initialKind,
    initialLifecycleState,
    initialPublicationState,
    initialQualityState,
    initialProviderDatasetId,
    initialHasIssue,
  });
  return <AdminFeaturesClientView {...controller} />;
}

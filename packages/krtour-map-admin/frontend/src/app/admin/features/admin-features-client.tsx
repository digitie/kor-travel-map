"use client";

import {
  AlertTriangleIcon,
  EyeIcon,
  ExternalLinkIcon,
  PlusIcon,
  RefreshCwIcon,
  SearchIcon,
  XCircleIcon,
} from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useMemo, useState } from "react";

import {
  FEATURE_KINDS,
  useAdminFeatures,
  useDeactivateAdminFeatureMutation,
  useFeatureDetail,
  type AdminFeatureRecord,
  type AdminFeatureSort,
  type FeatureKind,
  type SortOrder,
} from "@/api/features";
import { AdminShell } from "@/components/admin-shell";
import { FeatureWeatherPanel } from "@/components/feature-weather-panel";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Input } from "@/components/ui/input";
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
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

const FEATURE_STATUSES = [
  "active",
  "inactive",
  "hidden",
  "broken",
  "deleted",
] as const;
const PAGE_SIZE_OPTIONS = [25, 50, 100, 200, 500] as const;
const SORT_OPTIONS: AdminFeatureSort[] = [
  "name",
  "updated_at",
  "created_at",
  "kind",
  "status",
  "provider",
  "issue_count",
];

type FeatureStatusFilter = (typeof FEATURE_STATUSES)[number] | "all";
type HasIssueFilter = "all" | "yes" | "no";

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

function FeatureDetailInspector({ featureId }: { featureId: string | null }) {
  const detail = useFeatureDetail(featureId);

  if (!featureId) {
    return (
      <div className="rounded-lg border bg-background p-5 text-sm text-muted-foreground">
        table에서 feature를 선택하면 상세와 weather panel을 확인할 수 있습니다.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border bg-background">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
          <div className="min-w-0">
            <div className="font-medium">Feature detail</div>
            <div className="break-all font-mono text-xs text-muted-foreground">
              {featureId}
            </div>
          </div>
          <Link
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            href={featureDetailHref(featureId)}
          >
            <ExternalLinkIcon data-icon="inline-start" />
            전체 상세
          </Link>
        </div>
        {detail.isLoading ? <Skeleton className="m-4 h-48" /> : null}
        {detail.isError ? (
          <Alert className="m-4" variant="destructive">
            <AlertTitle>feature 상세 조회 실패</AlertTitle>
            <AlertDescription>{detail.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {detail.data ? (
          <div className="flex flex-col gap-4 p-4">
            <div>
              <div className="text-lg font-semibold">{detail.data.name}</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <StatusBadge status={detail.data.status} />
                <Badge variant="outline">{detail.data.kind}</Badge>
                <Badge variant="outline">{detail.data.category}</Badge>
              </div>
            </div>
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-sm">
              <dt className="text-muted-foreground">coord</dt>
              <dd className="font-mono">
                {typeof detail.data.lon === "number" &&
                typeof detail.data.lat === "number"
                  ? `${detail.data.lon.toFixed(5)}, ${detail.data.lat.toFixed(5)}`
                  : "없음"}
              </dd>
              <dt className="text-muted-foreground">sigungu</dt>
              <dd>{detail.data.sigungu_code ?? "없음"}</dd>
            </dl>
            <details>
              <summary className="cursor-pointer text-sm font-medium">address</summary>
              <JsonBlock value={detail.data.address} />
            </details>
            <details>
              <summary className="cursor-pointer text-sm font-medium">detail</summary>
              <JsonBlock value={detail.data.detail} />
            </details>
          </div>
        ) : null}
      </div>
      <FeatureWeatherPanel featureId={featureId} />
    </div>
  );
}

export function AdminFeaturesClient() {
  const [q, setQ] = useState("");
  const deferredQ = useDeferredValue(q.trim());
  const [kind, setKind] = useState<FeatureKind | "all">("all");
  const [status, setStatus] = useState<FeatureStatusFilter>("active");
  const [hasIssue, setHasIssue] = useState<HasIssueFilter>("all");
  const [sort, setSort] = useState<AdminFeatureSort>("name");
  const [order, setOrder] = useState<SortOrder>("asc");
  const [pageSize, setPageSize] = useState<(typeof PAGE_SIZE_OPTIONS)[number]>(50);
  const [cursor, setCursor] = useState<string | null>(null);
  const [selectedFeatureId, setSelectedFeatureId] = useState<string | null>(null);

  const params = useMemo(
    () => ({
      q: deferredQ.length > 0 ? deferredQ : undefined,
      kind: kind === "all" ? undefined : [kind],
      status:
        status === "all" ? Array.from(FEATURE_STATUSES) : [status],
      has_issue:
        hasIssue === "all" ? undefined : hasIssue === "yes",
      page_size: pageSize,
      cursor: cursor ?? undefined,
      sort,
      order,
    }),
    [cursor, deferredQ, hasIssue, kind, order, pageSize, sort, status],
  );
  const features = useAdminFeatures(params);
  const deactivate = useDeactivateAdminFeatureMutation();
  const items = features.data?.data.items ?? [];
  const nextCursor = features.data?.meta.page?.next_cursor ?? null;

  const resetCursor = () => setCursor(null);
  const refresh = () => {
    void features.refetch();
  };

  const deactivateFeature = (feature: AdminFeatureRecord) => {
    if (feature.status === "deleted") return;
    const ok = window.confirm(`${feature.name} feature를 비활성화할까요?`);
    if (!ok) return;
    deactivate.mutate({
      featureId: feature.feature_id,
      body: {
        operator: "local-admin",
        prevent_provider_reactivation: true,
        reason: "admin-ui deactivate",
      },
    });
  };

  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/admin/features/new"
          >
            <PlusIcon data-icon="inline-start" />
            새 작성
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
      description="운영자용 feature 목록, 상세, weather, 단건 비활성화 표면입니다."
      section="Admin"
      title="Admin features"
    >
      <div className="flex flex-col gap-4">
        {(features.isError || deactivate.isError) && (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>admin feature 처리 실패</AlertTitle>
            <AlertDescription>
              {features.error?.message ?? deactivate.error?.message}
            </AlertDescription>
          </Alert>
        )}

        <section className="rounded-lg border bg-background p-4">
          <div className="grid gap-3 md:grid-cols-[minmax(12rem,1fr)_auto_auto_auto_auto_auto]">
            <div className="relative">
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
              aria-label="feature status"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value as FeatureStatusFilter);
                resetCursor();
              }}
            >
              <NativeSelectOption value="all">all status</NativeSelectOption>
              {FEATURE_STATUSES.map((item) => (
                <NativeSelectOption key={item} value={item}>
                  {item}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="has issue"
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
            <NativeSelect
              aria-label="feature sort"
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
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
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
            <Badge variant="outline">
              {formatCount(items.length)} rows
            </Badge>
            <Badge variant="outline">
              {features.data?.meta.duration_ms ?? 0}ms
            </Badge>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_28rem]">
          <div className="min-w-0 rounded-lg border bg-background">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <div className="font-medium">Feature table</div>
                <div className="text-sm text-muted-foreground">
                  keyset cursor 기반 admin 목록
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  disabled={!cursor}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => setCursor(null)}
                >
                  첫 페이지
                </Button>
                <Button
                  disabled={!nextCursor}
                  size="sm"
                  type="button"
                  variant="outline"
                  onClick={() => setCursor(nextCursor)}
                >
                  다음
                </Button>
              </div>
            </div>
            {features.isLoading ? <Skeleton className="m-4 h-96" /> : null}
            <div className="overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>feature</TableHead>
                    <TableHead>kind/status</TableHead>
                    <TableHead>provider</TableHead>
                    <TableHead>issues</TableHead>
                    <TableHead>coord/address</TableHead>
                    <TableHead>updated</TableHead>
                    <TableHead>actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((feature) => (
                    <TableRow
                      className="cursor-pointer"
                      key={feature.feature_id}
                      data-state={
                        selectedFeatureId === feature.feature_id ? "selected" : undefined
                      }
                      onClick={() => setSelectedFeatureId(feature.feature_id)}
                    >
                      <TableCell>
                        <div className="font-medium">{feature.name}</div>
                        <div className="break-all font-mono text-xs text-muted-foreground">
                          {shortId(feature.feature_id, 18)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          <Badge variant="outline">{feature.kind}</Badge>
                          <StatusBadge status={feature.status} />
                        </div>
                        <div className="mt-1 font-mono text-xs text-muted-foreground">
                          {feature.category}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div>{feature.primary_provider ?? "-"}</div>
                        <div className="text-xs text-muted-foreground">
                          {feature.primary_dataset_key ?? "-"}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant={
                            feature.issue_count > 0 ? "destructive" : "outline"
                          }
                        >
                          {feature.issue_count}
                        </Badge>
                        {feature.issues.slice(0, 2).map((issue) => (
                          <div
                            className="mt-1 max-w-48 truncate text-xs text-muted-foreground"
                            key={issue.issue_id ?? issue.message}
                          >
                            {issue.violation_type ?? "issue"} ·{" "}
                            {issue.message ?? "-"}
                          </div>
                        ))}
                      </TableCell>
                      <TableCell>
                        <div className="font-mono text-xs">{coordLabel(feature)}</div>
                        <div className="mt-1 max-w-64 truncate text-xs text-muted-foreground">
                          {feature.address_label || "-"}
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(feature.updated_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          <Button
                            size="sm"
                            type="button"
                            variant="outline"
                            onClick={(event) => {
                              event.stopPropagation();
                              setSelectedFeatureId(feature.feature_id);
                            }}
                          >
                            <EyeIcon data-icon="inline-start" />
                            detail
                          </Button>
                          <Link
                            className={cn(
                              buttonVariants({ variant: "ghost", size: "sm" }),
                            )}
                            href={featureDetailHref(feature.feature_id)}
                            onClick={(event) => event.stopPropagation()}
                          >
                            <ExternalLinkIcon data-icon="inline-start" />
                            open
                          </Link>
                          <Button
                            disabled={
                              deactivate.isPending ||
                              feature.status === "inactive" ||
                              feature.status === "deleted"
                            }
                            size="sm"
                            type="button"
                            variant="ghost"
                            onClick={(event) => {
                              event.stopPropagation();
                              deactivateFeature(feature);
                            }}
                          >
                            <XCircleIcon data-icon="inline-start" />
                            deactivate
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!features.isLoading && items.length === 0 ? (
                    <TableRow>
                      <TableCell
                        className="h-32 text-center text-muted-foreground"
                        colSpan={7}
                      >
                        feature가 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </div>
          </div>

          <FeatureDetailInspector featureId={selectedFeatureId} />
        </section>
      </div>
    </AdminShell>
  );
}

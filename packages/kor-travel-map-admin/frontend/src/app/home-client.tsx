"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench (dashboard) · design-system: design.md · designed-as-app

import { type ColumnDef } from "@tanstack/react-table";
import {
  AlertTriangleIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";
import { type ReactNode, useMemo } from "react";

import { useDedupReviews } from "@/api/dedup";
import { useOpsMetrics } from "@/api/ops";
import {
  DAGSTER_UI_URL,
  usePipelineExecutions,
  usePipelineOverview,
} from "@/api/pipeline";
import { useHealth, useVersion } from "@/api/queries";
import { AdminShell } from "@/components/admin-shell";
import { EmptyState } from "@/components/empty-state";
import { EntityLink } from "@/components/entity-link";
import { SectionCard } from "@/components/section-card";
import { StatStrip } from "@/components/stat-strip";
import { StatusBadge } from "@/components/status-badge";
import {
  Alert,
  AlertActions,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { Card } from "@/components/ui/card";
import {
  DataTable,
  type DataTableColumnMeta,
} from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

import { canonicalPipelineRootRowId } from "./home-row-id";

/**
 * 홈 KPI의 e2e 훅 — 네 stat이 한 StatStrip을 공유하므로 값 단언은 반드시 소유 stat으로
 * scope한다(e2e/home.spec.ts · e2e/home-nav.spec.ts).
 */
const HOME_STAT_TEST_ID = {
  dedup: "home-stat-dedup",
  features: "home-stat-features",
  issues: "home-stat-issues",
  pipeline: "home-stat-pipeline",
} as const;

/**
 * KPI 컬럼 수: 모바일 1 · 태블릿 2 · 데스크톱 4(StatStrip 기본 auto-fit을 이 페이지에서만 고정).
 * e2e/home-nav.spec.ts의 밀도 계약(390/768/1280 → 1/2/4)이 이 클래스에 걸려 있다.
 */
const HOME_STAT_COLUMNS = "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4";

function StatusLine({
  tone,
  children,
}: {
  tone: "success" | "warning" | "destructive" | "neutral";
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 font-medium",
        tone === "success" && "text-success",
        tone === "warning" && "text-warning",
        tone === "destructive" && "text-destructive",
        tone === "neutral" && "text-text-secondary",
      )}
    >
      <span className="size-1.5 shrink-0 rounded-full bg-current" aria-hidden="true" />
      {children}
    </span>
  );
}

function MetricItemSkeleton() {
  return (
    <div
      className="flex min-w-0 flex-col gap-2 px-4 first:pl-0 [&:not(:first-child)]:border-l [&:not(:first-child)]:border-border"
      data-testid="metric-skeleton"
    >
      <Skeleton className="h-3.5 w-20" />
      <Skeleton className="h-8 w-24" />
      <Skeleton className="h-3 w-28" />
    </div>
  );
}

function sumValues(record: Record<string, number> | null | undefined): number | null {
  if (!record) return null;
  return Object.values(record).reduce((sum, count) => sum + count, 0);
}

type FailureItem = { source: string; message: string | undefined };

function useHomePageClientController() {
  const health = useHealth();
  const version = useVersion();
  const metrics = useOpsMetrics();
  const metricsData = metrics.data?.data;
  const pipeline = usePipelineOverview(8);
  const pipelineData = pipeline.data?.data;
  const pipelineExecutions = usePipelineExecutions({ page_size: 8 });
  const dedup = useDedupReviews({ status: ["pending"], page_size: 6 });
  const dagsterData = pipelineData?.dagster;

  const pipelineExecutionItems = pipelineExecutions.data?.data.items ?? [];
  const totalFeatures = metricsData?.features_total ?? null;
  const activeFeatures = metricsData?.features_active ?? null;
  const inactiveFeatures = metricsData?.features_inactive ?? null;
  const operationTotal = sumValues(pipelineData?.operations_by_status);
  const activeOperations = pipelineData?.active_operations ?? null;
  const dedupQueueTotal = sumValues(metricsData?.dedup_queue_by_status);
  const pendingDedupCount = metricsData?.dedup_fp_stats.pending ?? null;
  const openIssueCount = metricsData?.data_integrity_issues.open_total ?? null;
  type PipelineExecutionRow = NonNullable<
    typeof pipelineExecutions.data
  >["data"]["items"][number];
  const pipelineExecutionColumns = useMemo<
    ColumnDef<PipelineExecutionRow, unknown>[]
  >(
    () => [
      {
        accessorKey: "id",
        header: "실행",
        enableSorting: false,
        cell: ({ row }) => (
          <EntityLink
            className="text-xs"
            id={row.original.id}
            kind={
              row.original.kind === "import_job"
                ? "importJob"
                : "updateRequest"
            }
          >
            {shortId(row.original.id)}
          </EntityLink>
        ),
      },
      {
        accessorKey: "kind",
        header: "kind",
        enableSorting: true,
        cell: ({ row }) => (
          <span className="font-mono text-xs text-text-secondary">
            {row.original.kind}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: "status",
        enableSorting: true,
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "progress",
        header: "progress",
        enableSorting: true,
        meta: { align: "right" } satisfies DataTableColumnMeta,
        // progress 없음은 e2e(home-nav.spec)가 "-" 텍스트로 단언하므로 그대로 둔다(스펙 갱신 시 NULL_GLYPH로).
        cell: ({ row }) => (
          <span className={cn(row.original.progress === null && "text-text-tertiary")}>
            {row.original.progress === null ? "-" : `${row.original.progress}%`}
          </span>
        ),
      },
      {
        id: "updated",
        header: "updated",
        enableSorting: true,
        accessorFn: (row) =>
          row.finished_at ?? row.started_at ?? row.created_at,
        cell: ({ row }) => (
          <span className="text-text-secondary">
            {formatDateTime(
              row.original.finished_at ??
                row.original.started_at ??
                row.original.created_at,
            )}
          </span>
        ),
      },
    ],
    [],
  );

  const refreshAll = () => {
    void health.refetch();
    void version.refetch();
    void metrics.refetch();
    void pipeline.refetch();
    void pipelineExecutions.refetch();
    void dedup.refetch();
  };

  const isRefreshing =
    health.isFetching ||
    version.isFetching ||
    metrics.isFetching ||
    pipeline.isFetching ||
    pipelineExecutions.isFetching ||
    dedup.isFetching;

  const failureCandidates: Array<FailureItem | null> = [
    health.isError ? { source: "health", message: health.error?.message } : null,
    metrics.isError ? { source: "운영 metric", message: metrics.error?.message } : null,
    pipeline.isError ? { source: "파이프라인 요약", message: pipeline.error?.message } : null,
    pipelineExecutions.isError
      ? { source: "최근 실행", message: pipelineExecutions.error?.message }
      : null,
  ];
  const failures = failureCandidates.filter((item): item is FailureItem => item !== null);

  return {
    activeFeatures,
    activeOperations,
    dagsterData,
    dedup,
    dedupQueueTotal,
    failures,
    health,
    inactiveFeatures,
    isRefreshing,
    metrics,
    openIssueCount,
    operationTotal,
    pendingDedupCount,
    pipeline,
    pipelineExecutionColumns,
    pipelineExecutionItems,
    pipelineExecutions,
    refreshAll,
    totalFeatures,
    version,
  };
}

function HomePageClientView({
  activeFeatures,
  activeOperations,
  dagsterData,
  dedup,
  dedupQueueTotal,
  failures,
  health,
  inactiveFeatures,
  isRefreshing,
  metrics,
  openIssueCount,
  operationTotal,
  pendingDedupCount,
  pipeline,
  pipelineExecutionColumns,
  pipelineExecutionItems,
  pipelineExecutions,
  refreshAll,
  totalFeatures,
  version,
}: ReturnType<typeof useHomePageClientController>) {
  const metricsLoading = metrics.isLoading || pipeline.isLoading;
  const dedupItems = dedup.data?.data.items ?? [];
  const backendStatus =
    health.data?.data?.status ?? (health.isError ? "error" : "loading");
  const dagsterStatus =
    dagsterData?.status ?? (pipeline.isError ? "error" : "loading");
  return (
    <AdminShell
      actions={
        <>
          <Button
            loading={isRefreshing}
            type="button"
            variant="outline"
            onClick={refreshAll}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          <a
            className={cn(buttonVariants({ variant: "outline" }))}
            href={DAGSTER_UI_URL}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLinkIcon data-icon="inline-start" />
            Dagster
          </a>
        </>
      }
      description="운영 상태를 한 화면에서 확인합니다."
      title="운영 홈"
    >
      <div className="space-y-6">
        {failures.length > 0 ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>운영 summary 확인 필요</AlertTitle>
            <AlertDescription>
              <p>
                {failures.map((item) => item.source).join(" · ")} 조회가 실패했습니다.
                실패한 항목의 값은 —로 표시됩니다.
              </p>
              <ul className="list-disc space-y-0.5 pl-4">
                {failures.map((item) => (
                  <li key={item.source}>
                    <span className="font-medium">{item.source}</span>
                    {item.message ? <> — {item.message}</> : null}
                  </li>
                ))}
              </ul>
            </AlertDescription>
            <AlertActions>
              <Button
                loading={isRefreshing}
                size="sm"
                type="button"
                variant="outline"
                onClick={refreshAll}
              >
                다시 시도
              </Button>
            </AlertActions>
          </Alert>
        ) : null}

        <Card aria-busy={metricsLoading || undefined} size="sm">
          {metricsLoading ? (
            <div
              aria-label="운영 요약"
              className={cn("grid gap-y-6", HOME_STAT_COLUMNS)}
              role="group"
            >
              <MetricItemSkeleton />
              <MetricItemSkeleton />
              <MetricItemSkeleton />
              <MetricItemSkeleton />
            </div>
          ) : (
            <StatStrip
              ariaLabel="운영 요약"
              className={HOME_STAT_COLUMNS}
              items={[
                {
                  key: "features",
                  label: "Feature",
                  href: "/admin/features",
                  unit: "개",
                  value: totalFeatures,
                  caption: (
                    <>
                      활성 {formatCount(activeFeatures)} / 비활성{" "}
                      {formatCount(inactiveFeatures)}
                    </>
                  ),
                  testId: HOME_STAT_TEST_ID.features,
                },
                {
                  key: "pipeline",
                  label: "파이프라인 작업",
                  href: "/ops/pipeline",
                  unit: "건",
                  value: operationTotal,
                  caption:
                    activeOperations === null ? (
                      "진행 상태 확인 불가"
                    ) : (
                      <StatusLine tone={activeOperations > 0 ? "warning" : "success"}>
                        {activeOperations > 0
                          ? `${formatCount(activeOperations)}건 진행 중`
                          : "대기 중인 작업 없음"}
                      </StatusLine>
                    ),
                  testId: HOME_STAT_TEST_ID.pipeline,
                },
                {
                  key: "dedup",
                  label: "중복 검수",
                  href: "/admin/features/dedup-reviews",
                  unit: "건",
                  value: dedupQueueTotal,
                  caption: <>대기 {formatCount(pendingDedupCount)}건</>,
                  testId: HOME_STAT_TEST_ID.dedup,
                },
                {
                  key: "issues",
                  label: "이슈",
                  href: "/admin/issues",
                  unit: "건",
                  value: openIssueCount,
                  caption:
                    openIssueCount === null ? (
                      "이슈 상태 확인 불가"
                    ) : (
                      <StatusLine tone={openIssueCount > 0 ? "destructive" : "success"}>
                        {openIssueCount > 0 ? "조치 필요" : "열린 이슈 없음"}
                      </StatusLine>
                    ),
                  testId: HOME_STAT_TEST_ID.issues,
                },
              ]}
              size="lg"
            />
          )}
        </Card>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_var(--rail)]">
          <SectionCard
            actions={
              <Link
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
                href="/ops/pipeline"
              >
                전체 보기
              </Link>
            }
            title="최근 파이프라인 실행"
          >
            {pipelineExecutions.isError ? (
              <p className="text-xs text-destructive">
                최근 실행을 불러오지 못했습니다 — {pipelineExecutions.error.message}
              </p>
            ) : null}
            <DataTable
              columns={pipelineExecutionColumns}
              data={pipelineExecutionItems}
              emptyState={{
                title: "파이프라인 실행이 없습니다.",
                description: "적재·갱신이 시작되면 최근 8건이 여기에 표시됩니다.",
              }}
              getRowId={canonicalPipelineRootRowId}
              isLoading={pipelineExecutions.isLoading}
              manualSorting={false}
            />
          </SectionCard>

          <div className="flex min-w-0 flex-col gap-6">
            <SectionCard contentClassName="space-y-0 divide-y divide-border" title="서비스 상태">
              <div className="flex flex-col gap-2 py-3 first:pt-0" data-testid="service-backend">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-medium text-text-primary">Backend</span>
                  <StatusBadge status={backendStatus} />
                </div>
                <p className="font-mono text-2xs text-text-secondary tabular-nums">
                  {version.data ? (
                    <>
                      <span>admin {version.data.data.version}</span>
                      {" · "}
                      <span>map {version.data.data.kor_travel_map_version}</span>
                    </>
                  ) : (
                    <span>버전 —</span>
                  )}
                </p>
              </div>
              <div className="flex flex-col gap-2 py-3 last:pb-0" data-testid="service-dagster">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-medium text-text-primary">Dagster</span>
                  <StatusBadge status={dagsterStatus} />
                </div>
                <p className="text-2xs text-text-secondary tabular-nums">
                  <span>{formatCount(dagsterData?.recent_runs?.length)} recent runs</span>
                  {" · "}
                  <span>{formatCount(dagsterData?.schedule_count)} schedules</span>
                </p>
                <div>
                  <Link
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                    href="/ops/pipeline?tab=schedules"
                  >
                    작업 자동화
                  </Link>
                </div>
              </div>
            </SectionCard>

            <SectionCard
              contentClassName="space-y-0"
              description="검토 대기 후보"
              title="중복 검수 대기"
            >
              {dedup.isLoading ? (
                <div aria-busy="true" className="flex flex-col gap-2 py-1">
                  <Skeleton className="h-4 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              ) : dedupItems.length === 0 ? (
                <EmptyState
                  description="새 후보가 생기면 여기에 표시됩니다."
                  size="sm"
                  title="pending dedup review가 없습니다."
                />
              ) : (
                <ul className="divide-y divide-border">
                  {dedupItems.slice(0, 4).map((item) => (
                    <li key={item.review_id}>
                      <Link
                        className="-mx-2 flex flex-col gap-0.5 rounded-control px-2 py-2 text-sm text-text-primary transition-[color,background-color] hover:bg-surface-subtle focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus active:bg-surface-muted"
                        href="/admin/features/dedup-reviews"
                      >
                        <span className="truncate font-medium">
                          {item.feature_a.name} / {item.feature_b.name}
                        </span>
                        <span className="text-xs text-text-secondary tabular-nums">
                          점수 {item.total_score.toFixed(1)} ·{" "}
                          <span className="font-mono">{shortId(item.review_id)}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          </div>
        </section>
      </div>
    </AdminShell>
  );
}

export function HomePageClient() {
  const controller = useHomePageClientController();
  return <HomePageClientView {...controller} />;
}

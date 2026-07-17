"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  ActivityIcon,
  AlertTriangleIcon,
  DatabaseIcon,
  ExternalLinkIcon,
  GitCompareArrowsIcon,
  ListChecksIcon,
  MapIcon,
  RefreshCwIcon,
  WorkflowIcon,
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
import { EntityLink } from "@/components/entity-link";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCount, formatDateTime, shortId } from "@/lib/format";
import { cn } from "@/lib/utils";

function MetricCard({
  title,
  value,
  unit,
  icon: Icon,
  href,
  children,
}: {
  title: string;
  value: string;
  unit: string;
  icon: typeof ActivityIcon;
  href?: string;
  children: ReactNode;
}) {
  return (
    <Card className="min-h-40">
      <CardHeader>
        <CardTitle className="text-[12px] font-bold tracking-[0.05em] text-text-secondary uppercase">
          {href ? (
            <Link
              className="underline-offset-4 hover:underline"
              href={href}
            >
              {title}
            </Link>
          ) : (
            title
          )}
        </CardTitle>
        <CardAction>
          <span className="flex size-10 items-center justify-center rounded-xl bg-brand-tint text-brand">
            <Icon className="size-5" />
          </span>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <div className="flex items-end gap-1 text-text-primary">
          <span className="text-[36px] leading-none font-bold">{value}</span>
          <span className="pb-0.5 text-[18px] leading-none font-bold">{unit}</span>
        </div>
        {children}
      </CardContent>
    </Card>
  );
}

function StatusLine({
  tone,
  children,
}: {
  tone: "success" | "warning" | "destructive" | "muted";
  children: ReactNode;
}) {
  return (
    <p
      className={cn(
        "flex items-center gap-1.5 text-[13px] font-bold",
        tone === "success" && "text-success",
        tone === "warning" && "text-warning",
        tone === "destructive" && "text-destructive",
        tone === "muted" && "text-text-secondary",
      )}
    >
      <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
      {children}
    </p>
  );
}

function MetricCardSkeleton() {
  return (
    <Card className="min-h-40" data-testid="metric-skeleton">
      <CardHeader>
        <Skeleton className="h-4 w-24" />
        <CardAction>
          <Skeleton className="size-10 rounded-xl" />
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3">
        <Skeleton className="h-9 w-28" />
        <Skeleton className="h-3 w-full" />
      </CardContent>
    </Card>
  );
}

export function HomePageClient() {
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
  const totalFeatures = metricsData?.features_total ?? 0;
  const activeFeatures = metricsData?.features_active ?? 0;
  const activeFeatureRatio =
    totalFeatures > 0 ? Math.min(100, (activeFeatures / totalFeatures) * 100) : 0;
  const operationTotal = Object.values(
    pipelineData?.operations_by_status ?? {},
  ).reduce((sum, count) => sum + count, 0);
  const activeOperations = pipelineData?.active_operations ?? 0;
  const dedupQueueTotal = Object.values(
    metricsData?.dedup_queue_by_status ?? {},
  ).reduce((sum, count) => sum + count, 0);
  const pendingDedupCount = metricsData?.dedup_fp_stats.pending ?? 0;
  const openIssueCount = metricsData?.data_integrity_issues.open_total ?? 0;
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
        cell: ({ row }) => (
          <span className="font-mono">
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
          <span className="text-muted-foreground">
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

  return (
    <AdminShell
      actions={
        <>
          <Button type="button" variant="outline" onClick={refreshAll}>
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
        {(health.isError ||
          metrics.isError ||
          pipeline.isError ||
          pipelineExecutions.isError) && (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>운영 summary 확인 필요</AlertTitle>
            <AlertDescription>
              {health.error?.message ??
                metrics.error?.message ??
                pipeline.error?.message ??
                pipelineExecutions.error?.message}
            </AlertDescription>
          </Alert>
        )}

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {metrics.isLoading || pipeline.isLoading ? (
            <>
              <MetricCardSkeleton />
              <MetricCardSkeleton />
              <MetricCardSkeleton />
              <MetricCardSkeleton />
            </>
          ) : (
            <>
              <MetricCard
                href="/admin/features"
                icon={MapIcon}
                title="Feature"
                unit="개"
                value={formatCount(totalFeatures)}
              >
                <div className="space-y-2">
                  <div className="h-2 rounded-full bg-surface-muted">
                    <div
                      className="h-full rounded-full bg-brand"
                      style={{ width: `${activeFeatureRatio}%` }}
                    />
                  </div>
                  <p className="text-[13px] leading-normal text-text-secondary">
                    활성 {formatCount(activeFeatures)} / 비활성{" "}
                    {formatCount(metricsData?.features_inactive)}
                  </p>
                </div>
              </MetricCard>
              <MetricCard
                href="/ops/pipeline"
                icon={ListChecksIcon}
                title="파이프라인 작업"
                unit="건"
                value={formatCount(operationTotal)}
              >
                <StatusLine tone={activeOperations > 0 ? "warning" : "success"}>
                  {activeOperations > 0
                    ? `${formatCount(activeOperations)}건 진행 중`
                    : "대기 중인 작업 없음"}
                </StatusLine>
              </MetricCard>
              <MetricCard
                href="/admin/features/dedup-reviews"
                icon={GitCompareArrowsIcon}
                title="중복 검수"
                unit="건"
                value={formatCount(dedupQueueTotal)}
              >
                <p className="text-[13px] leading-normal text-text-secondary">
                  대기 {formatCount(pendingDedupCount)}건
                </p>
              </MetricCard>
              <MetricCard
                href="/admin/issues"
                icon={AlertTriangleIcon}
                title="이슈"
                unit="건"
                value={formatCount(openIssueCount)}
              >
                <StatusLine tone={openIssueCount > 0 ? "destructive" : "success"}>
                  {openIssueCount > 0 ? "조치 필요" : "열린 이슈 없음"}
                </StatusLine>
              </MetricCard>
            </>
          )}
        </section>

        <section className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <Card>
            <CardHeader>
              <CardTitle>최근 파이프라인 실행</CardTitle>
              <CardAction>
                <Link
                  className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
                  href="/ops/pipeline"
                >
                  전체
                </Link>
              </CardAction>
            </CardHeader>
            <CardContent>
              {pipelineExecutions.isError ? (
                <p className="text-sm text-destructive">
                  {pipelineExecutions.error.message}
                </p>
              ) : null}
              <DataTable
                columns={pipelineExecutionColumns}
                data={pipelineExecutionItems}
                getRowId={(row) => row.id}
                isLoading={pipelineExecutions.isLoading}
                emptyMessage="파이프라인 실행이 없습니다."
                manualSorting={false}
              />
            </CardContent>
          </Card>

          <div className="flex flex-col gap-6">
            <Card>
              <CardHeader>
                <CardTitle>서비스 상태</CardTitle>
                <CardAction>
                  <DatabaseIcon className="text-icon-default" />
                </CardAction>
              </CardHeader>
              <CardContent className="space-y-4">
                <div
                  className="rounded-xl bg-surface-subtle p-4"
                  data-testid="service-backend"
                >
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <span className="text-[12px] font-bold tracking-[0.05em] text-text-secondary uppercase">
                      Backend
                    </span>
                    <StatusBadge
                      status={health.data?.data?.status ?? (health.isError ? "error" : "loading")}
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {version.data ? (
                      <Badge variant="outline">admin {version.data.data.version}</Badge>
                    ) : null}
                    {version.data ? (
                      <Badge variant="outline">
                        map {version.data.data.kor_travel_map_version}
                      </Badge>
                    ) : null}
                  </div>
                </div>
                <div
                  className="rounded-xl bg-surface-subtle p-4"
                  data-testid="service-dagster"
                >
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <span className="text-[12px] font-bold tracking-[0.05em] text-text-secondary uppercase">
                      Dagster
                    </span>
                    <StatusBadge
                      status={
                        dagsterData?.status ?? (pipeline.isError ? "error" : "loading")
                      }
                    />
                  </div>
                  <div className="mb-3 flex flex-wrap gap-2">
                    <Badge variant="outline">
                      {formatCount(dagsterData?.recent_runs?.length)} recent runs
                    </Badge>
                    <Badge variant="outline">
                      {formatCount(dagsterData?.schedule_count)} schedules
                    </Badge>
                  </div>
                  <Link
                    className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                    href="/ops/pipeline?tab=schedules"
                  >
                    <WorkflowIcon data-icon="inline-start" />
                    작업 자동화
                  </Link>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>중복 검수 대기</CardTitle>
                <CardDescription>검토 대기 후보</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {(dedup.data?.data.items ?? []).slice(0, 4).map((item) => (
                  <Link
                    className="rounded-xl bg-surface-subtle px-4 py-3 text-[14px] text-text-primary transition-colors hover:bg-brand-tint"
                    href="/admin/features/dedup-reviews"
                    key={item.review_id}
                  >
                    <div className="font-medium">
                      {item.feature_a.name} / {item.feature_b.name}
                    </div>
                    <div className="text-[13px] text-text-secondary">
                      score {item.total_score.toFixed(1)} · {shortId(item.review_id)}
                    </div>
                  </Link>
                ))}
                {!dedup.isLoading && (dedup.data?.data.items.length ?? 0) === 0 ? (
                  <p className="text-[13px] text-text-secondary">
                    pending dedup review가 없습니다.
                  </p>
                ) : null}
              </CardContent>
            </Card>
          </div>
        </section>
      </div>
    </AdminShell>
  );
}

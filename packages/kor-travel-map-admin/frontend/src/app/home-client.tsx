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
import { useMemo } from "react";

import { DAGSTER_UI_URL, useDagsterSummary } from "@/api/dagster";
import { useDedupReviews } from "@/api/dedup";
import { useImportJobs } from "@/api/importJobs";
import { useOpsMetrics } from "@/api/ops";
import { useHealth, useVersion } from "@/api/queries";
import { AdminShell } from "@/components/admin-shell";
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
  description,
  icon: Icon,
}: {
  title: string;
  value: string;
  description: string;
  icon: typeof ActivityIcon;
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
        <CardAction>
          <Icon className="text-muted-foreground" />
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <div className="text-2xl font-semibold tracking-tight">{value}</div>
        <p className="text-xs text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

export function HomePageClient() {
  const health = useHealth();
  const version = useVersion();
  const metrics = useOpsMetrics();
  const metricsData = metrics.data?.data;
  const importJobs = useImportJobs({ page_size: 8 });
  const dedup = useDedupReviews({ status: ["pending"], page_size: 6 });
  const dagster = useDagsterSummary(8);
  const dagsterData = dagster.data?.data;

  const importJobItems = importJobs.data?.data.items ?? [];
  type ImportJobRow = NonNullable<
    typeof importJobs.data
  >["data"]["items"][number];
  const importJobColumns = useMemo<ColumnDef<ImportJobRow, unknown>[]>(
    () => [
      {
        accessorKey: "job_id",
        header: "job",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">{shortId(row.original.job_id)}</span>
        ),
      },
      { accessorKey: "kind", header: "kind", enableSorting: true },
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
          <span className="font-mono">{row.original.progress}%</span>
        ),
      },
      {
        id: "updated",
        header: "updated",
        enableSorting: true,
        accessorFn: (row) =>
          row.finished_at ?? row.heartbeat_at ?? row.started_at,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(
              row.original.finished_at ??
                row.original.heartbeat_at ??
                row.original.started_at,
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
    void importJobs.refetch();
    void dedup.refetch();
    void dagster.refetch();
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
      description="feature, import job, consistency, Dagster 상태를 한 화면에서 확인합니다."
      section="Overview"
      title="운영 홈"
    >
      <div className="flex flex-col gap-5">
        {(health.isError || metrics.isError || dagster.isError) && (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>운영 summary 확인 필요</AlertTitle>
            <AlertDescription>
              {health.error?.message ?? metrics.error?.message ?? dagster.error?.message}
            </AlertDescription>
          </Alert>
        )}

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {metrics.isLoading ? (
            <>
              <Skeleton className="h-28" />
              <Skeleton className="h-28" />
              <Skeleton className="h-28" />
              <Skeleton className="h-28" />
            </>
          ) : (
            <>
              <MetricCard
                description={`${formatCount(metricsData?.features_active)} active / ${formatCount(metricsData?.features_inactive)} inactive`}
                icon={MapIcon}
                title="Features"
                value={formatCount(metricsData?.features_total)}
              />
              <MetricCard
                description="queued, running, done, failed"
                icon={ListChecksIcon}
                title="Import jobs"
                value={formatCount(
                  Object.values(metricsData?.import_jobs_by_status ?? {}).reduce(
                    (sum, count) => sum + count,
                    0,
                  ),
                )}
              />
              <MetricCard
                description={`${formatCount(metricsData?.dedup_fp_stats.pending)} pending reviews`}
                icon={GitCompareArrowsIcon}
                title="Dedup queue"
                value={formatCount(
                  Object.values(metricsData?.dedup_queue_by_status ?? {}).reduce(
                    (sum, count) => sum + count,
                    0,
                  ),
                )}
              />
              <MetricCard
                description="open data integrity issues"
                icon={AlertTriangleIcon}
                title="Issues"
                value={formatCount(metricsData?.data_integrity_issues.open_total)}
              />
            </>
          )}
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
          <Card>
            <CardHeader>
              <CardTitle>최근 import jobs</CardTitle>
              <CardDescription>ops.import_jobs 상태</CardDescription>
              <CardAction>
                <Link
                  className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
                  href="/ops/import-jobs"
                >
                  전체
                </Link>
              </CardAction>
            </CardHeader>
            <CardContent className="overflow-auto">
              {importJobs.isError ? (
                <p className="text-sm text-destructive">
                  {importJobs.error.message}
                </p>
              ) : null}
              <DataTable
                columns={importJobColumns}
                data={importJobItems}
                getRowId={(row) => row.job_id}
                isLoading={importJobs.isLoading}
                emptyMessage="import job이 없습니다."
              />
            </CardContent>
          </Card>

          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader>
                <CardTitle>Backend</CardTitle>
                <CardDescription>health / version</CardDescription>
                <CardAction>
                  <DatabaseIcon className="text-muted-foreground" />
                </CardAction>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-2">
                  <StatusBadge
                    status={health.data?.data?.status ?? (health.isError ? "error" : "loading")}
                  />
                  {version.data ? (
                    <Badge variant="outline">admin {version.data.data.version}</Badge>
                  ) : null}
                  {version.data ? (
                    <Badge variant="outline">map {version.data.data.kor_travel_map_version}</Badge>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Dagster</CardTitle>
                <CardDescription>summary + embed</CardDescription>
                <CardAction>
                  <WorkflowIcon className="text-muted-foreground" />
                </CardAction>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-2">
                  <StatusBadge
                    status={
                      dagsterData?.status ?? (dagster.isError ? "error" : "loading")
                    }
                  />
                  <Badge variant="outline">
                    {formatCount(dagsterData?.asset_count)} assets
                  </Badge>
                  <Badge variant="outline">
                    {formatCount(dagsterData?.schedule_count)} schedules
                  </Badge>
                </div>
                <Link
                  className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
                  href="/admin/dagster"
                >
                  <WorkflowIcon data-icon="inline-start" />
                  Dagster 관리
                </Link>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Dedup pending</CardTitle>
                <CardDescription>검토 대기 후보</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {(dedup.data?.data.items ?? []).slice(0, 4).map((item) => (
                  <Link
                    className="rounded-md border px-3 py-2 text-sm hover:bg-muted"
                    href="/admin/dedup-reviews"
                    key={item.review_id}
                  >
                    <div className="font-medium">
                      {item.feature_a.name} / {item.feature_b.name}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      score {item.total_score.toFixed(1)} · {shortId(item.review_id)}
                    </div>
                  </Link>
                ))}
                {!dedup.isLoading && (dedup.data?.data.items.length ?? 0) === 0 ? (
                  <p className="text-sm text-muted-foreground">
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

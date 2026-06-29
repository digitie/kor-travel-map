"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { RefreshCwIcon } from "lucide-react";
import { useMemo, useState } from "react";

import {
  type IntegrityIssueStatus,
  useConsistencyReports,
  useIntegrityIssues,
  useOpsMetrics,
} from "@/api/ops";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { formatCount, formatDateTime, shortId } from "@/lib/format";

const issueStatuses: Array<IntegrityIssueStatus | "all"> = [
  "open",
  "acknowledged",
  "resolved",
  "ignored",
  "all",
];

export function ConsistencyClient() {
  const [status, setStatus] = useState<IntegrityIssueStatus | "all">("open");
  const metrics = useOpsMetrics();
  const metricsData = metrics.data?.data;
  const reports = useConsistencyReports({ page_size: 20 });
  const issues = useIntegrityIssues({
    status: status === "all" ? undefined : status,
    page_size: 100,
  });

  const refreshAll = () => {
    void metrics.refetch();
    void reports.refetch();
    void issues.refetch();
  };

  const reportItems = reports.data?.data.items ?? [];
  type ReportRow = NonNullable<typeof reports.data>["data"]["items"][number];
  const reportColumns = useMemo<ColumnDef<ReportRow, unknown>[]>(
    () => [
      {
        id: "report",
        header: "리포트",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.report_id)}
          </span>
        ),
      },
      {
        id: "batch",
        header: "배치",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.batch_id)}
          </span>
        ),
      },
      {
        accessorKey: "severity_max",
        header: "심각도",
        cell: ({ row }) => <StatusBadge status={row.original.severity_max} />,
      },
      {
        accessorKey: "finished_at",
        header: "완료",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.finished_at)}
          </span>
        ),
      },
    ],
    [],
  );

  const issueItems = issues.data?.data.items ?? [];
  type IssueRow = NonNullable<typeof issues.data>["data"]["items"][number];
  const issueColumns = useMemo<ColumnDef<IssueRow, unknown>[]>(
    () => [
      {
        id: "issue",
        header: "이슈",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {shortId(row.original.issue_id)}
          </span>
        ),
      },
      {
        accessorKey: "severity",
        header: "심각도",
        cell: ({ row }) => <StatusBadge status={row.original.severity} />,
      },
      {
        accessorKey: "provider",
        header: "provider",
        cell: ({ row }) => row.original.provider ?? "-",
      },
      {
        accessorKey: "message",
        header: "메시지",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-96 truncate">{row.original.message}</span>
        ),
      },
      {
        accessorKey: "detected_at",
        header: "감지",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.detected_at)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <AdminShell
      actions={
        <Button type="button" variant="outline" onClick={refreshAll}>
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="consistency report와 data integrity issue queue를 조회합니다."
      section="Ops"
      title="Consistency"
    >
      <div className="flex flex-col gap-4">
        {(metrics.isError || reports.isError || issues.isError) && (
          <Alert variant="destructive">
            <AlertTitle>consistency 조회 실패</AlertTitle>
            <AlertDescription>
              {metrics.error?.message ?? reports.error?.message ?? issues.error?.message}
            </AlertDescription>
          </Alert>
        )}

        <section className="grid gap-4 md:grid-cols-3">
          <div className="rounded-lg border bg-background p-4">
            <div className="text-sm text-muted-foreground">Open issues</div>
            <div className="mt-1 text-2xl font-semibold">
              {formatCount(metricsData?.data_integrity_issues.open_total)}
            </div>
          </div>
          <div className="rounded-lg border bg-background p-4">
            <div className="text-sm text-muted-foreground">Latest severity</div>
            <div className="mt-2">
              <StatusBadge
                status={metricsData?.latest_consistency_report?.severity_max ?? "none"}
              />
            </div>
          </div>
          <div className="rounded-lg border bg-background p-4">
            <div className="text-sm text-muted-foreground">Checked at</div>
            <div className="mt-1 font-mono text-sm">
              {formatDateTime(metricsData?.checked_at)}
            </div>
          </div>
        </section>

        <section className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-lg border bg-background">
            <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <div className="font-medium">Reports</div>
                <div className="text-sm text-muted-foreground">
                  최근 consistency batch
                </div>
              </div>
              <Badge variant="outline">
                {reports.data?.data.items.length ?? 0}
              </Badge>
            </div>
            <DataTable
              columns={reportColumns}
              data={reportItems}
              getRowId={(row) => row.report_id}
              isLoading={reports.isLoading}
              emptyMessage="데이터가 없습니다."
              manualSorting={false}
              containerClassName="overflow-auto"
            />
          </div>

          <div className="rounded-lg border bg-background">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
              <div>
                <div className="font-medium">Integrity issues</div>
                <div className="text-sm text-muted-foreground">
                  status/provider/type별 후속 처리 대상
                </div>
              </div>
              <NativeSelect
                aria-label="issue status"
                value={status}
                onChange={(event) =>
                  setStatus(event.target.value as IntegrityIssueStatus | "all")
                }
              >
                {issueStatuses.map((item) => (
                  <NativeSelectOption key={item} value={item}>
                    {item}
                  </NativeSelectOption>
                ))}
              </NativeSelect>
            </div>
            <DataTable
              columns={issueColumns}
              data={issueItems}
              getRowId={(row) => row.issue_id}
              isLoading={issues.isLoading}
              emptyMessage="데이터가 없습니다."
              manualSorting={false}
              containerClassName="overflow-auto"
            />
          </div>
        </section>
      </div>
    </AdminShell>
  );
}

"use client";

import { RefreshCwIcon } from "lucide-react";
import { useState } from "react";

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
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
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
              <Badge variant="outline">{reports.data?.meta.count ?? 0}</Badge>
            </div>
            {reports.isLoading ? <Skeleton className="m-4 h-72" /> : null}
            <div className="overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>report</TableHead>
                    <TableHead>batch</TableHead>
                    <TableHead>severity</TableHead>
                    <TableHead>finished</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(reports.data?.data.items ?? []).map((report) => (
                    <TableRow key={report.report_id}>
                      <TableCell className="font-mono text-xs">
                        {shortId(report.report_id)}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {shortId(report.batch_id)}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={report.severity_max} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(report.finished_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
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
            {issues.isLoading ? <Skeleton className="m-4 h-72" /> : null}
            <div className="overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>issue</TableHead>
                    <TableHead>severity</TableHead>
                    <TableHead>provider</TableHead>
                    <TableHead>message</TableHead>
                    <TableHead>detected</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(issues.data?.data.items ?? []).map((issue) => (
                    <TableRow key={issue.violation_key}>
                      <TableCell className="font-mono text-xs">
                        {shortId(issue.violation_key)}
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={issue.severity} />
                      </TableCell>
                      <TableCell>{issue.provider ?? "-"}</TableCell>
                      <TableCell className="max-w-96 truncate">
                        {issue.message}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(issue.detected_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </section>
      </div>
    </AdminShell>
  );
}

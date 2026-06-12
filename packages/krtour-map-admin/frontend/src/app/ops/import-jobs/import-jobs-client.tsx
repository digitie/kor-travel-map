"use client";

import { RefreshCwIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { type ImportJobStatus, useImportJobs } from "@/api/importJobs";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
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
import { formatDateTime, shortId } from "@/lib/format";

const statuses: Array<ImportJobStatus | "all"> = [
  "all",
  "queued",
  "running",
  "done",
  "failed",
  "cancelled",
];

type ImportJobsInitialFilters = {
  status?: string;
  kind?: string;
  loadBatchId?: string;
  parentJobId?: string;
};

const emptyInitialFilters: ImportJobsInitialFilters = {};

export function ImportJobsClient({
  initialFilters = emptyInitialFilters,
}: {
  initialFilters?: ImportJobsInitialFilters;
}) {
  const [status, setStatus] = useState<ImportJobStatus | "all">(() => {
    const value = initialFilters.status as ImportJobStatus | undefined;
    return value && statuses.includes(value) ? value : "all";
  });
  const [kind, setKind] = useState(() => initialFilters.kind ?? "");
  const [loadBatchId, setLoadBatchId] = useState(
    () => initialFilters.loadBatchId ?? "",
  );
  const [parentJobId, setParentJobId] = useState(
    () => initialFilters.parentJobId ?? "",
  );
  const jobs = useImportJobs({
    status: status === "all" ? undefined : status,
    kind: kind.trim() || undefined,
    load_batch_id: loadBatchId.trim() || undefined,
    parent_job_id: parentJobId.trim() || undefined,
    page_size: 100,
  });

  return (
    <AdminShell
      actions={
        <Button
          disabled={jobs.isFetching}
          type="button"
          variant="outline"
          onClick={() => void jobs.refetch()}
        >
          <RefreshCwIcon data-icon="inline-start" />
          새로고침
        </Button>
      }
      description="ops.import_jobs 진행 상태와 batch/parent 연결을 확인합니다."
      section="Ops"
      title="Import jobs"
    >
      <div className="flex flex-col gap-4">
        {jobs.isError ? (
          <Alert variant="destructive">
            <AlertTitle>import job 조회 실패</AlertTitle>
            <AlertDescription>{jobs.error.message}</AlertDescription>
          </Alert>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <NativeSelect
            aria-label="status"
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as ImportJobStatus | "all")
            }
          >
            {statuses.map((item) => (
              <NativeSelectOption key={item} value={item}>
                {item}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <Input
            className="max-w-72"
            placeholder="kind filter"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          />
          <Input
            className="max-w-80"
            placeholder="load_batch_id"
            value={loadBatchId}
            onChange={(event) => setLoadBatchId(event.target.value)}
          />
          <Input
            className="max-w-80"
            placeholder="parent_job_id"
            value={parentJobId}
            onChange={(event) => setParentJobId(event.target.value)}
          />
        </div>

        {jobs.isLoading ? <Skeleton className="h-96" /> : null}
        <div className="overflow-auto rounded-lg border bg-background">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>job</TableHead>
                <TableHead>batch</TableHead>
                <TableHead>parent</TableHead>
                <TableHead>kind</TableHead>
                <TableHead>status</TableHead>
                <TableHead>progress</TableHead>
                <TableHead>stage</TableHead>
                <TableHead>created</TableHead>
                <TableHead>finished</TableHead>
                <TableHead>error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(jobs.data?.data.items ?? []).map((job) => (
                <TableRow key={job.job_id}>
                  <TableCell className="font-mono text-xs">
                    <Link
                      className="text-primary underline-offset-4 hover:underline"
                      href={`/ops/import-jobs/${encodeURIComponent(job.job_id)}`}
                    >
                      {shortId(job.job_id)}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {job.load_batch_id ? shortId(job.load_batch_id) : "-"}
                  </TableCell>
                  <TableCell className="font-mono text-xs">
                    {job.parent_job_id ? shortId(job.parent_job_id) : "-"}
                  </TableCell>
                  <TableCell>{job.kind}</TableCell>
                  <TableCell>
                    <StatusBadge status={job.status} />
                  </TableCell>
                  <TableCell className="font-mono">{job.progress}%</TableCell>
                  <TableCell>{job.current_stage ?? "-"}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(job.created_at)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatDateTime(job.finished_at)}
                  </TableCell>
                  <TableCell className="max-w-80 truncate text-destructive">
                    {job.error_message ?? ""}
                  </TableCell>
                </TableRow>
              ))}
              {!jobs.isLoading && (jobs.data?.data.items.length ?? 0) === 0 ? (
                <TableRow>
                  <TableCell
                    className="h-32 text-center text-muted-foreground"
                    colSpan={10}
                  >
                    import job이 없습니다.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </div>
      </div>
    </AdminShell>
  );
}

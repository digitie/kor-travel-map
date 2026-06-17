"use client";

import { type ColumnDef } from "@tanstack/react-table";
import { RefreshCwIcon } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { type ImportJobStatus, useImportJobs } from "@/api/importJobs";
import { useOpsLiveInvalidation } from "@/api/live";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
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
  const live = useOpsLiveInvalidation({
    topics: [
      "import_jobs",
      "feature_update_requests",
      "offline_uploads",
      "dagster_runs",
    ],
  });

  const items = jobs.data?.data.items ?? [];
  type ImportJobRow = NonNullable<typeof jobs.data>["data"]["items"][number];
  const columns = useMemo<ColumnDef<ImportJobRow, unknown>[]>(
    () => [
      {
        id: "job",
        header: "job",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            <Link
              className="text-primary underline-offset-4 hover:underline"
              href={`/ops/import-jobs/${encodeURIComponent(row.original.job_id)}`}
              onClick={(event) => event.stopPropagation()}
            >
              {shortId(row.original.job_id)}
            </Link>
          </span>
        ),
      },
      {
        id: "batch",
        header: "batch",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.load_batch_id
              ? shortId(row.original.load_batch_id)
              : "-"}
          </span>
        ),
      },
      {
        id: "parent",
        header: "parent",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.parent_job_id
              ? shortId(row.original.parent_job_id)
              : "-"}
          </span>
        ),
      },
      { accessorKey: "kind", header: "kind" },
      {
        accessorKey: "status",
        header: "status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "progress",
        header: "progress",
        cell: ({ row }) => (
          <span className="font-mono">{row.original.progress}%</span>
        ),
      },
      {
        id: "stage",
        header: "stage",
        enableSorting: false,
        cell: ({ row }) => row.original.current_stage ?? "-",
      },
      {
        accessorKey: "created_at",
        header: "created",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
      },
      {
        accessorKey: "finished_at",
        header: "finished",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.finished_at)}
          </span>
        ),
      },
      {
        id: "error",
        header: "error",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-80 truncate text-destructive">
            {row.original.error_message ?? ""}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <AdminShell
      actions={
        <>
          <Badge variant={live.state === "live" ? "default" : "outline"}>
            {live.state}
          </Badge>
          <Button
            disabled={jobs.isFetching}
            type="button"
            variant="outline"
            onClick={() => void jobs.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
        </>
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

        <DataTable
          columns={columns}
          data={items}
          getRowId={(row) => row.job_id}
          isLoading={jobs.isLoading}
          emptyMessage="import job이 없습니다."
          containerClassName="overflow-auto rounded-lg border bg-background"
        />
      </div>
    </AdminShell>
  );
}

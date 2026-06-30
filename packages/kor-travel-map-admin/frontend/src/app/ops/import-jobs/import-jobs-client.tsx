"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  ArrowRightIcon,
  RefreshCwIcon,
  WorkflowIcon,
} from "lucide-react";
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

const statusLabels: Record<ImportJobStatus | "all", string> = {
  all: "전체",
  queued: "대기",
  running: "실행 중",
  done: "완료",
  failed: "실패",
  cancelled: "취소됨",
};

type ImportJobsInitialFilters = {
  status?: string;
  kind?: string;
  loadBatchId?: string;
  parentJobId?: string;
};

const emptyInitialFilters: ImportJobsInitialFilters = {};

function JobLink({ jobId }: { jobId: string }) {
  return (
    <Link
      className="inline-flex max-w-56 items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 text-xs shadow-sm transition-colors hover:bg-surface-subtle"
      href={`/ops/import-jobs/${encodeURIComponent(jobId)}`}
      onClick={(event) => event.stopPropagation()}
    >
      <span className="font-mono font-semibold">{shortId(jobId)}</span>
      <ArrowRightIcon className="size-3 text-muted-foreground" />
    </Link>
  );
}

function JobProgress({ value }: { value: number }) {
  const progress = Math.min(100, Math.max(0, value));
  return (
    <div className="flex min-w-28 items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-surface-muted">
        <div
          className="h-full rounded-full bg-brand"
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="w-10 text-right font-mono text-xs">{progress}%</span>
    </div>
  );
}

function MoisLocaldataNotice() {
  return (
    <Alert>
      <WorkflowIcon data-icon="inline-start" />
      <AlertTitle>MOIS 소스 동기화</AlertTitle>
      <AlertDescription>
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <span>
            <span className="font-mono">mois_localdata_source_sync</span>는
            MOIS bulk 적재 전에 먼저 실행되는 Dagster 선행 작업입니다.
          </span>
          <Link
            className="inline-flex w-fit items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm font-medium hover:bg-surface-subtle"
            href="/admin/dagster"
          >
            작업 자동화 열기
            <ArrowRightIcon className="size-4" />
          </Link>
        </div>
      </AlertDescription>
    </Alert>
  );
}

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
        header: "작업",
        enableSorting: false,
        cell: ({ row }) => <JobLink jobId={row.original.job_id} />,
      },
      {
        id: "error",
        header: "오류",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="block max-w-80 truncate text-destructive">
            {row.original.error_message ?? ""}
          </span>
        ),
      },
      {
        id: "batch",
        header: "배치",
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
        header: "상위 작업",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-xs">
            {row.original.parent_job_id
              ? shortId(row.original.parent_job_id)
              : "-"}
          </span>
        ),
      },
      { accessorKey: "kind", header: "종류" },
      {
        accessorKey: "status",
        header: "상태",
        cell: ({ row }) => <StatusBadge status={row.original.status} />,
      },
      {
        accessorKey: "progress",
        header: "진행",
        cell: ({ row }) => <JobProgress value={row.original.progress} />,
      },
      {
        id: "stage",
        header: "단계",
        enableSorting: false,
        cell: ({ row }) => row.original.current_stage ?? "-",
      },
      {
        accessorKey: "created_at",
        header: "생성",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.created_at)}
          </span>
        ),
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

  return (
    <AdminShell
      actions={
        <>
          <Badge variant={live.state === "live" ? "default" : "outline"}>
            {live.state === "live" ? "실시간" : live.state}
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
      description="적재 작업의 진행 상태와 배치/상위 작업 연결을 확인합니다."
      section="운영"
      title="적재 작업"
    >
      <div className="flex flex-col gap-4">
        {jobs.isError ? (
          <Alert variant="destructive">
            <AlertTitle>적재 작업 조회 실패</AlertTitle>
            <AlertDescription>{jobs.error.message}</AlertDescription>
          </Alert>
        ) : null}

        <MoisLocaldataNotice />

        <div className="flex flex-wrap items-center gap-2">
          <NativeSelect
            aria-label="상태"
            value={status}
            onChange={(event) =>
              setStatus(event.target.value as ImportJobStatus | "all")
            }
          >
            {statuses.map((item) => (
              <NativeSelectOption key={item} value={item}>
                {statusLabels[item]}
              </NativeSelectOption>
            ))}
          </NativeSelect>
          <Input
            className="max-w-72"
            placeholder="작업 종류"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
          />
          <Input
            className="max-w-80"
            placeholder="배치 ID"
            value={loadBatchId}
            onChange={(event) => setLoadBatchId(event.target.value)}
          />
          <Input
            className="max-w-80"
            placeholder="상위 작업 ID"
            value={parentJobId}
            onChange={(event) => setParentJobId(event.target.value)}
          />
        </div>

        <DataTable
          columns={columns}
          data={items}
          getRowId={(row) => row.job_id}
          isLoading={jobs.isLoading}
          emptyMessage="적재 작업이 없습니다."
          manualSorting={false}
          containerClassName="overflow-auto rounded-lg border bg-background"
        />
      </div>
    </AdminShell>
  );
}

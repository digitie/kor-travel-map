"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  ArrowLeftIcon,
  BanIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";

import {
  type ImportJobEventLevel,
  type OpsImportJobLink,
  type OpsImportJobRecord,
  useCancelImportJobMutation,
  useImportJob,
  useImportJobEvents,
} from "@/api/importJobs";
import { DAGSTER_UI_URL } from "@/api/dagster";
import { useOpsLiveInvalidation } from "@/api/live";
import { AdminShell } from "@/components/admin-shell";
import { StatusBadge, statusLabel } from "@/components/status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { NativeSelectOption } from "@/components/ui/native-select-option";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { formatDateTime, shortId } from "@/lib/format";
import { buttonVariants } from "@/components/ui/button-variants";

const terminalStatuses = new Set(["done", "failed", "cancelled"]);
const eventLevels: Array<ImportJobEventLevel | "all"> = [
  "all",
  "debug",
  "info",
  "warning",
  "error",
  "critical",
];

function jsonBlock(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

function pathTail(path: string) {
  const clean = path.split("?")[0]?.replace(/\/+$/, "") ?? "";
  return clean.slice(clean.lastIndexOf("/") + 1);
}

function relationHref(link: OpsImportJobLink) {
  if (link.rel === "self") {
    return `/ops/import-jobs/${encodeURIComponent(pathTail(link.href))}`;
  }
  if (link.rel === "parent_job") {
    return `/ops/import-jobs/${encodeURIComponent(pathTail(link.href))}`;
  }
  if (link.rel === "load_batch") {
    return link.href.replace(/^\/v1/, "");
  }
  if (link.rel === "feature_update_request") {
    return "/admin/feature-update-requests";
  }
  if (link.rel === "offline_upload") {
    return "/admin/offline-uploads";
  }
  if (link.rel === "dagster_run") {
    return `${DAGSTER_UI_URL.replace(/\/+$/, "")}/runs/${encodeURIComponent(
      pathTail(link.href),
    )}`;
  }
  return null;
}

function RelationLink({ link }: { link: OpsImportJobLink }) {
  const href = relationHref(link);
  if (!href || link.rel === "events" || link.rel === "cancel") {
    return (
      <div className="rounded-md border bg-muted/30 p-3">
        <div className="text-xs font-medium">{link.rel}</div>
        <div className="mt-1 break-all font-mono text-xs text-muted-foreground">
          {link.href}
        </div>
      </div>
    );
  }
  const external = href.startsWith("http");
  const label = link.label ?? link.rel;
  const content = (
    <>
      {label}
      {external ? <ExternalLinkIcon data-icon="inline-end" /> : null}
    </>
  );
  return (
    <div className="rounded-md border bg-background p-3">
      <div className="text-xs font-medium">{link.rel}</div>
      <div className="mt-2">
        {external ? (
          <a
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            href={href}
            rel="noreferrer"
            target="_blank"
          >
            {content}
          </a>
        ) : (
          <Link
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
            href={href}
          >
            {content}
          </Link>
        )}
      </div>
      <div className="mt-2 break-all font-mono text-xs text-muted-foreground">
        {pathTail(link.href)}
      </div>
    </div>
  );
}

function FieldRow({
  label,
  value,
}: {
  label: string;
  value: string | number | null | undefined;
}) {
  return (
    <div className="grid gap-1">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="min-h-5 break-all font-mono text-xs">{value ?? "-"}</dd>
    </div>
  );
}

function JobSummary({ job }: { job: OpsImportJobRecord }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Job</CardTitle>
        <CardDescription>{job.kind}</CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <FieldRow label="job_id" value={job.job_id} />
          <FieldRow label="load_batch_id" value={job.load_batch_id} />
          <FieldRow label="parent_job_id" value={job.parent_job_id} />
          <FieldRow label="source_checksum" value={job.source_checksum} />
          <FieldRow label="created_at" value={formatDateTime(job.created_at)} />
          <FieldRow label="started_at" value={formatDateTime(job.started_at)} />
          <FieldRow label="heartbeat_at" value={formatDateTime(job.heartbeat_at)} />
          <FieldRow label="finished_at" value={formatDateTime(job.finished_at)} />
        </dl>
      </CardContent>
    </Card>
  );
}

export function ImportJobDetailClient({ jobId }: { jobId: string }) {
  const [level, setLevel] = useState<ImportJobEventLevel | "all">("all");
  const [cancelReason, setCancelReason] = useState("");
  const job = useImportJob(jobId);
  const jobData = job.data?.data;
  const events = useImportJobEvents(jobId, {
    level: level === "all" ? undefined : level,
    page_size: 100,
  });
  const cancelJob = useCancelImportJobMutation();
  const live = useOpsLiveInvalidation({
    topics: [
      "import_jobs",
      `import_job:${jobId}`,
      `import_job_events:${jobId}`,
      "feature_update_requests",
      "offline_uploads",
      "dagster_runs",
    ],
  });
  const canCancel = Boolean(
    jobData?.status && !terminalStatuses.has(jobData.status),
  );
  const eventItems = events.data?.data.items ?? [];
  type EventRow = NonNullable<typeof events.data>["data"]["items"][number];
  const eventColumns = useMemo<ColumnDef<EventRow, unknown>[]>(
    () => [
      {
        accessorKey: "occurred_at",
        header: "time",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.occurred_at)}
          </span>
        ),
      },
      {
        accessorKey: "level",
        header: "level",
        cell: ({ row }) => <StatusBadge status={row.original.level} />,
      },
      {
        accessorKey: "stage",
        header: "stage",
        cell: ({ row }) => <>{row.original.stage ?? "-"}</>,
      },
      {
        accessorKey: "code",
        header: "code",
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.code ?? "-"}</span>
        ),
      },
      {
        accessorKey: "message",
        header: "message",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="min-w-80">{row.original.message}</span>
        ),
      },
      {
        id: "payload",
        header: "payload",
        enableSorting: false,
        cell: ({ row }) => (
          <pre className="max-h-28 min-w-72 overflow-auto whitespace-pre-wrap rounded bg-muted p-2 font-mono text-xs">
            {jsonBlock(row.original.payload)}
          </pre>
        ),
      },
    ],
    [],
  );
  const visibleLinks = useMemo(
    () => (jobData?.links ?? []).filter((link) => link.rel !== "self"),
    [jobData?.links],
  );

  function handleCancel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canCancel || cancelJob.isPending) {
      return;
    }
    cancelJob.mutate({
      jobId,
      body: {
        operator: "admin-ui",
        reason: cancelReason.trim() || undefined,
      },
    });
  }

  return (
    <AdminShell
      actions={
        <>
          <Link
            className={cn(buttonVariants({ variant: "outline" }))}
            href="/ops/import-jobs"
          >
            <ArrowLeftIcon data-icon="inline-start" />
            목록
          </Link>
          <Badge variant={live.state === "live" ? "default" : "outline"}>
            {live.state}
          </Badge>
          <Button
            disabled={job.isFetching || events.isFetching}
            type="button"
            variant="outline"
            onClick={() => {
              void job.refetch();
              void events.refetch();
            }}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
        </>
      }
      description={jobData ? `${jobData.kind} · ${shortId(jobData.job_id, 18)}` : jobId}
      section="Ops"
      title="Import job"
    >
      <div className="flex flex-col gap-4">
        {job.isError ? (
          <Alert variant="destructive">
            <AlertTitle>import job 조회 실패</AlertTitle>
            <AlertDescription>{job.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {events.isError ? (
          <Alert variant="destructive">
            <AlertTitle>event 조회 실패</AlertTitle>
            <AlertDescription>{events.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {cancelJob.isError ? (
          <Alert variant="destructive">
            <AlertTitle>cancel 실패</AlertTitle>
            <AlertDescription>{cancelJob.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {cancelJob.isSuccess ? (
          <Alert>
            <AlertTitle>cancel 요청됨</AlertTitle>
            <AlertDescription>
              {statusLabel(cancelJob.data.data.status)} · {shortId(cancelJob.data.data.job_id)}
            </AlertDescription>
          </Alert>
        ) : null}

        {job.isLoading ? <Skeleton className="h-96" /> : null}
        {jobData ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={jobData.status} />
              <Badge variant="outline">{jobData.progress}%</Badge>
              <Badge variant="outline">{jobData.current_stage ?? "stage 없음"}</Badge>
            </div>

            <JobSummary job={jobData} />

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
              <Card>
                <CardHeader>
                  <CardTitle>Events</CardTitle>
                  <CardDescription>
                    {eventItems.length} rows · {events.isFetching ? "syncing" : "idle"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <NativeSelect
                      aria-label="event level"
                      value={level}
                      onChange={(event) =>
                        setLevel(event.target.value as ImportJobEventLevel | "all")
                      }
                    >
                      {eventLevels.map((item) => (
                        <NativeSelectOption key={item} value={item}>
                          {item}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                    <Button
                      disabled={events.isFetching}
                      type="button"
                      variant="outline"
                      onClick={() => void events.refetch()}
                    >
                      <RefreshCwIcon data-icon="inline-start" />
                      event
                    </Button>
                  </div>
                  <DataTable
                    columns={eventColumns}
                    data={eventItems}
                    getRowId={(row) => row.event_id}
                    isLoading={events.isLoading}
                    emptyMessage="event가 없습니다."
                    manualSorting={false}
                    containerClassName="overflow-auto rounded-lg border"
                  />
                </CardContent>
              </Card>

              <div className="flex flex-col gap-4">
                <Card>
                  <CardHeader>
                    <CardTitle>Cancel</CardTitle>
                    <CardDescription>
                      {canCancel ? "queued/running" : "terminal"}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <form className="flex flex-col gap-2" onSubmit={handleCancel}>
                      <Input
                        disabled={!canCancel || cancelJob.isPending}
                        placeholder="reason"
                        value={cancelReason}
                        onChange={(event) => setCancelReason(event.target.value)}
                      />
                      <Button
                        disabled={!canCancel || cancelJob.isPending}
                        type="submit"
                        variant="destructive"
                      >
                        <BanIcon data-icon="inline-start" />
                        cancel
                      </Button>
                    </form>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Links</CardTitle>
                    <CardDescription>{visibleLinks.length} related</CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-2">
                    {visibleLinks.map((link) => (
                      <RelationLink key={`${link.rel}:${link.href}`} link={link} />
                    ))}
                    {visibleLinks.length === 0 ? (
                      <div className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
                        연결 링크가 없습니다.
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              </div>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>Payload</CardTitle>
                <CardDescription>{jobData.status_url}</CardDescription>
              </CardHeader>
              <CardContent>
                <pre className="max-h-[32rem] overflow-auto rounded-lg bg-muted p-3 font-mono text-xs">
                  {jsonBlock(jobData.payload)}
                </pre>
                {jobData.error_message ? (
                  <Alert className="mt-3" variant="destructive">
                    <AlertTitle>error</AlertTitle>
                    <AlertDescription>{jobData.error_message}</AlertDescription>
                  </Alert>
                ) : null}
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </AdminShell>
  );
}

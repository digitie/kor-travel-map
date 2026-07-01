"use client";

import { type ColumnDef } from "@tanstack/react-table";
import {
  ArrowLeftIcon,
  BanIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";
import { type FormEvent, type ReactNode, useMemo, useState } from "react";

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
import { StatusBadge } from "@/components/status-badge";
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

const eventLevelLabels: Record<ImportJobEventLevel | "all", string> = {
  all: "전체",
  debug: "debug",
  info: "info",
  warning: "warning",
  error: "error",
  critical: "critical",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function payloadLabel(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (Array.isArray(value)) {
    return `${value.length}개 항목`;
  }
  if (isRecord(value)) {
    return `${Object.keys(value).length}개 필드`;
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

function PayloadValue({
  depth = 0,
  value,
}: {
  depth?: number;
  value: unknown;
}): ReactNode {
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="text-muted-foreground">없음</span>;
    }
    return (
      <div className="flex flex-wrap gap-1">
        {value.slice(0, 6).map((item, index) => (
          <Badge key={index} variant="outline">
            {payloadLabel(item)}
          </Badge>
        ))}
        {value.length > 6 ? (
          <Badge variant="outline">+{value.length - 6}</Badge>
        ) : null}
      </div>
    );
  }

  if (isRecord(value)) {
    if (depth >= 2) {
      return <span>{payloadLabel(value)}</span>;
    }
    return <PayloadFields depth={depth + 1} value={value} />;
  }

  return (
    <span className={cn("break-words", value == null && "text-muted-foreground")}>
      {payloadLabel(value)}
    </span>
  );
}

function PayloadFields({
  compact = false,
  depth = 0,
  value,
}: {
  compact?: boolean;
  depth?: number;
  value: Record<string, unknown>;
}) {
  const entries = Object.entries(value);
  if (entries.length === 0) {
    return <span className="text-sm text-muted-foreground">값이 없습니다.</span>;
  }
  return (
    <dl
      className={cn(
        "grid gap-2",
        compact ? "min-w-72 text-xs" : "md:grid-cols-2",
      )}
    >
      {entries.map(([key, entryValue]) => (
        <div
          className={cn(
            "rounded-md border bg-background p-2",
            compact && "border-surface-muted",
          )}
          key={key}
        >
          <dt className="mb-1 truncate font-mono text-xs text-muted-foreground">
            {key}
          </dt>
          <dd className="text-sm">
            <PayloadValue depth={depth} value={entryValue} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function PayloadSummary({ value }: { value: unknown }) {
  if (isRecord(value)) {
    return <PayloadFields compact value={value} />;
  }
  return (
    <div className="min-w-56 rounded-md border bg-background p-2 text-sm">
      <PayloadValue value={value} />
    </div>
  );
}

function JobProgress({ value }: { value: number }) {
  const progress = Math.min(100, Math.max(0, value));
  return (
    <div className="flex items-center gap-3">
      <div className="h-2 min-w-40 flex-1 overflow-hidden rounded-full bg-surface-muted">
        <div
          className="h-full rounded-full bg-brand"
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="w-12 text-right font-mono text-sm">{progress}%</span>
    </div>
  );
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
    return "/admin/features/update-requests";
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
        <CardTitle>작업</CardTitle>
        <CardDescription>
          <span className="font-mono">{shortId(job.job_id, 18)}</span>
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={job.status} />
          <Badge variant="outline">{job.kind}</Badge>
          <Badge variant="outline">{job.current_stage ?? "단계 없음"}</Badge>
        </div>
        <JobProgress value={job.progress} />
        <dl className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <FieldRow label="작업 ID" value={job.job_id} />
          <FieldRow label="배치 ID" value={job.load_batch_id} />
          <FieldRow label="상위 작업 ID" value={job.parent_job_id} />
          <FieldRow label="소스 체크섬" value={job.source_checksum} />
          <FieldRow label="생성" value={formatDateTime(job.created_at)} />
          <FieldRow label="시작" value={formatDateTime(job.started_at)} />
          <FieldRow label="heartbeat" value={formatDateTime(job.heartbeat_at)} />
          <FieldRow label="완료" value={formatDateTime(job.finished_at)} />
        </dl>
      </CardContent>
    </Card>
  );
}

function CancelCard({
  canCancel,
  cancelReason,
  isPending,
  onReasonChange,
  onSubmit,
}: {
  canCancel: boolean;
  cancelReason: string;
  isPending: boolean;
  onReasonChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>중지</CardTitle>
        <CardDescription>
          {canCancel ? "대기/실행 중 작업에 중지 요청을 보냅니다." : "이미 종료된 작업입니다."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="flex flex-col gap-2 sm:flex-row" onSubmit={onSubmit}>
          <Input
            disabled={!canCancel || isPending}
            placeholder="중지 사유"
            value={cancelReason}
            onChange={(event) => onReasonChange(event.target.value)}
          />
          <Button
            className="sm:w-fit"
            disabled={!canCancel || isPending}
            type="submit"
            variant="destructive"
          >
            <BanIcon data-icon="inline-start" />
            중지 요청
          </Button>
        </form>
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
        header: "시각",
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatDateTime(row.original.occurred_at)}
          </span>
        ),
      },
      {
        accessorKey: "level",
        header: "레벨",
        cell: ({ row }) => <StatusBadge status={row.original.level} />,
      },
      {
        accessorKey: "stage",
        header: "단계",
        cell: ({ row }) => <>{row.original.stage ?? "-"}</>,
      },
      {
        accessorKey: "code",
        header: "코드",
        cell: ({ row }) => (
          <span className="font-mono text-xs">{row.original.code ?? "-"}</span>
        ),
      },
      {
        accessorKey: "message",
        header: "메시지",
        enableSorting: false,
        cell: ({ row }) => (
          <span className="min-w-80">{row.original.message}</span>
        ),
      },
      {
        id: "payload",
        header: "세부값",
        enableSorting: false,
        cell: ({ row }) => <PayloadSummary value={row.original.payload} />,
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
            {live.state === "live" ? "실시간" : live.state}
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
      section="운영"
      title="적재 작업 상세"
    >
      <div className="flex flex-col gap-4">
        {job.isError ? (
          <Alert variant="destructive">
            <AlertTitle>적재 작업 조회 실패</AlertTitle>
            <AlertDescription>{job.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {events.isError ? (
          <Alert variant="destructive">
            <AlertTitle>이벤트 조회 실패</AlertTitle>
            <AlertDescription>{events.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {cancelJob.isError ? (
          <Alert variant="destructive">
            <AlertTitle>중지 실패</AlertTitle>
            <AlertDescription>{cancelJob.error.message}</AlertDescription>
          </Alert>
        ) : null}
        {cancelJob.isSuccess ? (
          <Alert>
            <AlertTitle>중지 요청됨</AlertTitle>
            <AlertDescription>
              {cancelJob.data.data.status} · {shortId(cancelJob.data.data.job_id)}
            </AlertDescription>
          </Alert>
        ) : null}
        {jobData?.error_message ? (
          <Alert variant="destructive">
            <AlertTitle>작업 오류</AlertTitle>
            <AlertDescription>{jobData.error_message}</AlertDescription>
          </Alert>
        ) : null}

        {job.isLoading ? <Skeleton className="h-96" /> : null}
        {jobData ? (
          <>
            <JobSummary job={jobData} />
            <CancelCard
              canCancel={canCancel}
              cancelReason={cancelReason}
              isPending={cancelJob.isPending}
              onReasonChange={setCancelReason}
              onSubmit={handleCancel}
            />

            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
              <Card>
                <CardHeader>
                  <CardTitle>이벤트</CardTitle>
                  <CardDescription>
                    {eventItems.length}건 · {events.isFetching ? "동기화 중" : "대기"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <NativeSelect
                      aria-label="이벤트 레벨"
                      value={level}
                      onChange={(event) =>
                        setLevel(event.target.value as ImportJobEventLevel | "all")
                      }
                    >
                      {eventLevels.map((item) => (
                        <NativeSelectOption key={item} value={item}>
                          {eventLevelLabels[item]}
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
                      이벤트 새로고침
                    </Button>
                  </div>
                  <DataTable
                    columns={eventColumns}
                    data={eventItems}
                    getRowId={(row) => row.event_id}
                    isLoading={events.isLoading}
                    emptyMessage="이벤트가 없습니다."
                    manualSorting={false}
                    containerClassName="overflow-auto rounded-lg border"
                  />
                </CardContent>
              </Card>

              <div className="flex flex-col gap-4">
                <Card>
                  <CardHeader>
                    <CardTitle>연결</CardTitle>
                    <CardDescription>{visibleLinks.length}개</CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-2">
                    {visibleLinks.map((link) => (
                      <RelationLink key={`${link.rel}:${link.href}`} link={link} />
                    ))}
                    {visibleLinks.length === 0 ? (
                      <div className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
                        연결 링크 없음
                      </div>
                    ) : null}
                  </CardContent>
                </Card>
              </div>
            </div>

            <Card>
              <CardHeader>
                <CardTitle>요청값</CardTitle>
                <CardDescription>{jobData.status_url}</CardDescription>
              </CardHeader>
              <CardContent>
                {isRecord(jobData.payload) ? (
                  <PayloadFields value={jobData.payload} />
                ) : (
                  <PayloadValue value={jobData.payload} />
                )}
              </CardContent>
            </Card>
          </>
        ) : null}
      </div>
    </AdminShell>
  );
}

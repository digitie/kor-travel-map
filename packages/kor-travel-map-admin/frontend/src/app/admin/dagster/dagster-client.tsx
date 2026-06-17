"use client";

import { useEffect, useMemo, useState } from "react";

import { type ColumnDef } from "@tanstack/react-table";

import {
  ActivityIcon,
  AlertTriangleIcon,
  BoxesIcon,
  Clock3Icon,
  ExternalLinkIcon,
  GitBranchIcon,
  RefreshCwIcon,
  WorkflowIcon,
} from "lucide-react";

import {
  DAGSTER_UI_URL,
  type DagsterGraphqlError,
  type DagsterInstigationTick,
  type DagsterRepository,
  type DagsterRunEvent,
  type DagsterRunSummary,
  useDagsterRunDetail,
  useMarkDagsterNuxSeen,
  useDagsterSummary,
} from "@/api/dagster";
import { AdminShell } from "@/components/admin-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { DataTable } from "@/components/ui/data-table";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";

const terminalStatus = new Set(["SUCCESS", "FAILURE", "CANCELED"]);
const runTimeFormatter = new Intl.DateTimeFormat("ko-KR", {
  dateStyle: "short",
  timeStyle: "medium",
});
const checkedAtFormatter = new Intl.DateTimeFormat("ko-KR", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function statusVariant(status: string) {
  if (status === "ok" || status === "SUCCESS" || status === "STARTED") {
    return "secondary" as const;
  }
  if (
    status === "unavailable" ||
    status === "error" ||
    status === "FAILURE" ||
    status === "CANCELED"
  ) {
    return "destructive" as const;
  }
  return "outline" as const;
}

function formatEpoch(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) {
    return "-";
  }
  return runTimeFormatter.format(new Date(seconds * 1000));
}

function formatCheckedAt(value: string | undefined) {
  if (!value) {
    return "-";
  }
  return checkedAtFormatter.format(new Date(value));
}

function formatEventTimestamp(value: string | null | undefined) {
  if (!value) {
    return "-";
  }
  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return formatEpoch(numeric);
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return runTimeFormatter.format(date);
}

function shortRunId(runId: string) {
  return runId.length > 12 ? `${runId.slice(0, 12)}...` : runId;
}

function dagsterRunUrl(runId: string) {
  return `${DAGSTER_UI_URL.replace(/\/+$/, "")}/runs/${encodeURIComponent(runId)}`;
}

function graphqlErrorText(error: DagsterGraphqlError | null | undefined) {
  if (!error) {
    return null;
  }
  if (error.class_name && error.message) {
    return `${error.class_name}: ${error.message}`;
  }
  return error.message ?? error.class_name ?? error.stack?.[0] ?? "Dagster error";
}

function SummaryCard({
  title,
  value,
  description,
  icon: Icon,
  tone,
}: {
  title: string;
  value: string;
  description: string;
  icon: typeof ActivityIcon;
  tone: "blue" | "green" | "amber" | "slate";
}) {
  const toneClass = {
    blue: "bg-sky-50 text-sky-700 ring-sky-200",
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-700 ring-amber-200",
    slate: "bg-slate-50 text-slate-700 ring-slate-200",
  }[tone];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          {title}
        </CardTitle>
        <CardAction>
          <span
            className={cn(
              "inline-flex size-8 items-center justify-center rounded-md ring-1",
              toneClass,
            )}
          >
            <Icon className="size-4" />
          </span>
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <div className="text-2xl font-semibold">{value}</div>
        <p className="text-xs text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

function TickRows({
  ticks,
  onSelectRun,
}: {
  ticks: DagsterInstigationTick[];
  onSelectRun: (runId: string) => void;
}) {
  if (ticks.length === 0) {
    return <span className="text-xs text-muted-foreground">최근 tick 없음</span>;
  }

  return (
    <div className="flex flex-col gap-2">
      {ticks.map((tick) => (
        <div
          className="rounded-md bg-background p-2 text-xs"
          key={tick.tick_id}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <Badge variant={statusVariant(tick.status)}>{tick.status}</Badge>
              <span className="truncate font-mono text-muted-foreground">
                {tick.tick_id}
              </span>
            </div>
            <span className="text-muted-foreground">
              {formatEpoch(tick.timestamp)}
            </span>
          </div>
          {tick.skip_reason ? (
            <p className="mt-2 break-words text-muted-foreground">
              {tick.skip_reason}
            </p>
          ) : null}
          {graphqlErrorText(tick.error) ? (
            <p className="mt-2 break-words text-destructive">
              {graphqlErrorText(tick.error)}
            </p>
          ) : null}
          {tick.run_ids?.length ? (
            <div className="mt-2 flex flex-wrap gap-1">
              {tick.run_ids.map((runId) => (
                <Button
                  className="font-mono"
                  key={runId}
                  size="xs"
                  type="button"
                  variant="ghost"
                  onClick={() => onSelectRun(runId)}
                >
                  {shortRunId(runId)}
                </Button>
              ))}
            </div>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function InstigationList({
  title,
  items,
  onSelectRun,
}: {
  title: "Schedules" | "Sensors";
  items: Array<{
    name: string;
    status?: string | null;
    cron_schedule?: string | null;
    execution_timezone?: string | null;
    recent_ticks?: DagsterInstigationTick[];
  }>;
  onSelectRun: (runId: string) => void;
}) {
  return (
    <div className="rounded-md border bg-muted/30 p-3">
      <div className="mb-2 text-sm font-medium">{title}</div>
      <div className="flex flex-col gap-3">
        {items.length === 0 ? (
          <span className="text-xs text-muted-foreground">없음</span>
        ) : null}
        {items.map((item) => (
          <div className="flex flex-col gap-2" key={item.name}>
            <div className="flex items-center justify-between gap-3 text-xs">
              <span className="truncate font-mono">{item.name}</span>
              <Badge variant={statusVariant(item.status ?? "")}>
                {item.status ?? "unknown"}
              </Badge>
            </div>
            {item.cron_schedule ? (
              <div className="text-xs text-muted-foreground">
                {item.cron_schedule}
                {item.execution_timezone ? ` · ${item.execution_timezone}` : ""}
              </div>
            ) : null}
            <TickRows
              ticks={item.recent_ticks ?? []}
              onSelectRun={onSelectRun}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

function RepositoryList({
  repositories,
  onSelectRun,
}: {
  repositories: DagsterRepository[];
  onSelectRun: (runId: string) => void;
}) {
  if (repositories.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">
        등록된 code location이 없습니다.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {repositories.map((repository) => (
        <div
          key={`${repository.location_name}:${repository.name}`}
          className="rounded-md border bg-background p-4"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="font-medium">{repository.location_name}</div>
              <div className="text-xs text-muted-foreground">
                {repository.name}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">{repository.jobs.length} jobs</Badge>
              <Badge variant="outline">{repository.asset_count} assets</Badge>
            </div>
          </div>

          <div className="mt-4 grid gap-2 md:grid-cols-2">
            {repository.asset_groups.map((group) => (
              <div key={group.group_name} className="rounded-md bg-muted/60 p-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-medium">{group.group_name}</span>
                  <Badge variant="secondary">{group.asset_count}</Badge>
                </div>
                <div className="mt-2 flex flex-col gap-1">
                  {group.assets.slice(0, 4).map((asset) => (
                    <span
                      key={asset}
                      className="truncate font-mono text-xs text-muted-foreground"
                    >
                      {asset}
                    </span>
                  ))}
                  {group.assets.length > 4 ? (
                    <span className="text-xs text-muted-foreground">
                      +{group.assets.length - 4}
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <InstigationList
              items={repository.schedules}
              title="Schedules"
              onSelectRun={onSelectRun}
            />
            <InstigationList
              items={repository.sensors}
              title="Sensors"
              onSelectRun={onSelectRun}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function RunsTable({
  runs,
  selectedRunId,
  onSelectRun,
}: {
  runs: DagsterRunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const columns = useMemo<ColumnDef<DagsterRunSummary, unknown>[]>(
    () => [
      {
        id: "run",
        header: "run",
        enableSorting: false,
        cell: ({ row }) => {
          const run = row.original;
          const selected = run.run_id === selectedRunId;
          return (
            <span className="font-mono text-xs">
              <Button
                className="font-mono"
                size="xs"
                type="button"
                variant={selected ? "secondary" : "ghost"}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectRun(run.run_id);
                }}
              >
                {shortRunId(run.run_id)}
              </Button>
            </span>
          );
        },
      },
      {
        id: "job",
        header: "job",
        accessorFn: (run) => run.job_name ?? "-",
        cell: ({ row }) => row.original.job_name ?? "-",
      },
      {
        accessorKey: "status",
        header: "status",
        cell: ({ row }) => (
          <Badge variant={statusVariant(row.original.status)}>
            {row.original.status}
          </Badge>
        ),
      },
      {
        id: "updated",
        header: "updated",
        accessorFn: (run) =>
          run.update_time ?? run.end_time ?? run.start_time ?? 0,
        cell: ({ row }) => {
          const run = row.original;
          return (
            <span className="text-muted-foreground">
              {formatEpoch(run.update_time ?? run.end_time ?? run.start_time)}
            </span>
          );
        },
      },
      {
        id: "link",
        header: () => <span className="sr-only">Dagster link</span>,
        enableSorting: false,
        cell: ({ row }) => (
          <a
            className={cn(buttonVariants({ variant: "ghost", size: "icon-xs" }))}
            href={dagsterRunUrl(row.original.run_id)}
            rel="noreferrer"
            target="_blank"
            title="Dagster run 열기"
            onClick={(event) => event.stopPropagation()}
          >
            <ExternalLinkIcon />
            <span className="sr-only">Dagster run 열기</span>
          </a>
        ),
      },
    ],
    [onSelectRun, selectedRunId],
  );

  return (
    <DataTable
      columns={columns}
      data={runs}
      getRowId={(run) => run.run_id}
      emptyMessage="최근 Dagster run이 없습니다."
      onRowClick={(run) => onSelectRun(run.run_id)}
      isRowActive={(run) => run.run_id === selectedRunId}
    />
  );
}

function RunEventsTable({ events }: { events: DagsterRunEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">
        표시할 Dagster event가 없습니다.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>time</TableHead>
          <TableHead>event</TableHead>
          <TableHead>step</TableHead>
          <TableHead>message</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {events.map((event, index) => {
          const errorText = graphqlErrorText(event.error);
          return (
            <TableRow key={`${event.event_type}:${event.timestamp ?? index}`}>
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {formatEventTimestamp(event.timestamp)}
              </TableCell>
              <TableCell>
                <div className="flex flex-col gap-1">
                  <Badge variant={event.level === "ERROR" ? "destructive" : "outline"}>
                    {event.dagster_event_type ?? event.event_type}
                  </Badge>
                  {event.level ? (
                    <span className="text-xs text-muted-foreground">
                      {event.level}
                    </span>
                  ) : null}
                </div>
              </TableCell>
              <TableCell className="font-mono text-xs">
                {event.step_id ?? "-"}
              </TableCell>
              <TableCell>
                <div className="max-w-[34rem] whitespace-normal break-words text-sm">
                  {errorText ? (
                    <span className="text-destructive">{errorText}</span>
                  ) : (
                    (event.message ?? "-")
                  )}
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}

function RunDetailCard({ runId }: { runId: string | null }) {
  // event log cursor 페이지네이션 — 긴 run의 뒤쪽(실패) 이벤트로 전진하기 위함.
  // cursorStack: 2페이지부터의 after cursor 누적(1페이지는 after 없음). run 전환 시
  // 호출부의 key={runId}로 remount돼 1페이지로 리셋된다.
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const after = cursorStack.length > 0 ? cursorStack[cursorStack.length - 1] : null;

  const detail = useDagsterRunDetail(runId, 80, after);
  const data = detail.data?.data;
  const run = data?.run;
  const nextCursor = data?.event_cursor ?? null;
  const goNext = () => {
    if (data?.event_has_more && nextCursor) {
      setCursorStack((stack) => [...stack, nextCursor]);
    }
  };
  const goPrev = () => setCursorStack((stack) => stack.slice(0, -1));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Run detail</CardTitle>
        <CardDescription>backend GraphQL event log</CardDescription>
        <CardAction>
          {runId ? (
            <a
              className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }))}
              href={dagsterRunUrl(runId)}
              rel="noreferrer"
              target="_blank"
              title="Dagster run 열기"
            >
              <ExternalLinkIcon />
              <span className="sr-only">Dagster run 열기</span>
            </a>
          ) : (
            <ActivityIcon className="text-muted-foreground" />
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!runId ? (
          <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">
            최근 run을 선택하면 event log와 실패 원인이 표시됩니다.
          </div>
        ) : null}

        {detail.isLoading ? <Skeleton className="h-72 w-full" /> : null}

        {detail.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>Dagster run 상세 호출 실패</AlertTitle>
            <AlertDescription>{detail.error.message}</AlertDescription>
          </Alert>
        ) : null}

        {data?.errors?.length ? (
          <Alert variant={data.status === "not_found" ? "default" : "destructive"}>
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>Run detail 상태 확인 필요</AlertTitle>
            <AlertDescription>{data.errors.join(" / ")}</AlertDescription>
          </Alert>
        ) : null}

        {data ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={statusVariant(data.status)}>{data.status}</Badge>
            {run ? <Badge variant={statusVariant(run.status)}>{run.status}</Badge> : null}
            {data.event_has_more ? (
              <Badge variant="outline">events more</Badge>
            ) : null}
          </div>
        ) : null}

        {run ? (
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs text-muted-foreground">run id</div>
              <div className="mt-1 break-all font-mono text-xs">{run.run_id}</div>
            </div>
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs text-muted-foreground">job</div>
              <div className="mt-1 text-sm">{run.job_name ?? "-"}</div>
            </div>
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs text-muted-foreground">started</div>
              <div className="mt-1 text-sm">{formatEpoch(run.start_time)}</div>
            </div>
            <div className="rounded-md bg-muted/50 p-3">
              <div className="text-xs text-muted-foreground">updated</div>
              <div className="mt-1 text-sm">
                {formatEpoch(run.update_time ?? run.end_time)}
              </div>
            </div>
          </div>
        ) : null}

        {run && Object.keys(run.tags).length > 0 ? (
          <div className="rounded-md border bg-background p-3">
            <div className="mb-2 text-sm font-medium">Tags</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(run.tags).map(([key, value]) => (
                <Badge className="max-w-full" key={key} variant="outline">
                  <span className="truncate">
                    {key}: {value}
                  </span>
                </Badge>
              ))}
            </div>
          </div>
        ) : null}

        {data ? <RunEventsTable events={data.events ?? []} /> : null}

        {data?.run ? (
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              이벤트 페이지 {cursorStack.length + 1} · {data.events?.length ?? 0}건
              {data.event_has_more ? " (뒤쪽 이벤트 더 있음)" : ""}
            </span>
            <div className="flex gap-1">
              <Button
                disabled={cursorStack.length === 0 || detail.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={goPrev}
              >
                이전
              </Button>
              <Button
                aria-label="다음 이벤트"
                disabled={!data.event_has_more || detail.isFetching}
                size="sm"
                type="button"
                variant="outline"
                onClick={goNext}
              >
                다음
              </Button>
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function DagsterAdminClient() {
  const summary = useDagsterSummary(12);
  const { mutate: markNuxSeen, status: markNuxSeenStatus } =
    useMarkDagsterNuxSeen();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const data = summary.data?.data;
  const recentRuns = data?.recent_runs ?? [];
  const activeRuns = recentRuns.filter(
    (run) => !terminalStatus.has(run.status),
  ).length;
  const failedRuns = data?.run_counts.FAILURE ?? 0;
  const fallbackRun = recentRuns.find((run) => run.status === "FAILURE") ?? recentRuns[0];
  const effectiveSelectedRunId = selectedRunId ?? fallbackRun?.run_id ?? null;

  useEffect(() => {
    if (data?.status !== "ok" || markNuxSeenStatus !== "idle") {
      return;
    }
    markNuxSeen();
  }, [data?.status, markNuxSeen, markNuxSeenStatus]);

  return (
    <AdminShell
      actions={
        <>
          <Button
            disabled={summary.isFetching}
            type="button"
            variant="outline"
            onClick={() => void summary.refetch()}
          >
            <RefreshCwIcon data-icon="inline-start" />
            새로고침
          </Button>
          <a
            className={cn(buttonVariants({ variant: "default" }))}
            href={DAGSTER_UI_URL}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLinkIcon data-icon="inline-start" />
            Dagster 열기
          </a>
        </>
      }
      description={`checked ${formatCheckedAt(data?.checked_at)} · ${DAGSTER_UI_URL}`}
      section="Ops"
      title="Dagster 운영"
    >
      <div className="flex flex-col gap-5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={statusVariant(data?.status ?? "loading")}>
            {data?.status ?? (summary.isError ? "error" : "loading")}
          </Badge>
          {data?.version ? <Badge variant="outline">v{data.version}</Badge> : null}
        </div>

        {summary.isError ? (
          <Alert variant="destructive">
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>Dagster summary 호출 실패</AlertTitle>
            <AlertDescription>{summary.error.message}</AlertDescription>
          </Alert>
        ) : null}

        {data?.errors?.length ? (
          <Alert variant={data.status === "unavailable" ? "destructive" : "default"}>
            <AlertTriangleIcon data-icon="inline-start" />
            <AlertTitle>Dagster 상태 확인 필요</AlertTitle>
            <AlertDescription>{data.errors.join(" / ")}</AlertDescription>
          </Alert>
        ) : null}

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {summary.isLoading ? (
            <>
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
              <Skeleton className="h-32 w-full" />
            </>
          ) : (
            <>
              <SummaryCard
                title="Repositories"
                value={String(data?.repository_count ?? 0)}
                description={`${data?.job_count ?? 0} jobs / ${data?.schedule_count ?? 0} schedules`}
                icon={WorkflowIcon}
                tone="blue"
              />
              <SummaryCard
                title="Assets"
                value={String(data?.asset_count ?? 0)}
                description={`${data?.sensor_count ?? 0} sensors registered`}
                icon={BoxesIcon}
                tone="green"
              />
              <SummaryCard
                title="Active runs"
                value={String(activeRuns)}
                description="non-terminal recent runs"
                icon={ActivityIcon}
                tone="amber"
              />
              <SummaryCard
                title="Failed runs"
                value={String(failedRuns)}
                description="recent failure count"
                icon={AlertTriangleIcon}
                tone="slate"
              />
            </>
          )}
        </section>

        <section className="grid gap-4 xl:grid-cols-[minmax(28rem,0.85fr)_minmax(42rem,1.15fr)]">
          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader>
                <CardTitle>Code locations</CardTitle>
                <CardDescription>repository / asset group</CardDescription>
                <CardAction>
                  <GitBranchIcon className="text-muted-foreground" />
                </CardAction>
              </CardHeader>
              <CardContent>
                {summary.isLoading ? (
                  <Skeleton className="h-72 w-full" />
                ) : (
                  <RepositoryList
                    repositories={data?.repositories ?? []}
                    onSelectRun={setSelectedRunId}
                  />
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Recent runs</CardTitle>
                <CardDescription>Dagster run storage</CardDescription>
                <CardAction>
                  <Clock3Icon className="text-muted-foreground" />
                </CardAction>
              </CardHeader>
              <CardContent>
                {summary.isLoading ? (
                  <Skeleton className="h-56 w-full" />
                ) : (
                  <RunsTable
                    runs={recentRuns}
                    selectedRunId={effectiveSelectedRunId}
                    onSelectRun={setSelectedRunId}
                  />
                )}
              </CardContent>
            </Card>

            <RunDetailCard
              key={effectiveSelectedRunId ?? "none"}
              runId={effectiveSelectedRunId}
            />
          </div>

          <Card className="min-h-[48rem]">
            <CardHeader>
              <CardTitle>Dagster webserver</CardTitle>
              <CardDescription>embedded management UI</CardDescription>
              <CardAction>
                <ExternalLinkIcon className="text-muted-foreground" />
              </CardAction>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded-md border bg-background">
                <iframe
                  className="h-[44rem] w-full min-w-[44rem] border-0 bg-background"
                  data-testid="dagster-embed"
                  sandbox="allow-scripts allow-forms allow-popups allow-downloads"
                  src={DAGSTER_UI_URL}
                  title="Dagster management UI"
                />
              </div>
            </CardContent>
          </Card>
        </section>
      </div>
    </AdminShell>
  );
}

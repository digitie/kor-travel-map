"use client";

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
  type DagsterRepository,
  type DagsterRunSummary,
  useDagsterSummary,
} from "@/api/dagster";
import { AdminShell } from "@/components/admin-shell";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
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

function formatEpoch(seconds: number | null) {
  if (seconds === null) {
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

function shortRunId(runId: string) {
  return runId.length > 12 ? `${runId.slice(0, 12)}...` : runId;
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
        <div className="text-2xl font-semibold tracking-tight">{value}</div>
        <p className="text-xs text-muted-foreground">{description}</p>
      </CardContent>
    </Card>
  );
}

function RepositoryList({ repositories }: { repositories: DagsterRepository[] }) {
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
            <div className="rounded-md border bg-muted/30 p-3">
              <div className="mb-2 text-sm font-medium">Schedules</div>
              <div className="flex flex-col gap-2">
                {repository.schedules.length === 0 ? (
                  <span className="text-xs text-muted-foreground">없음</span>
                ) : null}
                {repository.schedules.map((schedule) => (
                  <div
                    className="flex items-center justify-between gap-3 text-xs"
                    key={schedule.name}
                  >
                    <span className="truncate font-mono">{schedule.name}</span>
                    <Badge variant={statusVariant(schedule.status ?? "")}>
                      {schedule.status ?? "unknown"}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
            <div className="rounded-md border bg-muted/30 p-3">
              <div className="mb-2 text-sm font-medium">Sensors</div>
              <div className="flex flex-col gap-2">
                {repository.sensors.length === 0 ? (
                  <span className="text-xs text-muted-foreground">없음</span>
                ) : null}
                {repository.sensors.map((sensor) => (
                  <div
                    className="flex items-center justify-between gap-3 text-xs"
                    key={sensor.name}
                  >
                    <span className="truncate font-mono">{sensor.name}</span>
                    <Badge variant={statusVariant(sensor.status ?? "")}>
                      {sensor.status ?? "unknown"}
                    </Badge>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function RunsTable({ runs }: { runs: DagsterRunSummary[] }) {
  if (runs.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-5 text-sm text-muted-foreground">
        최근 Dagster run이 없습니다.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>run</TableHead>
          <TableHead>job</TableHead>
          <TableHead>status</TableHead>
          <TableHead>updated</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((run) => (
          <TableRow key={run.run_id}>
            <TableCell className="font-mono text-xs">
              {shortRunId(run.run_id)}
            </TableCell>
            <TableCell>{run.job_name ?? "-"}</TableCell>
            <TableCell>
              <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
            </TableCell>
            <TableCell className="text-muted-foreground">
              {formatEpoch(run.update_time ?? run.end_time ?? run.start_time)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export function DagsterAdminClient() {
  const summary = useDagsterSummary(12);
  const data = summary.data;
  const activeRuns =
    data?.recent_runs.filter((run) => !terminalStatus.has(run.status)).length ?? 0;
  const failedRuns = data?.run_counts.FAILURE ?? 0;

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

        {data?.errors.length ? (
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
                  <RepositoryList repositories={data?.repositories ?? []} />
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
                  <RunsTable runs={data?.recent_runs ?? []} />
                )}
              </CardContent>
            </Card>
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
                  sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-downloads"
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
